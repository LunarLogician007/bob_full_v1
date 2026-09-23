#!/usr/bin/env bash
# M4 CLB flag sweep: every combination of the 7 CLB flags x random INITs x
# sequences of LUT inputs, routed CE/SR, gce, GSR and GWE, checked every cycle
# against software/bob/model.py (which generates hw/tb/clb_vectors.vh).
#   ./run_clb_sim.sh
set -euo pipefail
cd "$(dirname "$0")"
./gen_clb_vectors.py
SRC=(); while read -r l; do SRC+=("$l"); done < <(./hwfiles.sh --sim)
iverilog -g2012 -DSIMULATION -I../hw/src/generated -I../hw/tb -s tb_clb -o tb_clb.vvp \
    "${SRC[@]}" ../hw/tb/tb_clb.sv
vvp tb_clb.vvp
