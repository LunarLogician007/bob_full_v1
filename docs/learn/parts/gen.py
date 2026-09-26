#!/usr/bin/env python3
"""
gen.py - build docs/learn/bit_by_bit.html (volume 1) from docs/learn/parts/*.html and the chip.

Volume 1 is hand-written prose and animations, but every number in it that describes the chip
on the board is a {{PLACEHOLDER}} filled in here, so the page cannot drift from the hardware
again (until 2026-09-26 it still described the M21 fabric: 32,896 bits, 257 frames, 196 LUTs).
Volumes 2-4 are generated the same way, by docs/learn/{layers,frames,tools}/gen.py.

  software/bob/device.json       grid, channel width, muxes, frames, bits per kind
  hw/build.cfg                   the milestone whose bitstream is on the board
  software/host/dirtyjtag.py     the TCK rate bob's tools use
  software/host/designs.py       the partial-load demo (d_partial AND -> OR): the frame it changes

The page is the parts concatenated in order (a_head, b_body, c_js1, d_js2, e_js3). An unknown
or unfilled placeholder is an error, so a new number cannot be left behind.

    python3 docs/learn/parts/gen.py
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

PARTS = ["a_head.html", "b_body.html", "c_js1.html", "d_js2.html", "e_js3.html"]
OUT = os.path.join(ROOT, "docs", "learn", "bit_by_bit.html")


def n(v):
    return f"{v:,}"


def milestone():
    for ln in open(os.path.join(ROOT, "hw", "build.cfg")):
        m = re.match(r"\s*tag\s*=\s*(\w+)", ln)
        if m:
            return m.group(1)
    raise SystemExit("hw/build.cfg has no tag")


def tck_text():
    import dirtyjtag
    khz = dirtyjtag.DEFAULT_TCK_KHZ
    return (f"{khz // 1000} MHz" if khz % 1000 == 0 else f"{khz} kHz"), khz


def partial_frame():
    """The frame the chapter 11 demo really changes: designs.d_partial's AND and OR differ in
    one LUT, so their words differ in one frame (hwtest partial-swap loads exactly this)."""
    import designs
    import packets
    old = designs.d_partial("and").build().to_int()
    new = designs.d_partial("or").build().to_int()
    ch = packets.changed_frames(old, new)
    if len(ch) != 1:
        raise SystemExit(f"d_partial AND -> OR changes {len(ch)} frames, chapter 11 says one: {ch}")
    return ch[0]


def values():
    d = json.load(open(os.path.join(ROOT, "software", "bob", "device.json")))
    a, c = d["arch"], d["cluster"]
    k = d["lut_k"]
    nclb = sum(1 for b in d["blocks"] if b["type"] == "clb")
    cols = sorted({b["x"] for b in d["blocks"] if b["type"] == "clb"})
    rows = sorted({b["y"] for b in d["blocks"] if b["type"] == "clb"})
    node = {nd[0]: nd[1] for nd in d["rr"]["nodes"]}
    routing = [m for m in d["rr"]["muxes"] if node[m[0]] in ("CHANX", "CHANY", "IPIN")]
    xbar = [m for m in d["rr"]["muxes"] if node[m[0]] == "EIN"]

    # configuration bits by where they live on the host (cfg_store.v keeps a flip-flop for every
    # bit outside the L-frames' masks; the L bits are CFGLUT5 contents, lut_loader.v)
    def width(tt, kind):
        return sum(f["width"] for f in d["tile_types"][tt]["fields"] if f["kind"] == kind)
    per_clb_lut = width("clb", "lut_init") + width("clb", "mux")
    lutram = per_clb_lut * nclb
    fields = {t: sum(f["width"] for f in d["tile_types"][t]["fields"] if f["kind"] != "reserved")
              for t in d["tile_types"]}
    nblk = {t: sum(1 for b in d["blocks"] if b["type"] == t) for t in ("clb", "bram", "dsp")}
    flops = (fields["ctrl"] + sum(fields[t] * nblk[t] for t in nblk) - lutram
             + sum(m[2] for m in routing))
    chain = d["chain"]["width"]
    xbar_bits_elem = k * c["xbar_width"]
    elem_flags = c["element_width"]
    tck, khz = tck_text()
    return {
        "MILESTONE": milestone(),
        "CHAIN_BITS": n(chain),
        "FLOP_BITS": n(flops),
        "LUTRAM_BITS": n(lutram),
        "FRAMES": str(d["frames"]["count"]),
        "FRAMES_LAST": str(d["frames"]["count"] - 1),
        "LUT_BITS": str(1 << k),
        "ELEM_FLAGS": str(elem_flags),
        "ELEM_XBAR_BITS": str(xbar_bits_elem),
        "ELEM_BITS": str((1 << k) + elem_flags + xbar_bits_elem),
        "W": str(a["chan_width"]),
        "ROUTING_MUXES": n(len(routing)),
        "XBAR_MUXES": n(len(xbar)),
        "NCLB": str(nclb),
        "NLUT": str(nclb * c["n"]),
        "GRID": f"{len(cols)} × {len(rows)}",
        "GRID_COLS": str(len(cols)),
        "GRID_ROWS": str(len(rows)),
        "TCK": tck,
        "LOAD_MS": str(round(chain / khz)),
        "PARTIAL_FRAME": str(partial_frame()),
    }


def main():
    v = values()
    page = "".join(open(os.path.join(HERE, p)).read() for p in PARTS)
    used = set(re.findall(r"\{\{(\w+)\}\}", page))
    unknown = used - set(v)
    if unknown:
        raise SystemExit(f"placeholders with no value: {sorted(unknown)}")
    for key, val in v.items():
        page = page.replace("{{" + key + "}}", val)
    open(OUT, "w").write(page)
    unused = sorted(set(v) - used)
    print(f"wrote {os.path.relpath(OUT, ROOT)} ({len(page) // 1024} KB): {v['MILESTONE']}, "
          f"{v['CHAIN_BITS']} bits = {v['FRAMES']} frames, {v['NCLB']} CLBs, {v['NLUT']} LUTs"
          + (f"; values not used: {unused}" if unused else ""))


if __name__ == "__main__":
    main()
