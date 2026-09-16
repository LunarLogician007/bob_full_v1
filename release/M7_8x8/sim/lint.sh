#!/usr/bin/env bash
# Verilator lint of the synthesisable RTL, every board top, from hw/sources.f.
#
# Waived on purpose:
#   PROCASSINIT - the TAPs have no reset pin by design; state/ir/tdo and the
#                 configuration plane rely on power-up INIT values, which is
#                 exactly the FPGA idiom here.
#   UNUSEDPARAM - the instruction opcodes are documentation of the map; the
#                 unused ones fall through to the default (BYPASS) arm.
#   UNOPTFLAT   - the fabric only. A routing graph in which muxes can select each
#                 other has combinational cycles in the netlist BY CONSTRUCTION
#                 (VPR's rr graph has them). Whether a loop really exists depends
#                 on the bitstream, not on the RTL; the router never makes one.
set -euo pipefail
cd "$(dirname "$0")"

SRC=(); while read -r l; do SRC+=("$l"); done < <(./hwfiles.sh)

echo "-- single CLB --"
verilator --lint-only -Wall --timing -I../hw/src/generated \
    -Wno-PROCASSINIT -Wno-UNUSEDPARAM \
    -DSIMULATION --top-module mini_fpga_top "${SRC[@]}"

echo "-- complete FPGA (generated fabric) --"
verilator --lint-only -Wall --timing -I../hw/src/generated \
    -Wno-PROCASSINIT -Wno-UNUSEDPARAM -Wno-UNOPTFLAT --replication-limit 65536 \
    -DSIMULATION --top-module bob_top "${SRC[@]}"

echo "-- M2 configuration plane --"
verilator --lint-only -Wall --timing -I../hw/src/generated \
    -Wno-PROCASSINIT -Wno-UNUSEDPARAM \
    -DSIMULATION --top-module cfg_test_top "${SRC[@]}"

echo "lint clean"
