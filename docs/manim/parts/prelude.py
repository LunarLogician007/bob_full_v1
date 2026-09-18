# =============================================================================
#  shared prelude - palette, helpers and the BobScene base class.
#  docs/manim/build.py pastes this into the top of every episode cell.
# =============================================================================

from manim import *
import numpy as np

# ---------------------------------------------------------------- palette ----
BG    = "#11121a"
INK   = "#e8e8ea"
DIM   = "#8b93a7"
C_PY  = "#7aa2f7"   # blue    - Python / tools / the device description
C_VPR = "#f7768e"   # red     - VPR / external tools
C_RTL = "#9ece6a"   # green   - hardware, Verilog, things on the die
C_BIT = "#e0af68"   # amber   - configuration bits, FASM, the bitstream
C_GRF = "#bb9af7"   # purple  - graphs, JTAG, protocol
C_ERR = "#ff7a93"   # pink    - bugs, refusals, errors
MONO  = "monospace"


# ---------------------------------------------------------------- helpers ----
def mono(s, size=22, color=INK):
    """One line of monospace text (Pango crashes on '', so blanks become ' ')."""
    return Text(s if s else " ", font=MONO, font_size=size, color=color)


def code_block(lines, size=20, color=INK):
    g = VGroup(*[mono(l, size, color) for l in lines])
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.14)
    return g


def panel(mob, color=DIM, pad=0.32, fill=0.06):
    r = SurroundingRectangle(mob, color=color, buff=pad)
    r.set_fill(color, opacity=fill)
    return VGroup(r, mob)


def chip(label, color, w=2.6, h=0.95, size=22, weight="NORMAL"):
    box = RoundedRectangle(width=w, height=h, corner_radius=0.14,
                           color=color, stroke_width=3)
    box.set_fill(color, opacity=0.12)
    txt = Text(label, font_size=size, color=INK, weight=weight, line_spacing=0.75)
    if txt.width > w - 0.3:
        txt.scale_to_fit_width(w - 0.3)
    if txt.height > h - 0.2:
        txt.scale_to_fit_height(h - 0.2)
    return VGroup(box, txt.move_to(box.get_center()))


def arrow(a, b, color=DIM, buff=0.15, sw=3):
    return Arrow(a, b, buff=buff, color=color, stroke_width=sw,
                 max_tip_length_to_length_ratio=0.18)


def mux_symbol(color=C_RTL, h=1.9, w=0.8):
    """Classic trapezoid multiplexer symbol."""
    p = Polygon([-w / 2,  h / 2, 0], [w / 2,  h / 2 - 0.3, 0],
                [ w / 2, -h / 2 + 0.3, 0], [-w / 2, -h / 2, 0],
                color=color, stroke_width=3)
    p.set_fill(color, opacity=0.14)
    return p


def bitcells(n, size=0.3, on=(), color=C_BIT, off_color=DIM):
    """A strip of n little squares; indices in `on` are filled."""
    g = VGroup()
    for i in range(n):
        s = Square(size, color=off_color, stroke_width=1.6)
        if i in on:
            s.set_stroke(color).set_fill(color, opacity=0.85)
        g.add(s)
    g.arrange(RIGHT, buff=0.035)
    return g


def fieldbar(fields, total_w=11.0, h=0.62, size=15):
    """
    fields: [(label, nbits, color), ...] -> one horizontal bar split to scale,
    each slice labelled above and its bit range below. Returns VGroup(bar, labels, ranges).
    """
    nbits = sum(f[1] for f in fields)
    bar, labs, rngs = VGroup(), VGroup(), VGroup()
    x, lo = -total_w / 2, 0
    for label, n, col in fields:
        w = max(total_w * n / nbits, 0.34)
        r = Rectangle(width=w, height=h, color=col, stroke_width=2)
        r.set_fill(col, opacity=0.28).move_to(np.array([x + w / 2, 0, 0]))
        bar.add(r)
        t = Text(label, font_size=size, color=col)
        if t.width > w * 1.9:
            t.scale_to_fit_width(max(w * 1.9, 0.5))
        t.next_to(r, UP, buff=0.14)
        labs.add(t)
        rt = mono(f"{lo}" if n == 1 else f"{lo}..{lo + n - 1}", size - 2, DIM)
        rt.next_to(r, DOWN, buff=0.12)
        if rt.width > w * 1.9:
            rt.scale_to_fit_width(max(w * 1.9, 0.5))
        rngs.add(rt)
        x += w
        lo += n
    return VGroup(bar, labs, rngs)


