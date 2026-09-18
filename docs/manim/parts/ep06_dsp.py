# =============================================================================
#  EPISODE 6 - DSP: a trimmed DSP48E1, and the cascade
# =============================================================================

def s1_datapath(sc):
    sc.heading("The datapath", "hw/src/tiles/dsp_core.v, following AMD UG479's DSP48E1")

    a = chip("A  25", C_RTL, 1.6, 0.7, 19).move_to(np.array([-5.4, 1.9, 0]))
    d = chip("D  25", C_RTL, 1.6, 0.7, 19).move_to(np.array([-5.4, 0.9, 0]))
    b = chip("B  18", C_GRF, 1.6, 0.7, 19).move_to(np.array([-5.4, -0.3, 0]))
    c = chip("C  48", C_BIT, 1.6, 0.7, 19).move_to(np.array([-5.4, -1.5, 0]))
    sc.play(LaggedStart(FadeIn(a), FadeIn(d), FadeIn(b), FadeIn(c), lag_ratio=0.15),
            run_time=0.9)

    pre = Circle(radius=0.42, color=C_RTL, stroke_width=3).set_fill(C_RTL, 0.12)
    pret = Text("+/-", font_size=22, color=INK).move_to(pre)
    pre = VGroup(pre, pret).move_to(np.array([-3.0, 1.4, 0]))
    sc.play(FadeIn(pre),
            GrowArrow(arrow(a.get_right(), pre.get_left(), DIM, 0.12)),
            GrowArrow(arrow(d.get_right(), pre.get_left(), DIM, 0.12)), run_time=0.7)
    prel = mono("pre-adder  D +/- A", 16, C_RTL).next_to(pre, UP, buff=0.25)
    sc.play(FadeIn(prel), run_time=0.4)

    mul = chip("x\n25 x 18\nsigned", C_VPR, 1.7, 1.6, 19).move_to(np.array([-0.6, 0.6, 0]))
    sc.play(FadeIn(mul),
            GrowArrow(arrow(pre.get_right(), mul.get_left() + UP * 0.35, DIM, 0.12)),
            GrowArrow(arrow(b.get_right(), mul.get_left() + DOWN * 0.35, DIM, 0.12)),
            run_time=0.8)
    m = mono("M", 18, C_VPR).next_to(mul, RIGHT, buff=0.25)
    sc.play(FadeIn(m), run_time=0.3)

    alu = chip("+", C_BIT, 1.3, 1.6, 26).move_to(np.array([2.4, 0.2, 0]))
    sc.play(FadeIn(alu),
            GrowArrow(arrow(m.get_right(), alu.get_left() + UP * 0.35, DIM, 0.12)),
            GrowArrow(arrow(c.get_right(), alu.get_left() + DOWN * 0.45, DIM, 0.2)),
            run_time=0.8)
    p = chip("P  48", C_BIT, 1.6, 0.8, 20).move_to(np.array([5.0, 0.2, 0]))
    sc.play(FadeIn(p), GrowArrow(arrow(alu.get_right(), p.get_left(), DIM, 0.12)),
            run_time=0.5)

    fb = VMobject(color=DIM, stroke_width=2)
    fb.set_points_as_corners([p.get_bottom(), np.array([5.0, -1.9, 0]),
                              np.array([2.4, -1.9, 0]), alu.get_bottom()])
    fbl = mono("P feeds back  (accumulate)", 15, DIM).next_to(fb, DOWN, buff=0.05).set_x(3.6)
    sc.play(Create(fb), FadeIn(fbl), run_time=0.7)

    trim = Text("trimmed: dynamic OPMODE / INMODE / ALUMODE, ALU functions other than add, "
                "the 30-bit A port, pattern detect, CARRYIN",
                font_size=18, color=DIM)
    trim.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(trim), run_time=0.8)
    sc.wait(2.0)


