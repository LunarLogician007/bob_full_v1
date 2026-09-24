"""
The hw/ bundle is self-contained and every consumer agrees on it.
"""

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))

import buildcfg  # noqa: E402

HW = buildcfg.HW


def _xdc():
    return open(os.path.join(HW, buildcfg.read_cfg()["xdc"])).read()


def _device():
    return json.load(open(os.path.join(ROOT, "software", "bob", "device.json")))


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


# --- the timing contract ------------------------------------------------------
#
# Through M20 the fabric's sysclk -> sysclk multicycle was true only because clock_ctrl.v
# guaranteed gce pulses at least 2**GCE_MIN_GAP_SHIFT cycles apart, and it had to cover
# the longest path Vivado found through the unconfigured fabric. Until M16 nothing checked
# that agreement, and M16's first implementation ran 3 h 25 min and failed at WNS -465 ns.
# M21 showed the unconfigured path is not a property of the fabric (it grew with the
# budget), so the XDC's number is now XDC_SYSCLK_MULTICYCLE, far beyond any path, and the
# promise is kept per design by timing.contract() (tests/test_timing.py). These tests
# hold the XDC to device.py and the RTL to the generated header.


def test_the_sysclk_multicycle_is_the_one_device_py_names():
    c = _device()["clock"]
    want = c["xdc_multicycle"]
    m = re.search(r"^set_multicycle_path\s+-setup\s+(\d+)\s+-from\s+\[get_clocks sysclk\]"
                  r"\s+-to\s+\[get_clocks sysclk\]", _xdc(), re.M)
    assert m, "no sysclk -> sysclk setup multicycle in the XDC"
    assert int(m.group(1)) == want, (
        f"XDC relaxes sysclk by {m.group(1)} cycles but XDC_SYSCLK_MULTICYCLE in "
        f"software/bob/device.py is {want}: change them together")


def test_the_tck_multicycle_is_the_one_device_py_names():
    """M21: TCK paths through the empty fabric passed the 10 us period (WNS -228 ns), so
    TCK -> TCK is relaxed like sysclk, with hold at the same edge."""
    want = _device()["clock"]["xdc_tck_multicycle"]
    x = _xdc()
    setup = re.search(r"^set_multicycle_path\s+-setup\s+(\d+)\s+-from\s+\[get_clocks tck\]"
                      r"\s+-to\s+\[get_clocks tck\]", x, re.M)
    hold = re.search(r"^set_multicycle_path\s+-hold\s+(\d+)\s+-from\s+\[get_clocks tck\]"
                     r"\s+-to\s+\[get_clocks tck\]", x, re.M)
    assert setup and hold, "no tck -> tck multicycle pair in the XDC"
    assert int(setup.group(1)) == want, f"XDC tck multicycle {setup.group(1)}, device.py {want}"
    assert int(hold.group(1)) == want - 1, f"tck setup {want} needs hold {want - 1}"


def test_the_sysclk_multicycle_is_no_tighter_than_the_default_gap():
    """The multicycle only has to keep Vivado off the unconfigured fabric, but it must never
    be the tighter promise: every word timing.contract() accepts runs at least the default
    gap apart when clk_gap is 0, and the XDC must not claim less room than that."""
    c = _device()["clock"]
    assert c["xdc_multicycle"] >= 1 << c["gce_min_gap_shift"], (
        f"XDC multicycle {c['xdc_multicycle']} < the default gap 2**{c['gce_min_gap_shift']}")


def test_loads_are_held_to_the_timing_contract():
    """The XDC's relaxation is safe only because nothing reaches the fabric untimed: the
    flow's timing stage and cli.load must both call timing.contract()."""
    fl = open(os.path.join(ROOT, "software", "bob", "flow.py")).read()
    cl = open(os.path.join(ROOT, "software", "bob", "cli.py")).read()
    assert "T.contract(t, word)" in fl, "flow.py's timing stage no longer checks the contract"
    for fn in ("def load(", "def load_partial("):
        body = cl[cl.index(fn):].split("\ndef ", 1)[0]
        assert "contract(" in body, f"cli.py {fn[4:-1]} loads without the timing contract"
    # only the clock-margin sweep may over-clock, and only below the computed period
    hw = open(os.path.join(ROOT, "software", "host", "hwtest.py")).read()
    assert hw.count("over_clock=") == 1 and "over_clock=period < gap" in hw, (
        "over_clock is for check_clock_margin's sweep below the computed period only")


