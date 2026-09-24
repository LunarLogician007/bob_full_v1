"""
M9: VPR packs, places and routes the examples on the committed rr graph.

The VPR results are committed in software/bob/vpr/<top>/ (`make vpr`, Docker), so
these tests need no Docker: each result must be fresh (routed from today's netlist
and architecture), its FASM legal against device.json, the fixed pins where VPR
put the pads, and its chain must reproduce the source Verilog on model.py.
"""

import os
import re
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402
import fasm_from_vpr as FV  # noqa: E402
import vpr_run  # noqa: E402

needs_tools = pytest.mark.skipif(shutil.which("yosys") is None or shutil.which("iverilog") is None,
                                 reason="needs yosys and iverilog")


@needs_tools
@pytest.mark.parametrize("top", vpr_run.EXAMPLES)
def test_vpr_example(top):
    bs, contents, tr = FV.flow(top, cycles=200)          # raises if stale or != source
    d = os.path.join(vpr_run.RESULTS, top)
    F, _ = FV.features(d, top)
    FV.check_legal(F)
    # the pads VPR placed are the ones vpr_run fixed
    place = FV.read_place(os.path.join(d, f"{top}.place"))
    for line in open(os.path.join(d, f"{top}.pins")):
        if line.startswith("#"):
            continue
        blk, x, y, _z = line.split()
        assert place[blk] == (int(x), int(y))
    # a carry chain never runs longer than a CLB column
    text = open(os.path.join(d, f"{top}.eblif")).read()
    cin_of = {}
    cout_of = {}
    for m in re.finditer(r"\.subckt bob_add (.*)\n\.cname (\S+)", text):
        pins = dict(p.split("=") for p in m.group(1).split())
        if "cin" in pins:
            cin_of[m.group(2)] = pins["cin"]
        if "cout" in pins:
            cout_of[pins["cout"]] = m.group(2)
    for atom in cin_of:
        n, a = 1, atom
        while a in cin_of and cin_of[a] in cout_of:
            a = cout_of[cin_of[a]]
            n += 1
        assert n <= vpr_run.COL_ROWS


def test_results_committed_for_every_example():
    for top in vpr_run.EXAMPLES:
        for ext in vpr_run.KEEP:
            assert os.path.exists(os.path.join(vpr_run.RESULTS, top, f"{top}.{ext}")), (top, ext)
        stamp = open(os.path.join(vpr_run.RESULTS, top, "stamp.txt")).read()
        assert f"arch_sha256 {vpr_run.arch_sha()}" in stamp
        assert "--read_rr_graph rr.xml" in stamp


def test_arch_has_bob_cells():
    arch = open(os.path.join(vpr_run.ARCH_DIR, f"bob_k{B.LUT_K}.xml")).read()
    for model in ("bob_add", "bob_ff", "bob_bram", "bob_dsp"):
        assert f'<model name="{model}">' in arch
    # M21: the cluster's element (fle) has the reference's modes: one LUT, two fractured
    # LUTs, the adder (M24: Double Duty, the adder beside a LUT K-2); the crossbar feeds the
    # element inputs
    for mode in ("lut", "frac", "dd"):
        assert f'<mode name="{mode}">' in arch
    assert '<mode name="arithmetic">' not in arch
    assert f'<pb_type name="fle" num_pb="{B.CLB_N}">' in arch
    assert 'name="crossbar"' in arch or 'name="xb0_0"' in arch


def test_legality_rejects_bad_features():
    node, (lo, w, base, ins) = next((n, m) for n, m in B.MUX.items() if B.NODE[n][1] == "CHANX")
    with pytest.raises(FV.FasmError):
        FV.check_legal({f"rr{node}": base + len(ins)})             # past the last input
    with pytest.raises(FV.FasmError):
        FV.check_legal({"rr999999": 1})                             # no such mux
    clb = B.CLBS[0]
    with pytest.raises(FV.FasmError):
        FV.check_legal({f"{clb}.no_such_field": 1})
    with pytest.raises(FV.FasmError):
        FV.check_legal({f"{clb}.e0.ff_en": 2})
    with pytest.raises(FV.FasmError):                               # M21: a crossbar select past its sources
        FV.check_legal({f"{clb}.e0.x0": 2 + len(B.XBAR_SOURCES[0][0])})
    with pytest.raises(FV.FasmError):
        FV.check_legal({f"{clb}.e{B.CLB_N}.ff_en": 1})               # no such element
    FV.check_legal({f"{clb}.e0.ff_en": 1, f"{clb}.e0.x0": 1 + len(B.XBAR_SOURCES[0][0]),
                    f"rr{node}": base})


@needs_tools
def test_stale_result_is_refused(monkeypatch):
    import equiv
    equiv.equiv([os.path.join(ROOT, "work", "examples", "gates", "gates.v")], "gates", cycles=20)
    assert vpr_run.stale("gates") is None
    monkeypatch.setattr(vpr_run, "arch_sha", lambda: "0" * 64)
    assert "different architecture" in vpr_run.stale("gates")
    with pytest.raises(FV.FasmError):
        FV.build("gates")
