#!/usr/bin/env python3
"""
device.py - the bob device description. THE single source of truth.

Every consumer reads what this file generates instead of repeating numbers:

  software/bob/arch/bob_k6.xml         VPR architecture (and bob_k4.xml)
  software/bob/device.json             host tools (software/host/bitstream.py, model.py, bitgen)
  hw/src/generated/bob_params.vh    RTL `defines
  hw/src/generated/bob_fabric.v     the routing fabric, generated from VPR's rr graph

  ./device.py                        regenerate everything
  ./device.py --check                exit 1 if a generated file is stale
  ./device.py --arch-only            write only the VPR architectures (make rrgraph)
  ./device.py --lut-k 4 --out DIR    write a K=4 variant into DIR (tests use this)

The flow (M7, OpenFPGA's method)
--------------------------------
  1. this file describes the grid, the tiles' pins and the routing architecture
     and writes a VPR architecture (software/bob/vpr_arch.py, derived from
     OpenFPGA's k6_frac_N10_tileable_adder_chain_dpram8K_dsp36_fracff_40nm.xml)
  2. VPR builds its tileable routing-resource graph and routes a trivial
     netlist on it (software/bob/vpr_rrgraph.sh, Docker; `make rrgraph`)
  3. this file reads that graph back: every CHANX/CHANY/IPIN node that edges
     drive is a configuration mux; its bits get a place in the chain
  4. software/bob/fabric_gen.py writes the fabric RTL from the same data

Model
-----
  grid        VPR coordinates: x to the East, y to the North, (0,0) the
              South-West corner. io around the perimeter (corners empty), a
              BRAM column and a DSP column, CLBs everywhere else.
  block       clb (one BLE: LUT K + FF with CE/SR + carry), bram (UG473 RAMB18
              1024 x 18 true dual port, height 4), dsp (UG479 DSP48E1 slice,
              height 4, PCOUT -> PCIN up the column), io (one pad).
  tile        one grid location's configuration: the fields of the block
              rooted there, then the routing muxes VPR placed there.
  chain       ctrl tile first, then grid tiles row-major from (0,0), then a
              few reserved bits to a byte boundary. Chain bit k is the k-th bit
              shifted in on TDI (LSB-first).
  mux         a node with N driving edges. CHANX/CHANY: value 0 = const0,
              1..N = input 0..N-1. IPIN: 0 = const0, 1 = const1, 2..N+1 =
              inputs. Inputs are the driving node ids in ascending order.
              An all-zero chain is therefore a dark fabric with no loops.
  direct      an IPIN driven only by an OPIN (carry, DSP cascade) is a wire.

History
-------
  M1  the proven 4x4 fabric, bit for bit
  M4  LUT size K is a parameter; routed CE/SR; ctrl tile (user clock)
  M5  BRAM tile; M6 DSP tile (both on fabric edges)
  M7  heterogeneous fabric generated from VPR's rr graph: 8x8 core, L4
      unidirectional routing (W=24, Wilton Fs=3), 32 I/O pads, 48 CLBs, 2 BRAMs,
      2 DSP slices
"""

import argparse
import bisect
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import vpr_arch  # noqa: E402

ARCH_DIR = os.path.join(HERE, "arch")
JSON_NAME = "device.json"
VH_NAME = "bob_params.vh"
FABRIC_NAME = "bob_fabric.v"
JSON_PATH = os.path.join(HERE, JSON_NAME)
GEN_DIR = os.path.join(ROOT, "hw", "src", "generated")

SYSCLK_HZ = 125_000_000              # PYNQ-Z2 PL clock on H16
DIV_MIN_SHIFT = 9                    # free-running enable: every 2**(clk_div+9) sysclk cycles
GCE_MIN_GAP_SHIFT = 9                # M13: user-clock enables >= 2**GCE_MIN_GAP_SHIFT sysclk cycles
                                     # apart in both modes.
                                     # M16: 8 (256 cycles, 2048 ns) no longer covers the 12x10
                                     # fabric - implementation reported WNS -465 ns on
                                     # fabric flop -> flop paths, so the static path through the
                                     # unconfigured routing muxes is ~2500 ns. 9 = 512 cycles
                                     # = 4096 ns. Raising it makes timing easier and the
                                     # free-running guest clock slower (488 -> 244 kHz max).
                                     # M20: this is now the DEFAULT gap (clk_gap = 0): an
                                     # unconfigured fabric or a design without timing runs at it.
                                     # A design timed by the flow sets its own clk_gap from its
                                     # critical path (per-design sign-off), never below
                                     # GCE_GAP_FLOOR.
                                     # M21: no longer tied to the XDC. The cluster fabric's
                                     # empty mesh placed at WNS -133 ns against 512 cycles and
                                     # -290 ns against 1024: Vivado's loop cutting, not the
                                     # fabric, sets that path. The XDC now relaxes sysclk by
                                     # XDC_SYSCLK_MULTICYCLE, and timing.contract() refuses any
                                     # word whose own critical path does not fit its spacing.
XDC_SYSCLK_MULTICYCLE = 16384        # M21: the XDC's sysclk -> sysclk multicycle (131 us). Not a
                                     # timing budget any more, only "Vivado, do not optimise the
                                     # unconfigured fabric": it must exceed any path Vivado can
                                     # build through it. A simple path visits each fabric mux at
                                     # most once (~4800 in M21), a few LUT levels each, so tens
                                     # of us at worst. tests/test_layout.py holds the XDC to it.
XDC_TCK_MULTICYCLE = 16              # M21: the same for TCK -> TCK (16 x 10 us = 160 us).
                                     # Configuration bits and the boundary / IR update cells
                                     # drive the fabric and CAPTURE / boundary / DSP JTAG
                                     # capture it, all on TCK; the empty mesh's loop-cut path
                                     # passed the 10 us period (second M21 build, WNS -228 ns
                                     # with sysclk already relaxed).
GCE_GAP_FLOOR = 2                    # M20: hardware floor of the gce spacing (62.5 MHz)
PERIOD_W = 16                        # M20: clk_period / clk_gap field width (up to 65535 cycles)

# M13 frames (docs/bitstream-format.md sections 9-10): UG470-style configuration frames
FRAME_WORDS = 4
FRAME_BITS = 32 * FRAME_WORDS

# --- M7 architecture ---------------------------------------------------------------
# Two profiles. The 8x8 core (48 CLBs) is the M7 fabric frozen in release/M7_8x8/
# for a later Vivado build on a faster machine; the 6x4 core (16 CLBs, every
# feature kept: 2 BRAMs + 2 DSPs of height 2, cascade, SELECT) is what the board
# gets now. Changing ARCH means `make rrgraph` (Docker).
ARCH_6X4 = {
    "nx": 6, "ny": 4,                # 4 CLB columns x 4 rows = 16 CLBs, 20 pads
    "chan_width": 24,
    "segment_length": 4,
    "fs": 3,
    "fc_in": 0.15, "fc_out": 0.10,
    "io_capacity": 1,
    "columns": [{"type": "bram", "x": 3, "height": 2},
                {"type": "dsp", "x": 6, "height": 2}],
}

