> **bob_full_v1 note:** this README describes the M0 baseline inherited from `bob/` (4-bit IR, `IR_CONFIG` chain, old paths like `rtl/`). For the current plan, layout and status see [`PLAN.md`](PLAN.md).

# A 4×4 CLB fabric with a bitstream compiler, on the PYNQ-Z2

A miniature FPGA built inside the PL of a real one: sixteen configurable logic
blocks in a routed mesh, a 2896-bit configuration chain, an IEEE 1149.1 boundary
scan ring on the pads, and a place-and-route engine that turns a Python design
description into the bits. Everything is driven from a Raspberry Pi Pico running
DirtyJTAG on the PMODA header.

```sh
./host/fpga.py --load showcase      # compile, route, load, and run it
```

```
showcase: AND, OR and XOR of the two switches on the three LEDs

design: 3 LUT(s), 13 switch-box mux(es) used
  tile(0,0)  INIT=0x8888888888888888  i0=pad_i[0], i1=pad_i[1]
  tile(1,1)  INIT=0xEEEEEEEEEEEEEEEE  i0=pad_i[0], i1=pad_i[1]
  tile(2,2)  INIT=0x6666666666666666  i0=pad_i[0], i1=pad_i[1]
  route tile(0,0) -E0->  ('cell', 0, 0, 'o')
  ...
  loaded 2896 bits in 0.14s (bulk), readback verified

   pads in    SW1=1 SW0=1   BTN3..0 = 0000   (pad_i = 000011)
   pads out   LD2=0  LD1=1  LD0=1
   model      011                     match
```

Flip SW0 and SW1; LD0 is their AND, LD1 their OR, LD2 their XOR. Load a
different design and the same silicon does something else.

## The architecture

`rtl/clb_pkg.sv` defines it and is the authority. It came from `../both`
unchanged, and it already specified the whole fabric — this project implements
that specification rather than inventing one.

| Structure | Bits | What it is |
|---|---|---|
| CLB | 71 | fracturable LUT6 + flip-flop + carry chain |
| Connection box | 30 | 6 LUT-input muxes × 5 bits |
| Switch box | 80 | 4 directions × 4 tracks × 5 bits |
| **Tile** | **181** | CLB + CB + SB |
| **Fabric 4×4** | **2896** | 16 tiles, tile 0 at the low end |

Every mux in a tile chooses from the same 20-entry source bus:

```
0        const 0
1        const 1
2        this tile's CLB o
3        this tile's CLB o5      <- feedback, needs no routing
4..7     tracks arriving from the North
8..11    tracks arriving from the East
12..15   tracks arriving from the South
16..19   tracks arriving from the West
```

Tracks are point to point. Driving tile T's switch box output in direction D on
track t makes that signal arrive at T's neighbour on the opposite side, same
track number. The carry chain runs South to North up each column, so a column
of four tiles is a four-bit adder.

### Where the pads meet the fabric

Signals flow West to East, which makes a design read as a left-to-right
dataflow:

- **inputs** — every row's West edge carries `pad_i[3:0]` on tracks 0–3; every
  column's South edge carries `pad_i[4]` on track 0 and `pad_i[5]` on track 1
- **outputs** — `pad_o[k]` is row *k*'s East edge, track 0, for k = 0,1,2

So column 0 can reach `pad_i[3:0]` directly and row 0 can reach all six;
anything further in has to be routed there through switch boxes, which is the
part that makes this a fabric rather than a lookup table.

On the board: `pad_i[5:0]` is `{BTN3..BTN0, SW1, SW0}` and `pad_o[2:0]` is
`{LD2, LD1, LD0}`. LD3 lights once a non-zero bitstream is loaded.

## The bitstream engine

`host/bitstream.py` mirrors `clb_pkg.sv` constant for constant, and adds
placement, routing and a software model.

```python
from bitstream import Design, LUT

d = Design()
a, b = d.input(0), d.input(1)
g_and  = d.lut(0, 0, LUT.and2(), [a, b])      # place an AND at tile (0,0)
g_nand = d.lut(2, 2, LUT.inv(0), [g_and])     # invert it three tiles away
d.output(0, g_and)
d.output(2, g_nand)
bs = d.build()                                 # place, route, pack 2896 bits
```

