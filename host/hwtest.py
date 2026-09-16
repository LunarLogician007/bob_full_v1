#!/usr/bin/env python3
"""
Hardware test after every milestone, on the PYNQ-Z2 through the Pico.

  ./hwtest.py --milestone M0            regression, then that milestone's checks
  ./hwtest.py --milestone M0 --list     show what would run; touch no hardware
  ./hwtest.py --milestone M0 --manual   also walk through docs/hwtest/M0.md by hand

The regression always runs first, so a milestone can never pass while breaking
an earlier one:
  idcode    the IDCODE on the wire equals hw/build.cfg's - the PL holds THIS bundle
  bypass    BYPASS is exactly one bit long (TAP state machine and TDO edge sane)
  selftest  every design in host/designs.py loads, reads back and matches the
            software model through INTEST   (what fpga.py --selftest does)

Every run is appended to docs/hwtest/results.log.
"""

import argparse
import datetime
import os
import sys

import buildcfg

ROOT = buildcfg.ROOT
sys.path.insert(0, os.path.join(ROOT, "tools", "bob"))     # chainbits, model
LOG = os.path.join(ROOT, "docs", "hwtest", "results.log")


# --- checks ------------------------------------------------------------------
# Each takes (probe, ctx) and returns (ok, detail). Hardware imports stay inside
# them so --list works on a machine with no probe and no pyusb.

def check_idcode(p, ctx):
    want = buildcfg.expected_idcode(ctx["cfg"])
    got = p.read_idcode()
    ctx["idcode"] = got
    if want is None:
        return True, f"0x{got:08X} (build.cfg sets no idcode)"
    return got == want, f"0x{got:08X}, build.cfg expects 0x{want:08X}"


def check_bypass(p, ctx):
    irw = int(ctx["cfg"].get("ir_width", "4"))
    n, din = 24, 0xA5C35A
    mask = (1 << n) - 1
    p.shift_ir((1 << irw) - 1, width=irw)          # BYPASS is all ones at any width
    out = p.shift_dr(n, din)
    for length in range(0, 4):
        if out == (din << length) & mask:
            return length == 1, f"measured {length} bit(s)"
    return False, f"no clean delay: sent 0x{din:06X}, got 0x{out:06X}"


def check_selftest(p, ctx):
    import fpga
    from designs import DESIGNS
    results = [fpga.verify(p, k, d, f, s) for k, d, f, s in DESIGNS]
    fpga.go_live(p)
    return all(results), f"{sum(results)}/{len(results)} designs match the model"


def check_showcase_live(p, ctx):
    """Load showcase, leave test mode, and compare the REAL pads with the model
    for whatever the switches are set to right now (SAMPLE is transparent)."""
    import fpga
    from bitstream import simulate
    from designs import BY_KEY
    import cfgplane
    bs = BY_KEY["showcase"][1]().build()
    if not fpga.load_bitstream(p, bs, verbose=False):
        return False, "load/readback failed"
    fpga.go_live(p)
    cfgplane.ir(p, "SAMPLE")
    s = fpga.sample(p)
    exp = simulate(bs, s["i"])
    return s["leds"] == exp, f"pad_i={s['i']:06b} LD2..0={s['leds']:03b} model={exp:03b}"


def check_chain_length(p, ctx):
    """The config chain on the board is exactly device.json's width."""
    import cfgplane
    import fpga
    from bitstream import DEVICE, simulate
    from designs import BY_KEY
    W = DEVICE["chain"]["width"]
    key = "showcase"
    bs = BY_KEY[key][1]().build()
    word = bs.to_int()
    if not fpga.load_bitstream(p, bs, verbose=False):
        return False, "load/readback failed"

    # M3: a marker through CFG_OUT, which never commits (the M1 version had to
    # re-shift the config word behind the marker through the old CONFIG chain).
    n = cfgplane.measure_chain(p, W + 64)
    if n != W:
        return False, f"marker measured {n}, device.json width is {W}"
    if cfgplane.cfg_out(p, W) != word:
        return False, "config changed by the marker scan"
    vs = list(BY_KEY[key][2])
    got = fpga.intest_sweep(p, vs)
    bad = [v for v, g in zip(vs, got) if g != simulate(bs, v)]
    fpga.go_live(p)
    if bad:
        return False, f"chain is {W} bits but {len(bad)} vectors wrong afterwards"
    return True, f"{W} bits, design intact after the marker scan"


# --- M2: configuration plane on cfg_test_top ----------------------------------

M2_CHAIN_W = 64          # cfg_test_top: 4 tiles x 16 bits (hw/src/top/cfg_test_top.v)


def check_usercode(p, ctx):
    import cfgplane
    want = int(ctx["cfg"].get("usercode", "0"), 16)
    got = cfgplane.usercode(p)
    return got == want, f"0x{got:08X}, build.cfg expects 0x{want:08X}"


def check_ir_capture(p, ctx):
    """After JPROGRAM the IR capture reads 01 in the LSBs, INIT_B=1, DONE=0."""
    import cfgplane
    cfgplane.jprogram(p)
    s = cfgplane.ir_status(p)
    ok = s["lsb01"] and s["init_b"] and not s["done"] and not s["committed"]
    return ok, str(s)


def check_cfg_chain_length(p, ctx):
    """A marker through CFG_OUT comes out after exactly the chain width."""
    import cfgplane
    cfgplane.jprogram(p)
    n = cfgplane.measure_chain(p, M2_CHAIN_W + 64)
    return n == M2_CHAIN_W, f"measured {n}, cfg_test_top has {M2_CHAIN_W}"


