"""
Shared DirtyJTAG transport: a Pico running pico-dirtyJtag, driven over USB.

Everything in software/host/ goes through this. TAP navigation and short scans are
bit-banged pulse by pulse, exactly the semantics the testbench in sim/ models, so
hardware and simulation can be compared bit for bit; long Shift-DR runs go in bulk.

Protocol, from pico-dirtyJtag (V1.07) cmd.c, pio_jtag.c and dirtyJtag.c:

  CMD_SETSIG(mask, value)   set the TMS/TDI levels. Setting TCK *high* does not
                            park a level - it emits one complete clock pulse
                            through the PIO (at the CMD_FREQ rate) and latches TDO.
                            cmd_setsig applies TCK before TDI and TMS, so a pulse is
                            two SETSIGs: the levels (TCK low, a no-op), then TCK.
  CMD_GETSIG                returns the TDO latched by that pulse (one byte).
  CMD_XFER                  up to 496 bits with TMS low, TDI/TDO MSB first per byte.

TDO must be read that way round. The firmware only refreshes its cached TDO
inside a PIO transfer, so a bare CMD_GETSIG returns a stale bit.

Packets (2026-09-26). The firmware reads commands in 64-byte packets and answers each
packet with one reply holding every GETSIG/XFER byte it produced, in order. So a packet
carries up to 9 reading pulses (or 10 that read nothing), and the host sends the next
packet only after the reply to the last one: dirtyJtag.c warns that two packets in
flight can be merged into one read, which the protocol does not survive. Until then
every pulse was its own USB round trip, and the round trips, not TCK, set the speed
(hwtest fast-tck: a 10x faster TCK loaded 2.6x, then 1.0x, faster).

Stepping. In clock mode 0 with USER1 ce set, every TCK rising edge is one user clock,
and clock_ctrl.v keeps user clocks at least the design's gce spacing apart (4 us by
default), holding only one early request. Batched pulses come about 1 us apart at
1 MHz, so they would merge. While `stepping` is set (cfgplane.user1 sets it from the
ce bit), every pulse is its own round trip, as before, at least `edge_gap_s` after the
previous one (cfgplane sets that from the loaded word's gce spacing), and bulk shifts
fall back to pulses.
"""

import sys
import time

import usb.core
import usb.util

VID, PID = 0x1209, 0xC0CA

CMD_STOP, CMD_INFO, CMD_FREQ = 0x00, 0x01, 0x02
CMD_XFER = 0x03
CMD_SETSIG, CMD_GETSIG = 0x04, 0x05
XFER_NO_READ, XFER_EXTEND = 0x80, 0x40

# CMD_XFER caps a transfer at 62 bytes, and the command header plus a trailing
# CMD_STOP has to fit the 64-byte packet too. 60 bytes leaves room for both.
XFER_MAX_BYTES = 60

SIG_TCK, SIG_TDI, SIG_TDO, SIG_TMS = 1 << 1, 1 << 2, 1 << 3, 1 << 4
LEVELS = SIG_TMS | SIG_TDI

# the firmware's command and reply buffers (dirtyJtag.c cmd_buffer, cmd.c tx_buf): one packet
# of commands, CMD_STOP included, and one reply per packet
PACKET_BYTES = 64


def pulse_bytes(tms, tdi, read):
    """one TCK pulse with these levels: the levels, then TCK (which clocks), then TDO if read"""
    lv = (SIG_TMS if tms else 0) | (SIG_TDI if tdi else 0)
    return [CMD_SETSIG, LEVELS | SIG_TCK, lv, CMD_SETSIG, SIG_TCK, SIG_TCK] + ([CMD_GETSIG] if read else [])


