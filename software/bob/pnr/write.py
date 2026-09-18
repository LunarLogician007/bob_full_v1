"""
write.py - the Python PnR result in VPR's file formats (M12a).

Only the parts software/bob/fasm_from_vpr.py reads are written, in the same shape VPR
writes them:
  <name>.net     top block with one child per cluster (instance clb[i] / io[i] /
                 bram[i] / dsp[i], mode logic / arithmetic / inpad / outpad); inside
                 a CLB the lut (with port_rotation_map), add and ff blocks by atom name
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


def write_net(path, name, packed):
    top = ET.Element("block", name=f"{name}.net", instance="FPGA_packed_netlist[0]")
    count = {}
    for cname in sorted(packed.clusters):
        cl = packed.clusters[cname]
        i = count.get(cl.type, 0)
        count[cl.type] = i + 1
        attrs = {"name": cname, "instance": f"{cl.type}[{i}]"}
        if cl.mode:
            attrs["mode"] = cl.mode
        blk = ET.SubElement(top, "block", attrs)
        if cl.type == "clb":
            if cl.mode == "logic":
                lut = ET.SubElement(blk, "block", name=cl.atoms["lut"].name, instance="lut[0]")
                ins = ET.SubElement(lut, "inputs")
                rot = ["open"] * B.LUT_K                  # physical pin j carries atom input rot[j]
                for k in cl.lut_inputs:
                    rot[cl.lut_pin.get(k, k)] = str(k)
                ET.SubElement(ins, "port_rotation_map", name="in").text = " ".join(rot)
            else:
                ET.SubElement(blk, "block", name=cl.atoms["add"].name, instance="add[0]")
            if "ff" in cl.atoms:
                ff = ET.SubElement(blk, "block", name=cl.atoms["ff"].name, instance="ff[0]")
                outs = ET.SubElement(ff, "outputs")
                ET.SubElement(outs, "port", name="Q").text = cl.atoms["ff"].pins["Q"]
            else:
                ET.SubElement(blk, "block", name="open", instance="ff[0]")
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
