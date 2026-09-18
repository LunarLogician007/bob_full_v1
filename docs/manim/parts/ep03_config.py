# =============================================================================
#  EPISODE 3 - the configuration engine: memory, two write paths, startup
# =============================================================================

def s1_memory(sc):
    sc.heading("The configuration memory",
               "one array of flip-flops that every mux, LUT and flag in the fabric reads")

    big = mono("18 560 bits", 54, C_BIT).shift(UP * 1.9)
    sc.play(Write(big), run_time=1.0)

    split = code_block([
        "=  145 frames  x  4 words  x  32 bits",
    ], 26, INK)
    split.next_to(big, DOWN, buff=0.45)
    sc.play(FadeIn(split), run_time=0.7)

    frames = VGroup()
    for i in range(29):
        r = Rectangle(width=0.36, height=0.75, color=C_BIT, stroke_width=1.6)
        r.set_fill(C_BIT, opacity=0.18)
        frames.add(r)
    frames.arrange(RIGHT, buff=0.05).next_to(split, DOWN, buff=0.7)
    dots = mono("...  145 of them", 18, DIM).next_to(frames, RIGHT, buff=0.25)
    sc.play(LaggedStart(*[FadeIn(f) for f in frames], lag_ratio=0.03), FadeIn(dots),
            run_time=1.3)

    one = frames[4]
    z = SurroundingRectangle(one, color=INK, buff=0.06)
    words = VGroup(*[Rectangle(width=0.9, height=0.5, color=C_BIT, stroke_width=2)
                     .set_fill(C_BIT, opacity=0.25) for _ in range(4)])
    words.arrange(RIGHT, buff=0.12).next_to(frames, DOWN, buff=0.9).set_x(0)
    wl = VGroup(*[mono(f"w{i}", 15, DIM).next_to(w, DOWN, buff=0.1)
                  for i, w in enumerate(words)])
    sc.play(Create(z), run_time=0.4)
    sc.play(*[TransformFromCopy(one, w) for w in words], FadeIn(wl), run_time=1.0)
    fb = mono("one frame = 128 bits", 20, C_BIT).next_to(words, UP, buff=0.3)
    sc.play(FadeIn(fb), run_time=0.5)

    who = code_block([
        "what lives in those bits:",
        "   100 CLBs   x 71   = 7100",
        "   3391 routing muxes      (2 or 3 bits each)",
        "   2 BRAM x 8,  2 DSP x 16",
        "   1 ctrl tile x 8         (the user clock)",
        "   ... padded to whole frames",
    ], 19, INK)
    who[0].set_color(DIM)
    who.to_edge(DOWN, buff=0.3).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in who], lag_ratio=0.15), run_time=1.6)
    sc.wait(2.2)


def s2_layout(sc):
    sc.heading("Where a tile's bits actually are",
               "frames are column-major, like a 7-series device - and the chain is just all frames end to end")

    cols = VGroup()
    labels = ["ctrl", "x=0", "x=1", "x=2", "x=3", "x=4", "...", "x=13"]
    counts = ["1", "2", "13", "13", "6", "13", "", "1"]
    for lab, cnt in zip(labels, counts):
        h = 3.0 if lab not in ("ctrl", "x=0", "x=13", "...") else 1.4
        r = Rectangle(width=1.12, height=h, color=C_BIT, stroke_width=2)
        r.set_fill(C_BIT, opacity=0.16)
        t = Text(lab, font_size=16, color=INK)
        c = mono(cnt + (" frames" if cnt else ""), 13, DIM)
        g = VGroup(r, t.move_to(r.get_center() + UP * (h / 2 - 0.3)),
                   c.move_to(r.get_center() + DOWN * (h / 2 - 0.25)))
        cols.add(g)
    cols.arrange(RIGHT, buff=0.12, aligned_edge=DOWN).shift(UP * 0.85)
    far = VGroup(*[mono(f"FAR col {i}", 12, C_GRF).next_to(c, UP, buff=0.14)
                   for i, c in enumerate(cols)])
    sc.play(LaggedStart(*[FadeIn(c, shift=UP * 0.2) for c in cols], lag_ratio=0.1),
            run_time=1.4)
    sc.play(FadeIn(far), run_time=0.6)

    rule = code_block([
        "FAR column 0      the 8-bit ctrl tile, padded to one whole frame",
        "FAR column x + 1  VPR grid column x: tiles bottom to top, each one's",
        "                  block fields first, then its routing muxes by node id",
    ], 19, INK)
    rule.next_to(cols, DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in rule], lag_ratio=0.2), run_time=1.5)

    key = Text("So the scan chain IS all the frames concatenated: chain bit k = memory bit k. "
               "One .bit word loads identically down either path.",
               font_size=20, color=C_BIT)
    key.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(key), run_time=0.9)
    sc.wait(1.6)

    bug = Text("Bug we paid for: the first attempt made the BLOCK order column-major too, "
               "which broke tb_bob's counter probes. Frames are column-major; blocks stay row-major.",
               font_size=17, color=C_ERR)
    bug.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.3)
    sc.play(FadeOut(key), FadeIn(bug), run_time=0.8)
    sc.wait(2.0)


