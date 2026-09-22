#!/usr/bin/env python3
"""
timing.py - static timing of a configured design on the fabric (M20).

The fabric's user clock is a clock enable on the 125 MHz sysclk, and until M20 every
enable was at least 2**GCE_MIN_GAP_SHIFT = 512 sysclk cycles from the last. The XDC's
multicycle is written against that number, because Vivado can only time the fabric
*unconfigured*: every routing mux open, combinational loops everywhere, about 2500 ns
through the 12x10 mesh (HANDOFF §2).

A configured design is a different graph. Each mux passes one input, each LUT depends
on the inputs its truth table uses, and the longest register-to-register path is a few
tens of nanoseconds. FPGA overlays sign off that way (ZUMA, Brant & Lemieux FCCM 2012;
"Timing Optimization for Virtual FPGA Configurations", ARC 2021): per-element delays
measured on the host implementation, summed along the guest circuit's own paths.

This module does that from the configuration word alone, so it serves VPR and bob's
own PnR alike, and any .bit:

  sources    CLB flip-flops (clk->Q), BRAM read data, DSP P (clk->Q)
  endpoints  CLB flip-flop D, CE and SR (setup), BRAM and DSP inputs (setup)
  through    selected mux inputs (one delay per mux by its class), directs (carry and
             cascade wires, zero), LUTs (inputs the INIT depends on), carry cin->cout,
             DSP inputs -> P when the slice is combinational (conservatively always)
  not timed  pads: the switches, buttons and LEDs are asynchronous to the fabric and
             false-pathed in the XDC, so pad paths set no clock

A combinational loop in the configured design is reported, never cut silently.

Delays come from software/bob/delays.json: measured on the Vivado build by
hw/scripts/extract_delays.tcl (M20), or, until that exists, provisional values derived
from M16's timing report, which the result says it used.

  analyse(word) -> {"cpd_ns", "path": [...], "gap_cycles", "fmax_hz", "provisional", ...}
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402

DELAYS = os.path.join(HERE, "delays.json")
SYSCLK_NS = 1e9 / B.DEVICE["clock"]["sysclk_hz"]
GAP_FLOOR = B.DEVICE["clock"].get("gce_gap_floor", 2)
PERIOD_MAX = (1 << B.DEVICE["clock"].get("period_w", 16)) - 1
MARGIN_MEASURED = 1.25        # guard band on measured delays (the board sweep checks it)
MARGIN_PROVISIONAL = 2.0      # and on the provisional ones, which are an estimate

KIND = {n[0]: n[1] for n in B.DEVICE["rr"]["nodes"]}


class TimingError(Exception):
    pass


def load_delays(path=None):
    path = path or DELAYS
    try:
        d = json.load(open(path))
    except (OSError, ValueError) as e:
        raise TimingError(f"{os.path.relpath(path, ROOT)}: {e}")
    need = {"mux_chan", "mux_ipin", "lut", "carry", "ff_clk_q", "ff_setup",
            "bram_clk_q", "bram_setup", "dsp_clk_q", "dsp_comb", "dsp_setup"}
    missing = need - set(d.get("ns", {}))
    if missing:
        raise TimingError(f"{os.path.relpath(path, ROOT)}: no delay for {sorted(missing)}")
    return d


def _depends(init, j, k):
    """Does a K-input LUT with this INIT depend on input j?"""
    step = 1 << j
    for idx in range(1 << k):
        if not idx & step and ((init >> idx) & 1) != ((init >> (idx | step)) & 1):
            return True
    return False


def graph(word):
    """The configured design as a timing graph: {node: [(driver, delay-class)]} for every
    net, plus sources {node: class} and endpoints {node: class}."""
    word = int(word)
    get = lambda lo, w: (word >> lo) & ((1 << w) - 1)          # noqa: E731
    bs = B.Bitstream(word)
    fanin = {}                  # node -> [(driver node, class of the arc)]
    sources, endpoints = {}, {}

    for node, (lo, w, base, ins) in B.MUX.items():
        sel = get(lo, w)
        if base <= sel < base + len(ins):
            cls = "mux_ipin" if KIND.get(node) == "IPIN" else "mux_chan"
            fanin[node] = [(ins[sel - base], cls)]
    for ipin, opin in B.DIRECT.items():
        fanin[ipin] = [(opin, "direct")]

    k = B.LUT_K
    for name in B.CLBS:
        init = bs.get_block(name, "init")
        fl = {f: bs.get_block(name, f) for f in B.FLAG_NAMES}
        pin = lambda p: B.PIN[f"{name}.{p}"]                    # noqa: E731
        ins = [pin(f"I[{j}]") for j in range(k)]
        used = [ins[j] for j in range(k) if _depends(init, j, k)]
        comb_in = [(n, "lut") for n in used]
        if fl["cy_en"]:
            comb_in.append((pin("cin[0]"), "carry"))
            fanin[pin("cout[0]")] = [(n, "lut") for n in used] + [(pin("cin[0]"), "carry")]
        comb = f"{name}.comb"                                    # the LUT/carry output, internal
        fanin[comb] = comb_in
        # O5 depends on inputs 0..K-2 of the lower half of the INIT
        lo_init = init & ((1 << (1 << (k - 1))) - 1)
        fanin[pin("O5[0]")] = [(ins[j], "lut") for j in range(k - 1) if _depends(lo_init, j, k - 1)]
        if fl["ff_en"]:
            sources[pin("O[0]")] = "ff_clk_q"
            endpoints[comb] = "ff_setup"
            if fl["ff_ce_en"]:
                endpoints[pin("ce[0]")] = "ff_setup"
            if fl["ff_sr_en"]:
                endpoints[pin("sr[0]")] = "ff_setup"
        else:
            fanin[pin("O[0]")] = [(comb, "wire")]

    for b in range(B.NBRAM):
        for port in "ab":
            for n, w in B.BRAM_PORT_PINS:
                for i in range(w):
                    endpoints[B.PIN[f"bram{b}.{n}_{port}[{i}]"]] = "bram_setup"
            for i in range(18):
                p = f"bram{b}.do_{port}[{i}]"
                if p in B.PIN:
                    sources[B.PIN[p]] = "bram_clk_q"
    for s in range(B.NDSP):
        ins = [B.PIN[f"dsp{s}.{bus}[{i}]"] for bus, w in B.DSP_BUSES for i in range(w)
               if f"dsp{s}.{bus}[{i}]" in B.PIN]
        for n in ins:
            endpoints[n] = "dsp_setup"
        for i in range(48):
            for out in ("p", "pcout"):
                p = f"dsp{s}.{out}[{i}]"
                if p in B.PIN:
                    sources[B.PIN[p]] = "dsp_clk_q"
                    fanin[B.PIN[p]] = [(n, "dsp_comb") for n in ins]
    return fanin, sources, endpoints


def analyse(word, delays=None, margin=None):
    """Longest register-to-register path of the configured design, and the gce gap and
    period (in sysclk cycles) it can run at."""
    d = delays or load_delays()
    ns = d["ns"]
    provisional = bool(d.get("provisional"))
    margin = margin or (MARGIN_PROVISIONAL if provisional else MARGIN_MEASURED)
    fanin, sources, endpoints = graph(word)
    arrival, via, state = {}, {}, {}

    def arr(node):
        """Latest arrival at node (ns after the clock edge), or None if no register reaches it."""
        if state.get(node) == 2:
            return arrival.get(node)
        if state.get(node) == 1:
            raise TimingError(f"combinational loop through node {node} ({KIND.get(node, node)})")
        state[node] = 1
        best, best_from = None, None
        if node in sources:                     # a register output (a DSP P may also have
            best, best_from = ns[sources[node]], None     # a combinational fan-in: take the later)
        if node in fanin:
            for drv, cls in fanin[node]:
                a = arr(drv)
                if a is None:
                    continue
                t = a + ns.get(cls, 0.0)
                if best is None or t > best:
                    best, best_from = t, drv
        state[node] = 2
        if best is not None:
            arrival[node] = best
            via[node] = best_from
        return best

    sys.setrecursionlimit(max(10000, 4 * len(fanin)))
    worst, worst_end = 0.0, None
    for node, cls in endpoints.items():
        a = arr(node)
        if a is None:
            continue
        t = a + ns[cls]
        if t > worst:
            worst, worst_end = t, node
    path = []
    n = worst_end
    while n is not None:
        path.append({"node": n, "kind": KIND.get(n, "internal" if isinstance(n, str) else "?"),
                     "at_ns": round(arrival.get(n, 0.0), 3)})
        n = via.get(n)
    path.reverse()
    if worst_end is None:                               # no register-to-register path at all
        gap = GAP_FLOOR
    else:
        gap = max(GAP_FLOOR, -(-int(worst * margin * 1000) // int(SYSCLK_NS * 1000)))
    if gap > PERIOD_MAX:
        raise TimingError(f"critical path {worst:.1f} ns needs {gap} cycles, more than clk_gap holds")
    return {"cpd_ns": round(worst, 3), "margin": margin, "provisional": provisional,
            "delays": d.get("source", ""), "gap_cycles": gap,
            "fmax_hz": 1e9 / (gap * SYSCLK_NS), "endpoints": len(endpoints),
            "path": path, "levels": sum(1 for p in path if p["kind"] in ("CHANX", "CHANY", "IPIN"))}


def clock_for(t, hz=None):
    """(period, gap, div) for a timing result: the fastest safe rate, or the rate asked for
    if the design allows it. The enable spacing is period x 2**div sysclk cycles (div only
    prescales a rate too slow for clk_period alone)."""
    gap = t["gap_cycles"]
    if hz in (None, "auto", 0):
        return gap, gap, 0
    cycles = max(1, round(B.DEVICE["clock"]["sysclk_hz"] / float(hz)))
    div = 0
    while (cycles >> div) > PERIOD_MAX:
        div += 1
    if div > 16:
        raise TimingError(f"{hz} Hz is slower than clk_period x 2**clk_div can hold")
    period = max(1, round(cycles / (1 << div)))
    if (period << div) < gap:
        raise TimingError(f"{float(hz):.4g} Hz is faster than this design allows: its critical path "
                          f"{t['cpd_ns']} ns x {t['margin']} needs {gap} sysclk cycles "
                          f"({t['fmax_hz'] / 1e6:.3g} MHz at most)")
    return period, gap, div


def main():
    import argparse
    import bitgen
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bit")
    a = ap.parse_args()
    t = analyse(bitgen.read_bit(a.bit)["word"])
    print(f"critical path {t['cpd_ns']} ns over {t['levels']} routing hops"
          f" ({'provisional' if t['provisional'] else 'measured'} delays, margin {t['margin']}):"
          f" gap {t['gap_cycles']} cycles, Fmax {t['fmax_hz'] / 1e6:.3f} MHz")
    return 0


if __name__ == "__main__":
    sys.exit(main())
