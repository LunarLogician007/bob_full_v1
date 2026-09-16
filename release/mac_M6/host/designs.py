"""
The example designs, in one place.

sim/gen_vectors.py turns these into simulation vectors and host/fpga.py loads
the same ones onto the board, so what runs on hardware is exactly what the
testbench verified.

Each entry is (key, description, builder, input_sweep). The builder returns a
Design; the sweep is the set of pad_i values worth checking.
"""

from bitstream import BRAM_PINS, DSP_CTRL_NAMES, Cell, Design, LUT, LUT_K


def d_and():
    d = Design()
    d.output(0, d.lut(0, 0, LUT.and2(), [d.input(0), d.input(1)]))
    return d


def d_or():
    d = Design()
    d.output(0, d.lut(0, 0, LUT.or2(), [d.input(0), d.input(1)]))
    return d


def d_xor():
    d = Design()
    d.output(0, d.lut(0, 0, LUT.xor2(), [d.input(0), d.input(1)]))
    return d


def d_three_tile():
    """One AND, one XOR, and a NAND made by inverting the AND in a third tile.
    Exercises fanout and an L-shaped route."""
    d = Design()
    a, b = d.input(0), d.input(1)
    g_and = d.lut(0, 0, LUT.and2(), [a, b])
    g_xor = d.lut(1, 1, LUT.xor2(), [a, b])
    g_nand = d.lut(2, 2, LUT.inv(0), [g_and])
    d.output(0, g_and)
    d.output(1, g_xor)
    d.output(2, g_nand)
    return d


def d_far_corner():
    """The LUT sits as far from the input pads as the grid allows."""
    d = Design()
    d.output(0, d.lut(3, 3, LUT.or2(), [d.input(0), d.input(1)]))
    return d


def d_chain():
    """pad -> buffer -> inverter -> inverter -> pad, up column 0."""
    d = Design()
    b0 = d.lut(0, 0, LUT.buf(0), [d.input(0)])
    b1 = d.lut(1, 0, LUT.inv(0), [b0])
    b2 = d.lut(2, 0, LUT.inv(0), [b1])
    d.output(0, b2)
    return d


def d_and6():
    """All six pads into one tile: SW1 SW0 and all four buttons must be on."""
    d = Design()
    d.output(0, d.lut(0, 0, LUT.and6(), [d.input(k) for k in range(6)]))
    return d


def d_xor6():
    """Parity of all six pads, computed in a tile in the middle of the grid."""
    d = Design()
    d.output(0, d.lut(1, 2, LUT.xor6(), [d.input(k) for k in range(6)]))
    return d


def d_mux():
    """pad_i[2] (BTN0) selects between pad_i[1] and pad_i[0] (SW1 / SW0)."""
    d = Design()
    d.output(0, d.lut(0, 0, LUT.mux2(),
                      [d.input(0), d.input(1), d.input(2)]))
    return d


def d_consts():
    d = Design()
    d.output(0, d.lut(0, 0, LUT.buf(0), [d.const(0)]))
    d.output(1, d.lut(1, 1, LUT.buf(0), [d.const(1)]))
    return d


def d_showcase():
    """Something to leave on the board: each output pad a different function of
    the two switches, so one design lights the LEDs in three different ways."""
    d = Design()
    a, b = d.input(0), d.input(1)
    d.output(0, d.lut(0, 0, LUT.and2(), [a, b]))
    d.output(1, d.lut(1, 1, LUT.or2(), [a, b]))
    d.output(2, d.lut(2, 2, LUT.xor2(), [a, b]))
    return d


