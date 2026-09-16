# bob_full_v1 — a documented FPGA fabric and Verilog→bitstream flow

All new work goes in **`/Users/sk/work/bob/bob_full_v1/`**. This plan is saved there as `bob_full_v1/PLAN.md` in Milestone 0. The existing 4×4 build (`rtl/`, `host/`, `sim/`) stays as it is and keeps passing its 174 checks.

**Working rule:** one milestone at a time. Build it, run its "done when" checks, show you the results, and wait for your go-ahead before starting the next.

## Context

The audit (`docs/fabric-audit.html`) found bob's CLB is correct AMD 7-series and its JTAG link works on hardware. What's missing is everything around the CLB: a user clock, scalable configuration, real routing, an I/O tile, and a way to go from Verilog to bitstream. The goal is a fabric built from official references, with **frame-based configuration** and a **Verilog → bitstream** flow, running on the PYNQ-Z2 through the Pico.

Decisions so far:
- CLB built around a fracturable LUT6.
- Synthesis with yosys; pack, place, route and bitgen in Python. nextpnr comes later, for the physical-design chip.
- Vivado runs on another machine; you copy the files across.

## What already exists in `bob/`, and how v1 reuses it

Two ways of reusing:
- **use** — referenced in place from `bob_full_v1`, unchanged, never copied.
- **copy** — copied into `bob_full_v1`, then changed there; the original stays as it is.

| Existing (verified) | Status today | Reuse | Becomes |
|---|---|---|---|
| `rtl/lut6.sv` | fracturable LUT6, matches UG474 | use | CLB LUT in M3 |
| `rtl/clb.sv`, `rtl/clb_pkg.sv` | carry + FF, verified in `tb_mini_fpga` | copy | M3: add routable CE/SR/clock enable; field offsets move into `device.py` |
| `rtl/jtag_tap.v` | 16-state TAP, IR, IDCODE/BYPASS/USER, falling-edge TDO; **works on hardware** | copy | M2: add `CFG_FAR`/`CFG_FDRI`/`CFG_RDBK`/`CFG_CTRL`; keep the `tlr` glitch rule |
| `rtl/bsc_cell.v` | BC_1 cell, synchronous-TLR fix proven on hardware | use | boundary ring around I/O tiles, M4 |
| `rtl/mux_bank.v` | N muxes over a shared source bus | copy | connection-box muxes in `route_block.v`, M4 |
| `rtl/fabric.v` | generate-loop grid + carry chain | copy | pattern for the generated `fabric.v`, M4 |
| `host/dirtyjtag.py` `Probe` | `shift_ir`, bulk `shift_dr_fast` (MSB-first `CMD_XFER`), per-pulse fallback | use (import) | frame loader transport, M9 |
| `host/fpga.py` `load_bitstream` | load → readback → retry per-pulse | copy | `host/fpga2.py` per-frame load/verify, M9 |
| `host/bitstream.py` `simulate()`, `LUT` builders | fixed-point combinational model | copy | start of `model.py` (adds FFs and clock), M3–M4 |
| `sim/gen_vectors.py` + `host/designs.py` + `sim/tb_fpga4x4.v` | independent-model vector cross-check | copy pattern | golden co-simulation, M4 and M8 |
| `sim/lint.sh` | verilator lint with justified waivers | copy | `bob_full_v1/sim/lint.sh` from M2 on |
| `constr/pynq_z2_jtag.xdc` | PMODA JTAG pins (TCK on MRCC U18), pulls, SW/BTN/LED pins, LUTLP-1 downgrade | copy | `vivado/bob_top.xdc` + sysclk, M9 |
| `vivado/create_project.tcl`, `drc_waiver.tcl` | one-session build/program flow | copy | v1 build script + saved reports, M9 |
| `host/wire_check.py`, `tap_probe.py`, `detect.sh`, `pico/`, `docs/wiring.md` | harness proven on hardware | use | M9 bring-up, unchanged |

