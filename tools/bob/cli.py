#!/usr/bin/env python3
"""
bob - build a Verilog design for the bob FPGA and load it (M10).

  ./bob build examples/counter.v [--top counter] [--pcf pins.pcf] [-o counter.bit]
              [--clock jtag|run] [--div N] [--seed N] [--pnr vpr|python]
  ./bob load  counter.bit [--watch]          (Pico on PMODA, M7 bitstream in the PL)
  ./bob info  counter.bit
  ./bob fasm  counter.bit                     the chain as FASM

build, every step checked before the next:
  1. synthesis   tools/bob/synth.py (yosys onto bob cells)
  2. equivalence tools/bob/equiv.py: source == yosys netlist == golden netlist in
                 iverilog; saves the source trace and every golden net per clock
  3. place/route --pnr vpr (default): VPR on the committed rr graph (tools/bob/vpr_run.py);
                 a fresh committed result in tools/bob/vpr/<name>/ is reused (no
                 Docker), otherwise VPR runs in Docker into build/vpr/<name>/.
                 --pnr python (M12): bob's own pack/place/route (tools/bob/pnr/),
                 same netlist, pins and output files, into build/pnr/<name>/
  4. FASM        tools/bob/fasm_from_vpr.py, legality-checked against device.json
  5. bits        tools/bob/bitgen.py; --clock sets the ctrl tile (jtag: stepped over
                 JTAG, as the tests do; run: free-running, 125 MHz / 2**(div+8))
  6. model       tools/bob/model.py with these bits == the source trace (when the
                 ports follow the examples' sw/btn/led convention)
  7. .bit        chain + BRAM contents + META (docs/bitstream-format.md section 8)

Pins: without --pcf, sw[1:0] -> SW1..0, btn[3:0] -> BTN3..0, led[2:0] -> LD2..0.
A .pcf has `set_io <port bit> <SW0|SW1|BTN0..3|LD0..2|pad<N>>` lines.
"""

import argparse
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "host"))

import bitstream as B  # noqa: E402
import bitgen  # noqa: E402
import chainbits  # noqa: E402
import fasm_from_vpr as FV  # noqa: E402
import vpr_run  # noqa: E402

CONVENTION = {"clk", "sw", "btn", "led"}


class BuildError(Exception):
    pass


def result_dir(name, pnr="vpr"):
    """where build() took the place-and-route result from"""
    if pnr == "python":
        return os.path.join(ROOT, "build", "pnr", name)
    stamp = vpr_run.read_stamp(name)
    if stamp is not None and vpr_run.stale(name) is None:
        return os.path.join(vpr_run.RESULTS, name)
    return os.path.join(ROOT, "build", "vpr", name)


