# =============================================================================
#  EPISODE 12 - What is ours: bob against OpenFPGA, Aegis, ZUMA, prjxray
# =============================================================================

def s1_lineage(sc):
    sc.heading("Almost nothing here is invented",
               "and that is the point - every part is grounded in something already tested")

    rows = [
        ("CLB", "AMD UG474", "LUT6_2 fracture, MUXCY/XORCY, FDRE/FDSE, routable CE/SR", C_RTL),
        ("BRAM", "AMD UG473", "RAMB18E1 behaviour, write modes, DOx_REG", C_RTL),
        ("DSP", "AMD UG479", "A25/B18/D25, pre-adder, 25x18, P48, cascade", C_RTL),
        ("configuration", "AMD UG470", "packets, FAR, CMD, STAT, CRC, startup, AGHIGH", C_BIT),
        ("CRC", "prjxray crc.py", "CRC-32C over {register, data}", C_BIT),
        ("routing", "OpenFPGA k6_frac_N10", "tileable, L4, Wilton Fs 3, fc 0.15 / 0.10", C_VPR),
        ("chain", "OpenFPGA scan_chain, Aegis", "shift register plus a shadow register", C_GRF),
        ("PnR", "Betz & Rose; McMurchie & Ebeling", "annealing placer, PathFinder router", C_PY),
        ("FASM", "F4PGA", "feature = value between PnR and bits", C_PY),
        ("area idea", "ZUMA (FCCM 2012)", "configuration memory in host LUTRAM - considered", DIM),
    ]
    g = VGroup()
    for a, b, c, col in rows:
        g.add(VGroup(mono(a, 18, col), mono(b, 17, INK), Text(c, font_size=15, color=DIM))
              .arrange(RIGHT, buff=0.35, aligned_edge=DOWN))
    for r in g:
        r[1].align_to(g[0][1], LEFT).shift(RIGHT * 2.2)
        r[2].align_to(g[0][2], LEFT).shift(RIGHT * 6.0)
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.2)
    if g.width > 13.2:
        g.scale_to_fit_width(13.2)
    g.next_to(sc.mobjects[1], DOWN, buff=0.5).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.15) for r in g], lag_ratio=0.1),
            run_time=2.6)

    note = Text("Where bob diverges, PLAN.md and the report say so explicitly - "
                "there is a whole section listing it.", font_size=19, color=C_BIT)
    note.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.28)
    sc.play(FadeIn(note), run_time=0.8)
    sc.wait(2.2)


def s2_openfpga(sc):
    sc.heading("bob against OpenFPGA", "the project bob borrows its method from - and it is far bigger")

    a = Text("OpenFPGA", font_size=30, color=C_VPR, weight="BOLD").move_to(np.array([-3.4, 2.1, 0]))
    b = Text("bob", font_size=30, color=C_RTL, weight="BOLD").move_to(np.array([3.4, 2.1, 0]))
    sc.play(FadeIn(a), FadeIn(b), run_time=0.5)

    rows = [
        ("many architectures, from one XML", "one architecture, one board"),
        ("Verilog AND SPICE, ASIC-oriented", "Verilog only, an overlay on a real FPGA"),
        ("area and power models", "none"),
        ("scan_chain, frame_based, memory_bank...", "scan chain AND UG470 frames, on ONE memory"),
        ("a mature, general framework", "one device description drives RTL, VPR arch,"),
        ("", "models, FASM map and host tools"),
        ("verified mostly in simulation", "every milestone proven on real hardware"),
    ]
    g = VGroup()
    for l, r in rows:
        lt = Text(l, font_size=17, color=DIM)
        rt = Text(r, font_size=17, color=INK)
        g.add(VGroup(lt, rt).arrange(RIGHT, buff=0.6, aligned_edge=UP))
    for row in g:
        row[1].align_to(g[0][1], LEFT).shift(RIGHT * 5.6)
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.24)
    if g.width > 13.2:
        g.scale_to_fit_width(13.2)
    g.next_to(VGroup(a, b), DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=UP * 0.1) for r in g], lag_ratio=0.15),
            run_time=2.2)

    honest = Text("OpenFPGA is a research framework with years of work behind it. "
                  "bob is one fabric on one board. The comparison is about METHOD, not scale.",
                  font_size=19, color=C_BIT)
    honest.scale_to_fit_width(13.2).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(honest), run_time=0.9)
    sc.wait(2.2)


