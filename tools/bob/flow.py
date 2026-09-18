#!/usr/bin/env python3
"""
flow.py - the guest flow as discrete, timed stages (Phase 0 of the studio work).

`cli.py`'s build() runs the same steps as one 89-line function whose only output is
printed prose. This module runs them as separate stages, each returning a record:
name, ok, seconds, the numbers the stage already computes, and any compiler
diagnostics with their source positions. That record is what a GUI, a --json flag or
a report can be built on.

It is deliberately additive: nothing here modifies cli.py, and M16's hw/ bundle is
untouched. `tests/test_flow.py` asserts that Flow and cli.build() write a
byte-identical .bit for every example, so the two cannot drift while both exist.

Stages:
  synth   tools/bob/equiv.py: yosys onto bob cells, then source == netlist ==
          golden netlist in iverilog over 300 random cycles. One stage because
          equiv.equiv() does both in one call; splitting it needs equiv.py, which
          belongs to the next milestone's tree.
  pnr     VPR on the committed rr graph (reusing a fresh committed result when the
          netlist and pins match it), or bob's own Python pack/place/route.
  fasm    the place-and-route result -> FASM features, legality-checked against
          device.json, with the clock fields applied.
  bits    features -> the configuration word, checked to round-trip back to FASM.
  model   tools/bob/model.py on those bits == the source trace, when the ports
          follow the sw/btn/led convention.
  write   the .bit container: chain + BRAM contents + META.

  Flow(...).run() -> Result, or Flow(...).run(on_stage=cb) to watch it happen.
"""

import hashlib
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "host"))

import bitstream as B  # noqa: E402
import bitgen  # noqa: E402
import chainbits  # noqa: E402
import fasm_from_vpr as FV  # noqa: E402
import vpr_run  # noqa: E402

CONVENTION = {"clk", "sw", "btn", "led"}
STAGES = ("synth", "pnr", "fasm", "bits", "model", "write")


class FlowError(Exception):
    """A stage refused the design. The message is for the user, not a traceback."""


# What a stage is allowed to fail with. The same set cli.py's main() catches: a tool
# that could not run (yosys, iverilog, Docker) surfaces as RuntimeError/OSError, and
# those are the user's problem to fix, not a bug to traceback on.
FAILURES = (FlowError, FV.FasmError, chainbits.ChainFileError, vpr_run.VprError,
            RuntimeError, OSError)


# --- diagnostics -------------------------------------------------------------
#
# yosys, iverilog and VPR all name a file and a line when they complain. Parsing
# them into one shape is what lets a GUI put a marker on the offending line
# instead of showing the user a log.

# yosys writes "at file.v:110.46-110.78." and iverilog "file.v:7: error: ...", so the
# position may carry a column, or a whole line.col-line.col span, before the message.
_POS = re.compile(r"(?P<file>[\w./+-]+\.s?vh?):(?P<line>\d+)"
                  r"(?:\.\d+(?:-\d+\.\d+)?)?(?::(?P<col>\d+))?[.:]?\s*"
                  r"(?P<sev>[Ee]rror|[Ww]arning|ERROR|WARNING)?\s*:?\s*(?P<text>.*)")
_YOSYS = re.compile(r"^(?P<sev>Warning|ERROR):\s*(?P<text>.*)$")
_VPR = re.compile(r"^\s*(?P<sev>Error|Warning)\s*\d*:\s*(?P<text>.*)$")


def _sev(word, default="info"):
    if not word:
        return default
    w = word.lower()
    return "error" if w.startswith("err") else "warning" if w.startswith("warn") else default


MAX_MESSAGES = 60

# yosys names its own wires and cells with a leading $ ($2, $auto$alumacc, $for_loop$1),
# and the bob cell library alone produces a warning per BRAM word. None of that is about
# the design someone just wrote, and a Messages panel that shows it buries the two lines
# that matter.
_NOISE = re.compile(r"\$(auto|for_loop|techmap|procdff|\d)|'\$|\\\$")


