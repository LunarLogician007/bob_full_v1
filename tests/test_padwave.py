"""
software/host/padwave.py: the pad logic analyser (M19), against the board in software.

A capture has to be right before it is pretty: a stepped capture of a design driven with
its own source trace's inputs must show, clock for clock, the LEDs the source Verilog
gives. Then the trigger, the pre-trigger window, live sampling and the VCD.
"""

import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import cli  # noqa: E402
import padwave as wave  # noqa: E402
from bitstream import BOARD_IN, BOARD_OUT, NPAD  # noqa: E402
from fakeboard import FakeBob  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("yosys") is None or shutil.which("iverilog") is None,
                                reason="needs yosys and iverilog")


def _loaded(name, tmp_path, **kw):
    src = os.path.join(ROOT, "work", "examples", name, f"{name}.v")
    path, word, contents, tr, work = cli.build([src], out=str(tmp_path / f"{name}.bit"),
                                               log=lambda *_: None, **kw)
    p = FakeBob()
    ok, msg = cli.load(p, path, log=lambda *_: None)
    assert ok, msg
    return p, tr


LEDS = ["LD0", "LD1", "LD2"]


def _leds(row, names):
    return sum(row[names.index(n)] << k for k, n in enumerate(LEDS))


def test_every_pad_is_a_signal_and_board_pins_come_first():
    sig = wave.signals()
    assert [s["name"] for s in sig[:9]] == wave.BOARD_IN_NAMES + wave.BOARD_OUT_NAMES
    assert len(sig) == 9 + 2 * (NPAD - len(BOARD_IN) - len(BOARD_OUT))
    named = wave.signals({"a[0]": BOARD_IN[0], "y[0]": 7})
    assert named[0]["port"] == "a[0]"
    assert {s["port"] for s in named if s["pad"] == 7} == {"y[0]"}


def test_a_stepped_capture_equals_the_source_verilog(tmp_path):
    """counter.v driven by its own trace's inputs: captured LEDs == source LEDs, every clock."""
    p, tr = _loaded("counter", tmp_path)
    trace = tr["trace"][:120]
    vectors = [t[0] for t in trace]
    cap = wave.capture(p, "step", len(trace), sel=wave.BOARD_IN_NAMES + LEDS,
                       stimulus={"kind": "sequence", "vectors": vectors})
    names = [s["name"] for s in cap["signals"]]
    assert cap["vectors"] == vectors
    got = [_leds(row, names) for row in cap["samples"]]
    want = [t[2] for t in trace]
    assert got == want
    assert len(set(got)) > 2, "the stimulus must make the LEDs move"
    # the input cells show the vector applied for that clock
    assert all(row[names.index("BTN0")] == (v >> 2) & 1 for row, v in zip(cap["samples"], vectors))


def test_a_trigger_keeps_its_pre_trigger_window(tmp_path):
    p, _tr = _loaded("counter", tmp_path)
    count = {"kind": "hold", "vector": 0b000100}                          # BTN0: count
    # LD2 = q[5] first rises 31 clocks in: the window before it is full (a quarter of 64)
    cap = wave.capture(p, "step", 64, sel=LEDS, trigger={"signal": "LD2", "cond": "rise"}, pre=0.25,
                       stimulus=count)
    k = cap["trigger"]
    assert k == 16 and cap["depth"] == 64
    ld2 = [row[2] for row in cap["samples"]]
    assert ld2[k] == 1 and ld2[k - 1] == 0 and set(ld2[:k]) == {0}
    # LD0 = q[3] rises 7 clocks in: only the 7 samples that exist come before it, as in an ILA
    cap = wave.capture(p, "step", 64, sel=LEDS, trigger={"signal": "LD0", "cond": "rise"}, pre=0.25,
                       stimulus=count)
    assert cap["trigger"] == 7 and cap["depth"] == 64


def test_a_trigger_that_never_fires_says_so(tmp_path):
    p, _tr = _loaded("counter", tmp_path)
    with pytest.raises(wave.WaveError, match="no trigger"):
        wave.capture(p, "step", 16, sel=LEDS, trigger={"signal": "LD2", "cond": "high"},
                     stimulus={"kind": "hold", "vector": 0}, timeout=0.5)


def test_bad_requests_are_refused():
    p = FakeBob()
    with pytest.raises(wave.WaveError):
        wave.capture(p, "sideways", 16)
    with pytest.raises(wave.WaveError):
        wave.capture(p, "step", 1)
    with pytest.raises(wave.WaveError):
        wave.capture(p, "step", 16, sel=["nope"])
    with pytest.raises(wave.WaveError):
        wave.capture(p, "step", 16, trigger={"signal": "LD0", "cond": "sometimes"})


def test_live_sampling_follows_the_switches(tmp_path):
    """switches.v on the free-running clock: LD0 = SW0 xor SW1, sampled as a person flips them."""
    src = os.path.join(ROOT, "work", "examples", "switches", "switches.v")
    # LD0 is combinational, so a slow clock (div 20, ~0.2 Hz) loses nothing and keeps the
    # software board from simulating thousands of edges a second
    path, *_ = cli.build([src], out=str(tmp_path / "sw.bit"), clock="run", div=20, log=lambda *_: None)
    p = FakeBob(switches=lambda t: int(t / 0.02) % 4)
    ok, msg = cli.load(p, path, log=lambda *_: None)
    assert ok, msg
    cap = wave.capture(p, "live", 80, sel=["SW0", "SW1", "LD0"])
    assert cap["unit"] == "s" and cap["t"] == sorted(cap["t"])
    rows = cap["samples"]
    assert all(r[2] == r[0] ^ r[1] for r in rows)
    assert len({(r[0], r[1]) for r in rows}) >= 3


def test_vcd_lists_every_change(tmp_path):
    p, _tr = _loaded("counter", tmp_path)
    cap = wave.capture(p, "step", 40, sel=LEDS, stimulus={"kind": "hold", "vector": 0b000100})
    text = wave.vcd(cap, date="now")
    assert "$var wire 1 ! led_0 $end" in text and "$enddefinitions $end" in text
    toggles = sum(1 for a, b in zip(cap["samples"], cap["samples"][1:]) if a[0] != b[0])
    assert text.count("\n1!") + text.count("\n0!") == toggles + 1
