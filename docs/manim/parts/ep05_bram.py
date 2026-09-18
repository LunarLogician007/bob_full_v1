# =============================================================================
#  EPISODE 5 - BRAM: a UG473 RAMB18E1 subset, and why contents are separate
# =============================================================================

def s1_what(sc):
    sc.heading("bob's BRAM is a real RAMB18",
               "hw/src/tiles/bram_core.v is written to Vivado's inference template on purpose")

    mem = Rectangle(width=3.4, height=2.6, color=C_VPR, stroke_width=3)
    mem.set_fill(C_VPR, opacity=0.12)
    t = Text("1024 x 18\ntrue dual port", font_size=24, color=INK, line_spacing=0.8)
    core = VGroup(mem, t.move_to(mem)).move_to(np.array([0, 0.9, 0]))
    sc.play(FadeIn(core), run_time=0.7)

    for side, x, col in (("port A", -3.6, C_RTL), ("port B", 3.6, C_GRF)):
        pins = code_block(["addr[9:0]", "di[17:0]", "we", "en", "rst", "regce",
                           "", "do[17:0]"], 17, col)
        pins.move_to(np.array([x, 0.9, 0]))
        sc.play(FadeIn(pins), run_time=0.6)
        sc.play(GrowArrow(arrow(pins.get_right() if x < 0 else pins.get_left(),
                                mem.get_left() if x < 0 else mem.get_right(),
                                DIM, 0.25)), run_time=0.3)

    facts = code_block([
        "one block -> one RAMB18E1 on the host FPGA, not a pile of LUTs",
        "synchronous read (UG473): address is registered, data appears next cycle",
        "bob has two of them, in grid column x = 3, each 5 rows tall",
    ], 19, INK)
    facts.next_to(core, DOWN, buff=1.2).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in facts], lag_ratio=0.2), run_time=1.6)

    why = Text("Vivado's inference matches this RTL against a fixed template. Deviate from "
               "it and the same 1024 x 18 bits stop being a hard block - they become LUTs "
               "instead of one RAMB18.",
               font_size=19, color=C_BIT)
    why.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(why), run_time=0.9)
    sc.wait(2.0)


def s2_cfg(sc):
    sc.heading("Eight configuration bits", "that is the entire BRAM tile - the data is somewhere else")

    fields = [("wmode_a", 2, C_RTL), ("wmode_b", 2, C_GRF), ("reg_a", 1, C_BIT),
              ("reg_b", 1, C_BIT), ("jtag_a", 1, C_PY), ("jtag_b", 1, C_PY)]
    bar = fieldbar(fields, total_w=8.0, h=0.8, size=17)
    bar.shift(UP * 1.5)
    sc.play(Create(bar[0]), FadeIn(bar[1]), FadeIn(bar[2]), run_time=1.2)
    sc.wait(0.2)

    # two explicit columns (field name, then description) - built with absolute
    # coordinates rather than a chained align_to, which breaks when the anchor
    # row is itself one of the mutated rows (verified against this exact file)
    rows = [
        ("wmode_a / wmode_b", "0 WRITE_FIRST, 1 READ_FIRST, 2 NO_CHANGE (UG473)"),
        ("reg_a / reg_b", "DOA_REG / DOB_REG - one more pipeline stage on the output"),
        ("jtag_a / jtag_b", "USER4 drives that port's pins instead of the fabric -"),
        ("", "steps write modes one clock at a time from the host"),
    ]
    labels = [mono(a, 19, C_BIT) for a, _ in rows]
    descs = [Text(b, font_size=17, color=DIM) for _, b in rows]
    colw = max(l.width for l in labels) + 0.6
    g = VGroup()
    for i, (lab, desc) in enumerate(zip(labels, descs)):
        lab.move_to(np.array([lab.width / 2, -i * 0.45, 0]))
        desc.move_to(np.array([colw + desc.width / 2, -i * 0.45, 0]))
        desc.align_to(lab, DOWN)
        g.add(VGroup(lab, desc))
    g.next_to(bar, DOWN, buff=0.85).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in g], lag_ratio=0.18),
            run_time=1.8)

    trim = code_block([
        "trimmed from a real RAMB18E1, and we say so:",
        "   the 9 / 4 / 1-bit width modes (bit-level addressing stops inference)",
        "   per-byte write enables",
        "   separate RSTRAM / RSTREG pins - one RST pin drives both",
    ], 18, DIM)
    trim[0].set_color(C_ERR)
    trim.to_edge(DOWN, buff=0.35).set_x(0)
    sc.play(FadeIn(trim), run_time=0.9)
    sc.wait(2.0)


