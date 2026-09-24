"""
hwtest's checks against a software stand-in for the board. FakeBob (software/host/fakeboard.py,
promoted out of this file once bob studio needed it too) answers the
JTAG instructions the checks use (JPROGRAM, CFG_CTRL, CFG_IN/OUT, JSTART, USER1
autostep, INTEST, SAMPLE, CAPTURE, USER4 BRAM write/read) from software/bob/model.py,
and runs the free-running user clock in real time (ctrl.clk_mode / clk_div). It cannot find
hardware problems; it proves the checks' own scan ordering, bit indexing and
golden comparisons before they meet the board, and that they can fail.
"""

import os
import shutil
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

pytestmark = pytest.mark.skipif(shutil.which("yosys") is None or shutil.which("iverilog") is None,
                                reason="needs yosys and iverilog")

import bitstream as B  # noqa: E402
import cfgplane  # noqa: E402
import hwtest  # noqa: E402
import model  # noqa: E402
from fakeboard import FakeBob  # noqa: E402
from bitstream import CLB_N, LUT_K  # noqa: E402
from designs import snake_order  # noqa: E402

IR = {v: k for k, v in cfgplane.IR.items()}





@pytest.mark.parametrize("name", ["counter", "ram", "gates_swapped", "big"])
def test_m10_check_passes_on_a_good_board(name):
    ok, msg = hwtest._bob_check(name)(FakeBob(), {})
    assert ok, msg


def test_m10_check_fails_when_capture_is_wrong():
    ok, msg = hwtest._bob_check("counter")(FakeBob(corrupt_capture=True), {})
    assert not ok and "CAPTURE" in msg


def _wiggle(t):
    """a person flipping switches and pressing buttons: a new input vector every 0.3 s"""
    return (int(t / 0.3) * 0x2D) % 64


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(hwtest, "LIVE_SECONDS", 2.0)


@pytest.mark.parametrize("name", ["switches", "fir"])
def test_m11_live_passes_on_a_good_board(name, quick):
    ok, msg = hwtest._live_check(name)(FakeBob(switches=_wiggle), {})
    assert ok, msg
    assert "live samples" in msg and "not a terminal" in msg


def _fast_person(t):
    return (int(t / 0.08) * 0x2D) % 64          # every one of the 64 input vectors within 5 s


