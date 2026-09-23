#!/usr/bin/env python3
"""
place.py - pack and place a synthesised bob netlist onto the fabric (M8).

  software/bob/place.py counter [--check] [--seed N]

M8's "hand placement" helper: deliberately simple and deterministic, so that
M8 can prove synthesis on the board before VPR takes over packing, placement and
routing at M9. It reads build/synth/<top>/<top>.json (software/bob/synth.py), builds
a software/host/bitstream.py Design, and lets that router route it.

Packing (one element each; M21: a CLB is N elements, placed as element slots):
  BOB_ADD                      a CLB in carry mode, LUT = A ^ B (^1), I0 = A,
                               I1 = B; a BOB_FDRE/FDSE on its sum is absorbed when
                               the sum has no other load
  $lut -> FF                   one CLB when the LUT feeds only that FF; a LUT of at
                               most K-1 inputs with other loads too keeps them on O5
  $lut, FF alone               one CLB each (a lone FF gets a buffer LUT)
  carry chains                 run through the elements of a CLB column in carry
                               order (column(): e0..e<N-1> of each CLB, then the
                               carry direct to the CLB above). The first slot is a
                               carry-in generator (LUT 0, carry generate = I0 = CI):
                               the global USER1 cin never enters a design. A chain
                               longer than the column ends in a tap (sum = carry) and
                               continues from a generator in the next carry column.
  BOB_BRAM18 / BOB_DSP         bram0, bram1 / dsp0, dsp1

Placement: carry columns first, everything else on the free element slots column by
column, never putting two flip-flops with different CE or SR nets in one CLB (a CLB has
one CE and one SR pin); the Design router routes, through the crossbars. Board ports: clk (the user
clock), sw[1:0], btn[3:0] -> pad_i, led[2:0] -> LD2..0.

--check replays <top>.trace.json (software/bob/equiv.py: the SOURCE Verilog's outputs
under random inputs) through software/bob/model.py on the placed bitstream.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402
from bitstream import Cell, Const, Design, BramOut, DspOut  # noqa: E402

CLB_COLS = sorted({x for x, _y in B.CLB_AT})
ROWS = sorted({y for _x, y in B.CLB_AT})


def column(x):
    """M21: the element slots of CLB column x in carry order - every element of the bottom
    CLB (e0 .. e<N-1>), then the CLB above"""
    return [(x, y, e) for y in ROWS for e in range(B.CLB_N)]


class PlaceError(Exception):
    pass


def _param(cell, name, default=0):
    v = cell["parameters"].get(name)
    if v is None:
        return default
    if isinstance(v, str) and set(v) <= {"0", "1", "x", "z"}:
        return int(v.replace("x", "0").replace("z", "0"), 2)     # undefined bits read 0
    return int(v)


class Netlist:
    def __init__(self, mod):
        self.mod = mod
        self.cells = mod["cells"]
        self.driver = {}                      # bit -> ("port", name, i) | ("cell", cname, port, i)
        self.sinks = {}                       # bit -> [(cname, port, i)]
        for pname, p in mod["ports"].items():
            if p["direction"] == "input":
                for i, b in enumerate(p["bits"]):
                    self.driver[b] = ("port", pname, i)
        for cname, c in self.cells.items():
            for port, bits in c["connections"].items():
                d = c["port_directions"][port]
                for i, b in enumerate(bits):
                    if d == "output":
                        self.driver[b] = ("cell", cname, port, i)
                    elif not isinstance(b, str):
                        self.sinks.setdefault(b, []).append((cname, port, i))
        self.out_bits = {}
        for pname, p in mod["ports"].items():
            if p["direction"] == "output":
                for i, b in enumerate(p["bits"]):
                    self.out_bits.setdefault(b, []).append((pname, i))

    def bit(self, cname, port, i=0):
        return self.cells[cname]["connections"][port][i]

    def loads(self, b):
        """Every consumer of bit b: cell pins and output ports."""
        return len(self.sinks.get(b, [])) + len(self.out_bits.get(b, []))


def place(top, seed=0):
    path = os.path.join(ROOT, "build", "synth", top, f"{top}.json")
    mod = json.load(open(path))["modules"][top]
    nl = Netlist(mod)
    cells = nl.cells
    K = B.LUT_K
    d = Design()
    sig = {}                                  # bit -> Signal
    contents = {}                             # bram index -> list of words

    # --- clock and board ports ---------------------------------------------------
    clk_bits = set(mod["ports"]["clk"]["bits"]) if "clk" in mod["ports"] else set()
    for pname, p in mod["ports"].items():
        if pname == "clk":
            continue
        if p["direction"] == "input":
            base = {"sw": 0, "btn": 2}.get(pname)
            if base is None or len(p["bits"]) + base > {"sw": 2, "btn": 6}[pname]:
                raise PlaceError(f"input port {pname}: only sw[1:0], btn[3:0] and clk are board pins")
            for i, b in enumerate(p["bits"]):
                sig[b] = d.input(base + i)
        elif pname != "led" or len(p["bits"]) > 3:
            raise PlaceError(f"output port {pname}: only led[2:0] is a board pin")
    for cname, c in cells.items():
        port = {"BOB_FDRE": "C", "BOB_FDSE": "C", "BOB_BRAM18": "CLK"}.get(c["type"])
        if port and nl.bit(cname, port) not in clk_bits:
            raise PlaceError(f"{cname}: clocked by something other than the clk port")

    def S(b):
        if isinstance(b, str):
            return Const(1 if b == "1" else 0)            # "x" -> 0
        if b not in sig:
            raise PlaceError(f"net {b} has no placed driver")
        return sig[b]

    # --- packing ------------------------------------------------------------------
    ffs = {n for n, c in cells.items() if c["type"] in ("BOB_FDRE", "BOB_FDSE")}
    adds = {n for n, c in cells.items() if c["type"] == "BOB_ADD"}
    luts = {n for n, c in cells.items() if c["type"] == "$lut"}
    ff_of_d = {}
    for f in ffs:
        ff_of_d.setdefault(nl.bit(f, "D"), []).append(f)

    clusters = {}                             # name -> dict(kind, main, ff, o5)
    absorbed = set()

    def absorb_ff(out_bit, allow_o5):
        cand = ff_of_d.get(out_bit, [])
        free = [f for f in cand if f not in absorbed]
        if not free:
            return None, False
        others = nl.loads(out_bit) - 1
        if others == 0:
            absorbed.add(free[0])
            return free[0], False
        if allow_o5:
            absorbed.add(free[0])
            return free[0], True
        return None, False

    # carry chains
    ci_from = {}
    for a in adds:
        drv = nl.driver.get(nl.bit(a, "CI"))
        if drv and drv[0] == "cell" and cells[drv[1]]["type"] == "BOB_ADD" and drv[2] == "CO":
            ci_from[a] = drv[1]
    nxt = {v: k for k, v in ci_from.items()}
    chains = []
    for a in sorted(adds):
        if a in ci_from:
            continue
        chain = [a]
        while chain[-1] in nxt:
            chain.append(nxt[chain[-1]])
        chains.append(chain)
    for chain in chains:
        for i, a in enumerate(chain):
            co = nl.bit(a, "CO")
            internal = 1 if i + 1 < len(chain) else 0
            if nl.loads(co) - internal > 0 and i + 1 < len(chain):
                raise PlaceError(f"{a}: a carry out used inside a chain is not supported at M8")
            ff, _ = absorb_ff(nl.bit(a, "O"), allow_o5=False)
            clusters[a] = {"kind": "add", "main": a, "ff": ff}

    for l in sorted(luts):
        width = _param(cells[l], "WIDTH")
        ff, o5 = absorb_ff(nl.bit(l, "Y"), allow_o5=width <= K - 1)
        clusters[l] = {"kind": "lut", "main": l, "ff": ff, "o5": o5}
    for f in sorted(ffs - absorbed):
        clusters[f] = {"kind": "ff", "main": None, "ff": f}

    # --- placement ------------------------------------------------------------------
    free = [s for x in CLB_COLS for s in column(x)]
    at = {}                                   # cluster name -> (x, y, e)
    gens, taps = [], []                       # generator / tap CLBs: (xy, ci signal bit or const)
    col = 0
    for chain in chains:
        i = 0
        ci = nl.bit(chain[0], "CI")
        carry_sig = ("bit", ci)
        while i < len(chain):
            if col >= len(CLB_COLS):
                raise PlaceError("not enough CLB columns for the carry chains")
            x = CLB_COLS[col]
            col += 1
            slots = column(x)
            if [s for s in slots if s in free] != slots:
                raise PlaceError("carry column already used")
            gens.append((slots[0], carry_sig))
            room = len(slots) - 1
            take = chain[i:i + room] if len(chain) - i <= room else chain[i:i + room - 1]
            for k, a in enumerate(take):
                at[a] = slots[1 + k]
            i += len(take)
            last = take[-1]
            co_used = nl.loads(nl.bit(last, "CO")) > (1 if i < len(chain) else 0)
            if i < len(chain) or co_used:
                if 1 + len(take) >= len(slots):
                    raise PlaceError("no element left for a carry tap")
                tap_xy = slots[1 + len(take)]
                taps.append((tap_xy, nl.bit(last, "CO")))
                carry_sig = ("tap", tap_xy)
                free.remove(tap_xy)
            for sl in slots[:1 + len(take)]:
                free.remove(sl)
    others = [n for n in clusters if n not in at]
    if len(others) > len(free):
        raise PlaceError(f"{len(others)} elements needed, {len(free)} free")
    if seed:
        import random
        random.Random(seed).shuffle(free)

    def ctl(n):
        """the CE and SR nets a cluster's flip-flop needs (None: not used)"""
        f = clusters[n]["ff"]
        if not f:
            return None, None
        rst = "R" if cells[f]["type"] == "BOB_FDRE" else "S"
        ce, sr = nl.bit(f, "CE"), nl.bit(f, rst)
        return (None if ce == "1" else ce), (None if sr in ("0", "x") else sr)
    clb_ctl = {}                              # (x, y) -> [ce net, sr net] its flip-flops share
    for n in list(at):                        # the chains' flip-flops come first
        ce, sr = ctl(n)
        c = clb_ctl.setdefault(at[n][:2], [None, None])
        c[0], c[1] = c[0] or ce, c[1] or sr
    for n in others:
        ce, sr = ctl(n)
        for sl in free:
            c = clb_ctl.setdefault(sl[:2], [None, None])
            if (ce is None or c[0] in (None, ce)) and (sr is None or c[1] in (None, sr)):
                c[0], c[1] = c[0] or ce, c[1] or sr
                at[n] = sl
                free.remove(sl)
                break
        else:
            raise PlaceError(f"{n}: no CLB left whose CE/SR nets it can share")

    # --- signals of placed outputs ----------------------------------------------------
    for n, cl in clusters.items():
        x, y, e = at[n]
        if cl["kind"] == "add":
            if cl["ff"]:
                sig[nl.bit(cl["ff"], "Q")] = Cell(x, y, "o", e)
            else:
                sig[nl.bit(n, "O")] = Cell(x, y, "o", e)
        elif cl["kind"] == "lut":
            if cl["ff"]:
                sig[nl.bit(cl["ff"], "Q")] = Cell(x, y, "o", e)
                if cl["o5"]:
                    sig[nl.bit(n, "Y")] = Cell(x, y, "o5", e)
            else:
                sig[nl.bit(n, "Y")] = Cell(x, y, "o", e)
        else:
            sig[nl.bit(cl["ff"], "Q")] = Cell(x, y, "o", e)
    for (x, y, e), co_bit in taps:
        sig[co_bit] = Cell(x, y, "o", e)
    brams = sorted(n for n, c in cells.items() if c["type"] == "BOB_BRAM18")
    dsps = sorted(n for n, c in cells.items() if c["type"] == "BOB_DSP")
    if len(brams) > B.NBRAM or len(dsps) > B.NDSP:
        raise PlaceError(f"{len(brams)} BRAMs / {len(dsps)} DSPs, the fabric has {B.NBRAM} / {B.NDSP}")
    for b, n in enumerate(brams):
        for port in "ab":
            for k, bit in enumerate(nl.cells[n]["connections"][f"{port.upper()}_DO"]):
                sig[bit] = BramOut(b, port, k)
    for s, n in enumerate(dsps):
        for k, bit in enumerate(nl.cells[n]["connections"]["P"]):
            sig[bit] = DspOut(s, k)

    # --- configure -----------------------------------------------------------------------
    def ff_args(f):
        c = cells[f]
        rst = "R" if c["type"] == "BOB_FDRE" else "S"
        ce_b, sr_b = nl.bit(f, "CE"), nl.bit(f, rst)
        return ({"ff_en": 1, "ff_rstval": int(c["type"] == "BOB_FDSE"),
                 "ff_ce_en": int(ce_b != "1"), "ff_sr_en": int(sr_b not in ("0", "x"))},
                None if ce_b == "1" else S(ce_b), None if sr_b in ("0", "x") else S(sr_b))

    def full_init(lut_bits, width):
        return sum(((lut_bits >> (a & ((1 << width) - 1))) & 1) << a for a in range(1 << K))

    for n, cl in clusters.items():
        x, y, e = at[n]
        flags, ce, sr = ({}, None, None)
        if cl["ff"]:
            flags, ce, sr = ff_args(cl["ff"])
        if cl["kind"] == "add":
            inv = _param(cells[n], "INV_B")
            init = B.lut(lambda a, b: a ^ b ^ inv, 2)
            d.lut(x, y, init, [S(nl.bit(n, "A")), S(nl.bit(n, "B"))], ce=ce, sr=sr, e=e,
                  cy_en=1, **flags)
        elif cl["kind"] == "lut":
            width = _param(cells[n], "WIDTH")
            ins = [S(b) for b in cells[n]["connections"]["A"]]
            d.lut(x, y, full_init(_param(cells[n], "LUT"), width), ins, ce=ce, sr=sr, e=e, **flags)
        else:
            d.lut(x, y, B.LUT.buf(0), [S(nl.bit(cl["ff"], "D"))], ce=ce, sr=sr, e=e, **flags)
    for (x, y, e), carry in gens:
        src = S(carry[1]) if carry[0] == "bit" else Cell(carry[1][0], carry[1][1], "o", carry[1][2])
        d.lut(x, y, B.LUT.const0(), [src], e=e, cy_en=1)     # O6 = 0: cout = DI = I0
    for (x, y, e), _co in taps:
        d.lut(x, y, B.LUT.const0(), [], e=e, cy_en=1)        # sum = O6 ^ cin = the carry
    for b, n in enumerate(brams):
        c = cells[n]
        for port in "ab":
            P = port.upper()
            d.bram_mode(port, {0: "WRITE_FIRST", 1: "READ_FIRST", 2: "NO_CHANGE"}[_param(c, f"WMODE_{P}", 1)],
                        bram=b)
            conn = c["connections"]
            for k in range(10):
                d.bram_pin(port, f"addr{k}", S(conn[f"{P}_ADDR"][k]), bram=b)
            for k in range(18):
                d.bram_pin(port, f"di{k}", S(conn[f"{P}_DI"][k]), bram=b)
            for pin in ("WE", "EN", "RST"):
                d.bram_pin(port, pin.lower(), S(conn[f"{P}_{pin}"][0]), bram=b)
        init = _param(c, "INIT")
        contents[b] = [(init >> (18 * i)) & 0x3FFFF for i in range(1024)]
    for s, n in enumerate(dsps):
        d.dsp_config(s, opmode="M", bus_a="fabric", bus_b="fabric")
        for k, bit in enumerate(cells[n]["connections"]["A"]):
            d.dsp_pin(s, "a", k, S(bit))
        for k, bit in enumerate(cells[n]["connections"]["B"]):
            d.dsp_pin(s, "b", k, S(bit))
    for k, bit in enumerate(mod["ports"].get("led", {"bits": []})["bits"]):
        d.output(k, S(bit))
    if clk_bits:
        d.set_clock("jtag")
    return d, contents, at


