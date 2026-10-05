"""Chapter 11 - Verification and results: the layers, models as oracles, mutation testing, the
stand-in board, the board runs, the Vivado numbers, bob against OpenFPGA / Aegis / ZUMA /
prjxray, what is new, what is weaker, and the references."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bobvid.scene import *


class Ch11Results(BobScene):
    CH = "11"
    TITLE = "Verification and results"
    SUBTITLE = "how each claim in this film was proven, what bob achieved, and how it compares"

    def construct(self):
        F = self.F
        self.title_card(
            "An FPGA that only works in simulation proves very little. This last chapter is about evidence: "
            "how bob is checked, what the board showed, and how the project compares with its references.")
        self.layers()
        self.sims(F)
        self.mutants(F)
        self.board(F)
        self.vivado(F)
        self.compare()
        self.new_and_weak()
        self.refs_card(
            "These are the sources this film, and bob, follow.",
            [("UG470", "7 Series FPGAs Configuration: JTAG, packets, registers, FAR, CMD, startup, readback"),
             ("UG473 · UG474 · UG479", "Memory Resources (RAMB18E1), CLB (LUT6_2, CARRY4, FDRE/FDSE), DSP48E1"),
             ("UG949 · UG903 · UG909", "Methodology (clock enables), Constraints, Dynamic Function eXchange"),
             ("IEEE 1149.1", "the TAP, BC_1 boundary cells, Capture-IR 01, TDO high impedance"),
             ("OpenFPGA", "tileable rr graphs, k6_frac_N10 reference architecture, scan_chain / frame_based"),
             ("VPR", "Betz & Rose, FPL 1997 · McMurchie & Ebeling, PathFinder, FPGA 1995"),
             ("ZUMA", "Brant & Lemieux, FCCM 2012: an overlay's LUTs in host LUTRAM"),
             ("Double Duty", "Pun, Dai, Zgheib, Iyer, Boutros, Betz, Abdelfattah, FPL 2025"),
             ("Time travel", "Attia & Betz, TRETS 2022: state save and restore"),
             ("prjxray / F4PGA", "the 7-series CRC over {register, data}, and FASM")])
        self.closing(F)

    # ------------------------------------------------------------------
    def layers(self):
        self.heading("Seven layers of evidence", "each layer checks the one above it, and none trusts the RTL to check itself")
        L = [("references", "UG470/473/474/479, OpenFPGA, VPR", C_VPR),
             ("Python models", "model.py, packets.Controller, chainbits: the expected values", C_PY),
             ("RTL testbenches", "expectations come from the models, never from the RTL", C_RTL),
             ("mutation tests", "each guard broken on purpose must fail a testbench", C_ERR),
             ("golden co-simulation", "source ∥ golden netlist ∥ the whole FPGA loaded from its .bit", C_BIT),
             ("stand-in board", "every hardware check, against a passing and a failing board", C_GRF),
             ("PYNQ-Z2", "make hwtest M=Mx: the full regression plus the new checks, logged", C_CYN)]
        rows = VGroup()
        for i, (a, b, c) in enumerate(L):
            w = 5.0 + 1.0 * i
            box = RoundedRectangle(width=min(w, 11.6), height=0.56, corner_radius=0.08, color=c, stroke_width=1.8).set_fill(c, opacity=0.1)
            t = VGroup(txt(a, 17, c, weight=BOLD), txt(b, 15, INK)).arrange(RIGHT, buff=0.3)
            fit(t, box.width - 0.3)
            rows.add(VGroup(box, t.move_to(box)))
        rows.arrange(DOWN, buff=0.08).move_to(DOWN * 0.2)
        with self.narrate(
                "Every claim in this film rests on a chain of evidence. At the top are the references. From them "
                "come Python models of the hardware, and every expected value in every testbench comes from those "
                "models, never from the Verilog, because a testbench that asks the design what it should do only "
                "proves the design agrees with itself."):
            self.play(LaggedStart(*[FadeIn(r, shift=DOWN * 0.1) for r in rows[:3]], lag_ratio=0.4), run_time=1.6)
        with self.narrate(
                "Below them, mutation tests break each guard on purpose to show a test catches it. Golden "
                "co-simulation runs the source, the golden netlist and the whole loaded FPGA side by side. A "
                "stand-in board in Python tests every hardware check, both passing and failing. And then the "
                "real board, every milestone."):
            self.play(LaggedStart(*[FadeIn(r, shift=DOWN * 0.1) for r in rows[3:]], lag_ratio=0.4), run_time=2.0)
        self.wipe()

    def sims(self, F):
        v = F["verification"]
        tot = sum(b["checks"] for b in v["benches"])
        self.heading("Simulation", f"testbench checks per bench · {v['sim_source']}")
        mx = max(b["checks"] for b in v["benches"])
        rows = VGroup()
        for b in v["benches"]:
            bar = Rectangle(width=max(6.0 * b["checks"] / mx, 0.03), height=0.3, color=C_RTL, stroke_width=1).set_fill(C_RTL, opacity=0.45)
            rows.add(VGroup(mono(b["bench"], 15, INK), bar, mono(f"{b['checks']:,}", 14, INK)))
        rows.arrange(DOWN, buff=0.1)
        for r in rows:
            r[0].move_to([-2.4, r.get_y(), 0], aligned_edge=RIGHT)
            r[1].move_to([-2.2, r.get_y(), 0], aligned_edge=LEFT)
            r[2].next_to(r[1], RIGHT, buff=0.12)
        rows.move_to(UP * 0.3).set_x(0.4)
        total = txt(f"about {tot:,} checks, plus ~500 pytest tests and verilator lint", 18, C_BIT).next_to(rows, DOWN, buff=0.35)
        with self.narrate(
                f"In simulation, the last full check ran about {tot:,} testbench checks. The largest are the "
                f"co-simulation of every example through both place-and-route flows, the block RAM's every mode, "
                f"and the logic block's every flag and crossbar value, at two LUT sizes."):
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.15) for r in rows], lag_ratio=0.1), run_time=2.0)
            self.play(FadeIn(total), run_time=0.6)
        self.wipe()

    def mutants(self, F):
        ms = F["verification"]["mutants"]
        tot = sum(m["mutants"] for m in ms)
        self.heading("Mutation testing", f"{tot} deliberate bugs in three suites; every one must make a testbench fail")
        cards = VGroup()
        ex = {"mutate_cfg.sh": ["the CRC polynomial", "the length guard", "the write key"],
              "mutate_fabric.sh": ["no GWE freeze", "crossbar select off by one", "carry cut between CLBs"],
              "mutate_frames.sh": ["IDCODE unchecked", "LFRM ignores the CRC", "shadow not cleared"]}
        for m in ms:
            c = VGroup(mono(m["suite"], 18, C_ERR), bold(str(m["mutants"]), 34, INK),
                       *[txt(e, 15, DIM) for e in ex.get(m["suite"], [])]).arrange(DOWN, buff=0.1)
            box = RoundedRectangle(width=3.9, height=3.0, corner_radius=0.12, color=C_ERR, stroke_width=1.8).set_fill(C_ERR, opacity=0.05)
            cards.add(VGroup(box, c.move_to(box)))
        cards.arrange(RIGHT, buff=0.35).move_to(UP * 0.3)
        lesson = txt("the length check exists as a test because its first version could be deleted with every test passing", 17, C_BIT).next_to(cards, DOWN, buff=0.4)
        fit(lesson, 13)
        with self.narrate(
                f"Passing tests are only meaningful if the tests can fail. So {tot} mutants each break one guard: "
                f"the CRC polynomial, the write key, the freeze, a crossbar select off by one, the IDCODE check. "
                f"Every mutant must be killed. Several were not at first, and those gaps became new test scenarios."):
            self.play(LaggedStart(*[FadeIn(c, shift=UP * 0.15) for c in cards], lag_ratio=0.3), run_time=1.6)
            self.play(FadeIn(lesson), run_time=0.6)
        self.wipe()

    def board(self, F):
        ms = [m for m in F["milestones"] if m["pass"]]
        self.heading("On the board", f"checks per milestone run · the last: {F['board']['pass']}/{F['board']['total']} on {F['board']['date']}, TCK 1 MHz")
        vals = [(m["m"], int(m["pass"].split("/")[0]), int(m["pass"].split("/")[1])) for m in ms]
        mx = max(t for _, _, t in vals)
        bars = VGroup()
        bw = 12.0 / len(vals)
        for i, (name, p, t) in enumerate(vals):
            h = 4.0 * t / mx
            ok = p == t
            col = C_RTL if ok else C_BIT
            r = Rectangle(width=bw * 0.72, height=h, color=col, stroke_width=1).set_fill(col, opacity=0.5)
            r.move_to([-6.0 + bw * (i + 0.5), -2.3, 0], aligned_edge=DOWN)
            lab = mono(name, 11, DIM).rotate(PI / 2).next_to(r, DOWN, buff=0.06)
            num = mono(f"{t}", 11, INK).next_to(r, UP, buff=0.04)
            bars.add(VGroup(r, lab, num))
        bars.shift(UP * 0.35)
        note = VGroup(
            txt("each run repeats every earlier milestone's checks, then adds its own", 16, INK),
            txt("amber: a run with failures (" + ", ".join(f"{n} {p}/{t}" for n, p, t in vals if p < t) + "), each fixed and re-run", 16, C_BIT),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.08).move_to(UP * 2.15 + LEFT * 1.6)
        fit(note, 9.5)
        with self.narrate(
                "Every milestone ended on the board, and every run re-ran all the earlier checks, so the number "
                f"of checks grows from eleven at M0 to {F['board']['total']} at M26. The few amber runs had "
                "failures; each was diagnosed, fixed, and passed in a later run."):
            self.play(LaggedStart(*[GrowFromEdge(b[0], DOWN) for b in bars], lag_ratio=0.05),
                      FadeIn(VGroup(*[b[1] for b in bars])), run_time=2.0)
            self.play(FadeIn(VGroup(*[b[2] for b in bars])), FadeIn(note), run_time=0.8)
        self.wipe()

    def vivado(self, F):
        v = F["vivado"]
        self.heading("The host chip, nearly full", f"Vivado, M26 build: WNS +{v['wns_ns']} ns, WHS +{v['whs_ns']} ns · docs/reports/M26")
        items = [("slices", v["slices"], C_BIT), ("LUTs", v["luts"], C_RTL), ("LUT as memory (CFGLUT5)", v["lutram"], C_PY),
                 ("flip-flops", v["ffs"], C_CYN), ("block RAM tiles", v["bram_tiles"], C_GRF), ("DSP48E1", v["dsps"], C_VPR)]
        rows = VGroup()
        for name, d, c in items:
            track = Rectangle(width=6.0, height=0.36, color=FAINT, stroke_width=1)
            fill = Rectangle(width=max(6.0 * d["pct"] / 100, 0.03), height=0.36, color=c, stroke_width=0).set_fill(c, opacity=0.6)
            fill.align_to(track, LEFT)
            rows.add(VGroup(txt(name, 17, INK), VGroup(track, fill), mono(f"{d['pct']:.1f}%  {int(d['used']):,} / {int(d['avail']):,}", 15, INK)))
        rows.arrange(DOWN, buff=0.2)
        for r in rows:
            r[0].move_to([-2.2, r.get_y(), 0], aligned_edge=RIGHT)
            r[1].move_to([-2.0, r.get_y(), 0], aligned_edge=LEFT)
            r[2].next_to(r[1], RIGHT, buff=0.2)
        rows.move_to(UP * 0.5).set_x(0.3)
        luts = [(m["m"], m["luts"]) for m in F["milestones"] if m["luts"]]
        trend = mono("host LUTs:  " + "  ".join(f"{m} {l / 1000:.1f}k" for m, l in luts[-6:]), 15, DIM).next_to(rows, DOWN, buff=0.45)
        fit(trend, 13)
        wall = txt("10 × 10 is this CLB's ceiling on the XC7Z020: the limit is slices that can hold CFGLUT5s (SLICEM)", 17, C_BIT).next_to(trend, DOWN, buff=0.2)
        fit(wall, 13)
        with self.narrate(
                f"Inside the host, the M26 build uses {v['slices']['pct']:.0f} percent of the XC7Z020's slices and "
                f"{v['luts']['pct']:.0f} percent of its LUTs, nearly three quarters of the LUTs that can act as "
                f"memory, and meets timing with a worst slack of plus {v['wns_ns']} nanoseconds."):
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.15) for r in rows], lag_ratio=0.15), run_time=1.8)
        with self.narrate(
                "A grid sweep found the real wall: the slices that can hold CFGLUT5s. Ten by ten is the largest "
                "grid of this logic block that fits this chip."):
            self.play(FadeIn(trend), FadeIn(wall), run_time=0.8)
        self.wipe()

    def compare(self):
        self.heading("bob and its neighbours", "docs/project/GUIDE.md section 5: what bob borrows, and where it stands")
        rows = [["", "what it is", "scale", "bob took"],
                ["OpenFPGA", "architecture -> fabric, bitstream, VTR flow", "many architectures", "the rr-graph method, k6_frac_N10"],
                ["Aegis", "fabric generator, own PnR, RTL to GDS", "two LUT4 devices", "shift + shadow tile configuration"],
                ["ZUMA", "an overlay on a commercial FPGA", "a research overlay", "LUTs in host LUTRAM"],
                ["prjxray / F4PGA", "documents real Xilinx bitstreams", "device-accurate", "the 7-series CRC, FASM"],
                ["bob", "fabric, two config paths, tool chain", "100 CLBs, one board", "proven on the board, every step"]]
        t = table(rows, [2.2, 4.6, 2.7, 3.7], size=17, row_h=0.66)
        t.move_to(DOWN * 0.1)
        t[-1].set_color(C_BIT)
        with self.narrate(
                "Where does bob stand? OpenFPGA is a research framework that generates whole FPGAs for silicon, and "
                "bob borrows its central method. Aegis generates fabrics and takes them to tape-out. ZUMA is the "
                "classic overlay, and bob borrows its trick of keeping LUTs in host memory. prjxray documents the "
                "real Xilinx format bob imitates."):
            self.play(FadeIn(t[0]), FadeIn(t[1]), run_time=0.6)
            for r in t[2:-1]:
                self.play(FadeIn(r, shift=UP * 0.1), run_time=0.5)
        with self.narrate(
                "bob is far smaller than any of them. What it has is the whole loop, at a size one person can "
                "hold in their head, with hardware evidence at every step."):
            self.play(FadeIn(t[-1], shift=UP * 0.1), run_time=0.6)
        self.wipe()

    def new_and_weak(self):
        self.heading("What is new, and what is weaker", "said plainly, as the guide says it")
        new = VGroup(bold("strengths", 22, C_RTL), *bullets([
            "one description generates everything",
            "two configuration paths on one memory",
            "partial reconfiguration that keeps state",
            "time travel with GRESTORE",
            "a timing contract, not a hope",
            "Double Duty packing: 13.2% fewer elements",
            "every guard mutation-tested",
            "every milestone proven on the board",
        ], size=18, buff=0.14, dot=C_RTL, width=6.4)).arrange(DOWN, aligned_edge=LEFT, buff=0.18)
        weak = VGroup(bold("weaker, plainly", 22, C_ERR), *bullets([
            "one fabric shape; 400 LUTs on this chip",
            "LUT, carry and flip-flop delays estimated",
            "bob's own PnR is not timing-driven",
            "one clock domain, no async resets or latches",
            "a simplified 7-series-shaped bitstream",
            "an overlay: each hop is several host LUTs",
        ], size=18, buff=0.14, dot=C_ERR, width=6.4)).arrange(DOWN, aligned_edge=LEFT, buff=0.18)
        both = VGroup(new, weak).arrange(RIGHT, buff=0.9, aligned_edge=UP).move_to(DOWN * 0.15)
        fit(both, 13.2, 5.2)
        with self.narrate(
                "Its strengths: one description generates everything; two configuration protocols share one memory; "
                "partial reconfiguration keeps state; the clock is backed by a contract rather than a hope; and "
                "every guard is tested by breaking it."):
            self.play(FadeIn(new, lag_ratio=0.1), run_time=1.6)
        with self.narrate(
                "Its weaknesses, plainly: one fabric shape at a modest size, some delays still estimated, a single "
                "clock domain, and a bitstream that is shaped like AMD's but simplified. Every one of these is "
                "written down in the project's documents."):
            self.play(FadeIn(weak, lag_ratio=0.1), run_time=1.6)
        self.wipe()

    def closing(self, F):
        self.wipe()
        t = Text("bob", font=SANS, font_size=80, color=INK, weight=BOLD)
        s = txt("an FPGA inside an FPGA", 28, DIM)
        nums = txt(f"{F['count']['clb']} CLBs · {F['count']['luts']} LUT6 · {F['count']['bram']} BRAM · {F['count']['dsp']} DSP · "
                   f"{F['chain_width']:,} bits · {F['frames']['count']} frames · {F['board']['pass']}/{F['board']['total']} on the board", 20, C_BIT)
        fit(nums, 12.5)
        rd = txt("read on: docs/project/GUIDE.md · REPORT.md · docs/bitstream-format.md · docs/learn/", 17, DIM)
        g = VGroup(t, s, nums, rd).arrange(DOWN, buff=0.35).shift(UP * 0.3)
        with self.narrate(
                "That is bob, from a single lookup table to a configured, verified fabric: its logic blocks, "
                "routing, memories and multipliers, its JTAG port, its two ways of loading, and the tools that "
                "turn Verilog into its bits. The guide, the report and the bitstream specification in the "
                "repository go deeper into every part. Thank you for watching."):
            self.play(Write(t), run_time=1.0)
            self.play(FadeIn(s), run_time=0.6)
            self.play(FadeIn(nums), run_time=0.6)
            self.play(FadeIn(rd), run_time=0.6)
        self.wait(1.5)
        self.play(FadeOut(g), run_time=1.0)
