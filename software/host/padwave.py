#!/usr/bin/env python3
"""
padwave.py - a logic analyser on the pads, read through JTAG (M19).

Vivado's ILA sits inside the design and samples chosen nets into block RAM. bob needs no
extra logic for the pads: every pad already has two boundary cells (software/bob/device.json
"bsr"), bit n holding what the fabric drives out of pad n and bit NPAD + n the level on its
pin. A capture is a run of boundary scans, each one a sample of all 44 pads at once.

Two ways to take the samples, the choice an ILA makes with its sample clock:

  step   INTEST with USER1 autostep (the M10 board checks): every scan applies the input
         cells, gives the user clock one edge, and captures the outputs. One sample per user
         clock, cycle-exact, with the inputs chosen here (hold a vector, random, or follow the
         real switches, which costs a SAMPLE scan per cycle). The design must be built for the
         stepped clock (--clock jtag); a free-running design keeps running regardless.
  live   SAMPLE, repeated: the design runs undisturbed on its own clock and on the real
         switches, and each scan is stamped with the time it was taken. As fast as the probe
         scans (a few hundred per second on the Pico at 100 kHz TCK), so it shows what the pads
         do at human speeds, not every clock of a fast design.

A trigger is a condition on one signal (rise, fall, high, low, change) with a share of the
depth kept from before it, as an ILA's trigger position. Without one, capture starts at once.

  capture(probe, mode, depth, signals, trigger=None, pre=0.25, stimulus=...) -> dict
  vcd(capture) -> text for GTKWave and friends
"""

import random
import time

from bitstream import BOARD_IN, BOARD_OUT, BSR_W, NPAD, PAD_XY

BOARD_IN_NAMES = ["SW0", "SW1", "BTN0", "BTN1", "BTN2", "BTN3"]
BOARD_OUT_NAMES = ["LD0", "LD1", "LD2"]
CONDITIONS = ("rise", "fall", "high", "low", "change")
MODES = ("step", "live")
MAX_DEPTH = 4096


class WaveError(Exception):
    pass


def signals(pins=None):
    """Every pad as a signal: the board's named inputs (pin cell) and LEDs (output cell),
    then the other pads, both cells, named after the design's ports where a pin map says.

    pins: {"port[i]": pad} from the loaded design's .pcf, or None for the convention
    (sw[1:0], btn[3:0], led[2:0], as vpr_run.board_pins places them)."""
    if pins is None:
        pins = {**{f"sw[{k}]": BOARD_IN[k] for k in range(2)},
                **{f"btn[{k}]": BOARD_IN[2 + k] for k in range(4)},
                **{f"led[{k}]": BOARD_OUT[k] for k in range(3)}}
    port_of = {}
    for port, pad in (pins or {}).items():
        port_of.setdefault(pad, port)
    out = []
    for k, pad in enumerate(BOARD_IN):
        out.append({"name": BOARD_IN_NAMES[k], "pad": pad, "cell": "in", "port": port_of.get(pad),
                    "board": True})
    for k, pad in enumerate(BOARD_OUT):
        out.append({"name": BOARD_OUT_NAMES[k], "pad": pad, "cell": "out", "port": port_of.get(pad),
                    "board": True})
    named = set(BOARD_IN) | set(BOARD_OUT)
    for pad in sorted(PAD_XY):
        if pad in named:
            continue
        for cell in ("out", "in"):
            out.append({"name": f"pad{pad}.{cell}", "pad": pad, "cell": cell, "port": port_of.get(pad),
                        "board": False})
    return out


def _bit(raw, sig):
    return (raw >> (sig["pad"] if sig["cell"] == "out" else NPAD + sig["pad"])) & 1


def _in_word(vector):
    """A board input vector (bit k = SW0, SW1, BTN0..3) -> the boundary's input cells."""
    return sum(((vector >> k) & 1) << (NPAD + pad) for k, pad in enumerate(BOARD_IN))


def _vector_of(raw):
    return sum(((raw >> (NPAD + pad)) & 1) << k for k, pad in enumerate(BOARD_IN))


