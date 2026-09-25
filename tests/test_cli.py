"""
./bob as a person meets it (software/bob/cli.py and ux.py): what it says with no command,
how a failure reads (the file, the line, the source text, what to do), the resource line of
a build that worked, and the commands that help someone start: new, run, examples, pins,
doctor, info. Every board step here uses --probe fake.
"""

import os
import re
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import cli  # noqa: E402
import flow  # noqa: E402
import ux  # noqa: E402
import vpr_run  # noqa: E402

COUNTER = os.path.join(ROOT, "work", "examples", "counter", "counter.v")


def bob(*args, cwd=None):
    # BOB_RECENT: a project made here must not join the person's recent-projects list
    env = dict(os.environ, NO_COLOR="1", BOB_RECENT=os.path.join(tempfile.gettempdir(), "bob-recent-test.json"))
    r = subprocess.run([os.path.join(ROOT, "bob"), *args], capture_output=True, text=True,
                       cwd=cwd or ROOT, env=env, timeout=900)
    return r.returncode, r.stdout + r.stderr


def test_no_command_is_a_short_guide():
    rc, out = bob()
    assert rc == 0
    for cmd in ("./bob doctor", "./bob examples", "./bob new", "./bob run", "./bob pins", "./bob studio"):
        assert cmd in out, cmd
    assert "required" not in out


def test_help_has_no_milestone_jargon():
    for cmd in ("build", "load", "run", "snap", "new"):
        rc, out = bob(cmd, "-h")
        assert rc == 0 and "examples:" in out, cmd
        assert not re.search(r"\bM\d+\b", out), (cmd, re.findall(r".*\bM\d+\b.*", out))


def test_a_missing_file_is_named_before_anything_runs():
    rc, out = bob("build", "nothere.v")
    assert rc == 1
    assert "nothere.v: no such file" in out and "hint" in out
    assert "yosys" not in out.lower() and "Warning" not in out


def test_a_syntax_error_shows_the_line_once_with_a_hint(tmp_path):
    f = tmp_path / "t.v"
    f.write_text("module t(input clk, output [2:0] led);\n assign led = 3b101;\nendmodule\n")
    rc, out = bob("build", str(f))
    assert rc == 1
    assert out.count("t.v:2:") == 1, out
    assert "2 | assign led = 3b101;" in out
    assert "fix that line and build again" in out
    # none of yosys's bookkeeping about bob's own cell library
    assert "bob_cells_sim" not in out and "$for_loop" not in out
    assert len(out.splitlines()) < 10, out


def test_ports_without_pins_are_named_not_a_missing_vpr_log(tmp_path):
    """Before: a design with ports a, b, y and no .pcf failed with
    '[Errno 2] No such file or directory: .../vpr.log'."""
    f = tmp_path / "odd.v"
    f.write_text("module odd(input clk, input a, input b, output y);\n assign y = a ^ b;\nendmodule\n")
    rc, out = bob("build", str(f))
    assert rc == 1
    assert "a, b, y have no pin" in out and "./bob pins" in out
    assert "Errno" not in out and "vpr.log" not in out


