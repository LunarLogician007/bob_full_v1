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


def _synth_check(top, vpr=False):
    def check(p, ctx):
        """On the board, every user clock, the LEDs equal the source Verilog's.

        yosys -> netlist == source -> placed/routed (M8: place.py; vpr=True, M9: the
        committed VPR result -> FASM -> chain), loaded, clocked by INTEST autostep."""
        import cfgplane
        import fpga
        import place
        from bitstream import FABRIC_CFG_W
        if vpr:
            import fasm_from_vpr
            bs, contents, tr = fasm_from_vpr.flow(top)
            what = "VPR-routed"
        else:
            d, bs, contents, tr = place.flow(top)
            what = f"{len(d.cells)} CLBs"
        ok, msg = cfgplane.load(p, bs.to_int(), FABRIC_CFG_W, start=False)
        if not ok:
            return False, msg
        import cli
        cli.write_brams(p, contents)
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
        return not bad, (f"{what}, {len(trace)} clocks match the source Verilog"
                         if not bad else f"{len(bad)} wrong, first {bad[:3]}")
    check.__name__ = f"check_{'vpr' if vpr else 'synth'}_{top}"
    return check


# --- M10: bob build / bob load, golden LEDs and CAPTURE ------------------------------------

def _bob_check(name, pnr="vpr"):
    def check(p, ctx):
        """`bob build` -> .bit -> `bob load`; every user clock the LEDs equal the source's
        and CAPTURE (every CLB flip-flop) equals the golden netlist's registers.

        The chain read back by CFG_OUT is decoded to FASM and must equal the .bit's."""
        import bitgen
        import cfgplane
        import cli
        import fasm_from_vpr
        import fpga
        import vpr_run
        from bitstream import FABRIC_CFG_W, NCLB
        top, pcf = vpr_run.VARIANTS.get(name, (name, None))
        suffix = "_py" if pnr == "python" else ""
        path, word, contents, tr, work = cli.build([os.path.join(ROOT, "examples", f"{top}.v")], top, pcf,
                                                   os.path.join(ROOT, "build", "bit", f"{name}{suffix}.bit"),
                                                   name=name, log=lambda *_: None, pnr=pnr)
        ok, msg = cli.load(p, path, start=False, log=lambda *_: None)
        if not ok:
            return False, msg
        back = bitgen.features_from_word(cfgplane.cfg_out(p, FABRIC_CFG_W))
        if back != bitgen.features_from_word(bitgen.read_bit(path)["word"]):
            return False, "CFG_OUT readback decodes to different FASM than the .bit"
        cfgplane.jstart(p)
        cmap = fasm_from_vpr.capture_map(name, work)
        pos = {b: i for i, b in enumerate(tr["nets"])}
        cfgplane.user1(p, 0x10)                  # autostep: one user clock per INTEST scan
        cfgplane.ir(p, "INTEST")
        trace = tr["trace"][:SYNTH_HW_CYCLES]
        bad, caps = [], 0
        p.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(trace[0][0]))      # inputs 0, clock 0
        for k in range(len(trace)):
            if cmap:                                                 # registers after clock k
                cap = cfgplane.capture(p, NCLB)
                nets = int(tr["nets_after"][k], 16)
                for idx, bit in cmap:
                    want = (nets >> pos[bit]) & 1
                    if (cap >> idx) & 1 != want:
                        bad.append(f"clock {k}: CAPTURE bit {idx} = {(cap >> idx) & 1}, golden n{bit} = {want}")
                caps += 1
                cfgplane.ir(p, "INTEST")
            nxt = trace[k + 1][0] if k + 1 < len(trace) else trace[k][0]
            got = fpga.bsr_leds(p.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(nxt)))
            if got != trace[k][2]:
                bad.append(f"clock {k}: LEDs {got:03b} vs source {trace[k][2]:03b}")
        cfgplane.user1(p, 0)
        fpga.go_live(p)
        return not bad, (f"{msg}; readback == FASM; {len(trace)} clocks LEDs == source, "
                         f"{caps} CAPTUREs x {len(cmap)} registers == golden"
                         if not bad else f"{len(bad)} wrong, first {bad[:3]}")
    check.__name__ = f"check_bob_{name}{'_py' if pnr == 'python' else ''}"
    return check


# --- M11: real designs live on the board (free-running clock, real switches) ------------------

LIVE_DIV = 15                  # 125 MHz / 2**23 = 14.9 Hz: slower than a CAPTURE-SAMPLE-CAPTURE burst
LIVE_SECONDS = 8.0


def _live_build(name, pnr="vpr"):
    import cli
    import vpr_run
    top, pcf = vpr_run.VARIANTS.get(name, (name, None))
    suffix = "_py" if pnr == "python" else ""
    path, word, contents, tr, work = cli.build([os.path.join(ROOT, "examples", f"{top}.v")], top, pcf,
                                               os.path.join(ROOT, "build", "bit", f"{name}{suffix}_run.bit"),
                                               clock="run", div=LIVE_DIV, name=name, log=lambda *_: None, pnr=pnr)
    return path, word, work


