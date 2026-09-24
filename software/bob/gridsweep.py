#!/usr/bin/env python3
"""
gridsweep.py - how many CLBs fit the XC7Z020, measured (M23)

M22 left the chip at 71.8% LUTs, 70.6% SLICEM and 82.3% slices with 81 CLBs, and routing is
now most of the logic (64% of the yosys LUTs). This sweep asks, for bigger grids and a
cheaper routing fabric (channel width W, connection-box population fc_in):

  1. routability: VPR's minimum channel width for every example on the grid (binary search),
     at fc_in 0.15 and 0.10
  2. cost: the grid's rr graph at each W is built by VPR; its routing muxes are counted by
     size, each priced with its measured yosys cost (bob_mux.v synthesised alone at every
     size), and turned into host resources with a model calibrated on the two Vivado
     builds we have:
         Vivado logic LUTs = A * routing(yosys) + B * rest(yosys)     (M21 and M22 solve A, B)
         rest(yosys)       = REST_FIXED + REST_PER_CLB * CLBs          (M22)
         LUT as memory     = 152 CFGLUT5 per CLB                       (M22: 12,282 / 81)
         slices            = all LUTs / 3.49                           (M22's packing)
  3. limits: slices <= 95%, SLICEM <= 90%, LUTs <= 85% of the XC7Z020

Results in build/gridsweep/, the report in docs/reports/M23/grid_sweep.md.

  software/bob/gridsweep.py [--only TAG ...] [--report]
"""

import argparse
import collections
import json
import math
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import device  # noqa: E402
import sweep   # noqa: E402

OUT = os.path.join(ROOT, "build", "gridsweep")
REPORT = os.path.join(ROOT, "docs", "reports", "M23", "grid_sweep.md")
COST = os.path.join(HERE, "arch", "mux_cost_yosys.json")

# the XC7Z020
LUTS, SLICEM_LUTS, SLICES = 53200, 17400, 13300
LIMITS = {"luts": 0.85, "slicem": 0.90, "slices": 0.95}
# calibration (docs/reports/M21, M22; derivation in the report)
A_ROUTING, B_REST = 0.785, 0.551
REST_FIXED, REST_PER_CLB = 4000, 116          # M22: 13,382 yosys LUTs besides routing, 81 CLBs
CFGLUT5_PER_CLB = 152
# M23: each crossbar mux keeps its five CFGLUT5 leaves, and its root becomes a fixed OR in a
# plain LUT (an unselected leaf holds zeros): 24 x 5 + 8 = 128 CFGLUT5 per CLB, 24 OR roots.
# (Sharing a leaf between two muxes through O5/O6 looked like 80 per CLB, but Vivado maps a
# dual-output CFGLUT5 to SRL16E + SRLC32E, two LUT sites: the first M23 build did not place.)
CFGLUT5_PER_CLB_M23, OR_ROOTS_PER_CLB = 128, 24
SLICEMS = 4350
CFGLUT5_PER_SLICEM = 12282 / 3640              # M22's packing (one shift enable per CLB)
LUTS_PER_SLICE = 38184 / 10939                # M22's packing


def grid(nx, ny, bram_x, dsp_x, h, w=40, fc_in=0.15):
    return {"nx": nx, "ny": ny, "chan_width": w, "segment_length": 4, "fs": 3,
            "fc_in": fc_in, "fc_out": 0.10, "io_capacity": 1,
            "columns": [{"type": "bram", "x": bram_x, "height": h},
                        {"type": "dsp", "x": dsp_x, "height": h}],
            "cluster": dict(device.CLUSTER_N4)}


# CLB columns x rows; the hard columns keep 2 BRAM + 2 DSP (dsp_jtag.v holds two slices)
GRIDS = {
    "9x9":   (11, 9, 3, 8, 4),       # M22 as built: 81 CLBs
    "10x10": (12, 10, 3, 8, 5),      # 100
    "11x10": (13, 10, 3, 9, 5),      # 110
    "11x11": (13, 11, 3, 9, 5),      # 121
    "12x10": (14, 10, 3, 10, 5),     # 120
    "12x11": (14, 11, 3, 10, 5),     # 132
    "12x12": (14, 12, 3, 10, 6),     # 144
    "13x12": (15, 12, 3, 11, 6),     # 156
    "13x13": (15, 13, 3, 11, 6),     # 169
}
FC_INS = (0.15, 0.10)
FC_ONLY = {t: (0.10,) for t in ("11x11", "12x10", "12x11", "12x12", "13x12", "13x13")}     # 0.15 already fails at 110
WIDTHS = (40, 36, 32, 28, 24)


