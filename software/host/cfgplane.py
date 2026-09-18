#!/usr/bin/env python3
"""
cfgplane.py - drive the scan-chain configuration plane (6-bit AMD IR) from the Mac.

Implements the host side of docs/bitstream-format.md. Uses software/host/dirtyjtag.py's
Probe as transport and software/bob/chainbits.py for CRC and status decoding.

  ./cfgplane.py status                 IR capture + CFG_CTRL, decoded
  ./cfgplane.py load 0x5 [--no-start]  JPROGRAM, CRC, CFG_IN, verify, JSTART
  ./cfgplane.py readback               CFG_OUT
  ./cfgplane.py capture                CAPTURE chain
  ./cfgplane.py jprogram
  ./cfgplane.py user1 0x1              write USER1 (bit0 ce, bit1 sr, ...)
  ./cfgplane.py ids                    IDCODE and USERCODE

--width defaults to 64 (hw/src/top/cfg_test_top.v).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "software", "bob"))

import chainbits  # noqa: E402

IR_W = 6
IR = {
    "SAMPLE":   0b000001,
    "USER1":    0b000010,
    "CFG_CTRL": 0b000011,   # USER2
    "CFG_OUT":  0b000100,   # M13: frame packet readback (packets.py)
    "CFG_IN":   0b000101,   # M13: frame packet stream (packets.py)
    "CHAIN_OUT": 0b110100,  # M13: the configuration chain readback (private; was CFG_OUT)
    "CHAIN_IN":  0b110101,  # M13: the configuration chain write (private; was CFG_IN)
    "INTEST":   0b000111,   # private
    "USERCODE": 0b001000,
    "IDCODE":   0b001001,
    "JPROGRAM": 0b001011,
    "JSTART":   0b001100,
    "CAPTURE":  0b100010,   # USER3
    "BRAM":     0b100011,   # USER4 (M5)
    "DSP":      0b101000,   # private (M6): DSP test drive
    "EXTEST":   0b100110,
    "BYPASS":   0b111111,
}
JSTART_TCKS = 12
TEST_TOP_CHAIN_W = 64
TEST_TOP_CAPTURE_W = 16


class CfgError(RuntimeError):
    """The configuration plane refused, or answered as no bob bitstream would: a wrong
    version, a length that does not match, a write while GWE is high. A RuntimeError so
    every existing caller still catches it, its own class so new ones need not guess."""


def ir(p, name):
    """Load an instruction; returns the 6 captured IR bits."""
    return p.shift_ir(IR[name], width=IR_W)


def _shift(p, n, din, fast):
    return (p.shift_dr_fast if fast else p.shift_dr)(n, din)


def ir_status(p):
    return chainbits.decode_ir_capture(ir(p, "BYPASS"))


def idcode(p):
    p.reset_to_idle()                       # Test-Logic-Reset selects IDCODE
    return p.shift_dr(32)


def usercode(p):
    ir(p, "USERCODE")
    return p.shift_dr(32)


def jprogram(p):
    ir(p, "JPROGRAM")


def jstart(p, tcks=JSTART_TCKS):
    ir(p, "JSTART")
    for _ in range(tcks):
        p.pulse(tms=0)                      # Run-Test/Idle clocks the startup


def status(p):
    ir(p, "CFG_CTRL")
    st = chainbits.decode_ctrl(p.shift_dr(64, 0))
    if st["version"] != chainbits.CTRL_VERSION:
        raise CfgError(f"CFG_CTRL version 0x{st['version']:02X}, expected "
                           f"0x{chainbits.CTRL_VERSION:02X} - wrong bitstream or no config plane")
    return st


def write_expected(p, crc):
    ir(p, "CFG_CTRL")
    p.shift_dr(64, chainbits.ctrl_write_word(crc))


def cfg_in(p, word, width, fast=True):
    ir(p, "CHAIN_IN")
    _shift(p, width, word, fast)


def cfg_out(p, width, fast=True):
    ir(p, "CHAIN_OUT")
    return _shift(p, width, 0, fast)


def capture(p, n=TEST_TOP_CAPTURE_W):
    ir(p, "CAPTURE")
    return _shift(p, n, 0, n >= 64)


def user1(p, value):
    ir(p, "USER1")
    return p.shift_dr(32, value)


def idle(p, tcks):
    for _ in range(tcks):
        p.pulse(tms=0)


# --- M5: BRAM contents and test access over USER4 ---------------------------------

BRAM_CMD = {"nop": 0, "load_ptr": 1, "write": 2, "read": 3, "drive": 4, "select": 5}
BRAM_VERSION = 0x07          # M7: SELECT and the target field; M5/M6 builds report 0x05
DSP_VERSION = 0x07           # M7: the register moved to dsp_jtag.v; M6 builds report 0x06


def decode_bram(v):
    return {"rdata": v & 0x3FFFF, "ptr": (v >> 18) & 0x3FF, "do_a": (v >> 28) & 0x3FFFF,
            "do_b": (v >> 46) & 0x3FFFF, "err": (v >> 64) & 1, "gwe": (v >> 65) & 1,
            "target": (v >> 66) & 0xF, "version": (v >> 88) & 0xFF}


def bram_scan(p, cmd="nop", payload=0):
    ir(p, "BRAM")
    st = decode_bram(p.shift_dr_fast(96, (BRAM_CMD[cmd] << 92) | (payload & ((1 << 64) - 1))))
    if st["version"] != BRAM_VERSION:
        raise CfgError(f"USER4 version 0x{st['version']:02X}, expected 0x{BRAM_VERSION:02X}: "
                           "wrong bitstream in the PL")
    return st


def bram_select(p, b):
    """Pick the BRAM that LOAD_PTR / WRITE / READ / SET_DRIVE and the do_a/do_b capture act on."""
    bram_scan(p, "select", b)
    st = bram_scan(p, "nop")
    if st["target"] != b:
        raise CfgError(f"USER4 SELECT {b} not taken (target {st['target']})")
    return st


def bram_write(p, addr, words):
    bram_scan(p, "load_ptr", addr)
    for w in words:
        bram_scan(p, "write", w)


def bram_fill(p, words, addr=0):
    """Write words from addr with one IR scan and one DR scan per word (bram_write
    reloads the IR every word). Checks the version and err once at the end."""
    ir(p, "BRAM")
    p.shift_dr_fast(96, (BRAM_CMD["load_ptr"] << 92) | addr)
    for w in words:
        p.shift_dr_fast(96, (BRAM_CMD["write"] << 92) | (w & 0x3FFFF))
    st = bram_scan(p, "nop")
    if st["err"]:
        raise CfgError("USER4 WRITE refused (GWE is 1: contents are only written before JSTART)")
    return st


def bram_read(p, addr, n):
    """mem[addr..addr+n-1]; a READ's result is captured by the following scan."""
    bram_scan(p, "load_ptr", addr)
    bram_scan(p, "read")
    out = []
    for i in range(n):
        out.append(bram_scan(p, "read" if i < n - 1 else "nop")["rdata"])
    return out


