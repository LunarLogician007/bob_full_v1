  D("bram", {
    title: "BRAM — 1024 × 18 true dual port", sub: "column x=3 · bram0 rows 1–4 · bram1 rows 5–8 · one RAMB18 each", k: "BRAM", stage: "hw/src/tiles/bram_core.v",
    rows: [
      F("port A (port B identical)",
        ["64 IPIN MUXES", "addr·di·we·en·rst·regce from routing", "cbox", "GTX"],
        ["jtag_a", "or the USER4 drive word", "user4", "CFG"],
        ["bram_core", "Vivado READ_FIRST template", null, "BRAM"],
        ["WRITE MODE", "WRITE_FIRST / READ_FIRST / NO_CHANGE", null, "BRAM"],
        ["DOA_REG", "optional, REGCE, RST priority", null, "BRAM"],
        ["36 OPINs", "do_a / do_b onto the channels", "sbox", "GTX"]),
      B("contents (not in the chain)", ["USER4 WRITE / READ", "only while GWE = 0", "user4", "CFG"], ["SELECT", "which BRAM (M7)", "user4", "CFG"])],
    notes: ["8 config bits per BRAM: wmode_a, wmode_b, reg_a, reg_b, jtag_a, jtag_b. The pin muxes are ordinary rr-graph IPIN muxes.",
      "WRITE_FIRST and NO_CHANGE are derived from the READ_FIRST RAM with registers, so the mode is a <b>configuration bit</b> and the host still infers one RAMB18.",
      "Contents are loaded like UG470 keeps them: <b>separate from configuration</b>, write-locked once GWE rises; JPROGRAM does not clear them.",
      "M8 infers it from Verilog through yosys <code>memory_libmap</code> (<code>tools/bob/synth/bob_brams.txt</code>)."],
    src: [["AMD UG473 (RAMB18E1)", "true dual port, write modes, DOx_REG/REGCE, output latch semantics"], ["Vivado RAM inference template (UG901)", "the RTL shape that maps to RAMB18"],
      ["AMD UG470", "BRAM contents as their own block type, written before startup"], ["OpenFPGA arch memory tile", "a height>1 block in its own column"], ["yosys brams_xc4v.txt / brams_xc6v_map.v", "M8 memory library pattern"]],
    why: ["UG473 behaviour + the Vivado template means the guest BRAM is a real hard RAM on the host, not 18k flip-flops.", "A column block height 4 is what VPR/OpenFPGA tileable layouts support."],
    files: [["hw/src/tiles/bram_core.v", "memory + modes"], ["hw/src/tiles/bram_block.v", "fabric/JTAG pin choice"], ["hw/src/tiles/bram_jtag.v", "USER4, SELECT, contents CDC"],
      ["tools/bob/model.py", "class Bram"], ["tools/bob/synth/bob_brams.txt", "memory_libmap"], ["host/cfgplane.py", "bram_scan/select/write/read"]],
    tb: [["hw/tb/tb_bram.v", "5292 checks, all 36 mode × register combinations vs model.py"], [TB + " [12]–[15][19]", "contents, ROM, lock, modes, two BRAMs via SELECT"],
      ["hw/tb/tb_synth.v", "inferred RAM (examples/ram.v) vs source"], ["hwtest bram-* / bram-select / synth-ram", "on the board"]],
    drill: ["user4", "cbox", "dsp"]
  });

  D("dsp", {
    title: "DSP — DSP48E1-style slice", sub: "column x=6 · dsp0 rows 1–4 · dsp1 rows 5–8 · PCOUT → PCIN direct", k: "DSP", stage: "hw/src/tiles/dsp_core.v",
    rows: [
      F("datapath",
        ["A25 · B18 · C48 · D25", "IPIN muxes or DSP drive word", "cbox", "GTX"],
        ["PRE-ADDER", "D ± A (use_d, d_sub)", null, "DSP"],
        ["MULTIPLIER", "25 × 18 signed", null, "DSP"],
        ["OPMODE", "M · M+C · P+M · (PCIN>>>17)+M", null, "DSP"],
        ["P48", "OPINs; PCOUT = P", null, "DSP"]),
      B("register stages (config bits)", ["AREG/DREG", "ce_ad rst_ad", null, "DSP"], ["BREG", "", null, "DSP"], ["MREG", "", null, "DSP"], ["CREG/PREG", "ce_p rst_p", null, "DSP"]),
      B("cascade", ["dsp0.pcout → dsp1.pcin", "48 VPR directs, no bits", "carry", "DSP"])],
    notes: ["16 config bits per slice: opmode, use_d, d_sub, six REG bits, jtag_a/b/c/d, jtag_ctrl.",
      "Written in UG479 inference style, so Vivado maps each slice to a <b>DSP48E1</b>.",
      "M8 maps Verilog multipliers onto it with yosys <code>mul2dsp</code> at 25×18 signed (<code>examples/mult.v</code>)."],
    src: [["AMD UG479 (DSP48E1)", "A/B/C/D widths, pre-adder, OPMODE subset, register attributes, PCOUT→PCIN"], ["OpenFPGA arch mult_36 column", "hard multiplier as a tall column block with directs"],
      ["yosys share/xilinx/xc7_dsp_map.v + mul2dsp.v", "M8 multiplier mapping"]],
    why: ["The host has DSP48E1s: UG479 semantics make the guest slice cost one real DSP.", "Trimmed (no dynamic OPMODE, no pattern detect) to what synthesis actually uses."],
    files: [["hw/src/tiles/dsp_core.v", "datapath"], ["hw/src/tiles/dsp_block.v", "fabric/JTAG bus choice"], ["hw/src/tiles/dsp_jtag.v", "private DSP register"], ["tools/bob/model.py", "class Dsp"], ["tools/bob/synth/bob_map.v", "$__MUL25X18"]],
    tb: [["hw/tb/tb_dsp.v", "1344 checks vs model.py"], [TB + " [16]–[18][20]", "every opmode + cascade, multiplier, accumulator, pipeline"], ["hwtest dsp-* / synth-mult", "on the board"]],
    drill: ["dspjtag", "bram", "carry"]
  });

  D("io", {
    title: "I/O pad — VPR io block + two boundary cells", sub: "32 pads round the ring · 9 wired to the PYNQ-Z2 · the rest boundary-scan only", k: "IO", stage: "hw/src/fabric/bob_fpga.v",
    rows: [
      F("in", ["BOARD PIN", "SW/BTN or 0", "board", "BRD"], ["INPUT CELL", "BSR bit NPAD+k", "bsr", "CFG"], ["inpad OPIN", "onto the channels", "sbox", "GTX"]),
      F("out", ["outpad IPIN MUX", "routed", "cbox", "GTX"], ["GTS GATE", "0 until startup", "startup", "CFG"], ["OUTPUT CELL", "BSR bit k", "bsr", "CFG"], ["BOARD PIN", "LD0–2", "board", "BRD"])],
    notes: ["Pads are numbered row-major round the ring: SW0 8, SW1 10, BTN0–3 12/14/16/18 on the <b>West</b> edge; LD0–2 9/11/13 on the <b>East</b> edge — every design crosses the grid.",
      "No per-pad config bits (the board pins have fixed direction); GTS forces outputs 0 rather than hi-Z.",
      "INTEST drives the fabric's pads from JTAG, which is how every hardware check applies vectors independent of the real switches."],
    src: [["OpenFPGA arch io tile", "capacity-1 perimeter io, pins on all four sides"], ["IEEE 1149.1 BC_1 cell", "capture/update split, EXTEST/INTEST/SAMPLE"], ["Aegis docs/arch/io.md", "pad + boundary cell as one I/O tile"]],
    why: ["VPR needs io blocks on the perimeter to place and route pad nets (M9).", "The boundary ring was already hardware-proven in bob."],
    files: [["hw/src/fabric/bob_fpga.v", "64 bsc_cell, GTS gate"], ["hw/src/top/bob_top.v", "board pins → pad numbers"], ["hw/src/core/bsc_cell.v", "BC_1"], ["host/fpga.py", "bsr_word / bsr_leds"]],
    tb: [[TB + " [5]", "EXTEST, SAMPLE on the pads"], [TB + " [9]", "INTEST autostep with the real switch held"], ["hwtest selftest", "every design through INTEST"]],
    drill: ["bsr", "board", "startup"]
  });

  D("board", {
    title: "PYNQ-Z2 — the host board", sub: "XC7Z020 PL · Pico DirtyJTAG on PMODA · sysclk H16", k: "BRD", stage: "hw/constr/pynq_z2.xdc",
    rows: [B("pins", ["TCK U18 (MRCC)", "TMS Y18 · TDI Y19 · TDO Y16", "jtag", "CFG"], ["SYSCLK H16", "125 MHz", "clock", "CMT"],
        ["SW0 M20 · SW1 M19", "pads 8, 10", "io", "IO"], ["BTN0–3 D19 D20 L20 L19", "pads 12–18", "io", "IO"], ["LD0–2 R14 P14 N16", "pads 9 11 13 · LD3 M14 = DONE", "io", "IO"])],
    notes: ["TCK must sit on a clock-capable pin; moving it needs CLOCK_DEDICATED_ROUTE.", "The Pico runs DirtyJTAG; host/dirtyjtag.py bulk-shifts the 9400-bit chain in well under a second."],
    src: [["Xilinx PYNQ boards/Pynq-Z2 base.xdc", "pin numbers"], ["pico-dirtyJtag", "probe firmware and USB protocol"]],
    why: ["Official constraints avoid guessing pins; DirtyJTAG is the proven probe from bob."],
    files: [["hw/constr/pynq_z2.xdc", "pins, clocks, multicycles"], ["hw/src/top/bob_top.v", "BUFGs, pad map"], ["host/dirtyjtag.py", "probe"], ["host/hwtest.py", "hardware test"]],
    tb: [["tests/test_layout.py", "XDC is plain XDC, create_clock on tck"], ["tests/test_reports.py", "Vivado reports: tck constrained, RAMB18/DSP present"]],
    drill: ["io", "jtag", "clock"]
  });
