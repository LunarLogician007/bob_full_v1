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
    ok, msg = getattr(hwtest, check)(FakeBob(rate_scale=1e-4), {})     # the ROM runs free at div 0
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
