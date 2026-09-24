#!/usr/bin/env python3
"""
fasm_from_vpr.py - VPR's packed, placed and routed result -> bob FASM -> chain (M9).

  software/bob/fasm_from_vpr.py [counter ...] [--check]

Reads the committed VPR result software/bob/vpr/<top>/ (software/bob/vpr_run.py,
`make vpr`): <top>.net (packing), <top>.place, <top>.route and <top>.vpr.json
(what the netlist rewrite recorded). No Docker needed. Refuses a result routed
from another netlist or architecture. Writes build/vpr/<top>/<top>.fasm and .hex.

The FASM is one feature per line, in the spirit of F4PGA's FASM ("feature = value", only non-zero features written):

  clb_x2y3.init = 64'h6                  CLB fields (device.json tile_types.clb)
  clb_x2y3.cy_en = 1'b1
  bram0.wmode_a = 2'h1                   BRAM / DSP fields
  ctrl.clk_mode = 2'h0                   ctrl tile
  rr1234 = 3'h5                          routing mux of rr node 1234

Every feature is checked against device.json (block and field exist, value fits,
a mux value selects a real input or an IPIN constant) before it becomes chain
bits. This is M9's minimal FASM -> chain step; bitgen.py and the round trip are M10.

How the parts become features:
  packing   clb mode "logic": init = the LUT's table re-indexed through VPR's
            port_rotation_map (which physical pin carries which atom input);
            mode "arithmetic": init = I0 ^ I1 (^1 for INV_B), cy_en.
            mode "dd" (M24): dd + cy_en (cy_di_sel = INV_B), the adder on I[K-2], I[K-1];
            init[2**(K-1)-1:0] = the LUT's table on I[K-3:0], repeated over I[K-2] (O5) -> out[1].
            ff in the cluster: ff_en, ff_rstval (FDSE), ff_ce_en / ff_sr_en when
            CE / SR is a net.
  placement VPR's (x, y) is bob's (x, y); the block rooted there names the tile.
  routing   for each net in <top>.route, every node after the first on a branch
            selects the node before it (Bitstream.select). Directs (carry,
            cascade) are wires and have no bits; VPR lists them as global nets.
  constants pins the rewrite left open with a constant get IPIN value 0/1.
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402

BLOCK_AT = {(b["x"], b["y"]): b for b in B.DEVICE["blocks"]}
NODE_PIN = {}
for _pin, _node in B.PIN.items():
    _blk, _p = _pin.split(".", 1)
    NODE_PIN[_node] = (_blk, _p)
TABLES = {"clb": B.FIELD, "bram": B.BRAM_FIELD, "dsp": B.DSP_FIELD, "ctrl": B.CTRL_FIELD}


class FasmError(Exception):
    pass


def _children(blk):
    return [c for c in blk.findall("block") if c.get("name") != "open"]


def read_place(path):
    at = {}
    for line in open(path):
        if line.startswith(("#", "Netlist_File", "Array size")) or not line.strip():
            continue
        f = line.split()
        at[f[0]] = (int(f[1]), int(f[2]))
    return at


def read_route(path):
    """-> {net name: [[node ids of one branch], ...]} for routed (non-global) nets"""
    nets, cur = {}, None
    for line in open(path):
        m = re.match(r"Net \d+ \((.*)\)(: global net)?", line)
        if m:
            cur = None if m.group(2) else nets.setdefault(m.group(1), [[]])
            continue
        m = re.match(r"Node:\s+(\d+)\s+(\w+)", line)
        if m and cur is not None:
            cur[-1].append((int(m.group(1)), m.group(2)))
    return nets


def _port_text(blk, direction, name):
    for port in blk.find(direction).findall("port"):
        if port.get("name") == name:
            return port.text.split() if port.text else []
    return []


def _lut_init(leaf, spec, k):
    """the atom's truth table spec["tt"] over its own inputs, re-indexed onto the LUT's k
    physical pins through VPR's port_rotation_map (physical pin j carries logical input
    rot[j]); physical pins VPR left open read 0 and the table does not depend on them"""
    rot = None
    for r in leaf.find("inputs").findall("port_rotation_map"):
        rot = r.text.split()
    init = 0
    for addr in range(1 << k):
        a = 0
        for j, src in enumerate(rot):
            if src != "open":
                a |= ((addr >> j) & 1) << int(src)
        init |= ((spec["tt"] >> a) & 1) << addr
    return init


def _ff_features(put, el, side, ffblk, second=False):
    ff = side["ff"][ffblk.get("name")]
    p = "ff2" if second else "ff"
    put(f"{el}.{p}_en", 1)
    if ff["rstval"]:
        put(f"{el}.{p}_rstval", 1)
    if ff["ce"]:
        put(f"{el}.{p}_ce_en", 1)
    if ff["sr"]:
        put(f"{el}.{p}_sr_en", 1)


def features(work, result):
    """-> ({feature: value}, bram contents {index: words}) for the VPR result
    <work>/<name>.{net,place,route,vpr.json}"""
    side = json.load(open(os.path.join(work, f"{result}.vpr.json")))
    place = read_place(os.path.join(work, f"{result}.place"))
    root = ET.parse(os.path.join(work, f"{result}.net")).getroot()
    routes = read_route(os.path.join(work, f"{result}.route"))
    F = {}

    def put(feature, value):
        if F.get(feature, value) != value:
            raise FasmError(f"{feature} set to both {F[feature]} and {value}")
        F[feature] = value

    def pin_const(block, pin, v):
        put(f"rr{B.PIN[f'{block}.{pin}']}", v)

    # which cluster input pins each net actually reached (the router may use any pin of an
    # equivalent class, so the packer's choice in the .net is only a preference)
    reached = {}
    for net, branches in routes.items():
        for node, kind in branches[0]:
            if kind == "IPIN" and node in NODE_PIN:
                blk, pin = NODE_PIN[node]
                reached.setdefault((blk, net), set()).add(pin)

    contents = {}
    k = B.LUT_K
    for blk in root.findall("block"):
        inst = blk.get("instance").split("[")[0]
        x, y = place[blk.get("name")]
        dev = BLOCK_AT.get((x, y))
        if dev is None or dev["type"] != inst:
            raise FasmError(f"{blk.get('name')}: VPR put a {inst} at ({x},{y}), device.json has {dev}")
        name = dev["name"]
        if inst == "clb":
            clb_in = _port_text(blk, "inputs", "I")                     # net on each clb.I pin
            for fle in blk.findall("block"):
                if fle.get("name") == "open":
                    continue
                e = int(fle.get("instance").split("[")[1].rstrip("]"))
                el = f"{name}.e{e}"
                mode = fle.get("mode")
                kids = {c.get("instance"): c for c in _children(fle)}
                consts = {}
                if mode == "lut":
                    ble = kids["ble[0]"]
                    bk = {c.get("instance").split("[")[0]: c for c in _children(ble)}
                    if "lut" in bk:
                        lut = bk["lut"]
                        leaf = lut.find("block") if lut.find("block") is not None else lut
                        put(f"{el}.init", _lut_init(leaf, side["lut"][lut.get("name")], k))
                    if "ff" in bk:
                        _ff_features(put, el, side, bk["ff"])
                elif mode == "frac":
                    put(f"{el}.frac", 1)
                    init = 0
                    for half in (0, 1):                  # blef[0]: O6 = INIT[hi], blef[1]: O5 = INIT[lo]
                        ble = kids.get(f"blef[{half}]")
                        if ble is None:
                            continue
                        bk = {c.get("instance").split("[")[0]: c for c in _children(ble)}
                        if "lutf" in bk:
                            lut = bk["lutf"]
                            leaf = lut.find("block") if lut.find("block") is not None else lut
                            t = _lut_init(leaf, side["lut"][lut.get("name")], k - 1)
                            init |= t << ((1 << (k - 1)) if half == 0 else 0)
                        if "ff" in bk:
                            _ff_features(put, el, side, bk["ff"], second=(half == 1))
                    if init:
                        put(f"{el}.init", init)
                elif mode == "dd":
                    # M24 Double Duty: the adder on in[k-2] (A) / in[k-1] (B), INV_B in
                    # cy_di_sel; the LUT (bled, k-1 pins, the top one unconnected) on
                    # in[k-3:0] = the O5 half INIT[2**(k-1)-1:0] -> out[1]; _lut_init
                    # repeats the table over the unconnected pin, which the fabric drives with A
                    add = kids.get("add[0]")             # VPR may use dd for the LUT alone
                    if add is not None:
                        put(f"{el}.dd", 1)
                        put(f"{el}.cy_en", 1)
                        if side["add"][add.get("name")]["inv"]:
                            put(f"{el}.cy_di_sel", 1)
                        for pin, v in side["consts"].get(add.get("name"), {}).items():
                            if v is not None:
                                consts[{"a": k - 2, "b": k - 1}[pin]] = v
                    if "ff[0]" in kids:
                        _ff_features(put, el, side, kids["ff[0]"])
                    ble = kids.get("bled[0]")
                    if ble is not None:
                        bk = {c.get("instance").split("[")[0]: c for c in _children(ble)}
                        if "lutd" in bk:
                            lut = bk["lutd"]
                            leaf = lut.find("block") if lut.find("block") is not None else lut
                            put(f"{el}.init", _lut_init(leaf, side["lut"][lut.get("name")], k - 1))
                        if "ff" in bk:
                            _ff_features(put, el, side, bk["ff"], second=True)
                elif mode == "arithmetic":
                    add = kids["add[0]"]
                    inv = side["add"][add.get("name")]["inv"]
                    put(f"{el}.init", B.lut(lambda a, b: a ^ b ^ inv, 2))
                    put(f"{el}.cy_en", 1)
                    for pin, v in side["consts"].get(add.get("name"), {}).items():
                        if v is not None:
                            consts[{"a": 0, "b": 1}[pin]] = v
                    if "ff[0]" in kids:
                        _ff_features(put, el, side, kids["ff[0]"])
                # the crossbar: each used element input takes the source carrying its net
                fins = _port_text(fle, "inputs", "in")
                for j in range(k):
                    if j in consts:
                        put(f"{el}.x{j}", consts[j])          # 0 const0, 1 const1
                        continue
                    src = fins[j] if j < len(fins) else "open"
                    if src == "open":
                        continue
                    srcs = B.XBAR_SOURCES[e][j]
                    m = re.match(r"fle\[(\d+)\]\.out\[(\d+)\]", src)
                    if m:
                        pin = f"O[{2 * int(m.group(1)) + int(m.group(2))}]"
                    else:
                        m = re.match(r"clb\.I\[(\d+)\]", src)
                        if not m:
                            raise FasmError(f"{el} input {j}: unknown crossbar source {src}")
                        net = clb_in[int(m.group(1))]
                        got = reached.get((name, net), set())
                        want = f"I[{m.group(1)}]"
                        pin = want if want in got else next((p for p in srcs if p in got), None)
                        if pin is None:
                            raise FasmError(f"{el} input {j}: net {net} reaches {name} on "
                                            f"{sorted(got) or 'no pin'}, none on its crossbar")
                    if pin not in srcs:
                        raise FasmError(f"{el} input {j}: {pin} is not on its crossbar")
                    put(f"{el}.x{j}", 2 + srcs.index(pin))
        elif inst in ("bram", "dsp"):
            atom = _children(blk)[0].get("name")
            if inst == "bram":
                bs = side["bram"][atom]
                for p in "ab":
                    if bs[f"wmode_{p}"]:
                        put(f"{name}.wmode_{p}", bs[f"wmode_{p}"])
                contents[dev["index"]] = bs["contents"]
            for pin, v in side["consts"].get(atom, {}).items():
                if v:
                    pin_const(name, pin, v)
    for oname, v in side["out_consts"].items():
        if v:
            pin_const(B.pad_block(side["out_pads"][oname]), "outpad[0]", v)

    # routing
    for net, branches in routes.items():
        seen, prev = set(), None
        for node, kind in branches[0]:
            if node in seen:                       # a branch restarts from a node on the tree
                prev = node
                continue
            if prev is not None and kind in ("CHANX", "CHANY", "IPIN") and node not in B.DIRECT:
                lo, w, base, ins = B.MUX[node]
                if prev not in ins:
                    raise FasmError(f"net {net}: rr node {node} has no edge from {prev}")
                put(f"rr{node}", base + ins.index(prev))
            seen.add(node)
            prev = node

    put("ctrl.clk_mode", B.CLOCK_MODES["jtag"])
    return F, contents


def capture_map(result, work=None):
    """[(CAPTURE bit, yosys bit)] for every element output that is a flip-flop: the
    register state CAPTURE reads (bit 2i = element i's out[0], 2i+1 its out[1]), and the
    golden net (golden.py n<bit>) it must equal"""
    import vpr_run
    work = work or os.path.join(vpr_run.RESULTS, result)
    side = json.load(open(os.path.join(work, f"{result}.vpr.json")))
    place = read_place(os.path.join(work, f"{result}.place"))
    root = ET.parse(os.path.join(work, f"{result}.net")).getroot()
    out = []

    def ff_q(ff):
        q = ff.find("outputs").find("port").text.strip()
        bit = side["net_bits"].get(q)
        if bit is None:
            raise FasmError(f"{result}: flip-flop output net {q} has no yosys bit")
        return bit

    for blk in root.findall("block"):
        if not blk.get("instance").startswith("clb["):
            continue
        name = BLOCK_AT[place[blk.get("name")]]["name"]
        for fle in _children(blk):
            e = int(fle.get("instance").split("[")[1].rstrip("]"))
            idx = B.ELEM[f"{name}.e{e}"]["index"]
            for sub in _children(fle):                    # ble / blef[0] / blef[1] / add, ff / bled[0]
                inst = sub.get("instance")
                if inst == "ff[0]":
                    out.append((2 * idx, ff_q(sub)))
                    continue
                for leaf in _children(sub):
                    if leaf.get("instance") == "ff[0]":
                        out.append((2 * idx + (1 if inst in ("blef[1]", "bled[0]") else 0), ff_q(leaf)))
    return sorted(out)


def check_legal(F):
    """every feature names a real field / mux and its value is meaningful"""
    for feat, v in F.items():
        if feat.startswith("rr"):
            node = int(feat[2:])
            if node not in B.MUX:
                raise FasmError(f"{feat}: no such mux")
            lo, w, base, ins = B.MUX[node]
            ipin = B.NODE[node][1] == "IPIN"
            ok = (v == 0 or (ipin and v == 1) or base <= v < base + len(ins)) and v < (1 << w)
            if not ok:
                raise FasmError(f"{feat} = {v}: not a constant or an input of a {len(ins)}-input mux")
            continue
        block, field = feat.split(".", 1)
        m = re.fullmatch(r"e(\d+)\.x(\d+)", field)
        if m and block in B.BLOCKS and B.BLOCKS[block]["type"] == "clb":      # a crossbar select
            n = len(B.XBAR_SOURCES[int(m.group(1))][int(m.group(2))])
            if not (0 <= v < 2 + n and f"e{m.group(1)}.x{m.group(2)}" in B.FIELD):
                raise FasmError(f"{feat} = {v}: not a constant or one of the {n} crossbar sources")
            continue
        if block == "ctrl":
            table = B.CTRL_FIELD
        else:
            if block not in B.BLOCKS or B.BLOCKS[block]["type"] not in TABLES:
                raise FasmError(f"{feat}: no configurable block {block}")
            table = TABLES[B.BLOCKS[block]["type"]]
        if field not in table:
            raise FasmError(f"{feat}: {block} has no field {field}")
        if not 0 <= v < (1 << table[field][1]):
            raise FasmError(f"{feat} = {v} does not fit {table[field][1]} bits")


def feature_width(feat):
    if feat.startswith("rr"):
        return B.MUX[int(feat[2:])][1]
    block, field = feat.split(".", 1)
    if block == "ctrl":
        return B.CTRL_FIELD[field][1]
    return TABLES[B.BLOCKS[block]["type"]][field][1]


def to_fasm(F):
    lines = []
    for feat in sorted(F, key=lambda f: (f.startswith("rr"), int(f[2:]) if f.startswith("rr") else 0, f)):
        v = F[feat]
        if v or feat == "ctrl.clk_mode":
            lines.append(f"{feat} = {feature_width(feat)}'h{v:x}")
    return "\n".join(lines) + "\n"


def to_bitstream(F):
    bs = B.Bitstream()
    for feat, v in F.items():
        if feat.startswith("rr"):
            bs.set_mux(int(feat[2:]), v)
        elif feat.startswith("ctrl."):
            bs._put(*B.CTRL_FIELD[feat[5:]], v)
        else:
            block, field = feat.split(".", 1)
            bs.set_block(block, field, v)
    return bs


def build(name, work=None):
    """-> (bitstream, bram contents, fasm text). name is an example or a variant
    (vpr_run.VARIANTS); without work, the committed result, refused if stale."""
    import vpr_run
    if work is None:
        why = vpr_run.stale(name)
        if why:
            raise FasmError(why)
        work = os.path.join(vpr_run.RESULTS, name)
    F, contents = features(work, name)
    check_legal(F)
    text = to_fasm(F)
    out = os.path.join(ROOT, "build", "vpr", name)
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, f"{name}.fasm"), "w").write(text)
    bs = to_bitstream(F)
    open(os.path.join(out, f"{name}.hex"), "w").write(bs.to_hex() + "\n")
    return bs, contents, text


def top_of(name):
    import vpr_run
    return vpr_run.VARIANTS.get(name, (name, None))[0]


def board_trace(tr, pins):
    """The source trace (examples' convention: sw/btn -> pad_i, led -> pad_o) as the
    board sees it through a result's fixed pins. None if a port is off the board."""
    conv_in = [f"sw[{i}]" for i in range(2)] + [f"btn[{i}]" for i in range(4)]
    conv_out = [f"led[{i}]" for i in range(3)]
    perm_in, perm_out = [], []
    for k, port in enumerate(conv_in):
        pad = pins.get(port)
        if pad is not None:
            if pad not in B.BOARD_IN:
                return None
            perm_in.append((k, B.BOARD_IN.index(pad)))
    for k, port in enumerate(conv_out):
        pad = pins.get("out:" + port, pins.get(port))
        if pad is not None:
            if pad not in B.BOARD_OUT:
                return None
            perm_out.append((k, B.BOARD_OUT.index(pad)))

    def remap(v, perm):
        return sum(((v >> a) & 1) << b for a, b in perm)

    out = dict(tr)
    out["trace"] = [(remap(v, perm_in), remap(bef, perm_out), remap(aft, perm_out)) for v, bef, aft in tr["trace"]]
    return out


def check_model(name, bs, contents, work=None, top=None):
    """(bad samples, cycles, board trace) of these bits on model.py against the source
    trace, seen through the result's pins"""
    import model
    import vpr_run
    work = work or os.path.join(vpr_run.RESULTS, name)
    top = top or top_of(name)
    side = json.load(open(os.path.join(work, f"{name}.vpr.json")))
    tr = json.load(open(os.path.join(ROOT, "build", "synth", top, f"{top}.trace.json")))
    tr = board_trace(tr, side["pins"])
    if tr is None:
        raise FasmError(f"{name}: a port is not on a board pin; no model check")
    m = model.Fabric(bs)
    m.clock(gsr=1)
    for b, words in contents.items():
        m.brams[b].mem = list(words)
    bad = []
    for c, (v, before, after) in enumerate(tr["trace"]):
        if m.outputs(v) != before:
            bad.append((c, v, m.outputs(v), before))
        if tr["has_clk"]:
            m.clock(pad_i=v)
        if m.outputs(v) != after:
            bad.append((c, v, m.outputs(v), after))
    return bad, len(tr["trace"]), tr


def flow(name, cycles=300):
    """synth -> netlist == source -> committed VPR result (fresh?) -> FASM -> chain
    -> model == source trace. Returns (bitstream, bram contents, board trace dict)."""
    import equiv
    top = top_of(name)
    ok, lines, _mod = equiv.equiv([os.path.join(ROOT, "work", "examples", top, f"{top}.v")], top, cycles=cycles)
    if not ok:
        raise FasmError(f"{top}: synthesised netlist differs from the source: {lines}")
    bs, contents, _text = build(name)
    bad, n, tr = check_model(name, bs, contents)
    if bad:
        raise FasmError(f"{name}: VPR bitstream differs from the source in {len(bad)} of {2 * n} samples")
    return bs, contents, tr


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tops", nargs="*", help="default: every example")
    ap.add_argument("--check", action="store_true",
                    help="replay the source trace (software/bob/equiv.py) on model.py with these bits")
    args = ap.parse_args()
    import vpr_run
    fails = 0
    for top in args.tops or vpr_run.EXAMPLES + list(vpr_run.VARIANTS):
        try:
            bs, contents, text = build(top)
        except (FasmError, KeyError, FileNotFoundError) as e:
            print(f"FAIL  {top}: {e}")
            fails += 1
            continue
        nmux = sum(1 for l in text.splitlines() if l.startswith("rr"))
        line = (f"{top}: {len(text.splitlines())} FASM features ({nmux} routing muxes), "
                f"legal against device.json")
        if not args.check:
            print(f"PASS  {line}")
            continue
        bad, n, _tr = check_model(top, bs, contents)
        print(f"{'PASS' if not bad else 'FAIL'}  {line}; on model.py vs the source trace "
              f"{2 * n - len(bad)}/{2 * n} samples")
        for c, v, g, e in bad[:5]:
            print(f"      cycle {c} pad_i={v:06b} LD2..0={g:03b} source={e:03b}")
        fails += bool(bad)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
