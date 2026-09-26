#!/usr/bin/env python3
"""
gen.py - build docs/learn/layer_by_layer.html from docs/learn/layers/page.html and the real chip.

Every picture in "bob, layer by layer" is drawn from data taken here, not typed in: the grid,
pads and frame columns from software/bob/device.json, the counter example's netlist, packing,
placement, routes and FASM from software/bob/vpr/counter/, the host's use from the newest
docs/reports/M*/util.rpt. Rerun after an architecture change:

    python3 docs/learn/layers/gen.py
"""

import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

EXAMPLE = "counter"


def device():
    d = json.load(open(os.path.join(ROOT, "software", "bob", "device.json")))
    a = d["arch"]
    heights = {c["type"]: c["height"] for c in a["columns"]}
    cells = [[b["x"], b["y"], b["type"], heights.get(b["type"], 1)] for b in d["blocks"]]
    pads = {p["pad"]: [p["x"], p["y"]] for p in d["pads"]["io"]}
    board = ([{"name": b["name"], "xy": pads[b["pad"]], "dir": "in"} for b in d["pads"]["board_inputs"]]
             + [{"name": b["name"], "xy": pads[b["pad"]], "dir": "out"} for b in d["pads"]["board_outputs"]])
    c = d["cluster"]
    return {
        "w": a["grid_width"], "h": a["grid_height"], "cells": cells, "board": board,
        "W": a["chan_width"], "L": a["segment_length"], "sb": a["switch_block"],
        "fc_in": a["fc_in"], "fc_out": a["fc_out"],
        "K": d["lut_k"], "N": c["n"], "I": c["i"], "xbar_w": c["xbar_width"],
        "cfglut5": c["lutram"]["cfglut5_per_clb"], "elem_w": c["element_width"],
        "frames": d["frames"]["count"], "frame_bits": d["frames"]["bits"], "chain": d["chain"]["width"],
        "far_cols": [[col["x"], col["count"]] for col in d["frames"]["columns"]],
        "muxes": len(d["rr"]["muxes"]) - sum(1 for b in d["blocks"] if b["type"] == "clb") * c["n"] * d["lut_k"],
        "xbar_muxes": sum(1 for b in d["blocks"] if b["type"] == "clb") * c["n"] * d["lut_k"], "pads": d["pads"]["count"],
        "nclb": sum(1 for b in d["blocks"] if b["type"] == "clb"),
        "idcode": d.get("clock", {}).get("idcode"),
    }


def example():
    work = os.path.join(ROOT, "software", "bob", "vpr", EXAMPLE)
    src = open(os.path.join(ROOT, "work", "examples", EXAMPLE, f"{EXAMPLE}.v")).read()
    # the packed netlist: clusters and what each element holds
    root = ET.parse(os.path.join(work, f"{EXAMPLE}.net")).getroot()
    place = {}
    for ln in open(os.path.join(work, f"{EXAMPLE}.place")):
        f = ln.split()
        if len(f) >= 3 and not ln.startswith(("#", "Netlist", "Array")) and f[1].isdigit():
            place[f[0]] = [int(f[1]), int(f[2])]
    clusters = []
    for b in root.findall("block"):
        kind = b.get("instance").split("[")[0]
        if kind != "clb":
            continue
        els = []
        for f in b.findall("block"):
            if f.get("name") == "open":
                continue
            atoms = [c.get("instance").split("[")[0] for c in f.iter("block")
                     if c is not f and c.get("name") != "open"
                     and c.get("instance").split("[")[0] in ("add", "ff", "lut", "lutf", "lutd")]
            els.append({"e": int(f.get("instance").split("[")[1][:-1]), "mode": f.get("mode"), "atoms": atoms})
        clusters.append({"xy": place.get(b.get("name")), "elements": els})
    pads = [[n, xy] for n, xy in place.items() if not n.startswith(("bob_", "$"))]
    # routes: every net's wires, with coordinates
    nets, cur = [], None
    for ln in open(os.path.join(work, f"{EXAMPLE}.route")):
        m = re.match(r"Net \d+ \((.+)\)", ln)
        if m:
            cur = {"name": m.group(1), "segs": []}
            nets.append(cur)
            continue
        m = re.match(r"Node:\s+\d+\s+(\w+)\s+\((\d+),(\d+),\d+\)(?:\s+to\s+\((\d+),(\d+),\d+\))?(?:.*Track:\s+(\d+))?", ln)
        if m and cur is not None:
            t = m.group(1)
            x1, y1 = int(m.group(2)), int(m.group(3))
            x2 = int(m.group(4)) if m.group(4) else x1
            y2 = int(m.group(5)) if m.group(5) else y1
            cur["segs"].append([t, x1, y1, x2, y2, int(m.group(6)) if m.group(6) else -1])
    nets = [n for n in nets if any(s[0] in ("CHANX", "CHANY") for s in n["segs"])]
    side = json.load(open(os.path.join(work, f"{EXAMPLE}.vpr.json")))
    import fasm_from_vpr as FV
    feats, _contents = FV.features(work, EXAMPLE)
    lines = FV.to_fasm(feats).splitlines()
    stamp = dict(ln.split(" ", 1) for ln in open(os.path.join(work, "stamp.txt")).read().splitlines() if " " in ln)
    return {"name": EXAMPLE, "verilog": src, "clusters": clusters, "pads": pads, "nets": nets,
            "fasm_count": len(lines),
            "fasm": [ln for ln in lines if ".e1." in ln][:6] + [ln for ln in lines if ln.startswith("rr")][:4],
            "atoms": {k: len(v) for k, v in side.items() if k in ("lut", "ff", "add")},
            "wirelength": stamp.get("wirelength"), "cpd": stamp.get("cpd_ns") or stamp.get("critical_path_ns")}


