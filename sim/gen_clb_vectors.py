#!/usr/bin/env python3
"""
Generate hw/tb/clb_vectors.vh for hw/tb/tb_clb.sv - the cluster unit test (M21; the M4
CLB flag sweep before it).

The device under test is one bob_clb (generated into bob_fabric.v by software/bob/
fabric_gen.py): N elements (hw/src/clb/ble.sv) behind the crossbar. Each test is one
random cluster configuration run for a few cycles with random CLB inputs, carry-in,
CE, SR and the global gce / GSR / GWE; the expected outputs come from
software/bob/model.py's element functions, evaluated through the crossbar exactly as
device.json describes it. What the configurations cover, on purpose:

  every element flag     each of the 12 flags alone on element 0, then random mixes
  the modes              LUT K (frac 0), two LUT K-1 (frac 1), carry (cy_en) with both
                         generate sources
  every crossbar source  each element input selects const0, const1, a CLB input or a
                         feedback output; over the run every select value of every
                         element input is used
  the carry              chains of carry elements across all N elements, cin -> cout
  both flip-flops        ff_en / ff2_en, CE / SR / reset values, GSR and GWE

Feedback never makes a loop: an element reads another element's output only when that
output is registered or comes from an element below it (the carry runs upward too).

  ./gen_clb_vectors.py [--out FILE]      honours BOB_DEVICE_JSON (K=4 runs)
"""

import argparse
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "software", "bob"))
sys.path.insert(0, os.path.join(HERE, "..", "software", "host"))

import bitstream as B  # noqa: E402
import model as M      # noqa: E402

STEPS = 6


def evaluate(cfg, ins, cin, ce, sr, q, q2):
    """-> (o bits [2N], cout) of the cluster before the edge, and the comb/o5 per element"""
    N, K = B.CLB_N, B.LUT_K
    o = [None] * (2 * N)
    comb, comb5 = [0] * N, [0] * N
    for e in range(N):                            # registered outputs are known at once
        if cfg[e]["ff_en"]:
            o[2 * e] = q[e]
        if cfg[e]["ff2_en"]:
            o[2 * e + 1] = q2[e]
    cy = cin
    for e in range(N):                            # then in element order (feedback only from below)
        f = cfg[e]
        addr = 0
        for j in range(K):
            v = f[f"x{j}"]
            if v == 0:
                bit = 0
            elif v == 1:
                bit = 1
            else:
                src = B.XBAR_SOURCES[e][j][v - 2]
                idx = int(src[2:-1])
                bit = ins[idx] if src.startswith("I") else o[idx]
                assert bit is not None, (e, j, src)
            addr |= bit << j
        _o6, lo5, lcomb, cout = M.clb_comb(f["init"], f, addr, cy)
        comb[e], comb5[e] = lcomb, lo5
        if not f["ff_en"]:
            o[2 * e] = lcomb
        if not f["ff2_en"]:
            o[2 * e + 1] = lo5
        cy = cout
    return o, cy, comb, comb5


