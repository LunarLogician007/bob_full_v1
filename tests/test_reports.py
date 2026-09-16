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
