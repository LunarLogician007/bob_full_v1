#!/usr/bin/env python3
"""
equiv.py - the synthesised netlist equals its source Verilog (M8), by simulation.

  software/bob/equiv.py work/examples/counter/counter.v [--top counter] [--cycles 300]

Both the source and <top>_syn.v (software/bob/synth.py, simulated with
software/bob/synth/bob_cells_sim.v, whose BRAM/DSP models are the fabric's own
bram_core.v / dsp_core.v) get the same random inputs. Every output is compared
twice per cycle: just before and just after the rising clock edge.

The source run's outputs are also written to <out>/<top>.trace.json: per cycle
[pad_i, LEDs just before the edge, LEDs just after it]. software/bob/place.py (model),
hw/tb/tb_synth.v (fabric RTL) and software/host/hwtest.py (the board) check against it.

Board ports, the convention every example and the placer share:
  clk            the fabric's user clock (optional)
  sw[1:0]        pad_i bits 0..1
  btn[3:0]       pad_i bits 2..5
  led[2:0]       pad_o bits 0..2
"""

import argparse
import json
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import golden  # noqa: E402
import synth  # noqa: E402

SIM_LIBS = [os.path.join(HERE, "synth", "bob_cells_sim.v"),
            os.path.join(ROOT, "hw", "src", "tiles", "bram_core.v"),
            os.path.join(ROOT, "hw", "src", "tiles", "dsp_core.v")]
BOARD_IN = {"sw": 0, "btn": 2}           # port -> first pad_i bit
BOARD_OUT = {"led": 0}


def ports_of(mod):
    return {n: (p["direction"], len(p["bits"])) for n, p in mod["ports"].items()}


def testbench(top, ports, vectors, net_ids=()):
    ins = [(n, w) for n, (d, w) in ports.items() if d == "input" and n != "clk"]
    outs = [(n, w) for n, (d, w) in ports.items() if d == "output"]
    has_clk = "clk" in ports
    L = ["`timescale 1ns/1ps", "module tb;"]
    L.append("  reg clk = 0;")
    for n, w in ins:
        L.append(f"  reg [{w-1}:0] {n} = 0;")
    for n, w in outs:
        L.append(f"  wire [{w-1}:0] r_{n}, s_{n}, g_{n};")
    conn = lambda pre: ", ".join([".clk(clk)"] if has_clk else [] +          # noqa: E731
                                 [f".{n}({n})" for n, _ in ins] + [f".{n}({pre}{n})" for n, _ in outs])
    conn_r = ", ".join(([".clk(clk)"] if has_clk else []) + [f".{n}({n})" for n, _ in ins]
                       + [f".{n}(r_{n})" for n, _ in outs])
    conn_s = ", ".join(([".clk(clk)"] if has_clk else []) + [f".{n}({n})" for n, _ in ins]
                       + [f".{n}(s_{n})" for n, _ in outs])
    L.append(f"  {top} u_source ({conn_r});")          # not 'ref': a SystemVerilog keyword
    L.append(f"  {top}_syn u_netlist ({conn_s});")
    conn_g = ", ".join(([".clk(clk)"] if has_clk else []) + [f".{n}({n})" for n, _ in ins]
                       + [f".{n}(g_{n})" for n, _ in outs])
    L.append(f"  {top}_golden u_golden ({conn_g});")
    gnets = "{" + ", ".join(f"u_golden.n{b}" for b in reversed(net_ids)) + "}" if net_ids else "1'b0"
    L.append("  integer errors = 0;")
    L.append("  integer fh;")
    L.append("  reg [63:0] bef, aft;")
    rcat = "{" + ", ".join(f"r_{n}" for n, _ in reversed(outs)) + "}" if outs else "1'b0"
    scat = "{" + ", ".join(f"s_{n}" for n, _ in reversed(outs)) + "}" if outs else "1'b0"
    gcat = "{" + ", ".join(f"g_{n}" for n, _ in reversed(outs)) + "}" if outs else "1'b0"
    L.append("  task cmp(input integer c, input integer phase);")
    L.append(f"    if ({rcat} !== {scat} || {rcat} !== {gcat}) begin errors = errors + 1;")
    L.append(f'      if (errors < 10) $display("MISMATCH cycle %0d phase %0d: source %h netlist %h golden %h", '
             f'c, phase, {rcat}, {scat}, {gcat}); end')
    L.append("  endtask")
    L.append("  initial begin")
    L.append('    fh = $fopen("trace.txt", "w");')
    for c, v in enumerate(vectors):
        assigns = " ".join(f"{n} = {w}'h{(v[n]) & ((1 << w) - 1):x};" for n, w in ins)
        edge = (f" clk = 1; #1 cmp({c}, 1); aft = {rcat}; #4 clk = 0;" if has_clk
                else f" #1 aft = {rcat}; #4;")
        L.append(f"    {assigns} #4 cmp({c}, 0); bef = {rcat};{edge}"
                 f" $fwrite(fh, \"%0d %h %h %h\\n\", {c}, bef, aft, {gnets});")
    L.append('    $fclose(fh);')
    L.append('    if (errors == 0) $display("EQUIV_OK"); else $display("EQUIV_FAIL %0d", errors);')
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def random_vectors(ports, cycles, seed):
    """Biased random vectors in 50-cycle segments; each input bit is 1 with a
    probability of 1/64, 1/2 or 63/64 for the whole segment. Uniform bits never let
    a counter with a synchronous reset on an input count far (the M8 counter trace
    was all zeros), so the first two segments are fixed: every other bit (in port
    order) mostly 1 and the rest mostly 0, then the reverse. Later segments pick
    at random."""
    rng = random.Random(seed)
    ins = [(n, w) for n, (d, w) in ports.items() if d == "input" and n != "clk"]
    bits = [(n, k) for n, w in ins for k in range(w)]
    out = []
    for c in range(cycles):
        seg = c // 50
        if c % 50 == 0:
            if seg < 2:
                p = {nk: 63 if (i + seg) % 2 == 0 else 1 for i, nk in enumerate(bits)}
            else:
                p = {nk: rng.choice((1, 32, 63)) for nk in bits}
        out.append({n: sum((rng.randrange(64) < p[(n, k)]) << k for k in range(w)) for n, w in ins})
    return out