# (key, description, builder, input sweep, LUT inputs needed)
_ALL = [
    ("and",     "AND at tile(0,0), routed east to pad_o[0]",                  d_and,        range(4),  2),
    ("or",      "OR at tile(0,0)",                                            d_or,         range(4),  2),
    ("xor",     "XOR at tile(0,0)",                                           d_xor,        range(4),  2),
    ("three",   "AND / XOR / NAND across three tiles, with fanout",           d_three_tile, range(4),  2),
    ("corner",  "OR at tile(3,3), the far corner from the input pads",        d_far_corner, range(4),  2),
    ("chain",   "buffer / inverter chain up column 0 (pad -> 3 tiles -> pad)", d_chain,     range(2),  1),
    ("and6",    "6-input AND at tile(0,0): all six pads reach one tile",      d_and6,       range(64), 6),
    ("xor6",    "6-input parity at tile(1,2): every pad routed inward",       d_xor6,       range(64), 6),
    ("mux",     "MUX2 at tile(0,0): pad_i[2] selects pad_i[1] or pad_i[0]",   d_mux,        range(8),  3),
    ("const",   "constant sources: const0 and const1 through two tiles",      d_consts,     range(1),  1),
    ("showcase", "AND, OR and XOR of the two switches on the three LEDs",     d_showcase,   range(4),  2),
]

# Designs wider than the LUT size are left out (M4: K is a parameter).
DESIGNS = [(k, desc, fn, sweep) for k, desc, fn, sweep, need in _ALL if need <= LUT_K]
SKIPPED = [k for k, _d, _f, _s, need in _ALL if need > LUT_K]

BY_KEY = {k: (desc, fn, sweep) for k, desc, fn, sweep in DESIGNS}


def d_gsr_probe():
    """Not in DESIGNS: the software model is combinational only.

    One registered tile for the M3 startup checks: D = 0, reset/INIT value 1,
    clock enable from USER1 ce, output on pad_o[0] and CAPTURE bit 0. While GSR
    is asserted the flip-flop must read 1; after JSTART releases GSR and asserts
    GWE it clocks to 0. Used by hw/tb/tb_fpga4x4.v and host/hwtest.py.
    """
    d = Design()
    d.output(0, d.lut(0, 0, LUT.const0(), [], ff_en=1, ff_rstval=1, ff_ce_en=1))
    return d


# --- M4: sequential designs (not in DESIGNS: checked with tools/bob/model.py) ---

def d_ce_sr():
    """Routed CE and SR (UG474 FDRE). tile(0,0): D = 1, INIT/reset value 0,
    CE <- pad_i[0] (SW0), SR <- pad_i[1] (SW1), output on pad_o[0] (LD0).
    SW0 up loads a 1; SW1 up clears it (SR wins over CE); both down holds."""
    d = Design()
    d.output(0, d.lut(0, 0, LUT.const1(), [], ce=d.input(0), sr=d.input(1),
                      ff_en=1, ff_rstval=0, ff_ce_en=1, ff_sr_en=1))
    return d


def d_counter(mode="jtag", div=0):
    """A 4-bit counter up column 0 on the carry chain: q0 at tile(0,0) .. q3 at
    tile(3,0). Each tile: LUT = buf(own q) = propagate, XORCY sum = D, MUXCY
    carries to the tile above; USER1 cin = 1 makes it count. LD0..LD2 = q1..q3.

    mode 'jtag': one count per TCK edge while USER1 ce. mode 'run': free-running,
    one count every 2**(div+8) sysclk cycles (div 17 -> 3.7 counts/s, LD0 ~1 Hz)."""
    d = Design()
    d.set_clock(mode, div)
    for r in range(4):
        d.lut(r, 0, LUT.buf(0), [Cell(r, 0, "o")], ff_en=1, cy_en=1)
    for k in range(3):
        d.output(k, Cell(k + 1, 0, "o"))
    return d


# --- M5: the BRAM tile ------------------------------------------------------------

def d_bram_rom():
    """BRAM as a ROM through the fabric: port A addr[1:0] <- SW0/SW1 (pad_i[1:0]),
    EN = 1, READ_FIRST, DOA[2:0] -> LD0..LD2. Contents are loaded over JTAG USER4
    before startup; the free-running user clock (div 0) makes the synchronous read
    look immediate. Flip the switches to walk addresses 0..3."""
    d = Design()
    d.set_clock("run", 0)
    d.bram_mode("a", "READ_FIRST")
    d.bram_pin("a", "addr0", d.input(0))
    d.bram_pin("a", "addr1", d.input(1))
    d.bram_pin("a", "en", d.const(1))
    for k in range(3):
        d.output(k, d.bram_out("a", k))
    return d


