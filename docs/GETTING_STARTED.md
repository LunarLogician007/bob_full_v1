# Getting started with bob

bob is an FPGA built inside the FPGA of a PYNQ-Z2: 100 CLBs of four 6-input LUTs (400 LUTs,
400 flip-flops, a carry chain), 2 block RAMs and 2 DSP slices. You write Verilog for it, and
`./bob` synthesises, places, routes and loads it, over JTAG, from a Raspberry Pi Pico. Every
step also works with no board at all: `--probe fake` is the board in software.

This page takes you from nothing to your own design running, in about ten minutes.

## 1. Install

On a Mac (Linux works the same way with its own package manager):

```sh
brew install yosys icarus-verilog        # synthesis, and the check that it kept your design
pip3 install pyusb pywebview             # the Pico, and bob studio as a desktop app
brew install colima docker && colima start   # optional: VPR, the default place and route
```

Then ask bob what it found:

```sh
./bob doctor
```

`ok` lines are fine. `--` lines are optional: without Docker, build with `--pnr python`
(bob's own place and route); without pywebview, `./bob studio` opens in the browser. A `FAIL`
line says what to install.

## 2. Run an example

```sh
./bob examples                                            # the example designs, one line each
./bob run work/examples/counter/counter.v --probe fake    # build it and run it on the fake board
```

`run` builds the design, loads it and reads the LEDs once. The build prints one line per
stage, then what the design used and what to run next:

```
  PASS  built build/bit/counter.bit in 5.0 s
    uses    LUTs 0/400  flip-flops 6/400 (2%)  carry bits 6/400 (2%)  BRAMs 0/2  DSPs 0/2
    clock   stepped over JTAG; for a free-running clock up to 31.2 MHz build with --clock run --hz auto
  PASS  load build/bit/counter.bit: loaded 532 frames (2128 words) through CFG_IN, ..., DONE
    LEDs    LD2..0 = 000   (SW1..0 = 00, BTN3..0 = 0000); add --watch to follow them
```

With the board plugged in, drop `--probe fake`. Add `--watch` to follow the switches and
LEDs live (Ctrl-C stops watching; the design keeps running).

## 3. Your own design

```sh
./bob new blink                  # blink/blink.bobproj and blink/src/blink.v from a template
./bob run blink --probe fake     # a project folder builds like a file
./bob new mine --from fir        # or start from a copy of an example
```

The template is a 3-bit counter on the LEDs. Edit `blink/src/blink.v` and run it again. The
same folder opens in bob studio (Open Project… on its Start page).

## 4. Pins: which port names reach the board

```sh
./bob pins
```

A design whose ports are named like this needs no pin file:

| port | board |
|---|---|
| `input clk` | the user clock (see 5) |
| `input [1:0] sw` | SW1, SW0 |
| `input [3:0] btn` | BTN3 … BTN0 |
| `output [2:0] led` | LD2, LD1, LD0 |

Any other names need a `.pcf`, one line per port bit, and `--pcf` on the build:

```
set_io a      SW0
set_io y[0]   LD0
set_io probe  pad17
```

A port with no pin stops the build at the start of place and route, with its name.

## 5. The clock

By default the host steps `clk` over JTAG: one edge per step, slow and exact, which is what
the checks use. For a design that runs on its own:

```sh
./bob build fast.v --clock run --hz auto      # as fast as this design's timing allows
./bob build slow.v --clock run --div 15       # 125 MHz / 2^(15+9), about 7.45 Hz: a visible blink
./bob build d.v --sdc clocks.sdc              # create_clock -period 50 [get_ports clk]; fails if missed
```

Every build reports its critical path. bob refuses to load a design faster than that path
allows, so a design that loads also meets its timing.

## 6. Block RAM and DSP

Write a memory the usual way (`reg [15:0] mem [0:1023]` with a registered read) and a
multiply as `a * b`; yosys maps them onto bob's 2 BRAMs (1024 × 18 each) and 2 DSP slices.
`work/examples/ram` and `work/examples/fir` show both.

## 7. The board

1. Program the PYNQ-Z2 with bob's own bitstream (`docs/reports/M25/bob_top.bit`, from Vivado
   or the PYNQ image); this is the FPGA that bob is.
2. Plug the Pico (DirtyJTAG) into USB and into PMODA.
3. `./bob doctor` should end with `board  IDCODE 0x0B025093: the bob bitstream is running`.

Then `./bob load x.bit` configures bob with your design. `./bob load x.bit --partial` swaps a
running design for another, rewriting only the frames that differ, with its clock held.

## 8. bob studio

```sh
./bob studio            # the desktop app
./bob studio --browser  # the same in a browser tab
```

It opens on the **Start page**: the flow in five steps, every example with **Open** and
**Build & Program**, your projects, and the setup check. In the editor, **⌘/Ctrl Enter** builds
and **⌘/Ctrl ⇧ Enter** builds and programs; unsaved edits are saved first. A failed build
lists its errors under **Messages** with a hint; clicking one jumps to the line. **Device**
shows where the design landed, **Board** the LEDs and switches, **Waveform** a logic analyser on
the pads.

## 9. Debugging a running design

```sh
./bob snap save before              # every flip-flop of the running design
./bob snap sim before --steps 10 --save later   # run it on in the simulator
./bob snap restore later            # and put that state back on the chip
./bob snap list
```

`./bob info x.bit` says what a bitstream holds (design, pins, placement, timing, clock);
`./bob info x.bit --raw` prints every stored field.

## 10. When a build fails

bob names the stage, the file and line, shows the line, and suggests what to do:

```
  FAIL  synth: yosys failed on t
        t.v:2: syntax error, unexpected TOK_ID
            2 | assign led = 3b101;
  hint  fix that line and build again
  log   build/synth/t/t.log
```

| it says | do this |
|---|---|
| `no such file` | check the path; `./bob examples` lists the examples |
| `does not fit bob: it needs 520 LUTs (bob has 400)` | make the design smaller |
| `port(s) … have no pin` | rename the ports (`./bob pins`) or give a `--pcf` |
| `docker not found` / `is Docker running?` | `colima start`, or build with `--pnr python` |
| `did not route` / `Routing failed` | `--seed 5`, `--pnr python`, or a smaller design: bob's routing is thin |
| a timing `slack` below zero | a slower clock, or `--clock run --hz auto` |
| `no DirtyJTAG probe found` | plug the Pico in, or use `--probe fake`; `./bob doctor` |
| `the board answers IDCODE …, not bob's` | program bob's bitstream onto the PYNQ-Z2 first |

## Where next

- [`docs/learn/bit_by_bit.html`](learn/bit_by_bit.html) and
  [`docs/learn/layer_by_layer.html`](learn/layer_by_layer.html): animated tours of how bob works.
- [`docs/project/GUIDE.md`](project/GUIDE.md): every part, what it is and how to tweak it.
- [`README.md`](../README.md): the device, the milestones, the folder map.