def mux_cost():
    """yosys LUTs of one bob_mux by (inputs, const1), measured once and cached"""
    if os.path.exists(COST):
        return {tuple(map(int, k.split(","))): v for k, v in json.load(open(COST)).items()}
    import tempfile
    res = {}
    with tempfile.TemporaryDirectory() as t:
        for c1 in (0, 1):
            for n in range(1, 41):
                w = (n + 1 + c1).bit_length()
                v = os.path.join(t, "m.v")
                open(v, "w").write(f"module t(input [{w - 1}:0] sel, input [{n - 1}:0] in, output o);\n"
                                   f"  bob_mux #(.N({n}), .W({w}), .C1({c1})) m (.sel(sel), .in(in), .o(o));\nendmodule\n")
                subprocess.run(["yosys", "-q", "-p", f"read_verilog {ROOT}/hw/src/fabric/bob_mux.v {v}; "
                                f"synth_xilinx -flatten -top t; tee -q -o {t}/s.txt stat"], check=True,
                               capture_output=True)
                st = open(f"{t}/s.txt").read()
                res[(n, c1)] = {"luts": sum(int(x) for x in re.findall(r"^\s+(\d+)\s+LUT\d", st, re.M)), "bits": w}
    json.dump({f"{n},{c}": v for (n, c), v in sorted(res.items())}, open(COST, "w"), indent=0)
    return res


def hand_luts(n, c1):
    """LUT6s of one routing mux built from primitives (hw/src/fabric/bob_mux.v, M23): 4:1 LUT6
    leaves on sel[1:0] (the constants are INIT bits, not pins), MUXF7/MUXF8 on sel[2], sel[3]
    inside the slice, and one more LUT6 per four 16:1 groups above that"""
    leaves = math.ceil((n + 1 + c1) / 4)
    if leaves <= 4:
        return leaves
    groups = math.ceil(leaves / 4)
    return leaves + math.ceil(groups / 4) if groups <= 4 else leaves + groups // 4 + 1


def model(n_clb, hist, cost, hand=False):
    if hand:
        routing = sum(k * hand_luts(*key) for key, k in hist.items())
    else:
        routing = sum(k * cost[key]["luts"] for key, k in hist.items())
    sel_bits = sum(k * cost[key]["bits"] for key, k in hist.items())
    rest = REST_FIXED + REST_PER_CLB * n_clb
    logic = (1.0 if hand else A_ROUTING) * routing + B_REST * rest + (OR_ROOTS_PER_CLB * n_clb if hand else 0)
    mem = (CFGLUT5_PER_CLB_M23 if hand else CFGLUT5_PER_CLB) * n_clb
    luts = logic + mem
    return {"routing_yosys": routing, "select_bits": sel_bits, "logic_luts": round(logic),
            "cfglut5": mem, "luts": round(luts), "slices": round(luts / LUTS_PER_SLICE),
            "lut_pct": 100 * luts / LUTS, "slicem_pct": 100 * mem / SLICEM_LUTS,
            "slicem_slice_pct": 100 * mem / CFGLUT5_PER_SLICEM / SLICEMS,
            "slice_pct": 100 * luts / LUTS_PER_SLICE / SLICES,
            "fits": luts <= LIMITS["luts"] * LUTS and mem / CFGLUT5_PER_SLICEM <= LIMITS["slicem"] * SLICEMS
                    and luts / LUTS_PER_SLICE <= LIMITS["slices"] * SLICES}


def min_widths(tag, fc_in):
    """VPR's minimum channel width for every example on this grid and connection boxes"""
    nx, ny, bx, dx, h = GRIDS[tag]
    arch = grid(nx, ny, bx, dx, h, 24, fc_in)
    arch["delays"] = sweep.bob_delays()
    xml = device.Device(arch=arch, with_rr=False).arch_xml()
    name = device.Device(arch=arch, with_rr=False).name
    work = os.path.join(OUT, f"{tag}_fc{int(fc_in * 100)}", "minw")
    res = {}
    with ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(sweep.vpr, os.path.join(work, n), xml, n, name): n for n in sweep.EXAMPLES}
        for f, n in futs.items():
            r = f.result()
            res[n] = r["min_w"] if r["routed"] else None
    return res


