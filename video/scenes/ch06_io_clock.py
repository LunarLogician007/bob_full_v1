"""Chapter 06 - I/O pads and boundary scan, the user clock (gce), the gap guard, the
synchronisers, the freeze handshake FSM, and the timing contract."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bobvid.scene import *


class Ch06IoClock(BobScene):
    CH = "06"
    TITLE = "I/O and the user clock"
    SUBTITLE = "boundary-scan pads, a clock that is really an enable, and the freeze handshake"

    def construct(self):
        F = self.F
        self.title_card(
            "A fabric needs a way in and out, and a clock. bob's pads double as test points, "
            "and its clock is not a clock at all, which is what makes it safe and checkable.")
        self.pads(F)
        self.scan_uses(F)
        self.gce(F)
        self.modes(F)
        self.sync()
        self.freeze()
        self.contract(F)
        self.files_card(
            "The pads and boundary cells live in the top level; the clock controller is one file; and "
            "a dedicated testbench checks the spacing in both modes, early requests, the freeze and the release.",
            [("hw/src/top/bob_fpga.v", "pads + two BC_1 cells each"),
             ("hw/src/core/bsc_cell.v", "IEEE 1149.1 BC_1"),
             ("hw/src/core/clock_ctrl.v", "gce, gap guard, freeze")],
            [("device.json pads, bsr", f"{F['pads']['count']} pads, {F['bsr_width']}-bit register"),
             ("hw/constr/pynq_z2.xdc", "multicycles the contract backs")],
            [("hw/tb/tb_clock_gap.v", "spacing, freeze, release"),
             ("software/bob/timing.py", "contract(): refuses unsafe loads"),
             ("hwtest clock-margin", "the margin on silicon")])

    # ------------------------------------------------------------------
    def pads(self, F):
        self.heading("A pad and its two boundary cells", "IEEE 1149.1 BC_1 cells: one on the way out, one on the way in")
        world = Rectangle(width=1.6, height=4.2, color=C_CYN, stroke_width=2).set_fill(C_CYN, opacity=0.06).move_to(RIGHT * 5.3 + DOWN * 0.3)
        wl = txt("the board\nLEDs, switches", 16, C_CYN).move_to(world)
        fab = Rectangle(width=2.0, height=4.2, color=C_RTL, stroke_width=2).set_fill(C_RTL, opacity=0.06).move_to(LEFT * 5.1 + DOWN * 0.3)
        fl = txt("the fabric", 17, C_RTL).move_to(fab)
        oc = chip("output cell\nforced 0 while GTS", C_GRF, w=2.8, h=1.0, size=15).move_to(RIGHT * 0.4 + UP * 0.8)
        ic = chip("input cell", C_GRF, w=2.8, h=1.0, size=15).move_to(RIGHT * 0.4 + DOWN * 1.4)
        a1 = arrow(fab.get_right() + UP * 1.1, oc.get_left(), C_RTL, sw=3)
        a2 = arrow(oc.get_right(), world.get_left() + UP * 1.1, C_RTL, sw=3)
        a3 = arrow(world.get_left() + DOWN * 1.1, ic.get_right(), C_CYN, sw=3)
        a4 = arrow(ic.get_left(), fab.get_right() + DOWN * 1.1, C_CYN, sw=3)
        chain = DashedLine(oc.get_bottom(), ic.get_top(), color=C_BIT, stroke_width=2)
        tdi = txt("a scan chain: TDI → cells → TDO", 15, C_BIT).next_to(chain, RIGHT, buff=0.15)
        cnt = txt(f"{F['pads']['count']} pads × 2 = {F['bsr_width']} cells in the boundary register", 18, C_BIT).to_edge(DOWN, buff=1.3)
        with self.narrate(
                "Each of bob's pads is one block in VPR's eyes: an output pin and an input pin. In the "
                "hardware, each direction passes through a boundary-scan cell of the IEEE 1149.1 kind "
                "called BC underscore one."):
            self.play(FadeIn(fab), FadeIn(fl), FadeIn(world), FadeIn(wl), run_time=0.8)
            self.play(GrowArrow(a1), FadeIn(oc), GrowArrow(a2), run_time=0.8)
            self.play(GrowArrow(a3), FadeIn(ic), GrowArrow(a4), run_time=0.8)
        with self.narrate(
                "Normally the cells are transparent. But they are also linked into one long shift "
                f"register on JTAG, {F['bsr_width']} cells for {F['pads']['count']} pads, so the test "
                f"host can read every pin, or drive every pin, in a single scan. While the startup "
                f"signal GTS is high, the output cells force zero."):
            self.play(Create(chain), FadeIn(tdi), run_time=0.8)
            self.play(FadeIn(cnt), run_time=0.6)
        self.wipe()

    def scan_uses(self, F):
        self.heading("Why boundary scan matters here", "it turns a board you can watch into a board you can check")
        items = [
            ("SAMPLE", "read every real pin and every LED in one atomic scan", "the basis of the live checks", C_CYN),
            ("INTEST", "drive the fabric's inputs from JTAG, not from the switches", "no human at the board", C_GRF),
            ("autostep", "one user clock per INTEST scan", "apply inputs, clock once, read back: cycle-exact", C_BIT),
            ("CAPTURE", f"snapshot every element output: {F['capture_width']} bits", "compared with the golden netlist every clock", C_RTL),
        ]
        rows = VGroup()
        for n, a, b, c in items:
            rows.add(VGroup(mono(n, 22, c), VGroup(txt(a, 18, INK), txt(b, 15, DIM)).arrange(DOWN, aligned_edge=LEFT, buff=0.05)).arrange(RIGHT, buff=0.5))
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.35)
        for r in rows:
            r[0].set_x(-4.6 + r[0].width / 2)
            r[1].set_x(-1.9 + r[1].width / 2)
        rows.move_to(DOWN * 0.2)
        with self.narrate(
                "Loading a design and watching LEDs proves very little. Boundary scan lets the tests do "
                "better. SAMPLE reads the real pins at one instant. INTEST lets JTAG drive the fabric's "
                "inputs, so a test needs nobody pressing buttons."):
            self.play(FadeIn(rows[0], shift=RIGHT * 0.2), run_time=0.6)
            self.play(FadeIn(rows[1], shift=RIGHT * 0.2), run_time=0.6)
        with self.narrate(
                "With autostep, each INTEST scan also advances the design by exactly one clock. And "
                "CAPTURE reads back every element's outputs, which for a registered element is its "
                "flip-flop. Together they let the board be compared with a golden model after every "
                "single clock."):
            self.play(FadeIn(rows[2], shift=RIGHT * 0.2), run_time=0.6)
            self.play(FadeIn(rows[3], shift=RIGHT * 0.2), run_time=0.6)
        self.wipe()

    def gce(self, F):
        c = F["clock"]
        self.heading("The user clock is an enable", f"every fabric flip-flop runs on the {c['sysclk_hz'] // 1_000_000} MHz system clock, and moves only when gce is high")
        w = waveform([
            ("sysclk", "0101010101010101010101010101010101"),
            ("gce", "0000001100000000000000110000000000"),
            ("q", "0000000011111111111111111111111111"),
        ], t_w=0.3, row_h=0.9, x0=-4.2, size=17, colors=[DIM, C_CYN, C_RTL])
        w.move_to(UP * 0.7)
        hl1 = SurroundingRectangle(VGroup(*w[1][1][5:8]), color=C_BIT, buff=0.05)
        reasons = VGroup(
            txt("1  timing: one real clock for the whole fabric, as UG949 recommends", 18, INK),
            txt("2  determinism: one user clock per JTAG step makes every cycle checkable", 18, INK),
            txt("3  freezing: hold gce and nothing in the fabric can change (partial reconfiguration)", 18, INK),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.15).next_to(w, DOWN, buff=0.5)
        fit(reasons, 12.5)
        with self.narrate(
                f"The guest's clock is not a separate clock. Every flip-flop in the fabric is clocked by "
                f"the host's {c['sysclk_hz'] // 1_000_000} megahertz system clock, and is allowed to change "
                f"only on a cycle where a one-cycle enable, called gce, is high. One gce pulse is one user "
                f"clock."):
            self.play(Create(w[0]), run_time=0.8)
            self.play(Create(w[1]), run_time=0.8)
            self.play(Create(w[2]), Create(hl1), run_time=0.8)
        with self.narrate(
                "This buys three things. The timing tools see one real clock, which AMD's methodology "
                "guide recommends over derived clocks. The test host can step the design one clock at a "
                "time. And holding gce low freezes the entire fabric, which partial reconfiguration uses."):
            self.play(FadeIn(reasons, lag_ratio=0.3), run_time=1.6)
        self.wipe()

    def modes(self, F):
        c = F["clock"]
        self.heading("Two clock modes, and a guard", "clk_mode, clk_div, clk_period and clk_gap are fields of the ctrl tile")
        m0 = VGroup(mono("clk_mode 0: JTAG-stepped", 21, C_GRF),
                    txt("one gce per TCK rising edge while USER1 ce is set,", 17, INK),
                    txt("or one per step / INTEST autostep", 17, INK)).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        m1 = VGroup(mono("clk_mode 1: free-running", 21, C_GRF),
                    txt(f"one gce every 2^(clk_div + {c['div_min_shift']}) cycles,", 17, INK),
                    txt("or clk_period × 2^clk_div (M20: any rate)", 17, INK)).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        mm = VGroup(m0, m1).arrange(RIGHT, buff=1.0, aligned_edge=UP).move_to(UP * 1.3)
        gap = 2 ** c["gce_min_gap_shift"]
        guard = VGroup(
            bold("the gap guard", 21, C_BIT),
            txt(f"consecutive gce pulses are at least clk_gap cycles apart, in both modes;", 17, INK),
            txt(f"a request that arrives early waits. Default {gap} cycles = {gap * 8} ns; never below {c['gce_gap_floor']}.", 17, INK),
            txt("so every register-to-register path in the fabric has that long to settle, by construction", 17, DIM),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.08).next_to(mm, DOWN, buff=0.55)
        w = waveform([("req", "0110000110000000000"), ("gce", "0010000000000100000")],
                     t_w=0.32, row_h=0.62, x0=-1.6, size=15, colors=[DIM, C_CYN]).next_to(guard, DOWN, buff=0.3)
        with self.narrate(
                "gce comes from a small clock controller with two modes. Stepped by JTAG, it gives one "
                "pulse per test-clock edge or per step command. Free-running, it divides the system "
                "clock, and since milestone twenty any integer period is allowed."):
            self.play(FadeIn(m0, shift=UP * 0.1), run_time=0.6)
            self.play(FadeIn(m1, shift=UP * 0.1), run_time=0.6)
        with self.narrate(
                f"And in both modes it enforces a minimum gap between pulses: by default {gap} system "
                f"cycles, about four microseconds. A request that comes too soon waits. That guarantee "
                f"is what makes the timing constraints true, as we will see in a moment."):
            self.play(FadeIn(guard, lag_ratio=0.2), run_time=1.2)
            self.play(Create(w), run_time=1.0)
        self.wipe()

    def sync(self):
        self.heading("Crossing clock domains", "TCK and sysclk are unrelated; every control crosses through two flip-flops")
        tck = Rectangle(width=3.4, height=3.6, color=C_GRF, stroke_width=2).set_fill(C_GRF, opacity=0.06).move_to(LEFT * 4.3 + DOWN * 0.3)
        tl = txt("TCK domain\nJTAG, configuration", 16, C_GRF).next_to(tck.get_top(), DOWN, buff=0.2)
        sys_ = Rectangle(width=3.4, height=3.6, color=C_CYN, stroke_width=2).set_fill(C_CYN, opacity=0.06).move_to(RIGHT * 4.3 + DOWN * 0.3)
        sl = txt("sysclk domain\nthe fabric, gce", 16, C_CYN).next_to(sys_.get_top(), DOWN, buff=0.2)
        f1 = chip("FF", C_BIT, w=0.8, h=0.8, size=16).move_to(LEFT * 0.7 + DOWN * 0.3)
        f2 = chip("FF", C_BIT, w=0.8, h=0.8, size=16).move_to(RIGHT * 0.7 + DOWN * 0.3)
        ws = VGroup(arrow(tck.get_right() + DOWN * 0.0, f1.get_left(), DIM, sw=2.5, tip=0.14),
                    arrow(f1.get_right(), f2.get_left(), DIM, sw=2.5, tip=0.14),
                    arrow(f2.get_right(), sys_.get_left(), DIM, sw=2.5, tip=0.14))
        al = mono("(* ASYNC_REG = \"TRUE\" *)", 15, C_BIT).next_to(VGroup(f1, f2), UP, buff=0.3)
        what = txt("USER1 ce, step, cin · GSR, GWE · the clock settings · the freeze request; and back: frozen", 16, DIM).to_edge(DOWN, buff=1.35)
        fit(what, 13)
        with self.narrate(
                "The JTAG side runs on the test clock, the fabric on the system clock, and the two are "
                "unrelated. So every control signal that crosses between them goes through two "
                "flip-flops marked as an asynchronous register, the textbook synchroniser, which gives a "
                "metastable first stage a full cycle to settle."):
            self.play(FadeIn(tck), FadeIn(tl), FadeIn(sys_), FadeIn(sl), run_time=0.8)
            self.play(GrowArrow(ws[0]), FadeIn(f1), GrowArrow(ws[1]), FadeIn(f2), GrowArrow(ws[2]), FadeIn(al), run_time=1.2)
            self.play(FadeIn(what), run_time=0.6)
        self.wipe()

    def freeze(self):
        self.heading("The freeze handshake (M14)", "a state machine across both clock domains, after UG470's AGHIGH / GHIGH_B")
        states = ["RUNNING", "REQUESTED", "FROZEN", "ACKNOWLEDGED", "ERROR"]
        pos = {"RUNNING": (-4.6, 1.0), "REQUESTED": (-0.6, 1.0), "FROZEN": (3.6, 1.0),
               "ACKNOWLEDGED": (3.6, -1.5), "ERROR": (-1.8, -1.5)}
        edges = [("RUNNING", "REQUESTED", "CMD AGHIGH", 0),
                 ("REQUESTED", "FROZEN", "2 FF sync", 0),
                 ("FROZEN", "ACKNOWLEDGED", "2 FF back", 0),
                 ("ACKNOWLEDGED", "RUNNING", "LFRM, CRC ok", -0.45),
                 ("ACKNOWLEDGED", "ERROR", "LFRM, bad CRC", 0)]
        g, nodes, arrs = fsm(states, edges, pos, size=16, h=0.62, w=2.6)
        notes = {
            "RUNNING": "gce pulses as usual",
            "REQUESTED": "freeze = 1 (TCK domain)",
            "FROZEN": "gce held low, frozen = 1 (sysclk)",
            "ACKNOWLEDGED": "STAT GHIGH_B = 0: frames may be written",
            "ERROR": "stays frozen; only JPROGRAM recovers",
        }
        nl = VGroup()
        for s, t in notes.items():
            n = txt(t, 14, DIM).next_to(nodes[s], DOWN, buff=0.12)
            nl.add(n)
        nodes["ERROR"][0].set_color(C_ERR)
        with self.narrate(
                "To rewrite part of a running design, bob must stop the fabric safely, across both clock "
                "domains. The host sends the AGHIGH command; the configuration logic raises a freeze "
                "request on the test clock."):
            self.play(FadeIn(nodes["RUNNING"]), FadeIn(nl[0]), run_time=0.6)
            self.play(Create(arrs[("RUNNING", "REQUESTED")]), FadeIn(nodes["REQUESTED"]), FadeIn(nl[1]), run_time=0.8)
        with self.narrate(
                "Two flip-flops carry it into the system clock domain, where the clock controller holds "
                "gce low and raises frozen on the same edge. Two more carry that back, and only then does "
                "the status register report GHIGH bar as zero."):
            self.play(Create(arrs[("REQUESTED", "FROZEN")]), FadeIn(nodes["FROZEN"]), FadeIn(nl[2]), run_time=0.8)
            self.play(Create(arrs[("FROZEN", "ACKNOWLEDGED")]), FadeIn(nodes["ACKNOWLEDGED"]), FadeIn(nl[3]), run_time=0.8)
        with self.narrate(
                "Now no register, block RAM or DSP register in the fabric can change, because every one of "
                "them is enabled by gce. Frames are written, and the LFRM command releases the clock, but "
                "only if a checksum written after the last frame matched. Otherwise the fabric stays frozen "
                "with an error, and a half-written design never runs."):
            self.play(Create(arrs[("ACKNOWLEDGED", "RUNNING")]), run_time=0.8)
            self.play(Create(arrs[("ACKNOWLEDGED", "ERROR")]), FadeIn(nodes["ERROR"]), FadeIn(nl[4]), run_time=0.8)
        self.wipe()

    def contract(self, F):
        ex = F["counter"]
        c = F["clock"]
        self.heading("The timing contract (M21)", "Vivado cannot time an empty fabric, so software refuses any design that does not fit its clock")
        p1 = VGroup(bold("the problem", 20, C_ERR),
                    txt("unconfigured, the fabric is a mesh of loops through every mux;", 17, INK),
                    txt("Vivado cuts them wherever it likes and times nonsense paths", 17, INK),
                    txt("(M21: 6349 logic levels from the IR into the DSP's JTAG register)", 15, DIM)).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        p2 = VGroup(bold("the answer", 20, C_RTL),
                    txt(f"the XDC relaxes fabric paths ({c['xdc_multicycle']:,} sysclk cycles);", 17, INK),
                    txt("timing.py times each configured design from its own bits,", 17, INK),
                    txt("and contract() refuses it unless path × 2 fits its gce gap", 17, INK)).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        ps = VGroup(p1, p2).arrange(RIGHT, buff=0.8, aligned_edge=UP).move_to(UP * 1.1)
        fit(ps, 13)
        ex_t = VGroup(
            mono(f"counter: critical path {ex['bit_cpd_ns']} ns", 20, C_BIT),
            mono(f"× 2.0 guard = {2 * ex['bit_cpd_ns']:.1f} ns  ≤  gap × 8 ns", 20, C_BIT),
            txt("walked only through the mux inputs its configuration selects, register to register", 16, DIM),
        ).arrange(DOWN, buff=0.12).next_to(ps, DOWN, buff=0.55)
        with self.narrate(
                "One more piece makes the clock trustworthy. Vivado times the fabric unconfigured, and "
                "unconfigured it is a mesh of loops through every multiplexer. At milestone twenty-one its "
                "worst path ran through more than six thousand logic levels that no design could ever use."):
            self.play(FadeIn(p1, lag_ratio=0.2), run_time=1.2)
        with self.narrate(
                "So bob stopped asking Vivado. The constraints relax the fabric's paths, and the guarantee "
                "moved into software. timing dot py walks a configured design through exactly the inputs its "
                "bits select, and the contract refuses any build or load whose critical path, doubled, does "
                "not fit the spacing of its gce pulses."):
            self.play(FadeIn(p2, lag_ratio=0.2), run_time=1.2)
        with self.narrate(
                f"For the counter example, the critical path is {ex['bit_cpd_ns']} nanoseconds: through a "
                f"crossbar mux, a LUT, the carry chain up through two blocks over the direct carry wire, and a "
                f"flip-flop's setup time."):
            self.play(FadeIn(ex_t, lag_ratio=0.2), run_time=1.2)
        self.wipe()
