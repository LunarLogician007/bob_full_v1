# bob — an FPGA built inside an FPGA (PYNQ-Z2)

bob is a complete FPGA written in Verilog and running in the PL of a Zynq XC7Z020 (PYNQ-Z2):
- **Logic:** CLBs (LUT6 + carry + flip-flop), UG473-style BRAMs and UG479-style DSP slices.
- **Routing:** generated from VPR's routing-resource graph.
- **Configuration:** a CRC-checked JTAG scan chain.
- **Pads:** a boundary-scan ring.

A Raspberry Pi Pico running DirtyJTAG on PMODA configures it from a Mac.

**Try it:** `./host/studio.py --probe fake` opens **bob studio** at `http://127.0.0.1:8765` —
an EDA tool for this FPGA, laid out the way Vivado is. Write Verilog, run Synthesis,
Implementation and Generate Bitstream, watch each stage report what it measured, see the
design land on the real floorplan, then program a board and watch the LEDs. `--probe fake`
runs the whole thing against the board in software ([`software/host/fakeboard.py`](software/host/fakeboard.py)),
so it works with no hardware attached.

**Start here:** [`guide.html`](guide.html) / [`docs/project/GUIDE.md`](docs/project/GUIDE.md) explain every part — what it is, why it is built that way, how to use it and how to tweak it — and compare bob with OpenFPGA, Aegis and ZUMA. [`project.html`](project.html) / [`docs/project/REPORT.md`](docs/project/REPORT.md) are the project report: what was built, measured and learned. [`arch.html`](arch.html) is the interactive die slice.

For the working plan, conventions, gotchas and every milestone, read [`PLAN.md`](PLAN.md); the live state and next steps are in [`HANDOFF.md`](HANDOFF.md); the short agent rules are in [`CLAUDE.md`](CLAUDE.md).

## Where it stands (2026-09-18)

M0–M15 passed on the board. **M16 (10 × 10 CLBs = 100 CLBs, 18 560 configuration bits) is built and simulated** — RTL, routing graph, VPR and Python PnR results, and every simulation are green; the Vivado build and `make hwtest M=M16` are pending (`docs/hwtest/M16.md`, `HANDOFF.md`).

| Milestone | What | Status |
|---|---|---|
| M0–M6 | layout, device description, scan-chain config plane, 4×4 fabric, user clock, BRAM, DSP | passed on the board |
| **M7** | fabric generated from VPR's rr graph, **16-CLB board profile** | **passed on the board 2026-09-17** (26/26); timing hardening planned for the next rebuild |
| M8 | yosys synthesis onto bob cells → placed → runs on the fabric | **passed on the board 2026-09-17** (10/10, no rebuild) |
| M9 | VPR packs, places and routes the examples → FASM → chain | **passed on the board 2026-09-17** (10/10, no rebuild) |
| M10 | bitgen (FASM ⇄ chain, `.bit`), `bob build`/`bob load`, `.pcf` pins, golden co-simulation | **passed on the board 2026-09-17** (7/7, no rebuild) |
| M11 | real designs live on the board (free-running clock, real switches): switches, FIR on DSPs, RAM readback, blinky rate | **passed on the board 2026-09-17** (12/12, no rebuild) |
| M12 | bob's own Python pack/place/route (`--pnr python`), 0.99× VPR's wirelength; M12b smaller configuration store → 36-CLB grid | **M12a passed on the board 2026-09-17** (13/13, no rebuild); M12b **passed on the board** in the M15 build |
| M13 | frame-based configuration (UG470 packets on CFG_IN/CFG_OUT) next to the kept chain (CHAIN_IN/CHAIN_OUT), M7 timing fixed | **passed on the board 2026-09-17** (39/39, timing closes: WNS +0.877 ns) |
| M14 | partial reconfiguration of a running design (`bob load --partial`) | **passed on the board 2026-09-17** (in the M15 build) |
| M15 | BRAM contents as frames: one CRC-covered stream for the whole design | **passed on the board 2026-09-17** (48/48, WNS +0.585 ns, 10 411 LUTs) |
| M16 | the 10 × 10 CLB grid: 100 CLBs, 145 frames, new 56-CLB example | built and simulated 2026-09-18; **Vivado build + board test pending** |

After M7 the Vivado bitstream stayed the same through M11: those milestones only load new configuration chains over JTAG. M12a (Python PnR) needed no rebuild either. M15 (IDCODE `0xEBEEF093`), carrying M12b, M14 and M15, is on the board.

## The device

Generated from `software/bob/device.json` by `software/bob/devtable.py`; `tests/test_device_table.py` fails if it drifts.

