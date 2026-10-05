"""Chapter 04 - Routing: channels, L4 wires, Wilton switch boxes, connection boxes, the bob_mux
encoding, the dark fabric, the host implementation, a real routed net, measured delays."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bobvid.scene import *


class Ch04Routing(BobScene):
    CH = "04"
    TITLE = "Routing"
    SUBTITLE = "wires in channels, the switch and connection boxes, and the bits that choose"

    def construct(self):
        F = self.F
        self.title_card(
            "Routing is most of an FPGA's area, and most of bob's. This chapter follows a signal "
            "from a pin, along the wires, through the boxes that join them, to another block.")
        self.channels(F)
        self.switchbox(F)
        self.connbox(F)
        self.encoding(F)
        self.fanin(F)
        self.hostmux()
        self.routed(F)
        self.delays(F)
        self.files_card(
            "The mux cell is written by hand and checked against its old behavioural table at every "
            "width; every instance is generated; and the fabric testbench routes random netlists and "
            "compares every output with the model after every clock.",
            [("hw/src/fabric/bob_mux.v", "LUT6 / MUXF7 / MUXF8 mux"),
             ("software/bob/vpr_arch.py", "W, L, Fs, fc"),
             ("hw/scripts/delays.tcl", "measures hops on the build")],
            [("bob_fabric.v", "one bob_mux per driven rr node"),
             ("device.json rr.muxes", "[node, chain_lo, width, base, inputs]"),
             ("software/bob/delays.json", "the measured delays")],
            [("sim/run_mux_sim.sh", "every width up to 40 inputs"),
             ("tb_bob [22]", "random netlists vs model.py"),
             ("tests/test_device.py", "every mux encoding")])

    # ------------------------------------------------------------------
    def tiles(self, n=3, cell=1.2, gap=1.0, origin=ORIGIN):
        g = VGroup()
        pos = {}
        for x in range(n):
            for y in range(n):
                r = Square(cell, color=C_RTL, stroke_width=2).set_fill(C_RTL, opacity=0.12)
                c = origin + np.array([x * (cell + gap), y * (cell + gap), 0])
                r.move_to(c)
                pos[(x, y)] = c
                g.add(r)
        return g, pos

    def channels(self, F):
        a = F["arch"]
        self.heading("Channels", f"W = {a['chan_width']} tracks between every row and column of tiles")
        cell, gap = 1.0, 1.0
        tiles, pos = self.tiles(3, cell, gap, origin=np.array([-5.4, -2.15, 0]))
        right = pos[(2, 0)][0] + cell / 2 + 0.6
        tracks = VGroup()
        for row in range(2):
            y0 = pos[(0, row)][1] + cell / 2 + gap / 2
            for k in range(4):
                yy = y0 - 0.33 + 0.22 * k
                tracks.add(Line([-6.4, yy, 0], [right, yy, 0], color=C_GRF, stroke_width=1.4, stroke_opacity=0.6))
        for col in range(2):
            x0 = pos[(col, 0)][0] + cell / 2 + gap / 2
            for k in range(4):
                xx = x0 - 0.33 + 0.22 * k
                tracks.add(Line([xx, -2.95, 0], [xx, 2.35, 0], color=C_GRF, stroke_width=1.4, stroke_opacity=0.6))
        sk = pos[(0, 0)][1] + cell / 2 + gap / 2 - 0.33
        l4 = Arrow([-6.3, sk, 0], [right, sk, 0], buff=0,
                   color=C_BIT, stroke_width=5, max_tip_length_to_length_ratio=0.05)
        l4b = Arrow([right, sk + (cell + gap) + 0.22, 0], [-6.3, sk + (cell + gap) + 0.22, 0], buff=0,
                    color=C_CYN, stroke_width=5, max_tip_length_to_length_ratio=0.05)
        notes = VGroup(
            VGroup(mono(f"W = {a['chan_width']}", 22, C_GRF), txt("tracks per channel (4 drawn)", 16, DIM)),
            VGroup(mono(f"L = {a['segment_length']}", 22, C_BIT), txt("a wire spans four tiles", 16, DIM)),
            VGroup(mono("unidirectional", 22, C_CYN), txt("INC wires run east / north, DEC wires west / south;\none driver each, at the wire's start", 16, DIM)),
            VGroup(mono("CHANX / CHANY", 22, INK), txt("VPR's names for horizontal and vertical wires", 16, DIM)),
        )
        for nn in notes:
            nn.arrange(DOWN, aligned_edge=LEFT, buff=0.05)
        notes.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
        fit(notes, 5.6)
        notes.move_to(RIGHT * 3.4 + DOWN * 0.3)
        with self.narrate(
                f"Between every row and column of tiles runs a channel of wires: {a['chan_width']} "
                f"tracks wide in bob. Horizontal wires are called CHANX and vertical ones CHANY, "
                f"VPR's names."):
            self.play(FadeIn(tiles, lag_ratio=0.03), run_time=0.8)
            self.play(Create(tracks, lag_ratio=0.02), run_time=1.2)
            self.play(FadeIn(notes[0]), FadeIn(notes[3]), run_time=0.6)
        with self.narrate(
                f"Each wire is {a['segment_length']} tiles long, so a signal crosses the chip in a few "
                f"hops instead of one per tile. And each wire is unidirectional: it has exactly one "
                f"driver, a multiplexer at the end where it starts. Some wires run east or north, others "
                f"west or south."):
            self.play(GrowArrow(l4), FadeIn(notes[1]), run_time=1.0)
            self.play(GrowArrow(l4b), FadeIn(notes[2]), run_time=1.0)
        self.wipe()

    def switchbox(self, F):
        self.heading("The switch box", "Wilton, Fs = 3: an arriving wire may continue straight, or turn left or right")
        c = np.array([-2.2, -0.3, 0])
        sb = Square(2.2, color=C_GRF, stroke_width=2).set_fill(C_GRF, opacity=0.08).move_to(c)
        sbl = txt("switch box", 16, C_GRF).next_to(sb, DOWN, buff=0.1).shift(RIGHT * 1.0)
        incoming = Arrow(c + LEFT * 4.0, c + LEFT * 1.1, buff=0, color=C_BIT, stroke_width=5)
        inl = mono("track 4, from the west", 16, C_BIT).next_to(incoming, UP, buff=0.1)
        outs = [
            (Arrow(c + RIGHT * 1.1, c + RIGHT * 3.6, buff=0, color=C_CYN, stroke_width=4), "straight: track 4", RIGHT),
            (Arrow(c + UP * 1.1, c + UP * 2.6, buff=0, color=C_CYN, stroke_width=4), "turn north: another track", UP),
            (Arrow(c + DOWN * 1.1, c + DOWN * 2.4, buff=0, color=C_CYN, stroke_width=4), "turn south: another track", DOWN),
        ]
        inner = VGroup(
            Line(c + LEFT * 1.1, c + RIGHT * 1.1, color=DIM, stroke_width=2),
            CubicBezier(c + LEFT * 1.1, c + LEFT * 0.3, c + UP * 0.3, c + UP * 1.1, color=DIM, stroke_width=2),
            CubicBezier(c + LEFT * 1.1, c + LEFT * 0.3, c + DOWN * 0.3, c + DOWN * 1.1, color=DIM, stroke_width=2),
        )
        lbls = VGroup()
        for ar, t, d in outs:
            lb = txt(t, 15, C_CYN)
            if d is RIGHT:
                lb.next_to(ar, DOWN, buff=0.1)
            else:
                lb.next_to(ar, RIGHT, buff=0.15)
            lbls.add(lb)
        side = VGroup(
            txt("each outgoing wire is a mux", 19, INK),
            txt("whose inputs are the wires arriving here", 19, INK),
            txt("Wilton permutes the track number on a turn,", 17, DIM),
            txt("so different tracks reach different places", 17, DIM),
            txt("(Wilton 1997; OpenFPGA's reference uses it)", 15, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.12).move_to(RIGHT * 4.3 + DOWN * 0.2)
        with self.narrate(
                "Where a horizontal and a vertical channel cross sits a switch box. A wire that ends "
                "there can continue straight on, or turn left or right: three choices, which is what "
                "Fs equals three means."):
            self.play(Create(sb), FadeIn(sbl), GrowArrow(incoming), FadeIn(inl), run_time=0.9)
            self.play(Create(inner), run_time=0.6)
            for (ar, _, _), lb in zip(outs, lbls):
                self.play(GrowArrow(ar), FadeIn(lb), run_time=0.45)
        with self.narrate(
                "Because wires are unidirectional, the box is really a set of multiplexers: each wire "
                "leaving it is driven by a mux whose inputs are the wires arriving. The Wilton pattern "
                "changes the track number when a signal turns, so that the network mixes well."):
            self.play(FadeIn(side, lag_ratio=0.2), run_time=1.6)
        self.wipe()

    def connbox(self, F):
        a = F["arch"]
        self.heading("The connection box", f"fc_in = {a['fc_in']}: a block input reaches a few of the {a['chan_width']} tracks")
        tracks = VGroup(*[Line([-5.5, 1.6 - 0.22 * k, 0], [1.0, 1.6 - 0.22 * k, 0], color=C_GRF, stroke_width=1.6, stroke_opacity=0.55)
                          for k in range(12)])
        tl = txt("a channel (12 of its tracks drawn)", 15, C_GRF).next_to(tracks, UP, buff=0.12).align_to(tracks, LEFT)
        mx = mux_symbol(C_RTL, h=1.6, w=0.55).move_to([-1.2, -1.1, 0])
        taps = [1, 4, 7, 10]
        tw = VGroup()
        for i, k in enumerate(taps):
            y = 1.6 - 0.22 * k
            x = -4.6 + 0.9 * i
            tw.add(Dot([x, y, 0], radius=0.06, color=C_BIT),
                   VMobject(color=C_BIT, stroke_width=1.8).set_points_as_corners(
                       [[x, y, 0], [x, mx.get_y() + 0.45 - 0.3 * i, 0], [mx.get_left()[0], mx.get_y() + 0.45 - 0.3 * i, 0]]))
        clb = chip("CLB\ninput pin", C_RTL, w=1.6, h=1.1, size=17).move_to([1.4, -1.1, 0])
        ar = Arrow(mx.get_right(), clb.get_left(), buff=0.05, color=C_RTL, stroke_width=3)
        enc = VGroup(
            mono("IPIN mux select:", 19, C_BIT),
            mono("  0     constant 0", 18, INK),
            mono("  1     constant 1", 18, INK),
            mono("  2+i   the i-th driving track", 18, INK),
            txt("drivers in ascending rr node id", 15, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.1).move_to(RIGHT * 4.6 + DOWN * 0.2)
        with self.narrate(
                "Blocks connect to the channels through connection boxes. A block input pin is a "
                "multiplexer too, but it can only reach a fraction of the tracks: with fc in equal to "
                "nought point one, about four of the thirty-six."):
            self.play(Create(tracks), FadeIn(tl), run_time=0.8)
            self.play(Create(tw), FadeIn(mx), GrowArrow(ar), FadeIn(clb), run_time=1.2)
        with self.narrate(
                "Its select value zero means constant zero, one means constant one, and from two "
                "upwards it picks a track. Outputs work the other way round: a block output pin "
                "appears as an input on the muxes of a tenth of the tracks beside it."):
            self.play(FadeIn(enc, lag_ratio=0.15), run_time=1.4)
        self.wipe()

    def encoding(self, F):
        self.heading("The encoding, and the dark fabric", "bob_mux.v: the same rule for all 8,095 muxes".replace("8,095", f"{F['rr']['muxes']:,}"))
        rows = VGroup(
            mono("sel 0            -> constant 0     every mux", 20, C_BIT),
            mono("sel 1            -> constant 1     block input pins only", 20, INK),
            mono("sel base + i     -> driver i       ascending node id", 20, INK),
            mono("anything larger  -> constant 0", 20, DIM),
            mono("width            =  the fewest bits that fit", 20, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.16).move_to(UP * 1.0)
        dark = VGroup(
            bold("an all-zero configuration is a dark, loop-free fabric", 22, C_CYN),
            txt("every wire and every input reads constant 0, so nothing drives anything:", 18, INK),
            txt("no combinational loop can exist, and a random test configuration cannot oscillate", 18, INK),
            txt("JPROGRAM clears the memory to exactly this state (chapter 08)", 17, DIM),
        ).arrange(DOWN, buff=0.12).next_to(rows, DOWN, buff=0.55)
        with self.narrate(
                "Every routing multiplexer in bob uses one encoding. Value zero is constant zero. On "
                "block input pins value one is constant one. After that the drivers follow in "
                "ascending node number, and any value past the last driver also reads zero."):
            self.play(FadeIn(rows, lag_ratio=0.2), run_time=1.6)
        with self.narrate(
                "The choice of zero matters more than it looks. A configuration of all zeros connects "
                "nothing to anything, so it cannot contain a combinational loop. The fabric powers up "
                "dark and safe, and JPROGRAM returns it to exactly that state."):
            self.play(FadeIn(dark, lag_ratio=0.2), run_time=1.4)
        self.wipe()

    def fanin(self, F):
        rr = F["rr"]
        self.heading("How wide the muxes are", f"{rr['muxes']:,} muxes by number of drivers · device.json")
        hist = {int(k): v for k, v in rr["fanin_hist"].items()}
        ks = sorted(hist)
        mx = max(hist.values())
        bars = VGroup()
        bw, H = 0.62, 3.6
        for i, k in enumerate(ks):
            v = hist[k]
            col = C_GRF if k != 24 else C_RTL
            b = Rectangle(width=bw, height=max(H * v / mx, 0.02), color=col, stroke_width=1.2).set_fill(col, opacity=0.5)
            b.move_to([i * (bw + 0.18), 0, 0], aligned_edge=DOWN)
            lab = mono(str(k), 14, DIM).next_to(b, DOWN, buff=0.08)
            val = mono(str(v), 12, INK).next_to(b, UP, buff=0.05)
            bars.add(VGroup(b, lab, val))
        bars.move_to(DOWN * 0.2)
        xl = txt("drivers per mux", 15, DIM).next_to(bars, DOWN, buff=0.2)
        n24 = hist.get(24, 0)
        note = txt(f"the {n24:,} muxes with 24 drivers are the crossbars' element inputs (100 CLBs × 24)", 17, C_RTL).next_to(bars, UP, buff=0.2)
        with self.narrate(
                "Most routing muxes are small: two to twelve drivers. The tall bar on the right is "
                "the crossbars. Every one of the twenty-four element inputs in each of the hundred "
                "blocks chooses among twenty-four sources."):
            self.play(LaggedStart(*[GrowFromEdge(b, DOWN) for b in bars], lag_ratio=0.08), FadeIn(xl), run_time=1.8)
            self.play(FadeIn(note), run_time=0.6)
        self.wipe()

    def hostmux(self):
        self.heading("A mux in the host (M23)", "LUT6 4:1 leaves, then MUXF7, then MUXF8: sixteen inputs in one slice (UG474)")
        leaves = VGroup(*[chip(f"LUT6\n4:1  in[{4 * k}..{4 * k + 3}]", C_RTL, w=2.1, h=0.75, size=14) for k in range(4)])
        leaves.arrange(DOWN, buff=0.22).move_to(LEFT * 4.6 + DOWN * 0.3)
        f7a = mux_symbol(C_PY, h=1.4, w=0.45).move_to([-2.3, leaves[0:2].get_y(), 0])
        f7b = mux_symbol(C_PY, h=1.4, w=0.45).move_to([-2.3, leaves[2:4].get_y(), 0])
        f8 = mux_symbol(C_GRF, h=2.4, w=0.55).move_to([-0.5, leaves.get_y(), 0])
        ws = VGroup(
            Line(leaves[0].get_right(), f7a.get_left() + UP * 0.35, color=DIM, stroke_width=2),
            Line(leaves[1].get_right(), f7a.get_left() + DOWN * 0.35, color=DIM, stroke_width=2),
            Line(leaves[2].get_right(), f7b.get_left() + UP * 0.35, color=DIM, stroke_width=2),
            Line(leaves[3].get_right(), f7b.get_left() + DOWN * 0.35, color=DIM, stroke_width=2),
            Line(f7a.get_right(), f8.get_left() + UP * 0.6, color=DIM, stroke_width=2),
            Line(f7b.get_right(), f8.get_left() + DOWN * 0.6, color=DIM, stroke_width=2),
        )
        o = Arrow(f8.get_right(), f8.get_right() + RIGHT * 1.0, buff=0, color=C_GRF, stroke_width=3)
        labs = VGroup(mono("sel[1:0]", 14, C_BIT).next_to(leaves, UP, buff=0.12),
                      mono("MUXF7 sel[2]", 14, C_BIT).next_to(f7a, UP, buff=0.12),
                      mono("MUXF8 sel[3]", 14, C_BIT).next_to(f8, UP, buff=0.12))
        side = VGroup(
            txt("wider muxes pick among 16:1 groups on sel[W-1:4]", 17, INK),
            txt("the constants are tied inputs, folded into the LUT INIT", 17, INK),
            txt("Vivado keeps the primitives one for one:", 17, INK),
            txt("routing LUTs fell by about 30%", 19, C_BIT),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.16)
        fit(side, 4.6)
        side.next_to(o, RIGHT, buff=0.35)
        with self.narrate(
                "Inside the host, each routing mux is now built by hand from AMD primitives. Four-input "
                "slices of the mux are LUT6s on the two low select bits. Two of those meet in a MUXF7, "
                "and two of those in a MUXF8. A sixteen-way mux fills exactly one slice."):
            self.play(FadeIn(leaves, lag_ratio=0.15), FadeIn(labs[0]), run_time=1.0)
            self.play(Create(ws[:4]), FadeIn(f7a), FadeIn(f7b), FadeIn(labs[1]), run_time=0.8)
            self.play(Create(ws[4:]), FadeIn(f8), FadeIn(labs[2]), GrowArrow(o), run_time=0.8)
        with self.narrate(
                "Left to itself, synthesis had spent nearly a whole LUT on each small mux. Building them "
                "from primitives cut the routing's host LUTs by about thirty percent, and together with "
                "the crossbar change it made room for the ten by ten grid."):
            self.play(FadeIn(side, lag_ratio=0.2), run_time=1.4)
        self.wipe()

    def routed(self, F):
        self.heading("A real net: btn[1] in the counter", "from the committed VPR route; each hop is one mux and its select value")
        g, cells = grid_view(F, cell=0.34, gap=0.07)
        g.move_to(LEFT * 3.0 + DOWN * 0.3)
        step = cells[(2, 1)].get_x() - cells[(1, 1)].get_x()
        hop = F["counter"]["routes"]["btn[1]"]

        def center(xy):
            x, y = xy
            ref = cells[(1, 1)].get_center()
            return ref + np.array([(x - 1) * step, (y - 1) * step, 0])

        def chan_pts(h):
            (x1, y1), (x2, y2) = h["a"], h["b"]
            if h["kind"] == "CHANX":
                yy = center((x1, y1))[1] + step / 2
                return [np.array([center((x1, y1))[0], yy, 0]), np.array([center((x2, y2))[0], yy, 0])]
            xx = center((x1, y1))[0] + step / 2
            return [np.array([xx, center((x1, y1))[1], 0]), np.array([xx, center((x2, y2))[1], 0])]

        pts = [center(hop[0]["a"])]
        for h in hop[1:-1]:
            a, b = chan_pts(h)
            if np.linalg.norm(a - pts[-1]) > np.linalg.norm(b - pts[-1]):
                a, b = b, a
            pts += [a, b]
        pts.append(center(hop[-1]["a"]))
        path = VMobject(color=C_BIT, stroke_width=5).set_points_as_corners(pts)
        src = SurroundingRectangle(cells[tuple(hop[0]["a"])], color=C_CYN, buff=0.04, stroke_width=4)
        dst = SurroundingRectangle(cells[tuple(hop[-1]["a"])], color=C_RTL, buff=0.04, stroke_width=4)
        rows = VGroup()
        for h in hop:
            if h["kind"] in ("CHANX", "CHANY"):
                s = f"{h['node']:>5} {h['kind']} ({h['a'][0]},{h['a'][1]})->({h['b'][0]},{h['b'][1]})  rr{h['node']} = {h['sel']}"
            elif h["kind"] == "OPIN":
                s = f"{h['node']:>5} OPIN  ({h['a'][0]},{h['a'][1]})   pad btn[1]"
            else:
                s = f"{h['node']:>5} IPIN  ({h['a'][0]},{h['a'][1]})   rr{h['node']} = {h['sel']}"
            rows.add(mono(s, 15, INK))
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.12).move_to(RIGHT * 3.6 + DOWN * 0.1)
        fit(rows, 6.2)
        foot = txt("each select picks the previous node among that mux's drivers", 16, DIM).next_to(rows, DOWN, buff=0.3)
        with self.narrate(
                "Here is a real route from the counter example. The reset button, btn one, enters at a "
                "pad on the west edge, at x zero, y four. Its destination is a logic block at x seven, "
                "y three, where the counter lives."):
            self.play(FadeIn(g, lag_ratio=0.004), run_time=1.0)
            self.play(Create(src), Create(dst), FadeIn(rows[0]), run_time=0.8)
        with self.narrate(
                f"VPR chose {len(hop) - 2} wires: down the west channel, east along the bottom on three "
                f"consecutive length-four wires, then up into the block. Each hop is one multiplexer, "
                f"and its configuration value selects the hop before it."):
            self.play(Create(path), run_time=2.2)
            self.play(LaggedStart(*[FadeIn(r) for r in rows[1:]], lag_ratio=0.25), run_time=1.6)
            self.play(FadeIn(foot), run_time=0.5)
        self.wipe()

    def delays(self, F):
        d = F["counter"]["delays"]
        self.heading("What a hop costs", "measured on the routed host build (hw/scripts/delays.tcl), worst case per class")
        items = [("routing mux (CHANX/CHANY)", d["mux_chan"], C_GRF, "measured"),
                 ("input mux (IPIN)", d["mux_ipin"], C_GRF, "measured"),
                 ("crossbar mux", d["mux_xbar"], C_GRF, "measured"),
                 ("LUT", d["lut"], C_RTL, "estimated"),
                 ("carry, per element", d["carry"], C_VPR, "estimated"),
                 ("flip-flop clock-to-Q", d["ff_clk_q"], C_CYN, "estimated")]
        mx = max(v for _, v, _, _ in items)
        rows = VGroup()
        for name, v, col, kind in items:
            b = Rectangle(width=6.0 * v / mx, height=0.42, color=col, stroke_width=1.2).set_fill(col, opacity=0.45)
            rows.add(VGroup(txt(name, 18, INK), b, mono(f"{v:.3f} ns", 16, INK), txt(kind, 14, DIM)))
        for r in rows:
            r[0].move_to(ORIGIN, aligned_edge=RIGHT)
        rows.arrange(DOWN, buff=0.18)
        for r in rows:
            r[0].align_to(rows, RIGHT)
        right_edge = max(r[0].get_right()[0] for r in rows)
        for r in rows:
            r[0].move_to([right_edge, r[0].get_y(), 0], aligned_edge=RIGHT)
            r[1].move_to([right_edge + 0.25, r[0].get_y(), 0], aligned_edge=LEFT)
            r[2].next_to(r[1], RIGHT, buff=0.15)
            r[3].next_to(r[2], RIGHT, buff=0.15)
        rows.move_to(DOWN * 0.1)
        note = txt("an overlay's routing is slow: every guest hop is host LUTs and host wires", 17, C_BIT).next_to(rows, DOWN, buff=0.35)
        with self.narrate(
                "And this is the price of building an FPGA out of another one. A single routing hop "
                f"costs up to {d['mux_chan']:.1f} nanoseconds, because it is a host LUT, a MUXF7 and "
                f"real host wiring. These three numbers were measured on the routed host design; the "
                f"LUT, carry and flip-flop figures are still estimates."):
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in rows], lag_ratio=0.15), run_time=1.8)
        with self.narrate(
                "VPR now routes using these delays, and chapter six shows how bob turns them into a safe "
                "clock for every design."):
            self.play(FadeIn(note), run_time=0.6)
        self.wipe()
