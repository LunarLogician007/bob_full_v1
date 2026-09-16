"""
The hw/ bundle is self-contained and every consumer agrees on it.
"""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))

import buildcfg  # noqa: E402

HW = buildcfg.HW


def test_every_source_exists_and_lives_in_hw():
    srcs = buildcfg.read_sources()
    assert srcs, "sources.f is empty"
    for s in srcs:
        assert not os.path.isabs(s) and ".." not in s, f"{s} must be inside hw/"
        assert os.path.isfile(os.path.join(HW, s)), f"missing {s}"
    assert len(srcs) == len(set(srcs)), "duplicate entries in sources.f"


def test_build_cfg_is_complete():
    cfg = buildcfg.read_cfg()
    for key in ("tag", "top", "idcode", "part", "xdc", "project", "sim_top", "sim_files"):
        assert key in cfg, f"build.cfg lacks {key}"
    assert re.fullmatch(r"M\d+", cfg["tag"])
    assert re.fullmatch(r"[0-9A-Fa-f]{8}", cfg["idcode"])
    assert int(cfg["idcode"], 16) & 0xFFF == 0x093, "keep the JEDEC-style low bits"
    assert os.path.isfile(os.path.join(HW, cfg["xdc"]))
    for f in cfg["sim_files"].split():
        assert os.path.isfile(os.path.join(HW, f))
    # the project must be outside hw/, or pasting hw/ would clobber it
    proj = os.path.normpath(os.path.join(HW, cfg["project"]))
    assert not proj.startswith(HW + os.sep)


def test_xdc_is_plain_xdc():
    """Vivado skips Tcl control flow in an XDC with only a critical warning.
    That silently removed create_clock in the first M0 build."""
    cfg = buildcfg.read_cfg()
    banned = r"^\s*(if|else|elseif|catch|set|expr|foreach|for|while|proc|puts)\b"
    with open(os.path.join(HW, cfg["xdc"])) as fh:
        for n, line in enumerate(fh, 1):
            code = line.split("#", 1)[0]
            assert not re.match(banned, code), f"Tcl in XDC line {n}: {line.strip()}"
            assert "$" not in code, f"variable in XDC line {n}: {line.strip()}"
    text = open(os.path.join(HW, cfg["xdc"])).read()
    assert re.search(r"^create_clock\s.*get_ports tck", text, re.M)


def test_top_module_is_in_the_source_list():
    cfg = buildcfg.read_cfg()
    text = "".join(open(os.path.join(HW, s)).read() for s in buildcfg.read_sources())
    assert re.search(rf"\bmodule\s+{cfg['top']}\b", text)
    assert re.search(r"parameter\s+\[31:0\]\s+IDCODE_VALUE", text)


def test_sim_scripts_use_the_same_list():
    out = subprocess.run([os.path.join(ROOT, "sim", "hwfiles.sh")],
                         capture_output=True, text=True, check=True).stdout.split()
    assert [os.path.relpath(p, HW) for p in out] == buildcfg.read_sources()


def test_nothing_outside_hw_is_needed_by_vivado():
    tcl = open(os.path.join(HW, "scripts", "build.tcl")).read()
    # every file reference is built from hw_dir or script_dir
    for m in re.finditer(r"\$(\w+)/", tcl):
        assert m.group(1) in {"hw_dir", "script_dir", "proj_dir", "out_dir",
                              "tag"}, m.group(0)
