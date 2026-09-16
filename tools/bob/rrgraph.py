#!/usr/bin/env python3
"""
rrgraph.py - read the routing-resource graph VPR wrote for bob's architecture.

OpenFPGA builds its fabric from VPR's (tileable) rr graph: every routing node
that more than one edge can drive becomes a multiplexer, and the edges into it
are the mux inputs. bob does the same. This module only parses; the policy
(which nodes are muxes, how they are encoded, where their bits live) is in
tools/bob/device.py.

  RRGraph(path)          path is rr_graph.xml or rr_graph.xml.gz
    .nodes[id]           Node(id, type, xlow, ylow, xhigh, yhigh, ptc, direction, side)
    .fanin[id]           sorted source node ids of every edge into node id
    .block_types[id]     BlockType(name, width, height, pins{ptc: 'clb[0].I[3]'})
    .grid[(x, y)]        (block type name, width_offset, height_offset)
    .chan_width          channel width VPR built the graph for
"""

import gzip
import xml.etree.ElementTree as ET
from collections import namedtuple

Node = namedtuple("Node", "id type xlow ylow xhigh yhigh ptc direction side")
BlockType = namedtuple("BlockType", "id name width height pins")


class RRGraph:
    def __init__(self, path):
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rb") as fh:
            root = ET.parse(fh).getroot()

        ch = root.find("channels/channel")
        self.chan_width = int(ch.get("chan_width_max"))

        self.block_types = {}
        for bt in root.iter("block_type"):
            pins = {}
            for pc in bt.iter("pin_class"):
                for p in pc.iter("pin"):
                    pins[int(p.get("ptc"))] = p.text.strip()
            self.block_types[int(bt.get("id"))] = BlockType(
                int(bt.get("id")), bt.get("name"), int(bt.get("width")), int(bt.get("height")), pins)

        self.grid = {}
        for g in root.iter("grid_loc"):
            bt = self.block_types[int(g.get("block_type_id"))]
            self.grid[(int(g.get("x")), int(g.get("y")))] = (
                bt.name, int(g.get("width_offset")), int(g.get("height_offset")))

        self.nodes = {}
        for n in root.iter("node"):
            loc = n.find("loc")
            self.nodes[int(n.get("id"))] = Node(
                int(n.get("id")), n.get("type"),
                int(loc.get("xlow")), int(loc.get("ylow")), int(loc.get("xhigh")), int(loc.get("yhigh")),
                # tileable wires carry one track id per grid position they pass: "0,2,4,6"
                tuple(int(p) for p in loc.get("ptc").split(",")), n.get("direction"), loc.get("side"))

        fanin = {i: [] for i in self.nodes}
        for e in root.iter("edge"):
            fanin[int(e.get("sink_node"))].append(int(e.get("src_node")))
        self.fanin = {i: sorted(set(v)) for i, v in fanin.items()}

    def pin_name(self, node):
        """'clb[0].I[3]' for an IPIN/OPIN node."""
        n = self.nodes[node]
        name, _wo, _ho = self.grid[(n.xlow, n.ylow)]
        bt = next(b for b in self.block_types.values() if b.name == name)
        return bt.pins[n.ptc[0]]

    def block_root(self, node):
        n = self.nodes[node]
        _name, wo, ho = self.grid[(n.xlow, n.ylow)]
        return n.xlow - wo, n.ylow - ho
