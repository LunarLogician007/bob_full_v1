# M22: LUT contents in CFGLUT5 (ZUMA-style) and a 9 x 9 CLB grid

Approved by the user on 2026-09-23 (approach B, 9 x 9, measure first).

## Why

M21 (7 x 7 CLBs, 196 LUTs) filled 90.9% of the XC7Z020's slices: 36.4k LUTs and 36.3k FFs,
of which 32.9k are configuration flip-flops. Measured in yosys, one M21 CLB is 469 host
LUTs + 424 configuration FFs. The same CLB with its element LUTs and crossbar muxes in
AMD CFGLUT5 primitives (a LUT5 whose truth table is shifted in, UG953) is 193 LUTs (152 of
them CFGLUT5, SLICEM only) + 48 FFs: 2.4x fewer LUTs, 376 fewer FFs.

The binding resource then becomes SLICEM (17,400 LUTs): 81 CLBs x 152 = 12.3k (71%).
9 x 9 = 81 CLBs = 324 guest LUTs (1.65x M21). Routing muxes stay flip-flop configured (in
LUTRAM they would cap the fabric at ~48 CLBs).

## What stays

- The bitstream: frames, the chain, CRC, FAR, partial reconfiguration, BRAM content frames,
  FASM features, model.py semantics. Selects stay compact (5 bits), not truth tables.
- Readback: from the M21 BRAM shadow, which already holds exactly the frames written.
- CAPTURE, the clock controller, the timing contract.

## Design

### Layout (software/bob/device.py)
- A CLB tile starts on a frame boundary (the column is padded before it) and is:
  1. INIT frames: the N element truth tables, 2^K bits each, FB / 2^K per frame
  2. crossbar frames: the N*K crossbar selects, xw bits each, floor(FB / xw) per frame
  3. the element flags (N x 12 bits), then the tile's routing muxes as before
- "L-frames" = 1 + 2: their bits live only in CFGLUT5s. device.json lists them
  (`lframes`), bob_params.vh carries `BOB_LFRAME_MASK`.
- ARCH_M22: nx 11, ny 9 (CLB columns 1,2,4..7,9..11), BRAM x=3 and DSP x=8, height 3
  (3 of each), W = 40 (re-checked by VPR on every example).

### Hardware
- `ble.sv`: the LUT is two CFGLUT5 (lo = INIT[2^(K-1)-1:0], hi = the upper half, both over
  i[K-2:0]); O6 = (i[K-1] | frac) ? hi : lo (MUXF7), O5 = lo. Flags from flip-flops.
- crossbar: each element input is a CFGLUT5 tree: ceil(S/5) leaves + 1 root (S <= 25
  sources); const0 = all-zero contents, const1 = an all-ones root.
- `cfg_store.v`: no flip-flops for L-frames (LMASK); exposes each frame write (index +
  buffer) to the loader.
- `lut_loader.v` (TCK): on the falling edge that writes a frame, copy the 128-bit buffer and
  index, then 32 TCK cycles of shifting (CE = busy and this CLB owns the frame). JPROGRAM:
  a 32-cycle sweep of zeros into every CFGLUT5 (a dark, loop-free fabric). JSTART ticks are
  held while busy. A frame arrives every >= 128 TCK, so a load always finishes first.
- `bob_lexp` (generated in bob_fabric.v): the shared expanders. CDI nets are functions of the
  loader's buffer and counter only, so every CLB shares them; the CE picks the CLB.
- Clocks: CFGLUT5 CLK = TCK. Their contents are TCK state read combinationally by sysclk
  logic, like the configuration flip-flops before them (async groups, TCK multicycle).

### Software
- bitstream.py: element fields through the CLB's field table (no contiguous element).
- rr graph + every committed VPR route regenerated for the 9 x 9 grid.
- delay samples regenerated; the crossbar delay stays provisional until the M22 build.

### Tests
- tb_clb loads every configuration through bob_lexp + CFGLUT5 shifting (the chip's path).
- tb_bob / tb_frames / cosim unchanged in method: they load over JTAG, so the loader runs.
- new pytest: layout invariants (tile alignment, L-frame contents, no field straddles).
- sim: JPROGRAM darkness, partial rewrite of one element's INIT frame keeps its neighbours.
- mutants: loader count, shift order, clear sweep, LMASK.
- hwtest M22: the full M21 list on the new fabric plus lutram checks.

## Risks
- SLICEM packing: CFGLUT5s in one slice share CLK and CE; every CE group is a multiple of 4.
- Vivado: CFGLUT5 on the TCK clock net (12.3k loads) - TCK is on a BUFG.
- The model's LUT/FF counts are yosys-based; the whole-design estimate runs before hand-off.
