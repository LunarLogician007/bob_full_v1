#!/usr/bin/env bash
# Regenerate the vectors from the bitstream engine, then run the complete-FPGA testbench.
#   ./run_fabric_sim.sh          run the tests
#   ./run_fabric_sim.sh --wave   run the tests with a VCD, then open it in gtkwave
# Sources come from hw/sources.f - the same list Vivado builds.
# The VCD is opt-in since M4: a 250 MHz simulated sysclk makes it huge and slow.
set -euo pipefail

cd "$(dirname "$0")"
./gen_vectors.py

SRC=(); while read -r l; do SRC+=("$l"); done < <(./hwfiles.sh --sim)

iverilog -g2012 -DSIMULATION -I../hw/src/generated -I../hw/tb -s tb_bob -o tb_bob.vvp \
    "${SRC[@]}" ../hw/tb/tb_bob.v

if [[ "${1:-}" == "--wave" ]]; then
    vvp tb_bob.vvp +wave
    gtkwave tb_bob.vcd >/dev/null 2>&1 &
else
    vvp tb_bob.vvp
fi
