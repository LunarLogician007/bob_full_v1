# Handoff — bob_full_v1, 2026-09-23

**Read `CLAUDE.md` first (the rules), then `PLAN.md` §2 (status) and §3 (how the user wants this done).**
This file is the live state: what is finished, what is in flight, and exactly what to do next.

---

## 0. Next agent: start here (2026-09-23, end of session)

### Where things are
- **Two checkouts.**
  - `/Users/sk/work/bob/bob_full_v1` is the user's folder, on `main` at `8e6ecff` (M20). It must
    keep the M20 tools while the board runs M20. Never check milestone WIP out there: the M20
    board session broke on it, every check `KeyError: 'cluster'`.
  - `/Users/sk/work/bob/bob_full_v1_m21` is a git worktree, branch `m21` (14 commits ahead of
    main). All M21 work is here.
- **Uncommitted, user's:** `docs/bob_full_v1_report.tex` (never commit it),
  `docs/hwtest/results.log` (the M20 board runs), `docs/reports/M20/` (bit and two reports),
  `runme.log` (the M21 Vivado log the user copied in).
- **Stale:** the sweep scratch (`build/sweep/`) and the SDD ledger
  (`.superpowers/sdd/have-a-look-into-agile-emerson/progress.md`) are in the worktree.

### M20 on the board (2026-09-23): 57 of 58 pass. Two defects, both already fixed on `m21`
1. **`bob-fir` fails at clock 16 (a stepping race).** INTEST autostep raised the step on the
   same falling TCK edge as the boundary update (`jtag_tap6.v`), so the guest clock came about
   30 ns after the new pad values. fir's button → DSP → adder → `y` path is longer than that
   on M20's placement.
   - Fix on `m21`: the step fires one TCK later.
   - Test: `tb_bob` measures pad inputs → gce, 112 ns in simulation, and requires at least a
     TCK.
   - Mutant: `autostep-same-edge`.
2. **Vivado WNS −0.919 ns** (`docs/reports/M20/bob_top_timing_summary_routed.rpt`). All 98
   endpoints are `clock_ctrl.v`, `per_m1 → cnt` (the period arithmetic in one 8 ns cycle).
   - Harmless on the board: the source is static config, and clock-rate / fmax / margin pass.
   - Fix on `m21`: `last` and `min_gap` are registered.
   - Mutants: `period-reg-stale`, `gap-floor-dropped`; both killed.

**Open decision for the user:** tag `m18`/`m19`/`m20` with these two recorded as known issues,
or rebuild M20. I recommended tagging; the user has not answered.

### M21 as built (branch `m21`)
- **The user approved N = 4, 7 × 7** (8 × 8 measured at ~86% of the chip):
  - 49 CLBs × 4 elements = 196 LUTs; I = 16, full crossbar, W = 40
  - 32,896 bits, 257 frames, 32 pads
- **The sweep:** `docs/reports/M21/cluster_sweep.md` (`software/bob/sweep.py`). N = 10, the
  plan's target, costs 421 host LUTs per LUT against N = 4's 289.
- **Built and verified:** everything in §1d below.
  - `make check` is green, apart from one test fixed afterwards:
    `test_build_tcl::...measures_the_fabric_delays` had stale `delay_samples.txt`; it was
    regenerated, and `tests/test_timing.py::test_delay_samples_name_this_device` now guards it.
  - The whole-design yosys estimate is 58,535 LUT / 35,995 FF, with the shadow as 2 × RAMB36.
- **Mutation suites are incomplete.**
  - `mutate_cfg`: all killed.
  - `mutate_fabric` / `mutate_frames` were stopped: two mutants (`xbar-sel-off-by-one`,
    `mux-inputs-shifted`) make combinational loops, and their zero-delay simulations spin
    forever.
  - **To do:** give `run_one` in `sim/mutate_*.sh` a per-mutant timeout. There is no
    `timeout` on this Mac; use a background `kill` watchdog. Count a hang as killed and say
    so. Then rerun `make mutate`. It is parallel (`MUTATE_JOBS`, default 4).

### THE BLOCKER: M21's Vivado implementation does not close timing
The user's log: `/Users/sk/work/bob/bob_full_v1/runme.log` (copied from
`bob_vivado\bob.runs\impl_1\runme.log`).

