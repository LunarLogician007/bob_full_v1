#!/usr/bin/env bash
# M5: bram_core.v against software/bob/model.py, every write mode x output register.
#   ./run_bram_sim.sh
set -euo pipefail
cd "$(dirname "$0")"
./gen_bram_vectors.py
iverilog -g2012 -DSIMULATION -I../hw/src/generated -I../hw/tb -s tb_bram -o tb_bram.vvp \
    ../hw/src/tiles/bram_core.v ../hw/tb/tb_bram.v
vvp tb_bram.vvp