`build()` runs a breadth-first search over tiles, allocating one switch box mux
per hop. A mux already carrying the same signal is free to traverse again, which
is how fanout works with no special case. `d.report()` prints the placement and
every route it took; `simulate(bs, pad_i)` evaluates the packed bitstream in
software.

That software model is not a convenience — it is the cross-check. `sim/gen_vectors.py`
builds each design with the real engine, computes expected outputs with the
model, and emits `sim/vectors.vh`. The testbench loads *the same bits* into the
RTL. If the generator and the fabric disagree about what a bitstream means, a
named vector fails.

## Quickstart

```sh
./sim/run_fabric_sim.sh                # 174 checks, including 11 compiled designs
./sim/lint.sh

vivado -mode batch -source vivado/create_project.tcl            # build
vivado -mode batch -source vivado/create_project.tcl -tclargs all # build + program

./host/fpga.py --list                  # what is built in
./host/fpga.py --report three          # place and route it, no hardware needed
./host/fpga.py --load showcase         # compile, load, run
./host/fpga.py --selftest              # load every design, verify through INTEST
```

One script does the whole flow in one Vivado session — creating and building
separately meant the second script had to re-open a project the first had
already opened, which is the "project already opened" error.

```sh
vivado -mode batch -source vivado/create_project.tcl                 # build
vivado -mode batch -source vivado/create_project.tcl -tclargs all    # build + program
vivado -mode batch -source vivado/create_project.tcl -tclargs program  # program only
```

Append a top module to build the other design, e.g. `-tclargs build mini_fpga_top`,
or just `-tclargs mini_fpga_top`.

## Two builds, told apart on the wire

| IDCODE | Top | CONFIG | Tool |
|---|---|---|---|
| `0x2BEEF093` | `mini_fpga_top` | 71 bits | `host/minifpga.py` |
| `0x3BEEF093` | `fpga4x4_top` | 2896 bits | `host/fpga.py` |

The version nibble tracks the design, and every tool checks it, so loading the
wrong bitstream says so instead of behaving strangely. `host/detect.sh` names
whichever one it finds.

They share the TAP, the instruction set and the boundary ring; only `CFG_W`
differs. The single-CLB build is the one that came up on hardware first and is
worth keeping as a fallback.

## Driving it from JTAG

The switches are convenient but they are not the point — the boundary scan ring
can take them over.

```sh
./host/fpga.py --load xor --bscan
```

```
  mode INTEST   -   boundary drives the fabric - the switches are disconnected

   bit         8  7  6  5  4  3  |  2  1  0
   signal     i5 i4 i3 i2 i1 i0  | o2 o1 o0
   driving    0  0  0  0  1  1  |  -  -  -
   captured   0  0  0  0  0  1  |  0  1  1

   scan = 000001011     pins i[5:0] = 000001     LEDs = 011
   the fabric is seeing 000011, not the switches (000001)
   model = 011   match

   0-5 toggle an input bit      a all inputs on      z all off
   7 8 9 toggle an output pad (EXTEST only)
   i INTEST    e EXTEST    s SAMPLE    r re-read    q quit
```

Keys `0`–`5` toggle the LUT inputs one bit at a time and the result appears on
the LEDs and in the scan. Three instructions give three different relationships
to the same nine cells:

| key | mode | the boundary… |
|---|---|---|
| `i` | INTEST | **drives** the fabric's inputs and captures its outputs — you are the switches |
| `e` | EXTEST | **drives** the output pads; the fabric is isolated, so keys `7`–`9` light LEDs directly |
| `s` | SAMPLE | drives nothing and just **watches** — the fabric runs from the real switches |

Read the two rows carefully, because they are not the same thing. A BC_1 cell
captures its system input *whatever the mode is*, so in INTEST bits 8:3 come
back as the **physical pins**, not the vector you are injecting. You see both at
once: what the switches are actually doing, and what the fabric makes of what
you sent it instead. In the capture above SW0 is genuinely on, and the fabric is
being told `000011` regardless.

