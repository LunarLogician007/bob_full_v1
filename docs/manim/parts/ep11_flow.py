# =============================================================================
#  EPISODE 11 - The whole flow: by hand, and by tool
# =============================================================================

def s1_byhand(sc):
    sc.heading("Before there were tools, there was an API",
               "software/host/bitstream.py - place a LUT, name its inputs, let a BFS router connect them")

    code = code_block([
        "from bitstream import Design, LUT",
        "",
        "d = Design()",
        "a, b = d.input(0), d.input(1)",
        "g = d.lut(2, 3, LUT.and2(), [a, b])     # an AND at tile (2,3)",
        "d.output(0, g)                          # to LD0",
        "bs = d.build()                          # place, route, pack 18560 bits",
    ], 21, INK)
    cp = panel(code, C_PY)
    cp.shift(UP * 1.5)
    sc.play(FadeIn(cp), run_time=1.0)

    how = code_block([
        "build() runs a breadth-first search over the routing graph, allocating one",
        "mux per hop. A mux already carrying the same signal is free to traverse",
        "again - which is how fanout works with no special case at all.",
        "",
        "It still exists, and hwtest still uses it: the hand-built designs are the",
        "regression that every board run starts with.",
    ], 19, INK)
    how[4].set_color(C_BIT); how[5].set_color(C_BIT)
    how.next_to(cp, DOWN, buff=0.8).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in how], lag_ratio=0.18), run_time=2.0)

    note = Text("This is the honest way to learn a fabric: if you can place and route it "
                "by hand, you understand it.", font_size=20, color=C_BIT)
    note.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(note), run_time=0.9)
    sc.wait(2.0)


def s2_bytool(sc):
    sc.heading("./bob build", "seven steps, and every one of them is checked before the next runs")

    steps = [
        ("synthesis", "yosys onto bob cells", C_VPR),
        ("equivalence", "source == netlist == golden, 300 cycles", C_ERR),
        ("place and route", "VPR on the committed graph, or bob's own PnR", C_VPR),
        ("FASM", "features, legality-checked against device.json", C_BIT),
        ("bits", "bitgen; the ctrl tile gets the clock setting", C_BIT),
        ("model", "model.py with these bits == the source trace", C_ERR),
        (".bit", "chain + BRAM sections + META + file CRC", C_PY),
    ]
    g = VGroup()
    for i, (a, b, col) in enumerate(steps):
        n = mono(f"{i + 1}", 20, col)
        t = mono(a, 20, col)
        w = Text(b, font_size=17, color=DIM)
        g.add(VGroup(n, t, w).arrange(RIGHT, buff=0.4, aligned_edge=DOWN))
    for r in g:
        r[1].align_to(g[0][1], LEFT).shift(RIGHT * 0.55)
        r[2].align_to(g[0][2], LEFT).shift(RIGHT * 3.4)
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
    if g.width > 12.6:
        g.scale_to_fit_width(12.6)
    g.next_to(sc.mobjects[1], DOWN, buff=0.7).set_x(0)
    for r in g:
        sc.play(FadeIn(r, shift=RIGHT * 0.2), run_time=0.4)

    two = Text("Two commands, end to end:   ./bob build design.v    then    ./bob load x.bit",
               font_size=22, color=C_BIT)
    two.scale_to_fit_width(12.8).to_edge(DOWN, buff=0.4)
    sc.play(FadeIn(two), run_time=0.8)
    sc.wait(2.0)


