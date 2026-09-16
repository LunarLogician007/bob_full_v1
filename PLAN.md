# bob_full_v1 — plan, status and handoff

> **For any agent picking this up:** read this whole file before touching anything. It is the single current plan and records how the work is done.
> `PLAN_v0.md` is the superseded first draft; don't follow it. `README.md` describes the M0 baseline inherited from `bob/`.
> Last updated 2026-09-14, M7 built and simulated (awaiting M5 re-run and M6/M7 hardware).

---

## 1. What this project is

A complete FPGA **built inside an FPGA**. The guest fabric ("bob") is written in Verilog and runs on the PL of a **PYNQ-Z2 (Zynq XC7Z020, part `xc7z020clg400-1`)**. It is configured over JTAG from a Mac through a **Raspberry Pi Pico running DirtyJTAG** wired to PMODA.

End goal: `design.v → yosys → VPR (pack/place/route) → bob bitgen → bitstream → Pico JTAG → running on the guest fabric`. The fabric has CLBs, BRAM and DSP tiles, real routing and I/O.

Two flows, two bitstreams. Don't confuse them:
- **Host flow (Vivado, on a separate Windows machine):** bob's RTL → Vivado → AMD `.bit` for the XC7Z020. Once loaded, the Zynq *is* bob.
- **Guest flow (ours, on the Mac):** a user design → our tools → a bob configuration chain. It is loaded over the Pico's JTAG into the running bob fabric.

Starting point: `/Users/sk/work/bob/` is a hardware-proven 4×4 CLB fabric (JTAG TAP, boundary scan, 2896-bit config chain, 174 simulation checks). It was **copied whole** into `bob_full_v1/` and is **frozen**. All work happens in `bob_full_v1/`.

## 2. Status

| Milestone | What | Status |
|---|---|---|
| M0 | copy, `hw/` layout, adaptable `build.tcl`, tools | **done, passed on hardware** 2026-09-14 (WNS +67.3 ns) |
| M1 | `tools/bob/device.py` single source of truth | **done, passed on hardware** 2026-09-14 (chain-length 2896 confirmed on the board) |
| M2 | scan-chain configuration plane (6-bit AMD IR, CRC, startup, capture), standalone test top | **done, passed on hardware** 2026-09-14 (11/11 checks; tb_cfg 180, `make mutate` 5/5) |
| M3 | config plane wired into the 4×4 fabric + host loader | **done, passed on hardware** 2026-09-14 (WNS +63.9 ns; 3951 LUTs, 6115 FFs) |
| M4 | CLB core (routable CE/SR, **LUT size K as a parameter**) + user clock | **done, passed on hardware** 2026-09-14 (WNS only +0.84 ns on the 8 ns sysclk; the first `ce-sr` check leaked the real switches, fixed to INTEST autostep) |
| M5 | BRAM tile (UG473 RAMB18E1 subset) | **done, passed on hardware** 2026-09-14 (all BRAM checks incl. the fixed `bram-rom`, re-run on the M6 bitstream, which contains the M5 checks) |
| M6 | DSP tile (UG479 DSP48E1 trimmed) | **done, passed on hardware** 2026-09-14 (all 25 checks, run with the restored M6 tools in `release/mac_M6/`) |
| M7 | **done, passed on hardware 2026-09-17** (26/26 checks incl. bram-select, pipeline, full-column counter; 7670 LUTs, 10362 FFs, 2 RAMB18, 2 DSP48E1; WNS −1102 ns from unconfigured routing-loop paths, see M7 timing notes). Heterogeneous fabric generated from VPR's rr graph. **Board build = 16-CLB profile** (`ARCH_6X4`: 16 CLB, 2 BRAM, 2 DSP, 20 pads, 4216-bit chain, IDCODE `0xABEEF093`), switched 2026-09-15 because the 48-CLB Vivado synthesis was too slow on the build machine. The 48-CLB profile (`ARCH_8X8`, 9400 bits, IDCODE `0x9BEEF093`) is frozen complete in `release/M7_8x8/`, to be built later on a faster machine. 16-CLB results 2026-09-15: tb_bob 852, tb_synth 486, K=4 722, lint clean, pytest 88, `make mutate` 25/25 killed. The 48-CLB results at the time were | **built and simulated** 2026-09-14 (tb_bob 852 checks incl. random routed netlists, K=4 722, lint clean, pytest 80, `make mutate` 25/25 fabric + cfg all killed); awaiting M5/M6 hardware, then M7 hardware (bundle `hw/`, top `bob_top`) |
| M8 | yosys synthesis to bob cells | **done, passed on hardware 2026-09-17** (10/10 on the M7 bitstream: gates, adder, counter, blinky, ram, mult each match the source Verilog for 64 clocks). Built and simulated 2026-09-14: 6 examples, netlist == source (iverilog), placed model == source, fabric RTL == source (tb_synth 486); no rebuild, hardware test on the M7 bitstream after M7 passes |
| M9 | PnR with VPR | planned |
| M10 | bitgen + golden co-simulation | planned |
| M11 | full hardware bring-up of real designs | planned |
| M12 | Python PnR (checked against VPR) + optimisation | planned |
| M13 | frame-based configuration (UG470), replacing the scan chain | planned, deliberately last |

