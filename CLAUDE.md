# bob_full_v1: rules for agents

**Read `HANDOFF.md` first** (live state and the next steps), then `PLAN.md`. It has the status table, folder structure, commands, conventions, gotchas and every milestone in detail. `arch.html` is the interactive picture of the fabric and the guest flow; `docs/project/GUIDE.md` + `guide.html` explain every part (what/why/how to use/how to tweak) and compare bob with OpenFPGA and Aegis; `docs/project/REPORT.md` + `project.html` are the project report. Rebuild both pages with `python3 docs/project/collect.py && python3 docs/project/build.py`.

Where it stands (2026-09-24): **M0–M23 passed on the board.** The board runs M23: 10 × 10 = 100 CLBs (400 LUTs), each element's LUT contents and crossbar leaves in CFGLUT5 with plain OR roots, routing muxes from LUT6/MUXF7/MUXF8, IDCODE `0x0B023093` (WNS +0.048 ns, slices 88%, SLICEM 92.6%: 10 × 10 is this CLB's ceiling on the XC7Z020). Never use a CFGLUT5's O5: Vivado makes it two LUT sites. Vivado cannot time the unconfigured fabric, so the XDC relaxes its sysclk and TCK paths and `software/bob/timing.py`'s `contract()` refuses any build or load whose own critical path does not fit its clock. New milestones go in their own git worktree; never check milestone work-in-progress out in this folder while the board runs the previous milestone.

Earlier: **M0–M16 all passed on the PYNQ-Z2.** M16 is the 10 × 10 grid (100 CLBs, 145 frames, 18 560 bits, IDCODE `0xFBEEF093`): 20 498 LUTs (38.5%), 21 511 FFs, WNS +0.667 ns. Since M16 there is **bob studio** (`./bob studio --probe fake`, a desktop app since M19; the page is in `software/studio/`), an EDA tool over the same flow; its engine is `software/bob/flow.py` and it can drive the board in software (`software/host/fakeboard.py`). The device table in the documents is generated (`software/bob/devtable.py`), not typed.

Vivado synthesis must run without the XDC (`build.tcl`) and with no `keep_hierarchy`: both crashed it in timing-loop breaking. Before a hand-off compare `software/bob/synth_estimate.sh $PWD $PWD/build/est` with the last build. Whole-project report: `docs/project/REPORT.md`, `project.html` (rebuild with `docs/project/collect.py` + `build.py`).

The short version:
- This is an FPGA fabric ("bob") running inside a PYNQ-Z2 (XC7Z020), configured over JTAG from a Pico (DirtyJTAG). `/Users/sk/work/bob/` is the frozen original; work only here.
- **One milestone at a time.** Run its checks, show the results, then **stop and wait** for the user's go-ahead.
- **Every milestone ends with a hardware test** on the PYNQ-Z2: `make hwtest M=Mx` (interactive; `ONLY=check` reruns one), with a checklist in `docs/hwtest/Mx.md`. Anything the user does by hand needs a guide: what to press and what the LEDs must show, and time to do it.
- **Every Vivado build is the complete FPGA plus the new feature**, never a standalone block. The hardware test runs the full regression plus the new checks.
- Base designs on AMD UG470/473/474/479 and OpenFPGA/VPR, and say so where you diverge. Reuse existing verified code.
- Configuration has **two paths** from M13: UG470-style frames (default, `bob load`; partial reconfiguration `--partial` from M14; BRAM contents as frames from M15) and the scan chain (`--mode chain`, BRAM contents over USER4); keep both working.
- Vivado runs on the user's Windows machine. Everything it needs lives in `hw/`. The user replaces `E:\bob_full_v1\hw` and runs `build.tcl`, which reuses the project in `E:\bob_full_v1\bob_vivado` (never delete it).
- New RTL goes into `hw/sources.f`. Architecture numbers live only in `software/bob/device.py` (`make device`; `make rrgraph` for VPR arch changes, then `make vpr`). The XDC must be plain XDC with no Tcl.
- Guest flow: `./bob build design.v` → `./bob load x.bit`. VPR results and rr graphs are committed with stamps; Docker (Colima) is only needed to rebuild them (`make rrgraph`, `make vpr`).
- Hardware checks get a passing and a failing case against the stand-in board in `tests/test_hwtest_fake.py` before they go to the board. Check that stimulus actually exercises what it claims (the M8 counter trace was all zeros).
- Before any hand-off, `make check` must be green. Update `REUSE.md`, `README.md`, the status table in `PLAN.md` and, when the architecture or flow changes, `docs/arch/` (`python3 docs/arch/build.py`).
- Git: commit as you go; never commit `docs/bob_full_v1_report.tex` (the user's). Tag `mN` only after milestone N passes on the board.
