"""BobScene: the base class of every chapter.

    with self.narrate("First sentence. Second sentence."):
        self.play(...)            # animations that go with the words

The block's audio starts when the block starts; the subtitle shows the sentence the voice
is on; when the block ends the scene waits for the voice to finish. Every caption is
recorded, and tear_down writes script/chNN.md (the narration) and script/chNN.srt.
"""

import json
import os
import textwrap
from contextlib import contextmanager

from manim import *

from . import voice
from .style import *

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SCRIPT_DIR = os.path.join(ROOT, "script")

_FACTS = None


def facts():
    global _FACTS
    if _FACTS is None:
        with open(os.path.join(ROOT, "data", "facts.json")) as fh:
            _FACTS = json.load(fh)
    return _FACTS


def _balanced(text, width_chars):
    """Wrap into the fewest lines that fit, with the lines as even as possible."""
    n = len(textwrap.wrap(text, width_chars))
    if n <= 1:
        return [text]
    for w in range(len(text) // n, width_chars + 1):
        lines = textwrap.wrap(text, w)
        if len(lines) <= n:
            return lines
    return textwrap.wrap(text, width_chars)


def _caption(text, width_chars=78, size=22):
    lines = _balanced(text, width_chars)
    if len(lines) > 2:   # three lines: smaller type rather than cover the picture
        lines = _balanced(text, int(width_chars * 1.3))
        size = 18
    t = VGroup(*[Text(l, font=SANS, font_size=size, color=INK) for l in lines])
    t.arrange(DOWN, buff=0.1)
    fit(t, 13.2, 0.95)
    box = RoundedRectangle(width=t.width + 0.5, height=t.height + 0.24, corner_radius=0.1,
                           stroke_width=0).set_fill("#000000", opacity=0.66)
    box.move_to(t)
    g = VGroup(box, t)
    g.move_to([0, -3.5, 0])
    g.set_z_index(100)   # the whole family: manim sorts by z_index, and a child left at 0
    return g             # counts as static and is baked into the background (a ghost)


def _srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class BobScene(Scene):
    CH = "00"
    TITLE = "Title"
    SUBTITLE = ""

    def setup(self):
        self.camera.background_color = BG
        self.F = facts()
        self.captions = []           # (start, end, text)
        self.passages = []           # narration text, for the script
        self._heading = None

    # ------------------------------------------------------------ narration --
    def now(self):
        return self.renderer.time

    @contextmanager
    def narrate(self, text, min_time=0.0):
        wav, total, timing = voice.block(text)
        t0 = self.now()
        self.add_sound(wav)
        caps = [(_caption(s), a, b) for s, a, b in timing]
        # Every caption stays in the holder for the whole block and only its opacity
        # changes: manim takes the list of moving mobjects once per play(), so a caption
        # swapped in or out mid-play would be drawn from that stale list (a ghost).
        holder = VGroup(*[c for c, _, _ in caps])
        holder.set_z_index(100)
        state = {"i": None}
        scene = self

        def show(cap, on):
            box, lines = cap
            box.set_fill(opacity=0.66 if on else 0.0)
            lines.set_opacity(1.0 if on else 0.0)

        def upd(m, dt):
            t = scene.now() - t0
            i = -1
            for k, (_, a, b) in enumerate(caps):
                end = caps[k + 1][1] if k + 1 < len(caps) else b + voice.TAIL
                if a - 0.05 <= t < end:
                    i = k
                    break
            if i != state["i"]:
                for k, (c, _, _) in enumerate(caps):
                    show(c, k == i)
                state["i"] = i

        upd(holder, 0)
        holder.add_updater(upd)
        self.add(holder)
        for s, a, b in timing:
            self.captions.append((t0 + a, t0 + b, s))
        self.passages.append(voice.shown(" ".join(text.split())))
        try:
            yield
        finally:
            left = t0 + max(total, min_time) - self.now()
            if left > 0.02:
                self.wait(left)
            holder.clear_updaters()
            self.remove(holder)

    def pause(self, t=0.6):
        self.wait(t)

    # ------------------------------------------------------------ layout -----
    def heading(self, text, kicker=None, color=INK):
        t = Text(text, font=SANS, font_size=34, color=color, weight=BOLD)
        t.to_corner(UL, buff=0.45)
        rule = Line(LEFT * 6.65, RIGHT * 6.65, color=FAINT, stroke_width=1.5)
        rule.next_to(t, DOWN, buff=0.14).set_x(0)
        chn = Text(f"{self.CH}  {self.TITLE}", font=SANS, font_size=15, color=DIM)
        chn.to_corner(UR, buff=0.5).align_to(t, DOWN)
        g = VGroup(t, rule, chn)
        anims = [FadeIn(t, shift=RIGHT * 0.25), Create(rule), FadeIn(chn)]
        if kicker:
            k = Text(kicker, font=SANS, font_size=19, color=DIM)
            fit(k, 13.0)
            k.next_to(rule, DOWN, buff=0.12).align_to(t, LEFT)
            g.add(k)
            anims.append(FadeIn(k))
        if self._heading is not None:
            self.play(FadeOut(self._heading), run_time=0.3)
        self.play(*anims, run_time=0.6)
        self._heading = g
        return g

    def wipe(self, keep_heading=False, run_time=0.5):
        keep = {id(self._heading)} if keep_heading and self._heading is not None else set()
        mobs = [m for m in self.mobjects
                if id(m) not in keep and getattr(m, "z_index", 0) < 100]
        if mobs:
            self.play(*[FadeOut(m) for m in mobs], run_time=run_time)
        if not keep_heading:
            self._heading = None

    def content_top(self):
        if self._heading is not None:
            return self._heading.get_bottom()[1] - 0.25
        return 3.3

    # ------------------------------------------------------------ cards ------
    def title_card(self, narration):
        n = Text(f"CHAPTER {self.CH}", font=SANS, font_size=22, color=C_BIT, weight=BOLD)
        t = Text(self.TITLE, font=SANS, font_size=58, color=INK, weight=BOLD)
        s = Text(self.SUBTITLE, font=SANS, font_size=24, color=DIM)
        fit(t, 12.5)
        fit(s, 12.5)
        g = VGroup(n, t, s).arrange(DOWN, buff=0.35).shift(UP * 0.3)
        brand = Text("bob  ·  an FPGA inside an FPGA  ·  M26", font=SANS, font_size=16,
                     color=FAINT).to_edge(DOWN, buff=1.4)
        with self.narrate(narration):
            self.play(FadeIn(n), run_time=0.4)
            self.play(Write(t), run_time=1.0)
            self.play(FadeIn(s, shift=UP * 0.2), FadeIn(brand), run_time=0.6)
        self.play(FadeOut(VGroup(g, brand)), run_time=0.5)

    def files_card(self, narration, written, generated, proven):
        self.heading("Where this lives", "written by hand · generated · what proves it")
        cols = []
        for title, items, col in (("written by hand", written, C_RTL),
                                  ("generated", generated, C_PY),
                                  ("proven by", proven, C_BIT)):
            head = txt(title, 20, col, weight=BOLD)
            cards = VGroup(*[filecard(p, r, col) for p, r in items])
            cards.arrange(DOWN, aligned_edge=LEFT, buff=0.16)
            cols.append(VGroup(head, cards).arrange(DOWN, aligned_edge=LEFT, buff=0.22))
        row = VGroup(*cols).arrange(RIGHT, buff=0.55, aligned_edge=UP)
        fit(row, 13.2, 5.2)
        row.next_to(self._heading, DOWN, buff=0.4).set_x(0)
        with self.narrate(narration):
            for c in cols:
                self.play(FadeIn(c, shift=UP * 0.15), run_time=0.6)
        self.pause(0.8)
        self.wipe()

    def refs_card(self, narration, refs):
        """refs: [(short, long)]."""
        self.heading("Sources", "what this chapter follows, and where it diverges")
        rows = VGroup()
        for short, long in refs:
            rows.add(VGroup(ref(short, 15), txt(long, 18, INK)).arrange(RIGHT, buff=0.3))
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.2)
        fit(rows, 13.0, 5.4)
        rows.next_to(self._heading, DOWN, buff=0.45).to_edge(LEFT, buff=0.7)
        with self.narrate(narration):
            self.play(LaggedStart(*[FadeIn(r, shift=RIGHT * 0.2) for r in rows],
                                  lag_ratio=0.2), run_time=1.5)
        self.pause(0.6)

    # ------------------------------------------------------------ output -----
    def tear_down(self):
        super().tear_down()
        os.makedirs(SCRIPT_DIR, exist_ok=True)
        base = os.path.join(SCRIPT_DIR, f"ch{self.CH}")
        with open(base + ".srt", "w") as fh:
            for i, (a, b, s) in enumerate(self.captions, 1):
                fh.write(f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{s}\n\n")
        with open(base + ".md", "w") as fh:
            fh.write(f"# Chapter {self.CH}: {self.TITLE}\n\n*{self.SUBTITLE}*\n\n")
            fh.write(f"Running time {self.now() / 60:.1f} min. Generated by the render "
                     f"of `scenes/ch{self.CH}_*.py`; edit the scene, not this file.\n\n")
            for p in self.passages:
                fh.write(p + "\n\n")
