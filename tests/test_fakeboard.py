"""
software/host/fakeboard.py: the software board, and proof it is the one the tests already trust.

FakeBob was written inside tests/test_hwtest_fake.py, where every hardware check runs
against it with a passing and a failing case. software/host/fakeboard.py carries the same class
so tools that are not pytest - bob studio, a --probe fake flag - can use it. While M16
is in flight the test module keeps its own copy, so the job here is to prove the two
answer identically: same scan sequence, same bits out. When the next milestone's tree
folds them together these tests keep guarding the survivor.
"""

import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402
import cfgplane  # noqa: E402
import fakeboard  # noqa: E402
import fpga  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("yosys") is None or shutil.which("iverilog") is None,
                               reason="needs yosys and iverilog")

# dirtyjtag.Probe's surface, as the rest of software/host/ uses it.
SURFACE = ("shift_ir", "shift_dr", "shift_dr_fast", "pulse", "reset_to_idle",
           "read_idcode", "set_freq_khz")


def _test_module_fakebob():
    """What tests/test_hwtest_fake.py drives every hardware check against. It imported
    its own copy until the class moved here; this must stay the same class, so the
    checks that guard FakeBob go on guarding the one the tools use."""
    import test_hwtest_fake
    return test_hwtest_fake.FakeBob


# CAPTURE and SAMPLE read the fabric, so they only mean anything once a design is
# loaded; the rest answer from an unconfigured board.
COLD = (("IDCODE", 32), ("USERCODE", 32), ("BRAM", 96), ("DSP", 256))
LIVE = (("CAPTURE", B.NCLB), ("SAMPLE", 2 * B.NPAD))


def _scan(p, seq=COLD):
    """One fixed sequence over the instructions the host tools actually use.
    Returns every value the board shifted back, so any divergence shows up."""
    out = [p.read_idcode()]
    p.reset_to_idle()
    for name, width in seq:
        out.append(p.shift_ir(cfgplane.IR[name]))
        out.append(p.shift_dr_fast(width, 0))
    out.append(p.pulse(tms=1))
    out.append(p.pulse(tms=0, tdi=1))
    return out


def test_the_hardware_checks_drive_this_very_class():
    assert _test_module_fakebob() is fakeboard.FakeBob, (
        "tests/test_hwtest_fake.py has its own FakeBob again: the checks that prove the "
        "stand-in can fail would no longer be proving it about the one the tools use")


def test_the_two_copies_answer_identically():
    mine, theirs = fakeboard.FakeBob(), _test_module_fakebob()()
    assert _scan(mine) == _scan(theirs)


def test_the_two_copies_agree_on_a_real_load(tmp_path):
    """A whole M16 design through the frame path on each copy."""
    import cli
    bit = str(tmp_path / "counter.bit")
    cli.build([os.path.join(ROOT, "work", "examples", "counter", "counter.v")], out=bit, log=lambda *_: None)
    mine, theirs = fakeboard.FakeBob(), _test_module_fakebob()()
    a = cli.load(mine, bit, mode="frames")
    b = cli.load(theirs, bit, mode="frames")
    assert a == b
    assert a[0], a[1]
    # and with a design in the fabric, the instructions that read it back
    assert _scan(mine, LIVE) == _scan(theirs, LIVE)


def test_it_keeps_the_methods_the_checks_call():
    pub = {n for n in dir(fakeboard.FakeBob) if not n.startswith("_")}
    assert {"shift_ir", "shift_dr", "shift_dr_fast", "read_idcode"} <= pub


def test_it_offers_the_probe_surface():
    p = fakeboard.FakeBob()
    missing = [m for m in SURFACE if not callable(getattr(p, m, None))]
    assert not missing, f"FakeBob cannot stand in for dirtyjtag.Probe: {missing}"


def test_it_reports_the_device_this_tree_describes():
    assert fakeboard.FakeBob().read_idcode() == fpga.IDCODE_FABRIC


def test_set_freq_khz_is_accepted_and_does_nothing():
    assert fakeboard.FakeBob().set_freq_khz(100) is None


# --- the probe factory -------------------------------------------------------


def test_probe_fake_needs_no_hardware():
    assert isinstance(fakeboard.probe("fake"), fakeboard.FakeBob)


def test_probe_passes_options_through():
    assert fakeboard.probe("fake", corrupt_capture=True).corrupt_capture is True


def test_probe_refuses_an_unknown_kind():
    with pytest.raises(ValueError):
        fakeboard.probe("serial")


# --- it must still be able to fail -------------------------------------------


def test_a_broken_board_still_fails_its_check(tmp_path):
    """The stand-in is only useful if a wrong answer is caught: corrupt CAPTURE must
    break the check that reads it, exactly as it does in tests/test_hwtest_fake.py."""
    import hwtest
    ok, _msg = hwtest._bob_check("counter")(fakeboard.probe("fake"), {})
    assert ok
    bad, msg = hwtest._bob_check("counter")(fakeboard.probe("fake", corrupt_capture=True), {})
    assert not bad, f"a corrupt CAPTURE went unnoticed: {msg}"
