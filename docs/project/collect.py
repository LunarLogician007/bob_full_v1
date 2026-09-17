#!/usr/bin/env python3
"""
collect.py - the numbers behind docs/project/REPORT.md and project.html, taken from the
repository itself (never typed by hand):

  docs/hwtest/results.log      every board run: date, milestone, checks passed / failed
  docs/reports/M*/             Vivado utilisation and timing per build
  tools/bob/device.json        the current device
  tools/bob/vpr/*/stamp.txt    VPR results per example; docs/reports/M12b/pnr_vs_vpr.md
  build/m15_check2.log         check counts of the last `make check` (if present)
  sim/mutate_*.sh              mutants per suite
  git                          commits, tags, lines of code per area

  python3 docs/project/collect.py      -> docs/project/data.json
"""

import collections
import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def sh(*args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True).stdout


def board_runs():
    runs, cur = [], None
    for ln in open(os.path.join(ROOT, "docs", "hwtest", "results.log")):
        m = re.match(r"(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)\s+(\S+)\s+tag=(\S+)", ln)
        if m:
            cur = {"date": m.group(1), "time": m.group(2), "milestone": m.group(3), "tag": m.group(4),
                   "pass": 0, "fail": 0, "checks": []}
            runs.append(cur)
            continue
        m = re.match(r"\s+(PASS|FAIL)\s+(\S+)\s*(.*)", ln)
        if m and cur is not None:
            cur["pass" if m.group(1) == "PASS" else "fail"] += 1
            cur["checks"].append([m.group(1), m.group(2), m.group(3)[:220]])
    return runs


def vivado():
    out = {}
    base = os.path.join(ROOT, "docs", "reports")
    for d in sorted(os.listdir(base)):
        u, t = os.path.join(base, d, "util.rpt"), os.path.join(base, d, "timing.rpt")
        if not os.path.exists(u):
            continue
        txt = open(u).read()
        get = lambda name: int(re.search(r"\|\s*" + re.escape(name) + r"\s*\|\s*(\d+)", txt).group(1))  # noqa: E731
        row = {"lut": get("Slice LUTs"), "ff": get("Slice Registers")}
        for name, key in (("Block RAM Tile", "bram"), ("DSPs", "dsp")):
            m = re.search(r"\|\s*" + name + r"\s*\|\s*([\d.]+)", txt)
            row[key] = float(m.group(1)) if m else 0
        if os.path.exists(t):
            m = re.search(r"WNS\(ns\)\s+TNS\(ns\).*?\n[-\s]+\n\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(\d+)\s+(\d+)\s+(-?[\d.]+)",
                          open(t).read(), re.S)
            if m:
                row.update(wns=float(m.group(1)), tns=float(m.group(2)), failing=int(m.group(3)),
                           endpoints=int(m.group(4)), whs=float(m.group(5)))
        info = os.path.join(base, d, "build_info.txt")
        if os.path.exists(info):
            for ln in open(info):
                k, _, v = ln.strip().partition(" ")
                if k in ("idcode", "top", "built"):
                    row[k] = v.strip()
        out[d] = row
    return out


def device():
    d = json.load(open(os.path.join(ROOT, "tools", "bob", "device.json")))
    blocks = collections.Counter(b["type"] for b in d.get("blocks", [])) if isinstance(d.get("blocks"), list) else {}
    return {"chain_width": d["chain"]["width"], "frames": d["frames"]["count"], "frame_bits": d["frames"]["bits"],
            "grid": [d["arch"]["grid_width"], d["arch"]["grid_height"]], "chan_width": d["arch"]["chan_width"],
            "lut_k": d["lut_k"], "muxes": len(d["rr"]["muxes"]), "blocks": dict(blocks)}


def layout():
    """the current grid (blocks, board pads, frame columns) for the device picture"""
    d = json.load(open(os.path.join(ROOT, "tools", "bob", "device.json")))
    names = {p["pad"]: p["name"] for p in d["pads"]["board_inputs"] + d["pads"]["board_outputs"]}
    pads = [{"pad": p["pad"], "x": p["x"], "y": p["y"], "name": names.get(p["pad"])} for p in d["pads"]["io"]]
    heights = {c["type"]: c["height"] for c in d["arch"]["columns"]} if "columns" in d["arch"] else {}
    return {"blocks": [[b["name"], b["type"], b["x"], b["y"]] for b in d["blocks"]], "pads": pads,
            "heights": heights, "frame_columns": d["frames"]["columns"]}


