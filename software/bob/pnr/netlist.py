"""
netlist.py - the prepared netlist as atoms (M12a).

Reads the eblif text software/bob/vpr_run.py writes for VPR, so both flows start from
exactly the same netlist: constants already turned into pin constants, carry chains
cut to the column with generator/tap adders, buffer LUTs where a flip-flop's D is not
its own CLB's output.

  Atom(name, kind, pins)   kind: names | bob_add | bob_ff | bob_bram | bob_dsp
                           pins: {port pin name: net}, e.g. {"in[2]": "n12", "out": "n14"}
  Netlist.inputs / .outputs  top-level port nets (outputs: the net each output pad takes)
"""

from dataclasses import dataclass, field

INPUT_PORTS = {
    "names": None,                                   # in[k] inputs, out output
    "bob_add": {"a", "b", "cin"},
    "bob_ff": {"D", "CE", "SR", "C"},
}
OUTPUT_PORTS = {"bob_add": {"cout", "sumout"}, "bob_ff": {"Q"}}
CLOCK_PORTS = {("bob_ff", "C"), ("bob_bram", "clk"), ("bob_dsp", "clk")}


@dataclass
class Atom:
    name: str
    kind: str
    pins: dict = field(default_factory=dict)

    def is_output(self, pin):
        if self.kind == "names":
            return pin == "out"
        if self.kind in OUTPUT_PORTS:
            return pin in OUTPUT_PORTS[self.kind]
        base = pin.split("[")[0]
        return base in ("do_a", "do_b", "p", "pcout")          # bob_bram / bob_dsp outputs


@dataclass
class Netlist:
    top: str
    inputs: list
    outputs: list
    atoms: dict                      # name -> Atom

    def drivers(self):
        """net -> (atom name | 'in:<net>', pin)"""
        d = {net: (f"in:{net}", "inpad") for net in self.inputs}
        for a in self.atoms.values():
            for pin, net in a.pins.items():
                if a.is_output(pin):
                    d[net] = (a.name, pin)
        return d

    def sinks(self):
        """net -> [(atom name | 'out:<net>', pin)]"""
        s = {}
        for a in self.atoms.values():
            for pin, net in a.pins.items():
                if not a.is_output(pin):
                    s.setdefault(net, []).append((a.name, pin))
        for net in self.outputs:
            s.setdefault(net, []).append((f"out:{net}", "outpad"))
        return s


def parse_eblif(text, top):
    inputs, outputs, atoms = [], [], {}
    last = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        f = line.split()
        if f[0] == ".inputs":
            inputs = f[1:]
        elif f[0] == ".outputs":
            outputs = f[1:]
        elif f[0] == ".names":
            ins, out = f[1:-1], f[-1]
            pins = {f"in[{k}]": n for k, n in enumerate(ins)}
            pins["out"] = out
            last = Atom(out, "names", pins)                   # VPR names a LUT after its output net
            atoms[out] = last
        elif f[0] == ".subckt":
            pins = dict(t.split("=", 1) for t in f[2:])
            last = Atom(None, f[1], pins)
        elif f[0] == ".cname":
            last.name = f[1]
            atoms[f[1]] = last
        elif f[0] in (".model", ".end"):
            continue
        # anything else is a LUT cover line
    return Netlist(top, inputs, outputs, atoms)
