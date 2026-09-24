#!/usr/bin/env python3
"""
vpr_run.py - pack, place and route a synthesised bob netlist with VPR (M9).

  software/bob/vpr_run.py counter [--seed N]        -> build/vpr/<top>/

Input is software/bob/synth.py's build/synth/<top>/<top>.json. VPR (OpenFPGA's Docker
image, the same one that built the rr graph) runs on software/bob/arch/bob_k<K>.xml
and reads the COMMITTED rr graph (--read_rr_graph), so every route it finds is a
path through muxes the M7 bitstream really has.

What is handed to VPR (build/vpr/<top>/<top>.eblif) is the yosys netlist with the
few rewrites bob's fabric needs, so that VPR only sees what it can implement:

  constants        a constant on a CLB CE/SR, a BRAM/DSP pin, an adder A/B input
                   or an output pad is not a net: the pin is left open and the
                   constant goes to <top>.vpr.json, where fasm_from_vpr.py sets
                   that IPIN mux to const0/const1 (value 0/1). Constant LUT inputs
                   are folded into the truth table.
  carry chains     VPR places a chain as one macro up a CLB column (through the N
                   elements of each CLB, then the carry direct), so a chain is cut
                   to the column's element count. Each piece
                   starts with a generator (bob_add a = b = carry-in: sum bit 0,
                   cout = a) and, when the chain continues or its carry out is
                   used, ends in a tap (bob_add a = b = 0: sumout = cin). As in
                   M8's hand placer, the global USER1 cin never enters a design.
  flip-flops       BOB_FDRE / BOB_FDSE become bob_ff (FDRE vs FDSE is recorded in
                   <top>.vpr.json). The fabric's FF D is the LUT/adder output of
                   the same element, so when D is anything else (a pad, a net with
                   other loads) a buffer LUT is inserted (M21: two of those share an
                   element as a fractured LUT pair).
  outputs          a second output on the same net gets a buffer LUT.
  hard blocks      BOB_BRAM18 / BOB_DSP -> bob_bram / bob_dsp with the tile pin names.

Pins are fixed with --fix_clusters: sw[1:0], btn[3:0] and led[2:0] on the board
pads (device.json), clk on a spare pad (the user clock is global in bob; VPR's
ideal clock model does not route it either).
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "software", "host"))

import bitstream as B  # noqa: E402

IMAGE = "ghcr.io/lnis-uofu/openfpga-master:latest"
RESULTS = os.path.join(HERE, "vpr")                  # committed results: software/bob/vpr/<top>/
KEEP = ("eblif", "pins", "vpr.json", "net", "place", "route")
VPR = "/opt/openfpga/build/vtr-verilog-to-routing/vpr/vpr"
ARCH_DIR = os.path.join(HERE, "arch")
K = B.LUT_K
# the longest carry chain VPR can place: every element of every CLB up one column (M21)
COL_ROWS = len({y for _x, y in B.CLB_AT}) * B.CLB_N


class VprError(Exception):
    pass


def _param(cell, name, default=0):
    v = cell["parameters"].get(name)
    if v is None:
        return default
    if isinstance(v, str) and set(v) <= {"0", "1", "x", "z"}:
        return int(v.replace("x", "0").replace("z", "0"), 2)
    return int(v)


def atom(name):
    """a yosys cell name without this checkout's absolute path (so results commit)"""
    return name.replace(ROOT + "/", "")


def _const(b):
    """0 / 1 for a constant bit ("x"/"z" read 0), None for a net"""
    return None if isinstance(b, int) else (1 if b == "1" else 0)


# --- pins ------------------------------------------------------------------------------

BOARD_PIN_NAMES = {**{n: B.BOARD_IN[k] for k, n in enumerate(("SW0", "SW1", "BTN0", "BTN1", "BTN2", "BTN3"))},
                   **{f"LD{k}": pad for k, pad in enumerate(B.BOARD_OUT)}}


def board_pins(ports):
    """The examples' convention: sw[1:0] -> SW1..0, btn[3:0] -> BTN3..0, led[2:0] -> LD2..0."""
    pins = {}
    for pname, lo, n, board in (("sw", 0, 2, B.BOARD_IN), ("btn", 2, 4, B.BOARD_IN), ("led", 0, 3, B.BOARD_OUT)):
        for i in range(min(n, len(ports.get(pname, {}).get("bits", [])))):
            pins[f"{pname}[{i}]"] = board[lo + i]
    return pins


