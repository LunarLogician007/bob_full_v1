# =============================================================================
#  EPISODE 13 - Every error we hit, and the rule it became
# =============================================================================

def s1_intro(sc):
    n = Text("42", font_size=110, color=C_ERR, weight="BOLD").shift(UP * 0.8)
    t = Text("entries in the problems table", font_size=28, color=INK)
    t.next_to(n, DOWN, buff=0.4)
    sc.play(Write(n), run_time=0.9)
    sc.play(FadeIn(t), run_time=0.6)
    sc.wait(1.0)

    k = Text("Almost every one of them became a rule, a test, or both.",
             font_size=26, color=C_BIT)
    k.next_to(t, DOWN, buff=0.7)
    sc.play(FadeIn(k), run_time=0.8)
    sc.wait(1.6)
    sc.play(FadeOut(VGroup(n, t, k)), run_time=0.6)

    sc.heading("The worst kind of bug", "not the one that breaks - the one that passes")
    kinds = code_block([
        "a constraint file that was silently skipped, so nothing was constrained",
        "a guard that could be deleted with every test still green",
        "a test whose stimulus never exercised the thing it claimed to check",
        "a mutation that stopped matching when the grid grew",
        "",
        "All four of these happened here. All four now have a test that catches them.",
    ], 21, INK)
    kinds[5].set_color(C_BIT)
    kinds.next_to(sc.mobjects[1], DOWN, buff=0.9).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l, shift=RIGHT * 0.15) for l in kinds], lag_ratio=0.22),
            run_time=2.4)
    sc.wait(2.0)


def s2_tcl(sc):
    sc.heading("1. Tcl in the XDC", "M0 - and it reported success the whole time")

    bad = code_block([
        "the old constraint file did this:",
        "",
        "    if {$top eq \"fpga4x4_top\"} {",
        "        create_clock -period 1000.0 -name tck [get_ports tck]",
        "    }",
    ], 21, C_ERR)
    bad[0].set_color(DIM)
    bad.shift(UP * 1.7)
    sc.play(FadeIn(bad), run_time=0.9)

    what = code_block([
        "Vivado's XDC parser rejects Tcl control flow. It does not stop the build -",
        "it prints a critical warning and SKIPS the line.",
        "",
        "So create_clock never ran. TCK had no clock. Nothing was analysed.",
        "And the report said: all constraints met.",
    ], 20, INK)
    what[3].set_color(C_ERR); what[4].set_color(C_ERR)
    what.next_to(bad, DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in what], lag_ratio=0.2), run_time=2.0)

    rule = code_block([
        "RULE   the XDC is plain XDC.  tests/test_layout.py rejects Tcl commands in it.",
        "       Anything top-dependent lives in drc_waiver.tcl, which is real Tcl.",
        "       tests/test_reports.py checks the report says no_clock (0).",
    ], 19, C_RTL)
    rule.to_edge(DOWN, buff=0.4).set_x(0)
    sc.play(FadeIn(rule), run_time=0.9)
    sc.wait(2.2)


def s3_guard(sc):
    sc.heading("2. A guard that nobody tested", "M2 - which is why this project has mutation tests")

    story = code_block([
        "The configuration plane refuses a load whose bit count is wrong.",
        "There was a testbench for it. It passed.",
        "",
        "Then someone deleted the length check and ran the testbench again.",
        "It still passed.",
    ], 22, INK)
    story[4].set_color(C_ERR)
    story.shift(UP * 1.6)
    sc.play(FadeIn(story[0]), FadeIn(story[1]), run_time=0.9)
    sc.wait(0.8)
    sc.play(FadeIn(story[3]), run_time=0.6)
    sc.play(FadeIn(story[4]), run_time=0.6)
    sc.wait(1.0)

    fix = code_block([
        "make mutate now breaks each guard ON PURPOSE and requires a testbench to fail:",
        "",
        "   mutate_cfg.sh       5 mutants   CRC polynomial, CRC guard, length guard,",
        "                                   write key, start without commit",
        "   mutate_fabric.sh   25 mutants   GSR, GWE freeze, gce, routed CE, dividers,",
        "                                   BRAM modes, DSP cascade, mux encoding, carry",
        "   mutate_frames.sh   29 mutants   every frame-path refusal",
        "",
        "59 mutants. All killed. Two needed NEW scenarios before they could be.",
    ], 19, INK)
    fix[0].set_color(DIM)
    fix[8].set_color(C_BIT)
    fix.next_to(story, DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in fix], lag_ratio=0.15), run_time=2.4)
    sc.wait(2.2)


