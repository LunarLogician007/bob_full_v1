#!/usr/bin/env python3
"""
chainbits.py - configuration chains as data: CRC-32C, CFG_CTRL words, .bobc files.

Implements docs/bitstream-format.md sections 5 and 8 for the host side. The RTL
(hw/src/core/cfg_ctrl.v) implements the same CRC; sim/gen_cfg_vectors.py feeds
values computed here to the testbench, so the two are checked against each other.

  ./chainbits.py info  file.bobc
  ./chainbits.py crc   0x<hex word> <width>
"""

import argparse
import struct
import sys

CRC_POLY_REFLECTED = 0x82F63B78          # CRC-32C (Castagnoli) 0x1EDC6F41, reflected
CRC_INIT = 0xFFFFFFFF
CRC_XOROUT = 0xFFFFFFFF

CTRL_KEY = 0xC5
CTRL_VERSION = 0x02

MAGIC = b"BOBC"
FILE_VERSION = 2                         # 2 (M10): v1 + sections (BRAM contents, META) + file CRC
FILE_VERSIONS = (1, 2)


# --- CRC ------------------------------------------------------------------------

def crc32c_bits(word, width):
    """CRC-32C over `width` bits of `word`, bit 0 first - exactly the order the
    chain is shifted in, and exactly what cfg_ctrl.v computes."""
    crc = CRC_INIT
    for i in range(width):
        bit = (word >> i) & 1
        if (crc ^ bit) & 1:
            crc = (crc >> 1) ^ CRC_POLY_REFLECTED
        else:
            crc >>= 1
    return crc ^ CRC_XOROUT


def crc32c_bytes(data):
    """Byte-wise reference CRC-32C (iSCSI/Castagnoli). crc32c_bytes(b'123456789')
    is the published check value 0xE3069283."""
    crc = CRC_INIT
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ CRC_POLY_REFLECTED if crc & 1 else crc >> 1
    return crc ^ CRC_XOROUT


