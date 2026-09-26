"""
packets.py's load streams, checked on its bit-level model of cfg_frames.v (packets.Controller).

2026-09-26: a full load may be sparse, writing only the frames with a 1 in them, because
JPROGRAM zeroes all the others first (cfgplane.load_frames). hw/tb/tb_frames.v [20] runs the
same kind of stream on the RTL. These tests hold the host side: the sparse stream loads exactly
the word, its CRC is the one expected_crc reports, the full stream is unchanged, and a sparse
load that does NOT follow JPROGRAM leaves the old design's frames behind (the reason it may
only follow one).
"""

import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import packets as P  # noqa: E402

FRAME = (1 << P.FB) - 1


def frames_word(rng, frames):
    """a word with random non-zero content in exactly these frames"""
    return sum(((rng.getrandbits(P.FB) | 1) & FRAME) << (P.FB * f) for f in frames)


def load(words, mem=0, jprogram=True):
    c = P.Controller(mem=mem)
    if jprogram:
        c.jprogram()
    c.shift_in(*P.to_jtag(words))
    return c


@pytest.mark.parametrize("frames", [[0], [5], [3, 4, 5], [1, 7, 200, 201, P.NFRAMES - 1],
                                    list(range(0, P.NFRAMES, 3))])
def test_a_sparse_load_after_jprogram_loads_the_word(frames):
    rng = random.Random(len(frames))
    word = frames_word(rng, frames)
    s = P.load_stream(word, sparse=True)
    c = load(s, mem=frames_word(rng, range(P.NFRAMES)))
    assert c.mem == word
    assert c.flags["start_ok"] and not c.errors()
    assert P.used_frames(word) == sorted(set(frames))


def test_the_sparse_stream_carries_only_the_used_frames():
    rng = random.Random(1)
    word = frames_word(rng, [10, 11, 12, 300])
    s = P.load_stream(word, sparse=True)
    assert len(s) < len(P.load_stream(word)) // 10
    fdri = [w for w in s if w >> 29 == 1 and (w >> 13) & 0x1F == P.REG["FDRI"] and w >> 27 & 3 == P.OP_WRITE]
    assert [w & 0x7FF for w in fdri] == [3 * P.FW, 1 * P.FW]          # two runs: 10..12 and 300


def test_the_sparse_crc_is_the_one_expected_crc_reports():
    word = frames_word(random.Random(2), [4, 9, 9 + 1])
    s = P.load_stream(word, sparse=True)
    crc = s[s.index(P.type1(P.OP_WRITE, P.REG["CRC"], 1)) + 1]
    assert crc == P.expected_crc(word, sparse=True)
    assert crc != P.expected_crc(word)                     # the full stream covers other words


def test_a_sparse_load_with_a_wrong_crc_does_not_start():
    word = frames_word(random.Random(3), [7])
    c = load(P.load_stream(word, sparse=True, crc_override=0x1234))
    assert c.flags["crc_err"] and not c.flags["start_ok"]


def test_an_empty_design_still_writes_frame_0_so_start_is_accepted():
    s = P.load_stream(0, sparse=True)
    assert P.used_frames(0) == [0]
    c = load(s, mem=frames_word(random.Random(4), [0, 50]))
    assert c.mem == 0 and c.flags["start_ok"] and not c.errors()


def test_a_run_longer_than_a_type1_count_uses_a_type2_header():
    word = frames_word(random.Random(5), range(P.NFRAMES))       # one run of every frame
    s = P.load_stream(word, sparse=True)
    assert P.type2(P.OP_WRITE, P.NFRAMES * P.FW) in s
    c = load(s)
    assert c.mem == word and c.flags["start_ok"]


def test_bram_contents_travel_in_a_sparse_stream_too():
    rng = random.Random(6)
    word = frames_word(rng, [20])
    contents = [rng.getrandbits(18) for _ in range(40)]
    c = load(P.load_stream(word, brams={1: contents}, sparse=True))
    assert c.mem == word and c.flags["start_ok"]
    assert c.brams[1] == P.bram_words(contents)


def test_a_sparse_load_without_jprogram_leaves_the_old_frames():
    """why cfgplane.load_frames sends a sparse stream only straight after JPROGRAM"""
    rng = random.Random(7)
    old = frames_word(rng, [30, 31])
    new = frames_word(rng, [31])
    c = load(P.load_stream(new, sparse=True), mem=old, jprogram=False)
    assert c.mem != new and (c.mem >> (P.FB * 30)) & FRAME == (old >> (P.FB * 30)) & FRAME
    assert load(P.load_stream(new), mem=old, jprogram=False).mem == new     # the full stream overwrites


def test_the_readback_after_a_sparse_load_is_the_whole_word():
    word = frames_word(random.Random(8), [2, 90, 91])
    c = load(P.load_stream(word, sparse=True))
    c.shift_in(*P.to_jtag(P.readback_stream()))
    words = [c.read_word() for _ in range(P.NFRAMES * P.FW)]
    assert P.word_from_frames(words) == word


def test_a_partial_run_longer_than_a_type1_count_is_still_one_legal_stream():
    """partial_streams and restore_streams share the FDRI writer: runs past 2047 words
    (512 frames) switch to a type-2 header instead of raising"""
    rng = random.Random(9)
    old = frames_word(rng, range(P.NFRAMES))
    new = old ^ ((1 << (P.FB * P.NFRAMES)) - 1)                  # every frame changes
    freeze, frames, n = P.partial_streams(old, new)
    assert n == P.NFRAMES and P.type2(P.OP_WRITE, P.NFRAMES * P.FW) in frames
    c = P.Controller(mem=old)
    c.gwe = 1
    c.shift_in(*P.to_jtag(freeze))
    c.shift_in(*P.to_jtag(frames))
    assert c.mem == new and not c.errors() and not c.frozen()
