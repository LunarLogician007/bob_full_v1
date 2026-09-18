#!/usr/bin/env bash
# yosys synth_xilinx -flatten of bob_top from a checkout ($1); log/time to $2.{log,time}
# A Vivado-free size/memory estimate before a hand-off (M13: catches logic blow-ups like
# the first frame write). Usage: software/bob/synth_estimate.sh $PWD build/est
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
/usr/bin/time -l yosys -q -l "$2.log" -p "read_verilog -sv -D SYNTHESIS -I src/generated -I src/clb $FILES; hierarchy -top bob_top; synth_xilinx -flatten -top bob_top; stat" > "$2.time" 2>&1 || echo "yosys failed" >> "$2.time"
rm -rf "$T"
