#!/usr/bin/env python3
"""
project.py - a bob project: a folder with its sources, block designs, pin files and one
project file that opens it again (M18).

Vivado's project, cut down to what this fabric's flow takes. New Project makes

  <location>/<name>/
    <name>.bobproj        the project file (JSON); open it to reopen the project
    src/                  design sources (.v .sv .vh)
    bd/                   block designs (<bd>.bd) and their generated <bd>_wrapper.v
    ip/                   the IP cores the block designs use, copied in from software/bob/ip/
    constrs/              pin files (.pcf)
    build/                outputs: <name>.bit and the stage record

Every path in the project file is relative to it, so a project can be moved, zipped or
shared with its sources. The project turns into exactly the arguments flow.Flow takes
(flow_kwargs), so a project build is the same flow as `./bob build` - `tests/test_project.py`
holds the two to a byte-identical .bit.

  ./software/bob/project.py new  ~/fpga demo            make ~/fpga/demo/demo.bobproj
  ./software/bob/project.py show ~/fpga/demo/demo.bobproj
  ./bob build --project ~/fpga/demo/demo.bobproj
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
IP_DIR = os.path.join(HERE, "ip")

EXT = ".bobproj"
VERSION = 1
SOURCE_EXT = (".v", ".sv", ".vh")
HDL_EXT = (".v", ".sv")                 # what yosys reads; a .vh is only ever included
SUBDIRS = ("src", "bd", "ip", "constrs", "build")
SETTINGS = {"clock": "jtag", "div": 0, "seed": 1, "pnr": "vpr", "hz": "div"}
# hz (M20, with clock run): "div" = the power-of-two divider (div); "auto" = the fastest rate
# the design's own timing allows (software/bob/timing.py); a number = that rate in Hz
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
RECENT = os.path.join(os.path.expanduser("~"), ".bob", "recent.json")


class ProjectError(Exception):
    """Something the user asked for that the project cannot do. The message is for them."""


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


class Project:
    def __init__(self, path, data):
        self.path = os.path.abspath(path)
        self.dir = os.path.dirname(self.path)
        self.data = data

    # -- making and opening -----------------------------------------------------

    @classmethod
    def create(cls, location, name):
        """<location>/<name>/<name>.bobproj and its folders. The name becomes a Verilog
        identifier (a wrapper's module name) and a file name, so it must be both."""
        name = str(name).strip()
        if not NAME.fullmatch(name):
            raise ProjectError("a project name starts with a letter and holds letters, digits or _")
        location = os.path.abspath(os.path.expanduser(str(location)))
        if not os.path.isdir(location):
            raise ProjectError(f"{location} is not a folder")
        pdir = os.path.join(location, name)
        if os.path.exists(pdir):
            raise ProjectError(f"{pdir} already exists")
        for sub in SUBDIRS:
            os.makedirs(os.path.join(pdir, sub))
        p = cls(os.path.join(pdir, name + EXT),
                {"bobproj": VERSION, "name": name, "top": None, "sources": [],
                 "constraints": [], "active_pcf": None, "block_designs": [],
                 "settings": dict(SETTINGS), "created": _now()})
        p.save()
        return p

    @classmethod
    def open(cls, path):
        path = os.path.abspath(os.path.expanduser(str(path)))
        if os.path.isdir(path):
            found = [n for n in os.listdir(path) if n.endswith(EXT)]
            if len(found) != 1:
                raise ProjectError(f"{path}: expected one {EXT} file, found {len(found)}")
            path = os.path.join(path, found[0])
        if not path.endswith(EXT):
            raise ProjectError(f"{path} is not a {EXT} file")
        try:
            d = json.load(open(path))
        except (OSError, ValueError) as e:
            raise ProjectError(f"{path}: {e}")
        if d.get("bobproj") != VERSION:
            raise ProjectError(f"{path}: not a version-{VERSION} bob project")
        d.setdefault("settings", {})
        d["settings"] = {**SETTINGS, **d["settings"]}
        for k in ("sources", "constraints", "block_designs"):
            d.setdefault(k, [])
        return cls(path, d)

    def save(self):
        self.data["modified"] = _now()
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, self.path)
        remember(self.path)
        return self

    # -- paths ------------------------------------------------------------------

    @property
    def name(self):
        return self.data["name"]

    def abs(self, rel):
        return os.path.normpath(os.path.join(self.dir, rel))

    def rel(self, path):
        """Inside the project: relative to it. Outside (a referenced file): absolute."""
        ap = os.path.abspath(os.path.expanduser(path))
        return os.path.relpath(ap, self.dir) if self.contains(ap) else ap

    def contains(self, path):
        real = os.path.realpath(self.dir)
        ap = os.path.realpath(path)
        return ap == real or ap.startswith(real + os.sep)

    # -- sources, constraints, block designs ------------------------------------

    def add_source(self, path, copy=True):
        """A .v/.sv/.vh file. copy=True puts it in src/ (Vivado's "copy sources into
        project"), otherwise the project refers to it where it is."""
        ap = os.path.abspath(os.path.expanduser(path))
        if not ap.endswith(SOURCE_EXT):
            raise ProjectError(f"a source is one of {', '.join(SOURCE_EXT)}: {path}")
        if not os.path.isfile(ap):
            raise ProjectError(f"{path} does not exist")
        if copy and not self.contains(ap):
            dst = os.path.join(self.dir, "src", os.path.basename(ap))
            if os.path.exists(dst):
                raise ProjectError(f"src/{os.path.basename(ap)} already exists in the project")
            shutil.copy(ap, dst)
            ap = dst
        rel = self.rel(ap)
        if rel not in self.data["sources"]:
            self.data["sources"].append(rel)
        return rel

    def new_source(self, name, text):
        """src/<name>.v written from text (the studio's "create file")."""
        if not NAME.fullmatch(name):
            raise ProjectError("a file name starts with a letter and holds letters, digits or _")
        dst = os.path.join(self.dir, "src", name + ".v")
        if os.path.exists(dst):
            raise ProjectError(f"src/{name}.v already exists")
        with open(dst, "w") as fh:
            fh.write(text)
        return self.add_source(dst)

    def add_constraint(self, path, copy=True):
        ap = os.path.abspath(os.path.expanduser(path))
        if not ap.endswith(".pcf"):
            raise ProjectError(f"a constraint file is a .pcf: {path}")
        if not os.path.isfile(ap):
            raise ProjectError(f"{path} does not exist")
        if copy and not self.contains(ap):
            dst = os.path.join(self.dir, "constrs", os.path.basename(ap))
            if os.path.exists(dst):
                raise ProjectError(f"constrs/{os.path.basename(ap)} already exists in the project")
            shutil.copy(ap, dst)
            ap = dst
        rel = self.rel(ap)
        if rel not in self.data["constraints"]:
            self.data["constraints"].append(rel)
        if self.data.get("active_pcf") is None:
            self.data["active_pcf"] = rel
        return rel

    def set_active_pcf(self, rel):
        if rel is not None and rel not in self.data["constraints"]:
            raise ProjectError(f"{rel} is not one of the project's constraint files")
        self.data["active_pcf"] = rel

    def add_bd(self, rel):
        if rel not in self.data["block_designs"]:
            self.data["block_designs"].append(rel)
        return rel

    def remove(self, rel):
        """Take a file out of the project. The file itself stays on disk, as in Vivado."""
        hit = False
        for k in ("sources", "constraints", "block_designs"):
            if rel in self.data[k]:
                self.data[k].remove(rel)
                hit = True
        if not hit:
            raise ProjectError(f"{rel} is not in the project")
        if self.data.get("active_pcf") == rel:
            self.data["active_pcf"] = self.data["constraints"][0] if self.data["constraints"] else None

    def set_top(self, module):
        names = {m["name"] for m in self.modules()}
        if module not in names:
            raise ProjectError(f"no module {module} in the project's sources "
                               f"(found {sorted(names) or 'none'})")
        self.data["top"] = module

    def set_settings(self, **kw):
        bad = set(kw) - set(SETTINGS)
        if bad:
            raise ProjectError(f"unknown setting(s) {sorted(bad)}; expected {list(SETTINGS)}")
        if "clock" in kw and kw["clock"] not in ("jtag", "run"):
            raise ProjectError("clock is jtag or run")
        if "pnr" in kw and kw["pnr"] not in ("vpr", "python"):
            raise ProjectError("pnr is vpr or python")
        for k in ("div", "seed"):
            if k in kw:
                kw[k] = int(kw[k])
        if "hz" in kw:
            h = str(kw["hz"]).strip() or "div"
            if h not in ("div", "auto"):
                try:
                    if float(h) <= 0:
                        raise ValueError
                except ValueError:
                    raise ProjectError("hz is div, auto or a rate in Hz")
            kw["hz"] = h
        self.data["settings"].update(kw)

    # -- what the flow sees -----------------------------------------------------

    def hdl_files(self):
        """The files yosys reads, absolute, in project order. A missing file is an error
        here rather than a yosys one, so it names the project entry."""
        out = []
        for rel in self.data["sources"]:
            ap = self.abs(rel)
            if not os.path.isfile(ap):
                raise ProjectError(f"{rel} is in the project but not on disk")
            if ap.endswith(HDL_EXT):
                out.append(ap)
        return out

    def modules(self):
        """Every module in the sources: name, file, ports (direction and width at the
        default parameters) and parameters. Read by yosys, cached on the sources."""
        return modules(self.hdl_files())

    def result_name(self):
        """The flow's result name. It names build/synth/, build/vpr/ and the committed VPR
        result, so two projects whose tops are both `top` must not share it."""
        top = self.data["top"]
        return top if top == self.name or top.startswith(self.name + "_") else f"{self.name}_{top}"

    def bit_path(self):
        return os.path.join(self.dir, "build", f"{self.name}.bit")

    def flow_kwargs(self):
        """-> the keyword arguments flow.Flow / cli.build take, files included."""
        files = self.hdl_files()
        if not files:
            raise ProjectError("the project has no design sources: add a .v file")
        if not self.data.get("top"):
            raise ProjectError("no top module: set one (right-click a module, Set as top)")
        pcf = self.data.get("active_pcf")
        s = self.data["settings"]
        hz = s.get("hz", "div")
        return {"files": files, "top": self.data["top"],
                "pcf": self.abs(pcf) if pcf else None,
                "out": self.bit_path(), "name": self.result_name(),
                "clock": s["clock"], "div": int(s["div"]), "seed": int(s["seed"]), "pnr": s["pnr"],
                "hz": hz if s["clock"] == "run" and hz != "div" else None}

    def to_json(self, with_modules=True):
        d = dict(self.data)
        d["path"] = self.path
        d["dir"] = self.dir
        d["files"] = {k: [{"rel": r, "path": self.abs(r), "exists": os.path.exists(self.abs(r))}
                          for r in self.data[k]]
                      for k in ("sources", "constraints", "block_designs")}
        bit = self.bit_path()
        d["bit"] = bit if os.path.exists(bit) else None
        if with_modules:
            try:
                d["modules"] = self.modules()
                d["modules_error"] = None
            except (ProjectError, RuntimeError) as e:
                d["modules"], d["modules_error"] = [], str(e)
        return d