def _live_state(p, cmap_idx):
    """CAPTURE, SAMPLE, CAPTURE. -> (sample, capture) when no register changed in
    between, else None"""
    import cfgplane
    import fpga
    from bitstream import NCLB
    c1 = cfgplane.capture(p, NCLB)
    cfgplane.ir(p, "SAMPLE")
    smp = fpga.sample(p)
    c2 = cfgplane.capture(p, NCLB)
    mask = sum(1 << i for i in cmap_idx)
    return (smp, c1) if (c1 & mask) == (c2 & mask) else None


LIVE_TIMEOUT = 90.0            # interactive: give up on the goals after this long


def _interactive():
    return sys.stdin.isatty() and sys.stdout.isatty()


def _sw(k):
    return (f"SW1..0 = {k:02b}", lambda i, leds, h: (i & 3) == k)


def _btn(k, extra="", cond=lambda i, leds: True):
    return (f"BTN{k} pressed{extra}", lambda i, leds, h: (i >> (2 + k)) & 1 and cond(i, leds))


def _led_values(n):
    def seen(i, leds, h):
        h.setdefault("leds", set()).add(leds)
        return len(h["leds"]) >= n
    return (f"LEDs show {n} different values", seen)


def _ld2_toggles_off():
    def goal(i, leds, h):
        if leds & 4:
            h["ld2_was_on"] = True
        return h.get("ld2_was_on") and not leds & 4
    return ("BTN3 again turns LD2 back off", goal)


# What each live design asks of the person at the board. "try" rows are inputs to hold;
# the LEDs they should give are computed from model.py (inputs held for a few clocks).
LIVE_GUIDE = {
    "switches": {
        "about": "LD0 = SW0 xor SW1.  LD1 = BTN0, or BTN1 while SW0 is up.  LD2 toggles once per BTN3 press.",
        "try": [0b000000, 0b000001, 0b000011, 0b000100, 0b001001],
        "goals": [_sw(0), _sw(1), _sw(2), _sw(3),
                  _btn(0, " (LD1 on)", lambda i, leds: leds & 2),
                  _btn(1, " with SW0 up, BTN0 released (LD1 on)",
                       lambda i, leds: i & 1 and not i & 4 and leds & 2),
                  ("BTN3 press turns LD2 on", lambda i, leds, h: leds & 4),
                  _ld2_toggles_off()],
        "note": "LD2 is a register: each press flips it; holding BTN3 does nothing more.",
    },
    "fir": {
        "about": "x = SW1..0 each clock; y = x[n]*h0 + x[n-1]*h1, h0 = {BTN3,BTN2,1}, h1 = {BTN2,BTN3,1}; "
                 "LD2..0 = y[4:2]. Hold inputs for a moment: the delay line needs 2 clocks.",
        "try": [0b000011, 0b000001, 0b110011, 0b100010, 0b010011],
        "goals": [_sw(0), _sw(1), _sw(2), _sw(3), _btn(2, " (held)"), _btn(3, " (held)"),
                  ("BTN2 and BTN3 held together", lambda i, leds, h: (i >> 4) & 3 == 3), _led_values(3)],
    },
    "mult": {
        "about": "a = {BTN1,BTN0,SW1,SW0} and b = {BTN3,BTN2,SW1,SW0} are registered; p = a*b next clock; "
                 "LD2..0 = p[7:5]. The LEDs light only for large products: hold several buttons.",
        "try": [0b000011, 0b111111, 0b101111, 0b011011],
        "goals": [_sw(0), _sw(1), _sw(2), _sw(3), _btn(0), _btn(1), _btn(2), _btn(3), _led_values(3)],
    },
    "blinky": {
        "about": "a free-running 8-bit counter, LD2..0 = q[7:5]; nothing to press.",
        "try": [],
        "goals": [("16 counter states seen", lambda i, leds, h: len(h.get("states", ())) >= 16)],
        "auto": True,
    },
}


def _fmt_in(i):
    return f"SW1..0={i & 3:02b} BTN3..0={(i >> 2) & 15:04b}"


def _live_guide(name, word):
    import model
    from bitstream import Bitstream
    g = LIVE_GUIDE[name]
    print(f"\n           --- live-{name} ---")
    print(f"           {g['about']}")
    for v in g["try"]:
        m = model.Fabric(Bitstream(word))
        m.clock(gsr=1)
        for _ in range(4):
            m.clock(pad_i=v)
        print(f"             hold {_fmt_in(v)}  ->  LD2..0 = {m.outputs(v):03b}")
    if g.get("note"):
        print(f"           {g['note']}")
    if not g.get("auto"):
        print("           Goals (ticked off as the board shows them):")
        for label, _fn in g["goals"]:
            print(f"             [ ] {label}")


