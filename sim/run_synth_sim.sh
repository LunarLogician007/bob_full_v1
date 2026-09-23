#!/usr/bin/env bash
# M8: synthesise every example (yosys), prove the netlist equals the source, place
# and route it, then run it on the complete bob FPGA RTL against the source trace.
#   ./run_synth_sim.sh
set -euo pipefail
cd "$(dirname "$0")"
./gen_synth_vectors.py

SRC=(); while read -r l; do SRC+=("$l"); done < <(./hwfiles.sh --sim)

iverilog -g2012 -DSIMULATION -I../hw/src/generated -I../hw/tb -s tb_synth -o tb_synth.vvp \
    "${SRC[@]}" ../hw/tb/tb_synth.v
vvp tb_synth.vvp
