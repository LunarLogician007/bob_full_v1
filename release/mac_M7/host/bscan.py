"""
Interactive boundary-scan control.

Three instructions, three different things to do with the same nine cells:

  INTEST   the boundary DRIVES the fabric's inputs and captures its outputs.
           The physical switches are disconnected from the logic - you are the
           switches now.
  EXTEST   the boundary drives the output pads directly. The fabric is
           isolated, so the LEDs show whatever you put in the cells.
  SAMPLE   the boundary drives nothing and just watches. The fabric runs from
           the real switches; this is a window, not a lever.

A consequence of INTEST that surprises people: every cell drives, including the
three OUTPUT cells, so the LEDs are fed from those cells rather than from the
fabric. The fabric's answer arrives only by capture. This console writes each
captured answer back into the output cells, so the board shows what the logic
computed - one scan behind.

What comes back from a scan is worth reading carefully. A BC_1 cell captures
its system input whatever the mode is, so in INTEST bits 8:3 are the PHYSICAL
pins - not the vector you are injecting. You see both at once: what the
switches are actually doing, and what the fabric makes of what you sent it.
"""

import os
import select
import sys
import termios

import cfgplane      # 6-bit AMD instruction set since M3

CSI = "\x1b["

MODES = ("INTEST", "EXTEST", "SAMPLE")
MODE_BLURB = {
    "INTEST": "boundary drives the fabric - the switches are disconnected",
    "EXTEST": "boundary drives the LEDs - the fabric is isolated",
    "SAMPLE": "boundary watches only - the fabric runs from the real switches",
}

HELP = [
    "0-5 toggle an input bit      a all inputs on      z all off",
    "7 8 9 toggle an output pad (EXTEST only)",
    "i INTEST    e EXTEST    s SAMPLE    r re-read    q quit",
]


class Console:
    """Single-keystroke input, with a line-based fallback.

    Two things here are easy to get wrong and both make the console look dead:

    tty.setcbreak() turns off line buffering but LEAVES ECHO ON. Every key you
    press is then echoed into the middle of a display that redraws itself with
    cursor-up, which corrupts the frame and looks like nothing is happening. So
    ECHO is cleared explicitly. ISIG stays on, so Ctrl-C still works.

    sys.stdin.read(1) reads through Python's buffered text wrapper while
    select() watches the raw descriptor. Anything the wrapper has buffered is
    invisible to select, so keys get stranded. os.read() on the descriptor keeps
    the two in step.
    """

    def __init__(self, force_lines=False):
        self.force_lines = force_lines
        self.saved = None
        self.tty = False

    def __enter__(self):
        self.fd = sys.stdin.fileno()
        if self.force_lines or not sys.stdin.isatty():
            return self
        try:
            self.saved = termios.tcgetattr(self.fd)
            mode = termios.tcgetattr(self.fd)
            mode[3] &= ~(termios.ICANON | termios.ECHO)   # lflag
            mode[6][termios.VMIN] = 0
            mode[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, mode)
            termios.tcflush(self.fd, termios.TCIFLUSH)
            self.tty = True
        except (termios.error, OSError):
            self.saved = None      # fall back to line mode rather than fail
        return self

    def __exit__(self, *a):
        if self.saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    def key(self, timeout=0.15):
        if not self.tty:
            try:
                line = input("   key> ").strip()
            except (EOFError, KeyboardInterrupt):
                return "q"
            return line[:1] if line else "r"
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return None
        # Read a few bytes so an arrow key's escape sequence is consumed whole
        # instead of arriving as three separate keystrokes.
        data = os.read(self.fd, 8)
        if not data:
            return None
        return data.decode("utf-8", "ignore")[:1]


def _bits(v, n):
    return "  ".join(str((v >> i) & 1) for i in reversed(range(n)))


def run(p, model=None, label="", lines_mode=False):
    """model, if given, is a callable taking pad_i and returning expected pad_o."""
    mode = "INTEST"
    drive_in = 0          # the 6-bit vector we inject in INTEST
    drive_out = 0         # the 3-bit value we inject in EXTEST
    lines = 0

    cfgplane.ir(p, mode)

    with Console(force_lines=lines_mode) as con:
        try:
            while True:
                if mode == "INTEST":
                    raw = p.intest_settle(drive_in)
                elif mode == "EXTEST":
                    raw = p.extest_full(drive_out)
                else:
                    raw = p.shift_dr(9, 0)

                pins = (raw >> 3) & 0x3F
                outs = raw & 0x7
                applied = drive_in if mode == "INTEST" else pins

                body = []
                if label:
                    body.append(f"  {label}")
                body.append(f"  mode {mode}   -   {MODE_BLURB[mode]}")
                body.append("")
                body.append("   bit         8  7  6  5  4  3  |  2  1  0")
                body.append("   signal     i5 i4 i3 i2 i1 i0  | o2 o1 o0")
                if mode == "INTEST":
                    body.append(f"   driving    {_bits(drive_in, 6)}  |  -  -  -")
                elif mode == "EXTEST":
                    body.append(f"   driving     -  -  -  -  -  -  |  {_bits(drive_out, 3)}")
                else:
                    body.append("   driving     -  -  -  -  -  -  |  -  -  -")
                body.append(f"   captured   {_bits(pins, 6)}  |  {_bits(outs, 3)}")
                body.append("")
                body.append(f"   scan = {raw:09b}     pins i[5:0] = {pins:06b}"
                            f"     LEDs = {outs:03b}")
                if mode == "INTEST":
                    body.append(f"   the fabric is seeing {drive_in:06b}, "
                                f"not the switches ({pins:06b})")
                    body.append("   LEDs are mirrored from the capture: in INTEST the"
                                " output cells")
                    body.append("   drive the pads, so the answer is written back to"
                                " them to show it")
                if model is not None and mode in ("INTEST", "SAMPLE"):
                    try:
                        exp = model(applied)
                        ok = "match" if exp == outs else "MISMATCH"
                        body.append(f"   model = {exp:03b}   {ok}")
                    except Exception:
                        pass
                body.append("")
                for h in HELP:
                    body.append(f"   {h}")

                if lines and con.tty:
                    sys.stdout.write(f"{CSI}{lines}A")
                for ln in body:
                    sys.stdout.write(f"{CSI}2K" + ln + "\n")
                sys.stdout.flush()
                lines = len(body)
                if not con.tty:
                    lines = 0          # no cursor-up when a prompt is in the way

                k = con.key()
                if k is None:
                    continue
                if k in ("q", "\x03", "\x04"):
                    break
                elif k in "012345":
                    drive_in ^= 1 << int(k)
                elif k in "789":
                    drive_out ^= 1 << (int(k) - 7)
                elif k == "a":
                    drive_in = 0x3F
                elif k == "z":
                    drive_in, drive_out = 0, 0
                elif k in ("i", "e", "s"):
                    mode = {"i": "INTEST", "e": "EXTEST", "s": "SAMPLE"}[k]
                    cfgplane.ir(p, mode)
        except KeyboardInterrupt:
            pass

    cfgplane.ir(p, "BYPASS")
    print("\n  left test mode - the boundary is transparent and the switches"
          " drive the fabric again.")
