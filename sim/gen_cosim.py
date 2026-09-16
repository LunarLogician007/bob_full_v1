#!/usr/bin/env python3
"""
Generate build/cosim/cosim_designs.vh for sim/tb_cosim.v (M10 golden co-simulation).

For every example and pin variant: `bob build` (tools/bob/cli.py: yosys -> source ==
netlist == golden -> VPR result -> FASM -> bits -> .bit), then the testbench is
given, per design:
  - the SOURCE Verilog and the golden netlist (tools/bob/golden.py) instantiated
    live, each with its own clock - not a recorded trace
  - the chain and BRAM contents read back from the .bit file, loaded into the
    complete FPGA RTL through CFG_IN / USER4
  - fresh biased random input vectors (tools/bob/equiv.py, a different seed from
    the trace the build checked), as the source sees them and as the board pads
    see them through the design's pins
  - the CAPTURE map: which CLB holds which golden register bit

  sim/gen_cosim.py [--cycles N]
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "tools", "bob"))

import bitstream as B       # noqa: E402
import bitgen               # noqa: E402
import cli                  # noqa: E402
import equiv                # noqa: E402
import fasm_from_vpr as FV  # noqa: E402
import vpr_run              # noqa: E402
from chainbits import crc32c_bits  # noqa: E402

OUT_DIR = os.path.join(ROOT, "build", "cosim")
SEED = 2026                 # the build's trace uses seed 1


def designs():
    out = [(n, n, None) for n in vpr_run.EXAMPLES]
    out += [(n, top, pcf) for n, (top, pcf) in vpr_run.VARIANTS.items()]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=100)
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    W = B.CHAIN_W
    decl, mux, clk_on, runs, sources = [], [], [], [], set()
    for k, (name, top, pcf) in enumerate(designs()):
        src = os.path.join(ROOT, "examples", f"{top}.v")
        bit = os.path.join(OUT_DIR, f"{name}.bit")
        cli.build([src], top, pcf, bit, name=name, log=lambda *_: None)
        c = bitgen.read_bit(bit)
        sources.add(src)
        sources.add(os.path.join(ROOT, "build", "synth", top, f"{top}_golden.v"))
        mod = json.load(open(os.path.join(ROOT, "build", "synth", top, f"{top}.json")))["modules"][top]
        ports = {n: len(p["bits"]) for n, p in mod["ports"].items()}
        work = os.path.join(vpr_run.RESULTS, name)
        side = json.load(open(os.path.join(work, f"{name}.vpr.json")))
        pins = side["pins"]

        # instances: source and golden, own clock, inputs in the examples' convention
        decl.append(f"    // ---- {k}: {name}")
        decl.append(f"    reg clk_{k} = 1'b0;")
        decl.append(f"    wire [2:0] s_led_{k}, g_led_{k};")
        conn = []
        if "clk" in ports:
            conn.append(f".clk(clk_{k})")
        if "sw" in ports:
            conn.append(f".sw(src_in[{ports['sw'] - 1}:0])")
        if "btn" in ports:
            conn.append(f".btn(src_in[{2 + ports['btn'] - 1}:2])")
        for inst, led in (("", f"s_led_{k}"), ("_golden", f"g_led_{k}")):
            wires = conn + [f".led({led}[{ports['led'] - 1}:0])"]
            decl.append(f"    {top}{inst} u_{'gold' if inst else 'src'}_{k} ({', '.join(wires)});")
        if ports["led"] < 3:
            decl.append(f"    assign s_led_{k}[2:{ports['led']}] = 0; assign g_led_{k}[2:{ports['led']}] = 0;")

        # source LED k -> board LED j through the pins
        def board_leds(v):
            bits = ["1'b0"] * 3
            for i in range(ports["led"]):
                pad = pins.get(f"out:led[{i}]", side.get("out_pads", {}).get(f"led[{i}]"))
                if pad is not None and pad in B.BOARD_OUT:
                    bits[B.BOARD_OUT.index(pad)] = f"{v}[{i}]"
            return "{" + ", ".join(reversed(bits)) + "}"

        cmap = FV.capture_map(name)
        cap = ["1'b0"] * B.NCLB
        mask = 0
        for idx, nbit in cmap:
            cap[idx] = f"u_gold_{k}.n{nbit}"
            mask |= 1 << idx
        mux.append(f"            {k}: begin exp_led = {board_leds(f's_led_{k}')}; "
                   f"gld_led = {board_leds(f'g_led_{k}')};")
        mux.append(f"                cap_exp = {{{', '.join(reversed(cap))}}}; cap_mask = {B.NCLB}'h{mask:x}; end")
        clk_on.append(f"            {k}: clk_{k} = v;")

        # stimulus: source view and board view of the same vector
        vec_ports = {n: ("input", w) for n, w in ports.items()}
        vectors = equiv.random_vectors(vec_ports, args.cycles, SEED + k)
        runs.append(f"    // ---- {name}: {len(cmap)} registers on CAPTURE, pins {os.path.relpath(pcf, ROOT) if pcf else 'default'}")
        runs.append(f'    dname = "{name}"; cur = {k};')
        runs.append(f"    cfgw   = {W}'h{c['word']:0{(W + 3) // 4}x};")
        runs.append(f"    cfgcrc = 32'h{crc32c_bits(c['word'], W):08x};")
        runs.append("    commit_config;")
        for b, words in sorted(c["brams"].items()):
            for a, w in enumerate(words):
                if w:
                    runs.append(f"    bram_poke(4'd{b}, 10'd{a}, 18'h{w:05x});")
        runs.append("    start;")
        for v in vectors:
            sv = equiv.board_vector(v)
            bv = 0
            for i in range(ports.get("sw", 0)):
                pad = pins.get(f"sw[{i}]")
                if pad is not None:
                    bv |= ((sv >> i) & 1) << B.BOARD_IN.index(pad)
            for i in range(ports.get("btn", 0)):
                pad = pins.get(f"btn[{i}]")
                if pad is not None:
                    bv |= ((sv >> (2 + i)) & 1) << B.BOARD_IN.index(pad)
            runs.append(f"    cos_vec(6'b{sv:06b}, 6'b{bv:06b});")
        runs.append("    finish_design;")

    text = ["// build/cosim/cosim_designs.vh - GENERATED by sim/gen_cosim.py, do not edit.", ""]
    text += decl
    text += ["", "    always @* begin", "        exp_led = 3'b0; gld_led = 3'b0; cap_exp = 0; cap_mask = 0;",
             "        case (cur)"] + mux + ["            default: ;", "        endcase", "    end", "",
                                           "    task src_clock(input v);", "        case (cur)"] + clk_on + [
             "            default: ;", "        endcase", "    endtask", "",
             "    task run_cosim;", "    begin"] + runs + ["    end", "    endtask", ""]
    open(os.path.join(OUT_DIR, "cosim_designs.vh"), "w").write("\n".join(text))
    open(os.path.join(OUT_DIR, "sources.txt"), "w").write("\n".join(sorted(sources)) + "\n")
    print(f"wrote build/cosim/cosim_designs.vh: {len(designs())} designs x {args.cycles} cycles "
          f"(source and golden netlist live, chains from .bit files)")


if __name__ == "__main__":
    main()
