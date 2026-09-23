#!/usr/bin/env python3
"""
sweep.py - size the M21 cluster by measurement (PLAN M21 goal 2), before any RTL is frozen.

  software/bob/sweep.py [--only TAG ...] [--yosys] [--report]

For every combination of the cluster knobs (device.py: N elements per CLB, the crossbar
full or half, fracturable LUTs on) on a grid of about 300 LUTs, and for M16's one-LUT CLB
(the committed architecture) as the baseline:

  1. VPR (OpenFPGA's Docker image) routes every example with a binary search on the
     channel width: the minimum W each one needs
  2. the architecture is built at W = the largest minimum x 1.3 (VPR's low-stress
     margin), rounded up to even (unidirectional wires come in pairs): the rr graph
     VPR writes becomes a Device, so the configuration bits per CLB tile and per LUT
     are exact, not estimated
  3. every example is routed again on that graph: wirelength, and the critical path
     with bob's own delays (software/bob/delays.json: the routing mux, connection box,
     LUT and carry as measured or provisionally derived from M16's build; the crossbar
     is timed as a routing mux until M21's build measures it)
  4. --yosys: the generated fabric (bob_fabric + the cluster) through yosys
     synth_xilinx, for host LUTs and flip-flops

Everything lands in build/sweep/<tag>/ and the summary in build/sweep/results.json;
--report writes docs/reports/M21/cluster_sweep.md from it.
"""

import argparse
import gzip
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import device  # noqa: E402

OUT = os.path.join(ROOT, "build", "sweep")
REPORT = os.path.join(ROOT, "docs", "reports", "M21", "cluster_sweep.md")
EXAMPLES = ["gates", "adder", "counter", "blinky", "ram", "mult", "switches", "fir", "wide", "big",
            "atspeed", "fir16"]
IMAGE = "ghcr.io/lnis-uofu/openfpga-master:latest"
VPR = "/opt/openfpga/build/vtr-verilog-to-routing/vpr/vpr"


def _docker_env():
    env = dict(os.environ)
    sock = os.path.expanduser("~/.colima/default/docker.sock")
    if "DOCKER_HOST" not in env and os.path.exists(sock):
        env["DOCKER_HOST"] = f"unix://{sock}"
    return env
FLAGS = ["--absorb_buffer_luts", "off", "--const_gen_inference", "none",
         "--sweep_dangling_primary_ios", "off", "--sweep_dangling_nets", "off",
         "--sweep_dangling_blocks", "off", "--sweep_constant_primary_outputs", "off"]
MARGIN = 1.3


def bob_delays():
    """VPR delay strings (seconds) from software/bob/delays.json (ns)."""
    ns = json.load(open(os.path.join(HERE, "delays.json")))["ns"]
    s = lambda v: f"{v * 1e-9:.4g}"                 # noqa: E731
    return {"chan": s(ns["mux_chan"]), "ipin": s(ns["mux_ipin"]), "lut": s(ns["lut"]),
            "carry": s(ns["carry"]), "xbar": s(ns.get("mux_xbar", ns["mux_chan"]))}


def grid(nx, ny, bram_x, dsp_x, h, w=24):
    return {"nx": nx, "ny": ny, "chan_width": w, "segment_length": 4, "fs": 3,
            "fc_in": 0.15, "fc_out": 0.10, "io_capacity": 1,
            "columns": [{"type": "bram", "x": bram_x, "height": h},
                        {"type": "dsp", "x": dsp_x, "height": h}]}


# about 300 LUTs each (fir16 needs ~290 LUTs + flip-flops); two of every hard block
GRIDS = {4: grid(11, 10, 3, 8, 5),        # 9 x 10 CLBs = 90 x 4  = 360 LUTs
         8: grid(8, 7, 3, 6, 3),          # 6 x 7 CLBs  = 42 x 8  = 336
         10: grid(8, 6, 3, 6, 3)}         # 6 x 6 CLBs  = 36 x 10 = 360
