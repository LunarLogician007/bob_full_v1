"""Chapter 05 - BRAM (UG473 subset) and DSP (UG479 trimmed)."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bobvid.scene import *


class Ch05BramDsp(BobScene):
    CH = "05"
    TITLE = "BRAM and DSP"
    SUBTITLE = "the hard blocks: a true dual-port memory (UG473) and a multiply-accumulate slice (UG479)"

    def construct(self):
        F = self.F
        self.title_card(
            "Some things logic does badly: storing kilobits, and multiplying wide numbers. "
            "Real FPGAs add hard blocks for them, and so does bob, modelled on AMD's own.")
        self.bram_ports(F)
        self.write_modes()
        self.bram_bits(F)
        self.contents(F)
        self.dsp_path(F)
        self.opmodes(F)
        self.dsp_bits(F)
        self.files_card(
            "Both cores are written in Vivado's inference style, so they become a real block RAM and "
            "a real DSP slice in the host. Their testbenches walk every mode against the Python model, "
            "and the board checks repeat the same vectors over JTAG.",
            [("hw/src/tiles/bram_core.v", "1024 x 18 TDP, inferable"),
             ("hw/src/tiles/bram_jtag.v", "USER4 and frame contents"),
             ("hw/src/tiles/dsp_core.v", "trimmed DSP48E1")],
            [("synth: BOB_BRAM18, BOB_DSP", "memory_libmap, mul2dsp"),
             ("device.json bram / dsp", "ports, modes, opmodes")],
            [("hw/tb/tb_bram.v", "5292 checks"),
             ("hw/tb/tb_dsp.v", "1344 checks"),
             ("hwtest bram-modes, dsp-accum", "on the board")])

    # ------------------------------------------------------------------
    def bram_ports(self, F):
        b = F["bram"]
        depth, width = 2 ** b["addr_w"], b["data_w"]
        self.heading("Block RAM", f"{depth} words × {width} bits, true dual port: two independent ports on one array")
        arr = Rectangle(width=3.0, height=3.6, color=C_PY, stroke_width=2.5).set_fill(C_PY, opacity=0.12).move_to(DOWN * 0.3)
        rows = VGroup(*[Line(arr.get_left() + RIGHT * 0.1 + UP * (1.5 - 0.25 * k), arr.get_right() + LEFT * 0.1 + UP * (1.5 - 0.25 * k),
                             color=C_PY, stroke_width=1, stroke_opacity=0.4) for k in range(13)])
        al = txt(f"{depth} × {width}", 22, C_PY, weight=BOLD).move_to(arr)
        pa = VGroup(*[mono(s, 16, INK) for s in (f"addr_a[{b['addr_w'] - 1}:0]", f"di_a[{width - 1}:0]", "we_a  en_a", "rst_a regce_a")]).arrange(DOWN, aligned_edge=RIGHT, buff=0.22)
        pa.next_to(arr, LEFT, buff=0.9)
        pb = VGroup(*[mono(s, 16, INK) for s in (f"addr_b[{b['addr_w'] - 1}:0]", f"di_b[{width - 1}:0]", "we_b  en_b", "rst_b regce_b")]).arrange(DOWN, aligned_edge=LEFT, buff=0.22)
        pb.next_to(arr, RIGHT, buff=0.9)
        wa = VGroup(*[Arrow(p.get_right(), [arr.get_left()[0], p.get_y(), 0], buff=0.08, color=DIM, stroke_width=2, tip_length=0.12) for p in pa])
        wb = VGroup(*[Arrow(p.get_left(), [arr.get_right()[0], p.get_y(), 0], buff=0.08, color=DIM, stroke_width=2, tip_length=0.12) for p in pb])
        doa = Arrow(arr.get_bottom() + LEFT * 0.8, arr.get_bottom() + LEFT * 0.8 + DOWN * 0.7, buff=0, color=C_PY, stroke_width=3)
        dob = Arrow(arr.get_bottom() + RIGHT * 0.8, arr.get_bottom() + RIGHT * 0.8 + DOWN * 0.7, buff=0, color=C_PY, stroke_width=3)
        dl = VGroup(mono(f"do_a[{width - 1}:0]", 15, C_PY).next_to(doa, LEFT, buff=0.1),
                    mono(f"do_b[{width - 1}:0]", 15, C_PY).next_to(dob, RIGHT, buff=0.1))
        pl = VGroup(txt("port A", 18, C_BIT, weight=BOLD).next_to(pa, UP, buff=0.25),
                    txt("port B", 18, C_BIT, weight=BOLD).next_to(pb, UP, buff=0.25))
        with self.narrate(
                f"bob has {b['count']} block RAMs. Each is a subset of AMD's RAMB18 from UG473: "
                f"{depth} words of {width} bits, as one physical array."):
            self.play(FadeIn(arr), Create(rows), FadeIn(al), run_time=1.0)
        with self.narrate(
                "It has two complete ports, A and B, each with its own address, data in, write enable, "
                "enable, reset and output-register enable, and its own data out. Both ports can read or "
                "write the same array in the same cycle: that is what true dual port means."):
            self.play(FadeIn(pa), Create(wa), FadeIn(pl[0]), run_time=0.8)
            self.play(FadeIn(pb), Create(wb), FadeIn(pl[1]), run_time=0.8)
            self.play(GrowArrow(doa), GrowArrow(dob), FadeIn(dl), run_time=0.7)
        self.wipe()

    def write_modes(self):
        self.heading("Write modes", "what the output shows on the cycle a port writes (UG473)")
        before = VGroup(txt("before the clock:", 17, DIM), mono("mem[5] = 0x0AA   do = 0x111", 19, INK),
                        txt("this cycle: write 0x155 to address 5", 17, DIM)).arrange(DOWN, buff=0.12).move_to(UP * 1.7)
        modes = [("WRITE_FIRST", "do = 0x155", "the new data, written through", C_CYN),
                 ("READ_FIRST", "do = 0x0AA", "the old contents, then the write", C_BIT),
                 ("NO_CHANGE", "do = 0x111", "the output keeps its last value", C_GRF)]
        cards = VGroup()
        for name, out, d, col in modes:
            c = VGroup(mono(name, 22, col), mono(out, 22, INK), txt(d, 16, DIM)).arrange(DOWN, buff=0.15)
            box = RoundedRectangle(width=4.0, height=1.8, corner_radius=0.12, color=col, stroke_width=2).set_fill(col, opacity=0.06)
            cards.add(VGroup(box, c.move_to(box)))
        cards.arrange(RIGHT, buff=0.3).move_to(DOWN * 0.5)
        after = txt("all ports: mem[5] = 0x155 afterwards · an optional output register (DOx_REG) adds one cycle", 17, INK).next_to(cards, DOWN, buff=0.35)
        with self.narrate(
                "When a port writes, what should its output show on that same clock edge? UG473 offers "
                "three answers, and bob implements all three, per port."):
            self.play(FadeIn(before, lag_ratio=0.2), run_time=1.0)
        with self.narrate(
                "Write first shows the new data. Read first shows what was there before the write. And "
                "no change leaves the output exactly as it was. In every mode the memory holds the new "
                "word afterwards; only the output differs."):
            for c in cards:
                self.play(FadeIn(c, shift=UP * 0.15), run_time=0.6)
            self.play(FadeIn(after), run_time=0.6)
        with self.narrate(
                "bob builds the other two modes from read first, in the way Vivado infers a real RAMB18, "
                "so the host chip gives it a genuine block RAM rather than eighteen kilobits of LUTs."):
            self.play(Indicate(cards[1], color=C_BIT), run_time=1.0)
        self.wipe()

    def bram_bits(self, F):
        flds = F["bram_fields"]
        self.heading("Its configuration", f"{sum(w for _, w in flds)} bits per BRAM tile · device.json")
        colmap = {"wmode": C_BIT, "reg": C_CYN, "jtag": C_GRF}
        fields = [(n, w, colmap[n.split("_")[0]]) for n, w in flds]
        bar = fieldbar(fields, total_w=10.0, h=0.7, size=18).move_to(UP * 0.8)
        expl = VGroup(
            txt("wmode_a / wmode_b: WRITE_FIRST 0, READ_FIRST 1, NO_CHANGE 2", 18, INK),
            txt("reg_a / reg_b: the optional output register (DOA_REG, DOB_REG)", 18, INK),
            txt("jtag_a / jtag_b: drive that port from JTAG instead of the fabric (tests)", 18, INK),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.18).next_to(bar, DOWN, buff=0.6)
        with self.narrate(
                f"So the configuration of a block RAM is just {sum(w for _, w in flds)} bits: a write mode "
                f"for each port, an output register for each port, and two bits that let JTAG drive a port "
                f"directly, which the board tests use."):
            self.play(FadeIn(bar, lag_ratio=0.1), run_time=1.0)
            self.play(FadeIn(expl, lag_ratio=0.2), run_time=1.4)
        self.wipe()

    def contents(self, F):
        self.heading("Contents are not configuration", "UG470's split: the memory's words travel separately, and survive JPROGRAM")
        cfg = chip("configuration\n8 bits: how the RAM behaves", C_BIT, w=4.0, h=1.1, size=17).move_to(LEFT * 3.4 + UP * 1.0)
        con = chip("contents\n1024 × 18 bits: what it holds", C_PY, w=4.0, h=1.1, size=17).move_to(RIGHT * 3.4 + UP * 1.0)
        p1 = VGroup(txt("path 1: USER4", 18, C_GRF, weight=BOLD), txt("a JTAG register: LOAD_PTR, WRITE, READ", 16, INK),
                    txt("used by bob load --mode chain", 15, DIM)).arrange(DOWN, buff=0.08)
        p2 = VGroup(txt("path 2: frames, block type 001 (M15)", 18, C_GRF, weight=BOLD),
                    txt("frame n holds addresses 4n .. 4n+3, inside the load stream", 16, INK),
                    txt("under the same CRC as the configuration (chapter 09)", 15, DIM)).arrange(DOWN, buff=0.08)
        paths = VGroup(p1, p2).arrange(RIGHT, buff=1.0).move_to(DOWN * 1.0)
        lesson = txt("M11's lesson: contents survive JPROGRAM, so a load writes all 1024 words of every RAM it uses", 17, C_ERR).to_edge(DOWN, buff=1.3)
        fit(lesson, 13)
        with self.narrate(
                "One distinction matters a great deal. The eight configuration bits say how the RAM "
                "behaves. Its contents, eighteen thousand bits, are data, and AMD keeps them apart from "
                "configuration. So does bob."):
            self.play(FadeIn(cfg), FadeIn(con), run_time=0.8)
        with self.narrate(
                "Contents arrive one of two ways: through a dedicated JTAG register called USER4, or, "
                "since milestone fifteen, as frames of their own inside the configuration stream, protected "
                "by the same checksum. Keeping two independent paths caught several bugs."):
            self.play(FadeIn(p1, shift=UP * 0.1), run_time=0.7)
            self.play(FadeIn(p2, shift=UP * 0.1), run_time=0.7)
        with self.narrate(
                "And contents survive a JPROGRAM. An early loader wrote only up to the last non-zero word, "
                "so a new design could read the previous design's data. Now every word is written."):
            self.play(FadeIn(lesson), run_time=0.7)
        self.wipe()

    def dsp_path(self, F):
        d = F["dsp"]
        buses = dict((n, w) for n, w in d["buses"])
        self.heading("The DSP slice", f"UG479's DSP48E1, trimmed: A{buses['a']} B{buses['b']} C{buses['c']} D{buses['d']}, a pre-adder, a 25 × 18 multiplier, a 48-bit P")
        y = -0.1
        D = chip(f"D[{buses['d'] - 1}:0]", C_VPR, w=1.3, h=0.55, size=15, mono_font=True).move_to([-6.0, y + 0.9, 0])
        A = chip(f"A[{buses['a'] - 1}:0]", C_VPR, w=1.3, h=0.55, size=15, mono_font=True).move_to([-6.0, y + 0.1, 0])
        B = chip(f"B[{buses['b'] - 1}:0]", C_VPR, w=1.3, h=0.55, size=15, mono_font=True).move_to([-6.0, y - 1.0, 0])
        C = chip(f"C[{buses['c'] - 1}:0]", C_VPR, w=1.3, h=0.55, size=15, mono_font=True).move_to([-6.0, y - 2.0, 0])
        pre = chip("pre-adder\nD ± A", C_BIT, w=1.6, h=1.0, size=15).move_to([-3.6, y + 0.5, 0])
        mul = chip("× 25 × 18\nsigned", C_RTL, w=1.6, h=1.0, size=15).move_to([-1.2, y - 0.2, 0])
        alu = chip("ALU\nopmode", C_CYN, w=1.5, h=1.3, size=15).move_to([1.4, y - 0.6, 0])
        preg = chip("P[47:0]", C_PY, w=1.4, h=0.7, size=16, mono_font=True).move_to([3.6, y - 0.6, 0])
        ws = VGroup(
            arrow(D.get_right(), pre.get_left() + UP * 0.25, DIM, buff=0.05, sw=2, tip=0.12),
            arrow(A.get_right(), pre.get_left() + DOWN * 0.25, DIM, buff=0.05, sw=2, tip=0.12),
            arrow(pre.get_right(), mul.get_left() + UP * 0.25, DIM, buff=0.05, sw=2, tip=0.12),
            arrow(B.get_right(), mul.get_left() + DOWN * 0.3, DIM, buff=0.05, sw=2, tip=0.12),
            arrow(mul.get_right(), alu.get_left() + UP * 0.3, DIM, buff=0.05, sw=2, tip=0.12),
            arrow(C.get_right(), alu.get_left() + DOWN * 0.35, DIM, buff=0.05, sw=2, tip=0.12),
            arrow(alu.get_right(), preg.get_left(), DIM, buff=0.05, sw=2, tip=0.12),
        )
        ml = mono("M", 14, C_RTL).next_to(ws[4], UP, buff=0.04)
        fb = VMobject(color=C_PY, stroke_width=2).set_points_as_corners(
            [preg.get_bottom(), preg.get_bottom() + DOWN * 0.7, [alu.get_x(), preg.get_bottom()[1] - 0.7, 0], alu.get_bottom()])
        fbl = mono("P (accumulate)", 13, C_PY).next_to(fb, DOWN, buff=0.05)
        regs = VGroup(*[mono(r, 12, C_GRF) for r in ("AREG", "DREG", "BREG", "MREG", "CREG", "PREG")])
        regs[0].next_to(A, UP, buff=0.02).shift(RIGHT * 0.9)
        regs[1].next_to(D, UP, buff=0.02).shift(RIGHT * 0.9)
        regs[2].next_to(B, UP, buff=0.02).shift(RIGHT * 0.9)
        regs[3].next_to(mul, UP, buff=0.05)
        regs[4].next_to(C, UP, buff=0.02).shift(RIGHT * 0.9)
        regs[5].next_to(preg, UP, buff=0.05)
        pcout = Arrow(preg.get_right(), preg.get_right() + RIGHT * 1.6, buff=0, color=C_PY, stroke_width=3)
        pcl = mono("PCOUT -> next slice's PCIN", 14, C_PY).next_to(pcout, DOWN, buff=0.12).shift(RIGHT * 0.45)
        fit(pcl, 2.6)
        with self.narrate(
                f"Each of the {d['count']} DSP slices is a trimmed copy of AMD's DSP48E1 from UG479. "
                f"Four operand buses come in: A, B, C and D."):
            self.play(FadeIn(VGroup(D, A, B, C), lag_ratio=0.2), run_time=1.0)
        with self.narrate(
                "A pre-adder can form D plus or minus A. The result is multiplied by B in a twenty-five by "
                "eighteen signed multiplier. The product, M, goes into a forty-eight-bit adder whose other "
                "input is chosen by the operation mode, and lands in the P register."):
            self.play(FadeIn(pre), Create(ws[0]), Create(ws[1]), run_time=0.7)
            self.play(FadeIn(mul), Create(ws[2]), Create(ws[3]), run_time=0.7)
            self.play(FadeIn(alu), Create(ws[4]), FadeIn(ml), Create(ws[5]), run_time=0.7)
            self.play(FadeIn(preg), Create(ws[6]), Create(fb), FadeIn(fbl), run_time=0.7)
        with self.narrate(
                "Every stage has an optional pipeline register, as on the real slice. And P cascades into "
                "the next slice's PCIN over a dedicated wire, so two slices can build a filter without "
                "touching the routing."):
            self.play(FadeIn(regs, lag_ratio=0.15), run_time=1.0)
            self.play(GrowArrow(pcout), FadeIn(pcl), run_time=0.7)
        self.wipe()

    def opmodes(self, F):
        ops = F["dsp"]["opmodes"]
        self.heading("Four static opmodes", "chosen by configuration, not by a pin: two bits")
        meaning = {"M": "P = M: a plain multiplier",
                   "M+C": "P = C + M: multiply-add",
                   "P+M": "P = P + M: multiply-accumulate",
                   "PCIN>>17+M": "P = (PCIN >> 17) + M: wide products across two slices"}
        rows = VGroup()
        for name, code in sorted(ops.items(), key=lambda kv: kv[1]):
            rows.add(VGroup(mono(f"{code:02b}", 22, C_BIT), mono(name.ljust(11), 22, C_CYN), txt(meaning[name], 19, INK)).arrange(RIGHT, buff=0.45))
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.3).move_to(UP * 0.5)
        why = VGroup(
            txt("UG479's slice takes OPMODE, INMODE and ALUMODE as dynamic pins.", 17, DIM),
            txt("bob fixes them at configuration: dynamic pins would cost routing and bits", 17, DIM),
            txt("for features a 400-LUT fabric will not use. The cascade is kept: work/examples/fir uses it.", 17, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.1).next_to(rows, DOWN, buff=0.5)
        with self.narrate(
                "The real DSP48 chooses its operation every cycle from control pins. bob's slice chooses it "
                "once, in configuration, from four modes: multiply, multiply-add, multiply-accumulate, and "
                "the shifted cascade that joins two slices into one wider multiplier."):
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in rows], lag_ratio=0.3), run_time=1.8)
        with self.narrate(
                "Dynamic control would need more pins, which means more routing and more configuration, "
                "for features a fabric this size will not use. This is one of the places where bob "
                "deliberately simplifies its reference, and says so."):
            self.play(FadeIn(why, lag_ratio=0.2), run_time=1.2)
        self.wipe()

    def dsp_bits(self, F):
        flds = F["dsp_fields"]
        self.heading("Its configuration", f"{sum(w for _, w in flds)} bits per DSP slice · device.json")
        col = lambda n: C_BIT if n == "opmode" else C_VPR if n in ("use_d", "d_sub") else C_CYN if n.endswith("reg") else C_GRF if n.startswith("jtag") else FAINT
        fields = [(n, w, col(n)) for n, w in flds]
        bar = fieldbar(fields, total_w=12.4, h=0.7, size=15, min_w=0.6).move_to(UP * 0.8)
        expl = VGroup(
            txt("opmode: one of the four modes · use_d, d_sub: the pre-adder (D + A or D − A)", 18, INK),
            txt("areg … preg: one pipeline register per stage, each optional", 18, INK),
            txt("jtag_a … jtag_ctrl: drive inputs from the private DSP instruction (board tests)", 18, INK),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.18).next_to(bar, DOWN, buff=0.6)
        with self.narrate(
                f"The whole slice is configured by {sum(w for _, w in flds)} bits: the operation mode, the "
                f"pre-adder's use and sign, six optional registers, and the bits that let a JTAG instruction "
                f"drive its inputs for testing. Synthesis maps every multiplication in a design onto it "
                f"automatically."):
            self.play(FadeIn(bar, lag_ratio=0.08), run_time=1.2)
            self.play(FadeIn(expl, lag_ratio=0.2), run_time=1.4)
        self.wipe()
