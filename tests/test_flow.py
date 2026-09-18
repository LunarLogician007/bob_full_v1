"""
software/bob/flow.py: the staged flow must be the same flow.

flow.py exists so a GUI can watch a build stage by stage, and it runs beside cli.py's
build() until the next milestone's tree can fold them together. The point of these
tests is that the duplication cannot drift: for every design, both must write a
byte-identical .bit. The rest checks the record a stage hands back, since that record
is what the studio and --json are built on.
"""

import hashlib
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import cli  # noqa: E402
import flow  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("yosys") is None or shutil.which("iverilog") is None,
                                reason="needs yosys and iverilog")

# Small designs with committed VPR results: the equivalence is about the two code
# paths, not about routing, so there is no reason to pay for the big ones here.
SAME = ["gates", "adder", "counter"]


def _src(name):
    return [os.path.join(ROOT, "work", "examples", name, f"{name}.v")]


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _both(tmp_path, name, **kw):
    a = str(tmp_path / f"cli_{name}.bit")
    b = str(tmp_path / f"flow_{name}.bit")
    cli.build(_src(name), out=a, log=lambda *_: None, **kw)
    res = flow.Flow(_src(name), out=b, **kw).run()
    return a, b, res


@pytest.mark.parametrize("name", SAME)
def test_flow_and_cli_write_the_same_bit(tmp_path, name):
    a, b, res = _both(tmp_path, name)
    assert res.ok, res.error
    assert _sha(a) == _sha(b), f"{name}: flow.py and cli.build() disagree"


def test_the_same_bit_with_a_pin_file(tmp_path):
    """gates_swapped is a committed variant: the .pcf reaches both paths the same way."""
    a = str(tmp_path / "cli.bit")
    b = str(tmp_path / "flow.bit")
    cli.build(_src("gates"), out=a, log=lambda *_: None, name="gates_swapped")
    res = flow.Flow(_src("gates"), out=b, name="gates_swapped").run()
    assert res.ok, res.error
    assert _sha(a) == _sha(b)


def test_the_same_bit_with_a_free_running_clock(tmp_path):
    a, b, res = _both(tmp_path, "counter", clock="run", div=4)
    assert res.ok, res.error
    assert _sha(a) == _sha(b)
    bits = [s for s in res.stages if s.name == "bits"][0]
    assert bits.stats["hz"] == pytest.approx(125e6 / 2 ** (4 + 9))


def test_the_same_bit_through_the_python_pnr(tmp_path):
    a, b, res = _both(tmp_path, "counter", pnr="python")
    assert res.ok, res.error
    assert _sha(a) == _sha(b)
    pnr = [s for s in res.stages if s.name == "pnr"][0]
    assert pnr.stats["engine"] == "python"
    assert pnr.stats["clbs"] > 0


def test_every_stage_reports_itself(tmp_path):
    res = flow.Flow(_src("gates"), out=str(tmp_path / "x.bit")).run()
    assert res.ok, res.error
    assert [s.name for s in res.stages] == list(flow.STAGES)
    for s in res.stages:
        assert s.ok is True
        assert s.seconds >= 0.0
        assert s.detail
        assert s.to_json()["name"] == s.name
    assert res.seconds == pytest.approx(sum(s.seconds for s in res.stages))
    j = res.to_json()
    assert j["ok"] and j["device"]["chain_w"] and len(j["stages"]) == len(flow.STAGES)


def test_stages_fire_as_they_finish(tmp_path):
    seen = []
    res = flow.Flow(_src("gates"), out=str(tmp_path / "y.bit")).run(on_stage=seen.append)
    assert res.ok, res.error
    assert [s.name for s in seen] == list(flow.STAGES)


def test_the_model_stage_is_skipped_off_convention(tmp_path):
    """ram.v keeps to the convention; a design outside it must say so, not fail."""
    res = flow.Flow(_src("gates"), out=str(tmp_path / "z.bit")).run()
    model = [s for s in res.stages if s.name == "model"][0]
    assert model.ok and not model.stats.get("skipped")


# --- the failures it has to report -------------------------------------------


