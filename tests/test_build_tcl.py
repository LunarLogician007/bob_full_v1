"""
hw/scripts/build.tcl, run under tclsh against tests/tcl/vivado_stub.tcl.

These are the behaviours the Vivado machine relies on: paste a new hw/ over the
old one and re-run, without deleting the project.
"""

import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HW = os.path.join(ROOT, "hw")
STUB = os.path.join(ROOT, "tests", "tcl", "vivado_stub.tcl")

pytestmark = pytest.mark.skipif(shutil.which("tclsh") is None, reason="needs tclsh")


def run_build(hw_dir, *args, state):
    driver = (
        f"source {{{STUB}}}\n"
        f"set argv [list {' '.join('{' + a + '}' for a in args)}]\n"
        f"set argc [llength $argv]\n"
        f"source {{{os.path.join(hw_dir, 'scripts', 'build.tcl')}}}\n"
    )
    # Run from a file, not stdin: interactive tclsh reports an error and carries
    # on with exit status 0, which would hide every failure in build.tcl.
    drv = state + ".driver.tcl"
    with open(drv, "w") as fh:
        fh.write(driver)
    env = dict(os.environ, BOB_STUB_STATE=state)
    r = subprocess.run(["tclsh", drv], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _tag():
    with open(os.path.join(HW, "build.cfg")) as fh:
        for ln in fh:
            m = re.match(r"\s*tag\s*=\s*(\S+)", ln)
            if m:
                return m.group(1)
    raise AssertionError("no tag in build.cfg")


TAG = _tag()
CFG = dict(re.findall(r"^\s*(\w+)\s*=\s*(\S+)",
                      open(os.path.join(HW, "build.cfg")).read(), re.M))


@pytest.fixture
def site(tmp_path):
    """A pasted copy of hw/ with the project next to it, as on the Windows box."""
    hw = tmp_path / "site" / "hw"
    shutil.copytree(HW, hw)
    return hw, str(tmp_path / "stub_state.tcl")


def n_sources():
    with open(os.path.join(HW, "sources.f")) as fh:
        return sum(1 for ln in fh if ln.split("#")[0].strip())


def test_first_build_creates_project_and_outputs(site):
    hw, state = site
    out = run_build(str(hw), state=state)
    assert "STUB: create_project" in out
    assert out.count("STUB: add_files sources_1") == n_sources()
    assert "STUB: launch_runs impl_1" in out
    proj = hw.parent / "bob_vivado"
    assert (proj / "bob.xpr").exists()
    bit = proj / "out" / TAG / f"{CFG['top']}.bit"
    assert bit.exists()
    assert f"IDCODE_VALUE=32'h{CFG['idcode']}" in bit.read_text()
    if "usercode" in CFG:
        assert f"USERCODE_VALUE=32'h{CFG['usercode']}" in bit.read_text()
    info = (proj / "out" / TAG / "build_info.txt").read_text()
    assert re.search(r"fingerprint\s+[0-9a-f]{8}", info)


def test_rerun_unchanged_reuses_project_and_skips_build(site):
    hw, state = site
    run_build(str(hw), state=state)
    out = run_build(str(hw), state=state)
    assert "STUB: open_project" in out and "STUB: create_project" not in out
    assert "STUB: add_files" not in out and "STUB: remove_files" not in out
    assert "skipping" in out and "STUB: launch_runs" not in out


def test_edit_rebuilds_without_recreating(site):
    hw, state = site
    run_build(str(hw), state=state)
    f = hw / "src" / "clb" / "clb.sv"
    f.write_text(f.read_text() + "\n// edited\n")
    out = run_build(str(hw), state=state)
    assert "STUB: create_project" not in out
    assert "inputs changed" in out and "STUB: launch_runs impl_1" in out


def test_crlf_copy_does_not_force_rebuild(site):
    hw, state = site
    run_build(str(hw), state=state)
    f = hw / "src" / "core" / "bsc_cell.v"
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert "skipping" in run_build(str(hw), state=state)


def test_new_and_dropped_files_are_synced(site):
    hw, state = site
    run_build(str(hw), state=state)
    (hw / "src" / "core" / "new_block.v").write_text("module new_block; endmodule\n")
    srcf = hw / "sources.f"
    text = srcf.read_text().replace("src/fabric/mini_fpga.v\n", "")
    srcf.write_text(text + "src/core/new_block.v\n")
    out = run_build(str(hw), state=state)
    assert re.search(r"STUB: add_files sources_1 \S+/src/core/new_block\.v", out)
    assert re.search(r"STUB: remove_files sources_1 \S+/src/fabric/mini_fpga\.v", out)
    assert "STUB: create_project" not in out


def test_hw_pasted_somewhere_else_swaps_paths(site, tmp_path):
    hw, state = site
    proj = tmp_path / "shared_proj"
    run_build(str(hw), f"project={proj}", state=state)
    moved = tmp_path / "elsewhere" / "hw"
    shutil.copytree(hw, moved)
    out = run_build(str(moved), f"project={proj}", state=state)
    assert out.count("STUB: remove_files sources_1") == n_sources()
    assert out.count("STUB: add_files sources_1") == n_sources()
    assert str(moved) in out


def test_status_changes_nothing(site):
    hw, state = site
    out = run_build(str(hw), "status", state=state)
    assert "no project yet" in out and "STUB:" not in out
    run_build(str(hw), state=state)
    out = run_build(str(hw), "status", state=state)
    assert "up to date" in out
    assert "STUB: add_files" not in out and "STUB: launch_runs" not in out


def test_gui_style_bob_args(site):
    """The GUI cannot pass -tclargs; 'set bob_args {...}' before source must work."""
    hw, state = site
    driver = (
        f"source {{{STUB}}}\n"
        "namespace eval ::rdi { variable mode gui }\n"
        "set argv {}\n"
        "set bob_args {status}\n"
        f"source {{{os.path.join(str(hw), 'scripts', 'build.tcl')}}}\n"
        "if {[info exists ::bob_args]} { error {bob_args not cleared} }\n"
    )
    drv = state + ".gui.tcl"
    with open(drv, "w") as fh:
        fh.write(driver)
    r = subprocess.run(["tclsh", drv], capture_output=True, text=True,
                       env=dict(os.environ, BOB_STUB_STATE=state))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "action   : status" in r.stdout and "no project yet" in r.stdout


def test_top_override_keeps_rtl_idcode(site):
    hw, state = site
    run_build(str(hw), "force", "top=mini_fpga_top", state=state)
    bit = hw.parent / "bob_vivado" / "out" / TAG / "mini_fpga_top.bit"
    assert "generic=" in bit.read_text() and "IDCODE" not in bit.read_text()


def test_the_build_measures_the_fabric_delays(site):
    """M20: after implementation build.tcl times every sample in delay_samples.txt and
    delays.py folds the reports back into per-class delays."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(HW), "software", "bob"))
    import delays
    hw, state = site
    out = run_build(str(hw), state=state)
    assert "extract_delays:" in out
    rpt = hw.parent / "bob_vivado" / "out" / TAG / "delay_paths.rpt"
    text = rpt.read_text()
    samples = [ln for ln in open(os.path.join(HW, "scripts", "delay_samples.txt")) if ln.strip() and ln[0] != "#"]
    assert text.count("\n### ") + text.startswith("### ") == len(samples)
    d = delays.fold([text], False, "stub")
    for cls in ("mux_chan", "mux_ipin", "carry"):
        assert d["measured"][cls]["max"] == 1.5, cls
    assert d["ns"]["ff_clk_q"] == 1.2
    assert d["ns"]["ff_setup"] == round(max(0.0, 1.05 - d["ns"]["lut"]), 3)


def test_the_delays_are_measured_when_the_netlist_renames_the_fabric(site, monkeypatch):
    """M23: the M22 build returned every sample NOPATH because the flattened netlist filed
    fabric nets under another block (u_core/u_store/u_fabric/...). extract_delays.tcl finds
    them by their path from u_fabric/ on, and the fold reads the renamed nets back."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(HW), "software", "bob"))
    import delays
    hw, state = site
    monkeypatch.setenv("BOB_STUB_RENAME", "1")
    out = run_build(str(hw), state=state)
    assert "indexed" in out
    text = (hw.parent / "bob_vivado" / "out" / TAG / "delay_paths.rpt").read_text()
    assert "NONET" not in text and "u_core/u_store/u_fabric/" in text
    d = delays.fold([text], False, "stub")
    for cls in ("mux_chan", "mux_ipin", "carry"):
        assert d["measured"][cls]["max"] == 1.5, cls
    assert d["ns"]["ff_clk_q"] == 1.2


def test_delays_0_skips_the_measurement(site):
    hw, state = site
    out = run_build(str(hw), "delays=0", state=state)
    assert "extract_delays:" not in out