### Why INTEST needs three scans, not two

In INTEST *every* cell drives — including the three output cells. So the LEDs
are fed from those cells' update registers, not from the fabric. Shift zeros
into bits 2:0 and the pads are actively held dark no matter what the logic
computes; the fabric's answer arrives only by **capture**, never by itself
reaching a pad.

So each step is three scans: apply the vector, capture what the fabric made of
it, then write that answer back into the output cells so the board shows it.
The LEDs mirror the fabric one scan behind, and the console says so on screen.

This is correct IEEE behaviour rather than a quirk to work around — it is the
same separation that makes EXTEST possible at all. But it is genuinely
surprising the first time the scan reads `LEDs = 001` while the board sits
dark.

`--bscan` on its own skips the config load and takes over whatever is already
in the PL.

If the single-keystroke display misbehaves on your terminal, `--lines` switches
to typing a key and pressing Enter. The console also falls back to that on its
own if it cannot put the terminal into cbreak mode.

## The instruction set

| IR | name | register | width | what it does |
|----|------|----------|-------|--------------|
| `0000` | EXTEST | boundary | 9 | the boundary drives the LEDs; the fabric is isolated |
| `0001` | SAMPLE/PRELOAD | boundary | 9 | observe the pins without touching them |
| `0010` | IDCODE | idcode | 32 | which build is loaded |
| `0011` | USER | user | 32 | control in `[3:0]`; **all 16 CLB outputs** in `[19:4]` |
| `0100` | INTEST | boundary | 9 | drive the fabric's inputs, capture its outputs |
| `0101` | CONFIG | config | 71 or 2896 | the bitstream, readable and writable |
| `1111` | BYPASS | bypass | 1 | one flop |

`urjtag`'s `discovery` maps all of this with no database entry at all, which is
the quickest independent confirmation the fabric decodes what it should.

## Three things worth knowing before you debug this

**CONFIG, USER and the boundary are all read-modify-write.** Whatever you shift
in is committed at Update-DR. A "read" that shifts zeros in returns the right
answer and then leaves zeros behind it. Shift the same word back to read
non-destructively — `load_bitstream()` does, and then verifies.

**INTEST is pipelined by one scan.** What a scan captures answers the vector the
*previous* scan committed. Sweeping a truth table is one scan per row plus one
more at the end.

**The fabric contains combinational loops by construction, and Vivado will
stop the build over it.** A mesh where any switch box mux can select any
neighbouring track has cycles in the netlist graph: tile A's east output can
feed tile B whose west output feeds tile A. Whether a loop actually *exists*
depends on the bitstream — and none that `host/bitstream.py` emits contains
one, because the router builds a tree from each source to its sinks.

Verilator says `UNOPTFLAT`. Vivado fails implementation with:

```
[DRC LUTLP-1] Combinatorial Loop Alert: 1569 LUT cells form a combinatorial loop.
```

Of Vivado's two documented resolutions, naming a net per loop with
`ALLOW_COMBINATORIAL_LOOPS` is not workable here: there are many loops and the
net names are synthesis output that changes every build. So the check is
downgraded instead, in `constr/pynq_z2_jtag.xdc` and re-applied by
`vivado/drc_waiver.tcl` as a hook on `opt_design` and `write_bitstream` —
a DRC severity is a tool setting rather than a design property and does not
reliably survive every step.

**The downgrade is scoped to `fpga4x4_top`.** The single-CLB build has no mesh
and must never trip LUTLP-1; if it ever does, that is a real bug and masking it
would be wrong.

One consequence worth keeping in mind: Vivado breaks the loops arbitrarily for
static timing analysis, so some paths are not analysed and WNS is indicative
rather than exhaustive. That is why TCK is constrained at 1 MHz for the fabric
against a link actually driven at 100 kHz to 1 MHz — the margin is deliberate,
not accidental. The single CLB is shallow and stays at 5 MHz.

## The design

Pure PL: no Zynq PS, no AXI, no block design, no system clock. **TCK clocks the
entire chip**, which keeps everything in one clock domain — no CDC to get wrong,
no free-running core clock for a scan to race against.

