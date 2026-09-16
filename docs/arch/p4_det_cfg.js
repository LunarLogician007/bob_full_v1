  D("jtag", {
    title: "JTAG TAP — jtag_tap6.v", sub: "IEEE 1149.1 · 16-state FSM · 6-bit AMD 7-series IR", k: "CFG", stage: "hw/src/core/jtag_tap6.v",
    rows: [F("every host operation", ["TMS walk", "Select-DR/IR", null, "CFG"], ["Capture", "load the register", null, "CFG"], ["Shift", "LSB first, TDO on falling edge", null, "CFG"], ["Update", "falling edge", null, "CFG"]),
      B("instructions → registers",
        ["CFG_IN 000101 · CFG_OUT 000100", "the chain", "chain", "CFG"], ["USER2 000011 CFG_CTRL", "CRC, status", "cfgctrl", "CFG"],
        ["USER1 · USER3 CAPTURE", "ce/step/cin · CLB outs", "capture", "CFG"], ["USER4 100011 · DSP 101000", "BRAM / DSP access", "user4", "CFG"],
        ["JPROGRAM · JSTART", "clear · startup", "startup", "CFG"], ["SAMPLE · EXTEST · INTEST", "boundary", "bsr", "CFG"])],
    notes: ["Capture-IR returns <code>{DONE, INIT_B, COMMITTED, CRC_ERR, 0, 1}</code>, so any IR scan reports configuration status.",
      "<b>tlr is only consumed synchronously</b> — a combinational decode of the state register glitches, which broke EXTEST on the PS+PL build (bsc_cell.v history).",
      "USER1 bit 4 <b>autostep</b> gives exactly one fabric clock per INTEST scan: how the board checks run sequential designs."],
    src: [["IEEE 1149.1", "TAP state machine, edge timing"], ["AMD UG470 + OpenOCD xc7.cfg + openFPGALoader", "6-bit codes, IR capture DONE/INIT_B bits"], ["bob/rtl/jtag_tap.v", "hardware-proven 4-bit TAP it was copied from"]],
    why: ["Using AMD's codes makes bob look like a 7-series part to standard tools; the FSM is the proven one, unchanged."],
    files: [["hw/src/core/jtag_tap6.v", "TAP"], ["host/dirtyjtag.py", "shift_ir / shift_dr_fast"], ["host/cfgplane.py", "IR table"]],
    tb: [["hw/tb/tb_cfg.v", "180 checks on the config plane"], [TB + " [1][8][23]", "IDCODE, BYPASS, IR capture, TLR"], ["hwtest idcode / bypass / ir-status", "board"]],
    drill: ["cfgctrl", "startup", "chain", "bsr"]
  });

  D("cfgctrl", {
    title: "CFG_CTRL — CRC-32C commit guard", sub: "commit only if count == 4216 AND ~crc == expected", k: "CFG", stage: "hw/src/core/cfg_ctrl.v",
    rows: [F("one load", ["JPROGRAM", "clear cfg, GSR=GTS=1", "startup", "CFG"], ["CFG_CTRL write", "key 0xC5 + expected CRC", null, "CFG"],
        ["CFG_IN shift", "CRC + count per bit", "chain", "CFG"], ["Update-DR", "commit ⇔ len_good ∧ crc_good", null, "CFG"], ["CFG_OUT", "readback, never commits", "chain", "CFG"], ["JSTART", "phases", "startup", "CFG"]),
      B("status register (64)", ["[31:0] ~crc", "", null, "CFG"], ["[47:32] count", "", null, "CFG"], ["[55:48] flags", "DONE GWE GTS GSR COMMITTED LEN_ERR CRC_ERR CRC_OK", null, "CFG"], ["[63:56] 0x02", "version", null, "CFG"])],
    notes: ["CRC-32C reflected 0x82F63B78, init/xorout 0xFFFFFFFF, bit-serial in shift order; 4216 is byte aligned so it equals the byte-wise CRC-32C.",
      "A corrupted chain sets CRC_ERR and the <b>running design keeps working</b> (tb section [4], hwtest crc-reject-live)."],
    src: [["AMD UG470", "CRC before startup, write-protected registers (the key idea)"], ["CRC-32C (Castagnoli)", "polynomial 0x1EDC6F41"]],
    why: ["A scan chain has no framing: without length + CRC a dropped bit silently loads a different design."],
    files: [["hw/src/core/cfg_ctrl.v", "RTL"], ["tools/bob/chainbits.py", "crc32c_bits, ctrl words"], ["host/cfgplane.py", "load() sequence"], ["docs/bitstream-format.md", "the spec"]],
    tb: [["hw/tb/tb_cfg.v", "CRC vs Python, length/CRC reject, key"], ["sim/mutate_cfg.sh", "guards deleted one at a time, all killed"], ["tests/test_chainbits.py", "CRC check value 0xE3069283"]],
    drill: ["startup", "chain", "jtag"]
  });

  D("startup", {
    title: "Startup FSM — GSR → GTS → GWE → DONE", sub: "one phase per TCK in Run-Test/Idle with JSTART, only if COMMITTED", k: "CFG", stage: "hw/src/core/cfg_ctrl.v",
    rows: [F("phases", ["0 · reset", "GSR 1 GTS 1 GWE 0", null, "CFG"], ["1", "GSR ← 0", null, "CFG"], ["2", "GTS ← 0 (pads live)", null, "CFG"], ["3", "GWE ← 1 (FF/RAM writes)", null, "CFG"], ["4", "DONE ← 1 (LD3)", null, "BRAM"])],
    notes: ["JPROGRAM returns to phase 0 from anywhere. Without COMMITTED the FSM never leaves phase 0.",
      "GSR/GWE reach the fabric through clock_ctrl's two-flop synchronisers; the tb checks the clock edge that sees GSR=0 with GWE=0 leaves the FF frozen."],
    src: [["AMD UG470 startup sequence", "order GSR, GTS, GWE, DONE; JSTART clocked in RTI"]],
    why: ["Releasing GSR before GWE is what gives every flip-flop a defined INIT on the first user clock."],
    files: [["hw/src/core/cfg_ctrl.v", "phase counter"], ["hw/src/fabric/bob_fpga.v", "GTS gate on pad outputs"], ["hw/src/core/clock_ctrl.v", "gsr_s / gwe_s"]],
    tb: [[TB + " [2][7]", "GTS forced, edge-by-edge JSTART"], ["hwtest gts / gsr-gwe / jprogram", "board"]],
    drill: ["cfgctrl", "clock", "ff"]
  });

  D("chain", {
    title: "Configuration chain — 4216 bits", sub: "one shift register + shadow register · ctrl | 48 grid tiles row-major | tail", k: "CFG", stage: "hw/src/core/cfg_tile_sr.v",
    rows: [F("per bit", ["TDI", "enters bit 4215", null, "CFG"], ["sr (posedge)", "capture ← cfg · shift", null, "CFG"], ["cfg shadow (negedge)", "commit / clear", null, "CFG"], ["fabric", "sees only cfg", "routing", "GTX"]),
      B("order", ["ctrl 8", "clk_mode, clk_div", "clock", "CMT"], ["grid tiles", "block fields, then muxes by node id", "routing", "GTX"], ["tail", "byte pad", null, "CFG"])],
    notes: ["Chain bit k is the k-th bit shifted in. Tile boundaries exist only in device.json — the RTL is one 4216-bit <code>cfg_tile_sr</code>.",
      "Shadow register: the fabric never sees bits sliding past, and CFG_OUT readback is non-destructive.",
      "M13 replaces exactly this module with UG470 frames; tiles, VPR and the tools stay."],
    src: [["OpenFPGA config_protocol scan_chain", "chain through every tile's configuration flops"], ["Aegis docs/arch/configuration.md", "shift register + shadow config register"]],
    why: ["Scan chain is the simplest protocol proven in both projects; frames come last (M13) once everything else is solid."],
    files: [["hw/src/core/cfg_tile_sr.v", "cell"], ["tools/bob/device.py", "chain layout"], ["tools/bob/device.json", "tiles, chain_lo"], ["host/bitstream.py", "Bitstream word"]],
    tb: [[TB + " [2]", "random loop-free chain: commit, readback twice, 32-bit marker length"], ["tests/test_device.py", "every bit mapped exactly once, encode/decode round trip"]],
    drill: ["cfgctrl", "routing", "clb"]
  });

  D("clock", {
    title: "User clock — clock_ctrl.v", sub: "sysclk 125 MHz + gce enable · JTAG-stepped or free-running", k: "CMT", stage: "hw/src/core/clock_ctrl.v",
    rows: [F("clk_mode 0 — JTAG-stepped", ["TCK", "2-flop sync", null, "CMT"], ["rising edge ∧ USER1 ce", "or step / autostep", null, "CMT"], ["gce pulse", "one sysclk cycle", null, "CMT"]),
      F("clk_mode 1 — free-running", ["counter", "2^(clk_div+8) cycles", null, "CMT"], ["gce pulse", "≤ 488 kHz", null, "CMT"]),
      B("also synchronised", ["GSR · GWE · cin", "ASYNC_REG", null, "CMT"])],
    notes: ["gce pulses are ≥ 120 sysclk cycles apart, so every fabric flop-to-flop path gets a 120-cycle multicycle in the XDC — the routing graph needs hundreds of ns.",
      "M4's build closed with only +0.84 ns WNS on sysclk even with these multicycles; M7's much deeper routing depends on them."],
    src: [["AMD UG949", "clock enables instead of logic-generated clocks"], ["Aegis docs/arch/clock.md", "divider-based user clock"]],
    why: ["A single BUFG clock + enable keeps the host timing analysable; a generated clock through the fabric would not be."],
    files: [["hw/src/core/clock_ctrl.v", "RTL"], ["hw/constr/pynq_z2.xdc", "clock groups, multicycles"], ["host/bitstream.py", "Design.set_clock"]],
    tb: [[TB + " [10][11]", "one count per TCK edge; 100 pulses in 3200 ns"], ["sim/mutate_fabric.sh", "step-ignores-ce, divider-off-by-1 killed"], ["hwtest counter-run", "7.45 counts/s on the board"]],
    drill: ["ff", "startup", "jtag"]
  });

  D("capture", {
    title: "CAPTURE / USER1 — user-state readback", sub: "USER3: all 16 CLB outputs · USER1: ce/sr/cin/step/autostep + first 16", k: "CFG", stage: "hw/src/core/capture_chain.v",
    rows: [F("scan", ["Capture-DR", "snapshot clb_o[47:0]", null, "CFG"], ["Shift-DR", "LSB first", null, "CFG"], ["Update-DR", "nothing", null, "CFG"])],
    notes: ["AMD readback capture in scan form: nothing in the design is disturbed.", "Bit i is CLB i in row-major order (device.json capture.order)."],
    src: [["AMD UG470 readback capture", "snapshot user state over JTAG"]], why: ["Lets hardware checks see flip-flops without spending pads."],
    files: [["hw/src/core/capture_chain.v", "RTL"], ["host/hwtest.py", "counter checks decode it"]],
    tb: [[TB + " [6]", "CAPTURE == model.py for every CLB; == USER1[19:4]"], ["hwtest capture-user1 / counter8", "board"]],
    drill: ["jtag", "clb"]
  });

  D("user4", {
    title: "USER4 — BRAM contents & drive", sub: "96-bit register · LOAD_PTR WRITE READ SET_DRIVE SELECT · version 0x07", k: "CFG", stage: "hw/src/tiles/bram_jtag.v",
    rows: [F("a command crosses domains", ["Update-DR (TCK)", "latch cmd, payload, target", null, "CFG"], ["toggle req_t", "", null, "CFG"], ["2-flop sync (sysclk)", "edge detect", null, "CMT"], ["execute", "init_go[target] if GWE = 0", "bram", "BRAM"]),
      B("immediate in TCK domain", ["SET_DRIVE", "drive[target]", null, "CFG"], ["SELECT", "target ← payload if < NBRAM", null, "CFG"])],
    notes: ["A READ's word appears in the <b>next</b> scan's capture.", "WRITE after JSTART sets err — contents are locked like UG470."],
    src: [["AMD UG470", "BRAM contents separate, written before startup"]], why: ["Keeps megabytes of contents out of the configuration chain and its CRC."],
    files: [["hw/src/tiles/bram_jtag.v", "RTL"], ["host/cfgplane.py", "bram_scan / bram_select"]],
    tb: [[TB + " [12][14][19]", "contents, lock, SELECT"], ["sim/mutate_fabric.sh", "bram-init-unlocked, bram-select-ignored killed"]],
    drill: ["bram", "jtag"]
  });

  D("dspjtag", {
    title: "DSP register — private instruction 101000", sub: "256 bits · capture P0/P1 · SET_DRIVE 124 bits per slice", k: "CFG", stage: "hw/src/tiles/dsp_jtag.v",
    rows: [F("scan", ["Capture", "P0 · P1 · version 0x07", null, "CFG"], ["Shift", "", null, "CFG"], ["Update cmd 4", "drive ← [247:0]", null, "CFG"], ["dsp_block", "uses drive where jtag_* set", "dsp", "DSP"])],
    notes: ["All four AMD USER codes were taken, so the DSP gets a private code."],
    src: [["bob M6", "stepped DSP verification design"]], why: ["Lets every opmode be checked cycle by cycle on silicon without routing 248 signals."],
    files: [["hw/src/tiles/dsp_jtag.v", "RTL"], ["host/cfgplane.py", "dsp_scan"]],
    tb: [[TB + " [16]", "60 stepped operations vs model"], ["hwtest dsp-modes", "board"]],
    drill: ["dsp", "jtag"]
  });

  D("bsr", {
    title: "Boundary scan — 40 BC_1 cells", sub: "cell k < 20: output of pad k · cell 20+k: input of pad k", k: "CFG", stage: "hw/src/core/bsc_cell.v",
    rows: [F("one cell", ["capture_reg (posedge)", "data_in or scan_in", null, "CFG"], ["update_reg (negedge)", "", null, "CFG"], ["mode mux", "EXTEST/INTEST drive, else transparent", null, "CFG"])],
    notes: ["The capture/update split is what lets a scan change pins once, as a unit.", "Test-Logic-Reset is sampled synchronously — the fix proven on the PYNQ-Z2."],
    src: [["IEEE 1149.1 BC_1", "cell structure"], ["bob/rtl/bsc_cell.v", "hardware-proven cell with the TLR fix"]], why: ["Proven on this exact board; INTEST is the hardware test harness."],
    files: [["hw/src/core/bsc_cell.v", "cell"], ["hw/src/fabric/bob_fpga.v", "40-cell ring"], ["host/fpga.py", "intest_sweep, sample"]],
    tb: [[TB + " [5][9]", "EXTEST/SAMPLE/INTEST"], ["hwtest selftest / ce-sr / synth-*", "board"]],
    drill: ["io", "jtag"]
  });


