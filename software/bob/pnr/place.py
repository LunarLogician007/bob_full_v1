"""
place.py - simulated-annealing placement (M12a), after VPR's placer (Betz & Rose,
"VPR: A New Packing, Placement and Routing Tool for FPGA Research", FPL 1997).

  cost        sum over routed nets of the half-perimeter of the bounding box of the
              net's blocks (pads at their ring position, tall blocks at their root)
  moves       a single CLB to a random CLB site within the range limit (swap if
              occupied by another single); a carry macro to another column/offset
              (singles in the way take the macro's freed sites); BRAM/DSP between
              their column sites. Pads are fixed by the pins.
  schedule    T0 = 20 x std-dev of the cost of random moves; 10 * N^(4/3) moves per
              temperature; alpha from the acceptance rate (0.5 / 0.9 / 0.95 / 0.8);
              range limit scaled by (1 - 0.44 + rate); stop when
              T < 0.005 * cost / nets.
Deterministic for a seed.
"""

import math
import random
import sys
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "host"))

import bitstream as B  # noqa: E402


class PlaceError(Exception):
    pass


CLB_SITES = sorted(B.CLB_AT, key=lambda xy: (xy[0], xy[1]))
CLB_COLS = sorted({x for x, _y in CLB_SITES})
ROWS = sorted({y for _x, y in CLB_SITES})
HARD_SITES = {t: sorted((b["x"], b["y"]) for b in B.DEVICE["blocks"] if b["type"] == t) for t in ("bram", "dsp")}
GRID = max(B.DEVICE["arch"]["grid_width"], B.DEVICE["arch"]["grid_height"])