def s2_cfg(sc):
    sc.heading("Sixteen configuration bits per slice",
               "every pipeline register is a bit - that is what makes a DSP configurable")

    fields = [("opmode", 2, C_VPR), ("use_d", 1, C_RTL), ("d_sub", 1, C_RTL),
              ("areg", 1, C_BIT), ("breg", 1, C_BIT), ("creg", 1, C_BIT),
              ("dreg", 1, C_BIT), ("mreg", 1, C_BIT), ("preg", 1, C_BIT),
              ("jtag_a", 1, C_PY), ("jtag_b", 1, C_PY), ("jtag_c", 1, C_PY),
              ("jtag_d", 1, C_PY), ("jtag_ctrl", 1, C_PY), ("rsv", 1, DIM)]
    bar = fieldbar(fields, total_w=11.5, h=0.75, size=12)
    bar.shift(UP * 1.5)
    sc.play(Create(bar[0]), FadeIn(bar[1]), FadeIn(bar[2]), run_time=1.3)

    g = VGroup(
        VGroup(mono("opmode", 19, C_VPR),
               Text("which of the four static opmodes this slice computes", font_size=17, color=DIM))
        .arrange(RIGHT, buff=0.4, aligned_edge=DOWN),
        VGroup(mono("use_d / d_sub", 19, C_RTL),
               Text("bring the pre-adder in, and whether it subtracts", font_size=17, color=DIM))
        .arrange(RIGHT, buff=0.4, aligned_edge=DOWN),
        VGroup(mono("areg..preg", 19, C_BIT),
               Text("six independent pipeline registers - latency is configurable", font_size=17, color=DIM))
        .arrange(RIGHT, buff=0.4, aligned_edge=DOWN),
        VGroup(mono("jtag_*", 19, C_PY),
               Text("drive that bus from the JTAG drive word instead of the fabric", font_size=17, color=DIM))
        .arrange(RIGHT, buff=0.4, aligned_edge=DOWN),
    )
    for r in g:
        r[1].align_to(g[0][1], LEFT).shift(RIGHT * 2.6)
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
    if g.width > 12.8:
        g.scale_to_fit_width(12.8)
    g.next_to(bar, DOWN, buff=0.9).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in g], lag_ratio=0.2),
            run_time=1.9)

    ce = Text("CE and RST are grouped four ways (C shares P's) - a real DSP48E1 has more, "
              "and we list the difference rather than pretend.",
              font_size=18, color=DIM)
    ce.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(ce), run_time=0.8)
    sc.wait(2.2)


def s3_opmodes(sc):
    sc.heading("Four opmodes and one cascade",
               "static, because a dynamic OPMODE pin would cost fabric routing on every slice")

    modes = VGroup(
        VGroup(mono("0", 22, C_VPR), mono("P = M", 24, INK),
               Text("a plain multiply", font_size=17, color=DIM)),
        VGroup(mono("1", 22, C_VPR), mono("P = M + C", 24, INK),
               Text("multiply-add", font_size=17, color=DIM)),
        VGroup(mono("2", 22, C_VPR), mono("P = P + M", 24, INK),
               Text("accumulate - P fed back from its own register", font_size=17, color=DIM)),
        VGroup(mono("3", 22, C_VPR), mono("P = (PCIN >>> 17) + M", 24, INK),
               Text("the cascade: a wider multiply across two slices", font_size=17, color=DIM)),
    )
    for m in modes:
        m.arrange(RIGHT, buff=0.5, aligned_edge=DOWN)
    for m in modes:
        m[2].align_to(modes[3][2], LEFT).shift(RIGHT * 5.4)
    modes.arrange(DOWN, aligned_edge=LEFT, buff=0.38)
    if modes.width > 13.0:
        modes.scale_to_fit_width(13.0)
    modes.shift(UP * 1.3)
    sc.play(LaggedStart(*[FadeIn(m, shift=RIGHT * 0.2) for m in modes], lag_ratio=0.25),
            run_time=2.0)

    s0 = chip("dsp0", C_VPR, 2.2, 0.9, 21)
    s1 = chip("dsp1", C_VPR, 2.2, 0.9, 21)
    pair = VGroup(s0, s1).arrange(UP, buff=1.0).next_to(modes, DOWN, buff=0.9).set_x(-3.0)
    sc.play(FadeIn(pair), run_time=0.6)
    casc = arrow(s0.get_top(), s1.get_bottom(), C_BIT, 0.08)
    cl = mono("PCOUT -> PCIN", 18, C_BIT).next_to(casc, RIGHT, buff=0.3)
    sc.play(GrowArrow(casc), FadeIn(cl), run_time=0.6)

    note = code_block([
        "in the routing graph the cascade is a DIRECT, like the carry chain:",
        "48 wires, no multiplexers, no configuration bits.",
        "",
        "In VPR's architecture it is declared as a <direct> so the packer keeps",
        "a two-slice multiply together.",
    ], 18, INK)
    note[0].set_color(C_GRF); note[1].set_color(C_GRF)
    note.next_to(pair, RIGHT, buff=1.2).set_y(pair.get_y())
    if note.width > 7.0:
        note.scale_to_fit_width(7.0)
    sc.play(FadeIn(note), run_time=0.9)
    sc.wait(2.2)


