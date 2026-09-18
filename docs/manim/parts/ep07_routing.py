# =============================================================================
#  EPISODE 7 - Routing: boxes, muxes, directs, and loops by construction
# =============================================================================

def s1_boxes(sc):
    sc.heading("Two classic structures, one implementation",
               "bob never writes a 'connection box' or a 'switch box' - it writes muxes, one per graph node")

    cb = chip("connection box", C_GRF, 3.6, 1.0, 21).move_to(np.array([-3.6, 1.9, 0]))
    sb = chip("switch box", C_VPR, 3.6, 1.0, 21).move_to(np.array([3.6, 1.9, 0]))
    sc.play(FadeIn(cb), FadeIn(sb), run_time=0.6)
    cbt = Text("picks which track drives a block input pin", font_size=18, color=DIM)
    sbt = Text("picks which track drives another track", font_size=18, color=DIM)
    cbt.next_to(cb, DOWN, buff=0.25)
    sbt.next_to(sb, DOWN, buff=0.25)
    sc.play(FadeIn(cbt), FadeIn(sbt), run_time=0.5)

    down = VGroup(
        chip("an IPIN node with fan-in", C_GRF, 4.6, 0.85, 19),
        chip("a CHANX / CHANY node with fan-in", C_VPR, 5.4, 0.85, 19),
    ).arrange(RIGHT, buff=0.7).next_to(VGroup(cbt, sbt), DOWN, buff=0.9)
    sc.play(GrowArrow(arrow(cbt.get_bottom(), down[0].get_top(), DIM, 0.1)),
            GrowArrow(arrow(sbt.get_bottom(), down[1].get_top(), DIM, 0.1)),
            FadeIn(down), run_time=0.8)

    one = chip("bob_mux", C_RTL, 3.2, 0.9, 24, "BOLD")
    one.next_to(down, DOWN, buff=0.9).set_x(0)
    sc.play(GrowArrow(arrow(down[0].get_bottom(), one.get_top(), DIM, 0.1)),
            GrowArrow(arrow(down[1].get_bottom(), one.get_top(), DIM, 0.1)),
            FadeIn(one), run_time=0.8)

    pt = Text("The distinction is architectural vocabulary. In the RTL there is only "
              "one module, instantiated 3391 times.", font_size=20, color=C_BIT)
    pt.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.4)
    sc.play(FadeIn(pt), run_time=0.9)
    sc.wait(2.0)


def s2_arch(sc):
    sc.heading("The routing architecture",
               "every number here is OpenFPGA's k6_frac_N10 tileable reference, kept on purpose")

    rows = [
        ("W = 24", "tracks per channel, 12 each way", C_VPR),
        ("L4", "every wire spans 4 tiles, unidirectional", C_VPR),
        ("Wilton, Fs = 3", "each incoming track can turn 3 ways at a switch point", C_GRF),
        ("fc_in = 0.15", "a block input taps 15% of the channel -> fan-in 4", C_GRF),
        ("fc_out = 0.10", "a block output reaches 10% of the channel", C_GRF),
        ("fc = 0 on carry and clock pins", "they are directs and globals, not routed", C_BIT),
    ]
    g = VGroup()
    for a, b, col in rows:
        g.add(VGroup(mono(a, 21, col), Text(b, font_size=18, color=DIM))
              .arrange(RIGHT, buff=0.5, aligned_edge=DOWN))
    for r in g:
        r[1].align_to(g[0][1], LEFT).shift(RIGHT * 4.4)
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
    if g.width > 13.0:
        g.scale_to_fit_width(13.0)
    g.shift(UP * 1.2)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in g], lag_ratio=0.18),
            run_time=2.2)

    sweep = code_block([
        "W was chosen by sweeping VPR, and the cost is configuration bits:",
        "",
        "    W = 16  ->  4.2 k routing bits",
        "    W = 24  ->  6.0 k             <- chosen: IPIN fan-in 4 (0.15 x 24)",
        "    W = 32  ->  7.8 k",
    ], 19, INK)
    sweep[3].set_color(C_BIT)
    sweep.next_to(g, DOWN, buff=0.8).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in sweep], lag_ratio=0.18), run_time=1.6)

    div = Text("Where bob diverges from the reference, it says so: 1 BLE per CLB "
               "(N10 is too many config flops for an XC7Z020), carry south-to-north, "
               "bob's own BRAM and DSP blocks.", font_size=18, color=DIM)
    div.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(div), run_time=0.9)
    sc.wait(2.0)