Lessons carried over from the existing code:
- Existing CONFIG readback is read-modify-write: `read_config` has to shift the same word back in. In v1, `CFG_RDBK` is a **separate, non-destructive** instruction.
- Synchronous use of Test-Logic-Reset (`bsc_cell.v`), launching TDO on the falling edge, and the MSB-first byte order of bulk transfers are all kept.

## Two flows, two bitstreams

- **Host flow (Vivado):** the fabric RTL goes through Vivado onto the XC7Z020 and produces an AMD `.bit`. Once that's loaded, the Zynq *is* bob.
- **Guest flow (ours):** `design.v` → yosys → `pack` → `place` → `route` → `bitgen` → bob `.bit` (frames) → Pico JTAG. Vivado can't do this, because its device database only describes AMD silicon.
- **No Aegis binaries are used.** aegis-pack and nextpnr-aegis only understand Aegis's own bit layout; we study them and write bob's versions. A later `nextpnr-bob` would mean writing our own architecture file modelled on `aegis.cc`, fed from `device.py`.

## References, and what we take from each

| Area | From | What |
|---|---|---|
| CLB | AMD UG474 | LUT6_2 fracture, CARRY4 structure, FDRE/FDSE priority, routable CE/SR |
| Configuration | AMD UG470 + OpenFPGA `frame_based` | FAR, FDRI with FAR auto-increment, readback, CRC; address decoder + data + write enable |
| Routing | VTR/OpenFPGA | unidirectional wires, length-1 and length-2 segments, Wilton switch box with Fs=3, partial fan-in, no reflection |
| Neighbour links | Aegis `aegis.cc` | adjacent CLB outputs feed LUT inputs without using a track |
| I/O and clock | Aegis `io.md` / `clock.md` + AMD BUFG | 8-bit I/O tile; global clock from the 125 MHz board clock |
| BRAM | AMD UG473 | synchronous read, RAMB18E1, spans 4 rows, INIT loaded via frames |
| DSP | AMD UG479 (trimmed) | 18×18 signed, 48-bit accumulator, pre-adder, PCOUT→PCIN cascade |
| Synthesis mapping | Aegis `techmap_emitter.dart`, yosys `synth_xilinx` | cell library, techmap, BRAM rules (Apache-2.0, attributed) |
| Bitgen method | Aegis `aegis-pack` (read only), Project X-Ray FASM | routed pips → mux selects; FASM text |
| Area optimisation | ZUMA (FCCM 2012) | configuration memory in host LUTRAM |

## Folder layout (`bob_full_v1/`)

```
PLAN.md  README.md  REUSE.md   (which bob/ files are used or copied, and why)
rtl/        generated/  core/  tiles/  top/
tools/bob/  device.py pack.py place.py route.py bitgen.py model.py cli.py
            synth/ (bob_cells.v techmap.v bram.rules synth_bob.tcl)
tests/  sim/  examples/  host/  vivado/ (reports/)
```

---

## M0 — Setup

- Create the tree; copy this plan to `PLAN.md`; write `REUSE.md` from the table above.
- `brew install yosys`; check pytest, iverilog and verilator.

**Done when:** `yosys -V` works, `pytest bob_full_v1/tests` runs, and the old `sim/run_fabric_sim.sh` passes 174/174 plus `sim/lint.sh` is clean.

## M1 — Device description (single source of truth)

- New `tools/bob/device.py`: grid, tracks, segments, `FRAME_W`, column types, per-tile bit layout, routing-resource graph (pip → config bits).
- Generates `rtl/generated/bob_params.vh` and `device.json`. Takes over the job `clb_pkg.sv` does today, of holding the offsets in one place.

**Done when:** pytest checks there are no overlapping fields, all fields fit in `FRAME_W`, every pip maps to one field, and the 6×6 graph is connected.

## M2 — Frame configuration + JTAG TAP

- Start from a **copy of `rtl/jtag_tap.v`**: keep the FSM, timing and IDCODE/BYPASS; replace the USER and CONFIG registers with the `CFG_*` instructions.
- New `rtl/core/frame_cfg.v`: FAR, FDRI shift register, row/column decode → tile write enable, non-destructive readback multiplexer, CRC32, control bits (GSR, done, CRC-ok).
- Testbench built from the `tb_fpga4x4.v` probe tasks (`tick`, `shift_ir`, `shift_dr`).

