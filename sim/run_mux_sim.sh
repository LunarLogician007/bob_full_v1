#!/usr/bin/env bash
# M23 routing mux: hw/src/fabric/bob_mux.v (LUT6/MUXF7/MUXF8 primitives) against the
# behavioural table it replaced, every width up to 40 inputs (sim/gen_mux_tb.py). tb_bob only
# meets this fabric's muxes (at most 14 values), so the wide branch is checked here.
#   ./run_mux_sim.sh [bob_mux.v [outdir]]    (the mutation script passes a mutated copy and
#                                            its own folder: mutants run in parallel)
set -euo pipefail
cd "$(dirname "$0")"
MUX=${1:-../hw/src/fabric/bob_mux.v}
OUT=${2:-../build/mux}
mkdir -p "$OUT"
./gen_mux_tb.py "$OUT/tb_mux.v"
iverilog -g2012 -s tb_mux -o "$OUT/tb_mux.vvp" "$OUT/tb_mux.v" "$MUX" \
    ../hw/tb/prims/LUT6.v ../hw/tb/prims/MUXF7.v ../hw/tb/prims/MUXF8.v
vvp -n "$OUT/tb_mux.vvp" | tee "$OUT/tb_mux.log"
grep -q "ALL TESTS PASSED" "$OUT/tb_mux.log"