# --- modules and ports, by yosys ---------------------------------------------------

_CACHE = {}


def _yosys_json(files, script_mid, defer=False):
    """read the files, run script_mid, proc, write JSON -> the parsed JSON."""
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "m.json")
        read = " ".join(f'"{f}"' for f in files)
        cmd = f"read_verilog -sv{' -defer' if defer else ''} {read}; {script_mid}proc; write_json {out}"
        r = subprocess.run(["yosys", "-q", "-p", cmd], capture_output=True, text=True)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip().splitlines()
            raise ProjectError("yosys could not read the sources: " + (msg[-1] if msg else "?"))
        return json.load(open(out))


def _param_value(v):
    """yosys writes a parameter as a binary string (or a real/string as text)."""
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v and set(v) <= {"0", "1", "x", "z"}:
        return int(v.replace("x", "0").replace("z", "0"), 2)
    return v


def _module_record(name, m, file_of):
    ports = [{"name": p, "dir": v["direction"], "width": len(v["bits"])}
             for p, v in m["ports"].items()]
    params = {k: _param_value(v) for k, v in (m.get("parameter_default_values") or {}).items()}
    src = (m.get("attributes") or {}).get("src", "")
    return {"name": name, "file": file_of(src), "ports": ports, "params": params}


def _key(files, *extra):
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode())
        h.update(open(f, "rb").read())
    h.update(repr(extra).encode())
    return h.hexdigest()


