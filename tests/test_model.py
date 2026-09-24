"""
software/bob/model.py - the cycle model over the routing-resource graph - gives the
right answers: combinational designs against their truth tables (independent of
the router and the graph), sequential ones against their definitions, and the
BRAM/DSP models against UG473/UG479 behaviour.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402
import model as M      # noqa: E402
from designs import (COUNTER_X, DESIGNS, counter_cells, d_ce_sr, d_counter, d_gsr_probe, d_pipeline,  # noqa: E402
                     PIPELINE_BRAM)

TRUTH = {
    "and": lambda a, b, *r: a & b,
    "or": lambda a, b, *r: a | b,
    "xor": lambda a, b, *r: a ^ b,
    "three": lambda a, b, *r: (a & b) | ((a ^ b) << 1) | ((1 - (a & b)) << 2),
    "corner": lambda a, b, *r: a | b,
    "chain": lambda a, *r: a,
    "and6": lambda *v: int(all(v)),
    "xor6": lambda *v: sum(v) & 1,
    "mux": lambda a, b, s, *r: b if s else a,
    "const": lambda *r: 0b10,
    "showcase": lambda a, b, *r: (a & b) | ((a | b) << 1) | ((a ^ b) << 2),
    "cross": lambda a, b, *r: ((1 - (a & b)) ^ a) | ((a & b) << 1) | ((1 - (a & b)) << 2),
    # M24 Double Duty: LD0 = SW0 + SW1's sum, LD1 = its carry, LD2 = BTN0 AND SW0 (the LUT beside)
    "dd": lambda a, b, c, *r: (a ^ b) | ((a & b) << 1) | ((c & a) << 2),
}


def test_every_combinational_design_meets_its_truth_table():
    assert {k for k, *_ in DESIGNS} <= set(TRUTH)
    for key, _desc, fn, sweep in DESIGNS:
        bs = fn().build()
        m = M.Fabric(bs)
        for v in sweep:
            bits = [(v >> k) & 1 for k in range(6)]
            assert m.outputs(v) == TRUTH[key](*bits), f"{key} pad_i={v:06b}"
            assert B.simulate(bs, v) == m.outputs(v)


def test_counter_counts_through_the_carry_chain():
    m = M.Fabric(d_counter().build())
    m.clock(gsr=1)
    seen = []
    for _ in range(20):
        seen.append(sum(m.q[c] << r for r, c in enumerate(counter_cells(COUNTER_X, 4))))
        m.clock(cin=1)
    assert seen == [n % 16 for n in range(20)]


def test_counter_up_the_full_column():
    from designs import FULL_COL_BITS as NB, FULL_COL_X as X
    m = M.Fabric(d_counter("jtag", x=X, bits=NB).build())
    m.clock(gsr=1)
    for _ in range(300):
        m.clock(cin=1)
    assert sum(m.q[c] << r for r, c in enumerate(counter_cells(X, NB))) == 300 % (1 << NB)


def test_counter_holds_without_gce_or_gwe_and_resets_on_gsr():
    m = M.Fabric(d_counter().build())
    m.clock(gsr=1)
    for _ in range(5):
        m.clock(cin=1)
    state = dict(m.q)
    m.clock(cin=1, gce=0)
    m.clock(cin=1, gwe=0)
    assert m.q == state
    m.clock(cin=1, gsr=1)
    assert all(v == 0 for v in m.q.values())


def test_routed_ce_and_sr():
    m = M.Fabric(d_ce_sr().build())
    m.clock(gsr=1)
    q = lambda: m.q[(1, 1, 0)]                   # noqa: E731
    m.clock(pad_i=0b00); assert q() == 0      # CE low: hold INIT 0
    m.clock(pad_i=0b01); assert q() == 1      # CE high: D = 1
    m.clock(pad_i=0b00); assert q() == 1      # hold
    m.clock(pad_i=0b11); assert q() == 0      # SR beats CE
    m.clock(pad_i=0b10); assert q() == 0      # SR with CE low still resets (FDRE)
    m.clock(pad_i=0b01); assert q() == 1
    assert m.outputs(0b01) & 1 == 1           # and it reaches LD0


def _bram_step(bm, cfg, a=None, b=None):
    idle = {"addr": 0, "di": 0, "we": 0, "en": 0, "rst": 0, "regce": 0}
    bm.clock(cfg, {"a": {**idle, **(a or {})}, "b": {**idle, **(b or {})}})


def test_bram_write_modes_follow_ug473():
    for mode, expect in (("WRITE_FIRST", 0x22), ("READ_FIRST", 0x11), ("NO_CHANGE", 0x11)):
        cfg = {"wmode_a": M.WRITE_MODES[mode], "wmode_b": 0, "reg_a": 0, "reg_b": 0}
        bm = M.Bram()
        bm.init(True, 3, 0x11)
        _bram_step(bm, cfg, a={"addr": 3, "en": 1})
        assert bm.do("a", cfg) == 0x11
        _bram_step(bm, cfg, a={"addr": 3, "en": 1, "we": 1, "di": 0x22})
        assert bm.do("a", cfg) == expect, mode
        assert bm.mem[3] == 0x22


def test_bram_no_change_holds_across_writes_and_en_low_holds():
    cfg = {"wmode_a": M.NO_CHANGE, "wmode_b": 0, "reg_a": 0, "reg_b": 0}
    bm = M.Bram()
    bm.init(True, 1, 7)
    _bram_step(bm, cfg, a={"addr": 1, "en": 1})
    for d in (1, 2, 3):
        _bram_step(bm, cfg, a={"addr": 1, "en": 1, "we": 1, "di": d})
        assert bm.do("a", cfg) == 7
    _bram_step(bm, cfg, a={"addr": 0, "en": 0})
    assert bm.do("a", cfg) == 7


def test_bram_output_register_rst_and_regce():
    cfg = {"wmode_a": M.READ_FIRST, "wmode_b": 0, "reg_a": 1, "reg_b": 0}
    bm = M.Bram()
    bm.init(True, 0, 9)
    _bram_step(bm, cfg, a={"addr": 0, "en": 1})
    assert bm.do("a", cfg) == 0
    _bram_step(bm, cfg, a={"regce": 1})
    assert bm.do("a", cfg) == 9
    _bram_step(bm, cfg, a={"rst": 1})
    assert bm.do("a", cfg) == 0


def test_bram_rom_through_fabric_model():
    from designs import d_bram_rom
    m = M.Fabric(d_bram_rom().build())
    m.clock(gsr=1)
    words = [0b101, 0b010, 0b111, 0b001]
    for i, w in enumerate(words):
        m.bram.mem[i] = w
    for v in range(4):
        m.clock(pad_i=v)
        m.clock(pad_i=v)
        assert m.outputs(v) == words[v]


def _dsp_pins(**kw):
    p = {"a": 0, "b": 0, "c": 0, "d": 0, **{n: 0 for n in M.DSP_CTRL_NAMES}}
    p.update(kw)
    return p


def _dsp_cfg(**kw):
    c = {n: 0 for n in M.DSP_CFG_NAMES}
    c.update(kw)
    return c


def test_dsp_multiply_add_and_preadder_signed():
    s = M.Dsp()
    assert s.p(_dsp_cfg(opmode=0), _dsp_pins(a=-3, b=7)) == -21
    assert s.p(_dsp_cfg(opmode=1), _dsp_pins(a=5, b=6, c=-100)) == -70
    assert s.p(_dsp_cfg(opmode=0, use_d=1), _dsp_pins(a=2, d=10, b=3)) == 36
    assert s.p(_dsp_cfg(opmode=0, use_d=1, d_sub=1), _dsp_pins(a=2, d=10, b=3)) == 24
    full = -(1 << 24)
    assert s.p(_dsp_cfg(), _dsp_pins(a=full, b=-(1 << 17))) == full * -(1 << 17)


def test_dsp_accumulator_and_register_enables():
    s = M.Dsp()
    cfg = _dsp_cfg(opmode=2, preg=1)
    for k in range(5):
        s.clock(cfg, _dsp_pins(a=1, b=4, ce_p=1))
        assert s.p(cfg, _dsp_pins()) == 4 * (k + 1)
    s.clock(cfg, _dsp_pins(a=1, b=4, ce_p=0))
    assert s.p(cfg, _dsp_pins()) == 20
    s.clock(cfg, _dsp_pins(a=1, b=4, ce_p=1, rst_p=1))
    assert s.p(cfg, _dsp_pins()) == 0


def test_dsp_cascade_shift():
    sl = [M.Dsp(), M.Dsp()]
    cfgs = [_dsp_cfg(opmode=0, preg=1), _dsp_cfg(opmode=3)]
    pins = (_dsp_pins(a=1 << 20, b=1 << 10, ce_p=1), _dsp_pins(a=1, b=1))
    M.dsp_cascade_clock(sl, cfgs, pins)
    p0, p1 = M.dsp_cascade_p(sl, cfgs, pins)
    assert p0 == 1 << 30 and p1 == (1 << 13) + 1


def test_dsp_mult_design_through_fabric_model():
    from designs import d_dsp_mult_sw
    m = M.Fabric(d_dsp_mult_sw().build())
    m.dsp_drive = M.dsp_pins_to_drive(_dsp_pins(b=3), _dsp_pins())
    assert [m.outputs(v) for v in range(4)] == [(v * 3) & 7 for v in range(4)]


def test_pipeline_pad_lut_ff_bram_dsp_pad():
    m = M.Fabric(d_pipeline().build())
    m.clock(gsr=1)
    mem = [3, 5, 6, 1]
    for i, w in enumerate(mem):
        m.brams[PIPELINE_BRAM].mem[i] = w
    for v in (0, 1, 2, 3):
        for _ in range(3):                    # FF, BRAM read, PREG
            m.clock(pad_i=v)
        assert m.outputs(v) == (mem[v] * 3) & 7, f"SW={v:02b}"


def test_gsr_probe():
    m = M.Fabric(d_gsr_probe().build())
    m.clock(gsr=1)
    assert m.q[(1, 1, 0)] == 1
    m.clock(gwe=0)
    assert m.q[(1, 1, 0)] == 1
    m.clock()
    assert m.q[(1, 1, 0)] == 0
