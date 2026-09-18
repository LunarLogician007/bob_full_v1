"""
The device table in the documents is generated, not typed.

The same numbers used to be hand-copied into README.md, PLAN.md, HANDOFF.md, CLAUDE.md,
GUIDE.md and REPORT.md. They drifted: after M16 put 100 CLBs on the board, README.md's
table still described the 36-CLB M12b profile under a heading that said M16. Every
marked block now comes from tools/bob/devtable.py, and this fails if one goes stale.
"""

import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "bob"))
sys.path.insert(0, os.path.join(ROOT, "host"))

import devtable  # noqa: E402


def test_at_least_one_document_carries_the_table():
    assert devtable.apply(write=False), (
        "no document carries the device markers; the table would be hand-written again")


@pytest.mark.parametrize("rel", [r for r, _ in devtable.apply(write=False)])
def test_the_marked_block_is_up_to_date(rel):
    ok = dict(devtable.apply(write=False))[rel]
    assert ok, f"{rel} is stale: run tools/bob/devtable.py --write"


def test_the_table_reports_this_device():
    import bitstream as B
    t = devtable.table()
    assert str(B.NCLB) in t and str(B.CHAIN_W) in t
    assert f"{B.DEVICE['frames']['count']} frames" in t


def test_the_table_reports_the_gap_the_xdc_is_written_against():
    """The user-clock row is the one a reader checks the XDC against, so it must carry
    the gap, not just the divider - they were the same number until M16 split them."""
    f = devtable.facts()
    assert f"2**{f['gap_shift']} = {1 << f['gap_shift']} cycles apart" in devtable.table()


def test_utilisation_comes_from_the_build_that_is_on_the_board():
    """It is read from docs/reports/<tag>/, so it cannot claim a build that never ran."""
    f = devtable.facts()
    if f["luts"] is None:
        pytest.skip(f"no Vivado report for {f['tag']} yet")
    assert f"Vivado, {f['tag']}" in devtable.table()
    assert 0 < f["luts"][1] < 100


def test_a_stale_block_is_detected(tmp_path):
    """The guard has to be able to fail: an edited block must be reported stale."""
    rel = devtable.apply(write=False)[0][0]
    p = os.path.join(ROOT, rel)
    orig = open(p).read()
    try:
        open(p, "w").write(orig.replace("| CLBs |", "| CLBs (edited by hand) |", 1))
        assert not dict(devtable.apply(write=False))[rel], "an edited table went unnoticed"
    finally:
        open(p, "w").write(orig)
    assert dict(devtable.apply(write=False))[rel], "the file was not restored"
