# New FPGA ideas bob could build (research notes, 2026-09-24)

These are recent papers (2025–2026, plus two older ones they build on). For each: what the paper
shows, what it would be in bob, what it costs, and whether it fits one milestone. They are
ranked by how much they would change bob per unit of work.

## 1. Fast self-reconfiguration from the Zynq ARM (after *LUTstructions*)

**Paper.** P. Papaphilippou, *LUTstructions: Fast-Reconfigurable FPGA-Based Instructions*,
arXiv 2602.20802 (Feb 2026, rev. Aug 2026). A soft core gets reconfigurable instructions:
an FPGA-within-an-FPGA whose bitstreams are loaded from main memory at run time, with no
performance overhead.

**In bob.** bob is already an FPGA-within-an-FPGA, but it loads only over JTAG from a Pico
at 100 kHz TCK, so a full 89k-bit load takes about a second. The PYNQ-Z2 has a dual-core ARM
next to the PL. Give `cfg_store.v` a second write port: an AXI-Lite (or AXI-Stream) slave
that takes UG470 frames from DDR. It is the same packet parser (`cfg_frames.v`) with a word
input instead of TDI. Then:
- a full load in ~100 µs instead of ~1 s; a partial one in microseconds
- the ARM can swap designs (or LUT-network weights, idea 2) in a loop

The CFGLUT5 loader needs 32 cycles per frame whichever clock drives it, so a 100 MHz port
loads the 697 frames in about 0.2 ms.

**Cost.** One milestone: an AXI slave, a PS block design in `build.tcl` (the first one
bob would have), a PYNQ overlay script, and the partial-reconfiguration checks rerun over
the new port. JTAG stays as the second path. **The biggest practical win on this list.**

## 2. Truth tables as weights: LUT-native neural networks on bob

**Papers.**
- Hoang, Gupta, Harris, *KANELÉ: Kolmogorov-Arnold Networks for Efficient LUT-based
  Evaluation*, FPGA 2026 (best paper), arXiv 2512.12850.
- *TreeLUT* (gradient-boosted trees as LUTs), FPGA 2025, arXiv 2501.01511: 1.9× fewer LUTs,
  1.4× lower latency than earlier LUT networks.
- *NeuraLUT-Assemble*, arXiv 2504.00592.
- Mommen et al., *Fully Trainable Deep Differentiable Logic Gate Networks and Lookup Table
  Networks*, arXiv 2607.09399 (Jul 2026): 98.88% on MNIST with two layers of 2000 LUT6s.
- Survey: arXiv 2506.07367.

These train the network so that each neuron *is* a small LUT; inference is pure logic.

**In bob.** Since M22, bob's truth tables are CFGLUT5 contents that the loader rewrites
frame by frame. A LUT network's weights are those truth tables, so:
- a flow `bob nn model.json → netlist` places a trained LUT network straight onto the
  elements, skipping yosys (the connections are the learned sparsity)
- changing weights is a partial reconfiguration of the INIT frames only; the routing stays

528 LUT6s is small (MNIST needs ~4000), but a TreeLUT-sized classifier or a jet-tagging net
fits. With idea 1 the ARM swaps models in microseconds. It makes a strong demo: "the
weights are the bitstream".

**Cost.** Software only for the first cut: a trainer export → `designs.py`-style placement →
the existing partial-load path. A board check: the classifier matches its Python reference
on N inputs driven over INTEST.

## 3. Double Duty: LUT and adder in the same element

**Paper.** *Double Duty: FPGA Architecture to Enable Concurrent LUT and Adder Chain Usage*,
FPL 2025 (NTU, Cornell, Altera, Waterloo, Toronto), arXiv 2507.11709. Today an element's
adder takes its operands only from the LUT outputs, so an element is either a LUT or an
adder. Four of the existing inputs bypass the LUT straight into the adder. That gives 21.6%
less area on adder-heavy circuits and a 9.7% better area-delay product overall, with no new
cluster inputs.

**In bob.** `ble.sv` has the same restriction (MUXCY/XORCY fed by the LUT). The change:
- a flag per element: carry operands from i[K-2]/i[K-1] or from the LUT
- the VPR `pb_type` gains the mode, and yosys maps the adder bits with a bypass mode
- fir16 and the counters would pack into fewer elements

It is small, measurable and backed by the paper's own VPR evaluation (bob uses VPR too).

**Cost.** One milestone, mostly architecture and CAD. `tb_clb` and `model.py` gain the mode.
It costs about one extra host LUT per element.

## 4. Direct BRAM → DSP paths

**Paper.** Hu, Sunketa, Boutros, Arora, *Boosting FPGA Performance with Direct BRAM-DSP
Paths*, arXiv 2607.05756 (Jul 2026): up to +25% Fmax and −49% wirelength on deep-learning
layers, with negligible area.