def d_bram_jtag(wmode_a="WRITE_FIRST", wmode_b="READ_FIRST", reg_a=False, reg_b=False):
    """Every pin of both BRAM ports driven from the USER4 drive register, on the
    JTAG-stepped clock: each USER1 step is exactly one BRAM clock, so write
    modes and output registers can be checked cycle by cycle from the host."""
    d = Design()
    d.bram_mode("a", wmode_a, reg_a)
    d.bram_mode("b", wmode_b, reg_b)
    for port in "ab":
        for pin in BRAM_PINS:
            d.bram_pin(port, pin, "jtag")
    return d


# --- M6: the DSP tile -------------------------------------------------------------

def d_dsp_jtag(s0=None, s1=None):
    """Every bus and control of both DSP slices driven from the DSP JTAG register,
    JTAG-stepped clock: each USER1 step is exactly one DSP clock. s0/s1 are
    dsp_config keyword dicts (opmode, use_d, d_sub, areg..preg)."""
    d = Design()
    for s, cfg in ((0, s0 or {}), (1, s1 or {})):
        d.dsp_config(s, bus_a="jtag", bus_b="jtag", bus_c="jtag", bus_d="jtag", **cfg)
        for name in DSP_CTRL_NAMES:
            d.dsp_ctrl(s, name, "jtag")
    return d


def d_dsp_mult_sw():
    """Combinational multiplier through the fabric: slice 0 A <- {SW1, SW0} on North
    tracks 1..0, B from the DSP JTAG register (host sets it), P0[2:0] -> LD0..LD2."""
    d = Design()
    d.dsp_config(0, opmode="M", bus_a="fabric", bus_b="jtag")
    d.dsp_track(0, d.input(0))
    d.dsp_track(1, d.input(1))
    for k in range(3):
        d.output(k, d.dsp_out(0, k))
    return d


def d_dsp_accum(div=16):
    """Accumulator on the free-running user clock: slice 0 P <= P + A*B every enable
    (PREG, CE_P = 1), A and B from the DSP JTAG register. P0[2:0] -> LD0..LD2: with
    A*B = 1 and div 16 (7.45 enables/s) LD0 blinks ~3.7 Hz, LD1 ~1.9 Hz, LD2 ~0.93 Hz."""
    d = Design()
    d.set_clock("run", div)
    d.dsp_config(0, opmode="P+M", preg=1, bus_a="jtag", bus_b="jtag")
    d.dsp_ctrl(0, "ce_p", d.const(1))
    for k in range(3):
        d.output(k, d.dsp_out(0, k))
    return d


DSP_JTAG_VARIANTS = [
    ("DJ0", {"opmode": "M+C", "use_d": True, "d_sub": False, "mreg": 1, "preg": 1},
            {"opmode": "PCIN>>17+M", "breg": 1, "preg": 1}),
    ("DJ1", {"opmode": "P+M", "areg": 1, "breg": 1, "preg": 1},
            {"opmode": "M", "use_d": True, "d_sub": True, "dreg": 1, "creg": 1}),
    ("DJ2", {"opmode": "M", "use_d": True, "d_sub": True, "areg": 1, "dreg": 1, "mreg": 1},
            {"opmode": "PCIN>>17+M", "mreg": 1, "preg": 0}),
]


BRAM_JTAG_VARIANTS = [
    ("JT0", {"wmode_a": "WRITE_FIRST", "wmode_b": "READ_FIRST", "reg_a": False, "reg_b": False}),
    ("JT1", {"wmode_a": "NO_CHANGE",   "wmode_b": "WRITE_FIRST", "reg_a": True,  "reg_b": False}),
    ("JT2", {"wmode_a": "READ_FIRST",  "wmode_b": "NO_CHANGE",   "reg_a": False, "reg_b": True}),
]