def read_pcf(path):
    """VPR / nextpnr style: `set_io <port bit> <pin>` per line, # comments. A pin is a
    board name (SW0 SW1 BTN0..BTN3 LD0..LD2) or pad<N> for any of the fabric's pads
    (reachable by boundary scan only)."""
    pins = {}
    for n, line in enumerate(open(path), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        f = line.split()
        if len(f) != 3 or f[0] != "set_io":
            raise VprError(f"{path}:{n}: expected `set_io <port> <pin>`")
        pin = f[2]
        if pin in BOARD_PIN_NAMES:
            pad = BOARD_PIN_NAMES[pin]
        elif re.fullmatch(r"pad\d+", pin) and int(pin[3:]) in B.PAD_XY:
            pad = int(pin[3:])
        else:
            raise VprError(f"{path}:{n}: unknown pin {pin} (board names {sorted(BOARD_PIN_NAMES)} or pad0..pad{B.NPAD - 1})")
        pins[f[1]] = pad
    return pins


# --- netlist -> VPR eblif ---------------------------------------------------------------

def write_eblif(top, mod, pin_map=None):
    """-> (eblif text, sidecar dict, io placement {block name: pad}). pin_map: {port
    bit name: pad}, default board_pins()."""
    cells = mod["cells"]
    ports = mod["ports"]
    L = []
    side = {"top": top, "lut": {}, "add": {}, "ff": {}, "bram": {}, "dsp": {},
            "consts": {}, "out_consts": {}, "has_clk": "clk" in ports}

    # constant propagation through LUTs (a LUT whose folded table is constant)
    const = {}
    luts = {n: c for n, c in cells.items() if c["type"] == "$lut"}
    changed = True
    while changed:
        changed = False
        for n, c in luts.items():
            y = c["connections"]["Y"][0]
            if y in const:
                continue
            ins = c["connections"]["A"]
            if all(_const(b) is not None or b in const for b in ins):
                a = sum((_const(b) if _const(b) is not None else const[b]) << i for i, b in enumerate(ins))
                const[y] = (_param(c, "LUT") >> a) & 1
                changed = True

    def cval(b):
        """constant value of bit b, or None"""
        return _const(b) if _const(b) is not None else const.get(b)

    # loads
    loads = {}
    for n, c in cells.items():
        for p, bits in c["connections"].items():
            if c["port_directions"][p] == "input":
                for b in bits:
                    if isinstance(b, int):
                        loads[b] = loads.get(b, 0) + 1
    out_bits = []
    for pname, p in ports.items():
        if p["direction"] == "output":
            for i, b in enumerate(p["bits"]):
                out_bits.append((pname, i, b))
                if isinstance(b, int):
                    loads[b] = loads.get(b, 0) + 1

    def pname_bit(pname, i, width):
        return pname if width == 1 and pname == "clk" else f"{pname}[{i}]"

    name = {}
    for pname, p in ports.items():
        if p["direction"] == "input":
            for i, b in enumerate(p["bits"]):
                name[b] = pname_bit(pname, i, len(p["bits"]))
    driver = {}
    for n, c in cells.items():
        for p, bits in c["connections"].items():
            if c["port_directions"][p] == "output":
                for i, b in enumerate(bits):
                    driver[b] = (n, p, i)

    def N(b):
        return name.setdefault(b, f"n{b}")

    buffers = []                                   # (src net, dst net)
    outputs = []
    for pname, i, b in out_bits:
        oname = f"{pname}[{i}]"
        if cval(b) is not None or b not in driver and b not in name:
            side["out_consts"][oname] = cval(b) or 0
            continue
        if b not in name and b in driver:
            name[b] = oname
        elif name.get(b) != oname:
            buffers.append((N(b), oname))
        outputs.append(oname)

    # --- carry chains -----------------------------------------------------------
    adds = {n for n, c in cells.items() if c["type"] == "BOB_ADD"}
    ci_from = {}
    for a in adds:
        d = driver.get(cells[a]["connections"]["CI"][0])
        if d and d[0] in adds and d[1] == "CO":
            ci_from[a] = d[0]
    nxt = {v: k for k, v in ci_from.items()}
    body = []
    fresh = [0]
    tap_bits = {}

    def new(prefix):
        fresh[0] += 1
        return f"{prefix}{fresh[0]}"

    def add_line(name, a=None, b=None, cin=None, cout=None, sumout=None, inv=0, consts=None):
        pins = [f"{p}={v}" for p, v in (("a", a), ("b", b), ("cin", cin), ("cout", cout),
                                         ("sumout", sumout)) if v is not None]
        body.append(f".subckt bob_add {' '.join(pins)}")
        body.append(f".cname {atom(name)}")
        side["add"][atom(name)] = {"inv": inv}
        if consts:
            side["consts"][atom(name)] = consts

    def ab(bit):
        """(net name or None, const or None) for an adder data input"""
        v = cval(bit)
        return (None, v) if v is not None else (N(bit), None)

    for head in sorted(a for a in adds if a not in ci_from):
        chain = [head]
        while chain[-1] in nxt:
            chain.append(nxt[chain[-1]])
        for i, a in enumerate(chain[:-1]):
            if loads.get(cells[a]["connections"]["CO"][0], 0) > 1:
                raise VprError(f"{a}: a carry out used inside a chain is not supported")
        last_co = cells[chain[-1]]["connections"]["CO"][0]
        last_co_used = loads.get(last_co, 0) > 0
        ci = cells[head]["connections"]["CI"][0]
        carry_in = ab(ci)                                     # (net, const)
        i = 0
        while i < len(chain):
            rest = len(chain) - i
            if rest + 1 <= COL_ROWS and not (last_co_used and rest + 2 > COL_ROWS):
                take = chain[i:]
            else:
                take = chain[i:i + COL_ROWS - 2]
            i += len(take)
            gen = new("bob_gen")
            gco = new("cy")
            net, v = carry_in
            add_line(gen, a=net, b=net, cout=gco,
                     consts={"a": v, "b": v} if v is not None else None)
            cin = gco
            for k, a in enumerate(take):
                c = cells[a]["connections"]
                an, av = ab(c["A"][0])
                bn, bv = ab(c["B"][0])
                o = c["O"][0]
                co = new("cy") if (k + 1 < len(take) or i < len(chain) or last_co_used) else None
                consts = {p: v for p, v in (("a", av), ("b", bv)) if v is not None}
                add_line(a, a=an, b=bn, cin=cin, cout=co,
                         sumout=N(o) if loads.get(o, 0) else None,
                         inv=_param(cells[a], "INV_B"), consts=consts or None)
                cin = co
            if i < len(chain) or last_co_used:
                tap = new("bob_tap")
                out = N(last_co) if i >= len(chain) else new("cy")
                tap_bits[out] = cells[take[-1]]["connections"]["CO"][0]
                add_line(tap, cin=cin, sumout=out)
                carry_in = (out, None)

    # --- LUTs -------------------------------------------------------------------------
    for n in sorted(luts):
        c = luts[n]
        y = c["connections"]["Y"][0]
        if y in const or not loads.get(y, 0):
            continue
        ins, uniq = c["connections"]["A"], []
        for b in ins:
            if cval(b) is None and b not in uniq:
                uniq.append(b)
        tt = 0
        for a in range(1 << len(uniq)):
            full = 0
            for j, b in enumerate(ins):
                v = cval(b)
                bit = v if v is not None else (a >> uniq.index(b)) & 1
                full |= bit << j
            tt |= ((_param(c, "LUT") >> full) & 1) << a
        side["lut"][N(y)] = {"n": len(uniq), "tt": tt}
        body.append(f".names {' '.join(N(b) for b in uniq)} {N(y)}")
        for a in range(1 << len(uniq)):
            if (tt >> a) & 1:
                body.append("".join(str((a >> j) & 1) for j in range(len(uniq))) + " 1")

    # --- flip-flops ---------------------------------------------------------------------
    clk_used = False
    for n in sorted(x for x, c in cells.items() if c["type"] in ("BOB_FDRE", "BOB_FDSE")):
        c = cells[n]
        conn = c["connections"]
        fdse = c["type"] == "BOB_FDSE"
        d, ce, sr = conn["D"][0], conn["CE"][0], conn["S" if fdse else "R"][0]
        if conn["C"][0] != ports.get("clk", {}).get("bits", [None])[0]:
            raise VprError(f"{n}: clocked by something other than the clk port")
        if cval(d) is not None:
            raise VprError(f"{n}: constant D is not supported")
        if cval(ce) == 0 or cval(sr) == 1:
            raise VprError(f"{n}: CE tied 0 / SR tied 1 is not supported")
        drv = driver.get(d)
        direct = (drv is not None and loads.get(d, 0) == 1 and
                  ((cells[drv[0]]["type"] == "$lut") or
                   (cells[drv[0]]["type"] == "BOB_ADD" and drv[1] == "O")))
        dnet = N(d)
        if not direct:
            buf = new("ffd")
            buffers.append((dnet, buf))
            dnet = buf
        q = conn["Q"][0]
        pins = [f"D={dnet}", f"C={N(conn['C'][0])}", f"Q={N(q)}"]
        if cval(ce) is None:
            pins.append(f"CE={N(ce)}")
        if cval(sr) is None:
            pins.append(f"SR={N(sr)}")
        body.append(f".subckt bob_ff {' '.join(pins)}")
        body.append(f".cname {atom(n)}")
        side["ff"][atom(n)] = {"rstval": int(fdse), "ce": cval(ce) is None, "sr": cval(sr) is None}
        clk_used = True

    # --- hard blocks --------------------------------------------------------------------
    for n in sorted(x for x, c in cells.items() if c["type"] == "BOB_BRAM18"):
        c = cells[n]
        conn = c["connections"]
        pins, consts = [f"clk={N(conn['CLK'][0])}"], {}
        for p in "ab":
            P = p.upper()
            for yname, bname in (("ADDR", "addr"), ("DI", "di"), ("WE", "we"), ("EN", "en"), ("RST", "rst")):
                for k, b in enumerate(conn[f"{P}_{yname}"]):
                    pin = f"{bname}_{p}[{k}]"
                    if cval(b) is None:
                        pins.append(f"{pin}={N(b)}")
                    else:
                        consts[pin] = cval(b)
            for k, b in enumerate(conn[f"{P}_DO"]):
                if loads.get(b, 0):
                    pins.append(f"do_{p}[{k}]={N(b)}")
        body.append(f".subckt bob_bram {' '.join(pins)}")
        body.append(f".cname {atom(n)}")
        init = _param(c, "INIT")
        side["bram"][atom(n)] = {"wmode_a": _param(c, "WMODE_A", 1), "wmode_b": _param(c, "WMODE_B", 1),
                           "contents": [(init >> (18 * i)) & 0x3FFFF for i in range(1024)]}
        side["consts"][atom(n)] = consts
        clk_used = True
    for n in sorted(x for x, c in cells.items() if c["type"] == "BOB_DSP"):
        c = cells[n]
        conn = c["connections"]
        pins, consts = [], {}
        for bus in ("A", "B"):
            for k, b in enumerate(conn[bus]):
                pin = f"{bus.lower()}[{k}]"
                if cval(b) is None:
                    pins.append(f"{pin}={N(b)}")
                else:
                    consts[pin] = cval(b)
        for k, b in enumerate(conn["P"]):
            if loads.get(b, 0):
                pins.append(f"p[{k}]={N(b)}")
        if "clk" in ports:                     # VPR's model is clocked; bob's opmode M is not
            pins.append("clk=clk")
        body.append(f".subckt bob_dsp {' '.join(pins)}")
        body.append(f".cname {atom(n)}")
        side["dsp"][atom(n)] = {"opmode": "M"}
        side["consts"][atom(n)] = consts

    for src, dst in buffers:
        side["lut"][dst] = {"n": 1, "tt": 0b10}
        body.append(f".names {src} {dst}")
        body.append("1 1")

    # --- header: only inputs something uses --------------------------------------------
    inputs = []
    used = set()
    for line in body:
        if line.startswith(".subckt"):
            used.update(t.split("=", 1)[1] for t in line.split()[2:])
        elif line.startswith(".names"):
            used.update(line.split()[1:-1])
    for pname, p in ports.items():
        if p["direction"] == "input":
            for i, b in enumerate(p["bits"]):
                if name[b] in used:
                    inputs.append(name[b])
    # No paths in this header: its text is hashed into the committed result's stamp,
    # so a path here means moving a folder invalidates a route that did not change.
    L.append(f"# GENERATED from the yosys netlist of {top} - do not edit")
    L.append(f".model {top}")
    L.append(".inputs " + " ".join(inputs))
    L.append(".outputs " + " ".join(outputs))
    L.extend(body)
    L.append(".end")

    # --- pin constraints --------------------------------------------------------------------
    pin_map = pin_map or board_pins(ports)
    fixed = {}
    for net in inputs:
        if net == "clk" and net not in pin_map:
            spare = [p for p in sorted(B.PAD_XY) if p not in B.BOARD_IN and p not in B.BOARD_OUT]
            fixed[net] = spare[0]
        elif net in pin_map:
            fixed[net] = pin_map[net]
        else:
            raise VprError(f"input {net} has no pin (pcf set_io)")
    for net in list(outputs) + list(side["out_consts"]):
        if net not in pin_map:
            raise VprError(f"output {net} has no pin (pcf set_io)")
        if net in outputs:
            fixed["out:" + net] = pin_map[net]
    side["out_pads"] = {net: pin_map[net] for net in side["out_consts"]}
    used = list(fixed.values())
    dup = sorted({p for p in used if used.count(p) > 1})
    if dup:
        raise VprError(f"pads {dup} are assigned to more than one port")

    # which yosys bit each VPR net carries (CAPTURE comparisons against golden.py)
    bit_of = {nm: b for b, nm in name.items() if isinstance(b, int)}
    for src, dst in buffers:
        bit_of.setdefault(dst, bit_of.get(src))
    bit_of.update(tap_bits)
    side["net_bits"] = {nm: b for nm, b in sorted(bit_of.items()) if b is not None}
    return "\n".join(L) + "\n", side, fixed


# --- running VPR ---------------------------------------------------------------------

def _docker_env():
    env = dict(os.environ)
    sock = os.path.expanduser("~/.colima/default/docker.sock")
    if "DOCKER_HOST" not in env and os.path.exists(sock):
        env["DOCKER_HOST"] = f"unix://{sock}"
    return env


def prepare(top, pcf=None):
    """build/synth/<top>/<top>.json (+ optional .pcf) -> (eblif text, sidecar, fixed pins)"""
    jpath = os.path.join(ROOT, "build", "synth", top, f"{top}.json")
    if not os.path.exists(jpath):
        raise VprError(f"{os.path.relpath(jpath, ROOT)} missing: run software/bob/equiv.py work/examples/{top}/{top}.v")
    pin_map = read_pcf(pcf) if pcf else None
    return write_eblif(top, json.load(open(jpath))["modules"][top], pin_map)


def arch_sha():
    return hashlib.sha256(open(os.path.join(ARCH_DIR, f"bob_k{K}.xml"), "rb").read()).hexdigest()


def run(top, seed=1, work=None, pcf=None, name=None):
    """synth JSON -> eblif -> VPR in Docker. Files are <name>.* (name defaults to top) in
    the work directory (default build/vpr/<name>), which is returned."""
    name = name or top
    eblif, side, fixed = prepare(top, pcf)
    work = work or os.path.join(ROOT, "build", "vpr", name)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    arch = os.path.join(ARCH_DIR, f"bob_k{K}.xml")
    shutil.copy(arch, os.path.join(work, "arch.xml"))
    with gzip.open(os.path.join(ARCH_DIR, f"bob_k{K}_rr.xml.gz"), "rb") as src, \
            open(os.path.join(work, "rr.xml"), "wb") as dst:
        shutil.copyfileobj(src, dst)
    open(os.path.join(work, f"{name}.eblif"), "w").write(eblif)
    with open(os.path.join(work, f"{name}.pins"), "w") as fh:
        fh.write("# fixed I/O: block x y subblk (software/bob/vpr_run.py)\n")
        for blk, pad in sorted(fixed.items()):
            x, y = B.PAD_XY[pad]
            fh.write(f"{blk}\t{x}\t{y}\t0\n")
    side["pins"] = fixed
    side["pcf"] = os.path.relpath(pcf, ROOT) if pcf else None
    json.dump(side, open(os.path.join(work, f"{name}.vpr.json"), "w"), indent=0)

    text = open(arch).read()
    device = re.search(r'fixed_layout name="([^"]+)"', text).group(1)
    width = re.search(r'chan_width="(\d+)"', text).group(1)
    args = [VPR, "arch.xml", f"{name}.eblif", "--device", device, "--route_chan_width", width,
            "--read_rr_graph", "rr.xml", "--fix_clusters", f"{name}.pins", "--seed", str(seed),
            "--absorb_buffer_luts", "off", "--const_gen_inference", "none",
            "--sweep_dangling_primary_ios", "off", "--sweep_dangling_nets", "off",
            "--sweep_dangling_blocks", "off", "--sweep_constant_primary_outputs", "off",
            "--pack", "--place", "--route", "--analysis"]
    cmd = ["docker", "run", "--rm", "-u", "root", "--platform", "linux/amd64",
           "-v", f"{work}:/w", "-w", "/w", IMAGE, "bash", "-c",
           " ".join(a if re.fullmatch(r"[\w./:\-\[\]]+", a) else f"'{a}'" for a in args) + " > vpr.log 2>&1"]
    open(os.path.join(work, "command.txt"), "w").write(" ".join(["vpr"] + args[1:]) + "\n")
    try:
        subprocess.run(cmd, env=_docker_env(), check=False, capture_output=True)
    except FileNotFoundError:
        raise VprError("docker not found (VPR runs in OpenFPGA's image; `colima start`)")
    os.remove(os.path.join(work, "rr.xml"))                  # 6 MB; the .gz is committed
    logf = os.path.join(work, "vpr.log")
    log = open(logf).read() if os.path.exists(logf) else ""
    if "successfully routed" not in log:
        tail = re.findall(r"Error \d+:[\s\S]*?Message:.*", log) or log.splitlines()[-15:] or ["no vpr.log: is Docker running?"]
        raise VprError(f"VPR failed on {name}:\n" + "\n".join(tail))
    return work


ROUTE_TRIES = 4


def run_retry(top, seed=1, work=None, pcf=None, name=None, tries=ROUTE_TRIES):
    """run(), and when only the router gave up, again with the next seeds: a placement that
    leaves a few wires overused at 50 iterations routes with another one (M24: fir16 with
    Double Duty's denser packing, 9 overused nodes on seed 1, every seed 2-5 routes).
    -> (work, the seed that routed)"""
    for s in range(seed, seed + tries):
        try:
            return run(top, s, work, pcf, name), s
        except VprError as e:
            if "Routing failed" not in open(os.path.join(work or os.path.join(ROOT, "build", "vpr",
                                                                               name or top), "vpr.log")).read() \
                    or s == seed + tries - 1:
                raise
            print(f"  {name or top}: seed {s} did not route, trying seed {s + 1}", flush=True)
    raise VprError("unreachable")


def commit(top, work, seed, name=None, pcf=None):
    """copy the result VPR produced into software/bob/vpr/<name>/ (committed, so the
    rest of the flow - FASM, chain, simulations, hwtest - needs no Docker). name
    defaults to top; a design routed with a .pcf gets its own name."""
    name = name or top
    dst = os.path.join(RESULTS, name)
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst)
    for ext in KEEP:
        text = open(os.path.join(work, f"{name}.{ext}")).read()
        if ext == "net":                              # VPR writes its own run's absolute paths
            text = re.sub(r'(architecture_id|atom_netlist_id)="[^"]*"', r'\1=""', text)
        open(os.path.join(dst, f"{name}.{ext}"), "w").write(text)
    s = summary(work, name)
    digest = subprocess.run(["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", IMAGE],
                            env=_docker_env(), capture_output=True, text=True).stdout.strip() or IMAGE
    with open(os.path.join(dst, "stamp.txt"), "w") as fh:
        fh.write(f"top {top}\n")
        fh.write(f"pcf {os.path.relpath(pcf, ROOT) if pcf else '-'}\n")
        fh.write(f"arch_sha256 {arch_sha()}\n")
        fh.write(f"eblif_sha256 {hashlib.sha256(open(os.path.join(dst, name + '.eblif'), 'rb').read()).hexdigest()}\n")
        fh.write(f"seed {seed}\n")
        fh.write(f"image {digest}\n")
        fh.write("command " + open(os.path.join(work, "command.txt")).read())
        for key in ("wirelength", "cpd_ns", "fmax_mhz", "result_sha"):
            fh.write(f"{key} {s[key]}\n")
    return dst


