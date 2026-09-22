"""
software/bob/project.py: a bob project (M18).

A project is a folder with a .bobproj file anywhere on disk. What matters is that it
turns into the same flow `./bob build` runs: the last tests hold a project build and a
command-line build to a byte-identical .bit. The rest checks the folder, the paths
(relative, so the folder can move), the top, and that two projects never share a result.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import cli  # noqa: E402
import flow  # noqa: E402
import project as P  # noqa: E402

needs_tools = pytest.mark.skipif(shutil.which("yosys") is None or shutil.which("iverilog") is None,
                                 reason="needs yosys and iverilog")

COUNTER = os.path.join(ROOT, "work", "examples", "counter", "counter.v")
GATES = os.path.join(ROOT, "work", "examples", "gates", "gates.v")
GATES_PCF = os.path.join(ROOT, "work", "examples", "gates", "gates_swapped.pcf")


@pytest.fixture(autouse=True)
def _no_recent(tmp_path, monkeypatch):
    """Recent projects go to ~/.bob; a test must not write the user's."""
    monkeypatch.setattr(P, "RECENT", str(tmp_path / "recent.json"))


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# --- the folder and the file ------------------------------------------------------


def test_new_project_makes_the_folder_and_the_project_file(tmp_path):
    p = P.Project.create(tmp_path, "demo")
    assert p.path == str(tmp_path / "demo" / "demo.bobproj")
    for sub in P.SUBDIRS:
        assert (tmp_path / "demo" / sub).is_dir()
    d = json.load(open(p.path))
    assert d["bobproj"] == P.VERSION and d["name"] == "demo" and d["top"] is None
    assert d["settings"] == P.SETTINGS


@pytest.mark.parametrize("name", ["", "1abc", "a b", "../x", "a/b", "a.b", "x-y"])
def test_a_project_name_must_be_an_identifier(tmp_path, name):
    with pytest.raises(P.ProjectError):
        P.Project.create(tmp_path, name)


def test_a_project_never_overwrites_a_folder(tmp_path):
    (tmp_path / "demo").mkdir()
    with pytest.raises(P.ProjectError, match="already exists"):
        P.Project.create(tmp_path, "demo")


def test_a_project_needs_an_existing_location(tmp_path):
    with pytest.raises(P.ProjectError, match="not a folder"):
        P.Project.create(tmp_path / "nowhere", "demo")


def test_open_by_file_or_folder_and_the_round_trip(tmp_path):
    p = P.Project.create(tmp_path, "demo")
    p.add_source(COUNTER)
    p.add_constraint(GATES_PCF)
    p.set_settings(clock="run", div="7", pnr="python")
    p.save()
    for where in (p.path, p.dir):
        q = P.Project.open(where)
        assert q.data["sources"] == ["src/counter.v"]
        assert q.data["constraints"] == ["constrs/gates_swapped.pcf"]
        assert q.data["active_pcf"] == "constrs/gates_swapped.pcf"
        assert q.data["settings"] == {"clock": "run", "div": 7, "seed": 1, "pnr": "python", "hz": "div"}


def test_open_refuses_what_is_not_a_project(tmp_path):
    bad = tmp_path / "x.bobproj"
    bad.write_text("{not json")
    with pytest.raises(P.ProjectError):
        P.Project.open(bad)
    bad.write_text(json.dumps({"bobproj": 99}))
    with pytest.raises(P.ProjectError, match="version"):
        P.Project.open(bad)
    with pytest.raises(P.ProjectError):
        P.Project.open(COUNTER)


def test_sources_are_copied_in_or_referenced(tmp_path):
    p = P.Project.create(tmp_path, "demo")
    assert p.add_source(COUNTER) == "src/counter.v"
    assert (tmp_path / "demo" / "src" / "counter.v").read_text() == open(COUNTER).read()
    assert p.add_source(GATES, copy=False) == GATES          # outside: kept absolute
    assert p.hdl_files() == [str(tmp_path / "demo" / "src" / "counter.v"), GATES]
    with pytest.raises(P.ProjectError, match="already exists"):
        p.add_source(COUNTER)                                # a second copy would shadow the first


def test_a_source_must_be_hdl_and_exist(tmp_path):
    p = P.Project.create(tmp_path, "demo")
    with pytest.raises(P.ProjectError, match="source is one of"):
        p.add_source(GATES_PCF)
    with pytest.raises(P.ProjectError, match="does not exist"):
        p.add_source(str(tmp_path / "nope.v"))
    with pytest.raises(P.ProjectError, match=r"\.pcf"):
        p.add_constraint(COUNTER)


