# Handoff — bob_full_v1, 2026-09-24

**Read `CLAUDE.md` first (the rules), then `PLAN.md` §2 (status) and §3 (how the user wants this done).**
This file is the live state: what is finished, what is in flight, and exactly what to do next.

---

## 0. Next agent: start here (2026-09-24, M24 on branch `m24`)

- `main` matches the board (M23, IDCODE `0x0B023093`). **M24 is in the worktree
  `/Users/sk/work/bob/bob_full_v1_m24`, branch `m24`**; merge and tag only after its board test.
- The user chose (2026-09-24) option 4 of the paper list: more logic per element, "carry chain
  and Double Duty". Done: Double Duty, end to end (PLAN §2 M24). Not done: general logic on
  the carry chain via MIG (Kim & Anderson, FPL 2021). The fabric supports it now, but it needs
  a synthesis pass; this is the natural M25.
- Results: tb_clb 4048 PASS; every VPR example and the Python PnR pass the model check;
  elements −4.7% (VPR) / −13.2% (bob's packer); yosys 25,811 LUT (+120); fake-board
  double-duty pass and fail; `dd-*` mutants killed. `make check`: see the latest `m24` commit.
- Next: the user builds M24 in Vivado (`docs/hwtest/M24.md`), then `make hwtest M=M24`.
- Still missing from M23: `docs/reports/M23/{delay_paths.rpt, sysclk_1cycle.txt, drc.rpt,
  build_info.txt}`.

## 0z. The M23 state (kept for reference)
 (2026-09-24, after the M23 merge)

### Where things are
- **One checkout:** `/Users/sk/work/bob/bob_full_v1`, branch `main`, holds everything through
  M23 and matches the board (IDCODE `0x0B023093`). The `m23` worktree was merged and removed
  (branch kept); tags `m21`, `m22`, `m23` are set.
- Uncommitted and the user's: `docs/bob_full_v1_report.tex` (never commit it),
  `docs/reports/M20/`, `docs/reports/M21/` (`timing.rpt`, `util.rpt`, `bob_top.bit`).
- For the next milestone, work in a new worktree again.
- The user asked (2026-09-24, before sleeping): the delay fix, then the M23 sweep, then the
  biggest grid that fits (10 × 10 or more), then papers on new FPGA ideas bob could use.

### Done on `m23`
1. **Delay extraction fix** (`0447b6a`). M22's 1100 samples were all NOPATH because Vivado
   renamed the hierarchy (`u_core/u_store/u_fabric/...`). `extract_delays.tcl` now indexes
   every `*u_fabric/*` net/cell and finds a sample by its path below `u_fabric`;
   `delays.py` normalises the same way. `tests/test_build_tcl.py` has a renamed-netlist stub
   (`BOB_STUB_RENAME=1`), and the test fails with either half of the fix removed.
2. **The sweep** (`software/bob/gridsweep.py`, `docs/reports/M23/grid_sweep.md`). The model
   reproduces M22 exactly (38,218 LUTs). **The wall was SLICEM slices:** the four CFGLUT5s of
   a SLICEM share a shift enable (per CLB), so Vivado packed 3.37 per slice, and the SLICEMs
   were 84% full at 81 CLBs.
3. **Two cheaper building blocks:**
   - `hw/src/clb/lxor.v`: a crossbar mux keeps its CFGLUT5 leaves (O6 only), and the root is
     a fixed OR in a plain LUT. 152 → 128 CFGLUT5 per CLB.
   - `hw/src/fabric/bob_mux.v`: LUT6 4:1 leaves + MUXF7/MUXF8. It equals the M22 mux over 80
     sizes (iverilog), and yosys counts equal `gridsweep.hand_luts()`.
4. **10 × 10 = 100 CLBs = 400 LUTs** (`ARCH_M23`: 12 × 10 core, BRAM x=3 and DSP x=8 of
   height 5, W 36, fc_in 0.10, 44 pads, 532 frames, 68,096 bits). Every example routes in
   VPR (fir16 needs 34). SLICEM slices 87% at M22's packing; 11 × 10 would be 96%.
   Whole-design yosys: 25,691 LUT + 12,800 CFGLUT5 + 26,787 FF, 1.9 GB.
5. **The first M23 build failed to place (2026-09-24, 12 × 11).** That design shared each
   crossbar leaf between two muxes via O5/O6 (80 CFGLUT5 per CLB on paper). Vivado maps a
   dual-output CFGLUT5 to SRL16E + SRLC32E, two LUT sites. The placer reported "Weighted
   LUTRAM utilization is more than 100" and hung in Phase 3.2; the user stopped it. **Never
   use a CFGLUT5's O5 in bob.** The watch-items are in `docs/hwtest/M23.md`.
6. **Limits found on the way:**
   - `cfg_ctrl.v`'s 16-bit chain counter would have refused every chain load. It is 24 bits
     now; CFG_CTRL reports the low 16 and `len_err` does the full comparison. The host, the
     fake board and `tb_bob` follow.
   - The chain-wide L mask was split into `BOB_LKIND`/`BOB_LMASKS` (iverilog constant limit).
   - Bench literals are chunked (`sim/vlit.py`; iverilog's 16k-character lines).
   - `lint.sh` raises the stack (verilator segfaulted at 8 MB).
7. **Board check `xbar-pins`** (`docs/hwtest/M23.md`): the snake on every pin, ANDed with
   const1 on the others. The fake board has pass and fail cases (`dead_xbar_pin`,
   `lose_lframes`), plus a test that the M22 snake alone misses a dead pin.

### Verification state (10 × 10)
- tb_clb 4032 PASS. VPR: all 39 steps PASS. Fake-board M22/M23 tests 10/10. Crossbar
  mutants all killed by tb_clb: `lxor-root-and`, `lxor-drop-leaf0`, `expand-leaf-index`,
  `expand-no-const1`, `expand-bit-order`.
- **tb_bob 671/671 PASS** (20 min) and **lint clean** on 10 × 10.
- **Routing-mux mutants all killed** by the new `sim/run_mux_sim.sh` (tb_mux: bob_mux vs
  the behavioural table, 80 widths up to 40 inputs, 164,992 checks, 4 s; in `make sim`).
  Under tb_bob alone `mux-top-select` survived: this fabric's widest mux has 14 values, so
  the wide branch (sel[W-1:4]) is never instantiated, and `mux-leaf-init` only died as a
  45-min hang.
- **`make check` green on 10 × 10 (2026-09-24, 3 h 7 min).** tb_clb 4032, tb_mux 164,992,
  BRAM 5292, DSP 1344, tb_bob 671, cfg 180, K=4 4032 + 541, synth 972, cosim 7026, frames
  73 + 17 + 17, lint clean, pytest 521 passed / 23 skipped. Mutants: every M23 mutant
  killed. The 12 × 11 run passed tb_bob 672/672, cfg, K=4 and synth before it was
  stopped. cosim is slow with the primitive mux models (more than 3 h at 12 × 11).

### M23 on the board (2026-09-24)
- **Vivado:** timing closed, WNS +0.048 ns (WHS +0.075). 36,710 LUTs (69.0%; logic 23,982,
  LUT as memory 12,728 = 73.2% of SLICEM LUTs), 26,960 FFs, F7 5,638 / F8 1,634, slices
  11,709 (88.0%), SLICEMs 4,029 of 4,350 (92.6%). Slices came out fuller than the model's
  66-76%; **10 x 10 is the ceiling for this CLB on the XC7Z020.**
- **`make hwtest M=M23`: 68/68 automatic checks PASS** (9 min), including lutram-snake and
  xbar-pins over all 400 elements, frames and chain, partial reconfiguration, the fir16
  live checks and clock-margin 5.00x on silicon.
- **Manual steps done by the user (2026-09-24, reported: "manual over").** M23 passed; `m23`
  merged into `main` and tagged.
- Still missing from `docs/reports/M23/`: `delay_paths.rpt`, `sysclk_1cycle.txt`, `drc.rpt`,
  `build_info.txt` (in `E:\bob_full_v1\bob_vivado\out\M23\`). When they arrive, run
  `software/bob/delays.py fold docs/reports/M23/delay_paths.rpt` (the first build with the
  rename fix; `delays.json` is still provisional) and `tests/test_reports.py`.

### Next
1. The user runs the M23 Vivado build (`docs/hwtest/M23.md`). Watch "Phase 1.3" for the
   weighted-LUTRAM warning and "Phase 3.2" for time; the fallback is 10 × 9.
2. `delays.py fold docs/reports/M23/delay_paths.rpt`: the first build with the rename fix.
3. `make hwtest M=M23`, then merge `m23` into `main` and tag `m23`.
4. Paper ideas for M24+ are in `docs/research/2026-09-24-fpga-ideas.md`.

## 0a. After the M22 merge (2026-09-24), kept for reference

### Where things are
- **One checkout again:** `/Users/sk/work/bob/bob_full_v1`, branch `main`, holds everything
  through M22. The `m21` and `m22` worktrees were merged and removed (branches kept); tags
  `m21` and `m22` are set. The board runs M22 (IDCODE `0x0B022093`).
- Uncommitted and the user's: `docs/bob_full_v1_report.tex` (never commit it),
  `docs/reports/M20/`, `docs/reports/M21/` (`timing.rpt`, `util.rpt`, `bob_top.bit`;
  `tests/test_reports.py` fails on it until `sysclk_1cycle.txt` arrives from `out\M21\`).
- For the next milestone, work in a new worktree again, so `main` keeps the tools that
  match the bitstream on the board.

### M22 as built (branch `m22`, approved 2026-09-23: approach B, 9 x 9, measure first)
- **What:** each element's truth table and each crossbar mux in AMD CFGLUT5 (ZUMA-style);
  81 CLBs (9 x 9) = 324 LUTs; 441 frames (56,448 bits), 30,456 bits held only in CFGLUT5s;
  each CLB tile: frame 0 = 16 selects + the flags, 2 INIT frames, 8 selects + routing. Spec:
  `docs/superpowers/specs/2026-09-23-m22-lutram-design.md`; the design in
  `docs/bitstream-format.md` section 15; checklist `docs/hwtest/M22.md`.
- **Verified:** `make check`-equivalent runs (see the commit log): tb_clb 4032, tb_bob 671
  (with CFGLUT5 contents against an independent model and the JPROGRAM sweep), cfg, K=4,
  frames, cosim, synth; lint clean; pytest 501 + the device table; every example re-routed by
  VPR and legal; M22 mutants killed (see below).
- **Mutants:** all M22 mutants killed - `expand-bit-order`, `lxmux-root-no-ce`,
  `lut-halves-swapped` (tb_clb), `loader-no-sweep` (tb_bob), `loader-31-shifts` (as a hang:
  every table one bit off leaves loops, and the watchdog's 2700 s ended it). The full
  `make mutate` for M22 has not been rerun end to end (each tb_bob mutant is ~10 min).
- **`make check` green 2026-09-24** (2 h 20 min: cosim alone ~90 min with the CFGLUT5 model).
- **Size (yosys, whole design):** 36,980 logic LUTs + 12,312 CFGLUT5 = 49.3k (M21 58.5k),
  25.4k FFs (M21 36.0k), 5.1 GB peak. **Vivado projection 35-42k LUTs (66-79%)** - the two
  M21 calibrations disagree - and SLICEM ~71%. My grid table for the user said ~28k; it
  undercounted the routing each extra CLB brings. At the high end slices would be near 100%
  (M21: 68.5% LUTs was 90.9% of slices). **If placement or routing fails, step down:**
  `ARCH_M22` `ny` 9 -> 8 (72 CLBs) in `software/bob/device.py`, then `make rrgraph`,
  `make device`, `make vpr`, the pinned sizes in `tests/test_device.py`, `make check`.
- **Simulation-only pieces** (never in Vivado): `hw/tb/prims/CFGLUT5.v` (from
  `sim/hwfiles.sh --sim`: X-resolving reads as UNISIM, outputs held while shifting, and a
  10 ps output delay so a transient loop during a load - one CLB's crossbar and the routing
  live before another CLB's flags - oscillates in simulated time instead of spinning the
  simulator; it hung tb_synth on blinky), `cfg_store.sim_lmem`, and per-CLB gated shift
  clocks in `bob_fabric.v` under `ifdef SIMULATION` (without them tb_bob never finished: 12k
  CFGLUT5 processes woke on every TCK edge).
- **Layout lesson:** a CLB tile writes its flags before any crossbar content (frame 0 =
  16 selects + flags; a frame's flip-flops load at the write, before its CFGLUT5s shift).
  `tests/test_device.py::test_a_load_sets_the_flags_before_any_crossbar_select` holds it.

### M22 on the board (2026-09-24)
- **Vivado:** timing closed, WNS +0.172 ns (WHS +0.029). 38,184 LUTs (71.8%, inside the
  66-79% projection), 12,282 LUT as memory (70.6% of SLICEM), 25,599 FFs, slices 82.3%
  (M21 90.9%). Reports in `docs/reports/M22/` (all of `out\M22\`).
- **`make hwtest M=M22`: 65/67.** lutram-snake passed (all 324 CFGLUT5 elements, frames and
  chain), partial-cluster, bob-/pnr-fir16, clock-margin 4.25x. Failed: `live-fir16` (one LED
  sample at SW=11 BTN=1111 - all four buttons pressed, so button bounce during the JTAG
  sample is the likely cause - then "CFG_OUT readback while running differs") and the next
  check `fast-fir16` (frame load refused, PKT_ERROR). Readback and the load failing
  together look like one corrupted JTAG transfer.
- **Rerun non-interactively 2026-09-24 (no hands on the board): 12/12 PASS** (`live-fir16`
  and `fast-fir16` six times each: load accepted, LEDs == model, readback == .bit). Not
  reproduced. Still to do: one **interactive** `make hwtest M=M22 ONLY=live-fir16` (the goals
  need a person; press the buttons one at a time, as `docs/hwtest/M22.md` says).
- **Delay extraction measured nothing:** all 1100 samples in `delay_paths.rpt` are NOPATH, so
  the fold is refused (it used to relabel the old provisional numbers as measured - fixed,
  `tests/test_timing.py::test_a_fold_that_measured_nothing_changes_nothing`). `delays.json`
  stays provisional (2x guard band; silicon margin 4.25x). `extract_delays.tcl` now writes
  NONET when a sampled net or cell is not in the netlist. To diagnose without a rebuild, in
  Vivado on the routed M22 checkpoint:
  `llength [get_nets -quiet u_core/u_fabric/r1563]` and
  `report_timing -through [get_nets u_core/u_fabric/r1563] -max_paths 1`.

### Then
1. The interactive `live-fir16` rerun; then merge `m22` into `main` and tag `m22`.
2. The delay-sampling diagnosis (above) before the next build.

---

## 0b. The M21 session (2026-09-23), kept for reference

### Where things are
- **Two checkouts.**
  - `/Users/sk/work/bob/bob_full_v1` is the user's folder, on `main` at `8e6ecff` (M20). It must
    keep the M20 tools while the board runs M20. Never check milestone WIP out there: the M20
    board session broke on it, every check `KeyError: 'cluster'`.
  - `/Users/sk/work/bob/bob_full_v1_m21` is a git worktree, branch `m21`. All M21 work is
    here.
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
- **Mutation suites: every mutant killed (2026-09-23).** `mutate_cfg` 6/6; `mutate_fabric`
  all, `xbar-sel-off-by-one` and `mux-inputs-shifted` as hangs (the watchdog,
  `sim/mutate_lib.sh`, `MUTATE_TIMEOUT` 2700 s; a normal tb_bob is 443 s);
  `mutate_frames` 38/38. The first full run found two stale mutants - `carry-direct-cut` cut
  column 8's carry while the counter runs up column 9 (it survived), `xbar-no-feedback`
  expected `o[19]` - and that `make -k mutate` skips `mutate_frames.sh` once a suite fails.
  Both patterns fixed (the column now comes from `designs.FULL_COL_X`); `MUTATE_ONLY="a b"`
  reruns named mutants.

### The Vivado timing blocker, and the fix (2026-09-23, implemented, awaiting a Vivado run)
The user's log: `/Users/sk/work/bob/bob_full_v1/runme.log` (copied from
`bob_vivado\bob.runs\impl_1\runme.log`).

| gce gap / XDC sysclk multicycle | WNS after placement | TNS |
|---|---|---|
| 512 cycles (4096 ns; M16–M20) | −133 ns | −144,700 ns |
| 1024 cycles (8192 ns; commit `702842b`) | **−290 ns** | −13,400 ns |

- **What failed:** every failing net was fabric (`u_fabric/r<node>` routing wires, LUT trees,
  element flip-flops, DSP input registers; flattening renames many into `u_store/...`), and
  phys_opt ground on for hours recovering picoseconds.
- **Diagnosis:** Vivado times the **unconfigured** fabric: every mux open, a mesh of loops cut
  wherever the timer likes. The surviving chain grew from ~4.2 µs to ~8.5 µs when the budget
  doubled, so no gap closes it.

**Fix (a), implemented on `m21`:** PLAN §8's case analysis, done in software.
1. XDC: sysclk → sysclk multicycle **16384 / 16383** (131 µs; `XDC_SYSCLK_MULTICYCLE` in
   `device.py`, `clock.xdc_multicycle` in device.json). That is past any simple path through
   the ~4800 fabric muxes (IPIN 1488 + EIN 1176 + CHAN 2120). The one-cycle cell exceptions on
   `u_clk` / `u_bram_jtag` are unchanged. A multicycle, not a false path, so those still win
   (UG903).
2. Gap back to **512** (`GCE_MIN_GAP_SHIFT` = `DIV_MIN_SHIFT` = 9). Commit `702842b`'s shift
   is reverted; its generic test edits (`B.DIV_MIN_SHIFT` in test_flow, rate_scale) stay.
3. **The contract:** `timing.spacing(word)` (clk_gap, the floor, or 512 when 0),
   `timing.contract(t, word)`, `timing.check_contract(word)`. The flow's timing stage fails any
   build that breaks it: stepped, free-running, timed or not; no `.bit` is written.
   `cli.load` / `cli.load_partial` refuse before sending anything, and so does `./bob load`
   before opening the probe. That covers studio **Program** and the board checks that load a
   `.bit`. A combinational loop is refused too.
   **One exception:** hwtest's `clock-margin` sweep runs atspeed faster than its computed
   clock on purpose (that is how the guard band is proven on silicon). It passes
   `cli.load(..., over_clock=period < gap)`, which still refuses loops.
   `tests/test_layout.py` allows `over_clock=` in that one place only. (The full pytest run
   found this: the sweep's first load past the gap was refused.)
4. Tests: `tests/test_timing.py` checks the spacing, the contract and a loop; `cli.load` and
   `load_partial` refuse (frames and chain); the flow refuses a stepped build and `--hz auto`
   rescues it; and **every hand design in `designs.py`** keeps the contract (the board checks
   load those through `cfgplane` directly). `tests/test_layout.py` holds the XDC to device.py
   (≥ the gap, hold = setup − 1) and requires flow.py and cli.py to call the contract.
   Mutation-tested by hand: dropping the call in `cli.load` or `flow.py`, or changing the
   XDC number, each fails the suite.
5. Docs: the XDC comment, `docs/hwtest/M21.md` (what the timing summary should show, when to
   stop a run), PLAN M21 section and status row, REUSE, GUIDE, bitstream-format §rules, the arch
   page's timing card (`xdc_mc`), and the README device table (generated).

**Second rebuild (2026-09-23 15:58): WNS −228 ns after placement; it finished at 18:07 with a
bitstream** (`bob_full_v1/docs/reports/M21/`: `timing.rpt`, `util.rpt`, `bob_top.bit`).
- **sysclk met: WNS +0.868 ns, WHS +0.119 ns.** The sysclk fix worked.
- **TCK failed: WNS −463 ns, 66 endpoints.** Worst path: `u_tap/ir_reg[2]` (updated on the
  falling edge) → 6349 logic levels of empty fabric and DSP → `u_dsp_jtag/sr_reg[91]`,
  5463 ns against the 5000 ns fall → rise half period.
- **Utilization:** 36,450 LUTs (68.5%, as estimated), 36,308 FFs, 3 BRAM tiles, 2 DSPs.

M7 missed TCK the same way (−657 ns). M7 missed TCK the same way (−657 ns). So the earlier diagnosis that the
path "grows with the budget" was probably wrong: −133 / −290 / −228 ns look like this one
TCK path, moving with placement.
- **Fix:** TCK → TCK multicycle 16/15 (`XDC_TCK_MULTICYCLE`, `tests/test_layout.py`). Hold
  stays at the same edge.
- **`hw/scripts/place_report.tcl`** (place_design TCL.POST): prints `place_report: <clock>
  WNS ...` for sysclk and tck, with the worst path's endpoints, and writes
  `impl_1/bob_top_timing_placed.rpt`. The next failure will name its clock after about
  15 min instead of hours.

**Third build (2026-09-23 21:31, with the TCK multicycle): timing CLOSED.**
`bob_full_v1/docs/reports/M21/` (untracked, as the user copied it): `timing.rpt`, `util.rpt`,
`bob_top.bit`. sysclk WNS **+0.570 ns**, WHS +0.064 ns; tck WNS +4990.6 ns; 0 failing
endpoints. The board test (`make hwtest M=M21`) passed **66/66** on the second build's
bitstream (same RTL, the one before the TCK multicycle; `docs/hwtest/results.log` in the m21
worktree, 2026-09-23 20:22): bob-fir passes, clock-margin 4.50x on silicon.
- **Still missing from the report folder:** `sysclk_1cycle.txt` (tests/test_reports.py
  requires it for every M13+ build), `delay_paths.rpt` (for `delays.py fold`), and the DRC
  report. Copy the **whole** `bob_vivado\out\M21\` folder, then commit it and fold the delays.
- `m21` is merged into `main` (the board now runs M21). **Not tagged `m21` yet:** the final
  bitstream (third build) has not run `make hwtest M=M21`; its RTL is the tested one, only
  the XDC differs. Rerun it (or decide the second build's pass counts), then tag.

**What was unproven before the third build:** only Vivado can show that implementation now closes. Expect
sysclk WNS ≥ 0 with the fabric far inside 16384 cycles, and the one-cycle `u_clk` /
`u_bram_jtag` paths as the tight ones. If phys_opt still logs WNS in the hundreds of ns after
half an hour, stop the run. The fallback is (b): `set_case_analysis 0` on the configuration
flip-flops. That is 32,896 pins, flattening renames them, and the XDC must stay plain.

### Then
1. The user rebuilds with this `hw/` (it closes timing: IDCODE `0x0B021093`). Copy `out/M21/` to
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
| In flight | **M21: software done and simulated, in the worktree `../bob_full_v1_m21` (branch `m21`); the first Vivado build missed on fabric paths; the timing-contract fix is in, and the rebuild (IDCODE `0x0B021093`) and `make hwtest M=M21` are pending.** `main` (this project's folder) keeps the M20 tools for the M20 bitstream on the board. M18–M20 on the board 2026-09-23: 57/58, `bob-fir` failed (the autostep race) and the build had WNS −0.919 ns; both are fixed in M21's RTL (§1d). Whether to tag `m18`–`m20` with that known issue or rebuild M20 is the user's decision |

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
- **Timing contract:** the XDC's sysclk multicycle is 16384 (it no longer times the empty
  fabric), the gap is 512 again, and `timing.contract()` refuses any build or load whose
  critical path × guard band exceeds its gce spacing (§0). The gap was 1024 for one failed
  build (commit `702842b`, WNS −290 ns).
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
