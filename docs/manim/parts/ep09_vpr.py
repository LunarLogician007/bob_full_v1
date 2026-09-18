# =============================================================================
#  EPISODE 9 - VPR: the tool that designs the routing, then routes on it
#  (the standalone film docs/manim/vpr_explained.py is this same content)
# =============================================================================

# ============================================================ P01  TITLE ======
def s1_title(sc):
    title = Text("VPR", font_size=96, color=C_VPR, weight="BOLD")
    sub = Text("and how bob uses Python with it", font_size=34, color=INK)
    sub.next_to(title, DOWN, buff=0.4)
    line = Line(LEFT * 3.2, RIGHT * 3.2, color=DIM, stroke_width=2)
    line.next_to(sub, DOWN, buff=0.45)
    tag = Text("an FPGA built inside an FPGA", font_size=24, color=DIM)
    tag.next_to(line, DOWN, buff=0.35)

    sc.play(Write(title), run_time=1.2)
    sc.play(FadeIn(sub, shift=UP * 0.2), run_time=0.8)
    sc.play(Create(line), FadeIn(tag), run_time=0.8)
    sc.wait(1.4)

    q = Text("Two questions:", font_size=30, color=INK)
    q1 = Text("1.  What does VPR actually do?", font_size=28, color=C_VPR)
    q2 = Text("2.  Why do we run it twice, for two different jobs?",
              font_size=28, color=C_PY)
    qs = VGroup(q, q1, q2).arrange(DOWN, aligned_edge=LEFT, buff=0.35)

    sc.play(FadeOut(VGroup(title, sub, line, tag)), run_time=0.6)
    sc.play(FadeIn(q), run_time=0.5)
    sc.play(FadeIn(q1, shift=RIGHT * 0.3), run_time=0.7)
    sc.play(FadeIn(q2, shift=RIGHT * 0.3), run_time=0.7)
    sc.wait(2.0)


# ================================================== P02  WHAT IS A FABRIC =====
def s2_fabric(sc):
    sc.heading("First: what is an FPGA fabric?",
               "logic blocks, wires between them, and a switch at every junction")

    # --- the grid ------------------------------------------------------------
    blocks, wires = VGroup(), VGroup()
    for i in range(4):
        for j in range(3):
            b = Square(side_length=0.62, color=C_RTL, stroke_width=2.5)
            b.set_fill(C_RTL, opacity=0.14)
            b.move_to(np.array([-3.6 + i * 1.5, -1.9 + j * 1.5, 0]))
            blocks.add(b)
    for i in range(4):
        for j in range(3):
            c = blocks[i * 3 + j].get_center()
            wires.add(Line(c + RIGHT * 0.36, c + RIGHT * 1.14,
                           color=DIM, stroke_width=2))
            wires.add(Line(c + UP * 0.36, c + UP * 1.14,
                           color=DIM, stroke_width=2))

    lab = Text("logic blocks (LUT + flip-flop)", font_size=22, color=C_RTL)
    lab.next_to(blocks, DOWN, buff=0.45)
    sc.play(LaggedStart(*[FadeIn(b, scale=0.7) for b in blocks], lag_ratio=0.05),
            run_time=1.4)
    sc.play(FadeIn(lab), run_time=0.5)
    sc.play(LaggedStart(*[Create(w) for w in wires], lag_ratio=0.02), run_time=1.4)

    lab2 = Text("routing wires", font_size=22, color=DIM)
    lab2.next_to(lab, DOWN, buff=0.2)
    sc.play(FadeIn(lab2), run_time=0.5)
    sc.wait(0.8)

    # --- zoom out to one junction -------------------------------------------
    fabric = VGroup(blocks, wires, lab, lab2)
    sc.play(fabric.animate.scale(0.55).to_edge(LEFT, buff=0.5), run_time=1.0)

    q = Text("But what is AT a junction?", font_size=28, color=INK)
    q.move_to(np.array([2.6, 2.6, 0]))
    sc.play(FadeIn(q), run_time=0.6)

    mux = mux_symbol().move_to(np.array([2.6, 0.2, 0]))
    ins = VGroup()
    names = ["wire A", "wire B", "wire C", "wire D"]
    for k in range(4):
        y = 1.05 - k * 0.5
        ln = Line(np.array([0.9, y, 0]), np.array([2.2, y, 0]),
                  color=DIM, stroke_width=2.5)
        nm = Text(names[k], font_size=17, color=DIM)
        nm.next_to(ln, LEFT, buff=0.12)
        ins.add(VGroup(ln, nm))
    out = Arrow(np.array([3.0, 0.2, 0]), np.array([4.4, 0.2, 0]),
                buff=0, color=C_RTL, stroke_width=3)
    outl = Text("one output", font_size=18, color=C_RTL)
    outl.next_to(out, RIGHT, buff=0.12)

    sc.play(Create(mux), run_time=0.6)
    sc.play(LaggedStart(*[Create(i) for i in ins], lag_ratio=0.15), run_time=1.0)
    sc.play(GrowArrow(out), FadeIn(outl), run_time=0.6)

    sel = code_block(["sel = 2"], 24, C_BIT)
    sel.next_to(mux, DOWN, buff=0.6)
    selarrow = arrow(sel.get_top(), mux.get_bottom(), C_BIT, buff=0.1)
    sc.play(FadeIn(sel), GrowArrow(selarrow), run_time=0.7)

    # light up input C
    sc.play(ins[2].animate.set_color(C_BIT), out.animate.set_color(C_BIT),
            outl.animate.set_color(C_BIT), run_time=0.8)
    sc.wait(0.6)
    sc.play(sel[0].animate.become(mono("sel = 0", 24, C_BIT).move_to(sel[0])),
            ins[2].animate.set_color(DIM), run_time=0.5)
    sc.play(ins[0].animate.set_color(C_BIT), run_time=0.6)
    sc.wait(0.8)

    sc.play(FadeOut(VGroup(q, fabric)), run_time=0.6)
    detail = VGroup(mux, ins, out, outl, sel, selarrow)
    sc.play(detail.animate.scale(0.85).move_to(np.array([-2.6, 0.2, 0])),
            run_time=0.9)

    punch = VGroup(
        Text("A multiplexer.", font_size=32, color=INK, weight="BOLD"),
        Text("Its select bits come from", font_size=26, color=DIM),
        Text("configuration memory.", font_size=26, color=C_BIT),
        Text(" ", font_size=10),
        Text("So a bitstream is nothing", font_size=28, color=INK),
        Text("but the setting of every", font_size=28, color=INK),
        Text("multiplexer in the chip.", font_size=28, color=C_BIT,
             weight="BOLD"),
    ).arrange(DOWN, aligned_edge=LEFT, buff=0.22)
    punch.move_to(np.array([3.2, 0.1, 0]))
    sc.play(LaggedStart(*[FadeIn(l, shift=RIGHT * 0.2) for l in punch],
                        lag_ratio=0.25), run_time=2.4)

    note = Text("bob today:  3391 multiplexers,  18 560 configuration bits",
                font_size=22, color=C_GRF)
    note.to_edge(DOWN, buff=0.45)
    sc.play(FadeIn(note), run_time=0.7)
    sc.wait(2.0)


