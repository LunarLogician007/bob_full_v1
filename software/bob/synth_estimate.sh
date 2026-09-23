#!/usr/bin/env bash
# yosys synth_xilinx -flatten of bob_top from a checkout ($1): cell counts to $2.stat,
# time and peak memory to $2.time, the last 100 KB of yosys' warnings to $2.err.
# A Vivado-free size/memory estimate before a hand-off (M13: catches logic blow-ups like
# the first frame write). Usage: software/bob/synth_estimate.sh $PWD build/est
# (M21: it used to keep yosys' full log, 1.2 GB a run - build/ reached 8 GB)
set -e
T=$(mktemp -d)
cp -R "$1/hw" "$T/hw"
python3 - "$T/hw" <<'PY'
import sys, re, os
hw = sys.argv[1]
pkg = open(os.path.join(hw, "src/clb/clb_pkg.sv")).read()
body = pkg[pkg.index("package clb_pkg;") + len("package clb_pkg;"):pkg.index("endpackage")]
p = os.path.join(hw, "src/clb/clb.sv")
s = open(p).read().replace("  import clb_pkg::*;\n", "")
s = s.replace("module clb\n", "`include \"bob_params.vh\"\n" + body + "\nmodule clb\n", 1)
open(p, "w").write(s)
PY
cd "$T/hw"
FILES=$(grep -v '^\s*#' sources.f | grep -v '^\s*$' | grep -v clb_pkg.sv | tr '\n' ' ')
( /usr/bin/time -l yosys -q -p "read_verilog -sv -D SYNTHESIS -I src/generated -I src/clb $FILES; hierarchy -top bob_top; synth_xilinx -flatten -top bob_top; tee -q -o $2.stat stat" \
    > /dev/null 2> >(tail -c 100000 > "$2.err") ) 2> "$2.time" || echo "yosys failed" >> "$2.time"
rm -rf "$T"
