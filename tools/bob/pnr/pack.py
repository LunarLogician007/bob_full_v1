"""
pack.py - atoms -> clusters (M12a).

bob's CLB holds one BLE, so packing is the pattern matching VPR does with the
architecture's pack patterns (tools/bob/vpr_arch.py):

  logic       a .names LUT; the flip-flop its output feeds alone joins it (pattern ble)
  arithmetic  a bob_add; the flip-flop its sum feeds alone joins it (pattern chain);
              a -> I[0], b -> I[1], cin/cout on the carry direct
  bram / dsp  one hard block per atom; io one pad per top-level port bit

The netlist rewrite guarantees every flip-flop's D is a single-load LUT or adder
output, so no flip-flop is left over. Carry chains become macros: the clusters of
one chain, bottom to top, placed as a unit up a CLB column.

Cluster.pins maps a tile pin ("I[2]", "ce[0]", "O[0]", "do_a[3]", "inpad[0]") to a net.
Nets that only reach clock pins are global (not routed: the user clock is global in
bob); cout -> cin nets are directs (wires, no routing).
"""

from dataclasses import dataclass, field


class PackError(Exception):
    pass


@dataclass
class Cluster:
    name: str
    type: str                               # clb | bram | dsp | io
    mode: str = None                        # clb: logic | arithmetic; io: inpad | outpad
    atoms: dict = field(default_factory=dict)   # role (lut | add | ff | prim) -> Atom
    pins: dict = field(default_factory=dict)    # tile pin -> net
    lut_inputs: list = field(default_factory=list)   # logic: the atom's input indices
    lut_pin: dict = field(default_factory=dict)      # logic: atom input k -> tile pin I[j] (chosen by the router)


@dataclass
class Packed:
    clusters: dict                          # name -> Cluster
    macros: list                            # [[cluster name, ...] bottom to top]
    nets: dict                              # routed net -> {"driver": (cluster, pin), "sinks": [(cluster, pin)]}
    global_nets: set
    direct_nets: set


def _idx(pin):
    return pin if "[" in pin else f"{pin}[0]"


def pack(nl):
    sinks = nl.sinks()
    ff_of_d = {}
    for a in nl.atoms.values():
        if a.kind == "bob_ff":
            ff_of_d[a.pins["D"]] = a

    clusters = {}
    used = set()

    def absorb(net):
        ff = ff_of_d.get(net)
        if ff is None or len(sinks.get(net, [])) != 1 or ff.name in used:
            return None
        used.add(ff.name)
        return ff

    def add_ff(cl, ff):
        cl.atoms["ff"] = ff
        for pin, tile in (("CE", "ce[0]"), ("SR", "sr[0]")):
            if pin in ff.pins:
                cl.pins[tile] = ff.pins[pin]
        cl.pins["O[0]"] = ff.pins["Q"]

    for a in sorted(nl.atoms.values(), key=lambda a: a.name):
        if a.kind == "bob_add":
            cl = Cluster(a.name, "clb", "arithmetic", {"add": a})
            for pin, tile in (("a", "I[0]"), ("b", "I[1]"), ("cin", "cin[0]"), ("cout", "cout[0]")):
                if pin in a.pins:
                    cl.pins[tile] = a.pins[pin]
            if "sumout" in a.pins:
                ff = absorb(a.pins["sumout"])
                if ff:
                    add_ff(cl, ff)
                else:
                    cl.pins["O[0]"] = a.pins["sumout"]
            clusters[cl.name] = cl
        elif a.kind == "names":
            cl = Cluster(a.name, "clb", "logic", {"lut": a})
            k = 0
            while f"in[{k}]" in a.pins:
                cl.pins[f"I[{k}]"] = a.pins[f"in[{k}]"]
                cl.lut_inputs.append(k)
                k += 1
            ff = absorb(a.pins["out"])
            if ff:
                add_ff(cl, ff)
            else:
                cl.pins["O[0]"] = a.pins["out"]
            clusters[cl.name] = cl
        elif a.kind in ("bob_bram", "bob_dsp"):
            cl = Cluster(a.name, a.kind[4:], None, {"prim": a})
            cl.pins = {_idx(p): n for p, n in a.pins.items()}
            clusters[cl.name] = cl
    left = [a.name for a in nl.atoms.values() if a.kind == "bob_ff" and a.name not in used]
    if left:
        raise PackError(f"flip-flops without a LUT/adder to pack with: {left[:3]}")
    for net in nl.inputs:
        clusters[net] = Cluster(net, "io", "inpad", pins={"inpad[0]": net})
    for net in nl.outputs:
        clusters[f"out:{net}"] = Cluster(f"out:{net}", "io", "outpad", pins={"outpad[0]": net})

    # nets between clusters
    drv, snk = {}, {}
    for cl in clusters.values():
        for pin, net in cl.pins.items():
            base = pin.split("[")[0]
            if base == "clk":                                  # global user clock, not routed
                continue
            is_out = base in ("O", "cout", "inpad", "do_a", "do_b", "p", "pcout")
            if is_out:
                if net in drv:
                    raise PackError(f"net {net} has two drivers")
                drv[net] = (cl.name, pin)
            else:
                snk.setdefault(net, []).append((cl.name, pin))
    clock_nets = {a.pins[p] for a in nl.atoms.values() for p in ("C", "clk") if p in a.pins
                  and (a.kind, p) in {("bob_ff", "C"), ("bob_bram", "clk"), ("bob_dsp", "clk")}}
    nets, global_nets, direct_nets = {}, set(), set()
    for net, (cl, pin) in drv.items():
        ss = snk.get(net, [])
        if pin.startswith("cout"):
            if any(not p.startswith("cin") for _c, p in ss):
                raise PackError(f"carry net {net} reaches a routed pin")
            direct_nets.add(net)
            continue
        if net in clock_nets:
            global_nets.add(net)
            if ss:
                raise PackError(f"clock net {net} also drives logic")
            continue
        if ss:
            nets[net] = {"driver": (cl, pin), "sinks": ss}
    for net in snk:
        if net not in drv and net not in clock_nets:
            raise PackError(f"net {net} has sinks but no driver")
    for net in clock_nets:
        global_nets.add(net)

    # carry macros
    cout_to = {}
    for cl in clusters.values():
        if cl.mode == "arithmetic" and "cin[0]" in cl.pins:
            cout_to[cl.pins["cin[0]"]] = cl.name
    macros = []
    for cl in sorted(clusters.values(), key=lambda c: c.name):
        if cl.mode != "arithmetic" or "cin[0]" in cl.pins:
            continue
        chain = [cl.name]
        while "cout[0]" in clusters[chain[-1]].pins and clusters[chain[-1]].pins["cout[0]"] in cout_to:
            chain.append(cout_to[clusters[chain[-1]].pins["cout[0]"]])
        macros.append(chain)
    in_macro = {c for m in macros for c in m}
    orphans = [c.name for c in clusters.values() if c.mode == "arithmetic" and c.name not in in_macro]
    if orphans:
        raise PackError(f"adders whose carry-in comes from nowhere: {orphans[:3]}")
    return Packed(clusters, macros, nets, global_nets, direct_nets)
