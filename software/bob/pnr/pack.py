"""
pack.py - atoms -> logic elements -> clusters (M12a; M21: a real cluster packer).

M21's CLB is N logic elements behind a full crossbar (software/bob/vpr_arch.py), so
packing has two steps, as in VPR:

  elements   pattern matching with the architecture's pack patterns:
               lut    a .names LUT; the flip-flop its output feeds alone joins it (ble)
               arith  a bob_add; the flip-flop its sum feeds alone joins it (chain);
                      M24 Double Duty: a -> in[K-2], b -> in[K-1], cin/cout on the carry,
                      and a LUT of at most K-2 inputs beside it (in[0..K-3] -> out[1])
               frac   two LUTs of at most K-1 inputs whose inputs together are at most
                      K-1 (the fractured LUT: O6 and O5 over the shared inputs), each
                      with its flip-flop (the second one registers O5)
  clusters   greedy and connectivity-driven, after VPR's AAPack (Marquardt, Betz &
             Rose's T-VPack, FPGA 1999, as VPR 8's packer grew it): a carry chain fills
             consecutive elements from element 0, continuing in the CLB above; every
             other CLB starts from the most connected unpacked element (the seed) and
             takes the element sharing the most nets with it (the attraction) while
             the CLB stays legal: at most N elements, at most I distinct input nets
             from outside, one CE net and one SR net (the CLB's pins, shared by every
             flip-flop).

The crossbar is full, so which CLB input pin a net enters on is free: the router picks
it (every I pin of a CLB is one equivalent sink), and an element reads a net made
inside its own CLB through the crossbar's feedback, without routing.

  Cluster.elems   element e -> Elem (or None);  Cluster.pins: tile pin -> net for the
                  pins that are fixed (O[m], ce[0], sr[0], cin[0], cout[0], hard
                  blocks, pads);  Cluster.inputs: the nets the CLB needs from outside,
                  each on the I pin the router chose (in_pin)
Nets that only reach clock pins are global (not routed: the user clock is global in
bob); cout -> cin nets between CLBs are directs (wires, no routing).
"""

from dataclasses import dataclass, field
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "host"))

import bitstream as B  # noqa: E402


class PackError(Exception):
    pass


@dataclass
class Elem:
    mode: str                                   # lut | frac | arith
    luts: list = field(default_factory=list)    # lut: [atom]; frac: [O6 atom, O5 atom]
    add: object = None
    ffs: list = field(default_factory=lambda: [None, None])   # FF on out[0], on out[1]
    ins: list = field(default_factory=list)     # element input j -> net (None: open)
    outs: list = field(default_factory=lambda: [None, None])  # out[0], out[1] -> net

    def ctl(self, pin):
        return {ff.pins[pin] for ff in self.ffs if ff and pin in ff.pins}


@dataclass
class Cluster:
    name: str
    type: str                                   # clb | bram | dsp | io
    mode: str = None                            # io: inpad | outpad
    atoms: dict = field(default_factory=dict)   # hard blocks: prim -> Atom
    pins: dict = field(default_factory=dict)    # tile pin -> net (fixed pins)
    elems: list = field(default_factory=list)   # clb: element e -> Elem or None
    inputs: set = field(default_factory=set)    # clb: nets needed from outside
    in_pin: dict = field(default_factory=dict)  # clb: net -> I pin index (chosen by the router)


@dataclass
class Packed:
    clusters: dict                              # name -> Cluster
    macros: list                                # [[cluster name, ...] bottom to top]
    nets: dict                                  # routed net -> {"driver": (cluster, pin), "sinks": [(cluster, pin)]}
    global_nets: set
    direct_nets: set


def _idx(pin):
    return pin if "[" in pin else f"{pin}[0]"


def lut_ins(a):
    ins, k = [], 0
    while f"in[{k}]" in a.pins:
        ins.append(a.pins[f"in[{k}]"])
        k += 1
    return ins


