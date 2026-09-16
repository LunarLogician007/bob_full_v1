#!/usr/bin/env bash
# Build bob's routing-resource graphs with VPR (OpenFPGA's Docker image).
#
#   tools/bob/vpr_rrgraph.sh          (make rrgraph runs this between two device.py calls)
#
# For each LUT size: VPR loads tools/bob/arch/bob_k<K>.xml, packs, places and
# routes the trivial and2.blif at the fixed channel width, and writes the rr
# graph it routed on. Outputs, committed so nothing else needs Docker:
#   tools/bob/arch/bob_k<K>_rr.xml.gz     the graph the fabric RTL is generated from
#   tools/bob/arch/bob_k<K>_rr.stamp      sha256 of the arch it came from, image, command
#   tools/bob/arch/bob_k<K>_vpr.txt       the tail of VPR's log (route result)
set -euo pipefail
cd "$(dirname "$0")/arch"

IMAGE=ghcr.io/lnis-uofu/openfpga-master:latest
VPR=/opt/openfpga/build/vtr-verilog-to-routing/vpr/vpr
WORK=$(cd .. && pwd)/../../build/vpr
mkdir -p "$WORK"
WORK=$(cd "$WORK" && pwd)
DIGEST=$(docker image inspect --format '{{index .RepoDigests 0}}' "$IMAGE" 2>/dev/null || echo "$IMAGE")

for K in 6 4; do
    ARCH=bob_k$K.xml
    [[ -f $ARCH ]] || { echo "missing $ARCH: run tools/bob/device.py --arch-only"; exit 1; }
    W=$(sed -n 's/.*chan_width="\([0-9]*\)".*/\1/p' "$ARCH" | head -1)
    NAME=$(sed -n 's/.*fixed_layout name="\([^"]*\)".*/\1/p' "$ARCH" | head -1)
    rm -rf "$WORK/k$K" && mkdir -p "$WORK/k$K"
    cp "$ARCH" and2.blif "$WORK/k$K/"
    CMD="vpr $ARCH and2.blif --device $NAME --route_chan_width $W --timing_analysis off --write_rr_graph rr.xml"
    echo "== K=$K: $CMD"
    docker run --rm -u root --platform linux/amd64 -v "$WORK/k$K":/w -w /w "$IMAGE" \
        bash -c "$VPR ${CMD#vpr } > vpr.log 2>&1; echo exit=\$?" | tail -1
    if ! grep -q "Circuit successfully routed" "$WORK/k$K/vpr.log"; then
        grep -m5 -i "error" "$WORK/k$K/vpr.log" || tail -20 "$WORK/k$K/vpr.log"
        echo "VPR did not route and2 on $ARCH"; exit 1
    fi
    gzip -9 -n -c "$WORK/k$K/rr.xml" > bob_k${K}_rr.xml.gz
    grep -E "Circuit successfully routed|Final routing|Total wirelength|FPGA sized|Warning|Error" \
        "$WORK/k$K/vpr.log" | head -40 > bob_k${K}_vpr.txt || true
    tail -5 "$WORK/k$K/vpr.log" >> bob_k${K}_vpr.txt
    {
        echo "arch_sha256 $(shasum -a 256 "$ARCH" | cut -d' ' -f1)"
        echo "image $DIGEST"
        echo "command $CMD"
    } > bob_k${K}_rr.stamp
    echo "   routed; wrote bob_k${K}_rr.xml.gz ($(wc -c < bob_k${K}_rr.xml.gz) bytes)"
done
