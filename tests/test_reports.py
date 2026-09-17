"""
Vivado reports copied back from the build machine (docs/reports/<tag>/) must
show a real, analysed build - not just a bitstream.

A build can write a working bitstream while its constraints were silently
ignored (M0, first build: TCK had no clock, WNS was NA, and the report still
said "all constraints met"). These checks make that impossible to miss.
"""

import glob
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = sorted(d for d in glob.glob(os.path.join(ROOT, "docs", "reports", "M*"))
                 if os.path.isfile(os.path.join(d, "timing.rpt")))


def _read(d, name):
    p = os.path.join(d, name)
    return open(p, errors="replace").read() if os.path.exists(p) else ""


@pytest.mark.parametrize("d", REPORTS, ids=[os.path.basename(d) for d in REPORTS])
def test_tck_is_actually_constrained(d):
    t = _read(d, "timing.rpt")
    m = re.search(r"checking no_clock \((\d+)\)", t)
    assert m and m.group(1) == "0", f"{m.group(1) if m else '?'} register clock pins have no clock"
    assert re.search(r"^tck\s+\{", t, re.M), "no 'tck' clock in the clock summary"


@pytest.mark.parametrize("d", REPORTS, ids=[os.path.basename(d) for d in REPORTS])
def test_bram_is_a_real_ramb18_from_m5(d):
    """From M5 the BRAM tile must map to a block RAM primitive, not LUTs/flops."""
    if int(os.path.basename(d)[1:]) < 5:
        pytest.skip("no BRAM tile before M5")
    util = _read(d, "util.rpt")
    m = re.search(r"^\|\s*RAMB18\s*\|\s*([0-9.]+)", util, re.M)
    assert m and float(m.group(1)) >= 1, "util.rpt shows no RAMB18"


@pytest.mark.parametrize("d", REPORTS, ids=[os.path.basename(d) for d in REPORTS])
def test_dsp_is_a_real_dsp48_from_m6(d):
    """From M6 the DSP tile's multipliers must map to DSP48E1 blocks."""
    if int(os.path.basename(d)[1:]) < 6:
        pytest.skip("no DSP tile before M6")
    util = _read(d, "util.rpt")
    m = re.search(r"^\|\s*DSPs\s*\|\s*([0-9.]+)", util, re.M)
    assert m and float(m.group(1)) >= 1, "util.rpt shows no DSP48E1"


@pytest.mark.parametrize("d", REPORTS, ids=[os.path.basename(d) for d in REPORTS])
def test_no_constraint_file_critical_warnings(d):
    logs = _read(d, "synth_1.log") + _read(d, "impl_1.log")
    bad = sorted(set(re.findall(
        r"CRITICAL WARNING: \[(?:Designutils 20-1307|Common 17-1548|Vivado 12-4739)\][^\n]*", logs)))
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("d", REPORTS, ids=[os.path.basename(d) for d in REPORTS])
def test_timing_closes_from_m13(d):
    """M7 reported WNS -1102 ns (TNS -1.6e6 ns): paths through unconfigured routing loops
    under 120-cycle multicycles that synthesis had renamed away, and a TCK path under a
    1 MHz clock. M13 guarantees the 256-cycle gce gap in RTL, relaxes sysclk by clock
    and constrains TCK at 100 kHz, so setup and hold must close, and every multicycle
    must name real cells (docs/bitstream-format.md section 11)."""
    if int(os.path.basename(d)[1:]) < 13:
        pytest.skip("timing closure is an M13 requirement")
    t = _read(d, "timing.rpt")
    m = re.search(r"WNS\(ns\)\s+TNS\(ns\).*?\n[-\s]+\n\s*(-?[0-9.]+)\s+(-?[0-9.]+)\s+(\d+)\s+\d+\s+(-?[0-9.]+)",
                  t, re.S)
    assert m, "no Design Timing Summary in timing.rpt"
    wns, tns, failing, whs = float(m.group(1)), float(m.group(2)), int(m.group(3)), float(m.group(4))
    assert wns >= 0 and failing == 0, f"setup: WNS {wns} ns, TNS {tns} ns, {failing} failing endpoints"
    assert whs >= 0, f"hold: WHS {whs} ns"
    logs = _read(d, "synth_1.log") + _read(d, "impl_1.log")
    assert "No valid object" not in logs, "a timing constraint names no cells (see the logs)"


@pytest.mark.parametrize("d", REPORTS, ids=[os.path.basename(d) for d in REPORTS])
def test_single_cycle_filter_caught_its_registers(d):
    """From M13 sysclk -> sysclk is 256 cycles by clock, and only u_clk / u_bram_jtag are
    held to one cycle, by name, in a flattened netlist. gce (the one-cycle enable of every
    fabric register) and the BRAM INIT strobes must still carry those names."""
    if int(os.path.basename(d)[1:]) < 13:
        pytest.skip("the by-clock multicycle is an M13 constraint")
    cells = _read(d, "sysclk_1cycle.txt")
    for want in ("u_clk/gce_reg", "u_bram_jtag/init_go_reg", "u_bram_jtag/rdata_reg"):
        assert want in cells, f"{want} was renamed out of the XDC single-cycle filter"
