# bob, explained

**A guide to every part of the project: what it is, why it is built that way, how to use it, and how to tweak it.**

Companion documents: [`REPORT.md`](REPORT.md) is what was built and what happened; [`../bitstream-format.md`](../bitstream-format.md) is the exact specification; [`../../PLAN.md`](../../PLAN.md) is the working plan and status; [`../../arch.html`](../../arch.html) is the interactive die slice and [`../../project.html`](../../project.html) the interactive report. This guide is the one to read if you want to **understand and change** bob.

---

## 0. How to read this guide

- **§1–§2** give you the mental model and the vocabulary. Read them once, in order.
- **§3** is the reference: one entry per part, always in the same four steps — *What it is · Why this way · How to use it · How to tweak it* — plus where its code and tests live.
- **§4** is a cookbook of the changes people actually want to make.
- **§5** compares bob with OpenFPGA, Aegis, ZUMA and prjxray, honestly.
- **§6** is troubleshooting.

**Try this first** (needs the Mac tools; nothing else):

```sh
make check                                   # regenerate, simulate, lint, test: everything must be green
./bob build work/examples/counter/counter.v -o build/bit/counter.bit
./bob info build/bit/counter.bit             # what is in the file
./bob fasm build/bit/counter.bit | head      # the configuration as readable features
software/bob/packets.py dump build/bit/counter.bit | head -20   # the JTAG packet stream
```

With the board and the Pico attached:

```sh
./bob load build/bit/counter.bit             # frames (default)
make hwtest M=M16                            # the whole board test
```

---

## 1. The big picture

### 1.1 Two FPGAs

bob is an **FPGA implemented on an FPGA**. There are two of them, and two flows, and confusing them is the single most common mistake:

