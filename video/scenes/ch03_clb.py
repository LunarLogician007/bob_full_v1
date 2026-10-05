"""Chapter 03 - The CLB: cluster, crossbar, fracturable LUT6, carry, flip-flops, Double Duty,
the 109 bits of an element, and how it all sits in the host's CFGLUT5s."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bobvid.scene import *


def wire(a, b, color=DIM, sw=2.2):
    return Line(a, b, color=color, stroke_width=sw)


def elbow(a, b, color=DIM, sw=2.2, first="h"):
    """Two-segment wire: horizontal then vertical (or the other way)."""
    mid = np.array([b[0], a[1], 0]) if first == "h" else np.array([a[0], b[1], 0])
    return VMobject(color=color, stroke_width=sw).set_points_as_corners([a, mid, b])


class Ch03Clb(BobScene):
    CH = "03"
    TITLE = "The CLB"
    SUBTITLE = "four fracturable logic elements behind a full crossbar (UG474, OpenFPGA k6_frac_N10)"

    def construct(self):
        F = self.F
        self.title_card(
            "The configurable logic block is where a design's logic actually runs. bob's follows "
            "AMD's 7-series slice for the element, and OpenFPGA's clustered architecture for the block.")
        self.cluster(F)
        self.crossbar(F)
        self.element()
        self.carry()
        self.flipflops()
        self.double_duty()
        self.bits(F)
        self.worked()
        self.host(F)
        self.files_card(
            "The element is ble dot s v; the crossbar and the cluster are generated into the fabric; and "
            "the cluster testbench checks every flag, every LUT mode and every crossbar value "
            "against the Python model, at LUT size six and again at four.",
            [("hw/src/clb/ble.sv", "one logic element"),
             ("hw/src/clb/lxor.v", "a crossbar mux: CFGLUT5 leaves + OR"),
             ("hw/src/core/lut_loader.v", "shifts tables in as frames land")],
            [("bob_clb in bob_fabric.v", "4 elements + 24 crossbar muxes"),
             ("bob_params.vh", "BOB_ELE_* field offsets")],
            [("hw/tb/tb_clb.sv", "4032 checks vs model.py, K = 6 and 4"),
             ("software/bob/model.py", "the cycle model"),
             ("hwtest double-duty, init-srval", "on the board")])

    # ------------------------------------------------------------------
    def cluster(self, F):
        cl = F["cluster"]
        self.heading("A cluster of four elements", f"N = {cl['n']}, {cl['i']} inputs, {2 * cl['n']} outputs, a {cl['xbar']} crossbar")
        box = RoundedRectangle(width=8.4, height=4.5, corner_radius=0.15, color=C_RTL, stroke_width=2.5).set_fill(C_RTL, opacity=0.04)
        box.move_to(UP * 0.05)
        xb = Rectangle(width=1.5, height=3.8, color=C_GRF, stroke_width=2).set_fill(C_GRF, opacity=0.12).move_to(box.get_center() + LEFT * 2.2)
        xbl = txt("crossbar", 17, C_GRF).rotate(PI / 2).move_to(xb)
        els = VGroup(*[chip(f"element {e}\nLUT6 · carry · 2 FF", C_RTL, w=2.6, h=0.85, size=15) for e in range(4)])
        els.arrange(UP, buff=0.14).move_to(box.get_center() + RIGHT * 0.9)
        ins = VGroup(*[wire(xb.get_left() + LEFT * 1.1 + UP * (1.8 - 0.24 * k), xb.get_left() + UP * (1.8 - 0.24 * k), DIM, 1.4) for k in range(16)])
        inl = mono("I[0..15]", 16, INK).next_to(ins, LEFT, buff=0.1)
        e2x = VGroup()
        for e in els:
            for k in range(3):
                y = e.get_y() + 0.25 - 0.25 * k
                e2x.add(wire([xb.get_right()[0], y, 0], [e.get_left()[0], y, 0], DIM, 1.2))
        outs = VGroup()
        for e in els:
            for k in (0.15, -0.15):
                outs.add(wire([e.get_right()[0], e.get_y() + k, 0], [box.get_right()[0] + 0.7, e.get_y() + k, 0], C_RTL, 1.6))
        outl = mono("O[0..7]", 16, INK).next_to(outs, RIGHT, buff=0.1)
        fb = VGroup()
        for i, e in enumerate(els):
            y = e.get_y() + 0.15
            x1 = box.get_right()[0] - 0.4 - 0.08 * i
            fb.add(VMobject(color=C_CYN, stroke_width=1.4).set_points_as_corners(
                [[x1, y, 0], [x1, box.get_top()[1] - 0.15 - 0.05 * i, 0],
                 [xb.get_x() + 0.3 - 0.1 * i, box.get_top()[1] - 0.15 - 0.05 * i, 0], [xb.get_x() + 0.3 - 0.1 * i, xb.get_top()[1], 0]]))
        fbl = txt("feedback: element outputs back into the crossbar", 14, C_CYN).next_to(box, UP, buff=0.05).align_to(box, LEFT)
        cin = Arrow(els[0].get_bottom() + DOWN * 0.75, els[0].get_bottom(), buff=0, color=C_VPR, stroke_width=3)
        cout = Arrow(els[3].get_top(), els[3].get_top() + UP * 0.75, buff=0, color=C_VPR, stroke_width=3)
        cinl = mono("cin (from the CLB below)", 14, C_VPR).next_to(cin, RIGHT, buff=0.1)
        chain = VGroup(*[Arrow(els[i].get_top(), els[i + 1].get_bottom(), buff=0.02, color=C_VPR, stroke_width=2.5,
                               max_tip_length_to_length_ratio=0.5) for i in range(3)])
        with self.narrate(
                f"A bob logic block is a cluster of {cl['n']} logic elements. {cl['i']} signals come "
                f"in from the routing, and {2 * cl['n']} leave, two from each element."):
            self.play(Create(box), FadeIn(els, lag_ratio=0.2), run_time=1.2)
            self.play(Create(ins), FadeIn(inl), Create(outs), FadeIn(outl), run_time=1.0)
        with self.narrate(
                "Between the inputs and the elements sits a full crossbar: any element input can "
                "take any of the sixteen block inputs, or any element's output fed back. "
                "Neighbouring logic talks through it without using the general routing at all."):
            self.play(FadeIn(xb), FadeIn(xbl), Create(e2x), run_time=1.0)
            self.play(Create(fb), FadeIn(fbl), run_time=1.0)
        with self.narrate(
                "A carry chain runs up through the four elements, and on into the block above, "
                "over a dedicated wire with no configuration bits at all."):
            self.play(GrowArrow(cin), FadeIn(cinl), *[GrowArrow(c) for c in chain], GrowArrow(cout), run_time=1.4)
        with self.narrate(
                "Why four? It was measured, not guessed. A sweep built clusters of four, six, eight "
                "and ten elements, with full and half crossbars. Bigger clusters cost more host logic "
                "per element, because every crossbar mux is host logic, and half crossbars needed far "
                "wider channels. Four with a full crossbar won."):
            note = txt("sweep.py: N = 4 / 6 / 8 / 10, full or half crossbar → N = 4, full", 17, C_BIT).move_to([0, -2.72, 0]).align_to(box, LEFT)
            self.play(FadeIn(note), run_time=0.6)
        self.wipe()

    def crossbar(self, F):
        n_src = F["xbar_sources"]
        self.heading("One crossbar mux", f"{n_src} sources + two constants, chosen by a {F['cluster']['xbar_width']}-bit select")
        mx = mux_symbol(C_GRF, h=4.4, w=0.9).move_to(RIGHT * 0.3 + DOWN * 0.3)
        vals = [("0", "const 0", DIM), ("1", "const 1", DIM)] + \
               [(str(2 + i), f"I[{i}]", INK) for i in range(3)] + [("…", "…", DIM)] + \
               [(str(2 + 15), "I[15]", INK), (str(2 + 16), "O[0]  (element 0, out 0)", C_CYN), ("…", "…", DIM),
                (str(2 + n_src - 1), "O[7]  (element 3, out 1)", C_CYN)]
        rows = VGroup()
        for v, s, c in vals:
            rows.add(VGroup(mono(v.rjust(2), 16, C_BIT), txt(s, 16, c)).arrange(RIGHT, buff=0.3))
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.12).next_to(mx, LEFT, buff=0.5)
        sel = mono("e0.x0 = 5'h2", 22, C_BIT).next_to(mx, UP, buff=0.2)
        out = Arrow(mx.get_right(), mx.get_right() + RIGHT * 1.3, buff=0, color=C_RTL, stroke_width=3)
        outl = txt("element 0, LUT input 0", 17, C_RTL).next_to(out, RIGHT, buff=0.1)
        cnt = txt(f"{F['cluster']['n']} elements × 6 inputs = 24 such muxes per CLB", 17, DIM).next_to(out, DOWN, buff=0.5).align_to(out, LEFT)
        with self.narrate(
                f"Each element input has its own crossbar mux. Its select is five bits. Value zero "
                f"means constant zero, one means constant one, and two onward pick the {n_src} sources "
                f"in order: the sixteen block inputs, then the eight element outputs."):
            self.play(FadeIn(mx), GrowArrow(out), FadeIn(outl), run_time=0.8)
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.1) for r in rows], lag_ratio=0.12), run_time=1.6)
        hl = SurroundingRectangle(rows[2], color=C_BIT, buff=0.05)
        with self.narrate(
                "So the feature e0 dot x0 equal to two connects block input zero to element zero's first "
                "LUT input. Six inputs on four elements is twenty-four such muxes in every block."):
            self.play(FadeIn(sel), Create(hl), run_time=0.8)
            self.play(FadeIn(cnt), run_time=0.6)
        self.wipe()

    def element(self):
        self.heading("One logic element", "a fracturable LUT6, the carry, and two flip-flops (ble.sv)")
        ins = VGroup(*[mono(f"i{k}", 15, INK) for k in range(6)]).arrange(DOWN, buff=0.18).move_to(LEFT * 6.3 + UP * 0.35)
        lo = chip("CFGLUT5\nlo: INIT[31:0]", C_RTL, w=1.9, h=0.9, size=15).move_to(LEFT * 4.2 + UP * 1.05)
        hi = chip("CFGLUT5\nhi: INIT[63:32]", C_RTL, w=1.9, h=0.9, size=15).move_to(LEFT * 4.2 + DOWN * 0.25)
        f7 = mux_symbol(C_RTL, h=1.3, w=0.45).move_to(LEFT * 2.5 + UP * 0.4)
        f7l = mono("MUXF7", 12, DIM).next_to(f7, UP, buff=0.05)
        s7 = mono("i5 | frac", 13, C_BIT).next_to(f7, DOWN, buff=0.1)
        w_in = VGroup(*[wire(ins[k].get_right() + RIGHT * 0.05, [lo.get_left()[0], lo.get_y() + 0.3 - 0.12 * k, 0], DIM, 1.2) for k in range(5)],
                      *[wire(ins[k].get_right() + RIGHT * 0.05, [hi.get_left()[0], hi.get_y() + 0.3 - 0.12 * k, 0], DIM, 1.2) for k in range(5)])
        w_lo = wire(lo.get_right(), [f7.get_left()[0], f7.get_y() + 0.35, 0])
        w_hi = wire(hi.get_right(), [f7.get_left()[0], f7.get_y() - 0.35, 0])
        cy = chip("MUXCY\nXORCY", C_VPR, w=1.3, h=1.0, size=15).move_to(LEFT * 0.6 + UP * 0.4)
        o6 = wire(f7.get_right(), cy.get_left(), C_RTL)
        o6l = mono("O6", 14, C_RTL).next_to(o6, UP, buff=0.05)
        o5 = elbow(lo.get_right() + RIGHT * 0.25, [lo.get_right()[0] + 0.25, -1.9, 0], C_RTL, first="v")
        o5b = wire([lo.get_right()[0] + 0.25, -1.9, 0], [2.4, -1.9, 0], C_RTL)
        o5l = mono("O5", 14, C_RTL).next_to(o5b, UP, buff=0.05).shift(LEFT * 2.5)
        cm = mux_symbol(C_BIT, h=1.0, w=0.4).move_to(RIGHT * 1.1 + UP * 0.4)
        w_cy = wire(cy.get_right(), cm.get_left() + UP * 0.2)
        ff1 = chip("FF", C_CYN, w=0.9, h=0.9, size=18, weight=BOLD).move_to(RIGHT * 2.85 + UP * 0.4)
        ff2 = chip("FF2", C_CYN, w=0.9, h=0.9, size=18, weight=BOLD).move_to(RIGHT * 2.85 + DOWN * 1.9)
        w_cm = wire(cm.get_right(), ff1.get_left())
        om1 = mux_symbol(C_BIT, h=0.9, w=0.35).move_to(RIGHT * 4.4 + UP * 0.4)
        om2 = mux_symbol(C_BIT, h=0.9, w=0.35).move_to(RIGHT * 4.4 + DOWN * 1.9)
        w_f1 = wire(ff1.get_right(), om1.get_left() + UP * 0.2)
        w_f2 = wire(ff2.get_right(), om2.get_left() + UP * 0.2)
        byp1 = elbow(cm.get_right() + RIGHT * 0.25, [om1.get_left()[0], om1.get_y() - 0.2, 0], DIM, first="v")
        byp1.set_points_as_corners([cm.get_right() + RIGHT * 0.25, [cm.get_right()[0] + 0.25, -0.55, 0], [om1.get_left()[0] - 0.3, -0.55, 0], [om1.get_left()[0] - 0.3, om1.get_y() - 0.2, 0], [om1.get_left()[0], om1.get_y() - 0.2, 0]])
        o5_to2 = wire([2.4, -1.9, 0], ff2.get_left(), C_RTL)
        byp2 = VMobject(color=DIM, stroke_width=2.2).set_points_as_corners([[2.25, -1.9, 0], [2.25, -2.6, 0], [3.7, -2.6, 0], [3.7, -2.1, 0], [om2.get_left()[0], -2.1, 0]])
        o1 = Arrow(om1.get_right(), om1.get_right() + RIGHT * 0.9, buff=0, color=C_RTL, stroke_width=3)
        o2 = Arrow(om2.get_right(), om2.get_right() + RIGHT * 0.9, buff=0, color=C_RTL, stroke_width=3)
        o1l = mono("out0", 15, C_RTL).next_to(o1, UP, buff=0.04)
        o2l = mono("out1", 15, C_RTL).next_to(o2, UP, buff=0.04)
        cin = Arrow(cy.get_bottom() + DOWN * 0.8, cy.get_bottom(), buff=0, color=C_VPR, stroke_width=2.5)
        cout = Arrow(cy.get_top(), cy.get_top() + UP * 0.8, buff=0, color=C_VPR, stroke_width=2.5)
        cinl = mono("cin", 13, C_VPR).next_to(cin, LEFT, buff=0.06)
        coutl = mono("cout", 13, C_VPR).next_to(cout, LEFT, buff=0.06)
        o5cm = wire([cm.get_left()[0] - 0.25, -1.9, 0], [cm.get_left()[0] - 0.25, cm.get_y() - 0.2, 0], C_RTL, 1.4)
        o5cm2 = wire([cm.get_left()[0] - 0.25, cm.get_y() - 0.2, 0], cm.get_left() + DOWN * 0.2, C_RTL, 1.4)

        lut_g = VGroup(ins, lo, hi, f7, f7l, s7, w_in, w_lo, w_hi)
        with self.narrate(
                "Inside one element, the six-input LUT is stored as two halves of thirty-two bits, "
                "each addressed by inputs zero to four. Input five chooses between the halves, through "
                "a MUXF7, exactly as in AMD's LUT6."):
            self.play(FadeIn(ins), FadeIn(lo), FadeIn(hi), Create(w_in), run_time=1.2)
            self.play(Create(w_lo), Create(w_hi), FadeIn(f7), FadeIn(f7l), FadeIn(s7), run_time=0.8)
        with self.narrate(
                "Set the flag frac, and the select is forced high. Now the element is two five-input "
                "LUTs sharing their inputs: O6 is the upper half, and O5, the lower half, comes out "
                "separately. This is the fracturable LUT, UG474's LUT6 underscore 2."):
            self.play(Create(o6), FadeIn(o6l), Create(o5), Create(o5b), FadeIn(o5l), run_time=1.0)
            self.play(Indicate(s7, color=C_BIT), run_time=0.8)
        with self.narrate(
                "O6 feeds the carry logic and a small mux that picks what the first flip-flop stores: "
                "the carry sum, O6, or O5. O5 feeds the second flip-flop. And a last mux on each "
                "side, set by a configuration bit, picks whether the output is registered or not."):
            self.play(FadeIn(cy), GrowArrow(cin), GrowArrow(cout), FadeIn(cinl), FadeIn(coutl), run_time=0.8)
            self.play(Create(w_cy), FadeIn(cm), Create(o5cm), Create(o5cm2), Create(w_cm), FadeIn(ff1), run_time=0.9)
            self.play(Create(o5_to2), FadeIn(ff2), run_time=0.6)
            self.play(Create(w_f1), Create(w_f2), Create(byp1), Create(byp2), FadeIn(om1), FadeIn(om2), run_time=0.9)
            self.play(GrowArrow(o1), GrowArrow(o2), FadeIn(o1l), FadeIn(o2l), run_time=0.6)
        self.wipe()

    def carry(self):
        self.heading("The carry chain", "UG474's MUXCY and XORCY, in every element")
        eq = code_block([
            ("propagate p = O6", C_RTL),
            ("generate  d = cy_di_sel ? O5 : i0", C_RTL),
            ("cout = p ? cin : d        // MUXCY", C_VPR),
            ("sum  = p ^ cin            // XORCY", C_VPR),
        ], size=19).move_to(LEFT * 3.2 + UP * 0.9)
        ex = txt("for a + b, bit k:  p = a ⊕ b (the LUT),  d = a", 18, DIM).next_to(eq, DOWN, buff=0.35).align_to(eq, LEFT)
        # ripple: 4 elements stacked, carry rising
        a, b = 0b0111, 0b0001
        cells = VGroup()
        for k in range(4):
            ak, bk = (a >> k) & 1, (b >> k) & 1
            cells.add(chip(f"bit {k}: a={ak} b={bk}", C_RTL, w=2.6, h=0.62, size=15))
        cells.arrange(UP, buff=0.42).move_to(RIGHT * 3.6 + DOWN * 0.3)
        carries = VGroup(*[Arrow(cells[k].get_top(), cells[k + 1].get_bottom(), buff=0.02, color=FAINT, stroke_width=3,
                                 max_tip_length_to_length_ratio=0.5) for k in range(3)])
        sums = VGroup()
        c = 0
        cs = []
        for k in range(4):
            ak, bk = (a >> k) & 1, (b >> k) & 1
            s = ak ^ bk ^ c
            c = (ak & bk) | (c & (ak ^ bk))
            cs.append(c)
            sums.add(mono(f"sum {s}", 16, C_BIT).next_to(cells[k], RIGHT, buff=0.2))
        title = mono("0111 + 0001 = 1000", 20, C_BIT).next_to(cells, UP, buff=0.3)
        with self.narrate(
                "For addition, the LUT computes the propagate signal: for bit k of a plus b, that is "
                "a exclusive-or b. The carry multiplexer then either passes the incoming carry along, "
                "when propagate is one, or generates a new carry from a. An exclusive-or makes the sum."):
            self.play(FadeIn(eq, lag_ratio=0.2), run_time=1.4)
            self.play(FadeIn(ex), run_time=0.6)
        with self.narrate(
                "Seven plus one shows the point. The carry ripples up through all four elements with no "
                "trip through the general routing, and on into the logic block above. That is why "
                "synthesis maps every adder onto this chain."):
            self.play(FadeIn(cells, lag_ratio=0.15), FadeIn(title), run_time=0.8)
            for k in range(4):
                anims = [FadeIn(sums[k])]
                if k < 3 and cs[k]:
                    anims.append(carries[k].animate.set_color(C_VPR))
                elif k < 3:
                    anims.append(FadeIn(carries[k]))
                self.play(*anims, run_time=0.5)
        self.wipe()

    def flipflops(self):
        self.heading("Two flip-flops, in priority order", "FDRE / FDSE semantics (UG474); INIT and SRVAL are separate since M26")
        code = code_block([
            ("always @(posedge clk)", DIM),
            ("  if (gsr)                    q <= ff_init;     // startup, GRESTORE", C_ERR),
            ("  else if (gwe && gce) begin                    // writes enabled, user clock", C_CYN),
            ("    if (ff_sr_en && sr)       q <= ff_rstval;   // synchronous reset: SRVAL", C_BIT),
            ("    else if (!ff_ce_en || ce) q <= d;           // clock enable", C_RTL),
            ("  end", DIM),
        ], size=17).move_to(UP * 0.9)
        ladder = VGroup(
            chip("1  GSR → INIT", C_ERR, w=3.0, h=0.6, size=17),
            chip("2  GWE and gce, else hold", C_CYN, w=3.0, h=0.6, size=17),
            chip("3  SR → SRVAL", C_BIT, w=3.0, h=0.6, size=17),
            chip("4  CE → D", C_RTL, w=3.0, h=0.6, size=17),
        ).arrange(RIGHT, buff=0.2).next_to(code, DOWN, buff=0.45)
        fix = VGroup(
            mono("reg q = 1'b1;   always @(posedge clk) if (rst) q <= 1'b0; ...", 17, INK),
            txt("until M25 one bit was both values, so this register started at 0. M26: INIT = 1, SRVAL = 0, as on a real FDRE.", 17, DIM),
        ).arrange(DOWN, buff=0.12).next_to(ladder, DOWN, buff=0.4)
        fit(fix, 13)
        with self.narrate(
                "Both flip-flops follow AMD's FDRE and FDSE rules, in strict priority. Global set-reset "
                "comes first and loads the flip-flop's INIT value; it is held during configuration and "
                "released at startup. Nothing else can change the flip-flop unless writes are enabled "
                "and the user clock enable is high."):
            self.play(FadeIn(code, lag_ratio=0.1), run_time=1.4)
            self.play(FadeIn(ladder[0]), FadeIn(ladder[1]), run_time=0.8)
        with self.narrate(
                "Then the routed synchronous reset loads the reset value, and only then does the clock "
                "enable let D through. The CE and SR pins are shared by all eight flip-flops of a block, "
                "as one slice shares them on AMD's parts."):
            self.play(FadeIn(ladder[2]), FadeIn(ladder[3]), run_time=0.8)
        with self.narrate(
                "Milestone 26 split the initial value from the reset value. A register declared as one, "
                "with a reset to zero, now starts at one, as it would on real silicon. The board check "
                "init-srval proves it."):
            self.play(FadeIn(fix, shift=UP * 0.1), run_time=0.8)
        self.wipe()

    def double_duty(self):
        self.heading("Double Duty (M24)", "after Pun, Dai, Zgheib, Iyer, Boutros, Betz, Abdelfattah, FPL 2025")
        left = VGroup(bold("normal adder element", 20, DIM),
                      chip("LUT6: p = a ⊕ b", C_RTL, w=3.2, h=0.8, size=17),
                      chip("carry", C_VPR, w=3.2, h=0.6, size=17),
                      txt("the LUT is used up by the adder", 16, DIM)).arrange(DOWN, buff=0.22).move_to(LEFT * 3.5 + DOWN * 0.1)
        right = VGroup(bold("with dd = 1", 20, C_BIT),
                       chip("i4 = A, i5 = B  →  carry directly", C_VPR, w=4.2, h=0.7, size=17),
                       chip("LUT: free, a function of i0..i3 → out1", C_RTL, w=4.2, h=0.8, size=17),
                       txt("p = A ⊕ B ⊕ cy_di_sel (INV_B: subtract),  d = A", 16, DIM)).arrange(DOWN, buff=0.22).move_to(RIGHT * 3.2 + DOWN * 0.1)
        res = txt("bob's packer fills those free LUTs: 13.2% fewer elements over the examples (VPR: 4.7%)", 18, C_BIT).to_edge(DOWN, buff=1.3)
        with self.narrate(
                "An adder normally spends a whole LUT computing a exclusive-or b. Double Duty, from a "
                "2025 paper, feeds the adder's two operands straight from two element inputs instead."):
            self.play(FadeIn(left, lag_ratio=0.2), run_time=1.2)
            self.play(FadeIn(right[0]), FadeIn(right[1]), run_time=0.8)
        with self.narrate(
                "The LUT is then free, and its lower half drives the element's second output as an "
                "independent four-input function, beside the adder. One flag, dd, turns it on."):
            self.play(FadeIn(right[2]), FadeIn(right[3]), run_time=0.9)
        with self.narrate(
                "VPR's packer cannot aim for it, so it saved under five percent. bob's own packer fills "
                "the free LUTs of adder elements on purpose, and used thirteen point two percent fewer "
                "elements over the example designs."):
            self.play(FadeIn(res), run_time=0.7)
        self.wipe()

    def bits(self, F):
        ef = F["element_fields"]
        self.heading("The bits of one element", f"{F['element_bits']} per element · {F['tile_widths']['clb']} per CLB tile · from device.json")
        nfl = sum(w for n, w, o, k in ef if k == "flag")
        fields = [("crossbar x0..x5 · 30 bits", 30, C_GRF), (f"flags · {nfl}", nfl, C_CYN),
                  ("INIT: the truth table · 64 bits", 64, C_RTL)]
        bar = fieldbar(fields, total_w=12.0, h=0.6, size=17, show_ranges=False)
        bar.move_to(UP * 1.6)
        flags = [n for n, w, o, k in ef if k == "flag"]
        meaning = {"frac": "two LUT5s", "ff_en": "out0 registered", "ff_rstval": "FF SRVAL",
                   "ff_ce_en": "FF uses CE", "ff_sr_en": "FF uses SR", "cy_en": "carry on",
                   "cy_di_sel": "generate from O5 / INV_B", "ff_d_sel": "FF stores O5",
                   "ff2_en": "out1 registered", "ff2_rstval": "FF2 SRVAL", "ff2_ce_en": "FF2 uses CE",
                   "ff2_sr_en": "FF2 uses SR", "dd": "Double Duty", "ff_init": "FF INIT (M26)",
                   "ff2_init": "FF2 INIT (M26)"}
        rows = VGroup(*[VGroup(mono(f, 15, C_CYN), txt(meaning.get(f, ""), 14, DIM)).arrange(RIGHT, buff=0.15) for f in flags])
        cols = VGroup(rows[:8].copy().arrange(DOWN, aligned_edge=LEFT, buff=0.1),
                      rows[8:].copy().arrange(DOWN, aligned_edge=LEFT, buff=0.1)).arrange(RIGHT, buff=0.9, aligned_edge=UP)
        cols.next_to(bar, DOWN, buff=0.45)
        tot = txt(f"4 × {F['element_bits']} + 3 padding = {F['tile_widths']['clb']} bits per CLB, then the tile's routing muxes", 17, C_BIT).next_to(cols, DOWN, buff=0.3)
        with self.narrate(
                f"Every element is configured by exactly {F['element_bits']} bits: six crossbar selects "
                f"of five bits, {len(flags)} flags, and sixty-four bits of truth table."):
            self.play(FadeIn(bar, lag_ratio=0.1), run_time=1.2)
        with self.narrate(
                "The flags are the choices you have just seen: fracture, carry on, the generate source, "
                "which value each flip-flop stores, whether each output is registered, whether each "
                "flip-flop uses the clock enable and the reset, the two reset values and two initial "
                "values, and Double Duty."):
            self.play(FadeIn(cols, lag_ratio=0.05), run_time=1.6)
        with self.narrate(
                f"Four elements and three bits of padding make {F['tile_widths']['clb']} bits per block. "
                f"The routing multiplexers of that tile follow them in the configuration memory."):
            self.play(FadeIn(tot), run_time=0.6)
        self.wipe()

    def worked(self):
        self.heading("Worked example: AND of two switches", "what the tools write for one element")
        fasm = code_block([
            ("clb_x2y3.e0.x0   = 5'h2                 // LUT input 0  <- I[0]", C_GRF),
            ("clb_x2y3.e0.x1   = 5'h3                 // LUT input 1  <- I[1]", C_GRF),
            ("clb_x2y3.e0.init = 64'h8888888888888888 // f = i0 & i1", C_RTL),
            ("                                        // x2..x5 = 0: const 0", DIM),
            ("                                        // flags 0: out0 = O6, unregistered", DIM),
        ], size=18).move_to(UP * 0.6)
        note = txt("FASM: one line per configuration feature, named after device.py's fields (chapter 10)", 17, DIM).next_to(fasm, DOWN, buff=0.5)
        with self.narrate(
                "Put together, an AND of two inputs in element zero of block x2 y3 is three settings. "
                "Two crossbar selects bring block inputs zero and one to LUT inputs zero and one. "
                "The truth table is sixteen eights. Everything else stays zero, which means constant "
                "inputs and an unregistered output."):
            self.play(FadeIn(fasm, lag_ratio=0.25), run_time=2.0)
            self.play(FadeIn(note), run_time=0.5)
        self.wipe()

    def host(self, F):
        self.heading("How it sits in the host (M22, M23)", "truth tables and crossbars in AMD CFGLUT5s, as ZUMA does (Brant & Lemieux, FCCM 2012)")
        cfg = chip("CFGLUT5", C_RTL, w=2.2, h=1.4, size=22, weight=BOLD).move_to(LEFT * 3.4 + UP * 0.6)
        cdi = Arrow(cfg.get_left() + LEFT * 1.2, cfg.get_left(), buff=0, color=C_BIT, stroke_width=2.5)
        cdil = mono("CDI, CE, CLK = TCK", 14, C_BIT).next_to(cdi, DOWN, buff=0.05)
        o = Arrow(cfg.get_right(), cfg.get_right() + RIGHT * 0.8, buff=0, color=C_RTL, stroke_width=2.5)
        desc = txt("a LUT5 whose 32-bit table\nis shifted in, one bit per clock", 16, DIM).next_to(cfg, DOWN, buff=0.5)
        # crossbar mux = 5 leaves + OR
        leaves = VGroup(*[chip(f"leaf {k}", C_GRF, w=1.1, h=0.42, size=13) for k in range(5)]).arrange(DOWN, buff=0.1)
        leaves.move_to(RIGHT * 2.0 + UP * 0.5)
        orr = chip("OR\n(plain LUT)", C_PY, w=1.3, h=1.1, size=14).move_to(RIGHT * 4.0 + UP * 0.5)
        lw = VGroup(*[wire(l.get_right(), orr.get_left() + UP * (0.3 - 0.15 * i), DIM, 1.3) for i, l in enumerate(leaves)])
        ol = Arrow(orr.get_right(), orr.get_right() + RIGHT * 0.8, buff=0, color=C_GRF, stroke_width=2.5)
        xl = txt("one crossbar mux: select 2+i puts 'address bit i mod 5' in leaf i ÷ 5; the rest hold 0", 15, DIM)
        fit(xl, 6.4)
        xl.next_to(VGroup(leaves, orr), DOWN, buff=0.3)
        n = F["cfglut5_per_clb"]
        stats = VGroup(
            txt(f"{n} CFGLUT5 per CLB = 4 × 2 (tables) + 24 × 5 (crossbar leaves)", 18, C_BIT),
            txt("loaded by lut_loader.v while the frame holding them is written: 32 TCK cycles", 17, INK),
            txt("never use a CFGLUT5's O5: Vivado makes a dual-output one two LUT sites (M23's first build did not place)", 16, C_ERR),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.14)
        fit(stats, 12.6)
        stats.move_to(DOWN * 2.15)
        with self.narrate(
                "Finally, how this is built inside the host chip. A bob truth table is configuration, "
                "so it could sit in sixty-four flip-flops behind a sixty-four-way mux. That is far too "
                "big. Instead it lives in AMD's CFGLUT5: a real LUT whose table is shifted in serially."):
            self.play(FadeIn(cfg), GrowArrow(cdi), FadeIn(cdil), GrowArrow(o), FadeIn(desc), run_time=1.2)
        with self.narrate(
                "Each crossbar mux is five such LUTs, each looking at five sources, and a fixed OR. "
                "The selected source's leaf holds a table that copies that one input; every other leaf "
                "holds zeros, so the OR passes exactly the chosen signal."):
            self.play(FadeIn(leaves, lag_ratio=0.15), Create(lw), FadeIn(orr), GrowArrow(ol), run_time=1.4)
            self.play(FadeIn(xl), run_time=0.6)
        with self.narrate(
                f"That is {n} CFGLUT5s per block, loaded automatically as their configuration frame "
                f"arrives. It cut a block from roughly four hundred and seventy host LUTs to under two "
                f"hundred, and it is what let the grid reach ten by ten."):
            self.play(FadeIn(stats, lag_ratio=0.3), run_time=1.4)
        self.wipe()
