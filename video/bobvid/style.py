"""Palette and diagram helpers shared by every chapter.

Adapted from the 2026-09 docs/manim prelude (git show 3ed3f83^:docs/manim/parts/prelude.py):
the same colour meanings, so a colour means the same thing in every chapter.

Frame: 14.22 x 8 units. The subtitle band is y < -3.0; content stays in y in [-2.9, 3.0]
under a heading at the top.
"""

from manim import *
import numpy as np

# ---------------------------------------------------------------- palette ----
BG    = "#11121a"
PANEL = "#1a1c27"
INK   = "#e8e8ea"
DIM   = "#8b93a7"
FAINT = "#3b4052"
C_PY  = "#7aa2f7"   # blue    - Python, tools, the device description
C_VPR = "#f7768e"   # red     - VPR, external tools, references
C_RTL = "#9ece6a"   # green   - hardware, Verilog, things on the die
C_BIT = "#e0af68"   # amber   - configuration bits, FASM, the bitstream
C_GRF = "#bb9af7"   # purple  - graphs, JTAG, protocol, FSMs
C_ERR = "#ff7a93"   # pink    - bugs, refusals, errors
C_CYN = "#7dcfff"   # cyan    - data moving, signals, the user clock

SANS = "Avenir Next"
MONO = "Menlo"

TOP_Y = 2.75        # first content line under a heading
BOT_Y = -2.85       # lowest content line above the subtitles


# ---------------------------------------------------------------- text -------
def txt(s, size=24, color=INK, weight=NORMAL, slant=NORMAL):
    return Text(s if s else " ", font=SANS, font_size=size, color=color,
                weight=weight, slant=slant)


def bold(s, size=24, color=INK):
    return txt(s, size, color, weight=BOLD)


def mono(s, size=20, color=INK):
    """One line of monospace text (Pango dislikes '', so blanks become ' ')."""
    return Text(s if s else " ", font=MONO, font_size=size, color=color)


def code_block(lines, size=18, color=INK, colors=None):
    """lines: str or (str, colour). Left-aligned monospace block."""
    g = VGroup()
    for l in lines:
        if isinstance(l, tuple):
            g.add(mono(l[0], size, l[1]))
        else:
            g.add(mono(l, size, color))
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.12)
    return g


def fit(m, w=None, h=None):
    if w is not None and m.width > w:
        m.scale_to_fit_width(w)
    if h is not None and m.height > h:
        m.scale_to_fit_height(h)
    return m


def panel(mob, color=DIM, pad=0.28, fill=0.06, radius=0.12):
    r = RoundedRectangle(width=mob.width + 2 * pad, height=mob.height + 2 * pad,
                         corner_radius=radius, color=color, stroke_width=2)
    r.set_fill(color, opacity=fill).move_to(mob.get_center())
    return VGroup(r, mob)


def chip(label, color, w=2.6, h=0.9, size=22, weight=NORMAL, mono_font=False, fill=0.14):
    box = RoundedRectangle(width=w, height=h, corner_radius=0.12,
                           color=color, stroke_width=2.6)
    box.set_fill(color, opacity=fill)
    if mono_font:
        t = mono(label, size)
    else:   # one Text per line, centred (a multi-line Text is left-aligned)
        t = VGroup(*[Text(l, font=SANS, font_size=size, color=INK, weight=weight)
                     for l in label.split("\n")]).arrange(DOWN, buff=0.08)
    fit(t, w - 0.25, h - 0.16)
    return VGroup(box, t.move_to(box.get_center()))


def tag(label, color, size=16):
    t = txt(label, size, color, weight=BOLD)
    r = RoundedRectangle(width=t.width + 0.3, height=t.height + 0.18, corner_radius=0.08,
                         color=color, stroke_width=1.5).set_fill(color, opacity=0.15)
    return VGroup(r.move_to(t), t)


def arrow(a, b, color=DIM, buff=0.1, sw=3, tip=0.2):
    return Arrow(a, b, buff=buff, color=color, stroke_width=sw,
                 max_tip_length_to_length_ratio=0.25, tip_length=tip)