def packets_of(pulses):
    """(tms, tdi, read) pulses -> [(command bytes, reads)], each packet at most PACKET_BYTES with
    its CMD_STOP and holding at least one GETSIG, so that every packet is answered: a packet that
    reads nothing ends with a GETSIG whose byte is dropped (reads counts only the wanted ones)."""
    out, buf, nread = [], [], 0

    def size(nbytes, reads):                    # + CMD_STOP, + a closing GETSIG if nothing reads
        return nbytes + 1 + (0 if reads else 1)
    for tms, tdi, read in pulses:
        b = pulse_bytes(tms, tdi, read)
        if buf and size(len(buf) + len(b), nread + bool(read)) > PACKET_BYTES:
            out.append((buf, nread))
            buf, nread = [], 0
        buf += b
        nread += bool(read)
    if buf:
        out.append((buf, nread))
    return [(b if n else b + [CMD_GETSIG], n) for b, n in out]

# ---------------------------------------------------------------------------
# THE 4-BIT M0/M1 INSTRUCTION SET, for the bring-up tops only.
#
# This is the *old* TAP (rtl/jtag_tap.v, 4-bit IR, the single-CLB and 4x4 bitstreams)
# and it is kept because software/host/tap_probe.py, software/host/minifpga.py and this module's own
# load_config / read_config still drive those. It is NOT what bob_top speaks.
#
# The current device is a 6-bit AMD 7-series IR and its table lives in
# software/host/cfgplane.py (IR), with the IDCODE in software/host/fpga.py (IDCODE_FABRIC, read from
# hw/build.cfg). Look there, not here: this module is the transport everything
# imports, so these names are the first a reader meets and the wrong ones to use.
# ---------------------------------------------------------------------------
IR_EXTEST, IR_SAMPLE, IR_IDCODE = 0b0000, 0b0001, 0b0010
IR_USER, IR_INTEST, IR_CONFIG = 0b0011, 0b0100, 0b0101
IR_BYPASS = 0b1111

IR_WIDTH = 4
CFG_W = 71
BSR_W = 9

# USER control word bit positions
USER_CE, USER_SR, USER_CIN, USER_STEP, USER_AUTOSTEP = 0, 1, 2, 3, 4

IDCODE_EXPECTED = 0x2BEEF093      # the M0 single-CLB top; the fabric's is fpga.IDCODE_FABRIC


MAX_TCK_KHZ = 1000         # M25: the XDC constrains TCK at 1 us (M13-M24: 10 us); never drive it faster
DEFAULT_TCK_KHZ = 1000     # M25: bob's tools run TCK at 1 MHz since the board passed 71/71 at it (2026-09-25);
                           # the M13-M24 bitstreams are constrained for 100 kHz only


