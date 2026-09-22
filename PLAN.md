# bob_full_v1 — plan, status and handoff

> **For any agent picking this up:** read this whole file before touching anything. It is the single current plan and records how the work is done.
> `PLAN_v0.md` is the superseded first draft; don't follow it. `docs/README_M0.md` describes the M0 baseline inherited from `bob/`; `README.md` is the current overview.
> Last updated 2026-09-18 (see `HANDOFF.md` for the live state): M0–M15 passed on the PYNQ-Z2 (git tags `m7`…`m15`). Whole-project report: `docs/project/REPORT.md`, interactive `project.html`.

---

## 1. What this project is

A complete FPGA **built inside an FPGA**. The guest fabric ("bob") is written in Verilog and runs on the PL of a **PYNQ-Z2 (Zynq XC7Z020, part `xc7z020clg400-1`)**. It is configured over JTAG from a Mac through a **Raspberry Pi Pico running DirtyJTAG** wired to PMODA.

The flow works end to end: `design.v → yosys → VPR (pack/place/route on bob's own rr graph) → FASM → bob bitgen → .bit → Pico JTAG → running on the guest fabric`, checked at every step. It is one command each way: `./bob build design.v` and `./bob load design.bit`.

Two flows, two bitstreams. Don't confuse them:
- **Host flow (Vivado, on a separate Windows machine):** bob's RTL → Vivado → AMD `.bit` for the XC7Z020. Once loaded, the Zynq *is* bob. Host builds: M0–M7 each; M8–M12a needed none; M13 (frames, timing closed); M15 (36-CLB grid, partial reconfiguration, BRAM content frames) is on the board.
- **Guest flow (ours, on the Mac):** a user design → our tools → a bob configuration chain (`.bit`, chain file v2). It is loaded over the Pico's JTAG into the running bob fabric.

Starting point: `/Users/sk/work/bob/` is a hardware-proven 4×4 CLB fabric (JTAG TAP, boundary scan, 2896-bit config chain, 174 simulation checks). It was **copied whole** into `bob_full_v1/` and is **frozen**. All work happens in `bob_full_v1/`, which is a git repository (local only; milestone tags `m7`…`m11`).

**The device on the board (M7, `ARCH_6X4`):**
- VPR grid 8 × 6 (6 × 4 core inside an I/O ring)
- 16 CLBs (one BLE each: LUT6 O6/O5, MUXCY/XORCY carry, FDRE/FDSE with routed CE/SR)
- 2 BRAMs (1024×18 TDP, height 2, column x = 3) and 2 DSP slices (height 2, column x = 6, PCOUT→PCIN)
- 20 pads, L4 unidirectional routing W = 24, Wilton Fs = 3, 1095 routing muxes
- 4216-bit chain, 40-cell boundary, IDCODE `0xABEEF093`, USERCODE 7

The 8×8 profile (48 CLBs, 9400 bits, `0x9BEEF093`) is frozen in `release/M7_8x8/`, because its Vivado synthesis was too slow on the build machine.

## 2. Status

| Milestone | What | Status |
|---|---|---|
| M0 | copy, `hw/` layout, adaptable `build.tcl`, tools | **passed on hardware** 2026-09-14 (WNS +67.3 ns) |
| M1 | `software/bob/device.py` single source of truth | **passed on hardware** 2026-09-14 (chain-length 2896 on the board) |
| M2 | scan-chain configuration plane (6-bit AMD IR, CRC, startup, capture), standalone test top | **passed on hardware** 2026-09-14 (11/11; tb_cfg 180, `make mutate` 5/5) |
| M3 | config plane wired into the 4×4 fabric + host loader | **passed on hardware** 2026-09-14 (WNS +63.9 ns; 3951 LUTs, 6115 FFs) |
| M4 | CLB core (routable CE/SR, LUT size K as a parameter) + user clock | **passed on hardware** 2026-09-14 (WNS +0.84 ns on the 8 ns sysclk) |
| M5 | BRAM tile (UG473 RAMB18E1 subset) | **passed on hardware** 2026-09-14 |
| M6 | DSP tile (UG479 DSP48E1 trimmed) | **passed on hardware** 2026-09-14 (25 checks) |
| M7 | heterogeneous fabric generated from VPR's rr graph, 16-CLB board profile | **passed on hardware 2026-09-17** (26/26; 7670 LUTs, 10362 FFs, 2 RAMB18, 2 DSP48E1; WNS −1102 ns from unconfigured routing-loop paths, see M7 timing notes). Last Vivado build. |
| M8 | yosys synthesis to bob cells (+ M8 hand placer) | **passed on hardware 2026-09-17** (10/10, no rebuild) |
| M9 | pack/place/route with VPR on the committed rr graph | **passed on hardware 2026-09-17** (10/10, no rebuild) |
| M10 | FASM ⇄ chain, `.bit` v2, `./bob build/load`, `.pcf`, golden netlist + co-simulation | **passed on hardware 2026-09-17** (7/7, no rebuild) |
| M11 | real designs live: free-running clock, real switches, RAM readback, clock rate, FIR on DSPs | **passed on hardware 2026-09-17** (12/12 on the second run, every live goal reached; the first run found stale BRAM words, fixed in `bob load`) |
| M12 | M12a: Python PnR checked against VPR (no rebuild); M12b area/larger grid | **M12a passed on hardware 2026-09-17** (13/13 on the M7 bitstream: pnr-* ×9, live-fir-py, live-switches-py; wirelength 0.99× VPR). **M12b passed on hardware 2026-09-17** in the M15 build (streamed chain store, 8×6 core with 36 CLBs; bob-wide/pnr-wide) |
| M13 | frame-based configuration (UG470-style packets and frames) next to the kept chain, with the M7 timing fixes | **passed on hardware 2026-09-17** (39/39: full regression through the chain, 5 frame checks, every guest design loaded as frames; timing closes, WNS +0.877 ns / WHS +0.030 ns, M7 was −1102 ns; 11 607 LUTs, 12 287 FFs; synthesis only built with the XDC kept to implementation) |
| M14 | partial reconfiguration of a running design (UG470 AGHIGH … LFRM, changed frames only, state kept) | **passed on hardware 2026-09-17** in the M15 build (partial-swap, partial-live, partial-bad-crc, partial-guest) |
| M15 | BRAM contents as frames (FAR block type 001), one CRC-covered stream for the whole design | **passed on hardware 2026-09-17** (48/48 first run, with M12b and M14; 10 411 LUT / 11 097 FF, fewer LUTs than M13 with 2.25× the CLBs; WNS +0.585 ns / WHS +0.065 ns; synthesis 5.1 min at 2.0 GB) |

