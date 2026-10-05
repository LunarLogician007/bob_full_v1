"""Chapter 00 - An FPGA inside an FPGA: host and guest, the five layers, M0 to M26."""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from bobvid.scene import *


class Ch00Prologue(BobScene):
    CH = "00"
    TITLE = "An FPGA inside an FPGA"
    SUBTITLE = "what bob is, the machines it runs on, and how it was built"

    def construct(self):
        F = self.F
        c = F["count"]
        self.title_card(
            "This film explains bob from A to Z. bob is a complete, programmable FPGA, "
            "written in Verilog, that runs inside a real FPGA. Every number you will see is "
            "read from the repository itself, at milestone M26.")
        self.two_fpgas()
        self.host_vs_guest()
        self.inside(F, c)
        self.layers()
        self.journey(F)
        self.roadmap()

    # ------------------------------------------------------------------
    def two_fpgas(self):
        self.heading("Two FPGAs", "the host is silicon; the guest is our design running on it")
        host = RoundedRectangle(width=7.6, height=4.6, corner_radius=0.2, color=C_PY,
                                stroke_width=3).set_fill(C_PY, opacity=0.05).shift(RIGHT * 1.6 + DOWN * 0.25)
        host_l = txt("host: Xilinx XC7Z020 on a PYNQ-Z2", 19, C_PY).next_to(host, UP, buff=-0.45).align_to(host, LEFT).shift(RIGHT * 0.3)
        guest = RoundedRectangle(width=4.6, height=2.6, corner_radius=0.16, color=C_RTL,
                                 stroke_width=3).set_fill(C_RTL, opacity=0.1).move_to(host).shift(DOWN * 0.35)
        guest_l = txt("guest: bob", 22, C_RTL, weight=BOLD).move_to(guest).shift(UP * 0.85)
        g, _ = grid_view(self.F, cell=0.11, gap=0.02)
        g.move_to(guest).shift(DOWN * 0.25)
        mac = chip("Mac\nyosys · VPR · bitgen", C_BIT, w=2.9, h=1.0, size=17).move_to([-5.2, 1.3, 0])
        pico = chip("Raspberry Pi Pico\nDirtyJTAG", C_GRF, w=2.9, h=1.0, size=17).move_to([-5.2, -0.8, 0])
        pc = chip("Windows PC\nVivado", C_VPR, w=2.9, h=0.9, size=17).move_to([-5.2, -2.45, 0])
        a1 = arrow(mac.get_bottom(), pico.get_top(), C_BIT)
        pc.shift(UP * 0.15)
        usb = txt("USB", 14, DIM).next_to(a1, RIGHT, buff=0.1)
        a2 = arrow(pico.get_right(), guest.get_left(), C_GRF)
        jt = txt("JTAG", 15, C_GRF).next_to(a2.get_start(), UR, buff=0.08)
        a3 = arrow(pc.get_right(), host.get_left() + DOWN * 1.7, C_VPR)
        once = txt("bob_top.bit, once", 14, C_VPR).next_to(a3, UP, buff=0.04).shift(LEFT * 0.2)

        with self.narrate(
                "There are two FPGAs in this project, and keeping them apart is the first "
                "thing to understand. The host is real silicon: a Xilinx XC7Z020 on a PYNQ-Z2 board."):
            self.play(Create(host), FadeIn(host_l), run_time=1.0)
        with self.narrate(
                "The guest is bob. It is our own fabric of logic blocks, memories, multipliers "
                "and routing, written in Verilog and compiled by Vivado into the host."):
            self.play(Create(guest), FadeIn(guest_l), FadeIn(g, lag_ratio=0.01), run_time=1.6)
        with self.narrate(
                "Vivado, on a Windows machine, programs the host once, with a bitstream called "
                "bob_top.bit. After that the host never changes."):
            self.play(FadeIn(pc), GrowArrow(a3), FadeIn(once), run_time=1.0)
        with self.narrate(
                "The guest is programmed as often as you like. A Mac runs bob's own tools, and "
                "sends the guest's configuration over USB to a Raspberry Pi Pico, which speaks "
                "JTAG to the guest's own configuration port."):
            self.play(FadeIn(mac), run_time=0.6)
            self.play(GrowArrow(a1), FadeIn(usb), FadeIn(pico), run_time=0.8)
            self.play(GrowArrow(a2), FadeIn(jt), run_time=0.8)
            self.play(Indicate(guest, color=C_RTL, scale_factor=1.03), run_time=1.0)
        self.wipe()

    def host_vs_guest(self):
        self.heading("Whose bitstream is this?", "the question that settles most confusion")
        rows = [["", "host FPGA", "guest FPGA (bob)"],
                ["what it is", "Xilinx XC7Z020, PYNQ-Z2", "our fabric, in Verilog, inside it"],
                ["its bitstream", "bob_top.bit (Vivado)", "counter.bit (bob's tools)"],
                ["its tools", "Vivado", "yosys, VPR or bob PnR, FASM, bitgen"],
                ["how it loads", "once, by Vivado", "over JTAG from the Pico, in about a second"],
                ["when it changes", "when bob's hardware changes", "every time you build a design"]]
        t = table(rows, [2.6, 4.4, 5.6], size=19, row_h=0.62,
                  colors=[None, INK, INK, INK, INK, INK])
        t.move_to(DOWN * 0.2)
        # colour the column heads
        t[0][1].set_color(C_PY)
        t[0][2].set_color(C_RTL)
        with self.narrate(
                "So whenever something is confusing, ask whose bitstream it is. The host's "
                "bitstream is made by Vivado and changes only when bob's hardware changes. "
                "The guest's bitstream is made by bob's own tool chain from your Verilog, and "
                "it is loaded over JTAG every time you build a design."):
            self.play(FadeIn(t[0]), FadeIn(t[1]), run_time=0.6)
            for row in t[2:]:
                self.play(FadeIn(row, shift=UP * 0.1), run_time=0.45)
        self.wipe()

    def inside(self, F, c):
        self.heading("What the guest contains", f"device {F['name']} · IDCODE {F['idcode']} · read from device.json")
        g, cells = grid_view(F, cell=0.3, gap=0.04)
        g.move_to(LEFT * 3.3 + DOWN * 0.25)
        stats = [
            (f"{c['clb']} CLBs", f"10 × 10, each a cluster of {F['cluster']['n']} logic elements", C_RTL),
            (f"{c['luts']} LUT6", "fracturable, with carry and two flip-flops each", C_RTL),
            (f"{c['bram']} BRAMs", f"{2 ** F['bram']['addr_w']} × {F['bram']['data_w']} bits, true dual port", C_PY),
            (f"{c['dsp']} DSP slices", "25 × 18 multiply, 48-bit accumulate", C_VPR),
            (f"{c['io']} I/O pads", "switches, buttons, LEDs, and pads reached by JTAG", C_CYN),
            (f"{F['chain_width']:,} bits", f"of configuration, in {F['frames']['count']} frames of {F['frames']['bits']}", C_BIT),
        ]
        col = VGroup()
        for big, small, cc in stats:
            col.add(VGroup(bold(big, 26, cc), txt(small, 16, DIM)).arrange(DOWN, aligned_edge=LEFT, buff=0.05))
        col.arrange(DOWN, aligned_edge=LEFT, buff=0.18).move_to(RIGHT * 3.3 + DOWN * 0.25)
        lg = legend([("CLB", C_RTL), ("BRAM", C_PY), ("DSP", C_VPR), ("I/O pad", C_CYN)], 14)
        lg.next_to(g, LEFT, buff=0.3).align_to(g, DOWN)
        with self.narrate(
                f"Here is the guest, drawn from its own device description. A ring of "
                f"{c['io']} I/O pads surrounds a ten by ten array of logic blocks, with one "
                f"column of block RAM and one column of DSP slices cut into it."):
            self.play(FadeIn(g, lag_ratio=0.005), FadeIn(lg), run_time=1.6)
        with self.narrate(
                f"That is {c['clb']} configurable logic blocks holding {c['luts']} six-input "
                f"lookup tables, {c['bram']} block RAMs and {c['dsp']} DSP slices. Everything is "
                f"set by {F['chain_width']:,} configuration bits, organised as "
                f"{F['frames']['count']} frames."):
            for s in col:
                self.play(FadeIn(s, shift=LEFT * 0.2), run_time=0.45)
        self.wipe()

    def layers(self):
        self.heading("The five layers", "each layer is built from the one above it")
        L = [("1  ARCHITECTURE", "software/bob/device.py: one description of everything", C_PY),
             ("2  HARDWARE", "hw/src: Verilog generated from that description, and hand-written tiles", C_RTL),
             ("3  CONFIGURATION", "cfg_store, cfg_ctrl, cfg_frames: the memory and two ways to fill it", C_BIT),
             ("4  TOOLS", "yosys, then VPR or bob's PnR, then FASM, then bitgen: a design becomes bits", C_GRF),
             ("5  HOST", "cfgplane, cli, hwtest: loading, reading back, checking on the board", C_CYN)]
        rows = VGroup()
        for name, desc, cc in L:
            b = chip(name, cc, w=3.6, h=0.68, size=19, weight=BOLD)
            d = txt(desc, 18, INK)
            rows.add(VGroup(b, d).arrange(RIGHT, buff=0.35))
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.22).move_to(DOWN * 0.2)
        fit(rows, 13.0, 5.0)
        with self.narrate(
                "bob is built in five layers. The architecture is one Python file, device.py, "
                "and it is the only place where architecture numbers live. The hardware is "
                "generated from it. The configuration layer is the memory that holds the "
                "guest's bits and the controller that fills it. The tools turn a design into "
                "those bits, and the host software loads them and checks the result on the board."):
            for r in rows:
                self.play(FadeIn(r, shift=RIGHT * 0.2), run_time=0.6)
        rule = txt("Rule: change the architecture in one place; regenerate everything else.", 20, C_BIT)
        rule.next_to(rows, DOWN, buff=0.35)
        with self.narrate(
                "This one rule holds the project together. Growing the grid from 16 to 36 to "
                "100 logic blocks was an edit to one dictionary and two commands."):
            self.play(FadeIn(rule), run_time=0.6)
        self.wipe()

    def journey(self, F):
        self.heading("M0 to M26", "every milestone ended with a hardware test on the board")
        groups = [
            ("M0–M6", "the pieces: TAP, configuration plane, CLB, BRAM, DSP", C_GRF),
            ("M7", "a fabric generated from VPR's routing graph", C_RTL),
            ("M8–M12", "the tool flow: yosys, VPR, FASM, bitgen, bob's own PnR", C_PY),
            ("M13–M15", "AMD-style frames, partial reconfiguration, BRAM contents as frames", C_BIT),
            ("M16–M20", "100 CLBs, bob studio, a per-design user clock", C_CYN),
            ("M21–M23", "the cluster CLB, LUTs in CFGLUT5s, the 10 × 10 ceiling", C_RTL),
            ("M24–M26", "Double Duty, time travel, INIT apart from SRVAL", C_VPR),
        ]
        rows = VGroup()
        for m, d, cc in groups:
            dot = Dot(radius=0.09, color=cc)
            lab = bold(m, 20, cc)
            dsc = txt(d, 20, INK)
            rows.add(VGroup(dot, lab, dsc))
        for r in rows:
            r[1].next_to(r[0], RIGHT, buff=0.25)
            r[2].move_to(r[0].get_center() + RIGHT * 2.45, aligned_edge=LEFT)
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.2).move_to(UP * 0.1).to_edge(LEFT, buff=1.0)
        spine = Line(rows[0][0].get_center(), rows[-1][0].get_center(), color=FAINT, stroke_width=3)
        spine.set_z_index(-1)
        res = [m for m in F["milestones"] if m["m"] == "M26"][0]
        last = txt(f"M26 on the board ({F['board']['date']}): {F['board']['pass']}/{F['board']['total']} checks passed · IDCODE {F['idcode']}",
                   19, C_BIT).next_to(rows, DOWN, buff=0.3).align_to(rows, LEFT)
        with self.narrate(
                "The project was built in twenty seven milestones, from M0 to M26, and no "
                "milestone was closed by simulation alone. Each one ended with a hardware test on "
                "the board, which also re-ran every earlier milestone's checks."):
            self.play(Create(spine), run_time=0.6)
            for r in rows:
                self.play(FadeIn(r, shift=RIGHT * 0.15), run_time=0.4)
        with self.narrate(
                f"The pieces came first, then a fabric generated from the router's own graph, then "
                f"the tool flow, AMD-style configuration frames, the cluster logic block, and the "
                f"largest grid this chip can hold. The last run, M26, passed "
                f"{F['board']['pass']} of {F['board']['total']} checks."):
            self.play(FadeIn(last, shift=UP * 0.2), run_time=0.8)
        self.wipe()

    def roadmap(self):
        self.heading("This film", "twelve chapters, from the idea of an FPGA to the results")
        chs = ["00  An FPGA inside an FPGA", "01  What an FPGA is", "02  Architecture as data",
               "03  The CLB", "04  Routing", "05  BRAM and DSP", "06  I/O and the user clock",
               "07  JTAG and the TAP", "08  Configuration memory and the chain",
               "09  Frame-based configuration", "10  Bitstream generation", "11  Verification and results"]
        a = VGroup(*[txt(s, 21, INK) for s in chs[:6]]).arrange(DOWN, aligned_edge=LEFT, buff=0.24)
        b = VGroup(*[txt(s, 21, INK) for s in chs[6:]]).arrange(DOWN, aligned_edge=LEFT, buff=0.24)
        g = VGroup(a, b).arrange(RIGHT, buff=1.2, aligned_edge=UP).move_to(DOWN * 0.2)
        for m in list(a) + list(b):
            m[:2].set_color(C_BIT)
        with self.narrate(
                "The chapters follow the layers. First what an FPGA is, and how bob's architecture "
                "is described as data. Then the logic block, the routing, the memories and "
                "multipliers, the pads and the clock. Then JTAG, the configuration memory, the scan "
                "chain and the frame protocol. And finally how a design becomes a bitstream, and "
                "how all of it was verified."):
            self.play(LaggedStart(*[FadeIn(m, shift=RIGHT * 0.15) for m in list(a) + list(b)],
                                  lag_ratio=0.15), run_time=3.0)
        self.wipe()