# ==================================================== P03  WHAT IS VPR ========
def s3_whatisvpr(sc):
    sc.heading("VPR  =  Versatile Place and Route",
               "the back end of VTR (Verilog-to-Routing).  bob uses VPR 9.")

    arch = chip("architecture XML", C_PY, 3.3, 1.0, 22)
    net = chip("netlist  (.eblif)", C_PY, 3.3, 1.0, 22)
    ins = VGroup(arch, net).arrange(DOWN, buff=0.9).to_edge(LEFT, buff=0.7)
    ins.shift(DOWN * 0.3)

    archd = code_block([
        "a description of an",
        "IMAGINARY FPGA:",
        "  grid size, columns",
        "  block pins",
        "  wire lengths",
        "  switch pattern",
    ], 17, DIM)
    archd.next_to(arch, DOWN, buff=0.18).align_to(arch, LEFT)

    netd = code_block([
        "the user circuit as",
        "LUTs and flip-flops",
    ], 17, DIM)
    netd.next_to(net, DOWN, buff=0.18).align_to(net, LEFT)

    sc.play(FadeIn(arch, shift=RIGHT * 0.3), run_time=0.6)
    sc.play(FadeIn(archd), run_time=0.5)
    sc.play(FadeIn(net, shift=RIGHT * 0.3), run_time=0.6)
    sc.play(FadeIn(netd), run_time=0.5)

    vpr = RoundedRectangle(width=3.0, height=4.2, corner_radius=0.18,
                           color=C_VPR, stroke_width=3.5)
    vpr.set_fill(C_VPR, opacity=0.10).move_to(np.array([0.9, -0.3, 0]))
    vprt = Text("VPR", font_size=36, color=C_VPR, weight="BOLD")
    vprt.next_to(vpr.get_top(), DOWN, buff=0.25)
    sc.play(Create(vpr), Write(vprt), run_time=0.9)
    sc.play(GrowArrow(arrow(arch.get_right(), vpr.get_left() + UP * 1.0)),
            GrowArrow(arrow(net.get_right(), vpr.get_left() + DOWN * 1.0)),
            run_time=0.7)

    stages = VGroup(
        Text("pack", font_size=26, color=INK),
        Text("place", font_size=26, color=INK),
        Text("route", font_size=26, color=INK),
        Text("analysis", font_size=26, color=INK),
    ).arrange(DOWN, buff=0.42)
    stages.move_to(vpr.get_center() + DOWN * 0.25)
    expl = [
        "group primitives into blocks",
        "give every block a grid slot",
        "find a wire path per net",
        "report timing / wirelength",
    ]
    for s, e in zip(stages, expl):
        et = Text(e, font_size=18, color=DIM)
        et.next_to(vpr, RIGHT, buff=0.55).set_y(s.get_y())
        sc.play(FadeIn(s, shift=DOWN * 0.15), FadeIn(et, shift=RIGHT * 0.2),
                run_time=0.55)

    sc.wait(1.6)
    box = SurroundingRectangle(stages[2], color=C_BIT, buff=0.16)
    sc.play(Create(box), run_time=0.5)
    key = Text("routing is the part that decides every mux setting",
               font_size=24, color=C_BIT)
    key.to_edge(DOWN, buff=0.45)
    sc.play(FadeIn(key), run_time=0.7)
    sc.wait(2.0)


