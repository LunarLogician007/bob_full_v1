#!/usr/bin/env python3
"""
studio.py - the bob studio backend: an EDA tool for the bob FPGA, over HTTP.

  software/host/studio.py [--port 8765] [--probe usb|fake] [--no-browser]

Vivado's shape, mapped onto the flow this project already has. Nothing here
reimplements a stage; every route drives software/bob/flow.py (synthesis and its
equivalence check, place and route, FASM, bitgen, the model check) or
software/host/cfgplane.py (program, readback), and reports what they return.

  GET  /                        the page (studio.html, built by software/studio/build.py)
  GET  /api/device              the device: grid, blocks, columns, capacity, frames
  GET  /api/examples            the example designs, as starting projects
  GET  /api/source?path=        one source file, for the editor
  POST /api/save                write the editor back to a file inside the repo
  GET  /api/browse              the designs you can open: work/, work/examples/, and any .proj
  GET  /api/bits                the bitstreams in build/bit/, newest first
  POST /api/new                 scaffold work/<name>/<name>.v from a template
  POST /api/build               start a build -> {"job": id}
  GET  /api/events/<job>        Server-Sent Events: one per stage as it finishes
  GET  /api/job/<job>           the finished result, as flow.Result.to_json()
  GET  /api/placement/<name>    where the design landed, and its routed nets
  GET  /api/target              the open probe, or none
  POST /api/target              open one: {"kind": "usb" | "fake"}
  POST /api/program             load a .bit: {"bit": path, "mode": frames|chain, "partial": bool}
  GET  /api/board               IDCODE, STAT, DONE, LEDs, switches
  GET  /api/pins                the pad map: board names, free pads, which are wired where
  POST /api/pcf                 write a .pcf from a port -> pin assignment (into build/)
  POST /api/readback            read the fabric back and compare it with a .bit
  POST /api/capture             CAPTURE every CLB register
  POST /api/partial             reconfigure the running design, changed frames only
  GET  /api/fasm                a .bit as FASM, with its frame map

Projects and block designs (M18; software/bob/project.py, software/bob/bd.py):
  GET  /api/project             the open project (files, top, settings, its modules) or null
  POST /api/project/new         {location, name}: make <location>/<name>/<name>.bobproj, open it
  POST /api/project/open        {path}: a .bobproj, or the folder holding one
  POST /api/project/close
  POST /api/project/add         {path, copy}: a .v/.sv/.vh or .pcf into the project
  POST /api/project/create      {name}: a new src/<name>.v from the template
  POST /api/project/remove      {rel}: take a file out of the project (it stays on disk)
  POST /api/project/top         {module}
  POST /api/project/pcf         {rel|null}: the active pin file
  POST /api/project/settings    {clock, div, seed, pnr, hz}
  POST /api/project/clock       {mhz | period_ns}: constrs/<name>.sdc with create_clock (M20)
  GET  /api/recent              recently opened projects
  GET  /api/fs?path=            one folder's subfolders, projects and sources (New/Open dialogs)
  GET  /api/bd?rel=             a block design;  POST /api/bd {rel, bd} saves it
  POST /api/bd/new              {name}: an empty bd/<name>.bd
  POST /api/bd/check            {bd}: errors and warnings, each at an endpoint
  POST /api/bd/generate         {rel, top}: write the HDL wrapper (+ .pcf), add it to the project
  GET  /api/bd/palette          IP cores, the project's modules, the board's ports
  GET  /api/ports?kind=&type=&params=   a block's ports at these parameters

The waveform viewer (M19; software/host/padwave.py), a logic analyser on the pads over JTAG:
  GET  /api/wave/signals        every pad as a signal, named after the programmed design's ports
  POST /api/wave/capture        {mode: step|live, depth, sel, trigger, pre, stimulus, timeout}
  GET  /api/wave/vcd            the last capture as a .vcd file

Stdlib only: http.server and SSE, so the project gains no dependency. Builds write
where the CLI writes them, under build/, and nothing here ever regenerates the
device or touches hw/.
"""

import argparse
import json
import glob
import mimetypes
import os
import re
import queue
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))

import bd as BD  # noqa: E402
import bitstream as B  # noqa: E402
import fakeboard  # noqa: E402
import fasm_from_vpr as FV  # noqa: E402
import flow  # noqa: E402
import project as P  # noqa: E402
import vpr_run  # noqa: E402
import padwave as wave  # noqa: E402

PAGE = os.path.join(ROOT, "software", "studio", "studio.html")
EXAMPLES = os.path.join(ROOT, "work", "examples")


# --- jobs --------------------------------------------------------------------


class Job:
    """One build, on its own thread, with a queue the SSE route drains."""

    def __init__(self, spec):
        self.id = uuid.uuid4().hex[:12]
        self.started = time.time()
        self.spec = spec
        self.events = queue.Queue()
        self.result = None
        self.error = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _emit(self, kind, **body):
        self.events.put({"event": kind, **body})

    def _run(self):
        try:
            spec = dict(self.spec)
            record = spec.pop("record", None)
            f = flow.Flow(**spec)
            self._emit("start", design=f.name, top=f.top, stages=list(flow.STAGES))
            res = f.run(on_stage=lambda st: self._emit("stage", **st.to_json()))
            self.result = res.to_json()
            if record:                                # a project keeps its last build record
                with open(record, "w") as fh:
                    json.dump(self.result, fh, indent=2)
            self.result["placement"] = placement(f.name, res.work) if res.ok else None
            self._emit("done", **self.result)
        except Exception as e:                        # a bug here must reach the page
            self.error = f"{type(e).__name__}: {e}"
            traceback.print_exc()
            self._emit("failed", error=self.error)
        finally:
            self.done.set()
            self.events.put(None)

    def start(self):
        self.thread.start()
        return self


