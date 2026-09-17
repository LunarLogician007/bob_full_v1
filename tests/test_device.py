"""
tools/bob/device.py is a correct, complete description of the fabric - checked
against itself (at K=6 and K=4), against VPR's routing-resource graph, against
the RTL, and against host/bitstream.py.
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
sys.path.insert(0, os.path.join(ROOT, "tools", "bob"))
sys.path.insert(0, os.path.join(ROOT, "host"))

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


@pytest.mark.parametrize("k,chain_w", [(6, 18560), (4, 12800)])
def test_sizes(k, chain_w):
    """The board device, pinned: a change here must be a deliberate one.
    M7-M12 (6x4 core) packed the tiles into 4216 bits (K=4: 3352); M13 laid the memory
    out in 128-bit frames per column (4992 bits = 39 frames; K=4: 4096 = 32).
    M12b: 8x6 core, 36 CLBs, 28 pads: 8320 bits = 65 frames (K=4: 6016 = 47).
    M16: 12x10 core, 100 CLBs, 44 pads: 18560 bits = 145 frames (K=4: 12800 = 100).
    The 8x8 profile (48 CLBs, 9400 bits) is frozen in release/M7_8x8."""
    dev = DEVICES[k]
    assert (dev.width, dev.height, dev.arch["chan_width"]) == (14, 12, 24)
    assert {t: len(v) for t, v in dev.by_type.items()} == {"io": 44, "clb": 100, "bram": 2, "dsp": 2}
    assert dev.tile_types["clb"].width == (1 << k) + 7
    assert dev.tile_types["ctrl"].width == 8
    assert dev.tile_types["bram"].width == 8 and dev.tile_types["dsp"].width == 16
    assert dev.chain_width == chain_w


@pytest.mark.parametrize("k", [6, 4])
def test_mux_encoding(k):
    """0 is const0 (IPIN 1 const1), inputs from base; the width is the smallest that fits."""
    dev = DEVICES[k]
    for m in dev.muxes.values():
        ntype = dev.rr.nodes[m.node].type
        assert m.base == (2 if ntype == "IPIN" else 1)
        top = m.base + len(m.inputs) - 1
        assert top < (1 << m.width) and top >= (1 << (m.width - 1))
        assert list(m.inputs) == sorted(set(m.inputs)) == dev.rr.fanin[m.node]


@pytest.mark.parametrize("k", [6, 4])
def test_every_pip_is_exactly_one_field_value(k):
    dev = DEVICES[k]
    seen = set()
    n = 0
    for _tile, node, src, (lo, width, value) in dev.pips():
        assert value < 1 << width
        assert (lo, value) not in seen
        seen.add((lo, value))
        assert src in dev.rr.fanin[node]
        n += 1
    assert n == sum(len(v) for nid, v in dev.rr.fanin.items() if nid in dev.muxes)


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
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "bob", "device.py"),
                        "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_non_default_k_never_overwrites_committed_files():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "bob", "device.py"),
                        "--lut-k", "4"], capture_output=True, text=True)
    assert r.returncode != 0 and "--out" in (r.stdout + r.stderr)


@pytest.mark.parametrize("k", [6, 4])
def test_vpr_routed_the_trivial_netlist_on_this_architecture(k):
    log = open(os.path.join(ROOT, "tools", "bob", "arch", f"bob_k{k}_vpr.txt")).read()
    assert "Circuit successfully routed" in log
    stamp = open(os.path.join(ROOT, "tools", "bob", "arch", f"bob_k{k}_rr.stamp")).read()
    assert "--route_chan_width 24" in stamp


def test_arch_keeps_the_reference_routing():
    """What M7 takes from OpenFPGA's k6_frac_N10_tileable_adder_chain_dpram8K_dsp36 arch."""
    xml = open(os.path.join(ROOT, "tools", "bob", "arch", "bob_k6.xml")).read()
    assert 'tileable="true"' in xml and 'through_channel="false"' in xml
    assert '<switch_block type="wilton" fs="3"/>' in xml
    assert re.search(r'<segment name="L4"[^>]*length="4" type="unidir"', xml)
    fc = re.search(r'<fc in_type="frac" in_val="([0-9.]+)" out_type="frac" out_val="([0-9.]+)"', xml)
    assert fc and (float(fc.group(1)), float(fc.group(2))) == (0.15, 0.10)
    assert '<perimeter type="io"' in xml and '<corners type="EMPTY"' in xml


