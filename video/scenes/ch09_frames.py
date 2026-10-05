"""Chapter 09 - Frame-based configuration (UG470 chapter 5, simplified): sync hunt, packets,
the parser FSM, registers, FAR, CMD, the CRC over {register, data}, the load stream,
partial reconfiguration, BRAM content frames, GRESTORE and time travel."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bobvid.scene import *


def bitbox(word, groups, size=0.3, font=12):
    """A 32-bit word drawn MSB left, split into labelled groups [(hi, lo, label, colour)]."""
    cells = VGroup()
    for i in range(31, -1, -1):
        b = (word >> i) & 1
        sq = Square(size, stroke_width=1, color=FAINT)
        cells.add(VGroup(sq, mono(str(b), font, INK if b else DIM).move_to(sq)))
    cells.arrange(RIGHT, buff=0.02)
    labs = VGroup()
    for hi, lo, lab, col in groups:
        seg = VGroup(*[cells[31 - k] for k in range(hi, lo - 1, -1)])
        for c in seg:
            c[0].set_stroke(col, width=1.6).set_fill(col, opacity=0.2)
        br = Brace(seg, DOWN, buff=0.05, color=col)
        t = txt(lab, 13, col)
        fit(t, max(seg.width * 1.3, 1.0))
        t.next_to(br, DOWN, buff=0.05)
        labs.add(VGroup(br, t))
    return VGroup(cells, labs)


class Ch09Frames(BobScene):
    CH = "09"
    TITLE = "Frame-based configuration"
    SUBTITLE = "AMD 7-series packets on CFG_IN and CFG_OUT (UG470 chapter 5), simplified where noted"

    def construct(self):
        F = self.F
        self.title_card(
            "The second way into the configuration memory is the one bob load uses by default: "
            "AMD-style frames, carried in packets, exactly as a seven-series bitstream reaches a real part.")
        self.why()
        self.sync(F)
        self.header()
        self.parser(F)
        self.registers(F)
        self.far()
        self.crc()
        self.stream(F)
        self.partial()
        self.bram_frames()
        self.restore()
        self.simpl()
        self.files_card(
            "The frame controller is one Verilog file and one Python model. Every expected value in its "
            "testbench comes from the model, so the two cannot drift apart, and thirty-eight mutants prove "
            "each guard is tested.",
            [("hw/src/core/cfg_frames.v", "sync, parser, registers, FAR, CRC"),
             ("software/bob/packets.py", "streams + the Controller model"),
             ("software/host/snapshot.py", "save and restore state")],
            [("bob load", "sparse stream after JPROGRAM"),
             ("packets.py dump x.bit", "the stream, annotated")],
            [("hw/tb/tb_frames.v", "every error, partial, BRAM frames"),
             ("sim/mutate_frames.sh", "38 mutants, all killed"),
             ("hwtest partial-live, frames-bram-load", "on the board")])

    # ------------------------------------------------------------------
    def why(self):
        self.heading("Why frames as well as a chain", "three things a single long scan cannot do")
        items = [("self-synchronising", "the stream finds its own start: it may be split across any number of JTAG scans", C_CYN),
                 ("addressable", "write or read one frame at a time: partial reconfiguration, readback of a part", C_BIT),
                 ("self-checking", "a CRC over every write and an IDCODE check, as a real .bit file carries", C_RTL)]
        rows = VGroup(*[VGroup(bold(a, 22, c), txt(b, 18, INK)).arrange(DOWN, aligned_edge=LEFT, buff=0.08) for a, b, c in items])
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.45).move_to(DOWN * 0.2)
        both = txt("both paths write the same memory; a board check loads through one and reads back through the other", 17, DIM).next_to(rows, DOWN, buff=0.45)
        fit(both, 13)
        with self.narrate(
                "Why have a second path at all? The project was asked for frame-based writing just like AMD's, "
                "slightly simplified, and frames buy three things. The stream finds its own start, so it can be "
                "split however the host likes. Frames are addressable, so part of the memory can be rewritten or "
                "read. And the stream checks itself, with a CRC and the device's identity."):
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in rows], lag_ratio=0.4), run_time=2.4)
            self.play(FadeIn(both), run_time=0.6)
        self.wipe()

    def sync(self, F):
        sync = int(F["frames_ctrl"]["sync"], 16)
        self.heading("Finding the start: the sync word", f"the controller compares a 32-bit window, bit by bit, with {F['frames_ctrl']['sync']}")
        stream = "11111111" + format(sync, "032b") + "001100000000000000001000000000000001"
        win = 32
        cells = VGroup(*[mono(c, 15, DIM) for c in stream[:60]]).arrange(RIGHT, buff=0.06).move_to(UP * 1.1)
        fit(cells, 13.2)
        box = SurroundingRectangle(VGroup(*cells[0:win]), color=C_GRF, buff=0.06)
        lbl = txt("32-bit window", 15, C_GRF).next_to(box, UP, buff=0.1)
        notes = VGroup(
            txt("words are shifted in MSB first, as a 7-series .bit reaches a part over JTAG", 17, INK),
            txt("dummy words (FFFFFFFF) before the sync word are ignored", 17, INK),
            txt("after the match, every 32 bits is a word; Capture-DR and Update-DR do not break the alignment", 17, INK),
            txt("JPROGRAM or the DESYNC command returns the controller to hunting", 17, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.12).next_to(cells, DOWN, buff=0.7)
        fit(notes, 13)
        with self.narrate(
                f"The controller starts out hunting. It slides a thirty-two bit window along the incoming bits, "
                f"one bit at a time, until the window equals the sync word, A A nine nine five five six six, "
                f"AMD's own value. Dummy words before it are simply ignored."):
            self.play(FadeIn(cells), Create(box), FadeIn(lbl), run_time=0.8)
            for k in (2, 4, 8):
                self.play(box.animate.move_to(VGroup(*cells[k:k + win]).get_center()), lbl.animate.shift(RIGHT * (VGroup(*cells[k:k + win]).get_x() - box.get_x())), run_time=0.4)
            for c in cells[8:8 + win]:
                c.set_color(C_BIT)
            self.play(Indicate(VGroup(*cells[8:8 + win]), color=C_BIT, scale_factor=1.02), run_time=0.7)
        with self.narrate(
                "From then on every thirty-two bits is a word, however the host splits the stream into scans."):
            self.play(FadeIn(notes, lag_ratio=0.25), run_time=1.4)
        self.wipe()

    def header(self):
        self.heading("A packet header", "type 1: an operation, a register, and a word count (UG470 table 5-20)")
        w = 0x30008001
        bb = bitbox(w, [(31, 29, "type 001", C_GRF), (28, 27, "op 10 = WRITE", C_BIT), (17, 13, "register 00100 = CMD", C_CYN),
                        (10, 0, "word count = 1", C_RTL)], size=0.36, font=13)
        bb.move_to(UP * 0.9)
        hexw = mono("0x30008001", 26, C_BIT).next_to(bb, UP, buff=0.3)
        then = VGroup(mono("0x00000007", 22, C_RTL), txt("the one data word: CMD <- 7 = RCRC, reset the CRC", 17, INK)).arrange(RIGHT, buff=0.3).next_to(bb, DOWN, buff=0.9)
        t2 = VGroup(txt("type 2 (010): only a 27-bit count, for the same operation; the FDRI idiom is", 17, DIM),
                    mono("30004000  5000xxxx   = WRITE FDRI, count 0, then type 2 with the real count", 17, DIM)).arrange(DOWN, aligned_edge=LEFT, buff=0.1).next_to(then, DOWN, buff=0.4)
        fit(t2, 13)
        with self.narrate(
                "After the sync word come packets. Here is one header, three zero zero zero eight zero zero one, "
                "decoded. The top three bits say type one. The next two say write. Five bits name a register: "
                "four, the command register. And the low eleven bits say one data word follows."):
            self.play(FadeIn(hexw), FadeIn(bb[0], lag_ratio=0.02), run_time=1.2)
            self.play(LaggedStart(*[FadeIn(l) for l in bb[1]], lag_ratio=0.4), run_time=1.6)
        with self.narrate(
                "So the next word is written to the command register: seven, which resets the CRC. For long "
                "writes like frame data, a type one header with a count of zero is followed by a type two "
                "header that carries a twenty-seven bit count."):
            self.play(FadeIn(then, shift=UP * 0.1), run_time=0.7)
            self.play(FadeIn(t2), run_time=0.7)
        self.wipe()

    def parser(self, F):
        sts = F["frames_ctrl"]["parser_states"]
        self.heading("The packet parser", f"cfg_frames.v: a hunt flag and four states, {', '.join(sts)}")
        states = ["HUNT", "HDR", "T2", "DATA", "ERR"]
        pos = {"HUNT": (-5.0, 0.8), "HDR": (-1.4, 0.8), "T2": (2.4, 1.9), "DATA": (2.4, -0.5), "ERR": (-1.4, -1.8)}
        edges = [("HUNT", "HDR", "sync word", 0), ("HDR", "T2", "type 1, count 0", 0), ("T2", "DATA", "type 2", 0),
                 ("HDR", "DATA", "WRITE, count > 0", 0), ("DATA", "HDR", "last word", -0.6), ("HDR", "HDR", "NOP / READ", 0),
                 ("HDR", "ERR", "", 0), ("ERR", "HUNT", "JPROGRAM only", -0.4), ("HDR", "HUNT", "DESYNC", -0.6)]
        g, nodes, arrs = fsm(states, edges, pos, size=17, h=0.6, w=1.5)
        nodes["ERR"][0].set_color(C_ERR)
        errl = txt("unknown header, register or command;\nCRC mismatch; IDCODE mismatch", 14, C_ERR).next_to(nodes["ERR"], RIGHT, buff=0.35)
        rd = txt("a READ queues words for CFG_OUT: frames from FAR, STAT, FAR, IDCODE or CRC", 16, DIM).to_edge(DOWN, buff=1.3)
        fit(rd, 13)
        with self.narrate(
                "The parser is a small state machine. Once synchronised it expects a header. A write with a "
                "count goes straight to the data state; a count of zero first expects a type two header. After "
                "the last data word it expects a header again."):
            self.play(FadeIn(VGroup(*nodes.values()), lag_ratio=0.1), run_time=1.0)
            for e in [("HUNT", "HDR"), ("HDR", "T2"), ("T2", "DATA"), ("HDR", "DATA"), ("DATA", "HDR"), ("HDR", "HDR")]:
                self.play(Create(arrs[e]), run_time=0.4)
        with self.narrate(
                "Anything wrong, an unknown header, register or command, a CRC or IDCODE mismatch, sends it to "
                "the error state, which only JPROGRAM can leave. The DESYNC command returns it to hunting. A "
                "read has no data words in the input: it queues words for the output instruction."):
            self.play(Create(arrs[("HDR", "ERR")]), FadeIn(errl), run_time=0.7)
            self.play(Create(arrs[("ERR", "HUNT")]), Create(arrs[("HDR", "HUNT")]), run_time=0.8)
            self.play(FadeIn(rd), run_time=0.5)
        self.wipe()

    def registers(self, F):
        fc = F["frames_ctrl"]
        self.heading("Registers and commands", "7-series addresses and codes; the subset bob implements")
        rmean = {"CRC": "compare with the running CRC", "FAR": "frame address, auto-increments",
                 "FDRI": "frame data in: 4 words fill a frame", "FDRO": "frame data out", "CMD": "a command, below",
                 "STAT": "status", "IDCODE": "must match before any frame is accepted"}
        cmean = {"NULL": "", "WCFG": "arm frame writes", "LFRM": "last frame; release a freeze", "RCFG": "arm frame reads",
                 "START": "allow startup (needs a CRC match)", "RCRC": "reset the CRC", "AGHIGH": "freeze the user clock (M14)",
                 "GRESTORE": "flip-flops take INIT (M25)", "DESYNC": "back to hunting"}
        rc = VGroup(*[VGroup(mono(f"{v:05b}", 16, C_BIT), mono(n.ljust(7), 16, C_CYN), txt(rmean[n], 15, INK)).arrange(RIGHT, buff=0.25)
                      for n, v in fc["regs"]]).arrange(DOWN, aligned_edge=LEFT, buff=0.14)
        cc = VGroup(*[VGroup(mono(f"{v:>2}", 16, C_BIT), mono(n.ljust(9), 16, C_GRF), txt(cmean[n], 15, INK)).arrange(RIGHT, buff=0.25)
                      for n, v in fc["cmds"] if n != "NULL"]).arrange(DOWN, aligned_edge=LEFT, buff=0.14)
        hr = txt("registers", 18, C_CYN, weight=BOLD).next_to(rc, UP, buff=0.2).align_to(rc, LEFT)
        hc = txt("CMD values", 18, C_GRF, weight=BOLD).next_to(cc, UP, buff=0.2).align_to(cc, LEFT)
        both = VGroup(VGroup(hr, rc), VGroup(hc, cc)).arrange(RIGHT, buff=0.8, aligned_edge=UP).move_to(DOWN * 0.15)
        fit(both, 13.2)
        with self.narrate(
                "These are the registers a packet can address. FAR holds the frame address. FDRI takes frame "
                "data, four words to a frame, and FDRO returns it. CRC checks integrity, IDCODE checks "
                "identity, STAT reports status, and CMD takes commands."):
            self.play(FadeIn(both[0], lag_ratio=0.05), run_time=1.4)
        with self.narrate(
                "The commands arm writes and reads, reset the CRC, mark the last frame, allow startup, return "
                "to hunting, and two that later milestones added: AGHIGH freezes the user clock, and GRESTORE "
                "loads every flip-flop's initial value. All the codes are AMD's own."):
            self.play(FadeIn(both[1], lag_ratio=0.05), run_time=1.4)
        self.wipe()

    def far(self):
        self.heading("The frame address register", "the 7-series layout (UG470 table 5-24)")
        a = bitbox(0x00000080, [(25, 23, "block type", C_BIT), (22, 22, "top", DIM), (21, 17, "row", C_CYN),
                                (16, 7, "column", C_RTL), (6, 0, "minor", C_GRF)], size=0.34, font=12).move_to(UP * 1.2)
        ah = mono("FAR = 0x00000080: block type 0, column 1, minor 0", 19, C_BIT).next_to(a, UP, buff=0.25)
        notes = VGroup(
            txt("block type 000: configuration · column = FAR column · minor = frame within the column", 17, INK),
            txt("block type 001 (M15): BRAM contents · column = BRAM index", 17, INK),
            txt("after every whole frame FAR advances; past a column's last frame, to minor 0 of the next", 17, INK),
            txt("so one FDRI packet can write a run of consecutive frames without another address", 17, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.12).next_to(a, DOWN, buff=0.6)
        fit(notes, 13)
        with self.narrate(
                "A frame address uses AMD's field layout: a block type, a row, a column, and a minor address, "
                "the frame within its column. Block type zero is configuration; block type one, since milestone "
                "fifteen, is block RAM contents."):
            self.play(FadeIn(ah), FadeIn(a[0], lag_ratio=0.02), run_time=1.0)
            self.play(LaggedStart(*[FadeIn(l) for l in a[1]], lag_ratio=0.3), run_time=1.4)
        with self.narrate(
                "After every frame the address moves on by itself, across column boundaries, so a single data "
                "packet can write a whole run of frames."):
            self.play(FadeIn(notes, lag_ratio=0.25), run_time=1.2)
        self.wipe()

    def crc(self):
        self.heading("The packet CRC", "CRC-32C over {register[4:0], data[31:0]}, as prjxray computes the 7-series one")
        code = code_block([
            ("crc = 0                      // RCRC sets it to 0", C_CYN),
            ("for every WRITE data word (not to CRC):", DIM),
            ("    for each of the 37 bits of {reg, data}, LSB first:", DIM),
            ("        crc = (crc >> 1) ^ ((crc ^ bit) & 1 ? 0x82F63B78 : 0)", C_BIT),
            ("a WRITE to CRC compares:  equal -> CRC_OK,  different -> CRC_ERROR, parser stops", C_RTL),
            ("START and LFRM need CRC_OK after the last frame word", C_RTL),
        ], size=17).move_to(UP * 0.4)
        fit(code, 13)
        with self.narrate(
                "Every data word written, together with the five-bit address of the register it went to, "
                "feeds a running CRC. Near the end of the stream the host writes the value it expects. If "
                "they differ the parser stops, and startup is refused."):
            self.play(FadeIn(code, lag_ratio=0.15), run_time=1.8)
        with self.narrate(
                "Any frame data clears the match, so a CRC check must follow the last frame. A corrupted or "
                "truncated stream cannot start a design."):
            self.play(Indicate(code[-1], color=C_RTL), run_time=1.0)
        self.wipe()

    def stream(self, F):
        ex = F["counter"]
        self.heading("The stream bob load sends", f"the counter example: {ex['sparse_words']} words, only the {ex['sparse_frames']} frames that hold a 1")
        lines = ex["sparse_head"]
        code = code_block([(l, C_BIT if "sync" in l else C_CYN if "WRITE" in l or "NOP" in l else INK) for l in lines], size=15)
        code.move_to(LEFT * 2.6 + DOWN * 0.15)
        fit(code, 7.6, 5.2)
        rest = VGroup(
            txt("… then a FAR + FDRI pair per run of non-zero frames", 16, INK),
            txt("CRC <- expected · CMD LFRM · CMD START · CMD DESYNC", 16, INK),
            txt("then: STAT read, FDRO readback of all 532 frames,", 16, INK),
            txt("JSTART + 12 TCK, DONE", 16, INK),
            txt("sparse is safe only right after JPROGRAM,", 15, DIM),
            txt("which has already zeroed every frame", 15, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.12).next_to(code, RIGHT, buff=0.5)
        fit(rest, 5.4)
        with self.narrate(
                f"Here is the real stream that loads the counter example. Two dummy words, the sync word, reset "
                f"the CRC, write the IDCODE so the device can check it, arm frame writes, then a frame address "
                f"and the frame data."):
            self.play(FadeIn(code, lag_ratio=0.05), run_time=2.2)
        with self.narrate(
                f"Because JPROGRAM has just zeroed the memory, only frames containing a one are sent: "
                f"{ex['sparse_frames']} frames, {ex['sparse_words']} words instead of more than two thousand. "
                f"Then the expected CRC, last frame, start, and desync. The host reads every frame back to "
                f"check, and runs the startup sequence."):
            self.play(FadeIn(rest, lag_ratio=0.2), run_time=1.6)
        self.wipe()

    def partial(self):
        self.heading("Partial reconfiguration (M14)", "rewrite only the frames that changed, while the design keeps its state (UG470, UG909)")
        steps = [("scan 1  CFG_IN", "sync, RCRC, IDCODE, CMD AGHIGH", C_GRF),
                 ("scan 2  CFG_OUT", "STAT: wait for GHIGH_B = 0 (frozen, chapter 06)", C_CYN),
                 ("scan 3  CFG_IN", "WCFG, FAR + FDRI for each run of changed frames, CRC, LFRM, DESYNC", C_BIT),
                 ("scan 4  CFG_OUT", "STAT: GHIGH_B = 1, no error; chain readback equals the new design", C_RTL)]
        rows = VGroup(*[VGroup(mono(a, 18, c), txt(b, 17, INK)).arrange(RIGHT, buff=0.4) for a, b, c in steps])
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.3).move_to(UP * 0.7)
        fit(rows, 13)
        facts = VGroup(
            txt("a changed truth table in one CLB is one frame; a re-routed small design a few dozen", 17, INK),
            txt("registers keep their values across the change: no GSR; the testbench proves a free-running counter holds, then continues", 17, INK),
            txt("a wrong or missing CRC leaves the fabric frozen with an error: a half-written design never runs", 17, C_ERR),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.12).next_to(rows, DOWN, buff=0.5)
        fit(facts, 13)
        with self.narrate(
                "Frames make partial reconfiguration possible. The host compares the new design with the old "
                "one, freezes the user clock with AGHIGH, waits for the acknowledgement, writes only the frames "
                "that differ, and sends LFRM with a fresh CRC."):
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in rows], lag_ratio=0.35), run_time=2.2)
        with self.narrate(
                "Changing one truth table rewrites one frame. Every register keeps its value across the "
                "change, and the testbench proves it with a counter that holds while frozen and then carries "
                "on. If the CRC is wrong, the fabric stays frozen."):
            self.play(FadeIn(facts, lag_ratio=0.3), run_time=1.4)
        self.wipe()

    def bram_frames(self):
        self.heading("BRAM contents as frames (M15)", "FAR block type 001: one CRC-covered stream for the whole design")
        mem = VGroup(*[Rectangle(width=2.2, height=0.32, color=C_PY, stroke_width=1).set_fill(C_PY, opacity=0.1) for _ in range(8)])
        mem.arrange(DOWN, buff=0.03).move_to(LEFT * 4.0 + DOWN * 0.3)
        ml = VGroup(*[mono(f"{4 * k}..{4 * k + 3}", 12, DIM).next_to(mem[k], LEFT, buff=0.08) for k in range(8)])
        mt = txt("BRAM 0, addresses", 15, C_PY).next_to(mem, UP, buff=0.15)
        frame = VGroup(*[chip(f"word {w}: {{14'b0, data[17:0]}}", C_BIT, w=3.8, h=0.42, size=14, mono_font=True) for w in range(4)])
        frame.arrange(DOWN, buff=0.06).move_to(RIGHT * 1.2 + UP * 0.6)
        fl = txt("frame n = 4 words = addresses 4n .. 4n+3", 16, C_BIT).next_to(frame, UP, buff=0.15)
        notes = VGroup(
            txt("256 frames per BRAM; FAR rolls into the next BRAM", 16, INK),
            txt("written through the RAM's port A by a sysclk sequencer", 16, INK),
            txt("only while GWE = 0, like USER4", 16, INK),
            txt("read back over FDRO, compared with the design", 16, INK),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.1).next_to(frame, DOWN, buff=0.45).align_to(frame, LEFT)
        ar = arrow(frame.get_left(), mem[2].get_right(), C_BIT, sw=2.5, tip=0.14)
        with self.narrate(
                "AMD carries block RAM contents in the bitstream as their own block type, and since milestone "
                "fifteen bob does too. Each frame of block type one holds four consecutive words of a memory, "
                "each in the low eighteen bits of a thirty-two bit word."):
            self.play(FadeIn(mem), FadeIn(ml), FadeIn(mt), run_time=0.7)
            self.play(FadeIn(frame, lag_ratio=0.15), FadeIn(fl), GrowArrow(ar), run_time=1.0)
        with self.narrate(
                "So a whole design, configuration and memory contents, travels as one stream under one CRC, "
                "and is read back and compared after loading."):
            self.play(FadeIn(notes, lag_ratio=0.2), run_time=1.2)
        self.wipe()

    def restore(self):
        self.heading("GRESTORE and time travel (M25)", "after Attia and Betz, TRETS 2022: save every flip-flop, restore it later")
        steps = [("1  freeze", "AGHIGH: the user clock stops", C_CYN),
                 ("2  save", "CAPTURE reads every element output, so every flip-flop", C_RTL),
                 ("3  rewrite INIT", "partial frames set each flip-flop's ff_init to the saved value", C_BIT),
                 ("4  GRESTORE", "UG470 CMD 10: GSR for one word; every flip-flop takes its INIT", C_GRF),
                 ("5  put back, release", "the original INIT frames, CRC, LFRM: the design resumes from the snapshot", C_PY)]
        rows = VGroup(*[VGroup(mono(a, 18, c), txt(b, 17, INK)).arrange(RIGHT, buff=0.35) for a, b, c in steps])
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.24).move_to(UP * 0.4)
        fit(rows, 13)
        use = txt("bob snap: save a running design, restore it, or move its state into the simulator and back", 17, DIM).next_to(rows, DOWN, buff=0.4)
        with self.narrate(
                "The newest command makes something unusual possible: time travel. Freeze the design and read "
                "every flip-flop through CAPTURE. Later, write those values into the flip-flops' initial-value "
                "bits with partial frames, and issue GRESTORE, AMD's command that pulses global set-reset."):
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in rows[:4]], lag_ratio=0.35), run_time=2.0)
        with self.narrate(
                "Every flip-flop jumps to its saved value; put the original frames back, release the clock, and "
                "the design carries on from the moment it was saved. Milestone twenty-six's separate INIT bit "
                "is what makes this exact."):
            self.play(FadeIn(rows[4], shift=RIGHT * 0.2), run_time=0.6)
            self.play(FadeIn(use), run_time=0.5)
        self.wipe()

    def simpl(self):
        self.heading("Where bob simplifies 7-series", "listed in the spec, so nobody mistakes it for the real format")
        items = [
            "a frame is written when its last word arrives: no trailing pad frame, and no leading pad frame on readback",
            "no encryption, compression, bus-width detection, per-frame ECC, COR options or multiboot",
            "FAR does not roll from configuration into BRAM contents: the stream writes FAR again",
            "an error is left only by JPROGRAM",
            "a frame is 4 words here; a 7-series frame is 101",
        ]
        b = bullets(items, size=19, buff=0.28).move_to(DOWN * 0.2)
        fit(b, 13)
        with self.narrate(
                "And where bob departs from the real thing, the specification says so: no pad frames, no "
                "encryption or compression, no error correction, and frames of four words instead of a hundred "
                "and one. The structure, the codes and the checks are AMD's; the scale is bob's."):
            self.play(LaggedStart(*[FadeIn(x, shift=RIGHT * 0.15) for x in b], lag_ratio=0.25), run_time=2.0)
        self.wipe()