@pytest.fixture
def at_the_board(monkeypatch):
    """interactive mode: Enter is pressed at once, goals must be reached"""
    monkeypatch.setattr(hwtest, "_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    monkeypatch.setattr(hwtest, "LIVE_TIMEOUT", 25.0)


@pytest.mark.parametrize("name", ["switches", "fir", "mult"])
def test_m11_live_goals_reached_by_a_person(name, at_the_board):
    ok, msg = hwtest._live_check(name)(FakeBob(switches=_fast_person, rate_scale=4), {})
    assert ok and "all goals reached" in msg, msg


def test_m11_live_fails_when_nobody_touches_the_switches(at_the_board, monkeypatch):
    monkeypatch.setattr(hwtest, "LIVE_TIMEOUT", 2.0)
    ok, msg = hwtest._live_check("switches")(FakeBob(switches=lambda t: 0), {})
    assert not ok and "goals not reached" in msg


def test_m11_live_blinky_goal_is_automatic():
    ok, msg = hwtest._live_check("blinky")(FakeBob(rate_scale=8), {})
    assert ok and "all goals reached" in msg, msg


def test_m11_live_fails_when_leds_are_wrong(quick):
    ok, msg = hwtest._live_check("switches")(FakeBob(switches=_wiggle, corrupt_sample=True), {})
    assert not ok and "model" in msg


def test_m11_rate():
    assert hwtest.check_blinky_rate(FakeBob(), {})[0]
    ok, msg = hwtest.check_blinky_rate(FakeBob(rate_scale=1.5), {})
    assert not ok, msg


def test_m11_ram_readback():
    ok, msg = hwtest.check_ram_readback(FakeBob(), {})
    assert ok, msg


def test_m11_ram_readback_fails_when_memory_differs():
    class BadRam(FakeBob):
        def shift_dr(self, n, din=0):
            out = super().shift_dr(n, din)
            return out ^ 1 if self.ir == "BRAM" and not self.done else out
    ok, msg = hwtest.check_ram_readback(BadRam(), {})
    assert not ok and "bram0" in msg


@pytest.mark.parametrize("name", ["counter", "ram", "gates_swapped"])
def test_m12_python_pnr_check_passes_on_a_good_board(name):
    ok, msg = hwtest._bob_check(name, pnr="python")(FakeBob(), {})
    assert ok, msg


def test_m12_python_pnr_check_fails_when_capture_is_wrong():
    ok, msg = hwtest._bob_check("counter", pnr="python")(FakeBob(corrupt_capture=True), {})
    assert not ok and "CAPTURE" in msg


def test_m12_live_python_pnr(at_the_board):
    ok, msg = hwtest._live_check("switches", pnr="python")(FakeBob(switches=_fast_person, rate_scale=4), {})
    assert ok and "all goals reached" in msg, msg


@pytest.mark.parametrize("check", ["frames_load", "frames_crc_reject", "frames_idcode_reject",
                                   "frames_live_refused", "frames_vs_chain"])
def test_m13_frame_checks_pass_on_a_good_board(check):
    ok, msg = getattr(hwtest, f"check_{check}")(FakeBob(), {})
    assert ok, msg


def test_m13_frames_live_refused_fails_if_the_board_accepts_writes_while_running():
    class Reckless(FakeBob):
        def shift_dr(self, n, din=0):
            if self.ir == "CFG_IN":
                self.frames.gwe = 0                  # a board that ignores GWE
                self.frames.mem = self.chain
                self.frames.shift_in(n, din)
                self.chain = self.frames.mem
                return 0
            return super().shift_dr(n, din)
    ok, msg = hwtest.check_frames_live_refused(Reckless(), {})
    assert not ok, msg


def test_m13_crc_reject_fails_if_the_board_ignores_the_crc():
    class NoCrc(FakeBob):
        def shift_dr(self, n, din=0):
            out = super().shift_dr(n, din)
            if self.ir == "CFG_IN":
                self.frames.flags["crc_err"] = 0
                self.frames.flags["start_ok"] = 1
                self.frames.st = "hdr"
            return out
    ok, msg = hwtest.check_frames_crc_reject(NoCrc(), {})
    assert not ok, msg


# --- M14: partial reconfiguration --------------------------------------------------------

@pytest.mark.parametrize("check", ["check_partial_swap", "check_partial_bad_crc", "check_partial_guest"])
def test_m14_partial_checks_pass_on_a_good_board(check):
    ok, msg = getattr(hwtest, check)(FakeBob(), {})
    assert ok, msg


def test_m14_partial_live_passes_on_a_good_board():
    ok, msg = hwtest.check_partial_live(FakeBob(rate_scale=1.0), {})
    assert ok, msg


def test_m14_partial_swap_fails_when_state_is_lost():
    ok, msg = hwtest.check_partial_swap(FakeBob(wipe_on_partial=True), {})
    assert not ok, msg


def test_m14_partial_live_fails_when_the_freeze_does_not_hold():
    ok, msg = hwtest.check_partial_live(FakeBob(ignore_freeze=True), {})
    assert not ok, msg


def test_m14_bad_crc_fails_when_the_freeze_does_not_hold():
    ok, msg = hwtest.check_partial_bad_crc(FakeBob(ignore_freeze=True), {})
    assert not ok, msg


# --- M15: BRAM contents as frames ---------------------------------------------------------

@pytest.mark.parametrize("check", ["check_frames_bram_load", "check_frames_bram_live_refused",
                                   "check_ram_readback_frames"])
def test_m15_bram_frame_checks_pass_on_a_good_board(check):
    ok, msg = getattr(hwtest, check)(FakeBob(rate_scale=2e-4), {})     # the ROM runs free at div 0 (M21: the default rate halved)
    assert ok, msg


def test_m15_bram_live_refused_fails_if_frames_write_while_running():
    class Leaky(FakeBob):
        def shift_dr(self, n, din=0):
            if self.ir == "CFG_IN":
                self.frames.gwe = 0                  # broken: ignores GWE for everything
                done, self.done = self.done, 0
                try:
                    return super().shift_dr(n, din)
                finally:
                    self.done = done
            return super().shift_dr(n, din)
    ok, msg = hwtest.check_frames_bram_live_refused(Leaky(rate_scale=1e-4), {})
    assert not ok, msg


# --- M18: the block-design project ------------------------------------------------


@pytest.mark.parametrize("pnr", ["vpr", "python"])
def test_m18_project_check_passes_on_a_good_board(pnr):
    ok, msg = hwtest._bob_check("bd_demo", pnr=pnr)(FakeBob(), {})
    assert ok, msg
    assert "CAPTUREs" in msg


def test_m18_project_check_fails_when_capture_is_wrong():
    ok, msg = hwtest._bob_check("bd_demo")(FakeBob(corrupt_capture=True), {})
    assert not ok and "CAPTURE" in msg


def test_m18_live_goals_reached_by_a_person(at_the_board):
    ok, msg = hwtest._live_check("bd_demo")(FakeBob(switches=_fast_person, rate_scale=4), {})
    assert ok and "all goals reached" in msg, msg


def test_m18_live_fails_when_nobody_touches_the_switches(at_the_board, monkeypatch):
    monkeypatch.setattr(hwtest, "LIVE_TIMEOUT", 2.0)
    ok, msg = hwtest._live_check("bd_demo")(FakeBob(switches=lambda t: 0), {})
    assert not ok and "goals not reached" in msg


def test_m18_live_fails_when_leds_are_wrong(quick):
    ok, msg = hwtest._live_check("bd_demo")(FakeBob(switches=_wiggle, corrupt_sample=True), {})
    assert not ok and "model" in msg


def test_m18_goals_are_not_met_by_idle_inputs():
    """The stimulus must exercise the design: no single held input vector ticks every goal."""
    goals = hwtest.LIVE_GUIDE["bd_demo"]["goals"]
    for i in range(64):
        h = {}
        met = sum(bool(fn(i, leds, h)) for _l, fn in goals for leds in range(8))
        assert met < len(goals) * 8


# --- M19: the waveform viewer on the board ------------------------------------------


def test_m19_wave_step_passes_on_a_good_board():
    ok, msg = hwtest.check_wave_step(FakeBob(), {})
    assert ok and "== source Verilog" in msg, msg


def test_m19_wave_step_fails_when_the_board_loses_clocks():
    ok, msg = hwtest.check_wave_step(FakeBob(lose_clocks=7), {})
    assert not ok and "wrong" in msg, msg


def test_m19_wave_live_passes_on_a_good_board():
    ok, msg = hwtest.check_wave_live(FakeBob(switches=lambda t: int(t / 0.05) % 4), {})
    assert ok, msg


def test_m19_wave_live_fails_when_the_leds_are_wrong():
    ok, msg = hwtest.check_wave_live(FakeBob(switches=lambda t: int(t / 0.05) % 4, corrupt_sample=True), {})
    assert not ok and "xor" in msg, msg


# --- M20: the per-design user clock --------------------------------------------------
#
# The software board simulates every user-clock edge, so the at-speed checks run it with
# rate_scale well below 1 (tens of edges a second). max_hz is its slow-fabric fault: above
# that real rate a third of the registers miss each edge, as a setup violation would.

def _atspeed_fmax():
    import bitgen
    from bitstream import guest_hz
    path, *_rest, meta = hwtest._atspeed("vpr", "_fmax")
    return guest_hz("run", meta.get("pdiv", 0), meta["period"], meta["gap"])


@pytest.fixture
def quick_atspeed(monkeypatch):
    monkeypatch.setattr(hwtest, "ATSPEED_S", 0.6)


def test_m20_clock_rate_passes_on_a_good_board():
    ok, msg = hwtest.check_clock_rate(FakeBob(), {})
    assert ok, msg
    assert f"clk_period {hwtest.RATE_PERIOD} x 2**{hwtest.RATE_DIV}" in msg


def test_m20_clock_rate_fails_when_the_clock_is_off():
    ok, msg = hwtest.check_clock_rate(FakeBob(rate_scale=1.5), {})
    assert not ok, msg


@pytest.mark.parametrize("pnr", ["vpr", "python"])
def test_m20_clock_fmax_passes_on_a_fast_enough_fabric(pnr, quick_atspeed):
    ok, msg = hwtest._clock_fmax(pnr)(FakeBob(rate_scale=2e-5, budget=0.05), {})
    assert ok and "no error" in msg, msg


def test_m20_clock_fmax_fails_on_a_fabric_slower_than_computed(quick_atspeed):
    ok, msg = hwtest._clock_fmax("vpr")(FakeBob(rate_scale=2e-5, budget=0.05, max_hz=_atspeed_fmax() / 2), {})
    assert not ok and "too fast" in msg, msg


def test_m20_clock_margin_finds_the_edge_above_the_computed_clock(quick_atspeed):
    ok, msg = hwtest.check_clock_margin(FakeBob(rate_scale=2e-5, budget=0.05, max_hz=_atspeed_fmax() * 1.6), {})
    assert ok and "first failure" in msg and "margin" in msg, msg


def test_m20_clock_margin_fails_when_the_computed_clock_is_unsafe(quick_atspeed):
    ok, msg = hwtest.check_clock_margin(FakeBob(rate_scale=2e-5, budget=0.05, max_hz=_atspeed_fmax() * 0.7), {})
    assert not ok and "fails at the computed clock" in msg, msg


# --- M21: the cluster CLB and the BRAM-shadow readback --------------------------------

def test_m21_shadow_readback_passes_on_a_good_board():
    ok, msg = hwtest.check_shadow_readback(FakeBob(), {})
    assert ok and "all zeros" in msg, msg


def test_m21_shadow_readback_fails_when_jprogram_leaves_the_shadow():
    ok, msg = hwtest.check_shadow_readback(FakeBob(stale_shadow=True), {})
    assert not ok and "after JPROGRAM" in msg, msg


def test_m21_partial_cluster_passes_on_a_good_board():
    ok, msg = hwtest.check_partial_cluster(FakeBob(), {})
    assert ok and "FDRO == B: True" in msg, msg


def test_m21_partial_cluster_fails_when_the_clb_loses_its_state():
    ok, msg = hwtest.check_partial_cluster(FakeBob(wipe_on_partial=True), {})
    assert not ok, msg


@pytest.mark.parametrize("pnr", ["vpr", "python"])
def test_m21_fir16_passes_on_a_good_board(pnr):
    ok, msg = hwtest._bob_check("fir16", pnr=pnr)(FakeBob(), {})
    assert ok, msg


def test_m21_fir16_fails_when_capture_is_wrong():
    ok, msg = hwtest._bob_check("fir16")(FakeBob(corrupt_capture=True), {})
    assert not ok and "CAPTURE" in msg, msg


def test_m21_fir16_live_passes_on_a_good_board(quick):
    ok, msg = hwtest._live_check("fir16")(FakeBob(switches=_wiggle), {})
    assert ok, msg


def test_m21_fir16_fast_passes_on_a_fast_enough_fabric(quick):
    ok, msg = hwtest._live_check("fir16", fast=True)(FakeBob(switches=_wiggle, rate_scale=2e-5, budget=0.05), {})
    assert ok, msg


def test_m21_fir16_fast_fails_when_the_leds_disagree_with_the_model(quick):
    """A live check compares the LEDs with model.py given the captured registers, so it
    catches wrong logic at speed but not a register that missed an edge (the state it shows
    is still consistent): that is atspeed's job (fmax-cluster)."""
    ok, msg = hwtest._live_check("fir16", fast=True)(
        FakeBob(switches=_wiggle, rate_scale=2e-5, budget=0.05, corrupt_sample=True), {})
    assert not ok, msg


def test_m21_fmax_cluster_passes_and_fails(quick_atspeed):
    ok, msg = hwtest.check_fmax_cluster(FakeBob(rate_scale=2e-5, budget=0.05), {})
    assert ok and "no error" in msg, msg
    ok, msg = hwtest.check_fmax_cluster(FakeBob(rate_scale=2e-5, budget=0.05, max_hz=_atspeed_fmax() / 2), {})
    assert not ok and "too fast" in msg, msg


def test_m21_list_is_the_m20_regression_plus_the_cluster():
    names = [n for n, _c in hwtest.MILESTONE["M21"]]
    assert names[:len(hwtest.MILESTONE["M20"]) - 1] == [n for n, _c in hwtest.MILESTONE["M20"][:-1]]
    for n in ("shadow-readback", "partial-cluster", "bob-fir16", "pnr-fir16", "live-fir16", "fast-fir16",
              "fmax-cluster"):
        assert n in names
    assert names[-1] == "pipeline-live"


# --- M22: CFGLUT5 ---------------------------------------------------------------------------

def test_m22_lutram_snake_passes_on_a_good_board():
    ok, msg = hwtest.check_lutram_snake(FakeBob(), {})
    assert ok, msg
    assert f"{len(snake_order())} elements" in msg


def test_m22_lutram_snake_fails_when_the_loader_misses_the_tables():
    ok, msg = hwtest.check_lutram_snake(FakeBob(lose_lframes=True), {})
    assert not ok, msg


def test_m22_runs_the_full_m21_list_first():
    names = [n for n, _f in hwtest.MILESTONE["M22"]]
    assert names[:len(hwtest.MILESTONE["M21"]) - 1] == [n for n, _f in hwtest.MILESTONE["M21"]][:-1]
    assert "lutram-snake" in names


def test_m23_xbar_pins_passes_on_a_healthy_board():
    ok, msg = hwtest.check_xbar_pins(FakeBob(), {})
    assert ok, msg
    assert f"{len(snake_order())} elements" in msg


@pytest.mark.parametrize("j", [0, LUT_K - 1])
def test_m23_xbar_pins_fails_when_a_crossbar_input_is_dead(j):
    ok, msg = hwtest.check_xbar_pins(FakeBob(dead_xbar_pin=j), {})
    assert not ok, msg


def test_m23_lutram_snake_alone_misses_a_dead_last_pin():
    """why xbar-pins exists: the M22 snake only uses pin 0"""
    ok, msg = hwtest.check_lutram_snake(FakeBob(dead_xbar_pin=LUT_K - 1), {})
    assert ok, msg


def test_m23_xbar_pins_fails_when_the_loader_misses_the_tables():
    ok, msg = hwtest.check_xbar_pins(FakeBob(lose_lframes=True), {})
    assert not ok, msg


def test_m23_the_snake_pins_cover_every_pin_of_every_element():
    from designs import snake_pin
    seen = {(k % CLB_N, snake_pin(k)) for k in range(len(snake_order()))}
    assert seen == {(e, j) for e in range(CLB_N) for j in range(LUT_K)}


def test_m23_runs_the_full_m22_list_first():
    names = [n for n, _f in hwtest.MILESTONE["M23"]]
    assert names[:len(hwtest.MILESTONE["M22"]) - 1] == [n for n, _f in hwtest.MILESTONE["M22"]][:-1]
    assert "xbar-pins" in names
