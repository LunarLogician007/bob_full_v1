"""
The DirtyJTAG transport (software/host/dirtyjtag.py) against a model of the probe's firmware.

FakeBob (software/host/fakeboard.py) replaces a Probe at the method level, so it cannot see
how scans become USB packets. Here a Probe runs over PicoModel: pico-dirtyJtag V1.07's command
handler (cmd.c, pio_jtag.c) ported line for line, in front of an IEEE 1149.1 TAP with
jtag_tap6.v's edge discipline. The model also enforces what the firmware needs of its host:
packets of at most 64 bytes ending in CMD_STOP, and no packet sent while the previous one's
reply is unread (dirtyJtag.c: two packets in flight can be merged into one read).

2026-09-26: scans are batched, several pulses per packet, one round trip per packet; while
the user clock is stepped by TCK (clock mode 0, USER1 ce) every edge keeps its own round trip.
"""

import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import dirtyjtag as DJ  # noqa: E402

CMD_CLK = 0x06
IDCODE = 0x0B025093
IR_W = 6
IR = {"IDCODE": 0b001001, "USER1": 0b000010, "BIG": 0b100010, "BYPASS": 0b111111}
BIG_W = 150
BIG_CAPTURE = int("10110011100011110000" * 8, 2) & ((1 << BIG_W) - 1)

NEXT = {  # IEEE 1149.1 state machine: state -> (next if TMS 0, next if TMS 1)
    "TLR": ("RTI", "TLR"), "RTI": ("RTI", "SELDR"), "SELDR": ("CAPDR", "SELIR"),
    "CAPDR": ("SHDR", "EX1DR"), "SHDR": ("SHDR", "EX1DR"), "EX1DR": ("PADR", "UPDR"),
    "PADR": ("PADR", "EX2DR"), "EX2DR": ("SHDR", "UPDR"), "UPDR": ("RTI", "SELDR"),
    "SELIR": ("CAPIR", "TLR"), "CAPIR": ("SHIR", "EX1IR"), "SHIR": ("SHIR", "EX1IR"),
    "EX1IR": ("PAIR", "UPIR"), "PAIR": ("PAIR", "EX2IR"), "EX2IR": ("SHIR", "UPIR"),
    "UPIR": ("RTI", "SELDR"),
}


class Tap:
    """A TAP with jtag_tap6.v's discipline: state and shifts on the rising edge, TDO and the
    update latches on the falling one. DRs: IDCODE, a 32-bit USER1 word, a 150-bit BIG
    register that captures a fixed pattern, BYPASS."""

    def __init__(self):
        self.state, self.ir, self.ir_sr, self.dr, self.dr_w, self.tdo = "TLR", IR["IDCODE"], 0, 0, 1, 0
        self.user1 = 0
        self.big = 0
        self.edges = 0

    def _capture(self):
        if self.ir == IR["IDCODE"]:
            return IDCODE, 32
        if self.ir == IR["USER1"]:
            return self.user1, 32
        if self.ir == IR["BIG"]:
            return BIG_CAPTURE, BIG_W
        return 0, 1

    def clock(self, tms, tdi):
        tdo = self.tdo                                   # sampled while TCK is high
        self.edges += 1
        s = self.state
        if s == "CAPDR":
            self.dr, self.dr_w = self._capture()
        elif s == "SHDR":
            self.dr = (self.dr >> 1) | (tdi << (self.dr_w - 1))
        elif s == "CAPIR":
            self.ir_sr = 0b000001                        # the IEEE-mandated 01 in the two LSBs
        elif s == "SHIR":
            self.ir_sr = (self.ir_sr >> 1) | (tdi << (IR_W - 1))
        self.state = NEXT[s][tms]
        # falling edge
        if self.state == "UPIR":
            self.ir = self.ir_sr
        elif self.state == "UPDR":
            if self.ir == IR["USER1"]:
                self.user1 = self.dr
            elif self.ir == IR["BIG"]:
                self.big = self.dr
        elif self.state == "TLR":
            self.ir = IR["IDCODE"]
        self.tdo = (self.ir_sr & 1) if self.state == "SHIR" else (self.dr & 1) if self.state == "SHDR" else 0
        return tdo


