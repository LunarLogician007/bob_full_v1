  /* ============================================================================
     FLOORPLAN  —  the home screen: bob's real VPR grid, read from data.json (M16: 14 × 12 with the io ring, 100 CLBs) inside the XC7Z020 PL
     ========================================================================= */
  const W = 1700, H = 1112;
  const DIE = { x: 44, y: 70, w: 1196, h: 818 };
  const HITS = [];
  const NCLB = BOB.blocks.filter(b => b[1] === "clb").length;
  const NTYPE = {bram: BOB.blocks.filter(b => b[1] === "bram").length, dsp: BOB.blocks.filter(b => b[1] === "dsp").length};
  const NPAD = BOB.blocks.filter(b => b[1] === "io").length;

  txt(44, 30, "BOB — AN FPGA INSIDE AN FPGA", { size: 20, w: 680, anchor: "start", ls: -.45 });
  txt(44, 50, `DIE SLICE · TOP VIEW · ${NCLB}-CLB FABRIC GENERATED FROM VPR'S ROUTING-RESOURCE GRAPH`,
    { size: 9, anchor: "start", fill: C.MUTE, mono: true, ls: 1.1 });
  line(44, 58, 760, 58, { s: C.RULE, sw: 1 });
  txt(930, 50, "▸ CLICK ANY TILE, CHANNEL OR BLOCK", { size: 9, anchor: "end", fill: C.HOT2, mono: true, w: 700, ls: .7 });
  rect(944, 16, 296, 18, { f: "#fff", s: C.SOFT.s, sw: 1.2, dash: "5 3", rx: 4 });
  txt(1092, 28.5, "DASHED  =  HOST-SIDE / NOT IN THE PL", { size: 7.8, fill: C.SOFT.t, mono: true, w: 600 });
  rect(944, 39, 296, 18, { f: C.HARD.f, s: C.HARD.s, sw: 1.2, rx: 4 });
  txt(1092, 51.5, "SOLID  =  RTL IN hw/  (THE VIVADO BUNDLE)", { size: 7.8, fill: C.HARD.t, mono: true, w: 600 });

  /* ── host die + decorative pad ring ── */
  rect(DIE.x, DIE.y, DIE.w, DIE.h, { f: "#fcfcfa", s: C.DIE.s, sw: 2.4, rx: 12 });
  rect(DIE.x + 9, DIE.y + 9, DIE.w - 18, DIE.h - 18, { s: "#cfcfc8", sw: .8, rx: 9 });
  (function pads() {
    const g = [], p = 7.2, q = 5.8;
    for (let x = DIE.x + 22; x < DIE.x + DIE.w - 24; x += 13.4) {
      g.push(`<rect x="${x}" y="${DIE.y + 11.5}" width="${p}" height="${q}" rx="1.2" fill="#93938c"/>`);
      g.push(`<rect x="${x}" y="${DIE.y + DIE.h - 19.5}" width="${p}" height="${q}" rx="1.2" fill="#93938c"/>`);
    }
    for (let y = DIE.y + 22; y < DIE.y + DIE.h - 24; y += 13.4) {
      g.push(`<rect x="${DIE.x + 11.5}" y="${y}" width="${q}" height="${p}" rx="1.2" fill="#93938c"/>`);
      g.push(`<rect x="${DIE.x + DIE.w - 19.5}" y="${y}" width="${q}" height="${p}" rx="1.2" fill="#93938c"/>`);
    }
    S.push(`<g opacity=".8">${g.join("")}</g>`);
  })();
  txt(DIE.x + DIE.w - 8, DIE.y + DIE.h + 14, "HOST: XILINX XC7Z020 PL  ·  PYNQ-Z2  ·  bob_top", { size: 7.2, anchor: "end", fill: C.MUTE, mono: true, ls: .8 });

  /* ── the bob grid ── */
  // pitch, tile size, origin: the pitch shrinks so any grid fits left of the configuration
  // column (M7: 8 x 6, M12b: 10 x 8, M16: 14 x 12)
  const GX = 92, GY = 104, GPMAX = 75;
  const GP = Math.min(GPMAX, Math.floor(740 / BOB.W), Math.floor(600 / BOB.H));
  const GT = Math.round(GP * 0.84);
  const gx = x => GX + x * GP, gy = y => GY + (BOB.H - 1 - y) * GP;
  rect(GX - 14, GY - 18, BOB.W * GP + 16, BOB.H * GP + 22, { f: "#f5f7fa", s: "#d3dae2", sw: .9, rx: 5 });
  txt(GX - 6, GY - 5, `bob_fabric.v  ·  ${BOB.W} × ${BOB.H} VPR GRID  ·  x → East, y ↑ North`, { size: 7.4, anchor: "start", fill: C.MUTE, mono: true, ls: .6 });

  /* channels: CHANY between columns, CHANX between rows */
  for (let x = 0; x < BOB.W - 1; x++) {
    const cx = gx(x) + GT;
    rect(cx + 1, GY, GP - GT - 2, BOB.H * GP - (GP - GT), { f: "#e3f0f2", s: "#b9d8dc", sw: .5, rx: 1 });
    HITS.push(["routing", cx, GY, GP - GT, BOB.H * GP - (GP - GT)]);
  }
  for (let y = 0; y < BOB.H - 1; y++) {
    const cy = gy(y) - (GP - GT);
    rect(GX, cy + 1, BOB.W * GP - (GP - GT), GP - GT - 2, { f: "#e3f0f2", s: "#b9d8dc", sw: .5, rx: 1 });
    HITS.push(["routing", GX, cy, BOB.W * GP - (GP - GT), GP - GT]);
  }
  txt(gx(0) + GT + (GP - GT) / 2, gy(5) + 30, `CHANY · W=${BOB.chanw} · L4`, { size: 6.2, rot: -90, fill: C.GTX.t, mono: true });

  const tileOf = {};
  BOB.tiles.forEach(t => { if (t[1] !== null) tileOf[t[1] + "," + t[2]] = t; });
  const blk = {};
  BOB.blocks.forEach(b => blk[b[2] + "," + b[3]] = b);

  for (let x = 0; x < BOB.W; x++) for (let y = 0; y < BOB.H; y++) {
    const b = blk[x + "," + y], t = tileOf[x + "," + y];
    const X = gx(x), Y = gy(y);
    const corner = (x === 0 || x === BOB.W - 1) && (y === 0 || y === BOB.H - 1);
    if (corner) { rect(X, Y, GT, GT, { f: "url(#tilefine)", s: "#d6d6cf", sw: .6, rx: 2 }); continue; }
    if (!b) continue;                                     /* covered by a tall block */
    const [name, type, , , idx] = b;
    if (type === "io") {
      const pad = BOB.pads[idx];
      rect(X, Y, GT, GT, { f: C.IO.f, s: pad ? C.IO.s : "#c9c2b4", sw: pad ? 1.4 : .8, rx: 3 });
      txt(X + GT / 2, Y + 22, "pad " + idx, { size: 8.2, w: 640, fill: C.IO.t });
      txt(X + GT / 2, Y + 36, pad || "JTAG only", { size: pad ? 8.4 : 6.4, w: pad ? 700 : 400, mono: true, fill: pad ? C.HOT2 : C.FAINT });
      if (t) txt(X + GT / 2, Y + 52, t[5] + " mux", { size: 6, mono: true, fill: C.MUTE });
      HITS.push(["io", X, Y, GT, GT]);
    } else if (type === "clb") {
      rect(X, Y, GT, GT, { f: C.CLB.f, s: C.CLB.s, sw: 1, rx: 3 });
      rect(X, Y, GT, GT, { f: "url(#tile)", rx: 3 });
      txt(X + GT / 2, Y + 24, "CLB", { size: 9.4, w: 680, fill: C.CLB.t });
      txt(X + GT / 2, Y + 36, `x${x}y${y}`, { size: 6.8, mono: true, fill: C.MUTE });
      if (t) txt(X + GT / 2, Y + 52, `${t[4]} bits`, { size: 6.2, mono: true, fill: C.FAINT });
      if (y < BOB.H - 2) line(X + GT - 9, Y - 1, X + GT - 9, Y - (GP - GT) + 1, { s: C.DSP.s, sw: 1.6, marker: "ah" });
      HITS.push(["clb", X, Y, GT, GT]);
    } else {
      const hgt = (BOB.heights || {})[type] || 4, k = type === "bram" ? C.BRAM : C.DSP, top = gy(y + hgt - 1);
      const hh = hgt * GP - (GP - GT);
      rect(X, top, GT, hh, { f: k.f, s: k.s, sw: 1.3, rx: 3 });
      rect(X, top, GT, hh, { f: "url(#tile)", rx: 3 });
      txt(X + GT / 2 - 6, top + hh / 2, type === "bram" ? `BRAM${idx}  ·  1024×18 TDP` : `DSP${idx}  ·  DSP48E1-style`, { size: 9.4, w: 680, fill: k.t, rot: -90 });
      txt(X + GT / 2 + 9, top + hh / 2, type === "bram" ? "64 pins in · 36 out · USER4" : "A25 B18 C48 D25 · P48", { size: 6.8, mono: true, fill: C.MUTE, rot: -90 });
      if (type === "dsp" && idx === 0) {
        line(X + GT - 8, top - 1, X + GT - 8, top - (GP - GT) + 1, { s: C.DSP.s, sw: 2.2, marker: "ah" });
      }
      HITS.push([type, X, top, GT, hh]);
    }
  }
  cap(gx(6) + GT + 18, gy(4) - 4, "PCOUT→PCIN", { anchor: "start", fill: C.DSP.t });
  cap(gx(1) + 2, gy(1) + GT + 8, "row 1 cin ← USER1 cin", { fill: C.DSP.t, anchor: "start" });

  /* ── configuration plane column (inside the die, right of the grid) ── */
  const CPX = 878, CPW = 330;
  rect(CPX - 8, GY - 18, CPW + 16, BOB.H * GP + 22, { f: "#fdf5f3", s: C.CFG.s, sw: .9, rx: 5 });
  txt(CPX, GY - 5, "bob_fpga.v  ·  CONFIGURATION PLANE + CLOCK", { size: 7.4, anchor: "start", fill: C.CFG.t, mono: true, ls: .6, w: 600 });
  const cp = [
    ["JTAG TAP  ·  jtag_tap6.v", "IEEE 1149.1 FSM · 6-bit AMD IR", "jtag", C.CFG],
    ["FRAMES  ·  cfg_frames.v", "UG470 packets · FAR FDRI FDRO CRC", "frames", C.CFG],
    ["PARTIAL  ·  AGHIGH / LFRM", "M14: freeze gce, changed frames only", "partial", C.CFG],
    ["CFG_CTRL  ·  cfg_ctrl.v", "chain CRC + length · startup", "cfgctrl", C.CFG],
    ["STARTUP FSM", "GSR → GTS → GWE → DONE (LD3)", "startup", C.CFG],
    [`CONFIG MEMORY  ·  ${BOB.chain} bits`, "M12b: one frame buffer · cfg_store.v", "area", C.CFG],
    ["USER1 / CAPTURE", "ce · step · autostep · 16 CLB outs", "capture", C.CFG],
    ["USER4 + BRAM FRAMES  ·  bram_jtag.v", "M15: FAR type 001 · contents · drive", "bramframes", C.CFG],
    ["DSP REGISTER  ·  101000", "drive A/B/C/D · read P0 P1", "dspjtag", C.CFG],
    [`BOUNDARY SCAN  ·  ${2 * NPAD} BC_1`, "2 cells per pad · EXTEST INTEST SAMPLE", "bsr", C.CFG],
    ["USER CLOCK  ·  clock_ctrl.v", "sysclk 125 MHz · gce enable", "clock", C.CMT]
  ];
  const cph = (BOB.H * GP - (GP - GT) - (cp.length - 1) * 8) / cp.length;
  cp.forEach(([n, c2, id, k], i) => {
    const y = GY + i * (cph + 8);
    block(CPX, y, CPW, cph, n, c2, k, { size: 9.6, cs: 7.2, rx: 4 });
    HITS.push([id, CPX, y, CPW, cph]);
    if (i < cp.length - 1 && i < 3) line(CPX + CPW / 2, y + cph + 1, CPX + CPW / 2, y + cph + 7, { s: "#8e8e86", sw: 1.1, marker: "ah" });
  });
  line(CPX - 10, GY + 3 * (cph + 8) + cph / 2, gx(BOB.W - 1) + GT + 6, GY + 3 * (cph + 8) + cph / 2, { s: C.CFG.s, sw: 1.5, dash: "5 3", marker: "ah" });
  txt(CPX - 14, GY + 3 * (cph + 8) + cph / 2 - 6, `cfg[${BOB.chain - 1}:0] → every tile`, { size: 7, anchor: "end", fill: C.CFG.t, mono: true, w: 600 });

  /* ── legend panel ── */
  (function legend() {
    const LX = 1266, LY = DIE.y, LW = W - LX - 44;
    rect(LX, LY, LW, DIE.h, { f: "#fcfcfa", s: "#d3d3cc", sw: 1, rx: 7 });
    txt(LX + 15, LY + 23, "LEGEND", { size: 10.5, anchor: "start", w: 680, ls: 1.4 });
    line(LX + 15, LY + 31, LX + LW - 15, LY + 31, { s: C.RULE, sw: 1 });
    const sw = [
      [`CLB  ×${NCLB}`, "1 BLE · LUT6 + carry + FDRE/FDSE", C.CLB, "clb"],
      [`BRAM  ×${NTYPE.bram}`, "1024×18 true dual port", C.BRAM, "bram"],
      [`DSP  ×${NTYPE.dsp}`, "DSP48E1-style · cascaded", C.DSP, "dsp"],
      [`I/O PAD  ×${NPAD}`, "9 board pins · rest JTAG only", C.IO, "io"],
      ["ROUTING", `${BOB.nmux} muxes · ${BOB.mbits} bits · L4 W=${BOB.chanw}`, C.GTX, "routing"],
      ["CONFIG / JTAG", "scan chain · CRC · startup", C.CFG, "chain"],
      ["USER CLOCK", "sysclk + gce", C.CMT, "clock"]
    ];
    let y = LY + 47;
    sw.forEach(([n, c2, k, id]) => {
      rect(LX + 15, y, 26, 15, { f: k.f, s: k.s, sw: 1.1, rx: 2.5 });
      rect(LX + 15, y, 26, 15, { f: "url(#tile)", rx: 2.5 });
      txt(LX + 49, y + 8, n, { size: 8.6, anchor: "start", w: 640, fill: k.t });
      txt(LX + 49, y + 18.5, c2, { size: 7, anchor: "start", fill: C.MUTE, mono: true });
      HITS.push([id, LX + 13, y - 2, LW - 28, 24]);
      y += 27;
    });
    rect(LX + 15, y, 26, 15, { f: C.SOFT.f, s: C.SOFT.s, sw: 1.6, dash: "5 3", rx: 2.5 });
    txt(LX + 49, y + 8, "GUEST FLOW (Mac)", { size: 8.6, anchor: "start", w: 640, fill: C.SOFT.t });
    txt(LX + 49, y + 18.5, "yosys · VPR · bitgen · bob load", { size: 7, anchor: "start", fill: C.MUTE, mono: true });
    HITS.push(["flow", LX + 13, y - 2, LW - 28, 24]);
    y += 34;

    line(LX + 15, y, LX + LW - 15, y, { s: C.RULE, sw: 1 }); y += 19;
    txt(LX + 15, y, "LOADING A DESIGN  (cfgplane.load)", { size: 9.2, anchor: "start", w: 680, ls: .9 }); y += 13;
    const chain = [
      ["JPROGRAM", "clear cfg · GSR=GTS=1", C.CFG, "startup"],
      ["CFG_CTRL  ←  0xC5 · CRC-32C", "expected CRC behind a key", C.CFG, "cfgctrl"],
      [`CFG_IN  ·  ${BOB.chain} bits`, "bit k = k-th bit on TDI", C.CFG, "chain"],
      ["LENGTH ∧ CRC  →  COMMIT", "else CRC_ERR · old design kept", C.CFG, "cfgctrl"],
      ["CFG_OUT READBACK", "never commits", C.CFG, "chain"],
      ["USER4  (optional)", "BRAM contents while GWE = 0", C.BRAM, "user4"],
      ["JSTART  ·  12 TCK in RTI", "GSR → GTS → GWE → DONE", C.CFG, "startup"],
      ["DONE  ·  LD3 ON", "fabric is live", C.BRAM, "board"]
    ];
    const cw = LW - 30;
    chain.forEach(([n, c2, k, id], i) => {
      block(LX + 15, y, cw, 29, n, c2, k, { size: 8.2, cs: 6.6, rx: 3 });
      HITS.push([id, LX + 15, y, cw, 29]);
      y += 29;
      if (i < chain.length - 1) { line(LX + 15 + cw / 2, y, LX + 15 + cw / 2, y + 9, { s: "#8e8e86", sw: 1.2, marker: "ah" }); y += 9; }
    });
    y += 16;
    line(LX + 15, y, LX + LW - 15, y, { s: C.RULE, sw: 1 }); y += 19;
    txt(LX + 15, y, "ONE CHAIN, BY THE NUMBERS", { size: 9.2, anchor: "start", w: 680, ls: .9 }); y += 16;
    [["ctrl tile", "8"], [`${NCLB} CLB words`, String(NCLB * 71)], ["BRAM + DSP fields", "48"], ["routing muxes", String(BOB.mbits)], ["tail pad", String(BOB.chain - 8 - NCLB * 71 - 48 - BOB.mbits)], ["total", String(BOB.chain)]]
      .forEach(([a, b], i) => {
        txt(LX + 15, y, a, { size: 8, anchor: "start", fill: i === 5 ? C.INK : C.MUTE, w: i === 5 ? 680 : 400 });
        txt(LX + LW - 15, y, b, { size: 8.4, anchor: "end", mono: true, w: 700, fill: i === 5 ? C.CFG.t : C.INK });
        y += 14;
      });
  })();

  /* ── board-level strip ── */
  (function board() {
    const BX = 44, BY = 916, BW = W - 88, BH = 176;
    rect(BX, BY, BW, BH, { f: "#f8f8f5", s: "#d3d3cc", sw: 1, rx: 7 });
    txt(BX + 17, BY + 23, "BOARD AND HOST CONTEXT", { size: 10.5, anchor: "start", w: 680, ls: 1.4 });
    txt(BX + BW - 17, BY + 23, "WHAT TALKS TO THE PL, AND FROM WHERE", { size: 7.4, anchor: "end", fill: C.MUTE, mono: true, ls: .7 });
    const PY = BY + 45;
    line(BX + 17, PY, BX + BW - 17, PY, { s: C.DIE.s, sw: 2 });
    txt(BX + 17, PY - 7, "↑  XC7Z020  PL  PIN  BOUNDARY", { size: 7.4, anchor: "start", fill: C.INK, mono: true, w: 600, ls: .8 });
    const dev = [
      ["PICO DirtyJTAG", "USB probe on PMODA", "TCK U18 · TMS TDI TDO", "JTAG TAP", "jtag", false],
      ["125 MHz OSC", "board clock", "sysclk H16 · BUFG", "clock_ctrl", "clock", false],
      ["SLIDE SWITCHES", "SW0 · SW1", "M20 · M19", "pads 6, 8", "io", false],
      ["PUSH BUTTONS", "BTN0–BTN3", "D19 D20 L20 L19", "pads 10 12 0 1", "io", false],
      ["LEDs LD0–LD3", "LD3 = DONE", "R14 P14 N16 M14", "pads 7 9 11", "io", false],
      ["VIVADO (Windows)", "hw/ → bitstream", "build.tcl · reuse project", "bob_top.bit", "board", true],
      ["VPR (Docker)", "rr graph builder", "make rrgraph", "bob_fabric.v", "routing", true],
      ["MAC TOOLS", "bob build · bob load", "yosys · VPR · bitgen", ".bit → chain", "flow", true],
      ["hwtest.py", "every milestone", "INTEST · SAMPLE · CAPTURE", "results.log", "verify", true]
    ];
    const gap = 10, dw = (BW - 34 - gap * (dev.length - 1)) / dev.length;
    dev.forEach(([n, c2, sig, dst, id, soft], i) => {
      const x = BX + 17 + i * (dw + gap), y = PY + 57, h = BH - (y - BY) - 17;
      rect(x, y, dw, h, { f: soft ? "#fff" : C.BRD.f, s: soft ? C.SOFT.s : C.BRD.s, sw: 1.1, rx: 4, dash: soft ? "5 3" : null });
      txt(x + dw / 2, y + 18, n, { size: 8.2, w: 680, fill: soft ? C.SOFT.t : C.BRD.t });
      txt(x + dw / 2, y + 32, c2, { size: 6.7, fill: C.MUTE, mono: true });
      line(x + dw / 2, y, x + dw / 2, PY + 3, { s: "#7f7f77", sw: 1.3, marker: "ah" });
      txt(x + dw / 2, PY + 25, sig, { size: 6.5, fill: C.INK, mono: true });
      txt(x + dw / 2, PY + 37, "→ " + dst, { size: 6.5, fill: C.SOFT.t, mono: true, w: 600 });
      HITS.push([id, x, y, dw, h]);
    });
  })();

  HITS.forEach(([id, x, y, w, h]) => hit(id, x, y, w, h));
  document.getElementById("out").innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg"
     font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,system-ui,sans-serif">
     <rect width="${W}" height="${H}" fill="#fff"/>${DEFS}${S.join("\n")}</svg>`;
