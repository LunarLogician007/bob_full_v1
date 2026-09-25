#!/usr/bin/env python3
"""
gen.py - build docs/learn/tool_by_tool.html (volume 4) from docs/learn/tools/page.html and the tools.

"bob, tool by tool" follows one design, work/examples/wide/wide.v, through every step of
./bob build: what yosys reads, what it maps onto bob's cells, one LUT's truth table, the
equivalence check, packing, placement (a live simulated anneal on the real nets, then VPR's
result), routing, FASM, the critical path and the model check. Everything is taken here:

  yosys prep                     the coarse cells, each with its source line
  build/synth/wide/              the mapped netlist and the source trace (software/bob/synth.py
                                 and equiv.py are run first, as ./bob build runs them)
  software/bob/vpr/wide/         packing (.net), placement (.place), routes (.route)
  software/bob/fasm_from_vpr.py  the FASM and the configuration word
  software/bob/timing.py         the critical path, with every hop's arrival time

    python3 docs/learn/tools/gen.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))
sys.path.insert(0, os.path.join(ROOT, "docs", "learn", "layers"))

EX = "wide"
SRC = os.path.join(ROOT, "work", "examples", EX, f"{EX}.v")
OUT = os.path.join(ROOT, "docs", "learn", "tool_by_tool.html")


def coarse():
    """yosys prep: the cells before any mapping, with the source line each came from"""
    with tempfile.TemporaryDirectory() as t:
        j = os.path.join(t, "p.json")
        subprocess.run(["yosys", "-q", "-p", f"read_verilog {SRC}; prep -top {EX}; write_json {j}"],
                       check=True, capture_output=True)
        m = json.load(open(j))["modules"][EX]
    out = []
    for c in m["cells"].values():
        src = c.get("attributes", {}).get("src", "")
        line = int(re.search(r":(\d+)\.", src).group(1)) if re.search(r":(\d+)\.", src) else None
        w = max(len(b) for b in c["connections"].values())
        out.append({"type": c["type"].lstrip("$"), "w": w, "line": line})
    return sorted(out, key=lambda c: (c["line"] or 0, c["type"]))


def mapped():
    """software/bob/synth.py + equiv.py, as ./bob build runs them -> the cells and the trace"""
    import equiv
    ok, _lines, mod = equiv.equiv([SRC], EX)
    if not ok:
        raise SystemExit("wide: the equivalence check failed; fix that first")
    cells = []
    for name, c in mod["cells"].items():
        t = c["type"]
        rec = {"type": t}
        if t == "$lut":
            rec["init"] = c["parameters"]["LUT"]
            rec["k"] = int(c["parameters"]["WIDTH"], 2)
        cells.append(rec)
    tr = json.load(open(os.path.join(ROOT, "build", "synth", EX, f"{EX}.trace.json")))
    return cells, tr["trace"][:32]


def routes_and_nets():
    """from wide.route: every net's routed wires, and the blocks it joins (for the anneal)"""
    path = os.path.join(ROOT, "software", "bob", "vpr", EX, f"{EX}.route")
    nets, cur = [], None
    for ln in open(path):
        m = re.match(r"Net \d+ \((.+)\)", ln)
        if m:
            cur = {"name": m.group(1), "blocks": [], "segs": []}
            nets.append(cur)
            continue
        m = re.match(r"Node:\s+\d+\s+(\w+)\s+\((\d+),(\d+),\d+\)(?:\s+to\s+\((\d+),(\d+),\d+\))?(?:.*Track:\s+(\d+))?", ln)
        if m and cur is not None:
            t, x1, y1 = m.group(1), int(m.group(2)), int(m.group(3))
            if t in ("SOURCE", "SINK"):
                if [x1, y1] not in cur["blocks"]:
                    cur["blocks"].append([x1, y1])
            elif t in ("CHANX", "CHANY"):
                x2 = int(m.group(4)) if m.group(4) else x1
                y2 = int(m.group(5)) if m.group(5) else y1
                cur["segs"].append([t, x1, y1, x2, y2, int(m.group(6)) if m.group(6) else -1])
    return [n for n in nets if len(n["blocks"]) > 1]


def main():
    import bitgen
    import bitstream as B
    import fasm_from_vpr as FV
    import gen as vol2                              # docs/learn/layers/gen.py: packing, placement
    import timing as T
    vol2.EXAMPLE = EX
    ex = vol2.example()
    dev = vol2.device()
    cells, trace = mapped()
    work = os.path.join(ROOT, "software", "bob", "vpr", EX)
    _bs, _contents, text = FV.build(EX, work)
    word = bitgen.word_from_features(bitgen.parse_fasm(text))
    t = T.analyse(word)
    def xy(n):                                      # an rr node id, or an element name
        if isinstance(n, int) or str(n).isdigit():
            return B.NODE[int(n)][2], B.NODE[int(n)][3]
        m = re.search(r"_x(\d+)y(\d+)", str(n))
        return (int(m.group(1)), int(m.group(2))) if m else (None, None)
    path = [{"kind": h["kind"], "x": xy(h["node"])[0], "y": xy(h["node"])[1], "at": h["at_ns"], "node": str(h["node"])}
            for h in t["path"]]
    import device as DV
    data = {
        "ex": EX, "src": open(SRC).read().splitlines(), "coarse": coarse(), "cells": cells, "trace": trace,
        "inputs": list(DV.BOARD_INPUTS), "clusters": ex["clusters"], "pads": ex["pads"], "nets": routes_and_nets(),
        "fasm": text.splitlines(), "timing": {"cpd": t["cpd_ns"], "fmax": t["fmax_hz"], "margin": t["margin"],
                                              "provisional": t["provisional"], "path": path},
        "dev": {"w": dev["w"], "h": dev["h"], "cells": dev["cells"], "W": dev["W"], "N": dev["N"], "K": dev["K"]},
    }
    style = open(os.path.join(ROOT, "docs", "learn", "layers", "page.html")).read()
    style = style[style.index("<style>"):style.index("</style>") + len("</style>")]
    page = open(os.path.join(HERE, "page.html")).read()
    out = page.replace("<!--STYLE-->", style).replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))
    open(OUT, "w").write(out)
    print(f"wrote {os.path.relpath(OUT, ROOT)} ({len(out) // 1024} KB; {EX}: {len(data['coarse'])} coarse cells, "
          f"{len(cells)} mapped, {len(ex['clusters'])} CLBs, {len(data['nets'])} nets, cpd {t['cpd_ns']} ns)")


if __name__ == "__main__":
    main()
