#!/usr/bin/env python3
"""
delays.py - per-element delays of the fabric, measured on the Vivado implementation (M20).

software/bob/timing.py sums one delay per element class along a configured design's
paths: a routing mux (track <- track), an input mux (IPIN <- track), M21's crossbar mux
(element input <- CLB pin or feedback), a LUT (element input -> its output), carry (cin ->
cout), flip-flop clock-to-Q and setup. This module finds those
numbers in Vivado timing reports.

It works because Vivado keeps the fabric's rr-wire names through flattening: every
routing wire is a net u_core/u_fabric/r<node> (bob_fabric.v), and a timing report lists
each net with the arrival time at its load. Two consecutive rr nets A -> B on a reported
path, where B's mux has A as an input, are one routing hop, and arrival(B) - arrival(A) is
B's mux plus B's wire: exactly the per-node delay timing.py adds. The same holds for
IPIN -> OPIN of one CLB (the LUT, plus the output mux and wire).

  plan  -> hw/scripts/delay_samples.txt: which hops the build should time (a random sample
           of every class, reproducible by seed), read by hw/scripts/extract_delays.tcl
  fold REPORT... -> software/bob/delays.json: the worst hop of each class over every hop
           found in the reports (with its count, median and 95th percentile)

Until the M20 build exists, `fold docs/reports/M16/timing.rpt` measures the classes from
M16's one long reported path (over a thousand hops of the real 12x10 implementation) and
the result is marked provisional: one path is a sample, not the whole fabric.
"""

import argparse
import json
import os
import random
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402

OUT = os.path.join(HERE, "delays.json")
SAMPLES = os.path.join(ROOT, "hw", "scripts", "delay_samples.txt")
PREFIX = "u_core/u_fabric/"
KIND = {n[0]: n[1] for n in B.DEVICE["rr"]["nodes"]}
# a net line: "net (fo=9, routed)   2.312  5020.183    u_core/u_fabric/r4284"
NET = re.compile(r"^\s*net \(.*?\)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+(\S+)\s*$")
CELL_Q = re.compile(r"\((Prop_fd[rs]e_C_Q)\)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)")
SETUP = re.compile(r"\((Setup_fd[rs]e_C_(?:D|CE|R|S))\)\s+(-?\d+\.\d+)")

# M21: which element pins are which nodes, for the LUT and carry classes. An element's
# inputs (EIN) and the carry links between its CLB's elements (ECY) live inside bob_clb
# (bob_fabric.v), so their nets are u_clb_x<x>y<y>/x<e>[j] and u_clb_x<x>y<y>/cy[e+1];
# its outputs and the CLB's own carry pins are rr wires r<node>.
PIN_OF = {}
NET_OF = {}                                  # node -> its net in the flattened design
for _el in B.ELEMENTS:
    _p = _el["pins"]
    _cell = f"u_clb_x{_el['x']}y{_el['y']}"
    for _j in range(B.LUT_K):
        PIN_OF[_p[f"I[{_j}]"]] = (_el["name"], f"I[{_j}]")
        NET_OF[_p[f"I[{_j}]"]] = f"{PREFIX}{_cell}/x{_el['e']}[{_j}]"
    for _k in ("out0", "cin", "cout"):
        PIN_OF.setdefault(_p[_k], (_el["name"], _k))
    PIN_OF[_p["out0"]] = (_el["name"], "out0")
    if B.NODE[_p["cout"]][1] == "ECY":
        NET_OF[_p["cout"]] = f"{PREFIX}{_cell}/cy[{_el['e'] + 1}]"
for _n in B.NODE:
    NET_OF.setdefault(_n, f"{PREFIX}r{_n}")
NODE_OF_NET = {v: k for k, v in NET_OF.items()}
MUX_INPUTS = {node: set(ins) for node, (_lo, _w, _base, ins) in B.MUX.items()}


def _cls(node):
    return {"IPIN": "mux_ipin", "EIN": "mux_xbar"}.get(KIND.get(node), "mux_chan")


def _node(net):
    """u_core/u_fabric/r123 -> 123, u_core/u_fabric/u_clb_x1y1/x3[2] -> its EIN node"""
    return NODE_OF_NET.get(net)


HARD = re.compile(r"\b(DSP48E1|RAMB\w*|CARRY4|FD[RSCP]E\w*)\b")


