# bob configuration format: scan-chain plane (format version 2)

This is the spec shared by the RTL (`hw/src/core/jtag_tap6.v`, `cfg_ctrl.v`, `cfg_mem.v`, `cfg_tile_sr.v`, `capture_chain.v`) and the Python tools (`software/bob/chainbits.py`, `software/host/cfgplane.py`). If they disagree, this document decides, and the code is fixed.

Valid from M2 to M12. M13 replaces the chain with frames (UG470 packets); section 9 lists what changes then.

## 1. Sources

| Item | Source | Status |
|---|---|---|
| IR length 6; CFG_OUT 0x04, CFG_IN 0x05, JPROGRAM 0x0B, JSTART 0x0C, JSHUTDOWN 0x0D, USER1–4 0x02 0x03 0x22 0x23, BYPASS 0x3F | OpenOCD `tcl/fpga/xlnx/xc7.cfg` + `src/pld/virtex2.c` defaults | verified 2026-09-14 |
| USERCODE 0x08, IDCODE 0x09; IR capture DONE = bit 5, INIT_B = bit 4 | openFPGALoader `src/xilinx.cpp` | verified 2026-09-14 |
| EXTEST 0x26 (`100110`), SAMPLE 0x01 (`000001`) | XC7Z020 BSDL (bsdl.info XC7Z020/XA7Z020 entries, via search) | verified 2026-09-14 (a check against the BSDL in the Vivado install is still welcome) |
| CRC-32C, "CRC before startup", startup order GSR → GTS → GWE → DONE, JSTART clocked in Run-Test/Idle | AMD UG470 (ch. 5/6), `resourses/04-config-bitstream/CONFIG-CONTROLLER.md` | UG470 concept; bit-level definition below is ours |
| Per-tile shift register + shadow register; chain through tiles | OpenFPGA `config_protocol` `scan_chain`; Aegis `docs/arch/configuration.md` | concept |

## 2. Instruction register (6 bits)

| Code | Name | Selected DR | Width | Behaviour |
|---|---|---|---|---|
| `000001` | SAMPLE | boundary | top-specific | BC_1 cells transparent, capture pins |
| `100110` | EXTEST | boundary | top-specific | cells drive pads |
| `000111` | INTEST | boundary | top-specific | **private** (not an AMD code): cells drive the fabric inputs |
| `000010` | USER1 | control/status | 32 | `[0]` ce `[1]` sr `[2]` cin `[3]` step `[4]` autostep; capture returns `[3:0]` control + status bits above |
| `000011` | USER2 = **CFG_CTRL** | control/status | 64 | section 5 |
| `100010` | USER3 = **CAPTURE** | user-state snapshot | top-specific | section 7 |
| `000100` | **CFG_OUT** | packet output (M13) | 32 × words requested | frame / register readback, section 10 (up to M12: the chain) |
| `000101` | **CFG_IN** | packet input (M13) | any | the UG470-style packet stream, section 10 (up to M12: the chain) |
| `110100` | **CHAIN_OUT** | config chain | chain width | **private**, M13: the chain readback that was CFG_OUT (section 4); never commits |
| `110101` | **CHAIN_IN** | config chain | chain width | **private**, M13: the chain write that was CFG_IN; commits at Update-DR if length and CRC are right and GWE = 0 |
| `001000` | USERCODE | 32 | 32 | `USERCODE_VALUE` = milestone number |
| `001001` | IDCODE | 32 | 32 | selected by Test-Logic-Reset |
| `001011` | **JPROGRAM** | bypass | 1 | acts at Update-IR: section 6 |
| `001100` | **JSTART** | bypass | 1 | startup clocked in Run-Test/Idle: section 6 |
| `111111` | BYPASS | bypass | 1 | |
| anything else | BYPASS | bypass | 1 | |

A top without a boundary ring (parameter `BSR_PRESENT = 0`) treats SAMPLE/EXTEST/INTEST as BYPASS.

**Capture-IR value** (read by any IR scan, LSB first):

| bit | 5 | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|
| meaning | DONE | INIT_B (= no CRC or length error) | COMMITTED | CRC_ERR | 0 | 1 |

Bits 5 and 4 follow 7-series usage (openFPGALoader reads DONE and INIT_B there). Bits 3–2 are ours. Bits 1:0 = `01` is required by IEEE 1149.1.

## 3. Timing contract (unchanged from bob, proven on hardware)

- TMS and TDI are sampled, and the TAP state advances, on the **rising** TCK edge.
- TDO is launched on the **falling** edge. IR update, CFG_IN commit, JPROGRAM clear and the CFG_CTRL expected-CRC write happen on the **falling** edge during Update-IR/Update-DR.
- Status flags and startup phases change on the **rising** edge that leaves Update-IR/Update-DR or that is clocked in Run-Test/Idle.
- All shift registers are **LSB-first**: the first bit on TDI is bit 0.
- Test-Logic-Reset is consumed only synchronously. It selects IDCODE and **does not** touch configuration, status or startup.

## 4. The configuration chain

- **Width W** comes from the device description (`software/bob/device.json` `chain.width`). The M2 test top uses 64 = 4 tiles × 16; the fabric used 2896 at M3, 3064 at M4, 3488 at M5, 3720 at M6, **4216 from M7 on the board profile** (16 CLBs, `ARCH_6X4`; 3352 at K=4), 4992 at M13 (padded to frames), **8320 from M12b** (8×6 core, 36 CLBs, 28 pads, `ARCH_8X6`: 65 frames; 6016 = 47 at K=4), and **18 560 from M16** (12×10 core, 100 CLBs, 44 pads, `ARCH_12X10`: 145 frames; 12 800 = 100 at K=4). The frozen 48-CLB profile (`release/M7_8x8/` (git tag m25)) is 9400 (6808 at K=4).
- **M7 layout** (replaces the M4–M6 tile description below, kept for the frozen bundles). Bits come in this order:
  - the 8-bit **ctrl tile**
  - one entry per **grid location**, row-major from VPR (0,0) (x East, y North): first the fields of the block rooted there, then that location's routing muxes in ascending rr node id
  - reserved bits up to a byte boundary

  Block fields:

  | block | bits | fields |
  |---|---|---|
  | clb | 2^K + 7 | INIT, ff_en, ff_rstval, ff_ce_en, ff_sr_en, cy_en, cy_di_sel, ff_d_sel (as M4) |
  | bram | 8 | `[1:0]` wmode_a `[3:2]` wmode_b `[4]` reg_a `[5]` reg_b `[6]` jtag_a `[7]` jtag_b |
  | dsp | 16 | `[1:0]` opmode `[2]` use_d `[3]` d_sub `[9:4]` AREG BREG CREG DREG MREG PREG `[13:10]` jtag_a..jtag_d `[14]` jtag_ctrl `[15]` 0 |
  | io | 0 | — |

  **Routing muxes** are VPR's routing-resource-graph nodes with driving edges (`software/bob/arch/bob_k6_rr.xml.gz`):
  - For CHANX/CHANY, value 0 = const0 and value 1+i = the i-th driver, in ascending node id.
  - For IPIN (block input pins), 0 = const0, 1 = const1, and 2+i = the i-th driver.
  - Width = the smallest that fits; larger values read 0.
  - A CHAN mux sits at the location where its wire starts: (xlow, ylow) for INC_DIR, (xhigh, yhigh) for DEC_DIR. An IPIN mux sits at its pin's location.
  - IPINs driven only by an OPIN are VPR directs: the carry up each CLB column and dsp0.pcout → dsp1.pcin. They are wires, with no bits.
  - An all-zero chain is a dark, loop-free fabric. `device.json` `rr.muxes` lists `[node, chain_lo, width, base, inputs]` for every mux.