def check_load_readback(p, ctx):
    import random
    import cfgplane
    rng = random.Random()
    for _ in range(4):
        w = rng.getrandbits(M2_CHAIN_W)
        ok, msg = cfgplane.load(p, w, M2_CHAIN_W, start=False)
        if not ok:
            return False, msg
        if cfgplane.cfg_out(p, M2_CHAIN_W) != w:
            return False, "second readback differs"
    return True, "4 random chains committed with CRC and read back twice"


def check_crc_reject(p, ctx):
    import random
    import cfgplane
    from chainbits import crc32c_bits
    rng = random.Random()
    a = rng.getrandbits(M2_CHAIN_W)
    ok, msg = cfgplane.load(p, a, M2_CHAIN_W, start=False)
    if not ok:
        return False, "setup: " + msg
    b = rng.getrandbits(M2_CHAIN_W)
    cfgplane.write_expected(p, crc32c_bits(b, M2_CHAIN_W))
    cfgplane.cfg_in(p, b ^ (1 << rng.randrange(M2_CHAIN_W)), M2_CHAIN_W)
    st = cfgplane.status(p)
    back = cfgplane.cfg_out(p, M2_CHAIN_W)
    ok = st["crc_err"] and not st["crc_ok"] and st["committed"] and back == a
    return ok, f"crc_err={st['crc_err']} committed={st['committed']} previous kept={back == a}"


def check_len_reject(p, ctx):
    import random
    import cfgplane
    from chainbits import crc32c_bits
    a = cfgplane.cfg_out(p, M2_CHAIN_W)
    n = M2_CHAIN_W - 1
    b = random.Random().getrandbits(n)
    # CRC correct for the 63 bits sent, so only the length guard can refuse
    cfgplane.write_expected(p, crc32c_bits(b, n))
    cfgplane.cfg_in(p, b, n)
    st = cfgplane.status(p)
    back = cfgplane.cfg_out(p, M2_CHAIN_W)
    ok = st["len_err"] and not st["crc_err"] and st["count"] == n and back == a
    return ok, (f"len_err={st['len_err']} crc_err={st['crc_err']} count={st['count']} "
                f"previous kept={back == a}")


def check_startup(p, ctx):
    """JSTART needs a commit; then GSR, GTS, GWE, DONE. Leaves LD3 on, LD2..0 = 101."""
    import random
    import cfgplane
    cfgplane.jprogram(p)
    cfgplane.jstart(p)
    st = cfgplane.status(p)
    if st["done"] or not st["gsr"]:
        return False, f"JSTART without a commit changed startup: {st}"
    w = (random.Random().getrandbits(M2_CHAIN_W) & ~0b111) | 0b101
    ok, msg = cfgplane.load(p, w, M2_CHAIN_W, start=True)
    if not ok:
        return False, msg
    st = cfgplane.status(p)
    ok = st["done"] and st["gwe"] and not st["gsr"] and not st["gts"]
    return ok, f"GSR={st['gsr']} GTS={st['gts']} GWE={st['gwe']} DONE={st['done']}  (LD3 on, LD2..0 = 101)"


def check_capture(p, ctx):
    import cfgplane
    cfgplane.user1(p, 1)                       # ce: the counter runs while GWE
    cfgplane.idle(p, 40)
    c1 = cfgplane.capture(p)
    cfgplane.idle(p, 40)
    c2 = cfgplane.capture(p)
    cfgplane.user1(p, 0)
    ok = (c1 & 0xFF) != (c2 & 0xFF) and (c1 >> 8) & 0x3 == 0
    return ok, (f"counter {c1 & 0xFF} -> {c2 & 0xFF}, SW1..0={(c2 >> 10) & 3:02b} "
                f"BTN3..0={(c2 >> 12) & 0xF:04b}")


def check_jprogram(p, ctx):
    import cfgplane
    cfgplane.user1(p, 1)
    cfgplane.jprogram(p)
    cfgplane.idle(p, 8)
    c = cfgplane.capture(p)
    back = cfgplane.cfg_out(p, M2_CHAIN_W)
    st = cfgplane.status(p)
    cfgplane.user1(p, 0)
    ok = (c & 0xFF) == 0 and back == 0 and not st["done"] and st["gsr"] and not st["committed"]
    return ok, f"counter={c & 0xFF} chain=0x{back:X} DONE={st['done']} GSR={st['gsr']}"


# --- M3: the configuration plane inside the complete 4x4 fabric ----------------

def _fabric_bs(key):
    from designs import BY_KEY
    return BY_KEY[key][1]().build()


def check_fabric_ir_status(p, ctx):
    """After a full load the IR capture shows DONE, INIT_B and COMMITTED."""
    import cfgplane
    import fpga
    if not fpga.load_bitstream(p, _fabric_bs("showcase"), verbose=False):
        return False, "load failed"
    s = cfgplane.ir_status(p)
    return bool(s["done"] and s["init_b"] and s["committed"] and s["lsb01"]), str(s)


def check_crc_reject_live(p, ctx):
    """A corrupted chain is refused while showcase runs; showcase keeps working."""
    import cfgplane
    import fpga
    from bitstream import FABRIC_CFG_W, simulate
    from chainbits import crc32c_bits
    from designs import BY_KEY
    show = _fabric_bs("showcase")
    if not fpga.load_bitstream(p, show, verbose=False):
        return False, "load failed"
    other = _fabric_bs("xor6").to_int()
    cfgplane.write_expected(p, crc32c_bits(other, FABRIC_CFG_W))
    cfgplane.cfg_in(p, other ^ (1 << 1234), FABRIC_CFG_W)
    st = cfgplane.status(p)
    kept = cfgplane.cfg_out(p, FABRIC_CFG_W) == show.to_int()
    vs = list(BY_KEY["showcase"][2])
    got = fpga.intest_sweep(p, vs)
    bad = [v for v, g in zip(vs, got) if g != simulate(show, v)]
    fpga.go_live(p)
    ok = st["crc_err"] and st["done"] and kept and not bad
    return ok, f"crc_err={st['crc_err']} DONE={st['done']} config kept={kept} showcase vectors wrong={len(bad)}"


