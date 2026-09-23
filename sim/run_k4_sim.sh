#!/usr/bin/env bash
# The same RTL and the same testbenches at LUT K=4 - proof that the LUT size is
# really one parameter (M4). The committed build stays K=6.
#
# A K=4 device.json, bob_params.vh and bob_fabric.v (generated from the K=4 rr
# graph, software/bob/arch/bob_k4_rr.xml.gz) are written into a temp directory, the
# vectors are regenerated from them, that directory is put FIRST on the include
# path, and its bob_fabric.v replaces the committed one in the source list.
#   ./run_k4_sim.sh
set -euo pipefail
cd "$(dirname "$0")"

K4=$(mktemp -d)
trap 'rm -rf "$K4"' EXIT
../software/bob/device.py --lut-k 4 --out "$K4" >/dev/null
export BOB_DEVICE_JSON="$K4/device.json"
./gen_clb_vectors.py --out "$K4/clb_vectors.vh"
./gen_vectors.py --out "$K4/vectors.vh"

SRC=()
while read -r l; do
    if [[ "$l" == */generated/bob_fabric.v ]]; then SRC+=("$K4/bob_fabric.v"); else SRC+=("$l"); fi
done < <(./hwfiles.sh --sim)

echo "-- K=4 CLB flag sweep --"
iverilog -g2012 -DSIMULATION -I"$K4" -I../hw/src/generated -I../hw/tb -s tb_clb \
    -o "$K4/tb_clb.vvp" "${SRC[@]}" ../hw/tb/tb_clb.sv
(cd "$K4" && vvp tb_clb.vvp) | grep -E 'FAIL|checks|ALL TESTS|==='

echo "-- K=4 complete FPGA --"
iverilog -g2012 -DSIMULATION -I"$K4" -I../hw/src/generated -I../hw/tb -s tb_bob \
    -o "$K4/tb_bob.vvp" "${SRC[@]}" ../hw/tb/tb_bob.v
(cd "$K4" && vvp tb_bob.vvp) | grep -E 'FAIL|===|checks|config chain|skipped'