- **Bit order:** chain bit k is the k-th bit shifted in on TDI. From M4 the **ctrl tile comes first** (bits `[7:0]`), then fabric tiles row-major (tile (0,0) at bits `[8+TILE_W-1:8]`). Within a tile, bits are in field order (`device.json`).
- **Ctrl tile (M4), 8 bits:**

  | bit | field | meaning |
  |---|---|---|
  | 0 | `clk_mode` | 0: the fabric's user clock is one enable pulse per TCK rising edge while USER1 ce (JTAG-stepped, the pre-M4 behaviour); 1: free-running divider |
  | 5:1 | `clk_div` | free-running: one enable every 2^(clk_div+8) cycles of the 125 MHz sysclk |
  | 7:6 | reserved | 0 |

- **Fabric tile (M4), K=6:** CLB 71 (INIT 64 + 7 flags) · connection box 40 (K LUT inputs + CE + SR, 5 bits each) · switch box 80 = 191 bits. With K=4: 23 + 30 + 80 = 133.
- **Structure up to M13** (and still in the M2 test top `cfg_test_top.v`): each tile has a shift register `sr` and a shadow register `cfg`. TDI enters the MSB of the **last** tile. Each tile's `sr[0]` feeds the next-lower tile's MSB, and tile 0's `sr[0]` drives TDO. Tiles and the fabric see **only** `cfg`. Capture-DR loads every `sr` from its `cfg`; Update-DR in CFG_IN copies `sr` to `cfg` only if the count equals W and the CRC matches; otherwise nothing changes.
- **Structure from M12b** (`cfg_store.v`, the complete FPGA; the chain is on CHAIN_IN / CHAIN_OUT since M13): the memory `cfg` and **one 128-bit frame buffer**. A full-width `sr` cost W flip-flops and W LUTs (5.1k LUT / 10k FF of M13's 15.4k LUT / 12.2k FF in yosys), which is what paid for the bigger grid.
  - **Capture-DR** (either instruction): frame counter ← 0; CHAIN_OUT also loads frame 0 into the buffer.
  - **Shift-DR, CHAIN_IN:** bits enter the buffer LSB first; every 128th bit completes frame n (n = 0, 1, …), which is written to `cfg` on the next falling edge **only while GWE = 0**. Bits beyond W are ignored.
  - **Shift-DR, CHAIN_OUT:** the buffer shifts out LSB first and reloads the next frame every 128 bits, so the first W bits out are the memory, LSB first. After the last frame the buffer is a plain **128-bit delay line** from TDI. Readback never writes.
  - **Update-DR in CHAIN_IN:** COMMITTED and CRC_OK are set **only if** the count equals W **and** the CRC matches (and GWE = 0). The memory already holds the new bits either way; after a bad CRC or length COMMITTED stays 0, CRC_ERR / LEN_ERR is set and JSTART refuses to start, exactly as the frame path treats a bad CRC (UG470: frames are written as they arrive, and the CRC gates startup). A running design is never touched: while GWE = 1 nothing is written.
- **Length measurement:** shift a 32-bit marker **repeated** on TDI through CHAIN_OUT; from bit W on, every output bit equals the input bit (a delay of 128 = 4 × 32 before M12b's W), so the first position from which output == input is W (`cfgplane.measure_chain`).

## 5. Integrity: CRC-32C and CFG_CTRL

**CRC definition.** Standard CRC-32C (Castagnoli):
- polynomial `0x1EDC6F41`, reflected `0x82F63B78`
- init `0xFFFFFFFF`, final XOR `0xFFFFFFFF`
- computed **bit-serially over exactly the bits shifted in during one CFG_IN Shift-DR, in shift order**
- the register resets at Capture-DR of CFG_IN
- step: `crc = (crc >> 1) ^ (((crc ^ bit) & 1) ? 0x82F63B78 : 0)`; the result is `~crc`

When W is a multiple of 8 this equals the byte-wise CRC-32C of the chain bytes, taken LSB-first (byte j = chain bits `[8j+7:8j]`). The check value CRC-32C(`"123456789"`) = `0xE3069283` pins the implementation.

The init value is non-zero on purpose: a stuck-low TDI (all-zero chain) doesn't match the power-up expected CRC of 0.

**CFG_CTRL data register (64 bits).**

Capture-DR loads:

| bits | field |
|---|---|
| `[31:0]` | CRC computed over the most recent CFG_IN shift (`~crc`) |
| `[47:32]` | number of bits shifted in that scan (saturates at `0xFFFF`) |
| `[48]` | CRC_OK: the last CFG_IN committed |
| `[49]` | CRC_ERR: the last CFG_IN CRC mismatched |
| `[50]` | LEN_ERR: the last CFG_IN count ≠ W |
| `[51]` | COMMITTED: a valid configuration has been committed since power-up/JPROGRAM |
| `[52]` | GSR |
| `[53]` | GTS |
| `[54]` | GWE |
| `[55]` | DONE |
| `[63:56]` | format version = `0x02` |

Update-DR writes **expected CRC ← `[31:0]` only if `[63:56] == 0xC5`** (the write key, in the spirit of UG470's MASK register). A read that shifts zeros, or shifts the captured value back, changes nothing.

## 6. Startup

State after power-up **and** after JPROGRAM: all `cfg` = 0, COMMITTED = 0, CRC_OK = CRC_ERR = LEN_ERR = 0, **GSR = 1, GTS = 1, GWE = 0, DONE = 0**, startup phase 0. The expected CRC keeps its value.

- **JPROGRAM** acts during Update-IR when the new instruction is JPROGRAM: `cfg` cleared on the falling edge, flags on the next rising edge.
- **JSTART:** each rising TCK edge with the TAP in Run-Test/Idle and IR = JSTART advances one phase, **only if COMMITTED**:

| phase | edge | effect |
|---|---|---|
| 0 → 1 | 1st | GSR ← 0 (user flip-flops leave reset) |
| 1 → 2 | 2nd | GTS ← 0 (outputs enabled) |
| 2 → 3 | 3rd | GWE ← 1 (flip-flop/RAM writes enabled) |
| 3 → 4 | 4th | DONE ← 1 |

  The host clocks **12** TCKs in Run-Test/Idle after loading JSTART, as UG470's JTAG flow does. Without COMMITTED, DONE never rises.
- **Reconfiguration without JPROGRAM:** a later valid CFG_IN commit replaces `cfg` live and leaves the startup state as it is. This keeps bob's "load another design" workflow. Use JPROGRAM for a clean start.
- **What the signals mean for a top:** GSR holds every user flip-flop at its reset value; GTS forces fabric outputs inactive (M2/M3: LEDs 0; true hi-Z from M7 `io_tile`); GWE gates flip-flop clock enables and RAM writes; DONE is status (LD3 on the M2 test top).

## 7. CAPTURE (user state)

USER3 selects a read-only chain. Capture-DR snapshots the top's user-state vector, Shift-DR shifts it out LSB first, and Update-DR does nothing. Contents are top-specific:

| top | width | bits |
|---|---|---|
| `cfg_test_top` (M2) | 16 | `[7:0]` counter, `[9:8]` 0, `[11:10]` SW1..SW0, `[15:12]` BTN3..BTN0 |
| `fpga4x4_top` (M3–M6) | 16 | CLB `o` of tiles 0..15 |
| `bob_top` (M7–M20) | `device.json` `capture.width` (100 at M16) | CLB `o` of every CLB, row-major by (y, x) (`capture.order`); USER1 status returns the first 16. For a CLB with its flip-flop enabled, `o` is the register (M10 compares these with the golden netlist) |
| `bob_top` (M21) | 2 × elements (`capture.width`) | every **element's** two outputs, CLBs row-major by (y, x), elements 0..N−1 inside each: bit 2i is element i's `out[0]` (its first flip-flop, or O6 / the carry sum), bit 2i+1 its `out[1]` (the second flip-flop, or O5). `capture.order` names them; USER1 status still returns the first 16 bits |

**Boundary (M7):** 2 BC_1 cells per fabric pad (40 on the board profile, 20 pads; 64 for 8×8). Cell k (bit k, cell 0 nearest TDO) for k < NPAD is pad k's output cell: the fabric's pad output, forced 0 while GTS, to the world. Cell NPAD+k is pad k's input cell: the world to the fabric. Pads are numbered row-major over the I/O ring. Board profile: SW0, SW1, BTN0, BTN1 are pads 6, 8, 10, 12 (West edge), BTN2, BTN3 pads 0, 1 (South edge); LD0..LD2 are pads 7, 9, 11 (East edge); `device.json` `pads` has them. Every other pad reads 0 from the world and is reachable only by boundary scan.

## 7a. BRAM tile and USER4 (M5)

**Chain:** the BRAM tile's 424 bits close the chain (bits `[3487:3064]` at K=6).

| bits (tile-relative) | field |
|---|---|
| `[1:0]` / `[3:2]` | write mode A / B: 0 WRITE_FIRST, 1 READ_FIRST, 2 NO_CHANGE (UG473) |
| `[4]` / `[5]` | DOA_REG / DOB_REG |
| `[7:6]` | reserved |
| `[327:8]` | 64 pin source selects, 5 bits each: port A pins 0..31 then port B pins 32..63, each port `addr[9:0], di[17:0], we, en, rst, regce`. Source: 0 const0, 1 const1, 2 USER4 drive bit, 3..18 fabric East edge track 0..15 (track k = tile (k/4, 3) out_E[k%4]) |
| `[423:328]` | 16 output selects, 6 bits each, output k drives tile (k/4, 3) in_E[k%4]: 0 const0, 1..18 DO_A[0..17], 19..36 DO_B[0..17] |

**USER4 (`100011`) data register, 96 bits, LSB-first:**

- capture:

  | bits | field |
  |---|---|
  | `[17:0]` | word read by the previous READ |
  | `[27:18]` | address pointer |
  | `[45:28]` | live DO_A |
  | `[63:46]` | live DO_B |
  | `[64]` | err |
  | `[65]` | GWE |
  | `[69:66]` | target: the selected BRAM (M7; 0 before) |
  | `[87:70]` | 0 |
  | `[95:88]` | version `0x05` (M5–M6), `0x07` (M7) |

- update: `[95:92]` command, `[63:0]` payload. A capture shifted back has command 0 and does nothing.

  | command | name | effect |
  |---|---|---|
  | 1 | LOAD_PTR | ptr ← payload[9:0], err ← 0 |
  | 2 | WRITE | mem[ptr] ← payload[17:0], ptr++ |
  | 3 | READ | rdata ← mem[ptr], ptr++ |
  | 4 | SET_DRIVE | 64 pin values for pins whose source is "USER4 drive" (M7: the selected BRAM's drive word, used by a port whose `jtag_a`/`jtag_b` bit is set) |
  | 5 | SELECT | M7: target ← payload[3:0] if it is below the number of BRAMs. Every other command, and do_a/do_b in the capture, act on the target. Power-up target 0; JPROGRAM keeps it |

  WRITE and READ run only while **GWE = 0** (before JSTART, or after JPROGRAM); otherwise err is set. BRAM contents are separate from the configuration, as UG470 keeps them in their own frame block type. **JPROGRAM does not clear the contents.**

**BRAM clocking:** the same user clock enable (`gce`) and GSR/GWE as the fabric. GSR resets the output latches and registers to 0 (SRVAL 0) but never the contents.

## 7b. DSP tile and the DSP instruction (M6)

**Chain:** the DSP tile's 232 bits close the chain (bits `[3719:3488]` at K=6). Tile-relative:

| bits | field |
|---|---|
| `[17:0]` / `[35:18]` | slice 0 / slice 1: `[1:0]` opmode (0 M, 1 M+C, 2 P+M, 3 (PCIN>>>17)+M), `[2]` use_d, `[3]` d_sub, `[4..9]` AREG BREG CREG DREG MREG PREG, `[11:10]` `[13:12]` `[15:14]` `[17:16]` source of buses A B C D (0 const0, 1 DSP drive, 2 fabric: bit k ← North track k for k < 16, 3 const0) |
| `[39:36]` | reserved |
| `[119:40]` | 16 control selects, 5 bits each: slice 0 then slice 1, each `ce_ad ce_b ce_m ce_p rst_ad rst_b rst_m rst_p`. Source: 0 const0, 1 const1, 2 DSP drive bit, 3..18 North track 0..15 (track k = tile (3, k/4) out_N[k%4]) |
| `[231:120]` | 16 output selects, 7 bits each, output k drives tile (3, k/4) in_N[k%4]: 0 const0, 1..48 P0[0..47], 49..96 P1[0..47] |

**Semantics (UG479 trimmed):**
- AD = use_d ? (d_sub ? D−A : D+A) : A, 25 bits
- M = AD × B, 43 bits signed
- P per opmode; P+M always feeds back from the P register
- C and P share `ce_p`/`rst_p`; reset beats enable
- slice 1's PCIN = slice 0's P; slice 0's PCIN = 0
- gce, GWE and GSR act as they do on every other register

**DSP instruction `101000` (private, not an AMD 7-series code), 256 bits:**
- capture: `[47:0]` P0, `[95:48]` P1, `[247:96]` 0, `[255:248]` version `0x06` (M6), `0x07` (M7: the register lives in `dsp_jtag.v`; slices are `dsp0`/`dsp1` in the DSP column, and a slice uses its drive bits only where its `jtag_*` config bits say so)
- update: only `[255:252] == 4` (SET_DRIVE) does anything: drive ← `[247:0]`
- drive layout: slice s at `[124·s +: 124]` = `a[24:0] b[17:0] c[47:0] d[24:0]` then the 8 controls

## 8. Host load sequence

1. IR JPROGRAM.
2. IR CFG_CTRL, DR 64: `(0xC5 << 56) | crc`.
3. IR CFG_IN, DR W: the chain (bulk transfer allowed).
4. IR CFG_CTRL, DR 64 read: require COMMITTED, CRC_OK and count = W; otherwise retry the whole sequence per-pulse, then fail.
5. IR CFG_OUT, DR W read: must equal the chain; otherwise retry per-pulse, then fail.
6. IR JSTART, then 12 × TCK with TMS = 0.
7. IR CFG_CTRL read (or any IR capture): require DONE.

**Chain file (`.bobc`, host-side only; the chip never sees it):**

| offset | size | field |
|---|---|---|
| 0 | 4 | magic `BOBC` |
| 4 | 2 | file version = 1 (little-endian) |
| 6 | 2 | name length N |
| 8 | N | device name, ASCII (e.g. `bob4x4`, `cfg_test`) |
| 8+N | 4 | chain width W (LE) |
| 12+N | 4 | CRC-32C per section 5 (LE) |
| 16+N | ⌈W/8⌉ | chain bytes, byte j = chain bits `[8j+7:8j]` |

The loader checks magic, name, width and CRC **before** touching hardware.

**Version 2 (M10, `.bit` from `software/bob/bitgen.py` / `bob build`)** is version 1 with the version field = 2, followed by:

| size | field |
|---|---|
| 2 | section count S (LE) |
| S × (8 + len) | sections: 4-byte ASCII tag, 4-byte length (LE), data |
| 4 | CRC-32C (byte-wise, `crc32c_bytes`) of every byte before it |

| tag | data |
|---|---|
| `BRAM` | u8 BRAM index, u16 first address, u16 count, count × u32 words (LE). Written over USER4 (SELECT, LOAD_PTR, WRITE) after CFG_IN and before JSTART, while GWE = 0 |
| `META` | UTF-8 JSON: design, top, sources + sha256, pcf, VPR result hash, clock, fasm_sha256 |

Version 1 files still read. `bob load`: steps 1–5 above, the BRAM sections, then steps 6–7.

## 8a. FASM (M9/M10)

The text form of a chain, one feature per line (after F4PGA's FASM): `feature = <width>'h<value>`, `#` comments. Only non-zero features need to be written.

| feature | meaning |
|---|---|
| `<block>.<field>` | a field of a CLB, BRAM or DSP block (`clb_x2y3.init`, `bram0.wmode_a`), section 4 |
| `ctrl.<field>` | the ctrl tile (`ctrl.clk_mode`, `ctrl.clk_div`) |
| `rr<node>` | the routing mux of rr-graph node `<node>`: const0, const1 (IPIN) or base + input index |

The declared width must equal the device's; every value is checked (field exists, fits, a mux value is a constant or one of the mux's inputs). Chain → FASM decodes every configurable field and refuses set bits that no feature owns (the tail), so chain → FASM → chain is exact (`bitgen.py --roundtrip`).

## 9. Two ways to write the same configuration memory (M13)

From M13 the configuration memory is organised in **frames**, as in AMD 7-series devices, and there are two independent ways to write and read it back:

| path | instructions | unit | integrity | use |
|---|---|---|---|---|
| **frames** (default) | CFG_IN / CFG_OUT (the AMD codes) | 32-bit words in type-1/type-2 packets; frames of 4 words | CRC-32C over `{register, data}` of every write, IDCODE check | section 10; `bob load` |
| **chain** | CHAIN_IN / CHAIN_OUT (private) + CFG_CTRL | the whole memory in one DR scan | CRC-32C + length (section 5) | sections 4, 5, 8; `bob load --mode chain` |

Both write the same memory the fabric reads, both are refused while GWE = 1 (a running design is never reconfigured underneath itself) - **except** M14 partial reconfiguration on the frame path, which first freezes the user clock (section 12) - both are cleared by JPROGRAM, and both feed the same startup (section 6: JSTART after a good load).

**Frame layout of the memory.** The memory is cut into **frames of FRAME_WORDS = 4 words = 128 bits**. Frames are column-major, like the 7-series configuration columns:

- FAR column 0 is the configuration column: the 8-bit ctrl tile (section 4), padded to a whole frame.
- FAR column `c = x + 1` holds VPR grid column `x`: the tiles `(x, 0), (x, 1), … (x, H−1)` bottom to top, each as in section 4 (block fields, then routing muxes in ascending rr node id), padded with zeros to a whole number of frames. A column without configuration bits has no frames.
- Frame index `f` numbers the frames of column 0, then column 1, … in order; frame `f` is memory bits `[128·f + 127 : 128·f]`, and within a frame word `w` bit `k` is frame bit `32·w + k`.

So **the chain (section 4) is exactly all frames end to end**: chain bit `k` is memory bit `k` in both paths, the chain width is `128 × NFRAMES`, and a `.bit` chain word loads identically through either path. `device.json` `frames` lists every column's FAR column number, frame count and first frame index; padding bits are reserved and must be 0.

## 10. The frame path: packets, registers, readback (M13)

Modelled on UG470 chapter 5 (configuration packets and registers) and simplified where noted.

**Stream framing.** Over CFG_IN each 32-bit word is shifted **MSB first** (bit 31 of the first word is the first bit on TDI), as a 7-series `.bit` reaches the device over JTAG. The controller hunts bit by bit for the sync word **`0xAA995566`**; the next 32 bits are the first word. Dummy words before the sync word are ignored. Words can span as many DR scans as the host likes (Capture-DR and Update-DR do not reset the word alignment). JPROGRAM or a DESYNC command returns to hunting.

**Packet headers** (UG470 Table 5-20, 5-21):

| type | [31:29] | [28:27] | [26:13] | [12:11] | [10:0] / [26:0] |
|---|---|---|---|---|---|
| 1 | `001` | opcode: `00` NOP, `01` READ, `10` WRITE | register address (only [17:13] may be non-zero) | `00` | word count (11 bits) |
| 2 | `010` | opcode (must equal the preceding type-1's) | — | — | word count (27 bits) |

A type-1 header with count 0 must be followed by a type-2 header carrying the count (the FDRI idiom `30004000 5000xxxx`). A type-2 header anywhere else, an unknown header type, an unknown register or an unsupported command is a **packet error**. A WRITE is followed by its count data words; a READ has no data words in the input stream: it queues `count` words for CFG_OUT.

**Registers** (7-series addresses; the subset bob implements):

| addr | name | W/R | bob behaviour |
|---|---|---|---|
| `00000` | CRC | W | compare the written value with the running CRC: equal sets CRC_OK; different sets CRC_ERROR (packet parser stops, startup refused) |
| `00001` | FAR | W/R | frame address, below; auto-increments after every whole frame written or read |
| `00010` | FDRI | W | frame data in: words fill a frame; the 4th word writes the frame at FAR into the memory **immediately** and advances FAR |
| `00011` | FDRO | R | frame data out: words of the frame at FAR, advancing FAR per frame |
| `00100` | CMD | W | command, below |
| `00111` | STAT | R | status, below |
| `01100` | IDCODE | W | must equal the device IDCODE; a mismatch sets ID_ERROR (parser stops). FDRI is refused until it has matched |

**FAR** (7-series layout, UG470 Table 5-24): `[25:23]` block type (`000` configuration; `001` BRAM contents from M15, section 13), `[22]` top/bottom (0), `[21:17]` row (0 for configuration), `[16:7]` column, `[6:0]` minor (frame within the column). After each frame the minor advances; past the column's last frame it moves to minor 0 of the next column with frames. Writing or reading at an address outside the memory is a write error.

**CMD** (UG470 Table 5-25 codes): `00000` NULL · `00001` **WCFG** arm frame writes · `00011` **LFRM** (DGHIGH/LFRM) last frame; with a freeze pending it releases the freeze only after CRC_OK (section 12) · `00100` **RCFG** arm frame reads · `00101` **START** allow startup: requires CRC_OK after the last FDRI word, the IDCODE match and no error · `00111` **RCRC** reset the CRC · `01000` **AGHIGH** (M14) freeze the user clock for partial reconfiguration, needs the IDCODE match · `01101` **DESYNC** back to hunting. Any other value is a packet error.

**CRC.** CRC-32C (reflected polynomial `0x82F63B78`), initial value 0, no final inversion. Every WRITE data word except those written to CRC updates it with the 37-bit value `{register[4:0], data[31:0]}`, least significant bit first. RCRC sets it to 0 (after its own update). READs and headers do not contribute. (prjxray `crc.py` computes the 7-series CRC this way.)

**Frame writes** are accepted only while WCFG is armed, IDCODE has matched, no error is set, FAR is valid and **GWE = 0 or the freeze is acknowledged** (M14, section 12; BRAM content frames always need GWE = 0); otherwise the words are dropped and WR_ERROR is set. Any FDRI data word clears CRC_OK, so a CRC check must follow the frames before START.

**Simplifications against 7-series:** a frame is written the moment its last word arrives, so bitstreams need **no trailing pad frame**, and readback returns **no leading pad frame**; no encryption, compression (MFWR), bus-width detection, COR/CTL options, per-frame ECC or multiboot; FAR auto-increment does not cross from block type 0 into block type 1 (the stream writes FAR before the BRAM frames); a parser error is left only by JPROGRAM.

**STAT** (32 bits; positions follow 7-series where the meaning exists):

| bit | 0 | 5 | 6 | 7 | 11 | 12 | 14 | 15 | 23:16 | 24 | 25 | 26 | 27 | 28 | 29 | 30 | 31 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| meaning | CRC_ERROR | GTS_CFG_B (= not GTS) | GWE | GHIGH_B (M14: 0 = freeze acknowledged) | INIT_COMPLETE (1) | INIT_B (no error) | DONE | ID_ERROR | version (`0x13` M13, `0x14` M14, **`0x15`** M15) | PKT_ERROR | WR_ERROR | SYNCED | WCFG | CRC_OK | GSR | START accepted | RCFG |

**Readback (CFG_OUT).** Each READ packet queues words: FDRO gives frame words from FAR (advancing FAR per frame); STAT, FAR, IDCODE and CRC give one current value per word. A CFG_OUT DR scan shifts the queued words out MSB first, 32 bits per word; with nothing queued (and past the queue) each word reads STAT, so a bare 32-bit CFG_OUT scan is a status read. FDRO needs RCFG armed (else WR_ERROR, zeros).

**Load sequence** (what `bob load` sends; `software/bob/packets.py` builds and parses it):

```
FFFFFFFF FFFFFFFF          dummy
AA995566                   sync
20000000                   NOP
30008001 00000007          CMD    <- RCRC
30018001 <IDCODE>          IDCODE <- the device IDCODE
30002001 00000000          FAR    <- 0 (column 0, minor 0)
30008001 00000001          CMD    <- WCFG
30004000 5000xxxx          FDRI, type-2 count = 4 x NFRAMES
<4 x NFRAMES words>        frames 0 .. NFRAMES-1 (FAR advances by itself)
30002001 00800000          FAR    <- BRAM 0, frame 0              } M15, per BRAM the design
30004000 50000400          FDRI, type-2 count = 1024              } uses: all 1024 words,
<1024 words>               {14'b0, data[17:0]}                    } section 13
30000001 <CRC>             CRC    <- expected
30008001 00000003          CMD    <- LFRM
30008001 00000005          CMD    <- START
30008001 0000000D          CMD    <- DESYNC
20000000 20000000          NOP
```

then JTAG: CFG_IN READ of STAT and CFG_OUT (START accepted, no error), FDRO readback of the memory and (M15) of every BRAM's content frames, JSTART + 12 TCK in Run-Test/Idle, DONE. (Up to M14 the BRAM contents went over USER4 at this point; `bob load --mode chain` still does that.) Readback sends `sync, CMD <- RCFG, FAR <- 0, 28006000 4800xxxx (READ FDRO, type-2), DESYNC` on CFG_IN and shifts `32 × 4 × NFRAMES` bits out of CFG_OUT.

## 11. Host-to-fabric timing assumptions (M13)

These rules make the Vivado timing constraints true (hw/constr/pynq_z2.xdc):

1. **User-clock enables are at least 512 sysclk cycles apart** (4096 ns; 256 = 2048 ns through M15, raised at M16 because the 12×10 fabric's static path through the unconfigured routing muxes is about 2500 ns), enforced in `clock_ctrl.v` for both clock modes (a JTAG step arriving earlier waits; only one waits, so in clock mode 0 with USER1 ce, "one user clock per TCK edge" holds only while TCK edges are further apart than the gap: 4096 ns by default against 1000 ns at 1 MHz. The host's `shift_dr` is one USB round trip per edge, far slower, which is why the counter-step checks still count every edge; a bulk shift in clock mode 0 would merge edges unless the design's `clk_gap` is short). Through M20 every path from a fabric register through the fabric to a fabric register was therefore a 512-cycle multicycle. **From M21** the XDC relaxes sysclk → sysclk by 16 384 cycles (`XDC_SYSCLK_MULTICYCLE`), and what makes that true is software: `timing.contract()` (flow timing stage, `cli.load`) refuses any configuration whose critical path × guard band exceeds its gce spacing (`clk_gap`, or 512 when it is 0). The fabric is flattened (keeping its hierarchy crashed Vivado 2025.2 on the routing loops) and flattening renames its registers, so the constraint is by clock (sysclk → sysclk); the only other sysclk logic, `u_clk` and `u_bram_jtag`, is held to one cycle by cell name (build.tcl lists the caught registers in `sysclk_1cycle.txt`; `tests/test_reports.py` requires gce and the BRAM strobes there), except the cin synchroniser's paths into the fabric.
2. **TCK is at most 1 MHz** since M25 (M13–M24: 100 kHz; `software/host/dirtyjtag.py` refuses more, `MAX_TCK_KHZ`) and is constrained at that period (`XDC_TCK_PERIOD_NS`). From M21 the XDC relaxes TCK → TCK to 16 periods: the empty cluster mesh's IR → DSP JTAG path (5.46 µs) passed the 5 µs fall → rise half period at 100 kHz, and at 1 MHz it fits the 16 µs multicycle; a configured design's paths are tens of ns. The M13–M24 bitstreams are constrained for 100 kHz only, so drive them no faster.
3. **Configuration changes only while GWE = 0**, so the fabric never samples configuration bits while they change - or (M14) while the user clock is frozen and the freeze has been acknowledged in the TCK domain: then no fabric register, BRAM or DSP register is enabled (every one of them is gated by gce), so bits changing under a held enable cannot be captured.
4. **(M15) BRAM content frame requests are at least 32 TCK periods apart** (one frame word: 32 µs at 1 MHz, 320 µs at 100 kHz; a frame on the sysclk side takes ~12 cycles = 96 ns). Requests travel as a toggle through a two-flop synchroniser with their data stable, as the USER4 commands always did.
5. **(M14) The freeze handshake:** AGHIGH → `freeze` (TCK) → 2-flop synchroniser → `gce` forced low and `frozen` set on the same sysclk edge → 2-flop synchroniser on TCK → GHIGH_B = 0. The host reads STAT and sends frames only after GHIGH_B = 0; frames that arrive earlier are refused (WR_ERROR).

## 12. Partial reconfiguration of a running design (M14)

AMD 7-series devices reconfigure part of a running design by writing only that region's frames, with GHIGH_B asserted around the write (UG470 CMD AGHIGH / DGHIGH-LFRM; UG909 for the flow). bob follows the same command sequence; what bob's GHIGH_B holds is its user clock: every fabric flip-flop, BRAM and DSP register is enabled only by gce, so a held gce keeps the **whole** fabric's state exactly while any frames change.

**Sequence** (`software/bob/packets.py` `partial_streams(old, new)`, `software/host/cfgplane.py` `load_partial`, `bob load --partial x.bit`):

```
scan 1 (CFG_IN):  dummy, AA995566, NOP, CMD <- RCRC, IDCODE <- device, CMD <- AGHIGH, NOP
scan 2 (CFG_OUT): STAT; require GHIGH_B = 0 and no error
scan 3 (CFG_IN):  CMD <- WCFG, for each run of consecutive changed frames: FAR <- first, FDRI <- the run,
                  CRC <- over everything since RCRC, CMD <- LFRM, CMD <- DESYNC
scan 4 (CFG_OUT): STAT; require GHIGH_B = 1 and no error; CHAIN_OUT == new
```

- **Only changed frames** are written (the host reads the current memory over CHAIN_OUT, non-destructively). A LUT truth-table change in one CLB is one frame; a re-routed guest design typically 20-30 of 65.
- **State:** registers keep their values across the partial (no GSR); a design that needs a reset after reconfiguration must do it itself.
- **Release:** LFRM releases the freeze only if the CRC written after the last FDRI word matched. A wrong CRC, a missing CRC or any write error leaves the fabric **frozen** with the error in STAT; only JPROGRAM (and a full load) recovers. A half-written design never runs.
- **Refusals:** AGHIGH without a matched IDCODE, frames while GWE = 1 without an acknowledged freeze, frames sent before the acknowledgement (all WR_ERROR).
- **Not in M14:** region protection (any frame may be rewritten; the host decides), BRAM content writes while frozen, pad hold during the write (pads follow the changing logic combinationally).
- **Verification:** `tb_frames` [13]-[17] (a free-running counter holds while frozen and continues from its value; the gate changes; no CRC, bad CRC, no IDCODE, frames before acknowledgement), `tb_clock_gap` [4], 5 mutants in `sim/mutate_frames.sh`; board: `partial-swap`, `partial-live`, `partial-bad-crc`, `partial-guest`.

## 13. BRAM contents as frames (M15)

UG470 carries BRAM initial contents in the bitstream as their own block type. From M15 bob does too, and the whole design (configuration + contents) is one CRC-covered packet stream; USER4 (section 7a) stays as the second path, as the chain stays beside frames.

- **FAR block type `001`:** `[16:7]` column = BRAM index (0 .. NBRAM−1), frame n = `[22:17]` row × 128 + `[6:0]` minor, n = 0 .. 255. Frame n holds BRAM addresses 4n .. 4n+3, word w = `{14'b0, mem[4n+w][17:0]}` (the top 14 bits are written as 0 and read as 0). Auto-increment: n+1, then frame 0 of the next BRAM, then past the end (invalid).
- **Writes (FDRI):** WCFG, IDCODE matched, no error and **GWE = 0** (as USER4); otherwise WR_ERROR. The 4th word of a frame hands the 4 words to `bram_jtag.v`'s sysclk side, which writes them through bram_core's port A (timing rule 4, section 11).
- **Readback (FDRO):** RCFG and GWE = 0 (after JPROGRAM the contents are as the design left them). The controller prefetches each frame's 4 words through the same port while FAR points at it; with GWE = 1 FDRO of block type 1 reads zeros.
- **Load:** `load_stream(word, brams)` writes every word of every BRAM the design uses (all 1024: contents survive JPROGRAM, so a skipped word would keep the previous design's value), under the same CRC as the configuration frames.
- **Verification:** `tb_frames` [18]-[19] (bram0 frames, FAR crossing into bram1, FDRO readback, refusal while running), 5 mutants; board: `frames-bram-load` (both BRAMs, FDRO == contents, USER4 reads the same words, ROM LEDs), `frames-bram-live-refused`, `ram-readback-frames` (a design's own writes read back over FDRO == model.py == USER4), and every `bob-*` design load now sends its BRAMs as frames.

## 14. Readback from a BRAM shadow (M21)

Until M20 both readbacks - CHAIN_OUT (section 4) and FDRO (section 10) - read the
configuration flip-flops themselves through one frame-wide read multiplexer in
`cfg_store.v`: a 256:1 × 128-bit mux, about 11 800 of the design's LUTs in yosys and the
largest single cause of M16's routing congestion. M20 measured that restructuring the mux
does not help (a tree was +310 LUTs in the whole design); M21 removes it.

- **The shadow.** Every frame written into the memory - by the chain (CHAIN_IN, each
  128-bit frame as it completes) or by FDRI (CFG_IN) - is written on the same falling TCK
  edge, from the same frame buffer and under the same write enable, into a block RAM
  `shadow` (NFRAMES × 128 bits: one or two RAMB36 of the XC7Z020's 140). Partial
  reconfiguration (section 12) writes frames through the same path, so it is mirrored too.
- **Reads.** CHAIN_OUT and FDRO read the shadow through one synchronous port on the rising
  edge. The address must therefore be steady one cycle before the data is used: FDRO's
  frame changes only when a word is loaded, at least 32 TCK edges before the next;
  CHAIN_OUT reads frame `idx + 1`, and `idx` rests at all-ones between DR scans (set at
  Update-DR), so frame 0 is waiting at Capture-DR.
- **JPROGRAM** zeroes the flip-flops at once; a block RAM cannot be. Each frame has a
  `valid` bit, cleared with the flip-flops and set by every write; a frame that is not
  valid reads back as zeros - exactly what the cleared memory holds.
- **What readback proves now.** Readback returns the frames that were **written**, not
  what the configuration flip-flops **hold**. A flip-flop that failed to take its bit would
  no longer show up in a readback. The flip-flops stay covered, functionally, by the
  golden co-simulation (`tb_cosim`: every example's LEDs and registers against the source
  and the golden netlist, loaded from its `.bit`), by CAPTURE on the board (every register
  of every example against `golden.py`), and by the board's live model checks (the LEDs
  against `model.py` given the captured registers). On silicon, 7-series readback reads
  the configuration cells themselves; this is a deliberate divergence for area.
- **Nothing on the wire changes**: the same packets, the same CRC, the same STAT; a host
  cannot tell the shadow from the flip-flops.
- **Verification:** `tb_frames` [2] (FDRO == every frame loaded), [13] (after JPROGRAM
  every frame reads zero; after a partial write FDRO == the new design), `tb_bob`
  (CHAIN_OUT); mutants `shadow-no-rewrite` (a partial rewrite of a frame not mirrored),
  `shadow-wrong-frame`, `shadow-not-cleared`, `shadow-frames-only` (chain writes not
  mirrored) in `sim/mutate_frames.sh`.

## 15. LUT contents and the crossbar in CFGLUT5 (M22)

From M22 the bits that describe a CLB's logic - each element's truth table (`e<e>.init`)
and each crossbar select (`e<e>.x<j>`) - are not held in configuration flip-flops. They
live in AMD CFGLUT5 primitives (UG953: a LUT5 whose 32-bit table is shifted in on CLK
while CE, first bit ending at bit 31), the way ZUMA keeps an overlay's LUTs in host LUTRAM
(Brant & Lemieux, FCCM 2012). Nothing on the wire changes: the same fields, the same
frames, the same CRC, the same FASM.

- **Layout.** A CLB tile starts on a frame boundary. Frame 0 holds the first 16 crossbar
  selects (5 bits each, slot t at bit 5t) and then the 48 element-flag bits; the next two
  frames hold the truth tables (2^K bits each, 128 / 2^K per frame); the last frame holds
  the remaining 8 selects (again slot t at bit 5t), after which the tile's routing muxes
  follow as before. At K = 6, N = 4: 4 frames per CLB carry CFGLUT5 bits (2 of them mixed
  with flip-flop bits), 30,456 of the 56,448 bits; `BOB_LBIT_MASK` names them bit by bit.
- **Why this order.** Frames are written in ascending order, and a frame's flip-flop bits
  load at the write, before its CFGLUT5s start shifting - so a load sets the flags, then
  the truth tables, then the crossbar. A first layout wrote the crossbar before the flags:
  for 128 TCK cycles a new crossbar could feed an element's output back through its own
  LUT with its flip-flop still off (a counter's `q -> +1 -> q` became a ring oscillator).
  Harmless on silicon (GWE low, pads held), but it hung `tb_synth`. A second layout gave
  the flags a frame of their own and pushed the chain past 65,536 bits, iverilog's widest
  constant. `tests/test_device.py` now requires every flag frame to come no later than
  every select frame. `device.json` lists them (`lframes`),
  `bob_params.vh` carries `BOB_LFRAME_MASK`.
- **The element's LUT** is two CFGLUT5: lo = INIT[2^(K-1)-1:0], hi = the upper half, both
  over i[K-2:0]; O6 = (i[K-1] | frac) ? hi : lo (a MUXF7), O5 = lo - UG474's LUT6_2 fracture.
- **A crossbar mux** (M23, `lxor.v`) is ceil(S/5) CFGLUT5 leaves over the sources, each on
  O6 only, and a fixed OR of the leaves in a plain LUT (M22's `lxmux.v` had a CFGLUT5 root).
  Select 2+i puts "address bit i%5" in leaf i/5 and zeros in the others; select 1 (const1)
  is an all-ones leaf 0; 0 (and values past the sources) all zeros. On the wire nothing
  changes. (Sharing a leaf between two muxes through O5/O6 is not used: Vivado maps a
  dual-output CFGLUT5 to SRL16E + SRLC32E, two LUT sites.)
- **Loading.** Every write - chain or FDRI, full or partial - reaches memory from
  `cfg_store.v`'s frame buffer on a falling TCK edge. On that edge `lut_loader.v` copies the
  buffer and the frame index and shifts for 32 TCK cycles; each CLB compares the index with
  its own L-frames (CE), and one shared expander (`lut_expand.v`) turns the buffer into
  every slot's shift data: truth-table bits as they are, selects into the tree contents
  above. A frame takes at least 128 TCK cycles to arrive, so a load always finishes before
  the next; JSTART ticks are held while the loader is busy.
- **JPROGRAM** starts a 32-cycle sweep of zeros into every CFGLUT5: every select const0,
  every table 0 - the dark, loop-free fabric the cleared flip-flops give.
- **No flip-flops.** `cfg_store.v` keeps none for L-frames. Readback is unchanged: the M21
  shadow (section 14) holds what was written, L-frames included.
- **Clocks.** CFGLUT5 CLK is TCK; the fabric reads the tables combinationally, as it read
  the configuration flip-flops (TCK and sysclk are asynchronous groups; configuration only
  changes with the fabric frozen).
- **Verification:** `tb_clb` loads every configuration through `lut_expand.v` and 32 shift
  clocks per L-frame (4032 checks against `model.py`); `tb_bob` checks CLB (1,1)'s tables
  and one crossbar mux's leaves against contents `sim/gen_vectors.py` computes independently from
  the word, and the JPROGRAM sweep; every chip-level bench loads over JTAG, through the
  loader. Mutants `expand-bit-order`, `lut-halves-swapped`, `loader-31-shifts`,
  `loader-no-sweep`, and from M23 `lxor-root-and`, `lxor-drop-leaf0`, `expand-leaf-index`,
  `expand-no-const1` (`sim/mutate_fabric.sh`). On the board, `lutram-snake` chains every
  element (docs/hwtest/M22.md) and `xbar-pins` does it on every pin (docs/hwtest/M23.md).
- **M23 masks.** `BOB_LFRAME_MASK` became `BOB_LKIND` (a kind per frame) and `BOB_LMASKS`
  (the distinct per-frame masks): at 10 × 10 the chain is 68,096 bits, past iverilog's
  widest constant. `cfg_ctrl.v`'s chain count is 24 bits; CFG_CTRL still reports its low 16.


## 16. M24: Double Duty elements

A new element flag, `dd` (bit 12 of the element's flags, after `ff2_sr_en`), used with
`cy_en`. The adder reads A = element input K-2 and B = input K-1 directly: propagate =
A ^ B ^ `cy_di_sel` (INV_B, for subtraction), generate/DI = A. The LUT does not feed the
adder, so its O5 half (INIT[2**(K-1)-1:0], addressed by inputs K-2..0) drives out[1] as an
independent function. VPR's `dd` mode puts a LUT on inputs K-3..0 there, and FASM repeats its
table over input K-2. Pun et al., FPL 2025 (arXiv 2507.11709). The 13th flag moves one
crossbar select from frame 0 into the tile's last frame (`lutram_layout` `xbar_head` 16 → 15);
the chain width is unchanged.


## 17. M25: GRESTORE and snapshots

CMD register value 10, **GRESTORE** (UG470): pulses the fabric's GSR for one packet word
(32 TCK). Every element flip-flop takes its INIT value (`ff_rstval` / `ff2_rstval`). It is
accepted only after a matched IDCODE and with the fabric frozen (AGHIGH acknowledged) or
before startup (GWE = 0); otherwise WR_ERROR and ST_ERR. STAT's version byte is 0x16.

A restore (`packets.restore_streams(mem, init_mem)`) is one partial stream, in this order:

    AGHIGH, WCFG, [FAR + FDRI of the frames init_mem changes], CMD GRESTORE, NOP,
    [the same frames from mem], CRC over everything since RCRC, LFRM, DESYNC

`software/host/snapshot.py` reads the state through CAPTURE between the second frame write and
the CRC, while the fabric is still frozen.
