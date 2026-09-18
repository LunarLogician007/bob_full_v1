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

# The user-clock spacing guard the sysclk multicycle rests on. Run it twice: at a
# short gap, which is quick, and at the number the board and the XDC actually use
# (BOB_GCE_MIN_GAP_SHIFT), which nothing simulated before M16 - the gap is what makes
# the timing exception true, so the board's value is the one that has to hold.
BOARD_GAP=$(sed -n 's/^`define[[:space:]]*BOB_GCE_MIN_GAP_SHIFT[[:space:]]*\([0-9]*\).*/\1/p' \
            ../hw/src/generated/bob_params.vh)
for gap in 4 "${BOARD_GAP:-9}"; do
    iverilog -g2012 -DTB_GAP="$gap" -o tb_clock_gap.vvp -s tb_clock_gap \
        ../hw/src/core/clock_ctrl.v ../hw/tb/tb_clock_gap.v
    vvp tb_clock_gap.vvp
done
