"""
M8: yosys synthesis onto bob cells. For every example: only bob cells remain, the
netlist equals the source Verilog in iverilog, and the placed/routed bitstream
reproduces the source on software/bob/model.py.
"""

import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

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


def test_long_chain_crosses_columns():
    """The M8 placer must split a carry chain that is longer than a CLB column.
    blinky's 12 cells fitted two columns while columns were 4 and 8 rows; from M16 the
    columns are 10 rows, so `wide` (a 12-bit counter plus an 8-bit LFSR) is the design
    that has to be split."""
    import bitstream as B
    rows = len({y for (x, y) in B.CLB_XY_INDEX})
    d, bs, contents, tr = place.flow("wide", cycles=50)
    cols = {x for (x, y) in d.cells}
    assert len(cols) >= 2, f"a design of {len(d.cells)} cells cannot fit one {rows}-row column"
    for x in cols:                                     # each piece is a contiguous run of rows
        ys = sorted(y for (cx, y) in d.cells if cx == x)
        assert ys == list(range(ys[0], ys[0] + len(ys)))


def test_non_bob_cell_is_rejected(tmp_path):
    v = tmp_path / "latch.v"
    v.write_text("module latch(input [1:0] sw, output [2:0] led); reg q; "
                 "always @* if (sw[0]) q = sw[1]; assign led = {2'b0, q}; endmodule\n")
    # yosys itself stops at dfflegalize (no latch cell), or the cell check does
    with pytest.raises(RuntimeError, match="yosys failed|outside the bob library"):
        synth.synth([str(v)], "latch", str(tmp_path / "out"))
