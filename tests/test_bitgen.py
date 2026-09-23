"""
M10: bitgen (FASM <-> chain), the version-2 .bit file, pin files and the golden netlist.
"""

import os
import random
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitgen  # noqa: E402
import bitstream as B  # noqa: E402
import chainbits as cb  # noqa: E402
import fasm_from_vpr as FV  # noqa: E402
import vpr_run  # noqa: E402


def _random_features(rng):
    F = {}
    for node, (_lo, _w, base, ins) in B.MUX.items():
        if B.NODE[node][1] == "EIN":                 # the crossbar: CLB fields, below
            continue
        r = rng.random()
        if r < 0.2:
            F[f"rr{node}"] = base + rng.randrange(len(ins))
        elif r < 0.25 and B.NODE[node][1] == "IPIN":
            F[f"rr{node}"] = 1
    for c in B.CLBS:
        for e in range(B.CLB_N):
            F[f"{c}.e{e}.init"] = rng.getrandbits(B.LUT_INIT_W)
            for flag in B.FLAG_NAMES:
                F[f"{c}.e{e}.{flag}"] = rng.getrandbits(1)
            for j in range(B.LUT_K):                 # const0, const1 or any crossbar source
                F[f"{c}.e{e}.x{j}"] = rng.randrange(2 + len(B.XBAR_SOURCES[e][j]))
    for name, (_off, w) in B.BRAM_FIELD.items():
        F[f"bram1.{name}"] = rng.getrandbits(w) % 3 if name.startswith("wmode") else rng.getrandbits(w)
    F["ctrl.clk_mode"] = 1
    return {k: v for k, v in F.items() if v}


@pytest.mark.parametrize("seed", range(4))
def test_bits_fasm_bits_roundtrip_random(seed):
    F = _random_features(random.Random(seed))
    w = bitgen.word_from_features(F)
    assert bitgen.features_from_word(w) == F
    assert bitgen.word_from_features(bitgen.parse_fasm(FV.to_fasm(F))) == w


@pytest.mark.parametrize("name", vpr_run.EXAMPLES + list(vpr_run.VARIANTS))
def test_committed_results_roundtrip(name):
    F, _ = FV.features(os.path.join(vpr_run.RESULTS, name), name)
    w = bitgen.word_from_features(F)
    assert bitgen.word_from_features(bitgen.features_from_word(w)) == w
    assert bitgen.features_from_word(w) == {k: v for k, v in F.items() if v}


def test_reserved_bits_and_bad_fasm_are_refused():
    with pytest.raises(FV.FasmError):
        bitgen.features_from_word(1 << (B.CHAIN_W - 1))              # tail padding
    clb = B.CLBS[0]
    xw = B.FIELD["e0.x0"][1]
    for text in (f"{clb}.e0.init = 8'h1",                             # wrong width
                 f"{clb}.e0.nothing = 1'h1",                           # no such field
                 "rr999999 = 1'h1",                                    # no such mux
                 f"{clb}.e0.ff_en = 1'h1\n{clb}.e0.ff_en = 1'h1",      # twice
                 f"{clb}.e0.ff_en 1",                                  # syntax
                 f"{clb}.e0.x0 = {xw}'h{(1 << xw) - 1:x}"):            # M21: past the crossbar's sources
        with pytest.raises(FV.FasmError):
            bitgen.parse_fasm(text)


def test_bit_file_v2(tmp_path):
    F = _random_features(random.Random(9))
    w = bitgen.word_from_features(F)
    words = [0] * 1024
    words[0], words[5] = 0x3FFFF, 0x12345
    path = str(tmp_path / "x.bit")
    bitgen.write_bit(path, w, {1: words, 0: [0] * 1024}, {"design": "x"})
    c = bitgen.read_bit(path)
    assert c["word"] == w and c["version"] == 2
    assert c["brams"] == {0: [0] * 1024, 1: words} and c["meta"]["design"] == "x"   # used BRAMs, even all-zero
    blob = bytearray(open(path, "rb").read())
    blob[-20] ^= 1                                                     # inside META
    with pytest.raises(cb.ChainFileError):
        cb.unpack_chain(bytes(blob))
    v1 = cb.pack_chain(B.DEVICE["name"], w, B.CHAIN_W)                 # version 1 still reads
    assert cb.unpack_chain(v1)["word"] == w and struct.unpack_from("<H", v1, 4)[0] == 1


def test_pcf(tmp_path):
    p = tmp_path / "a.pcf"
    p.write_text("# comment\nset_io led[0] LD2\nset_io x pad3  # trailing\n")
    assert vpr_run.read_pcf(str(p)) == {"led[0]": B.BOARD_OUT[2], "x": 3}
    for bad in ("set_io led[0] LD9\n", "set_io led[0]\n", f"set_io a pad{B.NPAD}\n"):
        p.write_text(bad)
        with pytest.raises(vpr_run.VprError):
            vpr_run.read_pcf(str(p))


@pytest.mark.skipif(__import__("shutil").which("yosys") is None, reason="needs yosys and iverilog")
def test_variant_pins_really_differ():
    """gates_swapped's chain on the model disagrees with the UNREMAPPED trace, so the
    remapped comparison that passes is not vacuous"""
    import equiv
    import json
    import model
    equiv.equiv([os.path.join(ROOT, "work", "examples", "gates", "gates.v")], "gates")          # fresh clone: no build/ yet
    bs, contents, _text = FV.build("gates_swapped")
    tr = json.load(open(os.path.join(ROOT, "build", "synth", "gates", "gates.trace.json")))
    m = model.Fabric(bs)
    assert any(m.outputs(v) != after for v, _before, after in tr["trace"])
