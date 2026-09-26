# Handoff — bob_full_v1, 2026-09-26

**Read `CLAUDE.md` first (the rules), then this file (the live state), then `PLAN.md` §2 (status).**
The whole story, milestone by milestone, is `docs/project/REPORT.md`; every part explained is
`docs/project/GUIDE.md`. This file keeps only what is true now and what to do next. Older
hand-off notes are in git history (`git log -p HANDOFF.md`).

## 1. Where it stands

- **The board runs M25**: 10 × 10 = 100 CLBs × 4 Double Duty elements = 400 LUT6, 2 BRAM,
  2 DSP, 44 pads, 532 frames = 68,096 configuration bits, IDCODE `0x0B025093`. **71/71** on the
  board 2026-09-25, and 71/71 again at TCK 1 MHz (now the default). Vivado: 38,198 LUTs (71.8%),
  slices 86.8%, sysclk WNS +0.732 ns, TCK WNS +489 ns. `main` matches the board; tags `m7`…`m25`.
- **The hardware is locked** (the user, 2026-09-25): 10 × 10 is this CLB's ceiling on the
  XC7Z020. Work since then is software and documentation only.
- **After M25, on `main`:**
  - measured routing delays: `hw/scripts/delays.tcl` (standalone, no rebuild) →
    `docs/reports/M25/delay_hops.txt`; worst routing mux 4.60 ns, input mux 4.65 ns, crossbar
    3.01 ns. LUT, carry and flip-flop stay estimated, so `delays.json` is still provisional (2×).
  - the software pass: `./bob` guide, `run`, `new`, `examples`, `pins`, `doctor`; readable
    failures (file:line, the source line, hints) from `software/bob/ux.py`; bob studio's Start
    page, Build & Program, save-before-build. `docs/GETTING_STARTED.md`.
  - `docs/learn/`: four animated volumes (bit by bit, layer by layer, frame by frame, tool by
    tool), each built by its `gen.py` from the chip's own data, published as claude.ai artifacts
    (links in the pages' side rails).
  - `docs/presentation/slides.tex`: the Beamer slides for the professor (not compiled here).
  - the tree was cleaned 2026-09-26 (260 MB of build products; `release/`, old bitstreams,
    `docs/manim/`, superseded notes). All in git history; `git checkout m25 -- release/`.
  - **the whole-repo review** (2026-09-26): `docs/research/2026-09-26-review.md`: verified
    findings (thin connection boxes, VPR on 40 nm delays, sampled delays, the USB-bound
    link, clock mode 0 at 1 MHz, the studio's open local API), the architecture against real
    FPGAs, and what the silicon phase changes. Docs fixed in the same pass: volume 1 is now
    generated from `device.json` (`docs/learn/parts/gen.py`; it described M21), volume 2 has
    chapter 13 *Onto its own silicon*, volume 3 and GUIDE §3.11 no longer call bob's startup
    "UG470's order", `arch.html` shows 100 CLBs (it drew M22's 81), `bitstream-format.md` §11
    says TCK ≤ 1 MHz, and `docs/project/build.py` renders `**`code`**`.
  - **the fix pass** (2026-09-26, software only; the review's "Status" table): VPR runs on bob's
    measured delays (`device.py` `VPR_DELAYS_NS`; fabric byte-identical, examples re-routed);
    sparse full loads after JPROGRAM (`tb_frames` [20]); the Pico link batched per packet, one
    edge per round trip while TCK steps the user clock; bob studio's API behind a token and
    Host/Origin checks; `make check`'s banner at its end; `fcsweep.py` and
    `docs/research/2026-09-26-fc-sweep.md` for the next hardware milestone.

## 2. Waiting on the user

- **The board run of the fix pass:** `make hwtest M=M25` on the M25 bitstream. The USB link
  (`dirtyjtag.py`) and the load stream (sparse) changed; everything was checked against the
  firmware's command handler ported to Python (`tests/test_dirtyjtag.py`), the RTL and the
  stand-in board, never the Pico itself. `fast-tck` will show the speed-up.

- `docs/reports/M25/floorplan.txt` from `hw/scripts/floorplan.tcl` (read-only, run in the open
  Vivado project). Then `python3 docs/learn/frames/gen.py` turns chapter 14 of volume 3 into the
  real XC7Z020 site map; republish `docs/learn/frame_by_frame.html` (artifact
  `LrqGTKGsLe9hJQzjfBVaDg`).
- `sysclk_1cycle.txt` for M21, M23, M24, M25 (`test_reports` fails on them until copied).
- Republish volumes 1–3 to their artifacts (volume 1 `NxYMZQB9mLfusWduowi5k3`, volume 2
  `H7Sk39vinJtqpqwThZsNNK`, volume 3 `LrqGTKGsLe9hJQzjfBVaDg`): the repository copies were
  corrected on 2026-09-26 and the published pages still show the old ones.
- The hand steps in `docs/hwtest/M24.md` and `M25.md`.

## 3. Known open items

- **Delays:** LUT, carry and flip-flop samples name nets that no longer exist in the routed
  netlist (`probe_names.txt`: the element outputs' `r` nets are gone; the crossbar nets
  `u_clb_x<x>y<y>/x<e>[j]` and the `u_e<e>/q_reg` cells survive). A `delays.py plan` change to
  sample from those, then `delays.tcl` again. The three mux classes are maxima of 32–91 samples;
  every mux (`write_sdf`, or `get_net_delays` on the `r<node>` nets) would let the guard band
  drop from 2× to 1.25×. Both need Vivado.
- **Connection boxes:** at fc_in 0.10, 3 of every CLB's 16 inputs reach only 2 tracks (VPR
  hands fractional Fc out in pairs), which looks like what stopped SERV.
  `docs/research/2026-09-26-fc-sweep.md`: richer boxes cost +364 LUTs, but on the examples they
  route fir16 less often at W 36 (0-2/3 seeds against 3/3). Route SERV (a pin-limited design,
  no longer in the tree) on each variant before any hardware milestone changes the fabric.
- **The `fir` stand-in test** (`test_m11_live_goals_reached_by_a_person[fir]`) sometimes misses
  its 25 s budget; timing-sensitive, not a logic failure (it passed on the last full run).
- **Routing is bob's limit:** a SERV RISC-V trial fitted (186 LUTs) but did not route (4
  overused CLB input pins at fc_in 0.10). Any bigger-design work starts with `gridsweep.py` on
  fc_in 0.15.

## 4. Candidate next milestones (none chosen)

1. Configuration from the ARM core over AXI (loads in ms; a PYNQ notebook drives bob).
2. Scrubbing: readback CRC / frame ECC, repair a flipped bit while the design runs.
3. A built-in logic analyser into a BRAM, shown in bob studio.
4. Two designs side by side, one reloaded while the other runs.
5. Software only: the remaining delays; timing-driven placement on measured delays.

## 5. How to work here

- One milestone at a time, in its own git worktree; `main` always matches the board.
- `make check` green before a hand-off (the last full pytest: 585 passed, 3 failed only for the
  missing `sysclk_1cycle.txt`).
- Never commit `docs/bob_full_v1_report.tex` (the user's) or the user's uncopied report files
  (`docs/reports/M20/`, `docs/reports/M21/*` untracked).
- Vivado runs on the user's Windows machine from `E:\bob_full_v1\hw`; standalone scripts
  (`delays.tcl`, `floorplan.tcl`, `probe_names.tcl`) read the last build without rebuilding.
