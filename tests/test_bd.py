"""
software/bob/bd.py and software/bob/ip/: block designs (M18).

Three things are checked here:
  - every IP core does what its header says, cycle by cycle, against a Python model
    (iverilog, random stimulus that is checked to exercise the core);
  - every rule of check() has a failing case and the rule-abiding design passes;
  - a generated wrapper goes through the whole flow (synthesis == source, place and
    route, bits, model check), with and without a pin file.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import zlib

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bd as BD  # noqa: E402
import flow  # noqa: E402
import project as P  # noqa: E402
import vpr_run  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("yosys") is None or shutil.which("iverilog") is None,
                                reason="needs yosys and iverilog")


@pytest.fixture(autouse=True)
def _no_recent(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "RECENT", str(tmp_path / "recent.json"))


# --- the IP cores, against models -------------------------------------------------
#
# model(params) -> (state, step). step(state, inputs) -> (outputs now, next state):
# outputs are what the core shows during a cycle with these inputs, before the edge.

def m_counter(p):
    W = p["W"]
    return 0, lambda q, i: ({"q": q}, 0 if i["clr"] else (q + i["en"]) % (1 << W))


def m_clkdiv(p):
    N = p["N"]
    return 0, lambda c, i: ({"tick": int(c == (1 << N) - 1)}, (c + 1) % (1 << N))


def m_debounce(p):
    N = p["N"]

    def step(st, i):
        s0, s1, c, q = st
        out = {"q": q}
        if s1 == q:
            nc, nq = 0, q
        else:
            nc, nq = (c + 1) % (1 << N), (s1 if c == (1 << N) - 1 else q)
        return out, (i["d"], s0, nc, nq)
    return (0, 0, 0, 0), step


def m_edge(p):
    def step(st, i):
        s0, s1 = st
        return {"rise": s0 & (1 - s1), "fall": (1 - s0) & s1}, (i["d"], s0)
    return (0, 0), step


def m_toggle(p):
    return 0, lambda q, i: ({"q": q}, q ^ i["t"])


def m_register(p):
    return 0, lambda q, i: ({"q": q}, i["d"] if i["en"] else q)


def comb(f):
    return lambda p: (None, lambda st, i: (f(p, i), None))


MODELS = {
    "counter": ({"W": 3}, {"en": 1, "clr": 1}, m_counter),
    "clkdiv": ({"N": 3}, {}, m_clkdiv),
    "debounce": ({"N": 2}, {"d": 1}, m_debounce),
    "edge_detect": ({}, {"d": 1}, m_edge),
    "toggle": ({}, {"t": 1}, m_toggle),
    "register": ({"W": 4}, {"en": 1, "d": 4}, m_register),
    "mux2": ({"W": 3}, {"a": 3, "b": 3, "sel": 1}, comb(lambda p, i: {"y": i["b"] if i["sel"] else i["a"]})),
    "const": ({"W": 5, "VALUE": 22}, {}, comb(lambda p, i: {"y": 22})),
    "slice": ({"W_IN": 6, "HI": 4, "LO": 2}, {"d": 6}, comb(lambda p, i: {"y": (i["d"] >> 2) & 7})),
    "concat": ({"W_A": 2, "W_B": 3}, {"a": 2, "b": 3}, comb(lambda p, i: {"y": (i["a"] << 3) | i["b"]})),
    "and": ({"W": 3}, {"a": 3, "b": 3}, comb(lambda p, i: {"y": i["a"] & i["b"]})),
    "or": ({"W": 3}, {"a": 3, "b": 3}, comb(lambda p, i: {"y": i["a"] | i["b"]})),
    "xor": ({"W": 3}, {"a": 3, "b": 3}, comb(lambda p, i: {"y": i["a"] ^ i["b"]})),
    "not": ({"W": 3}, {"a": 3}, comb(lambda p, i: {"y": (~i["a"]) & 7})),
}
CYCLES = 200


def test_every_ip_core_has_a_model_and_a_header():
    cat = {r["ip"]: r for r in P.ip_catalog()}
    assert set(cat) == set(MODELS), "an IP core without a model here is an untested core"
    for name, r in cat.items():
        assert r["desc"], f"{name} has no @desc"
        declared = {q["name"] for q in r["params"]}
        assert declared == set(MODELS[name][0]), f"{name}: @param lines vs the model's parameters"


def _stimulus(inputs, seed, slow=()):
    """Random inputs; the ones in `slow` hold for a random 1..12 cycles so a debouncer sees
    both glitches and settled levels."""
    rnd = random.Random(seed)
    cur = {k: 0 for k in inputs}
    hold = {k: 0 for k in inputs}
    out = []
    for _ in range(CYCLES):
        for k, w in inputs.items():
            if k in slow:
                if hold[k] == 0:
                    cur[k] = rnd.getrandbits(w)
                    hold[k] = rnd.choice([1, 1, 2, 3, 6, 9, 12])
                hold[k] -= 1
            else:
                cur[k] = rnd.getrandbits(w)
        # a counter that is cleared half the time never counts far
        if "clr" in cur:
            cur["clr"] = int(rnd.random() < 0.08)
        out.append(dict(cur))
    return out


def _simulate(tmp_path, name, params, inputs, stim):
    rec = {r["ip"]: r for r in P.ip_catalog()}[name]
    ports = P.ports([rec["file"]], rec["module"], params)
    outs = [q for q in ports if q["dir"] == "output"]
    has_clk = any(q["name"] == "clk" for q in ports)
    lines = ["`timescale 1ns/1ps", "module tb;", "  reg clk = 0;"]
    for q in ports:
        if q["dir"] == "input" and q["name"] != "clk":
            lines.append(f"  reg [{q['width'] - 1}:0] {q['name']} = 0;")
        elif q["dir"] == "output":
            lines.append(f"  wire [{q['width'] - 1}:0] {q['name']};")
    ps = ", ".join(f".{k}({v})" for k, v in params.items())
    conns = ", ".join(f".{q['name']}({q['name']})" for q in ports)
    lines.append(f"  {rec['module']} {'#(' + ps + ')' if ps else ''} dut ({conns});")
    lines.append("  initial begin")
    for vec in stim:
        for k, v in vec.items():
            lines.append(f"    {k} = {v};")
        lines.append("    #1 $display(\"" + " ".join("%0d" for _ in outs) + "\""
                     + "".join(f", {q['name']}" for q in outs) + ");")
        if has_clk:
            lines.append("    #4 clk = 1; #5 clk = 0;")
        else:
            lines.append("    #9;")
    lines += ["    $finish;", "  end", "endmodule"]
    tb = tmp_path / f"tb_{name}.v"
    tb.write_text("\n".join(lines) + "\n")
    vvp = tmp_path / f"{name}.vvp"
    r = subprocess.run(["iverilog", "-g2012", "-o", str(vvp), str(tb), rec["file"]], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["vvp", "-n", str(vvp)], capture_output=True, text=True)
    rows = [ln.split() for ln in r.stdout.splitlines() if ln and ln[0].isdigit()]
    return [{q["name"]: int(v) for q, v in zip(outs, row)} for row in rows]


@pytest.mark.parametrize("name", sorted(MODELS))
def test_ip_core_matches_its_model(tmp_path, name):
    params, inputs, model = MODELS[name]
    stim = _stimulus(inputs, seed=zlib.crc32(name.encode()), slow=("d",) if name == "debounce" else ())
    got = _simulate(tmp_path, name, params, inputs, stim)
    assert len(got) == CYCLES
    st, step = model(params)
    seen = {}
    for k, (vec, g) in enumerate(zip(stim, got)):
        want, st = step(st, vec)
        assert g == want, f"{name} cycle {k}: inputs {vec}, got {g}, model {want}"
        for o, v in g.items():
            seen.setdefault(o, set()).add(v)
    # the stimulus must exercise the core, or matching the model proves little
    for o, vals in seen.items():
        if name != "const":
            assert len(vals) > 1, f"{name}.{o} never changed in {CYCLES} cycles"


# --- check(): every rule fails where it should --------------------------------------


def _bd(blocks, wires, name="t"):
    return {"bd": 1, "name": name, "blocks": blocks, "wires": wires}


CNT = {"id": "cnt", "kind": "ip", "type": "counter", "params": {"W": 3}}
MUX = {"id": "mux", "kind": "ip", "type": "mux2", "params": {"W": 3}}
GOOD_WIRES = [{"src": "board.sw[1]", "dst": "cnt.en"}, {"src": "board.btn[0]", "dst": "cnt.clr"},
              {"src": "cnt.q", "dst": "mux.a"}, {"src": "board.btn[3:1]", "dst": "mux.b"},
              {"src": "board.sw[0]", "dst": "mux.sel"}, {"src": "mux.y", "dst": "board.led"}]


def test_the_rule_abiding_design_has_no_errors():
    res = BD.check(_bd([CNT, MUX], GOOD_WIRES))
    assert res["errors"] == [] and res["warnings"] == []


def _errs(blocks, wires):
    return BD.check(_bd(blocks, wires))["errors"]


def _one(errs, where, text):
    assert any(e["where"] == where and text in e["msg"] for e in errs), errs


@pytest.mark.parametrize("change,where,text", [
    (lambda w: w[:-2] + w[-1:], "mux.sel", "not driven"),                       # undriven input
    (lambda w: w + [{"src": "board.sw[0]", "dst": "cnt.en"}], "cnt.en", "driven twice"),
    (lambda w: w[:2] + [{"src": "cnt.q[1:0]", "dst": "mux.a"}] + w[3:], "mux.a", "wide"),
    (lambda w: w + [{"src": "cnt.q[0]", "dst": "board.sw[0]"}], "board.sw[0]", "board input"),
    (lambda w: w + [{"src": "board.led[0]", "dst": "cnt.en"}], "board.led[0]", "board output"),
    (lambda w: w + [{"src": "board.sw[0]", "dst": "cnt.clk"}], "cnt.clk", "connected for you"),
    (lambda w: w + [{"src": "board.pad12", "dst": "cnt.en"}], "cnt.en", "wired to a switch"),
    (lambda w: w + [{"src": "board.pad99", "dst": "cnt.en"}], "cnt.en", "there is no pad99"),
    (lambda w: w + [{"src": "cnt.nope", "dst": "mux.a"}], "mux.a", "has no port nope"),
    (lambda w: w + [{"src": "cnt.q[5:0]", "dst": "mux.a"}], "mux.a", "outside"),
    (lambda w: w + [{"src": "ghost.q", "dst": "mux.a"}], "mux.a", "no block ghost"),
    (lambda w: w + [{"src": "cnt q", "dst": "mux.a"}], "mux.a", "an endpoint is"),
    (lambda w: w + [{"src": "mux.a", "dst": "board.pad1"}], "mux.a", "is an input"),
    (lambda w: w + [{"src": "board.pad0", "dst": "cnt.en"}], "cnt.en", "carries the clock"),
])
def test_each_rule_fails_where_it_should(change, where, text):
    _one(_errs([CNT, MUX], change(list(GOOD_WIRES))), where, text)


def test_a_pad_is_one_direction_only():
    w = GOOD_WIRES + [{"src": "board.pad1", "dst": "cnt.en"}]
    w = [x for x in w if x["dst"] != "cnt.en" or x["src"] == "board.pad1"]
    w.append({"src": "cnt.q[0]", "dst": "board.pad1"})
    _one(_errs([CNT, MUX], w), "board.pad1", "used as an input elsewhere")


@pytest.mark.parametrize("bad_id", ["board", "clk", "led", "pad3", "a__b", "1x", "", "edge", "wire", "logic"])
def test_block_names_are_checked(bad_id):
    _one(_errs([{**CNT, "id": bad_id}], []), bad_id or "?", "not a usable block name")


def test_block_types_and_parameters_are_checked():
    _one(_errs([{**CNT, "type": "nosuch"}], []), "cnt", "no IP called nosuch")
    _one(_errs([{**CNT, "params": {"Q": 1}}], []), "cnt", "no parameter")
    _one(_errs([CNT, {**MUX, "id": "cnt"}], []), "cnt", "two blocks")
    _one(_errs([{**CNT, "kind": "module"}], []), "cnt", "no module")


def test_undriven_leds_and_unused_blocks_are_warnings():
    res = BD.check(_bd([CNT, MUX, {"id": "k", "kind": "ip", "type": "const", "params": {}}],
                       GOOD_WIRES[:-1] + [{"src": "mux.y[0]", "dst": "board.led[2]"}]))
    assert res["errors"] == []
    msgs = " ".join(w["msg"] for w in res["warnings"])
    assert "LD0, LD1 not driven" in msgs and "k: no output is used" in msgs


# --- generate(): the wrapper, the pins, and the whole flow ----------------------------


def _project(tmp_path, blocks, wires, name="demo"):
    p = P.Project.create(tmp_path, name)
    rel = BD.new_bd(p, f"{name}_bd")
    doc = BD.load(p.abs(rel))
    doc["blocks"], doc["wires"] = blocks, wires
    BD.save(p.abs(rel), doc)
    p.set_settings(pnr="python")
    p.save()
    return p, rel


def test_generate_refuses_a_design_with_errors(tmp_path):
    p, rel = _project(tmp_path, [CNT], [])
    with pytest.raises(BD.BdError, match="not driven"):
        BD.generate(p, rel)
    assert not os.path.exists(os.path.join(p.dir, "bd", "demo_bd_wrapper.v"))


def test_the_generated_wrapper_builds_and_matches_its_source(tmp_path):
    """The board-only design: no pin file, and the flow's model check runs on it."""
    p, rel = _project(tmp_path, [CNT, MUX], GOOD_WIRES)
    out = BD.generate(p, rel, set_top=True)
    assert out["top"] == "demo_bd_wrapper" and out["pcf"] is None
    assert sorted(p.data["sources"]) == ["bd/demo_bd_wrapper.v", "ip/ip_counter.v", "ip/ip_mux2.v"]
    assert BD.is_generated(p.abs("bd/demo_bd_wrapper.v"))
    assert "demo_bd_wrapper" not in {m["name"] for m in P.modules(BD.user_files(p))}
    res = flow.Flow(**P.Project.open(p.path).flow_kwargs()).run()
    assert res.ok, res.error
    model = [s for s in res.stages if s.name == "model"][0]
    assert model.ok and "== source trace" in model.detail, model.detail


