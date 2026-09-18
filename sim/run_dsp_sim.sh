#!/usr/bin/env bash
# M6: two cascaded dsp_core.v slices against software/bob/model.py.
#   ./run_dsp_sim.sh
set -euo pipefail
cd "$(dirname "$0")"
./gen_dsp_vectors.py
iverilog -g2012 -DSIMULATION -I../hw/tb -s tb_dsp -o tb_dsp.vvp \
    ../hw/src/tiles/dsp_core.v ../hw/tb/tb_dsp.v
vvp tb_dsp.vvp
