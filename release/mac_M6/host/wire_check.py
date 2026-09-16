#!/usr/bin/env python3
"""
Check the harness one jumper at a time, using the Pico as the meter.

The Pico can *drive* TCK/TMS/TDI and *read* TDO, so every test here works by
feeding a known signal into one wire and reading it back out of the TDO wire.

  ./wire_check.py            run everything, guided
  ./wire_check.py --wires    continuity of each jumper, on its own
  ./wire_check.py --orient   confirm the PMODA pin numbering and that OUR
                             bitstream is the one currently in the PL

SAFETY: before touching wire ends together, unplug them from the PMODA header.
Shorting a Pico output to an FPGA output is driver-versus-driver contention and
can damage a pin on either side. Every test below says what to unplug.
"""

import sys

from dirtyjtag import Probe


def ask(prompt):
    try:
        input(f"\n  >> {prompt}\n     press Enter when ready (Ctrl-C to stop) ... ")
    except (EOFError, KeyboardInterrupt):
        print("\naborted")
        sys.exit(130)


def report(name, results):
    ok = all(got == want for want, got in results)
    detail = "  ".join(f"{want}->{got}" for want, got in results)
    print(f"     {name:<26} {detail}     {'PASS' if ok else 'FAIL'}")
    return ok


def test_wires(p):
    print("=" * 68)
    print("JUMPER CONTINUITY")
    print("=" * 68)
    print("""
  Unplug ALL FIVE wires from the PMODA header. Leave them plugged into the
  Pico. You will touch loose ends together in mid-air, so nothing on the FPGA
  is involved and there is no risk of contention.""")

    results = {}

    # --- TDI -----------------------------------------------------------
    ask("Touch the loose end of the TDI wire (Pico GP16) "
        "to the loose end of the TDO wire (Pico GP17).")
    r = [(v, p.pulse(tdi=v)) for v in (1, 0, 1, 1, 0)]
    results["TDI"] = report("TDI wire + TDO wire", r)

    # --- TMS -----------------------------------------------------------
    ask("Now move it: touch the loose end of the TMS wire (Pico GP19) "
        "to the loose end of the TDO wire.")
    r = [(v, p.pulse(tms=v)) for v in (1, 0, 1, 1, 0)]
    results["TMS"] = report("TMS wire + TDO wire", r)

    # --- TCK -----------------------------------------------------------
    # TCK cannot be parked at a level - CMD_SETSIG with TCK high emits a pulse.
    # TDO is sampled while TCK is high, so a good wire reads back 1.
    ask("Now touch the loose end of the TCK wire (Pico GP18) "
        "to the loose end of the TDO wire.")
    samples = [p.pulse() for _ in range(5)]
    ones = sum(samples)
    ok = ones >= 4
    print(f"     {'TCK wire + TDO wire':<26} sampled {samples}     "
          f"{'PASS' if ok else 'FAIL'}")
    if not ok:
        print("       (TCK is pulsed, not parked, so this test is the least"
              " reliable of the three -")
        print("        an intermittent result here is worth a retry before"
              " condemning the wire)")
    results["TCK"] = ok

    print()
    bad = [k for k, v in results.items() if not v]
    if bad:
        print(f"  -> suspect wire(s): {', '.join(bad)}")
        print("     Reseat the Dupont crimps at both ends, or swap the wire.")
    else:
        print("  -> all three signal wires carry a level end to end.")
        print("     Note this does NOT test the GND wire; check that with a"
              " multimeter,")
        print("     or just reseat it - a missing ground looks exactly like a"
              " dead link.")
    return not bad


def test_orient(p):
    print("=" * 68)
    print("PMODA ORIENTATION  +  IS OUR BITSTREAM ACTUALLY LIVE")
    print("=" * 68)
    print("""
  Plug ONLY the TDO wire into the Pico (GP17, pin 22). Leave TCK, TMS and TDI
  unplugged at BOTH ends, so the Pico is not driving anything on the header.
  Keep the GND wire connected between the two boards.

  You will use the free end of the TDO wire as a probe tip and touch it to
  numbered pins on the PMODA header.

  The last two checks rely on the internal pulls our design sets on its input
  pins - PULLUP on TMS, PULLDOWN on TCK. They are only present if OUR bitstream
  is the one in the PL, so they double as proof the right design is loaded.""")

    checks = [
        ("PMODA pin 6 (3V3)", 1,
         "should read 1 - this is the header's own 3.3 V rail"),
        ("PMODA pin 5 (GND)", 0,
         "should read 0 - the header's ground"),
        ("PMODA pin 1 (Y18, TMS)", 1,
         "should read 1 - our XDC sets PULLUP on TMS"),
        ("PMODA pin 7 (U18, TCK)", 0,
         "should read 0 - our XDC sets PULLDOWN on TCK"),
        ("PMODA pin 3 (Y16, TDO)", 0,
         "should read 0 - our TAP drives TDO low when idle"),
    ]

    results = []
    for label, want, why in checks:
        ask(f"Touch the TDO probe tip to {label}.  ({why})")
        samples = [p.pulse(tms=1) for _ in range(5)]
        got = 1 if sum(samples) >= 3 else 0
        ok = got == want
        results.append((label, want, got, ok))
        print(f"     read {got} (samples {samples})  expected {want}     "
              f"{'PASS' if ok else 'FAIL'}")

    print()
    rail_ok = results[0][3] and results[1][3]
    pull_ok = results[2][3] and results[3][3]

    if not rail_ok:
        print("  -> The 3V3/GND readings are wrong. Either the TDO wire is"
              " broken, or you")
        print("     are counting the header pins from the wrong end. PMODA pin"
              " 1 is the one")
        print("     marked on the silkscreen; pins 1-6 are the top row, 7-12"
              " the bottom.")
        print("     If 3V3 and GND came out swapped, your numbering is"
              " mirrored - and every")
        print("     other wire is on the wrong pin too.")
    elif not pull_ok:
        print("  -> The rails read correctly, so the wire and your pin"
              " numbering are fine,")
        print("     but the pull-ups/downs our design asks for are NOT"
              " present.")
        print("     That means the PL is configured with some OTHER bitstream."
              " DONE being lit")
        print("     only says *a* design is loaded, not that it is ours -"
              " if the board boots")
        print("     PYNQ from SD, the base overlay gets programmed at boot and"
              " will have")
        print("     replaced yours. Reprogram with -tclargs program and retest"
              " without power cycling.")
    else:
        print("  -> Header numbering is right and our bitstream is live in the"
              " PL.")
        print("     Reconnect all five wires and re-run:  ./host/tap_probe.py")
    return rail_ok and pull_ok


def main():
    p = Probe(freq_khz=100)
    args = sys.argv[1:]
    if "--wires" in args:
        return 0 if test_wires(p) else 1
    if "--orient" in args:
        return 0 if test_orient(p) else 1
    a = test_wires(p)
    print()
    b = test_orient(p)
    return 0 if (a and b) else 1


if __name__ == "__main__":
    sys.exit(main())
