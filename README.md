# bob — an FPGA built inside an FPGA (PYNQ-Z2)

bob is a complete FPGA written in Verilog and running in the PL of a Zynq XC7Z020 (PYNQ-Z2):
- **Logic:** CLBs (LUT6 + carry + flip-flop), UG473-style BRAMs and UG479-style DSP slices.
- **Routing:** generated from VPR's routing-resource graph.
- **Configuration:** a CRC-checked JTAG scan chain.
- **Pads:** a boundary-scan ring.

A Raspberry Pi Pico running DirtyJTAG on PMODA configures it from a Mac.

For the detailed plan, conventions, gotchas and every milestone, read [`PLAN.md`](PLAN.md); the short agent rules are in [`CLAUDE.md`](CLAUDE.md). The interactive die slice with sources, files and testbenches per block is [`arch.html`](arch.html).

## Where it stands (2026-09-17)

| Milestone | What | Status |
|---|---|---|
| M0–M6 | layout, device description, scan-chain config plane, 4×4 fabric, user clock, BRAM, DSP | passed on the board |
| **M7** | fabric generated from VPR's rr graph, **16-CLB board profile** | **passed on the board 2026-09-17** (26/26); timing hardening planned for the next rebuild |
| M8 | yosys synthesis onto bob cells → placed → runs on the fabric | **passed on the board 2026-09-17** (10/10, no rebuild) |
| M9 | VPR packs, places and routes the examples → FASM → chain | **passed on the board 2026-09-17** (10/10, no rebuild) |
| M10 | bitgen (FASM ⇄ chain, `.bit`), `bob build`/`bob load`, `.pcf` pins, golden co-simulation | **passed on the board 2026-09-17** (7/7, no rebuild) |
| M11 | real designs live on the board (free-running clock, real switches): switches, FIR on DSPs, RAM readback, blinky rate | built and simulated 2026-09-17; board test pending (no rebuild) |
| M12 | Python PnR, larger grid | planned |
| M13 | frame-based configuration (UG470) replacing the scan chain | planned, last |

After M7 the Vivado bitstream stays the same through M11: those milestones only load new configuration chains over JTAG. The next Vivado rebuilds come at M12 (bigger grid) and M13 (new config plane), or earlier if a later step shows the fabric needs a change.

## The M7 device (16-CLB profile)

| | |
|---|---|
| VPR grid | 8 × 6 (6 × 4 core inside an I/O ring, corners empty) |
| CLBs | 16 (columns x = 1, 2, 4, 5; one BLE each: LUT6 O6/O5, MUXCY/XORCY carry, FDRE/FDSE) |
| BRAM | 2 × 1024×18 true dual port (column x = 3, 2 rows tall), contents over USER4 |
| DSP | 2 × DSP48E1-style slices (column x = 6), PCOUT→PCIN cascade |
| I/O | 20 pads; SW0 SW1 BTN0 BTN1 on the West edge, BTN2 BTN3 South, LD0–LD2 East, LD3 = DONE |
| Routing | L4 unidirectional, W = 24, Wilton Fs = 3 (from OpenFPGA's k6_frac_N10 tileable arch); 1095 muxes |
| Configuration | 4216-bit chain, CRC-32C + length guard, GSR → GTS → GWE → DONE startup |
| JTAG | 6-bit AMD 7-series IR, IDCODE `0xABEEF093` |
| Host utilisation (yosys estimate) | ~11.4k LUTs, ~10.3k FFs, 2 RAMB18, 2 DSP48E1 |

A 48-CLB profile (8 × 8 core, 9400-bit chain, IDCODE `0x9BEEF093`) is fully built and simulated but was too slow to synthesise on the build machine. It is frozen complete in [`release/M7_8x8/`](release/M7_8x8/) to build later on a faster machine. Changing the grid is one setting (`ARCH` in `tools/bob/device.py`) followed by `make rrgraph`.

## Build and test it (every milestone)

On the Mac:

```sh
make check              # device files, all simulations, lint, pytest — must be green
make hw                 # refresh generated vectors inside hw/
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
```

Every run is appended to `docs/hwtest/results.log`. To test an older bitstream, use its frozen tools, e.g. `cd release/mac_M6/host && ./hwtest.py --milestone M6`.

## The guest flow (M8–M10, today)

```sh
tools/bob/synth.py examples/counter.v     # yosys → $lut / BOB_FDRE / BOB_ADD / BOB_BRAM18 / BOB_DSP
tools/bob/equiv.py examples/counter.v     # synthesised netlist == source Verilog (iverilog)
tools/bob/place.py counter --check        # M8 hand placer; placed bitstream == source (model)
make vpr                                  # M9: VPR packs/places/routes every example (Docker) -> tools/bob/vpr/
tools/bob/fasm_from_vpr.py --check        # committed VPR results -> FASM -> chain == source (model)
./bob build examples/counter.v            # M10: all of the above in one command -> build/bit/counter.bit
./bob build examples/gates.v --pcf examples/gates_swapped.pcf
./bob load build/bit/counter.bit          # CFG_IN + readback, BRAM contents, JSTART (Pico attached)
./bob build examples/switches.v --clock run --div 15   # free-running user clock (14.9 Hz); then ./bob load
./bob info build/bit/counter.bit          # or: ./bob fasm build/bit/counter.bit
sim/run_cosim_sim.sh                      # golden co-simulation: source live vs fabric RTL loaded from .bit
sim/run_synth_sim.sh                      # the same bitstreams on the complete FPGA RTL
```

Examples in `examples/`: `gates`, `adder`, `counter`, `blinky`, `ram`, `mult`, `switches`, `fir` (per-design report: `docs/reports/M11/designs.md`). The hand-written designs in `host/designs.py` load with `host/fpga.py --load showcase`.

## Folder map

```
hw/            the Vivado bundle: sources.f, build.cfg, src/ (RTL + generated fabric), tb/, constr/, scripts/
tools/bob/     device.py (single source of truth), VPR arch + rr graphs, fabric generator, model,
               chainbits, synth/equiv/place (M8), vpr_run/fasm_from_vpr + committed vpr/ results (M9), bitgen/golden/cli (M10)
host/          Pico/JTAG tools: cfgplane, fpga, hwtest, bitstream (router), designs
sim/           iverilog/verilator scripts, vector generators, mutation tests
tests/         pytest
examples/      Verilog designs for the synthesis flow
docs/          bitstream-format.md, hwtest/Mx.md checklists, reports/, arch/ (arch.html sources)
release/       frozen bundles: hw_M3…hw_M7, mac_M6/M7 (host tools), M7_8x8 (48-CLB profile)
```

Tools on the Mac: iverilog, verilator, yosys, Python 3 + pytest, tclsh. VPR runs in the OpenFPGA Docker image, through Colima (`colima start`).

The original README for the M0 4×4 baseline inherited from `bob/` is kept at [`docs/README_M0.md`](docs/README_M0.md).
