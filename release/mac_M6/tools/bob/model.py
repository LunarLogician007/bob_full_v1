#!/usr/bin/env python3
"""
model.py - cycle model of the fabric, with flip-flops and the user clock (M4).

Started from simulate() in host/bitstream.py (the combinational fixed point that
has matched the RTL since bob) and extended with each CLB's flip-flop exactly as
hw/src/clb/clb.sv implements it:

    if gsr:              q <= ff_rstval
    elif gwe and gce:
        if ff_sr_en & sr: q <= ff_rstval          (FDRE/FDSE: SR beats CE)
        elif !ff_ce_en | ce: q <= comb

CE and SR are the tile's routed connection-box muxes. One call to clock() is one
fabric clock edge with the given global enable.

Used by sim/gen_clb_vectors.py (CLB flag sweep), sim/gen_vectors.py (sequential
fabric designs) and tests/test_model.py. Honours BOB_DEVICE_JSON like bitstream.py.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "host"))

import bitstream as B  # noqa: E402

FLAGS = B.FLAG_NAMES


# --- one CLB ----------------------------------------------------------------------

def clb_comb(init, f, i, cin):
    """-> (o6, o5, comb, cout) for LUT input address i."""
    o6 = (init >> i) & 1
    o5 = (init >> (i & ((1 << (B.LUT_K - 1)) - 1))) & 1
    di = o5 if f["cy_di_sel"] else (i & 1)
    comb = (o6 ^ cin) if f["cy_en"] else (o5 if f["ff_d_sel"] else o6)
    cout = (cin if o6 else di) if f["cy_en"] else 0
    return o6, o5, comb, cout


def clb_next(q, f, comb, ce, sr, gce=1, gsr=0, gwe=1):
    """The flip-flop's next state."""
    if gsr:
        return f["ff_rstval"]
    if not (gwe and gce):
        return q
    if f["ff_sr_en"] and sr:
        return f["ff_rstval"]
    if (not f["ff_ce_en"]) or ce:
        return comb
    return q


# --- the BRAM (M5): hw/src/tiles/bram_core.v, cycle for cycle -------------------------

WRITE_FIRST, READ_FIRST, NO_CHANGE = 0, 1, 2
WRITE_MODES = {"WRITE_FIRST": WRITE_FIRST, "READ_FIRST": READ_FIRST, "NO_CHANGE": NO_CHANGE}
BRAM_PIN_NAMES = ([f"addr{k}" for k in range(10)] + [f"di{k}" for k in range(18)]
                  + ["we", "en", "rst", "regce"])


class Bram:
    """1024 x 18 true dual-port RAM with RAMB18E1 write modes, output latch and
    optional output register. Ports are 'a' and 'b'; pins are dicts with
    addr, di, we, en, rst, regce; cfg has wmode_a/b and reg_a/b."""

    ADDR_W, DATA_W = 10, 18

    def __init__(self):
        self.mem = [0] * (1 << self.ADDR_W)
        z = {"a": 0, "b": 0}
        self.ram, self.we_q, self.din_q, self.hold, self.reg = dict(z), dict(z), dict(z), dict(z), dict(z)
        self.rst_q = {"a": 1, "b": 1}

    def latch(self, p, wmode):
        if self.rst_q[p]:
            return 0
        if self.we_q[p] and wmode == WRITE_FIRST:
            return self.din_q[p]
        if self.we_q[p] and wmode == NO_CHANGE:
            return self.hold[p]
        return self.ram[p]

    def do(self, p, cfg):
        return self.reg[p] if cfg[f"reg_{p}"] else self.latch(p, cfg[f"wmode_{p}"])

    def init(self, write, addr, data=0):
        """One bram_jtag.v READ/WRITE through port A (only legal while GWE = 0)."""
        self.ram["a"] = self.mem[addr]
        if write:
            self.mem[addr] = data

    def clock(self, cfg, pins, gce=1, gsr=0, gwe=1):
        lat = {p: self.latch(p, cfg[f"wmode_{p}"]) for p in "ab"}
        if gsr:
            self.rst_q = {"a": 1, "b": 1}
            self.reg = {"a": 0, "b": 0}
            return
        if not (gwe and gce):
            return
        new_ram = dict(self.ram)
        writes = []
        for p in "ab":
            s = pins[p]
            if s["en"]:
                new_ram[p] = self.mem[s["addr"]]
                if s["we"]:
                    writes.append((s["addr"], s["di"]))
                self.we_q[p], self.din_q[p], self.rst_q[p], self.hold[p] = s["we"], s["di"], s["rst"], lat[p]
            if s["rst"]:
                self.reg[p] = 0
            elif s["regce"]:
                self.reg[p] = lat[p]
        for addr, di in writes:
            self.mem[addr] = di
        self.ram = new_ram