ARCH_8X8 = {
    "nx": 8, "ny": 8,                # core size; VPR grid is (nx+2) x (ny+2) with the io ring
    "chan_width": 24,                # tracks per channel (12 each way), L4 unidirectional
    "segment_length": 4,
    "fs": 3,                         # Wilton switch block
    "fc_in": 0.15, "fc_out": 0.10,   # OpenFPGA k6_frac_N10 reference values
    "io_capacity": 1,
    "columns": [{"type": "bram", "x": 3, "height": 4},
                {"type": "dsp", "x": 6, "height": 4}],
}

# M12b: 8x6 core (36 CLBs, 2 BRAMs + 2 DSPs of height 3, 28 pads). Affordable after
# the chain was streamed through one frame buffer (cfg_store.v): whole-design yosys
# estimate 15.8k LUT / 10.8k FF, against M13's 15.4k / 12.2k, which Vivado built in
# 3.5 min at 2.0 GB.
ARCH_8X6 = {
    "nx": 8, "ny": 6,
    "chan_width": 24,
    "segment_length": 4,
    "fs": 3,
    "fc_in": 0.15, "fc_out": 0.10,
    "io_capacity": 1,
    "columns": [{"type": "bram", "x": 3, "height": 3},
                {"type": "dsp", "x": 6, "height": 3}],
}

# M16: 12x10 core = 10 CLB columns x 10 rows = 100 CLBs, BRAM x=3 and DSP x=8 (height 5,
# so still 2 of each), 44 pads. Measure with software/bob/synth_estimate.sh before a build.
ARCH_12X10 = {
    "nx": 12, "ny": 10,
    "chan_width": 24,
    "segment_length": 4,
    "fs": 3,
    "fc_in": 0.15, "fc_out": 0.10,
    "io_capacity": 1,
    "columns": [{"type": "bram", "x": 3, "height": 5},
                {"type": "dsp", "x": 8, "height": 5}],
}

# M21: the cluster logic block (OpenFPGA k6_frac_N10). A CLB is N logic elements (each
# a fracturable LUT K - one LUT K or two LUT K-1 sharing K-1 inputs - with two flip-flops
# and the carry through all N), I general inputs and 2N outputs, and a local crossbar in
# front of every element input: "full" = every CLB input and every element output, "half"
# = every other one (a depopulated crossbar). Sized by software/bob/sweep.py
# (docs/reports/M21/cluster_sweep.md).
CLUSTER_N10 = {"n": 10, "i": 40, "xbar": "full", "frac": True}        # the plan's target (measured: too
                                                                     # costly per LUT on this chip)
CLUSTER_N4 = {"n": 4, "i": 16, "xbar": "full", "frac": True}          # M21 as built (user, 2026-09-23)

# M21: 9x7 core = 7 CLB columns x 7 rows = 49 CLBs of 4 elements = 196 LUTs, BRAM x=3 and
# DSP x=6 (height 3: two of each), 32 pads. W = 40: 1.3x the widest channel VPR needed on
# any example (fir16, 30; software/bob/sweep.py r2_n4). Whole design in yosys 58.6k LUT /
# 35.9k FF (about 36k LUT in Vivado, 68% of the XC7Z020); 8x8 CLBs would be ~86%.
ARCH_M21 = {
    "nx": 9, "ny": 7,
    "chan_width": 40,
    "segment_length": 4,
    "fs": 3,
    "fc_in": 0.15, "fc_out": 0.10,
    "io_capacity": 1,
    "columns": [{"type": "bram", "x": 3, "height": 3},
                {"type": "dsp", "x": 6, "height": 3}],
    "cluster": CLUSTER_N4,
}

ARCH = ARCH_M21

# Board pads (PYNQ-Z2): pad_i bit order and pad_o bit order used by every host tool
BOARD_INPUTS = ("SW0", "SW1", "BTN0", "BTN1", "BTN2", "BTN3")
BOARD_OUTPUTS = ("LD0", "LD1", "LD2")
STATUS_W = 16                        # USER1 returns the first 16 CLB outputs

# BRAM (hw/src/tiles/bram_block.v): RAMB18E1-style 1024 x 18 true dual port
BRAM_ADDR_W = 10
BRAM_DATA_W = 18
BRAM_PORT_PINS = [("addr", BRAM_ADDR_W), ("di", BRAM_DATA_W), ("we", 1), ("en", 1), ("rst", 1), ("regce", 1)]
BRAM_WRITE_MODES = {"WRITE_FIRST": 0, "READ_FIRST": 1, "NO_CHANGE": 2}
BRAM_JTAG_VERSION = 0x07

# DSP (hw/src/tiles/dsp_block.v): DSP48E1-style slice
DSP_OPMODES = {"M": 0, "M+C": 1, "P+M": 2, "PCIN>>17+M": 3}
DSP_BUSES = [("a", 25), ("b", 18), ("c", 48), ("d", 25)]
DSP_CTRL_NAMES = ("ce_ad", "ce_b", "ce_m", "ce_p", "rst_ad", "rst_b", "rst_m", "rst_p")
DSP_DRIVE_PER_SLICE = 25 + 18 + 48 + 25 + len(DSP_CTRL_NAMES)     # 124
DSP_JTAG_VERSION = 0x07


@dataclass(frozen=True)
class Field:
    name: str
    offset: int
    width: int
    kind: str       # lut_init | flag | value | mux | reserved
    group: str      # clb | bram | dsp | ctrl | rr
    doc: str = ""


@dataclass(frozen=True)
class TileType:
    name: str
    fields: tuple

    @property
    def width(self):
        return sum(f.width for f in self.fields)

    def field(self, name):
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(f"{self.name} has no field {name}")


@dataclass(frozen=True)
class Tile:
    name: str
    kind: str                # ctrl | grid | tail
    x: Optional[int]
    y: Optional[int]
    chain_lo: int
    fields: tuple

    @property
    def width(self):
        return sum(f.width for f in self.fields)

    def field(self, name):
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(f"{self.name} has no field {name}")


@dataclass(frozen=True)
class Block:
    name: str                # clb_x1y1, bram0, dsp1, io_x0y3
    type: str
    x: int
    y: int
    index: int               # within its type, row-major by root
    chain_lo: int            # absolute chain position of its fields (-1: none)


@dataclass(frozen=True)
class Mux:
    node: int
    lo: int                  # absolute chain position
    width: int
    base: int                # value of input 0 (1 for tracks, 2 for IPINs)
    inputs: tuple
    tile: str


