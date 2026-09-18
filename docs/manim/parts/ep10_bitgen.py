# =============================================================================
#  EPISODE 10 - Bitstream generation: FASM, bitgen, and the .bit container
# =============================================================================

def s1_fasm(sc):
    sc.heading("FASM: the seam between 'where things go' and 'which bits are set'",
               "borrowed from F4PGA / prjxray - a feature is a name and a value, nothing more")

    ex = code_block([
        "clb_x2y3.init      = 64'h8888888888888888",
        "clb_x2y3.ff_en     = 1'h1",
        "bram0.wmode_a      = 2'h1",
        "ctrl.clk_div       = 5'hF",
        "rr1204             = 3'h2",
    ], 24, C_BIT)
    exp = panel(ex, C_BIT)
    exp.shift(UP * 1.5)
    sc.play(FadeIn(exp), run_time=0.9)

    kinds = code_block([
        "<block>.<field>   a field of a CLB, BRAM or DSP block",
        "ctrl.<field>      the 8-bit ctrl tile - the user clock",
        "rr<node>          the routing mux of rr-graph node <node>",
        "",
        "only non-zero features need writing; everything else is 0",
    ], 20, INK)
    kinds[4].set_color(DIM)
    kinds.next_to(exp, DOWN, buff=0.8).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in kinds], lag_ratio=0.18), run_time=1.6)

    why = Text("Because it is text, the same file can come from VPR or from bob's own PnR, "
               "and you can read it, diff it and hand-edit it.",
               font_size=20, color=C_BIT)
    why.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.4)
    sc.play(FadeIn(why), run_time=0.9)
    sc.wait(2.0)


def s2_bitgen(sc):
    sc.heading("bitgen: FASM to bits, and back again exactly",
               "tools/bob/bitgen.py checks every feature against device.json before setting a bit")

    f = mono("clb_x2y3.ff_en = 1'h1", 22, C_BIT).shift(UP * 2.1)
    sc.play(FadeIn(f), run_time=0.5)

    steps = [
        ("look up the block", "device.json: clb_x2y3 is at chain_lo = 9412", C_PY),
        ("look up the field", "ff_en is offset 64, width 1", C_PY),
        ("check the width", "the declared 1'h must equal the device's", C_ERR),
        ("check the value", "fits the field; a mux value must be a real input", C_ERR),
        ("set the bit", "chain bit 9412 + 64 = 9476", C_RTL),
    ]
    g = VGroup()
    for a, b, col in steps:
        g.add(VGroup(mono(a, 20, col), Text(b, font_size=17, color=DIM))
              .arrange(RIGHT, buff=0.5, aligned_edge=DOWN))
    for r in g:
        r[1].align_to(g[0][1], LEFT).shift(RIGHT * 3.8)
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.26)
    if g.width > 12.6:
        g.scale_to_fit_width(12.6)
    g.next_to(f, DOWN, buff=0.7).set_x(0)
    for r in g:
        sc.play(FadeIn(r, shift=RIGHT * 0.2), run_time=0.4)

    rt = code_block([
        "and the other direction: chain -> FASM decodes every configurable field",
        "and REFUSES any set bit that no feature owns - the padding, the tail.",
        "",
        "So chain -> FASM -> chain is exact.  bitgen.py --roundtrip proves it.",
    ], 20, INK)
    rt[3].set_color(C_BIT)
    rt.next_to(g, DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in rt], lag_ratio=0.2), run_time=1.7)
    sc.wait(2.0)