def _dev(tag, fc_in, w):
    nx, ny, bx, dx, h = GRIDS[tag]
    arch = grid(nx, ny, bx, dx, h, w, fc_in)
    arch["delays"] = sweep.bob_delays()
    return arch


def _hist(dev):
    hist = collections.Counter()
    for m in dev.muxes.values():
        if m.node in dev.rr.nodes:
            hist[(len(m.inputs), 1 if m.base == 2 else 0)] += 1
    return hist


def _hand(r, n_clb, hist, cost):
    r.update(model(n_clb, hist, cost))
    h = model(n_clb, hist, cost, hand=True)
    r["hand"] = {k: h[k] for k in ("routing_yosys", "logic_luts", "cfglut5", "luts", "slices", "lut_pct",
                                   "slice_pct", "slicem_pct", "slicem_slice_pct", "fits")}
    r["hist"] = {f"{n},{c}": k for (n, c), k in sorted(hist.items())}
    return r


def cost_at(tag, fc_in, w, cost):
    arch = _dev(tag, fc_in, w)
    name = device.Device(arch=arch, with_rr=False).name
    xml = device.Device(arch=arch, with_rr=False).arch_xml()
    rr = sweep.rrgraph(os.path.join(OUT, f"{tag}_fc{int(fc_in * 100)}", f"rr_w{w}"), xml, name, w)
    dev = device.Device(arch=arch, rr_file=rr + ".gz")
    hist = _hist(dev)
    n_clb = len(dev.by_type["clb"])
    r = model(n_clb, hist, cost)
    r.update(clbs=n_clb, luts_guest=4 * n_clb, muxes=sum(hist.values()), chain=dev.chain_width,
             frames=dev.nframes, pads=len(dev.pads))
    _hand(r, n_clb, hist, cost)
    try:
        os.remove(rr)                               # keep the .gz only
    except OSError:
        pass
    return r


def add_hand(tag, fc_in, w, r, cost):
    """the hand-mapped variant of a row measured before it existed (from the kept graph)"""
    rr = os.path.join(OUT, f"{tag}_fc{int(fc_in * 100)}", f"rr_w{w}")
    gz = [os.path.join(rr, f) for f in os.listdir(rr) if f.endswith(".gz")]
    dev = device.Device(arch=_dev(tag, fc_in, w), rr_file=gz[0])
    return _hand(r, r["clbs"], _hist(dev), cost)


def run(tags):
    cost = mux_cost()
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "results.json")
    res = json.load(open(path)) if os.path.exists(path) else {}
    for tag in tags:
        for fc in FC_ONLY.get(tag, FC_INS):
            key = f"{tag}_fc{int(fc * 100)}"
            e = res.setdefault(key, {"grid": tag, "fc_in": fc})
            if "min_w" not in e:
                e["min_w"] = min_widths(tag, fc)
                json.dump(res, open(path, "w"), indent=1)
            need = max((w for w in e["min_w"].values() if w), default=None)
            e["need"] = need
            e.setdefault("at", {})
            for w in WIDTHS:
                if need is not None and w < need:
                    continue                        # the examples do not route
                if str(w) not in e["at"]:
                    e["at"][str(w)] = cost_at(tag, fc, w, cost)
                    json.dump(res, open(path, "w"), indent=1)
                if "slicem_slice_pct" not in e["at"][str(w)].get("hand", {}):
                    add_hand(tag, fc, w, e["at"][str(w)], cost)
                    json.dump(res, open(path, "w"), indent=1)
                print(f"{key} W={w}: {e['at'][str(w)]['clbs']} CLBs, {e['at'][str(w)]['luts']} LUTs "
                      f"({e['at'][str(w)]['lut_pct']:.0f}%), slices {e['at'][str(w)]['slice_pct']:.0f}%, "
                      f"SLICEM {e['at'][str(w)]['slicem_pct']:.0f}%, fits {e['at'][str(w)]['fits']}; hand-mapped "
                      f"{e['at'][str(w)]['hand']['luts']} LUTs, slices {e['at'][str(w)]['hand']['slice_pct']:.0f}%, "
                      f"fits {e['at'][str(w)]['hand']['fits']} "
                      f"(examples need W >= {need})", flush=True)
    return res


