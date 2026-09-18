# =============================================================================
#  EPISODE 1 - the CLB: which bit goes where, and why
# =============================================================================

def s1_where(sc):
    sc.heading("Where the CLB sits",
               "bob today: a 14 x 12 VPR grid - an I/O ring around a 12 x 10 core of 100 CLBs")

    grid = VGroup()
    for x in range(14):
        for y in range(12):
            edge = x in (0, 13) or y in (0, 11)
            corner = (x in (0, 13)) and (y in (0, 11))
            if corner:
                continue
            if edge:
                col, op = C_GRF, 0.18
            elif x == 3:
                col, op = C_VPR, 0.22
            elif x == 8:
                col, op = C_BIT, 0.22
            else:
                col, op = C_RTL, 0.16
            s = Square(0.38, color=col, stroke_width=1.6).set_fill(col, opacity=op)
            s.move_to(np.array([-3.4 + x * 0.44, -2.5 + y * 0.44, 0]))
            grid.add(s)
    grid.shift(LEFT * 1.6 + DOWN * 0.25)
    sc.play(LaggedStart(*[FadeIn(s, scale=0.6) for s in grid], lag_ratio=0.004),
            run_time=2.0)

    key = VGroup(
        VGroup(Square(0.26, color=C_RTL).set_fill(C_RTL, 0.16),
               Text("100 CLBs", font_size=20, color=C_RTL)).arrange(RIGHT, buff=0.2),
        VGroup(Square(0.26, color=C_VPR).set_fill(C_VPR, 0.22),
               Text("2 BRAM  (column x = 3)", font_size=20, color=C_VPR)).arrange(RIGHT, buff=0.2),
        VGroup(Square(0.26, color=C_BIT).set_fill(C_BIT, 0.22),
               Text("2 DSP   (column x = 8)", font_size=20, color=C_BIT)).arrange(RIGHT, buff=0.2),
        VGroup(Square(0.26, color=C_GRF).set_fill(C_GRF, 0.18),
               Text("44 I/O pads", font_size=20, color=C_GRF)).arrange(RIGHT, buff=0.2),
    ).arrange(DOWN, aligned_edge=LEFT, buff=0.3)
    key.to_edge(RIGHT, buff=1.0).shift(DOWN * 0.2)
    sc.play(LaggedStart(*[FadeIn(k, shift=RIGHT * 0.2) for k in key], lag_ratio=0.2),
            run_time=1.4)
    sc.wait(1.0)

    one = grid[60]
    ring = Circle(radius=0.42, color=INK, stroke_width=3).move_to(one)
    sc.play(Create(ring), run_time=0.5)
    sc.play(FadeOut(key), run_time=0.4)

    ble = chip("one CLB\n= one BLE", C_RTL, 3.0, 1.5, 24)
    ble.to_edge(RIGHT, buff=1.4)
    sc.play(GrowArrow(arrow(ring.get_right(), ble.get_left(), INK, 0.2)),
            FadeIn(ble), run_time=0.8)

    parts = code_block([
        "one LUT6      (fracturable, O6 and O5)",
        "one carry bit (MUXCY + XORCY)",
        "one flip-flop (FDRE / FDSE)",
        "",
        "71 configuration bits.",
    ], 21, INK)
    parts[4].set_color(C_BIT)
    parts.next_to(ble, DOWN, buff=0.5).set_x(ble.get_x())
    sc.play(LaggedStart(*[FadeIn(p, shift=UP * 0.15) for p in parts], lag_ratio=0.25),
            run_time=1.8)

    note = Text("AMD calls this a slice's BLE. bob has exactly one per CLB - "
                "OpenFPGA's reference has ten.", font_size=19, color=DIM)
    note.scale_to_fit_width(12.6).to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(note), run_time=0.7)
    sc.wait(2.2)


