"""
software/bob/timing.py: the design's own static timing (M20).

The per-design clock is only as good as this analysis, so it is checked on designs
built by hand where the answer is known:
  - a register -> n LUTs -> register chain: the critical path grows with n, starts at a
    flip-flop and ends at one, and follows exactly the selected routing
  - a combinational loop is reported, not cut
  - pad-only logic has no register-to-register path (the pads are asynchronous)
and then through the flow: --hz auto writes the clock into the .bit and the software
board runs at it; a rate faster than the design allows is refused.
"""

import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitgen  # noqa: E402
import bitstream as B  # noqa: E402
import flow  # noqa: E402
import timing as T  # noqa: E402

BUF = int("AA" * (1 << (B.LUT_K - 3)), 16)          # O = I[0]
X0, Y0 = B.BLOCKS[B.CLBS[0]]["x"], B.BLOCKS[B.CLBS[0]]["y"]
UNIT = {"provisional": False, "source": "test", "ns": {k: 1.0 for k in (
    "mux_chan", "mux_ipin", "lut", "carry", "ff_clk_q", "ff_setup", "bram_clk_q", "bram_setup",
    "dsp_clk_q", "dsp_comb", "dsp_setup")} | {"wire": 0.0, "direct": 0.0}}


def _clbs(n):
    """n CLB positions along the first row of CLBs"""
    row = sorted((B.BLOCKS[c]["x"], B.BLOCKS[c]["y"]) for c in B.CLBS if B.BLOCKS[c]["y"] == Y0)
    return row[:n]


def _chain(n):
    """register -> n buffers -> register, as a configuration word"""
    d = B.Design()
    pos = _clbs(n + 2)
    q0 = d.lut(*pos[0], BUF, [B.Cell(*pos[-1], "o")], ff_en=1)     # the register at the start
    s = q0
    for x, y in pos[1:-1]:
        s = d.lut(x, y, BUF, [s])
    d.lut(*pos[-1], BUF, [s], ff_en=1)                             # the register at the end
    return d.build().to_int()


def test_a_longer_chain_has_a_longer_critical_path():
    t1, t3 = T.analyse(_chain(1), UNIT), T.analyse(_chain(3), UNIT)
    assert 0 < t1["cpd_ns"] < t3["cpd_ns"]
    for t in (t1, t3):
        assert t["path"][0]["kind"] == "OPIN"                       # a flip-flop output
        assert t["path"][-1]["kind"] == "internal"                  # the flip-flop's D (LUT output)
        assert t["levels"] >= 1
    # every extra buffer costs at least one LUT and one input mux
    assert t3["cpd_ns"] - t1["cpd_ns"] >= 2 * (UNIT["ns"]["lut"] + UNIT["ns"]["mux_ipin"])


def test_the_gap_covers_the_path_with_its_margin():
    t = T.analyse(_chain(3), UNIT, margin=1.25)
    assert t["gap_cycles"] * T.SYSCLK_NS >= t["cpd_ns"] * 1.25
    assert (t["gap_cycles"] - 1) * T.SYSCLK_NS < t["cpd_ns"] * 1.25 or t["gap_cycles"] == T.GAP_FLOOR


def test_a_combinational_loop_is_reported():
    d = B.Design()
    (xa, ya), (xb, yb) = _clbs(2)
    a = d.lut(xa, ya, BUF, [B.Cell(xb, yb, "o")])                   # a <- b
    d.lut(xb, yb, BUF, [a], ff_en=1)                                # b's register D <- a ...
    d.output(0, a)
    word = d.build().to_int()
    assert T.analyse(word, UNIT)["cpd_ns"] > 0                      # ... is fine: the loop is registered
    d = B.Design()
    a = d.lut(xa, ya, BUF, [B.Cell(xb, yb, "o")])
    b = d.lut(xb, yb, BUF, [a])                                     # both combinational: a loop
    q = d.lut(*_clbs(3)[2], BUF, [b], ff_en=1)
    d.output(0, q)
    with pytest.raises(T.TimingError, match="combinational loop"):
        T.analyse(d.build().to_int(), UNIT)


def test_pad_only_logic_has_no_register_path():
    d = B.Design()
    d.output(0, d.lut(X0, Y0, BUF, [d.input(0)]))
    t = T.analyse(d.build().to_int(), UNIT)
    assert t["cpd_ns"] == 0 and t["gap_cycles"] == T.GAP_FLOOR and t["path"] == []


