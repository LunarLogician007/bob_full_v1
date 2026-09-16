# bob configuration format: scan-chain plane (format version 2)

This is the spec shared by the RTL (`hw/src/core/jtag_tap6.v`, `cfg_ctrl.v`, `cfg_mem.v`, `cfg_tile_sr.v`, `capture_chain.v`) and the Python tools (`tools/bob/chainbits.py`, `host/cfgplane.py`). If they disagree, this document decides, and the code is fixed.

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
| `000100` | **CFG_OUT** | config chain | chain width | readback; never commits |
| `000101` | **CFG_IN** | config chain | chain width | write; commits at Update-DR if length and CRC are right |
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

- **Width W** comes from the device description (`tools/bob/device.json` `chain.width`). The M2 test top uses 64 = 4 tiles × 16; the fabric used 2896 at M3, 3064 at M4, 3488 at M5, 3720 at M6, **4216 from M7 on the board profile** (16 CLBs, `ARCH_6X4`; 3352 at K=4). The frozen 48-CLB profile (`release/M7_8x8/`) is 9400 (6808 at K=4).
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

  **Routing muxes** are VPR's routing-resource-graph nodes with driving edges (`tools/bob/arch/bob_k6_rr.xml.gz`):
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
- **Structure:** each tile has a shift register `sr` and a shadow register `cfg`. TDI enters the MSB of the **last** tile. Each tile's `sr[0]` feeds the next-lower tile's MSB, and tile 0's `sr[0]` drives TDO. Tiles and the fabric see **only** `cfg`.
- **Capture-DR** (CFG_IN or CFG_OUT): every `sr` ← its `cfg`. So the first W bits out of any chain scan are the current configuration, LSB first.
- **Shift-DR:** shift by one per TCK. `cfg` doesn't change while shifting.
- **Update-DR in CFG_OUT:** nothing. Readback is non-destructive and never commits, whatever was shifted in.
- **Update-DR in CFG_IN:** `cfg` ← `sr` for all tiles **only if** the number of bits shifted in this scan equals W **and** the CRC equals the expected CRC. Otherwise nothing changes and CRC_ERR and/or LEN_ERR is set.
- **Scans longer than W** through CFG_OUT (a marker after W bits) measure the chain length without side effects.

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
| `bob_top` (M7) | `device.json` `capture.width` (16 on the board profile, 48 for 8×8) | CLB `o` of every CLB, row-major by (y, x) (`capture.order`); USER1 status returns the first 16. For a CLB with its flip-flop enabled, `o` is the register (M10 compares these with the golden netlist) |

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

**Version 2 (M10, `.bit` from `tools/bob/bitgen.py` / `bob build`)** is version 1 with the version field = 2, followed by:

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

## 9. What M13 changes

The chain (sections 4 and 8) is replaced by UG470 frames: sync word `0xAA995566`, type-1/2 packets, FAR/FDRI/FDRO with auto-increment, CRC over `{addr, data}`. The instruction codes, CFG_IN/CFG_OUT as the transport, startup (section 6) and CAPTURE stay.
