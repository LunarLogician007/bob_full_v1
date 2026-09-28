#!/usr/bin/env python3
"""
make_example.py - one design through bob's whole flow, every file kept, stage by stage.

  python3 example/make_example.py                      # work/examples/counter -> example/
  python3 example/make_example.py --design gates --out build/example_gates
  python3 example/make_example.py --reuse-vpr          # no Docker: the committed VPR result

Each numbered folder is one stage of the flow: what went in (inputs/, or the previous
folder), what came out, and readable views of it. The tools are the real ones, run the
way ./bob build runs them: yosys and iverilog (software/bob/synth.py, equiv.py), VPR in
OpenFPGA's Docker image (software/bob/vpr_run.py), fasm_from_vpr.py, bitgen.py, timing.py,
model.py, and the load and run go to the stand-in board (software/host/fakeboard.py),
which answers JTAG exactly as the PYNQ-Z2 does. example/README.md explains every file.
"""

import argparse
import filecmp
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(ROOT, "software", "bob"), os.path.join(ROOT, "software", "host")]

import bitstream as B  # noqa: E402
import bitgen  # noqa: E402
import cfgplane  # noqa: E402
import chainbits  # noqa: E402
import equiv  # noqa: E402
import fakeboard  # noqa: E402
import fasm_from_vpr as FV  # noqa: E402
import fpga  # noqa: E402
import model  # noqa: E402
import packets  # noqa: E402
import timing as T  # noqa: E402
import vpr_run  # noqa: E402

K = B.DEVICE["lut_k"]
FB = B.DEVICE["frames"]["bits"]


# --- small helpers -------------------------------------------------------------------

def rel(p):
    return os.path.relpath(p, ROOT)


def stage(out, name):
    d = os.path.join(out, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    return d


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")


def copy(src, dst_dir, name=None):
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, name or os.path.basename(src))
    shutil.copy(src, dst)
    return dst


def bob(*args):
    r = subprocess.run([os.path.join(ROOT, "bob"), *args], cwd=ROOT, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).rstrip() + "\n"


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def hexs(v, nbits, keep=24):
    s = f"{v:0{(nbits + 3) // 4}X}"
    return s if len(s) <= 2 * keep else f"{s[:keep]}...{s[-16:]} ({len(s)} hex digits)"


def far_fields(far):
    return {"type": (far >> 23) & 7, "top": (far >> 22) & 1, "row": (far >> 17) & 31,
            "column": (far >> 7) & 0x3FF, "minor": far & 0x7F}


def far_of(frame):
    for c in B.DEVICE["frames"]["columns"]:
        if c["base"] <= frame < c["base"] + c["count"]:
            return packets.far(c["far_col"], frame - c["base"])
    raise ValueError(frame)


def node_text(n):
    """a routing-resource node in words: type, place, track"""
    if n not in B.NODE:
        return str(n)
    _id, typ, xl, yl, xh, yh, ptc, _d = B.NODE[n]
    where = f"({xl},{yl})" if (xl, yl) == (xh, yh) else f"({xl},{yl})->({xh},{yh})"
    what = {"CHANX": "track", "CHANY": "track", "IPIN": "pin", "OPIN": "pin"}.get(typ, "ptc")
    return f"{typ:5s} {where:16s} {what} {ptc}"


FIELD_DOC = {}
for _t, _v in B.DEVICE["tile_types"].items():
    for _f in _v["fields"]:
        FIELD_DOC[(_t, _f["name"])] = _f.get("doc", "")


def feature_bits(feat):
    """FASM feature -> (chain lo, width, block type, field) exactly as bitgen places it"""
    if feat.startswith("rr"):
        lo, w, _base, _ins = B.MUX[int(feat[2:])]
        return lo, w, "rr", feat
    blk, field = feat.split(".", 1)
    if blk == "ctrl":
        off, w = B.CTRL_FIELD[field]
        return off, w, "ctrl", field
    b = B.BLOCKS[blk]
    off, w = bitgen.TABLES[b["type"]][field]
    return b["chain_lo"] + off, w, b["type"], field


def meaning(feat, value):
    """what setting this feature to this value does"""
    lo, w, typ, field = feature_bits(feat)
    if typ == "rr":
        n = int(feat[2:])
        _lo, _w, base, ins = B.MUX[n]
        if value == 0:
            pick = "const0"
        elif value == 1 and base == 2:
            pick = "const1"
        else:
            pick = f"input {value - base} = node {ins[value - base]} [{node_text(ins[value - base]).strip()}]"
        return f"mux driving {node_text(n).strip()}: {pick}"
    m = re.fullmatch(r"e(\d+)\.x(\d+)", field)
    if typ == "clb" and m:
        e, j = int(m.group(1)), int(m.group(2))
        srcs = B.DEVICE["cluster"]["xbar_sources"][e][j]
        pick = {0: "const0", 1: "const1"}.get(value) or srcs[value - 2]
        return f"crossbar: element {e} input i{j} <- {pick}"
    if field.endswith(".init"):
        return f"LUT truth table ({2 ** K} bits); O6 = INIT[i5..i0], O5 = the lower half"
    return FIELD_DOC.get((typ, field), "") or FIELD_DOC.get((typ, re.sub(r"^e\d+\.", "e0.", field)), "")


