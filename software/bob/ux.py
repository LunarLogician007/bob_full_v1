#!/usr/bin/env python3
"""
ux.py - how bob talks to people: the words and layout of ./bob's output.

cli.py runs things; this module says what happened. Everything here is text in, text out,
so the command line and bob studio (software/host/studio.py) explain a failure the same way:

  usage_line(usage)        "LUTs 6/400  flip-flops 6/400  ..." from a build's synth stage
  explain(result)          a failed build -> the lines to show: what failed, where in the
                           source, the line itself, and what to do about it
  hints(text, stage)       the "what to do" part alone (the studio shows it under Messages)
  getting_started()        what ./bob prints with no command
  pins_text()              ./bob pins: the board pins, the pads and the naming rules
  examples()               ./bob examples: every design in work/examples with its first line
  doctor()                 ./bob doctor: every tool bob needs, found or not, and how to fix it
  NEW_DESIGN               the design ./bob new starts from

Colour only on a terminal, and never with NO_COLOR set (https://no-color.org).
"""

import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402

EXAMPLES = os.path.join(ROOT, "work", "examples")

# --- colour ---------------------------------------------------------------------

_CODES = {"ok": "32", "fail": "31", "warn": "33", "dim": "2", "bold": "1", "cmd": "36"}


def colour_on(stream=None):
    stream = stream or sys.stdout
    return (hasattr(stream, "isatty") and stream.isatty() and "NO_COLOR" not in os.environ
            and os.environ.get("TERM") != "dumb")


def paint(text, kind, on=None):
    if not (colour_on() if on is None else on) or kind not in _CODES:
        return text
    return f"\033[{_CODES[kind]}m{text}\033[0m"


def rel(path):
    """a path as the person would type it: relative to where they are, else from ~"""
    ap = os.path.abspath(path)
    cwd = os.getcwd()
    if ap.startswith(cwd + os.sep):
        return os.path.relpath(ap, cwd)
    home = os.path.expanduser("~")
    return "~" + ap[len(home):] if ap.startswith(home + os.sep) else ap


# --- a build that worked ---------------------------------------------------------


def usage_line(usage):
    """[{name, used, cap}] -> 'LUTs 6/400 (2%)  flip-flops 6/400 (2%)  ...'"""
    parts = []
    for u in usage:
        pct = 100 * u["used"] / u["cap"] if u["cap"] else 0
        parts.append(f"{u['name']} {u['used']}/{u['cap']}" + (f" ({pct:.0f}%)" if u["used"] else ""))
    return "  ".join(parts)


def summary(res, load_cmd="./bob load"):
    """the closing lines of a build that worked: what it used, its clock, what to run next"""
    st = {s.name: s for s in res.stages}
    out = []
    use = st["synth"].stats.get("usage") if "synth" in st else None
    if use:
        out.append(f"    uses    {usage_line(use)}")
    t = st.get("timing")
    if t is not None and t.stats.get("fmax_hz"):
        fmax = t.stats["fmax_hz"] / 1e6
        if res.flow.clock == "run" and t.stats.get("hz"):
            out.append(f"    clock   free-running at {t.stats['hz'] / 1e6:.4g} MHz "
                       f"(this design allows up to {fmax:.3g} MHz)")
        elif res.flow.clock == "run":
            out.append(f"    clock   free-running on the divider (--div {res.flow.div}); "
                       f"this design allows up to {fmax:.3g} MHz (--hz auto)")
        else:
            out.append(f"    clock   stepped over JTAG; for a free-running clock up to "
                       f"{fmax:.3g} MHz build with --clock run --hz auto")
    bit = rel(res.bit)
    out.append(f"    next    {paint(f'{load_cmd} {bit}', 'cmd')}"
               f"   (no board? add --probe fake)")
    return out


# --- a build that did not --------------------------------------------------------

