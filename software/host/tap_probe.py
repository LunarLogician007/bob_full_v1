#!/usr/bin/env python3
"""
Low-level diagnostic for the TAP - bit-bangs TCK one pulse at a time and prints
the raw TDO stream.

This exists because "TDO is stuck at 0" from openFPGALoader or urjtag tells you
something is wrong but not what. The raw bits separate the failure modes.

  ./tap_probe.py             IDCODE, BYPASS and the CONFIG chain
  ./tap_probe.py --leds      walk a pattern across LD2..LD0 over EXTEST
  ./tap_probe.py --loopback  test the probe alone, FPGA disconnected
  ./tap_probe.py --idle      just report the resting TDO level

For the logic itself - gates, truth tables, the switches - use minifpga.py.
"""

import sys
import time

from dirtyjtag import Probe, IDCODE_EXPECTED, CFG_W, IR_EXTEST, IR_BYPASS


def bits_str(value, n):
    """LSB-first, as it comes off the wire."""
    return "".join(str((value >> i) & 1) for i in range(n))


def do_loopback(p):
    print("LOOPBACK TEST")
    print("  Disconnect the FPGA and jumper Pico GP16 (TDI, pin 21)")
    print("  to GP17 (TDO, pin 22), then re-run.\n")
    ok = True
    for want in (1, 0, 1, 1, 0):
        got = p.pulse(tdi=want)
        if got != want:
            ok = False
        print(f"  drove TDI={want} -> read TDO={got}   {'ok' if got == want else 'MISMATCH'}")
    print()
    if ok:
        print("  PASS - probe, firmware, USB stack and host tooling all work.")
        print("  The problem is on the FPGA side of the harness.")
    else:
        print("  FAIL - the probe itself is not looping back.")
        print("  Check the jumper, and that the firmware is pico-dirtyJtag V1.07.")
    return ok


def do_leds(p):
    """Walk a pattern across LD2..LD0 using EXTEST, so the boundary drives the
    pads directly and the CLB is not involved at all."""
    print("Walking a pattern on LD2..LD0 over EXTEST. Ctrl-C to stop.\n")
    p.reset_to_idle()
    p.shift_ir(IR_EXTEST)
    try:
        while True:
            for v in (0b001, 0b010, 0b100, 0b010):
                p.shift_dr(9, v)
                print(f"\r  pad_o = {v:03b}", end="", flush=True)
                time.sleep(0.15)
    except KeyboardInterrupt:
        p.shift_dr(9, 0)
        p.go_live()
        print("\n  cleared.")
    return 0


def do_scan(p):
    print("IDLE LEVEL")
    print(f"  TDO in Test-Logic-Reset: {p.sample_tdo()}")
    print("  (0 is expected - the TAP drives TDO low outside the shift states)\n")

    print("IDCODE SCAN")
    idcode = p.read_idcode()
    print(f"  raw TDO, LSB first : {bits_str(idcode, 32)}")
    print(f"  assembled          : 0x{idcode:08X}")
    print(f"  expected           : 0x{IDCODE_EXPECTED:08X}\n")

    if idcode == IDCODE_EXPECTED:
        print("  PASS - the mini FPGA is alive and answering.\n")
    elif idcode == 0x1BEEF093:
        print("  This is the TAP-ONLY build (version nibble 1), not the mini FPGA.")
        print("  Rebuild and reprogram:")
        print("    vivado -mode batch -source hw/scripts/build.tcl -tclargs all\n")
        return False
    elif idcode == 0:
        print("  FAIL - TDO never went high.")
        print("    * is the bitstream actually loaded?  (reprogram with -tclargs program,")
        print("      configuration is volatile and is lost on every power cycle)")
        print("    * is TDO wired from PMODA pin 3 (Y16) to Pico GP17 (pin 22)?")
        print("    * run with --loopback to rule out the probe.\n")
        return False
    elif idcode == 0xFFFFFFFF:
        print("  FAIL - TDO is stuck high, which usually means it is floating.")
        print("    The FPGA is not driving it: wrong pin, or no bitstream.\n")
        return False
    else:
        rot = [((idcode << k) | (idcode >> (32 - k))) & 0xFFFFFFFF for k in range(32)]
        if IDCODE_EXPECTED in rot:
            print(f"  NEARLY - the IDCODE rotated by {rot.index(IDCODE_EXPECTED)} bit(s).")
            print("    That is a clock-edge problem, not a wiring problem.\n")
        else:
            print("  FAIL - unexpected data. If it changes run to run, suspect")
            print("    signal integrity: shorten the leads and check the ground.\n")
        return False

    print("BYPASS SCAN")
    p.shift_ir(IR_BYPASS)
    pattern = 0xD5A73C91
    got = p.shift_dr(32, pattern)
    expect = (pattern << 1) & 0xFFFFFFFF
    print(f"  shifted in  : 0x{pattern:08X}")
    print(f"  read back   : 0x{got:08X}")
    print(f"  expected    : 0x{expect:08X}  (delayed one TCK, first bit is the captured 0)")
    ok = got == expect
    print(f"  {'PASS - BYPASS is a single bit, as it should be.' if ok else 'FAIL'}\n")

    print("CONFIG CHAIN")
    init = 0xA5A5A5A5DEADBEEF
    p.load_config(init)
    back = p.read_config(init)
    print(f"  wrote INIT  : 0x{init:016X}")
    print(f"  read back   : 0x{back & ((1 << 64) - 1):016X}")
    ok2 = (back & ((1 << 64) - 1)) == init
    print(f"  {'PASS - the ' + str(CFG_W) + '-bit config chain round-trips.' if ok2 else 'FAIL'}\n")

    p.go_live()
    return ok and ok2


def main():
    p = Probe()
    print(f"probe: {p.info()}\n")
    if "--loopback" in sys.argv:
        return 0 if do_loopback(p) else 1
    if "--leds" in sys.argv:
        return do_leds(p)
    if "--idle" in sys.argv:
        print(f"TDO in Test-Logic-Reset: {p.sample_tdo()}")
        return 0
    return 0 if do_scan(p) else 1


if __name__ == "__main__":
    sys.exit(main())