def test_a_bad_clock_mode_is_refused():
    with pytest.raises(flow.FlowError):
        flow.Flow(_src("gates"), clock="nonsense")


def test_a_bad_pnr_engine_is_refused():
    with pytest.raises(flow.FlowError):
        flow.Flow(_src("gates"), pnr="nonsense")


def test_a_variant_name_with_the_wrong_top_is_refused():
    with pytest.raises(flow.FlowError):
        flow.Flow(_src("counter"), name="gates_swapped")


def test_a_failing_stage_is_recorded_red_not_green(tmp_path, monkeypatch):
    """A stage that refuses must say so in its own record. `bits` used to finish with
    ok=True and then raise, so a failed build showed that stage green in the page."""
    import bitgen
    real = bitgen.word_from_features
    seen = {"n": 0}

    def broken(F):                       # corrupt only the round-trip re-encode
        seen["n"] += 1
        w = real(F)
        return w ^ 1 if seen["n"] > 1 else w

    monkeypatch.setattr(bitgen, "word_from_features", broken)
    res = flow.Flow(_src("gates"), out=str(tmp_path / "rt.bit")).run()
    assert not res.ok
    assert "round trip" in res.error
    bits = [s for s in res.stages if s.name == "bits"]
    assert bits and bits[0].ok is False, "the bits stage reported success on a failed build"
    assert all(s.ok for s in res.stages if s.name != "bits")


def test_a_missing_source_fails_in_the_synth_stage(tmp_path):
    res = flow.Flow([str(tmp_path / "nope.v")], out=str(tmp_path / "n.bit")).run()
    assert not res.ok
    assert res.stages and res.stages[-1].ok is False


# --- diagnostics -------------------------------------------------------------


def test_messages_carry_file_and_line():
    m = flow.messages("work/examples/fir/fir.v:14: warning: 'rst' is not used\n", "iverilog")
    assert m == [{"severity": "warning", "file": "work/examples/fir/fir.v", "line": 14,
                  "text": "'rst' is not used", "source": "iverilog"}]


def test_messages_pick_up_yosys_and_vpr_lines_without_a_position():
    m = flow.messages("Warning: Wire is used but has no driver.\nError 1: circuit is unroutable\n")
    assert {x["severity"] for x in m} == {"warning", "error"}
    assert all(x["file"] is None for x in m)


def test_errors_are_listed_before_warnings():
    """A long warning list must never push the line that has to be fixed out of sight."""
    m = flow.messages("a.v:3: warning: something minor here\n"
                      "a.v:9: error: this is the one that matters\n")
    assert [x["severity"] for x in m] == ["error", "warning"]


def test_messages_are_deduplicated_and_empty_input_is_fine():
    assert flow.messages("") == []
    assert flow.messages(None) == []
    dup = "a.v:3: warning: the same thing twice\na.v:3: warning: the same thing twice\n"
    assert len(flow.messages(dup)) == 1


def test_a_position_with_a_column_or_a_span_still_parses():
    """yosys writes file.v:110.46-110.78, iverilog file.v:7 - both name line 110 / 7."""
    a = flow.messages("Warning: wire is assigned in a block at /x/bob_cells.v:110.46-110.78.")
    assert a and a[0]["file"].endswith("bob_cells.v") and a[0]["line"] == 110
    b = flow.messages("work/examples/fir/fir.v:7:3: error: something went wrong here")
    assert b and b[0]["line"] == 7


def test_tool_bookkeeping_is_not_shown_as_a_diagnostic():
    """yosys names its own wires with a leading $, and the cell library emits one per
    BRAM word. None of it is about the design, and it would bury the real errors."""
    noise = ("Warning: wire '$for_loop$1[1012].u_core.mem' is assigned in a block.\n"
             "Warning: $auto$alumacc.cc:548:replace_alu$6 was optimised.\n")
    assert flow.messages(noise) == []


def test_the_message_list_is_capped():
    many = "".join(f"a.v:{i}: warning: something worth saying number {i}\n"
                   for i in range(flow.MAX_MESSAGES + 25))
    m = flow.messages(many)
    assert len(m) == flow.MAX_MESSAGES + 1
    assert m[-1]["text"].startswith("... and 25 more")
