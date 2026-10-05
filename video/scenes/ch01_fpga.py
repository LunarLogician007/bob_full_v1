"""Chapter 01 - What an FPGA is: LUT = truth table = mux tree, flip-flops, routing, bits."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bobvid.scene import *


def mux2(color=C_RTL, h=1.0, w=0.45):
    return mux_symbol(color, h=h, w=w)


class Ch01Fpga(BobScene):
    CH = "01"
    TITLE = "What an FPGA is"
    SUBTITLE = "a lookup table is a memory; a fabric is lookup tables, wires and the bits that choose"

    def construct(self):
        self.title_card(
            "Before bob, the idea it implements. An FPGA is hardware whose function is "
            "decided by memory. This chapter builds that idea from one logic gate.")
        self.lut2()
        self.lut6()
        self.state_and_carry()
        self.routing()
        self.config_memory()
        self.ingredients()

    # ------------------------------------------------------------------
    def lut2(self):
        self.heading("A gate is a table", "any function of two inputs is four bits")
        rows = [["a", "b", "a AND b"], ["0", "0", "0"], ["0", "1", "0"], ["1", "0", "0"], ["1", "1", "1"]]
        tt = table(rows, [0.8, 0.8, 1.6], size=24, row_h=0.55, font=MONO)
        tt.move_to(LEFT * 4.6 + DOWN * 0.2)
        with self.narrate(
                "Take an AND gate. Its whole behaviour is a truth table: four rows, one for each "
                "combination of its two inputs, and one output bit per row."):
            self.play(FadeIn(tt, lag_ratio=0.1), run_time=1.2)

        # four memory cells -> mux tree
        vals = [0, 0, 0, 1]
        cells = VGroup()
        for i, v in enumerate(vals):
            sq = Square(0.55, color=C_BIT, stroke_width=2).set_fill(C_BIT, opacity=0.5 if v else 0.05)
            cells.add(VGroup(sq, mono(str(v), 22, INK).move_to(sq)))
        cells.arrange(DOWN, buff=0.22).move_to(RIGHT * 0.2 + DOWN * 0.2)
        idx = VGroup(*[mono(f"{i:02b}", 15, DIM).next_to(c, LEFT, buff=0.15) for i, c in enumerate(cells)])
        m1 = mux2().move_to(cells[0:2].get_center() + RIGHT * 1.5)
        m2 = mux2().move_to(cells[2:4].get_center() + RIGHT * 1.5)
        m3 = mux2(h=1.4).move_to([m1.get_x() + 1.5, cells.get_y(), 0])
        wires = VGroup()
        for k, c in enumerate(cells):
            m = m1 if k < 2 else m2
            yy = m.get_top()[1] - 0.3 if k % 2 == 0 else m.get_bottom()[1] + 0.3
            wires.add(Line(c.get_right(), [m.get_left()[0], yy, 0], color=DIM, stroke_width=2))
        w1 = Line(m1.get_right(), [m3.get_left()[0], m3.get_top()[1] - 0.4, 0], color=DIM, stroke_width=2)
        w2 = Line(m2.get_right(), [m3.get_left()[0], m3.get_bottom()[1] + 0.4, 0], color=DIM, stroke_width=2)
        out = Arrow(m3.get_right(), m3.get_right() + RIGHT * 1.0, buff=0, color=C_RTL, stroke_width=3)
        y = mono("y", 24, C_RTL).next_to(out, RIGHT, buff=0.1)
        sb = mono("b", 20, C_CYN).next_to(VGroup(m1, m2), DOWN, buff=0.35)
        sa = mono("a", 20, C_CYN).next_to(m3, DOWN, buff=0.75)
        lb = VGroup(DashedLine(sb.get_top(), m2.get_bottom(), color=C_CYN, stroke_width=1.5),
                    DashedLine(m2.get_top(), m1.get_bottom(), color=C_CYN, stroke_width=1.5))
        la = DashedLine(sa.get_top(), m3.get_bottom(), color=C_CYN, stroke_width=1.5)
        tree = VGroup(cells, idx, m1, m2, m3, wires, w1, w2, out, y, sb, sa, lb, la)
        lab = txt("a LUT: memory cells + a multiplexer tree", 19, C_BIT).next_to(tree, UP, buff=0.3)
        with self.narrate(
                "Store those four output bits in four memory cells. Then let the inputs choose "
                "which cell to read, with a tree of two-way multiplexers: b picks within each "
                "pair, a picks between the pairs. This circuit is called a lookup table, or LUT."):
            self.play(FadeIn(cells, lag_ratio=0.2), FadeIn(idx), run_time=1.0)
            self.play(FadeIn(VGroup(m1, m2, m3)), Create(wires), Create(w1), Create(w2), run_time=1.0)
            self.play(GrowArrow(out), FadeIn(y), FadeIn(VGroup(sa, sb, la, lb)), FadeIn(lab), run_time=0.8)

        with self.narrate(
                "Apply a equals one and b equals one, and the tree reads the last cell, which "
                "holds a one. Change the contents of the cells, and the same circuit becomes "
                "an OR gate, or an exclusive OR, or any other function of two inputs."):
            for r in range(1, 5):
                rowbox = SurroundingRectangle(tt[r + 1], color=C_CYN, buff=0.06)   # tt[1] is the rule
                hl = SurroundingRectangle(cells[r - 1], color=C_CYN, buff=0.06)
                self.play(Create(rowbox), Create(hl), run_time=0.35)
                self.play(Indicate(y, color=C_BIT if vals[r - 1] else DIM), run_time=0.45)
                self.play(FadeOut(rowbox), FadeOut(hl), run_time=0.2)
            or_vals = [0, 1, 1, 1]
            new = VGroup()
            for c, v in zip(cells, or_vals):
                sq = c[0].copy().set_fill(C_BIT, opacity=0.5 if v else 0.05)
                new.add(VGroup(sq, mono(str(v), 22, INK).move_to(sq)))
            orl = txt("same circuit, new contents: a OR b", 19, C_PY).next_to(tree, DOWN, buff=0.25)
            self.play(Transform(cells, new), FadeIn(orl), run_time=0.8)
        self.wipe()

    def lut6(self):
        self.heading("LUT6: 64 bits, any function of six inputs", "bob's logic element has one, as AMD 7-series parts do (UG474)")
        bits = [1 if (i & 3) == 3 else 0 for i in range(64)]
        grid = VGroup()
        for i in range(64):
            sq = Square(0.36, color=C_BIT if bits[i] else FAINT, stroke_width=1.4)
            sq.set_fill(C_BIT, opacity=0.6 if bits[i] else 0)
            grid.add(sq)
        grid.arrange_in_grid(rows=8, cols=8, buff=0.05).move_to(LEFT * 3.4 + DOWN * 0.25)
        nums = VGroup(*[mono(str(r * 8), 12, DIM).next_to(grid[r * 8], LEFT, buff=0.12) for r in range(8)])
        hexs = mono("INIT = 64'h8888_8888_8888_8888", 24, C_BIT).move_to(RIGHT * 3.0 + UP * 1.2)
        why = VGroup(
            txt("bit i of INIT = f(i5 i4 i3 i2 i1 i0) where i = the input bits", 18, INK),
            txt("AND of i0 and i1: bit i is 1 when i ends in binary 11", 18, INK),
            txt("so every nibble is 1000 = 8, sixteen times", 18, INK),
            txt("2^6 = 64 bits: 2^64 possible functions", 18, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.2).next_to(hexs, DOWN, buff=0.45).align_to(hexs, LEFT)
        with self.narrate(
                "A six-input LUT works the same way with sixty-four cells, so it can compute any "
                "function at all of six inputs. Its contents are written as one 64-bit number, "
                "called INIT, exactly as AMD's own tools write it."):
            self.play(FadeIn(grid, lag_ratio=0.01), FadeIn(nums), run_time=1.4)
        with self.narrate(
                "For an AND of inputs zero and one, bit i of INIT is one whenever the low two bits "
                "of i are both one. Every group of four bits reads one, zero, zero, zero, which is "
                "an eight in hexadecimal, so the whole table is sixteen eights."):
            self.play(Write(hexs), run_time=1.0)
            self.play(LaggedStart(*[FadeIn(w, shift=UP * 0.1) for w in why], lag_ratio=0.3), run_time=2.0)
        self.wipe()

    def state_and_carry(self):
        self.heading("Memory and arithmetic", "a flip-flop for state, a carry chain for adding")
        lut = chip("LUT6", C_RTL, w=1.8, h=1.6, size=26, weight=BOLD).move_to(LEFT * 3.6 + DOWN * 0.3)
        ins = VGroup(*[Line(lut.get_left() + LEFT * 0.8 + UP * (0.6 - 0.24 * k), lut.get_left() + UP * (0.6 - 0.24 * k),
                            color=DIM, stroke_width=2) for k in range(6)])
        ff = chip("FF", C_CYN, w=1.4, h=1.6, size=24, weight=BOLD).move_to(RIGHT * 0.6 + DOWN * 0.3)
        ff.add(mono("D", 16, DIM).move_to(ff.get_left() + RIGHT * 0.2),
               mono("Q", 16, DIM).move_to(ff.get_right() + LEFT * 0.2))
        mx = mux_symbol(C_BIT, h=1.2, w=0.5).move_to(RIGHT * 2.6 + DOWN * 0.3)
        w1 = Line(lut.get_right(), ff.get_left(), color=DIM, stroke_width=2)
        byp = Line(lut.get_right() + RIGHT * 0.4, lut.get_right() + RIGHT * 0.4 + DOWN * 1.2, color=DIM, stroke_width=2)
        byp2 = Line(byp.get_end(), [mx.get_left()[0], byp.get_end()[1], 0], color=DIM, stroke_width=2)
        byp3 = Line(byp2.get_end(), mx.get_left() + DOWN * 0.3, color=DIM, stroke_width=2)
        w2 = Line(ff.get_right(), mx.get_left() + UP * 0.3, color=DIM, stroke_width=2)
        o = Arrow(mx.get_right(), mx.get_right() + RIGHT * 1.0, buff=0, color=C_RTL, stroke_width=3)
        cb = Square(0.3, color=C_BIT, stroke_width=1.6).set_fill(C_BIT, opacity=0.6).next_to(mx, UP, buff=0.3)
        cbl = txt("one configuration bit: registered or not", 15, C_BIT).next_to(cb, UP, buff=0.1)
        cl = DashedLine(cb.get_bottom(), mx.get_top(), color=C_BIT, stroke_width=1.5)
        clk = txt("clock", 15, DIM).next_to(ff, DOWN, buff=0.15)
        carry = VGroup(
            Arrow(lut.get_bottom() + DOWN * 1.15, lut.get_bottom() + DOWN * 0.05, buff=0, color=C_VPR, stroke_width=3),
            Arrow(lut.get_top() + UP * 0.05, lut.get_top() + UP * 1.0, buff=0, color=C_VPR, stroke_width=3),
        )
        ccl = txt("carry in / carry out: a dedicated fast path for adders", 16, C_VPR).next_to(carry[0], DOWN, buff=0.1)
        with self.narrate(
                "A table alone has no memory, so each LUT is paired with a flip-flop, which holds a "
                "value from one clock edge to the next. One configuration bit chooses whether the "
                "output is taken straight from the LUT, or from the flip-flop."):
            self.play(FadeIn(lut), Create(ins), run_time=0.7)
            self.play(Create(w1), FadeIn(ff), FadeIn(clk), run_time=0.7)
            self.play(Create(byp), Create(byp2), Create(byp3), Create(w2), FadeIn(mx), GrowArrow(o), run_time=0.9)
            self.play(FadeIn(cb), Create(cl), FadeIn(cbl), run_time=0.6)
        with self.narrate(
                "Adding numbers through general lookup tables is slow, so FPGAs also give every LUT "
                "a dedicated carry path to its neighbour. bob copies AMD's design of that path; "
                "chapter three takes it apart."):
            self.play(GrowArrow(carry[0]), GrowArrow(carry[1]), FadeIn(ccl), run_time=1.0)
        self.wipe()

    def routing(self):
        self.heading("Routing: wires and the bits that choose them", "most of an FPGA's area, and most of bob's")
        A = chip("LUT A", C_RTL, w=1.4, h=0.9, size=20).move_to(LEFT * 4.5 + UP * 1.1)
        B = chip("LUT B", C_RTL, w=1.4, h=0.9, size=20).move_to(LEFT * 4.5 + DOWN * 1.1)
        C = chip("LUT C", C_RTL, w=1.4, h=0.9, size=20).move_to(RIGHT * 4.3 + DOWN * 0.2)
        mx = mux_symbol(C_GRF, h=2.0, w=0.6).move_to(RIGHT * 1.0 + DOWN * 0.2)
        wa = Line(A.get_right(), [mx.get_left()[0], mx.get_top()[1] - 0.5, 0], color=DIM, stroke_width=2.4)
        wb = Line(B.get_right(), [mx.get_left()[0], mx.get_bottom()[1] + 0.5, 0], color=DIM, stroke_width=2.4)
        z = mono("0", 18, DIM).move_to([mx.get_left()[0] - 0.6, mx.get_y(), 0])
        wz = Line(z.get_right(), [mx.get_left()[0], mx.get_y(), 0], color=DIM, stroke_width=2)
        wc = Arrow(mx.get_right(), C.get_left(), buff=0.05, color=DIM, stroke_width=2.4)
        sel = bits_row([0, 1], size=0.4).next_to(mx, UP, buff=0.55)
        sl = DashedLine(sel.get_bottom(), mx.get_top(), color=C_BIT, stroke_width=1.6)
        st = txt("select bits = configuration", 16, C_BIT).next_to(sel, UP, buff=0.12)
        with self.narrate(
                "Lookup tables are useless until they are connected. Between them run wires, and "
                "wherever several wires could drive one input, there is a multiplexer. Its select "
                "lines are not driven by logic: they come from configuration bits."):
            self.play(FadeIn(A), FadeIn(B), FadeIn(C), run_time=0.6)
            self.play(Create(wa), Create(wb), FadeIn(z), Create(wz), FadeIn(mx), GrowArrow(wc), run_time=1.0)
            self.play(FadeIn(sel), Create(sl), FadeIn(st), run_time=0.6)
        with self.narrate(
                "Select one, and A drives C. Select two, and B drives C. Select zero picks a "
                "constant zero, so a fabric whose bits are all zero is quiet: nothing is connected "
                "to anything. bob relies on exactly that, as chapter four shows."):
            self.play(wa.animate.set_color(C_CYN).set_stroke(width=5), wc.animate.set_color(C_CYN), run_time=0.6)
            self.wait(0.6)
            new = bits_row([1, 0], size=0.4).move_to(sel)
            self.play(Transform(sel, new), wa.animate.set_color(DIM).set_stroke(width=2.4),
                      wb.animate.set_color(C_CYN).set_stroke(width=5), run_time=0.7)
            self.wait(0.6)
            new0 = bits_row([0, 0], size=0.4).move_to(sel)
            self.play(Transform(sel, new0), wb.animate.set_color(DIM).set_stroke(width=2.4),
                      wz.animate.set_color(C_CYN), wc.animate.set_color(DIM), run_time=0.7)
        self.wipe()

    def config_memory(self):
        F = self.F
        self.heading("Configuration memory", "programming an FPGA means filling it")
        strip = bitcells(48, size=0.22, on={2, 3, 7, 11, 12, 18, 19, 25, 30, 31, 33, 40, 41, 46})
        strip.move_to(UP * 1.4)
        groups = [("LUT contents", 0, 16, C_RTL), ("flip-flop and carry flags", 16, 24, C_CYN),
                  ("routing mux selects", 24, 44, C_GRF), ("block RAM / DSP settings", 44, 48, C_PY)]
        braces = VGroup()
        for name, a, b, cc in groups:
            br = Brace(strip[a:b], DOWN, color=cc)
            lab = txt(name, 15, cc)
            fit(lab, max(strip[a:b].width * 1.25, 1.2))
            lab.next_to(br, DOWN, buff=0.1)
            braces.add(VGroup(br, lab))
        big = VGroup(
            bold(f"bob: {F['chain_width']:,} bits", 30, C_BIT),
            txt(f"{F['frames']['count']} frames × {F['frames']['words']} words × 32 bits", 20, INK),
            txt("written over JTAG; read back to prove it", 18, DIM),
        ).arrange(DOWN, buff=0.15).move_to(DOWN * 1.6)
        with self.narrate(
                "Every choice in the fabric is a bit: every truth-table entry, every flip-flop "
                "option, every multiplexer select, every setting of a memory or multiplier. "
                "Together they are the configuration memory, and a bitstream is simply its contents."):
            self.play(FadeIn(strip, lag_ratio=0.02), run_time=1.2)
            self.play(LaggedStart(*[FadeIn(b) for b in braces], lag_ratio=0.3), run_time=1.6)
        with self.narrate(
                f"bob's configuration memory holds {F['chain_width']:,} bits, cut into "
                f"{F['frames']['count']} frames of four 32-bit words. Chapters eight and nine are "
                f"about how those bits get in, and how we prove they arrived."):
            self.play(FadeIn(big, shift=UP * 0.2), run_time=0.8)
        self.wipe()

    def ingredients(self):
        self.heading("The four ingredients", "and where each one is in this film")
        items = [("Logic blocks", "LUTs, carry, flip-flops", "03", C_RTL),
                 ("Hard blocks", "block RAM and DSP multipliers", "05", C_PY),
                 ("Routing", "wires in channels and the muxes between them", "04", C_GRF),
                 ("Configuration memory", "one bit per choice, and a port to fill it", "07 · 08 · 09", C_BIT)]
        cards = VGroup()
        for name, d, ch, cc in items:
            card = VGroup(bold(name, 24, cc), txt(d, 17, INK), txt(f"chapter {ch}", 15, DIM)).arrange(DOWN, buff=0.12)
            fit(card, 5.0)
            box = RoundedRectangle(width=5.6, height=1.7, corner_radius=0.12, color=cc,
                                   stroke_width=2).set_fill(cc, opacity=0.06)
            cards.add(VGroup(box, card.move_to(box)))
        cards.arrange_in_grid(rows=2, cols=2, buff=(0.5, 0.4)).move_to(DOWN * 0.2)
        extra = txt("plus I/O pads with boundary scan, and a clock (chapter 06)", 18, DIM).next_to(cards, DOWN, buff=0.3)
        with self.narrate(
                "So an FPGA is four things: logic blocks that compute, hard blocks for what logic "
                "does badly, routing to connect them, and the configuration memory that decides "
                "all of it. bob has all four, plus I/O pads and a clock, and the rest of this film "
                "takes them one at a time."):
            self.play(LaggedStart(*[FadeIn(c, shift=UP * 0.15) for c in cards], lag_ratio=0.3), run_time=2.0)
            self.play(FadeIn(extra), run_time=0.5)
        self.wipe()