# --- M6: DSP test drive over the private DSP instruction ----------------------------

def dsp_scan(p, drive=None):
    """One 256-bit DSP scan. drive=None reads only; otherwise SET_DRIVE.
    Returns P0 and P1 (as captured, unsigned 48-bit) and the version."""
    ir(p, "DSP")
    word = 0 if drive is None else ((4 << 252) | (drive & ((1 << 248) - 1)))
    v = p.shift_dr_fast(256, word)
    st = {"p0": v & ((1 << 48) - 1), "p1": (v >> 48) & ((1 << 48) - 1), "version": (v >> 248) & 0xFF}
    if st["version"] != DSP_VERSION:
        raise CfgError(f"DSP register version 0x{st['version']:02X}, expected 0x{DSP_VERSION:02X}: "
                           "wrong bitstream in the PL")
    return st


def step(p):
    """USER1 step: exactly one fabric/BRAM clock on the JTAG-stepped user clock."""
    user1(p, 0b1000)
    user1(p, 0)


def measure_chain(p, limit):
    """Chain length through CHAIN_OUT (never writes). Returns None if not within limit.

    M12b: CHAIN_OUT streams the memory frame by frame and, after the last frame, is a
    FRAME_BITS-long delay line from TDI (a pure shift register before M12b was a
    W-long one). Both pass a marker REPEATED every 32 bits through unchanged once
    the memory is out, because W is a multiple of 32. So shift the repeated marker
    and return the first position from which every bit out equals the bit in: that
    is W, unless the memory's own last bits happen to continue the pattern."""
    marker = 0xA5C35A3C
    n = limit + 256
    stream = 0
    for k in range(0, n, 32):
        stream |= marker << k
    stream &= (1 << n) - 1
    ir(p, "CHAIN_OUT")
    out = _shift(p, n, stream, True)
    diff = out ^ stream
    first = diff.bit_length()                  # every bit at or above this matches
    return first if first <= limit else None