def read_stamp(name):
    path = os.path.join(RESULTS, name, "stamp.txt")
    if not os.path.exists(path):
        return None
    return dict(l.split(" ", 1) for l in open(path).read().splitlines() if " " in l)


def stale(name):
    """None if software/bob/vpr/<name>/ was routed from today's netlist, pins and
    architecture, else why not"""
    stamp = read_stamp(name)
    if stamp is None:
        return f"no committed VPR result for {name}: run `make vpr` (Docker)"
    if stamp.get("arch_sha256") != arch_sha():
        return f"software/bob/vpr/{name} was routed on a different architecture: run `make vpr` (Docker)"
    pcf = stamp.get("pcf", "-")
    eblif, _side, _fixed = prepare(stamp.get("top", name), None if pcf == "-" else os.path.join(ROOT, pcf))
    if hashlib.sha256(eblif.encode()).hexdigest() != stamp.get("eblif_sha256"):
        return f"software/bob/vpr/{name} was routed from a different netlist or pins: run `make vpr` (Docker)"
    return None


def summary(work, top):
    """wirelength, critical path, block counts and a hash of the result files"""
    log = open(os.path.join(work, "vpr.log")).read()

    def grab(pat):
        m = re.search(pat, log)
        return m.group(1) if m else "?"

    h = hashlib.sha256()
    for ext in ("net", "place", "route"):
        text = open(os.path.join(work, f"{top}.{ext}")).read()
        text = "\n".join(l for l in text.splitlines() if not l.startswith(("Netlist_File", "Placement_File")))
        text = re.sub(r'architecture_id="[^"]*"|atom_netlist_id="[^"]*"|name="[^"]*\.net"', "", text)
        h.update(text.encode())
    return {
        "wirelength": grab(r"Total wirelength: (\d+)"),
        "cpd_ns": grab(r"Final critical path delay \(least slack\): ([\d.]+) ns"),
        "fmax_mhz": grab(r"Fmax: ([\d.]+) MHz"),
        "clbs": grab(r"\bclb\s*:\s*(\d+)"),
        "result_sha": h.hexdigest()[:16],
    }