def s2_datapath(sc):
    sc.heading("The datapath", "hw/src/clb/clb.sv - four inputs from the routing, three ways out")

    lut = chip("LUT6", C_RTL, 1.9, 2.2, 26)
    lut.move_to(np.array([-3.4, 0.4, 0]))
    sc.play(FadeIn(lut), run_time=0.6)

    ins = VGroup()
    for k in range(6):
        y = 1.35 - k * 0.38
        ln = Line(np.array([-5.6, y, 0]), np.array([-4.35, y, 0]), color=DIM, stroke_width=2)
        t = mono(f"i[{k}]", 16, DIM).next_to(ln, LEFT, buff=0.1)
        ins.add(VGroup(ln, t))
    sc.play(LaggedStart(*[Create(i) for i in ins], lag_ratio=0.08), run_time=0.9)
    src = Text("from the connection box", font_size=17, color=C_GRF)
    src.next_to(ins, DOWN, buff=0.3)
    sc.play(FadeIn(src), run_time=0.5)

    o6 = mono("O6", 18, C_RTL)
    o5 = mono("O5", 18, C_RTL)
    o6.next_to(lut, RIGHT, buff=0.2).shift(UP * 0.5)
    o5.next_to(lut, RIGHT, buff=0.2).shift(DOWN * 0.5)
    sc.play(FadeIn(o6), FadeIn(o5), run_time=0.5)

    cy = chip("carry\nMUXCY\nXORCY", C_BIT, 1.7, 2.2, 19)
    cy.move_to(np.array([-0.6, 0.4, 0]))
    sc.play(FadeIn(cy),
            GrowArrow(arrow(o6.get_right(), cy.get_left() + UP * 0.5, DIM, 0.12)),
            GrowArrow(arrow(o5.get_right(), cy.get_left() + DOWN * 0.5, DIM, 0.12)),
            run_time=0.8)
    cin = arrow(np.array([-0.6, -1.5, 0]), np.array([-0.6, -0.75, 0]), C_BIT, 0.05)
    cint = mono("cin  (from the CLB below)", 16, C_BIT).next_to(cin, DOWN, buff=0.12)
    cout = arrow(np.array([-0.6, 1.55, 0]), np.array([-0.6, 2.3, 0]), C_BIT, 0.05)
    coutt = mono("cout  (to the CLB above)", 16, C_BIT).next_to(cout, UP, buff=0.1)
    sc.play(GrowArrow(cin), FadeIn(cint), GrowArrow(cout), FadeIn(coutt), run_time=0.7)

    ff = chip("flip-flop\nFDRE / FDSE", C_GRF, 2.3, 1.5, 19)
    ff.move_to(np.array([2.5, 0.4, 0]))
    sc.play(FadeIn(ff), GrowArrow(arrow(cy.get_right(), ff.get_left(), DIM, 0.12)),
            run_time=0.7)
    lab = mono("comb", 16, DIM)
    lab.move_to(mid(cy.get_right(), ff.get_left()) + UP * 0.22)
    sc.play(FadeIn(lab), run_time=0.3)

    omux = mux_symbol(C_RTL, 1.3, 0.6).move_to(np.array([4.6, 0.4, 0]))
    sc.play(Create(omux),
            GrowArrow(arrow(ff.get_right(), omux.get_left() + DOWN * 0.25, DIM, 0.12)),
            run_time=0.6)
    bypass = VMobject(color=DIM, stroke_width=2)
    bypass.set_points_as_corners([cy.get_right() + RIGHT * 0.1,
                                  np.array([1.6, -1.35, 0]),
                                  np.array([4.25, -1.35, 0]),
                                  omux.get_left() + UP * 0.28])
    sc.play(Create(bypass), run_time=0.7)
    oarr = arrow(omux.get_right(), np.array([6.1, 0.4, 0]), C_RTL, 0.08)
    ot = mono("o", 20, C_RTL).next_to(oarr, RIGHT, buff=0.1)
    sc.play(GrowArrow(oarr), FadeIn(ot), run_time=0.5)

    sel = mono("ff_en", 15, C_BIT).next_to(omux, DOWN, buff=0.22)
    sc.play(FadeIn(sel), run_time=0.4)

    ctrl = code_block([
        "ce  routed clock enable      sr  routed synchronous set/reset",
        "gce global user-clock enable gsr / gwe  startup",
    ], 18, DIM)
    ctrl.to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(ctrl), run_time=0.7)
    sc.wait(2.4)


