"""
software/bob/device.py is a correct, complete description of the fabric - checked
against itself (at K=6 and K=4), against VPR's routing-resource graph, against
the RTL, and against software/host/bitstream.py.
"""

import json
import os
import random
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import device  # noqa: E402

DEVICES = {6: device.Device(), 4: device.Device(lut_k=4)}


# --- the description is self-consistent (both LUT sizes) -------------------------------

@pytest.mark.parametrize("k", [6, 4])
def test_fields_do_not_overlap_and_leave_no_holes(k):
    for t in DEVICES[k].tiles:
        used = [None] * t.width
        for f in t.fields:
            assert f.width > 0
            for b in range(f.offset, f.offset + f.width):
                assert used[b] is None, f"{t.name}.{f.name} overlaps {used[b]} at bit {b}"
                used[b] = f.name
        assert None not in used, f"hole at bit {used.index(None)} of {t.name}"


@pytest.mark.parametrize("k", [6, 4])
def test_chain_maps_every_bit_exactly_once(k):
    dev = DEVICES[k]
    assert dev.tiles[0].name == "ctrl" and dev.tiles[0].chain_lo == 0
    for t, nxt in zip(dev.tiles, dev.tiles[1:] + [None]):
        assert t.chain_lo + t.width == (nxt.chain_lo if nxt else dev.chain_width), "tiles not contiguous"
    for b in range(dev.chain_width):
        tile, f, bit = dev.locate(b)
        assert dev.chain_bit(tile, f.name, bit) == b
    assert dev.chain_width % 8 == 0, "byte-aligned chain: bit CRC == byte CRC-32C"


@pytest.mark.parametrize("k", [6, 4])
def test_chain_fields_chain_round_trip(k):
    dev = DEVICES[k]
    rng = random.Random(0xB0B)
    for _ in range(5):
        w = rng.getrandbits(dev.chain_width)
        assert dev.encode(dev.decode(w)) == w


SIZES = {"grid": (14, 12, 36), "blocks": {"io": 44, "clb": 100, "bram": 2, "dsp": 2},
         "cluster": (4, 16, "full"), "chain": {6: 68096, 4: 55296}}


@pytest.mark.parametrize("k", [6, 4])
def test_sizes(k):
    """The board device, pinned: a change here must be a deliberate one.
    M7-M12 (6x4 core) packed the tiles into 4216 bits (K=4: 3352); M13 laid the memory
    out in 128-bit frames per column (4992 bits = 39 frames; K=4: 4096 = 32).
    M12b: 8x6 core, 36 CLBs, 28 pads: 8320 bits = 65 frames (K=4: 6016 = 47).
    M16: 12x10 core, 100 CLBs, 44 pads: 18560 bits = 145 frames (K=4: 12800 = 100).
    M21: 9x7 core, 49 CLBs of 4 elements behind a full crossbar = 196 LUTs, 257 frames
    (software/bob/sweep.py, docs/reports/M21/cluster_sweep.md).
    M22: 11x9 core, 81 CLBs (324 LUTs), LUT contents and crossbar in CFGLUT5: 441 frames;
    each CLB tile frame aligned: selects + flags, 2 INIT frames, the remaining selects.
    M23: 12x10 core, 100 CLBs (400 LUTs), W 36, fc_in 0.10, 44 pads: 532 frames
    (software/bob/gridsweep.py, docs/reports/M23/grid_sweep.md; 12x11 did not place).
    M24: a 13th element flag (dd) leaves frame 0 room for 15 crossbar selects, not 16. At
    K=6 the tile already had a tail frame (unchanged, 68096); at K=4 (16 selects) each CLB
    gains one: 42496 -> 55296.
    The 8x8 profile (48 CLBs, 9400 bits) is frozen in release/M7_8x8."""
    dev = DEVICES[k]
    assert (dev.width, dev.height, dev.arch["chan_width"]) == SIZES["grid"]
    assert {t: len(v) for t, v in dev.by_type.items()} == SIZES["blocks"]
    c = dev.cluster
    assert (c["n"], c["i"], c["xbar"]) == SIZES["cluster"]
    # M22: the L-frames (INITs, crossbar selects, each frame padded), then 12 flags per element
    lay = dev.lutram_layout()
    assert lay["frames"] * device.FRAME_BITS >= c["n"] * ((1 << k) + k * dev.xbar_width())
    # M22: frame 0 (selects + flags), the INIT frames, then the remaining selects; the tile
    # ends in its last L-frame (the routing muxes fill the rest)
    w = dev.tile_types["clb"].width
    assert (lay["frames"] - 1) * device.FRAME_BITS < w <= lay["frames"] * device.FRAME_BITS
    # M20: clk_mode 1 + clk_div 5 + reserved 2 + clk_period 16 + clk_gap 16
    assert dev.tile_types["ctrl"].width == 8 + 2 * device.PERIOD_W == 40
    assert dev.tile_types["bram"].width == 8 and dev.tile_types["dsp"].width == 16
    assert dev.chain_width == SIZES["chain"][k]


