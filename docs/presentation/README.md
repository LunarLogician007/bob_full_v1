# The project presentation

`slides.tex` is a 25-slide Beamer deck (16:9) about the whole project. It is self-contained:
every figure is TikZ, so there are no image files to upload.

**Compile on Overleaf:** New Project → Upload Project → `slides.tex`; the compiler is pdfLaTeX
(the default). Fill in `\author{}` and `\institute{}` near the top first.

Every number on the slides comes from the project's own records: `docs/project/REPORT.md`,
the Vivado reports in `docs/reports/M*/`, the board runs in `docs/hwtest/results.log`, and
`software/bob/device.json`. If something changes, change it there first.

## Talking points, slide by slide

1. **Title.**
2. **The idea.** An FPGA written in Verilog, running inside a real FPGA, and configured the
   way AMD configures its own chips. Two flows: Vivado builds bob once; bob's own tools do
   everything after that.
3. **Outline.**
4. **Goals and rules.** The rule that shaped everything: every milestone ends on the board,
   and every board check is first shown to pass *and* fail against a simulated board.
5. **The device.** 100 CLBs × 4 elements = 400 LUT6. It costs 38k host LUTs and 86.8% of the
   slices: roughly 100 host LUTs per guest LUT, the price of programmability twice over.
6. **Element and CLB.** Double Duty (FPL 2025) lets the adder and the LUT work at once.
7. **Routing.** Not designed by hand: generated from VPR's own routing graph, so the router
   and the hardware can never disagree.
8. **JTAG and the TAP.** Four wires, one bit per clock, 1 MHz after it was constrained and
   proven.
9. **The packet stream.** The same sync word, headers and registers as a Xilinx 7-series
   bitstream; the CRC means one wrong bit stops startup.
10. **Frames.** 532 frames of 128 bits, column by column; FAR counts up by itself.
11. **The brain.** The packet parser decides; the frame store distributes to three kinds of
    storage. The two tricks that paid for the big grid: LUTs in the host's CFGLUT5s (ZUMA),
    and readback from a BRAM copy (saved ~11,800 LUTs).
12. **Partial reconfiguration and time travel.** Change logic while registers keep their
    state; save, restore, or simulate forward and put it back.
13. **Tool chain.** Every step is checked by something independent before the next runs.
14. **Own place and route.** Written from the papers; 0.93× VPR's wirelength.
15. **Timing.** Vivado cannot time an unconfigured fabric (it is all loops), so each design
    is timed from its own configuration bits, and a design that does not fit is refused.
16. **Software.** `./bob` and bob studio share one engine; a simulated board means everything
    works without hardware.
17. **Verification.** The pyramid, top to bottom; mutation testing proves the tests can fail.
18. **Growing the grid.** 16 → 400 LUTs on the same chip, always by removing overhead.
19. **Results.** One row per board-tested build.
20. **Problems.** The honest part: what broke and what it taught (including the RISC-V trial).
21. **Comparison.** What bob shares with OpenFPGA, ZUMA and Aegis, and what is its own.
22. **Documentation.** The four animated volumes are good to show live.
23. **Limits and future work.**
24. **Summary.**
25. **Questions.** For a live demo: `./bob run work/examples/counter/counter.v --probe fake`,
    `./bob studio`, or a `docs/learn/` volume.
