"""
M4: hw/src/clb/lutk.sv at K=6 is the same function as the hardware-proven
lut6.sv (kept in docs/reference/), and at K=4 matches a Python reference.
"""

import os
import random
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LUTK = os.path.join(ROOT, "hw", "src", "clb", "lutk.sv")
LUT6 = os.path.join(ROOT, "docs", "reference", "lut6.sv")

pytestmark = pytest.mark.skipif(shutil.which("iverilog") is None, reason="needs iverilog")


def _run(tmp_path, body, extra=()):
    tb = tmp_path / "t.sv"
    tb.write_text(body)
    out = tmp_path / "t.vvp"
    subprocess.run(["iverilog", "-g2012", "-o", str(out), LUTK, *extra, str(tb)],
                   check=True, capture_output=True, text=True)
    return subprocess.run(["vvp", str(out)], capture_output=True, text=True).stdout


def test_lutk6_equals_lut6(tmp_path):
    rng = random.Random(6)
    lines = []
    for _ in range(3000):
        lines.append(f"    init = 64'h{rng.getrandbits(64):016x}; i = 6'd{rng.randrange(64)}; #1 cmp;")
    body = (
        "module t; reg [63:0] init; reg [5:0] i; wire a6, a5, b6, b5; integer bad = 0;\n"
        "  lutk #(.K(6)) dut (.init(init), .i(i), .o6(a6), .o5(a5));\n"
        "  lut6 golden (.init(init), .i(i), .o6(b6), .o5(b5));\n"
        "  task cmp; if (a6 !== b6 || a5 !== b5) bad = bad + 1; endtask\n"
        "  initial begin\n" + "\n".join(lines) + "\n"
        '    if (bad == 0) $display("LUTK6_OK"); else $display("BAD %0d", bad);\n'
        "  end\nendmodule\n")
    assert "LUTK6_OK" in _run(tmp_path, body, [LUT6])


def test_lutk4_matches_reference(tmp_path):
    rng = random.Random(4)
    lines = []
    for _ in range(1000):
        init, i = rng.getrandbits(16), rng.randrange(16)
        o6, o5 = (init >> i) & 1, (init >> (i & 7)) & 1
        lines.append(f"    init = 16'h{init:04x}; i = 4'd{i}; #1 "
                     f"if (o6 !== 1'b{o6} || o5 !== 1'b{o5}) bad = bad + 1;")
    body = (
        "module t; reg [15:0] init; reg [3:0] i; wire o6, o5; integer bad = 0;\n"
        "  lutk #(.K(4)) dut (.init(init), .i(i), .o6(o6), .o5(o5));\n"
        "  initial begin\n" + "\n".join(lines) + "\n"
        '    if (bad == 0) $display("LUTK4_OK"); else $display("BAD %0d", bad);\n'
        "  end\nendmodule\n")
    assert "LUTK4_OK" in _run(tmp_path, body)
