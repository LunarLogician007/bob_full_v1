# bob_full_v1: rules for agents

**Read `PLAN.md` first.** It has the status table, folder structure, conventions, gotchas and every milestone in detail.

The short version:
- This is an FPGA fabric ("bob") running inside a PYNQ-Z2 (XC7Z020), configured over JTAG from a Pico (DirtyJTAG). `/Users/sk/work/bob/` is the frozen original; work only here.
- **One milestone at a time.** Run its checks, show the results, then **stop and wait** for the user's go-ahead.
- **Every milestone ends with a hardware test** on the PYNQ-Z2: `make hwtest M=Mx`, with a checklist in `docs/hwtest/Mx.md`.
- **Every Vivado build is the complete FPGA plus the new feature**, never a standalone block. The hardware test runs the full regression plus the new checks.
- Base designs on AMD UG470/473/474/479 and OpenFPGA/VPR, and say so where you diverge. Reuse existing verified code.
- Configuration stays a **scan chain** until M13 (frame-based last).
- Vivado runs on the user's Windows machine. Everything it needs lives in `hw/` (`sources.f`, `build.cfg`, `src/`, `tb/`, `constr/`, `scripts/build.tcl`). The user replaces `E:\bob_full_v1\hw` and runs `build.tcl`, which reuses the project in `E:\bob_full_v1\bob_vivado` (never delete it).
- New RTL goes into `hw/sources.f`. Architecture numbers live only in `tools/bob/device.py` (`make device`). The XDC must be plain XDC with no Tcl.
- Before any hand-off, `make check` must be green. Update `REUSE.md` and the status table in `PLAN.md` when a milestone closes.