# ================================================= P04  THE RR GRAPH ==========
def s4_rrgraph(sc):
    sc.heading("Before VPR can route, it builds a GRAPH",
               "the routing-resource graph: every wire and pin of that imaginary chip")

    # left: a scrap of fabric
    b1 = Square(0.8, color=C_RTL, stroke_width=3).set_fill(C_RTL, opacity=0.14)
    b2 = b1.copy()
    b1.move_to(np.array([-5.0, 1.1, 0]))
    b2.move_to(np.array([-5.0, -1.6, 0]))
    ch = VGroup(*[Line(np.array([-4.2, y, 0]), np.array([-2.4, y, 0]),
                       color=DIM, stroke_width=2.5)
                  for y in (-0.5, -0.15, 0.2)])
    l1 = Text("block", font_size=18, color=C_RTL).next_to(b1, UP, buff=0.12)
    l2 = Text("channel wires", font_size=18, color=DIM).next_to(ch, DOWN, buff=0.2)
    left = VGroup(b1, b2, ch, l1, l2)
    sc.play(FadeIn(left), run_time=0.9)

    conv = Text("becomes", font_size=22, color=DIM)
    conv.move_to(np.array([-1.5, 0.0, 0]))
    ar = arrow(np.array([-2.2, -0.6, 0]), np.array([-0.7, -0.6, 0]), C_GRF, 0.05)
    sc.play(FadeIn(conv), GrowArrow(ar), run_time=0.6)

    # right: nodes + edges
    def node(pos, label, color):
        d = Dot(pos, radius=0.13, color=color)
        t = Text(label, font_size=17, color=color)
        t.next_to(d, UP, buff=0.12)
        return VGroup(d, t)

    n_op = node(np.array([0.4, 1.3, 0]), "OPIN", C_RTL)
    n_cx = node(np.array([2.3, 0.7, 0]), "CHANX", C_GRF)
    n_cy = node(np.array([2.3, -0.9, 0]), "CHANY", C_GRF)
    n_ip = node(np.array([4.4, -0.2, 0]), "IPIN", C_RTL)
    nodes = VGroup(n_op, n_cx, n_cy, n_ip)

    edges = VGroup(
        arrow(n_op[0].get_center(), n_cx[0].get_center(), DIM, 0.18),
        arrow(n_op[0].get_center(), n_cy[0].get_center(), DIM, 0.18),
        arrow(n_cx[0].get_center(), n_ip[0].get_center(), DIM, 0.18),
        arrow(n_cy[0].get_center(), n_ip[0].get_center(), DIM, 0.18),
        arrow(n_cx[0].get_center(), n_cy[0].get_center(), DIM, 0.18),
    )
    sc.play(LaggedStart(*[FadeIn(n, scale=0.6) for n in nodes], lag_ratio=0.2),
            run_time=1.2)
    sc.play(LaggedStart(*[GrowArrow(e) for e in edges], lag_ratio=0.15),
            run_time=1.2)

    legend = code_block([
        "node   =  one wire, or one pin of a block",
        "edge   =  'this one CAN drive that one'",
        "         ... i.e. a programmable switch is there",
    ], 21, INK)
    legend.to_edge(DOWN, buff=0.7)
    sc.play(FadeIn(legend[0]), run_time=0.5)
    sc.play(FadeIn(legend[1]), run_time=0.5)
    sc.play(FadeIn(legend[2]), run_time=0.6)
    sc.wait(1.2)

    concl = Text("Routing a net = finding a path in this graph.",
                 font_size=28, color=C_BIT, weight="BOLD")
    concl.to_edge(DOWN, buff=0.35)
    sc.play(FadeOut(legend), FadeIn(concl), run_time=0.8)

    path = VGroup(
        edges[1].copy().set_color(C_BIT).set_stroke(width=6),
        edges[3].copy().set_color(C_BIT).set_stroke(width=6),
    )
    sc.play(Create(path), run_time=1.0)
    sc.wait(1.8)


