# bob, explained: the film

A narrated, subtitled documentation film of bob at M26, from what an FPGA is to the
results on the board. Twelve chapters, each its own MP4, plus the whole film as one file.
Made with Manim Community Edition; narrated by macOS `say`; every number on screen comes from
the repository (`facts.py`), never typed into a scene.

| # | chapter | covers |
|---|---|---|
| 00 | An FPGA inside an FPGA | host vs guest, the PYNQ-Z2 and the Pico, the five layers, M0 → M26 |
| 01 | What an FPGA is | a LUT as a truth table and a mux tree, INIT, flip-flops, routing, configuration memory |
| 02 | Architecture as data | `device.py`, the 14 × 12 grid, the VPR architecture, the OpenFPGA method, the rr graph counted |
| 03 | The CLB | the 4-element cluster and its crossbar, the fracturable LUT6, the carry chain, FDRE/FDSE priority and INIT vs SRVAL, Double Duty, the 109 bits, CFGLUT5 + OR roots |
| 04 | Routing | channels (W = 36, L = 4), the Wilton switch box, connection boxes, the `bob_mux` encoding and the dark fabric, mux widths, LUT6/MUXF7/MUXF8, a real routed net, measured delays |
| 05 | BRAM and DSP | 1024 × 18 true dual port, write modes, contents vs configuration; the trimmed DSP48E1, its opmodes and cascade, both bit layouts |
| 06 | I/O and the user clock | BC_1 boundary cells, SAMPLE/INTEST/autostep/CAPTURE, `gce`, clock modes and the gap guard, synchronisers, **the freeze FSM**, the timing contract |
| 07 | JTAG and the TAP | four wires, **the 16-state TAP FSM walked edge by edge**, the timing contract, the IR table, Capture-IR status, IDCODE, TDO high-Z |
| 08 | Configuration memory and the chain | frames in memory, the two traps and the frame buffer, CHAIN_IN, CRC-32C, CFG_CTRL and its key, **the startup FSM**, JPROGRAM, the BRAM shadow |
| 09 | Frame-based configuration | the sync hunt, packet headers decoded, **the packet parser FSM**, registers and commands, FAR, the packet CRC, the real load stream, partial reconfiguration, BRAM frames, GRESTORE and time travel, the simplifications |
| 10 | Bitstream generation | the counter through yosys, equivalence, VPR, FASM, bitgen and the `.bit` v2 container, then `bob load` |
| 11 | Verification and results | the evidence layers, simulation and mutation counts, every board run, the Vivado numbers, bob vs OpenFPGA / Aegis / ZUMA / prjxray, strengths and weaknesses, references |

`python build.py --list` prints the running time of each rendered chapter.

## Watch

After a build, `out/` holds `ch00.mp4` … `ch11.mp4`, the whole film `bob_explained.mp4`, and
`bob_explained.srt` (subtitles are also burned into the picture). `out/` is not committed:
rebuild it with the steps below.

## Build

```sh
mamba env create -f video/environment.yml        # once: manim + ffmpeg, about 0.8 GB
PY=~/mamba/envs/bobvideo/bin/python

python3 video/facts.py                           # repo -> video/data/facts.json (committed)
$PY video/build.py --preview                     # 480p15 drafts + stills: out/preview, out/stills
$PY video/build.py --preview 03 07               # just some chapters
$PY video/build.py --final                       # 1080p30: out/chNN.mp4
$PY video/build.py --join                        # out/bob_explained.mp4 + .srt
```

A full final render takes well over an hour on an M2; each chapter's partial files are deleted
as soon as it is assembled, so the peak extra disk use is one chapter's.

Narration is cached by sentence in `.cache/voice/`, so re-rendering after a visual change does
not re-speak anything. `BOB_VOICE=Samantha` or `BOB_RATE=160` change the voice (`say -v '?'`
lists them); `bobvid/voice.py` `SPOKEN` holds the pronunciation fixes (JTAG → "J-tag",
yosys → "yo-sis", UG470 → "U G 4 70", …).

## Re-record with your own voice

Every render writes `script/chNN.md` (the narration, passage by passage) and `script/chNN.srt`
(each sentence with its start and end time in that chapter). Record over the `.srt` timings, or
replace `voice.say()` with a function that returns your own WAV per sentence: the scenes wait for
the audio, whatever its length.

## How it is built

```
video/
  facts.py          reads device.json, hw/build.cfg, the RTL's constants, docs/reports/M26,
                    docs/hwtest/results.log, docs/project/REPORT.md and example/ at c072b6d
  data/facts.json   every number a scene shows; facts.py fails if a source moves
  bobvid/style.py   palette (the 2026-09 docs/manim colours), chips, muxes, bit fields,
                    FSM and waveform drawing, the grid from device.json
  bobvid/voice.py   say -> WAV per sentence, cached; {shown|spoken} pairs; SPOKEN fixes
  bobvid/scene.py   BobScene: narrate() blocks, subtitles, title / files / sources cards,
                    script + srt output
  scenes/chNN_*.py  one chapter each
  build.py          preview, final, join
  DESIGN.md         the agreed design
```

`with self.narrate("…"):` wraps the animations a passage describes. The passage's audio starts
with the block; the subtitle follows the sentence being spoken; the block does not end before
the voice does. Captions stay in the scene for the whole block and only change opacity, because
manim fixes its list of moving objects at the start of each `play()` (a caption swapped in
mid-play is drawn from that stale list, as a ghost under the next one).

The film describes the hardware at M26 (IDCODE `0x0B026093`). If the architecture changes,
`python3 video/facts.py` and a re-render update every number; the narration text that states a
number reads it from the same facts.
