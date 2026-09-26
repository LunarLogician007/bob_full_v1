#!/usr/bin/env python3
"""
fcsweep.py - connection-box population on the board's own grid, measured (2026-09-26)

M23 chose fc_in 0.10 at W 36 for the 10 x 10 fabric. VPR hands out fractional Fc two tracks
at a time over a port's pins, so at 0.10 thirteen of a CLB's sixteen inputs reach 4 tracks and
three reach only 2 (device.json: 1,856 input muxes of 4 tracks, 364 of 2). The SERV trial
failed on exactly that: 4 overused CLB input pins. M23's sweep priced fc_in 0.15 at W 40,
because fir16's minimum channel width, from one VPR seed, came out at 38 there.

This keeps everything but the connection boxes as the board has it (ARCH_M23: 12 x 10 core,
W 36, L4, Wilton, bob's delays) and, for each variant:

  1. routability: VPR's minimum channel width for every example, over several seeds (the
     best seed counts, as vpr_run.run_retry would find it), and whether it routes at W 36
  2. cost: VPR builds the variant's rr graph at W 36; every routing mux is priced as bob_mux.v
     builds it (gridsweep.hand_luts: LUT6 4:1 leaves, MUXF7/MUXF8) with its select bits

Results in build/fcsweep/results.json, the report in docs/research/2026-09-26-fc-sweep.md.
Docker (OpenFPGA's VPR, as make vpr) is needed.

  software/bob/fcsweep.py [--seeds 3] [--only VARIANT ...]
"""

import argparse
import collections
import gzip
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import device     # noqa: E402
import gridsweep  # noqa: E402
import sweep      # noqa: E402

OUT = os.path.join(ROOT, "build", "fcsweep")
REPORT = os.path.join(ROOT, "docs", "research", "2026-09-26-fc-sweep.md")
W_BOARD = device.ARCH_M23["chan_width"]

# name -> (fc_in_type, fc_in)
VARIANTS = {
    "frac-0.10": ("frac", 0.10),          # the board today (M23)
    "frac-0.15": ("frac", 0.15),          # the reference architecture's value
    "abs-4": ("abs", 4),                  # every input pin 4 tracks
    "abs-6": ("abs", 6),                  # every input pin 6 tracks: the same two LUT6 leaves
}


def arch_of(variant, w=W_BOARD):
    kind, fc = VARIANTS[variant]
    return dict(device.ARCH_M23, chan_width=w, fc_in=fc, fc_in_type=kind)


def _xml(arch):
    d = device.Device(arch=arch, with_rr=False)
    return d.arch_xml(), d.name


def routability(variant, seeds):
    """{example: {"min_w": best over seeds, "by_seed": {...}}} from VPR's binary search"""
    xml, name = _xml(arch_of(variant, 24))
    jobs = [(n, s) for n in sweep.EXAMPLES for s in range(1, seeds + 1)]
    out = collections.defaultdict(dict)
    with ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(sweep.vpr, os.path.join(OUT, variant, "minw", f"{n}_s{s}"), xml, n, name, seed=s): (n, s)
                for n, s in jobs}
        for f, (n, s) in futs.items():
            r = f.result()
            out[n][s] = r["min_w"] if r["routed"] else None
    return {n: {"by_seed": {str(s): w for s, w in sorted(v.items())},
                "min_w": min((w for w in v.values() if w), default=None)} for n, v in out.items()}


def fixed(variant, seeds):
    """{example: {seed: routed?}} at the board's W on the variant's own rr graph, as the board's
    flow routes (vpr_run: --read_rr_graph, --route_chan_width W). This is the number that
    matters: VPR's minimum-width search is not monotonic (fir16 on today's graph: the search
    says 38, yet it routes at 36 with seed 2)."""
    arch = arch_of(variant)
    xml, name = _xml(arch)
    gz = os.path.join(OUT, variant, f"rr_w{W_BOARD}", "rr.xml.gz")
    out = collections.defaultdict(dict)
    jobs = []
    for n in sweep.EXAMPLES:
        for s in range(1, seeds + 1):
            work = os.path.join(OUT, variant, f"w{W_BOARD}", f"{n}_s{s}")
            os.makedirs(work, exist_ok=True)
            with gzip.open(gz, "rb") as src, open(os.path.join(work, "rr.xml"), "wb") as dst:
                shutil.copyfileobj(src, dst)
            jobs.append((n, s, work))
    with ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(sweep.vpr, work, xml, n, name, width=W_BOARD, rr=True, seed=s): (n, s)
                for n, s, work in jobs}
        for f, (n, s) in futs.items():
            out[n][str(s)] = bool(f.result()["routed"])
    for _n, _s, work in jobs:
        try:
            os.remove(os.path.join(work, "rr.xml"))
        except OSError:
            pass
    return dict(out)