def build(files, top=None, pcf=None, out=None, clock="jtag", div=0, seed=1, name=None, log=print, pnr="vpr"):
    """-> (bit path, word, bram contents, board trace or None, result directory)"""
    import equiv
    top = top or os.path.splitext(os.path.basename(files[0]))[0]
    if not name and pcf:
        base = os.path.splitext(os.path.basename(pcf))[0]
        name = base if base.startswith(top) else f"{top}_{base}"
    name = name or top
    if name in vpr_run.VARIANTS and pcf is None:
        top_v, pcf = vpr_run.VARIANTS[name]
        if top_v != top:
            raise BuildError(f"{name} is a committed variant of {top_v}, not {top}")

    ok, lines, mod = equiv.equiv(files, top)
    if not ok:
        raise BuildError(f"{top}: synthesised netlist differs from the source:\n" + "\n".join(lines))
    from synth import summary
    log(f"  synth    {top}: {summary(mod)}; source == netlist == golden, 300 random cycles")

    stamp = vpr_run.read_stamp(name)
    same_pins = stamp is not None and stamp.get("pcf", "-") == (os.path.relpath(os.path.abspath(pcf), ROOT)
                                                               if pcf else "-")
    pnr_stats = None
    if pnr == "python":
        from pnr import pack as pnr_pack, place as pnr_place, route as pnr_route, run as pnr_run
        try:
            work, pnr_stats = pnr_run.run(top, seed, pcf, name)
        except (vpr_run.VprError, pnr_pack.PackError, pnr_place.PlaceError, pnr_route.RouteError) as e:
            raise BuildError(f"python pnr: {e}")
        log(f"  pnr      python: {pnr_stats['clusters']['clb']} CLBs, wirelength {pnr_stats['wirelength']}, "
            f"{pnr_stats['iterations']} routing iteration(s), "
            f"{pnr_stats['pack_s'] + pnr_stats['place_s'] + pnr_stats['route_s']:.2f} s -> {os.path.relpath(work, ROOT)}")
    elif pnr != "vpr":
        raise BuildError("--pnr is vpr or python")
    elif same_pins and vpr_run.stale(name) is None:
        work = os.path.join(vpr_run.RESULTS, name)
        log(f"  vpr      reused committed {os.path.relpath(work, ROOT)} (routed from this netlist and arch)")
    else:
        try:
            work = vpr_run.run(top, seed, pcf=pcf, name=name)
        except vpr_run.VprError as e:
            raise BuildError(str(e))
        s = vpr_run.summary(work, name)
        log(f"  vpr      routed in Docker: wirelength {s['wirelength']}, result {s['result_sha']} "
            f"-> {os.path.relpath(work, ROOT)}")

    bs, contents, text = FV.build(name, work)
    F = bitgen.parse_fasm(text)
    if clock not in B.CLOCK_MODES:
        raise BuildError(f"--clock is one of {sorted(B.CLOCK_MODES)}")
    F.pop("ctrl.clk_mode", None)
    F.pop("ctrl.clk_div", None)
    if B.CLOCK_MODES[clock]:
        F["ctrl.clk_mode"] = B.CLOCK_MODES[clock]
    if div:
        F["ctrl.clk_div"] = div
    word = bitgen.word_from_features(F)
    if clock == "run":
        hz = 125e6 / 2 ** (div + B.DIV_MIN_SHIFT)
        log(f"  clock    free-running: 125 MHz / 2^{div + B.DIV_MIN_SHIFT} = {hz:.4g} Hz "
            f"(one user clock every {1 / hz:.3g} s)")
    log(f"  fasm     {len(F)} features, legal against device.json; bits -> FASM -> bits identical: "
        f"{bitgen.word_from_features(bitgen.features_from_word(word)) == word}")

    tr = None
    if set(mod["ports"]) <= CONVENTION:
        bad, n, tr = FV.check_model(name, bs, contents, work, top)     # routed chain, jtag clock
        if bad:
            raise BuildError(f"model.py differs from the source trace in {len(bad)} of {2 * n} samples")
        log(f"  model    {2 * n}/{2 * n} samples == source trace")
    else:
        log("  model    skipped: ports outside the sw/btn/led convention")

    out = out or os.path.join(ROOT, "build", "bit", f"{name}.bit")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    stampd = vpr_run.read_stamp(name) if work.startswith(vpr_run.RESULTS) else {}
    meta = {"design": name, "top": top,
            "sources": [os.path.relpath(os.path.abspath(f), ROOT) for f in files],
            "source_sha256": hashlib.sha256(b"".join(open(f, "rb").read() for f in files)).hexdigest(),
            "pcf": os.path.relpath(os.path.abspath(pcf), ROOT) if pcf else None,
            "pnr": pnr,
            "vpr_result": (None if pnr == "python" else
                           stampd.get("result_sha") or vpr_run.summary(work, name)["result_sha"]),
            "pnr_seed": pnr_stats["seed"] if pnr_stats else None,
            "clock": clock, "div": div}
    bitgen.write_bit(out, word, contents, meta)
    log(f"  bit      {os.path.relpath(os.path.abspath(out), ROOT)}: {B.CHAIN_W}-bit chain"
        + (f", BRAM {sorted(b for b, w in contents.items() if any(w))}" if any(map(any, contents.values())) else ""))
    return out, word, contents, tr, work


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
    """.bit -> configuration memory -> BRAM contents over USER4 -> JSTART.
    mode "frames" (M13 default): UG470-style packets on CFG_IN, STAT, FDRO readback;
    mode "chain": CHAIN_IN with CFG_CTRL CRC, CHAIN_OUT readback."""
    import cfgplane
    c = bitgen.read_bit(path)
    if mode == "frames":
        ok, msg = cfgplane.load_frames(p, c["word"], start=False)
    elif mode == "chain":
        ok, msg = cfgplane.load(p, c["word"], B.CHAIN_W, start=False)
    else:
        return False, f"mode is frames or chain, not {mode}"
    if not ok:
        return False, msg
    msg += write_brams(p, c["brams"])
    if start:
        cfgplane.jstart(p)
        st = cfgplane.status(p)
        if not st["done"]:
            return False, f"{msg}; DONE did not rise: {st}"
        msg += ", DONE"
    return True, msg


def main():
    ap = argparse.ArgumentParser(prog="bob", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("files", nargs="+")
    b.add_argument("--top")
    b.add_argument("--pcf")
    b.add_argument("-o", "--output")
    b.add_argument("--clock", default="jtag")
    b.add_argument("--div", type=int, default=0)
    b.add_argument("--seed", type=int, default=1)
    b.add_argument("--name", help="result name (default top, or top_<pcf>)")
    b.add_argument("--pnr", default="vpr", choices=("vpr", "python"), help="place and route with VPR or bob's own (M12)")
    ld = sub.add_parser("load")
    ld.add_argument("bit")
    ld.add_argument("--watch", action="store_true", help="show the LEDs afterwards (fpga.py --watch)")
    ld.add_argument("--freq", type=int, default=100, help="TCK kHz (at most 100)")
    ld.add_argument("--mode", default="frames", choices=("frames", "chain"),
                    help="configuration path: UG470-style frames on CFG_IN (default) or the chain")
    sub.add_parser("info").add_argument("bit")
    sub.add_parser("fasm").add_argument("bit")
    args = ap.parse_args()

    try:
        if args.cmd == "build":
            print(f"bob build {' '.join(args.files)}")
            build(args.files, args.top, args.pcf, args.output, args.clock, args.div, args.seed, args.name,
                  pnr=args.pnr)
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
            from dirtyjtag import Probe
            bitgen.read_bit(args.bit)                                   # refuse before touching hardware
            p = Probe(freq_khz=args.freq)
            idcode = p.read_idcode()
            if idcode != fpga.IDCODE_FABRIC:
                print(f"IDCODE 0x{idcode:08X}, expected 0x{fpga.IDCODE_FABRIC:08X}: program the M7 bitstream")
                return 1
            ok, msg = load(p, args.bit, mode=args.mode)
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