def _build(spec, name):
    fields, off = [], 0
    for fname, width, kind, group, doc in spec:
        fields.append(Field(fname, off, width, kind, group, doc))
        off += width
    return TileType(name, tuple(fields))


def rr_path(k):
    return os.path.join(ARCH_DIR, f"bob_k{k}_rr.xml.gz")


def arch_path(k):
    return os.path.join(ARCH_DIR, f"bob_k{k}.xml")


class StaleRRGraph(RuntimeError):
    pass


class Device:
    def __init__(self, lut_k=6, arch=None, with_rr=True, rr_file=None):
        if not 2 <= lut_k <= 6:
            raise ValueError("lut_k must be 2..6")
        self.arch = dict(ARCH if arch is None else arch)
        a = self.arch
        self.lut_k = lut_k
        self.width, self.height = a["nx"] + 2, a["ny"] + 2
        self.name = f"bob{a['nx']}x{a['ny']}"
        a.update(vpr_width=self.width, vpr_height=self.height,
                 columns=[dict(c, startx=c["x"]) for c in a["columns"]])

        self.tile_types = {"ctrl": self._ctrl_type(), "clb": self._clb_type(),
                           "bram": self._bram_type(), "dsp": self._dsp_type()}
        self._grid()
        self.rr = None
        self.tiles = []
        self.rr_file = rr_file                 # software/bob/sweep.py: a graph built elsewhere
        if with_rr:
            self._load_rr()

    # --- the grid (VPR's fixed_layout rules, checked against the rr graph) -------------

    def _grid(self):
        W, H = self.width, self.height
        cell = {}
        for x in range(W):
            for y in range(H):
                if x in (0, W - 1) and y in (0, H - 1):
                    cell[(x, y)] = ("EMPTY", x, y)
                elif x in (0, W - 1) or y in (0, H - 1):
                    cell[(x, y)] = ("io", x, y)
                else:
                    cell[(x, y)] = ("clb", x, y)
        for col in self.arch["columns"]:
            x, h, y = col["x"], col["height"], 1
            while y <= H - 2:
                if y + h - 1 <= H - 2:
                    for dy in range(h):
                        cell[(x, y + dy)] = (col["type"], x, y)
                    y += h
                else:
                    cell[(x, y)] = ("EMPTY", x, y)
                    y += 1
        self.cell = cell
        roots = sorted({(r[2], r[1], r[0]) for r in cell.values() if r[0] != "EMPTY"})
        count = {}
        self.blocks = []
        for y, x, t in roots:
            i = count.get(t, 0)
            count[t] = i + 1
            name = f"{t}{i}" if t in ("bram", "dsp") else f"{t}_x{x}y{y}"
            self.blocks.append(Block(name, t, x, y, i, -1))
        self.by_type = {t: [b for b in self.blocks if b.type == t] for t in ("io", "clb", "bram", "dsp")}
        self.block_at = {(b.x, b.y): b for b in self.blocks}

        # pads: io blocks row-major; board pins on the West (inputs) and East (outputs) edges
        self.pads = self.by_type["io"]
        pad_of = {(b.x, b.y): b.index for b in self.pads}
        # inputs fill the West edge bottom-up, then the South edge left to right;
        # outputs fill the East edge bottom-up (every design crosses the grid)
        in_slots = [(0, y) for y in range(1, H - 1)] + [(x, 0) for x in range(1, W - 1)]
        out_slots = [(W - 1, y) for y in range(1, H - 1)]
        self.board_inputs = [{"name": n, "pad": pad_of[in_slots[i]], "bit": i}
                             for i, n in enumerate(BOARD_INPUTS)]
        self.board_outputs = [{"name": n, "pad": pad_of[out_slots[i]], "bit": i}
                              for i, n in enumerate(BOARD_OUTPUTS)]

    # --- block fields -----------------------------------------------------------------

    def _ctrl_type(self):
        return _build([
            ("clk_mode", 1, "flag", "ctrl",
             "0: fabric clock enable = one pulse per TCK rising edge while USER1 ce (JTAG-stepped); "
             "1: free-running divider"),
            ("clk_div", 5, "value", "ctrl",
             f"free-running: enable every 2**(clk_div+{DIV_MIN_SHIFT}) sysclk cycles (when clk_period is 0)"),
            ("reserved", 2, "reserved", "ctrl", "write 0"),
            ("clk_period", PERIOD_W, "value", "ctrl",
             "M20 free-running: enable every clk_period x 2**clk_div sysclk cycles; "
             "0 = every 2**(clk_div+DIV_MIN_SHIFT)"),
            ("clk_gap", PERIOD_W, "value", "ctrl",
             f"M20: this design's minimum gce spacing in sysclk cycles, from its critical path "
             f"(never below {GCE_GAP_FLOOR}); 0 = the safe 2**{GCE_MIN_GAP_SHIFT}"),
        ], "ctrl")

    # M21: one logic element (hw/src/clb/ble.sv). AMD UG474: LUT6_2 fracture (generalised
    # to K), CARRY4-style MUXCY/XORCY, FDRE/FDSE; the second flip-flop registers O5, as a
    # slice's second FF per LUT does.
    ELEMENT_FIELDS = (
        ("frac", 1, "flag", "two LUT(K-1)s: input K-1 reads 1, so O6 = INIT[2**K-1:2**(K-1)] and "
                            "O5 = INIT[2**(K-1)-1:0], both over i[K-2:0]"),
        ("ff_en", 1, "flag", "out[0] = FF q (1) or combinational (0)"),
        ("ff_rstval", 1, "flag", "INIT and sync reset value: FDRE=0 / FDSE=1"),
        ("ff_ce_en", 1, "flag", "1: FF honours the CLB's routed CE, 0: always enabled"),
        ("ff_sr_en", 1, "flag", "1: FF honours the CLB's routed SR, 0: reset ignored"),
        ("cy_en", 1, "flag", "carry mode: XORCY sum on out[0]'s datapath, MUXCY cout"),
        ("cy_di_sel", 1, "flag", "carry generate: 0 = i[0], 1 = O5"),
        ("ff_d_sel", 1, "flag", "out[0] datapath: 0 = O6, 1 = O5 (ignored if cy_en)"),
        ("ff2_en", 1, "flag", "out[1] = second FF q (1) or O5 (0)"),
        ("ff2_rstval", 1, "flag", "second FF: INIT and sync reset value"),
        ("ff2_ce_en", 1, "flag", "second FF honours the routed CE"),
        ("ff2_sr_en", 1, "flag", "second FF honours the routed SR"),
    )

    @property
    def cluster(self):
        return self.arch["cluster"]

    def xbar_sources(self, e, j):
        """Crossbar sources of element e's input j, as CLB pin names in mux input order
        (after const0 and const1): 'I[k]' then 'O[m]' (element feedback)."""
        c = self.cluster
        srcs = [f"I[{k}]" for k in range(c["i"])] + [f"O[{m}]" for m in range(2 * c["n"])]
        if c["xbar"] == "full":
            return srcs
        if c["xbar"] == "half":
            # every other source, alternating with the input: the K inputs of one element
            # see every source, so a LUT (inputs permutable) can take any net
            return [p for s, p in enumerate(srcs) if (s + e + j) % 2 == 0]
        raise ValueError(f"crossbar {c['xbar']!r}: full or half")

    def xbar_width(self):
        n = len(self.xbar_sources(0, 0))
        assert all(len(self.xbar_sources(e, j)) == n
                   for e in range(self.cluster["n"]) for j in range(self.lut_k))
        return (n + 1).bit_length()                  # values 0 const0, 1 const1, 2.. inputs

    def _clb_type(self):
        k = self.lut_k
        xw = self.xbar_width()
        spec = []
        for e in range(self.cluster["n"]):
            spec.append((f"e{e}.init", 1 << k, "lut_init", "clb",
                         f"element {e}: LUT{k} truth table; O5 = INIT[{(1 << (k - 1)) - 1}:0] over i[{k - 2}:0]"))
            spec += [(f"e{e}.{n}", w, kind, "clb", doc) for n, w, kind, doc in self.ELEMENT_FIELDS]
            spec += [(f"e{e}.x{j}", xw, "mux", "xbar",
                      f"element {e} input {j}: 0 const0, 1 const1, 2.. crossbar source "
                      f"(xbar_sources)") for j in range(k)]
        return _build(spec, "clb")

    def element_width(self):
        return self.tile_types["clb"].width // self.cluster["n"]

    def _bram_type(self):
        return _build([
            ("wmode_a", 2, "value", "bram", "port A write mode: 0 WRITE_FIRST, 1 READ_FIRST, 2 NO_CHANGE"),
            ("wmode_b", 2, "value", "bram", "port B write mode"),
            ("reg_a", 1, "flag", "bram", "DOA_REG: port A output register"),
            ("reg_b", 1, "flag", "bram", "DOB_REG: port B output register"),
            ("jtag_a", 1, "flag", "bram", "port A pins from the USER4 drive word instead of the fabric"),
            ("jtag_b", 1, "flag", "bram", "port B pins from the USER4 drive word instead of the fabric"),
        ], "bram")

    def _dsp_type(self):
        spec = [("opmode", 2, "value", "dsp", "0 M, 1 M+C, 2 P+M, 3 (PCIN>>>17)+M"),
                ("use_d", 1, "flag", "dsp", "pre-adder on: AD = D +/- A"),
                ("d_sub", 1, "flag", "dsp", "pre-adder subtracts: AD = D - A")]
        spec += [(r, 1, "flag", "dsp", f"{r.upper()} register stage")
                 for r in ("areg", "breg", "creg", "dreg", "mreg", "preg")]
        spec += [(f"jtag_{bus}", 1, "flag", "dsp", f"bus {bus.upper()} from the DSP JTAG drive word")
                 for bus, _w in DSP_BUSES]
        spec += [("jtag_ctrl", 1, "flag", "dsp", "CE/RST controls from the DSP JTAG drive word"),
                 ("reserved", 1, "reserved", "dsp", "write 0")]
        return _build(spec, "dsp")

    # --- tile pins (the VPR architecture's view) --------------------------------------

    def block_ports(self, t):
        """[(dir, name, width)] for a block type, in VPR pin order."""
        k = self.lut_k
        if t == "io":
            return [("in", "outpad", 1), ("out", "inpad", 1)]
        if t == "clb":
            c = self.cluster
            return [("in", "I", c["i"]), ("in", "ce", 1), ("in", "sr", 1), ("in", "cin", 1),
                    ("out", "O", 2 * c["n"]), ("out", "cout", 1), ("clk", "clk", 1)]
        if t == "bram":
            ports = []
            for p in "ab":
                ports += [("in", f"{n}_{p}", w) for n, w in BRAM_PORT_PINS]
            return ports + [("out", "do_a", BRAM_DATA_W), ("out", "do_b", BRAM_DATA_W), ("clk", "clk", 1)]
        if t == "dsp":
            ports = [("in", n, w) for n, w in DSP_BUSES]
            ports += [("in", n, 1) for n in DSP_CTRL_NAMES]
            return ports + [("in", "pcin", 48), ("out", "p", 48), ("out", "pcout", 48), ("clk", "clk", 1)]
        raise KeyError(t)

    def vpr_models(self):
        # M9: the CLB primitives bob's yosys flow emits (software/bob/synth), as VPR models.
        # bob_add = BOB_ADD (the LUT's A^B plus MUXCY/XORCY), bob_ff = BOB_FDRE or BOB_FDSE;
        # shaped like the reference arch's adder and dffr/dffs models.
        out = [
            {"name": "bob_add",
             "inputs": [(n, 1, ' combinational_sink_ports="sumout cout"') for n in ("a", "b", "cin")],
             "outputs": [("cout", 1, ""), ("sumout", 1, "")]},
        ]
        out.append({"name": "bob_ff",
                    "inputs": [("D", 1, ' clock="C"'), ("CE", 1, ' clock="C"'),
                               ("SR", 1, ' clock="C"'), ("C", 1, ' is_clock="1"')],
                    "outputs": [("Q", 1, ' clock="C"')]})
        for t, model in (("bram", "bob_bram"), ("dsp", "bob_dsp")):
            ins = [(n, w, ' clock="clk"') for d, n, w in self.block_ports(t) if d == "in"]
            ins.append(("clk", 1, ' is_clock="1"'))
            outs = [(n, w, ' clock="clk"') for d, n, w in self.block_ports(t) if d == "out"]
            out.append({"name": model, "inputs": ins, "outputs": outs})
        return out

    def vpr_tiles(self):
        k = self.lut_k
        h = k // 2

        def around(name, ports, height, fc0):
            # Routable pins round-robin over the sides that face a channel: left and
            # right at every row, the bottom of row 0, the top of the last row.
            # (VPR's "spread" puts pins on top/bottom sides INSIDE a tall block,
            # where through_channel="false" leaves no channel - unroutable pins.)
            locs = [("left", y) for y in range(height)] + [("right", y) for y in range(height)]
            locs += [("bottom", 0), ("top", height - 1)]
            slots = {loc: [] for loc in locs}
            i = 0
            for d, n, w in ports:
                if d == "clk" or n in fc0:
                    side = ("top", height - 1) if d == "out" else ("bottom", 0)
                    slots[side].append(f"{name}.{n}[{w - 1}:0]")
                    continue
                for b in range(w):
                    slots[locs[i % len(locs)]].append(f"{name}.{n}[{b}]")
                    i += 1
            return [(s, y, p) for (s, y), p in slots.items() if p]

        heights = {c["type"]: c["height"] for c in self.arch["columns"]}
        a = self.arch
        return [
            {"name": "io", "height": 1, "capacity": a["io_capacity"], "ports": self.block_ports("io"),
             "fc0": [],
             # the reference's io: every pin on all four sides (only the core-facing one has a channel)
             "pinloc": [(s, 0, ["io.outpad", "io.inpad"]) for s in ("left", "top", "right", "bottom")]},
            {"name": "clb", "height": 1, "capacity": 1, "ports": self.block_ports("clb"),
             "fc0": ["cin", "cout", "clk"],
             # a full crossbar makes every CLB input equivalent (the reference's clb.I)
             "equivalent": ("I",) if self.cluster["xbar"] == "full" else (),
             "pinloc": self._clb_pinloc()},
            {"name": "bram", "height": heights["bram"], "capacity": 1, "model": "bob_bram",
             "ports": self.block_ports("bram"), "fc0": ["clk"],
             "pinloc": around("bram", self.block_ports("bram"), heights["bram"], ["clk"])},
            {"name": "dsp", "height": heights["dsp"], "capacity": 1, "model": "bob_dsp",
             "ports": self.block_ports("dsp"), "fc0": ["clk", "pcin", "pcout"],
             "pinloc": around("dsp", self.block_ports("dsp"), heights["dsp"], ["clk", "pcin", "pcout"])},
        ]

    def _clb_pinloc(self):
        """CLB pins round-robin over the four sides (inputs and outputs each start on a
        different side, so every channel carries both); carry in at the bottom and out
        at the top (the chain runs South to North), the clock and CE on the left, SR on
        the right."""
        c = self.cluster
        sides = ("left", "top", "right", "bottom")
        slots = {s: [] for s in sides}
        for k in range(c["i"]):
            slots[sides[k % 4]].append(f"clb.I[{k}]")
        for m in range(2 * c["n"]):
            slots[sides[(m + 2) % 4]].append(f"clb.O[{m}]")
        slots["bottom"].append("clb.cin")
        slots["top"].append("clb.cout")
        slots["left"] += ["clb.clk", "clb.ce"]
        slots["right"].append("clb.sr")
        return [(s, 0, slots[s]) for s in sides]

    def vpr_directs(self):
        h = {c["type"]: c["height"] for c in self.arch["columns"]}["dsp"]
        # South to North, as bob's carry chain always ran (the reference runs its adder downwards)
        return [{"name": "carry", "from": "clb.cout", "to": "clb.cin", "dx": 0, "dy": 1},
                {"name": "dsp_cascade", "from": "dsp.pcout", "to": "dsp.pcin", "dx": 0, "dy": h}]

    def arch_xml(self):
        return vpr_arch.arch_xml(self)

    # --- the routing-resource graph -> muxes -> chain ------------------------------------

    def _load_rr(self):
        from rrgraph import RRGraph
        path = self.rr_file or rr_path(self.lut_k)
        stamp = path.replace("_rr.xml.gz", "_rr.stamp")
        want = hashlib.sha256(self.arch_xml().encode()).hexdigest()
        if self.rr_file:
            pass
        elif not (os.path.exists(path) and os.path.exists(stamp)):
            raise StaleRRGraph(f"no rr graph for K={self.lut_k}: run `make rrgraph` (Docker)")
        got = {} if self.rr_file else dict(
            line.split(" ", 1) for line in open(stamp).read().splitlines() if " " in line)
        if not self.rr_file and got.get("arch_sha256") != want:
            raise StaleRRGraph(f"{os.path.relpath(path, ROOT)} was built from a different "
                               f"architecture: run `make rrgraph` (Docker)")
        rr = RRGraph(path)
        self.rr = rr
        if rr.chan_width != self.arch["chan_width"]:
            raise StaleRRGraph(f"rr graph has W={rr.chan_width}, arch says {self.arch['chan_width']}")

        # the grid VPR built must be the one described here
        for (x, y), (t, wo, ho) in rr.grid.items():
            mine = self.cell[(x, y)]
            if (mine[0], x - mine[1], y - mine[2]) != (t, wo, ho):
                raise ValueError(f"grid ({x},{y}): VPR has {t}+{wo}/{ho}, device.py has {mine}")

        # pins: (block, 'I[3]') -> node
        self.pin_node, self.node_pin = {}, {}
        for nid, n in rr.nodes.items():
            if n.type not in ("IPIN", "OPIN"):
                continue
            rx, ry = rr.block_root(nid)
            blk = self.block_at[(rx, ry)]
            pin = rr.pin_name(nid).split(".", 1)[1]           # 'clb[0].I[3]' -> 'I[3]'
            self.pin_node[(blk.name, pin)] = nid
            self.node_pin[nid] = (blk.name, pin)

        # muxes and directs
        mux_spec, self.direct, self.undriven = {}, {}, []
        for nid, n in rr.nodes.items():
            if n.type not in ("CHANX", "CHANY", "IPIN"):
                continue
            ins = rr.fanin[nid]
            if n.type == "IPIN" and ins and all(rr.nodes[s].type == "OPIN" for s in ins):
                assert len(ins) == 1, f"IPIN {nid} has several direct drivers"
                self.direct[nid] = ins[0]
                continue
            assert all(rr.nodes[s].type in ("CHANX", "CHANY", "OPIN") for s in ins), nid
            if not ins:
                self.undriven.append(nid)
                continue
            if n.type == "IPIN":
                owner = (n.xlow, n.ylow)
                base = 2
            elif n.direction == "INC_DIR":
                owner, base = (n.xlow, n.ylow), 1
            elif n.direction == "DEC_DIR":
                owner, base = (n.xhigh, n.yhigh), 1
            else:
                raise ValueError(f"node {nid}: bidirectional wire in a unidirectional architecture")
            width = (len(ins) + base - 1).bit_length()
            mux_spec.setdefault(owner, []).append((nid, width, base, tuple(ins)))

        # memory: frames of FRAME_BITS, column-major (M13, docs/bitstream-format.md section 9).
        # FAR column 0: the ctrl tile; FAR column x+1: grid column x, tiles bottom to top
        # (block fields, then muxes by node id); each column padded to whole frames. The
        # chain is exactly all frames end to end.
        self.tiles = [Tile("ctrl", "ctrl", None, None, 0, self.tile_types["ctrl"].fields)]
        lo = self.tile_types["ctrl"].width
        self.frames = []                   # [{"far_col", "x", "base", "count", "lo"}]

        def close_column(far_col, x, start):
            nonlocal lo
            if lo == start:
                return
            if lo % FRAME_BITS:
                pad = FRAME_BITS - lo % FRAME_BITS
                self.tiles.append(Tile(f"pad_c{far_col}", "tail", None, None, lo,
                                       (Field("reserved", 0, pad, "reserved", "ctrl", "frame padding, write 0"),)))
                lo += pad
            self.frames.append({"far_col": far_col, "x": x, "base": start // FRAME_BITS,
                                "count": (lo - start) // FRAME_BITS, "lo": start})

        close_column(0, None, 0)
        self.muxes = {}
        blocks = []
        for x in range(self.width):
            start = lo
            for y in range(self.height):
                fields, off = [], 0
                blk = self.block_at.get((x, y))
                if blk is not None and blk.type in ("clb", "bram", "dsp"):
                    for f in self.tile_types[blk.type].fields:
                        fields.append(Field(f.name, off, f.width, f.kind, f.group, f.doc))
                        off += f.width
                    blocks.append(Block(blk.name, blk.type, x, y, blk.index, lo))
                elif blk is not None:
                    blocks.append(blk)
                for nid, width, base, ins in sorted(mux_spec.get((x, y), [])):
                    fields.append(Field(f"rr{nid}", off, width, "mux", "rr",
                                        f"{rr.nodes[nid].type} mux, {len(ins)} inputs"))
                    self.muxes[nid] = Mux(nid, lo + off, width, base, ins, f"t_x{x}y{y}")
                    off += width
                if fields:
                    self.tiles.append(Tile(f"t_x{x}y{y}", "grid", x, y, lo, tuple(fields)))
                    lo += off
            close_column(x + 1, x, start)
        self.nframes = lo // FRAME_BITS
        self._elements(blocks)
        # only memory positions are column-major: blocks keep their row-major order,
        # which the fabric's clb_o bits and CAPTURE use (block.index)
        blocks.sort(key=lambda bl: (bl.y, bl.x))
        self.chain_width = lo
        self.blocks = blocks
        self.by_type = {t: [b for b in blocks if b.type == t] for t in ("io", "clb", "bram", "dsp")}
        self.block_at = {(b.x, b.y): b for b in blocks}
        self.block_by_name = {b.name: b for b in blocks}
        self.tile_by_name = {t.name: t for t in self.tiles}
        self._tile_los = [t.chain_lo for t in self.tiles]
        self._bitmap = {}
        for t in self.tiles:
            m = [None] * t.width
            for f in t.fields:
                for b in range(f.width):
                    m[f.offset + b] = (f, b)
            self._bitmap[t.name] = m

    def _elements(self, blocks):
        """M21: the inside of every CLB as more nodes of the same graph. Each element
        input is a node (type EIN) driven by its crossbar mux, whose select bits are the
        CLB field e<e>.x<j> and whose inputs are the CLB's own IPIN/OPIN nodes; each carry
        link between two elements is a node (type ECY). Element outputs are the CLB's
        O pins (element e: O[2e] and O[2e+1]); CE, SR and the clock are shared. Every
        host tool (model, router, timing) then sees the crossbar as routing muxes."""
        c, k = self.cluster, self.lut_k
        nid = max(self.rr.nodes) + 1
        self.ext_nodes = {}                    # id -> (type, x, y, "e,j")
        self.elements = []                     # [{name, clb, e, x, y, index, chain_lo, pins}]
        ew = self.element_width()
        for blk in sorted((b for b in blocks if b.type == "clb"), key=lambda b: (b.y, b.x)):
            P = lambda pin: self.pin_node[(blk.name, pin)]          # noqa: E731
            cin = P("cin[0]")
            for e in range(c["n"]):
                pins = {}
                for j in range(k):
                    self.ext_nodes[nid] = ("EIN", blk.x, blk.y, f"{e},{j}")
                    lo, w = self.block_field(blk, f"e{e}.x{j}")
                    ins = tuple(P(p) for p in self.xbar_sources(e, j))
                    self.muxes[nid] = Mux(nid, lo, w, 2, ins, f"t_x{blk.x}y{blk.y}")
                    self.pin_node[(blk.name, f"e{e}.I[{j}]")] = nid
                    self.node_pin[nid] = (blk.name, f"e{e}.I[{j}]")
                    pins[f"I[{j}]"] = nid
                    nid += 1
                if e + 1 < c["n"]:
                    cout = nid
                    self.ext_nodes[nid] = ("ECY", blk.x, blk.y, f"{e},0")
                    self.pin_node[(blk.name, f"e{e}.cout[0]")] = nid
                    self.node_pin[nid] = (blk.name, f"e{e}.cout[0]")
                    nid += 1
                else:
                    cout = P("cout[0]")
                pins.update({"cin": cin, "cout": cout, "out0": P(f"O[{2 * e}]"),
                             "out1": P(f"O[{2 * e + 1}]"), "ce": P("ce[0]"), "sr": P("sr[0]")})
                self.elements.append({"name": f"{blk.name}.e{e}", "clb": blk.name, "e": e,
                                      "x": blk.x, "y": blk.y, "index": len(self.elements),
                                      "chain_lo": blk.chain_lo + e * ew, "pins": pins})
                cin = cout

    # --- lookups --------------------------------------------------------------------

    @property
    def ctrl_tile(self):
        return self.tiles[0]

    def block_field(self, block, name):
        """(absolute chain lo, width) of a block's field."""
        b = self.block_by_name[block] if isinstance(block, str) else block
        f = self.tile_types[b.type].field(name)
        return b.chain_lo + f.offset, f.width

    def chain_bit(self, tile, field_name, bit=0):
        f = tile.field(field_name)
        if not 0 <= bit < f.width:
            raise ValueError(f"{field_name} has {f.width} bits")
        return tile.chain_lo + f.offset + bit

    def locate(self, k):
        """chain bit -> (tile, field, bit within field)"""
        if not 0 <= k < self.chain_width:
            raise ValueError(f"chain bit {k} outside 0..{self.chain_width - 1}")
        tile = self.tiles[bisect.bisect_right(self._tile_los, k) - 1]
        f, b = self._bitmap[tile.name][k - tile.chain_lo]
        return tile, f, b

    def decode(self, word):
        """chain word -> {tile name: {field name: value}}"""
        return {t.name: {f.name: (word >> (t.chain_lo + f.offset)) & ((1 << f.width) - 1)
                         for f in t.fields} for t in self.tiles}

    def encode(self, cfg):
        """{tile name: {field name: value}} -> chain word; missing fields are 0"""
        word = 0
        for tname, vals in cfg.items():
            t = self.tile_by_name[tname]
            for fname, v in vals.items():
                f = t.field(fname)
                if not 0 <= v < (1 << f.width):
                    raise ValueError(f"{tname}.{fname} = {v} does not fit {f.width} bits")
                word |= v << (t.chain_lo + f.offset)
        return word

    def pips(self):
        """Every programmable connection: (tile, mux node, source node, (chain lo, width, value))."""
        for m in self.muxes.values():
            for i, src in enumerate(m.inputs):
                yield m.tile, m.node, src, (m.lo, m.width, m.base + i)

    # --- emitters ---------------------------------------------------------------------

    def to_json(self):
        rr = self.rr
        a = self.arch
        return {
            "name": self.name,
            "generated_by": "software/bob/device.py - do not edit",
            "lut_k": self.lut_k,
            "arch": {"grid_width": self.width, "grid_height": self.height,
                     "chan_width": a["chan_width"], "segment_length": a["segment_length"],
                     "switch_block": f"wilton fs={a['fs']}", "fc_in": a["fc_in"], "fc_out": a["fc_out"],
                     "vpr_arch": f"software/bob/arch/bob_k{self.lut_k}.xml",
                     "rr_graph": f"software/bob/arch/bob_k{self.lut_k}_rr.xml.gz",
                     "columns": [{"type": c["type"], "x": c["x"], "height": c["height"]}
                                 for c in a["columns"]]},
            "clock": {"sysclk_hz": SYSCLK_HZ, "div_min_shift": DIV_MIN_SHIFT,
                      "gce_min_gap_shift": GCE_MIN_GAP_SHIFT,
                      "xdc_multicycle": XDC_SYSCLK_MULTICYCLE,
                      "xdc_tck_multicycle": XDC_TCK_MULTICYCLE,
                      "gce_gap_floor": GCE_GAP_FLOOR, "period_w": PERIOD_W,
                      "modes": {"jtag": 0, "run": 1}},
            "tile_types": {name: {"width": tt.width,
                                  "fields": [{"name": f.name, "offset": f.offset, "width": f.width,
                                              "kind": f.kind, "group": f.group, "doc": f.doc}
                                             for f in tt.fields]}
                           for name, tt in self.tile_types.items()},
            "blocks": [{"name": b.name, "type": b.type, "x": b.x, "y": b.y, "index": b.index,
                        "chain_lo": b.chain_lo} for b in self.blocks],
            "block_ports": {t: [[d, n, w] for d, n, w in self.block_ports(t)]
                            for t in ("io", "clb", "bram", "dsp")},
            "pins": {f"{b}.{p}": n for (b, p), n in sorted(self.pin_node.items())},
            "rr": {
                "doc": "nodes: [id, type, xlow, ylow, xhigh, yhigh, ptc, direction]; "
                       "muxes: [node, chain_lo, width, base, [input nodes]] - value base+i selects "
                       "input i, 0 const0, 1 const1 (IPIN only); directs: [ipin, opin]",
                "nodes": [[n.id, n.type, n.xlow, n.ylow, n.xhigh, n.yhigh,
                           ",".join(map(str, n.ptc)), n.direction]
                          for n in rr.nodes.values() if n.type in ("CHANX", "CHANY", "IPIN", "OPIN")]
                         + [[i, t, x, y, x, y, ptc, None] for i, (t, x, y, ptc) in sorted(self.ext_nodes.items())],
                "muxes": [[m.node, m.lo, m.width, m.base, list(m.inputs)]
                          for m in sorted(self.muxes.values(), key=lambda m: m.node)],
                "directs": [[i, o] for i, o in sorted(self.direct.items())],
                "undriven": sorted(self.undriven),
            },
            "tiles": [{"name": t.name, "kind": t.kind, "x": t.x, "y": t.y, "chain_lo": t.chain_lo,
                       "width": t.width} for t in self.tiles],
            "chain": {
                "width": self.chain_width,
                "order": "frames end to end (M13): FAR column 0 = ctrl tile, FAR column x+1 = grid "
                         "column x with tiles bottom to top (the fields of the block rooted there, "
                         "then its routing muxes by rr node id), each column padded to whole frames",
                "bit_order": "chain bit k is the k-th bit shifted in on TDI (LSB-first)",
            },
            "frames": {"words": FRAME_WORDS, "bits": FRAME_BITS, "count": self.nframes,
                       "columns": [{k: c[k] for k in ("far_col", "x", "base", "count")} for c in self.frames],
                       "far": "[25:23] block type (000 config), [22] top/bottom, [21:17] row, "
                              "[16:7] column, [6:0] minor",
                       "doc": "frame f = chain bits [128f+127:128f]; word w bit k = frame bit 32w+k"},
            "pads": {"count": len(self.pads),
                     "io": [{"pad": b.index, "x": b.x, "y": b.y} for b in self.pads],
                     "board_inputs": self.board_inputs, "board_outputs": self.board_outputs},
            "bsr": {"width": 2 * len(self.pads),
                    "cells": "cell k (bit k, cell 0 nearest TDO): k < NPAD output cell of pad k "
                             "(fabric -> world, GTS-gated), k >= NPAD input cell of pad k-NPAD "
                             "(world -> fabric)"},
            "cluster": {"n": self.cluster["n"], "i": self.cluster["i"], "xbar": self.cluster["xbar"],
                        "frac": self.cluster["frac"], "element_width": self.element_width(),
                        "xbar_width": self.xbar_width(),
                        "xbar_sources": [[self.xbar_sources(e, j) for j in range(self.lut_k)]
                                         for e in range(self.cluster["n"])],
                        "doc": "CLB = n elements; element e's fields are e<e>.* at chain_lo + "
                               "e * element_width; its input j is node EIN driven by the crossbar "
                               "mux e<e>.x<j> (0 const0, 1 const1, 2+i xbar_sources[e][j][i]); "
                               "its outputs are the CLB's O[2e] (out[0]) and O[2e+1] (out[1])"},
            "elements": [{"name": el["name"], "clb": el["clb"], "e": el["e"], "x": el["x"], "y": el["y"],
                          "index": el["index"], "chain_lo": el["chain_lo"], "pins": el["pins"]}
                         for el in self.elements],
            "capture": {"width": 2 * len(self.elements), "status_w": STATUS_W,
                        "order": [f"{el['name']}.out{o}" for el in self.elements for o in (0, 1)]},
            "bram": {"count": len(self.by_type["bram"]), "addr_w": BRAM_ADDR_W, "data_w": BRAM_DATA_W,
                     "port_pins": [[n, w] for n, w in BRAM_PORT_PINS],
                     "write_modes": BRAM_WRITE_MODES, "jtag_version": BRAM_JTAG_VERSION,
                     "drive": "64 bits per BRAM: port A pins [31:0] (addr, di, we, en, rst, regce), port B [63:32]",
                     "jtag": "USER4 data register, docs/bitstream-format.md"},
            "dsp": {"count": len(self.by_type["dsp"]), "opmodes": DSP_OPMODES,
                    "buses": [[n, w] for n, w in DSP_BUSES], "ctrl_names": list(DSP_CTRL_NAMES),
                    "drive_per_slice": DSP_DRIVE_PER_SLICE, "jtag_version": DSP_JTAG_VERSION,
                    "cascade": "dsp1.pcin <- dsp0.pcout (= P), a VPR direct; dsp0.pcin = 0",
                    "jtag": "private instruction DSP 101000, docs/bitstream-format.md"},
        }

    def verilog_params(self):
        tt = self.tile_types["clb"]
        ct = self.tile_types["ctrl"]
        vals = [
            ("LUT_K", self.lut_k), ("LUT_INIT_W", 1 << self.lut_k), ("CLB_CFG_W", tt.width),
            ("CLB_N", self.cluster["n"]), ("CLB_I", self.cluster["i"]),
            ("ELE_W", self.element_width()), ("XBAR_W", self.xbar_width()),
            ("XBAR_N", len(self.xbar_sources(0, 0))),
            ("ELE_INIT_LO", tt.field("e0.init").offset),
        ]
        for name, _w, _k, _d in self.ELEMENT_FIELDS:
            vals.append((f"ELE_{name.upper()}", tt.field(f"e0.{name}").offset))
        vals.append(("ELE_XBAR_LO", tt.field("e0.x0").offset))
        vals += [
            ("GRID_W", self.width), ("GRID_H", self.height), ("CHAN_W", self.arch["chan_width"]),
            ("CTRL_W", ct.width), ("CHAIN_W", self.chain_width),
            ("CTRL_CLK_MODE", ct.field("clk_mode").offset),
            ("CTRL_CLK_DIV_LO", ct.field("clk_div").offset),
            ("CTRL_CLK_DIV_W", ct.field("clk_div").width),
            ("CTRL_CLK_PERIOD_LO", ct.field("clk_period").offset),
            ("CTRL_CLK_GAP_LO", ct.field("clk_gap").offset),
            ("CTRL_PERIOD_W", PERIOD_W), ("GCE_GAP_FLOOR", GCE_GAP_FLOOR),
            ("DIV_MIN_SHIFT", DIV_MIN_SHIFT), ("GCE_MIN_GAP_SHIFT", GCE_MIN_GAP_SHIFT),
            ("FRAME_WORDS", FRAME_WORDS), ("FRAME_BITS", FRAME_BITS), ("NFRAMES", self.nframes),
            ("FIDX_W", max(8, self.nframes.bit_length())),
            ("FAR_NCOLS", len(self.frames) and max(c["far_col"] for c in self.frames) + 1),
            ("NPAD", len(self.pads)), ("BSR_W", 2 * len(self.pads)),
            ("NCLB", len(self.by_type["clb"])), ("NELEM", len(self.elements)),
            ("NCAP", 2 * len(self.elements)), ("STATUS_W", STATUS_W),
            ("NBRAM", len(self.by_type["bram"])), ("NDSP", len(self.by_type["dsp"])),
            ("BRAM_ADDR_W", BRAM_ADDR_W), ("BRAM_DATA_W", BRAM_DATA_W),
            ("BRAM_PORT_PINS", sum(w for _n, w in BRAM_PORT_PINS)),
            ("BRAM_CFG_W", self.tile_types["bram"].width), ("DSP_CFG_W", self.tile_types["dsp"].width),
            ("DSP_DRIVE_W", DSP_DRIVE_PER_SLICE),
        ]
        vals += [(f"PAD_{p['name']}", p["pad"]) for p in self.board_inputs + self.board_outputs]
        lines = [
            "// -----------------------------------------------------------------------------",
            "// bob_params.vh - GENERATED by software/bob/device.py, do not edit.",
            "//",
            f"// Device {self.name}, LUT K = {self.lut_k}, channel width {self.arch['chan_width']}.",
            "// hw/src/clb/clb_pkg.sv derives its CLB widths from BOB_LUT_K independently;",
            "// tests/test_device.py elaborates both in iverilog and compares every constant.",
            "// -----------------------------------------------------------------------------",
            "`ifndef BOB_PARAMS_VH",
            "`define BOB_PARAMS_VH",
            "",
        ]
        w = max(len(n) for n, _ in vals)
        lines += [f"`define BOB_{n:<{w}} {v}" for n, v in vals]
        # FAR column -> (first frame, frame count), packed 32 bits each (M21: more than 256
        # frames): [c*32 +: 16] base, [c*32+16 +: 16] count
        ncol = max(c["far_col"] for c in self.frames) + 1
        table = {c["far_col"]: c for c in self.frames}
        packed = 0
        for c in range(ncol):
            if c in table:
                assert table[c]["count"] <= 128, "a FAR column holds at most 128 frames (7-bit minor)"
                packed |= table[c]["base"] << (32 * c) | table[c]["count"] << (32 * c + 16)
        lines += ["", "// FAR column c: [32c+15:32c] first frame index, [32c+31:32c+16] frame count (0: no frames)",
                  f"`define BOB_FAR_TABLE {32 * ncol}'h{packed:0{8 * ncol}x}"]
        lines += ["", "`endif", ""]
        return "\n".join(lines)


def generated(lut_k=6, out_dir=None, arch_only=False):
    """{path: text} of every generated file for this LUT size."""
    files = {}
    if out_dir is None:
        for k in (6, 4):                       # both architectures are always committed
            files[arch_path(k)] = Device(lut_k=k, with_rr=False).arch_xml()
    if arch_only:
        return files
    import fabric_gen
    dev = Device(lut_k=lut_k)
    jpath = os.path.join(out_dir, JSON_NAME) if out_dir else JSON_PATH
    gdir = out_dir or GEN_DIR
    files[jpath] = json.dumps(dev.to_json(), separators=(",", ":")) + "\n"
    files[os.path.join(gdir, VH_NAME)] = dev.verilog_params()
    files[os.path.join(gdir, FABRIC_NAME)] = fabric_gen.fabric_verilog(dev)
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if a generated file is out of date")
    ap.add_argument("--arch-only", action="store_true", help="write only the VPR architectures")
    ap.add_argument("--lut-k", type=int, default=6)
    ap.add_argument("--out", help="write into this directory instead of the committed paths")
    args = ap.parse_args()
    if args.lut_k != 6 and not args.out:
        sys.exit("a non-default --lut-k needs --out: the committed build is K=6")

    stale = []
    try:
        files = generated(args.lut_k, args.out, args.arch_only)
    except StaleRRGraph as e:
        if args.check:
            print(f"  STALE       {e}")
            return 1
        for path, text in generated(args.lut_k, args.out, arch_only=True).items():
            with open(path, "w") as fh:
                fh.write(text)
        sys.exit(f"wrote the architectures only - {e}")
    for path, text in files.items():
        cur = open(path).read() if os.path.exists(path) else None
        rel = os.path.relpath(path, ROOT)
        if cur == text:
            print(f"  up to date  {rel}")
            continue
        if args.check:
            stale.append(rel)
            print(f"  STALE       {rel}")
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(text)
            print(f"  wrote       {rel}")
    if stale:
        print("run software/bob/device.py to regenerate")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
