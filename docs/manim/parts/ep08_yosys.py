# =============================================================================
#  EPISODE 8 - Synthesis: turning Verilog into cells bob actually has
# =============================================================================

def s1_what(sc):
    sc.heading("Synthesis is translation, not magic",
               "software/bob/synth.py drives yosys with bob's own cell library and maps")

    src = chip("counter.v\nordinary Verilog", INK, 3.0, 1.2, 20).move_to(np.array([-4.6, 1.5, 0]))
    ys = chip("yosys", C_VPR, 2.2, 1.0, 24, "BOLD").move_to(np.array([-0.6, 1.5, 0]))
    out = chip("only bob cells", C_RTL, 3.2, 1.2, 20).move_to(np.array([3.6, 1.5, 0]))
    sc.play(FadeIn(src), run_time=0.4)
    sc.play(GrowArrow(arrow(src.get_right(), ys.get_left(), DIM, 0.1)), FadeIn(ys),
            run_time=0.5)
    sc.play(GrowArrow(arrow(ys.get_right(), out.get_left(), DIM, 0.1)), FadeIn(out),
            run_time=0.5)

    cells = code_block([
        "$lut         a K-input LUT             -> one CLB",
        "BOB_ADD      one carry bit             -> one CLB in carry mode",
        "BOB_FDRE     flip-flop, sync reset     -> the CLB's flop, ff_rstval = 0",
        "BOB_FDSE     flip-flop, sync set       -> ff_rstval = 1",
        "BOB_BRAM18   1024 x 18 true dual port  -> a BRAM block",
        "BOB_DSP      25 x 18 signed            -> a DSP slice",
    ], 19, C_RTL)
    cells.next_to(out, DOWN, buff=1.0).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l, shift=RIGHT * 0.15) for l in cells], lag_ratio=0.15),
            run_time=1.9)

    strict = Text("synth.py FAILS if anything else survives, or if the design has more "
                  "than one clock. There is no 'mostly mapped'.",
                  font_size=20, color=C_BIT)
    strict.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(strict), run_time=0.9)
    sc.wait(2.0)


def s2_passes(sc):
    sc.heading("The pass order", "patterned on yosys's own synth_xilinx, with bob's maps swapped in")

    steps = [
        ("read + hierarchy", "elaborate, pick the top", DIM),
        ("proc, flatten, opt", "ordinary front-end work", DIM),
        ("mul2dsp 25x18", "big multipliers become BOB_DSP", C_BIT),
        ("memory_libmap", "memories become BOB_BRAM18, rules in bob_brams.txt", C_BIT),
        ("techmap _80_bob_alu", "$alu becomes BOB_ADD carry chains", C_RTL),
        ("dfflegalize", "every flop becomes BOB_FDRE / BOB_FDSE", C_RTL),
        ("abc -lut K", "whatever is left becomes $lut", C_VPR),
        ("write json / blif / sim", "for the placer, for VPR, for simulation", C_PY),
    ]
    g = VGroup()
    for a, b, col in steps:
        g.add(VGroup(mono(a, 20, col), Text(b, font_size=17, color=DIM))
              .arrange(RIGHT, buff=0.5, aligned_edge=DOWN))
    for r in g:
        r[1].align_to(g[0][1], LEFT).shift(RIGHT * 4.6)
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.26)
    if g.width > 13.0:
        g.scale_to_fit_width(13.0)
    g.next_to(sc.mobjects[1], DOWN, buff=0.6).set_x(0)
    for r in g:
        sc.play(FadeIn(r, shift=RIGHT * 0.2), run_time=0.35)

    trap = code_block([
        "A trap worth remembering: the rule was first called _90_bob_alu, and yosys",
        "picked the generic _90_alu instead - rules are tried in NAME order.",
        "Renaming it _80_ fixed it. Nothing errored; the carry chains just vanished.",
    ], 18, C_ERR)
    trap.to_edge(DOWN, buff=0.35).set_x(0)
    sc.play(FadeIn(trap), run_time=0.9)
    sc.wait(2.2)