# ================================================== P05  THE BIG IDEA =========
def s5_bigidea(sc):
    sc.heading("The big idea", "bob does not describe its hardware to VPR - it BUILDS its hardware FROM VPR's graph")

    # a node with four drivers
    centre = np.array([-3.6, 0.3, 0])
    d = Dot(centre, radius=0.16, color=C_GRF)
    dl = Text("node 3", font_size=20, color=C_GRF).next_to(d, DOWN, buff=0.22)
    drivers, arrows_in = VGroup(), VGroup()
    ids = ["4258", "4259", "4270", "4271"]
    for k, nid in enumerate(ids):
        p = centre + np.array([-2.1, 1.35 - k * 0.9, 0])
        dd = Dot(p, radius=0.10, color=DIM)
        tt = Text(nid, font_size=17, color=DIM).next_to(dd, LEFT, buff=0.12)
        drivers.add(VGroup(dd, tt))
        arrows_in.add(arrow(p, centre, DIM, 0.2))

    sc.play(FadeIn(d), FadeIn(dl), run_time=0.5)
    sc.play(LaggedStart(*[FadeIn(x) for x in drivers], lag_ratio=0.15),
            run_time=0.9)
    sc.play(LaggedStart(*[GrowArrow(a) for a in arrows_in], lag_ratio=0.15),
            run_time=0.9)

    rule = Text("4 edges drive it  ->  it must be a multiplexer",
                font_size=24, color=C_BIT)
    rule.next_to(VGroup(drivers, d), DOWN, buff=0.8)
    sc.play(FadeIn(rule), run_time=0.8)
    sc.wait(1.0)

    # the generated Verilog
    v = code_block([
        "bob_mux #(.N(4), .W(3), .C1(1)) m3 (",
        "    .sel (cfg[384 +: 3]),",
        "    .in  ({r4271, r4270, r4259, r4258}),",
        "    .o   (r3)",
        ");",
    ], 21, C_RTL)
    v.move_to(np.array([2.9, 0.6, 0]))
    vp = panel(v, C_RTL)
    cap = Text("hw/src/generated/bob_fabric.v", font_size=18, color=DIM)
    cap.next_to(vp, UP, buff=0.2)

    sc.play(FadeIn(vp), FadeIn(cap), run_time=1.0)
    sc.wait(0.6)

    hl = [
        ("4 drivers", v[0], "N(4)"),
        ("their node ids", v[2], "in{...}"),
        ("where its bits live in the bitstream", v[1], "cfg[384 +: 3]"),
        ("the node itself", v[3], "r3"),
    ]
    for label, line, _ in hl:
        b = SurroundingRectangle(line, color=C_BIT, buff=0.08)
        t = Text(label, font_size=20, color=C_BIT)
        t.next_to(vp, DOWN, buff=0.35)
        sc.play(Create(b), FadeIn(t), run_time=0.55)
        sc.wait(0.75)
        sc.play(FadeOut(b), FadeOut(t), run_time=0.35)

    sc.play(FadeOut(VGroup(drivers, arrows_in, d, dl, rule)), run_time=0.6)
    sc.play(vp.animate.move_to(np.array([0, 1.3, 0])),
            cap.animate.next_to(vp, UP, buff=0.2).set_x(0), run_time=0.9)

    summary = code_block([
        "every graph node with fan-in    ->   one bob_mux in Verilog",
        "its incoming edges              ->   that mux's inputs",
        "an input driven by only ONE     ->   a plain wire, zero bits",
        "",
        "3391 nodes   ->   3391 muxes   ->   4416 lines of Verilog",
    ], 22, INK)
    summary[4].set_color(C_GRF)
    summary.next_to(vp, DOWN, buff=0.8)
    sc.play(LaggedStart(*[FadeIn(l, shift=UP * 0.15) for l in summary],
                        lag_ratio=0.3), run_time=2.2)
    sc.wait(2.2)


# ===================================================== P06  ROLE 1 ============
def s6_role1(sc):
    sc.heading("Role 1:  VPR designs the fabric",
               "run once, only when the architecture changes   ( make rrgraph )")

    steps = [
        ("device.py", C_PY, "the architecture,\nwritten once"),
        ("bob_k6.xml", C_PY, "VPR's\narchitecture file"),
        ("VPR", C_VPR, "builds and dumps\nthe rr graph"),
        ("bob_k6_rr.xml.gz", C_GRF, "committed,\nsha256-stamped"),
        ("bob_fabric.v", C_RTL, "the real Verilog\n4416 lines"),
    ]
    boxes = VGroup()
    for name, col, _ in steps:
        boxes.add(chip(name, col, 2.45, 0.85, 19))
    boxes.arrange(RIGHT, buff=0.62).scale(0.98).shift(UP * 0.7)

    subs = VGroup()
    for b, (_, col, sub) in zip(boxes, steps):
        t = Text(sub, font_size=15, color=DIM, line_spacing=0.7)
        t.next_to(b, DOWN, buff=0.22)
        subs.add(t)

    for i, b in enumerate(boxes):
        sc.play(FadeIn(b, scale=0.85), FadeIn(subs[i]), run_time=0.45)
        if i < len(boxes) - 1:
            sc.play(GrowArrow(arrow(b.get_right(),
                                    boxes[i + 1].get_left(), DIM, 0.05)),
                    run_time=0.25)

    cmd = code_block([
        "vpr bob_k6.xml and2.blif --device bob12x10 \\",
        "    --route_chan_width 24 --timing_analysis off \\",
        "    --write_rr_graph rr.xml",
    ], 19, C_VPR)
    cmdp = panel(cmd, C_VPR)
    cmdp.next_to(subs, DOWN, buff=0.75)
    sc.play(FadeIn(cmdp), run_time=0.8)
    sc.wait(1.0)

    notes = VGroup(
        Text("and2.blif is a trivial 2-input AND - nobody wants the result.",
             font_size=21, color=INK),
        Text("VPR only builds the graph when it is about to route something,",
             font_size=21, color=DIM),
        Text("so and2 exists purely to make VPR emit --write_rr_graph.",
             font_size=21, color=DIM),
    ).arrange(DOWN, aligned_edge=LEFT, buff=0.18)
    notes.to_edge(DOWN, buff=0.4)
    sc.play(FadeOut(cmdp), run_time=0.4)
    notes.next_to(subs, DOWN, buff=0.8)
    sc.play(LaggedStart(*[FadeIn(n) for n in notes], lag_ratio=0.3),
            run_time=1.6)
    sc.wait(1.4)

    d = Text("the graph is COMMITTED, so Docker is only needed to rebuild it",
             font_size=23, color=C_GRF)
    d.to_edge(DOWN, buff=0.4)
    sc.play(FadeOut(notes), FadeIn(d), run_time=0.8)
    sc.wait(1.8)