def s4_vivado(sc):
    sc.heading("3. Vivado crashed four times", "M13 - and the fourth one restarted Windows")

    rows = [
        ("1", "closed during synthesis",
         "cfg[idx*128 +: 128] <= data over 4992 bits is a barrel shifter:\n"
         "~12k LUTs, 1.7 GB in yosys alone", C_ERR),
        ("2", "crashed again, same point",
         "keep_hierarchy on u_fabric made Vivado use set_disable_timing on\n"
         "the kept boundary while breaking timing loops", C_ERR),
        ("3", "same crash",
         "keep_hierarchy on the SMALL modules was enough to do it too", C_ERR),
        ("4", "same step, and Windows restarted",
         "a program crash does not restart Windows - the machine was under load,\n"
         "and the constant was XDC-driven loop breaking during synthesis", C_ERR),
        ("5", "built in 3.5 min at 2.0 GB",
         "per-frame write decode, fabric flattened, multicycles by clock,\n"
         "and USED_IN_SYNTHESIS false on the XDC", C_RTL),
    ]
    g = VGroup()
    for n, a, b, col in rows:
        num = mono(n, 20, col)
        t = Text(a, font_size=18, color=col)
        w = Text(b, font_size=15, color=DIM, line_spacing=0.8)
        g.add(VGroup(num, VGroup(t, w).arrange(DOWN, aligned_edge=LEFT, buff=0.08))
              .arrange(RIGHT, buff=0.35, aligned_edge=UP))
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.24)
    if g.height > 5.0:
        g.scale_to_fit_height(5.0)
    g.next_to(sc.mobjects[1], DOWN, buff=0.5).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.15) for r in g], lag_ratio=0.2),
            run_time=2.6)

    rules = Text("RULES: no computed part-select over the configuration memory  ·  "
                 "no keep_hierarchy anywhere  ·  the XDC is implementation-only  ·  "
                 "compare a yosys estimate with the last good build before every hand-off",
                 font_size=17, color=C_RTL)
    rules.scale_to_fit_width(13.2).to_edge(DOWN, buff=0.28)
    sc.play(FadeIn(rules), run_time=0.9)
    sc.wait(2.4)


def s5_board(sc):
    sc.heading("4. Things only the board could teach us", "M11 - simulation was perfectly happy")

    a = code_block([
        "ram-readback failed on the real board.",
        "",
        "BRAM contents survive JPROGRAM. bob load wrote only up to the last",
        "non-zero word - so every zero word kept the PREVIOUS design's value.",
        "",
        "Fix: always write all 1024 words of every BRAM the design uses,",
        "and put a section in the .bit even when it is all zeros.",
    ], 20, INK)
    a[0].set_color(C_ERR)
    a[5].set_color(C_RTL); a[6].set_color(C_RTL)
    a.shift(UP * 1.4)
    sc.play(LaggedStart(*[FadeIn(l) for l in a], lag_ratio=0.18), run_time=2.0)
    sc.wait(0.8)

    b = code_block([
        "The live checks passed too - after seeing exactly ONE input vector.",
        "Eight seconds was not enough for a person to flip anything.",
        "",
        "Fix: guided checks. A description, example inputs, Enter to start,",
        "a live status line, explicit goals, and 90 seconds to reach them.",
    ], 20, INK)
    b[0].set_color(C_ERR)
    b[3].set_color(C_RTL); b[4].set_color(C_RTL)
    b.next_to(a, DOWN, buff=0.7).set_x(0)
    sc.play(LaggedStart(*[FadeIn(l) for l in b], lag_ratio=0.18), run_time=1.9)

    r = Text("Anything a person does by hand needs a guide: what to press, what the LEDs "
             "must show, and time to do it.", font_size=19, color=C_BIT)
    r.scale_to_fit_width(13.0).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(r), run_time=0.9)
    sc.wait(2.2)