def filecard(path, role, color):
    """A small card naming a repo file and what it is."""
    t = mono(path, 17, color)
    r = Text(role, font_size=14, color=DIM)
    g = VGroup(t, r).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
    box = SurroundingRectangle(g, color=color, buff=0.16)
    box.set_fill(color, opacity=0.07)
    return VGroup(box, g)


def mid(a, b):
    """midpoint, defined here so nothing depends on manim exporting space_ops."""
    return (a + b) / 2


def clear_all(sc, run_time=0.6):
    if sc.mobjects:
        sc.play(*[FadeOut(m) for m in sc.mobjects], run_time=run_time)


class BobScene(Scene):
    def setup(self):
        self.camera.background_color = BG

    def heading(self, text, kicker=None):
        t = Text(text, font_size=32, color=INK, weight="BOLD")
        t.to_corner(UL).shift(DOWN * 0.1)
        rule = Line(LEFT * 6.6, RIGHT * 6.6, color=DIM, stroke_width=1.5)
        rule.next_to(t, DOWN, buff=0.2).align_to(t, LEFT)
        g = VGroup(t, rule)
        self.play(FadeIn(t, shift=RIGHT * 0.3), Create(rule), run_time=0.7)
        if kicker:
            k = Text(kicker, font_size=19, color=DIM)
            if k.width > 13.0:
                k.scale_to_fit_width(13.0)
            k.next_to(rule, DOWN, buff=0.16).align_to(t, LEFT)
            g.add(k)
            self.play(FadeIn(k), run_time=0.4)
        return g

    def titlecard(self, number, title, subtitle):
        n = Text(number, font_size=26, color=C_BIT, weight="BOLD")
        t = Text(title, font_size=60, color=INK, weight="BOLD")
        s = Text(subtitle, font_size=26, color=DIM)
        if t.width > 12.5:
            t.scale_to_fit_width(12.5)
        if s.width > 12.5:
            s.scale_to_fit_width(12.5)
        g = VGroup(n, t, s).arrange(DOWN, buff=0.4)
        self.play(FadeIn(n), run_time=0.4)
        self.play(Write(t), run_time=1.1)
        self.play(FadeIn(s, shift=UP * 0.2), run_time=0.7)
        self.wait(1.6)
        self.play(FadeOut(g), run_time=0.6)

    def files_used(self, inputs, generated, verified):
        """Closing card: what this episode's topic is built from and checked by."""
        self.heading("Files", "what this part is written in, what is generated, and what proves it")
        cols = []
        for title, items, col in (("written by hand", inputs, C_RTL),
                                  ("generated", generated, C_PY),
                                  ("verified by", verified, C_BIT)):
            head = Text(title, font_size=21, color=col, weight="BOLD")
            cards = VGroup(*[filecard(p, r, col) for p, r in items])
            cards.arrange(DOWN, aligned_edge=LEFT, buff=0.18)
            g = VGroup(head, cards).arrange(DOWN, aligned_edge=LEFT, buff=0.28)
            cols.append(g)
        row = VGroup(*cols).arrange(RIGHT, buff=0.7, aligned_edge=UP)
        if row.width > 13.2:
            row.scale_to_fit_width(13.2)
        row.next_to(self.mobjects[1], DOWN, buff=0.55).set_x(0)
        for c in cols:
            self.play(FadeIn(c, shift=UP * 0.2), run_time=0.7)
        self.wait(2.4)