def s3_lut(sc):
    sc.heading("The LUT is a tree of 2-to-1 multiplexers",
               "hw/src/clb/lutk.sv - 64 configuration bits at the leaves, one answer at the root")

    lvl0 = VGroup(*[Square(0.3, color=C_BIT, stroke_width=1.5).set_fill(C_BIT, 0.5)
                    for _ in range(16)])
    lvl0.arrange(RIGHT, buff=0.06).shift(UP * 2.0)
    lab0 = mono("INIT  (the truth table)", 19, C_BIT).next_to(lvl0, UP, buff=0.2)
    sc.play(LaggedStart(*[FadeIn(s) for s in lvl0], lag_ratio=0.04), FadeIn(lab0),
            run_time=1.2)
    note = mono("16 shown - there are really 2**6 = 64", 16, DIM)
    note.next_to(lvl0, DOWN, buff=0.16)
    sc.play(FadeIn(note), run_time=0.4)

    levels = [lvl0]
    for lv in range(4):
        n = 16 >> (lv + 1)
        row = VGroup(*[mux_symbol(C_RTL, 0.34, 0.26) for _ in range(n)])
        row.arrange(RIGHT, buff=0.06 + lv * 0.42)
        row.move_to(np.array([0, 1.15 - lv * 0.78, 0]))
        edges = VGroup()
        for j, m in enumerate(row):
            for c in (2 * j, 2 * j + 1):
                edges.add(Line(levels[-1][c].get_bottom(), m.get_top(),
                               color=DIM, stroke_width=1.2))
        sel = mono(f"i[{lv}]", 16, C_GRF).next_to(row, LEFT, buff=0.35)
        sc.play(Create(edges), LaggedStart(*[Create(m) for m in row], lag_ratio=0.06),
                FadeIn(sel), run_time=0.8)
        levels.append(row)

    root = levels[-1][0]
    o6 = mono("O6  = INIT[ i[5:0] ]", 22, C_RTL)
    o6.next_to(root, DOWN, buff=0.5)
    sc.play(GrowArrow(arrow(root.get_bottom(), o6.get_top(), C_RTL, 0.12)),
            FadeIn(o6), run_time=0.7)
    sc.wait(1.0)

    frac = SurroundingRectangle(levels[3][0], color=C_VPR, buff=0.12)
    o5 = mono("O5  = the K-1 sub-tree, INIT[31:0] over i[4:0]", 20, C_VPR)
    o5.next_to(o6, DOWN, buff=0.3)
    sc.play(Create(frac), FadeIn(o5), run_time=0.8)
    why = Text("that free second output is UG474's LUT6_2 fracture - bob keeps it, "
               "and the router uses it for a second load", font_size=18, color=DIM)
    why.scale_to_fit_width(12.6).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(why), run_time=0.7)
    sc.wait(2.2)