EXAMPLES = ["gates", "adder", "counter", "blinky", "ram", "mult", "switches", "fir", "wide", "big", "atspeed",
            "fir16"]
# results routed with a pin file: name -> (top, pcf). gates_swapped proves .pcf pins reach the pads.
VARIANTS = {"gates_swapped": ("gates", os.path.join(ROOT, "work", "examples", "gates", "gates_swapped.pcf"))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tops", nargs="*", help=f"default: every example and variant "
                                              f"({' '.join(EXAMPLES + list(VARIANTS))})")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-commit", action="store_true", help="leave the result in build/vpr only")
    ap.add_argument("--repeat", action="store_true", help="route twice with the seed; results must match")
    args = ap.parse_args()
    fails = 0
    for name in args.tops or EXAMPLES + list(VARIANTS):
        top, pcf = VARIANTS.get(name, (name, None))
        try:
            work, seed = run_retry(top, args.seed, pcf=pcf, name=name)
            s = summary(work, name)
            again = f" (seed {seed})" if seed != args.seed else ""
            if args.repeat:
                s2 = summary(run(top, seed, work + "_repeat", pcf, name), name)
                again += ", same seed repeats: " + ("yes" if s2["result_sha"] == s["result_sha"] else "NO")
                fails += s2["result_sha"] != s["result_sha"]
            where = os.path.relpath(work if args.no_commit else commit(top, work, seed, name, pcf), ROOT)
        except VprError as e:
            print(f"FAIL  {name}: {e}")
            fails += 1
            continue
        print(f"PASS  {name}: routed, wirelength {s['wirelength']}, critical path {s['cpd_ns']} ns "
              f"(Fmax {s['fmax_mhz']} MHz), result {s['result_sha']}{again} -> {where}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
