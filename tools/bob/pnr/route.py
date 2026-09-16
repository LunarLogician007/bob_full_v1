"""
route.py - PathFinder routing on the committed rr graph (M12a).

McMurchie & Ebeling, "PathFinder: A Negotiation-Based Performance-Driven Router for
FPGAs" (FPGA 1995), as VPR's router uses it:

  every node has capacity 1 (a mux selects one driver)
  a sink may be a set of equivalent IPINs (a LUT's inputs are permutable, as VPR's
  lut_in port_class): the path ends on whichever is cheapest, the pins negotiate
  like any other node, and the caller re-indexes the LUT table from the choice
  cost(n) = base(n) x (1 + hist(n)) x (1 + pres_fac x overuse(n) if taken)
  each iteration rips up and reroutes every net: A* from the net's whole routing tree
  to each sink in turn (nearest first), heuristic = Manhattan distance / segment
  length; after the iteration hist += over-use, pres_fac *= 1.6
  done when no node is used by two nets

The graph is exactly the fabric's: a node's fan-in is its mux inputs (host/bitstream.py
MUX, from device.json). Only CHANX/CHANY nodes are expanded through; an IPIN is only
ever a target; directs (carry, DSP cascade) are wires and are not routed.
"""

import heapq
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "host"))

import bitstream as B  # noqa: E402


class RouteError(Exception):
    pass


SEG = B.DEVICE["arch"]["segment_length"]
BASE = {"CHANX": 1.0, "CHANY": 1.0, "IPIN": 0.95}


def _xy(node):
    n = B.NODE[node]
    return (n[2] + n[4]) / 2.0, (n[3] + n[5]) / 2.0


def _dist(node, target_xy):
    n = B.NODE[node]
    tx, ty = target_xy
    dx = max(n[2] - tx, 0, tx - n[4])
    dy = max(n[3] - ty, 0, ty - n[5])
    return dx + dy


def pin_node(block, pin):
    key = f"{block}.{pin}"
    if key not in B.PIN:
        raise RouteError(f"no rr node for pin {key}")
    return B.PIN[key]


def route(nets, max_iters=60, log=None):
    """nets: {name: (source OPIN node, [sinks])}; a sink is an IPIN node or a tuple of
    equivalent IPIN nodes. -> ({name: [[path nodes], ...]}, stats). Each path runs from a
    node already in the tree (the source for the first) to the IPIN it reached; paths
    are in the order of the sinks given."""
    for name, (src, sinks) in nets.items():
        if B.NODE[src][1] != "OPIN":
            raise RouteError(f"net {name}: source {src} is not an OPIN")
        for s in sinks:
            for n in (s if isinstance(s, tuple) else (s,)):
                if B.NODE[n][1] != "IPIN" or n not in B.MUX:
                    raise RouteError(f"net {name}: sink {n} is not a routable IPIN")
    hist = {}
    pres_fac = 0.5
    order = sorted(nets, key=lambda n: (-len(nets[n][1]), n))
    occ = {}
    result = {}
    for it in range(1, max_iters + 1):
        occ = {}
        result = {}
        for name in order:
            src, sinks = nets[name]
            tree = {src}
            paths = [None] * len(sinks)
            order_s = sorted(range(len(sinks)), key=lambda i: (_dist(src, _xy(_first(sinks[i]))), i))
            for i in order_s:
                targets = sinks[i] if isinstance(sinks[i], tuple) else (sinks[i],)
                path = _astar(tree, targets, occ, hist, pres_fac)
                if path is None:
                    raise RouteError(f"net {name}: sink {targets} unreachable from its tree")
                paths[i] = path
                tree.update(path)
            for n in tree:
                if n != src:
                    occ[n] = occ.get(n, 0) + 1
            result[name] = paths
        over = {n: c - 1 for n, c in occ.items() if c > 1}
        if log:
            log(f"    iteration {it}: {len(over)} overused nodes")
        if not over:
            wires = sum(1 for n in occ if B.NODE[n][1] in ("CHANX", "CHANY"))
            wl = sum(B.NODE[n][4] - B.NODE[n][2] + B.NODE[n][5] - B.NODE[n][3] + 1
                     for n in occ if B.NODE[n][1] in ("CHANX", "CHANY"))
            return result, {"iterations": it, "wire_nodes": wires, "wirelength": wl,
                            "ipins": sum(1 for n in occ if B.NODE[n][1] == "IPIN")}
        for n, o in over.items():
            hist[n] = hist.get(n, 0.0) + o
        pres_fac *= 1.6
    raise RouteError(f"congestion not resolved after {max_iters} iterations ({len(over)} nodes overused)")


def _first(s):
    return s[0] if isinstance(s, tuple) else s


def _astar(tree, targets, occ, hist, pres_fac):
    target = _xy(targets[0])
    goal = set(targets)
    heap, best, prev = [], {}, {}
    for t in tree:
        best[t] = 0.0
        prev[t] = None
        heapq.heappush(heap, (_dist(t, target) / SEG, 0.0, t))
    while heap:
        _f, g, n = heapq.heappop(heap)
        if n in goal:
            path = [n]
            while prev[path[-1]] is not None:
                path.append(prev[path[-1]])
            return list(reversed(path))
        if g > best.get(n, float("inf")):
            continue
        for m in B.FANOUT.get(n, ()):
            kind = B.NODE[m][1]
            if kind == "IPIN" and m not in goal:
                continue
            if kind not in ("CHANX", "CHANY", "IPIN"):
                continue
            c = BASE[kind] * (1.0 + hist.get(m, 0.0)) * (1.0 + pres_fac * occ.get(m, 0))
            ng = g + c
            if ng < best.get(m, float("inf")):
                best[m] = ng
                prev[m] = n
                heapq.heappush(heap, (ng + _dist(m, target) / SEG, ng, m))
    return None