def s3_mux(sc):
    sc.heading("The encoding, and the property it buys",
               "hw/src/fabric/bob_mux.v - four lines of Verilog with a deliberate choice in them")

    tbl = code_block([
        "sel = 0                  const 0",
        "sel = 1   (IPIN only)    const 1",
        "sel = base + i           input i          base = 1, or 2 on an IPIN",
        "sel  anything larger     const 0",
    ], 23, INK)
    tbl[0].set_color(C_BIT)
    tbl[3].set_color(DIM)
    tbl.shift(UP * 1.7)
    sc.play(LaggedStart(*[FadeIn(l) for l in tbl], lag_ratio=0.2), run_time=1.6)

    box = SurroundingRectangle(tbl[0], color=C_BIT, buff=0.1)
    sc.play(Create(box), run_time=0.5)
    big = Text("an all-zero configuration is a dark, loop-free fabric",
               font_size=30, color=C_BIT, weight="BOLD")
    big.scale_to_fit_width(11.5).next_to(tbl, DOWN, buff=0.9)
    sc.play(FadeIn(big), run_time=0.8)
    sc.wait(1.0)

    why = code_block([
        "That is not decoration. It means:",
        "   power-up and JPROGRAM leave a fabric that cannot oscillate",
        "   a half-written or refused load cannot build a ring oscillator",
        "   simulation of an unconfigured device terminates",
        "",
        "The out-of-range case matters too: a random or corrupted value can only",
        "ever select const 0, never a wire. Random chains in simulation rely on it.",
    ], 19, INK)
    why[0].set_color(DIM)
    why[5].set_color(DIM); why[6].set_color(DIM)
    why.next_to(big, DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in why], lag_ratio=0.15), run_time=2.2)
    sc.wait(2.0)


def s4_directs(sc):
    sc.heading("138 connections that cost nothing",
               "an IPIN driven by exactly one OPIN has no choice to make")

    a = Dot(np.array([-3.4, 1.4, 0]), radius=0.14, color=C_RTL)
    al = mono("OPIN  clb_x12y2.cout", 17, C_RTL).next_to(a, UP, buff=0.2)
    b = Dot(np.array([0.6, 1.4, 0]), radius=0.14, color=C_RTL)
    bl = mono("IPIN  clb_x12y3.cin", 17, C_RTL).next_to(b, UP, buff=0.2)
    sc.play(FadeIn(a), FadeIn(al), FadeIn(b), FadeIn(bl), run_time=0.6)
    sc.play(GrowArrow(arrow(a.get_center(), b.get_center(), DIM, 0.2)), run_time=0.5)

    v = mono("assign r1583 = r1308;   // clb_x12y3.cin[0] <- clb_x12y2.cout[0]", 19, C_RTL)
    vp = panel(v, C_RTL)
    vp.next_to(VGroup(a, b), DOWN, buff=0.9).set_x(0)
    sc.play(FadeIn(vp), run_time=0.8)
    note = Text("a wire. No mux, no configuration bits, no delay through a select.",
                font_size=20, color=C_BIT).next_to(vp, DOWN, buff=0.35)
    sc.play(FadeIn(note), run_time=0.6)

    which = code_block([
        "what is a direct in bob:",
        "   the carry chains, up every CLB column",
        "   the DSP PCOUT -> PCIN cascade, 48 bits",
        "",
        "and one node type that is neither: an undriven node reads 0,",
        "except the bottom row's cin, which is USER1's cin from JTAG.",
    ], 19, INK)
    which[0].set_color(DIM)
    which[4].set_color(DIM); which[5].set_color(DIM)
    which.next_to(note, DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in which], lag_ratio=0.18), run_time=1.8)

    trap = Text("The mutation test that cuts one carry direct is pinned to the LAST CLB column - "
                "when the grid grew from 8 to 12 columns it silently stopped matching, twice.",
                font_size=18, color=C_ERR)
    trap.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(trap), run_time=0.9)
    sc.wait(2.2)