def test_a_design_on_a_pad_gets_a_pin_file_that_builds(tmp_path):
    wires = GOOD_WIRES[:-1] + [{"src": "mux.y[1:0]", "dst": "board.led[1:0]"},
                               {"src": "mux.y[2]", "dst": "board.pad1"},
                               {"src": "board.pad2", "dst": "cnt.en"}]
    wires = [w for w in wires if w != {"src": "board.sw[1]", "dst": "cnt.en"}]
    p, rel = _project(tmp_path, [CNT, MUX], wires)
    out = BD.generate(p, rel, set_top=True)
    assert out["pcf"] == "constrs/demo_bd.pcf" and p.data["active_pcf"] == out["pcf"]
    pins = vpr_run.read_pcf(p.abs(out["pcf"]))
    assert pins["pad1[0]"] == 1 and pins["pad2[0]"] == 2 and pins["led[2]"] > 0
    text = open(p.abs("bd/demo_bd_wrapper.v")).read()
    assert "output wire       pad1" in text and "input  wire       pad2" in text
    assert "assign led[2] = 1'b0;" in text
    res = flow.Flow(**P.Project.open(p.path).flow_kwargs()).run()
    assert res.ok, res.error
    # back to the board only: the pin file is no longer the active one
    doc = BD.load(p.abs(rel))
    doc["wires"] = GOOD_WIRES
    BD.save(p.abs(rel), doc)
    assert BD.generate(p, rel)["pcf"] is None and p.data["active_pcf"] is None