def modules(files):
    files = list(files)
    if not files:
        return []
    key = _key(files, "modules")
    if key not in _CACHE:
        d = _yosys_json(files, "")

        def file_of(src):
            return src.split(":", 1)[0] if src else None

        _CACHE[key] = sorted((_module_record(n, m, file_of) for n, m in d["modules"].items()
                              if not n.startswith("$")), key=lambda r: r["name"])
    return _CACHE[key]


def ports(files, module, params=None):
    """The ports of one module elaborated with these parameters: [{name, dir, width}]."""
    files = list(files)
    params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
    key = _key(files, "ports", module, sorted(params.items()))
    if key not in _CACHE:
        for k, v in params.items():
            if not re.fullmatch(r"[A-Za-z_]\w*", k) or not re.fullmatch(r"-?\d+", str(v)):
                raise ProjectError(f"{module}: parameter {k} = {v!r} must be an integer")
        chp = "".join(f" -chparam {k} {v}" for k, v in params.items())
        d = _yosys_json(files, f"hierarchy -top {module}{chp}; ", defer=True)
        mods = {n: m for n, m in d["modules"].items() if n == module or n.endswith(f"\\{module}")}
        if not mods:
            raise ProjectError(f"no module {module} in the sources")
        m = next(iter(mods.values()))
        _CACHE[key] = [{"name": p, "dir": v["direction"], "width": len(v["bits"])}
                       for p, v in m["ports"].items()]
    return _CACHE[key]


