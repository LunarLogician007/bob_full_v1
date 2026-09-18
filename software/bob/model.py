#!/usr/bin/env python3
"""
model.py - cycle model of the fabric, with flip-flops and the user clock (M4),
BRAM (M5), DSP (M6), and since M7 the routing-resource graph itself.

The fabric is evaluated exactly as hw/src/generated/bob_fabric.v wires it: every
programmed mux passes its selected input (0 const0, IPIN 1 const1), directs
(carry, DSP cascade) are wires, and each CLB's flip-flop is clb.sv's:

    if gsr:              q <= ff_rstval
    elif gwe and gce:
        if ff_sr_en & sr: q <= ff_rstval          (FDRE/FDSE: SR beats CE)
        elif !ff_ce_en | ce: q <= comb

CE and SR are the CLB's routed input pins. One call to clock() is one fabric
clock edge with the given global enable.

Used by sim/gen_clb_vectors.py (CLB flag sweep), sim/gen_vectors.py (sequential
fabric designs) and tests/test_model.py. Honours BOB_DEVICE_JSON like bitstream.py.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "software", "host"))

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
    """The whole fabric for one chain word. Board vectors as software/host/bitstream.py:
    pad_i bit k = BOARD_IN[k]; outputs() bit k = LDk. `pads` (an NPAD-bit int)
    overrides the world side of every pad instead (boundary-scan-only pads)."""

    def __init__(self, bs):
        word = bs.to_int() if hasattr(bs, "to_int") else int(bs)
        self.word = word
        get = lambda lo, w: (word >> lo) & ((1 << w) - 1)          # noqa: E731

        # programmed muxes only: everything else is a constant 0
        self.active = []
        for node, (lo, w, base, ins) in B.MUX.items():
            sel = get(lo, w)
            if sel:
                self.active.append((node, sel, base, ins))
        self.active.sort()
        self.directs = sorted(B.DIRECT.items())
        self.cin_nodes = [B.PIN[f"{n}.cin[0]"] for n in B.CLBS if B.PIN[f"{n}.cin[0]"] not in B.DIRECT]

        self.clbs = []
        for i, name in enumerate(B.CLBS):
            blk = B.BLOCKS[name]
            bs_ = B.Bitstream(word)
            self.clbs.append({
                "xy": (blk["x"], blk["y"]), "index": i,
                "init": bs_.get_block(name, "init"),
                "flags": {f: bs_.get_block(name, f) for f in FLAGS},
                "I": [B.PIN[f"{name}.I[{j}]"] for j in range(B.LUT_K)],
                "ce": B.PIN[f"{name}.ce[0]"], "sr": B.PIN[f"{name}.sr[0]"],
                "cin": B.PIN[f"{name}.cin[0]"],
                "O": B.PIN[f"{name}.O[0]"], "O5": B.PIN[f"{name}.O5[0]"], "cout": B.PIN[f"{name}.cout[0]"],
            })
        self.q = {c["xy"]: 0 for c in self.clbs}

        bs_ = B.Bitstream(word)
        self.brams = [Bram() for _ in range(B.NBRAM)]
        self.bram = self.brams[0] if self.brams else None
        self.bram_drive = [0] * B.NBRAM
        self.bram_cfgs = [{f: bs_.get_bram(b, f) for f in ("wmode_a", "wmode_b", "reg_a", "reg_b",
                                                           "jtag_a", "jtag_b")}
                          for b in range(B.NBRAM)]
        self.bram_cfg = self.bram_cfgs[0] if self.bram_cfgs else None
        self.dsp = [Dsp() for _ in range(B.NDSP)]
        self.dsp_drive = 0
        self.dsp_cfgs = [{f: bs_.get_dsp(s, f) for f in DSP_CFG_NAMES + ("jtag_a", "jtag_b", "jtag_c",
                                                                        "jtag_d", "jtag_ctrl")}
                         for s in range(B.NDSP)]
        self.pad_in = [B.PIN[f"{B.pad_block(n)}.inpad[0]"] for n in range(B.NPAD)]
        self.pad_out = [B.PIN[f"{B.pad_block(n)}.outpad[0]"] for n in range(B.NPAD)]

    # --- pins of the hard blocks ---

    def bram_pins(self, v, b=0):
        pins = {}
        for pi, port in enumerate("ab"):
            if self.bram_cfgs[b][f"jtag_{port}"]:
                word = (self.bram_drive[b] >> (32 * pi)) & 0xFFFFFFFF
                bit = lambda k: (word >> k) & 1                    # noqa: E731
            else:
                nodes = []
                for n, w in B.BRAM_PORT_PINS:
                    nodes += [B.PIN[f"bram{b}.{n}_{port}[{k}]"] for k in range(w)]
                bit = lambda k, nodes=nodes: v.get(nodes[k], 0)     # noqa: E731
            pins[port] = {"addr": sum(bit(k) << k for k in range(Bram.ADDR_W)),
                          "di": sum(bit(Bram.ADDR_W + k) << k for k in range(Bram.DATA_W)),
                          "we": bit(28), "en": bit(29), "rst": bit(30), "regce": bit(31)}
        return pins

    def dsp_pins(self, v, s):
        cfg = self.dsp_cfgs[s]
        drv = (self.dsp_drive >> (124 * s)) & ((1 << 124) - 1)
        p = {}
        lo = 0
        for bus, w in B.DSP_BUSES:
            if cfg[f"jtag_{bus}"]:
                p[bus] = _sx(drv >> lo, w)
            else:
                p[bus] = _sx(sum(v.get(B.PIN[f"dsp{s}.{bus}[{k}]"], 0) << k for k in range(w)), w)
            lo += w
        for k, name in enumerate(DSP_CTRL_NAMES):
            p[name] = (drv >> (116 + k)) & 1 if cfg["jtag_ctrl"] else v.get(B.PIN[f"dsp{s}.{name}[0]"], 0)
        return p

    # --- evaluation ---

    def settle(self, pad_i=0, cin=0, pads=None, max_iter=1000):
        """Combinational fixed point with every register held."""
        if pads is None:
            pads = 0
            for k, n in enumerate(B.BOARD_IN):
                pads |= ((pad_i >> k) & 1) << n
        v = {}
        for n, node in enumerate(self.pad_in):
            v[node] = (pads >> n) & 1
        for node in self.cin_nodes:
            v[node] = cin & 1
        for b, bram in enumerate(self.brams):
            for port in "ab":
                do = bram.do(port, self.bram_cfgs[b])
                for k in range(Bram.DATA_W):
                    v[B.PIN[f"bram{b}.do_{port}[{k}]"]] = (do >> k) & 1
        comb, ce, sr = {}, {}, {}
        dsp_p = [0] * B.NDSP
        o5_mask = (1 << (B.LUT_K - 1)) - 1

        for _ in range(max_iter):
            changed = False

            def put(node, val):
                nonlocal changed
                if v.get(node, 0) != val or node not in v:
                    changed = changed or v.get(node, 0) != val
                    v[node] = val

            for node, sel, base, ins in self.active:
                if sel == 1 and base == 2:
                    val = 1
                elif base <= sel < base + len(ins):
                    val = v.get(ins[sel - base], 0)
                else:
                    val = 0
                put(node, val)
            for ipin, opin in self.directs:
                put(ipin, v.get(opin, 0))
            for c in self.clbs:
                i = sum(v.get(n, 0) << j for j, n in enumerate(c["I"]))
                _o6, lo5, lcomb, cout = clb_comb(c["init"], c["flags"], i, v.get(c["cin"], 0))
                xy = c["xy"]
                comb[xy], ce[xy], sr[xy] = lcomb, v.get(c["ce"], 0), v.get(c["sr"], 0)
                put(c["O"], self.q[xy] if c["flags"]["ff_en"] else lcomb)
                put(c["O5"], lo5)
                put(c["cout"], cout)
            pcin = 0
            for s in range(B.NDSP):
                p = self.dsp[s].p(self.dsp_cfgs[s], self.dsp_pins(v, s), pcin)
                dsp_p[s] = p
                pcin = p
                for k in range(48):
                    bit = (p >> k) & 1
                    put(B.PIN[f"dsp{s}.p[{k}]"], bit)
                    put(B.PIN[f"dsp{s}.pcout[{k}]"], bit)
            if not changed:
                break
        else:
            raise ValueError("fabric did not settle - combinational loop in the design")

        pad_out = sum(v.get(node, 0) << n for n, node in enumerate(self.pad_out))
        pad_o = sum(((pad_out >> n) & 1) << k for k, n in enumerate(B.BOARD_OUT))
        o = {c["xy"]: v.get(c["O"], 0) for c in self.clbs}
        return {"v": v, "o": o, "comb": comb, "ce": ce, "sr": sr, "pad_out": pad_out,
                "pad_o": pad_o, "dsp_p": tuple(dsp_p)}

    def outputs(self, pad_i=0, cin=0, pads=None):
        return self.settle(pad_i, cin, pads)["pad_o"]

    def clb_o(self, pad_i=0, cin=0):
        """Every CLB output as an int, bit i = CLB i (CAPTURE order)."""
        o = self.settle(pad_i, cin)["o"]
        return sum(o[c["xy"]] << c["index"] for c in self.clbs)

    def dsp_p(self, pad_i=0, cin=0):
        return self.settle(pad_i, cin)["dsp_p"]

    def clock(self, pad_i=0, cin=0, gce=1, gsr=0, gwe=1, pads=None):
        """One fabric clock edge."""
        s = self.settle(pad_i, cin, pads)
        v = s["v"]
        bram_pins = [self.bram_pins(v, b) for b in range(B.NBRAM)]
        dsp_pins = [self.dsp_pins(v, k) for k in range(B.NDSP)]
        self.q = {c["xy"]: clb_next(self.q[c["xy"]], c["flags"], s["comb"][c["xy"]],
                                    s["ce"][c["xy"]], s["sr"][c["xy"]], gce, gsr, gwe)
                  for c in self.clbs}
        for b, bram in enumerate(self.brams):
            bram.clock(self.bram_cfgs[b], bram_pins[b], gce=gce, gsr=gsr, gwe=gwe)
        pcin = 0
        for k in range(B.NDSP):
            p_pre = s["dsp_p"][k]
            self.dsp[k].clock(self.dsp_cfgs[k], dsp_pins[k], pcin, gce=gce, gsr=gsr, gwe=gwe)
            pcin = p_pre


if __name__ == "__main__":
    import designs
    m = Fabric(designs.d_counter().build())
    m.clock(gsr=1)
    seq = []
    for _ in range(18):
        seq.append(sum(m.q[(1, 1 + r)] << r for r in range(4)))
        m.clock(cin=1)
    print("counter states:", seq)
