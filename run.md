# Running bob end to end, one step at a time

A walk through the whole flow with `work/examples/counter/counter.v` (a 6-bit counter:
BTN0 enables it, BTN1 resets it, LEDs show the top 3 bits). Every command runs from the
repository root. Expected outputs are the ones seen on the M16 device (`bob12x10`).

Part A builds the fabric (the host FPGA) and is only needed when the architecture changes.
Part B takes a guest design from Verilog to a running design on bob.

---

## Part A: the fabric (host FPGA)

The PYNQ-Z2 already holds the M16 fabric, so this part is usually skipped.

### A1. Generate the device files from the architecture

```sh
python3 software/bob/device.py --check      # are the generated files up to date?
python3 software/bob/device.py              # (re)generate them
```

- Reads: the `ARCH` dictionary in `software/bob/device.py` and the committed rr graph
- Writes: `software/bob/device.json`, `hw/src/generated/bob_params.vh`,
  `hw/src/generated/bob_fabric.v` (the fabric)

### A2. Build the routing graph with VPR (Docker; only after changing W, L, the grid, ...)

```sh
colima start
export DOCKER_HOST=unix://$HOME/.colima/default/docker.sock
python3 software/bob/device.py --arch-only  # writes software/bob/arch/bob_k6.xml
software/bob/vpr_rrgraph.sh                 # VPR dumps software/bob/arch/bob_k6_rr.xml.gz
python3 software/bob/device.py              # regenerate bob_fabric.v from the new graph
```

`make rrgraph` runs exactly these three.

### A3. Simulate and test the fabric

```sh
make sim        # every testbench (tb_bob, tb_frames, tb_bram, tb_dsp, ...)
make lint
make test       # pytest
make check      # all of the above plus the device checks
```

### A4. Build the host bitstream with Vivado (Windows)

```sh
make hw         # refreshes testbench vectors and prints the hand-off steps
```

On Windows: replace `E:\bob_full_v1\hw`, then Vivado → Tools → Run Tcl Script →
`hw/scripts/build.tcl`, and program the PYNQ. Copy `bob_vivado\out\<tag>\` back to
`docs/reports/<tag>/`.

---

## Part B: the guest design (Verilog → running on bob)

### B1. Synthesis: Verilog → bob cells

```sh
python3 software/bob/synth.py work/examples/counter/counter.v --top counter
```

- Output: `build/synth/counter/`: `counter.json`, `counter.blif`, `counter_syn.v`, `counter.stat`
- Expected: `counter: {'BOB_ADD': 6, 'BOB_FDRE': 6}` (6 carry CLBs and 6 flip-flops)
- Look at: `cat build/synth/counter/counter.stat`

### B2. Equivalence: is the netlist the same as the source?

```sh
python3 software/bob/equiv.py work/examples/counter/counter.v
```

- Expected: `PASS counter: netlist == source over 300 random cycles`
- Output: `counter.trace.json` (the reference trace every later check compares against)
  and `counter_golden.v`

### B3. Place and route (choose one)

**B3a: bob's own PnR (Python, no Docker)**

```sh
python3 software/bob/pnr/run.py counter
```

- Output: `build/pnr/counter/`: `.eblif .net .place .route .vpr.json`
- Expected: `7 CLBs, ... 3 routing iteration(s), wirelength 194`

**B3b: VPR (Docker)**

```sh
python3 software/bob/vpr_run.py counter           # → build/vpr/counter/
```

Same file formats, plus VPR's logs and reports. The committed result lives in
`software/bob/vpr/counter/` (`make vpr` re-routes every example).

Look at: `build/pnr/counter/counter.place` (where each block landed) and `counter.route`
(which rr nodes each net uses).

### B4. FASM: the PnR result as readable features

```sh
python3 software/bob/fasm_from_vpr.py counter
head -20 build/vpr/counter/counter.fasm
```

- Expected: `118 FASM features (85 routing muxes), legal against device.json`
- Lines look like:

  ```
  clb_x7y2.init = 64'h6666666666666666    LUT = XOR (the sum bit)
  clb_x7y2.cy_en = 1'h1                   carry mode
  clb_x7y2.ff_en = 1'h1                   registered output
  rr1055 = 3'h4                           routing mux of rr node 1055 selects value 4
  ```

- The command-line version reads the VPR result (`software/bob/vpr/counter/`). For the
  Python PnR result, `./bob build --pnr python` does the FASM step internally.

### B5. bitgen: FASM → configuration bits → `.bit`

```sh
python3 software/bob/bitgen.py build/vpr/counter/counter.fasm -o build/bit/counter.bit
python3 software/bob/bitgen.py --roundtrip build/bit/counter.bit   # bits → FASM → bits identical?
```

Expected: `wrote ...: 18560-bit chain for bob12x10` and `PASS ... identical`.

### B6. Inspect the `.bit`

```sh
./bob info  build/bit/counter.bit                                    # header, CRC, metadata
./bob fasm  build/bit/counter.bit | head                             # the configuration as FASM
python3 software/bob/packets.py dump build/bit/counter.bit | head -30  # the JTAG packet stream
```

The dump is exactly what goes on the wire:

```
FFFFFFFF  dummy
AA995566  sync
30008001  WRITE CMD      00000007  RCRC
30018001  WRITE IDCODE   FBEEF093
30002001  WRITE FAR      00000000
30008001  WRITE CMD      00000001  WCFG
30004000 / 5000xxxx  FDRI ... 580 frame words ...
... CRC, LFRM, START, DESYNC
```

### B7. B1–B6 in one command (the normal way)

```sh
./bob build work/examples/counter/counter.v -o build/bit/counter.bit                    # VPR result
./bob build work/examples/counter/counter.v --pnr python -o build/bit/counter_py.bit    # bob's PnR
./bob build work/examples/blinky/blinky.v --clock run --div 15 -o build/bit/blinky.bit  # free-running clock
```

It prints each stage: `synth → pnr → fasm → bits → model (600/600 samples == source trace) → write`.

### B8. Load it

Without the board (software stand-in that answers from `model.py`):

```sh
./bob load build/bit/counter.bit --probe fake
```

Expected: `loaded 145 frames (580 words) through CFG_IN, CRC ..., FDRO readback verified, DONE`.

On the PYNQ-Z2 (Pico attached, M16 bitstream in the PL):

```sh
./bob load build/bit/counter.bit                 # frame path (default)
./bob load build/bit/counter.bit --mode chain    # scan-chain path
./bob load build/bit/other.bit --partial         # partial reconfiguration
```

LD3 lights (DONE). The counter is JTAG-stepped by default; build it with
`--clock run --div 15` to see the LEDs count on their own while BTN0 is held.

### B9. Check it on hardware

```sh
make hwtest M=M16                     # full regression + M16 checks
make hwtest M=M16 ONLY=partial-live   # one check
cd software/host && ./hwtest.py --milestone M16 --list   # list checks; touches no hardware
```

---

## The same flow in a GUI

```sh
./host/studio.py --probe fake       # then open http://127.0.0.1:8765
```

Synthesis → Implementation → Generate Bitstream → Program, with a Device view showing
where the design landed and which channels it routed through.

---

## Where each step's output goes

| step | output |
|---|---|
| B1 synth | `build/synth/counter/` |
| B2 equiv | `build/synth/counter/counter.trace.json`, `counter_golden.v` |
| B3a Python PnR | `build/pnr/counter/` |
| B3b VPR | `build/vpr/counter/` (committed copy in `software/bob/vpr/counter/`) |
| B4 FASM | `build/vpr/counter/counter.fasm`, `.hex` |
| B5 bitgen | `build/bit/counter.bit` |