| gce gap / XDC sysclk multicycle | WNS after placement | TNS |
|---|---|---|
| 512 cycles (4096 ns; M16–M20) | −133 ns | −144,700 ns |
| 1024 cycles (8192 ns; commit `702842b`) | **−290 ns** | −13,400 ns |

- **What fails:** every failing net is fabric: `u_fabric/r<node>` routing wires,
  `u_clb_x*y*/t_*` LUT trees, element flip-flops `q_i_*`/`q2_i_*`, DSP input registers
  `c_q`/`d_q`, starting at configuration bits (`u_store/...cfg_reg`). phys_opt_design then
  grinds for hours, recovering picoseconds per pass.
- **Diagnosis:** Vivado times the **unconfigured** fabric. With every mux open, the mesh is
  full of combinational loops, and Vivado cuts them arbitrarily. The longest surviving chain
  grew from ~4.2 µs to ~8.5 µs when the budget doubled, so it is not a property of the
  fabric. Raising the gap again will probably not converge, and every doubling halves the
  default (untimed) guest clock. (At M16 one raise to 512 worked; M21's cluster mesh — W = 40,
  crossbar feedback in 49 CLBs — is much bigger.)
- **Commit `702842b`** (gap 10) is on `m21`. It did not fix the build. Keep it or revert it
  depending on the fix below. `device.py`, the XDC, `test_layout.py`, docs and
  `test_flow`/`test_hwtest_fake` were all updated with it.

**Proposed fix (not implemented; the user asked for no further edits this session):**
PLAN §8's "case analysis", flagged in §5 below since M16: stop Vivado from timing paths that
exist only in an empty fabric. Since M20, the per-design sign-off is `timing.py`, with delays
measured on the build, proven on the board by `clock-margin` (5.17×). Two ways:

- **(a) Decouple the XDC from the gap.**
  1. Put a very large multicycle on sysclk → sysclk (for example 16384/16383) and keep the
     one-cycle cell exceptions for `u_clk` / `u_bram_jtag`. A clock-level `set_false_path`
     would override those exceptions (UG903 precedence), and cell-name exceptions on the
     fabric are unreliable because flattening renames its registers (the XDC comments).
  2. Move the hardware gap back to 512 (M20, board-proven).
  3. **Enforce** the contract in software: the flow (`flow.py` timing stage) and `cli.load`
     refuse a word whose critical path × margin exceeds its own gce spacing — `clk_gap`, or
     the default gap when 0 — in both clock modes. Add a pytest that every `designs.py` hand
     design passes too (hwtest loads those directly through `cfgplane`).
  4. `tests/test_layout.py`'s rule "XDC multicycle == 2**GCE_MIN_GAP_SHIFT" becomes "XDC
     multicycle ≥ the gap", plus the enforcement test.
- **(b) `set_case_analysis 0` on every configuration-memory flip-flop output**, so Vivado sees
  a dark, loop-free fabric. This is closest to PLAN §8. It is risky: 32,896 pins, flattening
  renames (`u_store` cells), and the XDC must stay plain (no Tcl loops).

**Try (a) first.** Before any hand-off, check it on a Vivado-free proxy: yosys
`synth_estimate.sh` does not time, so the real test is the next Vivado run. Tell the user to
**stop** a run stuck in phys_opt at a large negative WNS; it will not recover. Disabling
phys_opt (`build.tcl` sets `STEPS.PHYS_OPT_DESIGN.IS_ENABLED true` on purpose; read its M16
comment) is not the fix.

### Then
1. The Vivado build closes timing (IDCODE `0x0B021093`). Copy `out/M21/` to
   `docs/reports/M21/` in the worktree, run `software/bob/delays.py fold
   docs/reports/M21/delay_paths.rpt` (it samples the crossbar now), then `make check`.
2. `make hwtest M=M21` **from the worktree** (checklist `docs/hwtest/M21.md`).
3. Merge `m21` into `main` and tag `m21`. Tag `m18`–`m20` per the user's decision above.
4. Refresh the generated pages: `python3 docs/project/collect.py && python3 docs/project/build.py`,
   and `python3 docs/arch/build.py --data`.

---

## 1. Where the project stands