JOBS = {}
JOBS_LOCK = threading.Lock()
MAX_JOBS = 40                        # a long session should not hold every build it ran


def _remember(job):
    with JOBS_LOCK:
        JOBS[job.id] = job
        if len(JOBS) > MAX_JOBS:
            for jid in [k for k, v in sorted(JOBS.items(), key=lambda kv: kv[1].started)
                        if v.done.is_set()][:len(JOBS) - MAX_JOBS]:
                JOBS.pop(jid, None)


# --- device and results ------------------------------------------------------


def device():
    """Everything the Device view needs to draw this fabric, from device.json."""
    d = B.DEVICE
    used = {}
    for b in d["blocks"]:
        used[b["type"]] = used.get(b["type"], 0) + 1
    return {"name": d["name"], "lut_k": d["lut_k"],
            "grid": {"w": d["arch"]["grid_width"], "h": d["arch"]["grid_height"]},
            "chan_width": d["arch"]["chan_width"],
            "columns": d["arch"]["columns"],
            "blocks": [{"name": b["name"], "type": b["type"], "x": b["x"], "y": b["y"]}
                       for b in d["blocks"]],
            "capacity": used,
            "chain_w": B.CHAIN_W,
            "frames": d["frames"]["count"],
            "muxes": len(d["rr"]["muxes"]),
            "pads": d["pads"]["count"],
            "clock": d["clock"]}


BLOCK_AT = {(b["x"], b["y"]): b for b in B.DEVICE["blocks"]}


def placement(name, work):
    """Where each netlist block landed, and the routed nets, for the Device view."""
    if not work or not os.path.isdir(work):
        return None
    out = {"blocks": [], "nets": [], "wirelength": None}
    place = os.path.join(work, f"{name}.place")
    if os.path.exists(place):
        for blk, (x, y) in sorted(FV.read_place(place).items()):
            site = BLOCK_AT.get((x, y))
            out["blocks"].append({"name": blk, "x": x, "y": y,
                                  "type": site["type"] if site else "?",
                                  "site": site["name"] if site else None})
    route = os.path.join(work, f"{name}.route")
    if os.path.exists(route):
        nodes = {n[0]: n for n in B.DEVICE["rr"]["nodes"]}
        span = set()
        for net, branches in FV.read_route(route).items():
            ids = [nid for br in branches for nid, _kind in br]
            pts = []
            for nid in ids:
                n = nodes.get(nid)
                if n:
                    pts.append({"id": nid, "kind": n[1], "x0": n[2], "y0": n[3],
                                "x1": n[4], "y1": n[5]})
                    if n[1] in ("CHANX", "CHANY"):
                        span.add(nid)
            out["nets"].append({"name": net, "nodes": pts})
        out["wirelength"] = len(span)
    return out


SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")
DESIGNS = os.path.join(ROOT, "work")
EDITABLE = (".v", ".sv", ".vh", ".pcf", ".sdc", ".proj", ".bobproj", ".bd")

TEMPLATE = """// {name}.v - a bob design.
//
// The default pin convention is sw[1:0] -> SW1..0, btn[3:0] -> BTN3..0,
// led[2:0] -> LD2..0. Use the Pin Planner for anything else; it writes a .pcf
// and the next build picks it up.
//
// One clock only, no asynchronous resets, no latches: the fabric has one user
// clock and every flip-flop is enabled by it.
module {name} (
    input  wire       clk,
    input  wire [1:0] sw,
    input  wire [3:0] btn,
    output wire [2:0] led
);

    reg [2:0] q = 3'd0;

    always @(posedge clk)
        q <= btn[0] ? 3'd0 : q + {{2'd0, sw[0]}};

    assign led = q;

endmodule
"""


def browse():
    """Everything openable, newest first within each group. work/ is where your own
    work goes; work/examples/ ships with the project."""
    out = []
    for root, label in ((DESIGNS, "design"), (EXAMPLES, "example")):
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, names in os.walk(root):
            if os.path.basename(dirpath).startswith("."):
                continue
            # work/examples/ is walked as its own group, not as part of work/
            if label == "design" and os.path.commonpath([dirpath, EXAMPLES]) == EXAMPLES:
                continue
            for n in sorted(names):
                if not n.endswith(EDITABLE):
                    continue
                full = os.path.join(dirpath, n)
                rel = os.path.relpath(full, ROOT)
                out.append({"path": rel, "name": n, "kind": label,
                            "type": os.path.splitext(n)[1].lstrip("."),
                            "lines": sum(1 for _ in open(full, errors="replace")),
                            "mtime": os.path.getmtime(full)})
    return {"files": out, "designs_dir": os.path.relpath(DESIGNS, ROOT)}