@pytest.mark.parametrize("k", [6, 4])
def test_mux_encoding(k):
    """0 is const0 (IPIN 1 const1), inputs from base; the width is the smallest that fits.
    M21: a crossbar mux (its node is an element input, EIN) is an IPIN-like mux over its
    CLB's pins in device.xbar_sources order."""
    dev = DEVICES[k]
    for m in dev.muxes.values():
        if m.node not in dev.rr.nodes:
            t, x, y, ej = dev.ext_nodes[m.node]
            e, j = map(int, ej.split(","))
            assert t == "EIN" and m.base == 2
            clb = dev.block_at[(x, y)].name
            assert list(m.inputs) == [dev.pin_node[(clb, p)] for p in dev.xbar_sources(e, j)]
            assert 1 + len(m.inputs) < (1 << m.width)
            continue
        ntype = dev.rr.nodes[m.node].type
        assert m.base == (2 if ntype == "IPIN" else 1)
        top = m.base + len(m.inputs) - 1
        assert top < (1 << m.width) and top >= (1 << (m.width - 1))
        assert list(m.inputs) == sorted(set(m.inputs)) == dev.rr.fanin[m.node]


@pytest.mark.parametrize("k", [6, 4])
def test_crossbar_selects_are_the_clb_fields(k):
    """M21: element e's input j is the CLB field e<e>.x<j>, and its mux reads those bits"""
    dev = DEVICES[k]
    for el in dev.elements:
        blk = dev.block_by_name[el["clb"]]
        for j in range(k):
            m = dev.muxes[el["pins"][f"I[{j}]"]]
            assert (m.lo, m.width) == dev.block_field(blk, f"e{el['e']}.x{j}")
    # the carry runs cin -> e0 -> ... -> e<N-1> -> cout inside every CLB
    for blk in dev.by_type["clb"]:
        els = [el for el in dev.elements if el["clb"] == blk.name]
        assert els[0]["pins"]["cin"] == dev.pin_node[(blk.name, "cin[0]")]
        assert els[-1]["pins"]["cout"] == dev.pin_node[(blk.name, "cout[0]")]
        for lo, hi in zip(els, els[1:]):
            assert lo["pins"]["cout"] == hi["pins"]["cin"]


@pytest.mark.parametrize("k", [6, 4])
def test_every_pip_is_exactly_one_field_value(k):
    dev = DEVICES[k]
    seen = set()
    n = 0
    for _tile, node, src, (lo, width, value) in dev.pips():
        assert value < 1 << width
        assert (lo, value) not in seen
        seen.add((lo, value))
        assert src in (dev.rr.fanin[node] if node in dev.rr.nodes else dev.muxes[node].inputs)
        n += 1
    assert n == sum(len(m.inputs) for m in dev.muxes.values())


@pytest.mark.parametrize("k", [6, 4])
def test_every_block_pin_is_an_rr_node(k):
    dev = DEVICES[k]
    for b in dev.blocks:
        for d, name, w in dev.block_ports(b.type):
            for j in range(w):
                assert (b.name, f"{name}[{j}]") in dev.pin_node, f"{b.name}.{name}[{j}]"