# --- the DSP slice (M6): hw/src/tiles/dsp_core.v, cycle for cycle ------------------------

def _sx(v, w):
    """Interpret the low w bits of v as two's complement."""
    v &= (1 << w) - 1
    return v - (1 << w) if v >> (w - 1) else v


DSP_OPMODES = {"M": 0, "M+C": 1, "P+M": 2, "PCIN>>17+M": 3}
DSP_CTRL_NAMES = ("ce_ad", "ce_b", "ce_m", "ce_p", "rst_ad", "rst_b", "rst_m", "rst_p")
DSP_CFG_NAMES = ("opmode", "use_d", "d_sub", "areg", "breg", "creg", "dreg", "mreg", "preg")


class Dsp:
    """cfg: opmode, use_d, d_sub, areg..preg. pins: a, b, c, d (signed ints) and
    the 8 controls. p()/clock() take pcin (signed int, for the cascade)."""

    def __init__(self):
        self.a_q = self.d_q = self.b_q = self.c_q = self.m_q = self.p_q = 0

    def _comb(self, cfg, pins, pcin):
        a = self.a_q if cfg["areg"] else _sx(pins["a"], 25)
        d = self.d_q if cfg["dreg"] else _sx(pins["d"], 25)
        b = self.b_q if cfg["breg"] else _sx(pins["b"], 18)
        c = self.c_q if cfg["creg"] else _sx(pins["c"], 48)
        ad = _sx((d - a) if cfg["d_sub"] else (d + a), 25) if cfg["use_d"] else a
        m_c = _sx(ad * b, 43)
        m = self.m_q if cfg["mreg"] else m_c
        op = cfg["opmode"]
        if op == 0:
            p_c = m
        elif op == 1:
            p_c = m + c
        elif op == 2:
            p_c = self.p_q + m
        else:
            p_c = (_sx(pcin, 48) >> 17) + m
        return m_c, _sx(p_c, 48)

    def p(self, cfg, pins, pcin=0):
        return self.p_q if cfg["preg"] else self._comb(cfg, pins, pcin)[1]

    def clock(self, cfg, pins, pcin=0, gce=1, gsr=0, gwe=1):
        m_c, p_c = self._comb(cfg, pins, pcin)
        if gsr:
            self.__init__()
            return
        if not (gwe and gce):
            return
        if pins["rst_ad"]:
            self.a_q = self.d_q = 0
        elif pins["ce_ad"]:
            self.a_q, self.d_q = _sx(pins["a"], 25), _sx(pins["d"], 25)
        if pins["rst_b"]:
            self.b_q = 0
        elif pins["ce_b"]:
            self.b_q = _sx(pins["b"], 18)
        if pins["rst_p"]:
            self.c_q = 0
        elif pins["ce_p"]:
            self.c_q = _sx(pins["c"], 48)
        if pins["rst_m"]:
            self.m_q = 0
        elif pins["ce_m"]:
            self.m_q = m_c
        if pins["rst_p"]:
            self.p_q = 0
        elif pins["ce_p"]:
            self.p_q = p_c


# --- the fabric ---------------------------------------------------------------------

def pins_to_drive(a, b):
    """BRAM pin dicts -> the 64-bit USER4 drive word (port A pins 0..31, B 32..63)."""
    v = 0
    for base, s in ((0, a), (32, b)):
        for k in range(Bram.ADDR_W):
            v |= ((s["addr"] >> k) & 1) << (base + k)
        for k in range(Bram.DATA_W):
            v |= ((s["di"] >> k) & 1) << (base + Bram.ADDR_W + k)
        for j, name in enumerate(("we", "en", "rst", "regce")):
            v |= (s[name] & 1) << (base + Bram.ADDR_W + Bram.DATA_W + j)
    return v


def bram_random_ops(rng, n, naddr=8):
    """Random two-port operations that never make both ports touch one address
    in a cycle where either writes (undefined in UG473)."""
    ops = []
    for _ in range(n):
        ports = {}
        for p in "ab":
            ports[p] = {"addr": rng.randrange(naddr), "di": rng.getrandbits(Bram.DATA_W),
                        "we": int(rng.random() < 0.4), "en": int(rng.random() < 0.85),
                        # regce at 50%: REGCE = 0 with a changing latch must occur, or an
                        # output register that ignores REGCE goes unnoticed (it did at M5)
                        "rst": int(rng.random() < 0.08), "regce": int(rng.random() < 0.5)}
        a, b = ports["a"], ports["b"]
        if a["en"] and b["en"] and a["addr"] == b["addr"] and (a["we"] or b["we"]):
            b["addr"] = (a["addr"] + 1) % naddr
        ops.append((a, b))
    return ops