def test_a_project_module_is_a_block_with_its_parameters(tmp_path):
    p = P.Project.create(tmp_path, "mods")
    src = tmp_path / "inv.v"
    src.write_text("module inv #(parameter W = 2) (input wire [W-1:0] a, output wire [W-1:0] y);\n"
                   "  assign y = ~a;\nendmodule\n")
    p.add_source(str(src))
    p.save()
    blocks = [{"id": "u", "kind": "module", "type": "inv", "params": {"W": 3}}]
    wires = [{"src": "board.btn[2:0]", "dst": "u.a"}, {"src": "u.y", "dst": "board.led"}]
    res = BD.check(_bd(blocks, wires, "mods_bd"), p)
    assert res["errors"] == [], res["errors"]
    p.add_bd(os.path.join("bd", "mods_bd.bd"))
    BD.save(p.abs("bd/mods_bd.bd"), _bd(blocks, wires, "mods_bd"))
    out = BD.generate(p, "bd/mods_bd.bd", set_top=True)
    assert "inv #(.W(3)) u (" in open(p.abs(out["wrapper"])).read()
    p.set_settings(pnr="python")
    res = flow.Flow(**p.flow_kwargs()).run()
    assert res.ok, res.error


def test_the_bd_file_keeps_the_canvas(tmp_path):
    path = tmp_path / "x.bd"
    doc = _bd([{**CNT, "x": 120, "y": 40}], [], "x")
    doc["board"] = {"ix": 10, "in_pads": [3]}
    doc["junk"] = 1
    BD.save(str(path), doc)
    back = json.load(open(path))
    assert back["board"] == {"ix": 10, "in_pads": [3]} and back["blocks"][0]["x"] == 120
    assert "junk" not in back


def test_the_committed_example_project_builds(tmp_path):
    """work/examples/bd_demo is a project made by the studio; its wrapper is current."""
    path = os.path.join(ROOT, "work", "examples", "bd_demo", "bd_demo.bobproj")
    p = P.Project.open(path)
    doc = BD.load(p.abs(p.data["block_designs"][0]))
    res = BD.check(doc, p)
    assert res["errors"] == []
    want = BD.wrapper_text(doc, res, p.data["block_designs"][0])
    assert open(p.abs(f"bd/{doc['name']}_wrapper.v")).read() == want, \
        "bd_demo's wrapper is stale: run software/bob/bd.py generate on it"
    kw = p.flow_kwargs()
    kw["out"] = str(tmp_path / "bd_demo.bit")
    res = flow.Flow(**kw).run()
    assert res.ok, res.error
