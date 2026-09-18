# bob: an FPGA inside an FPGA

**Project report, M0–M15** · 2026-09-17 · `bob_full_v1` · **every milestone passed on the PYNQ-Z2**

Interactive companion: [`project.html`](../../project.html) (timeline, architecture, configuration streams, verification and hardware data, problems and fixes). The per-block die slice is [`arch.html`](../../arch.html). The specification is [`docs/bitstream-format.md`](../bitstream-format.md), and the working plan with every milestone's as-built notes is [`PLAN.md`](../../PLAN.md). The numbers in this report come from [`docs/project/data.json`](data.json), which `docs/project/collect.py` builds from the repository (board log, Vivado reports, device description, VPR stamps, check logs).

---

## Contents

1. [Summary](#1-summary)
2. [What was asked, and the rules of the work](#2-what-was-asked-and-the-rules-of-the-work)
3. [System overview: two flows, three machines](#3-system-overview-two-flows-three-machines)
4. [Timeline and status of every milestone](#4-timeline-and-status-of-every-milestone)
5. [The device](#5-the-device)
6. [JTAG: the TAP and the instruction set](#6-jtag-the-tap-and-the-instruction-set)
7. [Configuration I: the scan chain (M2–M12b)](#7-configuration-i-the-scan-chain-m2m12b)
8. [Configuration II: frames and packets (M13)](#8-configuration-ii-frames-and-packets-m13)
9. [Configuration III: partial reconfiguration (M14)](#9-configuration-iii-partial-reconfiguration-m14)
10. [Configuration IV: BRAM contents as frames (M15)](#10-configuration-iv-bram-contents-as-frames-m15)
11. [Startup, user clock, CAPTURE and the hard-block registers](#11-startup-user-clock-capture-and-the-hard-block-registers)
12. [The guest tool flow: Verilog to a running design](#12-the-guest-tool-flow-verilog-to-a-running-design)
13. [bob's own place and route (M12a)](#13-bobs-own-place-and-route-m12a)
14. [Host software and the Pico](#14-host-software-and-the-pico)
15. [Verification](#15-verification)
16. [Hardware results](#16-hardware-results)
17. [Vivado: builds, timing and the synthesis crashes](#17-vivado-builds-timing-and-the-synthesis-crashes)
18. [Area: where the logic went, and the 36-CLB grid (M12b)](#18-area-where-the-logic-went-and-the-36-clb-grid-m12b)
19. [Problems found and how each was fixed](#19-problems-found-and-how-each-was-fixed)
20. [Where bob follows its references and where it diverges](#20-where-bob-follows-its-references-and-where-it-diverges)
21. [Repository map and size](#21-repository-map-and-size)
22. [How to use it](#22-how-to-use-it)
23. [Open items and what comes next](#23-open-items-and-what-comes-next)
24. [References](#24-references)

---

## 1. Summary

bob is a complete, programmable FPGA written in Verilog and running inside the programmable logic of a **PYNQ-Z2 (Zynq XC7Z020)**. It has its own:
- logic cells, BRAMs, DSP slices, routing and I/O pads
- configuration memory and JTAG configuration controller
- tool chain: yosys synthesis, VPR or bob's own place and route, FASM, bitgen

A Mac configures it over JTAG through a Raspberry Pi Pico running DirtyJTAG.

A user design goes from Verilog to LEDs with two commands, `./bob build design.v` and `./bob load design.bit`. It is checked at every step against the source Verilog, a golden netlist and a cycle model.

| | |
|---|---|
| Guest device (on the board, M15) | 36 CLBs (LUT6 + carry + FF), 2 × 1024×18 BRAM, 2 DSP48E1-style slices, 28 pads, L4 routing W = 24, 1723 routing muxes |
| Configuration memory | 8320 bits = 65 frames × 4 × 32-bit words |
| Configuration paths | UG470-style packets (CFG_IN/CFG_OUT: CRC, IDCODE, FAR/FDRI/FDRO, STAT, **partial reconfiguration**, **BRAM content frames**), and a streamed scan chain (CHAIN_IN/CHAIN_OUT + CRC) |
| On the board | M15 bitstream (36 CLBs, frames, partial reconfiguration, BRAM content frames): **48/48**, WNS +0.585 ns, 10 411 LUT / 11 097 FF |
| Hardware test runs logged | 57 runs; every milestone M0–M15 ended in a full pass (M15: 48/48) |
| Simulation (last `make check`) | 28 744 testbench checks in 11 testbenches + 183 pytest tests; 59 mutants, all killed |
| Code (hand-written) | Python 13.5k lines, Verilog/SV 6.7k, Tcl 0.9k, shell 0.6k, docs 3.2k + generated fabric (2.3k lines of Verilog from VPR's routing graph) |

The main results:
1. **An OpenFPGA-style fabric generated from VPR's own routing-resource graph** (M7). Every rr node with fan-in is a mux in the RTL, so VPR routes on exactly the hardware that exists.
2. **The full guest flow** (M8–M11): yosys → VPR → FASM → bitgen → load. Every example design runs on the board, cycle-exact against its source and golden netlist.
3. **bob's own pack/place/route** (M12a) produces 0.93× VPR's wirelength on the same netlists and graph.
4. **AMD 7-series-style frame configuration** (M13): sync word, type-1/2 packets, CRC-32C over `{register, data}`, FAR auto-increment, readback. The chain is kept beside it. M7's −1102 ns timing failure was analysed and closed.
5. **Partial reconfiguration of a running design** (M14). AGHIGH freezes the user clock, only the changed frames are written, and LFRM releases after the CRC matches. Every register keeps its state.
6. **BRAM contents inside the configuration stream** (M15), under the same CRC.
7. **The 16 → 36 CLB grid** (M12b) was paid for by streaming the chain through one frame buffer instead of a full-width shift register. On Vivado the whole design is even smaller than M13 (10 411 vs 11 607 LUTs).

---

## 2. What was asked, and the rules of the work

**Goal (M0).** Build "bob", a complete FPGA inside the PYNQ-Z2's XC7Z020 PL, configured over JTAG from a Pico. The flow is Verilog → yosys → VPR → bitgen. It started from `/Users/sk/work/bob/`: a hardware-proven 4×4 CLB fabric with a 2896-bit chain and 174 simulation checks. That tree was copied whole into `bob_full_v1/` and frozen.

**Order of work** (the user's decisions):
1. configuration registers (scan chain)
2. BRAM
3. DSP
4. fabric
5. PnR with VPR
6. bitstream
7. frames last

Later requests added:
- Python PnR (M12a)
- frames with the chain kept (M13), plus M7's timing
- "everything till M15": area and a bigger grid, partial reconfiguration, BRAM content frames, with Vivado not crashing
- this report

**Rules that shaped every milestone** (PLAN.md §3):

| rule | effect on the work |
|---|---|
| One milestone at a time; stop for the user's go-ahead | Every milestone has a "done when" and a board test before the next starts (M12b/M14/M15 were built together at the user's request, with one board test) |
| Every milestone ends with a PYNQ-Z2 test (`make hwtest M=Mx`) | 56 logged board runs; simulation never closed a milestone |
| Every Vivado build is the complete FPGA | No standalone block bitstreams after M2; each board test runs the full regression |
| Tested references first (AMD UG470/473/474/479, OpenFPGA/VPR) | Instruction codes, packet format, CRC, startup, CLB/BRAM/DSP semantics and the routing architecture come from them; divergences are listed (§20) |
| Vivado runs on the user's Windows PC; one `hw/` folder is copied over; the project is reused | `hw/scripts/build.tcl` syncs sources, reuses the project, rebuilds on a fingerprint change, and writes reports to `out/<tag>/` |
| Guidance and time for anything done by hand | Checklists in `docs/hwtest/Mx.md`; guided live checks with goals and a status line (M11) |
| Git: commit as you go, tag `mN` only after a board pass; never commit the user's `.tex` report | Tags `m7`…`m13` |

---

## 3. System overview: two flows, three machines

```
 ┌──────────────────────────── Mac ─────────────────────────────┐        ┌──────── Windows PC ────────┐
 │  GUEST FLOW (ours)                                            │        │  HOST FLOW (AMD)            │
 │  design.v ─ yosys ─ VPR / bob PnR ─ FASM ─ bitgen ─ .bit      │        │  hw/ (bob RTL) ─ Vivado ─   │
 │                                   │                           │        │  bob_top.bit (XC7Z020)      │
 │  host/: cfgplane, hwtest ─ USB ─ Pico (DirtyJTAG) ──JTAG──┐   │        └──────────────┬──────────────┘
 └───────────────────────────────────────────────────────────┼───┘                       │ program once
                                                             ▼                            ▼
                              ┌──────────── PYNQ-Z2: XC7Z020 PL ─────────────────────────────────┐
                              │  bob_top ─ BUFG sysclk 125 MHz                                    │
                              │   bob_fpga: jtag_tap6 · cfg_frames · cfg_ctrl · cfg_store ·       │
                              │             clock_ctrl · capture · bram_jtag · dsp_jtag · BSR     │
                              │   bob_fabric (generated): 36 CLB · 2 BRAM · 2 DSP · 28 pads ·     │
                              │                           1723 routing muxes                      │
                              │  SW0 SW1 BTN0–3 → pads          pads → LD0–LD2, LD3 = DONE         │
                              └──────────────────────────────────────────────────────────────────┘
```

- **Host flow.** bob's RTL goes through Vivado to an AMD bitstream for the XC7Z020. Once it is programmed, the PL *is* bob. It is rebuilt only when bob's hardware changes: M0–M7, M13 and M15.
- **Guest flow.** A user design goes through bob's tools to a bob `.bit`, loaded over JTAG into the running fabric. No Vivado and no rebuild; M8–M12a used the M7 bitstream unchanged.
- **Wiring.** The Pico runs DirtyJTAG and connects to PMODA (TCK, TMS, TDI, TDO, GND). `host/dirtyjtag.py` drives it and refuses TCK above 100 kHz from M13.

---

## 4. Timeline and status of every milestone

M0–M6 were built on 2026-09-14 and M7–M15 on 2026-09-16/17.

| M | what was built | hardware result | host bitstream |
|---|---|---|---|
| M0 | Whole-tree copy; `hw/` layout; adaptable `build.tcl` (project reuse, fingerprint, stub-tested); `sources.f`; `hwtest.py`; Makefile. Found the inherited Tcl-in-XDC bug | idcode, bypass, selftest 11/11, showcase-live; 4341 LUT / 5910 FF, WNS +67.3 ns | `0x3BEEF093` |
| M1 | `tools/bob/device.py`: single source of truth → `device.json`, `bob_params.vh`; bitstream engine driven by it | chain-length 2896 measured on the board | reused |
| M2 | Configuration plane: 6-bit AMD IR, CFG_IN/OUT chain with shift + shadow, CRC-32C + length guard with a write key, JPROGRAM/JSTART startup, CAPTURE; standalone test top | 11/11; 175 LUT / 423 FF | `0x4BEEF093` |
| M3 | The plane in the 4×4 fabric; host loader with per-pulse fallback | 12/12; 3951 LUT / 6115 FF, WNS +63.9 ns | `0x5BEEF093` |
| M4 | CLB core per UG474 (routable CE/SR, FDRE/FDSE priority, LUT size K as a parameter); ctrl tile; user clock on sysclk with gce | 16/16 (first run: a check leaked the real switches into CE/SR); WNS +0.84 ns on 8 ns | `0x6BEEF093` |
| M5 | BRAM per UG473 (1024×18 TDP, write modes, DOx_REG); USER4 contents register | 19/20: every BRAM check passed except `bram-rom`, whose script crashed formatting its message; fixed, and it passed on the board inside the M6 run | `0x7BEEF093` |
| M6 | DSP per UG479 trimmed (A25/B18/D25, pre-adder, 25×18, P48, 4 opmodes, cascade); private DSP instruction | 23/23 (includes the M5 BRAM checks) | `0x8BEEF093` |
| M7 | Heterogeneous fabric **generated from VPR's rr graph** (OpenFPGA method); 16-CLB board profile; boundary 2 cells per pad | 26/26; 7670 LUT / 10362 FF / 2 RAMB18 / 2 DSP48E1; **WNS −1102 ns** (hardware correct) | `0xABEEF093` |
| M8 | yosys synthesis to bob cells; equivalence source == netlist; M8 hand placer | 10/10, no rebuild | M7 |
| M9 | VPR pack/place/route on the committed rr graph; FASM from VPR results | 10/10 | M7 |
| M10 | bitgen (FASM ⇄ chain, `.bit` v2), `bob build/load`, `.pcf` pins, golden netlist, co-simulation | 11/11 | M7 |
| M11 | Real designs live: free-running clock, real switches, RAM readback, clock-rate check, FIR on both DSPs | 12/12 on the 5th run (stale BRAM words and too-short live checks fixed; one USB disconnect) | M7 |
| M12a | bob's own pack (VPR patterns), annealing placer, PathFinder router; compared with VPR | 15/15, wirelength 0.99× VPR (16-CLB grid) | M7 |
| M13 | UG470-style frames on CFG_IN/CFG_OUT, chain moved to CHAIN_IN/CHAIN_OUT; M7 timing analysed and fixed; four Vivado synthesis crashes diagnosed | **39/39**; 11 607 LUT / 12 287 FF; **WNS +0.877 ns**, WHS +0.030 ns | `0xBBEEF093` |
| M12b | Chain streamed through one frame buffer (−3.6k LUT, −4.8k FF); 8×6 core, 36 CLBs; `wide` example (31 CLBs) | **48/48 in the M15 build**: bob-wide, pnr-wide (31 CLBs) | (C, in M15) |
| M14 | Partial reconfiguration: AGHIGH/GHIGH_B freeze, changed frames only, LFRM after CRC; `bob load --partial` | **48/48 in the M15 build**: partial-swap, partial-live, partial-bad-crc, partial-guest | (D, in M15) |
| M15 | BRAM contents as FAR block type 001 frames, one CRC-covered stream | **48/48**: frames-bram-load, frames-bram-live-refused, ram-readback-frames + full regression; 10 411 LUT / 11 097 FF / 2 RAMB18 / 2 DSP48E1; **WNS +0.585 ns**, WHS +0.065 ns; synthesis 5.1 min at 2.0 GB | `0xEBEEF093` |

---

## 5. The device

### 5.1 Grid and blocks

The architecture is written once in `tools/bob/device.py` (`ARCH_8X6` from M12b; `ARCH_6X4` for M7–M13).
- `vpr_arch.py` turns it into a VPR architecture XML.
- VPR (OpenFPGA's Docker image) builds the **tileable routing-resource graph**, which is committed with a sha256 stamp.
- `device.py` + `fabric_gen.py` then generate everything else from that graph: `bob_fabric.v`, `bob_params.vh`, `device.json` (every field, mux and frame), and the models.

| | M7–M13 (`ARCH_6X4`) | M12b onward (`ARCH_8X6`) |
|---|---|---|
| VPR grid (with I/O ring) | 8 × 6 | 10 × 8 |
| CLBs | 16 (x = 1, 2, 4, 5) | 36 (x = 1, 2, 4, 5, 7, 8) |
| BRAM | 2 × 1024×18, x = 3, height 2 | 2, x = 3, height 3 |
| DSP | 2 slices, x = 6, height 2, PCOUT→PCIN | 2, x = 6, height 3 |
| Pads | 20 | 28 |
| Routing | L4 unidirectional, W = 24, Wilton Fs = 3, fc_in 0.15 / fc_out 0.10 | same |
| Routing muxes | 1095 | 1723 |
| Configuration bits | 4216 (M7–M12) → 4992 = 39 frames (M13) | 8320 = 65 frames |
| Boundary cells | 40 | 56 |

The 8×8 profile (48 CLBs, 9400 bits) built at M7 is frozen in `release/M7_8x8/`. Its synthesis took over 30 minutes with the XDC in synthesis, the setting later found to crash Vivado.

### 5.2 CLB (UG474)

One BLE per CLB, **71 configuration bits** at K = 6:
- **INIT (64 bits):** a LUT6_2-style fracturable LUT (`lutk.sv`). O6 is the full function; O5 is the K−1 subtree.
- **Carry:** MUXCY/XORCY (`cy_en`, `cy_di_sel`), with a carry direct up each column.
- **Flip-flop:** FDRE/FDSE semantics (`ff_en`, `ff_rstval`); routable CE and SR (`ff_ce_en`, `ff_sr_en`); synchronous SR beats CE; `ff_d_sel` chooses O5/O6.
- **Global gating:** GSR sets the INIT value; GWE and **gce** (the user clock enable) gate every change.

The LUT size K is a parameter throughout. `make check` also runs the fabric testbench at K = 4 (23 CLB bits, 6016 configuration bits).

VPR sees the CLB as a `clb` pb_type with two modes, as OpenFPGA's fle has:
- `logic`: `.names` LUT → `bob_ff`
- `arithmetic`: `bob_add` → `bob_ff`, with pack patterns `ble` and `chain`

### 5.3 BRAM (UG473 subset)

- **Memory:** `bram_core.v` is 1024 × 18 true dual port in Vivado's READ_FIRST template, so it maps to one RAMB18. WRITE_FIRST and NO_CHANGE are rebuilt with registers, which makes the write mode a configuration bit.
- **Per port:** DOA/DOB_REG, EN, RST, REGCE.
- **Configuration (8 bits):** `wmode_a`, `wmode_b`, `reg_a`, `reg_b`, `jtag_a`, `jtag_b`. The jtag bits let USER4 drive a port's pins, for stepping write modes cycle by cycle.
- **Contents:** separate from the configuration, as in UG470. They load over USER4, or from M15 as FAR block type 001 frames, only while GWE = 0, and they survive JPROGRAM.
- **Trimmed:** 9/4/1-bit width modes, per-byte WE, separate RSTRAM/RSTREG.

### 5.4 DSP (UG479 trimmed)

- **Datapath:** `dsp_core.v`: A25, B18, C48, D25; pre-adder D±A; 25×18 signed multiplier; P48.
- **Opmodes:** M, M+C, P+M, (PCIN>>>17)+M.
- **Registers:** AREG/BREG/CREG/DREG/MREG/PREG as configuration bits; CE/RST in four groups; slice 1's PCIN = slice 0's P.
- **Configuration:** 16 bits per slice.
- **JTAG:** a private instruction drives any bus from JTAG and reads both P values.
- **Trimmed:** dynamic OPMODE/INMODE/ALUMODE, other ALU functions, the 30-bit A port, pattern detect, CARRYIN.

### 5.5 Routing and I/O

Every CHANX, CHANY and IPIN node with driving edges in the rr graph is a `bob_mux`:
- value 0 = const0
- IPIN value 1 = const1
- then the drivers in ascending node id
- width = the smallest that fits; out-of-range values read 0

An all-zero configuration is a dark, loop-free fabric. IPINs driven only by an OPIN are VPR directs (the carry chains, the DSP cascade): plain wires with no bits.

**Pads.** An I/O block is one VPR pad (outpad IPIN mux, inpad OPIN) plus two boundary cells. GTS forces outputs to 0; board pins have fixed directions, so there is no true tristate. The board's switches, buttons and LEDs sit on fixed pads (`device.json` `pads`). Every other pad is reachable only by boundary scan.

---

## 6. JTAG: the TAP and the instruction set

`jtag_tap6.v` has an IEEE 1149.1 state machine with a 6-bit IR using **AMD 7-series codes** where they exist:

| code | name | use |
|---|---|---|
| `001001` | IDCODE | `0x?BEEF093`, version nibble = build |
| `001000` | USERCODE | milestone number |
| `000001` / `100110` | SAMPLE / EXTEST | boundary scan |
| `000111` | INTEST (private) | boundary cells drive the fabric inputs |
| `000010` | USER1 | ce, sr, cin, step, autostep; status of the first 16 CLB outputs |
| `000011` | USER2 = CFG_CTRL | 64-bit chain CRC/status register with a write key |
| `100010` | USER3 = CAPTURE | snapshot of every CLB output |
| `100011` | USER4 | BRAM contents / drive / SELECT |
| `101000` | DSP (private) | DSP drive and P readback |
| `000101` / `000100` | CFG_IN / CFG_OUT | M13: packet streams (up to M12: the chain) |
| `110101` / `110100` | CHAIN_IN / CHAIN_OUT (private) | M13: the chain |
| `001011` / `001100` | JPROGRAM / JSTART | clear / startup |
| `111111` | BYPASS | |

- **Capture-IR** returns `{DONE, INIT_B, COMMITTED, CRC_ERR, 0, 1}`, so any IR scan is a status read. Bits 5 and 4 match where 7-series tools read DONE and INIT_B.
- **Timing contract** (proven on hardware, unchanged since the original bob):
  - TMS/TDI are sampled on the rising edge; TDO and updates happen on the falling edge.
  - Every shift register is LSB-first.
  - Test-Logic-Reset is consumed only synchronously and never touches configuration.

---

## 7. Configuration I: the scan chain (M2–M12b)

### 7.1 M2–M13: shift + shadow (OpenFPGA `scan_chain`, Aegis)

- **Structure:** each tile had a shift register and a shadow register, and the fabric saw only the shadow (`cfg_tile_sr.v`, `cfg_mem.v`).
- **Capture-DR** loaded shift ← shadow, so readback was non-destructive.
- **Update-DR** of CFG_IN committed shift → shadow **only if** exactly W bits had been shifted and the bit-serial CRC-32C matched the expected CRC.
- **Expected CRC:** written into CFG_CTRL behind the key `0xC5`.
- **CRC definition:** Castagnoli, reflected `0x82F63B78`, init and final XOR `0xFFFFFFFF`, check value `0xE3069283`. The non-zero init means a stuck-low TDI cannot match.

**Host sequence:** JPROGRAM → CFG_CTRL (key, CRC) → CFG_IN (W bits) → CFG_CTRL read (COMMITTED, CRC_OK, count) → CFG_OUT readback == word → JSTART + 12 TCK → DONE.

**Mutation tests** (`sim/mutate_cfg.sh`) prove each guard is tested: CRC polynomial, CRC guard, length guard, write key, and startup without commit. The first run of this suite found that the length check could be deleted without any test noticing.

**Rule added at M13:** the chain commits only while GWE = 0, so a running design is never reconfigured underneath itself.

### 7.2 M12b: streamed through one frame buffer

At M13 `cfg_store.v` kept the W-bit shift register beside the W-bit memory, with a data mux per bit. That cost W flip-flops and W LUTs: in yosys, 5.1k LUT and 10.0k FF of the whole design's 15.4k / 12.2k.

From M12b the store has **one 128-bit frame buffer**:

| scan | what happens |
|---|---|
| Capture-DR | frame counter ← 0; CHAIN_OUT loads frame 0 into the buffer |
| Shift-DR, CHAIN_IN | bits enter LSB first; every 128th bit completes frame n, written on the next falling edge **only while GWE = 0** |
| Shift-DR, CHAIN_OUT | the buffer shifts out and reloads the next frame every 128 bits; after the last frame it is a 128-bit delay line from TDI |
| Update-DR, CHAIN_IN | COMMITTED / CRC_OK only if count = W and the CRC matches; otherwise CRC_ERR / LEN_ERR and JSTART refuses |

- **Semantics now match the frame path (UG470):** bits land as they arrive and the CRC gates startup. A bad chain leaves new bits in memory but never runs.
- **The read mux** is one frame-wide mux, shared with FDRO.
- **Length measurement:** a pure shift register passes a marker after W bits, but the streamed chain would overwrite it. `cfgplane.measure_chain` now shifts a 32-bit marker *repeated*; from bit W on, output equals input (a delay of 128 = 4 × 32), so the first position from which output == input is W. It works on both designs.

---

## 8. Configuration II: frames and packets (M13)

### 8.1 Memory layout

The memory is cut into **frames of 4 × 32 = 128 bits**, column by column as in 7-series devices:
- FAR column 0 is the ctrl tile.
- FAR column x+1 is grid column x, bottom to top, padded to whole frames.

**The chain is exactly all frames end to end**, so one `.bit` word loads identically on either path, and `frames-vs-chain` checks both directions on the board.

### 8.2 Stream format (UG470 chapter 5)

- **Framing:** words are MSB first over CFG_IN. The controller hunts bit by bit for the sync word `0xAA995566`. Words may span DR scans. DESYNC or JPROGRAM returns to hunting.
- **Headers:** type-1 `001 op reg[17:13] count[10:0]` and type-2 `010 op count[26:0]`, as the 7-series FDRI idiom `30004000 5000xxxx` uses.
- **Registers:** CRC 0, FAR 1, FDRI 2, FDRO 3, CMD 4, STAT 7, IDCODE 12.
- **Commands:** NULL, WCFG, LFRM, RCFG, START, RCRC, AGHIGH (M14), DESYNC.
- **CRC:** CRC-32C, init 0, over the 37 bits `{reg[4:0], data}` of every WRITE data word except CRC's own (prjxray `crc.py`). CRC match sets CRC_OK; a mismatch sets CRC_ERROR and parks the parser.
- **FAR:** `[25:23]` block type, `[22:17]` row, `[16:7]` column, `[6:0]` minor, with auto-increment.
- **FDRI:** the 4th word writes the frame **immediately**, so bitstreams need no pad frame and readback returns none.
- **Write guards:** writes need WCFG, a matched IDCODE, no error and GWE = 0 (or an acknowledged freeze, M14). START needs CRC_OK *after* the last FDRI word.
- **STAT (32 bits),** positions following 7-series where the meaning exists:
  - CRC_ERROR, GTS_CFG_B, GWE, GHIGH_B (M14), INIT_COMPLETE, INIT_B, DONE, ID_ERROR
  - version (`0x13`/`0x14`/`0x15`)
  - PKT_ERROR, WR_ERROR, SYNCED, WCFG, CRC_OK, GSR, START_OK, RCFG
- **Readback:** READ packets queue words; each CFG_OUT scan shifts them out MSB first; with nothing queued CFG_OUT returns STAT. FDRO needs RCFG.

**Load stream** (`packets.load_stream`):

```
FFFFFFFF FFFFFFFF AA995566 20000000          dummy, dummy, sync, NOP
30008001 00000007 20000000                   CMD <- RCRC
30018001 EBEEF093                            IDCODE
30002001 00000000                            FAR <- 0
30008001 00000001 20000000                   CMD <- WCFG
30004000 50000104 <260 words>                FDRI: 65 frames
30002001 00800000 30004000 50000400 <1024>   M15: FAR <- BRAM b, FDRI contents   (per used BRAM)
30000001 <CRC>                               CRC
30008001 00000003 / 00000005 / 0000000D      LFRM, START, DESYNC
```

### 8.3 Implementation

**`cfg_frames.v`** is the parser: HDR / T2 / DATA / ERR states, the register file, FAR decode through a generated column table, frame writes, the readback queue and STAT.

**`cfg_store.v`** is the memory and both write paths. Its first version wrote `cfg[frame_idx*128 +: 128] <= data` over the whole memory. That synthesises as a barrel shifter (~12k LUTs, 1.7 GB in yosys), and Vivado ran out of memory. The rule since: **never a computed part-select over the configuration memory; decode per frame.** Each memory bit is a plain clock-enabled flip-flop with its D input from the one buffer.

**`tools/bob/packets.py`** builds every stream. Its `Controller` class is a **bit-level Python model** of `cfg_frames.v`, and every expected STAT value, memory and readback word in `tb_frames` comes from it, never from the RTL.

---

## 9. Configuration III: partial reconfiguration (M14)

7-series devices reconfigure part of a running design by writing only that region's frames, with GHIGH_B asserted around the write (UG470 CMD AGHIGH, DGHIGH/LFRM; UG909 for the flow). bob uses the same command sequence. What bob's GHIGH_B holds is its user clock.

```
 TCK domain                                   sysclk domain
 CMD AGHIGH (IDCODE matched) ─ freeze ──2FF──► clock_ctrl: gce forced 0, frozen = 1 (same edge)
 STAT GHIGH_B = 0  ◄──────────────────2FF──── frozen
 FAR/FDRI changed frames → cfg_store (every fabric register has CE = 0: bits change under a held enable)
 CRC, CMD LFRM: CRC_OK ─ freeze = 0 ───2FF──► gce resumes; frozen = 0 → GHIGH_B = 1
            no/bad CRC ─ WR_ERROR / CRC_ERROR, stays frozen; only JPROGRAM + a full load recover
```

- **Why the state is kept exactly.** Every fabric register (CLB flip-flops, BRAM, DSP) changes only when gce is high. `tb_clock_gap` [4] proves gce never pulses while frozen, in either clock mode, even with step requests arriving.
- **Host side:**
  - `cfgplane.load_partial` reads the current memory over CHAIN_OUT, which is non-destructive.
  - `packets.partial_streams(old, new)` builds a freeze scan and a frames scan with one FAR + FDRI per run of changed frames.
  - The host requires GHIGH_B = 0 before sending frames, and GHIGH_B = 1 plus CHAIN_OUT == new afterwards.
  - `bob load --partial x.bit` runs it.
- **Cost:** a one-LUT change is 1 frame of 65; re-routing `gates` into `gates_swapped` touches 26.
- **Refusals** (each tested in RTL and by a mutant):
  - AGHIGH without IDCODE
  - frames while running without a freeze
  - frames before the acknowledgement: the testbench stops sysclk during long scans, which showed the acknowledgement guard working before it was a planned test
  - LFRM without a CRC
  - a bad CRC
- **Not in M14:** region protection (the host decides which frames), BRAM writes while frozen, pad hold during the write.

---

## 10. Configuration IV: BRAM contents as frames (M15)

UG470 carries BRAM initial contents in the bitstream as their own block type. From M15 bob does too:

| | |
|---|---|
| FAR | block type `001`, column = BRAM index, frame n = row × 128 + minor, n = 0..255 |
| frame n | BRAM addresses 4n .. 4n+3, word = `{14'b0, data[17:0]}` |
| auto-increment | n+1, then frame 0 of the next BRAM, then invalid |
| write | WCFG, IDCODE, no error, **GWE = 0**; the 4th word toggles a request to `bram_jtag.v`'s sysclk sequencer, which writes the 4 words through the port USER4 uses |
| read | FDRO with RCFG and GWE = 0; the controller prefetches the frame FAR points at (the next word is at least 32 TCK periods away) |
| host | `load_stream(word, brams)` writes all 1024 words of every used BRAM (contents survive JPROGRAM, so a skipped word would keep the last design's value, which was the M11 bug) under the same CRC, and `load_frames` reads them back |
| kept | USER4, used by `bob load --mode chain` |

**Timing rule 4** (bitstream-format §11): content-frame requests are at least 32 TCK periods apart (320 µs at 100 kHz), and the sysclk side needs about 12 cycles.

---

## 11. Startup, user clock, CAPTURE and the hard-block registers

**Startup (UG470).** After power-up or JPROGRAM:
- memory = 0; GSR = 1, GTS = 1, GWE = 0, DONE = 0
- JSTART advances one phase per TCK in Run-Test/Idle (the host clocks 12), only after a committed chain or an accepted START: GSR ← 0 → GTS ← 0 → GWE ← 1 → DONE ← 1 (LD3)

**User clock (`clock_ctrl.v`).** The fabric runs on the 125 MHz sysclk with **gce** as the user clock (UG949 prefers an enable over a derived clock).
- **Modes:** `clk_mode` 0 is one step per TCK edge while USER1 ce (plus step/autostep, used for cycle-exact INTEST checks); `clk_mode` 1 is free-running, one enable every 2^(div+8) cycles.
- **Synchronisers:** every TCK-domain control reaches it through two-flop ASYNC_REG synchronisers.
- **Gap guard (M13):** gce pulses are at least 256 sysclk cycles apart in both modes, which is what makes the fabric's 256-cycle multicycle true.
- **Freeze (M14):** the handshake described in §9.

**CAPTURE (USER3)** snapshots every CLB output, and for a flip-flop CLB that is the register. M10 compares every register with the golden netlist after every user clock. **SAMPLE** takes pins and LEDs in one Capture-DR, which the live checks use.

**USER4** handles BRAM contents (LOAD_PTR, WRITE, READ only while GWE = 0), a drive word per BRAM, and SELECT. **DSP register:** a 248-bit drive word and both P values.

---

## 12. The guest tool flow: Verilog to a running design

```
design.v ─► synth.py (yosys) ─► equiv.py ─► vpr_run.prepare ─► VPR (Docker)  ─► fasm_from_vpr ─► bitgen ─► .bit ─► cli.load
             bob cells           source ==     eblif, pins,      or pnr/ (M12a)   features +        chain,    v2     frames / chain,
             $lut BOB_ADD         netlist ==    constants,        .net .place      legality +        CRC,             BRAM, readback,
             BOB_FDRE/FDSE        golden        carry cuts,       .route           model == trace    sections         JSTART
             BOB_BRAM18 BOB_DSP   (trace.json)  buffers
```

| stage | tool | what it guarantees |
|---|---|---|
| synthesis | `tools/bob/synth.py`: the `synth_xilinx` pass order with bob maps; `mul2dsp` 25×18; `memory_libmap` with bob's BRAM; `$alu` → `BOB_ADD`; `dfflegalize`; `abc -lut K` | only bob cells; one clock; no latches or async resets |
| equivalence | `tools/bob/equiv.py` | source, yosys netlist and **golden netlist** (`golden.py`: one named wire per bit) simulated together over biased random vectors (50-cycle segments, because uniform inputs held the counter's reset half the time and its trace was all zeros); the trace and every golden net after every clock are saved |
| netlist rewrite | `vpr_run.prepare` | constants → IPIN const0/const1; carry chains cut to the column height with generator and tap CLBs; FF D buffers; `.pcf` pins |
| place and route | VPR 9 in OpenFPGA's Docker image on the committed rr graph (`--read_rr_graph`, fixed seed, `--fix_clusters` pins), or bob's PnR | results committed with stamps (arch sha, eblif sha, seed, image digest, result hash); the same seed repeats |
| FASM | `fasm_from_vpr.py` | `.net` → LUT INIT through VPR's port rotation, adder and FF flags; `.route` → each node selects its predecessor; legality against `device.json`; **`model.py` with those bits == the source trace** |
| bitgen | `bitgen.py` | FASM ⇄ chain exact both ways (refuses bits no feature owns); `.bit` v2 = header + chain + `BRAM` and `META` sections + file CRC |
| load | `cli.load`, `cfgplane` | frames (default) or chain; readback == `.bit`; BRAM contents (frames from M15); JSTART; DONE |

**Examples** (`examples/`):
- gates, adder, counter, blinky, ram, mult
- switches and fir (M11)
- `gates_swapped.pcf` (pins)
- **wide** (M12b: 12-bit counter + 8-bit LFSR, **31 CLBs**)

On the 36-CLB graph VPR routes all 10 designs with total wirelength 2162, and bob's PnR gets 2015 (§13).

---

## 13. bob's own place and route (M12a)

`tools/bob/pnr/` reads the same prepared netlist and writes VPR-format `.net/.place/.route`, so everything after PnR is shared with VPR.

- **pack:** VPR's `ble` and `chain` patterns; carry chains as macros.
- **place:** simulated annealing with VPR's schedule (T0 = 20σ, 10·N^(4/3) moves, α by acceptance, range limit); half-perimeter bounding-box cost; macro moves; legality checks; fixed seed.
- **route:** PathFinder negotiated congestion (present × history cost) with A* on the rr graph.
  - A sink may be any of a LUT's equivalent inputs; the chosen pin sets the port rotation, which is why LUT-heavy designs beat VPR's wirelength.
  - Rip-up and reroute until no node is shared.

Results (`docs/reports/M12b/pnr_vs_vpr.md`, 36-CLB graph, seed 1):

| design | CLBs | wirelength VPR / bob | ratio | bob time |
|---|---|---|---|---|
| gates | 3 | 154 / 100 | 0.65 | 0.07 s |
| adder | 4 | 77 / 100 | 1.30 | 0.08 s |
| counter | 9 | 201 / 191 | 0.95 | 0.11 s |
| blinky | 11 | 136 / 101 | 0.74 | 0.07 s |
| ram | BRAM | 112 / 127 | 1.13 | 0.02 s |
| mult | 7 + DSP | 175 / 191 | 1.09 | 0.16 s |
| switches | 6 | 144 / 100 | 0.69 | 0.10 s |
| fir | 10 + 2 DSP | 257 / 279 | 1.09 | 0.15 s |
| wide | 31 | 757 / 711 | 0.94 | 0.74 s |
| gates_swapped | 3 | 149 / 115 | 0.77 | 0.07 s |
| **total** | | **2162 / 2015** | **0.93** | |

**Bugs found while building it:**
- Route branches were written in sink order instead of tree order, so a parser attached branches to the wrong predecessor. The model check caught legal-but-wrong mux values.
- BRAM/DSP clock pins were counted as logic sinks.

**Not included:** timing-driven PnR.

---

## 14. Host software and the Pico

| module | role |
|---|---|
| `host/dirtyjtag.py` | Pico DirtyJTAG USB protocol: pulses, IR/DR shifts, bulk `CMD_XFER` (MSB-first per byte, handled), TCK ≤ 100 kHz enforced |
| `host/cfgplane.py` | everything on the configuration plane: IR codes, JPROGRAM/JSTART, CFG_CTRL, chain load with per-pulse fallback, `measure_chain`, CAPTURE, USER1, USER4 BRAM, DSP register, **frames** (`frames_send/read/stat/readback`, `load_frames(brams)`), **`load_partial`**, `bram_frames_read` |
| `host/bitstream.py`, `host/designs.py` | hand-built designs on the rr graph (BFS router): showcase, counter, BRAM ROM, DSP designs, pipeline, `d_partial` |
| `host/fpga.py` | boundary vectors, INTEST sweeps, SAMPLE, watch |
| `host/hwtest.py` | per-milestone hardware test: regression + new checks, `--list`, `--manual`, `--only`; guided live checks (M11); appends `docs/hwtest/results.log` |
| `tools/bob/cli.py` (`./bob`) | `build` (synth → equiv → PnR → FASM → model check → `.bit`), `load` (`--mode frames|chain`, `--partial`), `info`, `fasm` |
| `tools/bob/packets.py` | streams, `Controller` model, `dump` |

**The stand-in board** (`tests/test_hwtest_fake.py`) puts `model.py` and the frame `Controller` behind the same JTAG API. It models the chain, CFG_CTRL, frames, freeze and partial reloads with state kept, BRAM content frames, the free-running clock in real time, INTEST/SAMPLE/CAPTURE, USER4 and JPROGRAM.

Every hardware check runs on it first, with a passing board and a broken one:
- a corrupted CAPTURE
- a clock 1.5× too fast
- wrong BRAM contents
- a board that loses state on a partial reload
- a freeze that does not hold
- BRAM frames written while running

It found two of its own gaps on the way: it never modelled USER1 `cin`, and its free-running clock read the real switches during INTEST.

---

## 15. Verification

### 15.1 Layers

```
 references (UG470/473/474/479, OpenFPGA, VPR)
   └─ Python models: model.py (CLB, BRAM, DSP, whole fabric), packets.Controller, chainbits CRC
        └─ RTL testbenches with model-generated expectations (never RTL-derived)
             └─ mutation tests: each guard broken on purpose must fail a testbench
                  └─ golden co-simulation: source Verilog ∥ golden netlist ∥ complete FPGA RTL loaded from .bit
                       └─ stand-in board: every hardware check, passing and failing boards
                            └─ PYNQ-Z2: make hwtest M=Mx, full regression + new checks, logged
```

### 15.2 Simulation counts (last `make check`, current RTL)

| testbench | checks | what |
|---|---|---|
| `tb_clb` K = 6 | 7 040 | 128 flag combinations × vectors vs `model.py` |
| `tb_clb` K = 4 | 7 040 | same at K = 4 |
| `tb_bram` | 5 292 | write modes × DOx_REG × both ports vs `model.py` |
| `tb_dsp` | 1 344 | every opmode × pre-adder, 2-slice cascade |
| `tb_bob` (36 CLBs) | 852 | complete FPGA: IR, chain CRC/readback/length/GTS, 12 routed designs, corrupt chain, boundary, CAPTURE, GSR/GWE, CE/SR, counters, free-running clock, BRAM over USER4, DSP, pad→LUT→FF→BRAM→DSP→pad, 4 random netlists vs the model every clock |
| `tb_bob` K = 4 | 722 | same at K = 4 |
| `tb_cfg` | 180 | M2 configuration plane |
| `tb_synth` | 972 | 12 synthesised designs (hand-placed and VPR) vs source traces |
| `tb_cosim` | 5 220 | every example through VPR **and** bob's PnR: LEDs == source == golden before and after every edge, CAPTURE == golden registers |
| `tb_frames` | 71 | frames load/readback, split streams, every error, chain after frames, **partial reconfiguration** [13]–[17], **BRAM frames** [18]–[19] |
| `tb_clock_gap` | 11 | gce spacing in both modes, **freeze** |
| **total** | **28 744** | plus pytest **183** tests (device, layout, Tcl build script against a Vivado stub, LUT, model, CRC, synth, VPR, bitgen, PnR, reports, stand-in board) and verilator lint |

### 15.3 Mutation testing

| suite | mutants | examples |
|---|---|---|
| `mutate_cfg.sh` | 5 | CRC polynomial, CRC guard, length guard, write key, start without commit |
| `mutate_fabric.sh` | 25 | no GSR, no GWE freeze, gce ignored, CE not routed, step ignores CE, divider off by one, … |
| `mutate_frames.sh` | 29 | CRC never fails, CRC over data only, IDCODE unchecked, FDRI ignores GWE/WCFG, FAR not incrementing, START without CRC, type-2 without type-1, FDRO without RCFG, wrong sync, LSB-first readback, chain writes while running, frame write/load dropped, chain write dropped, chain readback without reload, gce gap ignored, pending step lost, **freeze ignored, LFRM ignores CRC, frames without the acknowledgement, AGHIGH without IDCODE, GHIGH_B stuck**, **BRAM frames while running, FAR not crossing BRAMs, readback word order, no prefetch, write address** |

Every mutant is killed. Two guards survived their first mutation run and got new scenarios:
- **M13:** "no CRC write" and "FDRO without RCFG" (FAR pointed at a non-zero frame).
- **M14:** "LFRM without a CRC" (a bad CRC stops the parser before LFRM is read) and "frames before the acknowledgement".

`tb_cosim` itself was mutation-checked at M10: a wrong golden net, a CRC-valid routing change, a missing source clock, unswapped pins, dropped BRAM contents and a wrong golden LUT all fail it.

### 15.4 Hardware checks

`host/hwtest.py` holds 15 milestone lists. **M15** runs the M13 regression and then its own checks:
- **M13 regression:** idcode, bypass, selftest; the M7 fabric checks through the chain (usercode, chain-length, IR status, CRC reject while live, GTS, GSR/GWE, CAPTURE vs USER1, JPROGRAM, CE/SR, counters, BRAM init/locked/ROM/modes/select, DSP modes/multiplier/accumulator, pipeline, 8-bit counter); five frame checks; the guest designs through frames; ram-readback; blinky-rate
- **M12b:** bob-wide, pnr-wide
- **M14:** partial-swap, partial-live, partial-bad-crc, partial-guest
- **M15:** frames-bram-load, frames-bram-live-refused, ram-readback-frames
- pipeline-live last

---

## 16. Hardware results

### 16.1 Board runs

`docs/hwtest/results.log` holds **57 runs** (514 passing check results); 20 runs passed completely and 37 had a failure. Every milestone M0–M15 ended with its checks passing on the board (M5's through the M6 run; M12b, M14 and M15 in the one M15 run, 48/48, first try). The failing runs, in order:

| when | what failed | cause | fix |
|---|---|---|---|
| M0, 8 runs | idcode 0xFFFFFFFF | board not yet programmed / TDO | program first; debug table in README |
| M4, 2 runs | ce-sr | USER1 ce = 1 before INTEST let the real switches reach CE/SR | sequential INTEST checks use autostep with ce off |
| M5, 7 runs | bram-rom | the check crashed formatting `'%03b'` (not a Python %-format), after a correct comparison | f-strings; a crash is reported as FAIL with the exception |
| M5–M7, 16 runs | idcode mismatch / 0x00000000 / 0xFFFFFFFF | tests run before programming the new bitstream | hwtest prints the expected IDCODE; build tag per milestone |
| M11, 4 runs | ram-readback; bob-fir once; USB disconnect once | BRAM contents survive JPROGRAM and `bob load` wrote only up to the last non-zero word; live checks too short | write all 1024 words of every used BRAM; guided live checks |

### 16.2 Vivado builds

| build | top | LUT | FF | RAMB18 | DSP | WNS (ns) | WHS (ns) | failing endpoints |
|---|---|---|---|---|---|---|---|---|
| M0/M1 | fpga4x4_top | 4 341 | 5 910 | 0 | 0 | +67.290 | +0.083 | 0 |
| M2 | cfg_test_top | 175 | 423 | 0 | 0 | +493.735 | +0.096 | 0 |
| M3 | fpga4x4_top | 3 951 | 6 115 | 0 | 0 | +63.874 | +0.082 | 0 |
| M4 | fpga4x4_top | 4 187 | 6 510 | 0 | 0 | +0.843 | +0.055 | 0 |
| M7 | bob_top (16 CLB) | 7 670 | 10 362 | 2 | 2 | **−1102.283** | +0.031 | 1858 |
| M13 | bob_top (16 CLB, frames) | 11 607 | 12 287 | 2 | 2 | **+0.877** | +0.030 | 0 |
| M15 | bob_top (36 CLB, partial, BRAM frames) | 10 411 | 11 097 | 2 | 2 | **+0.585** | +0.065 | 0 |

M5 and M6 reports were not copied into `docs/reports`. Their board tests passed, and `tests/test_reports.py` required RAMB18/DSP48E1 from them on.

---

## 17. Vivado: builds, timing and the synthesis crashes

### 17.1 The `hw/` bundle and `build.tcl`

`hw/` is the only folder copied to Windows (`E:\bob_full_v1\hw`). `hw/scripts/build.tcl`:
- opens the project in `bob_vivado/`, never recreating it
- syncs sources, constraints and sim sets to `sources.f` / `build.cfg`
- sets top, generics (IDCODE, USERCODE), include dirs and the synthesis directive
- rebuilds only on a content fingerprint change
- writes `bit`, `timing.rpt`, `util.rpt`, `drc.rpt`, logs and `build_info.txt` to `out/<tag>/`
- (M13) writes `sysclk_1cycle.txt` and keeps the XDC out of synthesis

It is tested on the Mac against a Vivado command stub (`tests/test_build_tcl.py`).

### 17.2 M7's timing, analysed at M13

The M7 build reported WNS −1102 ns, TNS −1 608 726 ns and 1858 failing endpoints, while the hardware test passed 26/26. The analysis of `docs/reports/M7/timing.rpt` found two things:

1. **sysclk paths through unconfigured routing loops.**
   - **The path:** fabric register → 1202 logic levels → BRAM, 1110 ns.
   - **Why the analyser reports it:** it cannot know a configuration, so it walks paths no legal, loop-free configuration uses.
   - **Why it escaped M7's constraints:** they named cells by patterns; synthesis flattened and renamed the source (`hold_qb_reg[17]_i_5__0`), and 120 cycles = 960 ns was too short anyway.
   - **Fix:**
     - `clock_ctrl.v` **guarantees** gce pulses ≥ 256 sysclk cycles apart in both modes (`tb_clock_gap`).
     - sysclk → sysclk is a 256-cycle multicycle **by clock**.
     - The only other sysclk logic, `u_clk` and `u_bram_jtag`, is held to one cycle by cell name, and `build.tcl` + `test_reports.py` verify that gce and the BRAM strobes were caught by that filter.
2. **A real TCK path:** IR / boundary → fabric → DSP JTAG capture, ~1650 ns under a 1 MHz constraint while the link runs at 100 kHz.
   - **Fix:** TCK constrained at 10 µs and `dirtyjtag.py` refuses faster.

**Rule:** configuration changes only while GWE = 0, or under an acknowledged freeze from M14. **Result at M13:** WNS +0.877 ns, WHS +0.030 ns, 0 failing endpoints.

### 17.3 The M13 synthesis crashes

| attempt | symptom | diagnosis | change |
|---|---|---|---|
| 1 | Vivado closed during synthesis | `cfg[idx*128 +: 128] <= data` over 4992 bits synthesised as a shifter (yosys: ~12.3k LUT, 1.7 GB) | frame loads into the buffer, per-frame write enables; FDRO an explicit word array |
| 2 | crashed again, same point in all three logged runs | died while breaking the fabric's timing loops after applying the XDC, before Technology Mapping; M7 had broken 51 045 loops fine. M13 had added `keep_hierarchy` on `u_fabric`, and Vivado then used `set_disable_timing` on the kept boundary | fabric flattened again; multicycle by clock |
| 3 | same crash | a `u_corei_2` partition still appeared: `keep_hierarchy` on the small `u_clk`/`u_bram_jtag` was enough | no `keep_hierarchy` anywhere; `sysclk_1cycle.txt` check added |
| 4 | same step, **and Windows restarted** | a program crash alone does not restart Windows, which pointed at the machine under load; the constant was XDC-driven loop breaking in synthesis | **`USED_IN_SYNTHESIS false` on the XDC**; implementation still reads every constraint |
| 5 | **built**: synthesis 3.5 min at 2.0 GB, implementation 2.5 GB, timing closed | all four changes together: per-frame writes, flattened fabric, clock-based multicycles, XDC in implementation only | M13 passed 39/39 on the board |

### 17.4 The M16 implementation failures

Synthesis was never the problem at M16 — the M13 rules held. Implementation failed twice, for
two unrelated reasons, and both are worth keeping.

| attempt | symptom | diagnosis | change |
|---|---|---|---|
| 1 | 3 h 25 min and still running: `phys_opt_design` 1 h 15 min, router at `[Route 35-447]` congestion, overlaps rising 25 551 → 30 325 → 34 608 | **WNS −465.7 ns / TNS −333 768 ns** on fabric flop → flop paths. The 256-cycle (2048 ns) multicycle stopped describing the fabric: the 12 × 10 static path through the unconfigured routing muxes is about 2500 ns. 8 × 6 fitted inside 2048 ns; 12 × 10 does not | **gce gap and XDC multicycle 8 → 9 (512 cycles, 4096 ns)** in `device.py` and `pynq_z2.xdc`, together, so the exception stays a fact |
| 2 | `route_design` stopped inside "Phase 2.3 Update Timing": no `ERROR:` line, log ending mid-phase, only `[Vivado 12-13638] Failed runs(s) : 'impl_1'`. Run by hand from the placed checkpoint it took Vivado itself down | a **threading fault in the timing engine**, not the design. The timer cuts every combinational loop in the routing mesh — M16 has one strongly connected component of **2146 routing wires with 11 270 independent cycles** against M15's 1018 / 4130 — and two threads doing that concurrently falls over. The same component that killed M13 attempts 2–4 | **`set_param general.maxThreads 1`** in the implementation TCL.PRE hook (`drc_waiver.tcl`), hooked on `opt_design`, `route_design` and `write_bitstream` |
| 3 | **built**: WNS +0.667 ns, 0 failing endpoints of 62 692, 20 498 LUT (38.5%) / 21 511 FF, DRC clean | both changes together | M16 passed 50/50 on the board |

Two details that cost time and are easy to forget:

- `launch_runs` runs implementation in a **separate process**. A `set_param` typed in the GUI's
  Tcl console, or set by the script that launches the run, never reaches it — it has to be in a
  `STEPS.*.TCL.PRE` hook.
- Vivado stores `STEPS.PHYS_OPT_DESIGN.IS_ENABLED` **in the project**. A run that turns a step
  off keeps it off until something turns it back on, so `build.tcl` now sets it explicitly
  rather than relying on the default.

The gap number is the lesson that generalises: **it is a function of the grid, not a constant.**
Grow the fabric and `GCE_MIN_GAP_SHIFT` grows with it, in `device.py` and the XDC together.

**Rules kept for every later build** (CLAUDE.md, PLAN.md):
- no computed part-select over the configuration memory
- no `keep_hierarchy`
- the XDC stays out of synthesis
- implementation runs single-threaded, and the gce gap covers the fabric's static path
- compare the whole-design yosys estimate (`tools/bob/synth_estimate.sh`) with the last successful build before a hand-off

The M15 RTL estimates at 15 941 LUT / 11 069 FF / 1.36 GB, against M13's 15 358 / 12 220 / 1.04 GB.

---

## 18. Area: where the logic went, and the 36-CLB grid (M12b)

The first step was to measure. A per-module yosys run on M13 (`synth_xilinx` without flattening; LUT / FF per module) showed:

| module (M13) | LUT | FF |
|---|---|---|
| `cfg_store` | 5 106 | 9 984 |
| `cfg_frames` | 2 649 | 325 |
| `dsp_core` ×2 (622 + 207 each) | 1 244 | 414 |
| `bram_jtag` 245/319, `dsp_jtag` 100/504, `cfg_ctrl` 123/155, `clock_ctrl` 83/92, `jtag_tap6` 73/108, `bram_core` ×2 180/112 | 984 | 1 402 |
| fabric (CLBs, muxes) | the rest | |
| **whole design (flattened)** | **15 358** | **12 220** |

Half the design was configuration bookkeeping. Candidates were weighed against that measurement (PLAN.md M12b):
- **ZUMA-style LUTRAM configuration:** big savings, but no parallel readback and a new write path.
- **Removing the shadow copy:** needs re-proving glitch-free loads.
- **Just building the 8×8 profile:** too slow before, with no savings.

The chosen change keeps every protocol on the wire unchanged and removes the full-width shift register (§7.2):

| | LUT | FF |
|---|---|---|
| `cfg_store` + `cfg_frames` at M13 | 7 755 | 10 309 |
| `cfg_store` + `cfg_frames` at M12b | 4 104 | 5 469 |

The saved logic bought the 8×6 core with **36 CLBs (2.25×)**. The whole-design estimate stays at M13's size: 15 762 LUT / 10 772 FF for M12b, and 15 941 / 11 069 with M14 and M15 added. `wide` needs 31 CLBs.

---

## 19. Problems found and how each was fixed

| # | where | problem | what happened | rule / fix |
|---|---|---|---|---|
| 1 | M0 | Tcl in the XDC | `if`/`set` skipped with a critical warning, `create_clock` never ran; "all constraints met" with TCK unconstrained | plain XDC only (`test_layout.py`); `test_reports.py` checks `no_clock (0)` |
| 2 | M0 | Tcl `expr` with hex strings | returned a decimal | never build display strings with `expr` |
| 3 | M0 | Vivado GUI Run Tcl Script | no `-tclargs` | `set bob_args {…}` before `source` |
| 4 | M0/M7 | OpenFPGA Docker on Apple silicon | no arm64 image; Colima shares only `$HOME`; image user cannot write mounts | `--platform linux/amd64`, `-u root`, work dirs under `build/` |
| 5 | M2 | a guard nobody tests | the length check could be deleted with tests passing | mutation tests (`make mutate`) |
| 6 | M4 | random configuration in simulation | a random chain built an oscillating loop; simulation time stopped | random muxes select out-of-range sources |
| 7 | M4 | checks leaking the real switches | USER1 ce = 1 before INTEST let SW reach CE/SR | autostep with ce off |
| 8 | M4/M7 | editing while the board test ran | tools had to be restored | freeze with git tags before starting N+1 |
| 9 | M5 | check-script crash | `'%03b' % g` | f-strings; crashes reported as FAIL |
| 10 | M7 | VPR pin locations on tall blocks | `SINK has no fanin` | custom pin locations |
| 11 | M7 | rr graph `ptc` | tileable CHAN nodes carry one track per position | parse ptc as a tuple |
| 12 | M7 | Verilator replication limit | `{W{1'b0}}` over the chain | `--replication-limit 65536` |
| 13 | M7 | timing −1102 ns | §17.2 | fixed at M13 |
| 14 | M8 | yosys cannot `import clb_pkg::*` | parse error | perl shim |
| 15 | M8 | generated identifiers `ref`, `before` | SystemVerilog keywords | avoid them |
| 16 | M8 | 18 432-digit BRAM INIT literal | iverilog scanner overflow | hex, x → 0 |
| 17 | M8 | yosys rule priority | `_90_bob_alu` lost to `_90_alu` | name it `_80_` |
| 18 | M8→M9 | weak random stimulus | counter trace all zeros: its check could never fail | biased 50-cycle segments; check trace coverage |
| 19 | M9 | VPR pack-pattern asserts | chain pattern without a primitive edge; pattern into a multi-mode ff | one `bob_ff`, `sumout → ff.D` in the pattern |
| 20 | M9 | `--fix_clusters` | "requires placement" | pass `--pack --place --route` explicitly |
| 21 | M9/M10 | non-reproducible result hashes | `.net` embeds paths and file names | strip paths, exclude the name |
| 22 | M10 | yosys `_syn.v` renames everything | nothing maps to fabric locations | `golden.py` names every bit |
| 23 | M10 | "dead" blinky | built with `--div 26` (one clock per 137 s) and never loaded | `bob build` prints the clock rate |
| 24 | M11 | stale BRAM words | contents survive JPROGRAM; only up to the last non-zero word was written | write all 1024 words of every used BRAM |
| 25 | M11 | live checks too short | 8 s saw one input vector | guided checks with goals, 90 s |
| 26 | M12a | route branch order | legal but wrong mux values | tree order |
| 27 | M13 | block order changed by column-major frames | broke `tb_bob`'s counter probes | frames column-major, blocks row-major |
| 28 | M13 | a Verilog macro defined twice | the expected data was sent as the stream | unique names |
| 29 | M13 | model state across scenarios | a fresh Python model forgot earlier streams | model scenarios in sequence |
| 30 | M13 | parser error state | a check read FDRO after a refused load | read over CHAIN_OUT |
| 31 | M13 | frame write as a part-select | Vivado out of memory | per-frame decode (§8.3) |
| 32 | M13 | `keep_hierarchy` | Vivado crashed breaking loops | none anywhere (§17.3) |
| 33 | M13 | XDC in synthesis | crash, then Windows restarted | XDC in implementation only |
| 34 | M12b | a marker can no longer pass the streamed chain | length check | repeated marker |
| 35 | M12b | `compare.py` overwrote M12's committed report | M12's 16-CLB results replaced by the 36-CLB run | per-milestone output path |
| 36 | M14 | freeze and frames in one scan | refused, because sysclk was stopped in the testbench | host protocol: freeze, STAT, frames; became scenario [17] |
| 37 | M14 | "LFRM ignores the CRC" survived | a bad CRC stops the parser before LFRM | scenario with no CRC at all |
| 38 | M15 | never-written BRAM addresses | X in simulation | read back only written frames |
| 39 | M15 | `list.index(FAR value)` | matched a configuration data word | build streams explicitly |
| 40 | M15 | stand-in board gaps | no USER1 `cin`; INTEST pads ignored by the free-running clock; USER4 read before startup | modelled |
| 41 | M15 | Python bit packing | quadratic on 70k-bit streams | string-based conversion |
| 42 | M12b | a fabric mutant pinned to a grid position | `carry-direct-cut` cut column 5's carry, but the full-column test counter moved to column 8 on the 36-CLB grid, so the mutant survived | cut the last CLB column (`designs.FULL_COL_X`) |

---

## 20. Where bob follows its references and where it diverges

| area | follows | diverges (and why) |
|---|---|---|
| CLB | UG474 LUT6_2 fracture, CARRY4 MUXCY/XORCY, FDRE/FDSE priority, routable CE/SR | 1 BLE per CLB (N10 is too many config flops for an XC7Z020); carry south→north |
| BRAM | UG473 synchronous read, write modes, DOx_REG, contents separate from config | only 1K×18; no per-byte WE; one RST |
| DSP | UG479 A25/B18/D25, pre-adder, 25×18, P48, register options, cascade | static opmodes (4), add-only ALU, no pattern detect / CARRYIN / 30-bit A |
| Routing | OpenFPGA `k6_frac_N10_tileable_adder_chain_dpram8K_dsp36`: tileable, L4 unidirectional, Wilton Fs 3, fc 0.15/0.10 | bob's BRAM/DSP pb_types and heights; custom pin locations |
| JTAG | 7-series instruction codes, Capture-IR DONE/INIT_B | private INTEST, DSP, CHAIN_IN/CHAIN_OUT codes |
| Chain | OpenFPGA `scan_chain`, Aegis shift + shadow; CRC before startup | M12b: streamed through one frame buffer |
| Frames | UG470 sync, packets, registers, CMD codes, FAR, CRC over {reg, data}, STAT positions, readback | frame written on its 4th word (no pad frame); frames of 4 words; no encryption/compression/COR/ECC/multiboot; parser error until JPROGRAM |
| Partial | UG470 AGHIGH, DGHIGH/LFRM, GHIGH_B; UG909 flow | freeze = user clock held (no interconnect contention in a mux fabric); release needs a CRC match; no region protection |
| BRAM frames | UG470 FAR block type 001 | frame = 4 addresses; no FAR crossing from type 0 to 1 |
| Startup | UG470 GSR → GTS → GWE → DONE, JSTART with 12 TCK | GTS forces 0 (no true tristate) |
| Timing | UG949 enables over derived clocks; UG903 exception precedence | multicycles justified by RTL guarantees |

---

## 21. Repository map and size

```
bob_full_v1/
  hw/          the Vivado bundle: src/{clb,core,tiles,fabric,top,generated}, tb/, constr/, scripts/build.tcl, build.cfg, sources.f
  tools/bob/   device.py vpr_arch.py rrgraph.py fabric_gen.py model.py chainbits.py packets.py synth.py equiv.py golden.py
               vpr_run.py fasm_from_vpr.py bitgen.py cli.py report.py pnr/ arch/ (rr graphs) vpr/ (VPR results)
  host/        dirtyjtag.py cfgplane.py bitstream.py designs.py fpga.py hwtest.py buildcfg.py + bring-up tools
  sim/         run_*.sh, gen_*vectors.py, gen_cosim.py, tb_cosim.v, mutate_{cfg,fabric,frames}.sh, lint.sh
  tests/       pytest (13 files)
  examples/    gates adder counter blinky ram mult switches fir wide + gates_swapped.pcf
  docs/        bitstream-format.md, hwtest/ (checklists, results.log), reports/, arch/ (arch.html sources), project/ (this report)
  release/     frozen bundles (hw_M3…hw_M7, mac_M6/M7, M7_8x8)
  arch.html project.html PLAN.md README.md REUSE.md CLAUDE.md Makefile bob
```

| language | lines (hand-written) |
|---|---|
| Python | 13 537 |
| Verilog | 6 301 |
| SystemVerilog | 385 |
| Markdown | 3 238 |
| JavaScript (arch pages) | 1 608 |
| Tcl | 880 |
| shell | 626 |
| XDC | 124 |
| generated fabric (`bob_fabric.v`, 36 CLBs) | 2 296 |

---

## 22. How to use it

```sh
make check                 # device files fresh, every simulation, lint, pytest - green before any hand-off
make mutate                # mutation suites
make rrgraph && make vpr   # after an architecture change (Docker/Colima)
make pnr                   # Python PnR vs VPR report
make hwtest M=M15          # the board test (interactive); ONLY=<check> reruns one

./bob build examples/counter.v [--pcf pins.pcf] [--clock run --div 15] [--pnr python] -o build/bit/counter.bit
./bob load build/bit/counter.bit                    # frames (BRAM contents in the stream)
./bob load build/bit/counter.bit --mode chain       # the chain (+ USER4)
./bob load build/bit/other.bit --partial            # M14: only the changed frames, design keeps running
tools/bob/packets.py dump build/bit/counter.bit     # annotated packet stream
tools/bob/synth_estimate.sh $PWD $PWD/build/est     # whole-design yosys estimate before a Vivado hand-off
python3 docs/arch/build.py --data                   # arch.html
python3 docs/project/collect.py && python3 docs/project/build.py   # this report's data and project.html
```

**Vivado (Windows):**
1. Replace `E:\bob_full_v1\hw` with this `hw/`.
2. Tools → Run Tcl Script → `hw/scripts/build.tcl`.
3. Program the board.
4. Copy `bob_vivado\out\<tag>\` to `docs/reports/<tag>/`.

---

## 23. Open items and what comes next

**Done:** every milestone M0–M15 passed on the PYNQ-Z2; tags `m7`…`m15`.

**Known limits:**
- **Timing-driven PnR:** VPR's timing uses the reference 40 nm delays, not the emulated fabric.
- **Partial reconfiguration:** no region protection, no BRAM writes while frozen, pads not held during the write.
- **FAR:** does not cross from configuration frames into BRAM frames.
- **I/O:** no true tristate or per-pad options.
- **CAPTURE:** covers CLB registers only (not BRAM/DSP internal registers).
- **Synthesis:** one clock domain for guest designs; no async resets or latches.

**Candidates:**
1. **Readback CRC / SEU scan:** a background CRC over the configuration memory reporting through STAT, as AMD's readback CRC does.
2. **Region-protected partial bitstreams:** `bob build --partial --region` with PnR constrained to a column range, and host checks that a partial touches only its region.
3. **ZUMA-style LUTRAM routing memory:** a larger area step for a bigger grid.
4. **Timing-driven placement** in bob's PnR with a delay model of the emulated fabric.
5. **A larger board device:** M15 uses 19.6% of the LUTs and 10.4% of the registers with 36 CLBs, synthesising in 5 minutes; a 64-CLB grid looks affordable.

---

## 24. References

- **AMD:**
  - UG470 7 Series FPGAs Configuration (JTAG instructions, packets, registers, CMD, FAR, STAT, startup, readback, AGHIGH/DGHIGH)
  - UG473 Memory Resources (RAMB18E1)
  - UG474 CLB (LUT6_2, CARRY4, FDRE/FDSE)
  - UG479 DSP48E1
  - UG903 Constraints (exception precedence)
  - UG949 Methodology (clock enables)
  - UG909 Dynamic Function eXchange
- **OpenFPGA:** architecture `k6_frac_N10_tileable_adder_chain_dpram8K_dsp36_fracff_40nm.xml`; configuration protocols `scan_chain`, `frame_based`; Docker image `ghcr.io/lnis-uofu/openfpga-master`.
- **VTR/VPR 9:** tileable rr graphs, `--read_rr_graph`, `--fix_clusters`, pack patterns (`prepack.cpp`).
- **Algorithms:**
  - V. Betz, J. Rose, "VPR: A New Packing, Placement and Routing Tool for FPGA Research", FPL 1997
  - L. McMurchie, C. Ebeling, "PathFinder: A Negotiation-Based Performance-Driven Router for FPGAs", FPGA 1995
- **Overlays:** A. Brant, G. Lemieux, "ZUMA: An Open FPGA Overlay Architecture", FCCM 2012; Aegis architecture notes (`configuration.md`, `io.md`, `clock.md`, read only).
- **Bitstream tooling:** prjxray / F4PGA (`crc.py`, FASM).
- **Tools:** yosys 0.69 (`synth_xilinx` structure), Icarus Verilog, Verilator 5.050, Vivado 2025.2, DirtyJTAG on a Raspberry Pi Pico.