def word_to_bytes(word, width):
    """Chain bits -> bytes, byte j = bits [8j+7:8j]."""
    return word.to_bytes((width + 7) // 8, "little")


def bytes_to_word(data, width):
    return int.from_bytes(data, "little") & ((1 << width) - 1)


# --- CFG_CTRL -------------------------------------------------------------------

def ctrl_write_word(expected_crc):
    """The 64-bit CFG_CTRL value that sets the expected CRC."""
    return (CTRL_KEY << 56) | (expected_crc & 0xFFFFFFFF)


def decode_ctrl(v):
    return {
        "crc":       v & 0xFFFFFFFF,
        "count":     (v >> 32) & 0xFFFF,
        "crc_ok":    (v >> 48) & 1,
        "crc_err":   (v >> 49) & 1,
        "len_err":   (v >> 50) & 1,
        "committed": (v >> 51) & 1,
        "gsr":       (v >> 52) & 1,
        "gts":       (v >> 53) & 1,
        "gwe":       (v >> 54) & 1,
        "done":      (v >> 55) & 1,
        "version":   (v >> 56) & 0xFF,
    }


def decode_ir_capture(cap):
    return {
        "done":      (cap >> 5) & 1,
        "init_b":    (cap >> 4) & 1,
        "committed": (cap >> 3) & 1,
        "crc_err":   (cap >> 2) & 1,
        "lsb01":     (cap & 0b11) == 0b01,
    }


# --- .bobc files ------------------------------------------------------------------

class ChainFileError(ValueError):
    pass


def pack_chain(name, word, width, sections=None, version=None):
    """sections: [(4-char tag, bytes)]. Version 1 (no sections) is still written when
    asked for, and always read."""
    version = version or (FILE_VERSION if sections else 1)
    nb = name.encode("ascii")
    blob = (MAGIC + struct.pack("<HH", version, len(nb)) + nb
            + struct.pack("<II", width, crc32c_bits(word, width))
            + word_to_bytes(word, width))
    if version == 1:
        if sections:
            raise ChainFileError("version 1 files have no sections")
        return blob
    sections = sections or []
    blob += struct.pack("<H", len(sections))
    for tag, data in sections:
        t = tag.encode("ascii")
        if len(t) != 4:
            raise ChainFileError(f"section tag {tag!r} is not 4 characters")
        blob += t + struct.pack("<I", len(data)) + data
    return blob + struct.pack("<I", crc32c_bytes(blob))


def bram_section(index, words):
    """BRAM contents: u8 BRAM index, u16 first address, u16 count, count x u32 words
    (trailing zero words are not stored; the loader writes all 1024 words, zero-filled)"""
    last = max((a for a, w in enumerate(words) if w), default=-1)
    body = struct.pack("<BHH", index, 0, last + 1) + b"".join(struct.pack("<I", w) for w in words[:last + 1])
    return ("BRAM", body)


def unpack_chain(blob, expect_name=None, expect_width=None):
    if blob[:4] != MAGIC:
        raise ChainFileError("not a .bobc file (bad magic)")
    version, nlen = struct.unpack_from("<HH", blob, 4)
    if version not in FILE_VERSIONS:
        raise ChainFileError(f"file version {version}, this tool reads {FILE_VERSIONS}")
    name = blob[8:8 + nlen].decode("ascii")
    width, crc = struct.unpack_from("<II", blob, 8 + nlen)
    start = 16 + nlen
    nbytes = (width + 7) // 8
    sections, brams, meta = [], {}, {}
    if version == 1:
        payload = blob[start:]
        if len(payload) != nbytes:
            raise ChainFileError(f"payload is {len(payload)} bytes, width {width} needs {nbytes}")
    else:
        if len(blob) < start + nbytes + 6:
            raise ChainFileError("file is truncated")
        if crc32c_bytes(blob[:-4]) != struct.unpack("<I", blob[-4:])[0]:
            raise ChainFileError("file CRC mismatch - file is corrupt")
        payload = blob[start:start + nbytes]
        pos = start + nbytes
        (count,) = struct.unpack_from("<H", blob, pos)
        pos += 2
        for _ in range(count):
            tag = blob[pos:pos + 4].decode("ascii")
            (ln,) = struct.unpack_from("<I", blob, pos + 4)
            data = blob[pos + 8:pos + 8 + ln]
            if len(data) != ln:
                raise ChainFileError(f"section {tag} is truncated")
            sections.append((tag, data))
            pos += 8 + ln
            if tag == "BRAM":
                idx, first, n = struct.unpack_from("<BHH", data, 0)
                words = [0] * 1024
                for i in range(n):
                    words[first + i] = struct.unpack_from("<I", data, 5 + 4 * i)[0]
                brams[idx] = words
            elif tag == "META":
                import json
                meta = json.loads(data.decode("utf-8"))
        if pos != len(blob) - 4:
            raise ChainFileError("trailing bytes after the sections")
    word = bytes_to_word(payload, width)
    if crc32c_bits(word, width) != crc:
        raise ChainFileError("CRC mismatch - file is corrupt")
    if expect_name is not None and name != expect_name:
        raise ChainFileError(f"chain is for device '{name}', connected device is '{expect_name}'")
    if expect_width is not None and width != expect_width:
        raise ChainFileError(f"chain is {width} bits, device expects {expect_width}")
    return {"name": name, "width": width, "crc": crc, "word": word, "version": version,
            "sections": sections, "brams": brams, "meta": meta}


def write_chain(path, name, word, width, sections=None):
    with open(path, "wb") as fh:
        fh.write(pack_chain(name, word, width, sections))


def read_chain(path, **expect):
    with open(path, "rb") as fh:
        return unpack_chain(fh.read(), **expect)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("info")
    a.add_argument("file")
    b = sub.add_parser("crc")
    b.add_argument("word")
    b.add_argument("width", type=int)
    args = ap.parse_args()
    if args.cmd == "info":
        c = read_chain(args.file)
        print(f"device {c['name']}  width {c['width']}  crc 0x{c['crc']:08X}  version {c['version']}  "
              f"BRAMs {sorted(c['brams'])}  meta {c['meta']}  (valid)")
    else:
        print(f"0x{crc32c_bits(int(args.word, 0), args.width):08X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