def _live_check(name, pnr="vpr"):
    def check(p, ctx):
        """Live on the real switches (free-running clock): whenever the registers are stable
        across CAPTURE-SAMPLE-CAPTURE, model.py given those registers and the sampled pins
        reproduces the sampled LEDs, until every goal of LIVE_GUIDE has been seen on the
        board (interactive), then CFG_OUT readback while running == .bit."""
        import time
        import cfgplane
        import cli
        import fasm_from_vpr
        import fpga
        import model
        from bitstream import BLOCKS, CLBS, FABRIC_CFG_W, Bitstream
        guide = LIVE_GUIDE[name]
        path, word, work = _live_build(name, pnr)
        ok, msg = cli.load(p, path, log=lambda *_: None)
        if not ok:
            return False, msg
        idx = [i for i, _bit in fasm_from_vpr.capture_map(name, work)]
        interactive = _interactive() and not guide.get("auto")
        _live_guide(name, word)
        if interactive:
            input(f"           {name} is running. Press Enter, then work through the goals "
                  f"(up to {LIVE_TIMEOUT:.0f} s) ")
        limit = LIVE_TIMEOUT if (interactive or guide.get("auto")) else LIVE_SECONDS
        goals = guide["goals"]
        done = [False] * len(goals)
        hist = {"states": set()}
        seen_in, samples, skipped, bad = set(), 0, 0, []
        t0 = time.time()
        while time.time() - t0 < limit:
            got = _live_state(p, idx)
            if got is None:
                skipped += 1
                continue
            smp, cap = got
            m = model.Fabric(Bitstream(word))
            for i in idx:
                b = BLOCKS[CLBS[i]]
                m.q[(b["x"], b["y"])] = (cap >> i) & 1
            want = m.outputs(smp["i"])
            samples += 1
            seen_in.add(smp["i"])
            hist["states"].add(sum(((cap >> i) & 1) << k for k, i in enumerate(idx)))
            if want != smp["leds"]:
                bad.append(f"{_fmt_in(smp['i'])} registers {cap:04X}: LEDs {smp['leds']:03b}, model {want:03b}")
            else:
                for k, (_label, fn) in enumerate(goals):
                    if not done[k] and fn(smp["i"], smp["leds"], hist):
                        done[k] = True
            if interactive:
                mark = "ok" if want == smp["leds"] else "MISMATCH"
                print(f"\r           {_fmt_in(smp['i'])}  LEDs {smp['leds']:03b}  model {want:03b} {mark:8s} "
                      f"goals {sum(done)}/{len(goals)}  {time.time() - t0:4.0f} s ", end="", flush=True)
                if bad:
                    break
            if (interactive or guide.get("auto")) and all(done):
                break
        if interactive:
            print()
            for (label, _fn), d in zip(goals, done):
                print(f"             [{'x' if d else ' '}] {label}")
        back = cfgplane.cfg_out(p, FABRIC_CFG_W)
        fpga.go_live(p)
        if back != word:
            bad.append("CFG_OUT readback while running differs from the .bit")
        if samples == 0:
            return False, f"no stable sample in {limit:.0f} s ({skipped} bursts saw registers move)"
        stats = (f"{samples} live samples LEDs == model(registers, pins), {len(seen_in)} input vectors, "
                 f"{len(hist['states'])} register states, {skipped} bursts skipped (moving)")
        if bad:
            return False, f"{len(bad)} wrong, first {bad[:3]}"
        missing = [label for (label, _fn), d in zip(goals, done) if not d]
        if (interactive or guide.get("auto")) and missing:
            return False, f"{stats}; goals not reached in {limit:.0f} s: {missing}"
        how = ("all goals reached" if (interactive or guide.get("auto"))
               else "goals not checked (not a terminal: run `make hwtest` interactively)")
        return True, f"{stats}; {how}; readback while running == .bit"
    check.__name__ = f"check_live_{name}{'_py' if pnr == 'python' else ''}"
    return check


def check_blinky_rate(p, ctx):
    """blinky on the free-running clock counts at 125 MHz / 2**(LIVE_DIV+8) (CAPTURE of its
    8 register bits over about 4 s)."""
    import json
    import time
    import cfgplane
    import cli
    import fasm_from_vpr
    import fpga
    from bitstream import DIV_MIN_SHIFT, NCLB
    path, _word, _work = _live_build("blinky")
    ok, msg = cli.load(p, path, log=lambda *_: None)
    if not ok:
        return False, msg
    mod = json.load(open(os.path.join(ROOT, "build", "synth", "blinky", "blinky.json")))["modules"]["blinky"]
    qbits = mod["netnames"]["q"]["bits"]
    where = {bit: i for i, bit in fasm_from_vpr.capture_map("blinky")}

    def count():
        c = cfgplane.capture(p, NCLB)
        return sum(((c >> where[b]) & 1) << k for k, b in enumerate(qbits))

    t0, last, total = time.time(), count(), 0
    for _ in range(8):
        time.sleep(0.5)
        v = count()
        total += (v - last) % 256
        last = v
    dt = time.time() - t0
    rate, want = total / dt, 125e6 / 2 ** (LIVE_DIV + DIV_MIN_SHIFT)
    fpga.go_live(p)
    return abs(rate - want) <= 0.1 * want, f"{total} counts in {dt:.2f} s = {rate:.2f} Hz (expected {want:.2f})"