| | host FPGA | guest FPGA ("bob") |
|---|---|---|
| what it is | a real Xilinx XC7Z020 on a PYNQ-Z2 | our fabric, written in Verilog, running inside it |
| its bitstream | `bob_top.bit`, made by Vivado | `counter.bit`, made by bob's own tools |
| its tools | Vivado (on a Windows PC) | yosys + VPR (or bob's PnR) + FASM + bitgen, on the Mac |
| how it is loaded | Vivado programmes the board once | over JTAG from the Pico, in a second, as often as you like |
| when it changes | only when bob's hardware changes (M0–M7, M13, M15, M16) | every time you build a design |

Everything in §3 belongs to one of these two flows. When something is confusing, ask: *whose bitstream is this?*

### 1.2 What a (guest) FPGA is made of

An FPGA is four things:

1. **Logic blocks** that compute — here a CLB: one LUT6 with a carry chain and a flip-flop.
2. **Hard blocks** that do what logic does badly — a BRAM (memory) and a DSP (multiply–accumulate).
3. **Routing** — wires in channels between tiles, and **multiplexers** that choose which wire drives which. This is most of an FPGA's area, and most of bob's.
4. **Configuration memory** — one bit per choice: every LUT truth-table bit, every flag, every mux select. Programming an FPGA means filling this memory.

bob has all four, plus **I/O pads** (with boundary-scan cells) and a **JTAG controller** to fill the configuration memory.

### 1.3 The five layers

```
 1  ARCHITECTURE   software/bob/device.py          one description: grid, tiles, routing, fields
        │  writes the VPR architecture XML, runs VPR once to get the routing graph
 2  HARDWARE       hw/src/…, bob_fabric.v       Verilog generated from that graph + hand-written tiles and plane
        │  Vivado builds it into the host FPGA
 3  CONFIGURATION  cfg_store / cfg_ctrl / cfg_frames   the memory and the two ways to fill it
        │  JTAG: frames (UG470-style packets) or the scan chain
 4  TOOLS          yosys → VPR or bob PnR → FASM → bitgen        your design becomes bits
        │
 5  HOST           cfgplane / cli / hwtest      loading, reading back, checking on real hardware
```

**The rule that holds it together:** layer 1 is the *only* place where architecture numbers live. Everything else is generated from it or reads `device.json`. If you change the grid, you change one dictionary and re-run two commands.

### 1.4 How a design becomes LEDs

```
counter.v
  │  yosys (software/bob/synth.py)          → bob cells: $lut, BOB_ADD, BOB_FDRE, BOB_BRAM18, BOB_DSP
  │  equiv.py                            → source == netlist == golden netlist (300 random cycles)
  │  vpr_run.prepare                     → .eblif: constants folded, carry chains cut to column height, pins fixed
  │  VPR (or software/bob/pnr)              → .net (packing) .place (where) .route (which wires)
  │  fasm_from_vpr.py                    → FASM: clb_x2y3.init = 64'h…, rr1234 = 3'h5
  │  bitgen.py                           → the configuration word + CRC + .bit file
  │  cli.load → cfgplane                 → JTAG packets → configuration memory → JSTART
  └─ the design runs on the fabric; LEDs follow your Verilog
```

Every arrow is checked: yosys against the source, FASM against `device.json`, the resulting bits against `model.py` and the source trace, and finally the board against the golden netlist.

---

## 2. Vocabulary

| term | meaning in bob |
|---|---|
| **CLB** | configurable logic block: one LUT6 (fracturable into two LUT5s), carry logic, one flip-flop, 71 configuration bits |
| **BLE** | basic logic element: the LUT + flip-flop pair. bob has one per CLB (commercial FPGAs pack 8–10) |
| **tile** | one grid position: its block (CLB/BRAM/DSP/IO) plus the routing muxes that live there |
| **rr graph** | routing-resource graph: VPR's description of every wire (CHANX/CHANY), block pin (IPIN/OPIN) and the edges between them. bob's fabric *is* this graph turned into Verilog |
| **mux** | a routing multiplexer: one rr node with several drivers; its select bits live in the configuration memory |
| **direct** | a hard connection with no bits: the carry chain between stacked CLBs, and DSP cascade |
| **channel width (W)** | how many wires run in each routing channel; 24 here |
| **Fs** | how many wires a switch box connects to each incoming wire (Wilton pattern, Fs = 3) |
| **fc_in / fc_out** | what fraction of the channel a block input/output can reach (0.15 / 0.10) |
| **configuration memory** | the flip-flops holding every configuration bit — 18 560 of them at M16 |
| **chain** | the configuration memory seen as one long shift register (`CHAIN_IN`/`CHAIN_OUT`) |
| **frame** | 4 × 32-bit words = 128 bits of that memory, the unit AMD-style packets address |
| **FAR** | frame address register: which frame the next write or read touches |
| **FASM** | text form of a configuration: one `feature = value` per line (F4PGA's format) |
| **bitgen** | the step that turns FASM into the configuration word and a `.bit` file |
| **GSR / GTS / GWE** | global set-reset, tristate, write-enable: the startup sequence that releases a loaded design |
| **gce** | the guest FPGA's user clock, as an *enable* on the host's 125 MHz clock |
| **CAPTURE** | a JTAG snapshot of every CLB output (and so of every user flip-flop) |
| **stand-in board** | a Python model that answers JTAG like the real board, so hardware checks can be tested without hardware |

---

## 3. Part by part

### 3.1 `software/bob/device.py` — the single source of truth

**What it is.** One Python file that describes the whole device: the grid (`ARCH_*` dictionaries), the tile types and their fields (CLB 71 bits, BRAM 8, DSP 16, ctrl 8), where every block sits, which rr nodes are muxes and how wide each one is, the frame layout, and the board pad mapping. It writes:

- `software/bob/device.json` — the machine-readable device, read by every tool and the host software
- `hw/src/generated/bob_params.vh` — the same numbers as Verilog macros
- `hw/src/generated/bob_fabric.v` — the fabric RTL
- `software/bob/arch/bob_k{6,4}.xml` — the VPR architecture

**Why this way.** Any FPGA project has to keep hardware, tools and host software agreeing about thousands of numbers. Two copies of a number is a bug waiting to happen (bob's M1 milestone exists precisely to remove that risk). Generating everything from one description also makes the architecture a *variable*: the 16 → 36 → 100 CLB steps were dictionary edits, not rewrites.

**How to use it.**

```sh
make device        # regenerate everything from the committed routing graphs
software/bob/device.py --check      # fail if any generated file is out of date
software/bob/device.py --lut-k 4 --out build/k4   # a K = 4 device, written elsewhere
python3 -c "import json; d=json.load(open('software/bob/device.json')); print(d['chain']['width'])"
```

**How to tweak it.**
- **Grid size / columns:** edit or add an `ARCH_*` dict and set `ARCH = …`, then `make rrgraph` (Docker: VPR rebuilds the routing graph), then `make vpr` (re-route the examples). See the recipe in §4.2.
- **A new configuration field** (say a second flip-flop mode): add it to the tile type's field list. Width, offsets, `device.json`, `bob_params.vh` and the FASM feature name follow automatically; then teach `model.py` and the RTL what the bit does.
- **Board pads:** `BOARD_INPUTS` / `BOARD_OUTPUTS` name which pad is SW0, LD2 and so on.

**Code and tests.** `software/bob/device.py`, `vpr_arch.py`, `rrgraph.py`, `fabric_gen.py`; `tests/test_device.py` (field overlaps, chain round-trip, frame tiling, pinned sizes, constants against `clb_pkg.sv`).

### 3.2 The VPR architecture (`vpr_arch.py`) and the routing graph

**What it is.** `vpr_arch.py` writes a VPR architecture XML: the tile types and their pins, the CLB's two modes (`logic` and `arithmetic`), the models VPR needs (`bob_add`, `bob_ff`), the layout (I/O ring, CLB fill, BRAM and DSP columns), the routing segment (L4 unidirectional), the switch box (Wilton, Fs = 3) and the connection-box fractions. `software/bob/vpr_rrgraph.sh` then runs VPR once inside Docker on a trivial design and asks it to **write out the routing-resource graph** it built. That graph is committed (gzipped, with a sha256 stamp of the architecture it came from).

**Why this way.** This is OpenFPGA's method and it is the heart of the project: rather than inventing a routing structure and hoping VPR can use it, bob lets **VPR build the routing** and then generates hardware that matches it node for node. The result is that the router's model of the chip and the chip are the same object, so a route that VPR finds is always loadable, and a mux in the RTL always exists in the router's graph.

**How to use it.**

```sh
colima start                        # Docker for the OpenFPGA image
make rrgraph                        # arch XML → VPR → rr graph (committed) → device files
cat software/bob/arch/bob_k6_rr.stamp  # what that graph was built from
```

**How to tweak it.**
- **Channel width W:** `chan_width` in the `ARCH_*` dict. Wider = more routability, more bits, more LUTs. At 8 × 8 the measurements were W=16: 4.2k routing bits, W=24: 6.0k, W=32: 7.8k.
- **Segment length:** `segment_length` (4 today). Longer wires cross the die faster but waste area on short nets.
- **Fs / fc:** `fs`, `fc_in`, `fc_out`. Lower fc means fewer mux inputs (smaller, harder to route).
- **A new block type:** add its pb_type and model in `vpr_arch.py`, add a column entry, teach `device.py` its fields and `fabric_gen.py` how to instantiate it.

After any of these, the committed rr graph is stale on purpose: every tool refuses to run until `make rrgraph` regenerates it.

### 3.3 `fabric_gen.py` and `bob_mux.v` — turning the graph into hardware

**What it is.** The generator walks the rr graph and writes `bob_fabric.v` (4416 lines at M16): one `bob_mux` instance per rr node that has drivers, a wire per node, one block instance per CLB/BRAM/DSP/pad, and the directs (carry, DSP cascade) as plain assignments. Mux select bits are slices of the `cfg` bus.

**Why this way.** A generated fabric is dull, regular Verilog — exactly what synthesis handles well — and it cannot disagree with the router. Encoding conventions matter: value 0 always means "constant 0", and for block input pins value 1 means "constant 1". That makes an all-zero configuration a **dark, loop-free fabric**, which is what lets a device power up safely and what keeps a random test configuration from oscillating.

**How to use it.** It runs inside `make device`. To see what a mux looks like: `grep -n "bob_mux" hw/src/generated/bob_fabric.v | head`, and `device.json`'s `rr.muxes` lists `[node, chain_lo, width, base, inputs]` for every one of them.

**How to tweak it.**
- The mux cell itself is `hw/src/fabric/bob_mux.v` — 20 lines. If you wanted one-hot selects, or a different tie-off for out-of-range values, this is the file (and `model.py` must match).
- The instantiation order and naming come from `fabric_gen.py`; the configuration bit order comes from `device.py` (tiles in row-major order, muxes in ascending node id).

**Tests.** `tb_bob` section [22] routes four random netlists and compares every CLB output with `model.py` after every clock; `tests/test_device.py` checks every mux encoding and that every block pin is an rr node.

### 3.4 The CLB (`hw/src/clb/clb.sv`, `lutk.sv`)

**What it is.** One BLE: a fracturable LUT (`lutk.sv`, parameterised by K — O6 is the full function, O5 the K−1 sub-function), carry logic in the AMD style (MUXCY/XORCY), and one flip-flop with FDRE/FDSE semantics, routable clock-enable and set/reset. 71 configuration bits at K = 6: 64 INIT plus 7 flags (`ff_en`, `ff_rstval`, `ff_ce_en`, `ff_sr_en`, `cy_en`, `cy_di_sel`, `ff_d_sel`).

**Why this way.** It is UG474's CLB with everything bob does not need removed. One BLE per CLB instead of 8–10 is a deliberate trade: every extra BLE multiplies the configuration memory, and configuration memory is what limits how big bob can be on a mid-range host chip.

**How to use it.** From Python, a hand-built design places LUTs directly:

```python
d = Design(); a, b = d.input(0), d.input(1)
d.output(0, d.lut(1, 1, LUT.and2(), [a, b]))       # AND of the two switches on LD0
```

From Verilog, you never touch it: yosys and the placer do.

**How to tweak it.**
- **LUT size K:** `software/bob/device.py --lut-k 4`, or the `lut_k` default. Everything derives from it, and `make check` runs the whole fabric at K = 4 as well. The hardware build stays K = 6.
- **More BLEs per CLB:** a real change — `clb.sv`, the pb_type in `vpr_arch.py`, the field list in `device.py`, `model.py`, the packer in `pnr/pack.py`.
- **Flip-flop behaviour** (e.g. an asynchronous reset): `clb.sv` plus `model.py`, and a new field if it is configurable.

**Tests.** `hw/tb/tb_clb.sv` sweeps 128 flag combinations against `model.py` (7040 checks at each of K = 6 and K = 4); `tests/test_lutk.py` proves `lutk(6)` equals the hardware-proven `lut6.sv`.

### 3.5 The BRAM tile

**What it is.** `bram_core.v` is a 1024 × 18 true dual-port memory written in Vivado's inference template so it becomes a real RAMB18 in the host FPGA, wrapped by `bram_block.v` which selects each port's pins from the fabric or from JTAG. Configuration: write mode per port (WRITE_FIRST / READ_FIRST / NO_CHANGE), optional output register per port, and two "drive from JTAG" bits. Contents are **not** configuration: they are loaded separately (USER4, or FAR block type 001 frames since M15) and survive JPROGRAM.

**Why this way.** Everything follows UG473 and UG470's split between configuration and contents. Writing the core as an inference template matters: if it does not infer, the host FPGA implements 18 kbit in LUTs and the design no longer fits.

**How to use it.**

```python
d.bram_mode("a", "READ_FIRST", bram=0)
d.bram_pin("a", "addr0", d.input(0), bram=0)      # SW0 → address bit 0
d.output(0, d.bram_out("a", 0, bram=0))           # data bit 0 → LD0
```
From Verilog, write ordinary inferable memory (`work/examples/ram/ram.v`) and yosys maps it to `BOB_BRAM18`.

**How to tweak it.**
- **More BRAMs:** column `height` in the `ARCH_*` dict decides how many fit in the column (`ny / height`).
- **Wider or deeper memory:** `BRAM_ADDR_W` / `BRAM_DATA_W` in `device.py` plus `bram_core.v`; keep it inferable.
- **Another write mode or a byte write-enable:** `bram_core.v`, a new field, `model.py`, and vectors in `tb_bram.v`.

**Tests.** `tb_bram.v` (5292 checks): every write mode × output-register combination on both ports against `model.py`; on the board, `bram-modes` steps the same vectors through JTAG.

### 3.6 The DSP tile

**What it is.** `dsp_core.v` is a trimmed DSP48E1: A25, B18, C48, D25 inputs, a pre-adder (D ± A), a 25 × 18 signed multiplier, a 48-bit accumulator, four static opmodes (M, M+C, P+M, (PCIN >> 17)+M), optional registers on every stage, and a PCOUT → PCIN cascade between the two slices. 16 configuration bits per slice.

**Why this way.** UG479's structure, minus everything that would need dynamic control pins (OPMODE/INMODE/ALUMODE) — those would cost routing and configuration for features a small fabric will not use. The cascade is kept because it is what makes two slices useful for filters (`work/examples/fir/fir.v`).

**How to use it.** yosys maps `*` to `BOB_DSP` automatically (`work/examples/mult/mult.v`, `fir.v`). By hand: `d.dsp_config(...)`, `d.dsp_pin(...)`, `d.dsp_ctrl(...)`, `d.dsp_out(...)`.

**How to tweak it.** More opmodes (`dsp_core.v` + the `opmode` field width + `model.py`), more slices (column height), or dynamic OPMODE (needs new pins in the pb_type, more routing).

**Tests.** `tb_dsp.v` (1344 checks) covers every opmode × pre-adder × register combination and the cascade; `dsp-mult` and `dsp-accum` run on the board.

### 3.7 I/O pads and the boundary scan

**What it is.** Each pad is one VPR block (an `outpad` input pin and an `inpad` output pin) plus **two BC_1 boundary-scan cells** in `bob_fpga.v`: one on the way out (fabric → world, forced 0 while GTS) and one on the way in (world → fabric). The board's switches, buttons and LEDs sit on fixed pads; the rest are reachable only over JTAG.

**Why this way.** Boundary scan is IEEE 1149.1 and costs almost nothing, and it buys two things bob relies on constantly: **INTEST**, which drives the fabric's inputs from JTAG so a design can be exercised deterministically with no human at the board, and **SAMPLE**, which reads the real pins and the LEDs in one atomic scan (the basis of the "live" checks).

**How to use it.**

```python
import fpga, cfgplane
cfgplane.ir(p, "INTEST")
leds = fpga.intest_sweep(p, [0, 1, 2, 3])   # apply four input vectors, read the LEDs
raw  = fpga.sample(p)                        # the real switches and LEDs, at once
```

**How to tweak it.** Pad count follows the grid. Adding per-pad configuration (pull-ups, drive strength, true tristate) would mean new fields in `device.py` and real I/O primitives in `bob_fpga.v`; the board's pins have fixed directions, which is why GTS only forces outputs to 0 today.

### 3.8 The user clock (`clock_ctrl.v`)

**What it is.** The guest fabric runs on the host's 125 MHz clock, but only advances when **`gce`** is high. `clock_ctrl.v` produces `gce` in two modes: *JTAG-stepped* (one pulse per TCK edge while USER1 `ce`, or a single `step`) and *free-running* (one pulse every 2^(div+9) cycles). It also synchronises every TCK-domain control into the sysclk domain with two-flop synchronisers, guarantees at least 2^GAP_SHIFT = 512 cycles between pulses, and implements the M14 **freeze** (hold `gce`, acknowledge back to the TCK domain).

**Why this way.** Three reasons, in order of importance:
1. **Timing.** A clock enable keeps the whole fabric on one real clock; a generated or gated clock would need clock resources the host does not have to spare, and UG949 recommends enables.
2. **Determinism.** One clock per JTAG scan makes cycle-exact checks possible: the board and the model can be compared after every single user clock.
3. **Honest constraints.** Because the RTL *guarantees* the 512-cycle spacing, the 512-cycle multicycle in the XDC is a fact, not an assumption. That is what closed M7's timing failure. It also has to be *big enough*: at M16 the grid grew to 12 × 10, the static path through the unconfigured routing muxes reached about 2500 ns, and the old 256 cycles (2048 ns) left implementation 465 ns short — `phys_opt_design` burned 1 h 15 min on it and the router abandoned timing. The fix is one number in two places, not a placement or routing effort setting.

**How to use it.** Per design, from the `.bit`:

```sh
./bob build work/examples/blinky/blinky.v --clock run --div 15 -o build/bit/blinky.bit   # free-running
./bob build work/examples/counter/counter.v -o build/bit/counter.bit                      # JTAG-stepped (default)
```
`bob build` prints the resulting rate, because a `--div 26` build once looked like a dead board.

**How to tweak it.**
- **Rate:** `--div N` (period = 2^(N+8) sysclk cycles).
- **Minimum spacing:** `GCE_MIN_GAP_SHIFT` in `device.py` (and the matching multicycle in the XDC). Raising it makes timing easier and the fabric slower. Grow the grid and this is the number that has to grow with it: 12 × 10 needs 9 (512 cycles), 8 × 6 fitted in 8.
- **A second clock domain:** a real project — a second `gce`, per-CLB clock selection, and VPR would need two global nets.

**Tests.** `hw/tb/tb_clock_gap.v` (11 checks): spacing in both modes, requests that arrive too early, no `gce` at all while frozen, and pulses resuming after release.

### 3.9 The JTAG TAP (`jtag_tap6.v`)

**What it is.** A standard IEEE 1149.1 state machine with a 6-bit instruction register using AMD 7-series codes where they exist (IDCODE, USERCODE, SAMPLE, EXTEST, USER1–4, CFG_IN, CFG_OUT, JPROGRAM, JSTART, BYPASS) plus three private ones (INTEST, the DSP register, CHAIN_IN/CHAIN_OUT). Capture-IR returns `{DONE, INIT_B, COMMITTED, CRC_ERR, 0, 1}`, so any instruction scan is also a status read.

**Why this way.** Using the real 7-series codes means standard tools and habits transfer: `openFPGALoader` reads DONE and INIT_B exactly where they are on a real part. The private codes are for things 7-series does not have (bob keeps its scan chain beside the frame path).

**How to use it.** Everything goes through `software/host/cfgplane.py`, which names the instructions:

```python
cfgplane.ir(p, "CFG_IN"); cfgplane.frames_send(p, packets.load_stream(word))
print(cfgplane.ir_status(p))          # {'done': 1, 'init_b': 1, 'committed': 1, 'crc_err': 0}
```

**How to tweak it.** Adding an instruction = a code in `jtag_tap6.v`, a `sel_*` strobe, a data register, an entry in `cfgplane.IR`, and a line in the spec's instruction table. The TAP's timing rules (TMS/TDI on the rising edge, TDO and updates on the falling edge, synchronous Test-Logic-Reset) are hardware-proven; do not change them casually.

### 3.10 The configuration memory (`cfg_store.v`)

**What it is.** The flip-flops the fabric reads — 18 560 of them at M16 — plus **one 128-bit frame buffer** through which every write passes, and one frame-wide read mux shared by chain readback and frame readback. Both paths write the same memory:

| path | instruction | how a write happens |
|---|---|---|
| chain | `CHAIN_IN` | bits shift into the buffer; every 128th bit completes a frame, written on the next falling edge (only while GWE = 0) |
| frames | `CFG_IN` (parsed by `cfg_frames.v`) | the 4th word of an FDRI frame lands in the buffer; a per-frame enable copies it |

**Why this way.** The obvious implementations are both traps, and bob hit both:
- Writing `cfg[frame_idx*128 +: 128] <= data` is a **barrel shifter over the whole memory**: ~12 000 LUTs and 1.7 GB in yosys, and Vivado ran out of memory. *Never* use a computed part-select over the configuration memory.
- Keeping a full-width shift register beside the memory (the M13 design, and the classic scan-chain textbook answer) costs W flip-flops *and* W LUTs — half of M13's logic. Streaming through one frame buffer removed 3.6k LUTs and 4.8k flip-flops, which is what paid for the 36-CLB and then the 100-CLB grid.

The price is a semantic change, taken deliberately to match AMD: a chain load with a bad CRC now leaves the new bits in memory but never starts (COMMITTED stays 0, JSTART refuses), instead of leaving the old design untouched. A running design is still never written.

**How to use it.** Indirectly: `bob load` (frames) or `bob load --mode chain`. Directly, for experiments:

```python
cfgplane.load(p, word, B.CHAIN_W)          # chain load with CRC, readback and JSTART
cfgplane.cfg_out(p, B.CHAIN_W)             # chain readback (never writes)
cfgplane.measure_chain(p, B.CHAIN_W + 256) # measure the chain length on the board
```

**How to tweak it.** The frame size is `FRAME_WORDS` in `device.py` (4 words = 128 bits). Bigger frames mean fewer frames and a coarser partial-reconfiguration grain; smaller frames mean more FAR traffic. Both the RTL and `packets.py` read the number from `device.json`, so it is one edit plus `make device`.

**Tests.** `tb_bob` sections [2]–[4] (commit, readback, corrupt chain), `tb_frames` [1]–[12], and three mutants (`chain-write-dropped`, `chain-out-no-reload`, `chain-writes-live`).

### 3.11 Chain control: CRC and startup (`cfg_ctrl.v`)

**What it is.** The 64-bit `CFG_CTRL` register (status out, expected CRC in behind the write key `0xC5`), the bit-serial CRC-32C over everything shifted in during a `CHAIN_IN` scan, the length counter, the COMMITTED/CRC_ERR/LEN_ERR flags, and the startup sequence **GSR → GTS → GWE → DONE** stepped by JSTART in Run-Test/Idle.

**Why this way.** It is UG470's order: check integrity *before* releasing anything, then release in the order that cannot damage the design (registers leave reset, outputs enable, writes enable, DONE). The CRC init is `0xFFFFFFFF` on purpose, so a stuck-low TDI cannot match the power-up expected value of 0. The write key exists so that reading the register (which shifts zeros back in) cannot silently change the expected CRC — the same idea as UG470's MASK register.

**How to use it.**

```python
cfgplane.write_expected(p, chainbits.crc32c_bits(word, B.CHAIN_W))
st = cfgplane.status(p)      # committed, crc_ok, crc_err, len_err, count, gsr/gts/gwe/done
cfgplane.jprogram(p); cfgplane.jstart(p)
```

**How to tweak it.** A different CRC polynomial is one constant in `cfg_ctrl.v` and one in `chainbits.py` (and a mutant proves the testbench notices). Startup phases are a small FSM; adding one (say a "wait for a PLL lock" phase) means an extra state and an extra status bit.

**Tests.** `tb_cfg.v` (180 checks) on the standalone M2 top; `sim/mutate_cfg.sh` breaks each guard in turn (CRC polynomial, CRC check, length check, write key, start-without-commit) — the suite exists because the first version of the length check could be deleted with every test still passing.

### 3.12 The frame controller (`cfg_frames.v`)

**What it is.** The UG470-style packet path on `CFG_IN`/`CFG_OUT`: a bit-by-bit hunt for the sync word `0xAA995566`, then 32-bit words parsed as type-1/type-2 packets into registers **CRC, FAR, FDRI, FDRO, CMD, STAT, IDCODE**, with a running CRC-32C over `{register, data}`, FAR auto-increment, a readback queue, and the status word. Frame writes need WCFG, a matched IDCODE, no error, a valid FAR and GWE = 0 (or an acknowledged freeze); START needs a CRC match *after* the last frame.

**Why this way.** The user asked for "frame based writing just like AMD (slightly simplified)". Frames buy three things a chain cannot: the stream is **self-synchronising** (it can be split across any number of JTAG scans), it is **addressable** (you can write or read one frame), and it carries its own integrity and identity checks (CRC, IDCODE) the way a real `.bit` does. The simplifications are listed in the spec: a frame lands on its 4th word (no pad frame), and no encryption/compression/ECC/multiboot.

**How to use it.**

```python
import packets
words = packets.load_stream(word, brams=contents)   # the full stream bob load sends
cfgplane.frames_send(p, words)
print(cfgplane.frames_stat(p))                      # decoded STAT
print(cfgplane.frames_readback(p) == word)          # FDRO readback of the whole memory
software/bob/packets.py dump build/bit/counter.bit     # the same stream, annotated, from the shell
```

**How to tweak it.** New CMD verbs and registers are small additions (`cfg_frames.v` + `packets.py` + a scenario in `tb_frames.v` + a mutant). Keep the Python model and the RTL in step: **every expected value in `tb_frames` comes from `packets.Controller`**, so if you change one and not the other, the testbench fails immediately — that is the point.

**Tests.** `tb_frames.v` (71 checks over 19 scenarios) and 29 mutants.

### 3.13 Partial reconfiguration (M14)

**What it is.** Reconfiguring part of a running design: `CMD AGHIGH` raises a freeze, `clock_ctrl` holds `gce` and acknowledges (STAT bit 7 `GHIGH_B` goes 0), only the frames that differ are written, and `CMD LFRM` releases the freeze — but only if the CRC written after the last frame matched.

**Why this way.** It mirrors UG470/UG909 (AGHIGH … DGHIGH/LFRM around a partial bitstream), but what bob's GHIGH_B holds is the **user clock**. That works because every fabric register — CLB flip-flops, BRAM and DSP registers — is enabled only by `gce`: hold it, and configuration bits can change under a held enable without any register capturing anything. The CRC gate means a half-written or corrupted partial never runs; the fabric simply stays frozen until JPROGRAM.

**How to use it.**

```sh
./bob load build/bit/gates.bit                    # load a design normally
./bob load --partial build/bit/gates_swapped.bit  # rewrite only the frames that differ
```
It prints how many frames it rewrote (a one-LUT change is 1 frame of 145; a re-routed design 20–30).

```python
ok, msg, n = cfgplane.load_partial(p, new_word)   # the same thing from Python
```

**How to tweak it.**
- **Region protection** is the obvious next step: today any frame may be rewritten and the *host* decides which. A `--region` option would constrain PnR to a column range and let the host refuse a partial that touches frames outside it.
- **Resetting the reconfigured part** (AMD asserts GSR for the reconfigured region) would need a per-region GSR.

**Tests.** `tb_frames` [13]–[17] (a free-running counter holds while frozen and continues afterwards; no CRC, bad CRC, no IDCODE, frames before the acknowledgement), `tb_clock_gap` [4], five mutants, and four board checks including `partial-live` on a free-running design.

### 3.14 BRAM contents as frames (M15)

**What it is.** FAR block type `001`: column = BRAM index, frame n = row × 128 + minor covers addresses 4n … 4n+3, each word `{14'b0, data[17:0]}`. Writes (GWE = 0 only) hand each frame to `bram_jtag.v`'s sysclk sequencer through a toggle handshake; reads prefetch the frame FAR points at. `bob load` now carries every word of every used BRAM inside the load stream, under the same CRC, and reads them back over FDRO.

**Why this way.** UG470 carries BRAM contents in the bitstream as their own block type, and one CRC over the whole design is the honest version of "the file is intact". USER4 stays as the second path (and is what `--mode chain` uses), because keeping two independent ways to reach the same state is how several bugs were caught.

**How to tweak it.** The frame→address mapping is a few lines in `cfg_frames.v` and `packets.bram_far`; the sequencer that walks the four words lives in `bram_jtag.v`. If you change the BRAM width or depth, both follow `device.json`.

**Tests.** `tb_frames` [18]–[19] (writes into bram0, FAR crossing into bram1, FDRO readback, refusal while running), five mutants, three board checks.

### 3.15 Debug and test access: CAPTURE, USER1, USER4, the DSP register

**What it is.**
- **CAPTURE (USER3):** Capture-DR snapshots every CLB output (100 bits at M16) and shifts it out. For a CLB whose flip-flop is enabled, that output *is* the register.
- **USER1:** the control word — `ce`, `sr`, `cin`, `step`, `autostep` — plus status (the first 16 CLB outputs).
- **USER4:** BRAM contents (LOAD_PTR / WRITE / READ while GWE = 0), a per-BRAM "drive" word, and SELECT.
- **DSP register (private):** drive every DSP input and read both P values.

**Why this way.** These are what make the board **checkable** rather than merely runnable. Loading a design and watching LEDs proves very little; comparing all 100 registers against a golden netlist after every user clock proves a lot. `autostep` — one user clock per INTEST scan — is what makes that possible without a free-running clock.

**How to use it.**

```python
cfgplane.user1(p, 0x10)                 # autostep on
cfgplane.ir(p, "INTEST")
p.shift_dr_fast(fpga.BSR_W, fpga.bsr_word(v))   # apply inputs and advance one user clock
cap = cfgplane.capture(p, B.NCLB)               # every CLB output
```

**How to tweak it.** CAPTURE's width follows `NCLB` automatically. Adding BRAM/DSP internal state to the capture chain would mean widening `capture_chain.v` and teaching `fasm_from_vpr.capture_map` which golden register each new bit is.

### 3.16 The models (`model.py`, `packets.Controller`, `chainbits.py`)

**What it is.** Python implementations of the hardware: `model.Fabric` evaluates exactly the muxes, LUTs, carries, flip-flops, BRAMs and DSPs that the RTL has, cycle by cycle; `packets.Controller` is a bit-level model of the frame controller; `chainbits` is the CRC and `.bit` file format.

**Why this way.** Every expected value in the testbenches comes from these models, never from the RTL — otherwise a testbench only proves the RTL agrees with itself. It also gives the stand-in board (§3.23) something real to answer with, and lets `bob build` check a configuration *before* it ever reaches hardware.

**How to use it.**

```python
import model, bitstream as B
f = model.Fabric(B.Bitstream(word)); f.clock(gsr=1)
f.clock(pad_i=0b01, cin=1)
print(f"{f.outputs(0b01):03b}", hex(f.clb_o(0b01)))
```

**How to tweak it.** If you change fabric semantics, change `model.py` in the same commit — the K=4 and K=6 sweeps will tell you immediately if the two disagree.

### 3.17 Synthesis (`software/bob/synth.py`, `synth/bob_cells*.v`)

**What it is.** A yosys script in the shape of `synth_xilinx`, mapping to bob's cell library: `$lut` (K inputs), `BOB_ADD` (one CLB in carry mode), `BOB_FDRE`/`BOB_FDSE`, `BOB_BRAM18`, `BOB_DSP`. It fails if any other cell survives, or if the design has more than one clock.

**Why this way.** Reusing yosys's passes in their proven order avoids reinventing synthesis, and the strict cell check means a design either maps onto hardware bob actually has, or the flow stops with a clear error instead of producing something unroutable.

**How to use it.** `./bob build design.v` runs it. Directly: `software/bob/synth.py work/examples/fir/fir.v --top fir --out build/synth/fir`.

**How to tweak it.**
- Map a new operator to a hard block: add a rule (the DSP path uses `mul2dsp`, the BRAM path `memory_libmap` with `bob_brams.txt`).
- Watch rule priority: bob's `$alu` rule is named `_80_` precisely so it beats yosys's generic `_90_alu`.

**Tests.** `tests/test_synth.py` (only bob cells; a latch is rejected; carry chains split across columns), and `equiv.py` on every example.

### 3.18 Equivalence and the golden netlist (`equiv.py`, `golden.py`)

**What it is.** `equiv.py` simulates the source Verilog and the synthesised netlist together over 300 biased random cycles and compares them before and after every edge, saving a trace. `golden.py` writes the same netlist with **one named wire per bit**, so every register in it can be pointed at a specific CLB later.

**Why this way.** Two independent reasons. First, synthesis bugs are silent; comparing against the source catches them at the first step. Second, the golden netlist is what makes the board check meaningful: `CAPTURE` bit *i* is compared with golden register *n*, every clock. Vanilla yosys output cannot do that, because `_syn.v` renames everything.

Stimulus quality matters: uniform random inputs once held a counter's synchronous reset half the time, so its trace was all zeros and the check could not fail. Vectors are biased and generated in 50-cycle segments now.

**How to use it.** `software/bob/equiv.py work/examples/fir/fir.v` prints the cell counts and the comparison result.

**How to tweak it.** Cycle count and bias live in `equiv.random_vectors`. If you add an example whose ports are not `clk/sw/btn/led`, give it a `.pcf` — the model and trace checks need to know which pad is which.

### 3.19 Place and route: VPR (`vpr_run.py`) and bob's own (`software/bob/pnr/`)

**What it is.** `vpr_run.prepare` rewrites the yosys netlist into an `.eblif` VPR can pack: constants become IPIN constants, carry chains are cut to the column height with generator and tap CLBs, buffers are inserted where a flip-flop's D is not a single-load LUT output, and `.pcf` pins are fixed. Then either **VPR 9** (in Docker, on the committed rr graph, fixed seed) or **bob's own PnR** (`pack.py`, `place.py` simulated annealing, `route.py` PathFinder negotiated congestion with A*) produces `.net`/`.place`/`.route` in the same formats.

**Why this way.** VPR first, because it is the reference implementation and its results are trustworthy; bob's own afterwards, to show the flow is not magic and to get a second opinion on every design. Because both emit the same file formats, everything downstream — FASM, bitgen, the model check, the board test — is shared.

**How to use it.**

```sh
make vpr                                   # re-route every example with VPR (Docker)
./bob build work/examples/fir/fir.v --pnr python    # use bob's PnR instead
make pnr                                   # compare them: docs/reports/M16/pnr_vs_vpr.md
```

**How to tweak it.** Placement cost and schedule are in `place.py` (VPR's own schedule: T0 = 20σ, 10·N^(4/3) moves, range limit); routing cost and the A* heuristic in `route.py`. Both are small and readable — this is the part of the project most worth experimenting with. `--seed N` changes the result; the same seed always reproduces it, and the stamp in each result directory records what it was built from.

**Tests.** `tests/test_vpr.py`, `tests/test_pnr.py` (legality read back from the files, determinism, failing cases), and the golden co-simulation of both flows.

### 3.20 FASM, bitgen and the `.bit` file

**What it is.** `fasm_from_vpr.py` turns a PnR result into **FASM** text (`clb_x2y3.init = 64'h…`, `rr1234 = 3'h5`), checked line by line against `device.json`. `bitgen.py` turns FASM into the configuration word (and back — the round trip is exact) and writes a `.bit`: a header, the configuration bytes, a `BRAM` section per used memory, a `META` JSON section (design, sources and their hashes, PnR result hash, clock), and a file CRC.

**Why this way.** A text intermediate is a debugging superpower: you can read a configuration, diff two of them, and hand-edit one. The legality check means a wrong feature name or an out-of-range mux value is caught before anything touches hardware, and the exact round trip means a readback from the board can be decoded and compared as FASM.

**How to use it.**

```sh
./bob fasm build/bit/counter.bit | head          # read a configuration
./bob info build/bit/counter.bit                 # header, sections, metadata
software/bob/bitgen.py --roundtrip build/bit/counter.bit
```

**How to tweak it.** Feature names come from `device.py`'s field names, so renaming a field renames its FASM feature. New `.bit` sections are a tag plus a reader/writer pair.

### 3.21 The host side (`dirtyjtag.py`, `cfgplane.py`, `cli.py`)

**What it is.** `dirtyjtag.py` speaks the Pico's USB protocol (single pulses, IR/DR shifts, bulk transfers, and a hard 100 kHz TCK ceiling). `cfgplane.py` is the configuration plane in Python: every instruction, chain load with a per-pulse fallback, frames, partial reconfiguration, CAPTURE, USER1/USER4/DSP. `cli.py` is `./bob` — `build`, `load`, `info`, `fasm`.

**Why this way.** One layer that knows JTAG, one that knows the protocol, one that knows the flow. Every hardware check and every experiment is written against `cfgplane`, so a protocol change is one file.

**How to use it.**

```sh
./bob build work/examples/switches/switches.v --clock run --div 15 -o build/bit/switches.bit
./bob load build/bit/switches.bit            # frames
./bob load build/bit/switches.bit --mode chain
./bob load build/bit/other.bit --partial
```

**How to tweak it.** `--freq` sets TCK (capped at 100 kHz because the XDC constrains it there). New board-side helpers belong in `cfgplane`, not in the checks.

### 3.22 Hardware tests (`hwtest.py`) and the stand-in board

**What it is.** `software/host/hwtest.py` holds a list of named checks per milestone. Each check is a function `(probe, ctx) -> (ok, message)`. A run does the regression first (IDCODE, bypass, self-test, then the earlier milestones' checks) and then the new ones, and appends every result to `docs/hwtest/results.log`. `tests/test_hwtest_fake.py` contains a **stand-in board**: `model.py` and `packets.Controller` behind the same JTAG API, including the free-running clock in real time, BRAM contents, the frame path, the freeze and partial reloads.

**Why this way.** A hardware check that has never failed is not a check. Every check is first run against the stand-in board twice: on a *good* board (it must pass) and on a deliberately *broken* one — a corrupted CAPTURE, a clock 1.5× too fast, wrong BRAM contents, a board that loses state on a partial reload, a freeze that does not hold. Several real bugs were caught this way before the board saw them.

**How to use it.**

```sh
make hwtest M=M16                 # everything
make hwtest M=M16 ONLY=partial-live
cd host && ./hwtest.py --milestone M16 --list      # what would run, touches no hardware
cd host && ./hwtest.py --milestone M16 --manual    # also walk through docs/hwtest/M16.md
```

**How to tweak it.** To add a check: write it, add passing and failing stand-in cases in `tests/test_hwtest_fake.py`, then put it in `MILESTONE["Mx"]`. Keep the message informative — it is what lands in `results.log`.

### 3.23 Simulation, lint and mutation testing

**What it is.**

| what | where | scale |
|---|---|---|
| unit testbenches | `tb_clb`, `tb_bram`, `tb_dsp` | 13 676 checks against `model.py` |
| the whole FPGA | `tb_bob` (+ K=4) | 852 + 722 checks: JTAG, both configuration paths, every block, random routed netlists |
| the configuration plane | `tb_cfg` | 180 |
| synthesised designs | `tb_synth` | 972 |
| golden co-simulation | `sim/tb_cosim.v` | 5 220: source ∥ golden netlist ∥ the real fabric loaded from a `.bit` |
| the frame path | `tb_frames`, `tb_clock_gap` | 71 + 11 |
| lint | `sim/lint.sh` (verilator) | must be clean |
| Python tests | `tests/` (pytest) | 193 |
| mutation | `sim/mutate_{cfg,fabric,frames}.sh` | 59 deliberately broken guards, all must be caught |

**Why this way.** Coverage of *behaviour* is not enough; you also need coverage of *guards*. Mutation testing is the cheapest way to prove a test would notice a broken check: break the CRC comparison, drop the GWE gate, ignore the freeze — if every testbench still passes, the guard is untested. This found a length check nobody tested (M2) and two frame guards (M13, M14).

**How to use it.**

```sh
make check      # device + all simulations + lint + pytest
make mutate     # the three mutation suites (slow)
sim/run_frames_sim.sh     # one testbench on its own
```

**How to tweak it.** A new mutant is one line in a `mutate_*.sh` script: a name, the file, and a `perl -pe` expression that breaks exactly one guard. Beware of pinning a mutant to a grid position — `carry-direct-cut` has had to follow the last CLB column twice as the fabric grew.

### 3.24 The Vivado bundle (`hw/`, `build.tcl`, the XDC)

**What it is.** `hw/` is the only folder the Windows machine needs: sources listed in `sources.f`, `build.cfg` (tag, top, part, IDCODE, USERCODE, jobs, synthesis directive), the testbenches, the XDC, and `scripts/build.tcl`. The Tcl opens the existing project (never recreates it), syncs the file lists, sets the generics, rebuilds only when a content fingerprint changes, and writes `bit`, `timing.rpt`, `util.rpt`, `drc.rpt`, the logs, `build_info.txt` and `sysclk_1cycle.txt` into `out/<tag>/`.

**Why this way.** The hand-off has to be one folder and one script, because it crosses machines. The fingerprint exists so a re-paste with no changes does not spend 20 minutes rebuilding. `sysclk_1cycle.txt` exists because a constraint that silently matches nothing is worse than no constraint.

**The four rules that came from crashed builds:**
1. No computed part-select over the configuration memory (it becomes a barrel shifter).
2. No `keep_hierarchy` anywhere (it changed how Vivado breaks the fabric's routing loops, and it crashed).
3. The XDC is **implementation-only** (`USED_IN_SYNTHESIS false`); synthesis with clocks crashed, and once restarted Windows.
4. Before any hand-off, compare `software/bob/synth_estimate.sh` with the last successful build.

**How to use it.**

```sh
make hw     # refresh generated testbench vectors and print the hand-off steps
# Windows: replace E:\bob_full_v1\hw, Tools → Run Tcl Script → hw/scripts/build.tcl
#          then copy bob_vivado\out\<tag>\ back to docs/reports/<tag>/
make check  # now also checks those reports (timing must close from M13 on)
```

**How to tweak it.** `build.cfg` is where the tag, IDCODE nibble, USERCODE, `jobs` and the synthesis directive live. The XDC must stay **plain XDC** — Tcl in an XDC is silently skipped, which once left TCK unconstrained while the report said "all constraints met".

### 3.25 `software/bob/flow.py` and bob studio (`software/host/studio.py`)

**What it is.** `flow.py` runs the guest flow as separate stages — synth (with its equivalence
check), pnr, fasm, bits, model, write — each one timed and each returning what it measured:
cell counts, wirelength, routing iterations, FASM feature count, model samples, and any
compiler diagnostic with the file and line it names. `./bob build` is a wrapper over it, and
`./bob build --json FILE` writes the record instead of prose.

**bob studio** (`software/host/studio.py`) is that engine behind an application, laid out the way
Vivado is: sources and an editor, a Flow Navigator with Synthesis / Implementation / Generate
Bitstream, a Device view of where the design landed and which channels it routed through, a
Pin Planner that writes a `.pcf`, and Program and Debug — program, readback and verify,
CAPTURE, partial reconfiguration. Messages are clickable to the source line.

**Why this way.** The flow was one 89-line function whose only output was printed prose, so
nothing could watch it happen — not a GUI, not a report, not a `--json` flag. Separating the
engine from the CLI costs nothing and makes all three possible. The two are kept honest by
`tests/test_flow.py`, which requires `flow.py` and `cli.build()` to write a **byte-identical
`.bit`** for every example.

The backend is stdlib `http.server` plus Server-Sent Events, and the page is one
self-contained file with no external libraries, assembled from `software/studio/` exactly as
`arch.html` is assembled from `docs/arch/`. So the project gained no dependency, and the
page opens offline.

It also runs with **no board attached**: `--probe fake` uses `software/host/fakeboard.py`, the software
stand-in that answers JTAG out of `software/bob/model.py`. That class was written for
`tests/test_hwtest_fake.py` and moved here when the studio needed it; the test now imports it,
so the checks that prove the stand-in can *fail* go on guarding the one the tools use.

**How to use it.**

```sh
software/host/studio.py --probe fake     # no hardware; http://127.0.0.1:8765
software/host/studio.py --probe usb      # the Pico on PMODA
./bob build --json rec.json work/examples/fir/fir.v
./bob build --project bob.proj    # sources, top, pins and settings in one file
./bob load design.bit --probe fake
python3 software/studio/build.py      # rebuild studio.html from software/studio/p*.{html,js}
```

**Pin files, exactly.** A `.pcf` names one bit per line and every port bit is `port[i]`,
*including a one-bit port*: `en` is the net `en[0]`. `vpr_run.write_eblif` builds those
names from the yosys port bits with no special case for width 1, so a bare name in a
`.pcf` is silently ignored and place-and-route then stops with
`input en[0] has no pin (pcf set_io)`. The Pin Planner expands every port to one row per
bit and refuses an un-indexed name.

**How to tweak it.** A new stage is a method on `Flow` plus its name in `STAGES`; it returns a
`Stage` and the page picks it up with no change. A new view is a part file in `software/studio/`
(they are concatenated in name order) and a route in `software/host/studio.py`. The one thing to keep
is that every route drives `flow.py` or `software/host/cfgplane.py` and reports what they return —
the studio must never become a second implementation of the flow.

**A caveat worth knowing.** One guest clock on the software board costs a `model.settle()`,
about 2 ms at 100 CLBs, so a free-running design runs behind the rate it asks for.
`studio.DemoBoard` bounds the backlog to a time budget and the page says how many edges it
skipped. The real board has no such problem.

---

## 4. Cookbook

Each recipe is the whole change, in order. All of them end the same way: `make check` green, then (if the hardware changed) a Vivado build and `make hwtest`.

### 4.1 Build and run a design

```sh
./bob build work/examples/fir/fir.v -o build/bit/fir.bit           # VPR
./bob build work/examples/fir/fir.v --pnr python -o build/bit/fir_py.bit
./bob build work/examples/blinky/blinky.v --clock run --div 15 -o build/bit/blinky.bit   # free-running clock
./bob load build/bit/fir.bit                              # frames (default)
./bob load build/bit/fir.bit --mode chain                 # the scan chain instead
./bob load build/bit/other.bit --partial                  # rewrite only what differs, design keeps running
```

### 4.2 Change the grid (this is milestone M16 in one recipe)

1. Edit or add an `ARCH_*` dictionary in `software/bob/device.py` and set `ARCH = …`:
   ```python
   ARCH_12X10 = {"nx": 12, "ny": 10, "chan_width": 24, "segment_length": 4, "fs": 3,
                 "fc_in": 0.15, "fc_out": 0.10, "io_capacity": 1,
                 "columns": [{"type": "bram", "x": 3, "height": 5},
                             {"type": "dsp",  "x": 8, "height": 5}]}
   ```
   CLB count = (nx − number of hard columns) × ny. Hard blocks per column = ny / height.
2. `colima start && make rrgraph` — VPR rebuilds the routing graph (Docker), then the device files.
3. `make vpr` — re-route every example on the new graph. `make pnr` for the comparison report.
4. `software/bob/synth_estimate.sh $PWD $PWD/build/est` — **the size gate**. Compare with the last build that Vivado actually finished, and tell the user the numbers.
5. `make check`. Expect to fix: pinned sizes in `tests/test_device.py`, anything in the testbenches that assumed the old widths, and mutants pinned to a grid position (`carry-direct-cut` follows the last CLB column).
6. `hw/build.cfg`: new `tag`, `idcode` nibble, `usercode`. Write `docs/hwtest/Mx.md`.
7. Add a board check only the new grid can pass (M16 added `work/examples/big/big.v`, 56 CLBs), with stand-in cases first.
8. `make hw`, hand `hw/` to Vivado, copy `out/<tag>/` back, `make check`, `make hwtest M=Mx`.

### 4.3 Change the LUT size K

```sh
software/bob/device.py --lut-k 4 --out build/k4      # try it without touching the repo
make check                                        # the K = 4 fabric is simulated in every run
```
To make it the board's K: set `lut_k` in `device.py`, `make rrgraph` (the architecture changes), then the same steps as §4.2. Everything that depends on K — `lutk.sv`, `clb_pkg.sv`, field widths, `bitstream.py`, yosys `abc -lut K` — reads it from one place.

### 4.4 Add an example design

1. Write `work/examples/name.v` with ports `clk`, `sw[1:0]`, `btn[3:0]`, `led[2:0]` (or any ports plus a `.pcf`).
2. Add `"name"` to `EXAMPLES` in `software/bob/vpr_run.py` and to the `equiv` loop in the `Makefile`.
3. `software/bob/equiv.py work/examples/name.v` — source == netlist.
4. `software/bob/vpr_run.py --repeat name` — route it and commit the result.
5. `make check` — it joins `tb_cosim`, `test_vpr`, `test_bitgen` automatically.
6. Board check: `("bob-name", _bob_check("name"))` in the milestone list, with a stand-in case.

### 4.5 Add a configuration field to a tile

1. `device.py`: add `(name, width, kind, group, doc)` to that tile type's field list.
2. `make device` — `device.json`, `bob_params.vh` and the FASM feature name follow.
3. Use the new `cfg` bits in the RTL (`clb.sv`, `bram_block.v`, …).
4. Teach `model.py` what the bits do, and add vectors to the tile's testbench.
5. If a tool should set it: `bitstream.py` (hand-built designs), `fasm_from_vpr.py` (from PnR), or both.
6. A mutant that breaks the new behaviour, so you know a test would catch it.

### 4.6 Add a JTAG instruction

1. A code and a `sel_*` strobe in `jtag_tap6.v` (private codes only — do not collide with AMD's).
2. A data register module, and its `so` into the TAP's TDO mux.
3. `cfgplane.IR` and a helper function in `software/host/cfgplane.py`.
4. A row in `docs/bitstream-format.md` §2.
5. A scenario in `tb_bob.v` or `tb_cfg.v`, and a stand-in board answer in `tests/test_hwtest_fake.py`.

### 4.7 Change the user clock

- Per design: `--clock jtag` (one step per TCK edge) or `--clock run --div N` (period 2^(N+8) sysclk cycles).
- Globally: `DIV_MIN_SHIFT` / `GCE_MIN_GAP_SHIFT` in `device.py`. The gap shift and the XDC multicycle must agree — that is what makes the constraint true.
- On the board, `USER1` bit 0 is `ce`, bit 3 `step`, bit 4 `autostep` (one clock per INTEST scan).

### 4.8 Use partial reconfiguration

```sh
./bob build work/examples/gates/gates.v -o build/bit/a.bit
./bob load build/bit/a.bit
./bob build work/examples/gates/gates.v --pcf work/examples/gates/gates_swapped.pcf -o build/bit/b.bit
./bob load --partial build/bit/b.bit        # prints how many frames it rewrote
```
The design keeps running: registers, BRAM and DSP state survive. A bad CRC leaves the fabric frozen — `./bob load build/bit/a.bit` (a full load, which starts with JPROGRAM) recovers it.

### 4.9 Read the hardware back

```python
import cfgplane, packets
cfgplane.cfg_out(p, B.CHAIN_W)            # the whole configuration over the chain
cfgplane.frames_readback(p)               # the same thing over FDRO
cfgplane.bram_frames_read(p, 0, 0, 4)     # 4 content frames of BRAM 0 (GWE = 0 only)
cfgplane.capture(p, B.NCLB)               # every CLB output / user register
print(packets.decode_stat(cfgplane.frames_read(p, 1)[0]))
```

### 4.10 Regenerate the documents

```sh
python3 docs/arch/build.py --data                  # arch.html (--data after make device)
python3 docs/project/collect.py                    # numbers from the repo → data.json
python3 docs/project/build.py                      # project.html and guide.html
```

---

## 5. How bob compares

bob is a student-scale project that deliberately reuses the methods of much larger ones. This section is what it does better, what it does worse, and what it simply does not do.

### 5.1 The projects

| project | what it is | scale |
|---|---|---|
| **bob** (this) | an FPGA fabric + configuration controller + full tool chain, running inside a PYNQ-Z2, built milestone by milestone with a board test each time | one fabric, one board, ~27k lines |
| **OpenFPGA** (LNIS, Utah) | an academic framework that turns an architecture description into a fabric (Verilog + SPICE), a bitstream generator and a full VTR-based flow, aimed at taping out FPGAs | many architectures and technologies, years of work, a research community |
| **Aegis** (`/Users/sk/work/aegis`, Apache-2.0, read-only reference here) | a parameterised FPGA fabric generator written in Dart/ROHD: emits synthesisable SystemVerilog for a whole device — clock tiles, I/O and SerDes, a LUT/BRAM/DSP grid — programmed by one scan chain through every tile | a generator with a documented architecture, PDK notes and a CAD story |
| **ZUMA** (Brant & Lemieux, FCCM 2012) | an open FPGA **overlay**: a virtual FPGA on a commercial one, with configuration held in the host's LUTRAM | a research overlay, the classic reference for overlay area |
| **prjxray / F4PGA** | reverse-engineering of real Xilinx bitstreams and an open flow that targets them | large, device-accurate, no fabric of its own |

### 5.2 Where bob is genuinely strong

1. **Every step is proven on real hardware.** Seventeen milestones, fifty-seven logged board runs, and a rule that simulation never closes a milestone. Most fabric generators are validated in simulation or on one demo design; bob has a regression that re-runs every earlier milestone's checks on each new bitstream.
2. **One description generates everything.** `device.py` → VPR architecture, routing graph, fabric RTL, `device.json`, FASM map, Python models and host tools. Growing 16 → 36 → 100 CLBs was a dictionary edit plus two commands. OpenFPGA has the same philosophy at a much larger scale; Aegis parameterises its generator but its CAD side is not this tightly coupled.
3. **Two configuration paths on one memory.** A scan chain (OpenFPGA's `scan_chain`, Aegis's shift + shadow) *and* AMD UG470-style frames (sync word, type-1/2 packets, CRC over `{register, data}`, FAR auto-increment, FDRO readback, STAT) — with a board check that loads through one and reads back through the other. Most projects pick one protocol.
4. **Partial reconfiguration that provably keeps state.** AGHIGH freezes the user clock, only changed frames are written, LFRM releases after a CRC match, and the testbench proves a free-running counter holds its value and then continues. ZUMA and Aegis do not do this; OpenFPGA supports frame-based protocols but bob's freeze-and-prove loop is unusually concrete for a project this size.
5. **Verification depth per line of code.** 28 744 testbench checks whose expectations come from independent Python models, golden co-simulation (source ∥ golden netlist ∥ fabric RTL, 5 220 checks), 59 mutants that must all be caught, and a stand-in board so every hardware check is tested — passing *and* failing — before the board sees it.
6. **The tool chain is small enough to read.** Synthesis is a yosys script; place and route is ~1 500 lines of Python you can modify in an afternoon; the bitstream is text (FASM) before it is bits. For learning, that is worth more than a production flow.
7. **Honest constraints.** Every timing exception is backed by an RTL guarantee (the 256-cycle `gce` gap) or a host limit (TCK ≤ 100 kHz), and `tests/test_reports.py` fails the build if the reports do not show timing closing.

### 5.3 Where bob is weaker — plainly

| | bob | the others |
|---|---|---|
| **Architecture coverage** | one fabric shape: 1 BLE per CLB, one BRAM and one DSP type, L4 unidirectional routing, W = 24 | OpenFPGA covers fracturable LUTs, multi-BLE clusters, many segment types, memory banks, and generates them all |
| **Targets** | one board (PYNQ-Z2, XC7Z020) | OpenFPGA targets silicon (SPICE, layout, PDKs); prjxray targets real Xilinx parts |
| **Timing** | VPR's numbers come from the reference 40 nm architecture and are *not* the emulated fabric's real speed; bob's own PnR is not timing-driven at all | OpenFPGA produces delay models from SPICE; VPR's timing-driven flow is used properly there |
| **Scale** | 100 CLBs; a design of 56 CLBs is "big" | a real overlay (ZUMA) or a taped-out OpenFPGA fabric is orders of magnitude larger |
| **Area efficiency** | configuration in flip-flops: ~186 bits per CLB-equivalent; the memory alone is ~18.5k flip-flops | ZUMA's whole point is LUTRAM configuration, which is far denser on a commercial host |
| **Design support** | one clock domain, no asynchronous resets or latches, no true tristate, no clock enables inferred from arbitrary logic | commercial and open flows handle all of this |
| **Bitstream realism** | bob's format is 7-series *shaped*, deliberately simplified (no encryption, compression, ECC, multiboot, bus-width detection) | prjxray documents the real thing, bit for bit |
| **Maturity** | a project built over days, by one person and an assistant, with a frozen reference implementation next to it | years of work, papers, users, CI |

### 5.4 What bob took from each, explicitly

- **OpenFPGA:** the tileable rr-graph method (let VPR build the routing, generate hardware to match), the `k6_frac_N10_tileable_adder_chain_dpram8K_dsp36_fracff_40nm` reference architecture's parameters (L4, Wilton Fs = 3, fc 0.15/0.10, hard-block columns), and the `scan_chain` / `frame_based` configuration protocols.
- **Aegis:** the shift + shadow register idea for a tile's configuration (so logic never glitches while a chain shifts), and its I/O and clock-tile notes.
- **AMD UG470/473/474/479 and prjxray:** the instruction codes, packet and register layout, CRC-32C over `{register, data}`, FAR semantics, startup order, readback and capture, the CLB/BRAM/DSP semantics, and FASM as the text form.
- **VTR/VPR:** packing patterns, the placer's annealing schedule, and PathFinder for the router.

### 5.5 The honest summary

bob is not a better OpenFPGA, and it is not trying to be: OpenFPGA is a research framework for building real FPGAs, and Aegis is a broader generator with SerDes, clock tiles and a PDK story. What bob has that neither emphasises is **an end-to-end, hardware-proven loop at a size one person can hold in their head** — architecture, RTL, two configuration protocols, partial reconfiguration, a complete tool chain and a verification strategy where every guard is deliberately broken to prove a test catches it. If you want to *learn* how an FPGA and its tools fit together, that loop is the thing worth copying.

---

## 6. When something goes wrong

| symptom | first thing to check | usual cause |
|---|---|---|
| `IDCODE 0xFFFFFFFF` | is the board programmed? is TDO wired? | the host bitstream is not loaded |
| IDCODE mismatch | `hw/build.cfg` tag vs what the board reports | an older bitstream in the PL |
| `bob load` refused: CRC error | `./bob info x.bit`, then `packets.dump` | a corrupted file, or a device/bitstream mismatch |
| DONE never rises | `cfgplane.status(p)` / `frames_stat(p)` | no CRC match after the last frame, or a load while GWE = 1 |
| readback ≠ `.bit` | compare as FASM (`bob fasm` vs `bitgen.features_from_word`) | a stale `.bit`, or a genuine memory fault |
| the design is dark | did you `--clock run`? what rate did `bob build` print? | a `--div` so large the clock ticks once per minute |
| LEDs disagree with the source | run the same design in `tb_cosim` | usually a PnR or FASM bug, which the model check normally catches first |
| a partial reload is refused | STAT `GHIGH_B`, `CRC_ERROR`, `WR_ERROR` | frames sent before the freeze was acknowledged, or a bad CRC — do a full load to recover |
| VPR cannot route | the design's CLB count vs the grid | too big, or a `.pcf` that pins signals impossibly |
| `make check` says a result is stale | the stamp in `software/bob/vpr/<name>/` | the architecture changed: `make rrgraph`, then `make vpr` |
| Vivado synthesis is very slow or crashes | the four rules in §3.24 | a part-select over the memory, `keep_hierarchy`, or the XDC in synthesis |
| timing does not close | `docs/reports/<tag>/timing.rpt` | a path that is not covered by the `gce` guarantee — read §17.2 of the report before relaxing anything |

---

## 7. Where to go next

- **`docs/bitstream-format.md`** — the exact protocol, section by section. Read §9–§13 if you touch configuration.
- **`REPORT.md` §19** — 42 problems and their fixes. It is the fastest way to learn the traps.
- **`PLAN.md` §10** — every milestone's "as built" notes, including what was deliberately left out.
- **`arch.html`** — click any block to see what it is, what it came from, and which testbench covers it.
- **Good first changes:** add an example design (§4.4); change the router's cost function in `software/bob/pnr/route.py` and watch `make pnr`; add a configuration field and a mutant for it (§4.5); try `--lut-k 4` end to end.
