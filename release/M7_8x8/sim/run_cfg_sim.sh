#!/usr/bin/env bash
# M2 configuration-plane testbench: regenerate CRC vectors from chainbits.py,
# then run tb_cfg against cfg_test_top.
#   ./run_cfg_sim.sh          run the tests
#   ./run_cfg_sim.sh --wave   run the tests, then open the VCD in gtkwave
# Sources come from hw/sources.f - the same list Vivado builds.
set -euo pipefail

cd "$(dirname "$0")"
./gen_cfg_vectors.py

SRC=(); while read -r l; do SRC+=("$l"); done < <(./hwfiles.sh)

iverilog -g2012 -DSIMULATION -I../hw/src/generated -I../hw/tb -s tb_cfg -o tb_cfg.vvp \
    "${SRC[@]}" ../hw/tb/tb_cfg.v
vvp tb_cfg.vvp

if [[ "${1:-}" == "--wave" ]]; then
    gtkwave tb_cfg.vcd >/dev/null 2>&1 &
fi
