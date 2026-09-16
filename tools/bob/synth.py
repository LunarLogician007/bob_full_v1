#!/usr/bin/env python3
"""
synth.py - yosys synthesis of a Verilog design onto the bob cell library (M8).

  tools/bob/synth.py examples/counter.v [more.v ...] [--top counter] [--out DIR]

The script is yosys' synth_xilinx flow (`yosys -p "help synth_xilinx"`) with
bob's cells substituted (tools/bob/synth/):

  prepare     proc, flatten, opt, fsm, wreduce, peepopt
  map_dsp     mul2dsp.v at 25 x 18 signed  -> BOB_DSP        (bob_map.v)
  coarse      cmp2lut/cmp2lcu, alumacc, share, memory -nomap
  map_memory  memory_libmap bob_brams.txt -> BOB_BRAM18     (bob_brams_map.v)
  fine        techmap: $alu -> BOB_ADD (one CLB per bit)    (bob_map.v)
  map_ffs     dfflegalize $_SDFFE_PP0P_/PP1P_, init = reset -> BOB_FDRE/BOB_FDSE
  map_luts    abc -lut K (K from tools/bob/device.json)

Outputs in DIR (default build/synth/<top>):
  <top>.json     the netlist the placer reads (tools/bob/place.py)
  <top>.blif     BLIF for VPR (M9): $lut as .names, bob cells as .subckt
  <top>_syn.v    the netlist with $lut as BOB_LUT, for equivalence simulation
  <top>.stat     yosys stat

Fails if anything other than bob cells remains, or if the design has more than
one clock (the fabric has one user clock).
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LIB = os.path.join(HERE, "synth")
CELLS = {"$lut", "BOB_FDRE", "BOB_FDSE", "BOB_ADD", "BOB_BRAM18", "BOB_DSP"}
SEQ_CLOCK = {"BOB_FDRE": "C", "BOB_FDSE": "C", "BOB_BRAM18": "CLK"}

SCRIPT = r"""
read_verilog -lib {lib}/bob_cells_sim.v
{reads}
hierarchy -check -top {top}
proc
flatten
tribuf -logic
deminout
opt_expr
opt_clean
check
opt -nodffe -nosdff
fsm
opt
wreduce
peepopt
opt_clean
memory_dff
techmap -map +/mul2dsp.v -map {lib}/bob_map.v -D DSP_A_MAXWIDTH=25 -D DSP_B_MAXWIDTH=18 -D DSP_A_MINWIDTH=2 -D DSP_B_MINWIDTH=2 -D DSP_SIGNEDONLY -D DSP_NAME=$__MUL25X18
select a:mul2dsp
setattr -unset mul2dsp
opt_expr -fine
wreduce
select -clear
chtype -set $mul t:$__soft_mul
techmap -map +/cmp2lut.v -map +/cmp2lcu.v -D LUT_WIDTH={k}
alumacc
share
opt
memory -nomap
opt_clean
memory_libmap -lib {lib}/bob_brams.txt
techmap -map {lib}/bob_brams_map.v
opt -fast -full
memory_map
opt -full
techmap -map +/techmap.v -map {lib}/bob_map.v
opt -fast
dfflegalize -cell $_SDFFE_PP0P_ r -cell $_SDFFE_PP1P_ r
techmap -map {lib}/bob_map.v
opt_expr -mux_undef
abc -lut {k}
opt_clean -purge
hierarchy -check
check
tee -o {out}/{top}.stat stat
write_json {out}/{top}.json
write_blif -param -cname {out}/{top}.blif
techmap -map {lib}/bob_lut_map.v
write_verilog -noattr {out}/{top}_syn.v
"""


def lut_k():
    dj = os.environ.get("BOB_DEVICE_JSON") or os.path.join(HERE, "device.json")
    return json.load(open(dj))["lut_k"]


def synth(files, top, out, quiet=True):
    os.makedirs(out, exist_ok=True)
    reads = "\n".join(f"read_verilog -sv {os.path.abspath(f)}" for f in files)
    script = SCRIPT.format(lib=LIB, reads=reads, top=top, out=out, k=lut_k())
    ys = os.path.join(out, f"{top}.ys")
    open(ys, "w").write(script)
    log = os.path.join(out, f"{top}.log")
    r = subprocess.run(["yosys", "-q", "-l", log, "-s", ys], capture_output=True, text=True)
    if r.returncode != 0:
        tail = open(log).read().splitlines()[-15:] if os.path.exists(log) else [r.stderr]
        raise RuntimeError(f"yosys failed on {top}:\n" + "\n".join(tail))
    return check(out, top)


def check(out, top):
    """Only bob cells, one clock. Returns the parsed netlist module."""
    nl = json.load(open(os.path.join(out, f"{top}.json")))
    mod = nl["modules"][top]
    bad = sorted({c["type"] for c in mod["cells"].values()} - CELLS)
    if bad:
        raise RuntimeError(f"{top}: cells outside the bob library remain: {bad}")
    clocks = {tuple(c["connections"][SEQ_CLOCK[c["type"]]]) for c in mod["cells"].values()
              if c["type"] in SEQ_CLOCK}
    if len(clocks) > 1:
        raise RuntimeError(f"{top}: {len(clocks)} clocks; the fabric has one user clock")
    return mod


def summary(mod):
    count = {}
    for c in mod["cells"].values():
        count[c["type"]] = count.get(c["type"], 0) + 1
    return count


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--top")
    ap.add_argument("--out")
    args = ap.parse_args()
    top = args.top or os.path.splitext(os.path.basename(args.files[0]))[0]
    out = os.path.abspath(args.out or os.path.join(ROOT, "build", "synth", top))
    try:
        mod = synth(args.files, top, out)
    except RuntimeError as e:
        print(f"FAIL  {e}")
        return 1
    print(f"{top}: {summary(mod)}  ->  {os.path.relpath(out, ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