# (pattern in the error or the messages, stage or None for any, what to do)
_HINTS = (
    (r"no such file", None,
     "check the path; ./bob examples lists the example designs"),
    (r"does not fit", "synth",
     "make the design smaller: bob has 400 elements (one LUT, one flip-flop and one carry "
     "bit each), 2 BRAMs and 2 DSPs"),
    (r"have no pin|has no pin", None,
     "./bob pins shows the pins and the port names that need no pin file"),
    (r"syntax error|error:|ERROR", "synth",
     "fix the line above and build again"),
    (r"differs from the source", "synth",
     "yosys changed what the design does: please report it with the --json record"),
    (r"docker not found|Cannot connect to the Docker daemon|is Docker running|docker\.sock", "pnr",
     "VPR runs in Docker: start it (colima start), or place and route without Docker: "
     "--pnr python"),
    (r"Routing failed|did not route|VPR failed", "pnr",
     "bob's routing is thin (each CLB input reaches 4 of 36 tracks): try --seed 5, --pnr python, "
     "or a smaller design"),
    (r"python pnr", "pnr",
     "try --seed 2, or the default VPR (--pnr vpr)"),
    (r"slack|does not meet|faster than", "timing",
     "ask for a slower clock, or let bob choose: --clock run --hz auto"),
    (r"differs from the source trace", "model",
     "the placed design does not behave like the source: please report it with --json"),
)


def hints(text, stage=None):
    out = []
    for pat, where, tip in _HINTS:
        if (where is None or where == stage) and re.search(pat, text or "") and tip not in out:
            out.append(tip)
    return out[:2]


def _source_line(path, line, cands=()):
    """the text of line `line` of `path` (tried as given, then next to each candidate)"""
    for p in [path] + [os.path.join(os.path.dirname(c), os.path.basename(path)) for c in cands]:
        try:
            with open(p, errors="replace") as fh:
                for i, text in enumerate(fh, 1):
                    if i == line:
                        return text.rstrip("\n")
        except OSError:
            continue
    return None


def explain(res, max_messages=6):
    """a failed flow Result -> the lines that tell the person what to do"""
    failed = next((s for s in res.stages if s.ok is False), None)
    stage = failed.name if failed else "flow"
    first = ((res.error or "").splitlines() or [""])[0].rstrip(":")
    out = [paint(f"  FAIL  {stage}: ", "fail") + first]
    msgs = [m for m in (failed.messages if failed else []) if m["severity"] == "error"]
    if not msgs and failed:
        msgs = [m for m in failed.messages if m["severity"] == "warning" and m.get("file")][:2]
    seen, uniq = set(), []
    for m in msgs:
        k = (os.path.basename(m.get("file") or ""), m.get("line"), m["text"])
        if k not in seen:
            seen.add(k)
            uniq.append(m)
    for m in uniq[:max_messages]:
        where = f"{m['file']}:{m['line']}: " if m.get("file") else ""
        out.append(f"        {where}{m['text']}")
        if m.get("file") and m.get("line"):
            src = _source_line(m["file"], m["line"], res.flow.files)
            if src is not None:
                out.append(paint(f"        {m['line']:>5} | {src.strip()}", "dim"))
    rest = (res.error or "").splitlines()[1:]
    if not msgs and rest:
        out += [f"        {ln}" for ln in rest[-8:]]
    text = (res.error or "") + "\n" + "\n".join(m["text"] for m in (failed.messages if failed else []))
    for tip in hints(text, stage):
        out.append(paint(f"  hint  {tip}", "warn"))
    log = {"synth": os.path.join(ROOT, "build", "synth", res.flow.top, f"{res.flow.top}.log"),
           "pnr": os.path.join(ROOT, "build", "vpr", res.flow.name, "vpr.log")}.get(stage)
    if log and os.path.exists(log):
        out.append(paint(f"  log   {rel(log)}", "dim"))
    return out


# --- what ./bob says with no command -------------------------------------------------


def getting_started():
    return f"""bob - an FPGA built inside the PYNQ-Z2's FPGA: {B.NCLB} CLBs, {len(B.ELEMENTS)} LUTs.

  First time here?
    ./bob doctor                        check the tools and the board
    ./bob examples                      the example designs
    ./bob run work/examples/counter/counter.v --probe fake
                                        build one and run it on the board in software

  Your own design
    ./bob new blink                     start one (blink/blink.v, sw/btn/led ready)
    ./bob build blink/src/blink.v       synthesis, place and route, bitstream
    ./bob load build/bit/blink.bit      configure the board (--probe fake: no board)
    ./bob run blink/src/blink.v         build and load in one go, then show the LEDs
    ./bob pins                          which port names reach the switches, buttons and LEDs

  More
    ./bob studio                        bob studio: editor, flow, device view, waveforms
    ./bob info x.bit | fasm x.bit       what a bitstream holds
    ./bob snap save|restore|list|sim    time-travel debugging of the running design
    ./bob <command> -h                  the options of one command

  docs/GETTING_STARTED.md walks through all of it."""


