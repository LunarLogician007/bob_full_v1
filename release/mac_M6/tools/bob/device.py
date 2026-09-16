#!/usr/bin/env python3
"""
device.py - the bob device description. THE single source of truth.

Every consumer reads what this file generates instead of repeating numbers:

  tools/bob/device.json             host tools (host/bitstream.py, model.py,
                                    later VPR arch and bitgen)
  hw/src/generated/bob_params.vh    RTL `defines (clb_pkg.sv, tile.v, fabric.v,
                                    fpga4x4.v, mini_fpga.v include it)

  ./device.py                        regenerate both
  ./device.py --check                exit 1 if either generated file is stale
  ./device.py --lut-k 4 --out DIR    write a variant into DIR (tests use this;
                                     the committed files are never touched)

Model
-----
  tile type   an ordered list of Fields (name, offset, width, kind, group).
              Offsets are relative to the tile's config word.
  tile        an instance of a type with a chain_lo. Fabric tiles have a
              (row, col); the ctrl tile has none.
  chain       the configuration scan chain. Bit k of the chain word is the k-th
              bit shifted in on TDI (LSB-first). Order: the ctrl tile first
              (bits 0..CTRL_W-1), then fabric tiles row-major. Chain position is
              DERIVED: chain_lo + field offset + bit.
  sources     the 20-entry mux source bus every CB/SB mux selects from.
  pip         (tile, mux field, source) -> the value written into that field.
  pads        where each board pad enters or leaves the fabric edge.

History
-------
  M1  the proven 4x4 fabric, bit for bit (LUT6, 181-bit tile, 2896-bit chain)
  M4  LUT size K is a parameter (default 6 - AMD UG474's LUT6_2; K=4 for
      OpenFPGA-style k4 architectures). Connection box gains routable CE and SR
      muxes (UG474: CE/SR are per-slice routable pins). A ctrl tile opens the
      chain: clock mode and divider for the user clock.
  M5  a BRAM tile (1024 x 18 true dual port, UG473 RAMB18E1 behaviour) closes the
      chain: write modes, output registers, 64 pin source muxes and 16 output
      muxes onto the fabric's East edge tracks.
  M6  a DSP tile (two cascaded DSP48E1-style slices, UG479 trimmed) on the North
      edge closes the chain.
"""

import argparse
import bisect
import json
import os
import sys
from dataclasses import dataclass
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
JSON_NAME = "device.json"
VH_NAME = "bob_params.vh"
JSON_PATH = os.path.join(HERE, JSON_NAME)
VH_PATH = os.path.join(ROOT, "hw", "src", "generated", VH_NAME)

DIRS = ("N", "E", "S", "W")          # index order is part of the layout

SYSCLK_HZ = 125_000_000              # PYNQ-Z2 PL clock on H16
DIV_MIN_SHIFT = 8                    # free-running enable: every 2**(clk_div+8) sysclk cycles

# M5 BRAM tile (hw/src/tiles/bram_tile.v): RAMB18E1-style 1024 x 18 true dual port
BRAM_ADDR_W = 10
BRAM_DATA_W = 18
BRAM_PIN_NAMES = ([f"addr{k}" for k in range(BRAM_ADDR_W)] + [f"di{k}" for k in range(BRAM_DATA_W)]
                  + ["we", "en", "rst", "regce"])
BRAM_PIN_SELW = 5
BRAM_OUT_SELW = 6
BRAM_EDGE_TRACKS = 16                # fabric East edge: row r track t = r*4+t
BRAM_WRITE_MODES = {"WRITE_FIRST": 0, "READ_FIRST": 1, "NO_CHANGE": 2}