def _worth_showing(text):
    """Is this a diagnostic about the user's source, or tool bookkeeping?"""
    t = (text or "").strip()
    if len(t) <= 3 or _NOISE.search(t):
        return False
    return t[0].isalpha() or t[0] in "'\"`" 


def _order(msgs):
    """Errors first: they are what has to be fixed, and a warning list should never push
    them out of sight."""
    rank = {"error": 0, "warning": 1, "info": 2}
    return sorted(msgs, key=lambda m: rank.get(m["severity"], 3))


def messages(text, source=""):
    """Compiler output -> [{severity, file, line, text, source}], errors first.

    A GUI puts these on the line they name, so a fragment with a line number is worse
    than no message at all - it marks the wrong thing as wrong."""
    out, seen = [], set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _POS.search(line)
        if m:
            # iverilog puts the message after the position ("f.v:7: error: ..."); yosys
            # often puts it before ("Warning: wire ... in a block at f.v:110.46-110.78.").
            # Either way the person wants the line number, so take whichever side has text.
            text = (m.group("text") or "").strip()
            sev = m.group("sev")
            if not text:
                before = line[:m.start()].strip().rstrip("at").rstrip()
                head = _YOSYS.match(before) or _VPR.match(before)
                if head:
                    sev, text = head.group("sev"), head.group("text").strip()
                else:
                    text = before
                text = text.rstrip(",;:").strip()
        if m and text:
            rec = {"severity": _sev(sev, "warning"),
                   "file": m.group("file"), "line": int(m.group("line")),
                   "text": text, "source": source}
        else:
            m = _YOSYS.match(line) or _VPR.match(line)
            if not m:
                continue
            rec = {"severity": _sev(m.group("sev")), "file": None, "line": None,
                   "text": m.group("text").strip(), "source": source}
        if not _worth_showing(rec["text"]):
            continue
        key = (rec["file"], rec["line"], rec["text"])
        if key not in seen:
            seen.add(key)
            out.append(rec)
    # Errors first: they are what the person has to fix, and a long warning list should
    # never push them out of sight.
    out = _order(out)
    if len(out) > MAX_MESSAGES:
        rest = len(out) - MAX_MESSAGES
        out = out[:MAX_MESSAGES] + [{"severity": "info", "file": None, "line": None,
                                     "text": f"... and {rest} more", "source": source}]
    return out


def _rel(path):
    """Path relative to the repo when it is inside it, absolute when it is not."""
    ap = os.path.abspath(path)
    return os.path.relpath(ap, ROOT) if ap.startswith(ROOT + os.sep) else ap


def _log_messages(path, source):
    try:
        return messages(open(path, errors="replace").read(), source)
    except OSError:
        return []


# --- records -----------------------------------------------------------------


class Stage:
    """One step of the flow. `detail` is the line cli.py prints today."""

    def __init__(self, name):
        self.name = name
        self.ok = None
        self.seconds = 0.0
        self.stats = {}
        self.messages = []
        self.detail = ""
        self._t0 = None

    def start(self, flow=None):
        self._t0 = time.time()
        if flow is not None:
            flow._current = self
        return self

    def finish(self, ok, detail="", **stats):
        self.seconds = time.time() - self._t0 if self._t0 else 0.0
        self.ok = ok
        self.detail = detail
        self.stats.update(stats)
        return self

    def to_json(self):
        return {"name": self.name, "ok": self.ok, "seconds": round(self.seconds, 3),
                "stats": self.stats, "messages": self.messages, "detail": self.detail}


class Result:
    def __init__(self, flow):
        self.flow = flow
        self.stages = []
        self.ok = False
        self.bit = None
        self.word = None
        self.brams = None
        self.trace = None
        self.work = None
        self.error = None

    @property
    def seconds(self):
        return sum(s.seconds for s in self.stages)

    @property
    def messages(self):
        return [m for s in self.stages for m in s.messages]

    def to_json(self):
        return {"design": self.flow.name, "top": self.flow.top, "ok": self.ok,
                "seconds": round(self.seconds, 3), "bit": self.bit,
                "pnr": self.flow.pnr, "clock": self.flow.clock, "div": self.flow.div,
                "seed": self.flow.seed,
                "device": {"name": B.DEVICE["name"], "chain_w": B.CHAIN_W,
                           "nclb": B.NCLB, "frames": B.DEVICE["frames"]["count"]},
                "stages": [s.to_json() for s in self.stages],
                "error": self.error}


