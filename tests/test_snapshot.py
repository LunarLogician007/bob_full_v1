"""M25 time-travel debugging: software/host/snapshot.py and `bob snap`, on the stand-in board."""

import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))

import bitstream as B  # noqa: E402
import cfgplane  # noqa: E402
import fpga  # noqa: E402
import packets as P  # noqa: E402
import snapshot as S  # noqa: E402
from designs import COUNTER_X, counter_cells, d_counter, d_dd  # noqa: E402
from fakeboard import FakeBob  # noqa: E402

IDX = {(e["x"], e["y"], e["e"]): e["index"] for e in B.ELEMENTS}


def value(state):
    return sum(state[(IDX[c], 0)] << r for r, c in enumerate(counter_cells(COUNTER_X, 4)))


def step(p, n):
    for _ in range(n):
        cfgplane.user1(p, 0b1100)
        cfgplane.user1(p, 0b0100)


@pytest.fixture
def board():
    p = FakeBob()
    word = d_counter("jtag").build().to_int()
    assert fpga.load_bitstream(p, B.Bitstream(word), verbose=False)
    cfgplane.user1(p, 0b0100)
    return p, word


def test_registers_are_the_flip_flops_the_design_uses():
    word = d_counter("jtag").build().to_int()
    assert sorted(S.registers(word)) == sorted((IDX[c], 0) for c in counter_cells(COUNTER_X, 4))
    assert S.registers(d_dd().build().to_int()) == []          # combinational: nothing to save


def test_with_init_changes_only_the_init_bits():
    word = d_counter("jtag").build().to_int()
    state = {(IDX[c], 0): 1 for c in counter_cells(COUNTER_X, 4)}
    init = S.with_init(word, state)
    diff = word ^ init
    assert bin(diff).count("1") == 4
    frames = P.changed_frames(word, init)
    assert 1 <= len(frames) <= 2                               # the counter's CLB flag frame(s)


def test_restore_stream_writes_the_init_frames_twice_around_one_grestore():
    word = d_counter("jtag").build().to_int()
    init = S.with_init(word, {(IDX[c], 0): 1 for c in counter_cells(COUNTER_X, 4)})
    _fr, frames, n = P.restore_streams(word, init)
    fdri = sum(1 for w in frames if (w >> 29) == 1 and (w >> 13) & 0x1F == P.REG["FDRI"] and (w >> 27) & 3 == 2)
    assert fdri == 2 * len(P._frame_runs(P.changed_frames(word, init)))
    assert P.CMD["GRESTORE"] in frames and frames[-S.LFRM_TAIL:][3] == P.CMD["LFRM"]


def test_snapshot_restore_and_count_on(board):
    p, word = board
    step(p, 3)
    a, notes = S.snapshot(p, word)
    assert value(a) == 3 and notes == []
    step(p, 7)
    assert value(S.capture(p, word)) == 10
    S.restore(p, word, a)
    assert value(S.capture(p, word)) == 3
    step(p, 2)
    assert value(S.capture(p, word)) == 5


def test_the_simulator_hand_off_round_trip(board):
    p, word = board
    step(p, 4)
    m = S.to_model(word, S.capture(p, word))
    for _ in range(6):
        m.clock(cin=1)
    S.restore(p, word, S.from_model(m, word))
    assert value(S.capture(p, word)) == 10


def test_restore_raises_when_the_chip_does_not_take_it():
    p = FakeBob(no_grestore=True)
    word = d_counter("jtag").build().to_int()
    assert fpga.load_bitstream(p, B.Bitstream(word), verbose=False)
    state = {(IDX[c], 0): 1 for c in counter_cells(COUNTER_X, 4)}
    with pytest.raises(S.SnapshotError):
        S.restore(p, word, state)


def test_grestore_unfrozen_after_startup_is_refused(board):
    p, word = board
    loose = ([P.DUMMY, P.SYNC, P.NOP] + P.write("IDCODE", P.device_idcode()) + P.write("CMD", P.CMD["GRESTORE"])
             + P.write("CMD", P.CMD["DESYNC"]) + [P.NOP, P.NOP])
    cfgplane.frames_send(p, loose)
    assert cfgplane.frames_stat(p)["WR_ERROR"]


def test_bob_snap_save_restore_sim(board, tmp_path, monkeypatch):
    import cli
    p, word = board
    import fakeboard
    monkeypatch.setattr(fakeboard, "probe", lambda *a, **k: p)
    monkeypatch.setattr(cli, "SNAP_DIR", str(tmp_path))
    ns = lambda **k: types.SimpleNamespace(**{"name": None, "steps": 1, "pads": 0, "save": None,  # noqa: E731
                                              "cin": 0, "probe": "fake", **k})
    step(p, 2)
    assert cli.snap_cmd(ns(action="save", name="a")) == 0
    step(p, 5)
    assert cli.snap_cmd(ns(action="restore", name="a")) == 0
    assert value(S.capture(p, word)) == 2
    assert cli.snap_cmd(ns(action="sim", name="a", steps=4, cin=1, save="b")) == 0
    assert cli.snap_cmd(ns(action="restore", name="b")) == 0
    assert value(S.capture(p, word)) == 6                       # 2 on the chip, +4 in model.py
    assert cli.snap_cmd(ns(action="list")) == 0
