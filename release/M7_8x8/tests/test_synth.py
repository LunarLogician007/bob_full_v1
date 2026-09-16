"""
M8: yosys synthesis onto bob cells. For every example: only bob cells remain, the
netlist equals the source Verilog in iverilog, and the placed/routed bitstream
reproduces the source on tools/bob/model.py.
"""

import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "bob"))
sys.path.insert(0, os.path.join(ROOT, "host"))

pytestmark = pytest.mark.skipif(shutil.which("yosys") is None or shutil.which("iverilog") is None,
                                reason="needs yosys and iverilog")

import place  # noqa: E402
import synth  # noqa: E402

EXPECT = {                     # cells each example must map to (the point of each example)
    "gates": {"$lut"},
    "adder": {"BOB_ADD"},
    "counter": {"BOB_ADD", "BOB_FDRE"},
    "blinky": {"BOB_ADD", "BOB_FDRE"},
    "ram": {"BOB_BRAM18"},
    "mult": {"BOB_DSP", "BOB_FDRE"},
}


@pytest.mark.parametrize("top", place.EXAMPLES)
def test_example_flow(top):
    d, bs, contents, tr = place.flow(top, cycles=200)
    mod = synth.check(os.path.join(ROOT, "build", "synth", top), top)
    kinds = set(synth.summary(mod))
    assert EXPECT[top] <= kinds <= synth.CELLS
    assert len(tr["trace"]) == 200


def test_blinky_chain_crosses_columns():
    d, bs, contents, tr = place.flow("blinky", cycles=50)
    cols = {x for (x, y) in d.cells}
    assert len(cols) >= 2, "a 12-bit carry chain cannot fit one 8-row column"


def test_non_bob_cell_is_rejected(tmp_path):
    v = tmp_path / "latch.v"
    v.write_text("module latch(input [1:0] sw, output [2:0] led); reg q; "
                 "always @* if (sw[0]) q = sw[1]; assign led = {2'b0, q}; endmodule\n")
    # yosys itself stops at dfflegalize (no latch cell), or the cell check does
    with pytest.raises(RuntimeError, match="yosys failed|outside the bob library"):
        synth.synth([str(v)], "latch", str(tmp_path / "out"))