def check_ram_readback(p, ctx):
    """ram.v written through the design (INTEST, 64 clocks of the source trace), then
    stopped with JPROGRAM (GWE = 0) and its BRAM read back over USER4 == the memory
    model.py computed for the same clocks; the chain read back == the .bit."""
    import cfgplane
    import cli
    import fpga
    import model
    from bitstream import FABRIC_CFG_W, Bitstream
    path, word, contents, tr, _work = cli.build([os.path.join(ROOT, "examples", "ram.v")], "ram", None,
                                         os.path.join(ROOT, "build", "bit", "ram.bit"), log=lambda *_: None)
    ok, msg = cli.load(p, path, log=lambda *_: None)
    if not ok:
        return False, msg
    trace = tr["trace"][:SYNTH_HW_CYCLES]
    m = model.Fabric(Bitstream(word))
    m.clock(gsr=1)
    for b, words in contents.items():
        m.brams[b].mem = list(words)
    cfgplane.user1(p, 0x10)
    cfgplane.ir(p, "INTEST")
    p.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(trace[0][0]))
    m.clock(pad_i=trace[0][0])
    for k in range(1, len(trace)):
        p.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(trace[k][0]))
        m.clock(pad_i=trace[k][0])
    cfgplane.user1(p, 0)
    back = cfgplane.cfg_out(p, FABRIC_CFG_W)
    cfgplane.jprogram(p)                                   # stop: GWE = 0, BRAM reads allowed
    bad = []
    for b in sorted(contents):                             # the BRAMs the design uses
        cfgplane.bram_select(p, b)
        got = cfgplane.bram_read(p, 0, 16)
        want = m.brams[b].mem[:16]
        if got != want:
            bad.append(f"bram{b}[0..15] = {got}, model {want}")
    fpga.go_live(p)
    if back != word:
        bad.append("CFG_OUT readback differs from the .bit")
    writes = sum(1 for v, _b, _a in trace if (v >> 2) & 1)
    return not bad, (f"{len(trace)} clocks ({writes} with BTN0 write), bram0[0..15] = "
                     f"{m.brams[0].mem[:16]} read back after JPROGRAM == model (all 1024 words were "
                     f"written at load, so no earlier design's words remain); chain readback == .bit"
                     if not bad else "; ".join(bad))


# --- M13: frame configuration (UG470-style packets) next to the chain -------------------

def _sweep_ok(p, bs, key):
    import fpga
    from bitstream import simulate
    from designs import BY_KEY
    vs = list(BY_KEY[key][2])
    got = fpga.intest_sweep(p, vs)
    fpga.go_live(p)
    return [v for v, g in zip(vs, got) if g != simulate(bs, v)], len(vs)


def check_frames_load(p, ctx):
    """showcase through the frame path: STAT (START accepted), FDRO readback == chain word,
    CHAIN_OUT readback of the same memory == chain word, JSTART -> DONE, LEDs == model."""
    import cfgplane
    from bitstream import FABRIC_CFG_W
    show = _fabric_bs("showcase")
    word = show.to_int()
    ok, msg = cfgplane.load_frames(p, word, start=False)
    if not ok:
        return False, msg
    chain = cfgplane.cfg_out(p, FABRIC_CFG_W)
    cfgplane.jstart(p)
    done = cfgplane.status(p)["done"]
    bad, n = _sweep_ok(p, show, "showcase")
    good = ok and chain == word and done and not bad
    return good, f"{msg}; CHAIN_OUT == word: {chain == word}; DONE={done}; {n - len(bad)}/{n} vectors == model"


def check_frames_crc_reject(p, ctx):
    """one flipped frame-data bit: STAT CRC_ERROR, START refused, JSTART cannot bring DONE up,
    IR capture shows INIT_B low."""
    import cfgplane
    import packets
    word = _fabric_bs("xor6").to_int()
    s = packets.load_stream(word)
    s[s.index(packets.type2(packets.OP_WRITE, packets.NFRAMES * packets.FW)) + 1 + 40] ^= 1 << 3
    cfgplane.jprogram(p)
    cfgplane.frames_send(p, s)
    st = cfgplane.frames_stat(p)
    cfgplane.jstart(p)
    done = cfgplane.status(p)["done"]
    irst = cfgplane.ir_status(p)
    ok = st["CRC_ERROR"] and not st["START_OK"] and not done and not irst["init_b"]
    return ok, f"CRC_ERROR={st['CRC_ERROR']} START_OK={st['START_OK']} DONE={done} INIT_B={irst['init_b']}"


def check_frames_idcode_reject(p, ctx):
    """a stream for another IDCODE: STAT ID_ERROR, no frame written (CHAIN_OUT reads zeros)."""
    import cfgplane
    import packets
    from bitstream import FABRIC_CFG_W
    word = _fabric_bs("showcase").to_int()
    cfgplane.jprogram(p)
    cfgplane.frames_send(p, packets.load_stream(word, idcode=packets.device_idcode() ^ 0x10000000))
    st = cfgplane.frames_stat(p)
    empty = cfgplane.cfg_out(p, FABRIC_CFG_W) == 0
    return st["ID_ERROR"] and empty, f"ID_ERROR={st['ID_ERROR']} memory empty={empty}"


