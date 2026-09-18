#!/usr/bin/env python3
"""
Build a design, route it, load it into the bob fabric over JTAG, and run it on
the board.

  ./fpga.py --list                 what designs are built in
  ./fpga.py --report three         place and route it, print the result, no hardware
  ./fpga.py --load and             build it, load it, then watch the switches
  ./fpga.py --selftest             load every design and verify it through INTEST
  ./fpga.py --watch                monitor the board pads, leave the config alone

The board: SW0, SW1, BTN0..3 are pad_i bits 0..5 and sit on West-edge fabric
pads; LD0..LD2 are pad_o bits 0..2 on East-edge pads; LD3 is DONE. Since M7 the
boundary has two cells per fabric pad (software/bob/device.json "bsr"); the helpers
below translate board vectors to and from it.

Loading goes through software/host/cfgplane.py (docs/bitstream-format.md section 8).
"""

import argparse
import sys
import time

import buildcfg
import cfgplane
from bitstream import BOARD_IN, BOARD_OUT, BSR_W, FABRIC_CFG_W, NPAD, simulate
from designs import DESIGNS, BY_KEY

_CFG = buildcfg.read_cfg()
IDCODE_FABRIC = (buildcfg.expected_idcode(_CFG)
                 if _CFG.get("top") == "bob_top" and _CFG.get("idcode") else 0x9BEEF093)
CSI = "\x1b["


# --- the boundary, in board terms ---------------------------------------------

def bsr_word(v):
    """Board input vector -> boundary word (input cell of pad n is bit NPAD + n)."""
    return sum(((v >> k) & 1) << (NPAD + pad) for k, pad in enumerate(BOARD_IN))


def bsr_leds(raw):
    """Captured boundary word -> LD2..0 as the fabric drove them (output cells)."""
    return sum(((raw >> pad) & 1) << k for k, pad in enumerate(BOARD_OUT))


def bsr_board_in(raw):
    """Captured boundary word -> the physical board inputs (input cells capture pins)."""
    return sum(((raw >> (NPAD + pad)) & 1) << k for k, pad in enumerate(BOARD_IN))


def sample(p):
    """One SAMPLE scan (the IR must hold SAMPLE): board inputs and LEDs, undisturbed."""
    raw = p.shift_dr_fast(BSR_W, 0)
    i = bsr_board_in(raw)
    return {"raw": raw, "i": i, "sw": i & 3, "btn": (i >> 2) & 0xF, "leds": bsr_leds(raw)}


# --- configuration ---------------------------------------------------------

def load_bitstream(p, bs, verbose=True, force_slow=False):
    """Load the chain through the configuration plane and start it: JPROGRAM,
    expected CRC, CFG_IN, status, CFG_OUT readback, JSTART, DONE. The readback
    is the only thing between a silently mangled transfer and a design that was
    never loaded; the CRC stops a mangled chain from ever reaching the fabric."""
    t0 = time.time()
    ok, msg = cfgplane.load(p, bs.to_int(), FABRIC_CFG_W, start=True,
                            fast_first=not force_slow)
    dt = time.time() - t0
    if ok:
        if verbose:
            print(f"  {msg} in {dt:.2f}s")
        return True
    print(f"  FAIL  {msg}")
    return False


def go_live(p):
    cfgplane.ir(p, "BYPASS")


# --- verification ----------------------------------------------------------

def intest_sweep(p, vectors):
    """Apply each board vector through the boundary and collect LD2..0.

    INTEST is pipelined by one scan: what a scan captures answers the vector the
    previous scan committed. So prime with the first vector and read one late.
    """
    cfgplane.ir(p, "INTEST")
    vs = list(vectors)
    p.shift_dr_fast(BSR_W, bsr_word(vs[0]))
    out = []
    for k in range(len(vs)):
        nxt = vs[(k + 1) % len(vs)]
        out.append(bsr_leds(p.shift_dr_fast(BSR_W, bsr_word(nxt))))
    return out


def verify(p, key, desc, fn, sweep):
    bs = fn().build()
    print(f"\n[{key}] {desc}")
    if not load_bitstream(p, bs):
        return False
    vs = list(sweep)
    got = intest_sweep(p, vs)
    bad = []
    for v, g in zip(vs, got):
        e = simulate(bs, v)
        if g != e:
            bad.append((v, g, e))
    if bad:
        print(f"  FAIL  {len(bad)} of {len(vs)} vectors wrong")
        for v, g, e in bad[:6]:
            print(f"        pad_i={v:06b}  LD2..0={g:03b}  expected {e:03b}")
        return False
    print(f"  PASS  {len(vs)} vectors match the model")
    return True