**In bob.** bob already has one hard direct: DSP0 PCOUT → DSP1 PCIN. Add BRAM do_a → DSP
a/b as a second direct in the architecture XML, generated like the cascade in
`fabric_gen.py`, plus a placer rule that keeps the pair adjacent. fir and fir16 read
coefficients from RAM and would use it.

**Cost.** Small, but bob has 2 BRAMs and 2 DSPs, so it is a demonstration more than a win.
Worth it bundled with a bigger change.

## 5. Compute-in-BRAM

**Papers.**
- Arora et al., *CoMeFa: Compute-in-Memory Blocks for FPGAs* (FCCM 2022; TRETS 2023)
- Chen et al., *BRAMAC: Compute-in-BRAM Architectures for Multiply-Accumulate on FPGAs* (FCCM 2023)

The bitlines of a block RAM become bit-serial SIMD lanes, for 1.6–2.3× more MAC throughput at
1.8% die area.

**In bob.** `bram_block.v` wraps a host RAMB18, so the host array cannot be touched. It could
be emulated: a "compute mode" in which the wrapper streams a column through a small
bit-serial PE array in host LUTs. That shows the idea, but on bob it saves nothing, because
the host does the work either way. **Interesting to teach, weak as an upgrade.**

## 6. Screening bitstreams before they load

**Paper.** *Hardware-Accelerated Line-Rate Bitstream Screening for Secure FPGA
Reconfiguration*, arXiv 2605.08984 (May 2026). It checks a (partial) bitstream for
forbidden structures at line rate, as it streams in.

**In bob.** bob already has both halves of the rule:
- the timing contract (`timing.contract` refuses a word whose critical path does not fit)
- the dark-fabric guarantees (const0 selects, the JPROGRAM sweep)

A hardware screener in the frame path could refuse, at load time on the chip:
- combinational loops (a routing-graph check is hard, but a per-CLB "no LUT output feeds
  its own crossbar" check is cheap)
- two drivers onto one pad
- a gce spacing below the design's `clk_gap`

This matters once idea 1 lets software on the ARM load anything.

**Cost.** Medium; best done together with idea 1.

## Older ideas still worth knowing

- **And-Inverter Cones** (Parandeh-Afshar et al., FPGA 2012) replace LUTs with AND-inverter
  trees. bob's value is in being a real LUT fabric, so no.
- **Multi-die / 3D routing** (arXiv 2606.06421) is out of scope for a single XC7Z020.

## Recommendation

1. **M24: the ARM configuration port** (idea 1). This changes what bob *is*: an
   FPGA-in-an-FPGA the processor next to it reprograms in microseconds.
2. **M25: truth tables as weights** (idea 2) on top of it: a LUT-network classifier whose
   weights reload by partial reconfiguration, with its accuracy checked on the board.
3. **Double Duty** (idea 3) whenever the grid needs more arithmetic per CLB.

## Sources

- [LUTstructions, arXiv 2602.20802](https://arxiv.org/abs/2602.20802)
- [KANELÉ, arXiv 2512.12850](https://arxiv.org/abs/2512.12850)
- [TreeLUT, FPGA 2025](https://dl.acm.org/doi/10.1145/3706628.3708877) / [arXiv 2501.01511](https://arxiv.org/pdf/2501.01511)
- [NeuraLUT-Assemble, arXiv 2504.00592](https://arxiv.org/pdf/2504.00592)
- [Differentiable logic gate and LUT networks, arXiv 2607.09399](https://arxiv.org/abs/2607.09399)
- [Survey of LUT-based DNNs, arXiv 2506.07367](https://arxiv.org/html/2506.07367)
- [Double Duty, arXiv 2507.11709](https://arxiv.org/html/2507.11709)
- [Direct BRAM-DSP paths, arXiv 2607.05756](https://arxiv.org/pdf/2607.05756)
- [CoMeFa, TRETS](https://dl.acm.org/doi/10.1145/3603504)
- [BRAMAC](https://www.researchgate.net/publication/372256699_BRAMAC_Compute-in-BRAM_Architectures_for_Multiply-Accumulate_on_FPGAs)
- [Bitstream screening, arXiv 2605.08984](https://arxiv.org/html/2605.08984)
- [And-Inverter Cones, FPGA 2012](https://www.epfl.ch/labs/lap/wp-content/uploads/2018/05/ParandehAfsharFeb12_RethinkingFpgasEludeTheFlexibilityExcessOfLutsWithAndInverterCones_FPGA12.pdf)
- [Multi-die FPGA routing, arXiv 2606.06421](https://arxiv.org/html/2606.06421v3)
