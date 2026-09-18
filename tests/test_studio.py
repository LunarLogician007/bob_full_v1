"""
host/studio.py: the backend behind bob studio.

The page is thin on purpose - every route drives tools/bob/flow.py or host/cfgplane.py
and reports what they return - so testing the routes is most of testing the app. These
run against the board in software, so they need no hardware and no Docker.
"""

import json
import os
import shutil
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "bob"))
sys.path.insert(0, os.path.join(ROOT, "host"))

import bitstream as B  # noqa: E402
import studio  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("yosys") is None or shutil.which("iverilog") is None,
                                reason="needs yosys and iverilog")


@pytest.fixture(scope="module")
def srv():
    os.environ["BOB_STUDIO_QUIET"] = "1"
    s = ThreadingHTTPServer(("127.0.0.1", 0), studio.Handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()
    s.server_close()


def get(srv, path, timeout=180):
    with urllib.request.urlopen(srv + path, timeout=timeout) as r:
        return json.load(r)


def post(srv, path, body, timeout=300):
    rq = urllib.request.Request(srv + path, data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(rq, timeout=timeout) as r:
        return json.load(r)


def _repo_copy(path):
    """VPR and yosys read paths inside the repo, so a temp source is copied into
    build/ (scratch, gitignored) before it is built."""
    dst = os.path.join(ROOT, "build", "tests", os.path.basename(path))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy(path, dst)
    return dst


def build(srv, spec, timeout=300):
    """Start a build and drain its event stream. -> the final event."""
    job = post(srv, "/api/build", spec)["job"]
    with urllib.request.urlopen(f"{srv}/api/events/{job}", timeout=timeout) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            if ev["event"] in ("done", "failed"):
                return ev
    raise AssertionError("the event stream ended without a result")


# --- what the page reads at boot ---------------------------------------------


def test_device_matches_the_device_description(srv):
    d = get(srv, "/api/device")
    assert d["name"] == B.DEVICE["name"]
    assert d["chain_w"] == B.CHAIN_W
    assert d["capacity"]["clb"] == B.NCLB
    assert d["frames"] == B.DEVICE["frames"]["count"]
    assert len(d["blocks"]) == len(B.DEVICE["blocks"])


def test_examples_are_listed(srv):
    ex = get(srv, "/api/examples")
    assert {e["name"] for e in ex} >= {"gates", "counter", "fir"}
    assert all(e["lines"] > 0 for e in ex)


def test_a_source_file_can_be_read(srv):
    r = get(srv, "/api/source?path=examples/gates.v")
    assert "module gates" in r["text"]


# --- a build, over HTTP ------------------------------------------------------


def test_a_build_streams_its_stages_and_lands_a_bitstream(srv):
    ev = build(srv, {"files": ["examples/gates.v"]})
    assert ev["event"] == "done" and ev["ok"], ev.get("error")
    assert [s["name"] for s in ev["stages"]] == list(__import__("flow").STAGES)
    assert all(s["ok"] for s in ev["stages"])
    bit = ev["stages"][-1]["stats"]["path"]
    assert os.path.exists(os.path.join(ROOT, bit))


def test_a_build_reports_where_the_design_landed(srv):
    ev = build(srv, {"files": ["examples/fir.v"]})
    pl = ev["placement"]
    assert pl and pl["blocks"], "no placement came back"
    kinds = {b["type"] for b in pl["blocks"]}
    assert "clb" in kinds
    assert all(0 <= b["x"] < B.DEVICE["arch"]["grid_width"] for b in pl["blocks"])
    assert all(0 <= b["y"] < B.DEVICE["arch"]["grid_height"] for b in pl["blocks"])
    assert pl["wirelength"] > 0 and pl["nets"]


def test_a_build_with_no_sources_is_refused(srv):
    with pytest.raises(urllib.error.HTTPError) as e:
        post(srv, "/api/build", {"files": []})
    assert e.value.code == 400


def test_a_build_with_a_bad_engine_is_refused_before_it_starts(srv):
    with pytest.raises(urllib.error.HTTPError) as e:
        post(srv, "/api/build", {"files": ["examples/gates.v"], "pnr": "nonsense"})
    assert e.value.code == 400


def test_a_source_outside_the_repo_is_refused(srv):
    with pytest.raises(urllib.error.HTTPError) as e:
        post(srv, "/api/build", {"files": ["../../../etc/passwd"]})
    assert e.value.code == 400


def test_an_unknown_job_is_not_found(srv):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(srv, "/api/job/deadbeef")
    assert e.value.code == 404


# --- the target --------------------------------------------------------------


def test_the_software_board_can_be_opened_and_reports_this_device(srv):
    t = post(srv, "/api/target", {"kind": "fake"})
    assert t["kind"] == "fake"
    assert t["match"], f"{t['idcode']} != {t['expected']}"


def test_programming_the_software_board_and_reading_it_back(srv):
    ev = build(srv, {"files": ["examples/counter.v"]})
    assert ev["ok"], ev.get("error")
    post(srv, "/api/target", {"kind": "fake"})
    r = post(srv, "/api/program", {"bit": ev["stages"][-1]["stats"]["path"], "mode": "frames"})
    assert r["ok"], r["message"]
    assert "readback verified" in r["message"]
    b = get(srv, "/api/board")
    assert b["open"] and b["match"] and b["simulated"]
    assert b["status"]["done"] == 1


def test_programming_a_bitstream_outside_the_repo_is_refused(srv):
    post(srv, "/api/target", {"kind": "fake"})
    with pytest.raises(urllib.error.HTTPError) as e:
        post(srv, "/api/program", {"bit": "/etc/passwd"})
    assert e.value.code == 400


def test_the_simulated_clock_cannot_run_away(srv):
    """DemoBoard bounds how many guest edges one scan may simulate; without that a
    free-running design makes the board stop answering (one edge is a model.settle)."""
    board = studio.DemoBoard()
    assert board.BUDGET > 0
    assert board.skipped == 0
    assert board._per_edge > 0


# --- the page must not be able to reach outside the repo ----------------------


@pytest.mark.parametrize("name", ["../../../../tmp/pwned", "/etc/passwd", "..", "", "a/b/c"])
def test_a_pcf_name_cannot_escape_the_build_directory(srv, name):
    """`name` comes from the page and used to be pasted straight into a path, so
    "../../../x" wrote outside the repo. It names a file in build/pcf/, nothing more."""
    r = post(srv, "/api/pcf", {"name": name, "assign": {"led[0]": "LD0"}})
    out = os.path.realpath(os.path.join(ROOT, r["pcf"]))
    assert out.startswith(os.path.realpath(os.path.join(ROOT, "build", "pcf")) + os.sep), out
    assert os.path.exists(out)


def test_a_source_path_cannot_escape_the_repo(srv):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(srv, "/api/source?path=" + urllib.parse.quote("../../../../etc/passwd"))
    assert e.value.code == 404


def test_a_fasm_path_cannot_escape_the_repo(srv):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(srv, "/api/fasm?bit=" + urllib.parse.quote("/etc/passwd"))
    assert e.value.code == 400


def test_finished_jobs_do_not_accumulate_forever(srv):
    """A long session should not hold every build it ever ran."""
    assert studio.MAX_JOBS > 0
    for i in range(studio.MAX_JOBS + 5):
        j = studio.Job({"files": []})
        j.done.set()
        studio._remember(j)
    assert len(studio.JOBS) <= studio.MAX_JOBS


# --- your own designs ---------------------------------------------------------


def test_a_new_design_is_scaffolded_and_builds(srv, tmp_path):
    """The point of designs/: create one from the template and run it through the
    whole flow, exactly as an example goes."""
    name = "studiotest"
    shutil.rmtree(os.path.join(ROOT, "designs", name), ignore_errors=True)
    try:
        r = post(srv, "/api/new", {"name": name})
        assert r["path"] == f"designs/{name}/{name}.v"
        text = get(srv, "/api/source?path=" + r["path"])["text"]
        assert f"module {name}" in text
        ev = build(srv, {"files": [r["path"]], "top": name})
        assert ev["ok"], ev.get("error")
    finally:
        shutil.rmtree(os.path.join(ROOT, "designs", name), ignore_errors=True)


@pytest.mark.parametrize("name", ["../../etc/x", "a/b", "x.y", "9bad", "", "  "])
def test_an_unsafe_design_name_is_refused_not_rewritten(srv, name):
    """Asking for ../../etc/x and quietly getting designs/x/x.v is worse than an error."""
    with pytest.raises(urllib.error.HTTPError) as e:
        post(srv, "/api/new", {"name": name})
    assert e.value.code == 400


def test_a_design_name_is_not_reused(srv):
    name = "studiodup"
    shutil.rmtree(os.path.join(ROOT, "designs", name), ignore_errors=True)
    try:
        post(srv, "/api/new", {"name": name})
        with pytest.raises(urllib.error.HTTPError) as e:
            post(srv, "/api/new", {"name": name})
        assert e.value.code == 400
    finally:
        shutil.rmtree(os.path.join(ROOT, "designs", name), ignore_errors=True)


def test_the_editor_can_save_and_read_back(srv):
    name = "studiosave"
    shutil.rmtree(os.path.join(ROOT, "designs", name), ignore_errors=True)
    try:
        rel = post(srv, "/api/new", {"name": name})["path"]
        marker = "// written by the editor\n"
        post(srv, "/api/save", {"path": rel, "text": marker})
        assert get(srv, "/api/source?path=" + rel)["text"] == marker
    finally:
        shutil.rmtree(os.path.join(ROOT, "designs", name), ignore_errors=True)


@pytest.mark.parametrize("path", ["/etc/passwd", "../../../tmp/x.v", "designs/x.exe",
                                  "Makefile", ""])
def test_saving_outside_the_repo_or_the_wrong_type_is_refused(srv, path):
    with pytest.raises(urllib.error.HTTPError) as e:
        post(srv, "/api/save", {"path": path, "text": "x"})
    assert e.value.code == 400


def test_browse_lists_examples_and_your_designs(srv):
    b = get(srv, "/api/browse")
    kinds = {f["kind"] for f in b["files"]}
    assert "example" in kinds
    assert b["designs_dir"] == "designs"
    assert all(not os.path.isabs(f["path"]) for f in b["files"])
    assert {f["path"] for f in b["files"] if f["kind"] == "example"} >= {"examples/fir.v"}


# --- programming something built earlier --------------------------------------


def test_bitstreams_built_earlier_are_listed(srv):
    """The Board pane offers every .bit in build/, not only one built in this tab —
    a design built from the command line has to be loadable from the studio too."""
    ev = build(srv, {"files": ["examples/counter.v"]})
    assert ev["ok"], ev.get("error")
    bits = get(srv, "/api/bits")
    assert bits, "no bitstreams listed"
    paths = {b["path"] for b in bits}
    assert ev["stages"][-1]["stats"]["path"] in paths
    newest = bits[0]
    assert newest["mtime"] >= bits[-1]["mtime"], "not newest first"
    one = [b for b in bits if b["path"].endswith("counter.bit")]
    assert one and one[0]["top"] == "counter" and one[0]["ok"]


def test_a_bitstream_from_a_previous_session_can_be_programmed(srv):
    """The exact case that failed: build it, forget the session, program it by path."""
    ev = build(srv, {"files": ["examples/gates.v"]})
    path = ev["stages"][-1]["stats"]["path"]
    post(srv, "/api/target", {"kind": "fake"})
    r = post(srv, "/api/program", {"bit": path})
    assert r["ok"], r["message"]
    assert post(srv, "/api/readback", {"bit": path})["ok"]


def test_programming_without_a_target_is_reported_not_ignored(srv):
    """A dead Program button is how 'I pressed it and nothing happened' happens."""
    studio.TARGET.probe = None
    studio.TARGET.kind = None
    ev = build(srv, {"files": ["examples/gates.v"]})
    with pytest.raises(urllib.error.HTTPError) as e:
        post(srv, "/api/program", {"bit": ev["stages"][-1]["stats"]["path"]})
    assert e.value.code == 500
    body = json.load(e.value)
    assert "no target" in body["error"].lower()


# --- the pin planner ----------------------------------------------------------


def test_the_pad_map_names_the_board_pins(srv):
    p = get(srv, "/api/pins")
    assert len(p["pads"]) == B.DEVICE["pads"]["count"]
    named = {x["name"] for x in p["pads"] if x["name"]}
    assert {"SW0", "SW1", "BTN0", "BTN1", "BTN2", "BTN3", "LD0", "LD1", "LD2"} <= named


def test_a_pcf_the_flow_can_actually_read(srv):
    """It must parse the way vpr_run.read_pcf will read it during a build."""
    import vpr_run
    r = post(srv, "/api/pcf", {"name": "roundtrip",
                               "assign": {"led[0]": "LD2", "sw[0]": "SW1"}})
    pins = vpr_run.read_pcf(os.path.join(ROOT, r["pcf"]))
    assert pins == {"led[0]": vpr_run.BOARD_PIN_NAMES["LD2"],
                    "sw[0]": vpr_run.BOARD_PIN_NAMES["SW1"]}


VEC = """module vectest (clk, a, en, y, z);
  input  wire       clk;
  input  wire [2:0] a;
  input  wire       en;
  output wire [1:0] y;
  output wire       z;
  reg [1:0] r = 2'd0;
  always @(posedge clk) if (en) r <= a[1:0];
  assign y = r;
  assign z = ^a;
endmodule
"""


def test_synthesis_reports_port_widths_and_directions(srv, tmp_path):
    """The Pin Planner needs a row per PIN, so it needs each port's width: a 3-bit `a`
    is three rows. Before this, ports came back as bare names and a vector got one row."""
    src = tmp_path / "vectest.v"
    src.write_text(VEC)
    # No .pcf, and these ports are not the sw/btn/led convention, so place-and-route
    # refuses - correctly. Synthesis is what carries the port widths, so that is what
    # this checks.
    ev = build(srv, {"files": [os.path.relpath(_repo_copy(src), ROOT)], "top": "vectest"})
    synth = ev["stages"][0]
    assert synth["name"] == "synth" and synth["ok"], synth["detail"]
    ports = {p["name"]: p for p in synth["stats"]["ports"]}
    assert ports["a"] == {"name": "a", "width": 3, "dir": "input"}
    assert ports["y"] == {"name": "y", "width": 2, "dir": "output"}
    assert ports["en"]["width"] == 1 and ports["z"]["dir"] == "output"


def test_a_pcf_must_index_every_bit_including_one_bit_ports(srv):
    """vpr_run names every port bit port[i] - a one-bit `en` is the net `en[0]`. A bare
    name in a .pcf is ignored and the build then fails with "input en[0] has no pin",
    so the planner must refuse it up front."""
    with pytest.raises(urllib.error.HTTPError) as e:
        post(srv, "/api/pcf", {"name": "bare", "assign": {"a[0]": "SW0", "en": "BTN1"}})
    assert e.value.code == 400
    r = post(srv, "/api/pcf", {"name": "indexed", "assign": {"a[0]": "SW0", "en[0]": "BTN1"}})
    assert r["pcf"].endswith("indexed.pcf")


def test_a_design_with_vector_ports_builds_with_its_generated_pcf(srv, tmp_path):
    src = tmp_path / "vecbuild.v"
    src.write_text(VEC.replace("vectest", "vecbuild"))
    rel = os.path.relpath(_repo_copy(src), ROOT)
    pcf = post(srv, "/api/pcf", {"name": "vecbuild", "assign": {
        "a[0]": "SW0", "a[1]": "SW1", "a[2]": "BTN0", "en[0]": "BTN1",
        "y[0]": "LD0", "y[1]": "LD1", "z[0]": "LD2"}})["pcf"]
    ev = build(srv, {"files": [rel], "top": "vecbuild", "pcf": pcf, "name": "vecbuild_pins"})
    assert ev["ok"], ev.get("error")


def test_two_ports_on_one_pin_is_refused(srv):
    with pytest.raises(urllib.error.HTTPError) as e:
        post(srv, "/api/pcf", {"name": "clash", "assign": {"a": "LD0", "b": "LD0"}})
    assert e.value.code == 400


def test_an_unknown_pin_is_refused(srv):
    with pytest.raises(urllib.error.HTTPError) as e:
        post(srv, "/api/pcf", {"name": "bad", "assign": {"a": "NOSUCHPIN"}})
    assert e.value.code == 400


# --- readback, capture and the bitstream browser ------------------------------


def test_readback_confirms_what_was_programmed(srv):
    ev = build(srv, {"files": ["examples/gates.v"]})
    bit = ev["stages"][-1]["stats"]["path"]
    post(srv, "/api/target", {"kind": "fake"})
    post(srv, "/api/program", {"bit": bit})
    r = post(srv, "/api/readback", {"bit": bit})
    assert r["ok"] and r["differing_bits"] == 0, r["message"]


def test_readback_notices_a_different_bitstream(srv):
    """The check has to be able to fail: program one design, verify another."""
    a = build(srv, {"files": ["examples/gates.v"]})["stages"][-1]["stats"]["path"]
    b = build(srv, {"files": ["examples/counter.v"]})["stages"][-1]["stats"]["path"]
    post(srv, "/api/target", {"kind": "fake"})
    post(srv, "/api/program", {"bit": a})
    r = post(srv, "/api/readback", {"bit": b})
    assert not r["ok"] and r["differing_bits"] > 0


def test_capture_reads_every_clb_register(srv):
    ev = build(srv, {"files": ["examples/counter.v"]})
    post(srv, "/api/target", {"kind": "fake"})
    post(srv, "/api/program", {"bit": ev["stages"][-1]["stats"]["path"]})
    c = post(srv, "/api/capture", {})
    assert c["ok"], c["message"]
    assert c["nclb"] == B.NCLB and len(c["bits"]) == B.NCLB
    assert all(b in (0, 1) for b in c["bits"])


def test_capture_on_an_unconfigured_board_says_so(srv):
    """Clicking Capture before Program must explain itself, not 500."""
    post(srv, "/api/target", {"kind": "fake"})          # fresh board, nothing loaded
    c = post(srv, "/api/capture", {})
    assert c["ok"] is False and "loaded" in c["message"]


def test_the_bitstream_browser_describes_the_bit(srv):
    ev = build(srv, {"files": ["examples/counter.v"]})
    f = get(srv, "/api/fasm?bit=" + ev["stages"][-1]["stats"]["path"])
    assert f["width"] == B.CHAIN_W
    assert len(f["frames"]) == B.DEVICE["frames"]["count"]
    assert f["features"] > 0 and "clb_" in f["fasm"]
    assert 0 < sum(1 for x in f["frames"] if x["set"]) < len(f["frames"])


# --- routes that must not exist ----------------------------------------------


def test_an_unknown_route_is_not_found(srv):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(srv, "/api/nope")
    assert e.value.code == 404
