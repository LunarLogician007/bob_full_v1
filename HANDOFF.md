# Handoff — bob_full_v1, 2026-09-22

**Read `CLAUDE.md` first (the rules), then `PLAN.md` §2 (status) and §3 (how the user wants this done).**
This file is the live state: what is finished, what is in flight, and exactly what to do next.

---

## 1. Where the project stands

| | |
|---|---|
| Milestones M0–M16 | **all passed on the PYNQ-Z2** |
| Bitstream in the PL | **M16** (`0xFBEEF093`): 100 CLBs (12 × 10 core), 145 frames = 18 560 bits, 2 BRAM, 2 DSP, 44 pads. 20 498 LUTs (38.5%), 21 511 FFs (20.2%), WNS +0.667 ns, WHS +0.112 ns, DRC clean |
| Guest tooling | `./bob build｜load｜info｜fasm`, and **bob studio** (`software/host/studio.py`), which since M18 has **projects** (`.bobproj`) and **block designs** |
| Whole-project report | `docs/project/REPORT.md` + `project.html`; the learning guide is `docs/project/GUIDE.md` + `guide.html` (**done**, committed in `807f2b9`) |
| In flight | **M20: software done; the Vivado build (IDCODE `0x0B020093`) and `make hwtest M=M20` are pending.** M20's list runs M18's and M19's checks too, so one board session closes all three. After the build: copy `out/M20/` to `docs/reports/M20/`, run `software/bob/delays.py fold docs/reports/M20/delay_paths.rpt`, `make check`, then the board. Checklists `docs/hwtest/M18.md`, `M19.md`, `M20.md`. Tag `m18`/`m19`/`m20` only after they pass |

The device table in `README.md` is generated from `software/bob/device.json` by
`software/bob/devtable.py`; `make check` fails if it drifts.

---

## 1c. M20 — the user clock from the design's own timing

- **Hardware:** `clock_ctrl.v` has `clk_period` and `clk_gap` (ctrl tile 8 → 40 bits; the chain
  is still 18,560 bits in 145 frames). `clk_gap` = 0 is the safe 512, so the XDC is unchanged.
  `tb_clock_gap` has 17 checks (period, gap,
  prescale, floor, safe default, steps at a gap), and `sim/mutate_frames.sh` has 4 new mutants.
- **Timing:** `software/bob/timing.py` (the design's critical path from its bits) and a new flow
  stage **timing** between bits and model. `./bob build --hz auto|N`; the studio's `hz` setting;
  projects store `hz` (`div` = before).
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
