"""
hwtest's M10 checks against a software stand-in for the board: FakeBob answers the
JTAG instructions the checks use (JPROGRAM, CFG_CTRL, CFG_IN/OUT, JSTART, USER1
autostep, INTEST, CAPTURE, USER4 BRAM) from tools/bob/model.py. It cannot find
hardware problems; it proves the checks' own scan ordering, bit indexing and
golden comparisons before they meet the board, and that they can fail.
"""

import os
import shutil
import sys

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

IR = {v: k for k, v in cfgplane.IR.items()}


class FakeBob:
    def __init__(self, corrupt_capture=False):
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

    # --- probe API used by cfgplane / fpga / hwtest ---
    def shift_ir(self, code, width=6):
        self.ir = IR[code]
        return 0b010001 | (self.done << 5) | (self.committed << 3)

    def pulse(self, tms=0, tdi=0):
        if self.ir == "JSTART" and self.committed and not self.done:
            self.done = 1
            self.fab = model.Fabric(B.Bitstream(self.chain))
            self.fab.clock(gsr=1)
            for b, words in self.brams.items():
                self.fab.brams[b].mem = list(words)

    def reset_to_idle(self):
        self.ir = "IDCODE"

    def read_idcode(self):
        return 0xABEEF093

    def shift_dr_fast(self, n, din=0):
        return self.shift_dr(n, din)

    def shift_dr(self, n, din=0):
        ir = self.ir
        if ir == "JPROGRAM":
            return 0
        if ir == "CFG_CTRL":
            out = (self.expected | (self.count << 32) | (int(chainbits.crc32c_bits(self.chain, B.CHAIN_W)
                   == self.expected) << 48) | (self.committed << 51) | (self.done << 55)
                   | (chainbits.CTRL_VERSION << 56))
            if din >> 56 == chainbits.CTRL_KEY:
                self.expected = din & 0xFFFFFFFF
                self.committed = self.done = 0
            return out
        if ir == "CFG_IN":
            self.chain, self.count = din, n
            self.committed = int(chainbits.crc32c_bits(din, n) == self.expected and n == B.CHAIN_W)
            self.brams = {}
            return 0
        if ir == "CFG_OUT":
            return self.chain
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
            return (self.target << 66) | (cfgplane.BRAM_VERSION << 88)
        if ir == "INTEST":
            leds = self.fab.outputs(self.bsr_in)
            raw = sum(((leds >> k) & 1) << pad for k, pad in enumerate(B.BOARD_OUT))
            self.bsr_in = sum(((din >> (B.NPAD + pad)) & 1) << k for k, pad in enumerate(B.BOARD_IN))
            if self.user1 & 0x10:
                self.fab.clock(pad_i=self.bsr_in)
            return raw
        if ir == "CAPTURE":
            v = self.fab.clb_o(0)            # IR is not INTEST: the pads read the real switches (0)
            return v ^ ((1 << B.NCLB) - 1) if self.corrupt_capture else v
        return 0


@pytest.mark.parametrize("name", ["counter", "ram", "gates_swapped"])
def test_m10_check_passes_on_a_good_board(name):
    ok, msg = hwtest._bob_check(name)(FakeBob(), {})
    assert ok, msg


def test_m10_check_fails_when_capture_is_wrong():
    ok, msg = hwtest._bob_check("counter")(FakeBob(corrupt_capture=True), {})
    assert not ok and "CAPTURE" in msg
