# One design through the whole bob flow, every file kept

This folder is `work/examples/counter/counter.v` (a 6-bit counter: BTN0 enables, BTN1 resets,
LD2..0 show the top three bits) taken through every stage of bob's flow. Each numbered folder
is one stage: what went in, what came out, and readable views of it. The same design runs
through the slides (`docs/presentation/bob_m26_tech.tex`), so every number there can be found
here.

It is generated, not written by hand, and the tools are the real ones, run the way
`./bob build` runs them:

```sh
python3 example/make_example.py                  # regenerate this folder (about 15 s)
python3 example/make_example.py --reuse-vpr      # without Docker: copy the committed VPR result
python3 example/make_example.py --design fir --out build/example_fir   # any other example
```

Needs yosys and iverilog. Step 04 runs VPR in OpenFPGA's Docker image (`colima start`).
Steps 10 and 11 run on the **stand-in board** (`software/host/fakeboard.py`, which answers JTAG
the way the PYNQ-Z2 does); on the real board the same file loads with
`./bob load example/07_bitstream/counter.bit`.

## The flow at a glance

```
 00_rtl            counter.v
   | yosys + bob's cell library                        software/bob/synth.py
 01_synthesis      counter.json / .blif / _syn.v       6 BOB_ADD + 6 BOB_FDRE, 0 LUTs
   | iverilog: source == netlist == golden, 300 cycles software/bob/equiv.py, golden.py
 02_equivalence    golden netlist, testbench, trace
   | constants, carry chains, pins                     software/bob/vpr_run.py prepare
 03_vpr_prepare    counter.eblif, .vpr.json, .pins
   | VPR 9 on bob's architecture and rr graph          vpr_run.py (Docker)
 04_place_route    counter.net / .place / .route + VPR's logs and reports
   | (a picture of it)
 05_layout         layout.svg, layout.txt, route_in_words.txt
   | fasm_from_vpr.py, checked against device.json
 06_fasm           counter.fasm, feature_map.txt
   | bitgen.py, packets.py
 07_bitstream      counter.bit + hexdump, frames, packet streams
   | timing.py on the bits
 08_timing         12.909 ns critical path -> 31.25 MHz
   | model.py on the bits == the source trace
 09_model_check    600/600 samples equal
   | cfgplane.py over JTAG (stand-in board)
 10_load           the JTAG transcript of the load
   | INTEST + autostep + CAPTURE, one user clock per scan
 11_run            the counter counting: table and VCD
```

`reports/` holds what `./bob build` itself prints (`build_log.txt`) and the record of every
stage it writes with `--json` (`flow_record.json`: time, numbers and messages per stage).

## Stage by stage

### 00_rtl: the design
| file | what it is |
|---|---|
| `counter.v` | the source Verilog. Ports follow the board convention (`clk`, `sw[1:0]`, `btn[3:0]`, `led[2:0]`), so no pin file is needed |

### 01_synthesis: yosys onto bob's cell library
Process: `software/bob/synth.py`, a yosys script in the shape of `synth_xilinx` with bob's cells.
| file | what it is |
|---|---|
| `inputs/synth_script.ys` | the exact yosys script that ran (read, proc, flatten, mul2dsp, alumacc, memory_libmap, dfflegalize, `abc -lut 6`, ...) |
| `inputs/bob_cell_library/bob_cells_sim.v` | bob's cells as yosys sees them: `BOB_ADD`, `BOB_FDRE`/`FDSE`, `BOB_BRAM18`, `BOB_DSP` |
| `inputs/bob_cell_library/bob_map.v` | techmap rules: `$alu` to `BOB_ADD` (one element per bit), flip-flops, the 25 x 18 multiplier to `BOB_DSP` |
| `inputs/bob_cell_library/bob_lut_map.v` | yosys `$lut` to bob's LUT cell |
| `inputs/bob_cell_library/bob_brams.txt`, `bob_brams_map.v` | the BRAM shape for `memory_libmap` (1024 x 18, two ports) and its mapping |
| `counter.json` | the synthesised netlist (yosys JSON): what place and route reads |
| `counter.blif` | the same netlist as BLIF |
| `counter_syn.v` | the same netlist as Verilog, for simulation |
| `counter.stat` | yosys's cell statistics |
| `yosys.log` | yosys's full log |
| `cells.txt` | the result in two lines: 6 `BOB_ADD`, 6 `BOB_FDRE`, and the named nets |