# M6 DSP tile (hw/src/tiles/dsp_tile.v): two cascaded DSP48E1-style slices on the North edge
DSP_SLICES = 2
DSP_OPMODES = {"M": 0, "M+C": 1, "P+M": 2, "PCIN>>17+M": 3}
DSP_BUS_SOURCES = {"const0": 0, "jtag": 1, "fabric": 2}
DSP_CTRL_NAMES = ("ce_ad", "ce_b", "ce_m", "ce_p", "rst_ad", "rst_b", "rst_m", "rst_p")
DSP_CTRL_SELW = 5
DSP_OUT_SELW = 7
DSP_DRIVE_PER_SLICE = 25 + 18 + 48 + 25 + len(DSP_CTRL_NAMES)     # 124


@dataclass(frozen=True)
class Field:
    name: str
    offset: int
    width: int
    kind: str       # lut_init | flag | mux | value | reserved
    group: str      # clb | cb | sb | ctrl
    doc: str = ""


@dataclass(frozen=True)
class TileType:
    name: str
    fields: tuple

    @property
    def width(self):
        return max(f.offset + f.width for f in self.fields)

    def field(self, name):
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(f"{self.name} has no field {name}")


@dataclass(frozen=True)
class Tile:
    name: str
    type: str
    row: Optional[int]
    col: Optional[int]
    chain_lo: int


def _build(fields_spec, type_name):
    fields = []
    for name, width, kind, group, doc in fields_spec:
        off = sum(f.width for f in fields)
        fields.append(Field(name, off, width, kind, group, doc))
    return TileType(type_name, tuple(fields))