def check_gts(p, ctx):
    """Committed but not started: outputs forced 0. After JSTART: the design's answer."""
    import cfgplane
    import fpga
    from bitstream import FABRIC_CFG_W, simulate
    show = _fabric_bs("showcase")
    ok, msg = cfgplane.load(p, show.to_int(), FABRIC_CFG_W, start=False)
    if not ok:
        return False, msg
    vec = 0b000011                     # SW1=SW0=1: showcase answers 011
    before = fpga.intest_sweep(p, [vec])[0]
    cfgplane.jstart(p)
    after = fpga.intest_sweep(p, [vec])[0]
    fpga.go_live(p)
    exp = simulate(show, vec)
    return before == 0 and after == exp, \
        f"outputs before JSTART={before:03b}, after={after:03b}, model={exp:03b}"


def check_gsr_gwe(p, ctx):
    """GSR holds a FF at INIT; with GSR off but GWE still 0 it stays frozen; GWE lets it clock."""
    import cfgplane
    from bitstream import FABRIC_CFG_W
    from designs import d_gsr_probe
    ok, msg = cfgplane.load(p, d_gsr_probe().build().to_int(), FABRIC_CFG_W, start=False)
    if not ok:
        return False, msg
    cfgplane.user1(p, 1)               # ce
    cfgplane.idle(p, 8)
    held = cfgplane.capture(p) & 1
    done_early = cfgplane.status(p)["done"]

    # One TCK in Run-Test/Idle with JSTART = phase 1 (GSR off). Leaving RTI for
    # the CAPTURE scan is a second RTI edge = phase 2 (GTS off). GWE rises only
    # at phase 3, so the flip-flop has seen GSR=0/GWE=0 and must still be 1.
    cfgplane.jstart(p, tcks=1)
    frozen = cfgplane.capture(p) & 1
    mid = cfgplane.status(p)

    cfgplane.jstart(p)
    cfgplane.idle(p, 8)
    ran = cfgplane.capture(p) & 1
    done = cfgplane.status(p)["done"]
    cfgplane.user1(p, 0)
    ok = (held == 1 and not done_early and frozen == 1 and not mid["gsr"]
          and not mid["gwe"] and ran == 0 and done)
    return ok, (f"q: GSR={held} (INIT 1), GSR off+GWE 0={frozen} (frozen 1, gsr={mid['gsr']} "
                f"gwe={mid['gwe']}), running={ran} (D 0); DONE before/after JSTART={done_early}/{done}")


def check_capture_user1(p, ctx):
    """CAPTURE (16 CLB outputs) agrees with USER1 status bits [19:4]."""
    import cfgplane
    import fpga
    if not fpga.load_bitstream(p, _fabric_bs("showcase"), verbose=False):
        return False, "load failed"
    fpga.go_live(p)
    c = cfgplane.capture(p)
    u = (cfgplane.user1(p, 0) >> 4) & 0xFFFF
    return c == u, f"CAPTURE=0x{c:04X} USER1[19:4]=0x{u:04X} (switches must not move during the check)"


def check_fabric_jprogram(p, ctx):
    """JPROGRAM from a running design: config cleared, outputs dark, DONE off."""
    import cfgplane
    import fpga
    from bitstream import FABRIC_CFG_W
    if not fpga.load_bitstream(p, _fabric_bs("showcase"), verbose=False):
        return False, "load failed"
    cfgplane.jprogram(p)
    st = cfgplane.status(p)
    back = cfgplane.cfg_out(p, FABRIC_CFG_W)
    pads = fpga.intest_sweep(p, [0b000011])[0]
    fpga.go_live(p)
    ok = not st["done"] and st["gts"] and back == 0 and pads == 0
    return ok, f"DONE={st['done']} GTS={st['gts']} chain zero={back == 0} outputs={pads:03b}"


# --- M4: user clock, routed CE/SR, carry-chain counter -----------------------------

def _counter_value(capture_bits, x=None, bits=4):
    """q0..q[bits-1] of a counter up column x: CLBs (x,1)..(x,bits), at their CAPTURE indices."""
    import bitstream as B
    from designs import COUNTER_X
    x = COUNTER_X if x is None else x
    return sum(((capture_bits >> B.CLB_XY_INDEX[(x, 1 + r)]) & 1) << r for r in range(bits))


def _capture_w():
    import bitstream as B
    return B.NCLB


