# =============================================================================
#  EPISODE 4 - I/O, pads and the user clock
# =============================================================================

def s1_iotile(sc):
    sc.heading("An I/O block is smaller than you expect",
               "no io_tile.v at all - one VPR pad plus two boundary cells, wired in bob_fpga.v")

    world = chip("the world\n(a package pin)", C_GRF, 2.6, 1.2, 19)
    world.move_to(np.array([-5.0, 0.6, 0]))
    sc.play(FadeIn(world), run_time=0.5)

    inc = chip("input cell\ncell 44 + k", C_PY, 2.3, 0.9, 17).move_to(np.array([-1.7, 1.6, 0]))
    outc = chip("output cell\ncell k", C_PY, 2.3, 0.9, 17).move_to(np.array([-1.7, -0.5, 0]))
    sc.play(FadeIn(inc), FadeIn(outc), run_time=0.6)

    opin = chip("OPIN\ninpad", C_RTL, 1.9, 0.9, 17).move_to(np.array([1.7, 1.6, 0]))
    ipin = chip("IPIN mux\noutpad", C_RTL, 1.9, 0.9, 17).move_to(np.array([1.7, -0.5, 0]))
    fab = chip("the fabric", C_RTL, 2.2, 2.4, 20).move_to(np.array([4.7, 0.55, 0]))
    sc.play(FadeIn(opin), FadeIn(ipin), FadeIn(fab), run_time=0.6)

    sc.play(GrowArrow(arrow(world.get_right(), inc.get_left(), DIM, 0.08)),
            GrowArrow(arrow(inc.get_right(), opin.get_left(), DIM, 0.08)),
            GrowArrow(arrow(opin.get_right(), fab.get_left() + UP * 0.6, DIM, 0.08)),
            run_time=0.7)
    sc.play(GrowArrow(arrow(fab.get_left() + DOWN * 0.6, ipin.get_right(), DIM, 0.08)),
            GrowArrow(arrow(ipin.get_left(), outc.get_right(), DIM, 0.08)),
            GrowArrow(arrow(outc.get_left(), world.get_right() + DOWN * 0.35, DIM, 0.08)),
            run_time=0.7)

    gts = mono("GTS", 20, C_ERR).next_to(outc, DOWN, buff=0.2)
    sc.play(FadeIn(gts), GrowArrow(arrow(gts.get_top(), outc.get_bottom(), C_ERR, 0.1)),
            run_time=0.6)

    notes = code_block([
        "the outpad IPIN is an ordinary routing mux - it costs configuration bits",
        "the inpad OPIN is a source - it costs none",
        "GTS forces every pad output to 0 during startup",
        "there is no true tri-state: the board's pins have fixed directions,",
        "so bob drives 0 instead of releasing. An honest simplification.",
    ], 19, INK)
    notes[2].set_color(C_ERR)
    notes[3].set_color(DIM); notes[4].set_color(DIM)
    notes.next_to(VGroup(world, fab), DOWN, buff=0.9).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in notes], lag_ratio=0.18), run_time=1.8)
    sc.wait(2.2)


def s2_padmap(sc):
    sc.heading("44 pads, 9 of them wired to something you can see",
               "software/bob/device.py picks the numbers; bob_top.v is the only file that knows about a board")

    # software/bob/device.json "pads.io" gives every pad's (x, y) on this 14x12 grid
    # (bob_params.vh: BOB_GRID_W=14, BOB_GRID_H=12). Reproduced here so the square
    # that lights up is the square that pad number actually is, not just its draw
    # order around the loop.
    def pad_of(x, y):
        if y == 0:  return x - 1        # south edge,              pad 0..11
        if y == 11: return 31 + x       # north edge,              pad 32..43
        if x == 0:  return 10 + 2 * y   # west edge (SW/BTN side), pad 12,14..30
        return 11 + 2 * y               # east edge (LD side),     pad 13,15..31

    ring = VGroup()
    pos = {}
    for x in range(14):
        for y in range(12):
            if (x in (0, 13)) and (y in (0, 11)):
                continue
            if not (x in (0, 13) or y in (0, 11)):
                continue
            s = Square(0.3, color=C_GRF, stroke_width=1.5).set_fill(C_GRF, 0.14)
            s.move_to(np.array([-3.0 + x * 0.42, -2.2 + y * 0.42, 0]))
            pos[pad_of(x, y)] = s
            ring.add(s)
    ring.shift(LEFT * 1.4)
    sc.play(LaggedStart(*[FadeIn(s, scale=0.6) for s in ring], lag_ratio=0.02),
            run_time=1.6)

    board = [("SW0", 12, C_RTL), ("SW1", 14, C_RTL), ("BTN0", 16, C_RTL),
             ("BTN1", 18, C_RTL), ("BTN2", 20, C_RTL), ("BTN3", 22, C_RTL),
             ("LD0", 13, C_BIT), ("LD1", 15, C_BIT), ("LD2", 17, C_BIT)]
    tbl = VGroup()
    for n, p, c in board:
        tbl.add(VGroup(mono(f"pad {p:2d}", 18, DIM), mono(n, 18, c))
                .arrange(RIGHT, buff=0.4))
    tbl.arrange(DOWN, aligned_edge=LEFT, buff=0.2).to_edge(RIGHT, buff=1.4)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in tbl], lag_ratio=0.12),
            run_time=1.4)
    sc.play(LaggedStart(*[pos[p].animate.set_stroke(c).set_fill(c, 0.7)
                          for n, p, c in board], lag_ratio=0.15), run_time=1.6)

    rest = Text("every other pad's input is 0 and its output goes nowhere - "
                "they exist, and INTEST/SAMPLE boundary scan is the only way to reach them",
                font_size=19, color=DIM)
    rest.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(rest), run_time=0.8)
    sc.wait(2.0)


