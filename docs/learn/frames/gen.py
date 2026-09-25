#!/usr/bin/env python3
"""
gen.py - build docs/learn/frame_by_frame.html (volume 3) from docs/learn/frames/page.html and the chip.

"bob, frame by frame" follows one configuration from the cable into the chip: JTAG, the TAP,
the packet stream, the packet parser (bob's configuration "brain"), frames and the frame
address, where every frame lands on the grid, the two kinds of configuration cell, startup,
readback, and where it all sits on the XC7Z020. Every number and picture comes from here:

  software/bob/device.json      grid, frame columns, which tile owns every frame, L-frames
  software/bob/packets.py       the real load stream of the counter example, and its CRC
  software/bob/vpr/counter/     the counter example's configuration word (its frames)
  software/bob/vpr/fir16/       the busiest CLB of fir16, whose truth tables are full (chapter 9)
  docs/reports/M*/floorplan.txt where Vivado put each part of bob (hw/scripts/floorplan.tcl);
                                without it the last chapter says how to get it

The style is volume 2's (docs/learn/layers/page.html), spliced in, so the volumes match.

    python3 docs/learn/frames/gen.py
"""

import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

EXAMPLE = "counter"
OUT = os.path.join(ROOT, "docs", "learn", "frame_by_frame.html")


def device():
    d = json.load(open(os.path.join(ROOT, "software", "bob", "device.json")))
    a = d["arch"]
    heights = {c["type"]: c["height"] for c in a["columns"]}
    cells = [[b["x"], b["y"], b["type"], heights.get(b["type"], 1)] for b in d["blocks"]]
    F = d["frames"]
    return d, {
        "w": a["grid_width"], "h": a["grid_height"], "cells": cells,
        "frames": F["count"], "fbits": F["bits"], "fwords": F["words"], "chain": d["chain"]["width"],
        "cols": [[c["far_col"], c["x"], c["base"], c["count"]] for c in F["columns"]],
        "nclb": sum(1 for b in d["blocks"] if b["type"] == "clb"), "K": d["lut_k"],
        "N": d["cluster"]["n"],
    }


def frame_map(d):
    """every frame -> [kind, owner x, owner y, used bits]; kinds: ctrl, route (routing and
    block fields in flip-flops), xbar / init (CLB bits that live in CFGLUT5s), bram, dsp, pad"""
    fb = d["frames"]["bits"]
    lf = {f: (clb, kind) for f, clb, kind, _i in d["lframes"]["list"]}
    blocks = {(b["x"], b["y"]): b["type"] for b in d["blocks"]}
    tiles = sorted(d["tiles"], key=lambda t: t["chain_lo"])
    out = []
    for f in range(d["frames"]["count"]):
        lo, hi = f * fb, f * fb + fb
        if f in lf:
            clb, kind = lf[f]
            m = re.match(r"clb_x(\d+)y(\d+)", clb)
            out.append([kind, int(m.group(1)), int(m.group(2)), fb])
            continue
        own, used = None, 0
        for t in tiles:
            a, b = t["chain_lo"], t["chain_lo"] + t["width"]
            if b <= lo or a >= hi or t["kind"] == "tail":
                continue
            used += min(b, hi) - max(a, lo)
            if own is None:
                own = t
        if own is None:
            out.append(["pad", -1, -1, 0])
        elif own["kind"] == "ctrl":
            out.append(["ctrl", -1, -1, used])
        else:
            typ = blocks.get((own["x"], own["y"]))
            kind = {"bram": "bram", "dsp": "dsp"}.get(typ, "route")
            out.append([kind, own["x"], own["y"], used])
    return out


def example_word(name=EXAMPLE):
    import bitgen
    import fasm_from_vpr as FV
    work = os.path.join(ROOT, "software", "bob", "vpr", name)
    _bs, contents, text = FV.build(name, work)
    return bitgen.word_from_features(bitgen.parse_fasm(text)), contents


CLB_EXAMPLE = "fir16"      # the counter is all adders (Double Duty): its truth tables are empty