def dsp_pins_to_drive(p0, p1):
    """Two slices' pin dicts -> the 248-bit DSP drive word (slice s at 124*s)."""
    v = 0
    for s, p in enumerate((p0, p1)):
        base = 124 * s
        v |= (p["a"] & ((1 << 25) - 1)) << base
        v |= (p["b"] & ((1 << 18) - 1)) << (base + 25)
        v |= (p["c"] & ((1 << 48) - 1)) << (base + 43)
        v |= (p["d"] & ((1 << 25) - 1)) << (base + 91)
        for k, name in enumerate(DSP_CTRL_NAMES):
            v |= (p[name] & 1) << (base + 116 + k)
    return v


def dsp_random_ops(rng, n):
    """Random signed data (with full-scale corners) and CE/RST for two slices."""
    corners = {25: [1, -1, (1 << 24) - 1, -(1 << 24)], 18: [1, -1, (1 << 17) - 1, -(1 << 17)],
               48: [1, -1, (1 << 47) - 1, -(1 << 47)]}

    def rs(w):
        return rng.choice(corners[w]) if rng.random() < 0.2 else rng.randrange(-(1 << (w - 1)), 1 << (w - 1))
    ops = []
    for _ in range(n):
        pair = []
        for _ in range(2):
            p = {"a": rs(25), "b": rs(18), "c": rs(48), "d": rs(25)}
            for name in DSP_CTRL_NAMES:
                p[name] = int(rng.random() < (0.08 if name.startswith("rst") else 0.8))
            pair.append(p)
        ops.append(tuple(pair))
    return ops


def dsp_cascade_clock(slices, cfgs, pins, gce=1, gsr=0, gwe=1):
    """Clock both slices as dsp_tile.v wires them (slice 1 PCIN = slice 0 P before the edge)."""
    p0_pre = slices[0].p(cfgs[0], pins[0], 0)
    slices[0].clock(cfgs[0], pins[0], 0, gce=gce, gsr=gsr, gwe=gwe)
    slices[1].clock(cfgs[1], pins[1], p0_pre, gce=gce, gsr=gsr, gwe=gwe)


def dsp_cascade_p(slices, cfgs, pins):
    p0 = slices[0].p(cfgs[0], pins[0], 0)
    return p0, slices[1].p(cfgs[1], pins[1], p0)


