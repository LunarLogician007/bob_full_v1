#!/usr/bin/env python3
"""
packets.py - the frame path's bitstream: UG470-style packets (M13).

docs/bitstream-format.md sections 9-10. The same configuration memory the chain
writes, as frames of FRAME_WORDS 32-bit words, carried in type-1/type-2 packets:

  load_stream(word)      dummy, sync, RCRC, IDCODE, FAR <- 0, WCFG, FDRI (type 2)
                         <all frames>, CRC, LFRM, START, DESYNC       -> [words]
  readback_stream()      sync, RCFG, FAR <- 0, READ FDRO (type 2), DESYNC
  read_stream(reg, n)    sync, READ <reg> n, DESYNC   (then CFG_OUT: n words)
  to_jtag(words)         (nbits, value): the words MSB first on TDI, value bit 0 first
  from_jtag(value, n)    CFG_OUT bits (value bit 0 = first out) -> n words
  Controller             a Python model of hw/src/core/cfg_frames.v: feed it the
                         bits a CFG_IN scan carries, read STAT / memory / errors

  ./packets.py dump <file.bit>     the load stream of a .bit, annotated
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "host"))

import bitstream as B  # noqa: E402
import buildcfg  # noqa: E402

SYNC = 0xAA995566
DUMMY = 0xFFFFFFFF
NOP = 0x20000000
REG = {"CRC": 0, "FAR": 1, "FDRI": 2, "FDRO": 3, "CMD": 4, "STAT": 7, "IDCODE": 12}
REG_NAME = {v: k for k, v in REG.items()}
CMD = {"NULL": 0, "WCFG": 1, "LFRM": 3, "RCFG": 4, "START": 5, "RCRC": 7, "DESYNC": 13}
CMD_NAME = {v: k for k, v in CMD.items()}
OP_NOP, OP_READ, OP_WRITE = 0, 1, 2
FRAMES = B.DEVICE["frames"]
FW = FRAMES["words"]
FB = FRAMES["bits"]
NFRAMES = FRAMES["count"]
VERSION = 0x13

STAT_BITS = {"CRC_ERROR": 0, "GTS_CFG_B": 5, "GWE": 6, "INIT_COMPLETE": 11, "INIT_B": 12, "DONE": 14,
             "ID_ERROR": 15, "PKT_ERROR": 24, "WR_ERROR": 25, "SYNCED": 26, "WCFG": 27, "CRC_OK": 28,
             "GSR": 29, "START_OK": 30, "RCFG": 31}


def device_idcode():
    """the IDCODE the bitstream in the PL reports (hw/build.cfg)"""
    return buildcfg.expected_idcode()


def type1(op, reg, count):
    if not 0 <= count < 2048:
        raise ValueError("type-1 count is 11 bits")
    return 0x20000000 | (op << 27) | (reg << 13) | count


def type2(op, count):
    return 0x40000000 | (op << 27) | count


def write(reg, *data):
    return [type1(OP_WRITE, REG[reg], len(data)), *data]


def crc37(crc, reg, data):
    v = (reg << 32) | data
    for i in range(37):
        crc = ((crc >> 1) ^ 0x82F63B78) if ((crc ^ (v >> i)) & 1) else (crc >> 1)
    return crc


def far(column, minor=0, block_type=0):
    return (block_type << 23) | (column << 7) | minor


def frame_words(word):
    """the memory as NFRAMES x FW words, frame 0 word 0 first"""
    return [(word >> (32 * i)) & 0xFFFFFFFF for i in range(NFRAMES * FW)]


def word_from_frames(words):
    return sum(w << (32 * i) for i, w in enumerate(words))


def load_stream(word, idcode=None, crc_override=None):
    idcode = device_idcode() if idcode is None else idcode
    data = frame_words(word)
    s = [DUMMY, DUMMY, SYNC, NOP]
    s += write("CMD", CMD["RCRC"]) + [NOP]
    s += write("IDCODE", idcode)
    s += write("FAR", far(0))
    s += write("CMD", CMD["WCFG"]) + [NOP]
    s += [type1(OP_WRITE, REG["FDRI"], 0), type2(OP_WRITE, len(data))] + data
    s += write("CRC", expected_crc(word, idcode) if crc_override is None else crc_override)
    s += write("CMD", CMD["LFRM"])
    s += write("CMD", CMD["START"])
    s += write("CMD", CMD["DESYNC"]) + [NOP, NOP]
    return s


def expected_crc(word, idcode=None):
    """the CRC value load_stream writes: every WRITE data word after RCRC except CRC's"""
    idcode = device_idcode() if idcode is None else idcode
    crc = 0
    for reg, val in [(REG["IDCODE"], idcode), (REG["FAR"], far(0)), (REG["CMD"], CMD["WCFG"])]:
        crc = crc37(crc, reg, val)
    for w in frame_words(word):
        crc = crc37(crc, REG["FDRI"], w)
    return crc