def s3_userclock(sc):
    sc.heading("The user clock is not a clock",
               "hw/src/core/clock_ctrl.v - UG949 prefers a clock ENABLE to a logic-generated clock")

    sys = chip("sysclk\n125 MHz, H16, on a BUFG", C_GRF, 4.0, 1.1, 19)
    sys.move_to(np.array([-4.0, 1.7, 0]))
    ff = chip("every fabric flip-flop,\nBRAM and DSP register", C_RTL, 4.2, 1.1, 19)
    ff.move_to(np.array([2.4, 1.7, 0]))
    sc.play(FadeIn(sys), FadeIn(ff),
            GrowArrow(arrow(sys.get_right(), ff.get_left(), DIM, 0.1)), run_time=0.8)
    gce = mono("gce", 26, C_BIT).next_to(ff, DOWN, buff=0.55)
    sc.play(FadeIn(gce), GrowArrow(arrow(gce.get_top(), ff.get_bottom(), C_BIT, 0.1)),
            run_time=0.6)
    gl = Text("the enable: hold gce high for one sysclk cycle, the fabric advances once.",
              font_size=19, color=C_BIT)
    gl.next_to(gce, DOWN, buff=0.3).set_x(0)
    sc.play(FadeIn(gl), run_time=0.6)
    sc.wait(0.5)

    modes = VGroup(
        VGroup(mono("clk_mode = 0", 22, C_PY),
               Text("JTAG-stepped: one gce per TCK rising edge while USER1 ce is set, plus",
                    font_size=17, color=DIM),
               Text("one per step / autostep - how cycle-exact INTEST tests step the fabric.",
                    font_size=17, color=DIM)).arrange(DOWN, aligned_edge=LEFT, buff=0.12),
        VGroup(mono("clk_mode = 1", 22, C_VPR),
               Text("free-running: one gce every 2**(clk_div + 8) sysclk cycles.",
                    font_size=17, color=DIM),
               Text("clk_div = 15 gives 14.9 Hz - slow enough to watch an LED blink.",
                    font_size=17, color=DIM)).arrange(DOWN, aligned_edge=LEFT, buff=0.12),
    ).arrange(DOWN, aligned_edge=LEFT, buff=0.45)
    modes.next_to(gl, DOWN, buff=0.45).set_x(-0.4)
    sc.play(LaggedStart(*[FadeIn(m, shift=RIGHT * 0.2) for m in modes], lag_ratio=0.3),
            run_time=2.0)

    ctrl = Text("Both live in the 8-bit ctrl tile - the very first bits of the chain, "
                "FAR column 0. ./bob build --clock run --div 15 sets them.",
                font_size=19, color=C_BIT)
    ctrl.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(ctrl), run_time=0.8)
    sc.wait(2.2)


def s4_gap(sc):
    sc.heading("The 256-cycle guarantee",
               "the single most important line of timing in the project, and it is enforced in RTL")

    bad = code_block([
        "M7's Vivado report:   WNS  -1102 ns      1858 failing endpoints",
        "and yet the board passed 26 / 26.",
    ], 22, C_ERR)
    bad.shift(UP * 2.0)
    sc.play(FadeIn(bad), run_time=0.9)
    sc.wait(0.8)

    why = code_block([
        "The analyser cannot know a configuration, so it walked a path no legal,",
        "loop-free bitstream ever uses: fabric register -> 1202 logic levels -> BRAM.",
        "It bounced between dsp0 and dsp1 thirty-four times.",
    ], 19, DIM)
    why.next_to(bad, DOWN, buff=0.5)
    sc.play(LaggedStart(*[FadeIn(l) for l in why], lag_ratio=0.2), run_time=1.5)
    sc.wait(0.8)

    g1 = VGroup(
        mono("clock_ctrl.v GUARANTEES gce pulses are >= 2**8 = 256 sysclk cycles apart,", 19, C_BIT),
        mono("in BOTH modes - a request that arrives sooner waits (one is kept pending).", 19, C_BIT),
    ).arrange(DOWN, aligned_edge=LEFT, buff=0.14)
    g2 = VGroup(
        mono("So the XDC can say, truthfully:", 19, DIM),
        mono("    set_multicycle_path -setup 256 -from [get_clocks sysclk] -to [get_clocks sysclk]", 16, C_PY),
    ).arrange(DOWN, aligned_edge=LEFT, buff=0.14)
    g3 = mono("256 cycles = 2048 ns > the 1110 ns path.  WNS at M13: +0.877 ns, 0 failing.", 19, C_RTL)
    fix = VGroup(g1, g2, g3).arrange(DOWN, aligned_edge=LEFT, buff=0.28)
    fix.next_to(why, DOWN, buff=0.6)
    sc.play(LaggedStart(*[FadeIn(m) for m in (g1[0], g1[1], g2[0], g2[1], g3)],
                        lag_ratio=0.18), run_time=2.2)

    lesson = Text("A multicycle exception is a PROMISE. tb_clock_gap.v exists to prove "
                  "bob keeps it - 11 checks, including while frozen.",
                  font_size=19, color=C_BIT)
    lesson.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(lesson), run_time=0.9)
    sc.wait(2.2)