@pytest.mark.parametrize("k", [6, 4])
def test_directs_are_the_carry_chain_and_the_dsp_cascade(k):
    dev = DEVICES[k]
    carry = {(dev.node_pin[i], dev.node_pin[o]) for i, o in dev.direct.items() if dev.node_pin[i][1] == "cin[0]"}
    expect = {((f"clb_x{b.x}y{b.y}", "cin[0]"), (f"clb_x{b.x}y{b.y - 1}", "cout[0]"))
              for b in dev.by_type["clb"] if b.y > 1}
    assert carry == expect
    casc = {(dev.node_pin[i], dev.node_pin[o]) for i, o in dev.direct.items() if dev.node_pin[i][1].startswith("pcin")}
    assert casc == {(("dsp1", f"pcin[{j}]"), ("dsp0", f"pcout[{j}]")) for j in range(48)}
    undriven_cin = {dev.node_pin[n] for n in dev.undriven if dev.node_pin.get(n, ("", ""))[1] == "cin[0]"}
    assert undriven_cin == {(f"clb_x{b.x}y1", "cin[0]") for b in dev.by_type["clb"] if b.y == 1}


def test_board_pads():
    dev = DEVICES[6]
    assert [p["name"] for p in dev.board_inputs] == ["SW0", "SW1", "BTN0", "BTN1", "BTN2", "BTN3"]
    for p in dev.board_inputs:
        pad = dev.pads[p["pad"]]
        assert pad.x == 0 or pad.y == 0, "board inputs sit on the West, then South, edge"
    for p in dev.board_outputs:
        assert dev.pads[p["pad"]].x == dev.width - 1, "LEDs sit on the East edge"


def test_generated_files_are_current():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "software", "bob", "device.py"),
                        "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_non_default_k_never_overwrites_committed_files():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "software", "bob", "device.py"),
                        "--lut-k", "4"], capture_output=True, text=True)
    assert r.returncode != 0 and "--out" in (r.stdout + r.stderr)


@pytest.mark.parametrize("k", [6, 4])
def test_vpr_routed_the_trivial_netlist_on_this_architecture(k):
    log = open(os.path.join(ROOT, "software", "bob", "arch", f"bob_k{k}_vpr.txt")).read()
    assert "Circuit successfully routed" in log
    stamp = open(os.path.join(ROOT, "software", "bob", "arch", f"bob_k{k}_rr.stamp")).read()
    assert f"--route_chan_width {SIZES['grid'][2]}" in stamp


def test_arch_keeps_the_reference_routing():
    """What M7 takes from OpenFPGA's k6_frac_N10_tileable_adder_chain_dpram8K_dsp36 arch."""
    xml = open(os.path.join(ROOT, "software", "bob", "arch", "bob_k6.xml")).read()
    assert 'tileable="true"' in xml and 'through_channel="false"' in xml
    assert '<switch_block type="wilton" fs="3"/>' in xml
    assert re.search(r'<segment name="L4"[^>]*length="4" type="unidir"', xml)
    fc = re.search(r'<fc in_type="frac" in_val="([0-9.]+)" out_type="frac" out_val="([0-9.]+)"', xml)
    assert fc and (float(fc.group(1)), float(fc.group(2))) == (0.10, 0.10)    # M23: fc_in 0.10 (the sweep)
    assert '<perimeter type="io"' in xml and '<corners type="EMPTY"' in xml


# --- the description matches the RTL ----------------------------------------------------