def check_frames_live_refused(p, ctx):
    """while showcase runs (GWE = 1) a complete frame load of another design is refused
    (WR_ERROR) and a good chain for it does not commit either; showcase keeps working."""
    import cfgplane
    import fpga
    import packets
    from bitstream import FABRIC_CFG_W
    from chainbits import crc32c_bits
    show = _fabric_bs("showcase")
    ok, msg = cfgplane.load_frames(p, show.to_int())
    if not ok:
        return False, msg
    other = _fabric_bs("xor6").to_int()
    cfgplane.frames_send(p, packets.load_stream(other))
    st = cfgplane.frames_stat(p)
    # the controller now sits in its error state until JPROGRAM, so read the memory over the chain
    kept_frames = cfgplane.cfg_out(p, FABRIC_CFG_W) == show.to_int()
    cfgplane.write_expected(p, crc32c_bits(other, FABRIC_CFG_W))
    cfgplane.cfg_in(p, other, FABRIC_CFG_W)
    kept_chain = cfgplane.cfg_out(p, FABRIC_CFG_W) == show.to_int()
    done = cfgplane.status(p)["done"]
    bad, n = _sweep_ok(p, show, "showcase")
    fpga.go_live(p)
    good = st["WR_ERROR"] and kept_frames and kept_chain and done and not bad
    return good, (f"frames: WR_ERROR={st['WR_ERROR']} memory kept={kept_frames}; chain while running kept={kept_chain}; "
                  f"DONE={done}; showcase {n - len(bad)}/{n} vectors == model")


def check_frames_vs_chain(p, ctx):
    """one memory, two paths: a chain load reads back identically through FDRO, and a frame
    load identically through CHAIN_OUT (a different design each way)."""
    import cfgplane
    from bitstream import FABRIC_CFG_W
    a = _fabric_bs("xor6").to_int()
    b = _fabric_bs("showcase").to_int()
    ok1, m1 = cfgplane.load(p, a, FABRIC_CFG_W, start=False)
    fdro = cfgplane.frames_readback(p) == a
    ok2, m2 = cfgplane.load_frames(p, b, start=False)
    chain = cfgplane.cfg_out(p, FABRIC_CFG_W) == b
    return ok1 and ok2 and fdro and chain, f"chain load -> FDRO == word: {fdro}; frame load -> CHAIN_OUT == word: {chain}"


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
    # M9: still no RTL change. The same examples packed, placed and routed by VPR on
    # the rr graph the bitstream was generated from, turned into chain bits by
    # tools/bob/fasm_from_vpr.py.
    "M9": [("chain-length", check_chain_length),
           ("vpr-gates", _synth_check("gates", vpr=True)),
           ("vpr-adder", _synth_check("adder", vpr=True)),
           ("vpr-counter", _synth_check("counter", vpr=True)),
           ("vpr-blinky", _synth_check("blinky", vpr=True)),
           ("vpr-ram", _synth_check("ram", vpr=True)),
           ("vpr-mult", _synth_check("mult", vpr=True))],
    # M10: still no RTL change. `bob build` -> .bit -> `bob load`, readback decoded to
    # FASM, then LEDs against the source and CAPTURE against the golden netlist.
    "M10": [("chain-length", check_chain_length),
            ("bob-gates", _bob_check("gates")),
            ("bob-adder", _bob_check("adder")),
            ("bob-counter", _bob_check("counter")),
            ("bob-blinky", _bob_check("blinky")),
            ("bob-ram", _bob_check("ram")),
            ("bob-mult", _bob_check("mult")),
            ("bob-gates-swapped", _bob_check("gates_swapped"))],
    # M11: still no RTL change. The two new examples through the M10 golden check, then
    # designs live on the free-running clock and the real switches.
    "M11": [("chain-length", check_chain_length),
            ("bob-switches", _bob_check("switches")),
            ("bob-fir", _bob_check("fir")),
            ("ram-readback", check_ram_readback),
            ("blinky-rate", check_blinky_rate),
            ("live-blinky", _live_check("blinky")),
            ("live-fir", _live_check("fir")),
            ("live-mult", _live_check("mult")),
            ("live-switches", _live_check("switches"))],          # last: leaves switches.v running
    # M13 is built further down (it reuses the lists above).
    # M12a: still no RTL change. Every example placed and routed by bob's own Python PnR
    # (tools/bob/pnr/) instead of VPR, through the M10 golden check, then two live.
    "M12": [("chain-length", check_chain_length),
            ("pnr-gates", _bob_check("gates", pnr="python")),
            ("pnr-adder", _bob_check("adder", pnr="python")),
            ("pnr-counter", _bob_check("counter", pnr="python")),
            ("pnr-blinky", _bob_check("blinky", pnr="python")),
            ("pnr-ram", _bob_check("ram", pnr="python")),
            ("pnr-mult", _bob_check("mult", pnr="python")),
            ("pnr-switches", _bob_check("switches", pnr="python")),
            ("pnr-fir", _bob_check("fir", pnr="python")),
            ("pnr-gates-swapped", _bob_check("gates_swapped", pnr="python")),
            ("live-fir-py", _live_check("fir", pnr="python")),
            ("live-switches-py", _live_check("switches", pnr="python"))],   # last: leaves switches running
}

# M13: a Vivado rebuild (frames, timing fixes), so the complete regression runs again:
# every M7 fabric check (loaded over the CHAIN path, CHAIN_IN / CHAIN_OUT), then the frame
# path on its own, then the guest designs, which bob load now sends as frames.
# --- M14: partial reconfiguration (docs/bitstream-format.md section 12) -------------------

def _partial_q(p):
    """the M14 pair's 4-bit counter, from CAPTURE"""
    import cfgplane
    from bitstream import CLB_XY_INDEX, NCLB
    from designs import PARTIAL_Q
    cap = cfgplane.capture(p, NCLB)
    return sum(((cap >> CLB_XY_INDEX[xy]) & 1) << k for k, xy in enumerate(PARTIAL_Q))


