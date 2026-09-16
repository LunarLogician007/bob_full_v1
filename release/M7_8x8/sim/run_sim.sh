#!/usr/bin/env bash
# Build and run the mini FPGA testbench with Icarus Verilog.
#   ./run_sim.sh          run the tests
#   ./run_sim.sh --wave   run the tests, then open the VCD in gtkwave
# Sources come from hw/sources.f - the same list Vivado builds.
set -euo pipefail

cd "$(dirname "$0")"
OUT=tb_mini_fpga.vvp

SRC=(); while read -r l; do SRC+=("$l"); done < <(./hwfiles.sh)

iverilog -g2012 -DSIMULATION -I../hw/src/generated -I../hw/tb -s tb_mini_fpga -o "$OUT" \
    "${SRC[@]}" ../hw/tb/tb_mini_fpga.v
vvp "$OUT"

if [[ "${1:-}" == "--wave" ]]; then
    gtkwave tb_mini_fpga.vcd >/dev/null 2>&1 &
fi