def s4_jtag(sc):
    sc.heading("The private DSP instruction",
               "all four AMD USER codes were taken, so M6 took a private one: 101000")

    dr = fieldbar([("drive word: A, B, C, D and 8 controls, per slice", 248, C_PY),
                   ("P0", 48, C_BIT), ("P1", 48, C_BIT)], total_w=11.0, h=0.8, size=15)
    dr.shift(UP * 1.4)
    sc.play(Create(dr[0]), FadeIn(dr[1]), FadeIn(dr[2]), run_time=1.1)

    why = code_block([
        "Why drive a DSP from JTAG at all?",
        "",
        "Because a fabric-fed DSP can only be tested through routing, and at M6",
        "there was no routing yet. The drive word lets the host put any operand",
        "on any bus and read both P values back - so tb_dsp.v and the board test",
        "check the SAME vectors against model.py, 1344 of them.",
        "",
        "It stayed after M7 because it is still the fastest way to prove a slice",
        "works without building a design around it.",
    ], 19, INK)
    why[0].set_color(C_BIT)
    why.next_to(dr, DOWN, buff=0.8).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in why], lag_ratio=0.15), run_time=2.4)
    sc.wait(2.0)


def s5_files(sc):
    sc.files_used(
        inputs=[("hw/src/tiles/dsp_core.v", "the arithmetic, registers and opmodes"),
                ("hw/src/tiles/dsp_block.v", "per-bus source: fabric or drive word"),
                ("hw/src/tiles/dsp_jtag.v", "the 248-bit drive register")],
        generated=[("software/bob/device.json", "16 fields, opmodes, cascade"),
                   ("software/bob/model.py", "class Dsp + the cascade helpers")],
        verified=[("hw/tb/tb_dsp.v", "1344 checks: every opmode x pre-adder, 2 slices"),
                  ("sim/mutate_fabric.sh", "dsp-no-d-sub, dsp-shift-16, dsp-no-cascade"),
                  ("work/examples/fir/fir.v", "a 2-tap FIR on both slices, live on the board")])


EP06 = [s1_datapath, s2_cfg, s3_opmodes, s4_jtag, s5_files]


class Ep06DSP(BobScene):
    def construct(self):
        self.titlecard("EPISODE 6", "DSP",
                       "a trimmed DSP48E1, and the cascade that costs no bits")
        for i, part in enumerate(EP06):
            part(self)
            if i < len(EP06) - 1:
                clear_all(self)


class E06S1Datapath(BobScene):
    def construct(self): s1_datapath(self)


class E06S2Cfg(BobScene):
    def construct(self): s2_cfg(self)


class E06S3Opmodes(BobScene):
    def construct(self): s3_opmodes(self)


class E06S4Jtag(BobScene):
    def construct(self): s4_jtag(self)


class E06S5Files(BobScene):
    def construct(self): s5_files(self)