def _autostep(p, n):
    """n user clocks on the JTAG-stepped clock: USER1 autostep, one INTEST scan each"""
    import cfgplane
    import fpga
    cfgplane.user1(p, 0x14)                          # autostep + cin
    cfgplane.ir(p, "INTEST")
    for _ in range(n):
        p.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(0))
    cfgplane.user1(p, 0x04)                          # cin only: no more clocks


def _gate_sweep(p, gate):
    """LD1 for SW = 00, 01, 10, 11 on the board (INTEST, no clocks), and what the gate must give"""
    import fpga
    got = [(v >> 1) & 1 for v in fpga.intest_sweep(p, range(4))]
    want = [(v & 1) & (v >> 1) if gate == "and" else (v & 1) | (v >> 1) for v in range(4)]
    return got, want


def check_partial_swap(p, ctx):
    """M14 on the JTAG-stepped clock: design A (counter + AND) loaded and stepped 5 clocks;
    a partial reload to B (the same counter + OR) rewrites only the changed frame(s) with
    the design running; the counter still reads 5 (no clock, no reset), LD1 is now OR, and
    3 more clocks give 8: the state survived the reconfiguration."""
    import cfgplane
    import fpga
    import packets
    from designs import d_partial
    a, b = d_partial("and").build(), d_partial("or").build()
    ok, msg = cfgplane.load_frames(p, a.to_int())
    if not ok:
        return False, "load A: " + msg
    _autostep(p, 5)
    q5 = _partial_q(p)
    ga, wa = _gate_sweep(p, "and")
    ok, msg, n = cfgplane.load_partial(p, b.to_int())
    if not ok:
        fpga.go_live(p)
        return False, "partial: " + msg
    q_after = _partial_q(p)
    gb, wb = _gate_sweep(p, "or")
    _autostep(p, 3)
    q8 = _partial_q(p)
    done = cfgplane.status(p)["done"]
    fpga.go_live(p)
    good = q5 == 5 and q_after == 5 and q8 == 8 and ga == wa and gb == wb and done and 1 <= n <= 2
    return good, (f"{n} of {packets.NFRAMES} frames rewritten; counter 5 -> {q_after} across the partial -> {q8} "
                  f"after 3 clocks; LD1 A (AND) {ga} (model {wa}), B (OR) {gb} (model {wb}); DONE={done}")


def check_partial_live(p, ctx):
    """M14 on the FREE-RUNNING clock (div 17, ~3.7 counts/s): while frozen (AGHIGH acknowledged)
    the counter does not move for a second; the partial lands; after LFRM it counts again and
    LD1 has changed from AND to OR."""
    import time
    import cfgplane
    import fpga
    import packets
    from designs import d_partial
    a, b = d_partial("and", "run", 17).build(), d_partial("or", "run", 17).build()
    ok, msg = cfgplane.load_frames(p, a.to_int())
    if not ok:
        return False, "load A: " + msg
    cfgplane.user1(p, 0x04)                                  # cin: count
    q0 = _partial_q(p)
    time.sleep(1.2)
    moving = _partial_q(p) != q0
    freeze, frames, n = packets.partial_streams(a.to_int(), b.to_int())
    cfgplane.frames_send(p, freeze)
    st = cfgplane.frames_stat(p)
    f0 = _partial_q(p)
    time.sleep(1.2)
    f1 = _partial_q(p)
    cfgplane.frames_send(p, frames)
    st2 = cfgplane.frames_stat(p)
    time.sleep(1.2)
    r1 = _partial_q(p)
    gb, wb = _gate_sweep(p, "or")
    fpga.go_live(p)
    held = st["GHIGH_B"] == 0 and f0 == f1
    released = st2["GHIGH_B"] == 1 and not any(st2[k] for k in ("CRC_ERROR", "WR_ERROR", "PKT_ERROR")) and r1 != f1
    good = moving and held and released and gb == wb
    return good, (f"before: counting={moving}; frozen (GHIGH_B={st['GHIGH_B']}): {f0} -> {f1} over 1.2 s; "
                  f"{n} frame(s) written; released (GHIGH_B={st2['GHIGH_B']}): {f1} -> {r1}; LD1 {gb} (OR model {wb})")


def check_partial_bad_crc(p, ctx):
    """M14: a partial with a wrong CRC is refused at LFRM and the fabric STAYS frozen (the
    free-running counter does not move, DONE stays), until JPROGRAM + a full load."""
    import time
    import cfgplane
    import fpga
    from designs import d_partial
    a, b = d_partial("and", "run", 17).build(), d_partial("or", "run", 17).build()
    ok, msg = cfgplane.load_frames(p, a.to_int())
    if not ok:
        return False, "load A: " + msg
    cfgplane.user1(p, 0x04)
    ok, msg, _n = cfgplane.load_partial(p, b.to_int(), old=a.to_int(), crc_override=0x12345678)
    st = cfgplane.frames_stat(p)
    f0 = _partial_q(p)
    time.sleep(1.2)
    f1 = _partial_q(p)
    done = cfgplane.status(p)["done"]
    ok2, msg2 = cfgplane.load_frames(p, a.to_int())          # recovery
    cfgplane.user1(p, 0x04)
    r0 = _partial_q(p)
    time.sleep(1.2)
    recovered = ok2 and _partial_q(p) != r0
    fpga.go_live(p)
    good = (not ok) and st["CRC_ERROR"] and st["GHIGH_B"] == 0 and f0 == f1 and done and recovered
    return good, (f"refused={not ok} CRC_ERROR={st['CRC_ERROR']} GHIGH_B={st['GHIGH_B']}; frozen counter {f0} -> {f1}; "
                  f"DONE={done}; JPROGRAM + full load counts again={recovered}")