class Placement:
    def __init__(self, packed, fixed, seed=1):
        """fixed: {io cluster name: pad number}"""
        self.p = packed
        self.rng = random.Random(seed)
        self.pos = {}
        for name, cl in packed.clusters.items():
            if cl.type == "io":
                if name not in fixed:
                    raise PlaceError(f"pad {name} has no fixed position")
                self.pos[name] = B.PAD_XY[fixed[name]]
        self.macro_of = {c: i for i, m in enumerate(packed.macros) for c in m}
        self.singles = sorted(n for n, c in packed.clusters.items() if c.type == "clb" and n not in self.macro_of)
        self.hard = {t: sorted(n for n, c in packed.clusters.items() if c.type == t) for t in ("bram", "dsp")}
        need = len(self.singles) + sum(len(m) for m in packed.macros)
        if need > len(CLB_SITES):
            raise PlaceError(f"{need} CLBs needed, the device has {len(CLB_SITES)}")
        for t in ("bram", "dsp"):
            if len(self.hard[t]) > len(HARD_SITES[t]):
                raise PlaceError(f"{len(self.hard[t])} {t} blocks needed, the device has {len(HARD_SITES[t])}")
        if any(len(m) > len(ROWS) for m in packed.macros):
            raise PlaceError("a carry chain is longer than a CLB column")
        self.nets_of = {}
        self.net_blocks = {}
        for net, n in packed.nets.items():
            blocks = sorted({n["driver"][0]} | {c for c, _p in n["sinks"]})
            self.net_blocks[net] = blocks
            for b in blocks:
                self.nets_of.setdefault(b, []).append(net)
        self._initial()

    # --- state ---------------------------------------------------------------------
    def _initial(self):
        self.occ = {xy: None for xy in CLB_SITES}
        for i, m in sorted(enumerate(self.p.macros), key=lambda im: -len(im[1])):
            windows = [(x, y0) for x in CLB_COLS for y0 in ROWS[:len(ROWS) - len(m) + 1]
                       if all(self.occ[(x, y0 + k)] is None for k in range(len(m)))]
            if not windows:
                raise PlaceError("no free column window for a carry chain")
            x, y0 = self.rng.choice(windows)
            for k, c in enumerate(m):
                self.pos[c] = (x, y0 + k)
                self.occ[(x, y0 + k)] = c
        free = [xy for xy in CLB_SITES if self.occ[xy] is None]
        self.rng.shuffle(free)
        for c, xy in zip(self.singles, free):
            self.pos[c] = xy
            self.occ[xy] = c
        self.hocc = {}
        for t in ("bram", "dsp"):
            sites = list(HARD_SITES[t])
            self.rng.shuffle(sites)
            for c, xy in zip(self.hard[t], sites):
                self.pos[c] = xy
            for xy in HARD_SITES[t]:
                self.hocc[xy] = next((c for c in self.hard[t] if self.pos[c] == xy), None)
        self.net_cost = {n: self._bb(n) for n in self.net_blocks}
        self.cost = sum(self.net_cost.values())

    def _bb(self, net):
        xs = [self.pos[b][0] for b in self.net_blocks[net]]
        ys = [self.pos[b][1] for b in self.net_blocks[net]]
        return (max(xs) - min(xs)) + (max(ys) - min(ys))

    # --- moves: return a list of (cluster, new xy) or None ----------------------------------
    def _propose(self, rlim):
        units = self.singles + [f"#m{i}" for i in range(len(self.p.macros))] + self.hard["bram"] + self.hard["dsp"]
        u = self.rng.choice(units)
        if u.startswith("#m"):
            m = self.p.macros[int(u[2:])]
            x0, y0 = self.pos[m[0]]
            cols = [x for x in CLB_COLS if abs(x - x0) <= rlim]
            x = self.rng.choice(cols)
            y = self.rng.choice(ROWS[:len(ROWS) - len(m) + 1])
            if (x, y) == (x0, y0):
                return None
            window = [(x, y + k) for k in range(len(m))]
            if any(self.occ[xy] is not None and self.occ[xy] not in m and self.occ[xy] in self.macro_of
                   for xy in window):
                return None
            displaced = [self.occ[xy] for xy in window if self.occ[xy] is not None and self.occ[xy] not in m]
            freed = [self.pos[c] for c in m if self.pos[c] not in window]
            moves = [(c, xy) for c, xy in zip(m, window)]
            moves += list(zip(displaced, freed))
            return moves
        c = u
        t = self.p.clusters[c].type
        x0, y0 = self.pos[c]
        if t in ("bram", "dsp"):
            other = [xy for xy in HARD_SITES[t] if xy != (x0, y0)]
            if not other:
                return None
            xy = self.rng.choice(other)
            o = self.hocc[xy]
            return [(c, xy)] + ([(o, (x0, y0))] if o else [])
        cand = [xy for xy in CLB_SITES if xy != (x0, y0) and abs(xy[0] - x0) <= rlim and abs(xy[1] - y0) <= rlim]
        if not cand:
            return None
        xy = self.rng.choice(cand)
        o = self.occ[xy]
        if o is not None and o in self.macro_of:
            return None
        return [(c, xy)] + ([(o, (x0, y0))] if o else [])

    def _apply(self, moves):
        for c, _xy in moves:
            if self.p.clusters[c].type == "clb":
                if self.occ.get(self.pos[c]) == c:
                    self.occ[self.pos[c]] = None
            else:
                if self.hocc.get(self.pos[c]) == c:
                    self.hocc[self.pos[c]] = None
        for c, xy in moves:
            self.pos[c] = xy
            if self.p.clusters[c].type == "clb":
                self.occ[xy] = c
            else:
                self.hocc[xy] = c

    def _delta(self, moves):
        nets = {n for c, _xy in moves for n in self.nets_of.get(c, ())}
        old = {c: self.pos[c] for c, _xy in moves}
        for c, xy in moves:
            self.pos[c] = xy
        new = {n: self._bb(n) for n in nets}
        for c, xy in old.items():
            self.pos[c] = xy
        return sum(new[n] - self.net_cost[n] for n in nets), new

    # --- anneal ---------------------------------------------------------------------------
    def anneal(self):
        movable = len(self.singles) + len(self.p.macros) + len(self.hard["bram"]) + len(self.hard["dsp"])
        nnets = max(1, len(self.net_blocks))
        if movable == 0 or not self.net_blocks:
            return self.stats(0, 0)
        rlim = float(GRID)
        samples = []
        for _ in range(max(20, movable)):
            mv = self._propose(rlim)
            if mv:
                d, new = self._delta(mv)
                samples.append(d)
        mean = sum(samples) / max(1, len(samples))
        std = math.sqrt(sum((s - mean) ** 2 for s in samples) / max(1, len(samples)))
        T = 20.0 * std if std > 0 else 1.0
        inner = max(100, int(10 * movable ** (4 / 3)))
        temps = moves_total = 0
        while True:
            accepted = 0
            for _ in range(inner):
                mv = self._propose(int(rlim))
                if not mv:
                    continue
                d, new = self._delta(mv)
                if d <= 0 or self.rng.random() < math.exp(-d / T):
                    self._apply(mv)
                    self.net_cost.update(new)
                    self.cost += d
                    accepted += 1
            moves_total += inner
            temps += 1
            rate = accepted / inner
            rlim = min(float(GRID), max(1.0, rlim * (1 - 0.44 + rate)))
            alpha = 0.5 if rate > 0.96 else 0.9 if rate > 0.8 else 0.95 if rate > 0.15 else 0.8
            T *= alpha
            if T < 0.005 * max(self.cost, 1) / nnets or temps > 400:
                break
        # greedy finish at T = 0
        for _ in range(inner):
            mv = self._propose(int(max(1, rlim)))
            if mv:
                d, new = self._delta(mv)
                if d < 0:
                    self._apply(mv)
                    self.net_cost.update(new)
                    self.cost += d
        self.cost = sum(self._bb(n) for n in self.net_blocks)
        self.check()
        return self.stats(temps, moves_total)

    def stats(self, temps, moves):
        return {"bb_cost": self.cost, "temperatures": temps, "moves": moves}

    def check(self):
        """legality: every CLB cluster on its own CLB site, macros contiguous up a column,
        hard blocks on their column sites, pads where fixed"""
        seen = {}
        for name, cl in self.p.clusters.items():
            xy = self.pos[name]
            if cl.type == "clb":
                if xy not in B.CLB_AT:
                    raise PlaceError(f"{name} at {xy} is not a CLB site")
            elif cl.type in ("bram", "dsp"):
                if xy not in HARD_SITES[cl.type]:
                    raise PlaceError(f"{name} at {xy} is not a {cl.type} site")
            if cl.type != "io":
                if xy in seen:
                    raise PlaceError(f"{name} and {seen[xy]} both at {xy}")
                seen[xy] = name
        for m in self.p.macros:
            x0, y0 = self.pos[m[0]]
            for k, c in enumerate(m):
                if self.pos[c] != (x0, y0 + k):
                    raise PlaceError(f"carry chain broken at {c}")
