"""
M2: software/bob/chainbits.py implements docs/bitstream-format.md sections 5 and 8.
The RTL CRC is checked against these functions by hw/tb/tb_cfg.v.
"""

import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))

import chainbits as cb  # noqa: E402


def test_crc32c_published_check_value():
    assert cb.crc32c_bytes(b"123456789") == 0xE3069283


def test_bit_serial_equals_byte_wise_when_byte_aligned():
    rng = random.Random(7)
    for width in (8, 64, 2896, 4000):
        for _ in range(5):
            w = rng.getrandbits(width)
            assert cb.crc32c_bits(w, width) == cb.crc32c_bytes(cb.word_to_bytes(w, width))


def test_single_bit_flip_always_changes_crc():
    rng = random.Random(9)
    w = rng.getrandbits(64)
    c = cb.crc32c_bits(w, 64)
    for b in range(64):
        assert cb.crc32c_bits(w ^ (1 << b), 64) != c


def test_stuck_low_tdi_does_not_match_power_up_expected():
    # expected CRC register powers up at 0; an all-zero chain must not match it
    assert cb.crc32c_bits(0, 64) != 0
    assert cb.crc32c_bits(0, 2896) != 0


def test_ctrl_words():
    v = cb.ctrl_write_word(0xDEADBEEF)
    assert v >> 56 == cb.CTRL_KEY and v & 0xFFFFFFFF == 0xDEADBEEF
    st = cb.decode_ctrl((0x02 << 56) | (1 << 55) | (1 << 51) | (1 << 48) | (64 << 32) | 0x1234)
    assert st == {"crc": 0x1234, "count": 64, "crc_ok": 1, "crc_err": 0, "len_err": 0,
                  "committed": 1, "gsr": 0, "gts": 0, "gwe": 0, "done": 1, "version": 2}
    ir = cb.decode_ir_capture(0b010001)
    assert ir["lsb01"] and ir["init_b"] and not ir["done"]


def test_chain_file_round_trip_and_rejections():
    w = random.Random(3).getrandbits(2896)
    blob = cb.pack_chain("bob4x4", w, 2896)
    c = cb.unpack_chain(blob, expect_name="bob4x4", expect_width=2896)
    assert c["word"] == w and c["crc"] == cb.crc32c_bits(w, 2896)

    bad = bytearray(blob)
    bad[-1] ^= 0x01
    with pytest.raises(cb.ChainFileError, match="CRC"):
        cb.unpack_chain(bytes(bad))
    with pytest.raises(cb.ChainFileError, match="device"):
        cb.unpack_chain(blob, expect_name="cfg_test")
    with pytest.raises(cb.ChainFileError, match="bits"):
        cb.unpack_chain(blob, expect_width=64)
    with pytest.raises(cb.ChainFileError, match="magic"):
        cb.unpack_chain(b"XXXX" + blob[4:])


def test_host_ir_codes_match_rtl():
    """software/host/cfgplane.py and hw/src/core/jtag_tap6.v must agree on every code."""
    import re
    sys.path.insert(0, os.path.join(ROOT, "software", "host"))
    import cfgplane
    rtl = open(os.path.join(ROOT, "hw", "src", "core", "jtag_tap6.v")).read()
    codes = {m.group(1): int(m.group(2), 2)
             for m in re.finditer(r"localparam \[5:0\] IR_(\w+)\s*=\s*6'b([01]{6})", rtl)}
    alias = {"CFG_CTRL": "USER2", "CAPTURE": "USER3", "BRAM": "USER4"}
    for name, code in cfgplane.IR.items():
        assert codes[alias.get(name, name)] == code, name