def save_source(rel, text):
    """Write the editor back. Inside the repo, and only file types the flow reads -
    the studio is a tool for this project, not a general file manager."""
    ap = _inside(rel)
    if ap is None:
        raise ValueError("path is outside the repo and the open project")
    if not ap.endswith(EDITABLE):
        raise ValueError(f"only {', '.join(EDITABLE)} files can be saved")
    proj = PROJECT.get()
    is_proj = proj is not None and ap == os.path.realpath(proj.path)
    if is_proj:
        try:                                   # the open project must stay readable
            json.loads(text)
        except ValueError as e:
            raise ValueError(f"not saved: the project file must be JSON ({e})")
    os.makedirs(os.path.dirname(ap), exist_ok=True)
    with open(ap, "w") as fh:
        fh.write(text)
    if is_proj:
        with PROJECT.lock:
            PROJECT.set(P.Project.open(ap))
    return _show(ap)


def _show(ap):
    """A path as the page shows it: repo-relative inside the repo, absolute elsewhere."""
    real = os.path.realpath(ap)
    return os.path.relpath(real, REAL_ROOT) if _under(real, REAL_ROOT) else ap


def new_design(name):
    """work/<name>/<name>.v from the template. -> its repo-relative path.

    A name that is not already a plain name is refused, not quietly rewritten: asking
    for "../../etc/x" and silently getting work/x/x.v is worse than an error."""
    name = str(name).strip()
    if not name or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name):
        raise ValueError("a design name starts with a letter and holds letters, digits, "
                         "_ or - (no slashes, no dots)")
    rel = os.path.join("work", name, f"{name}.v")
    if _inside(rel) is None:
        raise ValueError("refusing to write outside the repo")
    if os.path.exists(os.path.join(ROOT, rel)):
        raise ValueError(f"{rel} already exists")
    os.makedirs(os.path.dirname(os.path.join(ROOT, rel)), exist_ok=True)
    open(os.path.join(ROOT, rel), "w").write(TEMPLATE.format(name=name))
    return rel


def bitstreams():
    """Everything in build/bit/, newest first. A bitstream built in an earlier session or
    from the command line is just as loadable as one built in this tab."""
    import bitgen
    out = []
    found = glob.glob(os.path.join(ROOT, "build", "bit", "*.bit"))
    proj = PROJECT.get()
    if proj:
        found += glob.glob(os.path.join(proj.dir, "build", "*.bit"))
    for f in sorted(found):
        rel = os.path.relpath(f, ROOT) if f.startswith(ROOT + os.sep) else f
        rec = {"path": rel, "name": os.path.basename(f)[:-4], "mtime": os.path.getmtime(f)}
        try:
            c = bitgen.read_bit(f)
            rec.update(top=c["meta"].get("top"), design=c["meta"].get("design"),
                       sources=c["meta"].get("sources"), clock=c["meta"].get("clock"),
                       pcf=c["meta"].get("pcf"), crc=f"0x{c['crc']:08X}", ok=True)
        except Exception as e:
            rec.update(ok=False, error=str(e))
        out.append(rec)
    out.sort(key=lambda r: -r["mtime"])
    return out


def examples():
    """One folder per example under work/examples/<name>/<name>.v, the same shape a
    design of your own has."""
    out = []
    if not os.path.isdir(EXAMPLES):
        return out
    for name in sorted(os.listdir(EXAMPLES)):
        src = os.path.join(EXAMPLES, name, f"{name}.v")
        if not os.path.isfile(src):
            continue
        stamp = vpr_run.read_stamp(name) or {}
        out.append({"name": name, "path": os.path.relpath(src, ROOT),
                    "lines": sum(1 for _ in open(src)),
                    "routed": bool(stamp), "wirelength": stamp.get("wirelength")})
    return out


def pins():
    """The pad ring: which pads the board wires to a switch, button or LED, and which
    are reachable by boundary scan only. This is what a .pcf may name."""
    import vpr_run
    d = B.DEVICE
    named = {pad: name for name, pad in vpr_run.BOARD_PIN_NAMES.items()}
    out = []
    for io in d["pads"]["io"]:
        pad = io["pad"]
        out.append({"pad": pad, "x": io["x"], "y": io["y"],
                    "name": named.get(pad), "kind": (
                        "input" if named.get(pad, "").startswith(("SW", "BTN"))
                        else "output" if named.get(pad, "").startswith("LD") else "scan")})
    return {"pads": out, "board": vpr_run.BOARD_PIN_NAMES,
            "convention": "sw[1:0] -> SW1..0, btn[3:0] -> BTN3..0, led[2:0] -> LD2..0"}