| | |
|---|---|
| Milestones M0–M16 | **all passed on the PYNQ-Z2** |
| Bitstream in the PL | **M16** (`0xFBEEF093`): 100 CLBs (12 × 10 core), 145 frames = 18 560 bits, 2 BRAM, 2 DSP, 44 pads. 20 498 LUTs (38.5%), 21 511 FFs (20.2%), WNS +0.667 ns, WHS +0.112 ns, DRC clean |
| Guest tooling | `./bob build｜load｜info｜fasm`, and **bob studio** (`software/host/studio.py`), which since M18 has **projects** (`.bobproj`) and **block designs** |
| Whole-project report | `docs/project/REPORT.md` + `project.html`; the learning guide is `docs/project/GUIDE.md` + `guide.html` (**done**, committed in `807f2b9`) |
| In flight | **M21: software done and simulated, in the worktree `../bob_full_v1_m21` (branch `m21`); the Vivado build (IDCODE `0x0B021093`) and `make hwtest M=M21` are pending.** `main` (this project's folder) keeps the M20 tools for the M20 bitstream on the board. M18–M20 on the board 2026-09-23: 57/58, `bob-fir` failed (the autostep race) and the build had WNS −0.919 ns; both are fixed in M21's RTL (§1d). Whether to tag `m18`–`m20` with that known issue or rebuild M20 is the user's decision |

The device table in `README.md` is generated from `software/bob/device.json` by
`software/bob/devtable.py`; `make check` fails if it drifts.

---

## 1d. M21 — the cluster CLB and the BRAM shadow

- **Where:** worktree `/Users/sk/work/bob/bob_full_v1_m21`, branch `m21` (never check a milestone's WIP
  out in the main folder while the board runs the previous one: the M20 board session broke on it).
- **Architecture** (`device.py` `ARCH_M21`): 9 × 7 core, 49 CLBs of N = 4 elements, I = 16, full
  crossbar, W = 40, 32 pads, 32 896 bits in 257 frames (FIDX_W 9: FAR table 32 bits/column).
  Chosen from `software/bob/sweep.py` (`docs/reports/M21/cluster_sweep.md`); the user approved N = 4, 7 × 7.
- **Elements:** `hw/src/clb/ble.sv`; the cluster `bob_clb` is generated into `bob_fabric.v`. In
  the host tools a CLB's crossbar is ordinary muxes over synthetic nodes (EIN element inputs,
  ECY carry links), so model/router/timing reuse their code. Fields are per element:
  `clb_x1y1.e3.init`, crossbar selects `clb_x1y1.e3.x2`. CAPTURE is 2 bits per element.
- **PnR:** VPR packs the cluster itself; `fasm_from_vpr.py` sets the crossbar from the `.net` and
  the route (any equivalent CLB pin). bob's packer is `pnr/pack.py` (AAPack-style; dense when the
  design fills > 70% of the CLBs).
- **Readback:** BRAM shadow in `cfg_store.v` (section 14 of the format doc).
- **M20 fixes:** `jtag_tap6.v` autostep a TCK late; `clock_ctrl.v` registered `last`/`min_gap`.
- **gce gap 1024 cycles** (`GCE_MIN_GAP_SHIFT` = `DIV_MIN_SHIFT` = 10, XDC multicycle 1024/1023): the first
  M21 implementation placed at WNS −133 ns on fabric paths (the empty cluster mesh's path is
  ~4230 ns > 512 × 8 ns) and phys_opt ground on for over an hour, as at M16. Only untimed designs
  pay (122 kHz max); a design built with timing sets its own `clk_gap`.
- **Size:** yosys 58.6k LUT / 35.9k FF whole design (about 36k LUT in Vivado, 68%).
  Implementation will take longer than M16's.
- **Next:** hand `hw/` to Vivado (`docs/hwtest/M21.md`); after the build fold `delay_paths.rpt`
  (it now samples the crossbar), `make check`, `make hwtest M=M21`, tag `m21`.

## 1c. M20 — the user clock from the design's own timing

- **Hardware:** `clock_ctrl.v` has `clk_period` and `clk_gap` (ctrl tile 8 → 40 bits; the chain
  is still 18,560 bits in 145 frames). `clk_gap` = 0 is the safe 512, so the XDC is unchanged.
  `tb_clock_gap` has 17 checks (period, gap,
  prescale, floor, safe default, steps at a gap), and `sim/mutate_frames.sh` has 4 new mutants.