def s3_chain(sc):
    sc.heading("Write path A: the scan chain",
               "CHAIN_IN - one enormous DR scan, streamed through a single 128-bit buffer")

    tdi = mono("TDI", 20, C_GRF).move_to(np.array([-6.0, 1.5, 0]))
    buf = VGroup(*[Square(0.26, color=C_GRF, stroke_width=1.6) for _ in range(16)])
    buf.arrange(RIGHT, buff=0.04).move_to(np.array([-2.4, 1.5, 0]))
    bl = mono("one 128-bit frame buffer", 17, C_GRF).next_to(buf, UP, buff=0.2)
    sc.play(FadeIn(tdi), Create(buf), FadeIn(bl),
            GrowArrow(arrow(tdi.get_right(), buf.get_left(), DIM, 0.15)), run_time=0.9)

    mem = VGroup(*[Rectangle(width=0.5, height=0.42, color=C_BIT, stroke_width=1.6)
                   .set_fill(C_BIT, opacity=0.14) for _ in range(6)])
    mem.arrange(DOWN, buff=0.07).move_to(np.array([2.6, 1.1, 0]))
    ml = mono("the memory,\nframe by frame", 16, C_BIT).next_to(mem, RIGHT, buff=0.3)
    sc.play(Create(mem), FadeIn(ml), run_time=0.7)

    for k in range(3):
        sc.play(buf.animate.set_fill(C_GRF, opacity=0.55), run_time=0.35)
        sc.play(TransformFromCopy(buf, mem[k]),
                mem[k].animate.set_fill(C_BIT, opacity=0.8), run_time=0.4)
        sc.play(buf.animate.set_fill(C_GRF, opacity=0.0), run_time=0.2)
    every = mono("every 128th bit completes a frame, written on the next falling edge",
                 18, DIM)
    every.next_to(mem, DOWN, buff=0.7).set_x(0)
    sc.play(FadeIn(every), run_time=0.7)

    guards = code_block([
        "and it only lands if all of this holds:",
        "   GWE = 0            a running design is never written underneath itself",
        "   bit count == W     exactly 18 560 bits were shifted",
        "   CRC-32C matches    reflected 0x82F63B78, init and final XOR 0xFFFFFFFF",
        "                      check value CRC('123456789') = 0xE3069283",
    ], 19, INK)
    guards[0].set_color(DIM)
    guards[1].set_color(C_ERR); guards[2].set_color(C_ERR); guards[3].set_color(C_BIT)
    guards.next_to(every, DOWN, buff=0.5).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in guards], lag_ratio=0.18), run_time=1.8)

    why = Text("The non-zero CRC seed is deliberate: a stuck-low TDI cannot produce a "
               "matching all-zero chain.", font_size=19, color=C_BIT)
    why.scale_to_fit_width(12.8).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(why), run_time=0.8)
    sc.wait(2.2)


def s4_frames(sc):
    sc.heading("Write path B: frames and packets",
               "UG470 chapter 5, simplified - this is what ./bob load sends by default")

    stream = code_block([
        "FFFFFFFF FFFFFFFF     dummy",
        "AA995566              the sync word - the controller hunts for it BIT by bit",
        "20000000              NOP",
        "30008001 00000007     CMD    <- RCRC     reset the CRC",
        "30018001 FBEEF093     IDCODE <- must match, or nothing is written",
        "30002001 00000000     FAR    <- column 0, minor 0",
        "30008001 00000001     CMD    <- WCFG     arm frame writes",
        "30004000 50000244     FDRI, type-2, count = 4 x 145",
        "<580 words>           the frames. FAR auto-increments.",
        "30002001 00800000     FAR    <- BRAM 0            (M15)",
        "30004000 50000400     FDRI, 1024 words            contents",
        "30000001 <CRC>        CRC    <- expected",
        "30008001 00000003     CMD    <- LFRM",
        "30008001 00000005     CMD    <- START   needs CRC_OK after the last FDRI",
        "30008001 0000000D     CMD    <- DESYNC",
    ], 17, INK)
    stream[1].set_color(C_GRF)
    for i in (4, 11, 13):
        stream[i].set_color(C_BIT)
    stream.next_to(sc.mobjects[1], DOWN, buff=0.4).to_edge(LEFT, buff=0.7)
    sc.play(LaggedStart(*[FadeIn(l, shift=RIGHT * 0.1) for l in stream], lag_ratio=0.1),
            run_time=3.0)

    hdr = code_block([
        "type 1   001 op reg[17:13] .. count[10:0]",
        "type 2   010 op ............ count[26:0]",
        "",
        "registers",
        "  0 CRC   1 FAR   2 FDRI",
        "  3 FDRO  4 CMD   7 STAT",
        " 12 IDCODE",
        "",
        "commands",
        "  0 NULL   1 WCFG   3 LFRM",
        "  4 RCFG   5 START  7 RCRC",
        "  8 AGHIGH 13 DESYNC",
    ], 17, C_VPR)
    hdrp = panel(hdr, C_VPR)
    hdrp.to_edge(RIGHT, buff=0.5).set_y(0.1)
    sc.play(FadeIn(hdrp), run_time=0.9)
    sc.wait(1.4)

    far = code_block([
        "FAR  [25:23] block type   000 = configuration,  001 = BRAM contents",
        "     [22] top/bottom   [21:17] row   [16:7] column   [6:0] minor",
    ], 18, C_GRF)
    far.to_edge(DOWN, buff=0.3).set_x(-1.0)
    sc.play(FadeIn(far), run_time=0.8)
    sc.wait(2.0)