def bullets(items, size=24, color=INK, buff=0.24, width=12.4, dot=C_BIT):
    """items: str or (str, colour). A left-aligned bullet list."""
    rows = VGroup()
    for it in items:
        s, c = it if isinstance(it, tuple) else (it, color)
        d = Dot(radius=0.05, color=dot)
        t = txt(s, size, c)
        fit(t, width - 0.4)
        rows.add(VGroup(d, t).arrange(RIGHT, buff=0.2, aligned_edge=UP))
        d.shift(DOWN * 0.11)
    rows.arrange(DOWN, aligned_edge=LEFT, buff=buff)
    return rows


def table(rows, col_w, size=17, head_color=C_BIT, row_h=0.42, colors=None, font=SANS):
    """rows[0] is the header. col_w: widths. colors: optional per-row text colour."""
    g = VGroup()
    y = 0
    for i, r in enumerate(rows):
        x = 0
        line = VGroup()
        for j, cell in enumerate(r):
            c = head_color if i == 0 else (colors[i] if colors and colors[i] else INK)
            t = Text(str(cell) if str(cell) else " ", font=font, font_size=size, color=c,
                     weight=BOLD if i == 0 else NORMAL)
            fit(t, col_w[j] - 0.15, row_h * 0.85)
            t.move_to([x + 0.08, y, 0], aligned_edge=LEFT)
            line.add(t)
            x += col_w[j]
        g.add(line)
        if i == 0:
            g.add(Line([0, y - row_h / 2, 0], [sum(col_w), y - row_h / 2, 0],
                       color=FAINT, stroke_width=1.5))
        y -= row_h
    return g


def mux_symbol(color=C_RTL, h=1.6, w=0.7):
    """Trapezoid multiplexer symbol, wide side left."""
    p = Polygon([-w / 2, h / 2, 0], [w / 2, h / 2 - 0.28, 0],
                [w / 2, -h / 2 + 0.28, 0], [-w / 2, -h / 2, 0],
                color=color, stroke_width=2.6)
    p.set_fill(color, opacity=0.14)
    return p


def bitcells(n, size=0.28, on=(), color=C_BIT, off_color=FAINT, buff=0.03):
    g = VGroup()
    for i in range(n):
        s = Square(size, color=off_color, stroke_width=1.4)
        if i in on:
            s.set_stroke(color).set_fill(color, opacity=0.85)
        g.add(s)
    g.arrange(RIGHT, buff=buff)
    return g


def bits_row(values, size=0.34, color=C_BIT, label_size=15):
    """A row of cells showing 0/1 digits."""
    g = VGroup()
    for v in values:
        s = Square(size, color=color if v else FAINT, stroke_width=1.4)
        s.set_fill(color, opacity=0.55 if v else 0.0)
        d = mono(str(v), label_size, INK if v else DIM).move_to(s)
        g.add(VGroup(s, d))
    g.arrange(RIGHT, buff=0.03)
    return g


def fieldbar(fields, total_w=11.5, h=0.55, size=15, min_w=0.36, show_ranges=True):
    """fields: [(label, nbits, colour)] -> one bar split to scale (with a minimum width),
    labels above and bit ranges below."""
    nbits = sum(f[1] for f in fields)
    ws = [max(total_w * n / nbits, min_w) for _, n, _ in fields]
    k = total_w / sum(ws)
    ws = [w * k for w in ws]
    bar, labs, rngs = VGroup(), VGroup(), VGroup()
    x, lo = -total_w / 2, 0
    for (label, n, col), w in zip(fields, ws):
        r = Rectangle(width=w, height=h, color=col, stroke_width=1.8)
        r.set_fill(col, opacity=0.3).move_to([x + w / 2, 0, 0])
        bar.add(r)
        t = txt(label, size, col)
        fit(t, max(w * 1.6, 0.5))
        t.next_to(r, UP, buff=0.1)
        labs.add(t)
        if show_ranges:
            rt = mono(f"{lo}" if n == 1 else f"{lo}..{lo + n - 1}", size - 3, DIM)
            fit(rt, max(w * 1.6, 0.5))
            rt.next_to(r, DOWN, buff=0.08)
            rngs.add(rt)
        x += w
        lo += n
    return VGroup(bar, labs, rngs)