CONFIGS = [(f"n{n}_{x}", n, x) for n in (4, 8, 10) for x in ("full", "half")]
EXTRA = {"n10_half_7x5": (10, "half", grid(7, 5, 3, 6, 2)),       # 5 x 5 = 25 CLBs = 250 LUTs
         "n10_half_6x4": (10, "half", grid(6, 4, 3, 6, 2))}       # 4 x 4 = 16 CLBs = 160 LUTs
# round 2: what the XC7Z020 can afford (round 1 put a 360-LUT cluster fabric at 100k+ host
# LUTs): about 200 LUTs each, full crossbars, I = 4N or Betz's K(N+1)/2
ROUND2 = {"r2_n4": (4, 16, grid(9, 7, 3, 6, 3)),          # 7 x 7 = 49 CLBs = 196 LUTs
          "r2_n6": (6, 24, grid(8, 6, 3, 6, 3)),          # 6 x 6 = 36 CLBs = 216
          "r2_n8": (8, 32, grid(7, 5, 3, 6, 2)),          # 5 x 5 = 25 CLBs = 200
          "r2_n8_i27": (8, 27, grid(7, 5, 3, 6, 2)),
          "r2_n10": (10, 40, grid(6, 5, 3, 5, 2)),        # 4 x 5 = 20 CLBs = 200
          "r2_n10_i33": (10, 33, grid(6, 5, 3, 5, 2))}


def arch_of(tag):
    if tag in ROUND2:
        n, i, g = ROUND2[tag]
        a = json.loads(json.dumps(g))
        a["cluster"] = {"n": n, "i": i, "xbar": "full", "frac": True}
        a["delays"] = bob_delays()
        return a
    if tag in EXTRA:
        n, x, g = EXTRA[tag]
    else:
        _t, n, x = next(c for c in CONFIGS if c[0] == tag)
        g = GRIDS[n]
    a = json.loads(json.dumps(g))
    a["cluster"] = {"n": n, "i": 4 * n, "xbar": x, "frac": True}
    a["delays"] = bob_delays()
    return a