def board_vector(v):
    """{sw: .., btn: ..} -> pad_i int (the model's and the hardware's input vector)."""
    x = 0
    for name, lo in BOARD_IN.items():
        x |= v.get(name, 0) << lo
    return x


def equiv(files, top, out=None, cycles=300, seed=1):
    out = out or os.path.join(ROOT, "build", "synth", top)
    mod = synth.synth(files, top, out)
    ports = ports_of(mod)
    vectors = random_vectors(ports, cycles, seed)
    net_ids = golden.nets(mod)
    open(os.path.join(out, f"{top}_golden.v"), "w").write(golden.write(mod, top))
    syn = open(os.path.join(out, f"{top}_syn.v")).read()
    syn = re.sub(rf"\bmodule\s+{re.escape(top)}\b", f"module {top}_syn", syn, count=1)
    # BRAM INIT arrives as an 18432-digit binary literal with x for unset words: too
    # long for iverilog's scanner. Rewrite long literals as hex; x reads 0, as the
    # fabric's never-written BRAM words do.
    syn = re.sub(r"(\d+)'b([01x]{64,})",
                 lambda m: f"{m.group(1)}'h{int(m.group(2).replace('x', '0'), 2):x}", syn)
    open(os.path.join(out, f"{top}_syn_renamed.v"), "w").write(syn)
    tb = os.path.join(out, "tb_equiv.v")
    open(tb, "w").write(testbench(top, ports, vectors, net_ids))
    vvp = os.path.join(out, "tb_equiv.vvp")
    r = subprocess.run(["iverilog", "-g2012", "-o", vvp, "-s", "tb", *[os.path.abspath(f) for f in files],
                        os.path.join(out, f"{top}_syn_renamed.v"), os.path.join(out, f"{top}_golden.v"),
                        *SIM_LIBS, tb],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"iverilog failed:\n{r.stderr[-2000:]}")
    r = subprocess.run(["vvp", vvp], capture_output=True, text=True, cwd=out)
    ok = "EQUIV_OK" in r.stdout
    trace, nets_after = [], []
    for line, v in zip(open(os.path.join(out, "trace.txt")).read().split("\n"), vectors):
        c, bef, aft, gn = line.split()
        trace.append((board_vector(v), int(bef, 16), int(aft, 16)))   # inputs, before edge, after edge
        nets_after.append(gn)                                           # golden n<bit>s after the edge, hex
    json.dump({"top": top, "has_clk": "clk" in ports, "trace": trace,
               "nets": net_ids, "nets_after": nets_after},
              open(os.path.join(out, f"{top}.trace.json"), "w"))
    return ok, r.stdout.strip().splitlines()[-10:], mod


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--top")
    ap.add_argument("--cycles", type=int, default=300)
    args = ap.parse_args()
    top = args.top or os.path.splitext(os.path.basename(args.files[0]))[0]
    try:
        ok, lines, mod = equiv(args.files, top, cycles=args.cycles)
    except RuntimeError as e:
        print(f"FAIL  {top}: {e}")
        return 1
    print(f"{'PASS' if ok else 'FAIL'}  {top}: netlist {synth.summary(mod)} "
          f"{'== source over' if ok else '!= source,'} {args.cycles} random cycles")
    if not ok:
        print("\n".join("      " + ln for ln in lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