# ===================================================== P07  ROLE 2 ============
def s7_role2(sc):
    sc.heading("Role 2:  VPR routes a user design",
               "run for every design   ( ./bob build counter.v )")

    row1 = VGroup(
        chip("counter.v", INK, 2.1, 0.8, 19),
        chip("yosys", C_PY, 1.9, 0.8, 19),
        chip("vpr_run\nprepare()", C_PY, 2.3, 0.9, 17),
        chip(".eblif\n+ pins", C_PY, 1.9, 0.9, 17),
    ).arrange(RIGHT, buff=0.55).shift(UP * 1.7)

    row2 = VGroup(
        chip("VPR", C_VPR, 1.9, 0.85, 22, "BOLD"),
        chip(".net .place\n.route", C_VPR, 2.3, 0.9, 17),
        chip("fasm_from_vpr", C_PY, 2.7, 0.85, 17),
        chip("FASM -> bits", C_BIT, 2.4, 0.85, 18),
    ).arrange(RIGHT, buff=0.55).shift(DOWN * 0.3)

    for row in (row1, row2):
        for i, b in enumerate(row):
            sc.play(FadeIn(b, scale=0.85), run_time=0.35)
            if i < len(row) - 1:
                sc.play(GrowArrow(arrow(b.get_right(), row[i + 1].get_left(),
                                        DIM, 0.05)), run_time=0.2)
        if row is row1:
            sc.play(GrowArrow(arrow(row1[3].get_bottom(), row2[0].get_top(),
                                    DIM, 0.1)), run_time=0.3)

    tail = VGroup(chip(".bit", C_BIT, 1.5, 0.8, 20),
                  chip("the board", C_RTL, 2.2, 0.8, 20))
    tail.arrange(RIGHT, buff=0.7).next_to(row2, DOWN, buff=0.85).set_x(2.4)
    sc.play(GrowArrow(arrow(row2[3].get_bottom(), tail[0].get_top(), DIM, 0.1)),
            FadeIn(tail[0]), run_time=0.45)
    sc.play(GrowArrow(arrow(tail[0].get_right(), tail[1].get_left(), DIM, 0.05)),
            FadeIn(tail[1]), run_time=0.45)

    flag = code_block(["--read_rr_graph rr.xml"], 26, C_GRF)
    flagp = panel(flag, C_GRF)
    flagp.next_to(row2[0], LEFT, buff=0.5).shift(DOWN * 1.1).set_x(-3.4)
    sc.play(FadeIn(flagp), GrowArrow(arrow(flagp.get_right(),
                                           row2[0].get_left(), C_GRF, 0.1)),
            run_time=0.8)
    msg = Text("the SAME committed graph the Verilog was generated from",
               font_size=22, color=C_GRF)
    msg.to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(msg), run_time=0.7)
    sc.wait(1.4)

    inv = Text("VPR routes on exactly the hardware that exists.",
               font_size=30, color=C_BIT, weight="BOLD")
    inv.to_edge(DOWN, buff=0.35)
    sc.play(FadeOut(msg), FadeIn(inv), run_time=0.8)
    sc.wait(2.2)