def random_cfg(rng, t, flags_on=None):
    N, K = B.CLB_N, B.LUT_K
    cfg = []
    for e in range(N):
        f = {"init": rng.getrandbits(1 << K)}
        for name in M.FLAGS:
            f[name] = rng.getrandbits(1)
        if flags_on is not None:                  # the single-flag tests: element 0 only
            for name in M.FLAGS:
                f[name] = int(e == 0 and name == flags_on)
        if t % 5 == 0:                            # a carry chain through every element
            f["cy_en"] = 1
        if t % 10 == 5:                           # M24: a Double Duty chain through every element
            f["cy_en"] = f["dd"] = 1
        cfg.append(f)
    def legal(e, v, j):
        if v < 2:
            return True
        src = B.XBAR_SOURCES[e][j][v - 2]
        if src.startswith("I"):
            return True
        m = int(src[2:-1])
        return bool(cfg[m // 2]["ff_en" if m % 2 == 0 else "ff2_en"]) or m // 2 < e

    for e in range(N):
        for j in range(K):
            n = len(B.XBAR_SOURCES[e][j])
            v = (t + 7 * e + 3 * j) % (2 + n)     # every select value comes round in turn
            if legal(e, v, j):
                cfg[e][f"x{j}"] = v
                continue
            if flags_on is None:                   # a combinational feedback from above:
                m = int(B.XBAR_SOURCES[e][j][v - 2][2:-1])  # register that output instead
                cfg[m // 2]["ff_en" if m % 2 == 0 else "ff2_en"] = 1
                cfg[e][f"x{j}"] = v
                continue
            while True:
                v = rng.randrange(2 + n)
                if v < 2:
                    break
                src = B.XBAR_SOURCES[e][j][v - 2]
                if src.startswith("I"):
                    break
                m = int(src[2:-1])
                reg = cfg[m // 2]["ff_en" if m % 2 == 0 else "ff2_en"]
                if reg or m // 2 < e:
                    break
            cfg[e][f"x{j}"] = v
    return cfg


def encode(cfg):
    word = 0
    for e, f in enumerate(cfg):
        for name, v in f.items():
            off, w = B.FIELD[f"e{e}.{name}"]
            word |= v << off
    return word


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.normpath(
        os.path.join(HERE, "..", "hw", "tb", "clb_vectors.vh")))
    ap.add_argument("--tests", type=int, default=240)
    args = ap.parse_args()

    N, K, W, NI = B.CLB_N, B.LUT_K, B.CLB_CFG_W, B.CLB_I
    rng = random.Random(0xC1B)
    out = [
        "// hw/tb/clb_vectors.vh - GENERATED by sim/gen_clb_vectors.py, do not edit.",
        f"// cluster: {N} elements, LUT K = {K}, {NI} inputs, config {W} bits; expected values",
        "// from software/bob/model.py through the crossbar of device.json.",
        "",
    ]
    tests = [("flag", f) for f in M.FLAGS] + [("random", None)] * args.tests
    used = set()
    n = 0
    for t, (kind, flag) in enumerate(tests):
        cfg = random_cfg(rng, t, flag)
        for e in range(N):
            for j in range(K):
                used.add((e, j, cfg[e][f"x{j}"]))
        word = encode(cfg)
        q = [0] * N
        q2 = [0] * N
        for s in range(STEPS):
            ins = [rng.getrandbits(1) for _ in range(NI)]
            cin, ce, sr = rng.getrandbits(1), rng.getrandbits(1), rng.getrandbits(1)
            if s == 0:
                gsr, gce, gwe = 1, rng.getrandbits(1), 0          # establish q = INIT
            else:
                gsr = 1 if rng.random() < 0.08 else 0
                gce = 1 if rng.random() < 0.8 else 0
                gwe = 1 if rng.random() < 0.85 else 0
            known = s > 0
            o_pre, cout, comb, comb5 = evaluate(cfg, ins, cin, ce, sr, q, q2)
            q = [M.clb_next(q[e], cfg[e], comb[e], ce, sr, gce, gsr, gwe) for e in range(N)]
            q2 = [M.clb_next(q2[e], cfg[e], comb5[e], ce, sr, gce, gsr, gwe, ff="2") for e in range(N)]
            o_post, _c, _x, _y = evaluate(cfg, ins, cin, ce, sr, q, q2)
            vi = sum(b << k for k, b in enumerate(ins))
            pre = sum(b << k for k, b in enumerate(o_pre))
            post = sum(b << k for k, b in enumerate(o_post))
            out.append(f"    step({W}'h{word:x}, {NI}'h{vi:x}, {cin}, {ce}, {sr}, {gce}, {gsr}, {gwe}, "
                       f"{2 * N}'h{pre:x}, {int(known)}, {cout}, {2 * N}'h{post:x});")
            n += 1
    total = sum(2 + len(B.XBAR_SOURCES[e][j]) for e in range(N) for j in range(K))
    with open(args.out, "w") as fh:
        fh.write("\n".join(out) + "\n")
        fh.write(f"    // crossbar select values used: {len(used)} of {total}\n")
    print(f"wrote {args.out}  ({n} cycles, {len(tests)} configurations, K={K}, N={N}; "
          f"crossbar select values used {len(used)}/{total})")
    if len(used) < total:
        sys.exit(f"not every crossbar select value is exercised ({len(used)}/{total}): raise --tests")


if __name__ == "__main__":
    main()