def test_remove_takes_a_file_out_but_leaves_it_on_disk(tmp_path):
    p = P.Project.create(tmp_path, "demo")
    p.add_source(COUNTER)
    p.add_constraint(GATES_PCF)
    p.remove("constrs/gates_swapped.pcf")
    assert p.data["active_pcf"] is None and p.data["constraints"] == []
    assert (tmp_path / "demo" / "constrs" / "gates_swapped.pcf").exists()
    with pytest.raises(P.ProjectError):
        p.remove("src/nothing.v")


def test_settings_are_checked(tmp_path):
    p = P.Project.create(tmp_path, "demo")
    for bad in ({"clock": "fast"}, {"pnr": "magic"}, {"colour": 1}):
        with pytest.raises(P.ProjectError):
            p.set_settings(**bad)


# --- modules and the top -----------------------------------------------------------


@needs_tools
def test_modules_are_read_with_ports_and_parameters(tmp_path):
    p = P.Project.create(tmp_path, "demo")
    src = tmp_path / "two.v"
    src.write_text("module a #(parameter W = 4) (input wire clk, input wire [W-1:0] d, output wire y);\n"
                   "  assign y = ^d;\nendmodule\n"
                   "module b (input wire x, output wire [1:0] z); assign z = {x, x}; endmodule\n")
    p.add_source(str(src))
    mods = {m["name"]: m for m in p.modules()}
    assert set(mods) == {"a", "b"}
    assert mods["a"]["params"] == {"W": 4}
    assert {q["name"]: (q["dir"], q["width"]) for q in mods["a"]["ports"]} == \
        {"clk": ("input", 1), "d": ("input", 4), "y": ("output", 1)}
    assert [q["width"] for q in P.ports(p.hdl_files(), "a", {"W": 9}) if q["name"] == "d"] == [9]
    p.set_top("b")
    assert p.data["top"] == "b"
    with pytest.raises(P.ProjectError, match="no module"):
        p.set_top("c")


@needs_tools
def test_a_broken_source_is_the_users_error_not_a_crash(tmp_path):
    p = P.Project.create(tmp_path, "demo")
    src = tmp_path / "bad.v"
    src.write_text("module bad (input a; endmodule\n")
    p.add_source(str(src))
    with pytest.raises(P.ProjectError, match="yosys"):
        p.modules()
    assert p.to_json()["modules_error"]


def test_the_build_needs_sources_and_a_top(tmp_path):
    p = P.Project.create(tmp_path, "demo")
    with pytest.raises(P.ProjectError, match="no design sources"):
        p.flow_kwargs()
    p.add_source(COUNTER)
    with pytest.raises(P.ProjectError, match="no top"):
        p.flow_kwargs()


def test_a_missing_source_names_the_project_entry(tmp_path):
    p = P.Project.create(tmp_path, "demo")
    p.add_source(COUNTER)
    os.remove(tmp_path / "demo" / "src" / "counter.v")
    with pytest.raises(P.ProjectError, match="src/counter.v is in the project but not on disk"):
        p.hdl_files()


# --- what the flow sees --------------------------------------------------------------


def test_two_projects_with_the_same_top_never_share_a_result(tmp_path):
    names = set()
    for n in ("alpha", "beta"):
        p = P.Project.create(tmp_path, n)
        p.add_source(COUNTER)
        p.data["top"] = "counter"
        names.add(p.flow_kwargs()["name"])
    assert names == {"alpha_counter", "beta_counter"}
    p = P.Project.create(tmp_path, "demo")
    p.data["top"] = "demo_bd_wrapper"
    assert p.result_name() == "demo_bd_wrapper"          # already names the project
    p.data["top"] = "demo2_wrapper"
    assert p.result_name() == "demo_demo2_wrapper"       # demo2 is another project's name


def test_a_moved_project_still_opens_and_builds_from_its_new_place(tmp_path):
    p = P.Project.create(tmp_path / "", "demo")
    p.add_source(COUNTER)
    p.add_constraint(GATES_PCF)
    p.data["top"] = "counter"
    p.save()
    shutil.move(str(tmp_path / "demo"), str(tmp_path / "moved"))
    q = P.Project.open(tmp_path / "moved" / "demo.bobproj")
    kw = q.flow_kwargs()
    assert kw["files"] == [str(tmp_path / "moved" / "src" / "counter.v")]
    assert kw["pcf"] == str(tmp_path / "moved" / "constrs" / "gates_swapped.pcf")
    assert kw["out"] == str(tmp_path / "moved" / "build" / "demo.bit")
    assert all(os.path.exists(f) for f in kw["files"])