# ================================================ P08  ROUTE -> BITS ==========
def s8_routetobits(sc):
    sc.heading("How a route turns into bits",
               "this is the whole trick, and it is four lines of Python")

    ys = 1.55
    pts = [np.array([-4.6, ys, 0]), np.array([-1.7, ys, 0]),
           np.array([1.2, ys, 0]), np.array([4.1, ys, 0])]
    labels = ["r900\nOPIN", "r1204\nCHANX", "r1631\nCHANY", "r68\nIPIN"]
    cols = [C_RTL, C_GRF, C_GRF, C_RTL]
    nodes = VGroup()
    for p, l, c in zip(pts, labels, cols):
        dd = Dot(p, radius=0.15, color=c)
        tt = Text(l, font_size=18, color=c, line_spacing=0.7)
        tt.next_to(dd, UP, buff=0.18)
        nodes.add(VGroup(dd, tt))
    hops = VGroup(*[arrow(pts[i], pts[i + 1], DIM, 0.22) for i in range(3)])

    sc.play(LaggedStart(*[FadeIn(n) for n in nodes], lag_ratio=0.15),
            run_time=1.0)
    sc.play(LaggedStart(*[GrowArrow(h) for h in hops], lag_ratio=0.2),
            run_time=0.9)

    rt = code_block([
        "counter.route",
        "  Net 7 (n_q3)",
        "    Node:  900  OPIN",
        "    Node: 1204  CHANX",
        "    Node: 1631  CHANY",
        "    Node:   68  IPIN",
    ], 18, DIM)
    rt[0].set_color(C_VPR)
    rtp = panel(rt, C_VPR)
    rtp.to_edge(LEFT, buff=0.5).shift(DOWN * 1.6)
    sc.play(FadeIn(rtp), run_time=0.7)
    sc.wait(0.6)

    code = code_block([
        "for node in branch:",
        "    lo, w, base, ins = B.MUX[node]",
        "    put(f\"rr{node}\", base + ins.index(prev))",
        "    prev = node",
    ], 19, C_PY)
    codep = panel(code, C_PY)
    codep.to_edge(RIGHT, buff=0.5).shift(DOWN * 1.35)
    sc.play(FadeIn(codep), run_time=0.8)

    say = Text("\"the mux at this node selects the node I came from\"",
               font_size=23, color=C_BIT)
    say.next_to(codep, UP, buff=0.3).set_x(2.6)
    sc.play(FadeIn(say), run_time=0.7)
    sc.wait(1.2)

    out = VGroup()
    feats = ["rr1204 = 3'h2", "rr1631 = 3'h1", "rr68   = 3'h4"]
    for i in range(3):
        sc.play(hops[i].animate.set_color(C_BIT).set_stroke(width=6),
                nodes[i + 1][0].animate.set_color(C_BIT), run_time=0.45)
        f = mono(feats[i], 21, C_BIT)
        if out:
            f.next_to(out[-1], DOWN, buff=0.16).align_to(out[-1], LEFT)
        else:
            f.move_to(np.array([-0.3, -0.6, 0]))
        out.add(f)
        sc.play(FadeIn(f, shift=DOWN * 0.15), run_time=0.45)
        sc.wait(0.3)

    sc.wait(0.8)
    sc.play(FadeOut(VGroup(rtp, codep, say)), run_time=0.5)
    sc.play(out.animate.move_to(np.array([-3.3, -1.3, 0])), run_time=0.7)

    chain = VGroup()
    for i in range(24):
        s = Square(0.28, color=DIM, stroke_width=1.6)
        s.set_fill(C_BIT if i in (3, 4, 10, 17, 18) else BG,
                   opacity=0.9 if i in (3, 4, 10, 17, 18) else 0.0)
        chain.add(s)
    chain.arrange(RIGHT, buff=0.04).move_to(np.array([2.6, -1.3, 0]))
    ctext = Text("the 18 560-bit configuration chain", font_size=19, color=DIM)
    ctext.next_to(chain, DOWN, buff=0.25)
    sc.play(GrowArrow(arrow(out.get_right(), chain.get_left(), C_BIT, 0.25)),
            Create(chain), FadeIn(ctext), run_time=1.0)

    fin = Text("bits -> FASM -> bits round-trips exactly:  a bit no feature owns is rejected",
               font_size=21, color=INK)
    fin.to_edge(DOWN, buff=0.35)
    sc.play(FadeIn(fin), run_time=0.7)
    sc.wait(2.2)


# ============================================= P09  PYTHON BOUNDARIES =========
def s9_python(sc):
    sc.heading("Where Python sits",
               "VPR does the algorithms;  Python owns every boundary around them")

    vpr = RoundedRectangle(width=2.4, height=1.5, corner_radius=0.16,
                           color=C_VPR, stroke_width=3.5)
    vpr.set_fill(C_VPR, opacity=0.12)
    vprt = Text("VPR", font_size=32, color=C_VPR, weight="BOLD").move_to(vpr)
    core = VGroup(vpr, vprt).move_to(ORIGIN + DOWN * 0.2)
    sc.play(FadeIn(core), run_time=0.6)

    items = [
        ("vpr_arch.py", "writes VPR's input", np.array([-4.3, 1.9, 0]),
         "turns the ARCH dict into the architecture XML"),
        ("rrgraph.py", "reads VPR's output", np.array([4.3, 1.9, 0]),
         "parses the rr graph;  the RTL is generated from it"),
        ("vpr_run.py", "prepares + drives", np.array([-4.3, -2.0, 0]),
         "netlist rewrite, pins, Docker, stamped results"),
        ("fasm_from_vpr.py", "reads VPR's output", np.array([4.3, -2.0, 0]),
         "net/place/route  ->  FASM  ->  configuration bits"),
    ]
    for name, role, pos, detail in items:
        b = chip(name, C_PY, 3.1, 0.8, 20).move_to(pos)
        r = Text(role, font_size=17, color=DIM).next_to(b, DOWN, buff=0.14)
        dt = Text(detail, font_size=15, color=DIM).next_to(r, DOWN, buff=0.1)
        if dt.width > 4.4:
            dt.scale_to_fit_width(4.4)
        a = arrow(b.get_center(), core.get_center(), C_PY, 1.55)
        sc.play(FadeIn(b, scale=0.85), FadeIn(r), FadeIn(dt),
                GrowArrow(a), run_time=0.7)

    sc.wait(1.6)
    big = Text("Python never does the placing or the routing here - "
               "it decides what VPR is asked, and what its answer means.",
               font_size=21, color=INK)
    big.scale_to_fit_width(12.8).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(big), run_time=0.9)
    sc.wait(2.0)


