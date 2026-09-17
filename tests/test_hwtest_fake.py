"""
hwtest's M10 and M11 checks against a software stand-in for the board: FakeBob answers the
JTAG instructions the checks use (JPROGRAM, CFG_CTRL, CFG_IN/OUT, JSTART, USER1
autostep, INTEST, SAMPLE, CAPTURE, USER4 BRAM write/read) from tools/bob/model.py,
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
sys.path.insert(0, os.path.join(ROOT, "tools", "bob"))
sys.path.insert(0, os.path.join(ROOT, "host"))

pytestmark = pytest.mark.skipif(shutil.which("yosys") is None or shutil.which("iverilog") is None,
                                reason="needs yosys and iverilog")

import bitstream as B  # noqa: E402
import cfgplane  # noqa: E402
import chainbits  # noqa: E402
import hwtest  # noqa: E402
import model  # noqa: E402
import packets  # noqa: E402

IR = {v: k for k, v in cfgplane.IR.items()}


class FakeBob:
    def __init__(self, corrupt_capture=False, corrupt_sample=False, rate_scale=1.0, switches=lambda t: 0,
                 ignore_freeze=False, wipe_on_partial=False):
        self.ir = "IDCODE"
        self.chain = 0
        self.expected = 0
        self.count = 0
        self.committed = self.done = 0
        self.user1 = 0
        self.bsr_in = 0                     # pad_i as the INTEST update cells hold it
        self.fab = None
        self.brams = {}
        self.target = 0
        self.ptr = 0
        self.corrupt_capture = corrupt_capture
        self.frames = packets.Controller()          # M13: the frame path on CFG_IN / CFG_OUT
        self.corrupt_sample = corrupt_sample
        self.rate_scale = rate_scale
        self.switches = switches            # time -> pad_i of the real board inputs
        self.rdata = 0
        self.ignore_freeze = ignore_freeze          # broken board: the user clock runs on while frozen
        self.wipe_on_partial = wipe_on_partial      # broken board: a partial reload loses the state
        self.t_last = time.time()

    def _pins(self):
        return self.switches(time.time())

    def _sync_brams_to_frames(self):
        """the frame model sees the BRAM contents as the design (or the last load) left them"""
        for b in range(B.NBRAM):
            if self.fab:
                self.frames.brams[b] = list(self.fab.brams[b].mem) + [0] * (1024 - len(self.fab.brams[b].mem))
            elif b in self.brams:
                self.frames.brams[b] = list(self.brams[b]) + [0] * (1024 - len(self.brams[b]))

    def _held(self):
        return self.frames.frozen() and not self.ignore_freeze

    def _run(self):
        """free-running clock: catch up on the edges that happened since JSTART"""
        now, last = time.time(), self.t_last
        self.t_last = now
        if not self.done or not (self.chain >> B.CTRL_FIELD["clk_mode"][0]) & 1:
            return
        if self._held():                             # M14: frozen time does not count
            self.t_start += now - last
            return
        off, w = B.CTRL_FIELD["clk_div"]
        hz = 125e6 / 2 ** (((self.chain >> off) & ((1 << w) - 1)) + B.DIV_MIN_SHIFT) * self.rate_scale
        due = int((time.time() - self.t_start) * hz)
        pins = self.bsr_in if self.ir == "INTEST" else self._pins()     # INTEST: the boundary drives the fabric
        while self.clocks < due:
            self.fab.clock(pad_i=pins, cin=(self.user1 >> 2) & 1)
            self.clocks += 1

    # --- probe API used by cfgplane / fpga / hwtest ---
    def shift_ir(self, code, width=6):
        self._run()
        errs = self.frames.errors() if hasattr(self, "frames") else 0
        cap = (0b000001 | (self.done << 5) | (int(not errs) << 4) | (self.committed << 3)
               | ((self.frames.flags["crc_err"] if errs else 0) << 2))
        self.ir = IR[code]
        if self.ir == "JPROGRAM":
            self.done = self.committed = 0
            self.frames.jprogram()
        return cap

    def pulse(self, tms=0, tdi=0):
        if self.ir == "JSTART" and (self.committed or self.frames.flags["start_ok"]) and not self.done:
            self.done = 1
            self.fab = model.Fabric(B.Bitstream(self.chain))
            self.fab.clock(gsr=1)
            for b, words in self.brams.items():
                self.fab.brams[b].mem = list(words)
            self.t_start, self.clocks = time.time(), 0

    def reset_to_idle(self):
        self.ir = "IDCODE"

    def read_idcode(self):
        return packets.device_idcode()

    def shift_dr_fast(self, n, din=0):
        return self.shift_dr(n, din)

    def shift_dr(self, n, din=0):
        self._run()
        ir = self.ir
        if ir == "JPROGRAM":
            return 0
        if ir == "CFG_IN":                           # M13 frame path
            self.frames.gwe = int(self.done)
            self.frames.mem = self.chain
            self._sync_brams_to_frames()
            before = [list(x) for x in self.frames.brams]
            self.frames.shift_in(n, din)
            for b in range(B.NBRAM):                 # M15: BRAM content frames
                if self.frames.brams[b] != before[b]:
                    self.brams[b] = list(self.frames.brams[b])
                    if self.fab:
                        self.fab.brams[b].mem = list(self.frames.brams[b])
            if self.done and self.frames.mem != self.chain:     # M14: partial while running
                old = self.fab
                self.fab = model.Fabric(B.Bitstream(self.frames.mem))
                if not self.wipe_on_partial:
                    self.fab.q, self.fab.brams, self.fab.dsp = old.q, old.brams, old.dsp
                    self.fab.bram_drive, self.fab.dsp_drive = old.bram_drive, old.dsp_drive
                    self.fab.bram = self.fab.brams[0] if self.fab.brams else None
            self.chain = self.frames.mem
            return 0
        if ir == "CFG_OUT":
            self._sync_brams_to_frames()
            words = [self.frames.read_word(gsr=int(not self.done), gts=int(not self.done),
                                           gwe=int(self.done), done=int(self.done))
                     for _ in range((n + 31) // 32)]
            return packets.to_jtag(words)[1] & ((1 << n) - 1)
        if ir == "CFG_CTRL":
            out = (self.expected | (self.count << 32) | (int(chainbits.crc32c_bits(self.chain, B.CHAIN_W)
                   == self.expected) << 48) | (self.committed << 51) | (self.done << 55)
                   | (chainbits.CTRL_VERSION << 56))
            if din >> 56 == chainbits.CTRL_KEY:          # only the expected CRC (cfg_ctrl.v)
                self.expected = din & 0xFFFFFFFF
            return out
        if ir == "CHAIN_IN":                         # M12b: frames streamed, only while GWE = 0
            self.count = n
            good = chainbits.crc32c_bits(din, n) == self.expected and n == B.CHAIN_W
            if not self.done:
                fb = B.DEVICE["frames"]["bits"]
                for f in range(min(n // fb, B.CHAIN_W // fb)):
                    mask = ((1 << fb) - 1) << (f * fb)
                    self.chain = (self.chain & ~mask) | (din & mask)
                if good:
                    self.committed = 1
            self.brams = {}
            return 0
        if ir == "CHAIN_OUT":                        # memory, then TDI delayed by one frame
            fb = B.DEVICE["frames"]["bits"]
            low = (1 << B.CHAIN_W) - 1
            return (self.chain & low) | ((din << fb) & ~low & ((1 << n) - 1))
        if ir == "USER1":
            self.user1 = din
            return 0
        if ir == "BRAM":
            cmd, payload = din >> 92, din & ((1 << 64) - 1)
            if cmd == 5:
                self.target = payload
            elif cmd == 1:
                self.ptr = payload
            elif cmd == 2:
                self.brams.setdefault(self.target, [0] * 1024)[self.ptr] = payload
                self.ptr += 1
            out = (self.target << 66) | (cfgplane.BRAM_VERSION << 88) | self.rdata
            if cmd == 3 and not self.done:          # READ only while GWE = 0: memory as the design left it
                mem = self.fab.brams[self.target].mem if self.fab else self.brams.get(self.target, [0] * 1024)
                self.rdata = mem[self.ptr]
                self.ptr += 1
            return out
        if ir == "INTEST":
            leds = self.fab.outputs(self.bsr_in, cin=(self.user1 >> 2) & 1)
            raw = sum(((leds >> k) & 1) << pad for k, pad in enumerate(B.BOARD_OUT))
            self.bsr_in = sum(((din >> (B.NPAD + pad)) & 1) << k for k, pad in enumerate(B.BOARD_IN))
            if self.user1 & 0x10 and not self._held():
                self.fab.clock(pad_i=self.bsr_in, cin=(self.user1 >> 2) & 1)
            return raw
        if ir == "SAMPLE":
            pins = self._pins()
            leds = self.fab.outputs(pins) ^ (1 if self.corrupt_sample else 0)
            return (sum(((leds >> k) & 1) << pad for k, pad in enumerate(B.BOARD_OUT))
                    | sum(((pins >> k) & 1) << (B.NPAD + pad) for k, pad in enumerate(B.BOARD_IN)))
        if ir == "CAPTURE":
            v = self.fab.clb_o(self._pins(), cin=(self.user1 >> 2) & 1)      # IR is not INTEST: the pads read the real switches
            return v ^ ((1 << B.NCLB) - 1) if self.corrupt_capture else v
        return 0


@pytest.mark.parametrize("name", ["counter", "ram", "gates_swapped"])
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