# --- M13: the frame path (UG470-style packets on CFG_IN / CFG_OUT, software/bob/packets.py) ----

def frames_send(p, words):
    """shift a packet stream into CFG_IN (words MSB first)"""
    import packets
    ir(p, "CFG_IN")
    n, v = packets.to_jtag(words)
    p.shift_dr_fast(n, v)


def frames_read(p, nwords):
    """nwords words out of CFG_OUT (the queued READ words, or STAT)"""
    import packets
    ir(p, "CFG_OUT")
    return packets.from_jtag(p.shift_dr_fast(32 * nwords, 0), nwords)


def frames_stat(p):
    import packets
    return packets.decode_stat(frames_read(p, 1)[0])


def frames_readback(p):
    """the whole configuration memory through FDRO, as a chain word"""
    import packets
    frames_send(p, packets.readback_stream())
    return packets.word_from_frames(frames_read(p, packets.NFRAMES * packets.FW))


def bram_frames_read(p, b, first=0, n=None):
    """M15: n content frames of BRAM b from frame `first` over FDRO (GWE = 0 only), as words"""
    import packets
    n = packets.BRAM_FRAMES - first if n is None else n
    frames_send(p, packets.bram_readback_stream(b, first, n))
    return [w & 0x3FFFF for w in frames_read(p, packets.FW * n)]


def load_frames(p, word, start=True, idcode=None, brams=None):
    """JPROGRAM, the frame load stream on CFG_IN (M15: with every word of each BRAM in
    `brams` as block-type-1 frames), STAT (START accepted, no error), FDRO readback ==
    word (and == the BRAM contents), then optionally JSTART and DONE. Returns (ok, message)."""
    import packets
    jprogram(p)
    frames_send(p, packets.load_stream(word, idcode=idcode, brams=brams))
    st = frames_stat(p)
    errs = [k for k in ("CRC_ERROR", "ID_ERROR", "PKT_ERROR", "WR_ERROR") if st[k]]
    if errs or not st["START_OK"]:
        return False, f"frame load refused: STAT {errs or ''} START_OK={st['START_OK']} SYNCED={st['SYNCED']}"
    back = frames_readback(p)
    if back != word:
        return False, f"FDRO readback differs in {bin(back ^ word).count('1')} bits"
    for b, words in sorted((brams or {}).items()):
        if bram_frames_read(p, b) != packets.bram_words(words):
            return False, f"bram{b}: FDRO readback of its content frames differs"
    nb = len(brams or {})
    msg = (f"loaded {packets.NFRAMES} frames ({packets.NFRAMES * packets.FW} words) through CFG_IN"
           + (f" + {nb * packets.BRAM_FRAMES} BRAM content frames ({nb} BRAM{'s' if nb != 1 else ''}, all 1024 words)"
              if nb else "")
           + f", CRC {packets.expected_crc(word, idcode, brams):08X}, FDRO readback verified")
    if start:
        jstart(p)
        if not status(p)["done"]:
            return False, f"{msg}; DONE did not rise"
        msg += ", DONE"
    return True, msg