def pins_text():
    import device as D
    ins = ", ".join(f"{n} (pad{p})" for n, p in zip(D.BOARD_INPUTS, B.BOARD_IN))
    outs = ", ".join(f"{n} (pad{p})" for n, p in zip(D.BOARD_OUTPUTS, B.BOARD_OUT))
    return f"""Board pins (PYNQ-Z2)
  inputs   {ins}
  outputs  {outs}
  clock    clk: the user clock (stepped over JTAG, or free-running with --clock run)

With these port names a design needs no pin file:
  input  wire       clk       the user clock
  input  wire [1:0] sw        sw[1:0]  -> SW1..SW0
  input  wire [3:0] btn       btn[3:0] -> BTN3..BTN0
  output wire [2:0] led       led[2:0] -> LD2..LD0

Any other names need a pin file (--pcf), one line per port bit:
  set_io a      SW0
  set_io y[0]   LD0
  set_io probe  pad17          (pads 0..{B.NPAD - 1} are the fabric's edge pins)"""


def examples():
    """[(name, path, one line)] for every example design"""
    out = []
    for d in sorted(glob.glob(os.path.join(EXAMPLES, "*"))):
        name = os.path.basename(d)
        v = os.path.join(d, f"{name}.v")
        proj = glob.glob(os.path.join(d, "*.bobproj"))
        path = v if os.path.isfile(v) else (proj[0] if proj else None)
        if not path:
            continue
        line = ""
        if path.endswith(".v"):
            head = []
            for ln in open(v, errors="replace"):
                t = ln[2:].strip()
                # the sentence goes on when the next comment line starts in lower case
                if not ln.startswith("//") or (head and not (t[:1].islower() or t[:1].isdigit())):
                    break
                head.append(t)
            line = re.sub(r"^\S+\.v\s*[-:]\s*", "", " ".join(head))
            line = re.sub(r"\s*\(M\d+[^)]*\)", "", line)
            line = line.split(". ")[0].rstrip(".:, ")
            if len(line) > 78:
                line = line[:76].rsplit(" ", 1)[0].rstrip(",:;") + " ..."
        else:
            line = "a bob studio project with a block design (./bob build --project ...)"
        out.append((name, path, line))
    return out


def examples_text():
    rows = examples()
    w = max(len(n) for n, _, _ in rows)
    lines = ["Example designs (work/examples):"]
    for n, p, line in rows:
        lines.append(f"  {n:<{w}}  {line}")
    lines += ["", "Build and run one:  ./bob run work/examples/counter/counter.v --probe fake",
              "Copy one to start:  ./bob new mine --from counter"]
    return "\n".join(lines)


# --- ./bob doctor ------------------------------------------------------------------


def _run(cmd, env=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)