def test_cli_reads_a_bobproj_as_the_project_says(tmp_path):
    p = P.Project.create(tmp_path, "demo")
    p.add_source(COUNTER)
    p.data["top"] = "counter"
    p.save()
    assert cli.read_project(p.path) == p.flow_kwargs()
    with pytest.raises(cli.BuildError):
        cli.read_project(str(tmp_path / "nope.bobproj"))


def test_recent_projects_are_remembered_newest_first(tmp_path):
    a = P.Project.create(tmp_path, "a")
    b = P.Project.create(tmp_path, "b")
    assert P.recent()[:2] == [b.path, a.path]
    a.save()
    assert P.recent()[0] == a.path
    shutil.rmtree(tmp_path / "b")
    assert b.path not in P.recent()                       # gone from disk, gone from the list


@needs_tools
def test_a_project_build_and_bob_build_write_the_same_bit(tmp_path):
    """The project is only a way of naming the flow's arguments: the command line and
    the project must produce one bitstream, byte for byte."""
    p = P.Project.create(tmp_path, "demo")
    p.add_source(COUNTER)
    p.set_top("counter")
    p.set_settings(pnr="python")
    p.save()
    kw = p.flow_kwargs()
    res = flow.Flow(**kw).run()
    assert res.ok, res.error
    assert res.bit == str(tmp_path / "demo" / "build" / "demo.bit")
    other = str(tmp_path / "cli.bit")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "software", "bob", "cli.py"), "build",
                        "--project", p.path, "-o", other], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _sha(other) == _sha(res.bit)
    # and the plain command line, given the same files and name, agrees too
    third = str(tmp_path / "plain.bit")
    cli.build(kw["files"], top="counter", out=third, name=kw["name"], pnr="python", log=lambda *_: None)
    assert _sha(third) == _sha(res.bit)


def test_the_hz_setting_reaches_the_flow_only_with_the_free_running_clock(tmp_path):
    """M20: hz "auto" (or a rate) times the design's own clock; with clock jtag, or hz "div",
    the flow is asked for nothing new, so older projects build exactly as before."""
    p = P.Project.create(tmp_path, "demo")
    p.add_source(COUNTER)
    p.data["top"] = "counter"
    assert p.flow_kwargs()["hz"] is None                      # the default: div
    p.set_settings(hz="auto")
    assert p.flow_kwargs()["hz"] is None                      # still clock jtag
    p.set_settings(clock="run")
    assert p.flow_kwargs()["hz"] == "auto"
    p.set_settings(hz="2.5e6")
    assert p.flow_kwargs()["hz"] == "2.5e6"
    p.set_settings(hz="div")
    assert p.flow_kwargs()["hz"] is None
    for bad in ("fast", "-3", "0"):
        with pytest.raises(P.ProjectError, match="hz is"):
            p.set_settings(hz=bad)



def test_a_clock_constraint_is_a_constraint_file_and_sets_the_clock(tmp_path):
    """M20: Create clock constraint writes constrs/<name>.sdc; a project with one builds on
    the free-running clock against it. One per project, and never an 'active pin file'."""
    p = P.Project.create(tmp_path, "demo")
    p.add_source(COUNTER)
    p.data["top"] = "counter"
    rel = p.set_clock(mhz=5)
    assert rel == "constrs/demo.sdc" and rel in p.data["constraints"]
    assert "create_clock -period 200.000 -name clk [get_ports clk]" in open(p.abs(rel)).read()
    assert p.data["active_pcf"] is None                         # a .sdc is not a pin file
    kw = p.flow_kwargs()
    assert kw["sdc"] == p.abs(rel) and kw["clock"] == "run" and kw["hz"] is None
    assert p.set_clock(period_ns=80) == rel                     # changing the clock rewrites it
    assert "-period 80.000" in open(p.abs(rel)).read()
    assert p.to_json(with_modules=False)["clock_constraint"]["period_ns"] == 80.0
    with pytest.raises(P.ProjectError, match="not a pin file"):
        p.set_active_pcf(rel)
    other = tmp_path / "other.sdc"
    other.write_text("create_clock -period 50 [get_ports clk]\n")
    p.add_constraint(str(other))
    with pytest.raises(P.ProjectError, match="two clock constraints"):
        p.flow_kwargs()
    p.remove("constrs/other.sdc")
    p.remove(rel)
    assert p.flow_kwargs()["sdc"] is None and p.flow_kwargs()["clock"] == "jtag"
