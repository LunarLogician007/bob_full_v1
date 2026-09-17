# bob_full_v1: rules for agents

**Read `HANDOFF.md` first** (live state and the next steps), then `PLAN.md`. It has the status table, folder structure, commands, conventions, gotchas and every milestone in detail. `arch.html` is the interactive picture of the fabric and the guest flow.

Where it stands: M0–M15 all passed on the PYNQ-Z2; **M16 (10 × 10 CLBs) is in progress**, see `HANDOFF.md`.

Where M15 stands: M0–M15 all passed on the PYNQ-Z2 (git tags `m7`…`m15`); the board runs the M15 bitstream (IDCODE `0xEBEEF093`, 36 CLBs, frames + partial reconfiguration + BRAM content frames, chain kept). Vivado synthesis must run without the XDC (`build.tcl`) and with no `keep_hierarchy`: both crashed it in timing-loop breaking. Before a hand-off compare `tools/bob/synth_estimate.sh $PWD $PWD/build/est` with the last build. Whole-project report: `docs/project/REPORT.md`, `project.html` (rebuild with `docs/project/collect.py` + `build.py`).

The short version:
- This is an FPGA fabric ("bob") running inside a PYNQ-Z2 (XC7Z020), configured over JTAG from a Pico (DirtyJTAG). `/Users/sk/work/bob/` is the frozen original; work only here.
- **One milestone at a time.** Run its checks, show the results, then **stop and wait** for the user's go-ahead.
- **Every milestone ends with a hardware test** on the PYNQ-Z2: `make hwtest M=Mx` (interactive; `ONLY=check` reruns one), with a checklist in `docs/hwtest/Mx.md`. Anything the user does by hand needs a guide: what to press and what the LEDs must show, and time to do it.
- **Every Vivado build is the complete FPGA plus the new feature**, never a standalone block. The hardware test runs the full regression plus the new checks.
- Base designs on AMD UG470/473/474/479 and OpenFPGA/VPR, and say so where you diverge. Reuse existing verified code.
- Configuration has **two paths** from M13: UG470-style frames (default, `bob load`; partial reconfiguration `--partial` from M14; BRAM contents as frames from M15) and the scan chain (`--mode chain`, BRAM contents over USER4); keep both working.
- Vivado runs on the user's Windows machine. Everything it needs lives in `hw/`. The user replaces `E:\bob_full_v1\hw` and runs `build.tcl`, which reuses the project in `E:\bob_full_v1\bob_vivado` (never delete it).
- New RTL goes into `hw/sources.f`. Architecture numbers live only in `tools/bob/device.py` (`make device`; `make rrgraph` for VPR arch changes, then `make vpr`). The XDC must be plain XDC with no Tcl.
- Guest flow: `./bob build design.v` → `./bob load x.bit`. VPR results and rr graphs are committed with stamps; Docker (Colima) is only needed to rebuild them (`make rrgraph`, `make vpr`).
- Hardware checks get a passing and a failing case against the stand-in board in `tests/test_hwtest_fake.py` before they go to the board. Check that stimulus actually exercises what it claims (the M8 counter trace was all zeros).
- Before any hand-off, `make check` must be green. Update `REUSE.md`, `README.md`, the status table in `PLAN.md` and, when the architecture or flow changes, `docs/arch/` (`python3 docs/arch/build.py`).
- Git: commit as you go; never commit `docs/bob_full_v1_report.tex` (the user's). Tag `mN` only after milestone N passes on the board.