def _clean(net):
    """An intermediate net that can sit inside one bob mux: an anonymous net of the
    flattened fabric itself - not the configuration store, not a hard block's, not another
    named fabric signal (dsp_p, bram do ...)."""
    if not net.startswith(PREFIX):
        return False
    rest = net[len(PREFIX):]
    rest = re.sub(r"^u_clb_x\d+y\d+/(u_e\d+/(u_lut/)?)?", "", rest)   # M21: inside one CLB / element
    return "/" not in rest and re.search(r"(_n_\d+|_i_\d+.*|\[\d+\]_i_\w*|^t\[\d+\])$", rest) is not None


def hops(text):
    """Every (class, from node, to node, ns) hop on every path in a report. A hop is two
    rr nets with only the LUTs of one mux between them: a path that passes through a hard
    block, the configuration store or any other named signal between them is not one hop
    (M16's report has r6013 -> DSP48 -> dsp_p -> r6003, where r6013 is also an input of
    r6003's mux: counting it would call a DSP a 14.8 ns routing mux)."""
    out = []
    for path in re.split(r"\n(?=Slack|-{20,}\s*\n\s*Slack)", text):
        prev = None                                   # (node, arrival) of the last rr net
        clean = True                                  # nothing but one mux's LUTs since then
        for line in path.splitlines():
            if HARD.search(line):
                clean = False
            m = NET.match(line)
            if not m:
                continue
            node = _node(m.group(3))
            if node is None:
                if not _clean(m.group(3)):
                    clean = False
                continue
            arr = float(m.group(2))
            if prev is not None and clean:
                a, ta = prev
                cls = None
                if node in MUX_INPUTS and a in MUX_INPUTS[node]:
                    cls = _cls(node)
                elif a in PIN_OF and node in PIN_OF and PIN_OF[a][0] == PIN_OF[node][0]:
                    pa, pb = PIN_OF[a][1], PIN_OF[node][1]
                    if pa.startswith("I[") and pb == "out0":
                        cls = "lut"
                    elif pa == "cin" and pb == "cout":
                        cls = "carry"
                    elif pa.startswith("I[") and pb == "cout":
                        cls = "lut_cout"
                elif a in B.DIRECT.values() and node in B.DIRECT and B.DIRECT[node] == a:
                    cls = "direct"
                if cls:
                    out.append((cls, a, node, round(arr - ta, 3)))
            prev = (node, arr)
            clean = True
    return out


def fold(texts, provisional, source):
    """reports -> the delays.json dict: the worst hop per class, with statistics."""
    found = {}
    for t in texts:
        for cls, _a, _b, ns in hops(t):
            found.setdefault(cls, []).append(ns)
        for cls, v in ff_samples(t).items():
            if v:
                found.setdefault(cls, []).extend(v)
    stats, ns = {}, {}
    for cls, v in sorted(found.items()):
        v = sorted(v)
        stats[cls] = {"n": len(v), "max": v[-1], "median": statistics.median(v),
                      "p95": v[min(len(v) - 1, int(0.95 * len(v)))]}
        ns[cls] = v[-1]
    # classes a report cannot show (the flip-flop's own timing, BRAM, DSP) and classes
    # the sample happened to miss keep the previous file's values, and say so
    try:
        prev = json.load(open(OUT))
        old = prev["ns"]
        old_prov = bool(prev.get("provisional"))
    except (OSError, ValueError, KeyError):
        old, old_prov = {}, False
    kept = {}
    for cls, v in old.items():
        if cls not in ns:
            ns[cls] = v
            kept[cls] = v
    ns["lut"] = max(ns.get("lut", 0), ns.get("lut_cout", 0))
    # input wire -> D is the LUT then the D select and setup; timing.py adds the LUT on
    # its own, so the flip-flop's share is what the LUT does not already cover
    if "ffd" in ns:
        ns["ff_setup"] = round(max(0.0, ns.pop("ffd") - ns["lut"]), 3)
        kept.pop("ff_setup", None)
    ns.setdefault("wire", 0.0)
    ns["direct"] = 0.0                    # a direct is a wire inside the fabric; its delay
    # M22: a fold that measured nothing (every sample NOPATH) must not relabel old numbers
    # as measured - that would drop timing.py's guard band from 2x to 1.25x on estimates.
    # And if any routing or LUT class still comes from a provisional file, stay provisional.
    if not stats:
        raise ValueError("no sample had a timing path (every one NOPATH): nothing measured, "
                         "delays.json left as it was")
    if old_prov and any(c in kept for c in ("mux_chan", "mux_ipin", "mux_xbar", "lut", "carry")):
        provisional = True
    return {"provisional": provisional,   # is in the next element's hop
            "source": source, "device": B.DEVICE["name"],
            "ns": ns, "measured": stats, "kept_from_previous": kept}