def check_ce_sr(p, ctx):
    """Routed CE (SW0 path) and SR (SW1 path) on tile(0,0) follow model.py, driven via INTEST
    autostep: one fabric clock per INTEST scan, independent of the real switches."""
    import cfgplane
    import fpga
    import model
    from designs import d_ce_sr
    bs = d_ce_sr().build()
    if not fpga.load_bitstream(p, bs, verbose=False):
        return False, "load failed"
    # USER1 autostep, ce OFF. The first version set ce=1 here: during that USER1
    # scan the boundary is transparent, the physical SW0/SW1 reached CE/SR for
    # ~30 TCK edges, and the flop started from whatever the switches said (it
    # failed with SW0 up / SW1 down). With ce off nothing clocks outside INTEST,
    # and each INTEST Update-DR clocks exactly once with the injected vector.
    cfgplane.user1(p, 0x10)
    m = model.Fabric(bs)
    m.clock(gsr=1)
    bad = []
    for v in (0b00, 0b01, 0b11, 0b01, 0b00, 0b10, 0b01):
        got = fpga.intest_sweep(p, [v])[0]   # scan 1 applies v (clock), scan 2 captures (clock)
        m.clock(pad_i=v)
        exp = m.outputs(v) & 1
        m.clock(pad_i=v)
        if got & 1 != exp:
            bad.append(f"SW1..0={v:02b}: q={got & 1} model={exp}")
    cfgplane.user1(p, 0)
    fpga.go_live(p)
    return not bad, "; ".join(bad) or "CE loads, SR clears (beats CE), both low holds - 7 steps match model.py"


def check_counter_step(p, ctx):
    """JTAG-stepped counter: exactly one count per TCK edge (an n-bit CAPTURE scan is n+5 edges)."""
    import cfgplane
    import fpga
    from designs import d_counter
    if not fpga.load_bitstream(p, d_counter("jtag").build(), verbose=False):
        return False, "load failed"
    n = _capture_w()
    want = (n + 5) % 16
    cfgplane.user1(p, 0b101)                     # ce + cin
    cfgplane.ir(p, "CAPTURE")
    vals = [_counter_value(p.shift_dr(n, 0)) for _ in range(6)]
    diffs = [(b - a) % 16 for a, b in zip(vals, vals[1:])]
    cfgplane.user1(p, 0b100)                     # cin only: ce off
    cfgplane.ir(p, "CAPTURE")
    held = [_counter_value(p.shift_dr(n, 0)) for _ in range(3)]
    return (all(d == want for d in diffs) and len(set(held)) == 1,
            f"counts {vals} (steps {diffs}, want {want} each); ce off: {held} (want constant)")


def check_counter_run(p, ctx):
    """Free-running user clock: div 16 = 125 MHz / 2**24 = 7.45 counts/s, measured over ~3 s."""
    import time
    import cfgplane
    import fpga
    from designs import d_counter
    if not fpga.load_bitstream(p, d_counter("run", 16).build(), verbose=False):
        return False, "load failed"
    cfgplane.user1(p, 0b100)                     # cin only; ce irrelevant in run mode
    cfgplane.ir(p, "CAPTURE")
    n = _capture_w()
    t0 = time.time()
    last = _counter_value(p.shift_dr(n, 0))
    counts = 0
    while time.time() - t0 < 3.0:
        v = _counter_value(p.shift_dr(n, 0))
        counts += (v - last) % 16                # samples are far faster than 16 counts
        last = v
    dt = time.time() - t0
    rate = counts / dt
    return 6.0 <= rate <= 9.0, f"{counts} counts in {dt:.2f} s = {rate:.2f}/s (expected 7.45)"


def check_blinky(p, ctx):
    """Leave the counter free-running at div 17 (3.73 counts/s) for the LED check."""
    import cfgplane
    import fpga
    from designs import d_counter
    if not fpga.load_bitstream(p, d_counter("run", 17).build(), verbose=False):
        return False, "load failed"
    cfgplane.user1(p, 0b100)
    fpga.go_live(p)
    return True, "running: LD0 ~0.93 Hz, LD1 ~0.47 Hz, LD2 ~0.23 Hz, LD3 on (check by eye)"


# --- M5: the BRAM tile -------------------------------------------------------------

def check_bram_init(p, ctx):
    """64 random words written over USER4 before startup read back exactly."""
    import random
    import cfgplane
    from bitstream import FABRIC_CFG_W
    from designs import d_bram_rom
    ok, msg = cfgplane.load(p, d_bram_rom().build().to_int(), FABRIC_CFG_W, start=False)
    if not ok:
        return False, msg
    cfgplane.bram_select(p, 0)                 # M7: USER4 acts on the selected BRAM
    words = [random.Random().getrandbits(18) for _ in range(64)]
    cfgplane.bram_write(p, 0, words)
    back = cfgplane.bram_read(p, 0, 64)
    ctx["rom_words"] = words
    bad = sum(1 for a, b in zip(words, back) if a != b)
    return bad == 0, f"{64 - bad}/64 words read back"


def check_bram_locked(p, ctx):
    """After JSTART, a WRITE is refused (err) - contents are write-protected like UG470's."""
    import cfgplane
    cfgplane.jstart(p)
    cfgplane.bram_scan(p, "load_ptr", 0)
    cfgplane.bram_scan(p, "write", 0x3FFFF)
    st = cfgplane.bram_scan(p, "nop")
    return bool(st["err"] and st["gwe"]), f"err={st['err']} gwe={st['gwe']}"


def check_bram_rom(p, ctx):
    """BRAM as a ROM through the fabric: INTEST SW1..0 = address, LD2..0 = mem[address][2:0]."""
    import fpga
    words = ctx.get("rom_words")
    if not words:
        return False, "needs bram-init first"
    got = [fpga.intest_sweep(p, [v])[0] for v in range(4)]
    exp = [w & 7 for w in words[:4]]
    fpga.go_live(p)
    # (the first version formatted with '%03b' - not a valid %-format in Python -
    # so the check crashed after the comparison it was reporting)
    return got == exp, f"LEDs {[f'{g:03b}' for g in got]} contents {[f'{e:03b}' for e in exp]}"


