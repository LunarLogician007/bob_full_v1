"""
M12a: bob's own pack/place/route (software/bob/pnr/), checked independently of itself.

For every example and variant the Python result must be legal (checked here from the
written files, not by the PnR's own bookkeeping), deterministic for a seed, and its
chain must reproduce the source Verilog on model.py. Plus the failures it must report.
"""

import hashlib
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402
import fasm_from_vpr as FV  # noqa: E402
import vpr_run  # noqa: E402
from pnr import netlist, pack, place, route  # noqa: E402
from pnr import run as pnr_run  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("yosys") is None or shutil.which("iverilog") is None,
                                reason="needs yosys and iverilog")
NAMES = vpr_run.EXAMPLES + list(vpr_run.VARIANTS)


@pytest.fixture(scope="module", autouse=True)
def synthesised():
    import equiv
    for top in vpr_run.EXAMPLES:
        if not os.path.exists(os.path.join(ROOT, "build", "synth", top, f"{top}.trace.json")):
            equiv.equiv([os.path.join(ROOT, "work", "examples", top, f"{top}.v")], top, cycles=100)


def _files_sha(work, name):
    h = hashlib.sha256()
    for ext in ("net", "place", "route"):
        h.update(open(os.path.join(work, f"{name}.{ext}"), "rb").read())
    return h.hexdigest()


@pytest.mark.parametrize("name", NAMES)
def test_python_pnr_result(name, tmp_path):
    top, pcf = vpr_run.VARIANTS.get(name, (name, None))
    work, st = pnr_run.run(top, 1, pcf, name, work=str(tmp_path / "a"))

    # placement: CLBs on CLB sites, hard blocks on their sites, no two blocks on one site,
    # pads where the pins put them
    placed = FV.read_place(os.path.join(work, f"{name}.place"))
    block_at = {(b["x"], b["y"]): b for b in B.DEVICE["blocks"]}
    import json
    side = json.load(open(os.path.join(work, f"{name}.vpr.json")))
    for blk, pad in side["pins"].items():
        assert placed[blk] == B.PAD_XY[pad]
    seen = {}
    for blk, xy in placed.items():
        if blk in side["pins"]:
            continue
        assert xy in block_at and block_at[xy]["type"] != "io", (blk, xy)
        assert xy not in seen, (blk, seen.get(xy))
        seen[xy] = blk

    # routing: every step is a real rr edge (the destination's mux has the source as an
    # input), branches start on the tree, no node carries two nets
    owner = {}
    for net, branches in FV.read_route(os.path.join(work, f"{name}.route")).items():
        tree, prev = set(), None
        for node, kind in branches[0]:
            if node in tree:
                prev = node
                continue
            if prev is None:
                assert kind == "OPIN", (net, node)
            else:
                assert node in B.MUX and prev in B.MUX[node][3], (net, prev, node)
            assert owner.setdefault(node, net) == net, (node, owner[node], net)
            tree.add(node)
            prev = node

    # every chain and every carry stays a legal chain; the bits reproduce the source
    bs, contents, text = FV.build(name, work)
    FV.check_legal(__import__("bitgen").parse_fasm(text))
    bad, n, _tr = FV.check_model(name, bs, contents, work, top)
    assert not bad, bad[:3]

    # same seed, same result
    work2, _st = pnr_run.run(top, 1, pcf, name, work=str(tmp_path / "b"))
    assert _files_sha(work, name) == _files_sha(work2, name)


def test_every_sink_reached(tmp_path):
    """the routed nets reach exactly the packed sinks (M21: a CLB's outside inputs on some
    I pin of it - the crossbar is full)"""
    work, _st = pnr_run.run("fir", 1, None, "fir", work=str(tmp_path / "f"))
    eblif, _side, _fixed = vpr_run.prepare("fir")
    packed = pack.pack(netlist.parse_eblif(eblif, "fir"))
    placed = FV.read_place(os.path.join(work, "fir.place"))
    block_at = {(b["x"], b["y"]): b["name"] for b in B.DEVICE["blocks"]}
    node_pin = {v: k for k, v in B.PIN.items()}
    routes = FV.read_route(os.path.join(work, "fir.route"))
    for net, n in packed.nets.items():
        reached = {node_pin[node] for node, kind in routes[net][0] if kind == "IPIN"}
        for c, p in n["sinks"]:
            blk = block_at[placed[c]]
            if p == "I":
                assert any(r.startswith(f"{blk}.I[") for r in reached), (net, c, p)
            else:
                assert f"{blk}.{p}" in reached, (net, c, p, reached)


def test_too_many_clbs_is_refused():
    eblif, _side, fixed = vpr_run.prepare("blinky")
    packed = pack.pack(netlist.parse_eblif(eblif, "blinky"))
    extra = next(c for c in packed.clusters.values() if c.mode == "logic" or c.type == "clb")
    import bitstream as B
    have = sum(1 for c in packed.clusters.values() if c.type == "clb")
    for k in range(B.NCLB + 1 - have):                        # one more CLB than the grid has
        clone = pack.Cluster(f"extra{k}", "clb", "logic", dict(extra.atoms), {})
        packed.clusters[clone.name] = clone
    with pytest.raises(place.PlaceError):
        place.Placement(packed, fixed, 1)


def test_unroutable_congestion_is_reported():
    # two nets that must end on the same input pin can never both be routed
    node = next(n for n, m in B.MUX.items() if B.NODE[n][1] == "IPIN" and len(m[3]) >= 2)
    srcs = [s for s in B.MUX[node][3] if B.NODE[s][1] in ("CHANX", "CHANY")]
    opins = [o for o, outs in B.FANOUT.items() if B.NODE[o][1] == "OPIN"][:2]
    with pytest.raises(route.RouteError):
        route.route({"a": (opins[0], [node]), "b": (opins[1], [node])}, max_iters=4)
    assert srcs


def test_lone_flip_flop_is_refused():
    nl = netlist.parse_eblif(".model t\n.inputs clk d\n.outputs q\n"
                             ".subckt bob_ff D=d C=clk Q=q\n.cname ff0\n.end\n", "t")
    with pytest.raises(pack.PackError):
        pack.pack(nl)