# --- the IP catalog ----------------------------------------------------------------

def ip_catalog():
    """software/bob/ip/*.v with their headers: // @ip name, // @desc ..., // @param N default text"""
    out = []
    for n in sorted(os.listdir(IP_DIR)):
        if not n.endswith(".v"):
            continue
        path = os.path.join(IP_DIR, n)
        rec = {"ip": None, "module": os.path.splitext(n)[0], "file": path, "desc": "", "params": []}
        for line in open(path):
            m = re.match(r"//\s*@(\w+)\s+(.*)", line.strip())
            if not m:
                if line.strip() and not line.startswith("//"):
                    break
                continue
            tag, val = m.group(1), m.group(2).strip()
            if tag == "ip":
                rec["ip"] = val
            elif tag == "desc":
                rec["desc"] = (rec["desc"] + " " + val).strip()
            elif tag == "param":
                f = val.split(None, 2)
                rec["params"].append({"name": f[0], "default": int(f[1]),
                                      "text": f[2] if len(f) > 2 else ""})
        if rec["ip"]:
            rec["ports"] = ports([path], rec["module"])
            out.append(rec)
    return out


# --- recent projects ----------------------------------------------------------------

def remember(path):
    try:
        os.makedirs(os.path.dirname(RECENT), exist_ok=True)
        try:
            lst = json.load(open(RECENT))
        except (OSError, ValueError):
            lst = []
        lst = [path] + [p for p in lst if p != path]
        with open(RECENT, "w") as fh:
            json.dump(lst[:12], fh, indent=1)
    except OSError:
        pass                                   # a read-only home is not a build failure


def recent():
    try:
        lst = json.load(open(RECENT))
    except (OSError, ValueError):
        return []
    return [p for p in lst if isinstance(p, str) and os.path.isfile(p)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="make <location>/<name>/<name>.bobproj")
    n.add_argument("location")
    n.add_argument("name")
    n.add_argument("--add", nargs="*", default=[], help="sources to copy in")
    n.add_argument("--pcf", help="a pin file to copy in")
    n.add_argument("--top")
    s = sub.add_parser("show", help="the project and its modules")
    s.add_argument("project")
    a = ap.parse_args()
    try:
        if a.cmd == "new":
            p = Project.create(a.location, a.name)
            for f in a.add:
                p.add_source(f)
            if a.pcf:
                p.add_constraint(a.pcf)
            if a.top:
                p.set_top(a.top)
            p.save()
            print(p.path)
        else:
            print(json.dumps(Project.open(a.project).to_json(), indent=2))
    except ProjectError as e:
        sys.exit(f"error: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