def load_partial(p, new, old=None, idcode=None, crc_override=None):
    """M14 partial reconfiguration of the RUNNING design (docs/bitstream-format.md section
    12): read the memory over CHAIN_OUT (non-destructive) unless `old` is given, send
    AGHIGH, require STAT GHIGH_B = 0 (the user clock is held, every fabric register keeps
    its value), send only the frames that differ + CRC + LFRM, require GHIGH_B = 1 again
    and no error, and check CHAIN_OUT == new. Returns (ok, message, frames written).
    On a CRC or write error the fabric STAYS frozen: JPROGRAM and a full load recover."""
    import packets
    if old is None:
        old = cfg_out(p, packets.NFRAMES * packets.FB)
    freeze, frames, n = packets.partial_streams(old, new, idcode=idcode, crc_override=crc_override)
    frames_send(p, freeze)
    st = frames_stat(p)
    errs = [k for k in ("CRC_ERROR", "ID_ERROR", "PKT_ERROR", "WR_ERROR") if st[k]]
    if errs or st["GHIGH_B"]:
        return False, f"freeze not acknowledged: STAT {errs} GHIGH_B={st['GHIGH_B']}", 0
    frames_send(p, frames)
    st = frames_stat(p)
    errs = [k for k in ("CRC_ERROR", "ID_ERROR", "PKT_ERROR", "WR_ERROR") if st[k]]
    if errs or not st["GHIGH_B"]:
        return False, (f"partial refused: STAT {errs} GHIGH_B={st['GHIGH_B']} "
                       f"(the fabric stays frozen until JPROGRAM)"), n
    back = cfg_out(p, packets.NFRAMES * packets.FB)
    if back != new:
        return False, f"after the partial the memory differs in {bin(back ^ new).count('1')} bits", n
    return True, f"partial: {n} of {packets.NFRAMES} frames rewritten with the design running, released", n


def load(p, word, width, start=True, fast_first=True):
    """The chain load (CHAIN_IN since M13), docs/bitstream-format.md section 8.
    Returns (ok, message). Bulk first, then per-pulse (the fallback bob's
    fpga.load_bitstream proved on hardware)."""
    crc = chainbits.crc32c_bits(word, width)
    msg = ""
    for fast in ((True, False) if fast_first else (False,)):
        how = "bulk" if fast else "per-pulse"
        jprogram(p)
        write_expected(p, crc)
        cfg_in(p, word, width, fast=fast)
        st = status(p)
        if not (st["committed"] and st["crc_ok"] and st["count"] == width):
            msg = (f"commit refused after {how} transfer: count={st['count']} "
                   f"crc_err={st['crc_err']} len_err={st['len_err']} "
                   f"chip crc=0x{st['crc']:08X} host crc=0x{crc:08X}")
            continue
        back = cfg_out(p, width, fast=fast)
        if back != word:
            msg = f"readback differs in {bin(back ^ word).count('1')} bits after {how} transfer"
            continue
        if start:
            jstart(p)
            st = status(p)
            if not st["done"]:
                return False, f"committed and verified, but DONE did not rise: {st}"
        return True, (f"loaded {width} bits ({how}), crc 0x{crc:08X}, readback verified"
                      + (", DONE" if start else ""))
    return False, msg


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--width", type=int, default=TEST_TOP_CHAIN_W)
    ap.add_argument("--freq", type=int, default=100, help="TCK kHz")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    ld = sub.add_parser("load")
    ld.add_argument("word")
    ld.add_argument("--no-start", action="store_true")
    sub.add_parser("readback")
    sub.add_parser("capture")
    sub.add_parser("jprogram")
    u = sub.add_parser("user1")
    u.add_argument("value")
    sub.add_parser("ids")
    args = ap.parse_args()

    from dirtyjtag import Probe
    p = Probe(freq_khz=args.freq)
    p.reset_to_idle()

    if args.cmd == "ids":
        print(f"IDCODE   0x{idcode(p):08X}")
        print(f"USERCODE 0x{usercode(p):08X}")
    elif args.cmd == "status":
        print("IR capture", ir_status(p))
        print("CFG_CTRL  ", status(p))
    elif args.cmd == "load":
        ok, msg = load(p, int(args.word, 0), args.width, start=not args.no_start)
        print(("OK   " if ok else "FAIL ") + msg)
        return 0 if ok else 1
    elif args.cmd == "readback":
        print(f"0x{cfg_out(p, args.width):0{(args.width + 3) // 4}X}")
    elif args.cmd == "capture":
        c = capture(p)
        print(f"0x{c:04X}  counter={c & 0xFF}  SW1..0={(c >> 10) & 3:02b}  BTN3..0={(c >> 12) & 0xF:04b}")
    elif args.cmd == "jprogram":
        jprogram(p)
        print("JPROGRAM sent;", status(p))
    elif args.cmd == "user1":
        user1(p, int(args.value, 0))
        print("USER1 written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