PKG_NAMES = ["LUT_K", "LUT_INIT_W"]


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="needs iverilog")
@pytest.mark.parametrize("k", [6, 4])
def test_params_vh_equals_clb_pkg_when_elaborated(k, tmp_path):
    """clb_pkg.sv (the one-element clb.sv of M4-M20, kept for the M0 bring-up fabric) takes
    only LUT_K from the header and derives its widths itself; iverilog elaborates both and
    compares the constants they share, and the element offsets ble.sv uses."""
    gen = os.path.join(ROOT, "hw", "src", "generated")
    if k != 6:
        gen = str(tmp_path / "gen")
        subprocess.run([sys.executable, os.path.join(ROOT, "software", "bob", "device.py"),
                        "--lut-k", str(k), "--out", gen], check=True, capture_output=True)
    dev = DEVICES[k]
    tt = dev.tile_types["clb"]
    flag0 = tt.field(f"e0.{dev.ELEMENT_FIELDS[0][0]}").offset
    want = {f"ELE_{n.upper()}": tt.field(f"e0.{n}").offset - flag0 for n, *_r in dev.ELEMENT_FIELDS}
    want.update(ELE_W=dev.element_width(), CLB_FLAGS_LO=flag0)      # M22: flags only, after the L-frames
    checks = "\n".join(
        f'    if (`BOB_{n} !== {n}) begin $display("MISMATCH {n} vh=%0d pkg=%0d", '
        f'`BOB_{n}, {n}); bad = bad + 1; end' for n in PKG_NAMES)
    checks += "\n" + "\n".join(
        f'    if (`BOB_{n} !== {v}) begin $display("MISMATCH {n} vh=%0d device=%0d", `BOB_{n}, {v}); '
        f'bad = bad + 1; end' for n, v in want.items())
    tb = tmp_path / "t.sv"
    tb.write_text(
        '`include "bob_params.vh"\n'
        "module t;\n  import clb_pkg::*;\n  integer bad = 0;\n  initial begin\n"
        f"{checks}\n"
        '    if (bad == 0) $display("PARAMS_OK"); $finish;\n  end\nendmodule\n')
    out = tmp_path / "t.vvp"
    subprocess.run(["iverilog", "-g2012", "-I", gen, "-o", str(out),
                    os.path.join(ROOT, "hw", "src", "clb", "clb_pkg.sv"), str(tb)],
                   check=True, capture_output=True, text=True)
    r = subprocess.run(["vvp", str(out)], capture_output=True, text=True)
    assert "PARAMS_OK" in r.stdout, r.stdout


def test_rtl_sizes_come_from_bob_params():
    fpga = open(os.path.join(ROOT, "hw", "src", "fabric", "bob_fpga.v")).read()
    assert '`include "bob_params.vh"' in fpga
    for n in ("NPAD", "NCLB", "NBRAM", "NDSP", "CHAIN_W", "CTRL_W", "BSR_W"):
        assert re.search(rf"localparam\s+integer\s+{n}\s*=\s*`BOB_{n}", fpga), n
    top = open(os.path.join(ROOT, "hw", "src", "top", "bob_top.v")).read()
    for p in ("SW0", "SW1", "BTN0", "BTN3", "LD0", "LD2"):
        assert f"`BOB_PAD_{p}" in top


def test_generated_fabric_has_every_mux_and_block():
    dev = DEVICES[6]
    text = open(os.path.join(ROOT, "hw", "src", "generated", "bob_fabric.v")).read()
    rr = [m for m in dev.muxes.values() if m.node in dev.rr.nodes]
    assert len(re.findall(r"^\s*bob_mux #.* m\d+ ", text, re.M)) == len(rr)
    # M21: one bob_clb module holds the crossbar (one mux per element input) and N elements
    body = text[text.index("module bob_clb"):]
    assert len(re.findall(r"^\s*lxor #", body, re.M)) == dev.cluster["n"] * dev.lut_k    # M23 (M22: lxmux)
    assert len(re.findall(r"^\s*ble u_e\d+ ", body, re.M)) == dev.cluster["n"]
    assert len(re.findall(r"^\s*bob_clb u_clb_x\d+y\d+ ", text, re.M)) == len(dev.by_type["clb"])
    assert len(re.findall(r"^\s*bram_block u_bram\d ", text, re.M)) == 2
    assert len(re.findall(r"^\s*dsp_block u_dsp\d ", text, re.M)) == 2
    for m in rr[::97]:
        assert f"m{m.node} (.sel(cfg[{m.lo} +: {m.width}])" in text