def cost(variant):
    """the variant's rr graph at the board's W: input-mux fan-in, host LUTs and select bits"""
    arch = arch_of(variant)
    xml, name = _xml(arch)
    work = os.path.join(OUT, variant, f"rr_w{W_BOARD}")
    rr = sweep.rrgraph(work, xml, name, W_BOARD)
    dev = device.Device(arch=arch, rr_file=rr + ".gz")
    fanin = collections.Counter()
    luts = bits = 0
    for m in dev.muxes.values():
        if m.node not in dev.rr.nodes:
            continue                                  # crossbar muxes: the same in every variant
        c1 = 1 if m.base == 2 else 0
        luts += gridsweep.hand_luts(len(m.inputs), c1)
        bits += m.width
        if c1:
            fanin[len(m.inputs)] += 1
    try:
        os.remove(rr)
    except OSError:
        pass
    return {"ipin_fanin": {str(k): v for k, v in sorted(fanin.items())}, "routing_luts": luts,
            "routing_bits": bits, "muxes": sum(1 for m in dev.muxes.values() if m.node in dev.rr.nodes),
            "chain": dev.chain_width, "frames": dev.nframes}


def report(res):
    base = res.get("frac-0.10", {}).get("cost")
    lines = ["# Connection boxes on the board's grid (2026-09-26)", "",
             "Generated by `software/bob/fcsweep.py` (results in `build/fcsweep/results.json`). Everything",
             f"is the board's architecture (ARCH_M23: 10 x 10 CLBs, W {W_BOARD}, L4, Wilton, bob's delays) except",
             "the connection-box population of the input pins. The cost columns price every routing mux",
             "as `bob_mux.v` builds it (`gridsweep.hand_luts`); the crossbar, CLBs and hard blocks are the",
             "same in every row. Minimum channel widths are VPR's binary search, the best of the seeds.", "",
             "| variant | input pins by tracks | routing muxes | routing LUTs (hand) | vs today | select bits | chain | "
             f"examples routed at W {W_BOARD} (any seed; all runs) | largest min W, VPR's search (example) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for v in VARIANTS:
        e = res.get(v)
        if not e or "cost" not in e or "route" not in e or "fixed" not in e:
            continue
        c, r, fx = e["cost"], e["route"], e["fixed"]
        fan = ", ".join(f"{k}: {n}" for k, n in c["ipin_fanin"].items())
        d = f"{c['routing_luts'] - base['routing_luts']:+,}" if base else ""
        ok = f"{sum(any(s.values()) for s in fx.values())}/{len(fx)} " \
             f"({sum(sum(s.values()) for s in fx.values())}/{sum(len(s) for s in fx.values())} runs)"
        worst = max(((x["min_w"] or 10 ** 6), n) for n, x in r.items())
        lines.append(f"| {v} | {fan} | {c['muxes']:,} | {c['routing_luts']:,} | {d} | {c['routing_bits']:,} | "
                     f"{c['chain']:,} | {ok} | {worst[0] if worst[0] < 10 ** 6 else 'unroutable'} "
                     f"({worst[1]}) |")
    lines += ["", f"Seeds that route each example on the variant's own W {W_BOARD} graph (pads left free, as",
              "`sweep.py` routes; `make vpr` fixes them to the board's pins). A run that fails ends with its",
              "overused nodes in `build/fcsweep/<variant>/w36/<example>_s<seed>/vpr.log`:", "",
              "| variant | " + " | ".join(sweep.EXAMPLES) + " |", "|---|" + "---|" * len(sweep.EXAMPLES)]
    for v in VARIANTS:
        fx = res.get(v, {}).get("fixed")
        if fx:
            lines.append(f"| {v} | " + " | ".join(
                ",".join(s for s, ok in sorted(fx.get(n, {}).items()) if ok) or "none" for n in sweep.EXAMPLES) + " |")
    lines += ["", "Minimum channel width per example from VPR's binary search (best seed; not monotonic,",
              "so it can exceed a width the example routes at):", "",
              "| variant | " + " | ".join(sweep.EXAMPLES) + " |", "|---|" + "---|" * len(sweep.EXAMPLES)]
    for v in VARIANTS:
        r = res.get(v, {}).get("route")
        if r:
            lines.append(f"| {v} | " + " | ".join(str(r.get(n, {}).get("min_w")) for n in sweep.EXAMPLES) + " |")
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    open(REPORT, "w").write("\n".join(lines) + "\n")
    print(f"wrote {os.path.relpath(REPORT, ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--only", nargs="*", default=None, choices=list(VARIANTS))
    ap.add_argument("--report", action="store_true", help="only rewrite the report from the results")
    a = ap.parse_args()
    if shutil.which("docker") is None and not a.report:
        print("fcsweep: needs Docker (OpenFPGA's VPR image, as make vpr)")
        return 1
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "results.json")
    res = json.load(open(path)) if os.path.exists(path) else {}
    if not a.report:
        for v in a.only or list(VARIANTS):
            e = res.setdefault(v, {})
            if "cost" not in e:
                e["cost"] = cost(v)
                json.dump(res, open(path, "w"), indent=1)
            if e.get("seeds") != a.seeds:
                e["route"], e["seeds"] = routability(v, a.seeds), a.seeds
                json.dump(res, open(path, "w"), indent=1)
            if e.get("fixed_seeds") != a.seeds:
                e["fixed"], e["fixed_seeds"] = fixed(v, a.seeds), a.seeds
                json.dump(res, open(path, "w"), indent=1)
            c = e["cost"]
            print(f"{v}: input pins by tracks {c['ipin_fanin']}, routing LUTs {c['routing_luts']:,}, "
                  f"min W per example {({n: x['min_w'] for n, x in e['route'].items()})}", flush=True)
    report(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