# ================================================ P10  PYTHON PnR ============
def s10_pythonpnr(sc):
    sc.heading("M12a:  Python doing VPR's job",
               "software/bob/pnr/  -  same input, same output files, no Docker")

    src = chip("vpr_run.prepare()\n.eblif  +  pins", C_PY, 3.4, 1.1, 19)
    src.move_to(np.array([-4.3, 1.4, 0]))
    sc.play(FadeIn(src), run_time=0.6)

    top = chip("VPR  (Docker)", C_VPR, 3.0, 0.85, 21)
    bot = chip("software/bob/pnr/", C_PY, 3.0, 0.85, 21)
    top.move_to(np.array([-0.3, 2.4, 0]))
    bot.move_to(np.array([-0.3, 0.3, 0]))
    out = chip(".net  .place  .route", C_BIT, 3.6, 0.9, 19)
    out.move_to(np.array([3.9, 1.4, 0]))

    sc.play(GrowArrow(arrow(src.get_right(), top.get_left(), DIM, 0.1)),
            FadeIn(top), run_time=0.5)
    sc.play(GrowArrow(arrow(src.get_right(), bot.get_left(), DIM, 0.1)),
            FadeIn(bot), run_time=0.5)
    sc.play(GrowArrow(arrow(top.get_right(), out.get_left(), DIM, 0.1)),
            GrowArrow(arrow(bot.get_right(), out.get_left(), DIM, 0.1)),
            FadeIn(out), run_time=0.6)
    shared = Text("everything after this point is shared",
                  font_size=19, color=DIM)
    shared.next_to(out, DOWN, buff=0.22)
    sc.play(FadeIn(shared), run_time=0.5)
    sc.wait(0.8)

    algs = code_block([
        "pack.py    one BLE per CLB, carry chains as macros   (VPR's pack patterns)",
        "place.py   simulated annealing, bounding-box cost     (Betz & Rose, 1997)",
        "route.py   PathFinder negotiated congestion + A*      (McMurchie & Ebeling, 1995)",
    ], 18, INK)
    algs.next_to(bot, DOWN, buff=1.0).set_x(0)
    sc.play(LaggedStart(*[FadeIn(a, shift=RIGHT * 0.2) for a in algs],
                        lag_ratio=0.3), run_time=1.6)
    sc.wait(1.0)

    cost = code_block([
        "cost(n) = base(n) x (1 + hist(n)) x (1 + pres_fac x overuse(n))",
    ], 20, C_BIT)
    costp = panel(cost, C_BIT)
    costp.next_to(algs, DOWN, buff=0.45)
    sc.play(FadeIn(costp), run_time=0.7)
    why = Text("every node has capacity 1 - a mux selects exactly one driver",
               font_size=19, color=DIM)
    why.next_to(costp, DOWN, buff=0.2)
    sc.play(FadeIn(why), run_time=0.6)
    sc.wait(1.8)

    sc.play(FadeOut(VGroup(src, top, bot, out, shared, algs, costp, why)),
            run_time=0.6)

    res = Text("Total wirelength, 11 designs, 100-CLB grid",
               font_size=26, color=INK).shift(UP * 2.0)
    sc.play(FadeIn(res), run_time=0.5)

    def bar(label, value, width, color, y):
        r = Rectangle(width=width, height=0.62, color=color, stroke_width=2.5)
        r.set_fill(color, opacity=0.35)
        r.move_to(np.array([-4.6 + width / 2, y, 0]))
        lt = Text(label, font_size=22, color=color).next_to(r, LEFT, buff=0.3)
        vt = Text(str(value), font_size=22, color=color).next_to(r, RIGHT, buff=0.25)
        return VGroup(r, lt, vt)

    b1 = bar("VPR", 4017, 7.2, C_VPR, 0.7)
    b2 = bar("bob", 3601, 6.45, C_PY, -0.3)
    sc.play(GrowFromEdge(b1[0], LEFT), FadeIn(b1[1]), FadeIn(b1[2]),
            run_time=0.9)
    sc.play(GrowFromEdge(b2[0], LEFT), FadeIn(b2[1]), FadeIn(b2[2]),
            run_time=0.9)

    ratio = Text("0.90x", font_size=46, color=C_BIT, weight="BOLD")
    ratio.shift(DOWN * 1.6)
    sc.play(Write(ratio), run_time=0.7)
    caveat = Text("VPR is still timing-driven;  bob's router optimises "
                  "congestion and wirelength only",
                  font_size=19, color=DIM).to_edge(DOWN, buff=0.4)
    sc.play(FadeIn(caveat), run_time=0.6)
    sc.wait(2.2)