def test_a_lut_input_the_function_ignores_is_not_a_path():
    """The same wiring twice - I[0] from a register directly, I[1] from it the long way
    round - differing only in which input the last LUT's function uses. Only a used
    input is a path."""
    buf1 = int("CC" * (1 << (B.LUT_K - 3)), 16)                   # O = I[1]

    def word(init):
        d = B.Design()
        pos = _clbs(4)
        q = d.lut(*pos[0], BUF, [B.Cell(*pos[3], "o")], ff_en=1)
        far = d.lut(*pos[2], BUF, [d.lut(*pos[1], BUF, [q])])
        d.lut(*pos[3], init, [q, far], ff_en=1)
        return d.build().to_int()

    near, long_way = T.analyse(word(BUF), UNIT), T.analyse(word(buf1), UNIT)
    assert near["cpd_ns"] + 2 * UNIT["ns"]["lut"] <= long_way["cpd_ns"]


def test_clock_for_refuses_a_rate_the_design_cannot_make():
    t = T.analyse(_chain(3), UNIT)
    assert T.clock_for(t) == (t["gap_cycles"], t["gap_cycles"], 0)
    slow = B.SYSCLK_HZ / (t["gap_cycles"] * 3)
    assert T.clock_for(t, slow)[:3:2] == (t["gap_cycles"] * 3, 0)
    # a rate too slow for clk_period alone is prescaled by clk_div, still an integer period
    period, _gap, div = T.clock_for(t, 10.0)
    assert div > 0 and period <= T.PERIOD_MAX
    assert B.guest_hz("run", div, period, _gap) == pytest.approx(10.0, rel=1e-3)
    # a rate the fabric could make but this design cannot: the constraint report
    slow_design = T.analyse(_chain(3), UNIT, margin=4.0)
    too_fast = 1e9 / (slow_design["cpd_ns"] * 4.0 - 1.0)
    with pytest.raises(T.TimingViolation, match="timing not met"):
        T.clock_for(slow_design, too_fast)
    # and one no design can make: faster than the fabric's 2-cycle floor
    with pytest.raises(T.SdcError, match="fastest clock is 16 ns"):
        T.clock_for(t, B.SYSCLK_HZ / 1.5)


def test_the_committed_delays_are_complete_and_labelled():
    d = T.load_delays()
    assert d["source"] and all(v >= 0 for v in d["ns"].values())
    assert d.get("provisional") in (True, False)


needs_tools = pytest.mark.skipif(shutil.which("yosys") is None or shutil.which("iverilog") is None,
                                 reason="needs yosys and iverilog")


@needs_tools
def test_hz_auto_writes_the_clock_and_the_board_runs_at_it(tmp_path):
    from fakeboard import FakeBob
    import cli
    src = [os.path.join(ROOT, "work", "examples", "counter", "counter.v")]
    res = flow.Flow(src, out=str(tmp_path / "c.bit"), clock="run", hz="auto").run()
    assert res.ok, res.error
    st = [s for s in res.stages if s.name == "timing"][0]
    meta = bitgen.read_bit(res.bit)["meta"]
    assert meta["period"] == meta["gap"] == st.stats["gap"] > 0
    bs = B.Bitstream(res.word)
    assert bs.get_ctrl("clk_period") == meta["period"] and bs.get_ctrl("clk_gap") == meta["gap"]
    p = FakeBob(rate_scale=1e-5)                    # the software board at a watchable rate
    ok, msg = cli.load(p, res.bit, log=lambda *_: None)
    assert ok, msg
    hz = B.guest_hz("run", 0, meta["period"], meta["gap"])
    assert hz == pytest.approx(B.SYSCLK_HZ / meta["period"])
    # the model check still ran on the timed build
    assert [s for s in res.stages if s.name == "model"][0].ok


@needs_tools
def test_a_rate_faster_than_the_design_is_refused(tmp_path):
    src = [os.path.join(ROOT, "work", "examples", "big", "big.v")]
    res = flow.Flow(src, out=str(tmp_path / "b.bit"), clock="run", hz=B.SYSCLK_HZ / 2).run()
    assert not res.ok and "timing not met" in res.error and "slack -" in res.error
    assert [s.name for s in res.stages][-1] == "timing"


