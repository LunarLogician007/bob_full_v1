#!/usr/bin/env python3
"""
snapshot.py - time-travel debugging: capture a running design's state, restore it (M25).

After Attia & Betz, "Toward Software-like Debugging for FPGAs via Checkpointing and
Transaction-based Co-Simulation" (TRETS 2022), on bob's own configuration plane:

  capture   freeze the fabric (UG470 AGHIGH: every user-clock enable held, M14) and read
            every flip-flop through CAPTURE (element i: bit 2i = out[0] = FF q, bit 2i+1 =
            out[1] = FF2 q, for the flip-flops the design uses)
  restore   one partial stream (packets.restore_streams): the CLB frames with each used
            flip-flop's INIT/reset bit (ff_rstval / ff2_rstval) set to the snapshot, then
            UG470 GRESTORE (CMD 10: the fabric's GSR, every flip-flop takes its INIT value),
            then the original frames back, one CRC over it all, LFRM. The state is read back
            through CAPTURE while still frozen, before the release.
  model     a snapshot becomes model.py's state (to_model) and back (from_model): run a
            design on the board, move it into the simulator, step it there, and push the
            simulator's state back onto the chip.

What a snapshot holds: the CLB flip-flops. BRAM contents are left as they are (GRESTORE does
not touch them, and bob reads them with USER4 / FDRO when it needs to). Not restored: BRAM
output registers and DSP pipeline registers, which GSR resets (UG470: the same holds for
AMD's GRESTORE) - `snapshot()` says so for a design that uses them.

    from snapshot import freeze, capture, restore, resume
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bob"))

import bitstream as B  # noqa: E402

LFRM_TAIL = 8          # words: CRC, CMD LFRM, CMD DESYNC (2 each) + 2 NOPs (packets.restore_streams)


class SnapshotError(Exception):
    pass


def registers(word):
    """[(element index, 0 or 1)] of every flip-flop the design uses (ff_en / ff2_en)"""
    bs = B.Bitstream(word)
    out = []
    for el in B.ELEMENTS:
        for which, flag in ((0, "ff_en"), (1, "ff2_en")):
            if bs.get_block(el["name"], flag):
                out.append((el["index"], which))
    return out


def lossy_parts(word):
    """what GRESTORE resets but a snapshot cannot restore: BRAM output registers and DSP
    pipeline registers the design enables"""
    bs = B.Bitstream(word)
    parts = []
    for b in range(B.NBRAM):
        if any(bs.get_bram(b, f"reg_{p}") for p in "ab"):
            parts.append(f"bram{b} output register")
    for s in range(B.NDSP):
        if any(bs.get_dsp(s, f) for f in ("areg", "breg", "creg", "dreg", "mreg", "preg")):
            parts.append(f"dsp{s} pipeline registers")
    return parts


def from_capture(word, cap):
    """{(element index, 0|1): bit} from a CAPTURE word"""
    return {(i, w): (cap >> (2 * i + w)) & 1 for i, w in registers(word)}


def with_init(word, state):
    """the design with each used flip-flop's INIT/reset bit set to `state`"""
    bs = B.Bitstream(word)
    by_index = {el["index"]: el["name"] for el in B.ELEMENTS}
    for (i, w), v in state.items():
        bs.set_block(by_index[i], "ff_rstval" if w == 0 else "ff2_rstval", v)
    return bs.to_int()


# --- the board ---------------------------------------------------------------------------

def _stat_ok(p, frozen):
    import cfgplane
    st = cfgplane.frames_stat(p)
    errs = [k for k in ("CRC_ERROR", "ID_ERROR", "PKT_ERROR", "WR_ERROR") if st[k]]
    if errs:
        raise SnapshotError(f"STAT {errs}")
    if bool(st["GHIGH_B"]) == frozen:
        raise SnapshotError(f"GHIGH_B={st['GHIGH_B']}: the fabric is {'not ' if frozen else ''}frozen")


def freeze(p, word):
    """hold the design (AGHIGH); returns the stream tail that releases it (resume())"""
    import cfgplane
    import packets
    fr, frames, _n = packets.partial_streams(word, word)
    cfgplane.frames_send(p, fr)
    _stat_ok(p, frozen=True)
    return frames                        # WCFG, no frames, CRC, LFRM


def resume(p, tail):
    import cfgplane
    cfgplane.frames_send(p, tail)
    _stat_ok(p, frozen=False)


def capture(p, word):
    """the design's flip-flops, read through CAPTURE (freeze first for a running design)"""
    import cfgplane
    return from_capture(word, cfgplane.capture(p, B.NCAP))


def snapshot(p, word):
    """freeze, capture, release: (state, notes)"""
    tail = freeze(p, word)
    try:
        state = capture(p, word)
    finally:
        resume(p, tail)
    return state, lossy_parts(word)


def restore(p, word, state, keep_frozen=False):
    """put `state` back into the running design (see the module doc). Verified through
    CAPTURE before the release; raises SnapshotError if the chip does not hold it. Returns
    the number of frames rewritten (each twice). With keep_frozen the release tail is
    returned instead of sent (the caller resumes)."""
    import cfgplane
    import packets
    init = with_init(word, state)
    fr, frames, n = packets.restore_streams(word, init)
    body, tail = frames[:-LFRM_TAIL], frames[-LFRM_TAIL:]
    cfgplane.frames_send(p, fr)
    _stat_ok(p, frozen=True)
    cfgplane.frames_send(p, body)
    _stat_ok(p, frozen=True)
    got = capture(p, word)
    bad = [k for k, v in state.items() if got.get(k) != v]
    if bad:
        cfgplane.frames_send(p, tail)
        raise SnapshotError(f"{len(bad)} of {len(state)} flip-flops did not take the snapshot, "
                            f"e.g. element {bad[0][0]} FF{bad[0][1] + 1}")
    if keep_frozen:
        return n, tail
    resume(p, tail)
    return n


# --- the simulator ---------------------------------------------------------------------

def to_model(word, state):
    """a model.Fabric of the design holding `state` (to step in software)"""
    import model
    m = model.Fabric(B.Bitstream(word))
    xy = {el["index"]: (el["x"], el["y"], el["e"]) for el in B.ELEMENTS}
    for (i, w), v in state.items():
        (m.q if w == 0 else m.q2)[xy[i]] = v
    return m


def from_model(m, word):
    """the model's flip-flops as a snapshot of `word`'s design"""
    xy = {el["index"]: (el["x"], el["y"], el["e"]) for el in B.ELEMENTS}
    return {(i, w): (m.q if w == 0 else m.q2)[xy[i]] for i, w in registers(word)}
