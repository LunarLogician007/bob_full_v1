"""Chapter 08 - The configuration memory and the scan-chain path: frames in memory, the single
frame buffer, CHAIN_IN, CRC-32C, CFG_CTRL and its write key, the startup FSM, JPROGRAM, the
BRAM shadow for readback."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bobvid.scene import *


class Ch08Config(BobScene):
    CH = "08"
    TITLE = "Configuration memory and the chain"
    SUBTITLE = "where the bits live, the first of two ways in, and how a design is released"

    def construct(self):
        F = self.F
        self.title_card(
            f"Every one of bob's {F['chain_width']:,} configuration bits lives in one memory. This "
            f"chapter is about that memory, the simplest way to fill it, and the sequence that starts a design.")
        self.layout(F)
        self.traps()
        self.chain(F)
        self.crc(F)
        self.ctrl(F)
        self.startup()
        self.jprogram(F)
        self.shadow()
        self.files_card(
            "The memory, the chain control and the startup sequence are three small Verilog files. "
            "Their testbenches take every expected value from the Python models, and a mutation suite "
            "breaks each guard in turn to prove the tests notice.",
            [("hw/src/core/cfg_store.v", "memory, frame buffer, shadow"),
             ("hw/src/core/cfg_ctrl.v", "CRC, length, CFG_CTRL, startup"),
             ("software/bob/chainbits.py", "the CRC, host side")],
            [("device.json frames", "FAR columns, frame counts"),
             ("bob_params.vh", "chain width, frame layout")],
            [("hw/tb/tb_cfg.v", "180 checks, M2 plane"),
             ("sim/mutate_cfg.sh", "CRC, length, key, start guards"),
             ("tb_frames [20]", "the shadow after JPROGRAM")])

    # ------------------------------------------------------------------
    def layout(self, F):
        fr = F["frames"]
        self.heading("The memory, as frames", f"{F['chain_width']:,} bits = {fr['count']} frames × {fr['words']} words × 32 bits, column by column")
        cols = fr["columns"]
        kinds = {}
        for blk in F["blocks"]:
            kinds.setdefault(blk["x"], set()).add(blk["type"])
        colmap = {"ctrl": C_BIT, "io": C_CYN, "clb": C_RTL, "bram": C_PY, "dsp": C_VPR}
        total = fr["count"]
        W = 12.6
        bar = VGroup()
        labels = VGroup()
        x = -W / 2
        for c in cols:
            if c["x"] is None:
                k = "ctrl"
            else:
                ks = kinds.get(c["x"], set())
                k = "bram" if "bram" in ks else "dsp" if "dsp" in ks else "clb" if "clb" in ks else "io"
            w = W * c["count"] / total
            r = Rectangle(width=max(w, 0.04), height=0.8, color=colmap[k], stroke_width=1).set_fill(colmap[k], opacity=0.45)
            r.move_to([x + w / 2, 0.9, 0])
            bar.add(r)
            if c["count"] >= 7:
                labels.add(mono(str(c["count"]), 13, INK).move_to(r))
            x += w
        ticks = VGroup(*[mono(f"col {c['far_col']}", 11, DIM).next_to(bar[i], DOWN, buff=0.08) for i, c in enumerate(cols) if c["count"] >= 7])
        lg = legend([("ctrl tile (FAR column 0)", C_BIT), ("I/O columns", C_CYN), ("CLB columns", C_RTL),
                     ("BRAM column", C_PY), ("DSP column", C_VPR)], 15)
        lg.arrange(RIGHT, buff=0.4).next_to(ticks, DOWN, buff=0.35)
        expl = VGroup(
            txt("FAR column x+1 = grid column x, tiles bottom to top: each block's fields, then its routing muxes", 17, INK),
            txt("each column padded to whole frames · the chain is all frames end to end, bit k = memory bit k", 17, DIM),
        ).arrange(DOWN, buff=0.1).next_to(lg, DOWN, buff=0.3)
        fit(expl, 13)
        with self.narrate(
                f"The configuration memory is organised as AMD organises its own: in frames. A frame is "
                f"four 32-bit words, {fr['bits']} bits, and the memory is {fr['count']} of them."):
            self.play(LaggedStart(*[GrowFromEdge(b, LEFT) for b in bar], lag_ratio=0.03), run_time=1.6)
            self.play(FadeIn(labels), FadeIn(ticks), run_time=0.6)
        with self.narrate(
                "Frames go column by column, like the configuration columns of a seven-series part. Column "
                "zero is the control tile. Then each grid column in turn, its tiles from bottom to top, "
                "each tile's block fields followed by its routing multiplexers. A logic-block column needs "
                "fifty-one frames; the memory and multiplier columns far fewer."):
            self.play(FadeIn(lg), run_time=0.6)
            self.play(FadeIn(expl, lag_ratio=0.3), run_time=1.0)
        self.wipe()

    def traps(self):
        self.heading("Two obvious designs, both traps", "bob fell into each one before finding the third")
        t1 = VGroup(bold("1  cfg[frame*128 +: 128] <= data", 19, C_ERR),
                    txt("a computed part-select is a barrel shifter over all 68k bits:", 16, INK),
                    txt("about 12,000 LUTs, 1.7 GB in yosys, and Vivado ran out of memory", 16, DIM)).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        t2 = VGroup(bold("2  a full-width shift register beside the memory", 19, C_ERR),
                    txt("the textbook scan chain: shift, then copy to a shadow", 16, INK),
                    txt("costs one flip-flop and one LUT per configuration bit, twice over", 16, DIM)).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        t3 = VGroup(bold("3  stream everything through one 128-bit frame buffer (M12b)", 19, C_RTL),
                    txt("each completed frame is written into its place with a per-frame enable", 16, INK),
                    txt("removed 3.6k LUTs and 4.8k flip-flops: what paid for the 36- and 100-CLB grids", 16, DIM)).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        g = VGroup(t1, t2, t3).arrange(DOWN, aligned_edge=LEFT, buff=0.4).move_to(DOWN * 0.2)
        fit(g, 13)
        with self.narrate(
                "How do bits get from JTAG into that memory? The first obvious answer writes a frame with a "
                "computed index into the memory. Synthesis turns that into a shifter across every bit, and "
                "the host tools ran out of memory."):
            self.play(FadeIn(t1, shift=RIGHT * 0.2), run_time=0.8)
        with self.narrate(
                "The second obvious answer, the textbook scan chain, keeps a whole second copy of the memory "
                "as a shift register. It works, but it doubles the cost."):
            self.play(FadeIn(t2, shift=RIGHT * 0.2), run_time=0.8)
        with self.narrate(
                "bob's answer is to stream everything through a single frame buffer of one hundred and "
                "twenty-eight bits, and write each completed frame into place. That one change paid for the "
                "larger grids."):
            self.play(FadeIn(t3, shift=RIGHT * 0.2), run_time=0.8)
        self.wipe()

    def chain(self, F):
        self.heading("Path 1: the chain (CHAIN_IN)", "the whole memory in one long data-register scan, least significant bit first")
        tdi = mono("TDI", 20, C_BIT).move_to(LEFT * 6.2 + UP * 1.2)
        buf = bitcells(16, size=0.36, on=set()).move_to(LEFT * 1.8 + UP * 1.2)
        bl = txt("frame buffer: 128 bits (16 drawn)", 16, C_BIT).next_to(buf, UP, buff=0.15)
        a = arrow(tdi.get_right(), buf.get_left(), C_BIT, sw=2.5, tip=0.14)
        mem = VGroup(*[Rectangle(width=4.6, height=0.3, color=FAINT, stroke_width=1).set_fill(FAINT, opacity=0.1) for _ in range(8)])
        mem.arrange(DOWN, buff=0.04).move_to(RIGHT * 4.0 + DOWN * 0.5)
        ml = txt("configuration memory, frame by frame", 16, DIM).next_to(mem, UP, buff=0.12)
        cnt = mono("frame n = 0", 18, C_CYN).next_to(buf, DOWN, buff=0.45)
        rules = VGroup(
            txt("every 128th bit completes frame n, written on the next falling edge, only while GWE = 0", 16, INK),
            txt("bits past the chain width are ignored; the CRC and a bit counter see every bit", 16, INK),
            txt("CHAIN_OUT reads it back the same way: frame by frame through the buffer, never writing", 16, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.1).to_edge(DOWN, buff=1.25)
        fit(rules, 13)
        with self.narrate(
                f"The first way in is the scan chain. Select the private instruction chain in, and shift all "
                f"{F['chain_width']:,} bits through TDI in one scan, least significant first. They enter the "
                f"frame buffer."):
            self.play(FadeIn(tdi), GrowArrow(a), FadeIn(buf), FadeIn(bl), run_time=0.8)
            self.play(FadeIn(mem), FadeIn(ml), FadeIn(cnt), run_time=0.6)
        with self.narrate(
                "Every hundred and twenty-eight bits complete a frame, which is written into its place in "
                "memory on the next falling clock edge, and the frame counter moves on. But only while "
                "writes to a running design are disabled: a running design is never rewritten underneath itself."):
            for n in range(3):
                for k in range(0, 16, 4):
                    on = VGroup(*[buf[i] for i in range(k, k + 4)])
                    self.play(on.animate.set_fill(C_BIT, opacity=0.8).set_stroke(C_BIT), run_time=0.12)
                cp = buf.copy()
                self.play(cp.animate.scale(0.5).move_to(mem[n]), run_time=0.5)
                self.play(mem[n].animate.set_fill(C_BIT, opacity=0.5).set_stroke(C_BIT), FadeOut(cp),
                          buf.animate.set_fill(opacity=0).set_stroke(FAINT),
                          Transform(cnt, mono(f"frame n = {n + 1}", 18, C_CYN).move_to(cnt)), run_time=0.4)
        with self.narrate(
                "Reading the chain back works the same way in reverse, and never writes."):
            self.play(FadeIn(rules, lag_ratio=0.3), run_time=1.2)
        self.wipe()

    def crc(self, F):
        poly = F["frames_ctrl"]["crc_poly_reflected"]
        self.heading("Integrity: CRC-32C, bit by bit", "Castagnoli polynomial, reflected; over exactly the bits shifted in")
        code = code_block([
            ("crc = 0xFFFFFFFF                       // at Capture-DR", C_CYN),
            (f"for each bit shifted in:", DIM),
            (f"    crc = (crc >> 1) ^ ((crc ^ bit) & 1 ? {poly} : 0)", C_BIT),
            ("result = ~crc", C_CYN),
            ("commit  only if  count == chain width  and  result == expected", C_RTL),
        ], size=19).move_to(UP * 0.9)
        why = VGroup(
            txt("init 0xFFFFFFFF on purpose: a stuck-low TDI shifts all zeros, which would match an expected CRC of 0", 17, INK),
            txt("check value: CRC-32C(\"123456789\") = 0xE3069283 pins the implementation in both RTL and Python", 17, INK),
            txt("the length check exists because its first version could be deleted with every test still passing", 17, C_ERR),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.14).next_to(code, DOWN, buff=0.5)
        fit(why, 13)
        with self.narrate(
                "While the bits stream in, a CRC is computed one bit at a time, with the Castagnoli "
                "polynomial, and a counter counts them. At the end of the scan the design is committed only "
                "if the count is exactly the chain width and the CRC equals the value the host promised in advance."):
            self.play(FadeIn(code, lag_ratio=0.15), run_time=1.6)
        with self.narrate(
                "Two details. The CRC starts at all ones, so a TDI wire stuck at zero cannot accidentally "
                "match. And the length check is guarded by a mutation test, because the first version of it "
                "could be deleted with every test still passing."):
            self.play(FadeIn(why, lag_ratio=0.3), run_time=1.4)
        self.wipe()

    def ctrl(self, F):
        key = F["frames_ctrl"]["ctrl_key"]
        self.heading("CFG_CTRL (USER2)", "64 bits: status out, and the expected CRC in, behind a write key")
        fields = [("~crc", 32, C_BIT), ("count", 16, C_CYN), ("ok", 1, C_RTL), ("ce", 1, C_ERR), ("le", 1, C_ERR),
                  ("C", 1, C_RTL), ("GSR", 1, C_GRF), ("GTS", 1, C_GRF), ("GWE", 1, C_GRF), ("DN", 1, C_GRF),
                  ("version / key", 8, C_PY)]
        bar = fieldbar(fields, total_w=12.8, h=0.6, size=13, min_w=0.62).move_to(UP * 1.3)
        key_l = txt("ok CRC_OK · ce CRC_ERR · le LEN_ERR · C COMMITTED · DN DONE", 14, DIM).next_to(bar, DOWN, buff=0.12)
        notes = VGroup(
            txt("Capture-DR: the CRC of the last scan, its length, the flags, and the startup state", 18, INK),
            txt(f"Update-DR writes the expected CRC only if bits [63:56] = {key}", 18, C_BIT),
            txt("so a read, which shifts zeros back in, can never change it (the idea of UG470's MASK register)", 17, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.14).next_to(key_l, DOWN, buff=0.45)
        fit(notes, 13)
        bar.add(key_l)
        with self.narrate(
                "The chain has a control register beside it. Reading it returns the last CRC, how many bits "
                "arrived, the error flags, whether a configuration is committed, and the four startup signals."):
            self.play(FadeIn(bar, lag_ratio=0.05), run_time=1.4)
            self.play(FadeIn(notes[0]), run_time=0.5)
        with self.narrate(
                "Writing it sets the expected CRC, but only if the top byte carries a key. Reading a JTAG "
                "register shifts new bits in at the same time, so without the key, every status read would "
                "silently overwrite the expected value."):
            self.play(FadeIn(notes[1:], lag_ratio=0.3), run_time=1.0)
        self.wipe()

    def startup(self):
        self.heading("The startup state machine", "cfg_ctrl.v: one phase per TCK in Run-Test/Idle with JSTART, only if COMMITTED")
        states = ["0  configuring", "1  GSR released", "2  GTS released", "3  GWE = 1", "4  DONE"]
        pos = {s: (-5.2 + 2.6 * i, 0.9) for i, s in enumerate(states)}
        edges = [(states[i], states[i + 1], "", 0) for i in range(4)]
        g, nodes, arrs = fsm(states, edges, pos, size=15, h=0.7, w=2.2)
        tick = txt("each arrow: one TCK in Run-Test/Idle with JSTART loaded", 15, DIM).next_to(VGroup(*nodes.values()), UP, buff=0.35)
        eff = ["GSR = 1, GTS = 1\nGWE = 0, DONE = 0", "flip-flops leave\nreset (INIT)", "outputs enabled", "flip-flop and RAM\nwrites enabled", "LD3 lights:\nthe design runs"]
        el = VGroup(*[txt(e, 14, DIM).next_to(nodes[s], DOWN, buff=0.2) for s, e in zip(states, eff)])
        nodes[states[4]][0].set_color(C_RTL)
        diff = VGroup(
            txt("the host clocks 12 TCKs in Run-Test/Idle after JSTART, as UG470's JTAG flow does", 17, INK),
            txt("bob's order is its own: AMD's default raises DONE in phase 4, then GTS and GWE;", 17, DIM),
            txt("bob raises DONE last, so a lit DONE means the design is running", 17, DIM),
            txt("without COMMITTED (a good chain CRC, or START accepted on the frame path) DONE never rises", 17, C_ERR),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.1).to_edge(DOWN, buff=1.2)
        fit(diff, 13)
        with self.narrate(
                "A loaded design does not start by itself. After power-up or JPROGRAM, global set-reset and "
                "the output tristate are held, writes are disabled, and DONE is low."):
            self.play(FadeIn(nodes[states[0]]), FadeIn(el[0]), FadeIn(tick), run_time=0.6)
        with self.narrate(
                "With the JSTART instruction loaded, each test clock in Run-Test Idle advances one phase. "
                "First the flip-flops leave reset, taking their initial values. Then the outputs are enabled. "
                "Then writes are enabled, so the design starts to run. Last, DONE rises."):
            for i in range(4):
                self.play(Create(arrs[(states[i], states[i + 1])]), FadeIn(nodes[states[i + 1]]), FadeIn(el[i + 1]), run_time=0.7)
        with self.narrate(
                "This follows UG470's principle, check first and then release in a safe order, but the order "
                "is bob's own: DONE comes last, so a lit DONE LED means the design is really running. And "
                "nothing advances unless a configuration was committed."):
            self.play(FadeIn(diff, lag_ratio=0.25), run_time=1.4)
        self.wipe()

    def jprogram(self, F):
        self.heading("JPROGRAM: back to the dark fabric", "UG470's instruction, acting at Update-IR")
        steps = VGroup(
            txt("configuration flip-flops cleared on the falling edge", 19, INK),
            txt("a 32-cycle sweep of zeros into every CFGLUT5 (lut_loader.v)", 19, INK),
            txt("every frame of the readback shadow marked invalid", 19, INK),
            txt("GSR = GTS = 1, GWE = DONE = 0, COMMITTED = 0", 19, INK),
            txt("not cleared: the expected CRC, and BRAM contents", 19, C_BIT),
        )
        rows = VGroup(*[VGroup(Dot(radius=0.06, color=C_CYN), s).arrange(RIGHT, buff=0.2) for s in steps])
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.22).move_to(UP * 0.4)
        res = txt("every mux selects constant 0, every table is 0: the dark, loop-free fabric of chapter 04", 18, C_CYN).next_to(rows, DOWN, buff=0.45)
        fit(res, 13)
        with self.narrate(
                "JPROGRAM resets all of it. The configuration flip-flops clear, every CFGLUT5 is swept to "
                "zero, readback is invalidated, and startup returns to phase zero. What survives is the "
                "expected CRC and the contents of the block RAMs."):
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.15) for r in rows], lag_ratio=0.25), run_time=2.0)
        with self.narrate(
                "Every mux now selects zero and every table is zero: the dark fabric again. That is also why "
                "a load straight after JPROGRAM may skip every frame that is all zeros."):
            self.play(FadeIn(res), run_time=0.6)
        self.wipe()

    def shadow(self):
        self.heading("Readback from a BRAM shadow (M21)", "what was written, kept in a block RAM beside the memory")
        buf = chip("frame buffer", C_BIT, w=2.4, h=0.8, size=17).move_to(LEFT * 4.2 + UP * 0.6)
        mem = chip("configuration memory\nflip-flops + CFGLUT5s", C_RTL, w=3.4, h=1.1, size=16).move_to(RIGHT * 0.6 + UP * 1.5)
        sh = chip("shadow\none host block RAM", C_PY, w=3.4, h=1.1, size=16).move_to(RIGHT * 0.6 + DOWN * 0.4)
        out = chip("CHAIN_OUT\nFDRO", C_GRF, w=2.2, h=1.0, size=16).move_to(RIGHT * 4.9 + DOWN * 0.4)
        a1 = arrow(buf.get_right(), mem.get_left(), C_BIT, sw=2.5, tip=0.14)
        a2 = arrow(buf.get_right(), sh.get_left(), C_BIT, sw=2.5, tip=0.14)
        a3 = arrow(sh.get_right(), out.get_left(), C_PY, sw=2.5, tip=0.14)
        same = txt("the same edge, the same data", 15, DIM).next_to(buf, DOWN, buff=0.3)
        trade = VGroup(
            txt("until M20 readback was a 256-way, 128-bit mux over the flip-flops: about a third of the design", 17, INK),
            txt("the trade: readback proves what was written, not what the cells hold;", 17, INK),
            txt("CAPTURE and the model checks cover the cells. A per-frame valid bit reads unwritten frames as 0.", 17, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.1).to_edge(DOWN, buff=1.25)
        fit(trade, 13)
        with self.narrate(
                "One more saving. Every frame written into the memory is also written, on the same edge, into "
                "a block RAM of the host. Readback, on either path, reads that copy."):
            self.play(FadeIn(buf), FadeIn(mem), GrowArrow(a1), run_time=0.8)
            self.play(FadeIn(sh), GrowArrow(a2), FadeIn(same), GrowArrow(a3), FadeIn(out), run_time=1.0)
        with self.narrate(
                "Before this, readback was a giant multiplexer over the configuration flip-flops, about a "
                "third of the whole design. The honest trade-off is that readback now proves what was "
                "written, not what the cells hold; the capture checks cover the cells."):
            self.play(FadeIn(trade, lag_ratio=0.3), run_time=1.4)
        self.wipe()