class Probe:
    def __init__(self, freq_khz=100):
        dev = usb.core.find(idVendor=VID, idProduct=PID)
        if dev is None:
            sys.exit("no DirtyJTAG probe found (expected %04x:%04x)" % (VID, PID))
        self.dev = dev

        # The firmware also exposes a CDC UART, so do not assume interface 0 -
        # find the vendor-specific interface with a bulk IN/OUT pair.
        cfg = dev.get_active_configuration()
        self.ep_out = self.ep_in = None
        for intf in cfg:
            if intf.bInterfaceClass != 0xFF:
                continue
            outs = [e for e in intf if usb.util.endpoint_direction(e.bEndpointAddress)
                    == usb.util.ENDPOINT_OUT]
            ins = [e for e in intf if usb.util.endpoint_direction(e.bEndpointAddress)
                   == usb.util.ENDPOINT_IN]
            if outs and ins:
                self.ep_out, self.ep_in = outs[0], ins[0]
                break
        if self.ep_out is None:
            sys.exit("no vendor-specific bulk interface on the probe")
        self._init_state()
        self.set_freq_khz(freq_khz)

    @classmethod
    def over(cls, ep_out, ep_in):
        """A Probe on endpoints that are already open: tests/test_dirtyjtag.py drives one over a
        Python model of the firmware's command handler and a TAP."""
        p = cls.__new__(cls)
        p.dev, p.ep_out, p.ep_in = None, ep_out, ep_in
        p._init_state()
        return p

    def _init_state(self):
        self.stepping = False          # USER1 ce in clock mode 0: every TCK edge is a user clock
        self.edge_gap_s = 0.0          # the loaded design's gce spacing (cfgplane.note_loaded)
        self._last_edge = 0.0

    # --- transport --------------------------------------------------------

    def _xact(self, payload, want_reply=False):
        self.ep_out.write(bytes(payload) + bytes([CMD_STOP]))
        return bytes(self.ep_in.read(64, timeout=2000)) if want_reply else b""

    def info(self):
        try:
            return self._xact([CMD_INFO], True).split(b"\n")[0].decode(errors="replace")
        except Exception:
            return "(no reply to CMD_INFO)"

    def set_freq_khz(self, khz):
        if khz > MAX_TCK_KHZ:
            raise ValueError(f"TCK {khz} kHz: bob's timing constraints assume at most {MAX_TCK_KHZ} kHz "
                             "(hw/constr/pynq_z2.xdc, docs/bitstream-format.md section 11)")
        self._xact([CMD_FREQ, (khz >> 8) & 0xFF, khz & 0xFF])

    def pulse(self, tms=0, tdi=0):
        """One TCK cycle in its own USB round trip. Returns the TDO bit sampled during it.
        While stepping it also keeps edge_gap_s after the previous TCK edge."""
        if self.stepping and self.edge_gap_s:
            wait = self._last_edge + self.edge_gap_s - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
        r = self._xact(pulse_bytes(tms, tdi, True), True)
        self._last_edge = time.perf_counter()
        return 1 if r[0] & SIG_TDO else 0

    def run(self, pulses):
        """Clock a sequence of (tms, tdi, read) pulses; returns the TDO bits of the pulses with
        read set, in order. Several pulses per packet, one round trip per packet; while
        stepping, one round trip per pulse (see the module notes)."""
        pulses = list(pulses)
        out = []
        if self.stepping:
            for tms, tdi, read in pulses:
                bit = self.pulse(tms, tdi)
                if read:
                    out.append(bit)
            return out
        for cmds, nread in packets_of(pulses):
            r = self._xact(cmds, True)
            if len(r) < max(nread, 1):
                raise IOError(f"DirtyJTAG answered {len(r)} bytes to a packet of {max(nread, 1)} reads")
            out += [1 if x & SIG_TDO else 0 for x in r[:nread]]
        return out

    def idle(self, tcks):
        """TCKs with TMS low (Run-Test/Idle, e.g. for JSTART)"""
        self.run([(0, 0, False)] * tcks)

    def sample_tdo(self):
        """TDO, sampled by one harmless pulse held in Test-Logic-Reset."""
        return self.pulse(tms=1)

    # --- bulk shifting ----------------------------------------------------
    #
    # One USB round trip per bit is fine for a 32-bit IDCODE and hopeless for a
    # 2896-bit configuration chain. CMD_XFER shifts up to 496 bits per packet
    # with TMS held low, which is exactly what Shift-DR needs.
    #
    # Two things matter and are easy to get wrong:
    #   - data is MSB-first WITHIN each byte (pico-dirtyJtag's jtag_set_tdi
    #     writes 1u<<7 for a single bit, which is what pins this down)
    #   - only whole bytes are transferred here, so the ragged tail and the
    #     final TMS=1 bit are done with ordinary pulses

    @staticmethod
    def _pack_msb(bits):
        out = bytearray()
        for j in range(0, len(bits), 8):
            byte = 0
            for k in range(8):
                if j + k < len(bits) and bits[j + k]:
                    byte |= 1 << (7 - k)
            out.append(byte)
        return bytes(out)

    @staticmethod
    def _unpack_msb(data, n):
        bits = []
        for byte in data:
            for k in range(8):
                if len(bits) < n:
                    bits.append((byte >> (7 - k)) & 1)
        return bits

    def _xfer(self, payload, nbits):
        op = CMD_XFER
        ln = nbits
        if ln >= 256:
            op |= XFER_EXTEND
            ln -= 256
        self.ep_out.write(bytes([op, ln]) + payload + bytes([CMD_STOP]))
        return bytes(self.ep_in.read(64, timeout=5000))[:nbits // 8]

    def shift_dr_fast(self, n, din=0):
        """Same contract as shift_dr, but the body of the scan goes in bulk (CMD_XFER). Falls
        back to shift_dr for anything too short to be worth it, and while stepping (a bulk
        transfer runs TCK edges closer than the user clock may follow)."""
        if n < 64 or self.stepping:
            return self.shift_dr(n, din)

        bits = [(din >> i) & 1 for i in range(n)]

        # Everything except a byte-aligned remainder and the final bit.
        bulk = ((n - 1) // 8) * 8

        self.run([(1, 0, False), (0, 0, False), (0, 0, False)])     # Select-DR, Capture-DR, Shift-DR

        out = []
        sent = 0
        while sent < bulk:
            take = min(XFER_MAX_BYTES * 8, bulk - sent)
            chunk = self._pack_msb(bits[sent:sent + take])
            got = self._xfer(chunk, take)
            out.extend(self._unpack_msb(got, take))
            sent += take

        # the ragged tail, the last bit with TMS high, then Update-DR and Run-Test/Idle
        out += self.run([(0, bits[i], True) for i in range(bulk, n - 1)] + [(1, bits[n - 1], True)]
                        + [(1, 0, False), (0, 0, False)])

        value = 0
        for i, b in enumerate(out):
            if b:
                value |= 1 << i
        return value

    # --- TAP navigation, mirroring sim/tb_mini_fpga.v ---------------------

    def reset_to_idle(self):
        self.run([(1, 0, False)] * 5 + [(0, 0, False)])

    def shift_dr(self, n, din=0):
        """Select-DR, Capture-DR, Shift-DR, n bits LSB first (the last with TMS high), Update-DR,
        Run-Test/Idle: n + 5 TCK edges. Returns the n bits TDO carried, bit 0 first."""
        bits = self.run([(1, 0, False), (0, 0, False), (0, 0, False)]
                        + [(1 if i == n - 1 else 0, (din >> i) & 1, True) for i in range(n)]
                        + [(1, 0, False), (0, 0, False)])
        return sum(b << i for i, b in enumerate(bits))

    def shift_ir(self, value, width=IR_WIDTH):
        """Select-DR, Select-IR, Capture-IR, Shift-IR, width bits, Update-IR, Run-Test/Idle"""
        bits = self.run([(1, 0, False), (1, 0, False), (0, 0, False), (0, 0, False)]
                        + [(1 if i == width - 1 else 0, (value >> i) & 1, True) for i in range(width)]
                        + [(1, 0, False), (0, 0, False)])
        return sum(b << i for i, b in enumerate(bits))

    # --- mini FPGA operations --------------------------------------------

    def read_idcode(self):
        self.reset_to_idle()
        return self.shift_dr(32)

    def load_config(self, init, ctrl=0):
        """Write the 71-bit CLB config: 64-bit LUT INIT plus 7 control bits."""
        word = (ctrl & 0x7F) << 64 | (init & ((1 << 64) - 1))
        self.shift_ir(IR_CONFIG)
        self.shift_dr(CFG_W, word)
        return word

    def read_config(self, expect):
        """Non-destructive readback: CONFIG is read-modify-write, so the same
        word has to be shifted back in or the readback commits zeros."""
        self.shift_ir(IR_CONFIG)
        return self.shift_dr(CFG_W, expect)

    def write_user(self, value):
        self.shift_ir(IR_USER)
        self.shift_dr(32, value)

    def read_user(self):
        self.shift_ir(IR_USER)
        return self.shift_dr(32, 0)

    def intest(self, vec):
        """One INTEST scan: apply `vec` to i[5:0], return the {cout,o5,o} that
        was captured - which answers the vector applied by the PREVIOUS scan."""
        rx = self.shift_dr(BSR_W, (vec & 0x3F) << 3)
        return rx & 0x7

    def intest_full(self, vec):
        """One INTEST scan, returning the whole 9-bit boundary.

        Worth knowing what comes back: a BC_1 cell captures its system input
        regardless of mode, so bits 8:3 are the PHYSICAL pins - not the vector
        you are driving. Bits 2:0 are the fabric's outputs for the vector the
        previous scan committed. You therefore see both worlds at once: what
        the switches are really doing, and what the fabric makes of the vector
        you injected instead.
        """
        return self.shift_dr(BSR_W, (vec & 0x3F) << 3)

    def intest_settle(self, vec):
        """Apply vec, read the answer, and light the LEDs with it.

        Three scans, and the third one is the interesting one. In INTEST every
        cell drives, including the three OUTPUT cells - so the pads are fed from
        those cells' update registers, not from the fabric. Shifting zeros into
        bits 2:0 therefore holds the LEDs off no matter what the logic computes.
        The fabric's answer only ever arrives by CAPTURE.

        So: scan A applies the vector, scan B captures what the fabric made of
        it, and scan C writes that answer back into the output cells so the
        board shows it. The LEDs then mirror the fabric one scan behind.

        Returns the boundary from scan B: physical pins in 8:3, fabric outputs
        in 2:0.
        """
        v = (vec & 0x3F) << 3
        self.shift_dr(BSR_W, v)                      # A: apply the vector
        raw = self.shift_dr(BSR_W, v)                # B: capture the answer
        self.shift_dr(BSR_W, v | (raw & 0x7))        # C: mirror it to the pads
        return raw

    def extest_full(self, pads):
        """Drive the three output pads from the boundary; the fabric is isolated."""
        return self.shift_dr(BSR_W, pads & 0x7)

    def truth_table(self, n_inputs=2):
        """Walk every row of an n-input function and return the list of o bits.

        INTEST is pipelined by one scan, so this primes with row 0 and then
        reads each answer one scan late.
        """
        rows = 1 << n_inputs
        self.shift_ir(IR_INTEST)
        self.intest(0)                          # prime
        out = []
        for r in range(rows):
            res = self.intest((r + 1) % rows)
            out.append(res & 1)
        return out

    def sample(self):
        """One SAMPLE scan: read the whole boundary without disturbing anything.

        SAMPLE leaves bsr_mode low, so the boundary stays transparent and the
        CLB keeps running from the real switches while you watch it. This is
        the instruction to monitor with.
        """
        rx = self.shift_dr(BSR_W, 0)
        return {
            "raw":  rx,
            "i":    (rx >> 3) & 0x3F,      # what the CLB is seeing
            "sw":   (rx >> 3) & 0x3,       # i[1:0]
            "btn":  (rx >> 5) & 0xF,       # i[5:2]
            "o":     rx & 1,
            "o5":   (rx >> 1) & 1,
            "cout": (rx >> 2) & 1,
        }

    def extest(self, pads):
        """Drive the three output pads straight from the boundary."""
        self.shift_ir(IR_EXTEST)
        self.shift_dr(BSR_W, pads & 0x7)

    def go_live(self):
        """Leave test mode so the boundary is transparent and the CLB runs from
        the physical switches and buttons."""
        self.shift_ir(IR_BYPASS)


# Two-input LUT INIT words, replicated across all 64 entries so i[5:2] are
# don't-care. The nibble is the truth table for (i1, i0).
GATES = {
    "and":  (0x8888888888888888, [0, 0, 0, 1]),
    "or":   (0xEEEEEEEEEEEEEEEE, [0, 1, 1, 1]),
    "xor":  (0x6666666666666666, [0, 1, 1, 0]),
    "nand": (0x7777777777777777, [1, 1, 1, 0]),
    "nor":  (0x1111111111111111, [1, 0, 0, 0]),
    "xnor": (0x9999999999999999, [1, 0, 0, 1]),
    "buf":  (0xAAAAAAAAAAAAAAAA, [0, 1, 0, 1]),
    "not":  (0x5555555555555555, [1, 0, 1, 0]),
}