def write_pcf(name, assign, into_project=False):
    """{port bit: pin name} -> build/pcf/<name>.pcf, checked against the pad map. With a
    project open and into_project, constrs/<name>.pcf instead, made the active pin file.

    `name` comes from the page, so it never reaches a path as given: it names a file in
    build/pcf/ and nothing else. Without this, "../../../x" walked out of the repo."""
    import vpr_run
    name = SAFE_NAME.sub("_", os.path.basename(str(name))).strip("._-") or "design"
    bad = [v for v in assign.values()
           if v not in vpr_run.BOARD_PIN_NAMES
           and not (re.fullmatch(r"pad\d+", str(v)) and int(str(v)[3:]) in B.PAD_XY)]
    if bad:
        raise ValueError(f"unknown pin(s) {sorted(set(bad))}")
    if len(set(assign.values())) != len(assign):
        raise ValueError("two ports on one pin")
    # write_eblif names every port bit port[i], one-bit ports included, so a bare port
    # name in a .pcf is silently ignored and the build then fails on the indexed net.
    bare = sorted(k for k in assign if not re.fullmatch(r"[^\[\]]+\[\d+\]", str(k)))
    if bare:
        raise ValueError(f"name each bit as port[i], one-bit ports included: {bare}")
    proj = PROJECT.get() if into_project else None
    out = (os.path.join(proj.dir, "constrs", f"{name}.pcf") if proj
           else os.path.join(ROOT, "build", "pcf", f"{name}.pcf"))
    if _inside(out) is None:
        raise ValueError(f"refusing to write outside the repo: {name}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        fh.write(f"# written by bob studio for {name}\n")
        for port, pin in sorted(assign.items()):
            fh.write(f"set_io {port} {pin}\n")
    vpr_run.read_pcf(out)                      # it must parse the way a build will read it
    if proj:
        with PROJECT.lock:
            rel = proj.add_constraint(out)
            proj.set_active_pcf(rel)
            proj.save()
    return _show(out)


def fasm_of(bit):
    """A .bit as FASM text plus the frame map, for the bitstream browser."""
    import bitgen
    import fasm_from_vpr as FV
    c = bitgen.read_bit(bit)
    F = bitgen.features_from_word(c["word"])
    fw = B.DEVICE["frames"]["bits"]
    word = c["word"]
    frames = []
    for i in range(B.DEVICE["frames"]["count"]):
        v = (word >> (i * fw)) & ((1 << fw) - 1)
        frames.append({"index": i, "set": bin(v).count("1"),
                       "hex": f"{v:0{fw // 4}X}"})
    cols = B.DEVICE["frames"]["columns"]
    return {"features": len(F), "fasm": FV.to_fasm(F), "crc": f"0x{c['crc']:08X}",
            "width": c["width"], "meta": c["meta"], "frames": frames, "columns": cols,
            "brams": sorted(c["brams"])}


REAL_ROOT = os.path.realpath(ROOT)


def _under(ap, base):
    return ap == base or ap.startswith(base + os.sep)


def _inside(path):
    """Only ever touch paths inside the repo or inside the open project, and never follow
    a link out of them. A relative path is relative to the repo; a project's files come as
    absolute paths. Both sides are resolved, so a symlink cannot make them differ."""
    if not path:
        return None
    ap = os.path.realpath(os.path.join(ROOT, os.path.expanduser(str(path))))
    if _under(ap, REAL_ROOT):
        return ap
    proj = PROJECT.get()
    if proj and _under(ap, os.path.realpath(proj.dir)):
        return ap
    return None


# --- projects and block designs (M18) -----------------------------------------


class OpenProject:
    """The one project the studio has open. Routes run on server threads, so every
    change to it happens under the lock and is saved before the lock is let go."""

    def __init__(self):
        self.lock = threading.RLock()
        self.p = None

    def get(self):
        return self.p

    def set(self, p):
        with self.lock:
            self.p = p
        return p

    def need(self):
        if self.p is None:
            raise P.ProjectError("no project open: File > New Project or Open Project")
        return self.p


PROJECT = OpenProject()
FS_SHOW = (".bobproj", ".v", ".sv", ".vh", ".pcf", ".sdc", ".bd")


def fs_list(path):
    """One folder for the New/Open dialogs: subfolders and the files a project uses.
    Read-only, and only names - never contents."""
    path = os.path.abspath(os.path.expanduser(path or "~"))
    if not os.path.isdir(path):
        raise ValueError(f"{path} is not a folder")
    dirs, files = [], []
    try:
        names = sorted(os.listdir(path), key=str.lower)
    except OSError as e:
        raise ValueError(str(e))
    for n in names:
        if n.startswith("."):
            continue
        full = os.path.join(path, n)
        if os.path.isdir(full):
            dirs.append({"name": n, "path": full,
                         "project": any(x.endswith(".bobproj") for x in _safe_listdir(full))})
        elif n.endswith(FS_SHOW):
            files.append({"name": n, "path": full, "type": os.path.splitext(n)[1].lstrip(".")})
    parent = os.path.dirname(path)
    return {"path": path, "parent": parent if parent != path else None, "dirs": dirs,
            "files": files, "home": os.path.expanduser("~"), "repo": ROOT}


def _safe_listdir(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


def project_json():
    proj = PROJECT.get()
    return {"project": proj.to_json() if proj else None, "recent": P.recent()}


def project_post(action, b):
    """Every POST /api/project/<action>. -> the project as the page draws it."""
    with PROJECT.lock:
        if action == "new":
            PROJECT.set(P.Project.create(b.get("location") or "~", b.get("name", "")))
        elif action == "open":
            PROJECT.set(P.Project.open(b.get("path", "")))
            P.remember(PROJECT.p.path)         # onto the recent list; opening changes nothing
        elif action == "close":
            PROJECT.set(None)
        else:
            proj = PROJECT.need()
            if action == "add":
                path = str(b.get("path", ""))
                if path.endswith((".pcf", ".sdc")):
                    proj.add_constraint(path, copy=b.get("copy", True))
                else:
                    proj.add_source(path, copy=b.get("copy", True))
            elif action == "clock":                  # M20: constrs/<name>.sdc, create_clock
                proj.set_clock(period_ns=b.get("period_ns"), mhz=b.get("mhz"))
            elif action == "create":
                name = str(b.get("name", "")).strip()
                proj.new_source(name, TEMPLATE.format(name=name))
            elif action == "remove":
                proj.remove(b.get("rel", ""))
            elif action == "top":
                proj.set_top(b.get("module", ""))
            elif action == "pcf":
                proj.set_active_pcf(b.get("rel"))
            elif action == "settings":
                proj.set_settings(**{k: v for k, v in b.items() if k in P.SETTINGS})
            else:
                raise P.ProjectError(f"no project action {action}")
            proj.save()
    return project_json()


def bd_get(rel):
    proj = PROJECT.need()
    if rel not in proj.data["block_designs"]:
        raise P.ProjectError(f"{rel} is not one of the project's block designs")
    return {"rel": rel, "bd": BD.load(proj.abs(rel))}


def bd_save(rel, bd):
    proj = PROJECT.need()
    if rel not in proj.data["block_designs"]:
        raise P.ProjectError(f"{rel} is not one of the project's block designs")
    BD.save(proj.abs(rel), bd)
    return {"rel": rel, "saved": True}


def block_ports(kind, typ, params):
    proj = PROJECT.get()
    if kind == "ip":
        rec = {r["ip"]: r for r in P.ip_catalog()}.get(typ)
        if rec is None:
            raise P.ProjectError(f"no IP called {typ}")
        return P.ports([rec["file"]], rec["module"], params)
    if proj is None:
        raise P.ProjectError("no project open")
    return P.ports(BD.user_files(proj), typ, params)


# --- the board ---------------------------------------------------------------


class DemoBoard(fakeboard.FakeBob):
    """FakeBob with its simulated free-running clock kept tractable.

    One simulated guest clock edge costs a model.settle() - a Python fixed point over
    3391 muxes, about a millisecond at 100 CLBs - so a design built with --clock run asks
    for more edges than the model can run, and a few seconds away from the page would
    queue tens of thousands. FakeBob bounds the backlog when it is given a budget: it
    skips ahead, counts what it skipped, and the page says the simulated clock is behind.
    The real board has no such problem."""

    BUDGET = 0.05                    # seconds of simulation allowed per scan (every
                                     # scan calls _run, so a request spends several)


class Target:
    """The open probe. `kind` is None until the page opens one."""

    def __init__(self, kind=None):
        self.kind = None
        self.probe = None
        self.bit = None                 # the last .bit programmed: its pins name the waveform's signals
        self.last_wave = None
        self.lock = threading.Lock()
        if kind:
            self.open(kind)

    def open(self, kind):
        with self.lock:
            self.probe = DemoBoard() if kind == "fake" else fakeboard.probe(kind)
            self.kind = kind
            idcode = self.probe.read_idcode()
        return {"kind": kind, "idcode": f"0x{idcode:08X}",
                "expected": f"0x{_expected():08X}", "match": idcode == _expected()}

    def status(self):
        if not self.probe:
            return {"kind": None, "open": False}
        import cfgplane
        import fpga
        with self.lock:
            idcode = self.probe.read_idcode()
            st, pins = None, None
            # An unprogrammed or unconfigured board answers neither; that is a state
            # the page should show, not a failure it should raise on.
            try:
                st = cfgplane.status(self.probe)
            except Exception as e:
                st = {"error": str(e)}
            try:
                cfgplane.ir(self.probe, "SAMPLE")     # fpga.sample needs the IR held there
                pins = fpga.sample(self.probe)
            except Exception as e:
                pins = {"error": str(e)}
        return {"kind": self.kind, "open": True, "idcode": f"0x{idcode:08X}",
                "expected": f"0x{_expected():08X}", "match": idcode == _expected(),
                "status": st, "pins": pins,
                "leds": (pins or {}).get("leds"), "sw": (pins or {}).get("sw"),
                "btn": (pins or {}).get("btn"),
                "simulated": self.kind == "fake",
                "clocks": getattr(self.probe, "clocks", None),
                "skipped": getattr(self.probe, "skipped", None),
                "edge_ms": round(getattr(self.probe, "_per_edge", 0) * 1000, 2)}

    def program(self, bit, mode="frames", partial=False):
        import cli
        if not self.probe:
            raise RuntimeError("no target open: POST /api/target first")
        with self.lock:
            if partial:
                ok, msg = cli.load_partial(self.probe, bit)
            else:
                ok, msg = cli.load(self.probe, bit, mode=mode)
            if ok:
                self.bit = bit
        return {"ok": ok, "message": msg, "mode": "partial" if partial else mode}

    def pins(self):
        """{port bit: pad} of the programmed design: its .pcf, or None (the convention)."""
        import bitgen
        if not self.bit or not os.path.exists(self.bit):
            return None, None
        meta = bitgen.read_bit(self.bit)["meta"]
        pcf = meta.get("pcf")
        if not pcf:
            return None, meta
        path = pcf if os.path.isabs(pcf) else os.path.join(ROOT, pcf)
        try:
            return vpr_run.read_pcf(path), meta
        except (OSError, vpr_run.VprError):
            return None, meta

    def wave_signals(self):
        pins, meta = self.pins()
        return {"signals": wave.signals(pins), "design": (meta or {}).get("design"),
                "clock": (meta or {}).get("clock"), "bit": self.bit,
                "conditions": list(wave.CONDITIONS), "max_depth": wave.MAX_DEPTH}

    def wave(self, b):
        """One capture. The probe is held for its length, so the timeout is kept short."""
        if not self.probe:
            raise RuntimeError("no target open: POST /api/target first")
        pins, meta = self.pins()
        with self.lock:
            cap = wave.capture(self.probe, b.get("mode", "step"), int(b.get("depth", 256)),
                               sel=b.get("sel") or None, trigger=b.get("trigger") or None,
                               pre=float(b.get("pre", 0.25)), stimulus=b.get("stimulus") or None,
                               timeout=min(30.0, float(b.get("timeout", 10.0))), pins=pins)
        cap["design"] = (meta or {}).get("design")
        cap["clock"] = (meta or {}).get("clock")
        self.last_wave = cap
        return cap


    def readback(self, bit):
        """Read the configuration back over FDRO and compare it with the .bit."""
        import bitgen
        import cfgplane
        if not self.probe:
            raise RuntimeError("no target open: POST /api/target first")
        want = bitgen.read_bit(bit)["word"]
        with self.lock:
            try:
                got = cfgplane.frames_readback(self.probe)
            except Exception as e:
                return {"ok": False, "differing_bits": None, "width": B.CHAIN_W,
                        "message": f"could not read the fabric back: {e}"}
        diff = bin(got ^ want).count("1")
        return {"ok": diff == 0, "differing_bits": diff, "width": B.CHAIN_W,
                "message": ("readback == the .bit" if diff == 0
                            else f"{diff} of {B.CHAIN_W} bits differ")}

    def capture(self):
        """CAPTURE every CLB register: the fabric's own state, as the board holds it.

        An unconfigured fabric has no registers to report, and a person clicking
        Capture before Program should be told that, not handed a traceback."""
        import cfgplane
        if not self.probe:
            raise RuntimeError("no target open: POST /api/target first")
        with self.lock:
            try:
                v = cfgplane.capture(self.probe, B.NCLB)
            except Exception as e:
                return {"ok": False, "nclb": B.NCLB, "bits": [], "ones": 0,
                        "message": f"nothing to capture - is a design loaded? ({e})"}
        return {"ok": True, "nclb": B.NCLB, "value": f"{v:0{(B.NCLB + 3) // 4}X}",
                "bits": [(v >> i) & 1 for i in range(B.NCLB)],
                "ones": bin(v).count("1"),
                "message": f"{bin(v).count('1')} of {B.NCLB} CLB registers set"}

    def partial(self, bit):
        """M14: rewrite only the frames that differ, with the user clock held."""
        import cli
        if not self.probe:
            raise RuntimeError("no target open: POST /api/target first")
        with self.lock:
            ok, msg = cli.load_partial(self.probe, bit)
        return {"ok": ok, "message": msg}


def _checked(res):
    """check()'s result without the resolved internals the page has no use for."""
    return {"errors": res["errors"], "warnings": res["warnings"],
            "ports": {bid: list(b["ports"].values()) for bid, b in res["blocks"].items()}}


def _expected():
    import fpga
    return fpga.IDCODE_FABRIC


TARGET = Target()


# --- HTTP --------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "bob-studio"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("BOB_STUDIO_QUIET"):
            return
        sys.stderr.write(f"  studio  {fmt % args}\n")

    # -- helpers ----------------------------------------------------------

    def _send(self, code, body=b"", ctype="application/json", extra=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    def _fail(self, code, msg):
        self._json({"error": msg}, code)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    # -- routes -----------------------------------------------------------

    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        try:
            if p in ("/", "/index.html"):
                return self._page()
            if p == "/api/device":
                return self._json(device())
            if p == "/api/examples":
                return self._json(examples())
            if p == "/api/source":
                return self._source(q.get("path", [""])[0])
            if p.startswith("/api/events/"):
                return self._events(p.rsplit("/", 1)[1])
            if p.startswith("/api/job/"):
                return self._job(p.rsplit("/", 1)[1])
            if p.startswith("/api/placement/"):
                return self._placement(p.rsplit("/", 1)[1], q)
            if p == "/api/target":
                return self._json(TARGET.status())
            if p == "/api/board":
                return self._json(TARGET.status())
            if p == "/api/bits":
                return self._json(bitstreams())
            if p == "/api/browse":
                return self._json(browse())
            if p == "/api/pins":
                return self._json(pins())
            if p == "/api/fasm":
                bit = _inside(q.get("bit", [""])[0])
                if not bit or not os.path.exists(bit):
                    return self._fail(400, "no such .bit inside the repo or the project")
                return self._json(fasm_of(bit))
            if p.startswith("/static/"):
                return self._static(p[len("/static/"):])
            if p == "/api/project":
                return self._json(project_json())
            if p == "/api/recent":
                return self._json({"recent": P.recent()})
            if p == "/api/fs":
                try:
                    return self._json(fs_list(q.get("path", [""])[0]))
                except ValueError as e:
                    return self._fail(400, str(e))
            if p == "/api/bd":
                return self._project_call(lambda: bd_get(q.get("rel", [""])[0]))
            if p == "/api/bd/palette":
                return self._project_call(lambda: BD.palette(PROJECT.get()))
            if p == "/api/wave/signals":
                return self._json(TARGET.wave_signals())
            if p == "/api/wave/vcd":
                if not TARGET.last_wave:
                    return self._fail(404, "no capture yet")
                name = (TARGET.last_wave.get("design") or "pads") + ".vcd"
                return self._send(200, wave.vcd(TARGET.last_wave), "text/plain; charset=utf-8",
                                  [("Content-Disposition", f'attachment; filename="{name}"')])
            if p == "/api/ports":
                return self._project_call(lambda: {"ports": block_ports(
                    q.get("kind", ["ip"])[0], q.get("type", [""])[0],
                    json.loads(q.get("params", ["{}"])[0] or "{}"))})
            return self._fail(404, f"no route {p}")
        except BrokenPipeError:
            pass
        except Exception as e:
            traceback.print_exc()
            self._fail(500, f"{type(e).__name__}: {e}")

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            if p == "/api/build":
                return self._build()
            if p == "/api/target":
                return self._json(TARGET.open(self._body().get("kind", "fake")))
            if p == "/api/program":
                b = self._body()
                bit = _inside(b.get("bit", ""))
                if not bit or not os.path.exists(bit):
                    return self._fail(400, "no such .bit inside the repo or the project")
                return self._json(TARGET.program(bit, b.get("mode", "frames"),
                                                 bool(b.get("partial"))))
            if p == "/api/save":
                b = self._body()
                try:
                    return self._json({"path": save_source(b.get("path", ""), b.get("text", ""))})
                except (ValueError, OSError) as e:
                    return self._fail(400, str(e))
            if p == "/api/new":
                try:
                    return self._json({"path": new_design(self._body().get("name", ""))})
                except (ValueError, OSError) as e:
                    return self._fail(400, str(e))
            if p == "/api/pcf":
                b = self._body()
                try:
                    return self._json({"pcf": write_pcf(b.get("name") or "design",
                                                        b.get("assign") or {},
                                                        bool(b.get("project")))})
                except ValueError as e:
                    return self._fail(400, str(e))
            if p in ("/api/readback", "/api/partial"):
                b = self._body()
                bit = _inside(b.get("bit", ""))
                if not bit or not os.path.exists(bit):
                    return self._fail(400, "no such .bit inside the repo or the project")
                return self._json(TARGET.readback(bit) if p.endswith("readback")
                                  else TARGET.partial(bit))
            if p == "/api/capture":
                return self._json(TARGET.capture())
            if p == "/api/wave/capture":
                try:
                    return self._json(TARGET.wave(self._body()))
                except (wave.WaveError, ValueError, RuntimeError) as e:
                    return self._fail(400, str(e))
            if p.startswith("/api/project/"):
                b = self._body()
                return self._project_call(lambda: project_post(p.rsplit("/", 1)[1], b))
            if p == "/api/bd":
                b = self._body()
                return self._project_call(lambda: bd_save(b.get("rel", ""), b.get("bd") or {}))
            if p == "/api/bd/new":
                b = self._body()
                return self._project_call(lambda: {"rel": BD.new_bd(PROJECT.need(), b.get("name", "")),
                                                   **project_json()})
            if p == "/api/bd/check":
                b = self._body()
                return self._project_call(lambda: _checked(BD.check(b.get("bd") or {}, PROJECT.get())))
            if p == "/api/bd/generate":
                b = self._body()

                def gen():
                    with PROJECT.lock:
                        proj = PROJECT.need()
                        if b.get("bd") is not None:
                            bd_save(b.get("rel", ""), b["bd"])
                        out = BD.generate(proj, b.get("rel", ""), set_top=bool(b.get("top")))
                    return {"generated": out, **project_json()}
                return self._project_call(gen)
            return self._fail(404, f"no route {p}")
        except Exception as e:
            traceback.print_exc()
            self._fail(500, f"{type(e).__name__}: {e}")

    def _project_call(self, fn):
        """A project or block-design action: its refusals are the user's to read (400),
        anything else is a bug (500, from the caller)."""
        try:
            return self._json(fn())
        except (P.ProjectError, BD.BdError, vpr_run.VprError, ValueError, OSError) as e:
            return self._fail(400, str(e))

    # -- implementations --------------------------------------------------

    def _page(self):
        if not os.path.exists(PAGE):
            return self._send(503, "studio.html is not built yet:\n"
                                   "  python3 software/studio/build.py\n", "text/plain")
        body = open(PAGE, "rb").read()
        self._send(200, body, "text/html; charset=utf-8")

    def _static(self, rel):
        ap = _inside(os.path.join("software", "studio", rel))
        if not ap or not os.path.isfile(ap):
            return self._fail(404, "no such file")
        ctype = mimetypes.guess_type(ap)[0] or "application/octet-stream"
        self._send(200, open(ap, "rb").read(), ctype)

    def _source(self, rel):
        ap = _inside(unquote(rel))
        if not ap or not os.path.isfile(ap):
            return self._fail(404, "no such file inside the repo or the project")
        return self._json({"path": rel, "text": open(ap, errors="replace").read()})

    def _build(self):
        spec = self._body()
        if spec.get("project"):
            try:
                proj = PROJECT.need()
                kw = proj.flow_kwargs()
                kw["record"] = os.path.join(proj.dir, "build", f"{proj.name}.json")
                flow.Flow(**{k: v for k, v in kw.items() if k != "record"})
            except (P.ProjectError, flow.FlowError) as e:
                return self._fail(400, str(e))
            job = Job(kw)
            _remember(job)
            job.start()
            return self._json({"job": job.id})
        files = [f for f in spec.get("files", []) if _inside(f)]
        if not files:
            return self._fail(400, "no source files inside the repo")
        kw = {"files": [_inside(f) for f in files]}
        for k in ("top", "pcf", "name", "pnr", "clock", "hz"):     # hz: M20, "auto" or a rate
            if spec.get(k):
                kw[k] = spec[k]
        for k in ("div", "seed"):
            if spec.get(k) is not None:
                kw[k] = int(spec[k])
        if kw.get("pcf"):
            kw["pcf"] = _inside(kw["pcf"])
        try:
            flow.Flow(**kw)                     # reject bad options before starting a thread
        except flow.FlowError as e:
            return self._fail(400, str(e))
        job = Job(kw)
        _remember(job)
        job.start()
        return self._json({"job": job.id})

    def _events(self, jid):
        job = JOBS.get(jid)
        if not job:
            return self._fail(404, "no such job")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        while True:
            ev = job.events.get()
            if ev is None:
                break
            self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
            self.wfile.flush()

    def _job(self, jid):
        job = JOBS.get(jid)
        if not job:
            return self._fail(404, "no such job")
        if not job.done.is_set():
            return self._json({"running": True, "job": jid})
        return self._json(job.result or {"error": job.error})

    def _placement(self, name, q):
        work = q.get("work", [None])[0]
        if work:
            work = _inside(work)
        else:
            work = os.path.join(vpr_run.RESULTS, name)
        pl = placement(name, work)
        if pl is None:
            return self._fail(404, f"no place-and-route result for {name}")
        return self._json(pl)


def serve(port=8765, probe=None, open_browser=True):
    if probe:
        t = TARGET.open(probe)
        print(f"  target  {t['kind']}: IDCODE {t['idcode']}"
              + ("" if t["match"] else f"  MISMATCH, expected {t['expected']}"), flush=True)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        # Restarting the studio is a constant, and a stack trace is a poor way to say
        # "the last one is still running".
        busy = "in use" in str(e) or getattr(e, "errno", None) in (48, 98)
        print(f"  studio  cannot listen on 127.0.0.1:{port}: {e}")
        if busy:
            print(f"  studio  something is already there. Stop it, or use --port {port + 1}.")
            print(f"  studio  find it with:  lsof -ti tcp:{port}")
        raise SystemExit(1)
    url = f"http://127.0.0.1:{port}/"
    print(f"  device  {B.DEVICE['name']}: {B.NCLB} CLBs, {B.CHAIN_W}-bit chain, "
          f"{B.DEVICE['frames']['count']} frames")
    print(f"  studio  {url}", flush=True)
    if not os.path.exists(PAGE):
        print("  studio  studio.html is not built: python3 software/studio/build.py")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  studio  stopped")
    finally:
        srv.server_close()


class AppBridge:
    """What the page may ask the native window for (window.pywebview.api.*): the file
    dialogs a browser tab cannot open. Only paths come back; reading and writing stay
    with the routes above and their guards."""

    window = None

    def pick_folder(self, start=""):
        import webview
        r = self.window.create_file_dialog(webview.FileDialog.FOLDER, directory=start or os.path.expanduser("~"))
        return r[0] if r else None

    def pick_files(self, kind="hdl", start=""):
        import webview
        types = {"hdl": ("Verilog (*.v;*.sv;*.vh)",), "pcf": ("Pin files (*.pcf)",),
                 "project": ("bob projects (*.bobproj)",)}.get(kind, ("All files (*.*)",))
        r = self.window.create_file_dialog(webview.FileDialog.OPEN, directory=start or os.path.expanduser("~"),
                                           allow_multiple=kind != "project", file_types=types)
        return list(r) if r else []

    def save_text(self, name, text):
        """Save a download (the .vcd) where the user says. -> the path, or None if cancelled."""
        import webview
        r = self.window.create_file_dialog(webview.FileDialog.SAVE, directory=os.path.expanduser("~"),
                                           save_filename=os.path.basename(str(name)))
        if not r:
            return None
        path = r if isinstance(r, str) else r[0]
        with open(path, "w") as fh:
            fh.write(text)
        return path


def serve_app(port=0, probe=None):
    """bob studio as a desktop app: the same backend, in this process, shown in a native
    window (pywebview: WebKit on macOS, WebView2 on Windows, GTK/Qt on Linux) instead of a
    browser tab. Without pywebview it says so and falls back to the browser."""
    try:
        import webview
    except ImportError:
        print("  studio  the app window needs pywebview (pip3 install pywebview); opening the browser instead")
        return serve(port or 8765, probe, True)
    if probe:
        t = TARGET.open(probe)
        print(f"  target  {t['kind']}: IDCODE {t['idcode']}"
              + ("" if t["match"] else f"  MISMATCH, expected {t['expected']}"), flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)      # port 0: any free one
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"  studio  app window on {url}", flush=True)
    if not os.path.exists(PAGE):
        print("  studio  studio.html is not built: python3 software/studio/build.py")
    bridge = AppBridge()
    bridge.window = webview.create_window("bob studio", url, js_api=bridge, width=1480, height=940,
                                          min_size=(1000, 640), text_select=True)
    try:
        webview.start()
    finally:
        srv.shutdown()
        srv.server_close()
        print("  studio  closed")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=None, help="default 8765 (browser) or any free port (--app)")
    ap.add_argument("--probe", choices=("usb", "fake"),
                    help="open a target at startup (fake needs no hardware)")
    ap.add_argument("--app", action="store_true", help="a desktop window instead of a browser tab (pywebview)")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if a.app:
        serve_app(a.port or 0, a.probe)
    else:
        serve(a.port or 8765, a.probe, not a.no_browser)


if __name__ == "__main__":
    main()