# --- the description matches the RTL ----------------------------------------------------

PKG_NAMES = ["LUT_K", "LUT_INIT_W", "CLB_CFG_W", "CLB_INIT_LO", "CLB_FF_EN", "CLB_FF_RSTVAL",
             "CLB_FF_CE_EN", "CLB_FF_SR_EN", "CLB_CY_EN", "CLB_CY_DI_SEL", "CLB_FF_D_SEL"]


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="needs iverilog")
@pytest.mark.parametrize("k", [6, 4])
def test_params_vh_equals_clb_pkg_when_elaborated(k, tmp_path):
    """clb_pkg.sv takes only LUT_K from the header and derives every width
    itself; iverilog elaborates both and compares all constants."""
    gen = os.path.join(ROOT, "hw", "src", "generated")
    if k != 6:
        gen = str(tmp_path / "gen")
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "bob", "device.py"),
                        "--lut-k", str(k), "--out", gen], check=True, capture_output=True)
    checks = "\n".join(
        f'    if (`BOB_{n} !== {n}) begin $display("MISMATCH {n} vh=%0d pkg=%0d", '
        f'`BOB_{n}, {n}); bad = bad + 1; end' for n in PKG_NAMES)
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
    assert len(re.findall(r"^\s*bob_mux #", text, re.M)) == len(dev.muxes)
    assert len(re.findall(r"^\s*clb u_clb_x\d+y\d+ ", text, re.M)) == len(dev.by_type["clb"])
    assert len(re.findall(r"^\s*bram_block u_bram\d ", text, re.M)) == 2
    assert len(re.findall(r"^\s*dsp_block u_dsp\d ", text, re.M)) == 2
    for m in list(dev.muxes.values())[::97]:
        assert f"m{m.node} (.sel(cfg[{m.lo} +: {m.width}])" in text


# --- host/bitstream.py is driven by the description --------------------------------------

def test_bitstream_py_constants_come_from_device_json():
    import bitstream as B
    dev = DEVICES[6]
    assert B.FABRIC_CFG_W == B.CHAIN_W == dev.chain_width
    assert (B.LUT_K, B.CLB_CFG_W, B.NCLB, B.NBRAM, B.NDSP, B.NPAD, B.BSR_W) == (6, 71, 100, 2, 2, 44, 88)
    assert len(B.MUX) == len(dev.muxes)
    assert B.CLBS[0] == "clb_x1y1" and B.CLB_XY_INDEX[(2, 2)] == 11


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
    assert bs.get_mux(B.PIN["clb_x1y1.ce[0]"]) == 1                  # const1
    assert bs.get_mux(B.PIN["clb_x1y1.sr[0]"]) == 0                  # const0
    assert dev.decode(word)["ctrl"] == {"clk_mode": 0, "clk_div": 0, "reserved": 0}
    for pad in B.BOARD_OUT:
        assert bs.get_mux(B.PIN[f"{B.pad_block(pad)}.outpad[0]"]) >= 2   # routed, not a constant
    run = dev.decode(d_counter("run", 17).build().to_int())
    assert run["ctrl"]["clk_mode"] == 1 and run["ctrl"]["clk_div"] == 17


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
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "bob", "device.py"),
                    "--lut-k", "4", "--out", str(gen)], check=True, capture_output=True)
    code = (
        "import designs, bitstream as B\n"
        "assert B.LUT_K == 4 and B.FABRIC_CFG_W == 12800\n"
        "assert set(designs.SKIPPED) == {'and6', 'xor6'}\n"
        "for k, d, f, s in designs.DESIGNS:\n"
        "    bs = f().build()\n"
        "    [B.simulate(bs, v) for v in s]\n"
        "designs.d_pipeline().build()\n"
        "print('K4_OK', len(designs.DESIGNS))\n")
    env = dict(os.environ, BOB_DEVICE_JSON=str(gen / "device.json"))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                       cwd=os.path.join(ROOT, "host"))
    assert "K4_OK 10" in r.stdout, r.stdout + r.stderr
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