Hardware results are in `docs/hwtest/results.log`; Vivado reports are in `docs/reports/Mx/`.

## 3. How the user wants this done (non-negotiable)

1. **One milestone at a time.** Build it, run its "done when" checks, show the results, and **stop for the user's go-ahead** before the next milestone.
2. **Every milestone ends with a PYNQ-Z2 hardware test** (`make hwtest M=Mx`). Simulation alone never closes a milestone. If a milestone has no RTL change, reuse the previous bitstream, but still run the board test.
2a. **Every hardware build is the complete FPGA plus the new feature, never a standalone block.** (User, after M2's `cfg_test_top` build.) A new block goes into the full fabric top, and the hardware test runs the full regression (all earlier designs) plus the new feature's checks. Small test tops like `cfg_test_top` may still exist for simulation (`tb_cfg`), but they aren't what goes to Vivado.
3. **Tested references first.** Ground designs in AMD user guides (UG470 config, UG473 BRAM, UG474 CLB, UG479 DSP) and OpenFPGA/VPR (regression-tested architectures). Flag any divergence explicitly.
4. **Reuse verified code** from `bob/` (copied here) instead of rewriting it.
5. **Scan chain first, frame-based last.** The configuration stays a JTAG scan chain (the working type) until M13.
6. **Vivado is not on the Mac.** The user copies `bob_full_v1/hw/` to Windows (e.g. `E:\bob_full_v1\hw`), replacing the old `hw`, and runs `hw/scripts/build.tcl` (usually from the GUI: Tools → Run Tcl Script). The Vivado project must be **reused, never recreated**.
7. **Explain concepts** (routing, mapping, host vs guest flow) before asking for decisions.
8. Decisions already made: VPR does PnR first (Python PnR later); 6-bit AMD 7-series JTAG IR codes; yosys for synthesis; no Aegis binaries (read-only study only).

## 4. Folder structure (actual)

```
bob_full_v1/
  PLAN.md                this file
  CLAUDE.md              short rules for agents; points here
  REUSE.md               origin/status of every file (update when you add or modify files)
  README.md              the M0 baseline description inherited from bob/
  PLAN_v0.md             superseded first plan
  Makefile               make check | device | hw | hwtest M=Mx | clean
  .gitignore

  hw/                    THE Vivado bundle: the only folder copied to Windows
    README.md            Windows/Vivado usage
    sources.f            ordered synthesisable source list, relative to hw/
                         (read by build.tcl, sim/*.sh via sim/hwfiles.sh, and sim/lint.sh)
    build.cfg            tag, top, idcode, part, xdc, sim_top, sim_files, sim_defines, project, jobs
    src/
      clb/               clb_pkg.sv lutk.sv clb.sv
      core/              jtag_tap.v bsc_cell.v jtag_tap6.v cfg_tile_sr.v cfg_mem.v cfg_ctrl.v capture_chain.v clock_ctrl.v
      tiles/             bram_core.v bram_jtag.v bram_block.v dsp_core.v dsp_jtag.v dsp_block.v
      fabric/            bob_mux.v bob_fpga.v (M7 complete FPGA) mini_fpga.v
      top/               bob_top.v mini_fpga_top.v cfg_test_top.v
      generated/         bob_params.vh bob_fabric.v  (GENERATED by tools/bob/device.py; do not edit)
    tb/                  tb_bob.v tb_cfg.v tb_clb.sv tb_bram.v tb_dsp.v tb_mini_fpga.v *vectors.vh (GENERATED)
    (M7 retired fabric.v tile.v mux_bank.v fpga4x4*.v bram_tile.v dsp_tile.v tb_fpga4x4.v: see release/hw_M6)
    constr/pynq_z2.xdc   PLAIN XDC ONLY (see gotchas)
    scripts/build.tcl    adaptable Vivado flow
    scripts/drc_waiver.tcl  LUTLP-1 downgrade, fabric top only

  tools/bob/             guest-flow tools (Mac)
    device.py            device description → arch XML, device.json, bob_params.vh, bob_fabric.v
    vpr_arch.py          VPR architecture writer (derived from OpenFPGA k6_frac_N10_tileable_..._dsp36)
    vpr_rrgraph.sh       Docker VPR: routes arch/and2.blif, writes arch/bob_k{6,4}_rr.xml.gz + .stamp + _vpr.txt
    rrgraph.py           rr_graph.xml(.gz) reader
    fabric_gen.py        rr graph → hw/src/generated/bob_fabric.v
    arch/                bob_k6.xml bob_k4.xml (GENERATED), rr graphs, stamps, VPR log tails (COMMITTED; need Docker to rebuild)
    model.py             cycle model over the rr graph (CLB/BRAM/DSP)
    chainbits.py         CRC-32C, ctrl words, .bobc files
    device.json          GENERATED
    (later: fasm_from_vpr.py, bitgen.py, cli.py, synth/)

  host/                  talks to the board through the Pico (Mac)
    dirtyjtag.py         Probe: pulse, shift_ir(value, width), shift_dr, shift_dr_fast (bulk, MSB-first per byte)
    bitstream.py         Design API + BFS/rip-up router over the rr graph; everything from tools/bob/device.json
    designs.py           the example designs in VPR (x,y) coordinates (shared by simulation and hardware)
    fpga.py              load/verify/watch bob; board vectors <-> the 64-cell boundary
    cfgplane.py          config plane, USER4 (BRAM, SELECT), DSP register
    (bscan.py is the pre-M7 interactive 9-cell boundary tool; not ported to bob_top)
    hwtest.py            per-milestone hardware test; appends docs/hwtest/results.log
    buildcfg.py          reads hw/build.cfg and hw/sources.f (same rules as build.tcl)
    bscan.py minifpga.py tap_probe.py wire_check.py detect.sh urjtag-*.jtag   bring-up tools

  sim/                   Mac simulation scripts (iverilog, verilator)
    hwfiles.sh           prints hw/sources.f as absolute paths
    run_sim.sh           single-CLB testbench
    run_fabric_sim.sh    regenerates vectors, runs tb_bob (complete FPGA, 852 checks at M7)
    run_k4_sim.sh        CLB sweep + tb_bob at K=4 from a generated K=4 device (committed K=4 rr graph)
    mutate_fabric.sh     mutants that tb_bob must kill (make mutate)
    lint.sh              verilator lint of each top, with justified waivers
    gen_vectors.py       designs.py → hw/tb/vectors.vh

  tests/                 pytest (run by make check)
    test_layout.py       hw/ bundle is self-contained; XDC is plain XDC; sources exist
    test_build_tcl.py    build.tcl run under tclsh against tests/tcl/vivado_stub.tcl
    test_device.py       device.py self-consistency + iverilog cross-check against clb_pkg.sv
    test_reports.py      docs/reports/Mx: TCK constrained, no XDC critical warnings

  docs/
    hwtest/Mx.md         per-milestone hardware checklist ("- [ ]" lines = manual steps)
    hwtest/results.log   every hwtest run
    reports/Mx/          Vivado outputs copied back from Windows (bit, timing, util, drc, logs, build_info)
    reference/create_project_v0.tcl   the original bob/ Vivado script
    (M2: bitstream-format.md)
    wiring.md architecture.html fabric-audit.html report.tex bits.json   inherited docs

  pico/README.md         probe firmware notes
```

Outside the project (read-only references):
- `/Users/sk/work/bob/`: frozen original.
- `/Users/sk/work/resourses/`: study notes. `04-config-bitstream/CONFIG-CONTROLLER.md` is the UG470 gloss; `repos/OpenFPGA` is a shallow clone.
- `/Users/sk/work/aegis/docs/arch/*.md`: Aegis architecture docs (Apache-2.0; per-tile shift/shadow register, BRAM/DSP/clock/IO).
- On the Windows machine: `E:\bob_full_v1\hw` (pasted) and `E:\bob_full_v1\bob_vivado\` (the Vivado project, **never delete**).

## 5. Everyday commands

```sh
make check            # device files fresh + all sims + lint + pytest. Must be green before any hand-off.
make device           # regenerate arch XML, device.json, bob_params.vh, bob_fabric.v from the committed rr graphs
make rrgraph          # after an architecture change in device.py: Docker VPR rebuilds the rr graphs, then make device
make mutate           # mutation tests (slow, ~1 h at M7)
make hw               # refresh hw/tb/vectors.vh, print the Vivado hand-off steps
make hwtest M=M2      # hardware test with the Pico attached  (host/hwtest.py --milestone M2 [--manual] [--list])
tools/bob/device.py --check
```

Tools on the Mac: iverilog, verilator 5.050, yosys 0.69 (brew), python 3.14 + pytest, tclsh 8.6, Docker.
VPR: `docker run --rm --platform linux/amd64 ghcr.io/lnis-uofu/openfpga-master:latest …`. There is no arm64 image, so it runs under emulation. The binary is at `/opt/openfpga/build/vtr-verilog-to-routing/vpr/vpr` (VPR 9.0), plus `/opt/openfpga/build/openfpga/openfpga` and `/opt/openfpga/build/yosys/yosys`.

## 6. Hardware hand-off loop (every milestone)

1. Mac: `make check` green, then `make hw`.
2. Copy `bob_full_v1/hw` to Windows and **replace** `E:\bob_full_v1\hw`. Don't delete `bob_vivado`.
3. Vivado GUI: Tools → Run Tcl Script → `E:/bob_full_v1/hw/scripts/build.tcl`. It builds only if inputs changed.
   - Other actions, typed in the Tcl Console: `set bob_args {all}` (or `program`, `force`, `status`, `sim`, `top=…`), then `source E:/bob_full_v1/hw/scripts/build.tcl`.
   - Batch alternative: `vivado -mode batch -source …/build.tcl -tclargs all`.
4. Program the board (`set bob_args {program}`).
5. Copy `E:\bob_full_v1\bob_vivado\out\<tag>\` to `docs/reports/<tag>/`.
6. Mac: `make check` (now also checks the reports), then `make hwtest M=<tag>`.
7. Show the user the results and wait.

What `build.tcl` guarantees (tested on the Mac with the stub):
- The project lives outside `hw/`: `build.cfg project = ../bob_vivado`.
- An existing project is opened, never recreated.
- sources_1, constrs_1 and sim_1 are synced to `sources.f` / `build.cfg`, adding new files and removing dropped ones. It also works if `hw` is pasted to a new location.
- Rebuild happens only if a content fingerprint changes: FNV-1a over sources, XDC and waiver, plus top/idcode/part, with CRLF normalised.
- `idcode` from `build.cfg` is passed as the `IDCODE_VALUE` generic. A `top=` override without `idcode=` keeps the RTL default.
- Outputs go to `bob_vivado/out/<tag>/`: `<top>.bit`, `timing.rpt`, `util.rpt`, `drc.rpt`, `synth_1.log`, `impl_1.log`, `build_info.txt`.
- In the GUI the project stays open after the build; in batch mode it is closed.

## 7. Conventions

- **New synthesisable file** → add it to `hw/sources.f` in dependency order (packages first). Lint and sims pick it up automatically.
- **New top** → give it a `parameter [31:0] IDCODE_VALUE` and the board ports `tck tms tdi tdo sw[1:0] btn[3:0] led[3:0]`, so `pynq_z2.xdc` applies unchanged. Add it to `sim/lint.sh`.
- **Per milestone with RTL changes:**
  - bump `hw/build.cfg`: `tag = Mx`, and a new `idcode` version nibble (the top 4 bits; low 12 bits stay `093`)
  - add `docs/hwtest/Mx.md`
  - register checks in `host/hwtest.py` `MILESTONE["Mx"]`
  - update `REUSE.md` and this file's status table
- **IDCODE map:** `0x1BEEF093` bare TAP (bob), `0x2BEEF093` single CLB, `0x3BEEF093` 4×4 fabric (M0–M1), `0x4BEEF093` M2 cfg test top, `0x5BEEF093` M3, `0x6BEEF093` M4, `0x7BEEF093` M5, `0x8BEEF093` M6, `0x9BEEF093` M7 (`bob_top`); after that, the next free nibble.
- **Architecture changes (M7 on):** edit `ARCH` / block ports in `tools/bob/device.py`, then `make rrgraph` (Docker). `device.py --check` (and pytest) fails with "run make rrgraph" when the committed rr graph was built from a different arch (sha256 stamp). The generated fabric, device.json, the router, the model and the testbench all follow automatically. From M2 on, the AMD `USERCODE` instruction also returns the milestone number, so versions don't run out.
- **Architecture numbers live only in `tools/bob/device.py`.** Consumers read `device.json` or `bob_params.vh`; never hand-copy a constant. After editing `device.py`, run `make device`. pytest fails if the generated files are stale.
- **Shift conventions** (from `bob/`, proven on hardware):
  - TMS/TDI sampled and state advanced on the rising TCK edge
  - TDO launched and IR/DR update latches on the falling edge
  - every shift register is LSB-first
  - chain bit k is the k-th bit shifted in
  - DirtyJTAG bulk `CMD_XFER` is MSB-first within each byte (handled in `Probe.shift_dr_fast`)
- **Test-Logic-Reset (`tlr`) is only ever consumed synchronously.** A combinational decode of the state register glitches on RTI→SelectDR, CaptureIR→Exit1IR and UpdateIR→SelectDR. `bsc_cell.v`'s header records the hardware failure this caused.
- **Every hardware test appends to `docs/hwtest/results.log`.** Don't edit past entries.

## 8. Gotchas already paid for

| Problem | What happened | Rule |
|---|---|---|
| Tcl in XDC | `if`/`catch`/`set` in the XDC were skipped with a critical warning, so `create_clock` never ran. TCK was unconstrained and Vivado still said "all constraints met". | XDC is plain XDC; `tests/test_layout.py` enforces it. Top-dependent logic goes in `drc_waiver.tcl`. `tests/test_reports.py` checks `no_clock (0)`. |
| Tcl `expr` with hex strings | `expr {… ? "0x3BEEF093" : …}` returned `1005514899` | Never build display strings with `expr`. |
| tclsh reading stdin | errors are printed and the exit status is 0 | Run Tcl test drivers from a file. |
| Vivado GUI Run Tcl Script | can't pass `-tclargs` | `set bob_args {…}` before `source`. `build.tcl` detects the GUI with `$::rdi::mode`. |
| OpenFPGA Docker | no arm64 manifest | `--platform linux/amd64`. |
| Old CONFIG readback | read-modify-write: a read had to shift the same word back in | M2 separates `CFG_OUT` (never commits) from `CFG_IN`. |
| Fabric combinational loops | LUTLP-1 DRC and Synth 8-295 by construction (any switch-box mux can select a neighbour) | Downgraded only for the fabric tops (`fpga4x4_top`, `bob_top`) in `drc_waiver.tcl`; UNOPTFLAT waived in lint. Expected; not a bug. |
| VPR `pinlocations pattern="spread"` on tall blocks (M7) | puts pins on top/bottom sides *inside* a height-4 BRAM/DSP where `through_channel="false"` leaves no channel: `check_rr_graph: SINK has no fanin` | `device.py` places hard-block pins round-robin on left/right of every row + bottom/top of the ends; io pins on all four sides as the reference does. |
| rr graph `ptc` (M7) | OpenFPGA's tileable CHAN nodes carry one track id per position: `ptc="0,2,4,6"` | `rrgraph.py` parses ptc as a tuple. |
| Docker bind mounts (M7) | a mount of the session scratch dir under `/private/tmp` showed an empty directory in the container; the image's user can't write a mount | run VPR in a folder under the project (`build/vpr`) with `-u root`. |
| Test that relied on design order (M7) | tb section [4] assumed `showcase` was the last design `run_designs` loaded; adding `cross` broke it | sections load what they check. |
| Verilator 9400-bit replication (M7) | `{W{1'b0}}` over the whole chain exceeds `--replication-limit 8192` | `lint.sh` passes `--replication-limit 65536` for `bob_top`. |
| IDCODE `0xFFFFFFFF` in hwtest | board not programmed (or TDO unwired) | Program first; see the `README.md` debug table. |
| Probe | DirtyJTAG on a Pico, USB VID/PID in `dirtyjtag.py` | 100 kHz on first contact (`--freq`). |
| A guard nobody tests | M2's first testbench passed with the length check deleted (the length test also broke the CRC, so the CRC rejected it first) | Test each guard in isolation. Run `make mutate` after touching `cfg_ctrl.v`; add a mutant for every new guard. |
| zsh vs bash | `$VAR` holding several paths isn't word-split in zsh | Put multi-file shell logic in `bash` scripts that use arrays. |
| Random config in simulation | M4's fabric sim hung forever after committing a random 3064-bit chain: random routing mux values built an inverting combinational loop, and a zero-delay oscillation stops simulation time. (M3 and the K=4 run happened to be lucky.) | Never commit a fully random chain into the fabric in simulation. `gen_vectors.py` makes every routing mux select an out-of-range source (reads const 0). On hardware the same would be a real ring oscillator. |
| Parallel work on `hw/` | M4 was built while M3 was on the board; editing `hw/` would change the M3 bundle | `release/hw_Mx/` is a frozen copy of the bundle under test. Paste that one if the milestone hasn't been built yet. |
| Parallel work on the Mac tools (M7) | M7 rewrote `host/` and `tools/bob/` for the new fabric while M6 was still to be tested; `make hwtest M=M6` then read the M7 `build.cfg` and could not drive the M6 bitstream. The M6 tools had to be rebuilt from the session transcript (verified byte-identical via `bob_params.vh` and `vectors.vh`). | Before starting milestone N+1, freeze **both** `release/hw_MN/` and `release/mac_MN/` (hw + host + tools/bob + sim). Test an older bitstream with `cd release/mac_MN/host && ./hwtest.py --milestone MN`, then append its `docs/hwtest/results.log` entry to the main log. |
| Hardware checks that leak the real switches | M4 `ce-sr` set USER1 ce=1 before entering INTEST; during that scan the boundary is transparent, so SW0/SW1 reached CE/SR and the result depended on switch position | Anything sequential driven through INTEST uses USER1 **autostep** with ce off (one clock per INTEST scan). `tb_fpga4x4` reproduces it with SW0 held up. |
| Check-script crashes | M5 `bram-rom` raised `ValueError` on `'%03b' % g` (no `b` in %-formatting) | Use f-strings. A crash in a check is reported as FAIL with the exception; read the detail before suspecting the RTL. |

## 9. References and what each is used for

| Area | Source | Used for |
|---|---|---|
| CLB | AMD UG474 | LUT6_2 fracture (O5 = INIT[31:0] over i[4:0]), CARRY4 MUXCY/XORCY, FDRE/FDSE priority, routable CE/SR |
| Configuration | AMD UG470; `resourses/04-config-bitstream/CONFIG-CONTROLLER.md`; prjxray `bitstream.py`/`crc.py` | JTAG instruction codes, CRC-32C (`0x1EDC6F41`) and the rule "CRC before startup", startup order GSR→GTS→GWE→DONE, readback, capture; frames at M13 |
| Scan-chain protocol | OpenFPGA `docs/source/manual/arch_lang/config_protocol.rst` (`scan_chain`); Aegis `configuration.md` | chain through each tile's config flops; per-tile shift register + shadow register, updated only on load |
| Frame protocol (M13) | OpenFPGA `frame_based` (`openfpga_arch/k4_N4_40nm_frame_*`); UG470 FAR/FDRI/FDRO | address decoders, auto-increment |
| Routing | VPR/OpenFPGA `vpr_arch/k6_frac_N10_tileable_adder_chain_dpram8K_dsp36_fracff_40nm.xml` + `openfpga_arch/k6_frac_N10_adder_chain_dpram8K_dsp36_fracff_40nm_openfpga.xml` | unidirectional L1/L4, Wilton Fs=3, fc_in/fc_out, BRAM/DSP column heights |
| BRAM | AMD UG473 | synchronous read, WRITE_FIRST/READ_FIRST/NO_CHANGE, DOA_REG, width modes, INIT separate from config |
| DSP | AMD UG479 | A25/B18/D25, pre-adder, 25×18 multiply, P48, OPMODE subset, register attributes, PCOUT→PCIN |
| I/O, clock | Aegis `io.md`, `clock.md`; AMD BUFG; PYNQ-Z2 master XDC (sysclk H16, 125 MHz; verify) | I/O tile, user clock |
| Synthesis | yosys `synth_xilinx`, Aegis techmap (read only) | cell library, techmap, `memory_bram` rules |
| Bitgen method | prjxray FASM | routed pips → mux values |
| Area | ZUMA (FCCM 2012) | configuration memory in host LUTRAM (M12) |

---

## 10. Milestones in detail

### M0: copy + `hw/` layout + adaptable Tcl (DONE)

Delivered: the full copy of `bob/`; the `hw/` reorganisation (no RTL logic change except an `IDCODE_VALUE` parameter on both tops); `sources.f`, `build.cfg`, `build.tcl` with the Vivado stub tests; `sim/*` reading `sources.f`; `hwtest.py`; `Makefile`; `REUSE.md`. Found and fixed the Tcl-in-XDC bug inherited from `bob/`.
Hardware: `idcode`, `bypass` (1 bit), `selftest` 11/11, `showcase-live`; project reuse and skip-on-no-change confirmed in Vivado. Reports in `docs/reports/M0`: 4271 LUTs, 5910 FFs, WNS +67.3 ns, WHS +0.083 ns.

### M1: `device.py` (DONE)

Delivered: `tools/bob/device.py` (tile type = ordered fields `name/offset/width/kind/group`; row-major tiles with `chain_lo`; `locate`, `chain_bit`, `decode`, `encode`, `pips`); generated `device.json` and `bob_params.vh`; `host/bitstream.py` driven by `device.json` (generated vectors byte-identical to M0); `tests/test_device.py` (12 tests, including an iverilog elaboration comparing 21 constants with `clb_pkg.sv`).
Hardware: M0 bitstream reused; `selftest` on the `device.json`-driven engine passes; `chain-length` measured 2896 on the board with a 16-bit marker.
Not done yet (belongs to M7): pads and chain order for non-CLB tiles.

### M2: scan-chain configuration plane (NEXT)

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
- `tools/bob/chainbits.py`: `crc32c_bits(word, width)`; a byte-wise CRC-32C reference; `.bit` write/read/validate; `load_sequence` description.
- `host/cfgplane.py`: 6-bit IR constants; `jprogram`, `write_expected_crc`, `cfg_in`, `status()` decode, `cfg_out`, `jstart(tcks=12)`, `capture(n)`, `usercode`, `load(word, width)` (the full sequence with checks and a per-pulse fallback like `fpga.load_bitstream`).
- `host/hwtest.py` `MILESTONE["M2"]`. The regression for this top is `idcode` + `bypass` (the fabric self-test returns at M3). New checks:
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

### M3: config plane into the 4×4 fabric + host loader

- `hw/src/fabric/fpga4x4.v`: `jtag_tap` → `jtag_tap6`; `cfg` from `cfg_mem #(NTILE=16, TILE_W=181)`, sizes from `bob_params.vh`; `capture_chain` over the 16 CLB `o`.
- Minimal CLB change for GSR: `clb.sv` gets a `gsr` input (`if (gsr) q <= ff_rstval` ahead of SR/CE), so GSR resets every FF regardless of `ff_sr_en` (UG470 semantics). CE is gated by GWE.
- Fabric pad outputs forced to 0 while GTS = 1; true hi-Z comes with `io_tile` in M7.
- Retire the old `jtag_tap.v` from `fpga4x4`. `mini_fpga` stays on the old 4-bit TAP (as built: legacy single-CLB top, still simulated and linted; ties gsr=0, gwe=1).
- As built: `fpga4x4.v` keeps its size parameters (checked against `device.py` by `tests/test_device.py`) instead of including `bob_params.vh`, so no include-path changes were needed in Vivado/iverilog/verilator. The M0/M1 hwtest for the old 4-bit fabric no longer applies to the new bitstream.
- Host: `fpga.py`/`dirtyjtag.py` move to 6-bit IR constants; `fpga.load_bitstream` uses `cfgplane.load` (JPROGRAM → CRC → CFG_IN → status → CFG_OUT verify → JSTART, per-pulse retry kept); `sim/gen_vectors.py` and `tb_fpga4x4.v` use the new load sequence. `chain-length` check moves to CFG_OUT.
- `build.cfg`: `tag = M3`, `top = fpga4x4_top`, `idcode = 5BEEF093`, `usercode = 3`.

**Done when:** the 174 fabric checks pass through the new load path; M2's config-plane checks pass on the fabric's 2896-bit chain.
**HW:** full regression (idcode, bypass, selftest 11/11, showcase-live, chain-length) plus a corrupted chain rejected with the previous design still running; DONE after JSTART; CAPTURE shows CLB outputs; `util.rpt` compared with M0 (expect roughly 2× config FFs for the shadow registers; record it).

### M4: CLB core + user clock + LUT size as a parameter

- **LUT size K becomes one parameter** (user request, 2026-09-14), so a later LUT6→LUT4 switch is mostly "change K, regenerate, re-test":
  - `hw/src/clb/lut6.sv` → `lutk.sv` with parameter `K` (INIT `2**K` bits; O5 = the K-1 sub-tree, as UG474's LUT6_2 does for K=6)
  - `clb.sv`, `clb_pkg.sv`, `tile.v` take `K` (connection box has K input muxes)
  - `tools/bob/device.py` gets `lut_k` (default 6); `init` = `2**K` bits; `cb_i0..cb_i{K-1}`
  - `host/bitstream.py`: every `64`/`range(6)`/`0x1F` derived from K
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
- **Models:** `tools/bob/model.py` is a cycle model with flip-flops. `tb_clb.sv` runs a 128-flag-combination sweep (7040 checks) against it; the fabric testbench checks routed CE/SR and a 4-bit carry-chain counter (JTAG-stepped every edge, free-running with TCK stopped) against it.
- **Mutation tests:** `sim/mutate_fabric.sh` adds no-gce, ce-not-routed, step-ignores-ce and divider-off-by-1 mutants.
- User clock: 125 MHz sysclk (H16, **verify** against the PYNQ-Z2 master XDC) → BUFG → divider (Aegis `clock.md` style). TCK remains the configuration clock; GSR/GTS/GWE synchronised into the user clock with 2-FF synchronisers. XDC gets `create_clock` for sysclk and `set_clock_groups -asynchronous` with TCK (plain XDC).
- `tools/bob/model.py`: starts from `simulate()` in `host/bitstream.py`, adds FFs and the clock.
- `device.py`: new CLB fields (CE/SR mux) → `make device`; `bitstream.py` follows.

**Done when:** a flag sweep (comb/FF/carry/O5/CE/SR/GSR) matches `model.py`; the `tb_mini_fpga.v` vectors still pass.
**HW:** a counter design blinks an LED from the user clock at the expected rate; CE/SR from switches stop and reset it; timing met on the sysclk domain.

### M5: BRAM tile (UG473 RAMB18E1 subset)

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

### M6: DSP tile (UG479 DSP48E1 trimmed)

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

### M7: heterogeneous fabric + routing + I/O

- `device.py`: column types CLB/BRAM/DSP/IO; unidirectional L1 + L4 tracks, Wilton switch box Fs=3, connection-box fc_in/fc_out taken from the OpenFPGA k6_frac_N10 dpram8K/dsp36 arch; chain order control → IO → tiles.
- It emits `hw/src/generated/fabric.v` (from the generate pattern in `fabric.v`, `mux_bank.v` for CB/SB muxes), `tools/bob/vpr_arch.xml` and the routing-resource-graph bit map.
- `hw/src/tiles/io_tile.v`: `bsc_cell.v` + GTS, 8-bit I/O (Aegis `io.md`). Grid size set from the M3–M6 utilisation reports.

**Done when:** hand-built chains route pad → LUT → FF → BRAM → DSP → pad; RTL equals `model.py` every cycle; VPR loads `vpr_arch.xml` and routes a trivial netlist.
**HW:** the generated fabric fits; that hand-built design works from switches to LEDs; all earlier designs re-run.

**As built (2026-09-14), OpenFPGA's method:** describe the architecture → VPR builds the tileable routing-resource graph → generate the fabric RTL, the chain map, the router and the model from that one graph.
- **Architecture** (`tools/bob/device.py` `ARCH`, written by `vpr_arch.py`, derived from OpenFPGA `k6_frac_N10_tileable_adder_chain_dpram8K_dsp36_fracff_40nm.xml`).
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
- **VPR:** `tools/bob/vpr_rrgraph.sh` (Docker, `make rrgraph`) routes `arch/and2.blif` at W=24 for K=6 and K=4 ("Circuit successfully routed", `arch/bob_k*_vpr.txt`) and writes the rr graph. The graphs are committed (gzip, ~80 kB), with a stamp holding the arch sha256, image digest and command.
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

### M8: synthesis (yosys)

- `tools/bob/synth/bob_cells.v` (LUT6_2, CARRY, DFF with CE/SR, BOB_BRAM18, BOB_DSP), `techmap.v`, `bram.rules`, `synth_bob.tcl` (`synth -run`, `abc -lut 6`, `memory_bram`, DSP techmap, patterned on `synth_xilinx`), writing BLIF for VPR.
- Examples in `examples/`: gates, adder, counter, blinky, ram, fir. The `designs.py` functions are rewritten as Verilog.

**Done when:** yosys stats show only bob cells; the post-synthesis netlist equals the source in iverilog.
**HW:** fabric unchanged (no rebuild); a synthesised `gates.v`, hand-placed, loads and matches.

**As built (2026-09-14):**
- **Cell library** (`tools/bob/synth/bob_cells_sim.v`):
  - `$lut` (K from `device.json`)
  - `BOB_FDRE` / `BOB_FDSE`: sync R/S beats CE, INIT = reset = GSR value
  - `BOB_ADD`: one CLB in carry mode, LUT A^B(^1), DI = I0 = A
  - `BOB_BRAM18`: 1024×18 TDP, no output register
  - `BOB_DSP`: 25×18 signed, opmode M
  - The BRAM/DSP models instantiate the fabric's `bram_core.v`/`dsp_core.v`.
- **Script** (`tools/bob/synth.py`): the `synth_xilinx` pass order, with bob maps patterned on yosys's xilinx maps.
  - DSP: `mul2dsp` 25×18.
  - BRAM: `memory_libmap` with `bob_brams.txt`, whose cell names were probed from the tool.
  - Arithmetic: `$alu` → BOB_ADD (rule prefix `_80_`, so it beats the generic `_90_alu`; BI must be constant).
  - Flip-flops: `dfflegalize $_SDFFE_PP0P_/PP1P_ r`.
  - LUTs: `abc -lut K`.
  - Outputs: JSON (placer), BLIF (VPR, M9) and a simulation netlist. It fails on any non-bob cell or more than one clock.
- **Proofs** (`tools/bob/equiv.py`, `tools/bob/place.py`, `hw/tb/tb_synth.v`):
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

### M9: PnR with VPR

- `tools/bob/vpr_run.py`: VPR in Docker (amd64), fixed seed, `.pcf` → fixed pins.
- `tools/bob/fasm_from_vpr.py`: `.net/.place/.route` → bob FASM (pip → mux value, BLE → LUT INIT and flags).

**Done when:** every example routes; FASM is legal against `device.json`; same seed gives the same result; timing and wirelength reports are printed.
**HW:** VPR-routed `gates.v` and `counter.v` (minimal FASM → chain) run on the board.

### M10: bitgen + golden co-simulation

- `tools/bob/bitgen.py`: FASM → chain → CRC → `.bit` wrapper. `tools/bob/cli.py`: `bob build design.v --pcf pins.pcf`, `bob load`.

**Done when:** bits → FASM → bits round-trips; every example's source Verilog equals the fabric RTL loaded with its chain through CFG_IN, on random vectors every cycle.
**HW:** `bob build` + `bob load` for every example; `hwtest.py` compares LEDs and CAPTURE against golden simulation.

### M11: full hardware bring-up

blinky, switches → LEDs, RAM and FIR on the PYNQ-Z2, verified by readback and CAPTURE. Reports committed.

### M12: Python PnR + optimisation

Python pack/place/route checked against VPR's results; LUTRAM configuration memory (ZUMA) to cut LUTs/FFs per tile, measured against the M3/M7 reports; larger grid.

### M13: frame-based configuration (only once everything above is solid)

Replace `cfg_mem.v` with a UG470-style frame controller: sync word `0xAA995566`, type-1/type-2 packets, FAR/FDRI/FDRO with auto-increment, CRC over `{addr, data}`, OpenFPGA `frame_based` decoders. Bitgen's output stage switches to frames. Tiles, VPR and FASM stay untouched.
**Done when:** the M10 golden tests pass unchanged through the frame path. **HW:** the same examples load through frames.