def s5_loops(sc):
    sc.heading("The fabric has combinational loops, by construction",
               "and that is a fact about mesh routing, not a bug in bob")

    ta = chip("tile A", C_RTL, 2.2, 0.9, 21).move_to(np.array([-2.2, 1.8, 0]))
    tb = chip("tile B", C_RTL, 2.2, 0.9, 21).move_to(np.array([2.2, 1.8, 0]))
    sc.play(FadeIn(ta), FadeIn(tb), run_time=0.5)
    e1 = CurvedArrow(ta.get_right(), tb.get_left(), angle=-0.7, color=C_ERR, stroke_width=3)
    e2 = CurvedArrow(tb.get_left(), ta.get_right(), angle=-0.7, color=C_ERR, stroke_width=3)
    sc.play(Create(e1), run_time=0.4)
    sc.play(Create(e2), run_time=0.4)
    lab = Text("A's east output can feed B, whose west output can feed A",
               font_size=19, color=DIM).next_to(VGroup(ta, tb), DOWN, buff=0.6)
    sc.play(FadeIn(lab), run_time=0.5)

    tools = code_block([
        "Verilator says:   UNOPTFLAT",
        "Vivado says:      [DRC LUTLP-1] Combinatorial Loop Alert",
        "yosys says:       5553 'logic loop' warnings",
    ], 20, C_ERR)
    tools.next_to(lab, DOWN, buff=0.6).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in tools], lag_ratio=0.2), run_time=1.3)

    ans = code_block([
        "Whether a loop EXISTS depends on the bitstream - and none that bob's",
        "tools emit contains one, because the router builds a tree from each",
        "source to its sinks, and an all-zero mux selects const 0.",
        "",
        "Naming a net per loop with ALLOW_COMBINATORIAL_LOOPS is not workable:",
        "there are thousands, and the names are synthesis output that changes",
        "every build. So the DRC is downgraded, scoped to the fabric top only.",
    ], 19, INK)
    ans[0].set_color(C_BIT); ans[1].set_color(C_BIT); ans[2].set_color(C_BIT)
    ans[4].set_color(DIM); ans[5].set_color(DIM); ans[6].set_color(DIM)
    ans.next_to(tools, DOWN, buff=0.6).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in ans], lag_ratio=0.15), run_time=2.4)

    cost = Text("The price: Vivado breaks the loops arbitrarily for timing analysis, "
                "so some paths are not analysed - which is exactly why the 256-cycle "
                "gce guarantee had to be made real in RTL.",
                font_size=18, color=C_ERR)
    cost.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.28)
    sc.play(FadeIn(cost), run_time=0.9)
    sc.wait(2.2)


def s6_files(sc):
    sc.files_used(
        inputs=[("hw/src/fabric/bob_mux.v", "the one routing multiplexer"),
                ("tools/bob/vpr_arch.py", "the architecture VPR is given"),
                ("hw/scripts/drc_waiver.tcl", "the LUTLP-1 downgrade, fabric tops only")],
        generated=[("hw/src/generated/bob_fabric.v", "3391 muxes, 138 directs, 4416 lines"),
                   ("tools/bob/arch/bob_k6_rr.xml.gz", "VPR's graph, committed and stamped"),
                   ("tools/bob/device.json", "every mux: node, bits, inputs")],
        verified=[("hw/tb/tb_bob.v", "4 random routed netlists vs model.py every clock"),
                  ("tests/test_device.py", "every pip is one field value, every pin a node"),
                  ("sim/mutate_fabric.sh", "mux-no-const1, mux-inputs-shifted, carry-direct-cut")])


EP07 = [s1_boxes, s2_arch, s3_mux, s4_directs, s5_loops, s6_files]


class Ep07Routing(BobScene):
    def construct(self):
        self.titlecard("EPISODE 7", "Routing",
                       "boxes, muxes, directs, and loops by construction")
        for i, part in enumerate(EP07):
            part(self)
            if i < len(EP07) - 1:
                clear_all(self)


class E07S1Boxes(BobScene):
    def construct(self): s1_boxes(self)


class E07S2Arch(BobScene):
    def construct(self): s2_arch(self)


class E07S3Mux(BobScene):
    def construct(self): s3_mux(self)


class E07S4Directs(BobScene):
    def construct(self): s4_directs(self)


class E07S5Loops(BobScene):
    def construct(self): s5_loops(self)


class E07S6Files(BobScene):
    def construct(self): s6_files(self)