def report(res):
    lines = ["# M23: how many CLBs fit the XC7Z020",
             "",
             "Generated by `software/bob/gridsweep.py` (results in `build/gridsweep/results.json`).",
             "",
             "Each row is a grid of 4-element CFGLUT5 CLBs (M22's cluster) with a channel width W and",
             "connection-box population fc_in. **W needed** is the largest minimum channel width VPR found",
             "over every example on that grid (binary search); a row exists only where the examples route.",
             "Host resources come from the routing graph VPR builds for that W: its muxes counted by size,",
             "each priced by its measured yosys cost, then the model calibrated on the M21 and M22 builds:",
             "",
             f"- Vivado logic LUTs = {A_ROUTING} × routing (yosys) + {B_REST} × rest (yosys), rest = {REST_FIXED} + {REST_PER_CLB} × CLBs",
             f"- LUT as memory = {CFGLUT5_PER_CLB} CFGLUT5 per CLB; slices = all LUTs / {LUTS_PER_SLICE:.2f} (M22's packing)",
             f"- SLICEM slices = CFGLUT5 / {CFGLUT5_PER_SLICEM:.2f} (M22: 12,282 in 3,640 SLICEMs; the four in a",
             "  SLICEM share one shift enable, so they must come from one CLB)",
             f"- fits = LUTs ≤ {int(LIMITS['luts'] * 100)}%, SLICEM slices ≤ {int(LIMITS['slicem'] * 100)}%, slices ≤ {int(LIMITS['slices'] * 100)}%",
             "",
             "The model reproduces M22 (9x9, W 40, fc_in 0.15) by construction; the other rows are",
             "predictions, to be confirmed by a whole-design yosys estimate and then Vivado.",
             "",
             "The **hand** columns price every routing mux as M23 builds it from primitives (LUT6 4:1 leaves,",
             "MUXF7/MUXF8 inside the slice; `hand_luts()`), which Vivado keeps one for one, and every crossbar",
             "root as a fixed OR in a plain LUT (the leaves stay CFGLUT5: 128 per CLB, not 152).",
             "",
             "| grid | CLBs | LUTs (guest) | fc_in | W needed | W | routing muxes | host LUTs | slices % | fits | host LUTs, hand | LUT %, hand | slices %, hand | SLICEM slices % | SLICEM slices %, hand | config bits | fits, hand |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key in sorted(res, key=lambda k: (GRIDS[res[k]["grid"]][0] * GRIDS[res[k]["grid"]][1], res[k]["fc_in"])):
        e = res[key]
        for w in sorted(e.get("at", {}), key=int, reverse=True):
            r = e["at"][w]
            h = r["hand"]
            lines.append(f"| {e['grid']} | {r['clbs']} | {r['luts_guest']} | {e['fc_in']} | {e.get('need')} | {w} | "
                         f"{r['muxes']} | {r['luts']:,} | {r['slice_pct']:.1f} | {'yes' if r['fits'] else 'no'} | "
                         f"{h['luts']:,} | {h['lut_pct']:.1f} | {h['slice_pct']:.1f} | "
                         f"{r['slicem_slice_pct']:.1f} | {h['slicem_slice_pct']:.1f} | {r['chain']:,} | {'**yes**' if h['fits'] else 'no'} |")
    lines += ["", "Minimum channel width per example:", "",
              "| grid, fc_in | " + " | ".join(sweep.EXAMPLES) + " |",
              "|---|" + "---|" * len(sweep.EXAMPLES)]
    for key in sorted(res):
        e = res[key]
        lines.append(f"| {e['grid']}, {e['fc_in']} | " + " | ".join(str(e['min_w'].get(n)) for n in sweep.EXAMPLES) + " |")
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    open(REPORT, "w").write("\n".join(lines) + "\n")
    print(f"wrote {os.path.relpath(REPORT, ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    res = run(a.only or list(GRIDS))
    report(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
