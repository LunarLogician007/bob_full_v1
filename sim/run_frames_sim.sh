#!/usr/bin/env bash
# M13: the frame configuration path (UG470-style packets) on the complete bob FPGA.
#   sim/run_frames_sim.sh
set -euo pipefail
cd "$(dirname "$0")"
./gen_frame_vectors.py
SRC=(); while read -r l; do SRC+=("$l"); done < <(./hwfiles.sh)
iverilog -g2012 -DSIMULATION -I../hw/src/generated -I../hw/tb -s tb_frames -o tb_frames.vvp \
    "${SRC[@]}" ../hw/tb/tb_frames.v
vvp tb_frames.vvp

# the user-clock spacing guard that the M13 timing constraints rely on
iverilog -g2012 -o tb_clock_gap.vvp -s tb_clock_gap ../hw/src/core/clock_ctrl.v ../hw/tb/tb_clock_gap.v
vvp tb_clock_gap.vvp
