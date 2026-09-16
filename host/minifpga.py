#!/usr/bin/env python3
"""
Drive the one-CLB mini FPGA on the PYNQ-Z2 from a Pico running DirtyJTAG.

The board IS the demo: SW1/SW0 and BTN3..0 are the logic block's input pads,
LD0/LD1/LD2 are its output pads. Send a 71-bit bitstream over JTAG and the
block becomes whatever gate you asked for - then flip the switches and watch
the LEDs.

  ./minifpga.py                     load AND, go live, watch the boundary
  ./minifpga.py --gate xor          same with a different gate
  ./minifpga.py --shell             interactive: reconfigure and poke at it
  ./minifpga.py --selftest          full verification run, mirrors the testbench

  ./minifpga.py --watch             just monitor, leave the config alone
  ./minifpga.py --drive 5           EXTEST: drive LD2..LD0 from JTAG
  ./minifpga.py --truth             walk the truth table over INTEST
  ./minifpga.py --init 0x8888...    load an arbitrary 64-bit LUT INIT
"""

import argparse
import sys
import time

from dirtyjtag import (Probe, GATES, IDCODE_EXPECTED, CFG_W, BSR_W,
                       IR_EXTEST, IR_SAMPLE, IR_INTEST, IR_BYPASS, IR_CONFIG,
                       USER_AUTOSTEP)

FAIL = []
CSI = "\x1b["


def gate_of(init):
    for name, (gi, _) in GATES.items():
        if gi == init:
            return name.upper()
    return None


def expected_o(init, i):
    """What the LUT should output for input vector i, straight from INIT."""
    return (init >> (i & 0x3F)) & 1


# ---------------------------------------------------------------------------
# the live view - this is the one that matters at the bench
# ---------------------------------------------------------------------------

def watch(p, init=None, refresh=0.05):
    """Monitor the boundary continuously with SAMPLE.

    SAMPLE captures the pins and the CLB outputs but drives nothing, so the
    block keeps running from the physical switches the whole time. Flip a
    switch and you see it move here and on the LEDs together.
    """
    name = gate_of(init) if init is not None else None
    title = f"INIT = 0x{init:016X}" + (f"   ({name})" if name else "") if init is not None else \
            "config not touched by this run"

    print(f"  {title}")
    print("  flip SW0 / SW1 on the board. Ctrl-C to stop.\n")

    p.shift_ir(IR_SAMPLE)
    lines = 0
    try:
        while True:
            s = p.sample()
            i = s["i"]
            out = []
            out.append("   boundary bit   8  7  6  5  4  3 |  2  1  0")
            out.append("   signal        i5 i4 i3 i2 i1 i0 | cy o5  o")
            out.append("   value         {:2d} {:2d} {:2d} {:2d} {:2d} {:2d} | {:2d} {:2d} {:2d}".format(
                (i >> 5) & 1, (i >> 4) & 1, (i >> 3) & 1,
                (i >> 2) & 1, (i >> 1) & 1, i & 1,
                s["cout"], s["o5"], s["o"]))
            out.append("")
            out.append(f"   pads in       SW1={ (s['sw'] >> 1) & 1 }  SW0={ s['sw'] & 1 }"
                       f"     BTN3..0 = {s['btn']:04b}")
            out.append(f"   pads out      LD2(cout)={s['cout']}  LD1(o5)={s['o5']}  LD0(o)={s['o']}")
            if init is not None:
                exp = expected_o(init, i)
                mark = "match" if exp == s["o"] else "MISMATCH"
                label = f"{name}(i1,i0)" if name else "LUT[i]"
                out.append(f"   expected      {label} = {exp}      {mark}")

            if lines:
                sys.stdout.write(f"{CSI}{lines}A")
            for ln in out:
                sys.stdout.write(f"{CSI}2K" + ln + "\n")
            sys.stdout.flush()
            lines = len(out)
            time.sleep(refresh)
    except KeyboardInterrupt:
        print("\n  stopped. The block is still configured and still live.")


# ---------------------------------------------------------------------------
# one-shot commands
# ---------------------------------------------------------------------------

def load(p, init, ctrl=0):
    p.reset_to_idle()
    p.load_config(init, ctrl)
    p.go_live()                       # boundary transparent: the pads take over
    name = gate_of(init)
    print(f"  loaded {CFG_W}-bit config, INIT = 0x{init:016X}"
          + (f"   ({name})" if name else ""))
    print("  boundary is transparent - the CLB is running from the real pins.")
    return init


