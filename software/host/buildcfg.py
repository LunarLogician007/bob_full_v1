"""
Read hw/build.cfg and hw/sources.f from Python, with the same rules as
hw/scripts/build.tcl: 'key = value', '#' starts a comment.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HW = os.path.join(ROOT, "hw")


def _strip(line):
    return line.split("#", 1)[0].strip()


def read_cfg(path=None):
    cfg = {}
    with open(path or os.path.join(HW, "build.cfg")) as fh:
        for raw in fh:
            line = _strip(raw)
            if not line:
                continue
            if "=" not in line:
                raise ValueError(f"build.cfg: no '=' in line: {raw.rstrip()}")
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


def read_sources(path=None):
    """Paths relative to hw/, in order."""
    with open(path or os.path.join(HW, "sources.f")) as fh:
        return [ln for ln in (_strip(r) for r in fh) if ln]


def expected_idcode(cfg=None):
    cfg = cfg or read_cfg()
    return int(cfg["idcode"], 16) if cfg.get("idcode") else None