# --- software/host/bitstream.py is driven by the description --------------------------------------

def test_bitstream_py_constants_come_from_device_json():
    import bitstream as B
    dev = DEVICES[6]
    assert B.FABRIC_CFG_W == B.CHAIN_W == dev.chain_width
    assert (B.LUT_K, B.CLB_CFG_W, B.NCLB, B.NBRAM, B.NDSP, B.NPAD, B.BSR_W) == \
        (6, dev.tile_types["clb"].width, len(dev.by_type["clb"]), 2, 2, len(dev.pads), 2 * len(dev.pads))
    assert (B.CLB_N, B.CLB_I, B.NCAP) == (dev.cluster["n"], dev.cluster["i"], 2 * len(dev.elements))
    assert len(B.MUX) == len(dev.muxes)
    ncol = len({x for x, _y in B.CLB_AT})                          # CLBs row-major, 2 bits per element
    assert B.CLBS[0] == "clb_x1y1" and B.CLB_XY_INDEX[(2, 2)] == 2 * B.CLB_N * (ncol + 1)
    assert B.CAP_INDEX[(1, 1, 3)] == 6 and B.CAP_STATE[7] == ((1, 1, 3), "q2")


def test_designs_decode_to_the_fields_they_set():
    import bitstream as B
    from designs import BY_KEY, d_counter
    dev = DEVICES[6]
    word = BY_KEY["showcase"][1]().build().to_int()
    assert dev.encode(dev.decode(word)) == word
    bs = B.Bitstream(word)
    assert bs.get_field(1, 1, "init") == B.LUT.and2()
    assert bs.get_field(2, 2, "init") == B.LUT.or2()
    assert bs.get_field(4, 3, "init") == B.LUT.xor2()
    assert bs.get_mux(B.PIN["clb_x1y1.ce[0]"]) == 0                  # M21: shared, unused: const0
    assert bs.get_mux(B.PIN["clb_x1y1.sr[0]"]) == 0                  # const0
    assert bs.get_mux(B.PIN["clb_x1y1.e0.I[0]"]) >= 2                # the crossbar takes a CLB pin
    assert dev.decode(word)["ctrl"] == {"clk_mode": 0, "clk_div": 0, "reserved": 0,
                                        "clk_period": 0, "clk_gap": 0}     # M20: unset = the old behaviour
    for pad in B.BOARD_OUT:
        assert bs.get_mux(B.PIN[f"{B.pad_block(pad)}.outpad[0]"]) >= 2   # routed, not a constant
    run = dev.decode(d_counter("run", 17).build().to_int())
    assert run["ctrl"]["clk_mode"] == 1 and run["ctrl"]["clk_div"] == 17
    # M20: a design clocked from its own timing carries the period and the gap instead
    timed = B.Bitstream(word)
    timed.set_ctrl(1, 0, 47, 12)
    assert dev.decode(timed.to_int())["ctrl"] == {"clk_mode": 1, "clk_div": 0, "reserved": 0,
                                                  "clk_period": 47, "clk_gap": 12}


def test_bram_rom_design_fields():
    import bitstream as B
    from designs import d_bram_rom
    bs = B.Bitstream(d_bram_rom().build().to_int())
    assert bs.get_bram(0, "wmode_a") == B.BRAM_WRITE_MODES["READ_FIRST"]
    assert bs.get_bram(0, "jtag_a") == 0 and bs.get_bram(0, "jtag_b") == 0
    assert bs.get_mux(B.PIN["bram0.en_a[0]"]) == 1                    # const1
    assert bs.get_mux(B.PIN["bram0.addr_a[0]"]) >= 2 and bs.get_mux(B.PIN["bram0.addr_a[1]"]) >= 2
    for n, w in B.BRAM_PORT_PINS:
        for j in range(w):
            assert bs.get_mux(B.PIN[f"bram0.{n}_b[{j}]"]) == 0        # port B idle
            assert bs.get_mux(B.PIN[f"bram1.{n}_a[{j}]"]) == 0        # bram1 untouched


