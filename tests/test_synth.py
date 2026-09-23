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


def test_long_chain_runs_through_the_elements():
    """The M8 placer puts a carry chain on consecutive element slots of a CLB column
    (M21: e0..e<N-1> of a CLB, then on across the carry direct into the CLB above), and
    a chain longer than a column is split into the next. blinky's chain crossed columns
    while CLBs held one element; `wide` (a 12-bit counter plus an 8-bit LFSR) now spans
    two CLBs of one column."""
    import bitstream as B
    d, bs, contents, tr = place.flow("wide", cycles=50)
    slots = {x: place.column(x) for x in place.CLB_COLS}
    carry = sorted((x, y, e) for (x, y, e) in d.cells if B.Bitstream(bs.to_int()).get_field(x, y, "cy_en", e))
    assert len({(x, y) for x, y, _e in carry}) >= 2, "the chain should cross a CLB boundary"
    for x in {x for x, _y, _e in carry}:              # each piece is a contiguous run of slots
        idx = sorted(slots[x].index(c) for c in carry if c[0] == x)
        assert idx == list(range(idx[0], idx[0] + len(idx)))


def test_non_bob_cell_is_rejected(tmp_path):
    v = tmp_path / "latch.v"
    v.write_text("module latch(input [1:0] sw, output [2:0] led); reg q; "
                 "always @* if (sw[0]) q = sw[1]; assign led = {2'b0, q}; endmodule\n")
    # yosys itself stops at dfflegalize (no latch cell), or the cell check does
    with pytest.raises(RuntimeError, match="yosys failed|outside the bob library"):
        synth.synth([str(v)], "latch", str(tmp_path / "out"))