def streams():
    """real packet streams from tools/bob/packets.py, annotated (the first and last words of each)"""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tools", "bob"))
    sys.path.insert(0, os.path.join(ROOT, "host"))
    import packets as P
    from designs import d_partial, d_showcase

    def annotate(words, head=24, tail=10, synced=False):
        lines = P.describe([P.SYNC] + words)[1:] if synced else P.describe(words)
        rows = [ln.split(None, 1) + [""] for ln in lines]
        rows = [[r[0], r[1].strip() if len(r) > 1 else ""] for r in rows]
        if len(rows) > head + tail:
            rows = rows[:head] + [["…", f"{len(rows) - head - tail} more words"]] + rows[-tail:]
        return rows

    show = d_showcase().build().to_int()
    a, b = d_partial("and").build().to_int(), d_partial("or").build().to_int()
    freeze, frames, n = P.partial_streams(a, b)
    brams = {0: [(k * 2654435761) & 0x3FFFF for k in range(1024)]}
    full = P.load_stream(show, brams=brams)
    return {"load": annotate(full, 22, 12), "load_words": len(full),
            "partial_freeze": annotate(freeze, 40, 0), "partial_frames": annotate(frames, 40, 0, synced=True),
            "partial_changed": n, "readback": annotate(P.readback_stream(), 40, 0),
            "bram_readback": annotate(P.bram_readback_stream(1, 5, 2), 40, 0)}


def vpr_examples():
    out = []
    base = os.path.join(ROOT, "tools", "bob", "vpr")
    for name in sorted(os.listdir(base)):
        st = os.path.join(base, name, "stamp.txt")
        if not os.path.exists(st):
            continue
        txt = open(st).read()
        wl = re.search(r"wirelength\s*[:=]?\s*(\d+)", txt)
        cp = re.search(r"critical[_ ]path\s*[:=]?\s*([\d.]+)", txt)
        clbs = None
        log = os.path.join(base, name, f"{name}.place")
        if os.path.exists(log):
            clbs = sum(1 for ln in open(log) if re.match(r"\S+\s+\d+\s+\d+\s+\d+\s+\d+\s+#\d+", ln))
        out.append({"name": name, "wirelength": int(wl.group(1)) if wl else None,
                    "critical_ns": float(cp.group(1)) if cp else None})
    pnr = os.path.join(ROOT, "docs", "reports", "M12b", "pnr_vs_vpr.md")
    rows = []
    if os.path.exists(pnr):
        for ln in open(pnr):
            c = [x.strip() for x in ln.strip().strip("|").split("|")]
            if len(c) >= 5 and c[0] and not c[0].startswith("-") and c[0] not in ("design", "Design"):
                rows.append(c)
    return {"vpr": out, "pnr_table": rows}


def checks():
    out = {}
    log = os.path.join(ROOT, "build", "m15_check2.log")
    if os.path.exists(log):
        txt = open(log).read()
        title = None
        for ln in txt.splitlines():
            m = re.match(r"=== (.*) ===$", ln)
            if m and "PASSED" not in m.group(1) and "green" not in m.group(1):
                title = m.group(1)
            m = re.match(r"\s+(\d+) checks$", ln)
            if m and title:
                out[title] = int(m.group(1))
        m = re.search(r"(\d+) passed, (\d+) skipped", txt)
        if m:
            out["pytest"] = int(m.group(1))
    muts, cur = {}, None
    mlog = os.path.join(ROOT, "build", "m15_mutate.log")          # the last `make mutate`
    if os.path.exists(mlog):
        for ln in open(mlog):
            m = re.match(r"sim/(mutate_\w+)\.sh", ln.strip())
            if m:
                cur = m.group(1)
                muts[cur] = {"killed": 0, "survived": 0}
            elif cur and ln.startswith("  killed"):
                muts[cur]["killed"] += 1
            elif cur and ("SURVIVED" in ln or "ERROR" in ln):
                muts[cur]["survived"] += 1
    return {"testbenches": out, "mutants": muts}


def code():
    files = sh("git", "ls-files").split()
    areas = collections.Counter()
    skip = ("release/", "docs/reports/", "tools/bob/vpr/", "tools/bob/arch/", "hw/src/generated/")
    for f in files:
        if f.startswith(skip) or f.endswith((".vh", ".json", ".gz", ".tex", ".log", ".html")):
            continue
        p = os.path.join(ROOT, f)
        if not os.path.isfile(p):
            continue
        try:
            n = sum(1 for _ in open(p, errors="replace"))
        except OSError:
            continue
        ext = os.path.splitext(f)[1]
        kind = {".v": "Verilog", ".sv": "SystemVerilog", ".py": "Python", ".sh": "shell", ".tcl": "Tcl",
                ".md": "Markdown", ".js": "JavaScript", ".xdc": "XDC"}.get(ext, "other")
        areas[kind] += n
    gen = sum(1 for _ in open(os.path.join(ROOT, "hw", "src", "generated", "bob_fabric.v")))
    return {"lines": dict(areas), "generated_fabric_lines": gen,
            "commits": int(sh("git", "rev-list", "--count", "HEAD").strip() or 0),
            "tags": sh("git", "tag").split()}


def main():
    data = {"board_runs": board_runs(), "vivado": vivado(), "device": device(), "examples": vpr_examples(),
            "checks": checks(), "code": code(), "layout": layout(), "streams": streams()}
    path = os.path.join(HERE, "data.json")
    json.dump(data, open(path, "w"), indent=1)
    r = data["board_runs"]
    print(f"wrote {os.path.relpath(path, ROOT)}: {len(r)} board runs, {sum(x['pass'] for x in r)} passing checks, "
          f"{len(data['vivado'])} Vivado builds, {len(data['examples']['vpr'])} VPR results")


if __name__ == "__main__":
    main()
