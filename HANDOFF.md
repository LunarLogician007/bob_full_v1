# Handoff — bob_full_v1, 2026-09-18

**Read `CLAUDE.md` first (the rules), then `PLAN.md` §2 (status) and §3 (how the user wants this done).**
This file is the live state: what is finished, what is in flight, and exactly what to do next.

---

## 1. Where the project stands

| | |
|---|---|
| Milestones M0–M15 | **all passed on the PYNQ-Z2**, git tags `m7`…`m15` |
| Bitstream in the PL | **M15** (`0xEBEEF093`): 36 CLBs, frames + partial reconfiguration + BRAM content frames, chain kept. 48/48 on the board, WNS +0.585 ns, 10 411 LUT / 11 097 FF |
| Whole-project report | `docs/project/REPORT.md` + `project.html` (built by `docs/project/collect.py` then `build.py`) |
| In flight | **M16: the 10 × 10 CLB grid** (user request, 2026-09-18) — RTL and tools done, `make check` running, not yet handed to Vivado |
| Also requested, not started | a **learning-oriented guide** (what each part is, why, how to use, how to tweak) as Markdown **and** an `arch.html`-style page, including an honest comparison with OpenFPGA / Aegis |

The user's latest message: *"for now polish for sharing … very detailed report, from all the parts, what is that, why is that used, how to use, how to tweak stuff … proper html like arch.html … how is our model better than openFPGA or aegis or not, also for now expand to 10x10 CLBs first."*

So: **finish M16 first** (it ends, as always, with a board test), then write the guide.

---

## 2. M16 — the 10 × 10 CLB grid

### What is already done (uncommitted working tree)

- **`tools/bob/device.py`:** new profile `ARCH_12X10` and `ARCH = ARCH_12X10`.
  - 12 × 10 core (VPR grid 14 × 12), BRAM column x = 3 and DSP column x = 8, both height 5.
  - **100 CLBs**, 2 BRAMs, 2 DSPs, 44 pads, W = 24, 3391 routing muxes.
  - **18 560 configuration bits = 145 frames** (was 8320 = 65).