| M16 | 10 × 10 CLB grid (12 × 10 core, 100 CLBs, 145 frames = 18 560 bits) | **passed on hardware 2026-09-18**. The first Vivado attempt did not close (3 h 25 min, WNS −465.7 ns on fabric flop → flop paths, `[Route 35-447]` congestion): the 12 × 10 fabric's static path through the unconfigured routing muxes is ~2500 ns and the 256-cycle gap only bought 2048 ns. Raising the gce gap and the XDC multicycle to 512 cycles closed it and halved the free-running guest clock (488 → 244 kHz). `route_design` then died in "Phase 2.3 Update Timing" until `general.maxThreads 1` (`drc_waiver.tcl`, hooked as TCL.PRE): the timer cuts every combinational loop in the routing mesh — one SCC of 2146 wires and 11 270 cycles, against M15's 1018 / 4130 — and two threads doing that concurrently faults. As built: 20 498 LUTs (38.5%), 21 511 FFs (20.2%), WNS +0.667 ns, WHS +0.112 ns, DRC clean. Checklist `docs/hwtest/M16.md` |
| M18 | bob studio projects and block designs: New/Open Project (a `.bobproj` folder anywhere on disk), sources + top + pin files, a block-design canvas (project modules, 14 IP cores, the board's pins) that generates an HDL wrapper and `.pcf`, and project builds into `<project>/build/` | **software done; hardware test pending** (`make hwtest M=M18`, no Vivado rebuild: the PL keeps M16). Example `work/examples/bd_demo`. Checklist `docs/hwtest/M18.md` |

Hardware results are in `docs/hwtest/results.log`; Vivado reports are in `docs/reports/Mx/`; per-design guest reports in `docs/reports/M11/designs.md`.

### After M16: the timing contract is checked, and there is a GUI

The gap and the XDC multicycle are the same number in two files, and the XDC says that
agreement "is the whole reason the exception is true rather than assumed". Nothing checked
it until it cost 3 h 25 min. `tests/test_layout.py` now does, and each guard was
mutation-tested; `bob_fpga.v` takes `GAP_SHIFT` from `` `BOB_GCE_MIN_GAP_SHIFT `` (it used
to pass `DIV_MIN_SHIFT` to both, so the gap knob did nothing), and `tb_clock_gap` runs at
the board's gap as well as the short simulation one.

**bob studio** (`software/host/studio.py --probe fake`) is an EDA tool over the same flow —
sources and an editor, Flow Navigator, per-stage timings and diagnostics, a Device view of
the placement and routing, a Pin Planner, program / readback / CAPTURE / partial
reconfiguration. Its engine is `software/bob/flow.py`, which runs `./bob build`'s flow as
separate timed stages; `tests/test_flow.py` requires it and `cli.build()` to write a
byte-identical `.bit`. It drives `software/host/fakeboard.py` when no board is attached. The page is
built from `docs/studio/` exactly as `arch.html` is built from `docs/arch/`, and the backend
is stdlib only, so the project gained no dependency.

### M18: projects and block designs

bob studio works on **projects** now, as Vivado does. `software/bob/project.py` owns a
folder with `<name>.bobproj`, `src/`, `bd/`, `ip/`, `constrs/` and `build/`. Paths are
relative to the project file, so the folder can move. A project turns into exactly the
arguments `flow.Flow` takes, and `tests/test_project.py` holds a project build and
`./bob build` to a byte-identical `.bit`. `software/bob/bd.py` is the block design (Vivado's
IP integrator cut down to this fabric). Its blocks are the project's own modules (ports read
by yosys, per parameter set), the IP cores in `software/bob/ip/` (each checked against a
Python model in iverilog) and the board's pins. It validates every endpoint and writes a
wrapper whose ports are the examples' convention (`clk sw btn led`), so a design on the
board's switches and LEDs needs no pin file and keeps the model check. A design that uses a
scan-only pad also gets `constrs/<name>.pcf`. The first spare pad is refused: it is the one
`vpr_run.write_eblif` gives `clk`. Block names exclude every Verilog/SystemVerilog keyword
(`edge` broke the first demo). The studio's path guard is now "inside the repo **or** inside
the open project".

The device table in the documents is generated by `software/bob/devtable.py` from
`device.json`; `make check` fails if it drifts. It had: after M16 put 100 CLBs on the board,
`README.md` still described the 36-CLB M12b profile.

## 3. How the user wants this done (non-negotiable)

1. **One milestone at a time.** Build it, run its "done when" checks, show the results, and **stop for the user's go-ahead** before the next milestone.
2. **Every milestone ends with a PYNQ-Z2 hardware test** (`make hwtest M=Mx`). Simulation alone never closes a milestone. If a milestone has no RTL change, reuse the previous bitstream, but still run the board test.
2a. **Every hardware build is the complete FPGA plus the new feature, never a standalone block.** A new block goes into the full fabric top, and the hardware test runs the full regression plus the new feature's checks.
3. **Tested references first.** Ground designs in AMD user guides (UG470 config, UG473 BRAM, UG474 CLB, UG479 DSP) and OpenFPGA/VPR (regression-tested architectures). Flag any divergence explicitly.
4. **Reuse verified code** instead of rewriting it.
5. **Scan chain first, frame-based last.** The configuration stays a JTAG scan chain until M13.
6. **Vivado is not on the Mac.** The user copies `bob_full_v1/hw/` to Windows (`E:\bob_full_v1\hw`), replacing the old `hw`, and runs `hw/scripts/build.tcl` (usually Tools → Run Tcl Script). The Vivado project must be **reused, never recreated**.
7. **Explain concepts** (routing, mapping, host vs guest flow) before asking for decisions. Give the user guidance for anything they do by hand at the board (what to press, what the LEDs must show) and enough time to do it.
8. Decisions already made: VPR does PnR first (Python PnR at M12); 6-bit AMD 7-series JTAG IR codes; yosys for synthesis; no Aegis binaries (read-only study only); the board runs the 16-CLB profile until the user decides otherwise (the 8×8 build is for a faster machine).
9. **Git:** commit as work progresses (never `docs/bob_full_v1_report.tex`, which the user edits); tag `mN` only after milestone N passes on the board. The tags replace the `release/mac_MN` copies for freezing tools.

## 4. Folder structure (actual)

```
bob_full_v1/
  PLAN.md  CLAUDE.md  README.md  REUSE.md  PLAN_v0.md (superseded)
  Makefile               check | device | rrgraph | vpr | sim | lint | test | mutate | hw | hwtest M=Mx [ONLY=..]
  bob                    wrapper: python3 software/bob/cli.py (./bob build | load | info | fasm)
  arch.html              interactive die slice (built from docs/arch/ by docs/arch/build.py)
  architecture-v2.html   the style reference arch.html copies

  hw/                    THE Vivado bundle: the only folder copied to Windows
    README.md  sources.f  build.cfg (tag M7, top bob_top, idcode ABEEF093, usercode 7)
    src/clb/             clb_pkg.sv lutk.sv clb.sv
    src/core/            jtag_tap.v jtag_tap6.v bsc_cell.v cfg_tile_sr.v cfg_mem.v cfg_ctrl.v capture_chain.v clock_ctrl.v
    src/tiles/           bram_core.v bram_jtag.v bram_block.v dsp_core.v dsp_jtag.v dsp_block.v
    src/fabric/          bob_mux.v bob_fpga.v (complete FPGA) mini_fpga.v
    src/top/             bob_top.v mini_fpga_top.v cfg_test_top.v
    src/generated/       bob_params.vh bob_fabric.v  (GENERATED by software/bob/device.py)
    tb/                  tb_bob.v tb_synth.v tb_cfg.v tb_clb.sv tb_bram.v tb_dsp.v tb_mini_fpga.v
                         bob_harness.vh (JTAG tasks shared by tb_synth and sim/tb_cosim.v), *vectors.vh (GENERATED)
    constr/pynq_z2.xdc   PLAIN XDC ONLY
    scripts/build.tcl drc_waiver.tcl

  software/bob/             guest-flow tools (Mac)
    device.py            THE device description → arch XML, device.json, bob_params.vh, bob_fabric.v
    vpr_arch.py          VPR arch writer (OpenFPGA k6_frac_N10_tileable…dsp36; CLB modes logic/arithmetic)
    vpr_rrgraph.sh       Docker VPR → arch/bob_k{6,4}_rr.xml.gz + stamps (make rrgraph)
    rrgraph.py fabric_gen.py model.py chainbits.py device.json
    arch/                arch XMLs (GENERATED), rr graphs + stamps + VPR log tails (COMMITTED)
    synth.py synth/      yosys script + cell library, maps, BRAM rules (M8)
    equiv.py golden.py   source == yosys netlist == golden netlist; source trace + golden nets per clock
    place.py             M8 hand placer on software/host/bitstream.py Design (kept for tb_synth)
    vpr_run.py           netlist rewrite → eblif, pins (.pcf), Docker VPR, commit + stale() (M9)
    vpr/<name>/          COMMITTED VPR results: eblif pins net place route vpr.json stamp.txt
    fasm_from_vpr.py     VPR result → FASM features, capture_map, check_model (M9/M10)
    bitgen.py            FASM ⇄ chain, .bit writer/reader (M10)
    cli.py               bob build / load / info / fasm (M10)
    report.py            docs/reports/M11/designs.md (M11)

  software/host/                  talks to the board through the Pico (Mac)
    dirtyjtag.py         Probe (pulse, shift_ir, shift_dr, shift_dr_fast)
    cfgplane.py          config plane, USER1, CAPTURE, USER4 BRAM (bram_fill), DSP register
    bitstream.py         Design API + BFS router over the rr graph (hand-built designs, M8 placer)
    designs.py fpga.py   example designs; load/verify/watch, boundary vectors, SAMPLE
    hwtest.py            per-milestone hardware test (--list --manual --only); appends docs/hwtest/results.log
    buildcfg.py bscan.py minifpga.py tap_probe.py wire_check.py detect.sh urjtag-*   bring-up tools

  sim/                   Mac simulation (iverilog, verilator)
    hwfiles.sh lint.sh run_sim.sh run_clb_sim.sh run_bram_sim.sh run_dsp_sim.sh run_cfg_sim.sh
    run_fabric_sim.sh (tb_bob) run_k4_sim.sh run_synth_sim.sh (tb_synth) run_cosim_sim.sh (tb_cosim)
    gen_*vectors.py gen_synth_vectors.py gen_cosim.py tb_cosim.v mutate_cfg.sh mutate_fabric.sh

  work/examples/              gates adder counter blinky ram mult (M8) switches fir (M11) gates_swapped.pcf (M10)
  tests/                 pytest: test_layout test_build_tcl test_device test_lutk test_model test_chainbits
                         test_reports test_synth test_vpr test_bitgen test_hwtest_fake (checks vs a stand-in board)
  docs/
    bitstream-format.md  chain, CRC, startup, CAPTURE, USER4, load sequence, .bit v2, FASM
    hwtest/Mx.md results.log   per-milestone checklist; every board run
    reports/Mx/          Vivado outputs (M0–M4, M7); M11/designs.md (guest designs)
    arch/                arch.html sources (p1_head … p9_nav, data.json, build.py)
    README_M0.md reference/ wiring.md architecture.html fabric-audit.html report.tex bob_full_v1_report.tex (user's)
  release/               hw_M3…hw_M7 (frozen Vivado bundles), mac_M6 mac_M7 (frozen tools), M7_8x8 (48-CLB profile)
  build/                 scratch, git-ignored (synth, vpr work dirs, bit, cosim)
  pico/README.md
```

Outside the project (read-only references):
- `/Users/sk/work/bob/`: frozen original.
- `/Users/sk/work/resourses/`: study notes; `repos/OpenFPGA` is a shallow clone (reference arch XMLs).
- `/Users/sk/work/aegis/docs/arch/*.md`: Aegis architecture docs (Apache-2.0).
- Windows: `E:\bob_full_v1\hw` (pasted) and `E:\bob_full_v1\bob_vivado\` (the Vivado project, **never delete**).

## 5. Everyday commands

```sh
make check            # device files fresh + all sims (incl. tb_synth, tb_cosim) + lint + pytest. Green before any hand-off.
make device           # regenerate arch XML, device.json, bob_params.vh, bob_fabric.v from the committed rr graphs
make rrgraph          # after an architecture change in device.py: Docker VPR rebuilds the rr graphs, then make device
make vpr              # after changing an example, the netlist rewrite or the arch: Docker VPR re-routes every example
make mutate           # mutation tests (slow)
make hw               # refresh hw/tb vectors, print the Vivado hand-off steps
make hwtest M=M11     # hardware test (interactive: live checks wait for Enter); ONLY=live-fir to rerun one check

./bob build work/examples/counter/counter.v [--pcf pins.pcf] [--clock run --div 15] [-o x.bit]
./bob load build/bit/counter.bit [--watch]
./bob info x.bit ; ./bob fasm x.bit
software/bob/fasm_from_vpr.py --check    # committed VPR results → FASM → model == source
software/bob/report.py                   # docs/reports/M11/designs.md
python3 docs/arch/build.py [--data]   # arch.html (--data after make device)
```

Tools on the Mac: iverilog, verilator 5.050, yosys 0.69 (brew), python 3.14 + pytest, tclsh 8.6, git.
VPR: OpenFPGA's Docker image `ghcr.io/lnis-uofu/openfpga-master:latest` (amd64 only, under emulation) through **Colima** (`colima start`; the tools set `DOCKER_HOST=unix://$HOME/.colima/default/docker.sock`). The binary is `/opt/openfpga/build/vtr-verilog-to-routing/vpr/vpr` (VPR 9.0). Colima shares only `$HOME`: VPR work directories live under `build/`.

## 6. Hardware hand-off loop (every milestone)

**Milestones without RTL changes (M8–M12a):** `make check` green → the user runs `make hwtest M=Mx` (with `--manual` steps from `docs/hwtest/Mx.md`) on the M7 bitstream → read `docs/hwtest/results.log` → fix what failed, or record the pass, tag `mx`.

**Milestones with RTL changes:**
1. Mac: `make check` green, then `make hw`.
2. Copy `bob_full_v1/hw` to Windows and **replace** `E:\bob_full_v1\hw`. Don't delete `bob_vivado`.
3. Vivado GUI: Tools → Run Tcl Script → `E:/bob_full_v1/hw/scripts/build.tcl`. It builds only if inputs changed.
   - Other actions, typed in the Tcl Console: `set bob_args {all}` (or `program`, `force`, `status`, `sim`, `top=…`), then `source E:/bob_full_v1/hw/scripts/build.tcl`.
4. Program the board (`set bob_args {program}`).
5. Copy `E:\bob_full_v1\bob_vivado\out\<tag>\` to `docs/reports/<tag>/`.
6. Mac: `make check` (now also checks the reports), then `make hwtest M=<tag>`.
7. Show the user the results and wait.

What `build.tcl` guarantees (tested on the Mac with the stub): the project lives outside `hw/` and is opened, never recreated; sources/constraints/sim sets sync to `sources.f` / `build.cfg`; rebuild only on a content fingerprint change; `idcode`/`usercode` generics from `build.cfg`; outputs in `bob_vivado/out/<tag>/`; `synth_directive` from `build.cfg`.

## 7. Conventions

- **New synthesisable file** → `hw/sources.f` in dependency order. Lint and sims pick it up.
- **New top** → `parameter [31:0] IDCODE_VALUE` and the board ports `tck tms tdi tdo sw[1:0] btn[3:0] led[3:0]`; add it to `sim/lint.sh`.
- **Per milestone with RTL changes:** bump `hw/build.cfg` `tag`, `idcode` version nibble and `usercode`; add `docs/hwtest/Mx.md`; register checks in `software/host/hwtest.py` `MILESTONE["Mx"]`; update `REUSE.md`, this file's status table and `README.md`.
- **Per milestone without RTL changes:** same, except `build.cfg` stays tagged with the bitstream in the PL (hwtest prints a note).
- **IDCODE map:** `0x1BEEF093` bare TAP, `0x2BEEF093` single CLB, `0x3BEEF093` 4×4 fabric (M0–M1), `0x4BEEF093` M2 cfg test top, `0x5BEEF093` M3, `0x6BEEF093` M4, `0x7BEEF093` M5, `0x8BEEF093` M6, `0x9BEEF093` M7 8×8 profile (`release/M7_8x8`), `0xABEEF093` M7 16-CLB board profile (M7–M12), `0xBBEEF093` M13 (frames), `0xEBEEF093` M15 (one build for M12b + M14 + M15; nibbles C and D were never built alone); next free nibble `0xF`.
- **Architecture numbers live only in `software/bob/device.py`.** Consumers read `device.json` or `bob_params.vh`. After editing it: `make device`, or `make rrgraph` if the VPR architecture changed (sha256 stamps make stale graphs fail). Then `make vpr` if the arch sha changed (committed VPR results are stamped too).
- **Guest designs** (`work/examples/*.v`): ports `clk`, `sw[1:0]`, `btn[3:0]`, `led[2:0]`, or any ports with a `.pcf`. A new example goes into `vpr_run.EXAMPLES` (or `VARIANTS` for a pin file), then `make vpr`.
- **Committed generated data** (rr graphs, VPR results) carries a stamp of what it was built from; tools refuse stale data with the command that rebuilds it. Docker is needed only to rebuild.
- **Hardware checks** are written so they can be run first against `tests/test_hwtest_fake.py`'s stand-in board, and each gets a failing case there.
- **Shift conventions** (proven on hardware): TMS/TDI sampled on rising TCK; TDO and update latches on falling; every shift register LSB-first; chain bit k is the k-th bit shifted in; DirtyJTAG bulk `CMD_XFER` is MSB-first per byte (handled in `Probe.shift_dr_fast`).
- **Test-Logic-Reset (`tlr`) is only ever consumed synchronously.**
- **Every hardware test appends to `docs/hwtest/results.log`.** Don't edit past entries.

## 8. Gotchas already paid for

| Problem | What happened | Rule |
|---|---|---|
| Tcl in XDC | `if`/`catch`/`set` in the XDC were skipped with a critical warning, so `create_clock` never ran; TCK unconstrained, "all constraints met" | XDC is plain XDC (`tests/test_layout.py`); top-dependent logic in `drc_waiver.tcl`; `tests/test_reports.py` checks `no_clock (0)` |
| Tcl `expr` with hex strings | `expr {… ? "0x3BEEF093" : …}` returned `1005514899` | Never build display strings with `expr` |
| tclsh reading stdin | errors printed, exit status 0 | Run Tcl test drivers from a file |
| Vivado GUI Run Tcl Script | can't pass `-tclargs` | `set bob_args {…}` before `source` |
| OpenFPGA Docker | no arm64 manifest; Colima shares only `$HOME`; the image user can't write a mount | `--platform linux/amd64`, `-u root`, work dirs under `build/` |
| Fabric combinational loops | LUTLP-1 DRC and Synth 8-295 by construction | Downgraded for fabric tops in `drc_waiver.tcl`; UNOPTFLAT waived in lint |
| Timing on the fabric (M7) | WNS −1102 ns: static paths through unconfigured routing loops | Hardware still correct; fixes (KEEP_HIERARCHY, commit only while GWE=0, TCK ceiling, case-analysis sign-off) are planned for the next rebuild |
| Vivado synthesis of 48 CLBs (M7) | 30+ min and still running on the build machine | Board runs the 16-CLB profile; 8×8 frozen in `release/M7_8x8/` |
| VPR `pinlocations spread` on tall blocks (M7) | pins inside a tall block where there is no channel: `SINK has no fanin` | custom pin locations in `device.py` |
| rr graph `ptc` (M7) | tileable CHAN nodes carry one track id per position | `rrgraph.py` parses ptc as a tuple |
| Test relying on design order (M7) | tb [4] assumed `showcase` was last | sections load what they check |
| Verilator replication limit (M7) | `{W{1'b0}}` over the whole chain | `--replication-limit 65536` |
| yosys `import clb_pkg::*` (M8) | unsupported | perl shim in synth (macOS sed has no `\s`/`\b`) |
| SystemVerilog keywords (M8) | `ref`, `before` as generated identifiers | avoid them in generated code |
| Long BRAM INIT literal (M8) | iverilog scanner overflow on 18432 binary digits | rewrite as hex, x → 0 |
| yosys alu rule priority (M8) | `_90_bob_alu` lost to the generic `_90_alu` | name it `_80_` |
| Weak random stimulus (M8→M9) | uniform inputs held the counter's sync reset half the time: its trace was all zeros, so the counter check could never fail (model, RTL and board) | biased 50-cycle segments in `equiv.random_vectors`; check coverage of traces |
| VPR pack patterns (M9) | assert in `update_chain_root_pins` with a chain pattern that has no primitive-to-primitive edge; "multi-fanout" error for a pattern into a multi-mode ff | one `bob_ff` primitive, `sumout → ff.D` in the chain pattern |
| VPR `--fix_clusters` (M9) | "requires that placement is enabled" | pass `--pack --place --route --analysis` explicitly |
| VPR result names (M9/M10) | `.net` embeds file names and absolute paths | strip paths from atom names; exclude them from the result hash |
| Python name shadowing (M10) | `name` reused for a block name inside `features()` | distinct names for result vs block |
| yosys `_syn.v` renames everything (M10) | nothing in it maps to fabric locations | `golden.py` writes the netlist with every bit named |
| CAPTURE outside INTEST (M10/M11) | pads read the real switches while IR = CAPTURE | on the board, compare only flip-flop CLBs; they don't clock with autostep outside INTEST |
| "Dead" blinky (M10) | built with `--div 26` (one clock per 137 s) and never loaded | `bob build` prints the clock rate; build ≠ load |
| Stale BRAM words (M11) | BRAM contents survive JPROGRAM and a new chain; `bob load` wrote only up to the last non-zero word | write all 1024 words of every used BRAM (`cli.write_brams`); a `.bit` section per used BRAM |
| Live checks too short (M11) | 8 s saw one input vector | guided checks: guide, Enter, status line, goals, 90 s |
| A guard nobody tests (M2) | a testbench passed with the length check deleted | test each guard in isolation; mutation tests (`make mutate`, tb_cosim mutants, fake-board failing cases) |
| zsh vs bash | `$VAR` with several paths isn't word-split | multi-file shell logic in bash scripts with arrays |
| Random config in simulation (M4) | a random chain built an oscillating loop; simulation time stopped | never commit a fully random chain; random muxes select out-of-range sources |
| Parallel work on hw/ and tools (M4, M7) | editing while the previous milestone was on the board; M6 tools had to be restored | freeze before starting N+1: git tag `mN` (earlier: `release/hw_MN`, `release/mac_MN`) |
| Checks that leak the real switches (M4) | USER1 ce=1 before INTEST let SW0/SW1 reach CE/SR | sequential checks through INTEST use USER1 autostep with ce off |
| Check-script crashes (M5) | `'%03b' % g` | f-strings; a crash is reported as FAIL with the exception |
| IDCODE `0xFFFFFFFF` | board not programmed or TDO unwired | program first; `README.md` debug table |

## 9. References and what each is used for

| Area | Source | Used for |
|---|---|---|
| CLB | AMD UG474 | LUT6_2 fracture, CARRY4 MUXCY/XORCY, FDRE/FDSE priority, routable CE/SR |
| Configuration | AMD UG470; prjxray `bitstream.py`/`crc.py` | JTAG instruction codes, CRC-32C before startup, GSR→GTS→GWE→DONE, readback, capture, BRAM contents in the bitstream; frames at M13 |
| Scan-chain protocol | OpenFPGA `config_protocol.rst` (`scan_chain`); Aegis `configuration.md` | chain through tile config flops; shift + shadow register |
| Frame protocol (M13) | OpenFPGA `frame_based`; UG470 FAR/FDRI/FDRO | address decoders, auto-increment |
| Routing / VPR arch | OpenFPGA `k6_frac_N10_tileable_adder_chain_dpram8K_dsp36_fracff_40nm.xml` | L4 unidirectional, Wilton Fs=3, fc, column blocks, fle modes, adder/dff models, pack patterns |
| PnR | VPR 9 (VTR); VTR `prepack.cpp` | M9 place & route; pack-pattern rules; M12 reference results |
| PnR algorithms (M12) | McMurchie & Ebeling, "PathFinder" (FPGA 1995); Betz & Rose VPR placer (simulated annealing, bounding-box cost, FPL 1997); nextpnr (read only) | negotiated-congestion router, annealing placer |
| BRAM | AMD UG473 | synchronous read, write modes, DOA_REG, INIT separate from config |
| DSP | AMD UG479 | A25/B18/D25, pre-adder, 25×18, P48, OPMODE subset, PCOUT→PCIN |
| I/O, clock | Aegis `io.md`, `clock.md`; PYNQ-Z2 master XDC | I/O tile, user clock (sysclk H16, 125 MHz) |
| Synthesis | yosys `synth_xilinx`, Aegis techmap (read only) | cell library, maps, `memory_libmap` rules |
| Bitgen | F4PGA / prjxray FASM | feature = value between PnR and bits |
| Area | ZUMA (Brant & Lemieux, FCCM 2012) | configuration memory in host LUTRAM (M12b candidate) |

---

## 10. Milestones in detail

### M0: copy + `hw/` layout + adaptable Tcl (DONE)

Delivered: the full copy of `bob/`; the `hw/` reorganisation (no RTL logic change except an `IDCODE_VALUE` parameter on both tops); `sources.f`, `build.cfg`, `build.tcl` with the Vivado stub tests; `sim/*` reading `sources.f`; `hwtest.py`; `Makefile`; `REUSE.md`. Found and fixed the Tcl-in-XDC bug inherited from `bob/`.
Hardware: `idcode`, `bypass` (1 bit), `selftest` 11/11, `showcase-live`; project reuse and skip-on-no-change confirmed in Vivado. Reports in `docs/reports/M0`: 4271 LUTs, 5910 FFs, WNS +67.3 ns, WHS +0.083 ns.

### M1: `device.py` (DONE)

Delivered: `software/bob/device.py` (tile type = ordered fields `name/offset/width/kind/group`; row-major tiles with `chain_lo`; `locate`, `chain_bit`, `decode`, `encode`, `pips`); generated `device.json` and `bob_params.vh`; `software/host/bitstream.py` driven by `device.json` (generated vectors byte-identical to M0); `tests/test_device.py` (12 tests, including an iverilog elaboration comparing 21 constants with `clb_pkg.sv`).
Hardware: M0 bitstream reused; `selftest` on the `device.json`-driven engine passes; `chain-length` measured 2896 on the board with a 16-bit marker.
Not done yet (belongs to M7): pads and chain order for non-CLB tiles.

### M2: scan-chain configuration plane (DONE)

**Goal:** a hardened JTAG configuration plane, proven on silicon in isolation before it replaces the fabric's old `IR_CONFIG` chain in M3.

**Why a standalone test top:** every milestone must be hardware-tested, and this one changes the TAP itself (IR width 4→6). Testing the config plane in a small top keeps a TAP or config bug from being tangled with the fabric. The 4×4 fabric and its old TAP (`jtag_tap.v`) stay untouched in `sources.f` until M3.

**Write first: `docs/bitstream-format.md`**, before any RTL. It is the spec both RTL and Python follow. Contents:

- **6-bit instruction register** (AMD 7-series codes, UG470; verify against UG470 before RTL):

  | Code | Name | DR | Notes |
  |---|---|---|---|
  | `000001` | SAMPLE | boundary | |
  | `100110` | EXTEST | boundary | |
  | `000111` | INTEST | boundary | **private**, not an AMD code |
  | `000010` | USER1 | 32-bit control/status | old USER word: ce, sr, cin, step, autostep |
  | `000011` | USER2 = CFG_CTRL | 64 | expected CRC in, status out |
  | `100010` | USER3 = CAPTURE | N user FFs | read-only snapshot |
  | `000100` | CFG_OUT | config chain | readback, never commits |
  | `000101` | CFG_IN | config chain | write, commits at Update-DR if length and CRC are right |
  | `001000` | USERCODE | 32 | `USERCODE_VALUE` (milestone number) |
  | `001001` | IDCODE | 32 | reset instruction |
  | `001011` | JPROGRAM | 1 (bypass) | clears config, re-asserts GSR/GTS, clears DONE |
  | `001100` | JSTART | 1 (bypass) | steps startup while in Run-Test/Idle |
  | `111111` | BYPASS | 1 | |

  Capture-IR loads `{DONE, COMMITTED, CRC_ERR, 1'b0, 2'b01}`, so a plain IR scan reports status (in the spirit of 7-series; the two LSBs `01` are what IEEE 1149.1 requires). Unknown codes select BYPASS.
- **Chain:**
  - order and width from `device.json`; chain bit k = k-th bit shifted in (LSB-first); TDI enters the top tile's MSB, TDO leaves tile 0's bit 0
  - Capture-DR (CFG_IN or CFG_OUT) loads every tile's shift register from its shadow register
  - Shift-DR shifts
  - Update-DR commits shift → shadow **only** in CFG_IN, and only if the bit count equals the chain width **and** the CRC matches
- **CRC:** standard CRC-32C (Castagnoli, poly `0x1EDC6F41`, reflected `0x82F63B78`, init `0xFFFFFFFF`, final XOR `0xFFFFFFFF`), computed bit-serially over exactly the bits shifted in during one CFG_IN Shift-DR, in shift order.
  - The chain width must be a multiple of 8 to equal the byte-wise CRC-32C; 2896 = 362 bytes. Otherwise the serial definition rules.
  - The init value is non-zero on purpose: a stuck-low TDI can't produce a matching all-zero chain against the power-up expected value of 0.
  - Check value: CRC-32C("123456789") = `0xE3069283`.
- **CFG_CTRL DR (64 bits, LSB-first):**
  - capture: `[31:0]` CRC computed over the last CFG_IN shift; `[47:32]` bits shifted in that CFG_IN (saturating); `[48]` CRC_OK; `[49]` CRC_ERR; `[50]` LEN_ERR; `[51]` COMMITTED; `[52]` GSR; `[53]` GTS; `[54]` GWE; `[55]` DONE; `[63:56]` format version `0x02`
  - Update-DR writes the **expected CRC** from `[31:0]` **only if `[63:56] == 0xC5`** (a write key, like UG470's MASK guard). A read that shifts zeros changes nothing.
- **Startup:**
  - power-up and after JPROGRAM: config = 0, COMMITTED = 0, GSR = 1, GTS = 1, GWE = 0, DONE = 0, errors cleared
  - JPROGRAM acts at Update-IR
  - JSTART: every TCK rising edge in Run-Test/Idle with IR = JSTART advances one phase **if COMMITTED**: release GSR → release GTS → assert GWE → assert DONE. The host clocks ≥ 12 TCKs in RTI, as UG470 describes for JSTART.
  - Without COMMITTED, DONE never rises.
  - A later valid CFG_IN commit replaces the config live without resetting startup (keeps today's "load another design" flow). JPROGRAM gives a clean state.
  - Test-Logic-Reset doesn't touch config or startup (as on AMD parts).
- **Host load sequence:** JPROGRAM → CFG_CTRL write (key `0xC5`, expected CRC) → CFG_IN shift (exactly W bits) → CFG_CTRL read (COMMITTED, CRC_OK, count = W) → CFG_OUT readback = word → JSTART + 12 TCK in RTI → IR capture or CFG_CTRL shows DONE.
- **`.bit` wrapper for chain files** (host-side only; the chip never sees it): magic `BOBC`, format version, device name, chain width, CRC-32C, then the chain bytes LSB-first. The host checks name, width and CRC before touching hardware.

**RTL (new files; old ones untouched):**
- `hw/src/core/jtag_tap6.v`: copy of `jtag_tap.v`.
  - kept: the state machine, falling-edge TDO and update latches, synchronous-`tlr` note, IDCODE, BYPASS, USER1 control word with manual/auto step
  - changed: 6-bit IR with the codes above; USERCODE; the CONFIG register moved out
  - exports qualified strobes (`cfg_capture/shift/update`, `sel_cfg_in`, `ctrl_*`, `cap_*`, `bsr_*`), `jprogram_pulse`, `rti_jstart`, and takes external DR outputs (`cfg_so`, `ctrl_so`, `cap_so`, `bsr_so`) plus status bits for Capture-IR
- `hw/src/core/cfg_tile_sr.v`: one tile's config: `sr` (posedge shift/capture) + `cfg` shadow (negedge commit or clear). `si` enters the MSB, `so = sr[0]`. Parameter `W`. (OpenFPGA `scan_chain` + Aegis `shiftReg`/`configReg`.)
- `hw/src/core/cfg_mem.v`: `NTILE × TILE_W` instances of `cfg_tile_sr` chained (tile i+1 `so` → tile i `si`); flat `cfg` output bus in the same bit layout the fabric already consumes. **This is the module M13 replaces.**
- `hw/src/core/cfg_ctrl.v`:
  - serial CRC-32C and bit counter during CFG_IN Shift-DR; expected-CRC register with write key
  - `commit` decision (count == W && CRC ok) given to `cfg_mem`
  - error and COMMITTED flags; startup FSM (GSR/GTS/GWE/DONE); the CFG_CTRL shift register
- `hw/src/core/capture_chain.v`: parameter N; Capture-DR loads `d[N-1:0]`, Shift-DR shifts, `so = sr[0]`; read-only.
- `hw/src/top/cfg_test_top.v`: board top, IDCODE `0x4BEEF093`, USERCODE `0x00000002`.
  - `jtag_tap6` + `cfg_ctrl` + `cfg_mem` (4 tiles × 16 bits = 64-bit chain) + `capture_chain`
  - capture chain (16 bits) = `{btn, sw, 2'b00, counter[7:0]}`
  - `counter` is an 8-bit TCK-domain counter that counts only while GWE = 1, is held at 0 while GSR = 1, and is enabled by USER1 ce/step
  - LEDs: `led[2:0] = GTS ? 0 : cfg[2:0]` (config bits shown only after startup), `led[3] = DONE`
  - no boundary-scan ring needed here (SAMPLE/EXTEST/INTEST fall back to BYPASS in this top)

**Tools / host:**
- `software/bob/chainbits.py`: `crc32c_bits(word, width)`; a byte-wise CRC-32C reference; `.bit` write/read/validate; `load_sequence` description.
- `software/host/cfgplane.py`: 6-bit IR constants; `jprogram`, `write_expected_crc`, `cfg_in`, `status()` decode, `cfg_out`, `jstart(tcks=12)`, `capture(n)`, `usercode`, `load(word, width)` (the full sequence with checks and a per-pulse fallback like `fpga.load_bitstream`).
- `software/host/hwtest.py` `MILESTONE["M2"]`. The regression for this top is `idcode` + `bypass` (the fabric self-test returns at M3). New checks:
  - `usercode` (= 2)
  - `ir-capture` (`01` LSBs, DONE = 0 after JPROGRAM)
  - `load-readback` (random 64-bit word commits, CFG_OUT equals it, a second read is unchanged)
  - `crc-reject` (one flipped bit → CRC_ERR, config unchanged)
  - `len-reject` (63 bits → LEN_ERR)
  - `startup` (JSTART without commit leaves DONE = 0; with commit GSR→GTS→GWE→DONE, LD3 lights, LD2..0 show cfg[2:0])
  - `jprogram` (clears config, LEDs dark, DONE = 0)
  - `capture` (the capture chain reads SW/BTN as the live SAMPLE does; the counter holds 0 under GSR and advances after startup)
- `hw/build.cfg`: `tag = M2`, `top = cfg_test_top`, `idcode = 4BEEF093`, `usercode = 00000002`, `sim_top = tb_cfg`. `build.tcl` also passes `USERCODE_VALUE`.
- `hw/tb/tb_cfg.v` + `sim/run_cfg_sim.sh`: probe tasks from `tb_fpga4x4.v` with IR width 6; vectors (word, CRC, expected status) generated by `chainbits.py` into `hw/tb/cfg_vectors.vh` so the RTL is checked against the Python CRC.
- `sim/lint.sh`: add `cfg_test_top`. `Makefile`: add the new sim to `make check`.

**Done when (simulation, `make check`):**
- IDCODE and USERCODE read through the 6-bit IR; Capture-IR LSBs are `01`
- random chains load through CFG_IN and read back bit-exact through CFG_OUT; reading twice changes nothing
- a one-bit-corrupted chain sets CRC_ERR and leaves the previous config; a wrong length sets LEN_ERR
- the RTL-computed CRC equals `chainbits.py` for every vector; `crc32c_bits` equals the byte-wise reference and `0xE3069283`
- CFG_CTRL read without the key doesn't change the expected CRC
- `cfg` outputs don't change during Shift-DR, only at the commit
- JSTART without commit leaves DONE low; with commit the phases go GSR→GTS→GWE→DONE in order
- JPROGRAM clears everything; CAPTURE returns known values; Test-Logic-Reset keeps config
- lint clean; M0/M1 sims and tests still green

**HW:** `make hwtest M=M2` passes all checks above on the board; `docs/hwtest/M2.md` manual steps (LD3 lights after JSTART; LD2..0 show the loaded bits; flipping SW changes the CAPTURE readout). Reports in `docs/reports/M2`.

### M3: config plane into the 4×4 fabric + host loader (DONE)

- `hw/src/fabric/fpga4x4.v`: `jtag_tap` → `jtag_tap6`; `cfg` from `cfg_mem #(NTILE=16, TILE_W=181)`, sizes from `bob_params.vh`; `capture_chain` over the 16 CLB `o`.
- Minimal CLB change for GSR: `clb.sv` gets a `gsr` input (`if (gsr) q <= ff_rstval` ahead of SR/CE), so GSR resets every FF regardless of `ff_sr_en` (UG470 semantics). CE is gated by GWE.
- Fabric pad outputs forced to 0 while GTS = 1; true hi-Z comes with `io_tile` in M7.
- Retire the old `jtag_tap.v` from `fpga4x4`. `mini_fpga` stays on the old 4-bit TAP (as built: legacy single-CLB top, still simulated and linted; ties gsr=0, gwe=1).
- As built: `fpga4x4.v` keeps its size parameters (checked against `device.py` by `tests/test_device.py`) instead of including `bob_params.vh`, so no include-path changes were needed in Vivado/iverilog/verilator. The M0/M1 hwtest for the old 4-bit fabric no longer applies to the new bitstream.
- Host: `fpga.py`/`dirtyjtag.py` move to 6-bit IR constants; `fpga.load_bitstream` uses `cfgplane.load` (JPROGRAM → CRC → CFG_IN → status → CFG_OUT verify → JSTART, per-pulse retry kept); `sim/gen_vectors.py` and `tb_fpga4x4.v` use the new load sequence. `chain-length` check moves to CFG_OUT.
- `build.cfg`: `tag = M3`, `top = fpga4x4_top`, `idcode = 5BEEF093`, `usercode = 3`.

**Done when:** the 174 fabric checks pass through the new load path; M2's config-plane checks pass on the fabric's 2896-bit chain.
**HW:** full regression (idcode, bypass, selftest 11/11, showcase-live, chain-length) plus a corrupted chain rejected with the previous design still running; DONE after JSTART; CAPTURE shows CLB outputs; `util.rpt` compared with M0 (expect roughly 2× config FFs for the shadow registers; record it).

### M4: CLB core + user clock + LUT size as a parameter (DONE)

- **LUT size K becomes one parameter** (user request, 2026-09-14), so a later LUT6→LUT4 switch is mostly "change K, regenerate, re-test":
  - `hw/src/clb/lut6.sv` → `lutk.sv` with parameter `K` (INIT `2**K` bits; O5 = the K-1 sub-tree, as UG474's LUT6_2 does for K=6)
  - `clb.sv`, `clb_pkg.sv`, `tile.v` take `K` (connection box has K input muxes)
  - `software/bob/device.py` gets `lut_k` (default 6); `init` = `2**K` bits; `cb_i0..cb_i{K-1}`
  - `software/host/bitstream.py`: every `64`/`range(6)`/`0x1F` derived from K
  - `designs.py`: designs wider than K are skipped or split when K < 6
  - pytest runs the device and bitstream tests at K=4 and K=6; the hardware build stays K=6
  - Effort for a later switch, estimated 2026-09-14: 1–2 days before M8; 3–5 days after M10 (yosys `abc -lut K`, OpenFPGA k4 arch, re-run golden tests). The M2 config plane doesn't depend on K.
- `clb.sv` (UG474): routable CE and SR per tile (selected by a connection-box mux instead of globals), FDRE/FDSE priority kept, GSR/GWE from M3.

**As built (2026-09-14):**
- **LUT size K:**
  - `lutk.sv` has parameter K; `lut6.sv` moved to `docs/reference/`, and `tests/test_lutk.py` proves lutk(6) == lut6 on random vectors
  - `device.py` takes `lut_k`; `bob_params.vh` provides `BOB_LUT_K` and all derived widths
  - `clb_pkg.sv` takes only K from the header and derives everything else, and pytest compares it with the header at K=6 and K=4
  - `tile.v`, `fabric.v`, `fpga4x4.v` and `mini_fpga.v` include `bob_params.vh` (Vivado `include_dirs` set by `build.tcl`; the fingerprint includes the header)
  - `designs.py` skips designs wider than K (`and6`/`xor6` at K=4)
  - `sim/run_k4_sim.sh` runs the CLB sweep and the full fabric testbench at K=4 from a generated K=4 description, in `make check`
- **Routed CE/SR:** the connection box has K+2 muxes (`cb_ce`, `cb_sr`); `Design.lut(..., ce=, sr=)` defaults to CE = const1, SR = const0. The tile is 191 bits at K=6.
- **Ctrl tile** (8 bits, chain head): `clk_mode` and `clk_div`, so the chain is 3064 bits. `Design.set_clock("jtag"|"run", div)`.
- **User clock** (`hw/src/core/clock_ctrl.v`):
  - fabric flops run on `sysclk` (H16, BUFG in the top) with `gce` as the user clock; UG949 recommends a clock enable over a logic-generated clock
  - jtag mode: one pulse per TCK rising edge while USER1 ce (plus step/autostep); run mode: every 2^(div+8) cycles
  - TCK, USER1 ce/step/cin, GSR, GWE and the config are synchronised with ASYNC_REG two-flop synchronisers
- **XDC:**
  - sysclk 8 ns, `set_clock_groups -asynchronous` between tck and sysclk
  - multicycle 120/119 on `u_clb/q_reg` → `u_clb/q_reg` and from `cin_m_reg` (gce pulses are at least 120 cycles apart)
  - USER1 sr no longer used by the fabric (superseded by routed SR)
- **Models:** `software/bob/model.py` is a cycle model with flip-flops. `tb_clb.sv` runs a 128-flag-combination sweep (7040 checks) against it; the fabric testbench checks routed CE/SR and a 4-bit carry-chain counter (JTAG-stepped every edge, free-running with TCK stopped) against it.
- **Mutation tests:** `sim/mutate_fabric.sh` adds no-gce, ce-not-routed, step-ignores-ce and divider-off-by-1 mutants.
- User clock: 125 MHz sysclk (H16, **verify** against the PYNQ-Z2 master XDC) → BUFG → divider (Aegis `clock.md` style). TCK remains the configuration clock; GSR/GTS/GWE synchronised into the user clock with 2-FF synchronisers. XDC gets `create_clock` for sysclk and `set_clock_groups -asynchronous` with TCK (plain XDC).
- `software/bob/model.py`: starts from `simulate()` in `software/host/bitstream.py`, adds FFs and the clock.
- `device.py`: new CLB fields (CE/SR mux) → `make device`; `bitstream.py` follows.

**Done when:** a flag sweep (comb/FF/carry/O5/CE/SR/GSR) matches `model.py`; the `tb_mini_fpga.v` vectors still pass.
**HW:** a counter design blinks an LED from the user clock at the expected rate; CE/SR from switches stop and reset it; timing met on the sysclk domain.

### M5: BRAM tile (UG473 RAMB18E1 subset) (DONE)

- `hw/src/tiles/bram_tile.v`:
  - 18K true dual port with **synchronous read**
  - WRITE_MODE WRITE_FIRST/READ_FIRST/NO_CHANGE, optional DOA_REG/DOB_REG, per-port CE/RST
  - width modes 1K×18, 2K×9, 4K×4, 16K×1 as config bits
  - written to Vivado's RAM inference template, so it maps to a host RAMB18
- INIT contents: separate `BRAM_INIT` DR on USER4 (`100011`) with address auto-increment, writable only while GWE = 0 (UG470 separates BRAM contents from config). Readable for verify.
- Spans 4 CLB rows (VPR `memory` height in the OpenFPGA arch). `device.py` gets the BRAM tile type.

**As built (2026-09-14):**
- **RTL:** `hw/src/tiles/bram_core.v`, `bram_jtag.v`, `bram_tile.v`.
- **Memory:** 1024 × 18 true dual port in Vivado's READ_FIRST template (one RAMB18); WRITE_FIRST and NO_CHANGE derived from it with registers, so the write mode is a configuration bit. Output latch semantics with EN/RST, DOA/DOB_REG with REGCE and RSTREG priority.
- **Position:** the tile is on the fabric's East edge and spans the 4 rows; until M7 it connects through the 16 East edge tracks, with a 5-bit source mux per pin and a 6-bit mux per output. The 424 config bits close the chain, which is 3488 bits.
- **USER4:** the contents register (LOAD_PTR/WRITE/READ, locked once GWE = 1) and SET_DRIVE, which drives BRAM pins from JTAG so write modes can be stepped one clock at a time.
- **Software:** `model.py` `Bram`, driven by `tb_bram.v` (all 36 mode × register combinations). `bitstream.py` has `bram_mode` / `bram_pin` / `bram_out` with automatic East-track allocation. Designs `d_bram_rom` and `d_bram_jtag`.
- **Trimmed from RAMB18E1:** the 9/4/1-bit width modes (bit-level addressing would stop RAMB18 inference), per-byte WE, and separate RSTRAM/RSTREG pins.
- **UNISIM comparison:** the RAMB18E1 UNISIM model isn't available on the Mac. The Vivado `util.rpt` RAMB18 check (enforced by `tests/test_reports.py` from M5) plus the hardware `bram-modes` check against `model.py` take its place.

**Done when:** all modes, both ports and CE/RST match a behavioural model and the Xilinx `RAMB18E1` UNISIM model on the same vectors; INIT through JTAG reads back.
**HW:** `util.rpt` shows RAMB18 (not LUTs); INIT loaded over JTAG reads back; a ROM test shows addressed contents on the LEDs as the switches step the address; JTAG read/write covers all three write modes.

### M6: DSP tile (UG479 DSP48E1 trimmed) (DONE)

- `hw/src/tiles/dsp_tile.v`:
  - A 25, B 18, D 25; pre-adder A±D; M = 25×18 signed; P 48
  - OPMODE subset {M, M+C, P+M, (PCIN>>17)+M}
  - AREG/BREG/DREG/MREG/PREG as config bits; per-group CE/RST; PCOUT→PCIN cascade
  - UG479 inference style, so it maps to a DSP48E1

**As built (2026-09-14):**
- **RTL:** `hw/src/tiles/dsp_core.v` and `dsp_tile.v` (flat buses; no references into generate scopes).
- **Slices:** two DSP48E1-style slices with a PCOUT→PCIN cascade: A25/B18/C48/D25, pre-adder D±A, 25×18 signed multiplier, P48. Static opmodes M, M+C, P+M (fed back from the P register), (PCIN>>>17)+M. AREG/BREG/CREG/DREG/MREG/PREG as config bits; CE/RST in 4 groups (C shares P's).
- **Position:** the tile is on the fabric's North edge, connected through its 16 tracks. Buses take their source per bus (const0 / JTAG drive / fabric tracks as bits 0..15); the 8 controls per slice have 5-bit muxes; 16 outputs have 7-bit muxes. 232 config bits; chain 3720.
- **JTAG:** a **private** instruction `101000` (DSP), 256 bits: a drive word for every data bit and control, plus live P0/P1 readback. All four AMD USER codes were already taken.
- **Software:** `model.py` `Dsp` plus cascade helpers, `tb_dsp.v` (1344 checks), the `bitstream.py` DSP API (`dsp_config`, `dsp_track`, `dsp_ctrl`, `dsp_out`), and designs `d_dsp_jtag`, `d_dsp_mult_sw`, `d_dsp_accum`.
- **Reports:** `tests/test_reports.py` requires DSPs ≥ 1 from M6.
- **Trimmed from UG479:** dynamic OPMODE/INMODE/ALUMODE pins, ALU functions other than add, the 30-bit A port and ACOUT/BCOUT, pattern detect, CARRYIN, and separate CEC/RSTC.

**Done when:** random vectors match a Python model in every mode/register combination; a 2-tile cascade matches.
**HW:** `util.rpt` shows DSP48E1; JTAG-driven vectors give the same P as the model; an accumulator on the user clock counts visibly on the LEDs.

### M7: heterogeneous fabric + routing + I/O (DONE)

- `device.py`: column types CLB/BRAM/DSP/IO; unidirectional L1 + L4 tracks, Wilton switch box Fs=3, connection-box fc_in/fc_out taken from the OpenFPGA k6_frac_N10 dpram8K/dsp36 arch; chain order control → IO → tiles.
- It emits `hw/src/generated/fabric.v` (from the generate pattern in `fabric.v`, `mux_bank.v` for CB/SB muxes), `software/bob/vpr_arch.xml` and the routing-resource-graph bit map.
- `hw/src/tiles/io_tile.v`: `bsc_cell.v` + GTS, 8-bit I/O (Aegis `io.md`). Grid size set from the M3–M6 utilisation reports.

**Done when:** hand-built chains route pad → LUT → FF → BRAM → DSP → pad; RTL equals `model.py` every cycle; VPR loads `vpr_arch.xml` and routes a trivial netlist.
**HW:** the generated fabric fits; that hand-built design works from switches to LEDs; all earlier designs re-run.

**As built (2026-09-14), OpenFPGA's method:** describe the architecture → VPR builds the tileable routing-resource graph → generate the fabric RTL, the chain map, the router and the model from that one graph.
- **Architecture** (`software/bob/device.py` `ARCH`, written by `vpr_arch.py`, derived from OpenFPGA `k6_frac_N10_tileable_adder_chain_dpram8K_dsp36_fracff_40nm.xml`).
  - *Kept from the reference:*
    - `tileable="true" through_channel="false" concat_pass_wire="true"`
    - io perimeter with EMPTY corners, clb fill, hard-block columns
    - one L4 unidirectional segment, sb/cb pattern all 1
    - Wilton Fs=3, switches `0` / `ipin_cblock`
    - fc_in 0.15 / fc_out 0.10, fc 0 on carry and clock pins
    - a carry direct
  - *Different, and why:*
    - **1-BLE CLB**: pins I[K], ce, sr, cin | O, O5, cout. N10 with local routing is too many config flops for an XC7Z020.
    - carry runs South→North (`dy=+1`, as bob always did).
    - the BRAM is bob's 1024×18 true dual port, height 4 (not dpram 1024×8).
    - the DSP is bob's DSP48E1-style slice, height 4, with a `pcout→pcin` direct (not the combinational mult_36).
  - *Grid:* VPR 10×10, core 8×8. BRAM column x=3 (bram0 rows 1–4, bram1 rows 5–8), DSP column x=6 (dsp0, dsp1), so 48 CLBs. 32 io pads (capacity 1).
  - *Channel width:* W=24, chosen by sweeping VPR at 8×8. Routing bits were W=16: 4.2k, W=24: 6.0k, W=32: 7.8k. W=24 gives IPIN fan-in 4 (fc_in 0.15 × 24).
- **VPR:** `software/bob/vpr_rrgraph.sh` (Docker, `make rrgraph`) routes `arch/and2.blif` at W=24 for K=6 and K=4 ("Circuit successfully routed", `arch/bob_k*_vpr.txt`) and writes the rr graph. The graphs are committed (gzip, ~80 kB), with a stamp holding the arch sha256, image digest and command.
- **Fabric from the graph** (`device.py` + `fabric_gen.py`):
  - Every CHANX/CHANY/IPIN node with driving edges is a `bob_mux` (value 0 const0; IPIN value 1 const1; inputs by ascending node id).
  - IPINs driven only by an OPIN are wires (42 carry directs, 48 cascade bits = 90 directs in all), and undriven nodes are 0 (bottom-row `cin` = USER1 cin).
  - K=6: 2105 muxes (792 IPIN, 719 CHANX, 594 CHANY) = 5934 routing bits.
  - Chain 9400 = ctrl 8 + 48 CLB × 71 + 2 × 8 + 2 × 16 + routing, then a byte pad. K=4: 6808.
  - `bob_fabric.v` is 2773 flat lines; `bob_fpga.v` wraps it with the unchanged configuration plane (one 9400-bit `cfg_tile_sr`), the 64-cell boundary (2 cells per pad, GTS-gated outputs), USER4 and the DSP register.
- **Hard blocks:**
  - `bram_block.v` (per port: fabric pins or the USER4 drive word) and `dsp_block.v` (per bus plus controls: fabric or the DSP drive word). The cores are unchanged.
  - `bram_jtag.v` serves both BRAMs with a new SELECT command (5) and a target field; version 0x07.
  - `dsp_jtag.v` is M6's register, version 0x07.
- **I/O:** no separate `io_tile.v`. An io block is one VPR pad (outpad IPIN mux, inpad OPIN) plus its two boundary cells in `bob_fpga.v`; GTS forces outputs 0 (no true hi-Z: the board pins have fixed directions). The board uses pads 8/10/12/14/16/18 for SW0/SW1/BTN0–3 (West) and 9/11/13 for LD0–2 (East); every other pad is reachable only by boundary scan.
- **Host:**
  - `bitstream.py`:
    - `Design` API in (x,y): `lut`, `output`, `pad_output`, `bram_pin(..., bram=)` / "jtag", `dsp_pin`, `dsp_ctrl`, `dsp_config`
    - BFS router over the rr graph, with fanout sharing and rip-up reordering when a net fails
    - `simulate()` = `model.Fabric`
  - `model.py` evaluates exactly the muxes and directs the RTL has.
  - `fpga.py` translates board vectors to and from the 64-cell boundary.
  - `hwtest.py` M7 checks: bram-select, pipeline, counter8, pipeline-live.
- **Tests:** `tb_bob.v` runs sections [1]–[19] of `tb_fpga4x4` on the new fabric, plus:
  - [19] two BRAMs behind SELECT
  - [20] pad→LUT→FF→BRAM→DSP→pad
  - [21] an 8-bit counter through seven carry directs, 300 edges
  - [22] 4 random routed netlists of 14 CLBs, where every CLB output and LED is compared with `model.py` after each of 24 clocks. This is the "RTL equals model every cycle" proof.

  `run_k4_sim.sh` runs the same at K=4. pytest checks the mux encoding, that every pip is one field value, that every block pin is an rr node, the directs, routes forming non-sharing trees, the reference routing parameters kept in the arch, and the VPR route logs.
- **Retired:** `fabric.v`, `tile.v`, `mux_bank.v`, `fpga4x4.v`, `fpga4x4_top.v`, `bram_tile.v`, `dsp_tile.v`, `tb_fpga4x4.v` (frozen in `release/hw_M6/`). `clb_pkg.sv` now has CLB constants only. `bscan.py` (interactive, 9-cell) is not ported.
- **Pre-Vivado estimate** (yosys `synth_xilinx -flatten` on `bob_top`, with `clb.sv`'s package import inlined because yosys can't parse it; `build/yosys/`):
  - ~23.0k LUTs (43% of the XC7Z020): LUT6 10.8k, LUT3 6.6k
  - 20.8k FFs, 2 RAMB18E1, 2 DSP48E1, 106 CARRY4
  - 5553 "logic loop" warnings: the routing graph's cycles, expected
  - synthesis took 3.5 min
- **Timing (2026-09-17 build):** setup WNS −1102 ns (sysclk) / −657 ns (TCK), hold met. The worst paths run through 101 routing loops, bouncing between dsp0 and dsp1 34 times, so no loop-free loaded chain can exercise them. They still expose two real gaps to fix at the next rebuild: cell-name multicycle filters stopped matching once synthesis renamed cells (e.g. `hold_qb_reg[17]_i_5__0`), and a programmable fabric cannot be bounded without its configuration. Planned: KEEP_HIERARCHY on u_fabric/u_chain; clean constraints on all fixed logic; boundary-based fabric exceptions justified by RTL-enforced rules (commit only while GWE=0, no ce+step mixing, TCK ceiling in dirtyjtag.py); per-chain timing sign-off with set_case_analysis on the config bits (M10). The hardware test passed on this bitstream.
- **Not done at M7:**
  - VPR packs and places only the trivial netlist; real designs through VPR are M9.
  - no L1 wires (the reference has only L4)
  - no per-pad config (pull-ups, drive) and no true tristate

### M8: synthesis (yosys) (DONE)

- `software/bob/synth/bob_cells.v` (LUT6_2, CARRY, DFF with CE/SR, BOB_BRAM18, BOB_DSP), `techmap.v`, `bram.rules`, `synth_bob.tcl` (`synth -run`, `abc -lut 6`, `memory_bram`, DSP techmap, patterned on `synth_xilinx`), writing BLIF for VPR.
- Examples in `work/examples/`: gates, adder, counter, blinky, ram, fir. The `designs.py` functions are rewritten as Verilog.

**Done when:** yosys stats show only bob cells; the post-synthesis netlist equals the source in iverilog.
**HW:** fabric unchanged (no rebuild); a synthesised `gates.v`, hand-placed, loads and matches.

**As built (2026-09-14):**
- **Cell library** (`software/bob/synth/bob_cells_sim.v`):
  - `$lut` (K from `device.json`)
  - `BOB_FDRE` / `BOB_FDSE`: sync R/S beats CE, INIT = reset = GSR value
  - `BOB_ADD`: one CLB in carry mode, LUT A^B(^1), DI = I0 = A
  - `BOB_BRAM18`: 1024×18 TDP, no output register
  - `BOB_DSP`: 25×18 signed, opmode M
  - The BRAM/DSP models instantiate the fabric's `bram_core.v`/`dsp_core.v`.
- **Script** (`software/bob/synth.py`): the `synth_xilinx` pass order, with bob maps patterned on yosys's xilinx maps.
  - DSP: `mul2dsp` 25×18.
  - BRAM: `memory_libmap` with `bob_brams.txt`, whose cell names were probed from the tool.
  - Arithmetic: `$alu` → BOB_ADD (rule prefix `_80_`, so it beats the generic `_90_alu`; BI must be constant).
  - Flip-flops: `dfflegalize $_SDFFE_PP0P_/PP1P_ r`.
  - LUTs: `abc -lut K`.
  - Outputs: JSON (placer), BLIF (VPR, M9) and a simulation netlist. It fails on any non-bob cell or more than one clock.
- **Proofs** (`software/bob/equiv.py`, `software/bob/place.py`, `hw/tb/tb_synth.v`):
  - The source and netlist are simulated together over 300 random cycles, compared before and after each edge. The source trace is saved.
  - `place.py` packs, places and routes:
    - add+FF and LUT+FF merges
    - O5 for extra loads of a LUT with K-1 or fewer inputs
    - carry chains up CLB columns, with a generator CLB at row 1 (the global USER1 cin never enters a design) and a tap CLB when a chain continues in the next column
    - BRAM/DSP blocks, then `bitstream.Design` routes
  - The placed bitstream on `model.py` and on the fabric RTL (`tb_synth`) is compared with the source trace.
- **Examples:** gates (3 LUT), adder (3 ADD), counter (6 ADD + 6 FDRE with CE/R on pins), blinky (12 ADD + 12 FDRE, chain crosses columns), ram (1 BRAM, contents over USER4), mult (1 DSP + 13 FDRE + 3 LUT). All pass the netlist, model and RTL comparisons against the source.
- **Hardware:** `hwtest M8` rebuilds each example, loads it, writes BRAM contents, runs JSTART, then clocks 64 times with USER1 autostep + INTEST and compares the LEDs after each clock with the source trace.
- **Gotchas:** SystemVerilog keywords `ref` and `before` as identifiers; iverilog's scanner overflows on the 18432-digit binary BRAM INIT (rewritten as hex, x → 0); zsh `echo =====` is `=`-expansion; `sed -E` on macOS has no `\s` / `\b` (use perl).
- **Not at M8:**
  - async resets and latches (rejected)
  - more than one clock
  - a carry out used in the middle of a chain
  - BRAM output registers and DSP register absorption
  - Placement is a simple column fill; real packing, placement and routing are VPR's job at M9.

### M9: PnR with VPR (DONE)

- `software/bob/vpr_run.py`: VPR in Docker (amd64), fixed seed, `.pcf` → fixed pins.
- `software/bob/fasm_from_vpr.py`: `.net/.place/.route` → bob FASM (pip → mux value, BLE → LUT INIT and flags).

**Done when:** every example routes; FASM is legal against `device.json`; same seed gives the same result; timing and wirelength reports are printed.
**HW:** VPR-routed `gates.v` and `counter.v` (minimal FASM → chain) run on the board.

**As built (2026-09-17):**
- **Architecture** (`software/bob/vpr_arch.py`): the CLB pb_type now has two modes, as the reference's fle does:
  - `logic`: `.names` LUT K → `bob_ff`
  - `arithmetic`: `bob_add` (A^B plus MUXCY/XORCY, a = I[0], b = I[1]) → `bob_ff`, with pack patterns `ble` (lut.out → ff.D) and `chain` (clb.cin → add.cin, add.cout → clb.cout, add.sumout → ff.D)

  Models `bob_add` and `bob_ff` are in `device.py` `vpr_models()`. Tile pins are unchanged: `make rrgraph` gave byte-identical K=6 and K=4 rr graphs, so no rebuild.
- **`software/bob/vpr_run.py`** (Docker; `make vpr`) rewrites the yosys JSON into `<top>.eblif`:
  - Constants on pins (CE/SR, BRAM/DSP pins, adder a/b, output pads) are left open and recorded, then become IPIN const0/const1. Constant LUT inputs are folded.
  - Carry chains are cut to the column height (4), each piece with a generator (a = b = carry-in) and, if it continues or its carry out is used, a tap (sumout = cin).
  - FDRE/FDSE → `bob_ff`, with the type kept in `<top>.vpr.json`.
  - A buffer LUT is inserted when an FF's D is not a single-load LUT/adder output, and for a second output on the same net.
  - Absolute paths are stripped from cell names so results commit.

  Pins are fixed with `--fix_clusters` (clk on a spare pad; the clock is global). VPR runs with `--read_rr_graph` on the committed graph, a fixed seed, buffer absorption and sweeps off. Results are committed in `software/bob/vpr/<top>/` with `stamp.txt` (arch sha, eblif sha, seed, image digest, command, wirelength, critical path, result hash).
- **`software/bob/fasm_from_vpr.py`** (no Docker) turns the committed result into chain bits:
  - `.net`: LUT INIT re-indexed through VPR's `port_rotation_map`; arithmetic INIT and cy_en; FF flags
  - `.place`: the tile
  - `.route`: each node selects its predecessor; directs are VPR global nets and have no bits

  Output is FASM (`clb_x2y3.init = 64'h…`, `rr1234 = 3'h5`), legality-checked against `device.json`, then the chain. It refuses stale results.
- **Proofs:**
  - `model.py` == source trace, 300 cycles
  - tb_synth runs all 12 designs (6 hand-placed, 6 VPR) == source
  - `tests/test_vpr.py`: fresh, legal, pads where fixed, chains ≤ column, stale refused, bad features rejected
  - `make vpr --repeat`: the same seed gives the same result hash
  - hwtest M9: `vpr-*` checks, 64 clocks each
- **Results:**

  | example | CLBs | wirelength | critical path |
  |---|---|---|---|
  | gates | 3 | 108 | 1.60 ns |
  | adder | 4 | 59 | 1.74 ns |
  | counter | 11 | 182 | 3.62 ns |
  | blinky | 15/16 | 144 | 4.85 ns |
  | ram | BRAM | 99 | 1.58 ns |
  | mult | 7 + DSP | 157 | 1.81 ns |

  Timing uses the reference's 40 nm numbers, not the emulated fabric.
- **Found and fixed:** the M8 `counter` source trace was all zeros: uniform random inputs assert the synchronous reset half the time, so M8's counter check (model, RTL and board) could not fail. `equiv.py` now uses biased vectors in 50-cycle segments; the counter trace reaches LED 0–6.
- **Gotchas:**
  - VPR asserts in `update_chain_root_pins` when a chain pattern has no primitive-to-primitive connection inside the cluster, and forbids pack patterns into a multi-mode ff ("Multi-fanout nets not supported"). Hence one `bob_ff` primitive, and the sumout → ff.D edge in the chain pattern.
  - `--fix_clusters` needs `--pack --place --route` given explicitly.
  - Colima only shares `$HOME`, so VPR work directories live in `build/`, not `/tmp`.
- **Not at M9:**
  - O5 is not offered to VPR, so one function per CLB
  - a carry out used in the middle of a chain
  - constant FF D, CE tied 0, SR tied 1
  - VPR timing does not model the emulated fabric
  - Single-feature deletion test: 477/527 caught. The survivors are mostly equivalent mutants (a generator whose carry-in is 0, a tap whose LUT inputs are const0); the rest are gaps in trace coverage.

### M10: bitgen + golden co-simulation (DONE)

- `software/bob/bitgen.py`: FASM → chain → CRC → `.bit` wrapper. `software/bob/cli.py`: `bob build design.v --pcf pins.pcf`, `bob load`.

**Done when:** bits → FASM → bits round-trips; every example's source Verilog equals the fabric RTL loaded with its chain through CFG_IN, on random vectors every cycle.
**HW:** `bob build` + `bob load` for every example; `hwtest.py` compares LEDs and CAPTURE against golden simulation.

**As built (2026-09-17):**
- **`software/bob/bitgen.py`** turns FASM (`feature = W'hV`) into a chain, checked against `device.json` (width, field, value, mux input), and a chain back into FASM. The decode refuses bits that no feature owns, so the round trip is exact. `.bit` is chain file version 2 (`docs/bitstream-format.md` §8, §8a):
  - v1 header and chain
  - sections: `BRAM` contents, `META` JSON
  - a file CRC-32C
- **`software/bob/cli.py`** (`./bob`):
  - `build`: synth → source == netlist == golden → VPR (reuses a fresh committed result, otherwise Docker) → FASM → bits → model == trace → `.bit`. Options: `--pcf`, `--clock jtag|run --div N`.
  - `load`: CFG_IN + readback → BRAM over USER4 → JSTART.
  - `info`, `fasm`.
- **Pins:** `.pcf` files with `set_io <port> <SW0..|LD0..|pad<N>>` (`vpr_run.read_pcf`). Committed variants live in `vpr_run.VARIANTS`: `gates_swapped` = gates.v + `work/examples/gates/gates_swapped.pcf`. Results are named per variant, and the stamp records top and pcf.
- **`software/bob/golden.py`:** the yosys JSON as Verilog with one wire per bit (`n<bit>`). `equiv.py` now simulates source, yosys netlist and golden together and saves every golden net after each clock (`trace.json` `nets`/`nets_after`). `vpr_run` records which yosys bit each VPR net carries (`net_bits`), and `fasm_from_vpr.capture_map()` gives CAPTURE bit → golden register.
- **Golden co-simulation** (`sim/tb_cosim.v`, `sim/gen_cosim.py`, `sim/run_cosim_sim.sh`, in `make sim`): 7 designs, each `bob build` → `.bit` → complete FPGA RTL through CFG_IN/USER4. The source Verilog and golden netlist are instantiated live with their own clocks. There are 100 fresh random cycles per design (seed ≠ build trace). LEDs == source == golden before and after each edge; CAPTURE == golden registers after each edge. 1707 checks, about 25 s. The shared JTAG harness is in `hw/tb/bob_harness.vh` (tb_synth uses it too).

  The testbench was mutation-checked; each of these fails it: a wrong golden net, a CRC-valid routing change, a missing source clock, unswapped pins, dropped BRAM contents, a wrong golden LUT.
- **hwtest M10** (`bob-*`, 7 checks):
  1. `bob build`
  2. `bob load` without start, with CFG_OUT readback decoded to FASM == `.bit` FASM
  3. JSTART
  4. 64 clocks, each with CAPTURE (every CLB flip-flop == golden) and LEDs == source

  `tests/test_hwtest_fake.py` runs this check against a stand-in board (`model.py` behind the JTAG instructions): it passes when the board is right and fails when CAPTURE is corrupted.
- **Gotchas:**
  - yosys' `_syn.v` renames cells and nets, so nothing inside it maps to fabric locations; hence golden.py.
  - A CAPTURE scan leaves INTEST, so the pads read the real switches. Only flip-flop CLBs are compared on the board; they don't clock outside INTEST with autostep.
  - VPR's `.net` top block carries the netlist file name; it is excluded from the result hash.
  - A variable called `name` shadowed the result name in `features()`.
- **Not at M10:** CAPTURE of combinational CLBs on the board; BRAM/DSP state in CAPTURE (not in the capture chain); designs whose ports aren't on the sw/btn/led convention get no model/trace check, only equivalence.

### M11: full hardware bring-up (DONE)

blinky, switches → LEDs, RAM and FIR on the PYNQ-Z2, verified by readback and CAPTURE. Reports committed.

**As built (2026-09-17):**
- **Examples:**
  - `switches.v`: live logic, plus a BTN3 toggle through a synchroniser and edge detector (6 CLBs).
  - `fir.v`: a 2-tap FIR with button coefficients on both DSP slices (12 CLBs). A 3-bit sample needed 17 CLBs, so the sample is SW1..0.

  Both are in `vpr_run.EXAMPLES`, so they are in `make vpr`, tb_cosim (now 9 designs), test_vpr and test_bitgen. The M8 hand placer's list is unchanged.
- **hwtest M11** (still on the M7 bitstream):
  - `bob-switches` / `bob-fir`: the M10 golden check.
  - `ram-readback`: 64 INTEST clocks, then JPROGRAM (GWE = 0 makes USER4 READ legal; BRAM contents survive). `bram_read` == `model.py` memory, and chain readback == `.bit`.
  - `blinky-rate`: CAPTURE of the 8 counter registers over 4 s == 14.9 Hz ± 10 %.
  - `live-*` (blinky, fir, mult, switches) on `--clock run --div 15` with the real switches: repeated CAPTURE → SAMPLE → CAPTURE bursts. When the registers are stable, `model.py` with those registers and the sampled pins == the sampled LEDs. CFG_OUT readback while running == `.bit`. Each result reports the input vectors and register states seen.
- **Stand-in board:** `tests/test_hwtest_fake.py` now models the free-running clock in real time, SAMPLE, JPROGRAM and USER4 READ, with a simulated person on the switches. Every M11 check passes on it, and fails on wrong LEDs, a clock 1.5× too fast, or wrong BRAM contents.
- **`bob build --clock run`** prints the user clock rate. At M10 a `--div 26` build (one clock per 137 s) looked like a dead board.
- **Reports:** `software/bob/report.py` → `docs/reports/M11/designs.md`, with cells, CLBs/BRAM/DSP, pins, wirelength, VPR path, FASM features and muxes, registers on CAPTURE, chain CRC and VPR result for all 9 designs. The chain CRCs equal the ones the board loaded at M10.
- **Why the live check is a model consistency check and not a trace comparison:** a person's inputs are unknown in advance. SAMPLE takes pins and LEDs in one Capture-DR, and CAPTURE gives the registers. A burst in which the registers moved (the 14.9 Hz clock ticked) is skipped, not failed.
- **First hardware run** (2026-09-17): everything passed except `ram-readback`.
  - **Stale BRAM words:** bram0[4..7] and bram1 held earlier tests' words. BRAM contents survive JPROGRAM and a new chain, and `bob load` wrote only up to the last non-zero word, so zero words kept the previous design's values.
    - Fix: `cli.write_brams` writes all 1024 words of every BRAM the design uses (`cfgplane.bram_fill`: one IR scan, then DR scans). The `.bit` has a section per used BRAM, even an all-zero one. The M8/M9 checks use the same writer.
  - **Live checks too short to exercise:** they saw 1 input vector because 8 s was not enough to flip anything. They are now guided:
    - a description and example inputs with model LEDs
    - Enter to start
    - a live status line (pins, LEDs, model, goals)
    - goals per design (`LIVE_GUIDE`), ending when all are reached or failing after 90 s with the missing ones

    Without a terminal they keep the 8 s mode and say "goals not checked". `make hwtest ONLY=...` / `--only` reruns single checks.
- **Not at M11:**
  - live consistency for BRAM designs (the BRAM output latch isn't observable while running; the RAM is verified by readback instead)
  - DSP registers (opmode M only)
  - designs larger than 16 CLBs (M12's larger grid)

### M12: Python PnR + optimisation

Split in two, because only the second half changes the Vivado bitstream:

**M12a — bob's own pack/place/route in Python, checked against VPR (no rebuild).**
- **Where:** `software/bob/pnr/`
  - `netlist.py`: reads the same prepared netlist `vpr_run.prepare()` writes (constants → IPIN constants, carry chains cut to the column with generator/tap CLBs, `bob_ff` buffers, `.pcf` pins). The two flows then differ only in pack/place/route.
  - `pack.py`: one BLE per CLB, as the architecture allows. A LUT or adder with the flip-flop its output feeds alone (VPR's `ble` / `chain` patterns); each carry chain is one macro; BRAM/DSP one block each.
  - `place.py`: simulated annealing over legal sites (Betz & Rose, as VPR's placer), cost = half-perimeter wirelength of every net (bounding box), with:
    - carry macros moving as a unit up a CLB column
    - BRAM/DSP only on their column sites
    - fixed pads from the pins
    - a fixed seed, so results are deterministic
  - `route.py`: PathFinder negotiated congestion (McMurchie & Ebeling) directly on the committed rr graph (`software/bob/arch/bob_k6_rr.xml.gz`, the same nodes the fabric muxes are):
    - node cost = (base + history) × present-congestion factor
    - A* with a Manhattan lower bound
    - rip-up and reroute until no node is shared
    - directs (carry, DSP cascade) are wires

    Output: the same result structure `fasm_from_vpr.features()` consumes (packing, placement, per-net node paths), so FASM, legality, bitgen, `.bit` and every check are shared with VPR.
- **CLI:** `./bob build design.v --pnr python` (default stays VPR); `software/bob/pnr/compare.py` prints both flows side by side:
  - CLBs used
  - total wirelength (rr wire nodes) and routing muxes set
  - critical-path hop count
  - runtime
  - routing iterations
- **Done when:**
  - Every example and variant routes with the Python PnR.
  - FASM is legal, and chain → FASM → chain is exact.
  - The same seed gives the same result.
  - `model.py` == the source trace.
  - The golden co-simulation passes for the Python-routed `.bit` of every example, alongside VPR's.
  - The comparison report `docs/reports/M12/pnr_vs_vpr.md` is committed, with wirelength within a stated factor of VPR (target ≤ 1.3×) or the reason when not.
  - Tests check the placer's legality (sites, macros, fixed pins) and the router (no shared nodes; every sink reached; paths only use real rr edges).
- **HW:** `make hwtest M=M12` on the M7 bitstream:
  - `pnr-*`: the M10 golden check (LEDs vs source, CAPTURE vs golden) for the Python-routed examples.
  - `live-*` again on Python-routed switches/fir.

**M12a as built (2026-09-17):**
- **`software/bob/pnr/`:**
  - `netlist.py`: the eblif from `vpr_run.prepare` → atoms.
  - `pack.py`: logic / arithmetic clusters, carry macros, global (clock) and direct (carry) nets.
  - `place.py`: annealing with VPR's schedule (T0 = 20σ, 10·N^(4/3) moves, α by acceptance, range limit), macro moves with displacement, a legality check.
  - `route.py`: PathFinder + A*. A sink may be a tuple of equivalent IPINs, so LUT inputs are permutable; the chosen pin sets the LUT's `port_rotation_map`.
  - `write.py`: `.net` / `.place` / `.route` in VPR formats, with branches emitted in tree order.
  - `run.py`: the driver, retrying the next seed if routing does not converge.
  - `compare.py`: both flows measured identically → `docs/reports/M12/pnr_vs_vpr.md`.
- **Integration:**
  - `./bob build --pnr python`, and `cli.build` now returns the result directory (5-tuple).
  - `hwtest M12`: `pnr-*` (9) and `live-fir-py`, `live-switches-py`.
  - `tb_cosim` runs every design through both flows (18).
  - `make pnr` regenerates the comparison.
- **Results:**
  - Same CLB count as VPR on every design.
  - Total wirelength 1201 vs VPR 1215 (0.99×): better on LUT-heavy designs (pin permutation), up to 1.17× on carry-heavy ones.
  - 0.02–0.17 s per design.
  - Co-sim 4618 checks; `test_pnr.py` 13 (independent legality from the files, determinism, failing cases); fake-board M12 cases.
- **Bugs found while building it:**
  - Branches were written in sink order, not routing order, so the `.route` parser attached a branch to the wrong predecessor. It gave an illegal edge in one design and legal-but-wrong mux values in `gates`, which the model check caught. Now emitted in tree order.
  - The BRAM/DSP `clk` pin was counted as a logic sink.
- **Not in M12a:** timing-driven placement/routing (VPR optimises delay too); LUT pin permutation is not applied to adder inputs (DI = I0 is structural).

**M12b — area and a larger grid (Vivado rebuild; needs the user's decision first).**
- **Measured problem:** the 16-CLB fabric already costs 7670 LUTs / 10362 FFs on the XC7Z020 (M7 `util.rpt`), mostly configuration (4216-bit shift register + 4216-bit shadow register) and routing muxes. The 48-CLB profile did not get through Vivado synthesis in reasonable time.
- **Candidates**, to be measured on the M7 reports before choosing:
  1. **Timing/synthesis hardening that is already planned:** KEEP_HIERARCHY on tiles, commit only while GWE = 0, TCK ceiling, case-analysis sign-off. This could make the 48-CLB profile synthesise acceptably without a new architecture.
  2. **Configuration memory in host LUTRAM (ZUMA):** routing muxes with their configuration folded into LUTRAM, written by address. It cuts FFs drastically, but it is a frame-like write path and overlaps M13.
  3. **Shift register without a full shadow copy for mux bits:** keep the scan-chain protocol, but store configuration once and gate the fabric with GWE/GTS during shifting. This saves about half the configuration FFs, at the cost of glitch-free load guarantees that must be re-proven.
  4. **Larger grid only:** build `release/M7_8x8` on a faster machine as it is.
- **Done when:** the chosen change is built as the complete FPGA; `util.rpt` LUT/FF per CLB is below M7's; every earlier hardware check passes on the new bitstream; the examples re-run through both PnR flows on the new graph.

### M13: frame-based configuration, the chain kept, M7 timing fixed

User, 2026-09-17: "frame based writing just like AMD (slightly simplified) … look into the WNS and TNS of M7 … keep an option for both" (area deferred to M12b).

**As built (2026-09-17):**
- **Spec first:** `docs/bitstream-format.md` sections 9–11. It covers the two write paths, frames, FAR, packets, registers, CMD, STAT, CRC, readback, the load sequence and the host-to-fabric timing rules.
- **Memory layout** (`device.py`):
  - Frames of FRAME_WORDS = 4 × 32 bits, column-major. FAR column 0 holds the ctrl tile; FAR column x+1 holds grid column x, tiles bottom to top, padded to whole frames.
  - 39 frames = 4992 bits (was 4216; K=4: 32 frames, 4096 bits). The chain is exactly the frames concatenated.
  - Blocks keep row-major order: `clb_o`, CAPTURE and the fabric wiring are unchanged. The first attempt reordered them too and broke `tb_bob`'s counter probes.
  - `device.json` gains `frames`; `bob_params.vh` gains `FRAME_WORDS/BITS`, `NFRAMES`, `FAR_NCOLS`, `FAR_TABLE`.
- **RTL:**
  - `cfg_frames.v`: bit-wise sync hunt; HDR/T2/DATA/ERR parser; CRC/FAR/FDRI/CMD/IDCODE writes; FAR auto-increment; FDRO/STAT/FAR/IDCODE/CRC read queue on CFG_OUT (STAT when nothing is queued); errors CRC/ID/PKT/WR; START only after a CRC match that followed the last FDRI word.
  - `cfg_store.v`: the one memory, written by the chain (shift + shadow) or frame by frame on the falling edge.
  - `jtag_tap6.v`: CFG_IN/CFG_OUT → packets; private CHAIN_IN `110101` / CHAIN_OUT `110100` → chain.
  - `cfg_ctrl.v`: chain commit only while GWE = 0; startup after the chain or after `frames_ok`; frame errors in the IR capture.
  - `clock_ctrl.v`: gce ≥ 2^GAP_SHIFT sysclk cycles apart in both modes, with one pending request.
  - `bob_fpga.v`: wiring; no `keep_hierarchy` anywhere, as at M7 (any kept hierarchy, even on `u_clk`/`u_bram_jtag`, crashed Vivado 2025.2 on the routing loops). `build.tcl` writes `sysclk_1cycle.txt`, the registers the single-cycle filter caught, and `test_reports.py` requires gce and the BRAM strobes in it.
  - `cfg_test_top.v`: the chain on CHAIN codes.
- **Timing** (`pynq_z2.xdc`, implementation only: `build.tcl` sets `USED_IN_SYNTHESIS false`, since synthesis with clocks crashed Vivado in loop breaking):
  - TCK at 10 µs; `dirtyjtag.py` MAX_TCK_KHZ = 100.
  - sysclk → sysclk gets 256/255 cycles by clock, replacing M7's 20 name filters. Every path starting or ending in `u_clk` or `u_bram_jtag` is held back to 1 cycle by cell, except those starting at the cin synchroniser.
  - Analysis of M7's report: sysclk WNS came from a 1202-level path through unconfigured routing loops whose flattened source escaped the 120-cycle filters (and 960 ns < 1110 ns anyway). tck WNS came from a real IR → boundary → fabric → DSP-capture path under a 1 MHz constraint.
  - `tests/test_reports.py` now requires WNS ≥ 0, 0 failing endpoints, WHS ≥ 0 and no "No valid object" from M13 on.
- **Host:**
  - `software/bob/packets.py`: stream builders; `to_jtag`/`from_jtag`; `Controller`, a bit-level model of `cfg_frames.v` including readback; `dump`.
  - `cfgplane.py`: `load_frames`, `frames_send/read/stat/readback`; the chain functions use CHAIN_IN/CHAIN_OUT.
  - `bob load --mode frames|chain` (frames default).
  - `hwtest` M13: 39 checks, i.e. the M7 regression via the chain, 5 frame checks, 6 guest designs via frames, ram-readback, blinky-rate, pipeline-live.
- **Verification:**
  - `tb_frames` (34) and `tb_clock_gap` (5) in `make sim`, with expectations from the Python model.
  - `tb_bob` 852, `tb_cfg` 180, `tb_synth` 972, `tb_cosim` 4618, K=4 all pass.
  - `sim/mutate_frames.sh` (16) in `make mutate`; `mutate_cfg` and `mutate_fabric` still pass, with one pattern updated.
  - Stand-in board: frame controller model, new passing and failing cases.
- **Gotchas:**
  - A Verilog macro defined twice (`RB_V`) silently sent the expected data as the stream.
  - A freshly built Python model has no memory of earlier streams; the board does (START_OK persists until JPROGRAM), so scenarios must be modelled in sequence.
  - After a parser error the controller ignores everything until JPROGRAM: a board check first read back over FDRO after a refused load. The stand-in board caught it; that check now reads over CHAIN_OUT.
  - The shared test harness defaulted the DUT IDCODE (`TB_IDCODE`).
  - iverilog aborts on a `$display` of a huge constant expression.
- **First Vivado attempt ran out of memory in synthesis:**
  - The cause: `cfg[frame_idx*FB +: FB] <= frame_data` over the 4992-bit memory is a shifter (yosys: ~12.3k LUTs, 2.3k MUXF, 1.7 GB).
  - The fix: `cfg_store` loads the frame into the chain shift register (don't-care outside CHAIN scans) on the rising edge, and copies it to the memory on the falling edge with a per-frame enable, the chain commit's own path. No memory bit needs a LUT.
  - FDRO reads an explicit word array.
  - yosys whole-design estimate: M7 11 349 LUTs / 10 375 FFs / 138 s / 1.40 GB; M13 15 146 / 12 218 / 152 s / 1.42 GB.
  - **Rule:** never write a computed part-select over the configuration memory; decode per frame. Before a Vivado handoff, run `software/bob/synth_estimate.sh $PWD build/est` (yosys, whole design) and compare with the last build.
- **Not in M13:** BRAM content frames (FAR block type 001 reserved); MFWR compression, encryption, COR/CTL options, per-frame ECC, multiboot; area (M12b).



### M12b: area, then a bigger grid (as built, 2026-09-17)

User, 2026-09-17: "implement everything all till m15 and we will run them in vivado, also make sure the vivado doesn't crash like it did for m7 and m13".

- **Measured first** (yosys per module on M13): `cfg_store` 5 106 LUT + 9 984 FF and `cfg_frames` 2 649 LUT, half of the design's 15 358 LUT / 12 220 FF. The 16-CLB fabric itself is the smaller half.
- **`cfg_store.v` streams the chain** through one 128-bit frame buffer (CHAIN_IN writes every 128th bit's frame while GWE = 0; CHAIN_OUT reloads frames and is a 128-bit delay line afterwards). One frame read mux is shared by CHAIN_OUT and FDRO. Store + controller: 4 104 LUT / 5 469 FF. The chain's semantics now match frames: a bad CRC leaves new bits but COMMITTED = 0 and JSTART refuses.
- **Grid** `ARCH_8X6`: 8×6 core (VPR 10×8), BRAM x=3 and DSP x=6 at height 3, 36 CLBs, 28 pads, W=24; 8320 bits = 65 frames (K=4: 6016 = 47). `make rrgraph`, `make vpr`, `make pnr` re-run (Python PnR 2 015 vs VPR 2 162 wirelength, 0.93×, incl. wide, `docs/reports/M12b/pnr_vs_vpr.md`). `work/examples/wide/wide.v` packs into 31 CLBs.
- **No-crash budget:** whole-design yosys estimate of the final (M15) RTL 15 941 LUT / 11 069 FF / 152 s / 1.36 GB against M13's 15 358 / 12 220 / 143 s / 1.04 GB; M13 built in Vivado in 3.5 min at 2.0 GB with the XDC out of synthesis and no keep_hierarchy, both kept.
- **Tests changed:** `tb_bob`'s marker check uses a repeated marker; `cfgplane.measure_chain` likewise; stand-in board streams the chain; device sizes re-pinned; frame mutants retargeted (+3).

### M14: partial reconfiguration (as built)

- `cfg_frames.v`: CMD **AGHIGH** (8) → `freeze` (needs IDCODE); `clock_ctrl.v` holds gce and sets `frozen` on the same edge; a 2-flop synchroniser brings it back; STAT bit 7 **GHIGH_B** = 0 when acknowledged; FDRI allowed with GWE = 1 only then; **LFRM** releases only after CRC_OK, else WR_ERROR and stays frozen; JPROGRAM clears. STAT version 0x14.
- Host: `packets.partial_streams`, `changed_frames`, Controller freeze model; `cfgplane.load_partial`; `bob load --partial`; `designs.d_partial` (counter + AND/OR gate differing in one LUT).
- Verification: `tb_frames` [13]-[17], `tb_clock_gap` [4], 5 mutants; stand-in board models freeze and state-keeping partials with failing cases; hwtest `partial-swap`, `partial-live`, `partial-bad-crc`, `partial-guest`.
- Found on the way: a freeze and frames in one scan with sysclk stopped (the testbench stops it during long scans) were correctly refused: the acknowledgement guard works, and became scenario [17]. A bad-CRC test alone could not catch "LFRM ignores the CRC" (the CRC error stops the parser first): scenario [14] sends no CRC at all.

### M15: BRAM contents as frames (as built)

- `cfg_frames.v`: FAR block type 1 (column = BRAM, frame n = row·128 + minor, n < 256 = addresses 4n..4n+3), FDRI (GWE = 0) hands 4 words to `bram_jtag.v`'s new sysclk sequencer; FDRO prefetches the frame FAR points at; auto-increment crosses into the next BRAM. STAT version 0x15.
- Host: `packets.load_stream(word, brams)` (all 1024 words per used BRAM under the CRC), `bram_readback_stream`; `cfgplane.load_frames(brams)` verifies contents over FDRO; `bob load` (frames) no longer uses USER4; `--mode chain` still does.
- Verification: `tb_frames` [18]-[19] (scans with sysclk running), 5 mutants; hwtest `frames-bram-load`, `frames-bram-live-refused`, `ram-readback-frames`.
- Gotchas: never-written BRAM addresses read X in simulation (read back only written frames); `list.index(FAR value)` matched a configuration data word (build streams explicitly); the stand-in board's free-running clock read the real switches during INTEST and never modelled USER1 `cin`; bit packing in `packets.py` was quadratic on 70k-bit streams.
- **Hand-off:** one Vivado build (`tag = M15`, IDCODE `0xEBEEF093`), then `make hwtest M=M15` (M13 regression + bob-wide, pnr-wide, 4 partial checks, 3 BRAM-frame checks), checklist `docs/hwtest/M15.md`.


### M16: the 10 × 10 CLB grid (as built, 2026-09-18)

User, 2026-09-18: "for now polish for sharing … also for now expand to 10x10 CLBs first".

- **`ARCH_12X10`** (`device.py`): 12 × 10 core = 10 CLB columns × 10 rows = **100 CLBs**; BRAM column x = 3 and DSP column x = 8, height 5, so still 2 of each; 44 pads; W = 24; 3391 routing muxes; **18 560 bits = 145 frames** (K = 4: 12 800 = 100). VPR grid 14 × 12.
- **Regenerated:** rr graphs (`make rrgraph`), `bob_fabric.v` (4416 lines), `device.json`, `bob_params.vh`, every VPR result and the Python PnR comparison (`docs/reports/M16/pnr_vs_vpr.md`: total wirelength VPR 4017, bob 3601 = 0.90×).
- **New example `work/examples/big/big.v`** (24-bit LFSR + 16-bit counter, **56 CLBs**): impossible on the 36-CLB grid, so it is the check that proves the new fabric. Board checks `bob-big` and `pnr-big` are in `MILESTONE["M16"]`.
- **Size gate:** whole-design yosys 32 891 LUT / 21 485 FF / 2.07 GB / 281 s against M15's 15 941 / 11 069 / 1.36 GB / 152 s. M15 became 10 411 LUT in Vivado (5.1 min, 2.0 GB), so expect roughly 21 k LUT (≈40%) and ≈21.5 k FF (≈20%). This is the first build bigger than M15; the fallback if the machine struggles is an 8 × 8 core (64 CLBs).
- **Bugs found by the resize** (each one a real defect, not just a number):
  - `tb_bob` used `` `CNT8_BITS `` above the `include` of `vectors.vh`; iverilog silently made the comparison register 2 bits wide and 298 checks failed. Comparison registers are plain 32-bit now. **Rule: never use a vector macro above its include.**
  - The CAPTURE check compared 64-bit values, but CAPTURE is 100 bits here.
  - `CNT8_MASK` was emitted with a fixed `8'h` width; it now follows the column height.
  - `tb_frames`' stream vector `SW` (16 384 bits) could not hold a 145-frame load stream: 40 960 in both `sim/gen_frame_vectors.py` and `hw/tb/tb_frames.v`.
  - `test_blinky_chain_crosses_columns`: with 10-row columns blinky fits one column, so the carry-splitting test uses `wide` and also checks each piece is a contiguous run of rows.
  - `sim/mutate_fabric.sh` `carry-direct-cut` is pinned to the last CLB column: x = 12 now.
- **`arch.html`:** the floor plan pitch now scales with the grid (it was fixed at 75 px and a 14 × 12 grid ran into the configuration column), and the legend, title and boundary-cell count come from `device.json`.
- **The user clock gap had to grow with the grid (first Vivado attempt, 2026-09-18 01:54).** Synthesis passed (the XDC is out of synthesis, so no timing-loop storm), then implementation ran 3 h 25 min without finishing: `phys_opt_design` started at **WNS −465.7 ns / TNS −333 768 ns** on fabric flop → flop paths, spent **1 h 15 min** on Critical Path Optimization and recovered only 128 ns, and the router then hit `[Route 35-447]` (congestion, East 32 × 32, overlaps 25.5 k → 30.3 k → 34.6 k per global iteration) with WNS ≈ −337 ns. Nothing was wrong with the tool settings: the **256-cycle (2048 ns) multicycle no longer described the fabric**. The static path through the 12 × 10 fabric's unconfigured routing muxes is about **2500 ns**; 8 × 6 fitted inside 2048 ns, 12 × 10 does not.
  - **Fix:** `DIV_MIN_SHIFT` = `GCE_MIN_GAP_SHIFT` = **9** in `device.py` (gce ≥ 512 sysclk cycles = 4096 ns, `clock_ctrl.v` enforces it in both clock modes) and `-setup 512 -hold 511` in the XDC. The constraint stays a fact, not an assumption — that pairing is the rule from M13.
  - **Cost:** the free-running guest clock halves (488 → 244 kHz maximum). JTAG-stepped mode is unaffected: TCK at 100 kHz is 10 µs per request, still slower than the 4.1 µs gap.
  - **Follow-on:** `check_counter_run` and `check_dsp_accum` had hard-coded rate windows (`6.0 <= rate <= 9.0`) and would have failed on the board at half rate; both now derive the expected rate from `DIV_MIN_SHIFT` like `blinky-rate` already did.
  - **`build.tcl`:** `STEPS.PHYS_OPT_DESIGN.IS_ENABLED` is set **explicitly** on `impl_1` — Vivado stores it in the project, so a run that turned it off keeps it off. It was off briefly (with the old gap it cost 1 h 15 min for 128 ns); it is **on** again after `route_design` died inside "Phase 2.3 Update Timing", since the one implementation that got past that phase had it in the flow. With the gap right it costs seconds.
  - **If this build still does not close:** the next number is 10 (1024 cycles, 8192 ns); if it is congestion rather than timing, drop to the 8 × 8 core (64 CLBs).
- **Then `route_design` crashed, and the cause was Vivado's threading, not the design.** With the gap fixed, implementation reached **WNS +0.531 ns after placement** (`[Place 30-746]`), `place_design` 6:26 (was 14:28) and post-place congestion N 4×4 / S 2×2 / E 4×4 / W 8×8 (was East 32×32) — and then `route_design` died inside "Phase 2.3 Update Timing": no `ERROR:` line, the log stopping mid-phase, only `[Vivado 12-13638] Failed runs(s) : 'impl_1'` in the GUI. Run by hand from `bob_top_placed.dcp` it took Vivado itself down. **`set_param general.maxThreads 1` routes the same checkpoint through.** The timer has to cut every combinational loop in the routing mesh (M16: one SCC of 2146 wires and 11 270 independent cycles, against M15's 1018 / 4130), and two threads doing that concurrently is the fault — the same component that killed three M13 synthesis runs.
  - **In the flow:** `hw/scripts/drc_waiver.tcl` sets `general.maxThreads 1` (and still downgrades LUTLP-1); `build.tcl` hooks it on `opt_design`, `route_design` and `write_bitstream`. It has to be a TCL.PRE hook because `launch_runs` runs implementation in a **separate process** — a `set_param` in the calling session or the GUI console never reaches it.
  - **Cost:** wall-clock only, roughly 1.3–1.7× on implementation (7-series caps these commands at 2 threads anyway). Worth retesting on a later Vivado.
- **Built, 2026-09-18 11:58** (`docs/reports/M16/`): **WNS +0.667 ns**, TNS 0, 0 failing endpoints of 62 692; WHS +0.112 ns, THS 0; "All user specified timing constraints are met". Per clock: sysclk +0.667, tck +1454.874. **20 498 LUT (38.5%)**, **21 511 FF (20.2%)**, 6926 slices (52.1%), 3332 F7 / 1249 F8 muxes, 2 RAMB18, 2 DSP48E1, 15 IOB, 2 BUFG. DRC: 0 errors — LUTLP-1 (downgraded, expected), the DSP pipelining notes and ZPS7-1, as at M15.
  - The yosys estimate said ~21 k LUT and ~21.5 k FF; the build came in at 20 498 / 21 511. The estimate method is sound.
  - Against M15 (10 411 LUT / 11 097 FF / 3546 slices): **2.8× the CLBs cost 1.97× the LUTs**, and the part is half full by slices.
  - The worst sysclk path is a **1-cycle** path (`u_bram0/u_core/mem_reg` → `u_bram_jtag/bf_rdata_reg[2]`, 8 ns requirement, 4 logic levels), not a fabric multicycle path — the 512-cycle gap now has room to spare, exactly as at M15 where the worst path was also 1-cycle logic outside the fabric.
- **IDCODE `0xFBEEF093`, USERCODE 0x10.** This is the **last free version nibble**; the next device needs a new numbering scheme.