def s3_bitfile(sc):
    sc.heading("The .bit container",
               "host-side only - the chip never sees a header. Chain file version 2.")

    rows = [
        ("BOBC", "magic", C_GRF),
        ("version = 2", "version 1 files still load", C_GRF),
        ("device name", "bob12x10 - a bitstream for the wrong device is refused", C_ERR),
        ("chain width W", "18560 - so is the wrong size", C_ERR),
        ("CRC-32C", "checked BEFORE any hardware is touched", C_ERR),
        ("the chain bytes", "byte j = chain bits [8j+7 : 8j]", C_BIT),
        ("section: BRAM", "index, first address, count, words - one per used BRAM", C_VPR),
        ("section: META", "JSON: design, top, source sha256s, pcf, PnR hash, clock", C_PY),
        ("file CRC-32C", "over every byte before it", C_ERR),
    ]
    g = VGroup()
    for a, b, col in rows:
        box = Rectangle(width=3.4, height=0.5, color=col, stroke_width=2)
        box.set_fill(col, opacity=0.16)
        t = mono(a, 17, INK)
        if t.width > 3.2:
            t.scale_to_fit_width(3.2)
        note = Text(b, font_size=16, color=DIM)
        g.add(VGroup(VGroup(box, t.move_to(box)), note)
              .arrange(RIGHT, buff=0.5, aligned_edge=LEFT))
    for r in g:
        r[1].align_to(g[0][1], LEFT).shift(RIGHT * 3.9)
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.12)
    if g.height > 5.2:
        g.scale_to_fit_height(5.2)
    g.next_to(sc.mobjects[1], DOWN, buff=0.45).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=UP * 0.15) for r in g], lag_ratio=0.12),
            run_time=2.2)

    note = Text("Three independent refusals before a single TCK pulse: wrong device, "
                "wrong width, corrupt file.", font_size=19, color=C_BIT)
    note.scale_to_fit_width(12.8).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(note), run_time=0.8)
    sc.wait(2.0)


def s4_load(sc):
    sc.heading("./bob load", "what actually happens between the file and a lit LED")

    steps = [
        "check the file: magic, device, width, CRC",
        "JPROGRAM  - clear the memory, drop DONE",
        "send the frames on CFG_IN, BRAM contents in the same CRC-covered stream",
        "read STAT: START accepted, no error",
        "FDRO readback of the whole memory - must equal the .bit",
        "JSTART + 12 TCK in Run-Test/Idle",
        "read DONE",
    ]
    g = VGroup()
    for i, s in enumerate(steps):
        n = mono(f"{i + 1}.", 20, C_BIT)
        t = Text(s, font_size=19, color=INK)
        g.add(VGroup(n, t).arrange(RIGHT, buff=0.35, aligned_edge=DOWN))
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
    if g.width > 12.6:
        g.scale_to_fit_width(12.6)
    g.next_to(sc.mobjects[1], DOWN, buff=0.7).set_x(0)
    for r in g:
        sc.play(FadeIn(r, shift=RIGHT * 0.2), run_time=0.4)

    alt = code_block([
        "./bob load x.bit                the frame path (default)",
        "./bob load x.bit --mode chain   the same memory, one giant scan + USER4",
        "./bob load x.bit --partial      only the frames that differ, design keeps running",
    ], 19, C_PY)
    alt.next_to(g, DOWN, buff=0.7).set_x(0)
    sc.play(FadeIn(alt), run_time=0.9)

    ver = Text("Every load is verified by reading the memory back. A load that cannot be "
               "read back is a failed load, not a warning.",
               font_size=19, color=C_BIT)
    ver.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(ver), run_time=0.8)
    sc.wait(2.0)


def s5_files(sc):
    sc.files_used(
        inputs=[("tools/bob/bitgen.py", "FASM <-> chain, .bit reader and writer"),
                ("tools/bob/fasm_from_vpr.py", "PnR result -> FASM features"),
                ("tools/bob/cli.py", "./bob build | load | info | fasm")],
        generated=[("build/bit/<name>.bit", "the loadable bitstream"),
                   ("the FASM text", "./bob fasm x.bit prints it back out"),
                   ("docs/reports/M11/designs.md", "per-design cells, CLBs, CRC")],
        verified=[("tests/test_bitgen.py", "round trip, bad features rejected"),
                  ("sim/tb_cosim.v", "the real .bit loaded into the full FPGA RTL"),
                  ("docs/hwtest/results.log", "bob-* checks: readback == FASM on the board")])


EP10 = [s1_fasm, s2_bitgen, s3_bitfile, s4_load, s5_files]


class Ep10Bitgen(BobScene):
    def construct(self):
        self.titlecard("EPISODE 10", "Bitstream generation",
                       "FASM, bitgen, and the container that refuses bad files")
        for i, part in enumerate(EP10):
            part(self)
            if i < len(EP10) - 1:
                clear_all(self)


class E10S1Fasm(BobScene):
    def construct(self): s1_fasm(self)


class E10S2Bitgen(BobScene):
    def construct(self): s2_bitgen(self)


class E10S3Bitfile(BobScene):
    def construct(self): s3_bitfile(self)


class E10S4Load(BobScene):
    def construct(self): s4_load(self)


class E10S5Files(BobScene):
    def construct(self): s5_files(self)