def build(top, seed_tries=8):
    last = None
    for seed in range(seed_tries):
        try:
            d, contents, at = place(top, seed)
            bs = d.build()
            return d, bs, contents
        except B.RouteError as e:
            last = e
    raise PlaceError(f"routing failed for every placement tried: {last}")


def check(top, bs, contents):
    import model
    tr = json.load(open(os.path.join(ROOT, "build", "synth", top, f"{top}.trace.json")))
    m = model.Fabric(bs)
    m.clock(gsr=1)
    for b, words in contents.items():
        m.brams[b].mem = list(words)
    bad = []
    for c, (v, before, after) in enumerate(tr["trace"]):
        got = m.outputs(v)
        if got != before:
            bad.append((c, v, got, before))
        if tr["has_clk"]:
            m.clock(pad_i=v)
        got = m.outputs(v)
        if got != after:
            bad.append((c, v, got, after))
    return bad, len(tr["trace"])


EXAMPLES = ["gates", "adder", "counter", "blinky", "ram", "mult"]


def flow(top, files=None, cycles=300):
    """synth -> netlist == source (iverilog) -> place/route -> placed model == source.
    Returns (design, bitstream, bram contents, trace dict)."""
    import equiv
    files = files or [os.path.join(ROOT, "work", "examples", top, f"{top}.v")]
    ok, lines, _mod = equiv.equiv(files, top, cycles=cycles)
    if not ok:
        raise PlaceError(f"{top}: synthesised netlist differs from the source: {lines}")
    d, bs, contents = build(top)
    bad, n = check(top, bs, contents)
    if bad:
        raise PlaceError(f"{top}: placed bitstream differs from the source in {len(bad)} samples")
    tr = json.load(open(os.path.join(ROOT, "build", "synth", top, f"{top}.trace.json")))
    return d, bs, contents, tr


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("top")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    try:
        d, bs, contents = build(args.top)
    except PlaceError as e:
        print(f"FAIL  {args.top}: {e}")
        return 1
    print(d.report())
    if args.check:
        bad, n = check(args.top, bs, contents)
        print(f"{'PASS' if not bad else 'FAIL'}  {args.top}: placed bitstream on model.py vs source "
              f"trace, {n - len(bad)}/{n} cycles")
        for c, v, g, e in bad[:5]:
            print(f"      cycle {c} pad_i={v:06b} LD2..0={g:03b} source={e:03b}")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
