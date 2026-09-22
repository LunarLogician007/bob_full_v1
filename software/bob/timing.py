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
import math
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


# --- the clock constraint (SDC) ---------------------------------------------------
#
# As in Vivado (XDC) and OpenFPGA, the designer states the clock and the tools check the
# design against it: create_clock -period <ns> [-name <n>] [-waveform {...}] [get_ports clk].
# The fabric has one clock, reaching the design's clk port, so one create_clock and nothing
# else; the pads are asynchronous to it (false-pathed in the XDC), so there are no I/O delays.

class SdcError(TimingError):
    pass


class TimingViolation(TimingError):
    """The design does not meet its clock constraint. The message is the report."""


PIN_NAME = {node: name for name, node in B.PIN.items()}


def read_sdc(path):
    """-> {"period_ns", "name", "file", "line"} from a .sdc holding one create_clock."""
    try:
        text = open(path).read()
    except OSError as e:
        raise SdcError(f"{path}: {e}")
    rel = os.path.relpath(os.path.abspath(path), ROOT) if os.path.abspath(path).startswith(ROOT) else path
    clocks = []
    lines = text.replace("\\\n", " ").splitlines()
    for n, raw in enumerate(lines, 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        toks = line.replace("[", " [ ").replace("]", " ] ").replace("{", " { ").replace("}", " } ").split()
        if toks[0] != "create_clock":
            raise SdcError(f"{rel}:{n}: {toks[0]} is not supported - bob's fabric has one clock and "
                           "asynchronous pads, so a .sdc holds one create_clock and nothing else")
        period, name, port = None, "clk", None
        i = 1
        while i < len(toks):
            t = toks[i]
            if t == "-period" and i + 1 < len(toks):
                try:
                    period = float(toks[i + 1])
                except ValueError:
                    raise SdcError(f"{rel}:{n}: -period takes nanoseconds, not {toks[i + 1]!r}")
                i += 2
            elif t == "-name" and i + 1 < len(toks):
                name = toks[i + 1]
                i += 2
            elif t == "-waveform":                       # accepted and ignored: one 50% clock
                j = toks.index("}", i) if "}" in toks[i:] else i + 1
                i = j + 1
            elif t == "[" and toks[i + 1:i + 2] == ["get_ports"]:
                j = toks.index("]", i)
                ports = [x for x in toks[i + 2:j] if x not in ("{", "}")]
                port = ports[0] if ports else None
                if ports != ["clk"]:
                    raise SdcError(f"{rel}:{n}: the fabric's clock reaches the design's clk port; "
                                   f"get_ports {' '.join(ports) or '(nothing)'} is not it")
                i = j + 1
            else:
                raise SdcError(f"{rel}:{n}: create_clock: unexpected {t!r} "
                               "(create_clock -period <ns> [-name <n>] [get_ports clk])")
        if period is None or period <= 0:
            raise SdcError(f"{rel}:{n}: create_clock needs -period <ns> > 0")
        clocks.append({"period_ns": period, "name": name, "file": rel, "line": n, "port": port or "clk"})
    if not clocks:
        raise SdcError(f"{rel}: no create_clock")
    if len(clocks) > 1:
        raise SdcError(f"{rel}:{clocks[1]['line']}: a second create_clock - bob's fabric has one clock")
    return clocks[0]


def _cycles(period_ns):
    """A period in ns -> (clk_period, clk_div): the nearest the 125 MHz base allows at or
    SLOWER than the period asked for, so the clock never runs faster than the constraint."""
    cycles = max(1, math.ceil(period_ns / SYSCLK_NS - 1e-9))
    div = 0
    while (cycles >> div) > PERIOD_MAX:
        div += 1
    if div > 16:
        raise SdcError(f"{period_ns} ns is slower than clk_period x 2**clk_div can hold")
    return max(1, math.ceil(cycles / (1 << div) - 1e-9)), div


def _where(node):
    if isinstance(node, str):
        return node.replace(".comb", " (LUT -> flip-flop D)")
    return PIN_NAME.get(node, f"{KIND.get(node, 'node')} {node}")


def constrain(t, period_ns, name="clk", origin=None):
    """Check a timing result against a clock period. -> {"met", "slack_ns", "required_ns",
    "period_ns", "period", "div", "achieved_ns", "achieved_hz"}; raises TimingViolation
    (the report) when the slack is negative, SdcError when the fabric cannot clock it."""
    floor_ns = GAP_FLOOR * SYSCLK_NS
    if period_ns < floor_ns - 1e-9:
        raise SdcError(f"create_clock -period {period_ns:g}: the fabric's fastest clock is "
                       f"{floor_ns:g} ns ({1e3 / floor_ns:g} MHz): {GAP_FLOOR} cycles of the 125 MHz base")
    period, div = _cycles(period_ns)
    achieved = (period << div) * SYSCLK_NS
    required = t["cpd_ns"] * t["margin"]
    slack = round(period_ns - required, 3)
    r = {"met": slack >= 0, "slack_ns": slack, "required_ns": round(required, 3),
         "period_ns": period_ns, "name": name, "period": period, "div": div,
         "achieved_ns": achieved, "achieved_hz": 1e9 / achieved, "origin": origin}
    if slack < 0:
        where = (f"  from {_where(t['path'][0]['node'])} to {_where(t['path'][-1]['node'])}, "
                 f"{t['levels']} routing hops\n" if t["path"] else "")
        best = t["gap_cycles"] * SYSCLK_NS
        raise TimingViolation(
            f"timing not met: clock {name} period {period_ns:.3f} ns ({1e3 / period_ns:.3f} MHz"
            + (f", {origin}" if origin else "") + ")\n"
            f"  critical path {t['cpd_ns']:.3f} ns x {t['margin']} guard band = {required:.3f} ns"
            f"  ->  slack {slack:+.3f} ns\n" + where +
            f"  the fastest this design can run: {best:.3f} ns ({1e3 / best:.3f} MHz). Relax "
            f"create_clock -period to at least {best:g}, or shorten the path")
    return r


def clock_for(t, hz=None):
    """(period, gap, div) for a timing result: the fastest safe rate ("auto"), or the rate
    asked for, checked as a constraint (TimingViolation if the design cannot make it)."""
    gap = t["gap_cycles"]
    if hz in (None, "auto", 0):
        return gap, gap, 0
    r = constrain(t, 1e9 / float(hz), origin=f"--hz {hz}")
    return r["period"], gap, r["div"]


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
