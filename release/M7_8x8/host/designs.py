"""
The example designs, in one place.

sim/gen_vectors.py turns these into simulation vectors and host/fpga.py loads
the same ones onto the board, so what runs on hardware is exactly what the
testbench verified.

M7: coordinates are VPR's (x East, y North). CLBs are at x in {1,2,4,5,7,8},
y in 1..8; the BRAM column is x=3 (bram0 rows 1-4, bram1 rows 5-8), the DSP
column x=6 (dsp0 rows 1-4, dsp1 rows 5-8). Board inputs SW0, SW1, BTN0..3 are
West-edge pads, LD0..LD2 East-edge pads, so every design routes across the grid.

Each entry is (key, description, builder, input_sweep). The builder returns a
Design; the sweep is the set of pad_i values worth checking.
"""

from bitstream import BRAM_PINS, DSP_CTRL_NAMES, Cell, Design, LUT, LUT_K


def d_and():
    d = Design()
    d.output(0, d.lut(1, 1, LUT.and2(), [d.input(0), d.input(1)]))
    return d


def d_or():
    d = Design()
    d.output(0, d.lut(1, 1, LUT.or2(), [d.input(0), d.input(1)]))
    return d


def d_xor():
    d = Design()
    d.output(0, d.lut(1, 1, LUT.xor2(), [d.input(0), d.input(1)]))
    return d


def d_three_tile():
    """One AND, one XOR, and a NAND made by inverting the AND in a third CLB.
    Exercises fanout and a route past the BRAM column."""
    d = Design()
    a, b = d.input(0), d.input(1)
    g_and = d.lut(1, 1, LUT.and2(), [a, b])
    g_xor = d.lut(2, 2, LUT.xor2(), [a, b])
    g_nand = d.lut(4, 3, LUT.inv(0), [g_and])
    d.output(0, g_and)
    d.output(1, g_xor)
    d.output(2, g_nand)
    return d


def d_far_corner():
    """The LUT sits in the far North-East corner, away from the input pads."""
    d = Design()
    d.output(0, d.lut(8, 8, LUT.or2(), [d.input(0), d.input(1)]))
    return d


def d_chain():
    """pad -> buffer -> inverter -> inverter -> pad, up column 1."""
    d = Design()
    b0 = d.lut(1, 1, LUT.buf(0), [d.input(0)])
    b1 = d.lut(1, 2, LUT.inv(0), [b0])
    b2 = d.lut(1, 3, LUT.inv(0), [b1])
    d.output(0, b2)
    return d


def d_and6():
    """All six board inputs into one CLB."""
    d = Design()
    d.output(0, d.lut(1, 1, LUT.and6(), [d.input(k) for k in range(6)]))
    return d


def d_xor6():
    """Parity of all six board inputs, computed in the middle of the grid."""
    d = Design()
    d.output(0, d.lut(5, 4, LUT.xor6(), [d.input(k) for k in range(6)]))
    return d


def d_mux():
    """pad_i[2] (BTN0) selects between pad_i[1] and pad_i[0] (SW1 / SW0)."""
    d = Design()
    d.output(0, d.lut(1, 1, LUT.mux2(), [d.input(0), d.input(1), d.input(2)]))
    return d


def d_consts():
    d = Design()
    d.output(0, d.lut(1, 1, LUT.buf(0), [d.const(0)]))
    d.output(1, d.lut(2, 2, LUT.buf(0), [d.const(1)]))
    return d


def d_showcase():
    """Something to leave on the board: each LED a different function of the two
    switches."""
    d = Design()
    a, b = d.input(0), d.input(1)
    d.output(0, d.lut(1, 1, LUT.and2(), [a, b]))
    d.output(1, d.lut(2, 2, LUT.or2(), [a, b]))
    d.output(2, d.lut(4, 3, LUT.xor2(), [a, b]))
    return d


def d_cross():
    """M7: signals cross both hard-block columns twice. AND at the North-West
    (2,8), inverted at the North-East (7,8), XORed with SW0 at (8,2)."""
    d = Design()
    a, b = d.input(0), d.input(1)
    g1 = d.lut(2, 8, LUT.and2(), [a, b])
    g2 = d.lut(7, 8, LUT.inv(0), [g1])
    g3 = d.lut(8, 2, LUT.xor2(), [g2, a])
    d.output(0, g3)
    d.output(1, g1)
    d.output(2, g2)
    return d


