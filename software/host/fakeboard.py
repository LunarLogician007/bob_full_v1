#!/usr/bin/env python3
"""
fakeboard.py - the bob board in software, as a drop-in for dirtyjtag.Probe.

FakeBob answers the JTAG instructions the host tools use - JPROGRAM, CFG_CTRL,
CFG_IN/CFG_OUT, JSTART, USER1 autostep, INTEST, SAMPLE, CAPTURE, USER4 BRAM
write/read, the DSP register - out of software/bob/model.py, and runs the free-running
user clock in real time from the ctrl tile's clk_mode / clk_div. It cannot find
hardware problems. What it is for is running the whole flow, and the tools built on
it, with no board attached: bob studio, and the hardware checks proving their own
scan ordering and bit indexing before they ever meet the board.

It implements exactly the surface dirtyjtag.Probe offers the rest of the host code:
shift_ir, shift_dr, shift_dr_fast, pulse, reset_to_idle, read_idcode, set_freq_khz.

Provenance: this class was written for tests/test_hwtest_fake.py, which drives every
hardware check against it with a passing AND a failing case. While M16 is in flight
that file keeps its own copy untouched; tests/test_fakeboard.py runs the same scan
sequence through both and requires identical answers, so the two cannot drift.
Folding the test onto this module is a job for the next milestone's tree.

    from fakeboard import FakeBob, probe
    p = probe("fake")          # or probe("usb") for the real Pico
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))

import bitstream as B  # noqa: E402
import cfgplane  # noqa: E402
import chainbits  # noqa: E402
import model  # noqa: E402
import packets  # noqa: E402

IR = {v: k for k, v in cfgplane.IR.items()}


class FakeBob:
    BUDGET = None                                   # seconds of simulation per scan; None: no bound

    def __init__(self, corrupt_capture=False, corrupt_sample=False, rate_scale=1.0, switches=lambda t: 0,
                 ignore_freeze=False, wipe_on_partial=False, lose_clocks=0, max_hz=None,
                 budget=None):
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
        self.lose_clocks = lose_clocks              # broken board: every Nth autostep edge never arrives
        # One simulated edge is a model.settle() - a Python fixed point over every mux,
        # about a millisecond at 100 CLBs - so a fast free-running clock asks for more
        # edges than this can run and the backlog grows without end. With a budget (in
        # seconds of simulation per scan) it skips ahead instead and counts what it
        # skipped, as the studio's board has done since M17. The real board never does.
        self.budget = budget if budget is not None else self.BUDGET
        self.skipped = 0
        self._per_edge = 0.008                      # seconds per guest clock, measured as it goes
        self.max_hz = max_hz                        # slow fabric: above this user clock (the real
                                                    # rate, before rate_scale) a third of the registers
                                                    # miss each edge, as a setup violation would
        self.steps = 0
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
        f = lambda n: (self.chain >> B.CTRL_FIELD[n][0]) & ((1 << B.CTRL_FIELD[n][1]) - 1)   # noqa: E731
        real = B.guest_hz("run", f("clk_div"), f("clk_period"), f("clk_gap"))
        hz = real * self.rate_scale
        too_fast = self.max_hz is not None and real > self.max_hz
        due = int((time.time() - self.t_start) * hz)
        if self.budget is not None and hz > 0:
            cap = max(1, int(self.budget / max(self._per_edge, 1e-6)))
            over = due - self.clocks - cap
            if over > 0:
                self.t_start += over / hz                # the guest simply ran slower
                self.skipped += over
                due -= over
        t0, before = time.time(), self.clocks
        pins = self.bsr_in if self.ir == "INTEST" else self._pins()     # INTEST: the boundary drives the fabric
        while self.clocks < due:
            held = dict(self.fab.q) if too_fast else None
            self.fab.clock(pad_i=pins, cin=(self.user1 >> 2) & 1)
            if too_fast:                                # the slow paths' registers keep their value
                for k, xy in enumerate(sorted(held)):
                    if k % 3 == self.clocks % 3:
                        self.fab.q[xy] = held[xy]
            self.clocks += 1
        ran, dt = self.clocks - before, time.time() - t0
        if ran > 0:
            self._per_edge += 0.25 * (dt / ran - self._per_edge)        # settles quickly

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
                self.steps += 1
                if not (self.lose_clocks and self.steps % self.lose_clocks == 0):
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

    # --- the rest of the dirtyjtag.Probe surface ---------------------------

    def set_freq_khz(self, khz):
        """No wire, no clock to set. Accepted so Probe and FakeBob are swappable."""
        return None


# --- choosing a board --------------------------------------------------------


def probe(kind="usb", freq_khz=100, **kw):
    """"usb": the Pico on PMODA. "fake": FakeBob. Anything else is an error."""
    if kind == "fake":
        return FakeBob(**kw)
    if kind == "usb":
        from dirtyjtag import Probe
        return Probe(freq_khz=freq_khz)
    raise ValueError(f"probe is usb or fake, not {kind}")