- **Timing:** `software/bob/timing.py` (the design's critical path from its bits) and a new flow
  stage **timing** between bits and model. **Clock constraints:** `.sdc` `create_clock` (`timing.read_sdc`,
  project `constrs/`, `--sdc`, studio **Create clock constraint…**). The slack is reported;
  negative slack fails the build (no `.bit`). `--hz N` is the same check; `--hz auto` is the
  fastest safe clock. Projects store `hz` (`div` = before).
- **Delays:** `software/bob/delays.json` is provisional: routing measured on M16's report,
  LUT/FF/BRAM/DSP estimated, 2× guard band. `build.tcl` sources `hw/scripts/extract_delays.tcl`
  after implementation; it times `hw/scripts/delay_samples.txt` (`delays.py plan`) into
  `out/M20/delay_paths.rpt`. `delays.py fold` turns it into measured delays (1.25× guard band).
  `tests/test_build_tcl.py` runs the round trip through the Vivado stub.
- **Board checks:** `work/examples/atspeed` (a self-checking counter, error latched on LD0,
  VPR route committed); `clock-rate`, `clock-fmax`, `clock-fmax-py` and `clock-margin` (sweeps
  to the 2-cycle floor; every rate up to the computed one must pass). FakeBob gained `max_hz`
  (a fabric too slow above that rate) and a time `budget` (it used to fall behind forever at
  MHz rates, which hung a test run overnight). The studio's `DemoBoard` now just sets that budget.
- **IDCODE:** version nibbles ran out at M16. From M20 it is `0x0B0<MM>093` (`build.cfg` notes it).
- **The readback-mux idea in §5 below does not work.** A tree beat the flat array on
  `cfg_store` alone, but was +310 LUTs in the whole design (yosys folds the flat array into
  FDRO's word select). `cfg_store.v` is unchanged. See PLAN's M20 section; room for M21 needs a
  different memory (BRAM shadow or LUTRAM), not a different mux.
- **Size:** yosys says 32,838 LUT / 21,549 FF, against 32,697 / 21,485 for M19 on the same
  tool. The clock logic costs +141 LUTs and +64 FFs, so Vivado should land near M16's 20.5k.

## 1b. M19 — the studio app and the waveform viewer

- `./bob studio [--probe fake|usb] [--browser]`: `studio.serve_app()` runs the backend in
  this process and shows it in a pywebview window. `AppBridge` gives the page the system's
  folder, open and save dialogs (`native()` in `p3_api.js`); the page falls back to its own
  folder browser in a tab. pywebview is optional (installed in the mamba Python beside pyusb).
- The studio page lives in `software/studio/` now (was `docs/studio/`), built into
  `software/studio/studio.html`.
- `zoomer()` in `p3_api.js` is the shared zoom and pan (block design, Device view). The
  waveform zooms time only (`p12_wave.js`).
- Block designs accept the board's pin names: `board.LD1` is `board.led[1]`
  (`bd.PIN_ALIAS`). The canvas's **+ input pin / + output pin** dialog lists them before
  the pads.
- `software/host/padwave.py`: capture over boundary scan. Step mode (INTEST autostep) pairs
  the vector applied for clock k with the outputs captured on the next scan, exactly as
  `_bob_check` does. `tests/test_padwave.py` requires a stepped capture of `counter.v` driven
  by its trace to equal the source. Studio routes `/api/wave/*`; board checks `wave-step`
  and `wave-live`; `FakeBob(lose_clocks=N)` is the failing board.
- The UI was driven in the real WebKit engine through pywebview's `evaluate_js`: every tab,
  a project and block design, board-pin wiring, validation marks, zoom, a triggered capture.
  Zero script errors.

## 1a. M18 — projects and block designs in bob studio

- `software/bob/project.py`: New/Open Project, a folder anywhere on disk (`<name>.bobproj`,
  `src/ bd/ ip/ constrs/ build/`), sources, top, the active `.pcf`, settings, recent list
  (`~/.bob/recent.json`). `project.flow_kwargs()` is what `flow.Flow` takes;
  `./bob build --project x.bobproj` reads it too.
- `software/bob/bd.py` + `software/bob/ip/` (14 cores): block designs. `check()` returns an
  error at each endpoint; `generate()` writes `bd/<name>_wrapper.v` (ports `clk sw btn led`
  plus pads) and `constrs/<name>.pcf` when a pad is used, copies the IP into `ip/`.
- Studio: Project Manager and Block Design tabs (`software/studio/p10_project.js`, `p11_bd.js`),
  routes under `/api/project/*`, `/api/bd*`, `/api/fs`, `/api/ports`. The path guard
  allows the repo **or** the open project.
- `work/examples/bd_demo/` (committed VPR route `software/bob/vpr/bd_demo_bd_wrapper/`),
  board checks `bob-bd_demo`, `pnr-bd_demo`, `live-bd_demo` in `MILESTONE["M18"]`.
- Worth knowing: the first spare pad is taken by `clk` (`vpr_run.write_eblif`); the Pin
  Planner does not know that, `bd.py` does. A new project defaults to `pnr vpr`, which needs
  Docker until its route is committed; `python` needs nothing.
- Exercised in WebKit at M19 (see 1b); the manual steps in `docs/hwtest/M18.md` are the human click-through.

## 2. M16 — the 10 × 10 CLB grid, as built

The first Vivado attempt did **not** close: implementation ran 3 h 25 min and ended at
WNS −465.7 ns on fabric flop → flop paths, with `[Route 35-447]` congestion. The cause was
the constraint, not the tool. The fabric's budget was `-setup 256` × 8 ns = 2048 ns, honest
only because `clock_ctrl.v` guaranteed gce pulses ≥ 256 sysclk cycles apart; the 12 × 10
fabric's static path through the unconfigured routing muxes is about **2500 ns**.

Raising the gap to 2⁹ = 512 cycles (4096 ns) fixed the timing. The cost is the free-running
guest clock: **244 kHz maximum instead of 488 kHz**. Stepped mode is unaffected (TCK at
100 kHz is 10 µs per request, slower than the 4.1 µs gap).

Then `route_design` died inside "Phase 2.3 Update Timing" — no error line, and by hand it
took Vivado itself down. The cause was threading, not the design: the timer has to cut every
combinational loop in the routing mesh, and M16 has one strongly connected component of
**2146 wires with 11 270 independent cycles** against M15's 1018 / 4130. `general.maxThreads 1`
in `drc_waiver.tcl` (hooked as TCL.PRE on `opt_design`, `route_design` and `write_bitstream`,
because `launch_runs` implements in a separate process) routes the same checkpoint through.
`phys_opt_design` is **on**: with the gap right it costs seconds.

**The rule this confirms:** the gce gap is not a constant, it is a function of the grid.
Grow the fabric and `GCE_MIN_GAP_SHIFT` grows with it. The next step up is 10 (1024 cycles,
8192 ns), and it halves the guest clock again — see §5 for the way out of that trade.

Since M16 that agreement is **checked**, not remembered (`tests/test_layout.py`):

- the XDC's sysclk → sysclk `-setup` must equal `2**GCE_MIN_GAP_SHIFT` from `device.json`
- `-hold` must be `-setup` − 1
- `bob_fpga.v` must take `GAP_SHIFT` from `` `BOB_GCE_MIN_GAP_SHIFT `` — it used to pass
  `DIV_MIN_SHIFT` to both, so `device.py`'s gap knob did nothing
- `DIV_MIN_SHIFT >= GCE_MIN_GAP_SHIFT`, or the divider would outrun the exception

Each of those four was mutation-tested: break the number and the suite fails.
`tb_clock_gap` now also runs at the board's gap, not only at the short simulation value.

---

## 3. bob studio

`software/host/studio.py --probe fake` (no board) or `--probe usb` (the Pico), then
`http://127.0.0.1:8765`. An EDA tool for this FPGA, laid out the way Vivado is: sources and
an editor, Flow Navigator, Synthesis / Implementation / Generate Bitstream with per-stage
timings and diagnostics, a Device view showing where the design landed and which channels it
routed through, a Pin Planner that writes a `.pcf`, and Program and Debug — program, readback
and verify, CAPTURE, partial reconfiguration.

- **`software/bob/flow.py`** is the engine: the same flow `./bob build` runs, as separate timed
  stages each returning what it measured. `cli.build()` is now a wrapper over it, and
  `tests/test_flow.py` requires both to write a **byte-identical `.bit`**.
- **`software/host/fakeboard.py`** is `FakeBob`, moved out of `tests/test_hwtest_fake.py` (which now
  imports it) so tools that are not pytest can use it. It answers from `software/bob/model.py`.
  It cannot find hardware problems — it is for running the flow with no board attached.
- **`software/studio/`** builds `studio.html` the way `docs/arch/` builds `arch.html`: one
  self-contained page, vanilla JS and hand-drawn SVG, no external libraries. The backend is
  stdlib `http.server` + Server-Sent Events, so the project gained **no new dependency**.
- New flags: `./bob build --json FILE` (the stage record), `--project bob.proj`,
  `./bob load --probe usb|fake`.

Worth knowing: the software board simulates one guest clock per `model.settle()`, about 2 ms
at 100 CLBs, so a free-running design runs behind the rate it asks for. `studio.DemoBoard`
bounds the backlog to a time budget and the page reports how many edges were skipped. The
real board has no such problem.

---

## 4. Everyday commands

```sh
make check            # device files + the generated device table + every simulation + lint + pytest
make rrgraph          # after an architecture change in device.py (Docker/Colima), then make device
make vpr              # re-route every example (Docker)
make pnr              # bob's PnR vs VPR report
make mutate           # the three mutation suites
make hwtest M=M16     # board test (interactive); ONLY=<check> reruns one
make clean-logs       # build/ grows to gigabytes of yosys estimate logs
software/host/studio.py --probe fake        # bob studio, no hardware
software/bob/devtable.py --write        # regenerate the device table in the documents
software/bob/synth_estimate.sh $PWD $PWD/build/est      # whole-design yosys estimate before a Vivado hand-off
python3 docs/project/collect.py && python3 docs/project/build.py   # report data + project.html
python3 docs/arch/build.py --data                    # arch.html (--data after make device)
python3 software/studio/build.py                         # studio.html
```

Docker for VPR: `colima start`, then `DOCKER_HOST=unix://$HOME/.colima/default/docker.sock`.

---

## 5. What is worth doing next

**The IDCODE numbering is out of nibbles.** M16 used `0xF`, the last one (`PLAN.md` §7).
M17 needs a new scheme before another board build can be told apart on the wire.

**The frame readback mux is about a third of the design, and it grows with the grid.**
`hw/src/core/cfg_store.v:82-97` builds readback as a flat `2**FIDX_W = 256`-entry ×
128-bit array indexed at run time — a real 256:1 mux. Measured with yosys on `cfg_store`
alone, including a control with the mux replaced by a constant:

| `cfg_store` | LUTs |
|---|---|
| NFRAMES = 65 (M15) | 5 726 |
| NFRAMES = 145 (M16) | 12 402 |
| NFRAMES = 145, readback mux removed | **599** |

So the mux is ~11 800 of 12 402 LUTs — **95% of `cfg_store` and ~36% of the whole design** —
and it serves only JTAG readback, which has no timing requirement at all. It is also the
biggest single contributor to the congestion that stalled M16's first implementation.

The coding style is deliberate and must stay: a *computed part-select* over the configuration
memory is what ran Vivado out of memory at M13 (the comment at `:79` says so). The fix is to
mirror the write path's hierarchical FAR decode (`cfg_frames.v:144-184`, column base +
per-column count): a small per-column mux feeding a ~15-way column mux, O(Σ columns) instead
of O(2⁸), with nothing on the wire changing.

**Then the gap stops having to grow.** `PLAN.md` §8 has listed case-analysis sign-off since
M7 and it was never done: constrain the configuration bits so Vivado never times a path that
exists only in an unconfigured fabric. That is what breaks the "every grid step halves the
guest clock" trade permanently.

Also open: ZUMA-style LUTRAM configuration memory (`PLAN.md:752`; configuration is 21 511
flip-flops, ~86% of every FF in the design, a fraction that grows with the grid); more than
one BLE per CLB, so 3391 routing muxes amortise over more logic; a substantial demo design
(the largest example is `work/examples/big/big.v`, 21 lines and 56 CLBs); and CI — the Mac-only half
of `make check` would run on a hosted runner today and there is no `.github/` at all.

---

## 6. Working agreements (from CLAUDE.md, worth repeating)

- One milestone at a time; show results and **stop for the user's go-ahead**.
- Every milestone ends with a PYNQ-Z2 test; simulation alone never closes one.
- Every Vivado build is the complete FPGA plus the new feature.
- Keep both configuration paths working (frames and chain).
- Anything the user does by hand needs a guide: what to press, what the LEDs must show, and time to do it.
- Git: commit as work progresses; **never** commit `docs/bob_full_v1_report.tex` (the user's file); tag `mN` only after milestone N passes on the board.
- **Do not edit `hw/` or the shared tools while a milestone is in flight on the Vivado machine** — freeze first (`PLAN.md` §8). Phase 0 of the studio work was written as new files only for exactly this reason.