def doctor(board=True):
    """-> [(ok: True/False/None, what, detail, fix)]; None = optional and missing"""
    out = []
    v = sys.version_info
    out.append((v >= (3, 9), "python", f"{v.major}.{v.minor}.{v.micro}", "Python 3.9 or newer"))
    for tool, fix in (("yosys", "brew install yosys (synthesis)"),
                      ("iverilog", "brew install icarus-verilog (the equivalence check)")):
        path = shutil.which(tool)
        detail = path or "not found"
        if path:
            _, text = _run([tool, "-V"])
            detail = (text.splitlines() or [path])[0][:60]
        out.append((path is not None, tool, detail, fix))
    import vpr_run
    if shutil.which("docker") is None:
        out.append((None, "docker", "not found: new designs route with --pnr python only",
                    "brew install colima docker && colima start (VPR, the default place and route)"))
    else:
        code, text = _run(["docker", "info", "--format", "{{.ServerVersion}}"], env=vpr_run._docker_env())
        if code != 0:
            out.append((None, "docker", "installed but not running",
                        "colima start (or use --pnr python)"))
        else:
            code, _ = _run(["docker", "image", "inspect", vpr_run.IMAGE], env=vpr_run._docker_env())
            out.append((True, "docker", f"server {text.splitlines()[0]}"
                        + ("" if code == 0 else f"; VPR image not pulled yet ({vpr_run.IMAGE})"),
                        f"docker pull {vpr_run.IMAGE}" if code else ""))
    try:
        import webview  # noqa: F401
        out.append((True, "pywebview", "bob studio opens as a desktop app", ""))
    except ImportError:
        out.append((None, "pywebview", "not installed: bob studio opens in the browser instead",
                    "pip3 install pywebview"))
    try:
        import usb.core  # noqa: F401
        usb_ok = True
    except ImportError:
        usb_ok = False
        out.append((False, "pyusb", "not installed: no board access", "pip3 install pyusb"))
    if usb_ok and board:
        import dirtyjtag
        import usb.core
        try:
            dev = usb.core.find(idVendor=dirtyjtag.VID, idProduct=dirtyjtag.PID)
        except Exception as e:                       # noqa: BLE001 - no backend (libusb)
            dev = None
            out.append((False, "libusb", str(e)[:60], "brew install libusb"))
        if dev is None:
            out.append((None, "Pico probe", "not plugged in (the board steps are skipped; "
                        "--probe fake works without it)", "plug the Pico (DirtyJTAG) into USB and PMODA"))
        else:
            out.append((True, "Pico probe", f"found ({dirtyjtag.VID:04x}:{dirtyjtag.PID:04x})", ""))
            out.append(_board_check())
    return out


def _board_check():
    import fpga
    from fakeboard import probe as open_probe
    try:
        p = open_probe("usb")
        idc = p.read_idcode()
    except (SystemExit, Exception) as e:            # noqa: BLE001 - report, never crash
        return (False, "board", f"no answer ({e})", "is the PYNQ-Z2 powered and the PMODA cable on?")
    if idc == fpga.IDCODE_FABRIC:
        return (True, "board", f"IDCODE 0x{idc:08X}: the bob bitstream is running", "")
    if idc in (0, 0xFFFFFFFF):
        return (False, "board", f"IDCODE 0x{idc:08X}: nothing answers on JTAG",
                "check the PMODA cable and that the board is on")
    return (False, "board", f"IDCODE 0x{idc:08X}, expected 0x{fpga.IDCODE_FABRIC:08X}",
            "program the bob bitstream (docs/reports/<milestone>/bob_top.bit) onto the PYNQ-Z2")


def doctor_text(rows):
    lines = ["bob doctor"]
    w = max(len(r[1]) for r in rows)
    for ok, what, detail, fix in rows:
        mark = paint("ok  ", "ok") if ok else paint("--  ", "warn") if ok is None else paint("FAIL", "fail")
        lines.append(f"  {mark}  {what:<{w}}  {detail}")
        if not ok and fix:
            lines.append(paint(f"        {'':<{w}}  -> {fix}", "dim"))
    bad = [r for r in rows if r[0] is False]
    lines.append("")
    lines.append("everything bob needs is here" if not bad else
                 f"{len(bad)} problem(s) above; the rest of bob works without the optional ones (--)")
    return "\n".join(lines)


# --- ./bob new ---------------------------------------------------------------------

NEW_DESIGN = """// {name}.v - a new bob design (./bob new). The ports below need no pin file:
//   clk  the user clock      sw[1:0]   the two switches
//   btn[3:0]  the buttons     led[2:0]  the three LEDs
// Build and run it:  ./bob run {path}        (--probe fake: no board)
module {name} (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);
    // a 3-bit counter: BTN0 counts, BTN1 clears, SW0 turns the LEDs off
    reg [2:0] count = 3'd0;
    always @(posedge clk)
        if (btn[1])      count <= 3'd0;
        else if (btn[0]) count <= count + 3'd1;
    assign led = sw[0] ? 3'b000 : count;
endmodule
"""