def test_vpr_run_retry_keeps_the_real_error_when_vpr_never_ran(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise vpr_run.VprError("input a has no pin (pcf set_io)")
    monkeypatch.setattr(vpr_run, "run", refuse)
    with pytest.raises(vpr_run.VprError, match="has no pin"):
        vpr_run.run_retry("odd", 1, work=str(tmp_path / "w"))


def test_a_design_too_big_is_refused_with_the_numbers(tmp_path):
    f = tmp_path / "huge.v"
    f.write_text("module huge(input clk, input [1:0] sw, output [2:0] led);\n"
                 " reg [449:0] r = 0;\n always @(posedge clk) r <= {r[448:0], sw[0]};\n"
                 " assign led = {^r[449:300], ^r[299:150], ^r[149:0]};\nendmodule\n")
    res = flow.Flow([str(f)], out=str(tmp_path / "h.bit")).run()
    assert not res.ok
    assert re.search(r"needs 45\d flip-flops \(bob has 400\)", res.error), res.error
    lines = "\n".join(ux.explain(res))
    assert "make the design smaller" in lines


def test_a_build_ends_with_usage_and_the_next_command(tmp_path):
    rc, out = bob("build", COUNTER, "-o", str(tmp_path / "c.bit"))
    assert rc == 0
    assert "flip-flops 6/400" in out and "carry bits 6/400" in out and "BRAMs 0/2" in out
    assert re.search(r"next\s+\./bob load \S+c\.bit", out)


def test_usage_counts_every_resource():
    use = flow.usage({"$lut": 10, "BOB_FDRE": 4, "BOB_ADD": 2, "BOB_BRAM18": 1, "BOB_DSP": 2})
    assert [(u["name"], u["used"], u["cap"]) for u in use] == [
        ("LUTs", 10, 400), ("flip-flops", 4, 400), ("carry bits", 2, 400), ("BRAMs", 1, 2), ("DSPs", 2, 2)]
    assert ux.usage_line(use).startswith("LUTs 10/400 (2%)  flip-flops 4/400 (1%)")


def test_examples_lists_every_example_with_a_line():
    rc, out = bob("examples")
    assert rc == 0
    for d in os.listdir(os.path.join(ROOT, "work", "examples")):
        if os.path.isdir(os.path.join(ROOT, "work", "examples", d)):
            assert re.search(rf"^\s+{d}\s+\S", out, re.M), d
    assert "(M" not in out


def test_pins_names_every_board_pin():
    rc, out = bob("pins")
    assert rc == 0
    for p in ("SW0", "SW1", "BTN0", "BTN3", "LD0", "LD2", "sw[1:0]", "set_io"):
        assert p in out


def test_new_then_run_on_the_fake_board(tmp_path):
    rc, out = bob("new", "blink", cwd=str(tmp_path))
    assert rc == 0, out
    assert (tmp_path / "blink" / "src" / "blink.v").exists()
    assert (tmp_path / "blink" / "blink.bobproj").exists()
    assert "./bob run blink" in out
    rc, out = bob("run", str(tmp_path / "blink"), "--probe", "fake", "--pnr", "python")
    assert rc == 0, out
    assert "PASS  built" in out and "PASS  load" in out and "LEDs" in out


def test_new_from_an_example_and_refusals(tmp_path):
    rc, out = bob("new", "mine", "--from", "counter", cwd=str(tmp_path))
    assert rc == 0 and (tmp_path / "mine" / "src" / "counter.v").exists()
    rc, out = bob("new", "mine", cwd=str(tmp_path))
    assert rc == 1 and "already exists" in out
    rc, out = bob("new", "x", "--from", "nosuch", cwd=str(tmp_path))
    assert rc == 1 and "counter" in out           # lists the examples it could have been
    assert not (tmp_path / "x").exists()          # and makes nothing
    rc, out = bob("new", "9bad", cwd=str(tmp_path))
    assert rc == 1 and "starts with a letter" in out


def test_info_reads_like_a_summary_and_raw_keeps_every_field(tmp_path):
    bit = str(tmp_path / "c.bit")
    cli.build([COUNTER], out=bit, log=lambda *_: None)
    rc, out = bob("info", bit)
    assert rc == 0
    for k in ("design  counter", "work/examples/counter/counter.v", "timing  critical path",
              "clock   stepped over JTAG", "pins    the sw/btn/led defaults"):
        assert k in out, k
    assert "source_sha256" not in out
    rc, raw = bob("info", bit, "--raw")
    assert "source_sha256:" in raw and "fasm_sha256:" in raw


def test_no_pico_is_advice_not_an_exit(monkeypatch):
    import fakeboard

    def gone(*a, **k):
        sys.exit("no DirtyJTAG probe found (expected 1209:c0ca)")
    monkeypatch.setattr(fakeboard, "probe", gone)
    with pytest.raises(cli.BuildError, match="--probe fake"):
        cli.open_board("usb")


def test_load_on_the_fake_board_reads_the_leds(tmp_path):
    bit = str(tmp_path / "c.bit")
    cli.build([COUNTER], out=bit, log=lambda *_: None)
    rc, out = bob("load", bit, "--probe", "fake")
    assert rc == 0 and "PASS  load" in out and "LD2..0 =" in out


def test_hints():
    assert any("colima start" in h for h in ux.hints("docker not found", "pnr"))
    assert any("--seed" in h for h in ux.hints("VPR failed on x: Routing failed", "pnr"))
    assert any("--hz auto" in h for h in ux.hints("slack -3.2 ns: does not meet", "timing"))
    assert ux.hints("all fine", "synth") == []


def test_doctor_reports_each_tool_and_how_to_fix_it():
    rows = ux.doctor(board=False)
    names = [r[1] for r in rows]
    for want in ("python", "yosys", "iverilog", "docker"):
        assert want in names
    text = ux.doctor_text([(True, "yosys", "0.69", ""), (False, "iverilog", "not found", "brew install x"),
                           (None, "docker", "not running", "colima start")])
    assert "FAIL" in text and "-> brew install x" in text and "-> colima start" in text
    assert "1 problem(s)" in text


def test_colour_only_on_a_terminal(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert ux.paint("x", "ok") == "x"
    assert ux.paint("x", "ok", on=True) == "\033[32mx\033[0m"