def s5_crc(sc):
    sc.heading("The CRC that gates everything",
               "CRC-32C, and it covers the register address as well as the data")

    w = code_block([
        "for every WRITE data word (except writes to CRC itself):",
        "",
        "        37 bits  =  { register[4:0] , data[31:0] }",
        "",
        "        fed LSB first into CRC-32C, reflected 0x82F63B78, init 0",
    ], 22, INK)
    w[2].set_color(C_BIT)
    w.shift(UP * 1.3)
    sc.play(LaggedStart(*[FadeIn(l) for l in w], lag_ratio=0.25), run_time=1.8)

    bar = fieldbar([("register[4:0]", 5, C_GRF), ("data[31:0]", 32, C_BIT)],
                   total_w=9.0, h=0.7, size=17)
    bar.next_to(w, DOWN, buff=0.7)
    sc.play(Create(bar[0]), FadeIn(bar[1]), FadeIn(bar[2]), run_time=1.0)

    why = code_block([
        "including the register address means a corrupted HEADER is caught too,",
        "not just corrupted data - this is how prjxray documents the 7-series CRC.",
        "",
        "Any FDRI data word clears CRC_OK, so a CRC check MUST follow the frames",
        "before START is accepted. A half-written design can never run.",
    ], 19, INK)
    why[0].set_color(DIM); why[1].set_color(DIM)
    why[3].set_color(C_ERR); why[4].set_color(C_ERR)
    why.next_to(bar, DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in why], lag_ratio=0.2), run_time=1.8)
    sc.wait(2.2)


def s6_startup(sc):
    sc.heading("Startup", "UG470's sequence: the fabric is held inert until a good load "
                          "has been proven, then released one stage at a time")

    boxes = VGroup(
        chip("JPROGRAM", C_ERR, 2.3, 0.8, 19),
        chip("load\n(chain or frames)", C_BIT, 2.8, 0.9, 17),
        chip("JSTART\n+ 12 TCK in RTI", C_GRF, 2.8, 0.9, 17),
    ).arrange(RIGHT, buff=0.9).shift(UP * 2.0)
    for i, b in enumerate(boxes):
        sc.play(FadeIn(b), run_time=0.4)
        if i < 2:
            sc.play(GrowArrow(arrow(b.get_right(), boxes[i + 1].get_left(), DIM, 0.05)),
                    run_time=0.25)

    sig = ["GSR", "GTS", "GWE", "DONE"]
    init = ["1", "1", "0", "0"]
    rows = VGroup()
    for n, v in zip(sig, init):
        lab = mono(n, 22, INK)
        val = mono(v, 22, C_ERR)
        rows.add(VGroup(lab, val).arrange(RIGHT, buff=0.6))
    rows.arrange(DOWN, aligned_edge=LEFT, buff=0.42)
    rows.next_to(boxes, DOWN, buff=0.9).set_x(-4.0)
    meaning = VGroup(
        Text("every flip-flop forced to its INIT value", font_size=17, color=DIM),
        Text("every pad output forced to 0", font_size=17, color=DIM),
        Text("no flip-flop may change at all", font_size=17, color=DIM),
        Text("LD3 - the design is live", font_size=17, color=DIM),
    )
    for m, r in zip(meaning, rows):
        m.next_to(r, RIGHT, buff=0.7).set_y(r.get_y())
    sc.play(FadeIn(rows), FadeIn(meaning), run_time=0.9)
    at = mono("after power-up or JPROGRAM", 18, C_ERR)
    at.next_to(rows, UP, buff=0.35).align_to(rows, LEFT)
    sc.play(FadeIn(at), run_time=0.5)
    sc.wait(1.2)

    phase = mono("phase 0", 20, C_GRF).to_edge(RIGHT, buff=1.3).set_y(rows.get_y())
    sc.play(FadeIn(phase), run_time=0.4)
    steps = [(0, "0", "GSR released - flip-flops may move"),
             (1, "0", "GTS released - pads drive the LEDs"),
             (2, "1", "GWE asserted - flip-flops may change"),
             (3, "1", "DONE - LD3 lights")]
    for idx, newv, note in steps:
        nt = Text(note, font_size=19, color=C_BIT)
        nt.to_edge(DOWN, buff=0.5)
        sc.play(rows[idx][1].animate.become(
                    mono(newv, 22, C_RTL).move_to(rows[idx][1])),
                phase.animate.become(mono(f"phase {idx + 1}", 20, C_GRF)
                                     .move_to(phase)),
                FadeIn(nt), run_time=0.6)
        sc.wait(0.55)
        sc.play(FadeOut(nt), run_time=0.2)

    gate = Text("JSTART does nothing unless COMMITTED or the frame path accepted START. "
                "Without a proven load, DONE never rises.",
                font_size=20, color=C_ERR)
    gate.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(gate), run_time=0.9)
    sc.wait(2.2)