def busiest_clb(fm, fb):
    """the CLB of CLB_EXAMPLE with the most truth-table frames, then the most 1 bits:
    its frames, each as hex, so chapter 9 shows real, full tables"""
    word, _ = example_word(CLB_EXAMPLE)
    per = {}
    for f, (kind, x, y, _u) in enumerate(fm):
        if kind in ("xbar", "init", "route") and x >= 0:
            v = (word >> (f * fb)) & ((1 << fb) - 1)
            per.setdefault((x, y), []).append((f, v))
    def score(kv):
        fr = kv[1]
        return (sum(1 for f, v in fr if fm[f][0] == "init" and v), sum(bin(v).count("1") for _f, v in fr))
    (x, y), frames = max(per.items(), key=score)
    return {"example": CLB_EXAMPLE, "xy": [x, y],
            "frames": [[f, fm[f][0], f"{v:032X}"] for f, v in frames]}


def stream(word, brams):
    import packets as PK
    words = PK.load_stream(word, brams=brams)
    fb = PK.FB
    nz = [f for f in range(PK.NFRAMES) if (word >> (f * fb)) & ((1 << fb) - 1)]
    # the stream with the frame data shown as a count, and a few real frame words
    head, i = [], 0
    while i < len(words) and words[i] != 0x30004000:
        head.append(f"{words[i]:08X}")
        i += 1
    t2 = words[i + 1]
    data0 = i + 2
    tail = [f"{w:08X}" for w in words[data0 + (t2 & 0x7FFFFFF):]]
    return {"head": head, "fdri": [f"{words[i]:08X}", f"{t2:08X}"], "count": t2 & 0x7FFFFFF,
            "first": [f"{w:08X}" for w in words[data0:data0 + 8]], "tail": tail,
            "total": len(words), "idcode": f"{PK.device_idcode():08X}",
            "crc": f"{PK.expected_crc(word, brams=brams):08X}", "nonzero": nz,
            "frames": {str(f): f"{(word >> (f * fb)) & ((1 << fb) - 1):032X}" for f in nz[:40]}}


def floorplan():
    """the newest docs/reports/M*/floorplan.txt -> sites grouped by part, or None"""
    found = sorted(glob.glob(os.path.join(ROOT, "docs", "reports", "M*", "floorplan.txt")),
                   key=lambda p: int(re.search(r"M(\d+)", p).group(1)))
    if not found:
        return None
    path = found[-1]
    sites, groups, part = [], [], None
    for ln in open(path):
        if ln.startswith("# floorplan.tcl:"):
            part = ln.split()[2]
        if ln.startswith("#") or not ln.strip():
            continue
        f = ln.split()
        if len(f) < 6:
            continue
        g = f[4]
        if re.match(r"clb_x\d+y\d+", g):
            g = "clb"                       # every guest CLB one colour; the count says how many
        if g not in groups:
            groups.append(g)
        kind = "S" if f[0].startswith("SLICE") else "B" if f[0].startswith("RAMB") else "D"
        sites.append([kind, int(f[1]), int(f[2]), groups.index(g)])
    return {"from": os.path.relpath(path, ROOT), "part": part, "groups": groups, "sites": sites}


def main():
    d, dev = device()
    word, brams = example_word()
    fm = frame_map(d)
    data = {"dev": dev, "fmap": fm, "st": stream(word, brams), "fp": floorplan(),
            "example": EXAMPLE, "clb": busiest_clb(fm, dev["fbits"])}
    style = open(os.path.join(ROOT, "docs", "learn", "layers", "page.html")).read()
    style = style[style.index("<style>"):style.index("</style>") + len("</style>")]
    page = open(os.path.join(HERE, "page.html")).read()
    out = page.replace("<!--STYLE-->", style).replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))
    open(OUT, "w").write(out)
    fp = data["fp"]
    print(f"wrote {os.path.relpath(OUT, ROOT)} ({len(out) // 1024} KB; {dev['frames']} frames, "
          f"{len(data['st']['nonzero'])} used by {EXAMPLE}; floorplan "
          f"{('from ' + fp['from'] + ', ' + str(len(fp['sites'])) + ' sites') if fp else 'not yet (hw/scripts/floorplan.tcl)'})")


if __name__ == "__main__":
    main()