def s3_proof(sc):
    sc.heading("Three copies of the same circuit, simulated together",
               "software/bob/equiv.py - this is what stops a wrong map from ever reaching the board")

    three = VGroup(
        chip("the source\ncounter.v", INK, 3.0, 1.2, 19),
        chip("the yosys netlist\ncounter_syn.v", C_VPR, 3.4, 1.2, 19),
        chip("the golden netlist\ngolden.py, one wire per bit", C_PY, 4.2, 1.2, 17),
    ).arrange(RIGHT, buff=0.6).shift(UP * 1.8)
    sc.play(LaggedStart(*[FadeIn(t) for t in three], lag_ratio=0.2), run_time=1.0)

    sim = chip("iverilog: all three, same stimulus, 300 cycles", C_BIT, 8.6, 0.9, 20)
    sim.next_to(three, DOWN, buff=0.8)
    for t in three:
        sc.play(GrowArrow(arrow(t.get_bottom(), sim.get_top(), DIM, 0.1)), run_time=0.2)
    sc.play(FadeIn(sim), run_time=0.5)

    chk = code_block([
        "compared before AND after every clock edge",
        "the source trace is saved   -> later checked against model.py and the board",
        "every golden net is saved   -> later checked against CAPTURE on the board",
    ], 19, INK)
    chk.next_to(sim, DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in chk], lag_ratio=0.2), run_time=1.5)

    why = Text("Why a third, 'golden' netlist? Because yosys's own output renames every "
               "cell and net, so nothing in it maps back to a fabric location. "
               "golden.py writes the same logic with one named wire per bit.",
               font_size=18, color=DIM)
    why.scale_to_fit_width(13.0).next_to(chk, DOWN, buff=0.5)
    sc.play(FadeIn(why), run_time=0.9)
    sc.wait(2.2)


def s4_stimulus(sc):
    sc.heading("The bug that made this episode necessary",
               "a test that passes for the wrong reason is worse than no test")

    story = code_block([
        "M8: the counter example passed. Model, RTL and board all agreed.",
        "",
        "M9: someone looked at the saved trace. It was all zeros.",
    ], 22, INK)
    story[2].set_color(C_ERR)
    story.shift(UP * 1.9)
    sc.play(FadeIn(story[0]), run_time=0.7)
    sc.wait(0.6)
    sc.play(FadeIn(story[2]), run_time=0.7)
    sc.wait(1.0)

    why = code_block([
        "The stimulus was uniform random over all inputs.",
        "The counter's synchronous reset was one of those inputs.",
        "So it was asserted about half the time - and the counter never counted.",
        "",
        "Every check compared zero against zero and passed.",
    ], 20, INK)
    why[4].set_color(C_ERR)
    why.next_to(story, DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in why], lag_ratio=0.2), run_time=1.9)

    fix = code_block([
        "The fix: biased vectors in 50-cycle segments, so control inputs hold still",
        "long enough for state to build up. The counter's trace now reaches LED 0-6.",
        "",
        "The rule: check that your stimulus actually exercises what it claims.",
    ], 20, C_BIT)
    fix[3].set_color(C_RTL)
    fix.next_to(why, DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in fix], lag_ratio=0.2), run_time=1.7)
    sc.wait(2.2)


def s5_files(sc):
    sc.files_used(
        inputs=[("software/bob/synth/bob_cells_sim.v", "the cell library, simulatable"),
                ("software/bob/synth/bob_map.v", "techmap rules, incl. _80_bob_alu"),
                ("software/bob/synth/bob_brams.txt", "memory_libmap rules"),
                ("work/examples/*.v", "the designs themselves")],
        generated=[("build/synth/<top>/<top>.json", "for the placer and VPR"),
                   ("build/synth/<top>/<top>_syn.v", "the netlist, for simulation"),
                   ("software/bob/golden.py output", "one named wire per bit"),
                   ("trace.json", "the source trace + every golden net per clock")],
        verified=[("software/bob/equiv.py", "source == netlist == golden, 300 cycles"),
                  ("hw/tb/tb_synth.v", "972 checks: the designs on the real fabric"),
                  ("tests/test_synth.py", "non-bob cells rejected, chains split by column")])


EP08 = [s1_what, s2_passes, s3_proof, s4_stimulus, s5_files]


class Ep08Yosys(BobScene):
    def construct(self):
        self.titlecard("EPISODE 8", "Synthesis",
                       "Verilog into cells bob actually has")
        for i, part in enumerate(EP08):
            part(self)
            if i < len(EP08) - 1:
                clear_all(self)


class E08S1What(BobScene):
    def construct(self): s1_what(self)


class E08S2Passes(BobScene):
    def construct(self): s2_passes(self)


class E08S3Proof(BobScene):
    def construct(self): s3_proof(self)


class E08S4Stimulus(BobScene):
    def construct(self): s4_stimulus(self)


class E08S5Files(BobScene):
    def construct(self): s5_files(self)