def _fires(cond, prev, cur):
    if cond == "rise":
        return prev == 0 and cur == 1
    if cond == "fall":
        return prev == 1 and cur == 0
    if cond == "high":
        return cur == 1
    if cond == "low":
        return cur == 0
    return prev is not None and prev != cur            # change


def capture(p, mode="step", depth=256, sel=None, trigger=None, pre=0.25,
            stimulus=None, timeout=10.0, pins=None):
    """-> {"mode", "signals": [...], "samples": [[bit per signal] ...], "t": [...],
    "trigger": index or None, "vectors": [...], "raw": [hex ...]}

    sel      signal names to keep (default: every board pin)
    trigger  {"signal": name, "cond": one of CONDITIONS} or None
    pre      share of the depth kept from before the trigger (0 .. 0.9)
    stimulus (step only) {"kind": "hold", "vector": n} | {"kind": "random", "seed": n}
             | {"kind": "pins"} | {"kind": "sequence", "vectors": [...]} (then held at the last):
             inputs applied each cycle, bit k = SW0, SW1, BTN0..BTN3
    timeout  seconds to wait for the trigger before giving up"""
    import cfgplane
    import fpga
    if mode not in MODES:
        raise WaveError(f"mode is one of {MODES}")
    depth = int(depth)
    if not 2 <= depth <= MAX_DEPTH:
        raise WaveError(f"depth is 2 .. {MAX_DEPTH} samples")
    every = signals(pins)
    by_name = {s["name"]: s for s in every}
    sel = sel or [s["name"] for s in every if s["board"]]
    bad = [n for n in sel if n not in by_name]
    if bad:
        raise WaveError(f"no signal(s) {bad}")
    chosen = [by_name[n] for n in sel]
    trig = None
    if trigger and trigger.get("signal"):
        if trigger["signal"] not in by_name:
            raise WaveError(f"no signal {trigger['signal']} to trigger on")
        if trigger.get("cond", "rise") not in CONDITIONS:
            raise WaveError(f"a trigger condition is one of {CONDITIONS}")
        trig = (by_name[trigger["signal"]], trigger.get("cond", "rise"))
    pre_n = int(depth * min(0.9, max(0.0, float(pre)))) if trig else 0
    stimulus = stimulus or {"kind": "hold", "vector": 0}
    rnd = random.Random(stimulus.get("seed", 1))

    ring = []                  # (t, raw, vector) before the trigger, at most pre_n kept
    post = []
    fired_at = None
    prev = None
    t0 = time.time()
    scans = 0

    if mode == "step":
        kind = stimulus.get("kind", "hold")
        if kind not in ("hold", "random", "pins", "sequence"):
            raise WaveError("stimulus is hold, random, pins or sequence")
        seq = [int(v) & 0x3F for v in stimulus.get("vectors", [])] if kind == "sequence" else []
        if kind == "sequence" and not seq:
            raise WaveError("a sequence stimulus needs vectors")
        step_n = [0]
        cfgplane.user1(p, 0x10)                     # autostep: one user clock per INTEST scan
        cfgplane.ir(p, "INTEST")

        def next_vector():
            if kind == "hold":
                return int(stimulus.get("vector", 0)) & 0x3F
            if kind == "random":
                return rnd.getrandbits(6)
            if kind == "sequence":
                v = seq[min(step_n[0], len(seq) - 1)]
                step_n[0] += 1
                return v
            cfgplane.ir(p, "SAMPLE")                # the real switches, then back to stepping
            v = _vector_of(p.shift_dr_fast(BSR_W, 0))
            cfgplane.ir(p, "INTEST")
            return v

        vec = next_vector()
        p.shift_dr_fast(BSR_W, _in_word(vec))       # applies vec, clocks once
        cycle = 0
        try:
            while True:
                nxt = next_vector()
                raw = p.shift_dr_fast(BSR_W, _in_word(nxt))   # outputs after the edge with vec applied
                scans += 1
                # the input cells of a sample are the vector that was applied for that clock
                raw = (raw & ((1 << NPAD) - 1)) | _in_word(vec)
                sample = (cycle, raw, vec)
                cycle += 1
                vec = nxt
                if fired_at is None:
                    cur = _bit(raw, trig[0]) if trig else None
                    if not trig or _fires(trig[1], prev, cur):
                        fired_at = len(ring)
                        post.append(sample)
                    else:
                        ring.append(sample)
                        if len(ring) > pre_n:
                            ring.pop(0)
                        prev = cur
                        if time.time() - t0 > timeout or cycle > 200 * MAX_DEPTH:
                            raise WaveError(f"no trigger ({trig[0]['name']} {trig[1]}) in {cycle} "
                                            f"clocks / {timeout:.0f} s")
                elif len(ring) + len(post) < depth:
                    post.append(sample)
                if fired_at is not None and len(ring) + len(post) >= depth:
                    break
        finally:
            cfgplane.user1(p, 0)
            fpga.go_live(p)
    else:
        cfgplane.ir(p, "SAMPLE")
        while True:
            raw = p.shift_dr_fast(BSR_W, 0)
            scans += 1
            sample = (time.time() - t0, raw, _vector_of(raw))
            if fired_at is None:
                cur = _bit(raw, trig[0]) if trig else None
                if not trig or _fires(trig[1], prev, cur):
                    fired_at = len(ring)
                    post.append(sample)
                else:
                    ring.append(sample)
                    if len(ring) > pre_n:
                        ring.pop(0)
                    prev = cur
                    if time.time() - t0 > timeout:
                        raise WaveError(f"no trigger ({trig[0]['name']} {trig[1]}) in "
                                        f"{timeout:.0f} s ({scans} samples)")
            else:
                post.append(sample)
            if fired_at is not None and len(ring) + len(post) >= depth:
                break

    rows = ring + post
    rows = rows[:depth]
    t_first = rows[0][0]
    elapsed = time.time() - t0
    return {"mode": mode, "depth": len(rows),
            "signals": [dict(s) for s in chosen],
            "samples": [[_bit(raw, s) for s in chosen] for _t, raw, _v in rows],
            "t": [round(t - t_first, 6) if mode == "live" else t - t_first for t, _r, _v in rows],
            "unit": "s" if mode == "live" else "clock",
            "vectors": [v for _t, _r, v in rows],
            "raw": [f"{raw:0{(BSR_W + 3) // 4}X}" for _t, raw, _v in rows],
            "trigger": fired_at if trig else None,
            "trigger_on": {"signal": trig[0]["name"], "cond": trig[1]} if trig else None,
            "scans": scans, "seconds": round(elapsed, 3),
            "rate": round(scans / elapsed, 1) if elapsed > 0 else None}


