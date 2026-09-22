#!/usr/bin/env python3
"""
bob - build a Verilog design for the bob FPGA and load it (M10).

  ./bob build work/examples/counter/counter.v [--top counter] [--pcf pins.pcf] [-o counter.bit]
              [--clock jtag|run] [--div N] [--seed N] [--pnr vpr|python] [--json FILE]
  ./bob build --project bob.proj             (the same settings, in one file)
  ./bob build --project demo/demo.bobproj    (a bob studio project, M18: .bit into demo/build/)
  ./bob load  counter.bit [--watch] [--probe usb|fake]
  ./bob info  counter.bit
  ./bob fasm  counter.bit                     the chain as FASM
  ./bob studio [--probe fake|usb] [--browser] bob studio, as a desktop app (M19)

build runs software/bob/flow.py: every step checked before the next, each one timed and
reported. `--json` writes that record instead of prose.
  1. synthesis   software/bob/synth.py (yosys onto bob cells)
  2. equivalence software/bob/equiv.py: source == yosys netlist == golden netlist in
                 iverilog; saves the source trace and every golden net per clock
  3. place/route --pnr vpr (default): VPR on the committed rr graph (software/bob/vpr_run.py);
                 a fresh committed result in software/bob/vpr/<name>/ is reused (no
                 Docker), otherwise VPR runs in Docker into build/vpr/<name>/.
                 --pnr python (M12): bob's own pack/place/route (software/bob/pnr/),
                 same netlist, pins and output files, into build/pnr/<name>/
  4. FASM        software/bob/fasm_from_vpr.py, legality-checked against device.json
  5. bits        software/bob/bitgen.py; --clock sets the ctrl tile (jtag: stepped over
                 JTAG, as the tests do; run: free-running, 125 MHz / 2**(div+9), or --hz auto|N (M20)
  6. model       software/bob/model.py with these bits == the source trace (when the
                 ports follow the examples' sw/btn/led convention)
  7. .bit        chain + BRAM contents + META (docs/bitstream-format.md section 8)

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


PROJECT_KEYS = ("files", "top", "pcf", "name", "clock", "div", "seed", "pnr", "hz")


def read_project(path):
    """bob.proj -> the keyword arguments build() takes. Paths are relative to the
    project file, so a project can be moved or shared with its sources.

    A .bobproj (M18, bob studio's New Project) is read by software/bob/project.py and also
    names where the .bit goes: <project>/build/<name>.bit."""
    if path.endswith(".bobproj"):
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
    if d.get("pcf"):
        d["pcf"] = os.path.normpath(os.path.join(base, d["pcf"]))
    return d


def result_dir(name, pnr="vpr"):
    """where build() took the place-and-route result from"""
    if pnr == "python":
        return os.path.join(ROOT, "build", "pnr", name)
    stamp = vpr_run.read_stamp(name)
    if stamp is not None and vpr_run.stale(name) is None:
        return os.path.join(vpr_run.RESULTS, name)
    return os.path.join(ROOT, "build", "vpr", name)


def build(files, top=None, pcf=None, out=None, clock="jtag", div=0, seed=1, name=None,
          log=print, pnr="vpr", hz=None):
    """-> (bit path, word, bram contents, board trace or None, result directory)

    The stages live in software/bob/flow.py, which times each one and hands back what it
    measured; this prints those lines and keeps the tuple older callers expect."""
    import flow
    try:
        f = flow.Flow(files, top=top, pcf=pcf, out=out, clock=clock, div=div,
                      seed=seed, name=name, pnr=pnr, hz=hz)
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


def load(p, path, start=True, log=print, mode="frames"):
    """.bit -> configuration memory + BRAM contents -> JSTART.
    mode "frames" (M13 default): UG470-style packets on CFG_IN, STAT, FDRO readback; since
    M15 the BRAM contents travel in the same stream as block-type-1 frames (under the CRC);
    mode "chain": CHAIN_IN with CFG_CTRL CRC, CHAIN_OUT readback, BRAM contents over USER4."""
    import cfgplane
    c = bitgen.read_bit(path)
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
    ok, msg, _n = cfgplane.load_partial(p, c["word"])
    return ok, msg


def main():
    ap = argparse.ArgumentParser(prog="bob", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("files", nargs="*")
    b.add_argument("--top")
    b.add_argument("--pcf")
    b.add_argument("-o", "--output")
    b.add_argument("--clock", default="jtag")
    b.add_argument("--div", type=int, default=0)
    b.add_argument("--hz", help="M20, with --clock run: 'auto' = the fastest rate this design's timing "
                                "allows, or a rate in Hz (refused if faster than that)")
    b.add_argument("--seed", type=int, default=1)
    b.add_argument("--name", help="result name (default top, or top_<pcf>)")
    b.add_argument("--pnr", default="vpr", choices=("vpr", "python"), help="place and route with VPR or bob's own (M12)")
    b.add_argument("--project", help="read files, top, pins and settings from a .proj or .bobproj file")
    b.add_argument("--json", metavar="FILE", help="write the build record (stages, timings, "
                                                  "diagnostics) as JSON; - for stdout")
    ld = sub.add_parser("load")
    ld.add_argument("bit")
    ld.add_argument("--watch", action="store_true", help="show the LEDs afterwards (fpga.py --watch)")
    ld.add_argument("--freq", type=int, default=100, help="TCK kHz (at most 100)")
    ld.add_argument("--probe", default="usb", choices=("usb", "fake"),
                    help="the board: the Pico on PMODA, or the one in software (software/host/fakeboard.py)")
    ld.add_argument("--mode", default="frames", choices=("frames", "chain"),
                    help="configuration path: UG470-style frames on CFG_IN (default) or the chain")
    ld.add_argument("--partial", action="store_true",
                    help="M14: reconfigure the RUNNING design, only the changed frames, user clock held")
    sub.add_parser("info").add_argument("bit")
    sub.add_parser("fasm").add_argument("bit")
    st = sub.add_parser("studio", help="bob studio: the desktop app (or --browser for a tab)")
    st.add_argument("--probe", choices=("usb", "fake"), help="open a target at start (fake: no board)")
    st.add_argument("--browser", action="store_true", help="a browser tab instead of the app window")
    st.add_argument("--port", type=int)
    args = ap.parse_args()

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
            import flow
            kw = dict(files=args.files, top=args.top, pcf=args.pcf, name=args.name,
                      clock=args.clock, div=args.div, seed=args.seed, pnr=args.pnr, hz=args.hz)
            if args.project:
                # the file supplies the defaults; anything given on the command line wins
                given = {k: v for k, v in kw.items()
                         if v not in (None, [], "jtag", 0, 1, "vpr") or k == "files" and v}
                kw = {**{k: v for k, v in kw.items() if k != "files"}, **read_project(args.project)}
                kw.update({k: v for k, v in given.items() if k != "files" and v is not None})
            if not kw.get("files"):
                raise BuildError("no sources: give files, or --project")
            kw["out"] = args.output or kw.get("out")
            print(f"bob build {' '.join(kw['files'])}")
            try:
                f = flow.Flow(**kw)
            except flow.FlowError as e:
                raise BuildError(str(e))
            res = f.run(on_stage=lambda st: print(f"  {st.name:8s} {st.detail}"))
            if args.json:
                text = json.dumps(res.to_json(), indent=2)
                if args.json == "-":
                    print(text)
                else:
                    open(args.json, "w").write(text + "\n")
                    print(f"  json     {os.path.relpath(os.path.abspath(args.json), ROOT)}")
            if not res.ok:
                raise BuildError(res.error)
            return 0
        if args.cmd == "info":
            c = bitgen.read_bit(args.bit)
            F = bitgen.features_from_word(c["word"])
            print(f"{args.bit}: device {c['name']}, {c['width']}-bit chain, crc 0x{c['crc']:08X}, "
                  f"file version {c['version']}, {len(F)} FASM features, "
                  f"BRAM contents {sorted(c['brams']) or 'none'}")
            for k, v in sorted(c["meta"].items()):
                print(f"  {k}: {v}")
            return 0
        if args.cmd == "fasm":
            sys.stdout.write(FV.to_fasm(bitgen.features_from_word(bitgen.read_bit(args.bit)["word"])))
            return 0
        if args.cmd == "load":
            import fpga
            from fakeboard import probe as open_probe
            bitgen.read_bit(args.bit)                                   # refuse before touching hardware
            p = open_probe(args.probe, freq_khz=args.freq)
            idcode = p.read_idcode()
            if idcode != fpga.IDCODE_FABRIC:
                print(f"IDCODE 0x{idcode:08X}, expected 0x{fpga.IDCODE_FABRIC:08X}: program the matching bob bitstream")
                return 1
            ok, msg = load_partial(p, args.bit) if args.partial else load(p, args.bit, mode=args.mode)
            fpga.go_live(p)
            print(f"{'PASS' if ok else 'FAIL'}  load {args.bit}: {msg}")
            if ok and args.watch:
                fpga.watch(p)
            return 0 if ok else 1
    except (BuildError, FV.FasmError, chainbits.ChainFileError, vpr_run.VprError, RuntimeError, OSError) as e:
        print(f"FAIL  {e}")
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