def test_routes_are_trees_and_never_share_a_wire():
    """Every routed node selects a node of its own net; no wire carries two nets."""
    import bitstream as B
    from designs import DESIGNS, d_pipeline
    for key, _d, fn, _s in DESIGNS + [("pipeline", "", d_pipeline, None)]:
        d = fn()
        d.build()
        owner = {}
        for net, nodes in d.routes.items():
            for n in nodes:
                assert n not in owner, f"{key}: node {n} in two nets"
                owner[n] = net
        for net, nodes in d.routes.items():
            for n in nodes[1:]:
                lo, w, base, ins = B.MUX[n]
                src = ins[d.bs.get_mux(n) - base]
                assert owner[src] == net, f"{key}: node {n} reads another net"


def test_bitstream_engine_at_k4(tmp_path):
    """The whole Python side works at K=4 from a K=4 device.json."""
    gen = tmp_path / "gen"
    subprocess.run([sys.executable, os.path.join(ROOT, "software", "bob", "device.py"),
                    "--lut-k", "4", "--out", str(gen)], check=True, capture_output=True)
    code = (
        "import designs, bitstream as B\n"
        f"assert B.LUT_K == 4 and B.FABRIC_CFG_W == {SIZES['chain'][4]}\n"
        "assert set(designs.SKIPPED) == {'and6', 'xor6'}\n"
        "for k, d, f, s in designs.DESIGNS:\n"
        "    bs = f().build()\n"
        "    [B.simulate(bs, v) for v in s]\n"
        "designs.d_pipeline().build()\n"
        "print('K4_OK', len(designs.DESIGNS))\n")
    env = dict(os.environ, BOB_DEVICE_JSON=str(gen / "device.json"))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                       cwd=os.path.join(ROOT, "software", "host"))
    assert "K4_OK 11" in r.stdout, r.stdout + r.stderr          # M24: + dd (a LUT2 beside the adder)
    assert json.load(open(gen / "device.json"))["lut_k"] == 4


@pytest.mark.parametrize("k", [6, 4])
def test_frames_tile_the_memory(k):
    """M13: frames of FRAME_BITS cover the memory exactly, column by column; every
    tile lies inside its column's frames; padding bits are reserved."""
    import device
    dev = DEVICES[k]
    assert dev.chain_width == dev.nframes * device.FRAME_BITS
    nxt = 0
    for col in dev.frames:
        assert col["base"] == nxt and col["lo"] == nxt * device.FRAME_BITS and col["count"] > 0
        nxt += col["count"]
    assert nxt == dev.nframes
    span = {c["far_col"]: (c["lo"], c["lo"] + c["count"] * device.FRAME_BITS) for c in dev.frames}
    assert span[0][0] == 0 and dev.ctrl_tile.chain_lo == 0
    for t in dev.tiles:
        if t.kind == "grid":
            lo, hi = span[t.x + 1]
            assert lo <= t.chain_lo and t.chain_lo + t.width <= hi, t.name
        if t.kind == "tail":
            assert all(f.kind == "reserved" for f in t.fields)


# --- M22: the L-frames (LUT contents and crossbar selects in CFGLUT5s) -------------------


@pytest.mark.parametrize("k", [6, 4])
def test_every_clb_starts_its_own_l_frames(k):
    """A CLB tile is frame aligned; its L-frames are its first frames (frame 0: selects then
    flags, the INIT frames, the remaining selects), and no L field straddles a frame."""
    from device import FRAME_BITS
    dev = DEVICES[k]
    lay = dev.lutram_layout()
    owner = {lf["frame"]: lf for lf in dev.lframes}
    assert len(dev.lframes) == lay["frames"] * len(dev.by_type["clb"])
    for blk in dev.by_type["clb"]:
        assert blk.chain_lo % FRAME_BITS == 0, blk.name
        f0 = blk.chain_lo // FRAME_BITS
        for i, kind in enumerate(lay["kinds"]):
            assert owner[f0 + i]["clb"] == blk.name and owner[f0 + i]["kind"] == kind
    tt = dev.tile_types["clb"]
    for f in tt.fields:
        if dev.is_lfield(f):
            assert f.offset // FRAME_BITS == (f.offset + f.width - 1) // FRAME_BITS, f.name