class Device:
    def __init__(self, rows=4, cols=4, ntrack=4, lut_k=6):
        if not 2 <= lut_k <= 6:
            raise ValueError("lut_k must be 2..6")
        self.name = f"bob{rows}x{cols}"
        self.rows, self.cols, self.ntrack, self.lut_k = rows, cols, ntrack, lut_k

        # Mux source bus, in the order clb_pkg.sv fixes. Code 0 is const0, so an
        # all-zero chain is a dark fabric with no loops.
        self.sources = (["const0", "const1", "clb_o", "clb_o5"]
                        + [f"{d}{t}" for d in DIRS for t in range(ntrack)])
        self.nsrc = len(self.sources)
        self.selw = (self.nsrc - 1).bit_length()

        self.tile_types = {"ctrl": self._ctrl_type(), "clb": self._clb_type(),
                           "bram": self._bram_type(), "dsp": self._dsp_type()}

        self.tiles = [Tile("ctrl", "ctrl", None, None, 0)]
        self.fabric_tiles = []
        lo = self.tile_types["ctrl"].width
        for r in range(rows):
            for c in range(cols):
                t = Tile(f"clb_r{r}c{c}", "clb", r, c, lo)
                self.tiles.append(t)
                self.fabric_tiles.append(t)
                lo += self.tile_types["clb"].width
        # M5: the BRAM tile on the East edge, spanning all rows, last in the chain
        self.bram_tile = Tile("bram", "bram", None, None, lo)
        self.tiles.append(self.bram_tile)
        lo += self.tile_types["bram"].width
        # M6: the DSP tile on the North edge, spanning all columns, last in the chain
        self.dsp_tile = Tile("dsp", "dsp", None, None, lo)
        self.tiles.append(self.dsp_tile)
        lo += self.tile_types["dsp"].width
        self.chain_width = lo
        self._tile_los = [t.chain_lo for t in self.tiles]

        # Per type: bit offset -> (field, bit within field)
        self._bitmap = {}
        for tt in self.tile_types.values():
            m = [None] * tt.width
            for f in tt.fields:
                for b in range(f.width):
                    m[f.offset + b] = (f, b)
            self._bitmap[tt.name] = m

        # Board pads. Inputs enter on an edge track of EVERY tile along that edge;
        # outputs leave one tile's edge track. Matches hw/src/fabric/fpga4x4.v.
        self.pad_inputs = (
            [{"pad": k, "edge": "W", "track": k, "board": b}
             for k, b in enumerate(("SW0", "SW1", "BTN0", "BTN1"))]
            + [{"pad": 4 + k, "edge": "S", "track": k, "board": b}
               for k, b in enumerate(("BTN2", "BTN3"))])
        self.pad_outputs = [{"pad": k, "row": k, "col": cols - 1, "dir": "E",
                             "track": 0, "board": f"LD{k}"} for k in range(3)]

    # --- tile types ----------------------------------------------------------

    def _ctrl_type(self):
        return _build([
            ("clk_mode", 1, "flag", "ctrl",
             "0: fabric clock enable = one pulse per TCK rising edge while USER1 ce (JTAG-stepped); "
             "1: free-running divider"),
            ("clk_div", 5, "value", "ctrl",
             f"free-running: enable every 2**(clk_div+{DIV_MIN_SHIFT}) sysclk cycles"),
            ("reserved", 2, "reserved", "ctrl", "write 0"),
        ], "ctrl")

    def _dsp_type(self):
        spec = []
        for s in range(DSP_SLICES):
            spec += [
                (f"s{s}_opmode", 2, "value", "dsp", "0 M, 1 M+C, 2 P+M, 3 (PCIN>>>17)+M"),
                (f"s{s}_use_d", 1, "flag", "dsp", "pre-adder on: AD = D +/- A"),
                (f"s{s}_d_sub", 1, "flag", "dsp", "pre-adder subtracts: AD = D - A"),
            ]
            spec += [(f"s{s}_{r}", 1, "flag", "dsp", f"{r.upper()} register stage")
                     for r in ("areg", "breg", "creg", "dreg", "mreg", "preg")]
            spec += [(f"s{s}_bus_{bus}", 2, "value", "dsp",
                      "0 const0, 1 JTAG drive, 2 fabric (bit k <- North track k), 3 const0")
                     for bus in "abcd"]
        spec.append(("reserved", 4, "reserved", "dsp", "write 0"))
        for s in range(DSP_SLICES):
            spec += [(f"s{s}_{name}", DSP_CTRL_SELW, "dsp_ctrl", "dsp_ctrl",
                      "0 const0, 1 const1, 2 JTAG drive, 3..18 fabric North edge track 0..15")
                     for name in DSP_CTRL_NAMES]
        spec += [(f"out{k}", DSP_OUT_SELW, "dsp_out", "dsp_out",
                  f"drives fabric tile ({self.rows - 1},{k // self.ntrack}) in_N[{k % self.ntrack}]: "
                  "0 const0, 1..48 P0[0..47], 49..96 P1[0..47]")
                 for k in range(BRAM_EDGE_TRACKS)]
        return _build(spec, "dsp")

    def _bram_type(self):
        spec = [
            ("wmode_a", 2, "value", "bram", "port A write mode: 0 WRITE_FIRST, 1 READ_FIRST, 2 NO_CHANGE"),
            ("wmode_b", 2, "value", "bram", "port B write mode"),
            ("reg_a", 1, "flag", "bram", "DOA_REG: port A output register"),
            ("reg_b", 1, "flag", "bram", "DOB_REG: port B output register"),
            ("reserved", 2, "reserved", "bram", "write 0"),
        ]
        for port in "ab":
            spec += [(f"{port}_{name}", BRAM_PIN_SELW, "bram_pin", "bram_pin",
                      f"port {port.upper()} {name} source: 0 const0, 1 const1, 2 JTAG drive, "
                      f"3..18 fabric East edge track 0..15")
                     for name in BRAM_PIN_NAMES]
        spec += [(f"out{k}", BRAM_OUT_SELW, "bram_out", "bram_out",
                  f"drives fabric tile ({k // self.ntrack},{self.cols - 1}) in_E[{k % self.ntrack}]: "
                  "0 const0, 1..18 DOA[0..17], 19..36 DOB[0..17]")
                 for k in range(BRAM_EDGE_TRACKS)]
        return _build(spec, "bram")

    def _clb_type(self):
        k = self.lut_k
        spec = [
            # AMD UG474: LUT6_2 fracture (generalised to K), CARRY4-style
            # MUXCY/XORCY, FDRE/FDSE.
            ("init", 1 << k, "lut_init", "clb",
             f"LUT{k} truth table; O5 = INIT[{(1 << (k - 1)) - 1}:0] over i[{k - 2}:0]"),
            ("ff_en", 1, "flag", "clb", "o = FF q (1) or combinational (0)"),
            ("ff_rstval", 1, "flag", "clb", "INIT and sync reset value: FDRE=0 / FDSE=1"),
            ("ff_ce_en", 1, "flag", "clb", "1: FF honours the routed CE, 0: always enabled"),
            ("ff_sr_en", 1, "flag", "clb", "1: FF honours the routed SR, 0: reset ignored"),
            ("cy_en", 1, "flag", "clb", "carry mode: XORCY sum on datapath, MUXCY cout"),
            ("cy_di_sel", 1, "flag", "clb", "carry generate: 0 = i[0], 1 = O5"),
            ("ff_d_sel", 1, "flag", "clb", "datapath: 0 = O6, 1 = O5 (ignored if cy_en)"),
        ]
        spec += [(f"cb_i{j}", self.selw, "mux", "cb", f"LUT input i[{j}]") for j in range(k)]
        spec += [("cb_ce", self.selw, "mux", "cb", "flip-flop clock enable (routed)"),
                 ("cb_sr", self.selw, "mux", "cb", "flip-flop synchronous set/reset (routed)")]
        spec += [(f"sb_{d}{t}", self.selw, "mux", "sb", f"outgoing track {d}[{t}]")
                 for d in DIRS for t in range(self.ntrack)]
        return _build(spec, "clb")

    # --- lookups --------------------------------------------------------------

    def tile(self, row, col):
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            raise ValueError(f"tile ({row},{col}) outside the {self.rows}x{self.cols} grid")
        return self.fabric_tiles[row * self.cols + col]

    @property
    def ctrl_tile(self):
        return self.tiles[0]

    def group_span(self, type_name, group):
        fs = [f for f in self.tile_types[type_name].fields if f.group == group]
        return min(f.offset for f in fs), sum(f.width for f in fs)

    def chain_bit(self, tile, field_name, bit=0):
        f = self.tile_types[tile.type].field(field_name)
        if not 0 <= bit < f.width:
            raise ValueError(f"{field_name} has {f.width} bits")
        return tile.chain_lo + f.offset + bit

    def locate(self, k):
        """chain bit -> (tile, field, bit within field)"""
        if not 0 <= k < self.chain_width:
            raise ValueError(f"chain bit {k} outside 0..{self.chain_width - 1}")
        tile = self.tiles[bisect.bisect_right(self._tile_los, k) - 1]
        f, b = self._bitmap[tile.type][k - tile.chain_lo]
        return tile, f, b

    # --- chain <-> fields -----------------------------------------------------

    def decode(self, word):
        """chain word -> {tile name: {field name: value}}"""
        out = {}
        for t in self.tiles:
            out[t.name] = {f.name: (word >> (t.chain_lo + f.offset)) & ((1 << f.width) - 1)
                           for f in self.tile_types[t.type].fields}
        return out

    def encode(self, cfg):
        """{tile name: {field name: value}} -> chain word; missing fields are 0"""
        by_name = {t.name: t for t in self.tiles}
        word = 0
        for tname, vals in cfg.items():
            t = by_name[tname]
            tt = self.tile_types[t.type]
            for fname, v in vals.items():
                f = tt.field(fname)
                if not 0 <= v < (1 << f.width):
                    raise ValueError(f"{tname}.{fname} = {v} does not fit {f.width} bits")
                word |= v << (t.chain_lo + f.offset)
        return word

    # --- routing resources ------------------------------------------------------

    def pips(self):
        """Every programmable connection: (tile, mux field, source, (chain_lo, width, value))."""
        for t in self.tiles:
            for f in self.tile_types[t.type].fields:
                if f.kind != "mux":
                    continue
                for value, src in enumerate(self.sources):
                    yield t.name, f.name, src, (t.chain_lo + f.offset, f.width, value)

    # --- emitters ---------------------------------------------------------------

    def to_json(self):
        return {
            "name": self.name,
            "generated_by": "tools/bob/device.py - do not edit",
            "lut_k": self.lut_k,
            "grid": {"rows": self.rows, "cols": self.cols},
            "clock": {"sysclk_hz": SYSCLK_HZ, "div_min_shift": DIV_MIN_SHIFT,
                      "modes": {"jtag": 0, "run": 1}},
            "routing": {
                "ntrack": self.ntrack,
                "selw": self.selw,
                "dirs": list(DIRS),
                "sources": self.sources,
                "tracks": "point to point: out_D[t] of a tile arrives at its D "
                          "neighbour on the opposite side, same t",
                "carry": "south to north up each column; row 0 takes the global cin",
            },
            "tile_types": {
                name: {
                    "width": tt.width,
                    "fields": [{"name": f.name, "offset": f.offset, "width": f.width,
                                "kind": f.kind, "group": f.group, "doc": f.doc}
                               for f in tt.fields],
                }
                for name, tt in self.tile_types.items()
            },
            "tiles": [{"name": t.name, "type": t.type, "row": t.row, "col": t.col,
                       "chain_lo": t.chain_lo} for t in self.tiles],
            "chain": {
                "width": self.chain_width,
                "order": "ctrl tile first, then fabric tiles row-major (tile (0,0) first); "
                         "within a tile, field order",
                "bit_order": "chain bit k is the k-th bit shifted in on TDI (LSB-first)",
            },
            "pads": {"inputs": self.pad_inputs, "outputs": self.pad_outputs},
            "bram": {
                "addr_w": BRAM_ADDR_W,
                "data_w": BRAM_DATA_W,
                "port_pins": BRAM_PIN_NAMES,
                "pin_sources": ["const0", "const1", "jtag"]
                               + [f"trk{k}" for k in range(BRAM_EDGE_TRACKS)],
                "out_sources": ["const0"] + [f"doa{k}" for k in range(BRAM_DATA_W)]
                               + [f"dob{k}" for k in range(BRAM_DATA_W)],
                "write_modes": BRAM_WRITE_MODES,
                "edge": "East; trkN = fabric tile (N//4, cols-1) out_E/in_E track N%4",
                "jtag": "USER4 data register, docs/bitstream-format.md",
            },
            "dsp": {
                "slices": DSP_SLICES,
                "opmodes": DSP_OPMODES,
                "bus_sources": DSP_BUS_SOURCES,
                "ctrl_names": list(DSP_CTRL_NAMES),
                "ctrl_sources": ["const0", "const1", "jtag"] + [f"trk{k}" for k in range(BRAM_EDGE_TRACKS)],
                "out_sources": ["const0"] + [f"p0_{k}" for k in range(48)] + [f"p1_{k}" for k in range(48)],
                "drive_per_slice": DSP_DRIVE_PER_SLICE,
                "edge": "North; trkN = fabric tile (rows-1, N//4) out_N/in_N track N%4",
                "jtag": "private instruction DSP 101000, docs/bitstream-format.md",
            },
        }

    def verilog_params(self):
        clb_lo, clb_w = self.group_span("clb", "clb")
        cb_lo, cb_w = self.group_span("clb", "cb")
        sb_lo, sb_w = self.group_span("clb", "sb")
        tt = self.tile_types["clb"]
        ct = self.tile_types["ctrl"]
        fabric_w = len(self.fabric_tiles) * tt.width
        vals = [
            ("LUT_K", self.lut_k), ("LUT_INIT_W", 1 << self.lut_k), ("CB_N", self.lut_k + 2),
            ("GRID_R", self.rows), ("GRID_C", self.cols), ("NTRACK", self.ntrack),
            ("NSRC", self.nsrc), ("SELW", self.selw),
            ("CLB_CFG_W", clb_w), ("CB_CFG_W", cb_w), ("SB_CFG_W", sb_w),
            ("TILE_CFG_W", tt.width), ("FABRIC_CFG_W", fabric_w),
            ("CTRL_W", ct.width), ("FABRIC_LO", ct.width), ("CHAIN_W", self.chain_width),
            ("TILE_CLB_LO", clb_lo), ("TILE_CB_LO", cb_lo), ("TILE_SB_LO", sb_lo),
            ("CLB_INIT_LO", tt.field("init").offset - clb_lo),
        ]
        for name in ("ff_en", "ff_rstval", "ff_ce_en", "ff_sr_en", "cy_en",
                     "cy_di_sel", "ff_d_sel"):
            vals.append((f"CLB_{name.upper()}", tt.field(name).offset - clb_lo))
        bt = self.tile_types["bram"]
        vals += [
            ("CTRL_CLK_MODE", ct.field("clk_mode").offset),
            ("CTRL_CLK_DIV_LO", ct.field("clk_div").offset),
            ("CTRL_CLK_DIV_W", ct.field("clk_div").width),
            ("DIV_MIN_SHIFT", DIV_MIN_SHIFT),
            ("BRAM_W", bt.width), ("BRAM_LO", self.bram_tile.chain_lo),
            ("BRAM_ADDR_W", BRAM_ADDR_W), ("BRAM_DATA_W", BRAM_DATA_W),
            ("BRAM_PORT_PINS", len(BRAM_PIN_NAMES)),
            ("BRAM_PIN_LO", bt.field("a_addr0").offset), ("BRAM_PIN_SELW", BRAM_PIN_SELW),
            ("BRAM_OUT_LO", bt.field("out0").offset), ("BRAM_OUT_SELW", BRAM_OUT_SELW),
        ]
        dt = self.tile_types["dsp"]
        vals += [
            ("DSP_W", dt.width), ("DSP_LO", self.dsp_tile.chain_lo),
            ("DSP_CTRL_LO", dt.field("s0_ce_ad").offset), ("DSP_CTRL_SELW", DSP_CTRL_SELW),
            ("DSP_OUT_LO", dt.field("out0").offset), ("DSP_OUT_SELW", DSP_OUT_SELW),
        ]
        lines = [
            "// -----------------------------------------------------------------------------",
            "// bob_params.vh - GENERATED by tools/bob/device.py, do not edit.",
            "//",
            f"// Device {self.name}, LUT K = {self.lut_k}. hw/src/clb/clb_pkg.sv derives its",
            "// widths from BOB_LUT_K independently; tests/test_device.py elaborates both",
            "// in iverilog and compares every constant.",
            "// -----------------------------------------------------------------------------",
            "`ifndef BOB_PARAMS_VH",
            "`define BOB_PARAMS_VH",
            "",
        ]
        w = max(len(n) for n, _ in vals)
        lines += [f"`define BOB_{n:<{w}} {v}" for n, v in vals]
        lines += ["", "`endif", ""]
        return "\n".join(lines)


def generated(dev=None, out_dir=None):
    dev = dev or Device()
    jpath = os.path.join(out_dir, JSON_NAME) if out_dir else JSON_PATH
    vpath = os.path.join(out_dir, VH_NAME) if out_dir else VH_PATH
    return {jpath: json.dumps(dev.to_json(), indent=2) + "\n", vpath: dev.verilog_params()}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if a generated file is out of date")
    ap.add_argument("--lut-k", type=int, default=6)
    ap.add_argument("--out", help="write into this directory instead of the committed paths")
    args = ap.parse_args()
    if args.lut_k != 6 and not args.out:
        sys.exit("a non-default --lut-k needs --out: the committed build is K=6")

    stale = []
    for path, text in generated(Device(lut_k=args.lut_k), args.out).items():
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
        print("run tools/bob/device.py to regenerate")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

