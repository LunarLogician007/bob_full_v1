#!/usr/bin/env python3
"""
run.py - Python pack/place/route of an example (M12a).

  software/bob/pnr/run.py counter [--seed N] [--pcf pins.pcf] [--name NAME]   -> build/pnr/<name>/

Same input as VPR (software/bob/vpr_run.prepare: the eblif and the fixed pins), same
output files as VPR (.net .place .route + <name>.vpr.json), so
software/bob/fasm_from_vpr.py turns either into FASM and chain bits. No Docker.
If routing does not converge, placement is retried with the next seeds.
"""

import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BOB = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(BOB))
sys.path.insert(0, BOB)
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402
import vpr_run  # noqa: E402
from pnr import netlist, pack, place, route, write  # noqa: E402

RESULTS = os.path.join(ROOT, "build", "pnr")
BLOCK_AT = {(b["x"], b["y"]): b["name"] for b in B.DEVICE["blocks"]}


def block_name(placement, cluster):
    return BLOCK_AT[placement.pos[cluster]]


def run(top, seed=1, pcf=None, name=None, work=None, tries=5, log=None):
    """-> (work directory, stats)"""
    name = name or top
    work = work or os.path.join(RESULTS, name)
    eblif, side, fixed = vpr_run.prepare(top, pcf)
    t0 = time.time()
    nl = netlist.parse_eblif(eblif, top)
    packed = pack.pack(nl)
    t_pack = time.time() - t0
    last = None
    for s in range(seed, seed + tries):
        t1 = time.time()
        pl = place.Placement(packed, fixed, s)
        pstats = pl.anneal()
        t_place = time.time() - t1
        nets, sink_of = {}, {}
        for net, n in packed.nets.items():
            dc, dp = n["driver"]
            src = route.pin_node(block_name(pl, dc), dp)
            sinks, keys = [], []
            for c, p in sorted(set(n["sinks"])):
                blk = block_name(pl, c)
                if p == "I":
                    # M21: behind a full crossbar every CLB input pin is equivalent
                    sinks.append(tuple(route.pin_node(blk, f"I[{j}]") for j in range(B.CLB_I)))
                else:
                    sinks.append(route.pin_node(blk, p))
                keys.append((c, p))
            nets[net] = (src, sinks)
            sink_of[net] = keys
        t2 = time.time()
        try:
            routed, rstats = route.route(nets, log=log)
        except route.RouteError as e:
            last = e
            if log:
                log(f"  seed {s}: {e}; retrying placement")
            continue
        t_route = time.time() - t2
        node_pin = {v: k for k, v in B.PIN.items()}
        for net, paths in routed.items():
            for (c, p), path in zip(sink_of[net], paths):
                if p == "I":
                    packed.clusters[c].in_pin[net] = int(node_pin[path[-1]].rsplit("I[", 1)[1][:-1])
        break
    else:
        raise route.RouteError(f"{name}: no routable placement in {tries} seeds ({last})")

    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    open(os.path.join(work, f"{name}.eblif"), "w").write(eblif)
    write.write_net(os.path.join(work, f"{name}.net"), name, packed)
    write.write_place(os.path.join(work, f"{name}.place"), name, pl)
    write.write_route(os.path.join(work, f"{name}.route"), routed, packed.global_nets)
    stats = {"seed": s, "clusters": {t: sum(1 for c in packed.clusters.values() if c.type == t)
                                     for t in ("clb", "bram", "dsp", "io")},
             "macros": [len(m) for m in packed.macros], "routed_nets": len(nets),
             "pack_s": round(t_pack, 3), "place_s": round(t_place, 3), "route_s": round(t_route, 3),
             **pstats, **rstats}
    side["pins"] = fixed
    side["pcf"] = os.path.relpath(pcf, ROOT) if pcf else None
    side["pnr"] = stats
    json.dump(side, open(os.path.join(work, f"{name}.vpr.json"), "w"), indent=0)
    return work, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tops", nargs="*")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    fails = 0
    for name in args.tops or vpr_run.EXAMPLES + list(vpr_run.VARIANTS):
        top, pcf = vpr_run.VARIANTS.get(name, (name, None))
        try:
            work, st = run(top, args.seed, pcf, name, log=print if args.verbose else None)
        except (vpr_run.VprError, pack.PackError, place.PlaceError, route.RouteError) as e:
            print(f"FAIL  {name}: {e}")
            fails += 1
            continue
        print(f"PASS  {name}: {st['clusters']['clb']} CLBs, bb cost {st['bb_cost']}, "
              f"{st['iterations']} routing iteration(s), wirelength {st['wirelength']} "
              f"({st['wire_nodes']} wires), place {st['place_s']} s, route {st['route_s']} s, "
              f"seed {st['seed']} -> {os.path.relpath(work, ROOT)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