def check_partial_guest(p, ctx):
    """M14 through the guest flow: `bob load` gates, then `bob load --partial` gates_swapped
    (different routing, same pins file flow): only the changed frames, LEDs == the new design."""
    import cfgplane
    import cli
    import fpga
    import packets
    from bitstream import Bitstream, simulate
    paths = {}
    for name in ("gates", "gates_swapped"):
        import vpr_run
        top, pcf = vpr_run.VARIANTS.get(name, (name, None))
        paths[name] = cli.build([os.path.join(ROOT, "examples", f"{top}.v")], top, pcf,
                                os.path.join(ROOT, "build", "bit", f"{name}.bit"), name=name,
                                log=lambda *_: None)[0]
    ok, msg = cli.load(p, paths["gates"], log=lambda *_: None)
    if not ok:
        return False, "load gates: " + msg
    import bitgen
    new = bitgen.read_bit(paths["gates_swapped"])["word"]
    ok, msg = cli.load_partial(p, paths["gates_swapped"], log=lambda *_: None)
    got = fpga.intest_sweep(p, range(4))
    want = [simulate(Bitstream(new), v) for v in range(4)]
    fpga.go_live(p)
    n = len(packets.changed_frames(bitgen.read_bit(paths["gates"])["word"], new))
    return ok and got == want, f"{msg}; LEDs {got} == gates_swapped model {want}: {got == want} ({n} frames differ)"


MILESTONE["M13"] = (
    [c for c in MILESTONE["M7"] if c[0] != "pipeline-live"] +
    [("frames-load", check_frames_load),
     ("frames-crc-reject", check_frames_crc_reject),
     ("frames-idcode-reject", check_frames_idcode_reject),
     ("frames-live-refused", check_frames_live_refused),
     ("frames-vs-chain", check_frames_vs_chain),
     ("bob-gates", _bob_check("gates")),
     ("bob-counter", _bob_check("counter")),
     ("bob-ram", _bob_check("ram")),
     ("bob-mult", _bob_check("mult")),
     ("bob-fir", _bob_check("fir")),
     ("pnr-switches", _bob_check("switches", pnr="python")),
     ("ram-readback", check_ram_readback),
     ("blinky-rate", check_blinky_rate),
     ("pipeline-live", dict(MILESTONE["M7"])["pipeline-live"])])      # last: leaves the pipeline on the switches


# --- M15: BRAM contents as frames (FAR block type 1) ----------------------------------------

def check_frames_bram_load(p, ctx):
    """M15: the BRAM ROM design with random contents in BOTH BRAMs, all in one frame stream:
    FDRO reads every content word back, USER4 (the other path) reads the same words, and
    after JSTART the ROM shows mem[SW][2:0] on the LEDs."""
    import random
    import time
    import cfgplane
    import fpga
    from designs import d_bram_rom
    rng = random.Random()
    brams = {b: [rng.getrandbits(18) for _ in range(1024)] for b in range(2)}
    rom = d_bram_rom(0).build().to_int()
    ok, msg = cfgplane.load_frames(p, rom, start=False, brams=brams)
    if not ok:
        return False, msg
    cross = []
    for b in range(2):
        cfgplane.bram_select(p, b)
        if cfgplane.bram_read(p, 1000, 8) != brams[b][1000:1008]:
            cross.append(b)
    cfgplane.jstart(p)
    got = []
    cfgplane.ir(p, "INTEST")
    for v in range(4):                       # apply the address, let the free-running ROM read it
        p.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(v))
        time.sleep(0.05)
        got.append(fpga.bsr_leds(p.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(v))))
    want = [brams[0][v] & 7 for v in range(4)]
    fpga.go_live(p)
    good = not cross and got == want
    return good, f"{msg}; USER4 reads the same words: {not cross}; ROM LEDs {got} == mem[SW] {want}"


def check_frames_bram_live_refused(p, ctx):
    """M15: while the ROM runs, a BRAM content frame is refused (WR_ERROR) and, read back
    after JPROGRAM, the contents are unchanged."""
    import random
    import cfgplane
    import fpga
    import packets
    from designs import d_bram_rom
    rng = random.Random()
    words = [rng.getrandbits(18) for _ in range(1024)]
    ok, msg = cfgplane.load_frames(p, d_bram_rom(0).build().to_int(), brams={0: words})
    if not ok:
        return False, msg
    other = [w ^ 0x3FFFF for w in words[:32]]
    stream = ([packets.DUMMY, packets.SYNC, packets.NOP] + packets.write("IDCODE", packets.device_idcode()) +
              packets.write("CMD", packets.CMD["WCFG"]) + packets.write("FAR", packets.bram_far(0)) +
              [packets.type1(packets.OP_WRITE, packets.REG["FDRI"], len(other))] + other +
              packets.write("CMD", packets.CMD["DESYNC"]) + [packets.NOP])
    cfgplane.frames_send(p, stream)
    st = cfgplane.frames_stat(p)
    cfgplane.jprogram(p)
    back = cfgplane.bram_frames_read(p, 0, 0, 8)
    fpga.go_live(p)
    kept = back == words[:32]
    return st["WR_ERROR"] and kept, f"WR_ERROR={st['WR_ERROR']}; bram0[0..31] after JPROGRAM unchanged={kept}"