def baseline_xml():
    """The committed M16/M20 architecture (one LUT per CLB) with bob's delays."""
    text = open(os.path.join(HERE, "arch", "bob_k6.xml")).read()
    if 'name="fle"' in text:
        text = subprocess.run(["git", "show", "8e6ecff:software/bob/arch/bob_k6.xml"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout
    d = bob_delays()
    text = text.replace('Tdel="58e-12"', f'Tdel="{d["chan"]}"')
    text = text.replace('Tdel="7.247000e-11"', f'Tdel="{d["ipin"]}"')
    text = text.replace("261e-12", d["lut"]).replace('max="0.3e-9"', f'max="{d["lut"]}"')
    return text.replace('max="0.01e-9"', f'max="{d["carry"]}"')


def docker(work, cmd):
    full = ["docker", "run", "--rm", "-u", "root", "--platform", "linux/amd64", "-v", f"{work}:/w",
            "-w", "/w", IMAGE, "bash", "-c", cmd]
    return subprocess.run(full, env=_docker_env(), capture_output=True, text=True)


def eblif(name):
    """the example's VPR netlist (vpr_run.write_eblif on the synthesised netlist); the
    sweep leaves pads unconstrained, so it does not depend on the grid's pad numbering"""
    path = os.path.join(OUT, "eblif", f"{name}.eblif")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import vpr_run
        text, _side, _fixed = vpr_run.prepare(name)
        open(path, "w").write(text)
    return path


def vpr(work, arch_text, name, device_name, width=None, rr=None):
    os.makedirs(work, exist_ok=True)
    open(os.path.join(work, "arch.xml"), "w").write(arch_text)
    shutil.copy(eblif(name), os.path.join(work, f"{name}.eblif"))
    args = [VPR, "arch.xml", f"{name}.eblif", "--device", device_name, "--seed", "1"] + FLAGS
    if width:
        args += ["--route_chan_width", str(width)]
    if rr:
        args += ["--read_rr_graph", "rr.xml"]
    r = docker(work, " ".join(a if re.fullmatch(r"[\w./:\-\[\]]+", a) else f"'{a}'" for a in args)
               + " > vpr.log 2>&1")
    log = open(os.path.join(work, "vpr.log")).read() if os.path.exists(os.path.join(work, "vpr.log")) else r.stderr

    def grab(pat, cast=float):
        m = re.search(pat, log)
        return cast(m.group(1)) if m else None
    res = {"routed": "successfully routed" in log,
           "min_w": grab(r"Best routing used a channel width factor of (\d+)", int),
           "wirelength": grab(r"Total wirelength: (\d+)", int),
           "cpd_ns": grab(r"Final critical path delay \(least slack\): ([\d.]+) ns"),
           "clbs": grab(r"\n\s*clb\s*:\s*(\d+)", int)}
    if not res["routed"]:
        m = re.search(r"(Failed to route|Unable to|Error.*)", log)
        res["why"] = m.group(0)[:200] if m else log.splitlines()[-1:]
    return res


def rrgraph(work, arch_text, device_name, width):
    os.makedirs(work, exist_ok=True)
    open(os.path.join(work, "arch.xml"), "w").write(arch_text)
    shutil.copy(os.path.join(HERE, "arch", "and2.blif"), work)
    docker(work, f"{VPR} arch.xml and2.blif --device {device_name} --route_chan_width {width} "
                 f"--timing_analysis off --write_rr_graph rr.xml > vpr.log 2>&1")
    path = os.path.join(work, "rr.xml")
    if not os.path.exists(path):
        raise RuntimeError(f"no rr graph in {work}: {open(os.path.join(work, 'vpr.log')).read()[-800:]}")
    with open(path, "rb") as src, gzip.open(path + ".gz", "wb") as dst:
        shutil.copyfileobj(src, dst)
    return path


def bits(dev):
    clb = [t for t in dev.tiles if t.kind == "grid" and dev.block_at.get((t.x, t.y)) is not None
           and dev.block_at[(t.x, t.y)].type == "clb"]
    tw = [t.width for t in clb]
    route = [sum(f.width for f in t.fields if f.group == "rr") for t in clb]
    n = dev.cluster["n"]
    return {"clb_fields": dev.tile_types["clb"].width, "clb_tile_mean": sum(tw) / len(tw),
            "route_per_tile": sum(route) / len(route),
            "per_lut": sum(tw) / len(tw) / n, "chain": dev.chain_width, "frames": dev.nframes,
            "clbs": len(clb), "luts": len(clb) * n,
            "xbar_inputs": len(dev.xbar_sources(0, 0)), "xbar_bits": dev.xbar_width(),
            "rr_muxes": sum(m.node in dev.rr.nodes for m in dev.muxes.values())}


def yosys(work, dev):
    """host LUTs / FFs of the generated fabric alone (cfg is an input: nothing folds)"""
    import fabric_gen
    gdir = os.path.join(work, "gen")
    os.makedirs(gdir, exist_ok=True)
    open(os.path.join(gdir, "bob_params.vh"), "w").write(dev.verilog_params())
    open(os.path.join(gdir, "bob_fabric.v"), "w").write(fabric_gen.fabric_verilog(dev))
    hw = os.path.join(ROOT, "hw", "src")
    files = [os.path.join(hw, p) for p in ("clb/lutk.sv", "clb/ble.sv", "fabric/bob_mux.v", "tiles/bram_core.v",
                                           "tiles/bram_block.v", "tiles/dsp_core.v", "tiles/dsp_block.v")]
    files.append(os.path.join(gdir, "bob_fabric.v"))
    log = os.path.join(work, "yosys.log")
    t0 = time.time()
    r = subprocess.run(["yosys", "-q", "-p", f"read_verilog -sv -D SYNTHESIS -I {gdir} {' '.join(files)}; "
                        "hierarchy -top bob_fabric; synth_xilinx -flatten -top bob_fabric; tee -o "
                        f"{work}/stat.txt stat"], capture_output=True, text=True)
    stat = open(os.path.join(work, "stat.txt")).read() if os.path.exists(os.path.join(work, "stat.txt")) else ""
    open(log, "w").write(r.stdout[-20000:] + r.stderr[-20000:])
    luts = sum(int(m) for m in re.findall(r"^\s+(\d+)\s+LUT\d", stat, re.M))
    ffs = sum(int(m) for m in re.findall(r"^\s+(\d+)\s+FD\w+", stat, re.M))
    muxf = sum(int(m) for m in re.findall(r"^\s+(\d+)\s+MUXF\d", stat, re.M))
    return {"luts": luts, "ffs": ffs, "muxf": muxf, "seconds": round(time.time() - t0)}


def run_config(tag, with_yosys):
    work = os.path.join(OUT, tag)
    res = {"tag": tag}
    if tag == "baseline":
        xml = baseline_xml()
        name = re.search(r'fixed_layout name="([^"]+)"', xml).group(1)
        res.update(n=1, xbar="-", grid="12x10 core (M16)")
        make_xml = lambda w: re.sub(r'chan_width="\d+"', f'chan_width="{w}"', xml)   # noqa: E731
    else:
        arch = arch_of(tag)
        c = arch["cluster"]
        res.update(n=c["n"], i=c["i"], xbar=c["xbar"], grid=f"{arch['nx']}x{arch['ny']} core")

        def make_xml(w):
            a = dict(arch, chan_width=w)
            return device.Device(arch=a, with_rr=False).arch_xml()
        name = device.Device(arch=arch, with_rr=False).name
    # 1. minimum channel width per example
    res["min_w"] = {}
    xml0 = make_xml(24)
    with ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(vpr, os.path.join(work, "minw", n), xml0, n, name): n for n in EXAMPLES}
        for f, n in futs.items():
            r = f.result()
            res["min_w"][n] = r["min_w"] if r["routed"] else None
            if not r["routed"]:
                res.setdefault("unroutable", {})[n] = r.get("why")
    need = max((w for w in res["min_w"].values() if w), default=24)       # the examples that fit
    W = max(2, 2 * math.ceil(need * MARGIN / 2))
    res["W"] = W
    # 2. rr graph at W -> exact configuration bits
    xml = make_xml(W)
    rr = rrgraph(os.path.join(work, "rr"), xml, name, W)
    if tag != "baseline":
        dev = device.Device(arch=dict(arch_of(tag), chan_width=W), rr_file=rr + ".gz")
        res["bits"] = bits(dev)
    else:
        dev = None
        res["bits"] = {"clb_fields": 71, "per_lut": None}
    # 3. every example on that graph
    res["route"] = {}
    with ThreadPoolExecutor(4) as ex:
        futs = {}
        for n in EXAMPLES:
            w2 = os.path.join(work, "route", n)
            os.makedirs(w2, exist_ok=True)
            shutil.copy(rr, os.path.join(w2, "rr.xml"))
            futs[ex.submit(vpr, w2, xml, n, name, W, True)] = n
        for f, n in futs.items():
            r = f.result()
            res["route"][n] = {k: r.get(k) for k in ("routed", "wirelength", "cpd_ns", "clbs", "why")}
            try:
                os.remove(os.path.join(work, "route", n, "rr.xml"))
            except OSError:
                pass
    if with_yosys and dev is not None:
        res["yosys"] = yosys(work, dev)
    json.dump(res, open(os.path.join(work, "result.json"), "w"), indent=1)
    return res


def _luts(path):
    try:
        s = open(path).read()
    except OSError:
        return None
    return sum(int(m) for m in re.findall(r"^\s+(\d+)\s+LUT\d", s, re.M)) or None


def tables():
    """The measured tables of docs/reports/M21/cluster_sweep.md, from build/sweep."""
    res = {}
    for t in ["baseline"] + [c[0] for c in CONFIGS] + list(EXTRA) + list(ROUND2):
        f = os.path.join(OUT, t, "result.json")
        if os.path.exists(f):
            res[t] = json.load(open(f))
            y = _luts(os.path.join(OUT, t, "stat.txt"))
            if y and not res[t].get("yosys"):
                res[t]["yosys"] = {"luts": y}
    base_y = _luts(os.path.join(OUT, "baseline_yosys", "stat.txt"))
    if "n10_full" in res and not res["n10_full"].get("yosys"):
        y = _luts(os.path.join(OUT, "n10_full_yosys", "stat.txt"))
        if y:
            res["n10_full"]["yosys"] = {"luts": y}
    show = ["big", "atspeed", "wide", "fir16"]
    L = []

    def row(t, r):
        b = r["bits"]
        y = (r.get("yosys") or {}).get("luts")
        luts = b.get("luts") or 100
        if t == "baseline":
            y = base_y
        cells = [t, str(r.get("n", "-")), str(r.get("i", 6 if t == "baseline" else "-")),
                 r.get("xbar", "-"), r.get("grid", ""), str(luts if t != "baseline" else 100),
                 str(r["W"]), f"{b.get('per_lut'):.0f}" if b.get("per_lut") else "149",
                 str(b.get("chain", 18560)), f"{y:,}" if y else "-", f"{y / luts:.0f}" if y else "-"]
        for n in show:
            v = r["route"].get(n, {})
            cells.append(f"{v['wirelength']} / {v['cpd_ns']:.0f}" if v.get("routed") else "does not fit")
        return "| " + " | ".join(cells) + " |"
    head = ("| config | N | I | crossbar | grid | LUTs | W | bits/LUT | chain bits | fabric host LUTs "
            "(yosys) | host LUTs / LUT | " + " | ".join(f"{n}: wirelength / critical path ns" for n in show) + " |")
    sep = "|" + "---|" * (11 + len(show))
    for title, tags in (("Round 1: about 350 LUTs", ["baseline"] + [c[0] for c in CONFIGS] + list(EXTRA)),
                        ("Round 2: about 200 LUTs, what the XC7Z020 can afford", ["baseline"] + list(ROUND2))):
        L += [f"### {title}", "", head, sep]
        L += [row(t, res[t]) for t in tags if t in res]
        L.append("")
    return "\n".join(L), res


def report():
    text = open(REPORT).read() if os.path.exists(REPORT) else "<!-- tables -->\n<!-- /tables -->\n"
    t, _res = tables()
    a, b = text.index("<!-- tables -->"), text.index("<!-- /tables -->")
    text = text[:a] + "<!-- tables -->\n" + t + "\n" + text[b:]
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    open(REPORT, "w").write(text)
    print(f"wrote {os.path.relpath(REPORT, ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--yosys", action="store_true")
    ap.add_argument("--report", action="store_true", help="only write the report from build/sweep")
    ap.add_argument("--yosys-only", action="store_true",
                    help="size the fabric of configurations already routed (build/sweep/<tag>)")
    args = ap.parse_args()
    tags = args.only or (["baseline"] + [c[0] for c in CONFIGS] + list(EXTRA))
    if args.report:
        report()
        return 0
    if args.yosys_only:
        def one(t):
            work = os.path.join(OUT, t)
            res = json.load(open(os.path.join(work, "result.json")))
            dev = device.Device(arch=dict(arch_of(t), chan_width=res["W"]),
                                rr_file=os.path.join(work, "rr", "rr.xml.gz"))
            res["yosys"] = yosys(work, dev)
            json.dump(res, open(os.path.join(work, "result.json"), "w"), indent=1)
            return t, res["yosys"]
        with ThreadPoolExecutor(2) as ex:
            for t, y in ex.map(one, [t for t in tags if t != "baseline"]):
                print(f"{t}: {y}", flush=True)
        return 0
    if not args.report:
        for t in tags:
            t0 = time.time()
            r = run_config(t, args.yosys)
            ok = sum(1 for v in r["route"].values() if v["routed"])
            print(f"{t}: W={r['W']} (min {max((w for w in r['min_w'].values() if w), default=0)}), "
                  f"bits/LUT {r['bits'].get('per_lut')}, routed {ok}/{len(r['route'])}, "
                  f"{r.get('yosys', '')} [{time.time() - t0:.0f}s]", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