def s3_aegis(sc):
    sc.heading("bob against Aegis", "a full-stack open FPGA going to real silicon - a different goal entirely")

    rows = [
        ("target", "GF180MCU / Sky130 silicon", "the PL of an XC7Z020"),
        ("written in", "Dart / ROHD -> SystemVerilog", "Verilog, generated from Python"),
        ("logic", "LUT4, one per tile", "LUT6 fracturable + carry + FF"),
        ("routing", "per-tile switchbox, 1-4 tracks per edge", "VPR rr graph, L4, W = 24, Wilton"),
        ("configuration", "one scan chain, shift + shadow, cfgLoad", "chain AND UG470 frames"),
        ("integrity", "none in the chain", "CRC-32C, length, IDCODE, per-write CRC"),
        ("partial reconfiguration", "no", "yes, with state provably kept"),
        ("what bob took", "the shift + shadow idea, the I/O and clock notes", ""),
    ]
    g = VGroup()
    for a, b, c in rows:
        g.add(VGroup(mono(a, 17, C_BIT), Text(b, font_size=16, color=DIM),
                     Text(c, font_size=16, color=INK))
              .arrange(RIGHT, buff=0.35, aligned_edge=UP))
    for r in g:
        r[1].align_to(g[0][1], LEFT).shift(RIGHT * 2.9)
        r[2].align_to(g[0][2], LEFT).shift(RIGHT * 8.0)
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.24)
    if g.width > 13.2:
        g.scale_to_fit_width(13.2)
    g.next_to(sc.mobjects[1], DOWN, buff=0.6).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.15) for r in g], lag_ratio=0.15),
            run_time=2.4)

    note = Text("Aegis solves a harder problem than bob does: it has to be manufacturable. "
                "bob only has to be correct, and provable, on one board.",
                font_size=19, color=C_BIT)
    note.scale_to_fit_width(13.2).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(note), run_time=0.9)
    sc.wait(2.2)


def s4_ours(sc):
    sc.heading("What is actually ours", "six things that are not borrowed from anywhere")

    items = [
        ("Hardware proof at every step",
         "sixteen milestones, each ending on the PYNQ-Z2. Simulation never closed one."),
        ("One description, five consumers",
         "device.py generates the RTL, the VPR architecture, the models, the FASM map"),
        ("", "and the host tools. They cannot drift, and pytest proves they have not."),
        ("Two configuration paths on ONE memory",
         "a UG470 frame engine and a scan chain, writing the same bits, both kept working"),
        ("Partial reconfiguration that keeps state provably",
         "AGHIGH holds the user clock; every register is gated by gce, so state is exact"),
        ("Golden co-simulation",
         "source Verilog and a golden netlist run beside the whole FPGA loaded from a real .bit"),
        ("A stand-in board",
         "every hardware check is tested - passing AND failing - before the board sees it"),
    ]
    g = VGroup()
    for a, b in items:
        if a:
            g.add(VGroup(mono("*", 20, C_BIT), Text(a, font_size=20, color=INK),)
                  .arrange(RIGHT, buff=0.3, aligned_edge=DOWN))
            g.add(Text(b, font_size=16, color=DIM))
        else:
            g.add(Text(b, font_size=16, color=DIM))
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.16)
    if g.width > 13.2:
        g.scale_to_fit_width(13.2)
    g.next_to(sc.mobjects[1], DOWN, buff=0.5).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.15) for r in g], lag_ratio=0.12),
            run_time=2.8)
    sc.wait(2.4)


def s5_notours(sc):
    sc.heading("And what bob is not", "saying this plainly is part of the work")

    items = [
        "one small fabric, on one board, with one BLE per CLB",
        "no timing-driven place and route - VPR's delays are the reference 40 nm numbers,",
        "not the emulated fabric's",
        "no ASIC flow, no SPICE, no area or power models",
        "one clock domain for guest designs; no async resets or latches",
        "K and W are fixed per build - changing them means a full regenerate and rebuild",
        "far less coverage of architectures and devices than OpenFPGA",
        "partial reconfiguration has no region protection: the host decides which frames",
    ]
    g = VGroup(*[VGroup(mono("-", 20, C_ERR), Text(t, font_size=19, color=INK))
                 .arrange(RIGHT, buff=0.3, aligned_edge=DOWN) for t in items])
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.26)
    if g.width > 13.2:
        g.scale_to_fit_width(13.2)
    g.next_to(sc.mobjects[1], DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.15) for r in g], lag_ratio=0.15),
            run_time=2.4)

    last = Text("A claim you cannot fail is not a claim. Every limit here is written down "
                "in PLAN.md and in the report.", font_size=20, color=C_BIT)
    last.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(last), run_time=0.9)
    sc.wait(2.4)


def s6_files(sc):
    sc.files_used(
        inputs=[("PLAN.md", "section 9: references, and what each is used for"),
                ("docs/project/REPORT.md", "section 20: follows vs diverges"),
                ("docs/project/GUIDE.md", "section 5: how bob compares")],
        generated=[("project.html", "the interactive report"),
                   ("guide.html", "the learning guide"),
                   ("arch.html", "the interactive die slice")],
        verified=[("tests/test_vpr.py", "the reference routing parameters are still kept"),
                  ("software/bob/arch/*.stamp", "which OpenFPGA image built the graph"),
                  ("docs/hwtest/results.log", "the hardware claim, run by run")])


EP12 = [s1_lineage, s2_openfpga, s3_aegis, s4_ours, s5_notours, s6_files]


class Ep12Novelty(BobScene):
    def construct(self):
        self.titlecard("EPISODE 12", "What is ours",
                       "bob against OpenFPGA, Aegis and ZUMA - honestly")
        for i, part in enumerate(EP12):
            part(self)
            if i < len(EP12) - 1:
                clear_all(self)


class E12S1Lineage(BobScene):
    def construct(self): s1_lineage(self)


class E12S2Openfpga(BobScene):
    def construct(self): s2_openfpga(self)


class E12S3Aegis(BobScene):
    def construct(self): s3_aegis(self)


class E12S4Ours(BobScene):
    def construct(self): s4_ours(self)


class E12S5Notours(BobScene):
    def construct(self): s5_notours(self)


class E12S6Files(BobScene):
    def construct(self): s6_files(self)