def readback_stream():
    n = NFRAMES * FW
    return ([DUMMY, SYNC, NOP] + write("CMD", CMD["RCFG"]) + write("FAR", far(0)) +
            [type1(OP_READ, REG["FDRO"], 0), type2(OP_READ, n)] + write("CMD", CMD["DESYNC"]) + [NOP])


def read_stream(reg, n=1):
    return [DUMMY, SYNC, NOP, type1(OP_READ, REG[reg], n)] + write("CMD", CMD["DESYNC"]) + [NOP]


def to_jtag(words):
    """-> (nbits, value): bit 0 of value is the first bit on TDI = bit 31 of words[0]"""
    v, n = 0, 0
    for w in words:
        for b in range(31, -1, -1):
            v |= ((w >> b) & 1) << n
            n += 1
    return n, v


def from_jtag(value, nwords):
    out = []
    for i in range(nwords):
        w = 0
        for k in range(32):
            w = (w << 1) | ((value >> (32 * i + k)) & 1)
        out.append(w)
    return out


def decode_stat(v):
    return {name: (v >> bit) & 1 for name, bit in STAT_BITS.items()} | {"VERSION": (v >> 16) & 0xFF}


def describe(words):
    """one line per word, for dumps"""
    out, st, op, reg, left, synced = [], "hunt", 0, 0, 0, False
    for w in words:
        if not synced:
            out.append(f"{w:08X}  {'sync' if w == SYNC else 'dummy'}")
            synced = w == SYNC
            continue
        if st == "data":
            label = REG_NAME.get(reg, "?")
            if reg == REG["CMD"]:
                label += " " + CMD_NAME.get(w, "?")
            out.append(f"{w:08X}    {label} data")
            left -= 1
            st = "hdr" if left == 0 else "data"
            if reg == REG["CMD"] and w == CMD["DESYNC"]:
                synced = False
            continue
        if st == "t2":
            left = w & 0x7FFFFFF
            out.append(f"{w:08X}  type-2 count {left}")
            st = "data" if left and op == OP_WRITE else "hdr"
            continue
        kind = w >> 29
        if kind == 1:
            op, reg, cnt = (w >> 27) & 3, (w >> 13) & 0x1F, w & 0x7FF
            name = {0: "NOP", 1: "READ", 2: "WRITE"}.get(op, "?")
            out.append(f"{w:08X}  type-1 {name} {REG_NAME.get(reg, reg) if op else ''} count {cnt}")
            if op == OP_WRITE and cnt:
                st, left = "data", cnt
            elif op and cnt == 0:
                st = "t2"
        else:
            out.append(f"{w:08X}  ??")
    return out