def s4_carry(sc):
    sc.heading("The carry chain", "UG474's MUXCY and XORCY - and why it runs south to north")

    eqs = code_block([
        "prop   = O6                      the LUT computes 'propagate'",
        "di     = cy_di_sel ? O5 : i[0]   'generate'",
        "",
        "cout   = prop ? cin : di         MUXCY",
        "sum    = prop ^ cin              XORCY  -> the datapath",
    ], 22, INK)
    eqs[0].set_color(C_RTL); eqs[1].set_color(C_RTL)
    eqs[3].set_color(C_BIT); eqs[4].set_color(C_BIT)
    eqs.to_edge(LEFT, buff=0.8).shift(UP * 1.2)
    for l in eqs:
        sc.play(FadeIn(l, shift=RIGHT * 0.15), run_time=0.45)
    sc.wait(0.8)

    adder = Text("set prop = A xor B and di = A, and one CLB is one full-adder bit",
                 font_size=21, color=C_BIT)
    adder.next_to(eqs, DOWN, buff=0.55).align_to(eqs, LEFT)
    sc.play(FadeIn(adder), run_time=0.7)

    col = VGroup()
    for r in range(5):
        c = chip(f"CLB  y = {r + 1}", C_RTL, 2.4, 0.66, 18)
        col.add(c)
    col.arrange(DOWN, buff=0.42).to_edge(RIGHT, buff=1.1)
    sc.play(LaggedStart(*[FadeIn(c) for c in col], lag_ratio=0.12), run_time=1.0)

    links = VGroup(*[arrow(col[i].get_top(), col[i - 1].get_bottom(), C_BIT, 0.06)
                     for i in range(len(col) - 1, 0, -1)])
    sc.play(LaggedStart(*[GrowArrow(a) for a in links], lag_ratio=0.2), run_time=1.2)
    dirn = mono("carry runs up the column", 18, C_BIT)
    dirn.next_to(col, DOWN, buff=0.35)
    sc.play(FadeIn(dirn), run_time=0.5)

    pt = code_block([
        "in the routing graph this is a VPR 'direct':",
        "an IPIN driven by exactly one OPIN.",
        "No choice to make, so NO configuration bits -",
        "it is a plain wire in bob_fabric.v.",
    ], 19, C_GRF)
    pt.next_to(adder, DOWN, buff=0.6).align_to(eqs, LEFT)
    sc.play(LaggedStart(*[FadeIn(l) for l in pt], lag_ratio=0.2), run_time=1.4)

    cut = Text("a chain cannot cross a column, so the tools cut it to the column height "
               "and add a generator CLB", font_size=18, color=DIM)
    cut.scale_to_fit_width(12.8).to_edge(DOWN, buff=0.28)
    sc.play(FadeIn(cut), run_time=0.7)
    sc.wait(2.2)


def s5_ff(sc):
    sc.heading("The flip-flop, and who wins",
               "FDRE / FDSE semantics plus the two startup globals - the order matters")

    code = code_block([
        "always @(posedge clk) begin",
        "    if (gsr)                  q <= ff_rstval;",
        "    else if (gwe && gce) begin",
        "        if (sr_eff)           q <= ff_rstval;",
        "        else if (ce_eff)      q <= comb;",
        "    end",
        "end",
    ], 23, INK)
    code.to_edge(LEFT, buff=0.7).shift(UP * 0.9)
    sc.play(FadeIn(code), run_time=0.9)

    ladder = [
        ("gsr", "startup reset - beats everything, even GWE", C_ERR),
        ("gwe && gce", "frozen unless startup finished AND this is a user-clock tick", C_GRF),
        ("sr_eff", "synchronous set/reset - beats the clock enable (FDRE/FDSE)", C_BIT),
        ("ce_eff", "clock enable - the ordinary case", C_RTL),
    ]
    rows = VGroup()
    for i, (name, why, col) in enumerate(ladder):
        n = mono(name, 21, col)
        w = Text(why, font_size=17, color=DIM)
        r = VGroup(n, w).arrange(RIGHT, buff=0.35, aligned_edge=UP)
        rows.add(r)
    rows.arrange(DOWN, aligned_edge=LEFT, buff=0.26)
    if rows.width > 12.8:
        rows.scale_to_fit_width(12.8)
    rows.next_to(code, DOWN, buff=0.7).set_x(0)
    for i, r in enumerate(rows):
        box = SurroundingRectangle(code[i + 1], color=ladder[i][2], buff=0.06)
        sc.play(Create(box), FadeIn(r, shift=RIGHT * 0.2), run_time=0.6)
        sc.wait(0.5)
        sc.play(FadeOut(box), run_time=0.25)

    two = code_block([
        "ff_ce_en = 0  ->  ce_eff = 1     the FF ignores the routed CE",
        "ff_sr_en = 0  ->  sr_eff = 0     the FF ignores the routed SR",
        "ff_rstval     ->  0 = FDRE, 1 = FDSE, and the power-up value too",
    ], 19, C_BIT)
    two.to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(two), run_time=0.8)
    sc.wait(2.2)