- **rr graphs rebuilt** (`make rrgraph`, Docker/Colima) and committed files updated: `tools/bob/arch/bob_k{6,4}*`.
- **Generated RTL refreshed** (`make device`): `hw/src/generated/bob_fabric.v` is now 4416 lines.
- **Every example re-routed** by VPR (`make vpr`, 29 PASS) — all 10 designs route on the bigger graph.
- **Testbench fixes for the larger widths** (these were real bugs, not just resizes):
  - `hw/tb/tb_bob.v`: CAPTURE is 100 bits now, so the "CAPTURE == model" check compares `rx[NCLB-1:0] === SHOW_CAP_11` instead of 64-bit values; `c8`/`c8_0` are plain 32-bit registers.
    **Gotcha:** `` `CNT8_BITS `` was used at line ~97 but `vectors.vh` is `include`d at line ~128. iverilog did not error; the register silently came out 2 bits wide and 298 checks failed. Never use a vector macro above its include.
  - `sim/gen_vectors.py`: `CNT8_MASK` now carries the real width (`10'h3ff`), not a fixed `8'h`.
  - `sim/gen_frame_vectors.py` + `hw/tb/tb_frames.v`: stream vector `SW` 16384 → **40960** bits (a 145-frame load stream is ~19 k bits). Both must match.
- **Simulations that have already passed on the new grid:** `tb_bob` 852, `tb_frames` 71, `tb_clock_gap` 11, `tb_clb`/`tb_bram`/`tb_dsp`, K = 4 722, `tb_synth` 972.

### Measured size (the no-crash gate)

`tools/bob/synth_estimate.sh` (whole design, yosys, same method for both):

| | LUT | FF | yosys time | yosys peak |
|---|---|---|---|---|
| M15 (36 CLBs, built by Vivado in 5.1 min at 2.0 GB → 10 411 LUT / 11 097 FF) | 15 941 | 11 069 | 152 s | 1.36 GB |
| **M16 (100 CLBs)** | **32 891** | **21 485** | 281 s | 2.07 GB |

Scaling by M15's yosys→Vivado ratio (0.65 for LUTs, ~1.0 for FFs): expect roughly **21 k LUTs (≈40% of the XC7Z020) and ~21.5 k FFs (≈20%)**. It fits, but Vivado synthesis will take clearly longer than M15's 5 minutes, and the loop-breaking phase grows with the routing muxes (1723 → 3391).

**Tell the user these numbers before the build**, and offer the fallback: an 8 × 8 core (64 CLBs) is roughly half the growth if the machine struggles. The Windows PC restarted once under load at M13, so this matters.

### What is left for M16, in order

1. **Wait for `make check`** (running in the background when this file was written; log `build/m16_check.log`). Co-simulation with 100 CLBs is slow — several minutes. Fix whatever it reports.
   - Expect failures in `tests/test_device.py` (`test_sizes` pins 8320 / 6016 and the block counts) — update the pinned numbers to 18560 / K=4's value, `(14, 12, 24)` and `{"io": 44, "clb": 100, "bram": 2, "dsp": 2}`.
   - `tests/test_pnr.py::test_too_many_clbs_is_refused` already derives the count from `B.NCLB`, so it should hold.
2. **`make pnr`** — regenerate `docs/reports/M12b/pnr_vs_vpr.md` on the new graph (it is per-milestone; consider `docs/reports/M16/`).
3. **`make mutate`** — all three suites. `sim/mutate_fabric.sh`'s `carry-direct-cut` cuts the carry of the **last CLB column** (`clb_x8y3` today); on a 12-column grid that column is `clb_x12y3`. Retarget it or the mutant survives (this exact trap already happened once at M12b).
4. **`hw/build.cfg`:** `tag = M16`, `idcode = FBEEF093`, `usercode = 00000010`. `0xF` is the last free IDCODE nibble (`PLAN.md` §7) — say so and decide with the user what the numbering does next.
5. **Docs:** `docs/hwtest/M16.md` (checklist, in the shape of `M15.md`), `PLAN.md` status row + an "as built" section, `README.md` device table, `REUSE.md`, `CLAUDE.md` one-liner, `docs/bitstream-format.md` §4 (the width list), `docs/arch/` + `python3 docs/arch/build.py`.
6. **`host/hwtest.py`:** `MILESTONE["M16"]` = M15's list (everything still applies) plus at least one check that only the bigger grid can run. Suggestion: an example that needs > 36 CLBs (extend `examples/wide.v` or add one), and a `frames-load` variant that proves all 145 frames load. Add passing **and** failing cases to `tests/test_hwtest_fake.py` first.
7. **Hand off to Vivado:** `make check` green → `make hw` → the user replaces `E:\bob_full_v1\hw`, runs `build.tcl`, copies `bob_vivado\out\M16\` back to `docs/reports/M16/`, then `make check` and `make hwtest M=M16`.
8. **After it passes:** commit, tag `m16`, update the status tables, rerun `docs/project/collect.py` + `build.py` so the report and `project.html` include M16.

### Build rules that must not be broken (each cost a crashed Vivado)

- No computed part-select over the configuration memory — decode per frame (`cfg_store.v`).
- No `keep_hierarchy` anywhere in `bob_fpga.v`.
- The XDC is **implementation-only** (`build.tcl` sets `USED_IN_SYNTHESIS false`).
- Compare `tools/bob/synth_estimate.sh` against the last successful build before every hand-off.
- Plain XDC only (no Tcl), and architecture numbers live only in `device.py`.

---

## 3. The guide the user asked for (not started)

**Goal:** something a person can learn the whole project from. For **every part**: what it is, why it is built that way, how to use it, how to tweak it, where its code and tests are.

Suggested shape (keep the existing pattern: Markdown as the source, HTML built from it):

- **`docs/project/GUIDE.md`** — the text. One section per part, each with the same four headings (*What it is · Why this way · How to use it · How to tweak it*), plus:
  - orientation for a newcomer (guest vs host FPGA, the five layers, vocabulary: rr graph, mux, FASM, frame, chain, BLE, pack/place/route)
  - a **cookbook**: change the LUT size K, change the grid, change the channel width, add an example, add a configuration field, add a JTAG instruction, add a board check, change the user clock, run a partial reconfiguration, debug a failing load (CRC error, DONE not rising, readback mismatch, VPR unroutable, Vivado crash)
  - **comparison with OpenFPGA, Aegis, ZUMA, prjxray/F4PGA** — honest, not boastful. Facts to build on:
    - *OpenFPGA* (LNIS): architecture description → Verilog + SPICE + bitstream + VTR flow, many architectures, ASIC-oriented, far larger scope and maturity than bob; bob borrows its tileable rr-graph method, its `k6_frac_N10…` reference architecture and its `scan_chain`/`frame_based` protocols.
    - *Aegis* (`/Users/sk/work/aegis/docs/arch/*.md`, read-only, Apache-2.0): a parameterised FPGA fabric generator in Dart/ROHD producing SystemVerilog for a whole device (clock tiles, I/O + SerDes, LUT/BRAM/DSP grid), configured by one scan chain through every tile. bob took its shift + shadow register idea and its I/O and clock notes.
    - Where bob is genuinely different: every milestone is proven on real hardware; one device description generates RTL, VPR architecture, models, FASM map and host tools; two configuration paths (UG470-style frames **and** a chain) on one memory; partial reconfiguration that provably keeps state; golden co-simulation and mutation testing; a stand-in board so hardware checks are tested before the board sees them; one command each way (`./bob build`, `./bob load`).
    - Where it is not: one small fabric on one board, 1 BLE per CLB, no timing-driven PnR, no ASIC flow, no SPICE/area models, no multi-clock designs, K and W fixed per build, far less coverage of architectures and devices than OpenFPGA.
- **`guide.html`** — same look as `arch.html`/`project.html`. Extend `docs/project/build.py` (it already converts Markdown and extracts tables) to build a second page from `GUIDE.md` with its own template: a parts explorer (click a part → what / why / use / tweak), the cookbook as steppers, and the comparison as a table with per-row notes.
- Verify the page the way `project.html` was verified: build it, then load it in WebKit and check for script errors and layout (the Swift snapshot tool used for that lives in the session scratchpad; re-create it if needed — it is ~50 lines using `WKWebView.takeSnapshot`).

---

## 4. Everyday commands

```sh
make check            # device files + every simulation + lint + pytest (green before any hand-off)
make rrgraph          # after an architecture change in device.py (Docker/Colima), then make device
make vpr              # re-route every example (Docker)
make pnr              # bob's PnR vs VPR report
make mutate           # the three mutation suites
make hwtest M=M16     # board test (interactive); ONLY=<check> reruns one
tools/bob/synth_estimate.sh $PWD $PWD/build/est      # whole-design yosys estimate before a Vivado hand-off
python3 docs/project/collect.py && python3 docs/project/build.py   # report data + project.html
python3 docs/arch/build.py --data                    # arch.html (--data after make device)
```

Docker for VPR: `colima start`, then `DOCKER_HOST=unix://$HOME/.colima/default/docker.sock` (the scripts set it).

---

## 5. Working agreements (from CLAUDE.md, worth repeating)

- One milestone at a time; show results and **stop for the user's go-ahead**.
- Every milestone ends with a PYNQ-Z2 test; simulation alone never closes one.
- Every Vivado build is the complete FPGA plus the new feature.
- Keep both configuration paths working (frames and chain).
- Anything the user does by hand needs a guide: what to press, what the LEDs must show, and time to do it.
- Git: commit as you go; **never** commit `docs/bob_full_v1_report.tex` (the user's file); tag `mN` only after milestone N passes on the board.