### 02_equivalence: is the netlist still the design?
Process: `software/bob/equiv.py` simulates the source, the netlist and a golden netlist together in
iverilog over 300 biased random cycles, and compares them before and after every clock edge.
| file | what it is |
|---|---|
| `counter_golden.v` | the netlist with **one named wire per bit** (`golden.py`), so each register can later be matched to a flip-flop on the chip |
| `counter_syn_renamed.v` | the yosys netlist, renamed so it can sit beside the source in one simulation |
| `tb_equiv.v` | the generated testbench (the 300 input vectors are in it) |
| `trace.txt`, `counter.trace.json` | the source's outputs before and after every edge: the reference that model.py (09) and the board are held to |
| `result.txt` | EQUAL, and the first 40 cycles of the trace |

### 03_vpr_prepare: the netlist VPR is given
Process: `vpr_run.prepare` rewrites the yosys netlist so that VPR sees only what the fabric can build.
| file | what it is |
|---|---|
| `counter.eblif` | the netlist for VPR: `bob_add` chains cut to the column height (a generator and a tap adder), `bob_ff`, constants folded |
| `counter.vpr.json` | what VPR does not carry: constant pins, FDRE vs FDSE, INIT values, yosys bit per net |
| `counter.pins` | every port fixed to its board pad (`btn[0]` on the pad wired to BTN0, ...) |
| `note.txt` | what was rewritten, and that this is the same netlist as the committed result (same sha256) |

### 04_place_route: VPR
Process: VPR 9 in OpenFPGA's Docker image: pack, place, route, analysis. It routes on the
committed routing-resource graph, the same graph the RTL fabric was generated from, so any
route it finds exists in the hardware.
| file | what it is |
|---|---|
| `inputs/bob_k6.xml` | bob's VPR architecture (written by `device.py`/`vpr_arch.py`): tiles, pins, the 4-element cluster, L4 wires, Wilton switch box, bob's measured delays |
| `inputs/bob_k6_rr.xml.gz` | the routing-resource graph (9,928 nodes); VPR reads it with `--read_rr_graph` |
| `inputs/command.txt` | the exact VPR command line |
| `counter.net` | **packing**: which atoms went into which cluster and element (XML) |
| `counter.place` | **placement**: each cluster's grid position (2 CLBs at (7,2) and (7,3), 6 pads) |
| `counter.route` | **routing**: every net as a list of rr nodes (pins, channel wires, tracks) |
| `counter.net.post_routing` | the packing after routing chose the pins |
| `vpr.log` / `vpr_stdout.log` | VPR's full log (wirelength 105, timing, run time) |
| `report_timing.setup.rpt`, `.hold.rpt`, `pre_pack.report_timing.setup.rpt`, `report_unconstrained_timing.*` | VPR's timing reports (on bob's delay model) |
| `packing_pin_util.rpt` | how full the packed clusters' pins are |
| `chanx_occupancy.txt`, `chany_occupancy.txt` | how many tracks are used in each channel segment |
| `summary.txt` | seed, image, wirelength, CLBs, and a check that this run is **identical** to the committed result in `software/bob/vpr/counter/` |

### 05_layout: what the chip looks like with the design on it
Made by `make_example.py` from `.place` and `.route` and the device description.
| file | what it is |
|---|---|
| `layout.svg` | the 14 x 12 grid: the I/O ring, 100 CLBs, the BRAM and DSP columns; used tiles filled, every routed wire drawn at its track, colour per net (open it in a browser; hover for names) |
| `layout.txt` | the same grid in text, and the list of placed clusters |
| `route_in_words.txt` | every net hop by hop: node, place, track, and the FASM select value that closes the hop (`rr6840 = 2 (selects node 7886)`) |

### 06_fasm: the configuration as text
Process: `fasm_from_vpr.py` turns the packing, placement and routing into FASM features, each
checked against `device.json`.
| file | what it is |
|---|---|
| `counter.fasm` | 79 lines (78 features and the clock mode) of `feature = value`: element flags (`clb_x7y2.e0.cy_en`, `.dd`, `.ff_en`, ...), crossbar selects (`.x5 = 5'h14`), routing mux selects (`rr6840 = 2'h2`) |
| `feature_map.txt` | **every feature, where its bits land and what it does**: chain bits, frame, word and bit in the frame, FAR, and the meaning (which input a mux selects, what a flag does) |