def show_truth(p, init):
    name = gate_of(init) or "LUT"
    rows = p.truth_table(2)
    print(f"\n  {name} over i[1:0], walked through INTEST")
    print("    i1 i0 | o")
    print("    ------+--")
    ok = True
    for r, v in enumerate(rows):
        exp = expected_o(init, r)
        bad = "" if v == exp else f"   <- expected {exp}"
        if v != exp:
            ok = False
        print(f"     {(r >> 1) & 1}  {r & 1} | {v}{bad}")
    print(f"    {'PASS' if ok else 'FAIL'}")
    p.go_live()
    return ok


def do_sample(p):
    p.shift_ir(IR_SAMPLE)
    s = p.sample()
    print(f"  boundary = {s['raw']:09b}")
    print(f"    i[5:0]  = {s['i']:06b}   SW1={(s['sw'] >> 1) & 1} SW0={s['sw'] & 1}"
          f"  BTN3..0={s['btn']:04b}")
    print(f"    outputs = cout {s['cout']}   o5 {s['o5']}   o {s['o']}")


def do_drive(p, pads):
    p.extest(pads)
    print(f"  EXTEST: driving LD2 LD1 LD0 = {pads & 0x7:03b}")
    print("  the CLB is isolated - those LEDs are coming straight from the")
    print("  boundary update registers, not from any logic.")


def do_intest(p, vec):
    p.shift_ir(IR_INTEST)
    p.intest(vec)                     # apply
    res = p.intest(vec)               # pipelined by one scan: this reads it
    print(f"  INTEST: applied i[5:0] = {vec & 0x3F:06b}")
    print(f"          o={res & 1}  o5={(res >> 1) & 1}  cout={(res >> 2) & 1}")
    print("  the physical switches are disconnected while INTEST is selected.")


# ---------------------------------------------------------------------------
# interactive shell
# ---------------------------------------------------------------------------

HELP = """
  gate <name>     load a gate: and or xor nand nor xnor buf not
  init <hex>      load an arbitrary 64-bit LUT INIT
  cfg             read the 71-bit config back (non-destructively)
  truth           walk the truth table over INTEST
  watch           live boundary monitor, Ctrl-C to come back
  sample          one boundary read
  in <vec>        INTEST: apply an input vector, e.g. 'in 11' or 'in 0b101101'
  drive <bits>    EXTEST: drive LD2..LD0, e.g. 'drive 5'
  live            leave test mode, hand the CLB back to the switches
  ff <name>       load a gate with the flip-flop enabled and autostep on
  step            one clock enable pulse
  sr              pulse the synchronous reset
  id              read the IDCODE
  quit
"""