def check_bram_modes(p, ctx):
    """3 configurations x 24 stepped operations: WRITE_FIRST/READ_FIRST/NO_CHANGE and
    DOA/DOB_REG on both ports match model.py cycle by cycle."""
    import random
    import cfgplane
    import model
    from bitstream import FABRIC_CFG_W
    from designs import BRAM_JTAG_VARIANTS, d_bram_jtag
    rng = random.Random()
    idle = {"addr": 0, "di": 0, "we": 0, "en": 0, "rst": 0, "regce": 0}
    cfgplane.user1(p, 0)
    total = bad = 0
    for name, v in BRAM_JTAG_VARIANTS:
        ok, msg = cfgplane.load(p, d_bram_jtag(**v).build().to_int(), FABRIC_CFG_W, start=False)
        if not ok:
            return False, f"{name}: {msg}"
        cfg = {"wmode_a": model.WRITE_MODES[v["wmode_a"]], "wmode_b": model.WRITE_MODES[v["wmode_b"]],
               "reg_a": int(v["reg_a"]), "reg_b": int(v["reg_b"])}
        bm = model.Bram()
        bm.clock(cfg, {"a": idle, "b": idle}, gsr=1)
        pre = [rng.getrandbits(18) for _ in range(8)]
        cfgplane.bram_write(p, 0, pre)
        for a, w in enumerate(pre):
            bm.init(True, a, w)
        cfgplane.jstart(p)
        for a, b in model.bram_random_ops(rng, 24):
            cfgplane.bram_scan(p, "drive", model.pins_to_drive(a, b))
            cfgplane.step(p)
            st = cfgplane.bram_scan(p, "nop")
            bm.clock(cfg, {"a": a, "b": b}, gce=1)
            total += 1
            if st["do_a"] != bm.do("a", cfg) or st["do_b"] != bm.do("b", cfg):
                bad += 1
    return bad == 0, f"{total - bad}/{total} stepped operations match model.py"


def check_bram_rom_live(p, ctx):
    """Leave the BRAM ROM running for the switch/LED check (contents 0b001,0b010,0b100,0b111)."""
    import cfgplane
    import fpga
    from bitstream import FABRIC_CFG_W
    from designs import d_bram_rom
    ok, msg = cfgplane.load(p, d_bram_rom().build().to_int(), FABRIC_CFG_W, start=False)
    if not ok:
        return False, msg
    cfgplane.bram_write(p, 0, [0b001, 0b010, 0b100, 0b111])
    cfgplane.jstart(p)
    fpga.go_live(p)
    return True, "SW1..0 = 00/01/10/11 should light LD0 / LD1 / LD2 / all three"


# --- M6: the DSP tile --------------------------------------------------------------

_DSP_ZERO = None


def _dsp_zero():
    import model
    return {"a": 0, "b": 0, "c": 0, "d": 0, **{n: 0 for n in model.DSP_CTRL_NAMES}}


def check_dsp_modes(p, ctx):
    """3 configuration pairs x 20 stepped operations through both cascaded slices:
    M, M+C, P+M, PCIN>>17+M, pre-adder D+A / D-A, every register stage."""
    import random
    import cfgplane
    import model
    from bitstream import FABRIC_CFG_W
    from designs import DSP_JTAG_VARIANTS, d_dsp_jtag
    M48 = (1 << 48) - 1
    rng = random.Random()
    cfgplane.user1(p, 0)
    total = bad = 0
    first = ""
    for name, c0, c1 in DSP_JTAG_VARIANTS:
        bs = d_dsp_jtag(c0, c1).build()
        ok, msg = cfgplane.load(p, bs.to_int(), FABRIC_CFG_W, start=True)
        if not ok:
            return False, f"{name}: {msg}"
        cfgs = model.Fabric(bs).dsp_cfgs
        slices = [model.Dsp(), model.Dsp()]
        for p0, p1 in model.dsp_random_ops(rng, 20):
            cfgplane.dsp_scan(p, model.dsp_pins_to_drive(p0, p1))
            cfgplane.step(p)
            st = cfgplane.dsp_scan(p)
            model.dsp_cascade_clock(slices, cfgs, (p0, p1))
            e0, e1 = model.dsp_cascade_p(slices, cfgs, (p0, p1))
            total += 1
            if st["p0"] != e0 & M48 or st["p1"] != e1 & M48:
                bad += 1
                first = first or f"{name}: P0 {st['p0']:012x}/{e0 & M48:012x} P1 {st['p1']:012x}/{e1 & M48:012x}"
    return bad == 0, f"{total - bad}/{total} stepped operations match model.py " + (f"(first: {first})" if first else "")


def check_dsp_mult(p, ctx):
    """Combinational multiplier through the fabric: INTEST {SW1,SW0} = 0..3 times B = 3 on LD2..0."""
    import cfgplane
    import fpga
    import model
    from designs import d_dsp_mult_sw
    if not fpga.load_bitstream(p, d_dsp_mult_sw().build(), verbose=False):
        return False, "load failed"
    cfgplane.dsp_scan(p, model.dsp_pins_to_drive({**_dsp_zero(), "b": 3}, _dsp_zero()))
    got = [fpga.intest_sweep(p, [v])[0] for v in range(4)]
    exp = [(v * 3) & 7 for v in range(4)]
    fpga.go_live(p)
    return got == exp, f"LEDs {[f'{g:03b}' for g in got]} expected {[f'{e:03b}' for e in exp]}"