def elements(nl):
    """-> ([Elem] of the logic, [chain: [Elem] bottom to top])"""
    sinks = nl.sinks()
    ff_of_d = {a.pins["D"]: a for a in nl.atoms.values() if a.kind == "bob_ff"}
    used = set()
    K = B.LUT_K

    def absorb(net):
        ff = ff_of_d.get(net)
        if ff is None or len(sinks.get(net, [])) != 1 or ff.name in used:
            return None
        used.add(ff.name)
        return ff

    luts, adds = [], {}
    for a in sorted(nl.atoms.values(), key=lambda a: a.name):
        if a.kind == "names":
            luts.append((a, absorb(a.pins["out"])))
        elif a.kind == "bob_add":
            el = Elem("arith", add=a)
            el.ins = [None] * (K - 2) + [a.pins.get("a"), a.pins.get("b")]      # M24: dd, A/B on K-2/K-1
            ff = absorb(a.pins["sumout"]) if "sumout" in a.pins else None
            el.ffs[0] = ff
            el.outs[0] = ff.pins["Q"] if ff else a.pins.get("sumout")
            adds[a.name] = el
    left = [a.name for a in nl.atoms.values() if a.kind == "bob_ff" and a.name not in used]
    if left:
        raise PackError(f"flip-flops without a LUT/adder to pack with: {left[:3]}")

    # carry chains, bottom to top
    by_cin = {el.add.pins["cin"]: el for el in adds.values() if "cin" in el.add.pins}
    chains = []
    for el in sorted(adds.values(), key=lambda e: e.add.name):
        if "cin" in el.add.pins:
            continue
        chain = [el]
        while chain[-1].add.pins.get("cout") in by_cin:
            chain.append(by_cin[chain[-1].add.pins["cout"]])
        chains.append(chain)
    if sum(len(c) for c in chains) != len(adds):
        raise PackError("adders whose carry-in comes from nowhere")

    # M24 Double Duty: an adder element's LUT is free (the adder reads in[K-2], in[K-1]
    # directly), so each takes a LUT of at most K-2 inputs on in[0..K-3] -> out[1], the one
    # sharing the most nets with its chain. VPR's packer cannot aim for this (it cannot say
    # "this LUT only beside an adder"); here it is a direct choice. A LUT whose flip-flop
    # would disagree with the adder's on CE or SR stays out (one CE and SR per CLB).
    tiny = sorted(((a, ff) for a, ff in luts if len(lut_ins(a)) <= K - 2), key=lambda t: t[0].name)
    taken = set()
    for chain in chains:
        chain_nets = set()
        for el in chain:
            chain_nets |= {n for n in el.ins + el.outs if n}
        for el in chain:
            best = None
            for a, ff in tiny:
                if a.name in taken:
                    continue
                if ff is not None and el.ffs[0] is not None and any(
                        ff.pins.get(p) != el.ffs[0].pins.get(p) for p in ("CE", "SR")):
                    continue
                ins = lut_ins(a)
                key = (len(set(ins) & chain_nets) + (a.pins["out"] in chain_nets), -len(ins), a.name)
                if best is None or key[:2] > best[0][:2]:
                    best = (key, a, ff)
            if best is None:
                continue
            _key, a, ff = best
            taken.add(a.name)
            ins = lut_ins(a)
            el.luts = [a]
            el.ins = ins + [None] * (K - 2 - len(ins)) + el.ins[K - 2:]
            el.ffs[1] = ff
            el.outs[1] = ff.pins["Q"] if ff else a.pins["out"]
            chain_nets |= {n for n in ins if n} | {el.outs[1]}
    luts = [(a, ff) for a, ff in luts if a.name not in taken]

    # fracturable pairs: two LUTs of <= K-1 inputs sharing inputs, together <= K-1
    small = sorted(((a, ff) for a, ff in luts if len(lut_ins(a)) <= K - 1),
                   key=lambda t: (-len(lut_ins(t[0])), t[0].name))
    paired, elems = set(), []
    for i, (a, fa) in enumerate(small):
        if a.name in paired:
            continue
        sa = set(lut_ins(a))
        best, best_score = None, None
        for b, fb in small[i + 1:]:
            if b.name in paired:
                continue
            sb = set(lut_ins(b))
            u = sa | sb
            if len(u) > K - 1:
                continue
            shared = len(sa & sb)
            if shared == 0 and len(u) > 2:            # unrelated LUTs only when tiny (buffers)
                continue
            score = (2 * shared - len(u), b.name)
            if best_score is None or score[0] > best_score[0]:
                best, best_score = (b, fb), score
        if best is None:
            continue
        b, fb = best
        paired |= {a.name, b.name}
        el = Elem("frac", luts=[a, b])
        union = sorted(set(lut_ins(a)) | set(lut_ins(b)))
        el.ins = union + [None] * (K - len(union))
        el.ffs = [fa, fb]
        el.outs = [fa.pins["Q"] if fa else a.pins["out"], fb.pins["Q"] if fb else b.pins["out"]]
        elems.append(el)
    for a, ff in luts:
        if a.name in paired:
            continue
        el = Elem("lut", luts=[a])
        ins = lut_ins(a)
        el.ins = ins + [None] * (K - len(ins))
        el.ffs = [ff, None]
        el.outs = [ff.pins["Q"] if ff else a.pins["out"], None]
        elems.append(el)
    return elems, chains