# ======================================================= P11  RECAP ===========
def s11_recap(sc):
    t = Text("So, in one picture", font_size=34, color=INK, weight="BOLD")
    t.to_edge(UP, buff=0.5)
    sc.play(FadeIn(t), run_time=0.6)

    dev = chip("device.py", C_PY, 2.4, 0.8, 20).move_to(np.array([-4.6, 1.5, 0]))
    vpr1 = chip("VPR", C_VPR, 1.7, 0.8, 20).move_to(np.array([-1.5, 1.5, 0]))
    grf = chip("rr graph", C_GRF, 2.3, 0.8, 20).move_to(np.array([1.6, 1.5, 0]))
    rtl = chip("bob_fabric.v", C_RTL, 2.7, 0.8, 20).move_to(np.array([4.9, 1.5, 0]))

    des = chip("design.v", INK, 2.2, 0.8, 20).move_to(np.array([-4.6, -1.3, 0]))
    vpr2 = chip("VPR  or  pnr/", C_VPR, 2.9, 0.8, 19).move_to(np.array([-1.3, -1.3, 0]))
    bits = chip("bits", C_BIT, 1.7, 0.8, 20).move_to(np.array([1.7, -1.3, 0]))
    brd = chip("the board", C_RTL, 2.4, 0.8, 20).move_to(np.array([4.9, -1.3, 0]))

    top_row = (dev, vpr1, grf, rtl)
    bot_row = (des, vpr2, bits, brd)
    for row in (top_row, bot_row):
        sc.play(LaggedStart(*[FadeIn(m, scale=0.85) for m in row],
                            lag_ratio=0.2), run_time=1.0)
        sc.play(LaggedStart(*[GrowArrow(arrow(row[i].get_right(),
                                              row[i + 1].get_left(), DIM, 0.08))
                              for i in range(3)], lag_ratio=0.2), run_time=0.8)

    down = DashedLine(grf.get_bottom(), vpr2.get_top() + RIGHT * 1.2,
                      color=C_GRF, stroke_width=3, dash_length=0.12)
    dl = Text("the same graph, both times", font_size=20, color=C_GRF)
    dl.next_to(down, RIGHT, buff=0.25).shift(DOWN * 0.1)
    sc.play(Create(down), FadeIn(dl), run_time=1.0)

    r1 = Text("role 1:  once per architecture", font_size=20, color=DIM)
    r1.next_to(dev, UP, buff=0.35).set_x(0)
    r2 = Text("role 2:  once per design", font_size=20, color=DIM)
    r2.next_to(des, DOWN, buff=0.35).set_x(0)
    sc.play(FadeIn(r1), FadeIn(r2), run_time=0.6)
    sc.wait(1.6)

    sc.play(FadeOut(VGroup(*sc.mobjects)), run_time=0.8)
    final = VGroup(
        Text("VPR designs the routing once,", font_size=32, color=INK),
        Text("bob's Verilog is generated from that design,", font_size=32, color=C_RTL),
        Text("and VPR then routes user designs on the very same graph.",
             font_size=32, color=C_GRF),
        Text(" ", font_size=14),
        Text("Python owns every boundary - and can replace the middle.",
             font_size=30, color=C_PY, weight="BOLD"),
    ).arrange(DOWN, buff=0.3)
    sc.play(LaggedStart(*[FadeIn(l, shift=UP * 0.2) for l in final],
                        lag_ratio=0.35), run_time=3.0)
    sc.wait(3.0)


# ================================================== SCENE WRAPPERS ===========
EP09 = [s1_title, s2_fabric, s3_whatisvpr, s4_rrgraph,
         s5_bigidea, s6_role1, s7_role2, s8_routetobits,
         s9_python, s10_pythonpnr, s11_recap]


class E09S1Title(BobScene):
    def construct(self): s1_title(self)


class E09S2Fabric(BobScene):
    def construct(self): s2_fabric(self)


class E09S3WhatIsVPR(BobScene):
    def construct(self): s3_whatisvpr(self)


class E09S4RRGraph(BobScene):
    def construct(self): s4_rrgraph(self)


class E09S5BigIdea(BobScene):
    def construct(self): s5_bigidea(self)


class E09S6Role1(BobScene):
    def construct(self): s6_role1(self)


class E09S7Role2(BobScene):
    def construct(self): s7_role2(self)


class E09S8RouteToBits(BobScene):
    def construct(self): s8_routetobits(self)


class E09S9Python(BobScene):
    def construct(self): s9_python(self)


class E09S10PythonPnR(BobScene):
    def construct(self): s10_pythonpnr(self)


class E09S11Recap(BobScene):
    def construct(self): s11_recap(self)


class Ep09VPR(BobScene):
    def construct(self):
        self.titlecard("EPISODE 9", "VPR",
                       "the tool that designs the routing and then routes on it")
        for i, part in enumerate(EP09):
            part(self)
            if i < len(EP09) - 1:
                clear_all(self)