# (key, description, builder, input sweep, LUT inputs needed)
_ALL = [
    ("and",     "AND at clb(1,1), routed East across the grid to LD0",        d_and,        range(4),  2),
    ("or",      "OR at clb(1,1)",                                             d_or,         range(4),  2),
    ("xor",     "XOR at clb(1,1)",                                            d_xor,        range(4),  2),
    ("three",   "AND / XOR / NAND across three CLBs, with fanout",            d_three_tile, range(4),  2),
    ("corner",  "OR at clb(8,8), the far corner from the input pads",         d_far_corner, range(4),  2),
    ("chain",   "buffer / inverter chain up column 1 (pad -> 3 CLBs -> pad)", d_chain,      range(2),  1),
    ("and6",    "6-input AND at clb(1,1): all six board inputs reach one CLB", d_and6,      range(64), 6),
    ("xor6",    "6-input parity at clb(5,4): every input routed inward",      d_xor6,       range(64), 6),
    ("mux",     "MUX2 at clb(1,1): pad_i[2] selects pad_i[1] or pad_i[0]",    d_mux,        range(8),  3),
    ("const",   "constant sources: const0 and const1 through two CLBs",       d_consts,     range(1),  1),
    ("showcase", "AND, OR and XOR of the two switches on the three LEDs",     d_showcase,   range(4),  2),
    ("cross",   "AND/INV/XOR on opposite corners: routes cross the BRAM and DSP columns", d_cross, range(4), 2),
]

# Designs wider than the LUT size are left out (M4: K is a parameter).
DESIGNS = [(k, desc, fn, sweep) for k, desc, fn, sweep, need in _ALL if need <= LUT_K]
SKIPPED = [k for k, _d, _f, _s, need in _ALL if need > LUT_K]

BY_KEY = {k: (desc, fn, sweep) for k, desc, fn, sweep in DESIGNS}


def d_gsr_probe():
    """Not in DESIGNS: the combinational model does not cover flip-flops.

    One registered CLB for the startup checks: D = 0, reset/INIT value 1, clock
    enable from USER1 ce, output on LD0 and CAPTURE bit 0 (clb(1,1)). While GSR is
    asserted the flip-flop must read 1; after JSTART releases GSR and asserts GWE
    it clocks to 0. Used by hw/tb/tb_bob.v and host/hwtest.py.
    """
    d = Design()
    d.output(0, d.lut(1, 1, LUT.const0(), [], ff_en=1, ff_rstval=1, ff_ce_en=1))
    return d


# --- M4: sequential designs (checked with tools/bob/model.py) ------------------------

def d_ce_sr():
    """Routed CE and SR (UG474 FDRE). clb(1,1): D = 1, INIT/reset value 0,
    CE <- SW0, SR <- SW1, output on LD0. SW0 up loads a 1; SW1 up clears it (SR
    wins over CE); both down holds."""
    d = Design()
    d.output(0, d.lut(1, 1, LUT.const1(), [], ce=d.input(0), sr=d.input(1),
                      ff_en=1, ff_rstval=0, ff_ce_en=1, ff_sr_en=1))
    return d


COUNTER_X = 1


def d_counter(mode="jtag", div=0, x=COUNTER_X, bits=4):
    """A counter up column x on the carry chain: q0 at clb(x,1) .. q[bits-1] at
    clb(x,bits). Each CLB: LUT = buf(own q) = propagate, XORCY sum = D, MUXCY
    carries to the CLB above (a VPR direct); USER1 cin = 1 makes it count.
    LD0..LD2 = q1..q3.

    mode 'jtag': one count per TCK edge while USER1 ce. mode 'run': free-running,
    one count every 2**(div+8) sysclk cycles (div 17 -> 3.7 counts/s, LD0 ~1 Hz)."""
    d = Design()
    d.set_clock(mode, div)
    for r in range(bits):
        d.lut(x, 1 + r, LUT.buf(0), [Cell(x, 1 + r, "o")], ff_en=1, cy_en=1)
    for k in range(3):
        d.output(k, Cell(x, 2 + k, "o"))
    return d


# --- M5: BRAM ---------------------------------------------------------------------------