def s3_modes(sc):
    sc.heading("Three write modes out of one template",
               "only READ_FIRST is inferable - the other two are rebuilt around it")

    base = chip("bram_core.v\nVivado's READ_FIRST template", C_VPR, 5.0, 1.2, 20)
    base.shift(UP * 1.8)
    sc.play(FadeIn(base), run_time=0.6)
    sc.wait(0.2)

    outs = VGroup(
        chip("READ_FIRST\nthe old word appears", C_RTL, 3.4, 1.1, 18),
        chip("WRITE_FIRST\nthe new word appears", C_BIT, 3.4, 1.1, 18),
        chip("NO_CHANGE\nthe output holds", C_GRF, 3.4, 1.1, 18),
    ).arrange(RIGHT, buff=0.5).next_to(base, DOWN, buff=1.1)
    for o in outs:
        sc.play(GrowArrow(arrow(base.get_bottom(), o.get_top(), DIM, 0.12)),
                FadeIn(o), run_time=0.45)
    sc.wait(0.2)

    how = code_block([
        "WRITE_FIRST and NO_CHANGE are not separate memories - they are READ_FIRST",
        "plus one register and a mux on the output path. That register-and-mux is",
        "why the write mode can be a CONFIGURATION BIT, not a synthesis parameter.",
    ], 19, INK)
    how[2].set_color(C_BIT)
    how.next_to(outs, DOWN, buff=0.8).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in how], lag_ratio=0.2), run_time=1.6)
    sc.wait(0.4)

    teaser = mono("next: the same write, watched under all three modes", 18, DIM)
    teaser.to_edge(DOWN, buff=0.4)
    sc.play(FadeIn(teaser), run_time=0.7)
    sc.wait(1.4)


def s4_modes_demo(sc):
    sc.heading("One write, three outputs",
               "port A writes address 5 on one cycle - wmode_a picks what DO_A shows next")

    before = code_block([
        "before this cycle:  mem[5] = 7   DO_A already reads 3 (an earlier access)",
        "this cycle:  we_a=1  en_a=1  addr_a=5  di_a=42   <- write 42 over the 7",
        "(reg_a = 0 here - DOA_REG would add one more cycle of delay)",
    ], 19, INK)
    before[1].set_color(C_BIT)
    before.move_to(np.array([0, 1.95, 0]))
    sc.play(LaggedStart(*[FadeIn(l) for l in before], lag_ratio=0.25), run_time=1.4)
    sc.wait(0.5)

    label = Text("one clock later, DO_A reads back:", font_size=20, color=INK)
    label.next_to(before, DOWN, buff=0.4)
    sc.play(FadeIn(label), run_time=0.5)

    # same RTL fact as bram_core.v's latch_a mux: rst_qa ? 0 : (WRITE_FIRST ? din :
    # NO_CHANGE ? hold : ram_a) - ram_a itself is the pre-write read, so this is
    # also exactly "read and write the same address on the same port, same cycle"
    modes = [("READ_FIRST", 7, C_RTL, "the old word"),
             ("WRITE_FIRST", 42, C_BIT, "the new word"),
             ("NO_CHANGE", 3, C_GRF, "frozen - ignores this write")]
    chips = VGroup(*[chip(f"{name}\nDO_A = {val}", col, 3.4, 1.5, 20)
                     for name, val, col, _ in modes])
    chips.arrange(RIGHT, buff=0.5).next_to(label, DOWN, buff=0.55)
    sc.play(LaggedStart(*[FadeIn(c, shift=UP * 0.15) for c in chips], lag_ratio=0.25),
            run_time=1.4)

    caps = VGroup()
    for c, (_, _, col, cap) in zip(chips, modes):
        caps.add(mono(cap, 16, col).next_to(c, DOWN, buff=0.18))
    sc.play(LaggedStart(*[FadeIn(cp) for cp in caps], lag_ratio=0.2), run_time=0.8)
    sc.wait(1.0)

    close = code_block([
        "same memory, same write - only the output MUX differs, and wmode_a[1:0]",
        "drives it. tb_bram.v sweeps 36 mode x register combos: 5292 checks total.",
    ], 18, C_BIT)
    close[1].set_color(DIM)
    close.to_edge(DOWN, buff=0.45).set_x(0)
    sc.play(FadeIn(close), run_time=0.9)
    sc.wait(2.2)


