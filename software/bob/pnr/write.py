"""
write.py - the Python PnR result in VPR's file formats (M12a).

Only the parts software/bob/fasm_from_vpr.py reads are written, in the same shape VPR
writes them:
  <name>.net     top block with one child per cluster (instance clb[i] / io[i] /
                 bram[i] / dsp[i]); inside a CLB (M21) its I pins and elements
                 fle[e] (mode lut / frac / arithmetic, each input's crossbar source),
                 then the lut / lutf (with port_rotation_map), add and ff blocks by
                 atom name
  <name>.place   "block x y subblk layer #n"
  <name>.route   "Net n (name)" then "Node: id TYPE" lines; each branch after the
                 first starts by repeating the tree node it leaves from; global nets
                 as "Net n (name): global net connecting:"
"""

import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "host"))

import bitstream as B  # noqa: E402


def _port(parent, direction, name, text):
    io = parent.find(direction)
    if io is None:
        io = ET.SubElement(parent, direction)
    ET.SubElement(io, "port", name=name).text = text


def _leaf(parent, atom, inst, rot=None):
    if atom is None:
        ET.SubElement(parent, "block", name="open", instance=inst)
        return
    blk = ET.SubElement(parent, "block", name=atom.name, instance=inst)
    if rot is not None:
        ins = ET.SubElement(blk, "inputs")
        ET.SubElement(ins, "port_rotation_map", name="in").text = " ".join(rot)
    if atom.kind == "bob_ff":
        _port(blk, "outputs", "Q", atom.pins["Q"])


def _rot(atom, pins, width):
    """physical LUT pin j carries atom input rot[j]: pins[j] is the net on pin j"""
    import pnr.pack as pk
    ins = pk.lut_ins(atom)
    return [str(ins.index(pins[j])) if j < len(pins) and pins[j] in ins else "open" for j in range(width)]


def write_net(path, name, packed):
    """M21: a CLB is its elements (fle[e], modes lut / frac / arithmetic), each input
    naming its crossbar source - a CLB input pin (clb.I[k], the pin the router chose) or
    an element output of the same CLB (fle[m].out[o], feedback)"""
    top = ET.Element("block", name=f"{name}.net", instance="FPGA_packed_netlist[0]")
    count = {}
    K = B.LUT_K
    for cname in sorted(packed.clusters):
        cl = packed.clusters[cname]
        i = count.get(cl.type, 0)
        count[cl.type] = i + 1
        attrs = {"name": cname, "instance": f"{cl.type}[{i}]"}
        if cl.mode:
            attrs["mode"] = cl.mode
        blk = ET.SubElement(top, "block", attrs)
        if cl.type == "clb":
            pins = ["open"] * B.CLB_I
            for net, k in cl.in_pin.items():
                pins[k] = net
            _port(blk, "inputs", "I", " ".join(pins))
            made = {}
            for e, el in enumerate(cl.elems):
                if el is not None:
                    for o, net in enumerate(el.outs):
                        if net:
                            made[net] = f"fle[{e}].out[{o}]"
            for e, el in enumerate(cl.elems):
                if el is None:
                    continue
                mode = {"lut": "lut", "frac": "frac", "arith": "arithmetic"}[el.mode]
                fle = ET.SubElement(blk, "block", name=el.outs[0] or el.outs[1] or f"{cname}.e{e}",
                                    instance=f"fle[{e}]", mode=mode)
                src = []
                for net in el.ins:
                    if net is None:
                        src.append("open")
                    elif net in made:
                        src.append(f"{made[net]}->crossbar")
                    else:
                        src.append(f"clb.I[{cl.in_pin[net]}]->crossbar")
                _port(fle, "inputs", "in", " ".join(src))
                if el.mode == "lut":
                    ble = ET.SubElement(fle, "block", name=el.luts[0].name, instance="ble[0]")
                    _leaf(ble, el.luts[0], "lut[0]", _rot(el.luts[0], el.ins, K))
                    _leaf(ble, el.ffs[0], "ff[0]")
                elif el.mode == "frac":
                    for half in (0, 1):
                        ble = ET.SubElement(fle, "block", name=el.luts[half].name, instance=f"blef[{half}]")
                        _leaf(ble, el.luts[half], "lutf[0]", _rot(el.luts[half], el.ins[:K - 1], K - 1))
                        _leaf(ble, el.ffs[half], "ff[0]")
                else:
                    _leaf(fle, el.add, "add[0]")
                    _leaf(fle, el.ffs[0], "ff[0]")
        elif cl.type in ("bram", "dsp"):
            ET.SubElement(blk, "block", name=cl.atoms["prim"].name, instance=f"{cl.type}_prim[0]")
    ET.ElementTree(top).write(path, encoding="unicode")


def write_place(path, name, placement):
    lines = [f"Netlist_File: {name}.net Netlist_ID: python-pnr",
             f"Array size: {B.DEVICE['arch']['grid_width']} x {B.DEVICE['arch']['grid_height']} logic blocks", "",
             "#block name\tx\ty\tsubblk\tlayer\tblock number"]
    for i, c in enumerate(sorted(placement.pos)):
        x, y = placement.pos[c]
        lines.append(f"{c}\t{x}\t{y}\t0\t0\t#{i}")
    open(path, "w").write("\n".join(lines) + "\n")


def write_route(path, routed, global_nets):
    L = ["Placement_File: python-pnr", "Routing:", ""]
    k = 0
    for net in sorted(routed):
        L += [f"Net {k} ({net})", ""]
        k += 1
        # each branch after the first leaves from a node already written: emit in tree order
        pending = list(routed[net])
        seen = {p[0] for p in pending if B.NODE[p[0]][1] == "OPIN"}      # the source
        ordered = []
        while pending:
            k2 = next((i for i, p in enumerate(pending) if p[0] in seen), None)
            if k2 is None:
                raise ValueError(f"net {net}: a branch does not start on its routing tree")
            p = pending.pop(k2)
            ordered.append(p)
            seen.update(p)
        for p in ordered:                               # p[0]: the source, or the tree node a branch leaves from
            for n in p:
                L.append(f"Node:\t{n}\t{B.NODE[n][1]} ({B.NODE[n][2]},{B.NODE[n][3]},0)")
        L.append("")
    for net in sorted(global_nets):
        L += [f"Net {k} ({net}): global net connecting:", ""]
        k += 1
    open(path, "w").write("\n".join(L) + "\n")
