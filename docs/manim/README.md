# bob, explained — the film series

Manim (Community Edition) explainers, one topic per episode, built the way this
repo builds its other pages: parts in `parts/`, one `build.py`, nothing
hand-edited in the output.

```sh
python3 docs/manim/build.py           # write every episode that has a part file
python3 docs/manim/build.py --list    # the series, and what exists
python3 docs/manim/build.py ep01_clb  # just one
```

Each episode is emitted twice from the same source:

| output | what it is |
|---|---|
| **`bob_explained.ipynb`** | **the whole series in one notebook — one cell per episode** |
| `epNN_name.py` | one self-contained `%%manim` cell (prelude inlined), for pasting |
| `epNN_name.ipynb` | that single episode as its own notebook |

`bob_explained.ipynb` is the one to open. Run the two setup cells once
(`!pip install manim`, then the prelude), and after that **each episode is a
single cell** — run it and its video appears inline.

Prerequisite, once per notebook, in a cell of its own:

```python
!pip install manim
from manim import *
```

Then paste the episode cell. `-ql` for a draft, `-qm` for medium, `-qh` for
1080p60. The class names listed at the top of every cell render **one section**
instead of the whole episode, which is how you re-watch a single idea.

No LaTeX anywhere (every label is `Text`/Pango), no `Code` mobject, hex colours
and the Pango generic `"monospace"` — so it renders on a bare Colab.

## The series

| # | episode | covers | state |
|---|---|---|---|
| 1 | **The CLB** | where a CLB sits in the grid · the LUT → carry → flip-flop datapath · the LUT as a mux tree and the O6/O5 fracture · MUXCY/XORCY and why carry runs south→north · the flip-flop priority ladder (`gsr` > `gwe && gce` > `sr` > `ce`) · **all 71 bits named** · a worked 2-input AND down to `INIT = 64'h8888…` | done |
| 2 | **JTAG** | four wires and why TCK clocks the whole chip · the 16-state TAP, walked · the timing contract (TMS/TDI rising, TDO and updates falling, LSB-first) · the full 6-bit instruction table · Capture-IR as a status read · BC_1 boundary cells and INTEST/EXTEST/SAMPLE | done |
| 3 | **The configuration engine** | 18 560 bits = 145 frames · where a tile's bits actually sit (column-major frames, row-major blocks) · path A: the streamed chain + CRC-32C + length · path B: UG470 packets, FAR, registers, CMD · the CRC over `{register, data}` · startup GSR→GTS→GWE→DONE · every refusal | done |
| 4 | **I/O, pads and the clock** | the I/O block as one VPR pad + two boundary cells · GTS · the board pad map · `clock_ctrl.v`: `gce` as the user clock, the two clock modes, the 256-cycle gap guard and why timing depends on it · the ASYNC_REG synchronisers | done |
| 5 | **BRAM** | UG473 subset: 1024×18 true dual port · the 8 configuration bits · write modes rebuilt from READ_FIRST · DOx_REG · contents as a separate thing from configuration (USER4, then FAR block type 001) | done |
| 6 | **DSP** | UG479 trimmed: A25/B18/C48/D25, pre-adder, 25×18 signed, P48 · the 16 configuration bits · the four static opmodes · the PCOUT→PCIN cascade · the private DSP instruction | done |
| 7 | **Routing** | connection box and switch box as rr-graph nodes · L4 unidirectional, W = 24, Wilton Fs = 3 · `bob_mux` encoding (0 = const0, IPIN 1 = const1) · why an all-zero chain is dark and loop-free · directs · the LUTLP-1 combinational-loop story | done |
| 8 | **Synthesis with yosys** | the bob cell library · the `synth_xilinx` pass order · `$alu` → `BOB_ADD` and the `_80_` rule-priority trap · `memory_libmap` · `abc -lut K` · source == netlist == golden equivalence, and the biased-vector bug that made the counter's trace all zeros | done |
| 9 | VPR and place-and-route | VPR's two roles, the rr graph, node → `bob_mux`, route → bits, the four Python boundaries, and M12a's own PathFinder/annealing PnR | done |
| 10 | **Bitstream generation** | FASM as the interface · feature → field → chain position · `bitgen` refusing bits no feature owns · the `.bit` v2 container, BRAM and META sections, file CRC · `bob load` and readback | done |
| 11 | **The whole flow** | a design by hand on the `bitstream.py` API vs `./bob build` · every check between the two commands · golden co-simulation · the stand-in board · what a board run actually does | done |
| 12 | **What is ours** | honest comparison with OpenFPGA, Aegis, ZUMA, prjxray/F4PGA: what bob borrows, where it diverges, what is genuinely new (one device description driving RTL + arch + model + FASM + host tools; two configuration paths on one memory; partial reconfiguration that provably keeps state; hardware proof every milestone) and where it is smaller | done |
| 13 | **Every error we hit** | the 42 entries of the problems table, told as stories: Tcl in the XDC, the guard nobody tested, the counter trace of all zeros, the frame write as a part-select, `keep_hierarchy` crashing Vivado, stale BRAM words, route branches in the wrong order, the carry mutant pinned to a grid position | done |

## Adding an episode

1. Write `parts/epNN_name.py`. It may use anything in `parts/prelude.py`
   (`mono`, `code_block`, `panel`, `chip`, `arrow`, `mux_symbol`, `bitcells`,
   `fieldbar`, `filecard`, `mid`, `clear_all`, and `BobScene.heading` /
   `.titlecard` / `.files_used`).
2. Give each section a function `sN_name(sc)` and a thin `class ENNSnName(BobScene)`
   wrapper — `build.py` finds those by name and lists them as render targets.
3. End with `class EpNNName(BobScene)` that plays `titlecard` then every section.
4. `python3 docs/manim/build.py`.

Every episode closes with a **Files** card: what is written by hand, what is
generated from it, and what proves it — so the film always points back at the
repo.