def check_dsp_accum(p, ctx):
    """Accumulator on the free-running clock, div 16: P grows 7.45 per second with A*B = 1."""
    import time
    import cfgplane
    import fpga
    import model
    from designs import d_dsp_accum
    if not fpga.load_bitstream(p, d_dsp_accum(16).build(), verbose=False):
        return False, "load failed"
    cfgplane.dsp_scan(p, model.dsp_pins_to_drive({**_dsp_zero(), "a": 1, "b": 1}, _dsp_zero()))
    t0 = time.time()
    p0 = cfgplane.dsp_scan(p)["p0"]
    time.sleep(3.0)
    p1 = cfgplane.dsp_scan(p)["p0"]
    dt = time.time() - t0
    rate = (p1 - p0) / dt
    return 6.0 <= rate <= 9.0, f"P0 {p0} -> {p1} in {dt:.2f} s = {rate:.2f}/s (expected 7.45)"


def check_dsp_accum_live(p, ctx):
    """Leave the DSP accumulator blinking the LEDs."""
    import cfgplane
    import fpga
    import model
    from designs import d_dsp_accum
    if not fpga.load_bitstream(p, d_dsp_accum(16).build(), verbose=False):
        return False, "load failed"
    cfgplane.dsp_scan(p, model.dsp_pins_to_drive({**_dsp_zero(), "a": 1, "b": 1}, _dsp_zero()))
    fpga.go_live(p)
    return True, "running: LD0 ~3.7 Hz, LD1 ~1.9 Hz, LD2 ~0.93 Hz (check by eye)"


# --- M7: the fabric generated from VPR's rr graph ---------------------------------------

PIPE_LIVE_WORDS = [3, 6, 4, 5]          # (w * 3) & 7 = 001, 010, 100, 111


def check_bram_select(p, ctx):
    """Two BRAMs behind one USER4 register: SELECT, write different words into each,
    both read back their own (the other's writes never land)."""
    import random
    import cfgplane
    from bitstream import FABRIC_CFG_W
    from designs import d_pipeline
    ok, msg = cfgplane.load(p, d_pipeline().build().to_int(), FABRIC_CFG_W, start=False)
    if not ok:
        return False, msg
    rng = random.Random()
    words = {b: [rng.getrandbits(18) for _ in range(16)] for b in (0, 1)}
    for b in (0, 1):
        cfgplane.bram_select(p, b)
        cfgplane.bram_write(p, 0, words[b])
    bad = []
    for b in (1, 0):
        cfgplane.bram_select(p, b)
        back = cfgplane.bram_read(p, 0, 16)
        bad += [f"bram{b}[{a}]" for a, (w, g) in enumerate(zip(words[b], back)) if w != g]
    st = cfgplane.bram_scan(p, "select", 9)
    st = cfgplane.bram_scan(p, "nop")
    ok = not bad and st["target"] == 0
    return ok, (f"16 words each read back from bram0 and bram1; SELECT 9 ignored (target {st['target']})"
                if ok else f"wrong: {bad[:6]} target {st['target']}")


def check_pipeline(p, ctx):
    """pad -> LUT -> FF -> BRAM -> DSP -> pad through generated routing: INTEST SW1..0 addresses
    bram1 through two CLB flip-flops, dsp0 multiplies by 3 into PREG, LD2..0 = (mem*3)[2:0]."""
    import random
    import cfgplane
    import fpga
    from bitstream import FABRIC_CFG_W
    from designs import PIPELINE_BRAM, d_pipeline
    ok, msg = cfgplane.load(p, d_pipeline().build().to_int(), FABRIC_CFG_W, start=False)
    if not ok:
        return False, msg
    words = [random.Random().getrandbits(18) for _ in range(4)]
    cfgplane.bram_select(p, PIPELINE_BRAM)
    cfgplane.bram_write(p, 0, words)
    cfgplane.jstart(p)
    vs = [0, 1, 2, 3, 1, 0, 3, 2]
    got = fpga.intest_sweep(p, vs)
    exp = [(words[v] * 3) & 7 for v in vs]
    fpga.go_live(p)
    return got == exp, f"LEDs {[f'{g:03b}' for g in got]} model {[f'{e:03b}' for e in exp]}"


def check_counter8(p, ctx):
    """8-bit JTAG-stepped counter up the full height of column 8: seven carry directs,
    +n+5 per n-bit CAPTURE scan, through 255 -> 0."""
    import cfgplane
    import fpga
    from designs import FULL_COL_BITS, FULL_COL_X, d_counter
    if not fpga.load_bitstream(p, d_counter("jtag", x=FULL_COL_X, bits=FULL_COL_BITS).build(), verbose=False):
        return False, "load failed"
    n = _capture_w()
    mod = 1 << FULL_COL_BITS
    cfgplane.user1(p, 0b101)
    cfgplane.ir(p, "CAPTURE")
    vals = [_counter_value(p.shift_dr(n, 0), x=FULL_COL_X, bits=FULL_COL_BITS) for _ in range(12)]
    cfgplane.user1(p, 0)
    diffs = [(b - a) % mod for a, b in zip(vals, vals[1:])]
    want = (n + 5) % mod
    return all(d == want for d in diffs), f"counts {vals} (steps {diffs}, want {want} each)"


def check_pipeline_live(p, ctx):
    """Leave the pipeline running on the real switches."""
    import cfgplane
    import fpga
    from bitstream import FABRIC_CFG_W
    from designs import PIPELINE_BRAM, d_pipeline
    ok, msg = cfgplane.load(p, d_pipeline().build().to_int(), FABRIC_CFG_W, start=False)
    if not ok:
        return False, msg
    cfgplane.bram_select(p, PIPELINE_BRAM)
    cfgplane.bram_write(p, 0, PIPE_LIVE_WORDS)
    cfgplane.jstart(p)
    fpga.go_live(p)
    return True, "SW1..0 = 00/01/10/11 should light LD0 / LD1 / LD2 / all three"