# --- 00 RTL ------------------------------------------------------------------------------

def s00_rtl(out, src, pcf):
    d = stage(out, "00_rtl")
    copy(src, d)
    if pcf:
        copy(pcf, d)
    return d


# --- 01 synthesis, 02 equivalence (equiv.equiv runs yosys, then iverilog) ---------------

def s01_s02_synth(out, src, top):
    ok, lines, mod = equiv.equiv([src], top)
    sd = os.path.join(ROOT, "build", "synth", top)
    d = stage(out, "01_synthesis")
    lib = os.path.join(d, "inputs", "bob_cell_library")
    for f in sorted(glob.glob(os.path.join(ROOT, "software", "bob", "synth", "*"))):
        copy(f, lib)
    copy(os.path.join(sd, f"{top}.ys"), os.path.join(d, "inputs"), "synth_script.ys")
    for ext in (".json", ".blif", "_syn.v", ".stat"):
        if os.path.exists(os.path.join(sd, top + ext)):
            copy(os.path.join(sd, top + ext), d)
    copy(os.path.join(sd, f"{top}.log"), d, "yosys.log")
    cells = {}
    for c in mod["cells"].values():
        cells[c["type"]] = cells.get(c["type"], 0) + 1
    names = {n: v for n, v in mod["netnames"].items() if not n.startswith("$")}
    write(os.path.join(d, "cells.txt"),
          f"{top}: yosys onto bob's cell library (software/bob/synth.py)\n\n"
          + "\n".join(f"  {t:12s} {n}" for t, n in sorted(cells.items()))
          + "\n\nnamed nets:\n" + "\n".join(f"  {n}  bits {v['bits']}" for n, v in sorted(names.items())))

    d2 = stage(out, "02_equivalence")
    for f in (f"{top}_golden.v", f"{top}_syn_renamed.v", "tb_equiv.v", "trace.txt", f"{top}.trace.json"):
        copy(os.path.join(sd, f), d2)
    tr = json.load(open(os.path.join(sd, f"{top}.trace.json")))
    rows = [f"{'cycle':>5}  {'inputs':>8}  {'out before':>10}  {'out after':>9}"]
    for c, (v, before, after) in enumerate(tr["trace"][:40]):
        rows.append(f"{c:5d}  {v:08b}  {before:10b}  {after:9b}")
    write(os.path.join(d2, "result.txt"),
          f"source {rel(src)} == yosys netlist == golden netlist: {'EQUAL' if ok else 'DIFFERENT'}\n"
          f"{len(tr['trace'])} biased random cycles in iverilog, compared before and after every edge.\n\n"
          "iverilog said:\n" + "\n".join("  " + l for l in lines) + "\n\n"
          "The first 40 cycles of the trace (board inputs as bits BTN3..0 SW1..0; outputs as the\n"
          "design's output ports). model.py and the board are later held to this same trace.\n\n"
          + "\n".join(rows))
    if not ok:
        raise SystemExit("synthesis is not equivalent to the source")
    return mod


# --- 03 VPR prepare, 04 place and route -------------------------------------------------