# --- live view -------------------------------------------------------------

def watch(p, bs=None, label="", refresh=0.05):
    print(f"  {label or 'monitoring the fabric'}")
    print("  flip SW0 / SW1, press the buttons. Ctrl-C to stop.\n")
    cfgplane.ir(p, "SAMPLE")
    lines = 0
    try:
        while True:
            s = sample(p)
            body = [
                "   pads in    SW1={} SW0={}   BTN3..0 = {:04b}   (pad_i = {:06b})".format(
                    (s["sw"] >> 1) & 1, s["sw"] & 1, s["btn"], s["i"]),
                "   pads out   LD2..0 = {:03b}".format(s["leds"]),
            ]
            if bs is not None:
                try:
                    e = simulate(bs, s["i"])
                    body.append("   model      {:03b}   {}".format(
                        e, "match" if e == s["leds"] else "MISMATCH"))
                except ValueError:
                    body.append("   model      (not a combinational design)")
            if lines:
                sys.stdout.write(f"{CSI}{lines}A")
            for ln in body:
                sys.stdout.write(f"{CSI}2K" + ln + "\n")
            sys.stdout.flush()
            lines = len(body)
            time.sleep(refresh)
    except KeyboardInterrupt:
        print("\n  stopped. The fabric is still configured and still live.")


# --- entry points ----------------------------------------------------------

def cmd_list():
    print("built-in designs:\n")
    for key, desc, fn, sweep in DESIGNS:
        print(f"  {key:9s} {desc}")
    print("\nload one with:  ./fpga.py --load <name>")
    return 0


def cmd_report(key):
    if key not in BY_KEY:
        sys.exit(f"unknown design '{key}'. try --list")
    desc, fn, sweep = BY_KEY[key]
    d = fn()
    bs = d.build()
    print(f"{key}: {desc}\n")
    print(d.report())
    print(f"\n  bitstream: {FABRIC_CFG_W} bits, {bin(bs.to_int()).count('1')} set")
    print("\n  truth table by the software model:")
    for v in sorted(set(list(BY_KEY[key][2])))[:16]:
        print(f"    pad_i={v:06b} -> LD2..0={simulate(bs, v):03b}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--report", metavar="NAME")
    ap.add_argument("--load", metavar="NAME")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--slow", action="store_true",
                    help="shift the config per-pulse instead of in bulk")
    ap.add_argument("--freq", type=int, default=100, help="TCK frequency in kHz")
    args = ap.parse_args()

    if args.list:
        return cmd_list()
    if args.report:
        return cmd_report(args.report)

    from dirtyjtag import Probe
    p = Probe(freq_khz=args.freq)
    print(f"probe: {p.info()}")
    idcode = p.read_idcode()
    if idcode != IDCODE_FABRIC:
        print(f"\n  IDCODE = 0x{idcode:08X}, expected 0x{IDCODE_FABRIC:08X}")
        print({0x2BEEF093: "  That is the single-CLB build.",
               0x4BEEF093: "  That is the M2 configuration-plane test top, not the fabric.",
               0x8BEEF093: "  That is the M6 4x4 fabric - build and program hw/ (M7, bob_top)."}
              .get(idcode, "  Run ./host/tap_probe.py to work out why."))
        return 1
    print(f"IDCODE 0x{idcode:08X}  - bob is alive\n")

    if args.selftest:
        ok = all(verify(p, k, d, f, s) for k, d, f, s in DESIGNS)
        go_live(p)
        print("\n=== ALL DESIGNS PASSED ===" if ok else "\n=== SOME DESIGNS FAILED ===")
        return 0 if ok else 1

    if args.watch:
        watch(p)
        return 0

    key = args.load or "showcase"
    if key not in BY_KEY:
        sys.exit(f"unknown design '{key}'. try --list")
    desc, fn, sweep = BY_KEY[key]
    d = fn()
    bs = d.build()
    print(f"{key}: {desc}\n")
    print(d.report())
    print()
    if not load_bitstream(p, bs, force_slow=args.slow):
        return 1
    go_live(p)
    print()
    watch(p, bs, label=f"{key}: {desc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