<!-- device:begin -->

| | |
|---|---|
| VPR grid | 14 × 12 (12 × 10 core inside an I/O ring, corners empty) |
| CLBs | 100 (columns x = 1, 2, 4, 5, 6, 7, 9, 10, 11, 12; one BLE each: LUT6 O6/O5, MUXCY/XORCY carry, FDRE/FDSE) |
| BRAM | 2 × 1024×18 true dual port (column x = 3, 5 rows tall); contents as frames (FAR type 001) or over USER4 |
| DSP | 2 × DSP48E1-style slices (column x = 8, 5 rows tall), PCOUT→PCIN cascade |
| I/O | 44 pads; board switches, buttons and LEDs on fixed pads, LD3 = DONE |
| Routing | L4 unidirectional, W = 24, Wilton Fs = 3 (from OpenFPGA's k6_frac_N10 tileable arch); 3391 muxes |
| Configuration | 18560 bits = 145 frames of 4 × 32; UG470-style packets on CFG_IN/CFG_OUT (CRC-32C, IDCODE, partial reconfiguration, BRAM content frames) or the streamed chain on CHAIN_IN/CHAIN_OUT; GSR → GTS → GWE → DONE startup |
| User clock | one sysclk enable at a time, at least 2**9 = 512 cycles apart (the fabric's multicycle); free-running at most 125 MHz / 2**9 = 244 kHz |
| JTAG | 6-bit AMD 7-series IR, IDCODE `0xFBEEF093` (M16) |
| Host utilisation (Vivado, M16) | 20 498 LUTs (38.53%), 21 511 FFs (20.22%), 2 RAMB18, 2 DSP48E1, WNS +0.667 ns |

<!-- device:end -->

A 48-CLB M7 profile (8 × 8 core, 9400-bit chain, IDCODE `0x9BEEF093`) is frozen in [`release/M7_8x8/`](release/M7_8x8/); it was synthesised with the XDC loop breaking that later crashed Vivado. M12b's 36-CLB profile costs no more logic than M13 thanks to the smaller configuration store. Changing the grid is one setting (`ARCH` in `software/bob/device.py`) followed by `make rrgraph`.

## Build and test it (every milestone)

On the Mac:

```sh
make check              # device files, all simulations, lint, pytest — must be green
make hw                 # refresh generated vectors inside hw/
make clean-logs         # drop the gigabyte yosys estimate logs from build/
```

On the Windows Vivado machine:

1. Replace `E:\bob_full_v1\hw` with this `hw/` folder. Never delete `E:\bob_full_v1\bob_vivado`; the script reuses that project.
2. Vivado → Tools → Run Tcl Script → `E:/bob_full_v1/hw/scripts/build.tcl`. It rebuilds only if something changed. For other actions, type `set bob_args {program}` (or `all`, `force`, `status`, `sim`) and then `source` the script. Details are in [`hw/README.md`](hw/README.md).
3. Program the board, then copy `bob_vivado\out\<tag>\` back to `docs/reports/<tag>/`.

Back on the Mac with the Pico attached:

```sh
make check              # now also checks the Vivado reports
make hwtest M=M7        # regression + milestone checks; checklist in docs/hwtest/M7.md
make hwtest M=M8        # same bitstream: yosys-synthesised examples (docs/hwtest/M8.md)
make hwtest M=M9        # same bitstream: the examples placed and routed by VPR (docs/hwtest/M9.md)
make hwtest M=M10       # same bitstream: bob build/load, LEDs vs source, CAPTURE vs golden (docs/hwtest/M10.md)
make hwtest M=M11       # same bitstream: designs live on the switches, RAM readback, clock rate (docs/hwtest/M11.md)
make hwtest M=M12       # same bitstream: every example placed and routed by bob's own Python PnR (docs/hwtest/M12.md)
```

Every run is appended to `docs/hwtest/results.log`. To test an older bitstream, use its frozen tools, e.g. `cd release/mac_M6/host && ./hwtest.py --milestone M6`.

## bob studio

```sh
./host/studio.py --probe fake        # no board needed
./host/studio.py --probe usb         # the Pico on PMODA
python3 docs/studio/build.py         # rebuild studio.html from docs/studio/p*.{html,js}
```

| Vivado / Quartus | bob studio | what actually runs |
|---|---|---|
| Synthesis | Synthesis | `software/bob/synth.py` (yosys onto bob cells) |
| — | Synthesis Verification | `software/bob/equiv.py`: source == netlist == golden, 300 cycles |
| Implementation | Implementation | pack / place / route — VPR, or bob's own Python PnR |
| Generate Bitstream | Generate Bitstream | `fasm_from_vpr.py` → `bitgen.py` → `.bit` |
| Device window | Device view | the placement and routed channels on the real grid |
| I/O Planning | Pin Planner | the 44 pads → writes a `.pcf` |
| Open Target / Program | Program and Debug | `software/host/cfgplane.py`, readback, CAPTURE, partial reconfiguration |
| Messages | Messages | yosys / iverilog / VPR diagnostics, clickable to the source line |

Your own work lives in `work/`. **Sources → New design** scaffolds
`work/<name>/<name>.v` from a template and opens it; edit and save with ⌘S / Ctrl-S;
**Open path…** opens anything inside the repo. The Pin Planner writes a `.pcf` the next
build picks up. The same design from the command line:

```sh
./bob build work/mything/mything.v
./bob build work/mything/mything.v --pcf work/mything/mything_pins.pcf
./bob load  build/bit/mything.bit --probe usb
```

The stages come from [`software/bob/flow.py`](software/bob/flow.py), which runs the same flow
`./bob build` does but as separate timed steps, each returning what it measured.
`./bob build --json FILE` writes that record; `tests/test_flow.py` requires `flow.py` and
`cli.build()` to produce a byte-identical `.bit`. The page is one self-contained file with
no external libraries, assembled from `docs/studio/` the way `arch.html` is.

## The guest flow (M8–M10, today)

```sh
software/bob/synth.py work/examples/counter/counter.v     # yosys → $lut / BOB_FDRE / BOB_ADD / BOB_BRAM18 / BOB_DSP
software/bob/equiv.py work/examples/counter/counter.v     # synthesised netlist == source Verilog (iverilog)
software/bob/place.py counter --check        # M8 hand placer; placed bitstream == source (model)
make vpr                                  # M9: VPR packs/places/routes every example (Docker) -> software/bob/vpr/
software/bob/fasm_from_vpr.py --check        # committed VPR results -> FASM -> chain == source (model)
./bob build work/examples/counter/counter.v            # M10: all of the above in one command -> build/bit/counter.bit
./bob build work/examples/gates/gates.v --pcf work/examples/gates/gates_swapped.pcf
./bob load build/bit/counter.bit          # frames on CFG_IN + FDRO readback, BRAM contents, JSTART (Pico attached)
./bob load build/bit/counter.bit --mode chain   # the same memory through the scan chain (CHAIN_IN)
software/bob/packets.py dump build/bit/counter.bit # the UG470-style packet stream
./bob build work/examples/switches/switches.v --clock run --div 15   # free-running user clock (7.45 Hz); then ./bob load
./bob info build/bit/counter.bit          # or: ./bob fasm build/bit/counter.bit
./bob build work/examples/fir/fir.v --pnr python   # M12: bob's own pack/place/route instead of VPR (no Docker)
software/bob/pnr/compare.py                  # Python PnR vs VPR -> docs/reports/M12/pnr_vs_vpr.md
sim/run_cosim_sim.sh                      # golden co-simulation: source live vs fabric RTL loaded from .bit
sim/run_synth_sim.sh                      # the same bitstreams on the complete FPGA RTL
```

Examples in `work/examples/`: `gates`, `adder`, `counter`, `blinky`, `ram`, `mult`, `switches`, `fir` (per-design report: `docs/reports/M11/designs.md`). The hand-written designs in `software/host/designs.py` load with `software/host/fpga.py --load showcase`.

## Folder map

```
hw/            the Vivado bundle: sources.f, build.cfg, src/ (RTL + generated fabric), tb/, constr/, scripts/
software/bob/     device.py (single source of truth), VPR arch + rr graphs, fabric generator, model,
               chainbits, synth/equiv/place (M8), vpr_run/fasm_from_vpr + committed vpr/ results (M9), bitgen/golden/cli (M10)
software/host/          Pico/JTAG tools: cfgplane, fpga, hwtest, bitstream (router), designs
sim/           iverilog/verilator scripts, vector generators, mutation tests
tests/         pytest
work/examples/      Verilog designs for the synthesis flow
docs/          bitstream-format.md, hwtest/Mx.md checklists, reports/, arch/ (arch.html sources)
release/       frozen bundles: hw_M3…hw_M7, mac_M6/M7 (host tools), M7_8x8 (48-CLB profile)
```

Tools on the Mac: iverilog, verilator, yosys, Python 3 + pytest, tclsh. VPR runs in the OpenFPGA Docker image, through Colima (`colima start`).

The original README for the M0 4×4 baseline inherited from `bob/` is kept at [`docs/README_M0.md`](docs/README_M0.md).