def s03_s04_vpr(out, top, pcf, reuse):
    committed = os.path.join(vpr_run.RESULTS, top)
    stamp = vpr_run.read_stamp(top) or {}
    seed = int(stamp.get("seed", 1))
    if reuse:
        work = committed
    else:
        work = os.path.join(ROOT, "build", "example_vpr", top)
        vpr_run.run(top, seed, work=work, pcf=pcf)
    d3 = stage(out, "03_vpr_prepare")
    for ext in (".eblif", ".vpr.json", ".pins"):
        copy(os.path.join(work, top + ext), d3)
    eb_sha = sha(os.path.join(work, f"{top}.eblif"))
    write(os.path.join(d3, "note.txt"),
          "vpr_run.prepare rewrote the yosys netlist into what VPR can pack:\n"
          "  constants on block pins -> IPIN constants (in .vpr.json, set by FASM later)\n"
          "  carry chains cut to the column height, with generator/tap adders\n"
          "  a buffer LUT where a flip-flop's D is not its own element's output\n"
          "  every port fixed to its board pad (.pins, from device.json or a .pcf)\n\n"
          f"eblif sha256 {eb_sha}\ncommitted stamp  {stamp.get('eblif_sha256', '-')}\n"
          f"same netlist as the committed result: {eb_sha == stamp.get('eblif_sha256')}")

    d4 = stage(out, "04_place_route")
    inp = os.path.join(d4, "inputs")
    copy(os.path.join(ROOT, "software", "bob", "arch", f"bob_k{K}.xml"), inp)
    copy(os.path.join(ROOT, "software", "bob", "arch", f"bob_k{K}_rr.xml.gz"), inp)
    if reuse:
        write(os.path.join(inp, "command.txt"), stamp.get("command", ""))
    else:
        copy(os.path.join(work, "command.txt"), inp)
    skip = {f"{top}{e}" for e in (".eblif", ".vpr.json", ".pins")} | {"arch.xml", "command.txt", "stamp.txt"}
    for f in sorted(os.listdir(work)):
        if f not in skip and os.path.isfile(os.path.join(work, f)):
            copy(os.path.join(work, f), d4)
    lines = []
    for ext in (".net", ".place", ".route"):
        a, b = os.path.join(work, top + ext), os.path.join(committed, top + ext)
        same = filecmp.cmp(a, b, shallow=False)
        note = ""
        if not same and ext == ".net":
            # vpr_run.commit blanks the two run-specific ids before committing a .net
            strip = lambda t: re.sub(r'(architecture_id|atom_netlist_id)="[^"]*"', r'\1=""', t)  # noqa: E731
            same = strip(open(a).read()) == strip(open(b).read())
            note = "  (after blanking architecture_id / atom_netlist_id, as vpr_run.commit does)"
        lines.append(f"  {top + ext:14s} {'identical' if same else 'DIFFERENT'}{note}")
    s = vpr_run.summary(work, top)
    place = FV.read_place(os.path.join(work, f"{top}.place"))
    at = {(b["x"], b["y"]): b["type"] for b in B.DEVICE["blocks"]}
    s["clbs"] = sum(1 for xy in place.values() if at.get(xy) == "clb")
    s["pads"] = sum(1 for xy in place.values() if at.get(xy) == "io")
    write(os.path.join(d4, "summary.txt"),
          f"VPR {'(the committed result, --reuse-vpr)' if reuse else 'run now in Docker'}, seed {seed}\n"
          f"  image   {vpr_run.IMAGE}\n  arch    inputs/bob_k{K}.xml (VPR's arch.xml)\n"
          f"  rr      inputs/bob_k{K}_rr.xml.gz (--read_rr_graph: the graph the RTL was generated from)\n\n"
          + "\n".join(f"  {k:12s} {v}" for k, v in s.items())
          + "\n\nagainst the committed result in " + rel(committed) + ":\n" + "\n".join(lines))
    return work


# --- 05 layout ---------------------------------------------------------------------------

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]