def s6_bits(sc):
    sc.heading("The 71 bits", "tools/bob/device.py names them once; clb_pkg.sv derives the same "
                              "layout independently and pytest compares the two")

    fields = [("INIT", 64, C_BIT), ("ff_en", 1, C_RTL), ("ff_rstval", 1, C_RTL),
              ("ff_ce_en", 1, C_GRF), ("ff_sr_en", 1, C_GRF),
              ("cy_en", 1, C_VPR), ("cy_di_sel", 1, C_VPR), ("ff_d_sel", 1, C_PY)]
    bar = fieldbar(fields, total_w=9.0, h=0.7, size=14)
    bar.shift(UP * 1.35)
    sc.play(Create(bar[0]), run_time=1.0)
    sc.play(LaggedStart(*[FadeIn(l) for l in bar[1]], lag_ratio=0.12), run_time=1.0)
    sc.play(LaggedStart(*[FadeIn(r) for r in bar[2]], lag_ratio=0.12), run_time=0.9)

    rows = [
        ("INIT[63:0]", "the truth table. O6 = INIT[i], O5 = INIT[i & 31]"),
        ("ff_en",      "o = the flip-flop (1) or straight combinational (0)"),
        ("ff_rstval",  "reset / power-up value: 0 = FDRE, 1 = FDSE"),
        ("ff_ce_en",   "honour the routed CE pin?"),
        ("ff_sr_en",   "honour the routed SR pin?"),
        ("cy_en",      "carry mode: datapath becomes XORCY's sum, cout becomes MUXCY"),
        ("cy_di_sel",  "carry generate comes from i[0] (0) or from O5 (1)"),
        ("ff_d_sel",   "datapath is O6 (0) or O5 (1) - ignored when cy_en"),
    ]
    tbl = VGroup()
    for name, why in rows:
        n = mono(name, 19, C_BIT)
        n.scale_to_fit_height(0.2)
        w = Text(why, font_size=17, color=DIM)
        tbl.add(VGroup(n, w).arrange(RIGHT, buff=0.3, aligned_edge=DOWN))
    tbl.arrange(DOWN, aligned_edge=LEFT, buff=0.19)
    if tbl.width > 12.6:
        tbl.scale_to_fit_width(12.6)
    tbl.next_to(bar, DOWN, buff=0.65).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.15) for r in tbl], lag_ratio=0.15),
            run_time=2.2)

    sc.wait(1.2)
    k4 = Text("K is a parameter: at K = 4 the same CLB is 16 + 7 = 23 bits, "
              "and make check runs the whole fabric that way too",
              font_size=18, color=C_PY)
    k4.scale_to_fit_width(12.6).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(k4), run_time=0.8)
    sc.wait(2.0)