def s6_subtle(sc):
    sc.heading("5. The quiet ones", "each of these produced a legal, plausible, wrong answer")

    rows = [
        ("route branches in sink order",
         "the .route parser attached a branch to the wrong predecessor - legal edges,"),
        ("", "wrong mux values. Only the model check caught it. Now emitted in tree order."),
        ("a Verilog macro defined twice",
         "the expected data was sent AS the stream. Unique names now."),
        ("`CNT8_BITS used above its include",
         "iverilog did not error; the register came out 2 bits wide and 298 checks failed."),
        ("a mutant pinned to a grid position",
         "carry-direct-cut cut column 5's carry; the test counter moved to column 8,"),
        ("", "then 12. The mutant survived silently - twice. It now follows the last column."),
        ("uniform random stimulus",
         "held a counter's reset half the time, so its trace was all zeros and its"),
        ("", "check could never fail. Biased 50-cycle segments now."),
    ]
    g = VGroup()
    for a, b in rows:
        if a:
            g.add(VGroup(mono(a, 18, C_ERR), Text(b, font_size=16, color=DIM))
                  .arrange(RIGHT, buff=0.4, aligned_edge=DOWN))
        else:
            g.add(Text(b, font_size=16, color=DIM))
    for r in g:
        if isinstance(r, VGroup) and len(r) == 2:
            r[1].align_to(g[0][1], LEFT).shift(RIGHT * 4.2)
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.2)
    if g.width > 13.2:
        g.scale_to_fit_width(13.2)
    g.next_to(sc.mobjects[1], DOWN, buff=0.6).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.15) for r in g], lag_ratio=0.14),
            run_time=2.8)

    note = Text("None of these threw an error. Every one was caught by comparing against "
                "something independent - a model, a trace, a mutant.",
                font_size=19, color=C_BIT)
    note.scale_to_fit_width(13.2).to_edge(DOWN, buff=0.3)
    sc.play(FadeIn(note), run_time=0.9)
    sc.wait(2.4)


def s7_rules(sc):
    sc.heading("The rules that came out of all this",
               "every one of them is in CLAUDE.md or PLAN.md, and every one was paid for")

    rules = [
        "One milestone at a time, and every milestone ends on the real board.",
        "Every Vivado build is the complete FPGA plus the new feature - never a block alone.",
        "Ground designs in tested references, and say explicitly where you diverge.",
        "Architecture numbers live in ONE file; everything else is generated from it.",
        "Committed generated data carries a stamp of what built it, and stale data is refused.",
        "Test each guard in isolation - if you can delete it and stay green, you have no test.",
        "Check that your stimulus exercises what it claims.",
        "Every hardware check runs against a stand-in board first, passing and failing.",
        "Never edit a past board result. Append.",
    ]
    g = VGroup(*[VGroup(mono("*", 19, C_BIT), Text(t, font_size=18, color=INK))
                 .arrange(RIGHT, buff=0.3, aligned_edge=DOWN) for t in rules])
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.26)
    if g.width > 13.2:
        g.scale_to_fit_width(13.2)
    g.next_to(sc.mobjects[1], DOWN, buff=0.6).set_x(0)
    sc.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.15) for r in g], lag_ratio=0.18),
            run_time=2.8)
    sc.wait(2.6)


def s8_files(sc):
    sc.files_used(
        inputs=[("PLAN.md", "section 8: gotchas already paid for"),
                ("docs/project/REPORT.md", "section 19: all 42, with the fix"),
                ("CLAUDE.md", "the rules, in the form an agent must follow")],
        generated=[("docs/hwtest/results.log", "57 runs - the failures are still in it"),
                   ("docs/reports/M*/", "every Vivado log, including the crashes")],
        verified=[("sim/mutate_*.sh", "59 mutants - the tests that test the tests"),
                  ("tests/test_layout.py", "no Tcl in the XDC, ever again"),
                  ("tests/test_reports.py", "WNS, failing endpoints, no_clock (0)")])


EP13 = [s1_intro, s2_tcl, s3_guard, s4_vivado, s5_board, s6_subtle, s7_rules, s8_files]


class Ep13Errors(BobScene):
    def construct(self):
        self.titlecard("EPISODE 13", "Every error we hit",
                       "and the rule it became")
        for i, part in enumerate(EP13):
            part(self)
            if i < len(EP13) - 1:
                clear_all(self)


class E13S1Intro(BobScene):
    def construct(self): s1_intro(self)


class E13S2Tcl(BobScene):
    def construct(self): s2_tcl(self)


class E13S3Guard(BobScene):
    def construct(self): s3_guard(self)


class E13S4Vivado(BobScene):
    def construct(self): s4_vivado(self)


class E13S5Board(BobScene):
    def construct(self): s5_board(self)


class E13S6Subtle(BobScene):
    def construct(self): s6_subtle(self)


class E13S7Rules(BobScene):
    def construct(self): s7_rules(self)


class E13S8Files(BobScene):
    def construct(self): s8_files(self)