def plan(n_per_class=200, seed=1):
    """A reproducible sample of hops of every class, for extract_delays.tcl."""
    rnd = random.Random(seed)
    lines = []
    by = {"mux_chan": [], "mux_ipin": [], "mux_xbar": []}
    for node, ins in MUX_INPUTS.items():
        for a in ins:
            by[_cls(node)].append((a, node))
    for el in B.ELEMENTS:
        p = el["pins"]
        by.setdefault("lut", []).extend((p[f"I[{j}]"], p["out0"]) for j in range(B.LUT_K))
        by.setdefault("carry", []).append((p["cin"], p["cout"]))
    for cls, pairs in sorted(by.items()):
        for a, b in rnd.sample(pairs, min(n_per_class, len(pairs))):
            lines.append(f"{cls} {NET_OF[a]} {NET_OF[b]}")
    # the flip-flop's own timing: clock-to-Q onto its output wire, and input wire -> D
    for el in rnd.sample(list(B.ELEMENTS), min(n_per_class // 4 or 1, len(B.ELEMENTS))):
        cell = f"{PREFIX}u_clb_x{el['x']}y{el['y']}/u_e{el['e']}/q_reg"
        lines.append(f"ffq {cell} {NET_OF[el['pins']['out0']]}")
        lines.append(f"ffd {NET_OF[el['pins']['I[0]']]} {cell}")
    return lines


def ff_samples(text):
    """The ffq / ffd sections of an extract_delays.tcl report -> {"ff_clk_q": [...],
    "ffd": [...]} in ns: clock-to-Q plus the output wire, and input wire -> D plus setup."""
    out = {"ff_clk_q": [], "ffd": []}
    for sec in text.split("\n### ")[1:]:
        head, _, body = sec.partition("\n")
        f = head.split()
        if len(f) < 3 or f[-1] == "NOPATH" or f[0] not in ("ffq", "ffd"):
            continue
        nets = {}
        for line in body.splitlines():
            m = NET.match(line)
            if m:
                nets[m.group(3)] = float(m.group(2))
        if f[0] == "ffq":
            m = CELL_Q.search(body)
            if m and f[2] in nets:
                start = float(m.group(3)) - float(m.group(2))
                out["ff_clk_q"].append(round(nets[f[2]] - start, 3))
        else:
            m = re.search(r"^\s*(-?\d+\.\d+)\s+arrival time", body, re.M)
            su = SETUP.search(body)
            if m and f[1] in nets:
                setup = abs(float(su.group(2))) if su else 0.0
                out["ffd"].append(round(float(m.group(1)) - nets[f[1]] + setup, 3))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("-n", type=int, default=200, help="hops per class")
    p.add_argument("--seed", type=int, default=1)
    f = sub.add_parser("fold")
    f.add_argument("reports", nargs="+")
    f.add_argument("--provisional", action="store_true")
    f.add_argument("--out", default=OUT)
    a = ap.parse_args()
    if a.cmd == "plan":
        lines = plan(a.n, a.seed)
        with open(SAMPLES, "w") as fh:
            fh.write(f"# delays.py plan -n {a.n} --seed {a.seed}: class from-net to-net\n")
            fh.write("\n".join(lines) + "\n")
        print(f"{os.path.relpath(SAMPLES, ROOT)}: {len(lines)} hops")
        return 0
    texts = [open(r, errors="replace").read() for r in a.reports]
    src = ", ".join(os.path.relpath(os.path.abspath(r), ROOT) for r in a.reports)
    try:
        d = fold(texts, a.provisional, ("provisional: hops on the paths of " if a.provisional else "measured: ") + src)
    except ValueError as e:
        print(f"delays.py fold: {e}")
        return 1
    with open(a.out, "w") as fh:
        json.dump(d, fh, indent=1)
        fh.write("\n")
    for cls, s in d["measured"].items():
        print(f"  {cls:9s} n={s['n']:5d}  max {s['max']:.3f}  p95 {s['p95']:.3f}  median {s['median']:.3f} ns")
    if d["kept_from_previous"]:
        print(f"  kept from the previous file: {d['kept_from_previous']}")
    print(f"wrote {os.path.relpath(a.out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