def check_ram_readback_frames(p, ctx):
    """M15: ram.v written by the design itself (64 INTEST clocks), stopped with JPROGRAM, and
    its BRAM read back over FDRO (block type 1) == model.py; the same words over USER4."""
    import cfgplane
    import cli
    import fpga
    import model
    from bitstream import Bitstream
    path, word, contents, tr, _work = cli.build([os.path.join(ROOT, "examples", "ram.v")], "ram", None,
                                                os.path.join(ROOT, "build", "bit", "ram.bit"), log=lambda *_: None)
    ok, msg = cli.load(p, path, log=lambda *_: None)
    if not ok:
        return False, msg
    trace = tr["trace"][:SYNTH_HW_CYCLES]
    m = model.Fabric(Bitstream(word))
    m.clock(gsr=1)
    for b, words in contents.items():
        m.brams[b].mem = list(words)
    cfgplane.user1(p, 0x10)
    cfgplane.ir(p, "INTEST")
    p.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(trace[0][0]))
    m.clock(pad_i=trace[0][0])
    for k in range(1, len(trace)):
        p.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(trace[k][0]))
        m.clock(pad_i=trace[k][0])
    cfgplane.user1(p, 0)
    cfgplane.jprogram(p)
    bad = []
    for b in sorted(contents):
        got = cfgplane.bram_frames_read(p, b, 0, 4)
        want = m.brams[b].mem[:16]
        if got != want:
            bad.append(f"bram{b} FDRO [0..15] = {got}, model {want}")
        cfgplane.bram_select(p, b)
        if cfgplane.bram_read(p, 0, 16) != got:
            bad.append(f"bram{b}: USER4 and FDRO disagree")
    fpga.go_live(p)
    return not bad, (f"bram0[0..15] = {m.brams[0].mem[:16]} over FDRO block type 1 after JPROGRAM == model, "
                     f"== USER4" if not bad else "; ".join(bad))


MILESTONE_M15_EXTRA = [("frames-bram-load", check_frames_bram_load),
                       ("frames-bram-live-refused", check_frames_bram_live_refused),
                       ("ram-readback-frames", check_ram_readback_frames)]

# M12b (8x6 grid, streamed chain) + M14 (partial reconfiguration): the M13 regression on the
# new bitstream, a design that needs the bigger grid through both PnR flows, and the partial
# reconfiguration checks. pipeline-live stays last.
MILESTONE["M14"] = (
    MILESTONE["M13"][:-1] +
    [("bob-wide", _bob_check("wide")),
     ("pnr-wide", _bob_check("wide", pnr="python")),
     ("partial-swap", check_partial_swap),
     ("partial-live", check_partial_live),
     ("partial-bad-crc", check_partial_bad_crc),
     ("partial-guest", check_partial_guest),
     MILESTONE["M13"][-1]])

# M15: everything above on the final bitstream, plus BRAM contents as frames. The build handed
# over for M12b, M14 and M15 together is this one.
MILESTONE["M15"] = MILESTONE["M14"][:-1] + MILESTONE_M15_EXTRA + [MILESTONE["M14"][-1]]

# M16: the 10 x 10 CLB grid (100 CLBs). Everything M15 checks still applies - the board test
# is the same regression on a bitstream with 2.8x the CLBs and 145 frames instead of 65 - plus
# `big`, a design that does not fit the old grid, through both PnR flows.
MILESTONE["M16"] = (
    MILESTONE["M15"][:-1] +
    [("bob-big", _bob_check("big")),
     ("pnr-big", _bob_check("big", pnr="python"))] +
    [MILESTONE["M15"][-1]])

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
    ap.add_argument("--only", metavar="CHECK[,CHECK]",
                    help="run only these milestone checks (idcode still runs first), e.g. --only live-fir")
    args = ap.parse_args()

    ms = args.milestone.upper()
    if ms not in MILESTONE:
        sys.exit(f"no checks defined for {ms}; known: {', '.join(MILESTONE)}")
    cfg = buildcfg.read_cfg()
    if cfg.get("tag") != ms:
        print(f"note: hw/build.cfg is tagged {cfg.get('tag')}, testing {ms}")

    checks = REGRESSION_BY_TOP.get(cfg.get("top"), REGRESSION) + MILESTONE[ms]
    if args.only:
        want = args.only.split(",")
        unknown = [w for w in want if w not in dict(checks)]
        if unknown:
            sys.exit(f"{ms} has no check {unknown}; see --list")
        checks = [c for c in checks if c[0] == "idcode" or c[0] in want]
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