def s05_layout(out, top, work):
    d = stage(out, "05_layout")
    place = FV.read_place(os.path.join(work, f"{top}.place"))
    route = FV.read_route(os.path.join(work, f"{top}.route"))
    gw, gh = B.DEVICE["arch"]["grid_width"], B.DEVICE["arch"]["grid_height"]
    W = B.DEVICE["arch"]["chan_width"]
    blocks = {(b["x"], b["y"]): b for b in B.DEVICE["blocks"]}
    height = {c["type"]: c["height"] for c in B.DEVICE["arch"]["columns"]}
    used = {}
    for name, xy in place.items():
        used.setdefault(xy, []).append(name)

    # text view
    grid = []
    for y in range(gh - 1, -1, -1):
        row = []
        for x in range(gw):
            b = blocks.get((x, y))
            if b is None:
                cover = next((bb for bb in B.DEVICE["blocks"] if bb["x"] == x and bb["type"] in height
                              and bb["y"] <= y < bb["y"] + height[bb["type"]]), None)
                row.append((cover["type"][0].lower() if cover else " ") * 2)
                continue
            ch = {"clb": "C", "io": "P", "bram": "B", "dsp": "D"}[b["type"]]
            row.append((ch + "#") if (x, y) in used else (ch.lower() + "."))
        grid.append(f"y{y:2d}  " + " ".join(row))
    grid.append("     " + " ".join(f"{x:2d}" for x in range(gw)))
    lst = [f"  {n:48s} at x={x:2d} y={y:2d}  ({blocks[(x, y)]['name'] if (x, y) in blocks else '?'})"
           for n, (x, y) in sorted(place.items(), key=lambda kv: (kv[1][1], kv[1][0]))]
    write(os.path.join(d, "layout.txt"),
          f"{top} on the {gw} x {gh} VPR grid (y up). '#' = used by this design.\n"
          "C/c CLB, P/p I/O pad, B/b BRAM, D/d DSP. A hard block is 5 rows tall: b./d. is its root\n"
          "tile (where it is placed and configured), bb/dd the rows above it that it covers.\n\n"
          + "\n".join(grid) + "\n\nplaced clusters (.place):\n" + "\n".join(lst))

    # route in words, with the FASM value that closes each hop
    feats = bitgen.parse_fasm(FV.build(top, work)[2])
    rtxt = []
    for net, trees in sorted(route.items()):
        rtxt.append(f"net {net}")
        for tree in trees:
            prev, branch = None, False
            for n, typ in tree:
                if typ in ("SOURCE", "SINK"):
                    branch = typ == "SINK"                # VPR restarts the next branch from the tree
                    continue
                if branch:
                    rtxt.append(f"         ... next branch, from node {n} (already routed above)")
                    prev, branch = n, False
                    continue
                sel = ""
                if n in B.MUX and f"rr{n}" in feats:
                    v = feats[f"rr{n}"]
                    sel = f"   rr{n} = {v}  (selects node {prev})" if prev is not None else f"   rr{n} = {v}"
                rtxt.append(f"  {n:6d} {node_text(n)}{sel}")
                prev = n
        rtxt.append("")
    write(os.path.join(d, "route_in_words.txt"),
          "Every routed net, node by node, from the .route file. A node with fan-in is a bob_mux\n"
          "in the RTL; its FASM feature rr<node> is the select value that picks the previous node.\n\n"
          + "\n".join(rtxt))

    # picture
    P, Tt, M = 72, 42, 34
    G = P - Tt
    X = lambda x: M + x * P                       # noqa: E731
    Y = lambda y: M + (gh - 1 - y) * P            # noqa: E731
    SW, SH = 2 * M + gw * P, 2 * M + gh * P + 70
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{SW}" height="{SH}" viewBox="0 0 {SW} {SH}" '
           f'font-family="Helvetica, Arial, sans-serif">',
           f'<rect width="100%" height="100%" fill="#ffffff"/>',
           f'<text x="{M}" y="{M - 10}" font-size="15" font-weight="bold" fill="#16202b">{top}: '
           f'placement and routing on bob12x10 (from {top}.place and {top}.route)</text>']
    fill = {"clb": ("#dfe7ef", "#0c7a64"), "io": ("#e9e4f3", "#6a4db3"),
            "bram": ("#d9ecf7", "#2f6db5"), "dsp": ("#f5e4d6", "#e38a1f")}
    for (x, y), b in sorted(blocks.items()):
        h = height.get(b["type"], 1)
        light, dark = fill[b["type"]]
        on = (x, y) in used
        svg.append(f'<rect x="{X(x)}" y="{Y(y + h - 1)}" width="{Tt}" height="{Tt + (h - 1) * P}" rx="3" '
                   f'fill="{dark if on else light}" fill-opacity="{0.85 if on else 1}" stroke="{dark}" stroke-width="0.8"/>')
        if b["type"] in ("bram", "dsp"):
            svg.append(f'<text x="{X(x) + Tt / 2}" y="{Y(y + h - 1) + (Tt + (h - 1) * P) / 2}" font-size="10" '
                       f'text-anchor="middle" fill="#16202b" transform="rotate(-90 {X(x) + Tt / 2} '
                       f'{Y(y + h - 1) + (Tt + (h - 1) * P) / 2})">{b["type"].upper()}</text>')
    for (x, y), names in used.items():
        kind = blocks.get((x, y), {}).get("type")
        label = f"CLB {len(names)}" if kind == "clb" and len(names) > 1 else (
            "CLB" if kind == "clb" else names[0].replace("out:", ""))
        svg.append(f'<text x="{X(x) + Tt / 2}" y="{Y(y) + Tt / 2 + 3.5}" font-size="10" text-anchor="middle" '
                   f'fill="#ffffff" font-weight="bold">{label}<title>{", ".join(names)}</title></text>')

    def seg(n):
        _i, typ, xl, yl, xh, yh, ptc, _d = B.NODE[n]
        t = (int(str(ptc).split(",")[0]) + 0.5) / W      # an L4 wire lists its track at each step
        if typ == "CHANX":
            yy = Y(yl) - G + t * G
            return (X(xl), yy, X(xh) + Tt, yy)
        xx = X(xl) + Tt + t * G
        return (xx, Y(yh), xx, Y(yl) + Tt)

    def near(px, py, s):
        x1, y1, x2, y2 = s
        return (min(max(px, min(x1, x2)), max(x1, x2)), min(max(py, min(y1, y2)), max(y1, y2)))

    legend = []
    for k, (net, trees) in enumerate(sorted(route.items())):
        col = PALETTE[k % len(PALETTE)]
        legend.append((net, col))
        for tree in trees:
            nodes = [(n, t) for n, t in tree if t not in ("SOURCE", "SINK")]
            for i, (n, typ) in enumerate(nodes):
                if typ in ("CHANX", "CHANY"):
                    x1, y1, x2, y2 = seg(n)
                    svg.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{col}" '
                               f'stroke-width="2" stroke-linecap="round"><title>{net}: {node_text(n)}</title></line>')
                elif typ in ("OPIN", "IPIN"):
                    _i, _t, xl, yl, _xh, _yh, _p, _d = B.NODE[n]
                    cx, cy = X(xl) + Tt / 2, Y(yl) + Tt / 2
                    nb = nodes[i + 1] if typ == "OPIN" and i + 1 < len(nodes) else (nodes[i - 1] if i else None)
                    if nb and nb[1] in ("OPIN", "IPIN"):
                        # a direct (carry out -> carry in): no channel, a wire between the two tiles
                        if typ == "OPIN":
                            _j, _u, x2, y2, _a, _b, _c, _e = B.NODE[nb[0]]
                            c2x, c2y = X(x2) + Tt / 2, Y(y2) + Tt / 2
                            ax, ay = min(max(c2x, X(xl)), X(xl) + Tt), min(max(c2y, Y(yl)), Y(yl) + Tt)
                            bx, by = min(max(cx, X(x2)), X(x2) + Tt), min(max(cy, Y(y2)), Y(y2) + Tt)
                            svg.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" stroke="{col}" '
                                       f'stroke-width="3"><title>{net}: direct {node_text(n)} -> '
                                       f'{node_text(nb[0])}</title></line>')
                        continue
                    if nb and nb[1] in ("CHANX", "CHANY"):
                        qx, qy = near(cx, cy, seg(nb[0]))
                        # the pin sits on the tile's edge, facing the channel it connects to
                        ex = min(max(qx, X(xl)), X(xl) + Tt)
                        ey = min(max(qy, Y(yl)), Y(yl) + Tt)
                        svg.append(f'<line x1="{ex:.1f}" y1="{ey:.1f}" x2="{qx:.1f}" y2="{qy:.1f}" stroke="{col}" '
                                   f'stroke-width="1.4" stroke-dasharray="2 2"/>')
                        cx, cy = ex, ey
                    svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.4" fill="{col}" stroke="#ffffff" '
                               f'stroke-width="1"><title>{net}: {node_text(n)}</title></circle>')
    ly = M + gh * P + 14
    for k, (net, col) in enumerate(legend):
        lx = M + (k % 6) * 150
        yy = ly + (k // 6) * 16
        svg.append(f'<line x1="{lx}" y1="{yy}" x2="{lx + 18}" y2="{yy}" stroke="{col}" stroke-width="3"/>'
                   f'<text x="{lx + 24}" y="{yy + 4}" font-size="11" fill="#16202b">{net}</text>')
    svg.append(f'<text x="{M}" y="{ly + 16 * ((len(legend) + 5) // 6) + 14}" font-size="10" fill="#566372">'
               f'Each wire is drawn at its track in the {W}-track channel (CHANX above a row, CHANY right of a column); '
               'dotted = a block pin to its channel. Filled tiles are used; hover for names.</text>')
    svg.append("</svg>")
    write(os.path.join(d, "layout.svg"), "\n".join(svg))


# --- 06 FASM -----------------------------------------------------------------------------

def s06_fasm(out, top, work):
    d = stage(out, "06_fasm")
    bs, contents, text = FV.build(top, work)
    write(os.path.join(d, f"{top}.fasm"), text)
    F = bitgen.parse_fasm(text)
    rows = []
    for feat, value in sorted(F.items(), key=lambda kv: feature_bits(kv[0])[0]):
        lo, w, _typ, _f = feature_bits(feat)
        hi = lo + w - 1
        fr, b = lo // FB, lo % FB
        far = far_of(fr)
        ff = far_fields(far)
        span = f"{lo}" if w == 1 else f"{lo}..{hi}"
        rows.append(f"{feat} = {w}'h{value:x}\n"
                    f"    chain bits {span}  ->  frame {fr} bit {b} (word {b // 32} bit {b % 32})"
                    + (f" .. frame {hi // FB} bit {hi % FB}" if hi // FB != fr else "")
                    + f"  ->  FAR 0x{far:08X} (column {ff['column']}, minor {ff['minor']})\n"
                    f"    {meaning(feat, value)}")
    write(os.path.join(d, "feature_map.txt"),
          f"Every FASM feature of {top}.fasm, where its bits land, and what it does.\n"
          f"chain bit k = configuration memory bit k; frame f = bits [{FB}f + {FB - 1} : {FB}f];\n"
          "word w bit k of a frame = frame bit 32w + k (docs/bitstream-format.md).\n\n" + "\n".join(rows))
    return bs, contents


# --- 07 bitstream --------------------------------------------------------------------------

def hexdump(data):
    out = []
    for off in range(0, len(data), 16):
        c = data[off:off + 16]
        h = " ".join(f"{x:02x}" for x in c)
        a = "".join(chr(x) if 32 <= x < 127 else "." for x in c)
        out.append(f"{off:08x}  {h:<47}  |{a}|")
    return "\n".join(out)


def s07_bitstream(out, top, src, pcf, reports):
    d = stage(out, "07_bitstream")
    bit = os.path.join(d, f"{top}.bit")
    args = [rel(src), "-o", rel(bit)] + (["--pcf", rel(pcf)] if pcf else [])
    rc, text = bob("build", *args)
    write(os.path.join(reports, "build_log.txt"), f"$ ./bob build {' '.join(args)}\n\n{text}")
    if rc:
        raise SystemExit(f"./bob build failed:\n{text}")
    rc, text = bob("build", *args, "--json", rel(os.path.join(reports, "flow_record.json")))
    c = bitgen.read_bit(bit)
    word = c["word"]
    write(os.path.join(d, f"{top}.bit.hexdump.txt"),
          f"{top}.bit, {os.path.getsize(bit)} bytes: header, the {B.CHAIN_W}-bit chain, a META section "
          "(JSON), CRCs\n(docs/bitstream-format.md section 8). ./bob info --raw decodes the fields.\n\n"
          + hexdump(open(bit, "rb").read()))
    _rc, info = bob("info", rel(bit))
    _rc, raw = bob("info", "--raw", rel(bit))
    write(os.path.join(d, "bit_info.txt"), f"$ ./bob info {rel(bit)}\n{info}\n$ ./bob info --raw {rel(bit)}\n{raw}")
    from fasm_from_vpr import to_fasm
    write(os.path.join(d, "bit_back_to.fasm"), to_fasm(bitgen.features_from_word(word)))

    # the configuration memory, frame by frame
    tiles = [(t["chain_lo"], t["chain_lo"] + t["width"], t["name"]) for t in B.DEVICE["tiles"] if t["width"]]
    lk = {f[0]: f"{f[1]} {f[2]} (CFGLUT5)" for f in B.DEVICE["lframes"]["list"]}
    rows, used = [], set(packets.used_frames(word))
    for fr in range(B.DEVICE["frames"]["count"]):
        far = far_of(fr)
        ff = far_fields(far)
        v = (word >> (fr * FB)) & ((1 << FB) - 1)
        ws = " ".join(f"{(v >> (32 * k)) & 0xFFFFFFFF:08X}" for k in range(FB // 32))
        own = sorted({n for lo, hi, n in tiles if lo < (fr + 1) * FB and hi > fr * FB})
        tag = lk.get(fr, ", ".join(own[:3]) + (" ..." if len(own) > 3 else ""))
        rows.append(f"{fr:4d}  0x{far:08X}  {ff['column']:3d} {ff['minor']:3d}  {ws}  {'*' if fr in used else ' '}  {tag}")
    write(os.path.join(d, "frames.txt"),
          f"The {B.CHAIN_W}-bit configuration memory as {B.DEVICE['frames']['count']} frames of {FB} bits "
          f"(4 words: word 0 first).\n'*' = the frame holds a 1 ({len(used)} frames): only those travel in a "
          "sparse load.\n\nframe FAR         col min  word0    word1    word2    word3     what lives there\n"
          + "\n".join(rows))

    full = packets.load_stream(word)
    sparse = packets.load_stream(word, sparse=True)
    write(os.path.join(d, "stream_full.txt"),
          f"The full UG470-style load stream: {len(full)} words (every frame).\n\n" + "\n".join(packets.describe(full)))
    write(os.path.join(d, "stream_sparse.txt"),
          f"The stream ./bob load sends right after JPROGRAM: {len(sparse)} words, only the {len(used)} "
          "frames holding a 1,\none FAR + FDRI packet per run of frames.\n\n" + "\n".join(packets.describe(sparse)))
    write(os.path.join(d, "stream_sparse.hex"), "\n".join(f"{w:08X}" for w in sparse))
    return bit, word, c


# --- 08 timing ---------------------------------------------------------------------------

def s08_timing(out, top, bit, word):
    d = stage(out, "08_timing")
    t = T.analyse(word)
    try:
        T.contract(t, word)
        verdict = (f"the timing contract holds: path x {t['margin']} fits the spacing this .bit runs at "
                   f"({T.spacing(word)} sysclk cycles; a JTAG-stepped build keeps the safe default)")
    except T.TimingError as e:
        verdict = f"REFUSED: {e}"
    delays = json.load(open(os.path.join(ROOT, "software", "bob", "delays.json")))
    rows, last = [], 0.0
    for p in t["path"]:
        rows.append(f"  {p['at_ns']:7.3f} ns  (+{p['at_ns'] - last:5.3f})  {p['kind']:8s}  "
                    f"{node_text(p['node']) if isinstance(p['node'], int) else p['node']}")
        last = p["at_ns"]
    if t["cpd_ns"] > last:
        rows.append(f"  {t['cpd_ns']:7.3f} ns  (+{t['cpd_ns'] - last:5.3f})  setup     the flip-flop's setup time")
    write(os.path.join(d, "timing_report.txt"),
          f"Static timing of {top} from its configuration bits alone (software/bob/timing.py).\n"
          "Only the selected mux inputs are walked, register to register.\n\n"
          f"critical path  {t['cpd_ns']} ns  ({'provisional' if t['provisional'] else 'measured'} delays, "
          f"guard band x {t['margin']})\n"
          f"gce spacing    {t['gap_cycles']} sysclk cycles of 8 ns -> Fmax {t['fmax_hz'] / 1e6:.2f} MHz\n"
          f"endpoints      {t['endpoints']}\n{verdict}\n\nthe critical path, node by node:\n" + "\n".join(rows)
          + "\n\ndelays used (software/bob/delays.json, " + delays.get("source", "") + "):\n"
          + "\n".join(f"  {k:12s} {v} ns" for k, v in delays["ns"].items()))
    return t


# --- 09 model check ------------------------------------------------------------------------

def s09_model(out, top, work, bs, contents):
    d = stage(out, "09_model_check")
    bad, n, tr = FV.check_model(top, bs, contents, work, top)
    m = model.Fabric(bs)
    m.clock(gsr=1)
    rows = [f"{'cycle':>5}  {'SW1..0':>6} {'BTN3..0':>7}  {'LD2..0 source':>13}  {'LD2..0 model':>12}"]
    for c, (v, _before, after) in enumerate(tr["trace"][:64]):
        if tr["has_clk"]:
            m.clock(pad_i=v)
        got = m.outputs(v)
        rows.append(f"{c:5d}  {format(v & 3, '02b'):>6s} {format((v >> 2) & 15, '04b'):>7s}  "
                    f"{format(after, '03b'):>13s}  {format(got, '03b'):>12s}  {'' if got == after else 'DIFF'}")
    write(os.path.join(d, "model_check.txt"),
          f"The bits on model.py (a cycle model of the fabric RTL) against the source trace of 02_equivalence.\n"
          f"{2 * n - len(bad)}/{2 * n} samples equal (before and after every edge of {n} cycles).\n\n"
          "The first 64 cycles, after each edge:\n" + "\n".join(rows))


# --- 10 load, 11 run on the stand-in board -----------------------------------------------------

IR_NAME = {v: k for k, v in cfgplane.IR.items()}


class Recorder:
    """The stand-in board, with every JTAG operation written down."""

    def __init__(self, inner):
        object.__setattr__(self, "_p", inner)
        object.__setattr__(self, "_log", [])
        object.__setattr__(self, "_ir", None)
        object.__setattr__(self, "_idle", 0)

    def __setattr__(self, name, value):
        setattr(self._p, name, value)

    def _flush(self):
        if self._idle:
            self._log.append(f"      Run-Test/Idle, {self._idle} TCK")
            object.__setattr__(self, "_idle", 0)

    def __getattr__(self, name):
        attr = getattr(self._p, name)
        if not callable(attr):
            return attr

        def call(*a, **k):
            r = attr(*a, **k)
            if name == "pulse":
                object.__setattr__(self, "_idle", self._idle + 1)
                return r
            self._flush()
            if name == "shift_ir":
                ir = IR_NAME.get(a[0], f"{a[0]:06b}")
                object.__setattr__(self, "_ir", ir)
                st = chainbits.decode_ir_capture(r)
                self._log.append(f"IR    {ir:10s} ({a[0]:06b})   Capture-IR {r:06b}: DONE={st['done']} "
                                 f"INIT_B={st['init_b']} COMMITTED={st['committed']} CRC_ERR={st['crc_err']}")
            elif name in ("shift_dr", "shift_dr_fast"):
                nbits, din = a[0], (a[1] if len(a) > 1 else k.get("din", 0))
                what, words = "", nbits // 32
                if self._ir == "CFG_IN" and words > 40:
                    what = f"   the load stream, {words} words (07_bitstream/stream_sparse.txt)"
                elif self._ir == "CFG_IN":
                    what = f"   packets, {words} words:\n" + "\n".join(
                        "                       " + ln for ln in packets.describe(packets.from_jtag(din, words)))
                elif self._ir == "CFG_OUT":
                    ones = bin(r or 0).count("1")
                    what = (f"   reads {words} word{'s' if words != 1 else ''} back"
                            + (f" ({ones} bits set: the design's configuration)" if words > 1 else " (STAT)"))
                self._log.append(f"DR    {nbits:6d} bits  in {hexs(din, nbits)}\n"
                                 f"                   out {hexs(r or 0, nbits)}{what}")
            else:
                self._log.append(f"      {name}{a if a else ''}")
            return r
        return call


def s10_s11_board(out, top, bit, word, work, mod, cycles):
    d = stage(out, "10_load")
    _rc, text = bob("load", rel(bit), "--probe", "fake")
    write(os.path.join(d, "load_log.txt"), f"$ ./bob load {rel(bit)} --probe fake\n\n{text}")
    p = Recorder(fakeboard.probe("fake"))
    ok, msg = cfgplane.load_frames(p, word)
    p._flush()
    write(os.path.join(d, "jtag_transcript.txt"),
          "Every JTAG operation of cfgplane.load_frames, on the stand-in board (fakeboard.py answers\n"
          "exactly as the PYNQ-Z2 does). IR = an instruction scan, DR = a data scan, hex MSB first.\n"
          "JPROGRAM clears, CFG_IN takes the packets, BYPASS/CFG_OUT read STAT, CFG_OUT reads every\n"
          "frame back (FDRO), JSTART runs GSR -> GTS -> GWE -> DONE.\n\n"
          f"result: {'OK' if ok else 'FAILED'}: {msg}\n\n" + "\n".join(p._log))
    if not ok:
        raise SystemExit(msg)

    # 11: step the loaded design and read its pins and registers every user clock
    d = stage(out, "11_run")
    fb = p._p
    cmap = FV.capture_map(top, work)
    bitname = {}                    # a bit can have several names (led = q[5:3]): keep the widest
    for n, v in sorted(mod["netnames"].items(), key=lambda kv: -len(kv[1]["bits"])):
        if n.startswith("$"):
            continue
        for i, b in enumerate(v["bits"]):
            bitname.setdefault(b, (n, i, len(v["bits"])))
    regs = sorted({bitname[b][0] for _i, b in cmap if b in bitname})
    # directed stimulus for the board convention: reset, count, pause, reset
    vec = [0b001000] * 2 + [0b000100] * (cycles - 8) + [0] * 4 + [0b001000] * 2
    cfgplane.user1(fb, 0x10)
    cfgplane.ir(fb, "INTEST")
    fb.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(vec[0]))
    rows = []
    for k in range(len(vec)):
        cap = cfgplane.capture(fb, B.NCAP)
        val = {r: 0 for r in regs}
        for idx, b in cmap:
            if b in bitname:
                n, i, _w = bitname[b]
                val[n] |= ((cap >> idx) & 1) << i
        cfgplane.ir(fb, "INTEST")
        nxt = vec[k + 1] if k + 1 < len(vec) else vec[k]
        leds = fpga.bsr_leds(fb.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(nxt)))
        rows.append((k, vec[k], val, leds))
    cfgplane.user1(fb, 0)
    width = {r: max(bitname[b][2] for _i, b in cmap if b in bitname and bitname[b][0] == r) for r in regs}
    head = f"{'clock':>5}  {'BTN3..0':>7}  " + "  ".join(f"{r + f'[{width[r] - 1}:0]':>8}" for r in regs) + "  LD2..0"
    lines = [head] + [f"{k:5d}  {format((v >> 2) & 15, '04b'):>7s}  "
                      + "  ".join(f"{val[r]:8d}" for r in regs) + f"  {leds:03b}"
                      for k, v, val, leds in rows]
    write(os.path.join(d, "run_table.txt"),
          f"{top} loaded on the stand-in board and stepped with INTEST + USER1 autostep: each scan drives\n"
          "the pins, gives the user clock one edge, and CAPTURE reads every element flip-flop.\n"
          "Registers are named through capture_map (CAPTURE bit -> the golden netlist's bit).\n"
          "Stimulus: BTN1 (reset) for 2 clocks, BTN0 (enable) held, released, then reset again.\n\n"
          + "\n".join(lines))

    # VCD for GTKWave: clk, the buttons, the LEDs, every register
    ids = iter("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
    sig = [("clk", 1, next(ids)), ("btn", 4, next(ids)), ("led", 3, next(ids))] + \
          [(r, width[r], next(ids)) for r in regs]
    v = ["$version bob example/make_example.py (stand-in board, one sample per user clock) $end",
         "$timescale 1ns $end", f"$scope module {top} $end"]
    v += [f"$var wire {w} {c} {n} [{w - 1}:0] $end" if w > 1 else f"$var wire 1 {c} {n} $end" for n, w, c in sig]
    v += ["$upscope $end", "$enddefinitions $end"]

    def val(w, x, c):
        return f"b{x:0{w}b} {c}" if w > 1 else f"{x & 1}{c}"
    v += ["#0", val(1, 0, sig[0][2]), val(4, (rows[0][1] >> 2) & 15, sig[1][2]), val(3, 0, sig[2][2])]
    v += [val(w, 0, c) for _n, w, c in sig[3:]]
    for k, vin, regv, leds in rows:
        v += [f"#{10 * k + 5}", val(1, 1, sig[0][2]), val(3, leds, sig[2][2])]
        v += [val(w, regv[n], c) for n, w, c in sig[3:]]
        v += [f"#{10 * k + 10}", val(1, 0, sig[0][2])]
        if k + 1 < len(rows):
            v += [val(4, (rows[k + 1][1] >> 2) & 15, sig[1][2])]
    write(os.path.join(d, f"{top}.vcd"), "\n".join(v))


# --- main --------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--design", default="counter", help="a folder of work/examples (default counter)")
    ap.add_argument("--out", default=HERE, help="where the numbered folders go (default example/)")
    ap.add_argument("--reuse-vpr", action="store_true", help="no Docker: copy the committed VPR result")
    ap.add_argument("--cycles", type=int, default=76, help="user clocks to step in 11_run")
    args = ap.parse_args()
    top = args.design
    src = os.path.join(ROOT, "work", "examples", top, f"{top}.v")
    if not os.path.exists(src):
        raise SystemExit(f"no {rel(src)}")
    pcf = None                                     # the committed examples use the board convention
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    reports = stage(out, "reports")

    print(f"00 rtl            {rel(s00_rtl(out, src, pcf))}")
    mod = s01_s02_synth(out, src, top)
    print("01 synthesis      yosys onto bob's cells;  02 equivalence  source == netlist == golden")
    work = s03_s04_vpr(out, top, pcf, args.reuse_vpr)
    print(f"03 vpr prepare    04 place and route  ({'committed result' if args.reuse_vpr else 'VPR in Docker'})")
    s05_layout(out, top, work)
    print("05 layout         layout.svg, layout.txt, route_in_words.txt")
    bs, contents = s06_fasm(out, top, work)
    print("06 fasm           features and where their bits land")
    bit, word, _c = s07_bitstream(out, top, src, pcf, reports)
    print(f"07 bitstream      {rel(bit)}, frames, packet streams")
    t = s08_timing(out, top, bit, word)
    print(f"08 timing         critical path {t['cpd_ns']} ns")
    s09_model(out, top, work, bs, contents)
    print("09 model check    model.py == the source trace")
    s10_s11_board(out, top, bit, word, work, mod, args.cycles)
    print("10 load, 11 run   stand-in board: JTAG transcript, register table, VCD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