def filecard(path, role, color):
    t = mono(path, 16, color)
    r = txt(role, 14, DIM)
    g = VGroup(t, r).arrange(DOWN, aligned_edge=LEFT, buff=0.06)
    box = RoundedRectangle(width=g.width + 0.3, height=g.height + 0.24, corner_radius=0.08,
                           color=color, stroke_width=1.5).set_fill(color, opacity=0.07)
    box.move_to(g)
    return VGroup(box, g)


def ref(text, size=15, color=C_VPR):
    """A citation chip: 'UG470 ch. 5' style."""
    return tag(text, color, size)


# ---------------------------------------------------------------- FSMs -------
def fsm(states, edges, pos, r=0.36, size=13, color=C_GRF, w=None, h=0.46):
    """A state diagram.
    states: [name], pos: {name: (x, y)}, edges: [(a, b, label, bend)] with bend in
    radians (0 straight). Returns (group, nodes {name: VGroup}, arrows {(a,b): mob}).
    Nodes are rounded boxes sized to their label (or width w)."""
    nodes, arrows = {}, {}
    g = VGroup()
    for s in states:
        t = txt(s, size, INK)
        bw = w if w else max(t.width + 0.3, 0.9)
        box = RoundedRectangle(width=bw, height=h, corner_radius=h / 2.2,
                               color=color, stroke_width=2).set_fill(color, opacity=0.12)
        fit(t, bw - 0.12)
        n = VGroup(box, t.move_to(box)).move_to([pos[s][0], pos[s][1], 0])
        nodes[s] = n
        g.add(n)
    for e in edges:
        a, b, lab = e[0], e[1], e[2]
        bend = e[3] if len(e) > 3 else 0
        if a == b:
            box = nodes[a][0]
            start = box.get_top() + LEFT * 0.15
            end = box.get_top() + RIGHT * 0.15
            ar = CurvedArrow(start, end, angle=-PI * 1.4, color=DIM, stroke_width=1.8,
                             tip_length=0.12)
        else:
            pa, pb = nodes[a][0].get_center(), nodes[b][0].get_center()
            d = pb - pa
            sa = _box_edge(nodes[a][0], d)
            sb = _box_edge(nodes[b][0], -d)
            if bend:
                ar = CurvedArrow(sa, sb, angle=bend, color=DIM, stroke_width=1.8,
                                 tip_length=0.12)
            else:
                ar = Arrow(sa, sb, buff=0.02, color=DIM, stroke_width=1.8,
                           max_tip_length_to_length_ratio=0.3, tip_length=0.13)
        lg = VGroup(ar)
        if lab:
            lt = mono(lab, 11, DIM)
            mpt = ar.point_from_proportion(0.5)
            lt.move_to(mpt).shift(_perp(ar) * 0.2)
            lg.add(lt)
        arrows[(a, b)] = lg
        g.add(lg)
    return g, nodes, arrows


def _box_edge(box, d):
    c = box.get_center()
    if np.linalg.norm(d) < 1e-6:
        return c
    hw, hh = box.width / 2, box.height / 2
    sx = hw / abs(d[0]) if abs(d[0]) > 1e-6 else 1e9
    sy = hh / abs(d[1]) if abs(d[1]) > 1e-6 else 1e9
    s = min(sx, sy)
    return c + d * s


def _perp(ar):
    a, b = ar.point_from_proportion(0.45), ar.point_from_proportion(0.55)
    d = b - a
    n = np.array([-d[1], d[0], 0])
    l = np.linalg.norm(n)
    return n / l if l > 1e-6 else UP


def highlight(node, color=C_BIT):
    """A glow box around an fsm node, to show the current state."""
    return SurroundingRectangle(node, color=color, buff=0.06, corner_radius=0.2,
                                stroke_width=4)