class PicoModel:
    """pico-dirtyJtag V1.07 cmd_handle() on a Tap, as the two USB endpoints a Probe uses"""

    def __init__(self, tap):
        self.tap, self.replies, self.log = tap, [], []
        self.tdi = self.tms = self.last_tdo = 0

    # --- ep_out --------------------------------------------------------------------------
    def write(self, data):
        data = bytes(data)
        assert len(data) <= DJ.PACKET_BYTES, f"a {len(data)}-byte packet: the firmware reads 64"
        assert data[-1] == DJ.CMD_STOP, "a packet ends with CMD_STOP"
        assert not self.replies, "a packet sent before the last reply was read (two in flight)"
        edges0, out, i = self.tap.edges, bytearray(), 0
        xfer = False
        while i < len(data) and data[i] != DJ.CMD_STOP:
            c = data[i] & 0x0F
            if c == DJ.CMD_INFO:
                out += b"DJTAG2\n\0\0\0"
            elif c == DJ.CMD_FREQ:
                i += 2
            elif c == DJ.CMD_XFER:
                xfer = True
                n = data[i + 1] + (256 if data[i] & DJ.XFER_EXTEND else 0)
                n = min(n, 62 * 8)
                nbytes = (n + 7) // 8
                payload, rx = data[i + 2:i + 2 + nbytes], bytearray(nbytes)
                self.tms = 0                                   # jtag_transfer sets TMS low
                for j in range(n):
                    bit = self.tap.clock(0, (payload[j // 8] >> (7 - j % 8)) & 1)
                    rx[j // 8] |= bit << (7 - j % 8)
                    self.last_tdo = bit
                if not data[i] & DJ.XFER_NO_READ:
                    out += rx
                i += 1 + nbytes
            elif c == DJ.CMD_SETSIG:
                mask, val = data[i + 1], data[i + 2]
                if mask & DJ.SIG_TCK and val & DJ.SIG_TCK:     # TCK first: clocks the OLD levels
                    self.last_tdo = self.tap.clock(self.tms, self.tdi)
                if mask & DJ.SIG_TDI:
                    self.tdi = 1 if val & DJ.SIG_TDI else 0
                if mask & DJ.SIG_TMS:
                    self.tms = 1 if val & DJ.SIG_TMS else 0
                i += 2
            elif c == DJ.CMD_GETSIG:
                out.append(DJ.SIG_TDO if self.last_tdo else 0)
            elif c == CMD_CLK:
                raise AssertionError("dirtyjtag.py does not use CMD_CLK")
            else:
                raise AssertionError(f"unsupported command 0x{data[i]:02x}")
            i += 1
        self.log.append({"t": time.perf_counter(), "edges": self.tap.edges - edges0, "xfer": xfer,
                         "reply": len(out)})
        if out:
            self.replies.append(bytes(out))

    # --- ep_in ---------------------------------------------------------------------------
    def read(self, n, timeout=None):
        assert self.replies, "read with no reply pending: the probe would time out"
        r = self.replies.pop(0)
        assert len(r) <= n
        return r


@pytest.fixture
def rig():
    tap = Tap()
    pico = PicoModel(tap)
    p = DJ.Probe.over(pico, pico)
    return p, pico, tap


def ir(p, name):
    return p.shift_ir(IR[name], width=IR_W)


def test_idcode_after_reset(rig):
    p, pico, tap = rig
    p.reset_to_idle()
    assert tap.state == "RTI"
    assert p.shift_dr(32) == IDCODE


def test_ir_capture_reads_01_and_loads_the_instruction(rig):
    p, pico, tap = rig
    p.reset_to_idle()
    assert ir(p, "USER1") & 0b11 == 0b01
    assert tap.ir == IR["USER1"]


def test_a_dr_scan_writes_and_reads_back(rig):
    p, pico, tap = rig
    p.reset_to_idle()
    ir(p, "USER1")
    p.shift_dr(32, 0xDEADBEEF)
    assert tap.user1 == 0xDEADBEEF
    assert p.shift_dr(32, 0x12345678) == 0xDEADBEEF
    assert tap.user1 == 0x12345678 and tap.state == "RTI"


@pytest.mark.parametrize("n", [BIG_W, 64, 71, 150])
def test_bulk_and_pulse_scans_agree(n):
    """shift_dr_fast (CMD_XFER body, pulsed tail) and shift_dr (pulses) shift the same bits"""
    results = []
    for fast in (False, True):
        tap = Tap()
        pico = PicoModel(tap)
        p = DJ.Probe.over(pico, pico)
        p.reset_to_idle()
        ir(p, "BIG")
        din = int("1100101" * 30, 2) & ((1 << n) - 1)
        got = (p.shift_dr_fast if fast else p.shift_dr)(n, din)
        results.append((got, tap.big, tap.state, any(e["xfer"] for e in pico.log)))
    (a, big_a, st_a, x_a), (b, big_b, st_b, x_b) = results
    assert a == b and big_a == big_b and st_a == st_b == "RTI"
    assert not x_a and x_b
    assert a & ((1 << min(n, BIG_W)) - 1) == BIG_CAPTURE & ((1 << min(n, BIG_W)) - 1)


def test_packets_are_full_and_every_one_is_answered(rig):
    p, pico, tap = rig
    p.reset_to_idle()
    ir(p, "USER1")
    before = len(pico.log)
    p.shift_dr(32, 0xA5A5A5A5)
    scan = pico.log[before:]
    assert sum(e["edges"] for e in scan) == 32 + 5
    assert len(scan) <= 6                              # was 37 round trips, one per edge
    assert all(e["reply"] >= 1 for e in scan)          # the host waits for each


def test_shift_dr_is_n_plus_5_edges_whichever_mode(rig):
    """the premise of hwtest counter-step: an n-bit scan is n + 5 TCK edges"""
    p, pico, tap = rig
    p.reset_to_idle()
    ir(p, "BIG")
    for stepping in (False, True):
        p.stepping = stepping
        e0 = tap.edges
        p.shift_dr(40, 0)
        assert tap.edges - e0 == 45


def test_stepping_sends_one_edge_per_round_trip(rig):
    """USER1 ce in clock mode 0: each TCK edge is a user clock, and clock_ctrl.v would merge
    edges closer than the design's gce spacing, so every edge gets its own round trip"""
    p, pico, tap = rig
    p.reset_to_idle()
    ir(p, "BIG")
    p.stepping = True
    before = len(pico.log)
    p.shift_dr_fast(BIG_W, 0)                          # a bulk scan falls back to pulses
    p.idle(12)
    p.shift_ir(IR["BYPASS"], width=IR_W)
    scan = pico.log[before:]
    assert scan and all(e["edges"] == 1 and not e["xfer"] for e in scan)


def test_stepping_keeps_the_designs_gce_spacing_between_edges(rig):
    p, pico, tap = rig
    p.reset_to_idle()
    p.stepping = True
    p.edge_gap_s = 0.003
    before = len(pico.log)
    p.idle(6)
    ts = [e["t"] for e in pico.log[before:]]
    assert len(ts) == 6
    assert min(b - a for a, b in zip(ts, ts[1:])) >= 0.003 * 0.95


def test_packet_packing():
    reading = DJ.packets_of([(0, 1, True)] * 20)
    assert [n for _, n in reading] == [9, 9, 2]
    silent = DJ.packets_of([(1, 0, False)] * 25)
    assert all(n == 0 and cmds[-1] == DJ.CMD_GETSIG for cmds, n in silent)   # answered anyway
    for cmds, _ in reading + silent:
        assert len(cmds) + 1 <= DJ.PACKET_BYTES
    assert sum(cmds.count(DJ.CMD_SETSIG) for cmds, _ in silent) == 50


def test_cfgplane_user1_sets_stepping_from_the_ce_bit(rig):
    import cfgplane
    p, pico, tap = rig
    p.reset_to_idle()
    cfgplane.user1(p, 0b101)                           # ce + cin
    assert p.stepping
    cfgplane.user1(p, 0b100)                           # cin only
    assert not p.stepping
    cfgplane.user1(p, 0x10)                            # INTEST autostep: one clock per scan, not per edge
    assert not p.stepping


def test_the_default_gce_spacing_is_512_sysclk_cycles():
    import cfgplane
    assert cfgplane.gce_spacing_s(0) == pytest.approx(512 / 125e6)


def test_a_full_load_batches_even_with_ce_set():
    """JPROGRAM clears GWE, so no user clock runs during a full load: the load goes in bulk
    whatever USER1 ce says, and the probe is stepping again afterwards"""
    import cfgplane

    class Probe:
        stepping = True
        seen = []

        def shift_ir(self, value, width=6):
            self.seen.append(("ir", self.stepping))
            return 1

        def shift_dr(self, n, din=0):
            self.seen.append(("dr", self.stepping))
            return 0

        shift_dr_fast = shift_dr

    p = Probe()
    with cfgplane._unstepped(p):
        cfgplane.frames_send(p, [0x20000000])
    assert p.stepping and all(not s for _k, s in p.seen)
