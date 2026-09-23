#!/usr/bin/env python3
"""
bitgen.py - bob FASM <-> configuration chain, and the .bit file (M10).

  software/bob/bitgen.py design.fasm -o design.bit [--bram 0:contents.json] [--meta k=v]
  software/bob/bitgen.py --dump design.bit            the chain back as FASM (stdout)
  software/bob/bitgen.py --roundtrip design.bit       bits -> FASM -> bits must be identical

FASM (written by software/bob/fasm_from_vpr.py, read here): one feature per line,
`feature = <width>'h<value>`, # comments, only non-zero features needed.

  <block>.<field>     a CLB / BRAM / DSP field (device.json tile_types); a CLB's are
                      per element (M21): clb_x1y1.e3.init, clb_x1y1.e3.x2 (crossbar)
  ctrl.<field>        the ctrl tile (clock mode, divider)
  rr<node>            the routing mux of rr-graph node <node>

The declared width must be the device's. Every feature is legality-checked
(fasm_from_vpr.check_legal): the field exists, the value fits, a mux value is
const0, const1 (IPINs only) or one of the mux's inputs.

bits -> FASM decodes every configurable field of the chain; any set bit that no
feature owns (the reserved tail) is an error, so the round trip is exact.

.bit = the chain file of docs/bitstream-format.md section 8, version 2: chain,
CRC-32C, a BRAM section per BRAM with contents, a META section (JSON: design, how
it was built) and a CRC over the whole file. software/host/bob load writes the chain through
CFG_IN, the BRAM contents over USER4, then JSTART.
"""

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402
import chainbits  # noqa: E402
from fasm_from_vpr import FasmError, check_legal, feature_width, to_bitstream, to_fasm  # noqa: E402


# --- FASM text ----------------------------------------------------------------------

def parse_fasm(text):
    F = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.fullmatch(r"([\w.\[\]]+)\s*=\s*(\d+)'([hbd])([0-9a-fA-F_]+)", line)
        if not m:
            raise FasmError(f"line {n}: expected `feature = <width>'h<value>`: {raw!r}")
        feat, width, base, digits = m.group(1), int(m.group(2)), m.group(3), m.group(4).replace("_", "")
        value = int(digits, {"h": 16, "b": 2, "d": 10}[base])
        if feat in F:
            raise FasmError(f"line {n}: {feat} given twice")
        try:
            want = feature_width(feat)
        except (KeyError, ValueError):
            raise FasmError(f"line {n}: no feature {feat} on this device")
        if width != want:
            raise FasmError(f"line {n}: {feat} is {want} bits on this device, the file says {width}")
        F[feat] = value
    check_legal(F)
    return F


# --- chain -> features -----------------------------------------------------------------

TABLES = {"clb": B.FIELD, "bram": B.BRAM_FIELD, "dsp": B.DSP_FIELD}


def features_from_word(word):
    """every non-zero configurable field of a chain, as FASM features"""
    F, owned = {}, 0

    def take(feat, lo, w):
        nonlocal owned
        owned |= ((1 << w) - 1) << lo
        v = (word >> lo) & ((1 << w) - 1)
        if v:
            F[feat] = v

    for name, (off, w) in B.CTRL_FIELD.items():
        take(f"ctrl.{name}", off, w)
    for bname, blk in B.BLOCKS.items():
        table = TABLES.get(blk["type"])
        if table is None:
            continue
        for field, (off, w) in table.items():
            take(f"{bname}.{field}", blk["chain_lo"] + off, w)
    for node, (lo, w, _base, _ins) in B.MUX.items():
        if B.NODE[node][1] != "EIN":                      # crossbar muxes are CLB fields (M21)
            take(f"rr{node}", lo, w)
    stray = word & ~owned & ((1 << B.CHAIN_W) - 1)
    if stray or word >> B.CHAIN_W:
        raise FasmError(f"chain has set bits no feature owns (first at {(stray & -stray).bit_length() - 1})")
    check_legal(F)
    return F


def word_from_features(F):
    check_legal(F)
    return to_bitstream(F).to_int()


# --- .bit ------------------------------------------------------------------------------

def write_bit(path, word, brams=None, meta=None):
    # a section for every BRAM the design uses, even all-zero: the loader writes all
    # 1024 words of each (trailing zeros are not stored in the file)
    sections = [chainbits.bram_section(b, words) for b, words in sorted((brams or {}).items())]
    meta = dict(meta or {})
    meta.setdefault("fasm_sha256", hashlib.sha256(to_fasm(features_from_word(word)).encode()).hexdigest())
    sections.append(("META", json.dumps(meta, sort_keys=True).encode()))
    chainbits.write_chain(path, B.DEVICE["name"], word, B.CHAIN_W, sections)


def read_bit(path):
    """-> dict(word, brams, meta, ...); refuses a file for another device or width"""
    c = chainbits.read_chain(path, expect_name=B.DEVICE["name"], expect_width=B.CHAIN_W)
    features_from_word(c["word"])                          # legal on this device
    return c


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help=".fasm to assemble, or .bit with --dump / --roundtrip")
    ap.add_argument("-o", "--output")
    ap.add_argument("--bram", action="append", default=[], metavar="IDX:FILE",
                    help="BRAM contents: a JSON list of up to 1024 words")
    ap.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--roundtrip", action="store_true")
    args = ap.parse_args()
    try:
        if args.dump or args.roundtrip:
            c = read_bit(args.input)
            F = features_from_word(c["word"])
            if args.dump:
                sys.stdout.write(to_fasm(F))
                return 0
            back = word_from_features(parse_fasm(to_fasm(F)))
            ok = back == c["word"]
            print(f"{'PASS' if ok else 'FAIL'}  {args.input}: bits -> {len(F)} FASM features -> bits "
                  f"{'identical' if ok else 'DIFFER'}")
            return 0 if ok else 1
        F = parse_fasm(open(args.input).read())
        brams = {}
        for spec in args.bram:
            idx, path = spec.split(":", 1)
            brams[int(idx)] = json.load(open(path))
        meta = dict(kv.split("=", 1) for kv in args.meta)
        out = args.output or os.path.splitext(args.input)[0] + ".bit"
        write_bit(out, word_from_features(F), brams, meta)
        print(f"wrote {out}: {len(F)} features, {B.CHAIN_W}-bit chain for {B.DEVICE['name']}")
        return 0
    except (FasmError, chainbits.ChainFileError, OSError) as e:
        print(f"FAIL  {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