def d_bram_rom(bram=0):
    """BRAM as a ROM through the fabric: port A addr[1:0] <- SW0/SW1, EN = 1,
    READ_FIRST, DOA[2:0] -> LD0..LD2. Contents are loaded over JTAG USER4 before
    startup; the free-running user clock (div 0) makes the synchronous read look
    immediate. Flip the switches to walk addresses 0..3."""
    d = Design()
    d.set_clock("run", 0)
    d.bram_mode("a", "READ_FIRST", bram=bram)
    d.bram_pin("a", "addr0", d.input(0), bram=bram)
    d.bram_pin("a", "addr1", d.input(1), bram=bram)
    d.bram_pin("a", "en", d.const(1), bram=bram)
    for k in range(3):
        d.output(k, d.bram_out("a", k, bram=bram))
    return d


def d_bram_jtag(wmode_a="WRITE_FIRST", wmode_b="READ_FIRST", reg_a=False, reg_b=False, bram=0):
    """Every pin of both ports of one BRAM driven from the USER4 drive word, on the
    JTAG-stepped clock: each USER1 step is exactly one BRAM clock."""
    d = Design()
    d.bram_mode("a", wmode_a, reg_a, bram=bram)
    d.bram_mode("b", wmode_b, reg_b, bram=bram)
    for port in "ab":
        for pin in BRAM_PINS:
            d.bram_pin(port, pin, "jtag", bram=bram)
    return d


# --- M6: DSP ----------------------------------------------------------------------------

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
    """Combinational multiplier through the fabric: slice 0 A[1:0] <- {SW1, SW0},
    B from the DSP JTAG register (host sets it), P0[2:0] -> LD0..LD2."""
    d = Design()
    d.dsp_config(0, opmode="M", bus_a="fabric", bus_b="jtag")
    d.dsp_pin(0, "a", 0, d.input(0))
    d.dsp_pin(0, "a", 1, d.input(1))
    for k in range(3):
        d.output(k, d.dsp_out(0, k))
    return d


def d_dsp_accum(div=16):
    """Accumulator on the free-running user clock: slice 0 P <= P + A*B every enable
    (PREG, CE_P = const1 on its pin), A and B from the DSP JTAG register. P0[2:0] ->
    LD0..LD2: with A*B = 1 and div 16 (7.45 enables/s) LD0 blinks ~3.7 Hz."""
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


# --- M7: the heterogeneous fabric end to end ----------------------------------------------

PIPELINE_BRAM = 1


def d_pipeline(mode="run", div=0):
    """pad -> LUT -> FF -> BRAM -> DSP -> pad, every hop through the routing:

      SW0, SW1   West pads
      clb(2,1), clb(2,2)   LUT buf + flip-flop: the registered address
      bram1      (rows 5-8 of the BRAM column) port A addr[1:0], EN = const1,
                 READ_FIRST, contents loaded over USER4 (SELECT 1)
      dsp0       A[2:0] <- DOA[2:0], B = 3 from const1 pins, PREG with CE_P = const1
      LD0..LD2   P[2:0], East pads

    After three user clocks (FF, BRAM read, PREG) the LEDs show
    (mem[{SW1,SW0}] * 3)[2:0]."""
    d = Design()
    d.set_clock(mode, div)
    q0 = d.lut(2, 1, LUT.buf(0), [d.input(0)], ff_en=1)
    q1 = d.lut(2, 2, LUT.buf(0), [d.input(1)], ff_en=1)
    b = PIPELINE_BRAM
    d.bram_mode("a", "READ_FIRST", bram=b)
    d.bram_pin("a", "addr0", q0, bram=b)
    d.bram_pin("a", "addr1", q1, bram=b)
    d.bram_pin("a", "en", d.const(1), bram=b)
    d.dsp_config(0, opmode="M", preg=1, bus_a="fabric", bus_b="fabric")
    for k in range(3):
        d.dsp_pin(0, "a", k, d.bram_out("a", k, bram=b))
    d.dsp_pin(0, "b", 0, d.const(1))
    d.dsp_pin(0, "b", 1, d.const(1))
    d.dsp_ctrl(0, "ce_p", d.const(1))
    for k in range(3):
        d.output(k, d.dsp_out(0, k))
    return d