def s5_sync(sc):
    sc.heading("Two clocks, and only one safe way across",
               "TCK and sysclk are declared asynchronous - everything that crosses is synchronised")

    t = chip("TCK domain\nTAP, configuration,\nboundary, CFG_CTRL", C_GRF, 3.6, 1.8, 19)
    t.move_to(np.array([-4.0, 0.8, 0]))
    s = chip("sysclk domain\nthe fabric, BRAM,\nDSP, clock_ctrl", C_RTL, 3.6, 1.8, 19)
    s.move_to(np.array([4.0, 0.8, 0]))
    sc.play(FadeIn(t), FadeIn(s), run_time=0.7)

    ff1 = Square(0.55, color=C_BIT, stroke_width=2.5).set_fill(C_BIT, 0.18)
    ff2 = ff1.copy()
    pair = VGroup(ff1, ff2).arrange(RIGHT, buff=0.35).move_to(np.array([0, 0.8, 0]))
    pl = mono("ASYNC_REG\ntwo-flop synchroniser", 16, C_BIT).next_to(pair, UP, buff=0.3)
    sc.play(FadeIn(pair), FadeIn(pl),
            GrowArrow(arrow(t.get_right(), pair.get_left(), DIM, 0.12)),
            GrowArrow(arrow(pair.get_right(), s.get_left(), DIM, 0.12)), run_time=0.9)

    crossers = code_block([
        "what crosses:   TCK itself (as data),  USER1 ce / step / cin,",
        "                GSR, GWE, the quasi-static clock configuration,",
        "                and the M14 freeze / acknowledgement handshake",
    ], 19, INK)
    crossers.next_to(pair, DOWN, buff=1.0).set_x(0)
    sc.play(FadeIn(crossers), run_time=0.9)

    xdc = code_block([
        "set_clock_groups -asynchronous -group [get_clocks tck] -group [get_clocks sysclk]",
    ], 16, C_PY)
    xdc.next_to(crossers, DOWN, buff=0.5)
    sc.play(FadeIn(xdc), run_time=0.6)

    rule = Text("And the rule that makes it sound: configuration only changes while GWE = 0. "
                "The fabric never samples bits while they move.",
                font_size=19, color=C_BIT)
    rule.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(rule), run_time=0.9)
    sc.wait(2.2)


def s6_files(sc):
    sc.files_used(
        inputs=[("hw/src/core/clock_ctrl.v", "gce, both modes, the gap guard"),
                ("hw/src/fabric/bob_fpga.v", "the boundary ring and GTS"),
                ("hw/src/top/bob_top.v", "the only file that knows a board exists"),
                ("hw/constr/pynq_z2.xdc", "pins and the multicycle promises")],
        generated=[("hw/src/generated/bob_params.vh", "BOB_PAD_*, BOB_NPAD, BOB_GCE_MIN_GAP_SHIFT"),
                   ("software/bob/device.json", "pads, board_inputs, board_outputs")],
        verified=[("hw/tb/tb_clock_gap.v", "11 checks on gce spacing and freeze"),
                  ("tests/test_layout.py", "the XDC is plain XDC, no Tcl"),
                  ("tests/test_reports.py", "WNS >= 0, 0 failing endpoints, from M13")])


EP04 = [s1_iotile, s2_padmap, s3_userclock, s4_gap, s5_sync, s6_files]


class Ep04IO(BobScene):
    def construct(self):
        self.titlecard("EPISODE 4", "I/O and the clock",
                       "pads, the boundary, and the enable that pretends to be a clock")
        for i, part in enumerate(EP04):
            part(self)
            if i < len(EP04) - 1:
                clear_all(self)


class E04S1Iotile(BobScene):
    def construct(self): s1_iotile(self)


class E04S2Padmap(BobScene):
    def construct(self): s2_padmap(self)


class E04S3Userclock(BobScene):
    def construct(self): s3_userclock(self)


class E04S4Gap(BobScene):
    def construct(self): s4_gap(self)


class E04S5Sync(BobScene):
    def construct(self): s5_sync(self)


class E04S6Files(BobScene):
    def construct(self): s6_files(self)