# --- the flow ----------------------------------------------------------------


class Flow:
    def __init__(self, files, top=None, pcf=None, out=None, clock="jtag", div=0,
                 seed=1, name=None, pnr="vpr"):
        self.files = list(files)
        self.top = top or os.path.splitext(os.path.basename(self.files[0]))[0]
        self.pcf = pcf
        self.out = out
        self.clock = clock
        self.div = div
        self.seed = seed
        self.pnr = pnr
        # A .pcf makes a separate result name, exactly as cli.build() derives it, so
        # a pin variant never overwrites the plain design's committed route.
        if not name and pcf:
            base = os.path.splitext(os.path.basename(pcf))[0]
            name = base if base.startswith(self.top) else f"{self.top}_{base}"
        self.name = name or self.top
        if self.name in vpr_run.VARIANTS and self.pcf is None:
            top_v, self.pcf = vpr_run.VARIANTS[self.name]
            if top_v != self.top:
                raise FlowError(f"{self.name} is a committed variant of {top_v}, not {self.top}")
        if clock not in B.CLOCK_MODES:
            raise FlowError(f"clock is one of {sorted(B.CLOCK_MODES)}")
        if pnr not in ("vpr", "python"):
            raise FlowError("pnr is vpr or python")
        self._mod = None
        self._pnr_stats = None
        self._features = None
        self._current = None        # the stage in progress, so a failure keeps its record

    # -- stages ---------------------------------------------------------------

    def synth(self):
        """yosys onto bob cells, then source == netlist == golden over 300 cycles."""
        import equiv
        from synth import summary
        st = Stage("synth").start(self)
        yosys_log = os.path.join(ROOT, "build", "synth", self.top, f"{self.top}.log")
        try:
            ok, lines, mod = equiv.equiv(self.files, self.top)
        except FAILURES as e:
            # The usual failure is a source error, and yosys and iverilog both name the
            # file and line. Parse them before re-raising, or the Messages panel stays
            # empty for exactly the case it exists to serve.
            # Both tools may have something to say; sort the union so the errors lead.
            st.messages = _order(_log_messages(yosys_log, "yosys")
                                 + messages(str(e), "iverilog" if "iverilog" in str(e) else "yosys"))
            st.finish(False, str(e).splitlines()[0] if str(e) else type(e).__name__)
            raise
        self._mod = mod
        st.messages = _log_messages(yosys_log, "yosys")
        cells = summary(mod)
        if not ok:
            st.messages += messages("\n".join(lines), "iverilog")
            st.finish(False, f"{self.top}: synthesised netlist differs from the source", cells=cells)
            raise FlowError(f"{self.top}: synthesised netlist differs from the source:\n"
                            + "\n".join(lines))
        # Ports carry their width and direction, because a pin file names one bit at a
        # time: a 3-bit `a` is a[0], a[1], a[2] on the wire, and a 1-bit one is just `a`.
        ports = [{"name": n, "width": len(p["bits"]), "dir": p.get("direction", "input")}
                 for n, p in sorted(mod["ports"].items())]
        return st.finish(True, f"{self.top}: {cells}; source == netlist == golden, 300 random cycles",
                         cells=cells, equiv=True, equiv_cycles=300,
                         ports=ports, port_names=sorted(mod["ports"]))

    def place_route(self):
        """VPR on the committed rr graph, or bob's own pack/place/route."""
        st = Stage("pnr").start(self)
        if self.pnr == "python":
            from pnr import pack as pnr_pack, place as pnr_place, route as pnr_route, run as pnr_run
            try:
                work, stats = pnr_run.run(self.top, self.seed, self.pcf, self.name)
            except (vpr_run.VprError, pnr_pack.PackError, pnr_place.PlaceError,
                    pnr_route.RouteError) as e:
                st.finish(False, f"python pnr: {e}")
                raise FlowError(f"python pnr: {e}")
            self._pnr_stats = stats
            secs = stats["pack_s"] + stats["place_s"] + stats["route_s"]
            return st.finish(True,
                             f"python: {stats['clusters']['clb']} CLBs, wirelength {stats['wirelength']}, "
                             f"{stats['iterations']} routing iteration(s), {secs:.2f} s "
                             f"-> {os.path.relpath(work, ROOT)}",
                             engine="python", work=os.path.relpath(work, ROOT),
                             clbs=stats["clusters"]["clb"], wirelength=stats["wirelength"],
                             iterations=stats["iterations"], pack_s=stats["pack_s"],
                             place_s=stats["place_s"], route_s=stats["route_s"],
                             seed=stats["seed"])

        stamp = vpr_run.read_stamp(self.name)
        want_pcf = os.path.relpath(os.path.abspath(self.pcf), ROOT) if self.pcf else "-"
        same_pins = stamp is not None and stamp.get("pcf", "-") == want_pcf
        if same_pins and vpr_run.stale(self.name) is None:
            work = os.path.join(vpr_run.RESULTS, self.name)
            return st.finish(True,
                             f"reused committed {os.path.relpath(work, ROOT)} "
                             "(routed from this netlist and arch)",
                             engine="vpr", reused=True, work=os.path.relpath(work, ROOT),
                             wirelength=stamp.get("wirelength"),
                             result_sha=stamp.get("result_sha"))
        try:
            work = vpr_run.run(self.top, self.seed, pcf=self.pcf, name=self.name)
        except vpr_run.VprError as e:
            st.messages = _log_messages(os.path.join(ROOT, "build", "vpr", self.name, "vpr.log"), "vpr")
            st.finish(False, str(e))
            raise FlowError(str(e))
        s = vpr_run.summary(work, self.name)
        st.messages = _log_messages(os.path.join(work, "vpr.log"), "vpr")
        return st.finish(True,
                         f"routed in Docker: wirelength {s['wirelength']}, result {s['result_sha']} "
                         f"-> {os.path.relpath(work, ROOT)}",
                         engine="vpr", reused=False, work=os.path.relpath(work, ROOT),
                         wirelength=s["wirelength"], result_sha=s["result_sha"])

    def fasm(self, work):
        """result -> FASM features, legality-checked, with the clock fields applied."""
        st = Stage("fasm").start(self)
        bs, contents, text = FV.build(self.name, work)
        F = bitgen.parse_fasm(text)
        # The clock fields are a build option, not a routing result: drop whatever the
        # result carried and set exactly what was asked for.
        F.pop("ctrl.clk_mode", None)
        F.pop("ctrl.clk_div", None)
        if B.CLOCK_MODES[self.clock]:
            F["ctrl.clk_mode"] = B.CLOCK_MODES[self.clock]
        if self.div:
            F["ctrl.clk_div"] = self.div
        self._features = F
        used = sorted(b for b, w in contents.items() if any(w))
        return st.finish(True, f"{len(F)} features, legal against device.json",
                         features=len(F), bram_used=used), bs, contents

    def bits(self):
        """features -> the configuration word, checked to round-trip back to FASM."""
        st = Stage("bits").start(self)
        word = bitgen.word_from_features(self._features)
        trip = bitgen.word_from_features(bitgen.features_from_word(word)) == word
        detail = f"{B.CHAIN_W}-bit chain; bits -> FASM -> bits identical: {trip}"
        if self.clock == "run":
            hz = 125e6 / 2 ** (self.div + B.DIV_MIN_SHIFT)
            detail += (f"; free-running 125 MHz / 2^{self.div + B.DIV_MIN_SHIFT} = {hz:.4g} Hz "
                       f"(one user clock every {1 / hz:.3g} s)")
        # finish with the real verdict before raising, or a failed build would show
        # this stage green in the record the page reads.
        st.finish(trip, detail, chain_w=B.CHAIN_W, roundtrip=trip,
                  clock=self.clock, div=self.div,
                  hz=(125e6 / 2 ** (self.div + B.DIV_MIN_SHIFT)) if self.clock == "run" else None)
        if not trip:
            raise FlowError("the configuration word does not survive a FASM round trip")
        return st, word

    def model(self, bs, contents, work):
        """model.py on these bits == the source trace (board-convention designs only)."""
        st = Stage("model").start(self)
        if not set(self._mod["ports"]) <= CONVENTION:
            return st.finish(True, "skipped: ports outside the sw/btn/led convention",
                             skipped=True), None
        bad, n, tr = FV.check_model(self.name, bs, contents, work, self.top)
        if bad:
            st.finish(False, f"differs from the source trace in {len(bad)} of {2 * n} samples",
                      samples=2 * n, bad=len(bad))
            raise FlowError(f"model.py differs from the source trace in {len(bad)} of {2 * n} samples")
        return st.finish(True, f"{2 * n}/{2 * n} samples == source trace",
                         samples=2 * n, bad=0), tr

    def write(self, word, contents, work):
        """The .bit container. META is byte-for-byte what cli.build() writes."""
        st = Stage("write").start(self)
        out = self.out or os.path.join(ROOT, "build", "bit", f"{self.name}.bit")
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        stampd = vpr_run.read_stamp(self.name) if work.startswith(vpr_run.RESULTS) else {}
        meta = {"design": self.name, "top": self.top,
                "sources": [os.path.relpath(os.path.abspath(f), ROOT) for f in self.files],
                "source_sha256": hashlib.sha256(
                    b"".join(open(f, "rb").read() for f in self.files)).hexdigest(),
                "pcf": os.path.relpath(os.path.abspath(self.pcf), ROOT) if self.pcf else None,
                "pnr": self.pnr,
                "vpr_result": (None if self.pnr == "python" else
                               stampd.get("result_sha") or vpr_run.summary(work, self.name)["result_sha"]),
                "pnr_seed": self._pnr_stats["seed"] if self._pnr_stats else None,
                "clock": self.clock, "div": self.div}
        bitgen.write_bit(out, word, contents, meta)
        rel = _rel(out)
        used = sorted(b for b, w in contents.items() if any(w))
        return st.finish(True, f"{rel}: {B.CHAIN_W}-bit chain"
                         + (f", BRAM {used}" if used else ""),
                         path=rel, bram=used, meta=meta), out

    # -- the whole thing ------------------------------------------------------

    def run(self, on_stage=None):
        """Every stage in order. on_stage(stage) fires as each one finishes."""
        res = Result(self)

        def done(st):
            res.stages.append(st)
            if on_stage:
                on_stage(st)
            return st

        try:
            done(self.synth())
            st = done(self.place_route())
            work = os.path.join(ROOT, st.stats["work"])
            res.work = work
            st, bs, contents = self.fasm(work)
            done(st)
            st, word = self.bits()
            done(st)
            st, tr = self.model(bs, contents, work)
            done(st)
            st, out = self.write(word, contents, work)
            done(st)
            res.ok, res.bit, res.word, res.brams, res.trace = True, out, word, contents, tr
        except FAILURES as e:
            res.error = str(e)
            # The stage that was running owns the failure: it already carries the
            # timing and whatever diagnostics it managed to parse. Only invent a record
            # if nothing had started - a bad option, a file that is not there.
            if not (res.stages and res.stages[-1].ok is False):
                st = self._current
                if st is not None and st not in res.stages:
                    if st.ok is None:
                        st.finish(False, str(e).splitlines()[0] if str(e) else type(e).__name__)
                    done(st)
                else:
                    reached = {x.name for x in res.stages}
                    nxt = next((n for n in STAGES if n not in reached), "flow")
                    done(Stage(nxt).start(self).finish(False, str(e)))
        return res


def build(files, on_stage=None, **kw):
    """Convenience: run the flow and return its Result."""
    return Flow(files, **kw).run(on_stage=on_stage)