def s7_example(sc):
    sc.heading("Worked example: a 2-input AND",
               "from a truth table to the bits that actually sit in the configuration memory")

    tt = code_block([
        "i[1] i[0]   o",
        "  0    0    0",
        "  0    1    0",
        "  1    0    0",
        "  1    1    1",
    ], 24, INK)
    tt[0].set_color(DIM)
    ttp = panel(tt, DIM)
    ttp.to_edge(LEFT, buff=1.0).shift(UP * 0.9)
    sc.play(FadeIn(ttp), run_time=0.8)

    step1 = code_block([
        "address i[5:0] = {0,0,0,0,i1,i0}",
        "INIT bit is 1 only when i1 & i0",
        "-> bits 3, 7, 11, 15, ... every",
        "   address whose low 2 bits are 11",
    ], 19, DIM)
    step1.next_to(ttp, DOWN, buff=0.5).align_to(ttp, LEFT)
    sc.play(FadeIn(step1), run_time=0.9)

    strip = bitcells(32, 0.26, on=[i for i in range(32) if i % 4 == 3])
    strip.to_edge(RIGHT, buff=0.7).shift(UP * 1.5)
    slab = mono("INIT[31:0]   (the other 32 bits repeat)", 17, DIM)
    slab.next_to(strip, UP, buff=0.18)
    sc.play(Create(strip), FadeIn(slab), run_time=1.1)

    val = mono("INIT = 64'h8888_8888_8888_8888", 26, C_BIT)
    val.next_to(strip, DOWN, buff=0.55)
    sc.play(Write(val), run_time=0.9)
    sc.wait(0.8)

    flags = code_block([
        "ff_en     = 0      combinational, no register",
        "ff_rstval = 0",
        "ff_ce_en  = 0      CE ignored",
        "ff_sr_en  = 0      SR ignored",
        "cy_en     = 0      not an adder",
        "cy_di_sel = 0",
        "ff_d_sel  = 0      take O6",
    ], 18, C_RTL)
    flags.next_to(val, DOWN, buff=0.5).set_x(val.get_x())
    sc.play(LaggedStart(*[FadeIn(f) for f in flags], lag_ratio=0.12), run_time=1.3)

    fasm = mono("clb_x2y3.init = 64'h8888888888888888", 22, C_PY)
    fasm.to_edge(DOWN, buff=0.75)
    ftag = Text("this is exactly what bob's FASM says, and bitgen turns it into "
                "71 bits at that tile's place in the chain",
                font_size=17, color=DIM)
    ftag.scale_to_fit_width(12.4).next_to(fasm, DOWN, buff=0.2)
    sc.play(FadeIn(fasm), FadeIn(ftag), run_time=0.9)
    sc.wait(2.4)


def s8_files(sc):
    sc.files_used(
        inputs=[("hw/src/clb/clb_pkg.sv", "field offsets, derived from K"),
                ("hw/src/clb/lutk.sv", "the mux tree, K a parameter"),
                ("hw/src/clb/clb.sv", "LUT -> carry -> flip-flop")],
        generated=[("hw/src/generated/bob_params.vh", "BOB_CLB_* offsets"),
                   ("tools/bob/device.json", "the same fields, for Python"),
                   ("tools/bob/model.py", "the cycle model of one CLB")],
        verified=[("hw/tb/tb_clb.sv", "7040 checks vs model.py"),
                  ("tests/test_lutk.py", "lutk(6) == the proven lut6.sv"),
                  ("tests/test_device.py", "clb_pkg.sv == bob_params.vh in iverilog"),
                  ("sim/mutate_fabric.sh", "no-gsr, no-gwe-freeze, ce-not-routed, ...")])


EP01 = [s1_where, s2_datapath, s3_lut, s4_carry, s5_ff, s6_bits, s7_example, s8_files]


class Ep01CLB(BobScene):
    def construct(self):
        self.titlecard("EPISODE 1", "The CLB",
                       "which bit goes where, and why")
        for i, part in enumerate(EP01):
            part(self)
            if i < len(EP01) - 1:
                clear_all(self)


class E01S1Where(BobScene):
    def construct(self): s1_where(self)


class E01S2Datapath(BobScene):
    def construct(self): s2_datapath(self)


class E01S3Lut(BobScene):
    def construct(self): s3_lut(self)


class E01S4Carry(BobScene):
    def construct(self): s4_carry(self)


class E01S5Ff(BobScene):
    def construct(self): s5_ff(self)


class E01S6Bits(BobScene):
    def construct(self): s6_bits(self)


class E01S7Example(BobScene):
    def construct(self): s7_example(self)


class E01S8Files(BobScene):
    def construct(self): s8_files(self)
