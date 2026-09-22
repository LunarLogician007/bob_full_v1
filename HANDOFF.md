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
| In flight | **M18: software done, `make hwtest M=M18` pending** (no Vivado rebuild; checklist `docs/hwtest/M18.md`). Tag `m18` only after it passes |

The device table in `README.md` is generated from `software/bob/device.json` by
`software/bob/devtable.py`; `make check` fails if it drifts.

---

## 1a. M18 — projects and block designs in bob studio

- `software/bob/project.py`: New/Open Project, a folder anywhere on disk (`<name>.bobproj`,
  `src/ bd/ ip/ constrs/ build/`), sources, top, the active `.pcf`, settings, recent list
  (`~/.bob/recent.json`). `project.flow_kwargs()` is what `flow.Flow` takes;
  `./bob build --project x.bobproj` reads it too.
- `software/bob/bd.py` + `software/bob/ip/` (14 cores): block designs. `check()` returns an
  error at each endpoint; `generate()` writes `bd/<name>_wrapper.v` (ports `clk sw btn led`
  plus pads) and `constrs/<name>.pcf` when a pad is used, copies the IP into `ip/`.
- Studio: Project Manager and Block Design tabs (`docs/studio/p10_project.js`, `p11_bd.js`),
  routes under `/api/project/*`, `/api/bd*`, `/api/fs`, `/api/ports`. The path guard
  allows the repo **or** the open project.
- `work/examples/bd_demo/` (committed VPR route `software/bob/vpr/bd_demo_bd_wrapper/`),
  board checks `bob-bd_demo`, `pnr-bd_demo`, `live-bd_demo` in `MILESTONE["M18"]`.
- Worth knowing: the first spare pad is taken by `clk` (`vpr_run.write_eblif`); the Pin
  Planner does not know that, `bd.py` does. A new project defaults to `pnr vpr`, which needs
  Docker until its route is committed; `python` needs nothing.
- Not yet exercised by hand in a browser (the page's logic was run headless in
  JavaScriptCore, and every route is covered by `tests/test_studio.py`). The manual steps in
  `docs/hwtest/M18.md` are the first click-through.

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
- **`docs/studio/`** builds `studio.html` the way `docs/arch/` builds `arch.html`: one
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
python3 docs/studio/build.py                         # studio.html
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