### 07_bitstream: the bits, and every readable form of them
Process: `bitgen.py` (FASM to the 68,096-bit configuration word, and back) and `packets.py` (the
UG470-style packet stream). The `.bit` here is written by `./bob build`, exactly as a user gets it.
| file | what it is |
|---|---|
| `counter.bit` | the bitstream file: header, the 68,096-bit chain, META (sources, hashes, clock), CRCs |
| `counter.bit.hexdump.txt` | the file byte by byte |
| `bit_info.txt` | `./bob info` and `./bob info --raw`: what is in the file, decoded |
| `bit_back_to.fasm` | the `.bit` decoded back into FASM: the round trip is exact |
| `frames.txt` | the configuration memory as 532 frames of 4 words, with FAR, the tiles each frame holds, and `*` on the 30 frames that hold a 1 |
| `stream_full.txt` | the full load stream, annotated (2,154 words) |
| `stream_sparse.txt` | the stream `./bob load` actually sends after JPROGRAM: 214 words, one FAR + FDRI per run of frames, then CRC, LFRM, START |
| `stream_sparse.hex` | those 214 words, one per line: the bits on the wire |

### 08_timing: timing from the bits
Process: `timing.py` walks only the selected mux inputs, register to register, with the delays
measured on the Vivado build (`software/bob/delays.json`).
| file | what it is |
|---|---|
| `timing_report.txt` | critical path 12.909 ns, hop by hop (clk to Q, crossbar 3.01, element 3.4, carry 5 x 1.0, setup 1.0); x 2 guard band = 4 sysclk cycles = 31.25 MHz; the timing contract's verdict |

### 09_model_check: do the bits do what the Verilog says?
| file | what it is |
|---|---|
| `model_check.txt` | `model.py` (a cycle model of the fabric RTL) loaded with these bits, run on the trace of 02: 600/600 samples equal; the first 64 cycles side by side |

### 10_load: loading over JTAG
| file | what it is |
|---|---|
| `load_log.txt` | `./bob load counter.bit --probe fake`: 30 of 532 frames, CRC 95ADDD48, FDRO readback of all 532 frames, DONE |
| `jtag_transcript.txt` | **every JTAG scan of the load**: JPROGRAM, CFG_IN with the 214-word stream, STAT, the read request (decoded), the 68,096-bit FDRO readback, JSTART, DONE = 1 |

### 11_run: the design running
| file | what it is |
|---|---|
| `run_table.txt` | 76 user clocks, stepped over JTAG (INTEST + autostep): the buttons applied, `q[5:0]` read from the flip-flops with CAPTURE, and the LEDs. `q` counts 0 to 63 and wraps; LD2..0 = `q[5:3]` |
| `counter.vcd` | the same run as a waveform (`clk`, `btn`, `led`, `q`) for GTKWave |

## Follow one wire through every file

The net `btn[0]` (the enable button) enters on the west edge and reaches the CLB at (7,3):

1. `04_place_route/counter.route`: its route runs `... 7886 CHANY -> 6840 CHANX -> 6862 ...`
2. `05_layout/route_in_words.txt`: `6840 CHANX (1,5)->(3,5) track 26,28,30   rr6840 = 2 (selects node 7886)`
3. `06_fasm/counter.fasm`: `rr6840 = 2'h2`
4. `06_fasm/feature_map.txt`: chain bits 3731..3732, frame 29 bits 19..20, FAR `0x00000119` (column 2, minor 25); input 1 = node 7886
5. `07_bitstream/frames.txt`: frame 29, word 0 = `00100000` (bit 20 set: the value 2 in bits 19..20)
6. `07_bitstream/stream_sparse.txt`: `FAR 0x00000119`, then `FDRI` with the word `00100000`
7. `10_load/jtag_transcript.txt`: that word goes out inside the 214-word CFG_IN scan, and comes back in the FDRO readback

8. In the RTL, `hw/src/generated/bob_fabric.v` line 3740, the multiplexer those two bits drive:
   ```verilog
   bob_mux #(.N(3), .W(2), .C1(0)) m6840 (.sel(cfg[3731 +: 2]), .in({r7893, r7886, r7860}), .o(r6840));  // CHANX (1,5)
   ```
   Select value 2 = input 1 = `r7886`: the wire from step 1.
