"""Chapter 07 - JTAG: four wires, the 16-state TAP FSM walked, the timing contract, the
instruction register, Capture-IR as status, IDCODE, TDO high impedance, the Pico."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bobvid.scene import *

PRETTY = {"TEST_LOGIC_RESET": "Test-Logic-Reset", "RUN_TEST_IDLE": "Run-Test/Idle"}


def pretty(n):
    if n in PRETTY:
        return PRETTY[n]
    a, b = n.rsplit("_", 1)
    return a.replace("_", "").capitalize().replace("Exit1", "Exit1").replace("Exit2", "Exit2") + "-" + b


class Ch07Jtag(BobScene):
    CH = "07"
    TITLE = "JTAG and the TAP"
    SUBTITLE = "IEEE 1149.1: four wires, a sixteen-state machine, and AMD's 7-series instruction codes"

    def construct(self):
        F = self.F
        self.title_card(
            "Everything the host does to bob goes through one port: JTAG. This chapter walks its "
            "state machine edge by edge, and shows the instructions bob gives it.")
        self.wires(F)
        g, nodes, arrs = self.tap(F)
        self.walk(g, nodes, arrs)
        self.timing()
        self.irtable(F)
        self.status(F)
        self.files_card(
            "The TAP is one Verilog file using AMD's codes; the host speaks it through two Python layers; "
            "and every instruction is exercised in the chip-level testbench and on the board.",
            [("hw/src/core/jtag_tap6.v", "the TAP, IR, strobes, TDO enable"),
             ("software/host/dirtyjtag.py", "the Pico's USB protocol"),
             ("software/host/cfgplane.py", "every instruction by name")],
            [("hw/build.cfg", f"idcode = {F['idcode'][2:]}"),
             ("docs/bitstream-format.md §2-3", "the IR table and timing")],
            [("tb_bob [1]-[4]", "IR, chain, capture, status"),
             ("hwtest idcode, bypass", "the first checks of every run")])

    # ------------------------------------------------------------------
    def wires(self, F):
        self.heading("Four wires", "TCK clocks the port, TMS steers the state machine, TDI in, TDO out")
        mac = chip("Mac\ncfgplane.py", C_BIT, w=2.2, h=1.0, size=17).move_to(LEFT * 5.2 + DOWN * 0.3)
        pico = chip("Pico\nDirtyJTAG", C_GRF, w=2.2, h=1.0, size=17).move_to(LEFT * 1.8 + DOWN * 0.3)
        tap = chip("bob's TAP\njtag_tap6.v", C_RTL, w=2.4, h=2.4, size=18).move_to(RIGHT * 3.6 + DOWN * 0.3)
        usb = arrow(mac.get_right(), pico.get_left(), C_BIT, sw=3)
        ul = txt("USB", 14, DIM).next_to(usb, UP, buff=0.08)
        names = [("TCK", C_CYN, True), ("TMS", C_GRF, True), ("TDI", C_BIT, True), ("TDO", C_RTL, False)]
        ws = VGroup()
        for i, (n, c, fwd) in enumerate(names):
            y = tap.get_y() + 0.75 - 0.5 * i
            a, b = [pico.get_right()[0], y, 0], [tap.get_left()[0], y, 0]
            ar = Arrow(a, b, buff=0.05, color=c, stroke_width=3) if fwd else Arrow(b, a, buff=0.05, color=c, stroke_width=3)
            ws.add(VGroup(ar, mono(n, 15, c).next_to(ar, UP, buff=0.02)))
        lim = txt("TCK ≤ 1 MHz (M25): dirtyjtag.py refuses more, and the XDC is constrained at that period", 16, C_BIT).to_edge(DOWN, buff=1.3)
        with self.narrate(
                "JTAG is four wires. The test clock, TCK, clocks the whole port. TMS steers a small state "
                "machine. TDI carries bits in, and TDO carries bits out."):
            self.play(FadeIn(tap), run_time=0.5)
            self.play(LaggedStart(*[FadeIn(w) for w in ws], lag_ratio=0.3), run_time=1.4)
        with self.narrate(
                "bob's host is a Raspberry Pi Pico running the DirtyJTAG firmware, driven over USB by "
                "bob's Python. The test clock is limited to one megahertz, and the host-chip constraints "
                "are written for exactly that period."):
            self.play(FadeIn(pico), FadeIn(mac), GrowArrow(usb), FadeIn(ul), run_time=1.0)
            self.play(FadeIn(lim), run_time=0.6)
        self.wipe()

    def tap(self, F):
        self.heading("The TAP state machine", "sixteen states (IEEE 1149.1), state codes as in jtag_tap6.v")
        xD, xDs, xI, xIs = -2.6, -1.05, 1.0, 2.55
        pos = {"TEST_LOGIC_RESET": (-5.4, 1.75), "RUN_TEST_IDLE": (-5.4, -0.5),
               "SELECT_DR": (xD, 1.75), "CAPTURE_DR": (xD, 0.95), "SHIFT_DR": (xD, 0.15), "EXIT1_DR": (xD, -0.65),
               "PAUSE_DR": (xDs, -0.65), "EXIT2_DR": (xDs, 0.15), "UPDATE_DR": (xD, -1.55),
               "SELECT_IR": (xI, 1.75), "CAPTURE_IR": (xI, 0.95), "SHIFT_IR": (xI, 0.15), "EXIT1_IR": (xI, -0.65),
               "PAUSE_IR": (xIs, -0.65), "EXIT2_IR": (xIs, 0.15), "UPDATE_IR": (xI, -1.55)}
        names = [n for n, _ in F["tap_states"]]
        assert set(names) == set(pos)
        disp = {n: pretty(n) for n in names}
        st = [disp[n] for n in names]
        P = {disp[n]: pos[n] for n in names}
        E = []
        for s in ("DR", "IR"):
            d = lambda k: disp[f"{k}_{s}"]
            E += [(d("SELECT"), d("CAPTURE"), "0", 0), (d("CAPTURE"), d("SHIFT"), "0", 0),
                  (d("SHIFT"), d("EXIT1"), "1", 0), (d("EXIT1"), d("PAUSE"), "0", 0),
                  (d("PAUSE"), d("EXIT2"), "1", 0), (d("EXIT2"), d("SHIFT"), "0", 0),
                  (d("EXIT1"), d("UPDATE"), "1", 0), (d("SHIFT"), d("SHIFT"), "0", 0),
                  (d("PAUSE"), d("PAUSE"), "0", 0), (d("CAPTURE"), d("EXIT1"), "1", -0.9),
                  (d("EXIT2"), d("UPDATE"), "1", -0.6)]
        TLR, RTI = disp["TEST_LOGIC_RESET"], disp["RUN_TEST_IDLE"]
        E += [(TLR, TLR, "1", 0), (TLR, RTI, "0", 0), (RTI, RTI, "0", 0), (RTI, disp["SELECT_DR"], "1", 0),
              (disp["SELECT_DR"], disp["SELECT_IR"], "1", 0), (disp["SELECT_IR"], TLR, "1", 0.5),
              (disp["UPDATE_DR"], RTI, "0", 0), (disp["UPDATE_IR"], RTI, "0", -0.35)]
        g, nodes, arrs = fsm(st, E, P, size=12, h=0.42, w=1.4)
        g.scale(1.06).move_to([-1.3, 0.2, 0])
        codes = {n: v for n, v in F["tap_states"]}
        cl = VGroup(*[mono(f"{codes[n]:X}", 10, C_BIT).next_to(nodes[disp[n]], LEFT, buff=0.04).shift(UP * 0.12) for n in names])
        cols = VGroup(txt("data register column", 14, C_PY).next_to(nodes[disp["SELECT_DR"]], UP, buff=0.15),
                      txt("instruction register column", 14, C_GRF).next_to(nodes[disp["SELECT_IR"]], UP, buff=0.15))
        side = VGroup(
            txt("every arrow is taken on a rising TCK", 15, INK),
            txt("edge, labelled with the TMS value", 15, INK),
            txt("five TMS = 1 from anywhere reach", 15, INK),
            txt("Test-Logic-Reset, which selects IDCODE", 15, INK),
            txt("and does not touch configuration", 15, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.06).move_to(RIGHT * 5.4 + DOWN * 0.6)
        fit(side, 3.0)
        with self.narrate(
                "This is the TAP controller, the same sixteen states in every JTAG device. It moves on "
                "every rising edge of the test clock, and the only thing that steers it is the value on TMS."):
            self.play(FadeIn(VGroup(*nodes.values()), lag_ratio=0.05), FadeIn(cl), run_time=1.6)
            self.play(Create(VGroup(*arrs.values()), lag_ratio=0.02), FadeIn(cols), run_time=2.0)
        with self.narrate(
                "There are two identical columns: one for scanning a data register, one for the "
                "instruction register. Each has capture, shift, exit, pause and update states. Holding "
                "TMS high for five clocks from anywhere reaches Test-Logic-Reset, which in bob only "
                "selects the IDCODE register. It never touches the configuration."):
            self.play(FadeIn(side, lag_ratio=0.2), run_time=1.4)
        self.side = side
        self.disp = disp
        return g, nodes, arrs

    def walk(self, g, nodes, arrs):
        d = self.disp
        hl = highlight(nodes[d["TEST_LOGIC_RESET"]])
        tms_t = mono("TMS:", 17, C_GRF).move_to(LEFT * 6.1 + DOWN * 2.6)
        bits = VGroup().next_to(tms_t, RIGHT, buff=0.15)
        self.play(FadeOut(self.side), run_time=0.3)
        info = VGroup().move_to(RIGHT * 5.3 + DOWN * 0.6)

        def go(target, tms, note=None):
            nonlocal bits
            b = mono(str(tms), 17, C_GRF)
            if len(bits):
                b.next_to(bits[-1], RIGHT, buff=0.08)
            else:
                b.next_to(tms_t, RIGHT, buff=0.15)
            bits.add(b)
            anims = [hl.animate.move_to(nodes[d[target]][0].get_center()), FadeIn(b)]
            self.play(*anims, run_time=0.32)

        def say(text):
            nonlocal info
            t = txt(text, 15, INK)
            fit(t, 3.2)
            t.move_to(RIGHT * 5.3 + DOWN * 1.6)
            self.play(FadeOut(info), FadeIn(t), run_time=0.25)
            info = t

        with self.narrate(
                "Let us load an instruction. From reset, TMS zero goes to Run-Test Idle. One, one goes "
                "through Select-DR to Select-IR. Zero captures: the instruction register loads a fixed "
                "status pattern, which we will come back to."):
            self.play(Create(hl), FadeIn(tms_t), run_time=0.4)
            go("RUN_TEST_IDLE", 0)
            go("SELECT_DR", 1)
            go("SELECT_IR", 1)
            go("CAPTURE_IR", 0)
            say("Capture-IR: status loaded")
        with self.narrate(
                "Zero enters Shift-IR. Six clocks shift the six-bit instruction in on TDI, least significant "
                "bit first, while the captured status comes out on TDO. TMS goes high on the sixth bit, "
                "which leaves through Exit1."):
            go("SHIFT_IR", 0)
            say("Shift-IR: 6 bits, LSB first")
            for _ in range(5):
                b = mono("0", 17, C_GRF).next_to(bits[-1], RIGHT, buff=0.08)
                bits.add(b)
                self.play(FadeIn(b), Indicate(nodes[d["SHIFT_IR"]], scale_factor=1.05, color=C_BIT), run_time=0.3)
            go("EXIT1_IR", 1)
        with self.narrate(
                "One more one reaches Update-IR, where the new instruction takes effect on the falling "
                "edge, and zero returns to Run-Test Idle. A data-register scan then follows the left "
                "column in exactly the same way."):
            go("UPDATE_IR", 1)
            say("Update-IR: new instruction (falling edge)")
            go("RUN_TEST_IDLE", 0)
            for s, t in (("SELECT_DR", 1), ("CAPTURE_DR", 0), ("SHIFT_DR", 0), ("EXIT1_DR", 1), ("UPDATE_DR", 1), ("RUN_TEST_IDLE", 0)):
                go(s, t)
        self.wipe()

    def timing(self):
        self.heading("The timing contract", "proven on the hardware since the first milestone; do not change it casually")
        w = waveform([
            ("TCK", "0011001100110011001100"),
            ("TMS", "1111000000001111111111"),
            ("TDI", "0000111111110000000000"),
            ("TDO", "0000001111111100000000"),
        ], t_w=0.42, row_h=0.8, x0=-3.6, size=18, colors=[C_CYN, C_GRF, C_BIT, C_RTL])
        w.move_to(UP * 0.8)
        rises = VGroup(*[DashedLine([-3.6 + k * 0.42, 2.0, 0], [-3.6 + k * 0.42, -0.6, 0], color=C_CYN, stroke_width=1, dash_length=0.06)
                         for k in (2, 6, 10, 14, 18)])
        rules = VGroup(
            txt("TMS and TDI are sampled, and the state advances, on the rising edge", 18, INK),
            txt("TDO changes, and updates (IR, commit, JPROGRAM) happen, on the falling edge", 18, INK),
            txt("every shift register is LSB first: the first bit on TDI is bit 0", 18, INK),
            txt("M26: TDO is driven only in Shift-IR and Shift-DR, high impedance elsewhere (IEEE 1149.1)", 18, C_BIT),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.14).next_to(w, DOWN, buff=0.45)
        fit(rules, 13)
        with self.narrate(
                "The edges are fixed. The probe changes TMS and TDI on the falling edge, and the TAP samples "
                "them, and moves, on the rising edge. TDO and every update happen on the falling edge, so "
                "each side has half a clock to settle."):
            self.play(Create(w, lag_ratio=0.1), run_time=1.6)
            self.play(Create(rises), run_time=0.6)
            self.play(FadeIn(rules[:2], lag_ratio=0.3), run_time=1.0)
        with self.narrate(
                "Every register shifts least significant bit first. And since milestone twenty-six, TDO is "
                "only driven while shifting, and floats otherwise, as the standard requires, so bob can "
                "share a chain with other devices."):
            self.play(FadeIn(rules[2:], lag_ratio=0.3), run_time=1.0)
        self.wipe()

    def irtable(self, F):
        self.heading("The instruction register", "six bits, AMD 7-series codes where they exist (UG470 table 6-3)")
        private = {"INTEST", "DSP", "CHAIN_OUT", "CHAIN_IN"}
        meaning = {"SAMPLE": "read every pin", "USER1": "control: ce, sr, step, autostep", "USER2": "CFG_CTRL: chain CRC + status",
                   "CFG_OUT": "frame readback", "CFG_IN": "frame packets in (chapter 09)", "INTEST": "drive the fabric's inputs",
                   "USERCODE": "milestone number", "IDCODE": "device identity", "JPROGRAM": "clear the configuration",
                   "JSTART": "run the startup sequence", "USER3": "CAPTURE: every element output", "USER4": "BRAM contents",
                   "DSP": "drive and read the DSP slices", "EXTEST": "drive the pins", "CHAIN_OUT": "chain readback",
                   "CHAIN_IN": "chain write (chapter 08)", "BYPASS": "one-bit pass-through"}
        rows = []
        for n, code in F["ir"]:
            rows.append((code, n, meaning.get(n, ""), n in private))
        half = (len(rows) + 1) // 2
        cols = VGroup()
        priv_rows = []
        for part in (rows[:half], rows[half:]):
            col = VGroup()
            for code, n, m, prv in part:
                r = VGroup(mono(code, 16, C_BIT), mono(n.ljust(9), 16, C_ERR if prv else C_GRF), txt(m, 14, INK)).arrange(RIGHT, buff=0.25)
                col.add(r)
                if prv:
                    priv_rows.append(r)
            col.arrange(DOWN, aligned_edge=LEFT, buff=0.12)
            cols.add(col)
        cols.arrange(RIGHT, buff=0.6, aligned_edge=UP).move_to(DOWN * 0.15)
        fit(cols, 13.2, 4.8)
        leg = VGroup(txt("AMD code", 15, C_GRF), txt("private to bob", 15, C_ERR)).arrange(RIGHT, buff=0.5).next_to(cols, DOWN, buff=0.25)
        with self.narrate(
                "The instruction decides which data register sits between TDI and TDO. bob uses AMD's own "
                "seven-series codes wherever the instruction exists on real parts, so standard tools find "
                "IDCODE, CFG in and JPROGRAM exactly where they expect them."):
            self.play(FadeIn(cols, lag_ratio=0.03), FadeIn(leg), run_time=2.4)
        with self.narrate(
                "Four are bob's own, shown in pink: INTEST to drive the fabric, the DSP test register, and "
                "the scan-chain pair, chain in and chain out, which AMD parts do not have."):
            for r in priv_rows:
                self.play(Indicate(r, color=C_ERR), run_time=0.4)
        self.wipe()

    def status(self, F):
        self.heading("Every instruction scan is also a status read", "Capture-IR loads six status bits, which shift out while the new instruction shifts in")
        bits = [("DONE", C_RTL), ("INIT_B", C_CYN), ("COMMITTED", C_BIT), ("CRC_ERR", C_ERR), ("0", DIM), ("1", DIM)]
        row = VGroup()
        for i, (n, c) in enumerate(bits):
            sq = Rectangle(width=1.8, height=0.75, color=c, stroke_width=2).set_fill(c, opacity=0.15)
            row.add(VGroup(sq, mono(n, 16, INK).move_to(sq), mono(str(5 - i), 13, DIM).next_to(sq, UP, buff=0.06)))
        row.arrange(RIGHT, buff=0.06).move_to(UP * 1.3)
        notes = VGroup(
            txt("bits 5 and 4 where 7-series parts put DONE and INIT_B (openFPGALoader reads them there)", 17, INK),
            txt("bits 3 and 2 are bob's · bits 1:0 = 01 is required by IEEE 1149.1", 17, INK),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.12).next_to(row, DOWN, buff=0.4)
        idc = F["idcode"]
        idg = VGroup(
            mono(f"IDCODE {idc}", 26, C_BIT),
            txt(f"0x0B0 · milestone {int(idc[5:7])} · 0x093: AMD's JEDEC manufacturer code with bit 0 = 1", 17, DIM),
        ).arrange(DOWN, buff=0.1).next_to(notes, DOWN, buff=0.5)
        with self.narrate(
                "Remember the pattern captured into the instruction register. bob puts its status there: "
                "DONE, INIT bar, whether a configuration has been committed, and whether a checksum failed. "
                "So every single instruction load also tells the host the state of the chip."):
            self.play(FadeIn(row, lag_ratio=0.1), run_time=1.2)
            self.play(FadeIn(notes, lag_ratio=0.3), run_time=1.0)
        with self.narrate(
                f"And the IDCODE register identifies the build. It ends in AMD's manufacturer code, and its "
                f"middle digits name the milestone: this is the M26 hardware. A test run against the wrong "
                f"bitstream stops at its first check."):
            self.play(FadeIn(idg, shift=UP * 0.15), run_time=0.8)
        self.wipe()