**Done when:** random frames written and read back match, FAR auto-increments, a bad CRC is flagged, and lint is clean.

## M3 — CLB tile core

- `lut6.sv` used in place; `clb.sv` copied, with routable CE/SR/clock enable.
- `model.py` starts from a copy of `simulate()` in `host/bitstream.py`, extended with FFs.

**Done when:** a testbench sweeps every flag combination (combinational, FF, carry, O5) and matches `model.py`; the existing `tb_mini_fpga.v` vectors are reused as extra cases.

## M4 — Routing block, I/O, clock, fabric

- `route_block.v` (Wilton, L1+L2, neighbour links; the connection box starts from a copy of `mux_bank.v`), `clb_tile.v`, `io_tile.v` (uses `bsc_cell.v`), `clock_tile.v`, `fabric.v` (from a copy of `rtl/fabric.v`'s generate pattern).
- `model.py` covers the whole fabric; a vector generator in the style of `gen_vectors.py`.

**Done when:** hand-built frames route pad → LUT → FF → pad across the grid, and RTL equals `model.py` every cycle.

## M5 — Synthesis (yosys)

- `synth/bob_cells.v`, `techmap.v`, `synth_bob.tcl`; examples `gates.v`, `adder4.v`, `counter.v`, `blinky.v`. The old `host/designs.py` functions (and6, xor6, mux…) are rewritten as Verilog examples.

**Done when:** yosys stats show only BOB_* cells, and the post-synthesis netlist equals the original Verilog in iverilog.

## M6 — Pack + place

- `pack.py` (LUT and FF pairs, carry macros, LUT5-pair merge), `place.py` (simulated annealing, `.pcf` pins, carry macros kept in a column).

**Done when:** the legality checker passes, a fixed seed is repeatable, and a wirelength report is printed.

## M7 — Route

- `route.py`: PathFinder over the graph in `device.json`, replacing the BFS in `host/bitstream.py`. Output uses nextpnr's `ROUTING` JSON format.

**Done when:** every net routes, no wire is shared between nets, and a congestion stress test converges.

## M8 — Bitgen + golden co-simulation

- `bitgen.py` → `.bit` (FAR/FDRI records, CRC) + `.fasm`; `cli.py`: `bob build design.v --pcf pins.pcf`.
- Golden test: original Verilog versus fabric RTL loaded with the frames, random vectors, every cycle.

**Done when:** bits → FASM → bits round-trips, and all examples match the golden simulation.

## M9 — Hardware bring-up (PYNQ-Z2)

- `bob_top.v`; `bob_top.xdc` from a copy of `constr/pynq_z2_jtag.xdc`, plus sysclk H16 (verify against the master XDC); build script from a copy of `vivado/create_project.tcl`, saving utilization and timing reports. You build on the Vivado machine.
- `host/fpga2.py`: imports `Probe` from `host/dirtyjtag.py`; per-frame load, readback and retry, after the pattern in `load_bitstream()`.
- Bring-up uses `detect.sh`, `wire_check.py` and `tap_probe.py` as they are.

**Done when:** IDCODE reads, readback equals `.bit`, blinky blinks, switches → LEDs match golden, and the reports are committed.

## M10 — BRAM tile

- UG473 behaviour: synchronous read, 4-row span, INIT through BRAM frames, yosys `memory_bram` rules, placer macro.

**Done when:** a RAM example passes golden simulation and runs on hardware.

## M11 — DSP tile

- UG479 trimmed: 18×18 signed, 48-bit accumulator, pre-adder, cascade.

**Done when:** a multiplier and a small FIR pass golden simulation and run on hardware.

## M12 — Optimisation and scale

- LUTRAM configuration memory (ZUMA); measure LUTs per tile against the M9 reports; grow the grid; optional `nextpnr-bob` from `device.json`.

**Done when:** LUTs per tile drops measurably, and a larger grid fits and passes M8.