@pytest.mark.parametrize("k", [6, 4])
def test_a_load_sets_the_flags_before_any_crossbar_select(k):
    """Frames are written in ascending order and a frame's flip-flops load at the write, so
    every flag must sit in a frame no later than every crossbar select's: otherwise a load
    passes through states where the crossbar feeds an element's output back through its
    own LUT with the flip-flop still off (M22 hung tb_synth that way)."""
    from device import FRAME_BITS
    dev = DEVICES[k]
    tt = dev.tile_types["clb"]
    flags = [tt.field(f"e{e}.{n}").offset // FRAME_BITS for e in range(dev.cluster["n"])
             for n, *_r in dev.ELEMENT_FIELDS]
    sels = [tt.field(f"e{e}.x{j}").offset // FRAME_BITS for e in range(dev.cluster["n"]) for j in range(k)]
    assert max(flags) <= min(sels)


@pytest.mark.parametrize("k", [6, 4])
def test_l_frame_slots_are_the_same_in_every_clb(k):
    """INIT e: tile frame 1 + e // per, slot e % per; crossbar select s = e*K + j at slot t,
    bit t * xbar_width, of its frame - fabric_gen.py and lut_expand.v assume it."""
    from device import FRAME_BITS
    dev = DEVICES[k]
    lay = dev.lutram_layout()
    tt = dev.tile_types["clb"]
    xw = dev.xbar_width()
    for e in range(dev.cluster["n"]):
        f, slot = divmod(e, lay["init_per_frame"])
        assert tt.field(f"e{e}.init").offset == (1 + f) * FRAME_BITS + slot * (1 << k)
        for j in range(k):
            fx, t = dev.xbar_slot(e * k + j)
            assert lay["kinds"][fx] == "xbar"
            assert tt.field(f"e{e}.x{j}").offset == fx * FRAME_BITS + t * xw


def test_the_lbit_mask_names_the_l_bits():
    vh = open(os.path.join(ROOT, "hw", "src", "generated", "bob_params.vh")).read()
    d = {k: (int(w), int(v, 16)) for k, w, v in
         re.findall(r"`define BOB_(LKIND|LMASKS)\s+(\d+)'h([0-9a-f]+)", vh)}
    kw = int(re.search(r"`define BOB_LKIND_W\s+(\d+)", vh).group(1))
    dev = DEVICES[6]
    from device import FRAME_BITS
    assert d["LKIND"][0] == kw * dev.nframes < 65536 and d["LMASKS"][0] == FRAME_BITS << kw
    # M23: the per-frame kinds and masks put back together are the L bits, frame by frame
    lbits = 0
    for f in range(dev.nframes):
        k = (d["LKIND"][1] >> (kw * f)) & ((1 << kw) - 1)
        lbits |= ((d["LMASKS"][1] >> (FRAME_BITS * k)) & ((1 << FRAME_BITS) - 1)) << (FRAME_BITS * f)
    assert lbits == dev.lbits
    # every L bit is inside an L-frame, and every CLB's INIT and crossbar bits are L bits
    from device import FRAME_BITS
    lf = {x["frame"] for x in dev.lframes}
    assert all((b // FRAME_BITS) in lf for b in range(dev.chain_width) if (dev.lbits >> b) & 1)
    for blk in dev.by_type["clb"]:
        lo, w = dev.block_field(blk, "e3.init")
        assert (dev.lbits >> lo) & ((1 << w) - 1) == (1 << w) - 1
        lo, w = dev.block_field(blk, "e3.ff_en")
        assert not (dev.lbits >> lo) & 1
