"""Chapter 02 - Architecture as data: device.py, the grid, the VPR architecture, the rr graph."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bobvid.scene import *


class Ch02Arch(BobScene):
    CH = "02"
    TITLE = "Architecture as data"
    SUBTITLE = "one description, and a fabric generated from the router's own graph"

    def construct(self):
        self.title_card(
            "Most FPGA projects describe their hardware twice: once for the chip and once "
            "for the tools. bob describes it once, in data, and generates everything else.")
        self.source_of_truth()
        self.grid()
        self.vpr_arch()
        self.openfpga_method()
        self.rr_numbers()
        self.files_card(
            "These are the files behind this chapter. device.py and the architecture writer are "
            "written by hand; the device file, the routing graph and the fabric are generated; "
            "and the device tests check that every mux encoding and every pin agree.",
            [("software/bob/device.py", "the single source of truth"),
             ("software/bob/vpr_arch.py", "writes the VPR architecture XML"),
             ("software/bob/fabric_gen.py", "rr graph -> fabric Verilog")],
            [("software/bob/device.json", "read by every tool"),
             ("software/bob/arch/bob_k6_rr.xml.gz", "VPR's rr graph, committed + stamped"),
             ("hw/src/generated/bob_fabric.v", "one bob_mux per rr node")],
            [("tests/test_device.py", "overlaps, encodings, pins, frames"),
             ("make device / --check", "fails if a generated file is stale")])

    # ------------------------------------------------------------------
    def source_of_truth(self):
        self.heading("One description", "software/bob/device.py is the only place architecture numbers live")
        src = chip("device.py\nARCH dict · tile fields · columns · pads", C_PY, w=4.0, h=1.3, size=19).move_to(LEFT * 4.3 + DOWN * 0.2)
        outs = [("device.json", "every tool and the host read it", C_PY),
                ("bob_params.vh", "the same numbers as Verilog macros", C_RTL),
                ("bob_fabric.v", "the fabric RTL", C_RTL),
                ("bob_k6.xml", "the VPR architecture", C_VPR),
                ("FASM names", "feature = field name", C_BIT),
                ("model.py, hwtest", "the models and the board checks", C_GRF)]
        cards = VGroup()
        for name, d, cc in outs:
            cards.add(VGroup(mono(name, 18, cc), txt(d, 15, DIM)).arrange(DOWN, aligned_edge=LEFT, buff=0.05))
        cards.arrange(DOWN, aligned_edge=LEFT, buff=0.22).move_to(RIGHT * 2.6 + DOWN * 0.2)
        arrs = VGroup(*[arrow(src.get_right(), c.get_left() + LEFT * 0.15, DIM, sw=2, tip=0.14) for c in cards])
        with self.narrate(
                "Everything about bob's architecture is one Python file, device.py. It says how big "
                "the grid is, which tile types exist and which configuration fields each one has, "
                "where the memory and multiplier columns go, and which pad is which switch or LED."):
            self.play(FadeIn(src, shift=RIGHT * 0.2), run_time=0.8)
        with self.narrate(
                "From it come the device file every tool reads, the Verilog parameters, the fabric "
                "itself, the architecture file for the VPR router, the names of every configuration "
                "feature, and through them the Python models and the board checks. Two copies of a "
                "number is a bug waiting to happen; here there is one."):
            for a, c in zip(arrs, cards):
                self.play(GrowArrow(a), FadeIn(c, shift=RIGHT * 0.1), run_time=0.45)
        self.wipe()

    def grid(self):
        F = self.F
        a = F["arch"]
        self.heading("The grid", f"{a['grid_width']} × {a['grid_height']} tiles: an I/O ring around {F['count']['clb']} CLBs, a BRAM column and a DSP column")
        g, cells = grid_view(F, cell=0.36, gap=0.05)
        g.move_to(LEFT * 2.3 + DOWN * 0.25)
        cols = {c["type"]: c for c in a["columns"]}
        bx, dx = cols["bram"]["x"], cols["dsp"]["x"]
        bl = txt(f"BRAM column x = {bx}\nheight {cols['bram']['height']}: {F['count']['bram']} blocks", 16, C_PY)
        dl = txt(f"DSP column x = {dx}\nheight {cols['dsp']['height']}: {F['count']['dsp']} slices", 16, C_VPR)
        VGroup(bl, dl).arrange(DOWN, aligned_edge=LEFT, buff=0.25).move_to(RIGHT * 4.4 + UP * 1.5)
        side = VGroup(
            bold("board pads", 20, C_CYN),
            *[txt(f"{p['name']}  pad {p['pad']}  ({F['pads']['xy'][str(p['pad'])][0]},{F['pads']['xy'][str(p['pad'])][1]})", 16, INK)
              for p in F["pads"]["inputs"]],
            *[txt(f"{p['name']}  pad {p['pad']}  ({F['pads']['xy'][str(p['pad'])][0]},{F['pads']['xy'][str(p['pad'])][1]})", 16, C_RTL)
              for p in F["pads"]["outputs"]],
            txt(f"the other {F['pads']['count'] - len(F['pads']['inputs']) - len(F['pads']['outputs'])} pads: JTAG only", 15, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        side.next_to(VGroup(bl, dl), DOWN, buff=0.35).align_to(bl, LEFT)
        with self.narrate(
                f"Here is the grid that description produces: {a['grid_width']} columns by "
                f"{a['grid_height']} rows of tiles. The outer ring is {F['pads']['count']} I/O pads, "
                f"and the corners are empty."):
            self.play(FadeIn(g, lag_ratio=0.004), run_time=1.6)
        with self.narrate(
                f"Inside, the columns are logic blocks, except column {bx}, which holds block RAM, "
                f"and column {dx}, which holds DSP slices. A memory or a multiplier is taller than a "
                f"logic block, so each one spans {cols['bram']['height']} rows, and each column holds two. "
                f"That leaves exactly ten by ten logic blocks."):
            self.play(Indicate(cells[(bx, 1)], color=C_PY), Indicate(cells[(bx, 6)], color=C_PY), FadeIn(bl), run_time=1.0)
            self.play(Indicate(cells[(dx, 1)], color=C_VPR), Indicate(cells[(dx, 6)], color=C_VPR), FadeIn(dl), run_time=1.0)
        hl = VGroup(*[SurroundingRectangle(cells[tuple(F["pads"]["xy"][str(p["pad"])])], color=C_CYN, buff=0.03)
                      for p in F["pads"]["inputs"] + F["pads"]["outputs"]])
        with self.narrate(
                "The board's switches and buttons sit on fixed pads on the west edge, and the LEDs on "
                "the east edge. Every other pad has no wire to the outside world: it is reached only "
                "through boundary scan, over JTAG."):
            self.play(Create(hl), FadeIn(side, lag_ratio=0.1), run_time=1.4)
        self.wipe()

    def vpr_arch(self):
        F = self.F
        a = F["arch"]
        self.heading("The VPR architecture", "what the router is told about the tiles and the wires")
        bp = F["block_ports"]["clb"]
        clb = RoundedRectangle(width=2.4, height=2.6, corner_radius=0.12, color=C_RTL, stroke_width=2.5).set_fill(C_RTL, opacity=0.1)
        clb.move_to(LEFT * 4.2 + DOWN * 0.3)
        lab = bold("CLB", 24, C_RTL).move_to(clb)
        ins = mono("I[0..15]", 16, INK).next_to(clb, LEFT, buff=0.15)
        outs = mono("O[0..7]", 16, INK).next_to(clb, RIGHT, buff=0.15)
        cin = mono("cin", 15, C_VPR).next_to(clb, DOWN, buff=0.12)
        cout = mono("cout", 15, C_VPR).next_to(clb, UP, buff=0.12)
        ctl = mono("ce sr clk", 14, DIM).move_to(clb.get_bottom() + UP * 0.3)
        params = VGroup(
            VGroup(mono(f"W = {a['chan_width']}", 22, C_GRF), txt("tracks in every routing channel", 16, DIM)),
            VGroup(mono(f"L = {a['segment_length']}", 22, C_GRF), txt("each wire spans four tiles, one direction", 16, DIM)),
            VGroup(mono(f"{a['switch_block']}", 22, C_GRF), txt("switch box: each wire turns onto three others", 16, DIM)),
            VGroup(mono(f"fc_in = {a['fc_in']}  fc_out = {a['fc_out']}", 22, C_GRF), txt("share of tracks a pin can reach", 16, DIM)),
            VGroup(mono("modes: logic · dd", 22, C_GRF), txt("element modes VPR packs into (Double Duty, chapter 03)", 16, DIM)),
        )
        for p in params:
            p.arrange(DOWN, aligned_edge=LEFT, buff=0.05)
        params.arrange(DOWN, aligned_edge=LEFT, buff=0.22).move_to(RIGHT * 2.8 + DOWN * 0.3)
        with self.narrate(
                "device.py also writes an architecture file for VPR, the academic place-and-route "
                "tool. It describes each tile's pins: a logic block has sixteen inputs from the "
                "routing, eight outputs back to it, a carry in and out, and clock enable, reset and clock."):
            self.play(Create(clb), FadeIn(lab), run_time=0.6)
            self.play(FadeIn(ins), FadeIn(outs), FadeIn(cin), FadeIn(cout), FadeIn(ctl), run_time=0.8)
        with self.narrate(
                f"And it describes the wires: channels {a['chan_width']} tracks wide, made of "
                f"unidirectional wires that each span {a['segment_length']} tiles, joined by Wilton "
                f"switch boxes, with ten percent of the tracks reachable from each pin. These numbers "
                f"follow OpenFPGA's reference architecture, and chapter four draws them."):
            self.play(LaggedStart(*[FadeIn(p, shift=LEFT * 0.15) for p in params], lag_ratio=0.25), run_time=2.2)
        self.wipe()

    def openfpga_method(self):
        self.heading("The OpenFPGA method", "let the router build the routing, then generate hardware that matches it")
        steps = [("bob_k6.xml", "architecture", C_VPR), ("VPR, once", "in Docker", C_VPR),
                 ("rr graph", "committed", C_GRF), ("fabric_gen.py", "walks the graph", C_PY),
                 ("bob_fabric.v", "the guest's RTL", C_RTL), ("Vivado", "into the host", C_RTL)]
        chips = VGroup(*[chip(f"{a}\n{b}", c, w=1.95, h=1.0, size=16) for a, b, c in steps])
        chips.arrange(RIGHT, buff=0.3).move_to(UP * 1.1)
        arrs = VGroup(*[arrow(chips[i].get_right(), chips[i + 1].get_left(), DIM, buff=0.04, sw=2, tip=0.12)
                        for i in range(len(chips) - 1)])
        # a tiny rr graph -> mux example
        n1 = Circle(0.22, color=C_GRF).set_fill(C_GRF, 0.2).move_to(LEFT * 4.6 + DOWN * 1.4)
        n2 = Circle(0.22, color=C_GRF).set_fill(C_GRF, 0.2).move_to(LEFT * 4.6 + DOWN * 2.3)
        n3 = Circle(0.22, color=C_GRF).set_fill(C_GRF, 0.2).move_to(LEFT * 2.6 + DOWN * 1.85)
        e1 = arrow(n1.get_right(), n3.get_left(), DIM, buff=0.05, sw=2, tip=0.12)
        e2 = arrow(n2.get_right(), n3.get_left(), DIM, buff=0.05, sw=2, tip=0.12)
        gl = txt("rr node with two drivers", 15, C_GRF).next_to(VGroup(n1, n2, n3), UP, buff=0.15)
        eq = mono("=>", 26, DIM).move_to(LEFT * 1.3 + DOWN * 1.85)
        mx = mux_symbol(C_RTL, h=1.3, w=0.55).move_to(RIGHT * 0.4 + DOWN * 1.85)
        mi = VGroup(*[mono(s, 14, INK).next_to(mx, LEFT, buff=0.1).shift(UP * dy) for s, dy in (("0", 0.4), ("a", 0.0), ("b", -0.4))])
        sel = mono("cfg[k+1:k]", 15, C_BIT).next_to(mx, UP, buff=0.1)
        ml = txt("bob_mux, 2 select bits in the configuration memory", 15, C_RTL).next_to(mx, RIGHT, buff=0.35)
        with self.narrate(
                "Here is the central idea, borrowed from OpenFPGA. Instead of inventing a routing "
                "network and hoping the router can use it, bob asks VPR to build its routing "
                "resource graph from the architecture file, once, and commits that graph."):
            self.play(LaggedStart(*[FadeIn(c) for c in chips[:3]], lag_ratio=0.3), GrowArrow(arrs[0]), GrowArrow(arrs[1]), run_time=1.6)
        with self.narrate(
                "Then fabric_gen walks the graph. Every node that has more than one possible driver "
                "becomes a multiplexer in Verilog, and its select bits become configuration bits. "
                "The result is compiled by Vivado into the host."):
            self.play(GrowArrow(arrs[2]), FadeIn(chips[3]), GrowArrow(arrs[3]), FadeIn(chips[4]), GrowArrow(arrs[4]), FadeIn(chips[5]), run_time=1.4)
            self.play(FadeIn(VGroup(n1, n2, n3, gl)), GrowArrow(e1), GrowArrow(e2), run_time=0.8)
            self.play(FadeIn(eq), FadeIn(mx), FadeIn(mi), FadeIn(sel), FadeIn(ml), run_time=0.9)
        with self.narrate(
                "So the router's model of the chip and the chip are the same object. A route VPR "
                "finds can always be loaded, and every mux in the hardware exists in the router's "
                "graph. If the architecture changes, the committed graph is stale on purpose, and "
                "every tool refuses to run until it is rebuilt."):
            self.play(Indicate(chips[2], color=C_GRF), Indicate(chips[4], color=C_RTL), run_time=1.4)
        self.wipe()

    def rr_numbers(self):
        F = self.F
        rr = F["rr"]
        self.heading("The graph, counted", "read from device.json's rr section")
        order = ["CHANX", "CHANY", "OPIN", "IPIN", "EIN", "ECY"]
        meaning = {"CHANX": "horizontal wires", "CHANY": "vertical wires", "OPIN": "block outputs",
                   "IPIN": "block inputs", "EIN": "element inputs (crossbar)", "ECY": "element carry"}
        mx = max(rr["node_types"].values())
        bars = VGroup()
        for k in order:
            v = rr["node_types"].get(k, 0)
            b = Rectangle(width=5.0 * v / mx, height=0.38, color=C_GRF, stroke_width=1.5).set_fill(C_GRF, opacity=0.4)
            row = VGroup(mono(k, 17, INK), b, mono(f"{v:,}", 16, INK), txt(meaning[k], 15, DIM))
            bars.add(row)
        for row in bars:
            row[0].move_to(ORIGIN, aligned_edge=RIGHT)
            row[1].next_to(row[0], RIGHT, buff=0.2)
            row[2].next_to(row[1], RIGHT, buff=0.15)
            row[3].next_to(row[2], RIGHT, buff=0.25)
        bars.arrange(DOWN, aligned_edge=LEFT, buff=0.16)
        for row in bars:
            row[0].align_to(bars, LEFT)
        for row in bars:
            row[1].next_to(row[0], RIGHT, buff=0.2).align_to(bars[0][1], LEFT)
            row[2].next_to(row[1], RIGHT, buff=0.15)
            row[3].next_to(row[2], RIGHT, buff=0.25)
        bars.move_to(LEFT * 1.3 + UP * 0.4)
        tot = VGroup(
            txt(f"{rr['nodes']:,} nodes · {rr['muxes']:,} muxes · {rr['mux_bits']:,} select bits · {rr['directs']} directs (no bits)", 19, C_BIT),
            txt("directs: the carry up each column and DSP cascade, plain wires", 16, DIM),
        ).arrange(DOWN, buff=0.12).next_to(bars, DOWN, buff=0.4).set_x(0)
        with self.narrate(
                f"Counted, the graph has {rr['nodes']:,} nodes. Horizontal and vertical wire "
                f"segments, block output and input pins, and inside each logic block the element "
                f"inputs and carry nodes of its crossbar."):
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in bars], lag_ratio=0.2), run_time=2.0)
        with self.narrate(
                f"{rr['muxes']:,} of those nodes have a choice of drivers, so the fabric has "
                f"{rr['muxes']:,} multiplexers and {rr['mux_bits']:,} select bits. The {rr['directs']} "
                f"direct connections, the carry chains and the DSP cascade, have no choice and so no bits."):
            self.play(FadeIn(tot, shift=UP * 0.15), run_time=0.8)
        self.wipe()
