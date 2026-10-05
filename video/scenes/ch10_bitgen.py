"""Chapter 10 - Bitstream generation: the counter through yosys, equivalence, VPR, FASM,
bitgen and the .bit v2 container, then bob load. Every artefact is from example/ at c072b6d."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bobvid.scene import *


class Ch10Bitgen(BobScene):
    CH = "10"
    TITLE = "Bitstream generation"
    SUBTITLE = "one design, the counter, through every stage from Verilog to a running fabric"

    def construct(self):
        F = self.F
        self.title_card(
            "Now the tools. This chapter follows one small design, a six-bit counter, through every stage "
            "of bob's flow, using the real files the flow produced for it.")
        self.pipeline()
        self.source(F)
        self.synth(F)
        self.equiv()
        self.pnr(F)
        self.fasm(F)
        self.bitfile(F)
        self.load(F)
        self.files_card(
            "Each stage is one Python module around an established tool, and each one is checked against "
            "the one before: source against netlist, FASM against the device, bits against the model, and "
            "the board against the golden netlist.",
            [("software/bob/synth.py", "the yosys script, bob cells"),
             ("software/bob/vpr_run.py · pnr/", "VPR, or bob's own PnR"),
             ("software/bob/fasm_from_vpr.py · bitgen.py", "FASM, the .bit file")],
            [(f"example/ at {F['example_rev']}", "the counter, every stage kept"),
             ("software/bob/vpr/<design>/", "committed VPR results, stamped")],
            [("software/bob/equiv.py", "source == netlist == golden"),
             ("hw/tb/tb_cosim.v", "every example, both PnRs"),
             ("bitgen.py --roundtrip", "FASM -> bits -> FASM exact")])

    # ------------------------------------------------------------------
    def pipeline(self):
        self.heading("The flow", "./bob build design.v, then ./bob load design.bit")
        st = [("Verilog", INK), ("yosys", C_PY), ("equivalence", C_PY), ("VPR / bob PnR", C_VPR),
              ("FASM", C_BIT), ("bitgen", C_BIT), (".bit", C_BIT), ("bob load", C_GRF), ("fabric", C_RTL)]
        chips = VGroup(*[chip(n, c, w=1.38, h=0.75, size=15) for n, c in st]).arrange(RIGHT, buff=0.12).move_to(UP * 0.6)
        fit(chips, 13.4)
        ar = VGroup(*[arrow(chips[i].get_right(), chips[i + 1].get_left(), DIM, buff=0.02, sw=2, tip=0.1) for i in range(len(chips) - 1)])
        checks = ["", "only bob cells", "300 cycles\nsource == netlist", "legal, routed", "checked vs\ndevice.json",
                  "round trip\nexact", "CRC, META", "readback ==\nFASM", "LEDs, CAPTURE\n== golden"]
        cl = VGroup(*[txt(c, 13, DIM).next_to(ch, DOWN, buff=0.18) for c, ch in zip(checks, chips) if c])
        with self.narrate(
                "From the user's side this is two commands: bob build, then bob load. Underneath, the design "
                "passes through synthesis, an equivalence check, place and route, a text form called FASM, the "
                "bitstream generator, the file, and the loader."):
            self.play(LaggedStart(*[FadeIn(c) for c in chips], lag_ratio=0.12), Create(ar), run_time=2.2)
        with self.narrate(
                "And every arrow is checked. Nothing is trusted because a tool said it worked: each stage is "
                "compared with the one before it, and finally with the hardware."):
            self.play(FadeIn(cl, lag_ratio=0.1), run_time=1.4)
        self.wipe()

    def source(self, F):
        ex = F["counter"]
        self.heading("The design", "work/examples/counter/counter.v")
        code = code_block(ex["verilog"], size=19)
        fit(code, 12.6, 5.2)
        code.move_to(DOWN * 0.1)
        code[0].set_color(DIM)
        with self.narrate(
                "Here it is: a six-bit register that counts while button zero is held, resets to zero on "
                "button one, and shows its top three bits on the LEDs. Small, but it has state, a reset, an "
                "enable and an adder, which exercises most of the logic block."):
            self.play(FadeIn(code, lag_ratio=0.06), run_time=1.6)
        self.wipe()

    def synth(self, F):
        cells = F["counter"]["cells"]
        self.heading("1  Synthesis with yosys", "a synth_xilinx-shaped script that maps only to bob's cells")
        lib = VGroup(
            mono("$lut       K-input LUT          -> an element's LUT", 18, INK),
            mono("BOB_ADD    one carry stage      -> an element in carry mode", 18, INK),
            mono("BOB_FDRE   flip-flop, reset     -> FF / FF2", 18, INK),
            mono("BOB_FDSE   flip-flop, set       -> FF / FF2", 18, INK),
            mono("BOB_BRAM18 memory               -> a BRAM tile", 18, INK),
            mono("BOB_DSP    multiply             -> a DSP slice", 18, INK),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.1).move_to(UP * 1.0)
        got = VGroup(*[mono(f"{n:9s} × {v}", 22, C_BIT) for n, v in cells.items()]).arrange(DOWN, aligned_edge=LEFT, buff=0.1)
        gl = txt("the counter becomes", 17, DIM)
        res = VGroup(gl, got).arrange(DOWN, aligned_edge=LEFT, buff=0.12).next_to(lib, DOWN, buff=0.45).to_edge(LEFT, buff=1.4)
        notes = VGroup(
            txt("any other cell left over: the build stops", 16, INK),
            txt("more than one clock: the build stops", 16, INK),
            txt("$alu -> BOB_ADD is rule _80_, so it beats", 16, INK),
            txt("yosys's generic _90_alu", 16, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.08).next_to(res, RIGHT, buff=1.2).align_to(res, UP)
        with self.narrate(
                "Synthesis is yosys, running the same sequence of passes as its Xilinx flow, but mapping onto "
                "bob's own cell library: lookup tables, a carry stage, two kinds of flip-flop, the block RAM and "
                "the DSP. If anything else survives, or the design has a second clock, the build stops with a clear error."):
            self.play(FadeIn(lib, lag_ratio=0.1), run_time=1.6)
            self.play(FadeIn(notes[:2]), run_time=0.6)
        with self.narrate(
                f"The counter becomes {cells.get('BOB_ADD', 0)} carry stages and {cells.get('BOB_FDRE', 0)} "
                f"flip-flops, with no LUTs at all: the increment lives entirely in the carry chain. One subtle "
                f"point: bob's adder rule is named so that it sorts ahead of yosys's generic one, or the generic "
                f"one wins."):
            self.play(FadeIn(res), run_time=0.7)
            self.play(FadeIn(notes[2:]), run_time=0.6)
        self.wipe()

    def equiv(self):
        self.heading("2  Equivalence, and the golden netlist", "synthesis bugs are silent, so the netlist is simulated against the source")
        s = chip("counter.v\n(source)", INK, w=2.4, h=1.0, size=16).move_to(LEFT * 4.6 + UP * 0.9)
        n = chip("counter_syn.v\n(bob cells)", C_PY, w=2.4, h=1.0, size=16).move_to(LEFT * 1.4 + UP * 0.9)
        g = chip("counter_golden.v\none wire per bit", C_BIT, w=2.6, h=1.0, size=16).move_to(RIGHT * 2.0 + UP * 0.9)
        eq1 = mono("==", 26, C_RTL).move_to(mid(s.get_center(), n.get_center()))
        eq2 = mono("==", 26, C_RTL).move_to(mid(n.get_center(), g.get_center()))
        cyc = txt("300 biased random cycles, compared before and after every edge, the trace saved", 17, INK).next_to(VGroup(s, g), DOWN, buff=0.4)
        story = VGroup(
            bold("the counter's trace that was all zeros (M8)", 18, C_ERR),
            txt("uniform random inputs held the synchronous reset half the time,", 16, INK),
            txt("so the counter never counted and the check could not fail;", 16, INK),
            txt("vectors are now biased and generated in 50-cycle segments", 16, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.08).next_to(cyc, DOWN, buff=0.45)
        why = txt("the golden netlist names every register, so CAPTURE bit i can later be compared with register n on the board", 16, C_BIT).next_to(story, DOWN, buff=0.3)
        fit(why, 13)
        with self.narrate(
                "Synthesis bugs make no noise, so the flow simulates the source and the synthesised netlist "
                "side by side, for three hundred cycles of random inputs, and compares them at every clock edge. "
                "It also writes a golden netlist, with one named wire for every bit, so that every register can "
                "later be found on the board."):
            self.play(FadeIn(s), FadeIn(n), FadeIn(eq1), run_time=0.7)
            self.play(FadeIn(g), FadeIn(eq2), FadeIn(cyc), run_time=0.8)
        with self.narrate(
                "The inputs are deliberately biased. In milestone eight, uniform random buttons held the reset "
                "half the time, so the counter never counted, its trace was all zeros, and the check could not "
                "have failed. Stimulus has to be checked too."):
            self.play(FadeIn(story, lag_ratio=0.2), run_time=1.2)
            self.play(FadeIn(why), run_time=0.6)
        self.wipe()

    def pnr(self, F):
        ex = F["counter"]
        v = ex["vpr"]
        self.heading("3  Place and route", "VPR 9 on the committed rr graph, or bob's own: the same file formats either way")
        g, cells = grid_view(F, cell=0.3, gap=0.05)
        g.move_to(LEFT * 3.6 + DOWN * 0.3)
        used = [(7, 2), (7, 3), (0, 3), (0, 4), (13, 1), (13, 2), (13, 3), (1, 0)]
        hl = VGroup(*[SurroundingRectangle(cells[u], color=C_BIT, buff=0.02, stroke_width=3) for u in used if u in cells])
        st = VGroup(
            mono(f"clusters (CLBs)  {v['clbs']}", 19, INK),
            mono(f"pads             {v['pads']}", 19, INK),
            mono(f"wirelength       {v['wirelength']}", 19, INK),
            mono(f"VPR's cpd        {float(v['cpd_ns']):.1f} ns", 19, INK),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.1)
        st.move_to([-0.6 + st.width / 2, 1.3, 0])
        steps = VGroup(
            txt("prepare: constants folded, carry chains cut to the column height,", 16, INK),
            txt("buffers where a flip-flop's D is not a lone LUT output, pins fixed", 16, INK),
            txt("pack -> place (annealing) -> route (PathFinder, negotiated congestion)", 16, INK),
            txt("bob's own PnR does the same in ~1,500 lines of Python: 0.93× VPR's wirelength", 16, C_BIT),
            txt("VPR runs in Docker, fixed seed; results are committed with a stamp", 15, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.1).next_to(st, DOWN, buff=0.45).align_to(st, LEFT)
        fit(steps, 7.2)
        with self.narrate(
                "Next the netlist is prepared for VPR: constants folded, carry chains cut to fit a column, pins "
                "fixed to the board's switches and LEDs. VPR packs it into clusters, places them by simulated "
                "annealing, and routes the nets with PathFinder, on exactly the routing graph the hardware was "
                "generated from."):
            self.play(FadeIn(g, lag_ratio=0.004), run_time=1.0)
            self.play(FadeIn(steps[:3], lag_ratio=0.2), run_time=1.2)
        with self.narrate(
                f"The counter needs {v['clbs']} logic blocks, stacked so the carry runs straight up, and "
                f"{v['pads']} pads. bob also has its own packer, placer and router, small enough to read, which "
                f"write the same files, so everything after this point is shared."):
            self.play(Create(hl), FadeIn(st, lag_ratio=0.2), run_time=1.2)
            self.play(FadeIn(steps[3:], lag_ratio=0.2), run_time=0.8)
        self.wipe()

    def fasm(self, F):
        ex = F["counter"]
        self.heading("4  FASM: the configuration as text", f"F4PGA's format: one feature = value per line · the counter has {ex['fasm_lines']} lines")
        lines = ex["fasm_sample"][:6] + ["..."] + ex["fasm_rr_sample"][:3] + ["ctrl.clk_mode = 1'h0"]
        code = code_block([(l, C_RTL if l.startswith("clb") else C_GRF if l.startswith("rr") else DIM if l == "..." else C_BIT) for l in lines], size=18)
        code.move_to(LEFT * 2.6 + DOWN * 0.2)
        notes = VGroup(
            txt("element features: flags, crossbar selects, INIT", 16, C_RTL),
            txt("rr<node> = the select of that routing mux", 16, C_GRF),
            txt("every line checked against device.json:", 16, INK),
            txt("unknown feature or value out of range -> error", 16, INK),
            txt("readable, diffable, hand-editable", 16, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.12).next_to(code, RIGHT, buff=0.6)
        with self.narrate(
                "The routed result becomes FASM, the text format of the F4PGA project: one line per configuration "
                "feature that is not zero. For the counter: carry and Double Duty flags, flip-flop enables, "
                "crossbar selects, and one line per routing mux, named by its node number, holding its select value."):
            self.play(FadeIn(code, lag_ratio=0.08), run_time=1.8)
        with self.narrate(
                "Every line is checked against the device description, so a misspelt feature or an out-of-range "
                "value is caught here, long before hardware. And being text, two configurations can be compared "
                "with an ordinary diff."):
            self.play(FadeIn(notes, lag_ratio=0.2), run_time=1.2)
        self.wipe()

    def bitfile(self, F):
        ex = F["counter"]
        self.heading("5  bitgen and the .bit file", f"FASM -> the {F['chain_width']:,}-bit configuration word -> a {ex['bit_bytes']:,}-byte file (format version 2)")
        hexl = code_block([(l[:58], INK) for l in ex["bit_hex"]], size=17).move_to(UP * 1.5)
        fields = [("BOBC", 4, C_BIT), ("ver 2", 2, C_CYN), ("len 8", 2, C_CYN), ("bob12x10", 8, C_PY),
                  ("width", 4, C_GRF), ("chain CRC", 4, C_RTL), ("the chain, LSB first …", 8, C_BIT)]
        bar = fieldbar(fields, total_w=12.0, h=0.5, size=14, show_ranges=False).next_to(hexl, DOWN, buff=0.55)
        parts = VGroup(
            mono(f"width = 0x00010A00 = {F['chain_width']:,} bits      chain CRC-32C = {ex['bit_crc']}", 16, INK),
            txt("then: a section count, and tagged sections: BRAM (contents of each RAM used), META (JSON:", 16, INK),
            txt("design, sources and their sha256, PnR result hash, clock), and a CRC over the whole file", 16, INK),
            txt(f"the counter: {ex['bit_features']} settings, critical path {ex['bit_cpd_ns']} ns, timed from its bits (chapter 06)", 16, C_BIT),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.1).next_to(bar, DOWN, buff=0.4)
        fit(parts, 13)
        with self.narrate(
                "bitgen turns FASM into the configuration word: each feature's name gives its field, and the "
                "field gives its bit positions. The conversion runs both ways, and the round trip is exact."):
            self.play(FadeIn(hexl, lag_ratio=0.2), run_time=1.0)
        with self.narrate(
                "The file starts with a magic number, B O B C, the format version, the device name, the chain "
                "width and the chain's own CRC. Then the configuration bits, then tagged sections: the contents "
                "of any block RAM the design uses, and a JSON record of exactly what the file was built from. A "
                "CRC over the whole file closes it."):
            self.play(FadeIn(bar, lag_ratio=0.1), run_time=1.2)
            self.play(FadeIn(parts, lag_ratio=0.25), run_time=1.6)
        self.wipe()

    def load(self, F):
        ex = F["counter"]
        self.heading("6  bob load", "what happens between the command and the LEDs")
        steps = [
            ("JPROGRAM", "clear the memory: the dark fabric", C_ERR),
            ("CFG_IN", f"the sparse stream: {ex['sparse_frames']} frames, {ex['sparse_words']} words, under one CRC", C_BIT),
            ("CFG_OUT", "STAT: synced, START accepted, no error", C_GRF),
            ("FDRO", f"read back all {F['frames']['count']} frames; decoded, they must equal the FASM", C_PY),
            ("contract", "the critical path must fit the gce spacing, or the load is refused", C_CYN),
            ("JSTART", "+ 12 TCK in Run-Test/Idle: GSR, GTS, GWE, DONE", C_RTL),
        ]
        rows = VGroup(*[VGroup(mono(a.ljust(9), 19, c), txt(b, 17, INK)).arrange(RIGHT, buff=0.35) for a, b, c in steps])
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.22).move_to(UP * 0.35)
        fit(rows, 13)
        then = txt("then the board check: 64 clocks, LEDs == source, CAPTURE of every register == golden netlist", 17, C_BIT).next_to(rows, DOWN, buff=0.45)
        fit(then, 13)
        with self.narrate(
                "Loading is just as careful. JPROGRAM clears the fabric. The sparse frame stream goes in over "
                "CFG in. The status register must show the start command accepted with no error. Then every "
                "frame is read back, decoded, and compared with the FASM it came from."):
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in rows[:4]], lag_ratio=0.3), run_time=2.0)
        with self.narrate(
                "Only then does the timing contract allow startup: JSTART, twelve test clocks, and DONE lights. "
                "On the board the tests then clock the design sixty-four times and compare its LEDs with the "
                "source and every register with the golden netlist."):
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in rows[4:]], lag_ratio=0.3), run_time=1.2)
            self.play(FadeIn(then), run_time=0.6)
        self.wipe()