# ---------------------------------------------------------------- waves ------
def waveform(signals, t_w=0.5, row_h=0.62, x0=0.0, label_w=1.3, size=15, colors=None):
    """signals: [(name, values)] where values are 0/1 per half-step, or a string with
    '0','1','x' (unknown), '=' (bus, keep), 'b' (bus edge) characters.
    Returns VGroup(rows); each row is VGroup(label, trace)."""
    rows = VGroup()
    for i, (name, vals) in enumerate(signals):
        col = colors[i] if colors else C_CYN
        y = -i * row_h
        lab = mono(name, size, col)
        lab.move_to([x0 - 0.15, y, 0], aligned_edge=RIGHT)
        pts = []
        hi, lo = y + row_h * 0.28, y - row_h * 0.28
        trace = VGroup()
        if isinstance(vals, str) and any(c in vals for c in "=b"):
            # bus: two lines with crossings at 'b'
            for k, c in enumerate(vals):
                xa, xb = x0 + k * t_w, x0 + (k + 1) * t_w
                if c == "b":
                    trace.add(Line([xa, hi, 0], [xb, lo, 0], color=col, stroke_width=2),
                              Line([xa, lo, 0], [xb, hi, 0], color=col, stroke_width=2))
                else:
                    trace.add(Line([xa, hi, 0], [xb, hi, 0], color=col, stroke_width=2),
                              Line([xa, lo, 0], [xb, lo, 0], color=col, stroke_width=2))
        else:
            seq = [int(c) if str(c) in "01" else 0 for c in vals]
            for k, v in enumerate(seq):
                yy = hi if v else lo
                xa, xb = x0 + k * t_w, x0 + (k + 1) * t_w
                if k and seq[k - 1] != v:
                    trace.add(Line([xa, lo, 0], [xa, hi, 0], color=col, stroke_width=2.4))
                trace.add(Line([xa, yy, 0], [xb, yy, 0], color=col, stroke_width=2.4))
        rows.add(VGroup(lab, trace))
    return rows


# ---------------------------------------------------------------- the grid ---
def grid_view(F, cell=0.42, show_labels=False, gap=0.06):
    """The 14 x 12 guest device from facts: io ring, CLBs, BRAM and DSP columns.
    Returns (group, cells {(x, y): Rectangle})."""
    W, H = F["arch"]["grid_width"], F["arch"]["grid_height"]
    kinds = {(b["x"], b["y"]): b["type"] for b in F["blocks"]}
    spans = {(b["x"], b["y"]): b.get("h", 1) for b in F["blocks"]}
    colmap = {"clb": C_RTL, "io": C_CYN, "bram": C_PY, "dsp": C_VPR}
    g, cells = VGroup(), {}
    covered = set()
    for (x, y), k in kinds.items():
        if k in ("bram", "dsp"):
            for dy in range(spans[(x, y)]):
                covered.add((x, y + dy))
    for x in range(W):
        for y in range(H):
            k = kinds.get((x, y))
            if k is None:
                if (x, y) in covered:
                    continue
                r = Square(cell, color=FAINT, stroke_width=1)
                r.move_to([x * (cell + gap), y * (cell + gap), 0])
                g.add(r)
                continue
            col = colmap[k]
            hh = spans[(x, y)] if k in ("bram", "dsp") else 1
            r = Rectangle(width=cell, height=hh * cell + (hh - 1) * gap, color=col,
                          stroke_width=1.6).set_fill(col, opacity=0.28 if k != "io" else 0.12)
            r.move_to([x * (cell + gap), y * (cell + gap) + (hh - 1) * (cell + gap) / 2, 0])
            cells[(x, y)] = r
            g.add(r)
            if show_labels and k in ("bram", "dsp"):
                g.add(txt(k.upper(), 11, col).rotate(PI / 2).move_to(r))
    g.move_to(ORIGIN)
    return g, cells


def legend(items, size=15):
    g = VGroup()
    for label, col in items:
        s = Square(0.22, color=col, stroke_width=1.6).set_fill(col, opacity=0.3)
        g.add(VGroup(s, txt(label, size, INK)).arrange(RIGHT, buff=0.12))
    g.arrange(DOWN, aligned_edge=LEFT, buff=0.14)
    return g


def mid(a, b):
    return (np.array(a) + np.array(b)) / 2