class Controller:
    """Bit-level model of hw/src/core/cfg_frames.v (for tests and as the spec's executable form)."""

    def __init__(self, idcode=None, mem=0):
        self.idcode = device_idcode() if idcode is None else idcode
        self.mem = mem
        self.gwe = 0
        self.reset()

    def reset(self):
        self.sh = 0
        self.synced = False
        self.bitcnt = 0
        self.st, self.op, self.reg, self.cnt = "hdr", 0, 0, 0
        self.far = 0
        self.crc = 0
        self.flags = dict(wcfg=0, rcfg=0, lfrm=0, id_ok=0, crc_ok=0, data_seen=0, crc_err=0, id_err=0,
                          pkt_err=0, wr_err=0, start_ok=0)
        self.buf = []
        self.rd = (0, 0)
        self.rwidx = 0

    def jprogram(self):
        self.mem = 0
        self.reset()

    # FAR helpers from device.json
    def _cols(self):
        return {c["far_col"]: c for c in FRAMES["columns"]}

    def far_valid(self):
        cols = self._cols()
        col, minor = (self.far >> 7) & 0x3FF, self.far & 0x7F
        return (self.far >> 17) == 0 and col in cols and minor < cols[col]["count"]

    def far_fidx(self):
        cols = self._cols()
        return cols[(self.far >> 7) & 0x3FF]["base"] + (self.far & 0x7F)

    def far_next(self):
        cols = self._cols()
        col, minor = (self.far >> 7) & 0x3FF, self.far & 0x7F
        if minor + 1 < cols[col]["count"]:
            return self.far + 1
        for c in sorted(cols):
            if c > col and cols[c]["count"]:
                return far(c)
        return far(1023)

    def errors(self):
        f = self.flags
        return f["crc_err"] | f["id_err"] | f["pkt_err"] | f["wr_err"]

    def shift_in(self, nbits, value):
        for i in range(nbits):
            bit = (value >> i) & 1
            self.sh = ((self.sh << 1) | bit) & 0xFFFFFFFF
            if not self.synced:
                if self.sh == SYNC:
                    self.synced, self.bitcnt = True, 0
                continue
            if self.bitcnt == 31:
                self.bitcnt = 0
                self._word(self.sh)
            else:
                self.bitcnt += 1

    def _err(self, name):
        self.flags[name] = 1
        self.st = "err"

    def _word(self, w):
        f = self.flags
        if self.st == "err":
            return
        if self.st == "hdr":
            if w >> 29 != 1:
                return self._err("pkt_err")
            op, reg, cnt = (w >> 27) & 3, (w >> 13) & 0x1F, w & 0x7FF
            self.op, self.reg = op, reg
            if op == OP_NOP:
                return
            ok_w = reg in (0, 1, 2, 4, 12)
            ok_r = reg in (1, 3, 7, 12, 0)
            if (w >> 18) & 0x1FF or (w >> 11) & 3 or op == 3 or (op == OP_WRITE and not ok_w) or \
                    (op == OP_READ and not ok_r):
                return self._err("pkt_err")
            if cnt == 0:
                self.st = "t2"
            elif op == OP_READ:
                self._queue(reg, cnt)
            else:
                self.cnt, self.st = cnt, "data"
            return
        if self.st == "t2":
            if w >> 29 != 2 or ((w >> 27) & 3) != self.op:
                return self._err("pkt_err")
            cnt = w & 0x7FFFFFF
            if cnt == 0:
                self.st = "hdr"
            elif self.op == OP_READ:
                self._queue(self.reg, cnt)
                self.st = "hdr"
            else:
                self.cnt, self.st = cnt, "data"
            return
        # data
        reg = self.reg
        if self.cnt == 1:
            self.st = "hdr"
        self.cnt -= 1
        if reg != REG["CRC"]:
            self.crc = crc37(self.crc, reg, w)
        if reg == REG["CRC"]:
            if w == self.crc:
                f["crc_ok"] = 1
            else:
                self._err("crc_err")
        elif reg == REG["FAR"]:
            self.far = w
        elif reg == REG["IDCODE"]:
            if w == self.idcode:
                f["id_ok"] = 1
            else:
                self._err("id_err")
        elif reg == REG["CMD"]:
            if w == CMD["WCFG"]:
                f["wcfg"] = 1
            elif w == CMD["LFRM"]:
                f["lfrm"] = 1
            elif w == CMD["RCFG"]:
                f["rcfg"] = 1
            elif w == CMD["START"]:
                if f["crc_ok"] and f["id_ok"] and f["data_seen"] and not self.errors():
                    f["start_ok"] = 1
            elif w == CMD["RCRC"]:
                self.crc = 0
            elif w == CMD["DESYNC"]:
                self.synced, self.st = False, "hdr"
            elif w != CMD["NULL"]:
                self._err("pkt_err")
        elif reg == REG["FDRI"]:
            f["crc_ok"] = 0
            f["data_seen"] = 1
            if f["wcfg"] and f["id_ok"] and not self.gwe and self.far_valid() and not self.errors():
                self.buf.append(w)
                if len(self.buf) == FW:
                    frame = sum(x << (32 * i) for i, x in enumerate(self.buf))
                    lo = FB * self.far_fidx()
                    self.mem = (self.mem & ~(((1 << FB) - 1) << lo)) | (frame << lo)
                    self.far = self.far_next()
                    self.buf = []
            else:
                self._err("wr_err")

    def _queue(self, reg, cnt):
        self.rd = (reg, cnt)
        self.rwidx = 0
        if reg == REG["FDRO"] and not self.flags["rcfg"]:
            self.flags["wr_err"] = 1

    def read_word(self, gsr=1, gts=1, gwe=0, done=0):
        """the next word a CFG_OUT scan returns (the RTL's rword + advance)"""
        reg, cnt = self.rd
        if cnt == 0:
            return self.stat(gsr, gts, gwe, done)
        self.rd = (reg, cnt - 1)
        if reg == REG["FDRO"]:
            if not (self.flags["rcfg"] and self.far_valid()):
                return 0
            w = (self.mem >> (FB * self.far_fidx() + 32 * self.rwidx)) & 0xFFFFFFFF
            if self.rwidx == FW - 1:
                self.rwidx = 0
                self.far = self.far_next()
            else:
                self.rwidx += 1
            return w
        return {REG["FAR"]: self.far, REG["IDCODE"]: self.idcode, REG["CRC"]: self.crc}.get(
            reg, self.stat(gsr, gts, gwe, done))

    def stat(self, gsr=1, gts=1, gwe=0, done=0):
        f = self.flags
        v = f["crc_err"] | (int(not gts) << 5) | (gwe << 6) | (1 << 11) | (int(not self.errors()) << 12)
        v |= (done << 14) | (f["id_err"] << 15) | (VERSION << 16) | (f["pkt_err"] << 24) | (f["wr_err"] << 25)
        v |= (int(self.synced) << 26) | (f["wcfg"] << 27) | (f["crc_ok"] << 28) | (gsr << 29)
        v |= (f["start_ok"] << 30) | (f["rcfg"] << 31)
        return v


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("bit")
    args = ap.parse_args()
    import bitgen
    c = bitgen.read_bit(args.bit)
    words = load_stream(c["word"])
    shown = 0
    for line in describe(words):
        if "FDRI data" in line:
            shown += 1
            if shown == 9:
                print(f"          ... {NFRAMES * FW - 8} more FDRI data words "
                      f"({NFRAMES} frames x {FW} words in all) ...")
            if shown > 8:
                continue
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