def test_the_sysclk_hold_multicycle_is_one_less_than_setup():
    """UG903: a setup multicycle of N needs a hold multicycle of N-1, or the tool
    moves the hold check with it and every short path fails."""
    x = _xdc()
    setup = re.search(r"^set_multicycle_path\s+-setup\s+(\d+)\s+-from\s+\[get_clocks sysclk\]", x, re.M)
    hold = re.search(r"^set_multicycle_path\s+-hold\s+(\d+)\s+-from\s+\[get_clocks sysclk\]", x, re.M)
    assert setup and hold, "the sysclk multicycle pair is not both present"
    assert int(hold.group(1)) == int(setup.group(1)) - 1, (
        f"setup {setup.group(1)} needs hold {int(setup.group(1)) - 1}, not {hold.group(1)}")


def test_the_rtl_gets_the_gap_from_the_generated_header():
    """bob_fpga.v must take GAP_SHIFT from BOB_GCE_MIN_GAP_SHIFT. Passing anything
    else makes software/bob/device.py's knob a decoration and the XDC check above a lie."""
    src = open(os.path.join(HW, "src", "fabric", "bob_fpga.v")).read()
    m = re.search(r"clock_ctrl\s*#\((.*?)\)\s*u_clk", src, re.S)
    assert m, "bob_fpga.v does not instantiate clock_ctrl with parameters"
    assert re.search(r"\.GAP_SHIFT\s*\(\s*GCE_MIN_GAP_SHIFT\s*\)", m.group(1)), (
        "GAP_SHIFT must come from GCE_MIN_GAP_SHIFT (= `BOB_GCE_MIN_GAP_SHIFT`); "
        f"it is currently {m.group(1).strip()}")


def test_the_generated_header_carries_both_clock_shifts():
    vh = open(os.path.join(HW, "src", "generated", "bob_params.vh")).read()
    d = _device()["clock"]
    for macro, key in (("BOB_DIV_MIN_SHIFT", "div_min_shift"),
                       ("BOB_GCE_MIN_GAP_SHIFT", "gce_min_gap_shift")):
        m = re.search(rf"`define\s+{macro}\s+(\d+)", vh)
        assert m, f"bob_params.vh lacks {macro}"
        assert int(m.group(1)) == d[key], f"{macro} is {m.group(1)}, device.json says {d[key]}"


def test_the_free_running_clock_cannot_outrun_the_gap():
    """The divider floor must be at least the gap, or the fabric would be asked for
    edges closer together than the multicycle exception promises."""
    c = _device()["clock"]
    assert c["div_min_shift"] >= c["gce_min_gap_shift"], (
        f"DIV_MIN_SHIFT {c['div_min_shift']} < GCE_MIN_GAP_SHIFT {c['gce_min_gap_shift']}: "
        "the free-running clock would beat the timing exception")


def test_the_tck_period_is_the_one_device_py_names_and_the_probe_obeys():
    """M25: TCK constrained at 1 MHz: the XDC period, device.py and the probe's ceiling agree"""
    want = _device()["clock"]["xdc_tck_period_ns"]
    m = re.search(r"^create_clock\s+-period\s+([\d.]+)\s+-name\s+tck", _xdc(), re.M)
    assert m and float(m.group(1)) == want, f"XDC tck period {m and m.group(1)}, device.py {want}"
    sys.path.insert(0, os.path.join(ROOT, "software", "host"))
    import dirtyjtag
    assert dirtyjtag.MAX_TCK_KHZ == round(1e6 / want)