def s5_contents(sc):
    sc.heading("Contents are not configuration",
               "UG470 keeps BRAM data in its own block type, and so does bob")

    mem = chip("the 1024 words", C_VPR, 3.2, 1.0, 21).shift(UP * 1.9)
    sc.play(FadeIn(mem), run_time=0.5)

    a = chip("USER4\nSELECT, LOAD_PTR,\nWRITE, READ", C_PY, 3.4, 1.4, 18)
    b = chip("FAR block type 001\nframes, inside the\nsame CRC stream", C_BIT, 3.8, 1.4, 18)
    a.move_to(np.array([-3.4, -0.1, 0]))
    b.move_to(np.array([3.4, -0.1, 0]))
    sc.play(GrowArrow(arrow(a.get_top(), mem.get_bottom(), DIM, 0.12)), FadeIn(a),
            run_time=0.6)
    sc.play(GrowArrow(arrow(b.get_top(), mem.get_bottom(), DIM, 0.12)), FadeIn(b),
            run_time=0.6)
    al = mono("M5, still used by --mode chain", 15, DIM).next_to(a, DOWN, buff=0.18)
    bl = mono("M15, the default", 15, DIM).next_to(b, DOWN, buff=0.18)
    sc.play(FadeIn(al), FadeIn(bl), run_time=0.4)

    frame = code_block([
        "block type 001:  column = BRAM index,  frame n = row x 128 + minor",
        "frame n holds addresses 4n .. 4n+3,  word = { 14'b0, data[17:0] }",
        "256 frames per BRAM; FAR auto-increments into the next one after that",
    ], 18, C_BIT)
    frame.next_to(VGroup(a, b), DOWN, buff=0.8).set_x(0)
    sc.play(FadeIn(frame), run_time=0.9)
    sc.wait(1.0)

    note = Text("both paths write into the same 1024 words - and both leave an untouched "
                "word exactly as it was.", font_size=18, color=DIM)
    note.scale_to_fit_width(12.5).to_edge(DOWN, buff=0.4)
    sc.play(FadeIn(note), run_time=0.8)
    sc.wait(2.0)


def s6_bug(sc):
    sc.heading("The bug that shipped: stale words",
               "M11, found on the board - contents survive JPROGRAM on purpose")

    rule = code_block([
        "both paths write only while GWE = 0 - you cannot rewrite a running memory",
        "JPROGRAM does NOT clear contents: they survive a reprogram, on purpose",
    ], 19, C_ERR)
    rule.move_to(np.array([0, 2.2, 0]))
    sc.play(FadeIn(rule), run_time=0.8)
    sc.wait(0.5)

    found = code_block([
        "docs/hwtest/results.log, M11:  bram0[4..7] read back",
        "68189  209573  104860  208805      model said   0  0  0  0",
    ], 19, C_ERR)
    found.next_to(rule, DOWN, buff=0.45).set_x(0)
    sc.play(FadeIn(found), run_time=0.9)
    sc.wait(0.6)

    cause = code_block([
        "cause: bob load wrote words only up to the last non-zero one per BRAM.",
        "a design whose own source is 0 past that point never overwrote the",
        "PREVIOUS design's words - they were never zero, just never touched.",
    ], 18, DIM)
    cause.next_to(found, DOWN, buff=0.5).set_x(0)
    sc.play(FadeIn(cause), run_time=1.0)
    sc.wait(0.5)

    fix = code_block([
        "fix: write all 1024 words of every used BRAM, always (cli.write_brams,",
        "load_stream) - a zero word overwrites now, it never just gets skipped.",
    ], 18, C_RTL)
    fix.next_to(cause, DOWN, buff=0.4).set_x(0)
    sc.play(FadeIn(fix), run_time=0.9)
    sc.wait(1.0)

    proof = Text("verified on the board: ram-readback now reads all 1024 words == model, "
                 "after JPROGRAM and loading a new design.", font_size=18, color=C_BIT)
    proof.scale_to_fit_width(12.8).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(proof), run_time=0.8)
    sc.wait(2.2)


def s7_files(sc):
    sc.files_used(
        inputs=[("hw/src/tiles/bram_core.v", "the inferable 1024x18 TDP memory"),
                ("hw/src/tiles/bram_block.v", "fabric pins or the USER4 drive word"),
                ("hw/src/tiles/bram_jtag.v", "USER4 commands + the M15 frame sequencer")],
        generated=[("software/bob/device.json", "the 8 fields, USER4 command codes"),
                   ("software/bob/model.py", "class Bram - the reference behaviour")],
        verified=[("hw/tb/tb_bram.v", "5292 checks, all 36 combinations"),
                  ("sim/mutate_fabric.sh", "bram-no-write-first, bram-en-ignored, ..."),
                  ("docs/hwtest/results.log", "ram-readback on the real board")])


EP05 = [s1_what, s2_cfg, s3_modes, s4_modes_demo, s5_contents, s6_bug, s7_files]


class Ep05BRAM(BobScene):
    def construct(self):
        self.titlecard("EPISODE 5", "BRAM",
                       "a UG473 subset, and why contents are not configuration")
        for i, part in enumerate(EP05):
            part(self)
            if i < len(EP05) - 1:
                clear_all(self)


class E05S1What(BobScene):
    def construct(self): s1_what(self)


class E05S2Cfg(BobScene):
    def construct(self): s2_cfg(self)


class E05S3Modes(BobScene):
    def construct(self): s3_modes(self)


class E05S4ModesDemo(BobScene):
    def construct(self): s4_modes_demo(self)


class E05S5Contents(BobScene):
    def construct(self): s5_contents(self)


class E05S6Bug(BobScene):
    def construct(self): s6_bug(self)


class E05S7Files(BobScene):
    def construct(self): s7_files(self)