Timing contract, the part that is easy to get wrong by one edge:

- TMS and TDI are sampled on the **rising** edge of TCK
- the state machine advances on the **rising** edge
- TDO is launched on the **falling** edge
- IR/DR update latches fire on the **falling** edge
- all shift registers are LSB-first

### Why `bsc_cell.v` takes Test-Logic-Reset synchronously

`bsc_cell.v` came from `../both` unchanged, and its header documents what
happened on hardware when that reset was asynchronous: the boundary silently
commits zeros at Update-DR, EXTEST and INTEST both fail, and capture and shift
still look perfect.

That warning is not specific to their state encoding. A combinational decode of
`TEST_LOGIC_RESET` can glitch in ours too, on three transitions where source and
destination between them set every bit:

```
RUN_TEST_IDLE 1100 -> SELECT_DR 0111
CAPTURE_IR    1110 -> EXIT1_IR  1001
UPDATE_IR     1101 -> SELECT_DR 0111
```

Nothing constrains four bits to change together, so `tlr` is only ever consumed
on a clock edge.

### Loading 2896 bits

One USB round trip per bit is fine for a 32-bit IDCODE and hopeless for the
config chain. `shift_dr_fast()` uses DirtyJTAG's `CMD_XFER`, which shifts up to
496 bits per packet with TMS held low. Two things matter: data is **MSB-first
within each byte** (pinned down by `jtag_set_tdi` writing `1u << 7`), and only
whole bytes go that way — the ragged tail and the final TMS=1 bit are ordinary
pulses. Every load is verified by readback and falls back to the per-pulse path
if the bulk transfer disagrees.

## Provenance

| file | origin |
|---|---|
| `rtl/clb_pkg.sv`, `lut6.sv`, `clb.sv`, `bsc_cell.v` | `../both`, byte-identical |
| `rtl/jtag_tap.v` | this project — the TAP that came up on hardware |
| `rtl/mux_bank.v`, `tile.v`, `fabric.v`, `fpga4x4*.v` | new, implementing `clb_pkg.sv`'s spec |
| `rtl/mini_fpga*.v` | the single-CLB build |

## Tools

```
host/bitstream.py    architecture model, placement, routing, software model
host/designs.py      the example designs, shared by simulation and hardware
host/fpga.py         compile, load and run on the 4x4 fabric
host/bscan.py        interactive boundary-scan control (INTEST/EXTEST/SAMPLE)
host/minifpga.py     the same for the single-CLB build
host/dirtyjtag.py    shared transport: TAP navigation and bulk shifting
host/tap_probe.py    raw TDO stream, --leds, --loopback, --idle
host/wire_check.py   test each jumper, then the PMODA pin numbering
host/detect.sh       IDCODE read, naming whichever build it finds
sim/gen_vectors.py   turn the designs into simulation vectors
```

`openFPGALoader` prints the IDCODE then stops with `Unknown device` — that is
success, not failure; it has no database entry for a TAP that is not a real
FPGA. Use urjtag past detection.

## If it does not answer

| Symptom | Cause |
|---------|-------|
| IDCODE is `0x1BEEF093` or `0x2BEEF093` | an older build is loaded; rebuild and reprogram |
| IDCODE all `0` or all `1` | TDO unwired, wrong pin, or no bitstream |
| IDCODE rotated by n bits | clock-edge problem, not wiring |
| Readback mismatch after a bulk transfer | the tool retries per-pulse and says so |
| Garbage at 1 MHz, fine at 100 kHz | lead length or missing ground return |
| Nothing at all, no error | TDI/TDO crossed — they are **not** crossed in JTAG |
| DONE is lit but nothing answers | DONE stays lit for *any* bitstream. `./host/wire_check.py --orient` probes the pull-up on TMS and pull-down on TCK, which exist only while our design is loaded |

Configuration is volatile: re-run `create_project.tcl -tclargs program` after
every power cycle. That skips the build and just reloads the bitstream.

See [`docs/wiring.md`](docs/wiring.md) for the harness and
[`pico/README.md`](pico/README.md) for the probe firmware.
