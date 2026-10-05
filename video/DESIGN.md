# bob, explained: the film (design, 2026-10-05)

## Intent

A research-grade documentation video of bob as it stands at M26: every concept from A to Z
(the CLB, routing, JTAG, BRAM and DSP, every FSM, the scan chain, frame-based configuration,
bitstream generation, the tool flow, verification and results), for a professor or examiner.
Rendered MP4 with a narrating voice and burned-in subtitles, as a series of chapters
(about 3–4 minutes each, 35–45 minutes in all) plus one film of all of them.

## Decisions (agreed 2026-10-05)

| question | answer |
|---|---|
| deliverable | rendered MP4 + the source to re-render it |
| audience, length | professor / examiner; a ~40 minute series in chapters, plus the joined film |
| narration | macOS `say` (Daniel, en_GB) + burned-in subtitles + `.srt`; the script is also kept as text so it can be re-recorded |
| tool | Manim Community Edition in the mamba env `bobvideo` (conda-forge, ffmpeg included) |
| numbers | never typed: `facts.py` reads `software/bob/device.json`, the M26 reports and the committed counter example into `data/facts.json`; scenes read only that |
| git | source, script and facts committed; `out/`, `media/` and `.cache/` ignored |

## Layout

```
video/
  DESIGN.md        this file
  README.md        how to rebuild; the chapter table
  environment.yml  the bobvideo env
  facts.py         repo -> data/facts.json (fails if a source is missing)
  data/facts.json  every number a scene shows
  bobvid/          style.py (palette, diagram helpers), voice.py (say -> WAV, cached),
                   scene.py (BobScene: narrate blocks, subtitles, .srt, title/refs/files cards)
  scenes/chNN_*.py one chapter each
  build.py         --list | --preview | --final | --join
  script/          written by every render: chNN.md narration and chNN.srt subtitles
  out/             generated (ignored): chNN.mp4, bob_explained.mp4
```

## Mechanism

`with self.narrate("sentence. sentence."):` wraps the animations a passage describes. Each
sentence is spoken to its own cached WAV; the block's WAV is their concatenation, added at the
block's start time. The subtitle shows the current sentence (two lines at most) in a reserved
band at the bottom of the frame (y < −3.0). On exit the block waits until its audio has ended,
so the picture never runs ahead of the voice. Text may carry `{shown|spoken}` pairs so a
caption reads `UG470` while the voice says "U G four seventy".

## Chapters

| # | title | covers |
|---|---|---|
| 00 | An FPGA inside an FPGA | host vs guest, PYNQ-Z2 + Pico, the five layers, the M0–M26 path |
| 01 | What an FPGA is | LUT = truth table = mux tree, configuration memory, the four ingredients |
| 02 | Architecture as data | `device.py`, the 14 × 12 grid, VPR arch, rr graph → `fabric_gen` (OpenFPGA method) |
| 03 | The CLB | N = 4 cluster, crossbar, fracturable LUT6, carry, FDRE/FDSE, INIT vs SRVAL, Double Duty, the bits, CFGLUT5 + OR roots |
| 04 | Routing | channels W = 36, L4, Wilton Fs = 3, connection boxes, `bob_mux` encoding, dark fabric, LUT6/MUXF7/MUXF8 |
| 05 | BRAM and DSP | UG473 1024×18 TDP, write modes, contents vs config; UG479 trimmed DSP, opmodes, cascade |
| 06 | I/O and the user clock | BC_1 cells, INTEST/SAMPLE, `gce`, gap guard, synchronisers, the freeze handshake |
| 07 | JTAG | 4 wires, the 16-state TAP FSM walked, timing contract, IR table, Capture-IR status, TDO high-Z |
| 08 | Configuration memory and the chain | `cfg_store`, the frame buffer, CHAIN_IN, CRC-32C, write key, the startup FSM, BRAM shadow |
| 09 | Frame-based configuration | sync hunt, packet parser FSM, registers, FAR, FDRI/FDRO, CMD, CRC, partial reconfiguration, BRAM frames, GRESTORE |
| 10 | Bitstream generation | yosys → equivalence → VPR/bob PnR → FASM → bitgen → `.bit` v2 → `bob load`, on the counter |
| 11 | Verification and results | models as oracles, mutants, stand-in board, 74/74, Vivado numbers, vs OpenFPGA/Aegis/ZUMA, references |

Each chapter ends on a files card: what implements it and what proves it.

## Checks

- `facts.py` fails if any source file or field is missing; scenes take numbers only from `facts.json`.
- every render writes the narration (`script/chNN.md`) and subtitles (`script/chNN.srt`); `build.py --list` reports running times.
- Every chapter is rendered at preview quality and inspected frame by frame (stills extracted
  at each narration block) for overlap or clipping before the final render.
- Final: 1080p30; each chapter's partial movie files are deleted once it is assembled (disk is tight).