def vcd(cap, date=None):
    """A capture as VCD. Step captures use one time unit per user clock (1 us timescale, as a
    label); live captures their real times in microseconds."""
    ids = [chr(33 + k) if k < 94 else f"s{k}" for k in range(len(cap["signals"]))]
    out = [f"$date {date or time.strftime('%Y-%m-%d %H:%M:%S')} $end",
           "$version bob wave.py (boundary-scan capture) $end",
           "$timescale 1us $end",
           "$scope module pads $end"]
    for sid, s in zip(ids, cap["signals"]):
        name = (s["port"] or s["name"]).replace("[", "_").replace("]", "").replace(".", "_")
        out.append(f"$var wire 1 {sid} {name} $end")
    out += ["$upscope $end", "$enddefinitions $end"]
    last = [None] * len(ids)
    for k, row in enumerate(cap["samples"]):
        t = int(round(cap["t"][k] * 1e6)) if cap["unit"] == "s" else k
        changes = [f"{v}{sid}" for v, sid, old in zip(row, ids, last) if v != old]
        if changes:
            out.append(f"#{t}")
            out += changes
        last = row
    end = cap["t"][-1] if cap["samples"] else 0
    out.append(f"#{int(round(end * 1e6)) + 1 if cap['unit'] == 's' else len(cap['samples'])}")
    return "\n".join(out) + "\n"