def host():
    rpts = sorted(glob.glob(os.path.join(ROOT, "docs", "reports", "M*", "util.rpt")),
                  key=lambda p: int(re.search(r"M(\d+)", p).group(1)))
    t = open(rpts[-1]).read()

    def row(name):
        m = re.search(r"^\|\s*" + re.escape(name) + r"\s*\|(.*)\|\s*$", t, re.M)
        if not m:
            return None
        nums = re.findall(r"[\d.]+", m.group(1))
        return [int(nums[0]), float(nums[-1])]
    m = re.search(r"\|\s+SLICEM\s+\|\s*(\d+)", t)
    return {"from": os.path.relpath(rpts[-1], ROOT), "luts": row("Slice LUTs"), "logic": row("LUT as Logic"),
            "mem": row("LUT as Memory"), "ffs": row("Slice Registers"), "slices": row("Slice"),
            "slicem": int(m.group(1)) if m else None}


def silicon():
    """Chapter 13's counts. Configuration bits by where they live on the host (cfg_store.v
    keeps a flip-flop for every bit outside the L-frames; the L bits are CFGLUT5 contents),
    and how many distinct tile layouts the routing needs: two tiles are the same layout when
    their multiplexers drive the same local tracks from the same local tracks and pins. A
    physical-design flow would draw each distinct layout once (OpenFPGA's tile grouping)."""
    import bisect
    import collections
    d = json.load(open(os.path.join(ROOT, "software", "bob", "device.json")))
    nodes = {nd[0]: nd for nd in d["rr"]["nodes"]}
    nclb = sum(1 for b in d["blocks"] if b["type"] == "clb")
    fields = lambda t, kinds: sum(f["width"] for f in d["tile_types"][t]["fields"] if f["kind"] in kinds)  # noqa: E731
    lutram = fields("clb", ("lut_init", "mux")) * nclb
    nblk = {t: sum(1 for b in d["blocks"] if b["type"] == t) for t in ("clb", "bram", "dsp")}
    used = ("lut_init", "mux", "flag", "value")
    routing = [m for m in d["rr"]["muxes"] if nodes[m[0]][1] in ("CHANX", "CHANY", "IPIN")]
    flops = (fields("ctrl", used) + sum(fields(t, used) * nblk[t] for t in nblk) - lutram
             + sum(m[2] for m in routing))

    tiles = sorted(d["tiles"], key=lambda t: t["chain_lo"])
    los = [t["chain_lo"] for t in tiles]
    blocks = {(b["x"], b["y"]): b["type"] for b in d["blocks"]}

    def local(q, tx, ty):
        kind, xl, yl, xh, yh, ptc = q[1], q[2], q[3], q[4], q[5], q[6]
        if kind in ("CHANX", "CHANY"):
            tracks = [int(v) for v in ptc.split(",")]
            if kind == "CHANX":
                i, side = tx - xl, (0 if xl <= tx <= xh else (1 if tx < xl else -1), yl - ty)
            else:
                i, side = ty - yl, (xl - tx, 0 if yl <= ty <= yh else (1 if ty < yl else -1))
            return (kind, q[7], tracks[min(max(i, 0), len(tracks) - 1)], side)
        return (kind, xl - tx, yl - ty, ptc)
    sig = collections.defaultdict(list)
    for nid, lo, w, _base, ins in d["rr"]["muxes"]:
        t = tiles[bisect.bisect_right(los, lo) - 1]
        if t["kind"] != "grid" or nodes[nid][1] == "EIN":
            continue
        tx, ty = t["x"], t["y"]
        sig[(tx, ty)].append((local(nodes[nid], tx, ty), w, tuple(sorted(local(nodes[k], tx, ty) for k in ins))))
    layouts = {}
    for xy, s in sig.items():
        layouts.setdefault((blocks.get(xy, "none"), tuple(sorted(s))), []).append(xy)
    kinds = collections.Counter(k[0] for k in layouts)
    return {"chain": d["chain"]["width"], "flops": flops, "lutram": lutram,
            "routing": len(routing), "xbar": len(d["rr"]["muxes"]) - len(routing),
            "tiles": len(sig), "layouts": len(layouts), "clb_layouts": kinds.get("clb", 0),
            "clb_tiles": sum(1 for xy in sig if blocks.get(xy) == "clb"),
            "biggest": max(len(v) for v in layouts.values())}


def main():
    dl = json.load(open(os.path.join(ROOT, "software", "bob", "delays.json")))
    import timing as T
    data = {"dev": device(), "ex": example(), "host": host(), "si": silicon(),
            "delays": {"ns": dl["ns"], "provisional": dl.get("provisional", False),
                       "guard": T.MARGIN_PROVISIONAL if dl.get("provisional") else T.MARGIN_MEASURED,
                       "measured_guard": T.MARGIN_MEASURED}}
    page = open(os.path.join(HERE, "page.html")).read()
    out = page.replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))
    path = os.path.join(ROOT, "docs", "learn", "layer_by_layer.html")
    open(path, "w").write(out)
    print(f"wrote {os.path.relpath(path, ROOT)} ({len(out) // 1024} KB; {data['dev']['nclb']} CLBs, "
          f"{len(data['ex']['nets'])} routed nets of {EXAMPLE}, host from {data['host']['from']})")


if __name__ == "__main__":
    main()