# --- M8: yosys-synthesised designs on the M7 fabric (no rebuild) ---------------------------

SYNTH_HW_CYCLES = 64


def _synth_check(top):
    def check(p, ctx):
        """yosys -> netlist == source -> placed/routed; on the board, every user clock
        (INTEST autostep) the LEDs equal the SOURCE Verilog's."""
        import cfgplane
        import fpga
        import place
        from bitstream import FABRIC_CFG_W
        d, bs, contents, tr = place.flow(top)
        ok, msg = cfgplane.load(p, bs.to_int(), FABRIC_CFG_W, start=False)
        if not ok:
            return False, msg
        for b, words in sorted(contents.items()):
            last = max((a for a, w in enumerate(words) if w), default=-1)
            if last >= 0:
                cfgplane.bram_select(p, b)
                cfgplane.bram_write(p, 0, words[:last + 1])
        cfgplane.jstart(p)
        cfgplane.user1(p, 0x10)                  # autostep: one user clock per INTEST scan
        cfgplane.ir(p, "INTEST")
        trace = tr["trace"][:SYNTH_HW_CYCLES]
        bad = []
        # scan k applies inputs k and clocks; scan k+1 captures the LEDs after that edge
        p.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(trace[0][0]))
        for k in range(len(trace)):
            nxt = trace[k + 1][0] if k + 1 < len(trace) else trace[k][0]
            got = fpga.bsr_leds(p.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(nxt)))
            if got != trace[k][2]:
                bad.append(f"clock {k}: {got:03b} vs {trace[k][2]:03b}")
        cfgplane.user1(p, 0)
        fpga.go_live(p)
        return not bad, (f"{len(d.cells)} CLBs, {len(trace)} clocks match the source Verilog"
                         if not bad else f"{len(bad)} wrong, first {bad[:3]}")
    check.__name__ = f"check_synth_{top}"
    return check


REGRESSION = [
    ("idcode", check_idcode),
    ("bypass", check_bypass),
    ("selftest", check_selftest),
]

# The regression depends on what the top can do: the fabric self-test needs the
# 4x4 fabric, which cfg_test_top (M2) does not contain.
REGRESSION_BY_TOP = {
    "bob_top": REGRESSION,
    "fpga4x4_top": REGRESSION,
    "cfg_test_top": [("idcode", check_idcode), ("bypass", check_bypass)],
}

# What each milestone adds on top of the regression. Checks that need hands on
# the board or on the Vivado machine live in docs/hwtest/<M>.md (--manual).
MILESTONE = {
    "M0": [("showcase-live", check_showcase_live)],
    # M1: no RTL change. selftest (regression) now runs on host/bitstream.py
    # driven by device.json, so passing it proves the description is right on
    # silicon; the chain check ties device.json's width to the real register.
    "M1": [("showcase-live", check_showcase_live),
           ("chain-length", check_chain_length)],
    # M2: the configuration plane alone (cfg_test_top). docs/bitstream-format.md
    "M2": [("usercode", check_usercode),
           ("ir-capture", check_ir_capture),
           ("chain-length", check_cfg_chain_length),
           ("load-readback", check_load_readback),
           ("crc-reject", check_crc_reject),
           ("len-reject", check_len_reject),
           ("startup", check_startup),
           ("capture", check_capture),
           ("jprogram", check_jprogram)],
    # M3: complete 4x4 fabric on the configuration plane. Regression (idcode,
    # bypass, selftest = all 11 designs) runs first; these follow.
    "M3": [("usercode", check_usercode),
           ("chain-length", check_chain_length),
           ("ir-status", check_fabric_ir_status),
           ("crc-reject-live", check_crc_reject_live),
           ("gts", check_gts),
           ("gsr-gwe", check_gsr_gwe),
           ("capture-user1", check_capture_user1),
           ("jprogram", check_fabric_jprogram),
           ("showcase-live", check_showcase_live)],     # last: leaves showcase running
    # M4: complete fabric + user clock, routed CE/SR, LUT K parameter (K=6 on the
    # board). Regression, then every M3 check, then the new ones.
    "M4": [("usercode", check_usercode),
           ("chain-length", check_chain_length),
           ("ir-status", check_fabric_ir_status),
           ("crc-reject-live", check_crc_reject_live),
           ("gts", check_gts),
           ("gsr-gwe", check_gsr_gwe),
           ("capture-user1", check_capture_user1),
           ("jprogram", check_fabric_jprogram),
           ("showcase-live", check_showcase_live),
           ("ce-sr", check_ce_sr),
           ("counter-step", check_counter_step),
           ("counter-run", check_counter_run),
           ("blinky", check_blinky)],                   # last: leaves the counter blinking
    # M5: + BRAM tile. Everything M4 checked (bar the blinky hand-off), then BRAM.
    "M5": [("usercode", check_usercode),
           ("chain-length", check_chain_length),
           ("ir-status", check_fabric_ir_status),
           ("crc-reject-live", check_crc_reject_live),
           ("gts", check_gts),
           ("gsr-gwe", check_gsr_gwe),
           ("capture-user1", check_capture_user1),
           ("jprogram", check_fabric_jprogram),
           ("showcase-live", check_showcase_live),
           ("ce-sr", check_ce_sr),
           ("counter-step", check_counter_step),
           ("counter-run", check_counter_run),
           ("bram-init", check_bram_init),
           ("bram-locked", check_bram_locked),
           ("bram-rom", check_bram_rom),
           ("bram-modes", check_bram_modes),
           ("bram-rom-live", check_bram_rom_live)],     # last: leaves the ROM on the switches
    # M6: + DSP tile. Everything M5 checked, then DSP.
    "M6": [("usercode", check_usercode),
           ("chain-length", check_chain_length),
           ("ir-status", check_fabric_ir_status),
           ("crc-reject-live", check_crc_reject_live),
           ("gts", check_gts),
           ("gsr-gwe", check_gsr_gwe),
           ("capture-user1", check_capture_user1),
           ("jprogram", check_fabric_jprogram),
           ("showcase-live", check_showcase_live),
           ("ce-sr", check_ce_sr),
           ("counter-step", check_counter_step),
           ("counter-run", check_counter_run),
           ("bram-init", check_bram_init),
           ("bram-locked", check_bram_locked),
           ("bram-rom", check_bram_rom),
           ("bram-modes", check_bram_modes),
           ("dsp-modes", check_dsp_modes),
           ("dsp-mult", check_dsp_mult),
           ("dsp-accum", check_dsp_accum),
           ("dsp-accum-live", check_dsp_accum_live)],   # last: leaves the accumulator blinking
    # M7: the heterogeneous fabric generated from VPR's rr graph (bob_top). Every
    # earlier check re-run on it (selftest in the regression now includes 'cross'),
    # then the new ones.
    "M7": [("usercode", check_usercode),
           ("chain-length", check_chain_length),
           ("ir-status", check_fabric_ir_status),
           ("crc-reject-live", check_crc_reject_live),
           ("gts", check_gts),
           ("gsr-gwe", check_gsr_gwe),
           ("capture-user1", check_capture_user1),
           ("jprogram", check_fabric_jprogram),
           ("showcase-live", check_showcase_live),
           ("ce-sr", check_ce_sr),
           ("counter-step", check_counter_step),
           ("counter-run", check_counter_run),
           ("bram-init", check_bram_init),
           ("bram-locked", check_bram_locked),
           ("bram-rom", check_bram_rom),
           ("bram-modes", check_bram_modes),
           ("dsp-modes", check_dsp_modes),
           ("dsp-mult", check_dsp_mult),
           ("dsp-accum", check_dsp_accum),
           ("bram-select", check_bram_select),
           ("pipeline", check_pipeline),
           ("counter8", check_counter8),
           ("pipeline-live", check_pipeline_live)],     # last: leaves the pipeline on the switches
    # M8: no RTL change - the M7 bitstream stays in the PL. Every example goes
    # yosys -> bob cells -> netlist == source -> placed/routed -> board == source.
    "M8": [("chain-length", check_chain_length),
           ("synth-gates", _synth_check("gates")),
           ("synth-adder", _synth_check("adder")),
           ("synth-counter", _synth_check("counter")),
           ("synth-blinky", _synth_check("blinky")),
           ("synth-ram", _synth_check("ram")),
           ("synth-mult", _synth_check("mult"))],
}