def shell(p):
    init = None
    print(HELP)
    while True:
        try:
            line = input("  minifpga> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        cmd, _, arg = line.partition(" ")
        cmd, arg = cmd.lower(), arg.strip()
        try:
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd in ("help", "?"):
                print(HELP)
            elif cmd == "gate":
                if arg not in GATES:
                    print(f"  unknown gate. choose from: {', '.join(sorted(GATES))}")
                    continue
                init = load(p, GATES[arg][0])
            elif cmd == "init":
                init = load(p, int(arg, 0))
            elif cmd == "ff":
                if arg not in GATES:
                    print(f"  unknown gate. choose from: {', '.join(sorted(GATES))}")
                    continue
                # FF_EN | FF_CE_EN | FF_SR_EN  -> the flop waits for a step
                init = load(p, GATES[arg][0], ctrl=0b0001101)
                p.write_user(1 << USER_AUTOSTEP)
                print("  flip-flop enabled, autostep on: each INTEST scan clocks it once.")
            elif cmd == "cfg":
                if init is None:
                    print("  nothing loaded this session; 'cfg' needs the word to shift back.")
                    continue
                back = p.read_config(init)
                print(f"  INIT read back = 0x{back & ((1 << 64) - 1):016X}"
                      f"   ctrl = {(back >> 64) & 0x7F:07b}")
                p.go_live()
            elif cmd == "truth":
                if init is None:
                    print("  load a gate first")
                    continue
                show_truth(p, init)
            elif cmd == "watch":
                watch(p, init)
            elif cmd == "sample":
                do_sample(p)
            elif cmd == "in":
                do_intest(p, int(arg, 0) if arg.startswith("0") else int(arg, 2))
            elif cmd == "drive":
                do_drive(p, int(arg, 0))
            elif cmd == "live":
                p.go_live()
                print("  boundary transparent - the switches drive the CLB again.")
            elif cmd == "step":
                p.write_user(1 << 3)
                p.write_user(0)
                print("  one clock enable pulse issued.")
            elif cmd == "sr":
                p.write_user((1 << 1) | (1 << 3))
                p.write_user(0)
                print("  synchronous reset pulsed.")
            elif cmd == "id":
                print(f"  IDCODE = 0x{p.read_idcode():08X}")
            else:
                print("  ? try 'help'")
        except ValueError:
            print("  could not parse that argument")
        except Exception as e:
            print(f"  error: {e}")


# ---------------------------------------------------------------------------

def selftest(p):
    print("=== mini FPGA self-test ===\n")
    idcode = p.read_idcode()
    ok = idcode == IDCODE_EXPECTED
    print(f"  {'PASS' if ok else 'FAIL'}  IDCODE = 0x{idcode:08X}")
    if not ok:
        if idcode == 0x1BEEF093:
            print("\n  That is the TAP-ONLY build. Rebuild and reprogram:")
            print("    vivado -mode batch -source hw/scripts/build.tcl -tclargs all")
        return 1

    p.shift_ir(IR_BYPASS)
    got = p.shift_dr(32, 0xD5A73C91)
    print(f"  {'PASS' if got == 0xAB4E7922 else 'FAIL'}  BYPASS = 0x{got:08X}")

    for name in ("and", "or", "xor", "nand", "nor", "xnor"):
        gi = GATES[name][0]
        p.load_config(gi)
        if not show_truth(p, gi):
            FAIL.append(name)

    print("\n[64-row sweep] 6-input parity")
    parity = 0
    for n in range(64):
        if bin(n).count("1") & 1:
            parity |= 1 << n
    p.load_config(parity)
    rows = p.truth_table(6)
    bad = [r for r in range(64) if rows[r] != (bin(r).count("1") & 1)]
    print(f"  {'PASS  all 64 rows match' if not bad else f'FAIL  {len(bad)} rows wrong'}")
    if bad:
        FAIL.append("parity")

    p.go_live()
    print()
    print("=== ALL CHECKS PASSED ===" if not FAIL else f"=== FAILED: {', '.join(FAIL)} ===")
    return 1 if FAIL else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gate", default=None, help="and or xor nand nor xnor buf not")
    ap.add_argument("--init", help="64-bit LUT INIT, e.g. 0x8888888888888888")
    ap.add_argument("--shell", action="store_true", help="interactive session")
    ap.add_argument("--selftest", action="store_true", help="full verification run")
    ap.add_argument("--watch", action="store_true", help="monitor only, do not configure")
    ap.add_argument("--truth", action="store_true", help="walk the truth table")
    ap.add_argument("--drive", help="EXTEST: drive LD2..LD0 (0-7)")
    ap.add_argument("--sample", action="store_true", help="one boundary read")
    ap.add_argument("--freq", type=int, default=100, help="TCK frequency in kHz")
    args = ap.parse_args()

    p = Probe(freq_khz=args.freq)
    print(f"probe: {p.info()}")

    idcode = p.read_idcode()
    if idcode != IDCODE_EXPECTED:
        print(f"\n  IDCODE = 0x{idcode:08X}, expected 0x{IDCODE_EXPECTED:08X}")
        if idcode == 0x1BEEF093:
            print("  That is the TAP-ONLY build - rebuild and reprogram first.")
        else:
            print("  Run ./host/tap_probe.py to work out why.")
        return 1
    print(f"IDCODE 0x{idcode:08X}  - mini FPGA is alive\n")

    if args.selftest:
        return selftest(p)
    if args.shell:
        shell(p)
        return 0
    if args.drive is not None:
        do_drive(p, int(args.drive, 0))
        return 0
    if args.sample:
        do_sample(p)
        return 0
    if args.watch:
        watch(p, None)
        return 0

    init = int(args.init, 0) if args.init else GATES[(args.gate or "and").lower()][0]
    load(p, init)
    if args.truth:
        return 0 if show_truth(p, init) else 1
    print()
    watch(p, init)
    return 0


if __name__ == "__main__":
    sys.exit(main())