class Fabric:
    def __init__(self, bs):
        self.bs = bs
        self.tiles = [(r, c) for r in range(B.GRID_R) for c in range(B.GRID_C)]
        self.q = {t: 0 for t in self.tiles}
        # M5 BRAM tile
        self.bram = Bram()
        self.drive = 0
        self.bram_cfg = {"wmode_a": bs.get_bram("wmode_a"), "wmode_b": bs.get_bram("wmode_b"),
                         "reg_a": bs.get_bram("reg_a"), "reg_b": bs.get_bram("reg_b")}
        self.bram_pin_sel = [bs.get_bram(f"{p}_{name}") for p in "ab" for name in B.BRAM_PINS]
        self.bram_out_sel = [bs.get_bram(f"out{k}") for k in range(B.N_EDGE)]
        # M6 DSP tile
        self.dsp = [Dsp(), Dsp()]
        self.dsp_drive = 0
        self.dsp_cfgs = [{name: bs.get_dsp(f"s{s}_{name}") for name in
                          DSP_CFG_NAMES + ("bus_a", "bus_b", "bus_c", "bus_d")} for s in (0, 1)]
        self.dsp_ctrl_sel = [[bs.get_dsp(f"s{s}_{name}") for name in DSP_CTRL_NAMES] for s in (0, 1)]
        self.dsp_out_sel = [bs.get_dsp(f"out{k}") for k in range(B.N_NORTH)]
        # CLB tiles
        self._cfg = {}
        for (r, c) in self.tiles:
            self._cfg[(r, c)] = {
                "init": bs.get_field(r, c, "init"),
                "flags": {n: bs.get_field(r, c, n) for n in FLAGS},
                "cb": [bs.get_cb(r, c, k) for k in range(B.LUT_K)],
                "ce": bs.get_field(r, c, "cb_ce"),
                "sr": bs.get_field(r, c, "cb_sr"),
                "sb": {(d, t): bs.get_sb(r, c, d, t) for d in range(4) for t in range(B.NTRACK)},
            }

    def dsp_pins(self, north_out):
        """Both DSP slices' inputs from the bus sources, control muxes and drive word."""
        fab = sum(bit << k for k, bit in enumerate(north_out))
        pins = []
        for s in (0, 1):
            drv = (self.dsp_drive >> (124 * s)) & ((1 << 124) - 1)
            cfg = self.dsp_cfgs[s]

            def bus(src, lo, w):
                if src == 1:
                    return _sx(drv >> lo, w)
                if src == 2:
                    return _sx(fab, w)
                return 0
            p = {"a": bus(cfg["bus_a"], 0, 25), "b": bus(cfg["bus_b"], 25, 18),
                 "c": bus(cfg["bus_c"], 43, 48), "d": bus(cfg["bus_d"], 91, 25)}
            for k, name in enumerate(DSP_CTRL_NAMES):
                sel = self.dsp_ctrl_sel[s][k]
                if sel <= 1:
                    p[name] = sel
                elif sel == B.DSP_SRC_JTAG:
                    p[name] = (drv >> (116 + k)) & 1
                elif B.DSP_SRC_TRK0 <= sel < B.DSP_SRC_TRK0 + B.N_NORTH:
                    p[name] = north_out[sel - B.DSP_SRC_TRK0]
                else:
                    p[name] = 0
            pins.append(p)
        return pins

    def dsp_p(self, north_out):
        return dsp_cascade_p(self.dsp, self.dsp_cfgs, self.dsp_pins(north_out))

    def settle(self, pad_i=0, cin=0, max_iter=256):
        """Combinational fixed point with every FF output held at its q."""
        o = {t: 0 for t in self.tiles}
        o5 = {t: 0 for t in self.tiles}
        comb = {t: 0 for t in self.tiles}
        ce = {t: 0 for t in self.tiles}
        sr = {t: 0 for t in self.tiles}
        carry = {}
        trk = {(r, c, d, t): 0 for (r, c) in self.tiles
               for d in range(4) for t in range(B.NTRACK)}

        do = {"a": self.bram.do("a", self.bram_cfg), "b": self.bram.do("b", self.bram_cfg)}
        dsp_p = [0, 0]           # refreshed every iteration: combinational DSP paths see the tracks

        def dsp_track(k):
            sel = self.dsp_out_sel[k]
            if B.DSP_OUT_P0 <= sel < B.DSP_OUT_P0 + 48:
                return (dsp_p[0] >> (sel - B.DSP_OUT_P0)) & 1
            if B.DSP_OUT_P1 <= sel < B.DSP_OUT_P1 + 48:
                return (dsp_p[1] >> (sel - B.DSP_OUT_P1)) & 1
            return 0

        def bram_track(k):
            sel = self.bram_out_sel[k]
            if B.BRAM_OUT_DOA0 <= sel < B.BRAM_OUT_DOA0 + Bram.DATA_W:
                return (do["a"] >> (sel - B.BRAM_OUT_DOA0)) & 1
            if B.BRAM_OUT_DOB0 <= sel < B.BRAM_OUT_DOB0 + Bram.DATA_W:
                return (do["b"] >> (sel - B.BRAM_OUT_DOB0)) & 1
            return 0

        def in_track(r, c, d, t):
            if d == B.DIR_N:
                return trk[(r + 1, c, B.DIR_S, t)] if r + 1 < B.GRID_R else dsp_track(c * B.NTRACK + t)
            if d == B.DIR_E:
                return trk[(r, c + 1, B.DIR_W, t)] if c + 1 < B.GRID_C else bram_track(r * B.NTRACK + t)
            if d == B.DIR_S:
                if r > 0:
                    return trk[(r - 1, c, B.DIR_N, t)]
                k = B.EDGE_PAD.get(("S", t))
                return (pad_i >> k) & 1 if k is not None else 0
            if c > 0:
                return trk[(r, c - 1, B.DIR_E, t)]
            k = B.EDGE_PAD.get(("W", t))
            return (pad_i >> k) & 1 if k is not None else 0

        def pick(s, sel):
            return s[sel] if sel < B.NSRC else 0

        for _ in range(max_iter):
            changed = False
            north = [trk[(B.GRID_R - 1, c, B.DIR_N, t)] for c in range(B.GRID_C) for t in range(B.NTRACK)]
            new_p = list(self.dsp_p(north))
            if new_p != dsp_p:
                dsp_p[:] = new_p
                changed = True
            for (r, c) in self.tiles:
                cfg = self._cfg[(r, c)]
                f = cfg["flags"]
                s = [0] * B.NSRC
                s[B.SRC_C1] = 1
                s[B.SRC_CLB_O] = o[(r, c)]
                s[B.SRC_CLB_O5] = o5[(r, c)]
                for t in range(B.NTRACK):
                    s[B.src_n(t)] = in_track(r, c, B.DIR_N, t)
                    s[B.src_e(t)] = in_track(r, c, B.DIR_E, t)
                    s[B.src_s(t)] = in_track(r, c, B.DIR_S, t)
                    s[B.src_w(t)] = in_track(r, c, B.DIR_W, t)

                i = sum(pick(s, sel) << k for k, sel in enumerate(cfg["cb"]))
                c_in = cin if r == 0 else carry.get((r - 1, c), 0)
                _o6, lo5, lcomb, cout = clb_comb(cfg["init"], f, i, c_in)
                lo = self.q[(r, c)] if f["ff_en"] else lcomb
                vals = (lo, lo5, lcomb, cout, pick(s, cfg["ce"]), pick(s, cfg["sr"]))
                if (o[(r, c)], o5[(r, c)], comb[(r, c)], carry.get((r, c)),
                        ce[(r, c)], sr[(r, c)]) != vals:
                    o[(r, c)], o5[(r, c)], comb[(r, c)], carry[(r, c)], ce[(r, c)], sr[(r, c)] = vals
                    changed = True
                for (d, t), sel in cfg["sb"].items():
                    v = pick(s, sel)
                    if trk[(r, c, d, t)] != v:
                        trk[(r, c, d, t)] = v
                        changed = True
            if not changed:
                break
        else:
            raise ValueError("fabric did not settle - combinational loop in the design")

        pad_o = sum(trk[(p["row"], p["col"], B.DIR_OF_NAME[p["dir"]], p["track"])] << k
                    for k, p in B.PAD_OUT.items())
        east = [trk[(r, B.GRID_C - 1, B.DIR_E, t)] for r in range(B.GRID_R) for t in range(B.NTRACK)]
        north = [trk[(B.GRID_R - 1, c, B.DIR_N, t)] for c in range(B.GRID_C) for t in range(B.NTRACK)]
        return {"o": o, "comb": comb, "ce": ce, "sr": sr, "pad_o": pad_o, "east_out": east,
                "north_out": north, "dsp_p": tuple(dsp_p)}

    def bram_pins(self, east_out):
        """The two BRAM ports' pin values from the pin muxes."""
        vals = []
        for k, sel in enumerate(self.bram_pin_sel):
            if sel <= 1:
                vals.append(sel)
            elif sel == B.BRAM_SRC_JTAG:
                vals.append((self.drive >> k) & 1)
            elif B.BRAM_SRC_TRK0 <= sel < B.BRAM_SRC_TRK0 + B.N_EDGE:
                vals.append(east_out[sel - B.BRAM_SRC_TRK0])
            else:
                vals.append(0)
        pins = {}
        n = len(B.BRAM_PINS)
        for pi, p in enumerate("ab"):
            v = vals[pi * n:(pi + 1) * n]
            pins[p] = {"addr": sum(v[k] << k for k in range(Bram.ADDR_W)),
                       "di": sum(v[Bram.ADDR_W + k] << k for k in range(Bram.DATA_W)),
                       "we": v[28], "en": v[29], "rst": v[30], "regce": v[31]}
        return pins

    def outputs(self, pad_i=0, cin=0):
        return self.settle(pad_i, cin)["pad_o"]

    def clb_o(self, pad_i=0, cin=0):
        """The 16 CLB outputs as an int, bit r*GRID_C+c (CAPTURE / USER1 order)."""
        o = self.settle(pad_i, cin)["o"]
        return sum(o[(r, c)] << (r * B.GRID_C + c) for (r, c) in self.tiles)

    def clock(self, pad_i=0, cin=0, gce=1, gsr=0, gwe=1):
        """One fabric clock edge."""
        s = self.settle(pad_i, cin)
        pins = self.bram_pins(s["east_out"])
        self.q = {t: clb_next(self.q[t], self._cfg[t]["flags"], s["comb"][t],
                              s["ce"][t], s["sr"][t], gce, gsr, gwe)
                  for t in self.tiles}
        self.bram.clock(self.bram_cfg, pins, gce=gce, gsr=gsr, gwe=gwe)
        dsp_cascade_clock(self.dsp, self.dsp_cfgs, self.dsp_pins(s["north_out"]), gce=gce, gsr=gsr, gwe=gwe)


if __name__ == "__main__":
    import designs
    m = Fabric(designs.d_counter().build())
    m.clock(gsr=1)
    seq = []
    for _ in range(18):
        seq.append(sum(m.q[(r, 0)] << r for r in range(4)))
        m.clock(cin=1)
    print("counter states:", seq)