def s7_guards(sc):
    sc.heading("The refusals", "each of these is a rule in RTL, a scenario in tb_frames, "
                               "and a mutant in make mutate")

    rows = [
        ("frames while GWE = 1", "WR_ERROR - unless a partial reconfiguration freeze is acknowledged"),
        ("IDCODE never matched", "ID_ERROR - FDRI is refused outright"),
        ("wrong CRC", "CRC_ERROR - the parser parks and only JPROGRAM revives it"),
        ("START without CRC_OK", "refused - CRC_OK must come AFTER the last FDRI word"),
        ("chain with wrong length", "LEN_ERR - COMMITTED stays 0, JSTART refuses"),
        ("FDRO without RCFG", "WR_ERROR, zeros"),
        ("AGHIGH without IDCODE", "freeze not entered"),
        ("LFRM without a CRC", "WR_ERROR and the fabric STAYS frozen"),
    ]
    g = VGroup()
    for a, b in rows:
        g.add(VGroup(mono(a, 19, C_ERR), Text(b, font_size=17, color=DIM))
              .arrange(RIGHT, buff=0.4, aligned_edge=DOWN))
    for r in g:
        r[1].align_to(g[0][1], LEFT).shift(RIGHT * 4.2)
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.26)
    if g.width > 13.0:
        g.scale_to_fit_width(13.0)
    g.next_to(sc.mobjects[1], DOWN, buff=0.6).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in g], lag_ratio=0.15),
            run_time=2.6)

    m = Text("Two of these survived their first mutation run and had to earn new scenarios: "
             "'LFRM ignores the CRC' and 'FDRO without RCFG'.",
             font_size=19, color=C_BIT)
    m.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(m), run_time=0.9)
    sc.wait(2.4)


def s8_files(sc):
    sc.files_used(
        inputs=[("hw/src/core/cfg_store.v", "the memory + both write paths"),
                ("hw/src/core/cfg_frames.v", "the UG470 packet parser"),
                ("hw/src/core/cfg_ctrl.v", "chain CRC, length, startup FSM")],
        generated=[("hw/src/generated/bob_params.vh", "NFRAMES, FAR_TABLE"),
                   ("tools/bob/device.json", "frames, columns, chain order"),
                   ("tools/bob/packets.py", "stream builder + a bit-level model")],
        verified=[("hw/tb/tb_frames.v", "71 checks, expectations from the model"),
                  ("sim/mutate_frames.sh", "29 mutants, all killed"),
                  ("tests/test_hwtest_fake.py", "a stand-in board, good and broken")])


EP03 = [s1_memory, s2_layout, s3_chain, s4_frames, s5_crc, s6_startup, s7_guards, s8_files]


class Ep03Config(BobScene):
    def construct(self):
        self.titlecard("EPISODE 3", "The configuration engine",
                       "one memory, two write paths, and the startup that gates them")
        for i, part in enumerate(EP03):
            part(self)
            if i < len(EP03) - 1:
                clear_all(self)


class E03S1Memory(BobScene):
    def construct(self): s1_memory(self)


class E03S2Layout(BobScene):
    def construct(self): s2_layout(self)


class E03S3Chain(BobScene):
    def construct(self): s3_chain(self)


class E03S4Frames(BobScene):
    def construct(self): s4_frames(self)


class E03S5Crc(BobScene):
    def construct(self): s5_crc(self)


class E03S6Startup(BobScene):
    def construct(self): s6_startup(self)


class E03S7Guards(BobScene):
    def construct(self): s7_guards(self)


class E03S8Files(BobScene):
    def construct(self): s8_files(self)