# --- runner ------------------------------------------------------------------

def manual_steps(milestone):
    path = os.path.join(ROOT, "docs", "hwtest", f"{milestone}.md")
    if not os.path.exists(path):
        return []
    steps = []
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if ln.startswith("- [ ]"):
                steps.append(ln[5:].strip())
    return steps


def log(milestone, rows, cfg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a") as fh:
        fh.write(f"{stamp}  {milestone}  tag={cfg.get('tag')} top={cfg.get('top')}\n")
        for name, ok, detail in rows:
            fh.write(f"    {'PASS' if ok else 'FAIL'}  {name:16s} {detail}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--milestone", required=True)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--manual", action="store_true")
    ap.add_argument("--freq", type=int, default=100, help="TCK frequency in kHz")
    args = ap.parse_args()

    ms = args.milestone.upper()
    if ms not in MILESTONE:
        sys.exit(f"no checks defined for {ms}; known: {', '.join(MILESTONE)}")
    cfg = buildcfg.read_cfg()
    if cfg.get("tag") != ms:
        print(f"note: hw/build.cfg is tagged {cfg.get('tag')}, testing {ms}")

    checks = REGRESSION_BY_TOP.get(cfg.get("top"), REGRESSION) + MILESTONE[ms]
    if args.list:
        print(f"{ms} (build.cfg tag {cfg.get('tag')}, top {cfg.get('top')}):")
        for name, fn in checks:
            print(f"  auto    {name:16s} {(fn.__doc__ or '').strip().splitlines()[0] if fn.__doc__ else ''}")
        for step in manual_steps(ms):
            print(f"  manual  {step}")
        return 0

    from dirtyjtag import Probe
    p = Probe(freq_khz=args.freq)
    print(f"probe: {p.info()}\n")

    ctx = {"cfg": cfg}
    rows = []
    for name, fn in checks:
        try:
            ok, detail = fn(p, ctx)
        except Exception as e:                      # a crash is a failure, not an abort
            ok, detail = False, f"{type(e).__name__}: {e}"
        rows.append((name, ok, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:16s} {detail}")
        if name == "idcode" and not ok:
            print("\n  wrong bitstream in the PL - stopping. Program this bundle first:")
            print("    vivado -mode batch -source hw/scripts/build.tcl -tclargs all")
            break

    if args.manual:
        print()
        for step in manual_steps(ms):
            ans = input(f"  [manual] {step}\n           ok? [y/n] ").strip().lower()
            rows.append((f"manual: {step[:40]}", ans == "y", "by hand"))

    log(ms, rows, cfg)
    ok = all(r[1] for r in rows)
    print(f"\n=== {ms} HARDWARE {'PASSED' if ok else 'FAILED'} ===   (logged to {os.path.relpath(LOG, ROOT)})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