def test_hz_needs_the_free_running_clock():
    with pytest.raises(flow.FlowError, match="clock run"):
        flow.Flow(["x.v"], clock="jtag", hz="auto")
    assert flow.Flow(["x.v"], hz="auto").clock == "run"          # unset: the clock hz implies
    with pytest.raises(flow.FlowError, match="hz is auto"):
        flow.Flow(["x.v"], clock="run", hz="fast")


# --- the clock constraint (SDC) --------------------------------------------------------


def _sdc(tmp_path, text, name="c.sdc"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


@pytest.mark.parametrize("text,period,name", [
    ("create_clock -period 50 [get_ports clk]\n", 50.0, "clk"),
    ("# 20 MHz\ncreate_clock -period 50.000 -name sys [get_ports {clk}]  # the fabric clock\n", 50.0, "sys"),
    ("create_clock -name clk -period 12.5 -waveform {0 6.25} [get_ports clk]\n", 12.5, "clk"),
    ("create_clock -period 40 \\\n    -name clk [get_ports clk]\n", 40.0, "clk"),
])
def test_read_sdc_takes_vivado_s_create_clock(tmp_path, text, period, name):
    c = T.read_sdc(_sdc(tmp_path, text))
    assert c["period_ns"] == period and c["name"] == name


@pytest.mark.parametrize("text,why", [
    ("set_input_delay 2 [get_ports sw]\n", "not supported"),
    ("create_clock -period 50 [get_ports clk]\ncreate_clock -period 20 [get_ports clk]\n", "second create_clock"),
    ("create_clock [get_ports clk]\n", "needs -period"),
    ("create_clock -period fast [get_ports clk]\n", "nanoseconds"),
    ("create_clock -period 50 [get_ports sysclk]\n", "clk port"),
    ("# nothing\n", "no create_clock"),
])
def test_read_sdc_refuses_what_the_fabric_cannot_mean(tmp_path, text, why):
    with pytest.raises(T.SdcError, match=why):
        T.read_sdc(_sdc(tmp_path, text))


def test_constrain_reports_slack_and_never_clocks_faster_than_asked():
    t = T.analyse(_chain(3), UNIT, margin=1.25)
    need = t["cpd_ns"] * 1.25
    ok = T.constrain(t, need + 10.0)
    assert ok["met"] and ok["slack_ns"] == pytest.approx(10.0, abs=1e-3)
    assert ok["achieved_ns"] >= ok["period_ns"] and ok["achieved_ns"] - ok["period_ns"] < T.SYSCLK_NS
    with pytest.raises(T.TimingViolation) as e:
        T.constrain(t, need - 1.0, origin="c.sdc:1")
    msg = str(e.value)
    assert "timing not met" in msg and "slack -1.000 ns" in msg and "c.sdc:1" in msg
    assert "the fastest this design can run" in msg
    with pytest.raises(T.SdcError, match="fastest clock is 16 ns"):
        T.constrain(t, 10.0)


@needs_tools
def test_a_met_constraint_sets_the_clock_and_records_the_slack(tmp_path):
    src = [os.path.join(ROOT, "work", "examples", "counter", "counter.v")]
    sdc = _sdc(tmp_path, "create_clock -period 200 -name clk [get_ports clk]\n")
    res = flow.Flow(src, out=str(tmp_path / "c.bit"), sdc=sdc).run()
    assert res.ok, res.error
    meta = bitgen.read_bit(res.bit)["meta"]
    assert meta["clock"] == "run" and meta["period"] == 25 and meta["period_ns"] == 200.0
    assert meta["slack_ns"] > 0 and meta["slack_ns"] == pytest.approx(200 - meta["cpd_ns"] * 2.0, abs=0.01) \
        or meta["slack_ns"] == pytest.approx(200 - meta["cpd_ns"] * 1.25, abs=0.01)
    st = [s for s in res.stages if s.name == "timing"][0]
    assert "met" in st.detail and st.stats["slack_ns"] == meta["slack_ns"]


@needs_tools
def test_a_missed_constraint_fails_the_build_and_writes_no_bit(tmp_path):
    src = [os.path.join(ROOT, "work", "examples", "big", "big.v")]
    sdc = _sdc(tmp_path, "create_clock -period 20 [get_ports clk]\n")
    out = tmp_path / "b.bit"
    res = flow.Flow(src, out=str(out), sdc=sdc).run()
    assert not res.ok and "timing not met" in res.error and "slack -" in res.error
    assert not out.exists()
    st = res.stages[-1]
    assert st.name == "timing" and st.ok is False and st.stats["slack_ns"] < 0


def test_a_constraint_does_not_mix_with_a_stepped_clock_or_hz(tmp_path):
    sdc = _sdc(tmp_path, "create_clock -period 100 [get_ports clk]\n")
    with pytest.raises(flow.FlowError, match="drop --clock jtag"):
        flow.Flow(["x.v"], clock="jtag", sdc=sdc)
    with pytest.raises(flow.FlowError, match="not both"):
        flow.Flow(["x.v"], sdc=sdc, hz="auto")
    with pytest.raises(flow.FlowError, match="not supported"):
        flow.Flow(["x.v"], sdc=_sdc(tmp_path, "set_false_path -from x\n", "bad.sdc"))


def test_delay_samples_name_this_device():
    """hw/scripts/delay_samples.txt (delays.py plan) must be regenerated when the device
    changes: every sampled hop must be two nets of this fabric, or the build times nothing
    (M21: a plan left from an earlier architecture would fold to no measurement at all)."""
    import delays
    lines = [ln.split() for ln in open(delays.SAMPLES) if ln.strip() and ln[0] != "#"]
    assert lines
    for cls, a, b in lines:
        if cls == "ffq":
            assert delays._node(b) is not None, (cls, b)
        elif cls == "ffd":
            assert delays._node(a) is not None, (cls, a)
        else:
            assert delays._node(a) is not None and delays._node(b) is not None, (cls, a, b)


# --- the contract with the XDC (M21) ---------------------------------------------------
#
# The XDC's sysclk multicycle no longer covers the fabric (hw/constr/pynq_z2.xdc): Vivado
# cannot time an unconfigured mesh of loops. What makes a design safe is now that its own
# critical path fits the gce spacing it runs at, and timing.contract() is that check. The
# flow runs it on every build and cli.load on every .bit; these tests hold both to it.

SLOW = {**UNIT, "ns": {k: v * 1000.0 for k, v in UNIT["ns"].items()}}   # microsecond hops


def _with_gap(word, gap):
    bs = B.Bitstream(word)
    bs.set_ctrl(B.CLOCK_MODES["run"], 0, max(gap, 1), gap)
    return bs.to_int()


def test_the_spacing_is_clk_gap_or_the_default():
    w = _chain(1)
    assert T.spacing(w) == T.GAP_DEFAULT == 1 << B.DEVICE["clock"]["gce_min_gap_shift"]
    assert T.spacing(_with_gap(w, 40)) == 40
    assert T.spacing(_with_gap(w, 1)) == T.GAP_FLOOR               # the hardware floor wins


def test_the_contract_holds_a_word_to_its_own_spacing():
    w = _chain(3)
    t = T.check_contract(w, UNIT)                                   # a few ns: fits 512 cycles
    assert t["spacing"] == T.GAP_DEFAULT
    slow = T.analyse(w, SLOW)
    assert slow["gap_cycles"] > T.GAP_DEFAULT                       # longer than the default...
    with pytest.raises(T.TimingViolation, match="default for clk_gap 0"):
        T.check_contract(w, SLOW)
    ok = _with_gap(w, slow["gap_cycles"])                           # ... unless clk_gap covers it
    assert T.check_contract(ok, SLOW)["spacing"] == slow["gap_cycles"]
    with pytest.raises(T.TimingViolation, match=f"spaces them {slow['gap_cycles'] - 1} "):
        T.check_contract(_with_gap(w, slow["gap_cycles"] - 1), SLOW)


def test_the_contract_refuses_a_combinational_loop():
    d = B.Design()
    (xa, ya), (xb, yb), pos = *_clbs(2), _clbs(3)[2]
    a = d.lut(xa, ya, BUF, [B.Cell(xb, yb, "o")])
    b = d.lut(xb, yb, BUF, [a])
    d.output(0, d.lut(*pos, BUF, [b], ff_en=1))
    with pytest.raises(T.TimingError, match="combinational loop"):
        T.check_contract(d.build().to_int(), UNIT)


def _slow_delays(tmp_path, monkeypatch):
    import json
    path = tmp_path / "delays.json"
    path.write_text(json.dumps({**SLOW, "ns": {**SLOW["ns"], "mux_xbar": 1000.0}}))
    monkeypatch.setattr(T, "DELAYS", str(path))


def test_load_refuses_a_bit_that_breaks_the_contract(tmp_path, monkeypatch):
    """cli.load (and so ./bob load, bob studio and the board checks that load a .bit) sends
    nothing when the design's path is longer than its spacing."""
    from fakeboard import FakeBob
    import cli
    bit = str(tmp_path / "c.bit")
    bitgen.write_bit(bit, _chain(3), {}, {"design": "chain3"})
    p = FakeBob()
    ok, msg = cli.load(p, bit, log=lambda *_: None)
    assert ok, msg
    _slow_delays(tmp_path, monkeypatch)
    for load in (lambda: cli.load(p, bit, log=lambda *_: None),
                 lambda: cli.load(p, bit, mode="chain", log=lambda *_: None),
                 lambda: cli.load_partial(p, bit)):
        ok, msg = load()
        assert not ok and "timing contract" in msg, msg
    # the board's clock-margin sweep may run a design past its clock on purpose ...
    ok, msg = cli.load(p, bit, log=lambda *_: None, over_clock=True)
    assert ok, msg


def test_over_clocking_still_refuses_a_loop(tmp_path):
    """... but never a combinational loop"""
    from fakeboard import FakeBob
    import cli
    d = B.Design()
    (xa, ya), (xb, yb), pos = *_clbs(2), _clbs(3)[2]
    a = d.lut(xa, ya, BUF, [B.Cell(xb, yb, "o")])
    d.output(0, d.lut(*pos, BUF, [d.lut(xb, yb, BUF, [a])], ff_en=1))
    bit = str(tmp_path / "loop.bit")
    bitgen.write_bit(bit, d.build().to_int(), {}, {"design": "loop"})
    ok, msg = cli.load(FakeBob(), bit, log=lambda *_: None, over_clock=True)
    assert not ok and "combinational loop" in msg, msg


@needs_tools
def test_the_flow_refuses_a_design_that_breaks_the_contract(tmp_path, monkeypatch):
    """A stepped build has no clock constraint, but it still runs at the default spacing:
    the timing stage fails it and no .bit is written."""
    src = [os.path.join(ROOT, "work", "examples", "counter", "counter.v")]
    _slow_delays(tmp_path, monkeypatch)
    out = tmp_path / "c.bit"
    res = flow.Flow(src, out=str(out), clock="jtag").run()
    assert not res.ok and "timing contract" in res.error, res.error
    st = res.stages[-1]
    assert st.name == "timing" and st.ok is False and st.stats["spacing"] == T.GAP_DEFAULT
    assert not out.exists()
    # --hz auto sets clk_gap from the same path, so the same design builds
    res = flow.Flow(src, out=str(out), hz="auto").run()
    assert res.ok, res.error


def _hand_designs():
    """Every hand-written design the board checks load straight through cfgplane,
    bypassing cli.load: each d_* builder at its defaults, and the variant tables."""
    import inspect
    import designs as D
    for name, fn in sorted(vars(D).items()):
        if name.startswith("d_") and callable(fn) and all(
                p.default is not p.empty for p in inspect.signature(fn).parameters.values()):
            yield name, fn
    for key, s0, s1 in D.DSP_JTAG_VARIANTS:
        yield f"d_dsp_jtag[{key}]", lambda s0=s0, s1=s1: D.d_dsp_jtag(s0, s1)
    for key, kw in D.BRAM_JTAG_VARIANTS:
        yield f"d_bram_jtag[{key}]", lambda kw=kw: D.d_bram_jtag(**kw)
    for gate in ("and", "or"):
        yield f"d_partial[{gate}]", lambda g=gate: D.d_partial(g)
        yield f"d_partial_cluster[{gate}]", lambda g=gate: D.d_partial_cluster(g)


@pytest.mark.parametrize("name,fn", list(_hand_designs()), ids=lambda v: v if isinstance(v, str) else "fn")
def test_every_hand_design_keeps_the_contract(name, fn):
    t = T.check_contract(fn().build().to_int())
    assert t["gap_cycles"] <= t["spacing"]