class _Clb:
    """a CLB being filled: its elements and what that costs in pins"""

    def __init__(self, n):
        self.el = [None] * n
        self.made = set()                   # nets an element of this CLB produces
        self.need = set()                   # nets its elements read
        self.ce, self.sr = set(), set()
        self.name = None

    def ext(self, made=None, need=None):
        made = self.made if made is None else made
        need = self.need if need is None else need
        return need - made

    def fits(self, el):
        if len(self.ce | el.ctl("CE")) > 1 or len(self.sr | el.ctl("SR")) > 1:
            return False
        made = self.made | {n for n in el.outs if n}
        need = self.need | {n for n in el.ins if n}
        return len(self.ext(made, need)) <= B.CLB_I

    def put(self, e, el):
        self.el[e] = el
        self.made |= {n for n in el.outs if n}
        self.need |= {n for n in el.ins if n}
        self.ce |= el.ctl("CE")
        self.sr |= el.ctl("SR")


def pack(nl):
    N = B.CLB_N
    if B.CLUSTER["xbar"] != "full":
        raise PackError("bob's packer assumes a full crossbar (device.json cluster.xbar); use VPR")
    elems, chains = elements(nl)
    clbs, macros = [], []

    # carry chains: consecutive elements from element 0, on up the column
    for chain in chains:
        m = []
        for k in range(0, len(chain), N):
            c = _Clb(N)
            for e, el in enumerate(chain[k:k + N]):
                if not c.fits(el):
                    raise PackError("a carry chain needs more CLB inputs or CE/SR nets than a CLB has")
                c.put(e, el)
            clbs.append(c)
            m.append(len(clbs) - 1)
        macros.append(m)

    # everything else: seed + attraction
    pool = list(elems)
    nets_of = {id(el): {n for n in el.ins + el.outs if n} for el in pool}
    fanout = {}
    for el in pool:
        for n in nets_of[id(el)]:
            fanout[n] = fanout.get(n, 0) + 1

    def attraction(c, el):
        return sum(1 for n in nets_of[id(el)] if n in c.made or n in c.need)

    # a design that would fill most of the device is packed densely: once nothing related is
    # left, a CLB takes unrelated elements too (VPR's packer does the same when the device
    # is tight); a small one keeps its CLBs to related logic, which routes better
    have = len(B.CLBS)
    need = len(clbs) + -(-len(pool) // N)
    dense = need > 0.7 * have

    def fill(c):
        while None in c.el and pool:
            best = None
            for el in sorted(pool, key=lambda el: (-attraction(c, el), el.outs[0] or el.outs[1] or "")):
                if attraction(c, el) == 0 and not dense:
                    break                               # nothing related left: close the CLB
                if c.fits(el):
                    best = el
                    break
            if best is None:
                return
            c.put(c.el.index(None), best)
            pool.remove(best)

    for c in clbs:                                      # top up the chains' CLBs first
        fill(c)
    while pool:
        seed = max(pool, key=lambda el: (sum(fanout[n] for n in nets_of[id(el)]),
                                         el.outs[0] or el.outs[1] or ""))
        c = _Clb(N)
        if not c.fits(seed):
            raise PackError(f"element {seed.outs} alone needs more than a CLB offers")
        c.put(0, seed)
        pool.remove(seed)
        fill(c)
        clbs.append(c)

    # clusters
    clusters = {}
    for i, c in enumerate(clbs):
        first = next(n for el in c.el if el for n in el.outs if n)
        cl = Cluster(f"{first}#clb{i}", "clb", None, elems=list(c.el))
        for e, el in enumerate(c.el):
            if el is None:
                continue
            for o in (0, 1):
                if el.outs[o]:
                    cl.pins[f"O[{2 * e + o}]"] = el.outs[o]
            if el.mode == "arith":
                if e == 0 and "cin" in el.add.pins:
                    cl.pins["cin[0]"] = el.add.pins["cin"]
                last = e == N - 1 or c.el[e + 1] is None or c.el[e + 1].mode != "arith"
                if last and e == N - 1 and "cout" in el.add.pins:
                    cl.pins["cout[0]"] = el.add.pins["cout"]
        if c.ce:
            cl.pins["ce[0]"] = next(iter(c.ce))
        if c.sr:
            cl.pins["sr[0]"] = next(iter(c.sr))
        cl.inputs = c.ext()
        clusters[cl.name] = cl
        c.name = cl.name
    macros = [[clbs[i].name for i in m] for m in macros]

    for a in nl.atoms.values():
        if a.kind in ("bob_bram", "bob_dsp"):
            cl = Cluster(a.name, a.kind[4:], None, {"prim": a})
            cl.pins = {_idx(p): n for p, n in a.pins.items()}
            clusters[cl.name] = cl
    for net in nl.inputs:
        clusters[net] = Cluster(net, "io", "inpad", pins={"inpad[0]": net})
    for net in nl.outputs:
        clusters[f"out:{net}"] = Cluster(f"out:{net}", "io", "outpad", pins={"outpad[0]": net})

    # nets between clusters: fixed pins, and each CLB's outside inputs on "I" (any I pin)
    drv, snk = {}, {}
    for cl in clusters.values():
        for pin, net in cl.pins.items():
            base = pin.split("[")[0]
            if base == "clk":                                  # global user clock, not routed
                continue
            if base in ("O", "cout", "inpad", "do_a", "do_b", "p", "pcout"):
                if net in drv:
                    raise PackError(f"net {net} has two drivers")
                drv[net] = (cl.name, pin)
            elif not (cl.type == "clb" and base == "cin"):
                snk.setdefault(net, []).append((cl.name, pin))
        for net in sorted(cl.inputs):
            snk.setdefault(net, []).append((cl.name, "I"))
    clock_nets = {a.pins[p] for a in nl.atoms.values() for p in ("C", "clk") if p in a.pins
                  and (a.kind, p) in {("bob_ff", "C"), ("bob_bram", "clk"), ("bob_dsp", "clk")}}
    # a carry net inside a CLB (element to element) is not a net between clusters
    inner_carry = {el.add.pins["cout"] for c in clbs for el in c.el
                   if el is not None and el.mode == "arith" and "cout" in el.add.pins}
    nets, global_nets, direct_nets = {}, set(), set()
    for net, (cl, pin) in drv.items():
        if pin.startswith("cout"):
            direct_nets.add(net)
            continue
        if net in clock_nets:
            global_nets.add(net)
            continue
        if snk.get(net):
            nets[net] = {"driver": (cl, pin), "sinks": snk[net]}
    for net in snk:
        if net not in drv and net not in clock_nets and net not in inner_carry:
            raise PackError(f"net {net} has sinks but no driver")
    for net in clock_nets:
        global_nets.add(net)
    for m in macros:                                   # a chain crosses CLBs on the carry direct
        for lo, hi in zip(m, m[1:]):
            if clusters[lo].pins.get("cout[0]") != clusters[hi].pins.get("cin[0]"):
                raise PackError(f"carry chain broken between {lo} and {hi}")
    return Packed(clusters, macros, nets, global_nets, direct_nets)
