#!/usr/bin/env python3
"""
devtable.py - the device table, generated from the device description.

  software/bob/devtable.py            print it
  software/bob/devtable.py --write    update every file that carries the markers
  software/bob/devtable.py --check    exit 1 if any marked block is out of date

The same numbers were hand-copied into README.md, PLAN.md, HANDOFF.md, CLAUDE.md,
GUIDE.md and REPORT.md, and they drifted: after M16 put 100 CLBs on the board,
README.md still described the 36-CLB M12b profile in the table under a heading that
said M16. device.json already holds every one of those numbers, so the table is
generated between

    <!-- device:begin --> ... <!-- device:end -->

and tests/test_device_table.py fails if a marked block no longer matches. Utilisation
and timing come from docs/reports/<tag>/, so they appear only once a build has been
done and copied back.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

BEGIN, END = "<!-- device:begin -->", "<!-- device:end -->"
FILES = ["README.md", "PLAN.md", "HANDOFF.md", "CLAUDE.md",
         "docs/project/GUIDE.md", "docs/project/REPORT.md"]


def _cfg():
    import buildcfg
    return buildcfg.read_cfg()


def _report(tag, name):
    p = os.path.join(ROOT, "docs", "reports", tag, name)
    return open(p, errors="replace").read() if os.path.exists(p) else ""


def facts():
    d = json.load(open(os.path.join(HERE, "device.json")))
    cfg = _cfg()
    a, blocks = d["arch"], d["blocks"]
    n = {}
    for b in blocks:
        n[b["type"]] = n.get(b["type"], 0) + 1
    cols = {t: sorted({b["x"] for b in blocks if b["type"] == t}) for t in ("clb", "bram", "dsp")}
    height = {c["type"]: c["height"] for c in a["columns"]}
    f = {
        "name": d["name"], "tag": cfg["tag"], "idcode": cfg["idcode"].upper(),
        "grid_w": a["grid_width"], "grid_h": a["grid_height"],
        "core_w": a["grid_width"] - 2, "core_h": a["grid_height"] - 2,
        "clb": n.get("clb", 0), "bram": n.get("bram", 0), "dsp": n.get("dsp", 0),
        "pads": d["pads"]["count"], "chan_w": a["chan_width"],
        "seg": a["segment_length"], "sb": a["switch_block"],
        "muxes": sum(1 for m in d["rr"]["muxes"] if m[0] not in {n[0] for n in d["rr"]["nodes"] if n[1] == "EIN"}),
        "lut_k": d["lut_k"],
        "chain_w": d["chain"]["width"], "frames": d["frames"]["count"],
        "fwords": d["frames"]["words"],
        "clb_cols": ", ".join(str(x) for x in cols["clb"]),
        "bram_col": ", ".join(str(x) for x in cols["bram"]), "bram_h": height.get("bram"),
        "dsp_col": ", ".join(str(x) for x in cols["dsp"]), "dsp_h": height.get("dsp"),
        "div_shift": d["clock"]["div_min_shift"], "gap_shift": d["clock"]["gce_min_gap_shift"],
        "gap_floor": d["clock"].get("gce_gap_floor"),
        "xdc_mc": d["clock"].get("xdc_multicycle"),
        "n": d.get("cluster", {}).get("n", 1), "ci": d.get("cluster", {}).get("i"),
        "xbar": d.get("cluster", {}).get("xbar"),
        "lframes": len(d.get("lframes", {}).get("list", [])),
    }
    f["max_hz"] = d["clock"]["sysclk_hz"] / 2 ** f["div_shift"]

    util, timing = _report(f["tag"], "util.rpt"), _report(f["tag"], "timing.rpt")
    m = re.search(r"\|\s*Slice LUTs\s*\|\s*(\d+)\s*\|[^|]*\|[^|]*\|\s*(\d+)\s*\|\s*([\d.]+)", util)
    f["luts"] = (int(m.group(1)), float(m.group(3))) if m else None
    m = re.search(r"\|\s*Register as Flip Flop\s*\|\s*(\d+)\s*\|[^|]*\|[^|]*\|\s*(\d+)\s*\|\s*([\d.]+)", util)
    f["ffs"] = (int(m.group(1)), float(m.group(3))) if m else None
    m = re.search(r"^Setup :\s+(\d+)\s+Failing Endpoints,\s+Worst Slack\s+(-?[\d.]+)ns", timing, re.M)
    f["wns"] = float(m.group(2)) if m else None
    return f


def table():
    f = facts()
    rows = [
        ("VPR grid", f"{f['grid_w']} × {f['grid_h']} "
                     f"({f['core_w']} × {f['core_h']} core inside an I/O ring, corners empty)"),
        ("CLBs", f"{f['clb']} × {f['n']} logic elements = {f['clb'] * f['n']} LUTs (columns x = {f['clb_cols']}); "
                 f"each element LUT{f['lut_k']} (or two LUT{f['lut_k'] - 1}), MUXCY/XORCY carry, two FDRE/FDSE; "
                 f"{f['ci']} inputs and a {f['xbar']} crossbar per CLB"
                 + ("; LUT contents and crossbar in CFGLUT5 (M22), crossbar muxes in pairs sharing "
                    "dual-output leaves (M23)" if f["lframes"] else "")),
        ("BRAM", f"{f['bram']} × 1024×18 true dual port (column x = {f['bram_col']}, "
                 f"{f['bram_h']} rows tall); contents as frames (FAR type 001) or over USER4"),
        ("DSP", f"{f['dsp']} × DSP48E1-style slices (column x = {f['dsp_col']}, "
                f"{f['dsp_h']} rows tall), PCOUT→PCIN cascade"),
        ("I/O", f"{f['pads']} pads; board switches, buttons and LEDs on fixed pads, LD3 = DONE"),
        ("Routing", f"L{f['seg']} unidirectional, W = {f['chan_w']}, {f['sb'].replace('wilton fs=', 'Wilton Fs = ')} "
                    f"(from OpenFPGA's k6_frac_N10 tileable arch); {f['muxes']} muxes, each LUT6 4:1 leaves "
                    "+ MUXF7/MUXF8 (M23)"),
        ("Configuration", f"{f['chain_w']} bits = {f['frames']} frames of {f['fwords']} × 32"
                          + (f" ({f['lframes']} of them held only in CFGLUT5s)" if f["lframes"] else "") + "; "
                          "UG470-style packets on CFG_IN/CFG_OUT (CRC-32C, IDCODE, partial "
                          "reconfiguration, BRAM content frames) or the streamed chain on "
                          "CHAIN_IN/CHAIN_OUT; GSR → GTS → GWE → DONE startup"),
        ("User clock", (f"one sysclk enable at a time, spaced by each design's own timing "
                        f"(clk_gap from software/bob/timing.py, never under {f['gap_floor']} cycles = "
                        f"{125 / f['gap_floor']:.1f} MHz); unset, at least 2**{f['gap_shift']} = "
                        f"{1 << f['gap_shift']} cycles apart"
                        + (" (a word is loaded only if its critical path fits its spacing)"
                           if f.get("xdc_mc") else " (the XDC's multicycle)") + ", "
                        f"at most {f['max_hz'] / 1000:.0f} kHz")
                       if f.get("gap_floor") else
                       (f"one sysclk enable at a time, at least 2**{f['gap_shift']} = "
                        f"{1 << f['gap_shift']} cycles apart (the fabric's multicycle); free-running "
                        f"at most 125 MHz / 2**{f['div_shift']} = {f['max_hz'] / 1000:.0f} kHz")),
        ("JTAG", f"6-bit AMD 7-series IR, IDCODE `0x{f['idcode']}` ({f['tag']})"),
    ]
    if f["luts"] and f["ffs"]:
        sp = lambda n: f"{n:,}".replace(",", "\u202f")     # thin space, as the docs use  # noqa: E731
        t = f", WNS {f['wns']:+g} ns" if f["wns"] is not None else ""
        rows.append((f"Host utilisation (Vivado, {f['tag']})",
                     f"{sp(f['luts'][0])} LUTs ({f['luts'][1]}%), {sp(f['ffs'][0])} FFs "
                     f"({f['ffs'][1]}%), {f['bram']} RAMB18, {f['dsp']} DSP48E1{t}"))
    body = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return f"{BEGIN}\n\n| | |\n|---|---|\n{body}\n\n{END}"


def apply(write):
    """-> list of (path, ok). Files without the markers are left alone."""
    want, out = table(), []
    pat = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    for rel in FILES:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        s = open(p).read()
        if BEGIN not in s:
            continue
        new = pat.sub(lambda _m: want, s)
        ok = new == s
        if write and not ok:
            open(p, "w").write(new)
        out.append((rel, ok))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if not (a.write or a.check):
        print(table())
        return 0
    res = apply(a.write)
    if not res:
        print(f"no file carries {BEGIN}; add it where the device table belongs")
        return 1
    stale = [r for r, ok in res if not ok]
    for rel, ok in res:
        print(f"  {'up to date' if ok else ('wrote     ' if a.write else 'STALE     ')}  {rel}")
    return 1 if (a.check and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
