#!/usr/bin/env bash
# M10 golden co-simulation: every example's source Verilog, its golden netlist and
# the complete bob FPGA RTL loaded from the design's .bit, on the same inputs.
#   sim/run_cosim_sim.sh [--cycles N]
set -euo pipefail
cd "$(dirname "$0")"
./gen_cosim.py "$@"

SRC=(); while read -r l; do SRC+=("$l"); done < <(./hwfiles.sh --sim)
EX=(); while read -r l; do EX+=("$l"); done < ../build/cosim/sources.txt

iverilog -g2012 -DSIMULATION -I../hw/src/generated -I../hw/tb -I../build/cosim -s tb_cosim \
    -o ../build/cosim/tb_cosim.vvp "${SRC[@]}" ../software/bob/synth/bob_cells_sim.v "${EX[@]}" tb_cosim.v
vvp ../build/cosim/tb_cosim.vvp
