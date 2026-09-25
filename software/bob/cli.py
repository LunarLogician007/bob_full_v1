#!/usr/bin/env python3
"""
bob - build a Verilog design for the bob FPGA and run it (M10; the commands a person uses).

  ./bob                          what bob can do, in short (ux.getting_started)
  ./bob build design.v           Verilog -> .bit: every stage of software/bob/flow.py, checked
  ./bob build blink              the same from a project folder or .bobproj (bob studio's)
  ./bob run design.v             build, load and read the LEDs in one step
  ./bob load x.bit               configure the board (--probe fake: the board in software)
  ./bob new blink [--from ex]    a project folder with a design to start from
  ./bob examples | pins | doctor the example designs, the board pins, a setup check
  ./bob info x.bit | fasm x.bit  what a bitstream holds
  ./bob snap save|restore|list|sim   time-travel debugging (M25)
  ./bob studio                   bob studio, the desktop app (M19)

What the output says - usage, hints, the failing source line - comes from software/bob/ux.py,
so bob studio explains a failure the same way. build() and load() stay the library calls the
tests, hwtest and studio use.

Pins: without --pcf, sw[1:0] -> SW1..0, btn[3:0] -> BTN3..0, led[2:0] -> LD2..0.
A .pcf has `set_io <port bit> <SW0|SW1|BTN0..3|LD0..2|pad<N>>` lines.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402
import bitgen  # noqa: E402
import chainbits  # noqa: E402
import fasm_from_vpr as FV  # noqa: E402
import vpr_run  # noqa: E402

CONVENTION = {"clk", "sw", "btn", "led"}


class BuildError(Exception):
    pass


PROJECT_KEYS = ("files", "top", "pcf", "name", "clock", "div", "seed", "pnr", "hz", "sdc")


def read_project(path):
    """bob.proj -> the keyword arguments build() takes. Paths are relative to the
    project file, so a project can be moved or shared with its sources.

    A .bobproj (M18, bob studio's New Project) is read by software/bob/project.py and also
    names where the .bit goes: <project>/build/<name>.bit."""
    if path.endswith(".bobproj") or os.path.isdir(path):
        import project
        try:
            return project.Project.open(path).flow_kwargs()
        except project.ProjectError as e:
            raise BuildError(str(e))
    try:
        d = json.load(open(path))
    except (OSError, ValueError) as e:
        raise BuildError(f"{path}: {e}")
    bad = set(d) - set(PROJECT_KEYS)
    if bad:
        raise BuildError(f"{path}: unknown key(s) {sorted(bad)}; expected {list(PROJECT_KEYS)}")
    if not d.get("files"):
        raise BuildError(f"{path}: no 'files'")
    base = os.path.dirname(os.path.abspath(path))
    d["files"] = [os.path.normpath(os.path.join(base, f)) for f in d["files"]]
    for k in ("pcf", "sdc"):
        if d.get(k):
            d[k] = os.path.normpath(os.path.join(base, d[k]))
    return d


def result_dir(name, pnr="vpr"):
    """where build() took the place-and-route result from"""
    if pnr == "python":
        return os.path.join(ROOT, "build", "pnr", name)
    stamp = vpr_run.read_stamp(name)
    if stamp is not None and vpr_run.stale(name) is None:
        return os.path.join(vpr_run.RESULTS, name)
    return os.path.join(ROOT, "build", "vpr", name)


def build(files, top=None, pcf=None, out=None, clock=None, div=0, seed=1, name=None,
          log=print, pnr="vpr", hz=None, sdc=None):
    """-> (bit path, word, bram contents, board trace or None, result directory)

    The stages live in software/bob/flow.py, which times each one and hands back what it
    measured; this prints those lines and keeps the tuple older callers expect."""
    import flow
    try:
        f = flow.Flow(files, top=top, pcf=pcf, out=out, clock=clock, div=div,
                      seed=seed, name=name, pnr=pnr, hz=hz, sdc=sdc)
    except flow.FlowError as e:
        raise BuildError(str(e))
    res = f.run(on_stage=lambda st: log(f"  {st.name:8s} {st.detail}"))
    if not res.ok:
        raise BuildError(res.error)
    return res.bit, res.word, res.brams, res.trace, res.work


def write_brams(p, brams):
    """Every word of every BRAM the design uses, zeros included: BRAM contents survive
    JPROGRAM and a new chain, so a word left out keeps the previous design's value
    (as UG470 bitstreams initialise all BRAM contents, not only the non-zero words)."""
    import cfgplane
    msg = ""
    for b, words in sorted(brams.items()):
        full = list(words) + [0] * (1024 - len(words))
        cfgplane.bram_select(p, b)
        cfgplane.bram_fill(p, full)
        msg += f", bram{b} all 1024 words"
    return msg


def contract(word, spacing=True):
    """M21: refuse a word whose critical path does not fit the gce spacing it would run at
    (software/bob/timing.py). The XDC no longer times the fabric; this check is what does.
    spacing=False keeps only the loop check: for the board's clock-margin sweep, which runs
    a design faster than its computed clock on purpose to find where silicon fails.
    -> None, or the reason."""
    import timing as T
    try:
        if spacing:
            T.check_contract(word)
        else:
            T.analyse(word)
    except T.TimingError as e:
        return str(e)
    return None


def load(p, path, start=True, log=print, mode="frames", over_clock=False):
    """.bit -> configuration memory + BRAM contents -> JSTART.
    mode "frames" (M13 default): UG470-style packets on CFG_IN, STAT, FDRO readback; since
    M15 the BRAM contents travel in the same stream as block-type-1 frames (under the CRC);
    mode "chain": CHAIN_IN with CFG_CTRL CRC, CHAIN_OUT readback, BRAM contents over USER4.
    M21: a word that breaks the timing contract is refused before anything is sent;
    over_clock=True (hwtest's clock-margin sweep only) lets it run faster than its path."""
    import cfgplane
    c = bitgen.read_bit(path)
    why = contract(c["word"], spacing=not over_clock)
    if why:
        return False, why
    if mode == "frames":
        ok, msg = cfgplane.load_frames(p, c["word"], start=False, brams=c["brams"])
    elif mode == "chain":
        ok, msg = cfgplane.load(p, c["word"], B.CHAIN_W, start=False)
    else:
        return False, f"mode is frames or chain, not {mode}"
    if not ok:
        return False, msg
    if mode == "chain":
        msg += write_brams(p, c["brams"])
    if start:
        cfgplane.jstart(p)
        st = cfgplane.status(p)
        if not st["done"]:
            return False, f"{msg}; DONE did not rise: {st}"
        msg += ", DONE"
    return True, msg


def load_partial(p, path, log=print):
    """M14: reconfigure the running design to this .bit, rewriting only the frames that
    differ, with the user clock held (AGHIGH ... LFRM). BRAM contents are not touched."""
    import cfgplane
    c = bitgen.read_bit(path)
    why = contract(c["word"])
    if why:
        return False, why
    ok, msg, _n = cfgplane.load_partial(p, c["word"])
    return ok, msg


SNAP_DIR = os.path.join(ROOT, "build", "snapshots")


def snap_cmd(args):
    """M25: bob snap save|restore|list|sim (software/host/snapshot.py)"""
    sys.path.insert(0, os.path.join(ROOT, "software", "host"))
    import zlib
    import snapshot as S
    os.makedirs(SNAP_DIR, exist_ok=True)
    path = lambda n: os.path.join(SNAP_DIR, f"{n}.json")                       # noqa: E731
    if args.action == "list":
        for f in sorted(os.listdir(SNAP_DIR)):
            d = json.load(open(os.path.join(SNAP_DIR, f)))
            print(f"{f[:-5]:20s} {len(d['state'])} flip-flops, design crc {d['design']}, {d['how']}")
        return 0
    if not args.name:
        raise BuildError(f"bob snap {args.action} needs a name")
    load_state = lambda d: {(i, w): v for i, w, v in d["state"]}              # noqa: E731
    dump = lambda st: [[i, w, v] for (i, w), v in sorted(st.items())]          # noqa: E731
    if args.action == "sim":
        d = json.load(open(path(args.name)))
        word = int(d["word"], 16)
        m = S.to_model(word, load_state(d))
        for _ in range(args.steps):
            m.clock(pad_i=args.pads, cin=args.cin)
        new = args.save or f"{args.name}+{args.steps}"
        json.dump({**d, "state": dump(S.from_model(m, word)),
                   "how": f"{args.name} + {args.steps} steps in model.py"}, open(path(new), "w"))
        print(f"  {new}: {args.name} run {args.steps} user-clock steps in the simulator "
              f"(bob snap restore {new} puts it on the chip)")
        return 0
    import cfgplane
    import packets
    p = open_board(args.probe)
    word = cfgplane.cfg_out(p, packets.NFRAMES * packets.FB)          # the design on the chip
    crc = f"{zlib.crc32(word.to_bytes((B.CHAIN_W + 7) // 8, 'little')):08x}"
    if args.action == "save":
        state, notes = S.snapshot(p, word)
        json.dump({"design": crc, "word": f"{word:x}", "state": dump(state), "how": "captured on the chip",
                   "notes": notes}, open(path(args.name), "w"))
        print(f"  saved {args.name}: {len(state)} flip-flops" + (f" (not restorable: {', '.join(notes)})" if notes else ""))
        return 0
    d = json.load(open(path(args.name)))
    if d["design"] != crc:
        raise BuildError(f"snapshot {args.name} is of another design (crc {d['design']}, the chip has {crc})")
    try:
        n = S.restore(p, word, load_state(d))
    except S.SnapshotError as e:
        raise BuildError(f"restore {args.name}: {e}")
    print(f"  restored {args.name}: {len(d['state'])} flip-flops ({n} frames rewritten twice, GRESTORE)")
    return 0


def open_board(kind="usb", freq=1000):
    """the probe, or a BuildError that says what to check (dirtyjtag exits the process when
    no Pico is plugged in: turn that into advice instead)"""
    from fakeboard import probe as open_probe
    try:
        return open_probe(kind, freq_khz=freq) if kind == "usb" else open_probe(kind)
    except SystemExit as e:
        raise BuildError(f"{e} - plug the Pico (DirtyJTAG) in, or use --probe fake for the "
                         "board in software; ./bob doctor checks the setup")
    except ImportError as e:
        raise BuildError(f"{e} - pip3 install pyusb (./bob doctor checks the setup)")


def _project_path(files):
    """a lone folder or .bobproj given as the design: a bob studio project"""
    if len(files) == 1 and (files[0].endswith(".bobproj") or os.path.isdir(files[0])):
        return files[0]
    return None


def build_cmd(args, quiet_next=False):
    """./bob build and the first half of ./bob run -> (ok, Result or None)"""
    import flow
    import ux
    kw = dict(files=args.files, top=args.top, pcf=args.pcf, name=args.name,
              clock=args.clock, div=args.div, seed=args.seed, pnr=args.pnr, hz=args.hz,
              sdc=args.sdc)
    proj = args.project or _project_path(args.files)
    if proj:
        # the file supplies the defaults; anything given on the command line wins
        given = {k: v for k, v in kw.items()
                 if v not in (None, [], "jtag", 0, 1, "vpr") or k == "files" and v}
        kw = {**{k: v for k, v in kw.items() if k != "files"}, **read_project(proj)}
        kw.update({k: v for k, v in given.items() if k != "files" and v is not None})
    if not kw.get("files"):
        raise BuildError("no sources: ./bob build design.v (or a project folder); ./bob examples lists some")
    kw["out"] = args.output or kw.get("out")
    print(f"bob build {' '.join(ux.rel(f) for f in kw['files'])}")
    try:
        f = flow.Flow(**kw)
    except flow.FlowError as e:
        raise BuildError(str(e))
    # a failed stage is told once, by ux.explain below, not also as its stage line
    res = f.run(on_stage=lambda st: st.ok and print(f"  {st.name:8s} {st.detail}"))
    if getattr(args, "json", None):
        text = json.dumps(res.to_json(), indent=2)
        if args.json == "-":
            print(text)
        else:
            open(args.json, "w").write(text + "\n")
            print(f"  json     {ux.rel(args.json)}")
    if not res.ok:
        print("\n".join(ux.explain(res)))
        return False, res
    print(ux.paint("  PASS  ", "ok") + f"built {ux.rel(res.bit)} in {res.seconds:.1f} s")
    lines = ux.summary(res)
    print("\n".join(lines[:-1] if quiet_next else lines))
    return True, res


def load_cmd(bit, probe="usb", freq=1000, mode="frames", partial=False, watch=False, show=False):
    import fpga
    import ux
    why = contract(bitgen.read_bit(bit)["word"])           # refuse before touching hardware
    if why:
        raise BuildError(why)
    p = open_board(probe, freq)
    idcode = p.read_idcode()
    if idcode != fpga.IDCODE_FABRIC:
        raise BuildError(f"the board answers IDCODE 0x{idcode:08X}, not bob's 0x{fpga.IDCODE_FABRIC:08X}: "
                         "program the bob bitstream onto the PYNQ-Z2 first "
                         "(or add --freq 100 for a bob bitstream older than the 1 MHz one)")
    ok, msg = load_partial(p, bit) if partial else load(p, bit, mode=mode)
    fpga.go_live(p)
    print((ux.paint("  PASS  ", "ok") if ok else ux.paint("  FAIL  ", "fail")) + f"load {ux.rel(bit)}: {msg}")
    if ok and show and not watch:
        try:
            fpga.cfgplane.ir(p, "SAMPLE")
            s = fpga.sample(p)
            fpga.go_live(p)
            print(f"    LEDs    LD2..0 = {s['leds']:03b}   (SW1..0 = {s['sw']:02b}, BTN3..0 = {s['btn']:04b});"
                  f" add --watch to follow them")
        except Exception:                                   # noqa: BLE001 - a reading is a bonus
            pass
    if ok and watch:
        fpga.watch(p)
    return ok


def new_cmd(args):
    import project
    import ux
    where = os.path.abspath(args.dir or ".")
    try:
        src = args.src
        if src and not os.path.isfile(src):          # checked before anything is made
            ex = {n: path for n, path, _ in ux.examples() if path.endswith(".v")}
            if src not in ex:
                raise project.ProjectError(f"--from {src}: not a file or an example ({', '.join(ex)})")
            src = ex[src]
        p = project.Project.create(where, args.name)
        if src:
            rel = p.add_source(src)
            top = os.path.splitext(os.path.basename(src))[0]
        else:
            rel = p.new_source(args.name, ux.NEW_DESIGN.format(
                name=args.name, path=ux.rel(os.path.join(p.dir))))
            top = args.name
        p.set_top(top)
        p.save()
    except project.ProjectError as e:
        raise BuildError(str(e))
    d = ux.rel(p.dir)
    print(ux.paint("  PASS  ", "ok") + f"new design {args.name} in {d}/")
    print(f"    source  {d}/{rel}")
    print(f"    project {d}/{os.path.basename(p.path)}   (bob studio: Open Project…)")
    print(f"    next    {ux.paint(f'./bob run {d} --probe fake', 'cmd')}   (drop --probe fake on the board)")
    return 0


def info_cmd(args):
    import ux
    c = bitgen.read_bit(args.bit)
    F = bitgen.features_from_word(c["word"])
    m = c["meta"]
    if args.raw:
        print(f"{args.bit}: device {c['name']}, {c['width']}-bit chain, crc 0x{c['crc']:08X}, "
              f"file version {c['version']}, {len(F)} FASM features, "
              f"BRAM contents {sorted(c['brams']) or 'none'}")
        for k, v in sorted(m.items()):
            print(f"  {k}: {v}")
        return 0
    import timing as T
    print(ux.rel(args.bit))
    src = ", ".join(ux.rel(os.path.normpath(os.path.join(ROOT, f))) for f in m.get("sources") or []) or "?"
    print(f"    design  {m.get('design', '?')} (top module {m.get('top', '?')}), from {src}")
    print(f"    device  {c['name']}: {c['width']}-bit configuration, CRC 0x{c['crc']:08X}, "
          f"{len(F)} configuration settings")
    print(f"    pins    {m['pcf'] if m.get('pcf') else 'the sw/btn/led defaults (./bob pins)'}")
    print(f"    placed  {'bob own place and route' if m.get('pnr') == 'python' else 'VPR'}"
          + (f" (result {m['vpr_result']})" if m.get("vpr_result") else ""))
    brams = sorted(c["brams"])
    print(f"    BRAM    {'contents for ' + ', '.join(f'bram{b}' for b in brams) if brams else 'none used'}")
    try:
        t = T.analyse(c["word"])
        print(f"    timing  critical path {t['cpd_ns']} ns, up to {t['fmax_hz'] / 1e6:.3g} MHz"
              f" ({'estimated' if t['provisional'] else 'measured'} delays x {t['margin']})")
    except T.TimingError as e:
        print(f"    timing  {e}")
    if m.get("clock") == "run":
        hz = B.guest_hz("run", m.get("pdiv") or m.get("div") or 0, m.get("period") or 0, m.get("gap") or 0)
        print(f"    clock   free-running at {hz / 1e6:.4g} MHz" if hz >= 1e5 else f"    clock   free-running at {hz:.4g} Hz")
    else:
        print("    clock   stepped over JTAG (the host steps it)")
    print(f"    next    {ux.paint(f'./bob load {ux.rel(args.bit)}', 'cmd')}   (--raw: every stored field)")
    return 0


EPILOG = """examples:
  ./bob                                  what bob can do, in short
  ./bob run work/examples/counter/counter.v --probe fake
  ./bob new blink && ./bob run blink     a design of your own
  ./bob doctor                           check the tools and the board
more: docs/GETTING_STARTED.md"""


def _parser():
    ap = argparse.ArgumentParser(prog="bob", description="bob - build Verilog for the bob FPGA and run it "
                                 "on the PYNQ-Z2 (or on the board in software).",
                                 epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", metavar="command")

    def build_args(b):
        b.add_argument("files", nargs="*", help="Verilog files, or a project folder / .bobproj")
        b.add_argument("--top", help="the top module (default: the first file's name)")
        b.add_argument("--pcf", help="a pin file, for ports other than clk/sw/btn/led (./bob pins)")
        b.add_argument("-o", "--output", help="where the .bit goes (default build/bit/<name>.bit)")
        b.add_argument("--clock", choices=("jtag", "run"),
                       help="jtag: the host steps the clock (default); run: a free-running clock "
                            "(the default with --sdc or --hz)")
        b.add_argument("--div", type=int, default=0,
                       help="with --clock run: 125 MHz / 2^(div+9)")
        b.add_argument("--hz", help="with --clock run: 'auto' = the fastest this design's timing allows, "
                                    "or a rate in Hz (refused if faster than that)")
        b.add_argument("--sdc", help="a clock constraint (create_clock -period <ns> [get_ports clk]); "
                                     "the build fails if the design does not meet it")
        b.add_argument("--seed", type=int, default=1, help="placement seed (another one may route "
                                                           "a design that did not)")
        b.add_argument("--name", help="result name (default: the top module)")
        b.add_argument("--pnr", default="vpr", choices=("vpr", "python"),
                       help="place and route with VPR (default, in Docker) or bob's own (no Docker)")
        b.add_argument("--project", help="read files, top, pins and settings from a .proj or .bobproj file")
        b.add_argument("--json", metavar="FILE", help="write the build record (stages, timings, "
                                                      "diagnostics) as JSON; - for stdout")

    def board_args(x):
        x.add_argument("--probe", default="usb", choices=("usb", "fake"),
                       help="usb: the Pico on PMODA (default); fake: the board in software")
        x.add_argument("--freq", type=int, default=1000,
                       help="JTAG clock in kHz (default 1000; 100 for a bob bitstream older than the 1 MHz one)")

    build_args(sub.add_parser("build", help="Verilog -> a bob bitstream (.bit)",
                              description="synthesis, equivalence check, place and route, bitstream, "
                                          "timing and a model check: every step checked before the next",
                              epilog="examples:\n  ./bob build work/examples/counter/counter.v\n"
                                     "  ./bob build blink                      (a project folder)\n"
                                     "  ./bob build fast.v --clock run --hz auto\n"
                                     "  ./bob build gates.v --pcf my_pins.pcf",
                              formatter_class=argparse.RawDescriptionHelpFormatter))
    r = sub.add_parser("run", help="build, load and show the LEDs, in one step",
                       epilog="examples:\n  ./bob run work/examples/counter/counter.v --probe fake\n"
                              "  ./bob run blink --watch",
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    build_args(r)
    board_args(r)
    r.add_argument("--watch", action="store_true", help="follow the switches and LEDs until Ctrl-C")
    ld = sub.add_parser("load", help="configure the board with a .bit",
                        epilog="examples:\n  ./bob load build/bit/counter.bit\n"
                               "  ./bob load build/bit/counter.bit --probe fake     (no board)\n"
                               "  ./bob load new.bit --partial     (swap the running design, frames that differ)",
                        formatter_class=argparse.RawDescriptionHelpFormatter)
    ld.add_argument("bit")
    board_args(ld)
    ld.add_argument("--watch", action="store_true", help="follow the switches and LEDs until Ctrl-C")
    ld.add_argument("--mode", default="frames", choices=("frames", "chain"),
                    help="configuration path: UG470-style frames (default) or the scan chain")
    ld.add_argument("--partial", action="store_true",
                    help="reconfigure the RUNNING design: only the frames that differ, clock held")
    n = sub.add_parser("new", help="start a design of your own (a project folder)",
                       epilog="examples:\n  ./bob new blink                (blink/src/blink.v from a template)\n"
                              "  ./bob new mine --from counter  (a copy of an example)",
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    n.add_argument("name", help="the design's name: letters, digits and _")
    n.add_argument("--from", dest="src", metavar="EXAMPLE_OR_FILE", help="start from an example or a .v file")
    n.add_argument("--dir", help="where the project folder goes (default: here)")
    sub.add_parser("examples", help="the example designs, one line each")
    sub.add_parser("pins", help="the board pins and the port names that need no pin file")
    d = sub.add_parser("doctor", help="check the tools, Docker, the Pico and the board")
    d.add_argument("--no-board", action="store_true", help="skip the USB and board checks")
    i = sub.add_parser("info", help="what a .bit holds: design, pins, timing, clock")
    i.add_argument("bit")
    i.add_argument("--raw", action="store_true", help="every stored field as it is")
    sub.add_parser("fasm", help="a .bit's configuration as FASM text").add_argument("bit")
    sn = sub.add_parser("snap", help="time-travel debugging: save / restore the running design's "
                                     "flip-flops, or run a snapshot on in the simulator",
                        epilog="examples:\n  ./bob snap save before\n  ./bob snap sim before --steps 10 --save later\n"
                               "  ./bob snap restore later\n  ./bob snap list",
                        formatter_class=argparse.RawDescriptionHelpFormatter)
    sn.add_argument("action", choices=("save", "restore", "list", "sim"))
    sn.add_argument("name", nargs="?")
    sn.add_argument("--steps", type=int, default=1, help="sim: user-clock steps in the simulator")
    sn.add_argument("--pads", type=lambda v: int(v, 0), default=0, help="sim: the input pads during the steps")
    sn.add_argument("--save", metavar="NEW", help="sim: store the result as snapshot NEW")
    sn.add_argument("--cin", type=int, default=0, help="sim: the bottom carry-in during the steps")
    sn.add_argument("--probe", default="usb", choices=("usb", "fake"))
    st = sub.add_parser("studio", help="bob studio: editor, flow, device view, waveforms")
    st.add_argument("--probe", choices=("usb", "fake"), help="open a target at start (fake: no board)")
    st.add_argument("--browser", action="store_true", help="a browser tab instead of the app window")
    st.add_argument("--port", type=int)
    return ap


def main(argv=None):
    import ux
    args = _parser().parse_args(argv)
    if not args.cmd:
        print(ux.getting_started())
        return 0

    if args.cmd == "studio":
        sys.path.insert(0, os.path.join(ROOT, "software", "host"))
        import studio
        if args.browser:
            studio.serve(args.port or 8765, args.probe, True)
        else:
            studio.serve_app(args.port or 0, args.probe)
        return 0

    try:
        if args.cmd == "build":
            return 0 if build_cmd(args)[0] else 1
        if args.cmd == "run":
            ok, res = build_cmd(args, quiet_next=True)
            if not ok:
                return 1
            return 0 if load_cmd(res.bit, args.probe, args.freq, watch=args.watch, show=True) else 1
        if args.cmd == "load":
            return 0 if load_cmd(args.bit, args.probe, args.freq, args.mode, args.partial,
                                 args.watch, show=True) else 1
        if args.cmd == "new":
            return new_cmd(args)
        if args.cmd == "examples":
            print(ux.examples_text())
            return 0
        if args.cmd == "pins":
            print(ux.pins_text())
            return 0
        if args.cmd == "doctor":
            rows = ux.doctor(board=not args.no_board)
            print(ux.doctor_text(rows))
            return 0 if all(r[0] is not False for r in rows) else 1
        if args.cmd == "snap":
            return snap_cmd(args)
        if args.cmd == "info":
            return info_cmd(args)
        if args.cmd == "fasm":
            sys.stdout.write(FV.to_fasm(bitgen.features_from_word(bitgen.read_bit(args.bit)["word"])))
            return 0
    except (BuildError, FV.FasmError, chainbits.ChainFileError, vpr_run.VprError, RuntimeError, OSError) as e:
        print(ux.paint("  FAIL  ", "fail") + str(e))
        for tip in ux.hints(str(e)):
            print(ux.paint(f"  hint  {tip}", "warn"))
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