def s3_layers(sc):
    sc.heading("Why you can believe the result",
               "each layer is checked against something that was NOT derived from it")

    layers = [
        ("references", "UG470 / 473 / 474 / 479, OpenFPGA, VPR", C_GRF),
        ("Python models", "model.py, packets.Controller, chainbits CRC", C_PY),
        ("RTL testbenches", "expectations come from the models, never from the RTL", C_RTL),
        ("mutation tests", "break each guard on purpose - a test MUST fail", C_ERR),
        ("golden co-simulation", "source || golden netlist || the whole FPGA from a .bit", C_BIT),
        ("the stand-in board", "every hardware check, on a good board and a broken one", C_VPR),
        ("the PYNQ-Z2", "make hwtest M=Mx, appended to results.log", INK),
    ]
    g = VGroup()
    for a, b, col in layers:
        g.add(VGroup(mono(a, 20, col), Text(b, font_size=17, color=DIM))
              .arrange(RIGHT, buff=0.5, aligned_edge=DOWN))
    for r in g:
        r[1].align_to(g[0][1], LEFT).shift(RIGHT * 4.4)
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
    if g.width > 13.0:
        g.scale_to_fit_width(13.0)
    g.next_to(sc.mobjects[1], DOWN, buff=0.6).set_x(0)
    for i, r in enumerate(g):
        sc.play(FadeIn(r, shift=RIGHT * 0.2), run_time=0.4)
        if i:
            sc.play(GrowArrow(arrow(g[i - 1].get_left() + LEFT * 0.25,
                                    r.get_left() + LEFT * 0.25, DIM, 0.02, 2)),
                    run_time=0.12)

    counts = Text("28 744 testbench checks  ·  193 pytest tests  ·  59 mutants, all killed  ·  "
                  "57 logged board runs", font_size=20, color=C_BIT)
    counts.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(counts), run_time=0.9)
    sc.wait(2.2)


def s4_board(sc):
    sc.heading("What a board run actually does",
               "make hwtest M=M16 - the regression first, so a new milestone cannot break an old one")

    g = VGroup(
        chip("idcode", C_GRF, 2.2, 0.7, 19),
        chip("bypass", C_GRF, 2.2, 0.7, 19),
        chip("selftest", C_GRF, 2.2, 0.7, 19),
    ).arrange(RIGHT, buff=0.4).shift(UP * 2.0)
    sc.play(FadeIn(g), run_time=0.6)
    gl = Text("the regression - every run, in this order", font_size=18, color=DIM)
    gl.next_to(g, DOWN, buff=0.22)
    sc.play(FadeIn(gl), run_time=0.4)

    more = code_block([
        "then the milestone's own checks, for example on M16:",
        "",
        "   the full M15 list      chain, frames, CRC, GTS, GSR/GWE, CAPTURE,",
        "                          BRAM modes, DSP, partial reconfiguration",
        "   bob-big / pnr-big      a 56-CLB design that could not fit the old grid,",
        "                          through VPR and through bob's own PnR",
        "   live checks            a person at the switches, with goals and a timer",
    ], 19, INK)
    more[0].set_color(DIM)
    more.next_to(gl, DOWN, buff=0.6).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in more], lag_ratio=0.15), run_time=2.0)

    rule = code_block([
        "Two rules that make these trustworthy:",
        "   every check runs against the STAND-IN board first, passing and failing",
        "   every run is appended to docs/hwtest/results.log and never edited",
    ], 19, C_BIT)
    rule[0].set_color(DIM)
    rule.next_to(more, DOWN, buff=0.6).set_x(0)
    sc.play(FadeIn(rule), run_time=0.9)
    sc.wait(2.2)


def s5_files(sc):
    sc.files_used(
        inputs=[("software/host/bitstream.py", "the hand-design API and its BFS router"),
                ("software/bob/cli.py", "./bob build and load"),
                ("software/host/hwtest.py", "15 milestone check lists")],
        generated=[("build/bit/*.bit", "loadable bitstreams"),
                   ("build/cosim/", "the co-simulation harness"),
                   ("docs/hwtest/results.log", "57 board runs, append only")],
        verified=[("sim/run_cosim_sim.sh", "5822 checks across 22 design builds"),
                  ("tests/test_hwtest_fake.py", "the stand-in board"),
                  ("the PYNQ-Z2", "M0-M15 all passed; M16 pending")])


EP11 = [s1_byhand, s2_bytool, s3_layers, s4_board, s5_files]


class Ep11Flow(BobScene):
    def construct(self):
        self.titlecard("EPISODE 11", "The whole flow",
                       "by hand, by tool, and why you can believe the answer")
        for i, part in enumerate(EP11):
            part(self)
            if i < len(EP11) - 1:
                clear_all(self)


class E11S1Byhand(BobScene):
    def construct(self): s1_byhand(self)


class E11S2Bytool(BobScene):
    def construct(self): s2_bytool(self)


class E11S3Layers(BobScene):
    def construct(self): s3_layers(self)


class E11S4Board(BobScene):
    def construct(self): s4_board(self)


class E11S5Files(BobScene):
    def construct(self): s5_files(self)
