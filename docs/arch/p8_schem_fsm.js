  /* ============================================================================
     JTAG TAP (jtag_tap6.v)  —  the 16-state machine, steppable
     ========================================================================= */
  const TAPN = {
    TLR: [532, 56, "Test-Logic-Reset"], RTI: [532, 118, "Run-Test / Idle"],
    SDS: [340, 118, "Select-DR"], SIS: [724, 118, "Select-IR"],
    CDR: [340, 176, "Capture-DR"], CIR: [724, 176, "Capture-IR"],
    SDR: [340, 234, "Shift-DR"], SIR: [724, 234, "Shift-IR"],
    E1DR: [340, 292, "Exit1-DR"], E1IR: [724, 292, "Exit1-IR"],
    PDR: [180, 292, "Pause-DR"], PIR: [884, 292, "Pause-IR"],
    E2DR: [180, 350, "Exit2-DR"], E2IR: [884, 350, "Exit2-IR"],
    UDR: [340, 408, "Update-DR"], UIR: [724, 408, "Update-IR"]
  };
  const TAPE = [
    ["TLR", "TLR", 1, "self"], ["TLR", "RTI", 0], ["RTI", "RTI", 0, "self"], ["RTI", "SDS", 1],
    ["SDS", "CDR", 0], ["SDS", "SIS", 1], ["SIS", "CIR", 0], ["SIS", "TLR", 1],
    ["CDR", "SDR", 0], ["CDR", "E1DR", 1], ["SDR", "SDR", 0, "self"], ["SDR", "E1DR", 1],
    ["E1DR", "PDR", 0], ["E1DR", "UDR", 1], ["PDR", "PDR", 0, "self"], ["PDR", "E2DR", 1],
    ["E2DR", "SDR", 0], ["E2DR", "UDR", 1], ["UDR", "RTI", 0], ["UDR", "SDS", 1],
    ["CIR", "SIR", 0], ["CIR", "E1IR", 1], ["SIR", "SIR", 0, "self"], ["SIR", "E1IR", 1],
    ["E1IR", "PIR", 0], ["E1IR", "UIR", 1], ["PIR", "PIR", 0, "self"], ["PIR", "E2IR", 1],
    ["E2IR", "SIR", 0], ["E2IR", "UIR", 1], ["UIR", "RTI", 0], ["UIR", "SDS", 1]
  ];
  const TAP = { st: "TLR", ir: "IDCODE", last: null };
  const IRS = [["IDCODE", "001001", "32-bit 0x9BEEF093"], ["USERCODE", "001000", "milestone number"], ["BYPASS", "111111", "1 bit"],
    ["CFG_IN", "000101", "chain write · commits if CRC+len"], ["CFG_OUT", "000100", "chain readback"], ["USER2 CFG_CTRL", "000011", "64-bit CRC/status"],
    ["USER1", "000010", "ce sr cin step autostep"], ["USER3 CAPTURE", "100010", "48 CLB outputs"], ["USER4 BRAM", "100011", "96-bit contents/drive"],
    ["DSP (private)", "101000", "256-bit drive / P"], ["JPROGRAM", "001011", "clears at Update-IR"], ["JSTART", "001100", "startup in RTI"],
    ["SAMPLE · EXTEST", "000001 · 100110", "64-cell boundary"], ["INTEST (private)", "000111", "cells drive the fabric"]];

  SCHEM.jtag = function () {
    S = [];
    hdr(0, 16, "jtag_tap6.v — sixteen states, TMS sampled on the rising TCK edge");
    const NW = 118, NH = 34;
    const DETOUR = {
      "SDS|SIS": [[[399, 135], [436, 135], [436, 166], [628, 166], [628, 135], [665, 135]], 532, 166],
      "UDR|SDS": [[[281, 425], [104, 425], [104, 135], [281, 135]], 104, 280],
      "UIR|SDS": [[[724, 442], [724, 452], [88, 452], [88, 100], [340, 100], [340, 118]], 88, 300],
      "CDR|E1DR": [[[399, 193], [430, 193], [430, 309], [399, 309]], 430, 251],
      "CIR|E1IR": [[[665, 193], [634, 193], [634, 309], [665, 309]], 634, 251]
    };
    const ctr = k => [TAPN[k][0], TAPN[k][1] + NH / 2];
    TAPE.forEach(([a, b, tms, kind]) => {
      const taken = TAP.last && TAP.last[0] === a && TAP.last[1] === b;
      const col = taken ? C.GRN : (tms ? C.HOT : "#9aa6b2"), sw = taken ? 2.4 : (tms ? 1.3 : 1.1), mk = taken ? "ahg" : "ah";
      const det = DETOUR[a + "|" + b];
      if (det) {
        wire(det[0], { s: col, sw, marker: mk });
        rect(det[1] - 5, det[2] - 6, 10, 11, { f: "#fdfdfb", rx: 2 });
        txt(det[1], det[2] + 3, String(tms), { size: 7, mono: true, fill: col, w: 700 });
        return;
      }
      if (kind === "self") {
        const [x, y] = ctr(a);
        path(`M${x - NW / 2},${y - 8} C${x - NW / 2 - 34},${y - 26} ${x - NW / 2 - 34},${y + 26} ${x - NW / 2},${y + 8}`, { s: col, sw, marker: mk });
        txt(x - NW / 2 - 40, y + 3, String(tms), { size: 7, mono: true, fill: col, anchor: "end", w: 700 });
        return;
      }
      const [x1, y1] = ctr(a), [x2, y2] = ctr(b);
      let pts;
      if (Math.abs(x1 - x2) < 2) pts = [[x1, y1 + NH / 2], [x2, y2 - NH / 2]];
      else if (Math.abs(y1 - y2) < 2) pts = [[x1 + (x2 > x1 ? NW / 2 : -NW / 2), y1], [x2 + (x2 > x1 ? -NW / 2 : NW / 2), y2]];
      else { const mx = (x1 + x2) / 2; pts = [[x1 + (x2 > x1 ? NW / 2 : -NW / 2), y1], [mx, y1], [mx, y2], [x2 + (x2 > x1 ? -NW / 2 : NW / 2), y2]]; }
      wire(pts, { s: col, sw, marker: mk });
      const lx = (pts[0][0] + pts[pts.length - 1][0]) / 2, ly = (pts[0][1] + pts[pts.length - 1][1]) / 2;
      rect(lx - 5, ly - 6, 10, 11, { f: "#fdfdfb", rx: 2 });
      txt(lx, ly + 3, String(tms), { size: 7, mono: true, fill: col, w: 700 });
    });
    Object.entries(TAPN).forEach(([k, [x, y, label]]) => {
      const cur = k === TAP.st, isShift = k === "SDR" || k === "SIR";
      const kk = cur ? { f: "#fdefe2", s: C.HOT2, t: C.HOT2 } : isShift ? C.CFG : k === "TLR" ? C.HARD : C.BRD;
      rect(x - NW / 2, y, NW, NH, { f: kk.f, s: kk.s, sw: cur ? 2.2 : (isShift ? 1.6 : 1.1), rx: 5 });
      txt(x, y + 21, label, { size: 8, w: cur || isShift ? 700 : 560, fill: kk.t });
    });

    /* bob's instruction register */
    frame(28, 476, 1028, 176, "BOB'S 6-BIT INSTRUCTIONS (AMD 7-SERIES CODES) — WHAT SHIFT-DR TALKS TO", { bg: "#fdfdfb" });
    IRS.forEach(([n, code, what], i) => {
      const col = i % 2, row = Math.floor(i / 2), x = 48 + col * 510, y = 500 + row * 21;
      const on = TAP.ir === n.split(" ")[0] || TAP.ir === n;
      txt(x, y, code, { size: 8.4, anchor: "start", mono: true, w: 700, fill: on ? C.HOT2 : C.CFG.t });
      txt(x + 118, y, n, { size: 8.6, anchor: "start", w: on ? 700 : 560, fill: on ? C.HOT2 : C.INK });
      txt(x + 270, y, what, { size: 7.6, anchor: "start", mono: true, fill: C.MUTE });
    });
    txt(0, 676, "Capture-IR loads {DONE, INIT_B, COMMITTED, CRC_ERR, 0, 1}. Orange edges TMS = 1, grey TMS = 0, green = the transition you just took. Five TMS = 1 always reaches Test-Logic-Reset.", { size: 8, anchor: "start", fill: C.MUTE });
    return svg(1064, 690, 920);
  };

  DEMO.jtag = {
    html: `<div class="demo"><h4>Live — <span>clock TCK with TMS = 0 or 1</span></h4><div class="ctl">
      <div class="grp"><button class="act" id="tms0">TCK ↑ with TMS = 0</button><button class="act" id="tms1">TCK ↑ with TMS = 1</button><button class="act" id="tmsrst">5 × TMS = 1</button></div>
      <div class="grp"><label>IR (for the table)</label><select id="tapir">${IRS.map(r => `<option>${r[0].split(" ")[0]}</option>`).join("")}</select></div>
      <div class="grp" style="margin-left:auto"><span class="hexout">state</span><span class="led hi" id="tapled">TLR</span></div></div></div>`,
    wire(redraw) {
      const step = tms => { const e = TAPE.find(([a, , t]) => a === TAP.st && t === tms); TAP.last = [e[0], e[1]]; TAP.st = e[1]; };
      const sync = () => { document.getElementById("tapled").textContent = TAPN[TAP.st][2]; };
      document.getElementById("tms0").onclick = () => { step(0); redraw(); sync(); };
      document.getElementById("tms1").onclick = () => { step(1); redraw(); sync(); };
      document.getElementById("tmsrst").onclick = () => { for (let i = 0; i < 5; i++) step(1); redraw(); sync(); };
      const sel = document.getElementById("tapir"); sel.value = TAP.ir; sel.onchange = () => { TAP.ir = sel.value; redraw(); };
      sync();
    }
  };

  /* ============================================================================
     STARTUP + COMMIT (cfg_ctrl.v)  —  load, reject, JSTART, JPROGRAM
     ========================================================================= */
  const SU = { phase: 0, committed: 0, crc_ok: 0, crc_err: 0, len_err: 0, gsr: 1, gts: 1, gwe: 0, done: 0, log: "power-up" };
  function suJprogram() { Object.assign(SU, { phase: 0, committed: 0, crc_ok: 0, crc_err: 0, len_err: 0, gsr: 1, gts: 1, gwe: 0, done: 0, log: "JPROGRAM: cfg cleared" }); }
  function suLoad(crc, len) {
    SU.crc_ok = +(crc && len); SU.crc_err = +!crc; SU.len_err = +!len;
    if (crc && len) { SU.committed = 1; SU.log = "CFG_IN Update-DR: count = 9400, ~crc = expected → COMMIT"; }
    else SU.log = `CFG_IN refused (${!crc ? "CRC_ERR " : ""}${!len ? "LEN_ERR" : ""}) — previous configuration kept`;
  }
  function suTick() {
    if (!SU.committed) { SU.log = "JSTART tick ignored: not COMMITTED"; return; }
    if (SU.phase === 4) { SU.log = "phase 4: DONE (stays)"; return; }
    const p = SU.phase++;
    if (p === 0) SU.gsr = 0; if (p === 1) SU.gts = 0; if (p === 2) SU.gwe = 1; if (p === 3) SU.done = 1;
    SU.log = ["GSR released", "GTS released — pads live", "GWE asserted — flops and RAM write", "DONE — LD3 on"][p];
  }

  SCHEM.startup = function () {
    S = [];
    hdr(0, 16, "cfg_ctrl.v — the commit guard and the startup phase counter");
    /* commit decision */
    frame(10, 40, 1044, 150, "COMMIT DECISION  (CFG_IN Update-DR, falling edge)", { bg: "#fdfdfb" });
    block(40, 70, 170, 44, "count == 9400", "16-bit counter per Shift-DR", C.CFG, { size: 9, cs: 6.6 });
    block(40, 128, 170, 44, "~crc == expected", "CRC-32C 0x82F63B78 · key 0xC5", C.CFG, { size: 9, cs: 6.6 });
    val(232, 92, SU.len_err ? 0 : (SU.crc_ok || SU.committed ? 1 : null), { label: "len_good" });
    val(232, 150, SU.crc_err ? 0 : (SU.crc_ok || SU.committed ? 1 : null), { label: "crc_good" });
    const g = gate("and", 300, 100, 46, 50, {});
    wire([[210, 92], [270, 92], [270, 114], [300, 114]]); wire([[210, 150], [270, 150], [270, 136], [300, 136]]);
    wire([[346, 125], [440, 125]], { s: SU.crc_ok ? C.GRN : C.WIRE, sw: 1.8, marker: SU.crc_ok ? "ahg" : "ah" });
    block(446, 100, 190, 50, "cfg_commit", "sr → cfg shadow (9400 bits)", SU.crc_ok ? C.BRAM : C.CFG, { size: 9.4, cs: 6.6 });
    block(680, 72, 170, 40, "CRC_ERR / LEN_ERR", "old cfg kept, INIT_B low", C.CFG, { size: 8.6, cs: 6.4 });
    block(680, 130, 170, 40, "COMMITTED", "enables JSTART", C.CFG, { size: 8.6, cs: 6.4 });
    val(870, 92, SU.crc_err | SU.len_err); val(870, 150, SU.committed);
    txt(900, 96, "IR capture bit 2 / 4", { size: 7, anchor: "start", mono: true, fill: C.MUTE });
    txt(900, 154, "IR capture bit 3", { size: 7, anchor: "start", mono: true, fill: C.MUTE });

    /* startup FSM */
    frame(10, 214, 1044, 240, "STARTUP FSM  —  one phase per TCK in Run-Test/Idle while IR = JSTART  ∧  COMMITTED", { bg: "#fdfdfb" });
    const ph = [["0", "RESET", "GSR 1 · GTS 1 · GWE 0"], ["1", "GSR ← 0", "flops leave INIT"], ["2", "GTS ← 0", "pads driven"], ["3", "GWE ← 1", "writes enabled"], ["4", "DONE ← 1", "LD3 on"]];
    ph.forEach(([n, a, b], i) => {
      const x = 40 + i * 202, y = 266, cur = SU.phase === i;
      rect(x, y, 150, 70, { f: cur ? "#fdefe2" : (i === 4 ? C.BRAM.f : C.CFG.f), s: cur ? C.HOT2 : (i === 4 ? C.BRAM.s : C.CFG.s), sw: cur ? 2.2 : 1.1, rx: 8 });
      txt(x + 22, y + 24, n, { size: 16, w: 700, mono: true, fill: cur ? C.HOT2 : C.CFG.t });
      txt(x + 88, y + 30, a, { size: 10, w: 700, fill: cur ? C.HOT2 : C.INK });
      txt(x + 88, y + 48, b, { size: 6.8, mono: true, fill: C.MUTE });
      if (i < 4) { wire([[x + 150, y + 35], [x + 202, y + 35]], { s: C.HOT, sw: 1.4, marker: "ahh" }); txt(x + 176, y + 28, "tick", { size: 6.4, mono: true, fill: C.HOT2 }); }
    });
    wire([[965, 336], [965, 380], [115, 380], [115, 336]], { s: C.CFG.s, sw: 1.3, dash: "5 3", marker: "ah" });
    txt(540, 396, "JPROGRAM (Update-IR) — from any phase, also clears cfg and COMMITTED", { size: 7.6, mono: true, fill: C.CFG.t, w: 600 });
    [["GSR", SU.gsr], ["GTS", SU.gts], ["GWE", SU.gwe], ["DONE", SU.done]].forEach(([n, v], i) => {
      txt(60 + i * 110, 430, n, { size: 8.6, anchor: "start", mono: true, w: 700 }); val(110 + i * 110, 426, v);
    });
    txt(520, 430, SU.log, { size: 8.4, anchor: "start", mono: true, fill: C.HOT2, w: 600 });
    txt(0, 482, "AMD UG470: integrity check before release; GSR → GTS → GWE → DONE. Checked edge by edge in hw/tb/tb_bob.v [7] and on the board by hwtest gsr-gwe.", { size: 8, anchor: "start", fill: C.MUTE });
    return svg(1064, 496, 900);
  };
  DEMO.startup = {
    html: `<div class="demo"><h4>Live — <span>walk a load the way cfgplane.load does</span></h4><div class="ctl">
      <div class="grp"><button class="act" id="sujp">JPROGRAM</button><button class="act" id="sugood">CFG_IN good chain</button><button class="act" id="sucrc">CFG_IN corrupted bit</button><button class="act" id="sulen">CFG_IN 9399 bits</button><button class="act" id="sutick">JSTART tick</button></div>
      <div class="grp" style="margin-left:auto"><span class="hexout">LD3 DONE</span><span class="led" id="suled">0</span></div></div></div>`,
    wire(redraw) {
      const sync = () => { const l = document.getElementById("suled"); l.textContent = SU.done; l.classList.toggle("hi", !!SU.done); };
      const on = (id, fn) => document.getElementById(id).onclick = () => { fn(); redraw(); sync(); };
      on("sujp", suJprogram); on("sugood", () => suLoad(1, 1)); on("sucrc", () => suLoad(0, 1)); on("sulen", () => suLoad(1, 0)); on("sutick", suTick);
      sync();
    }
  };

  /* ============================================================================
     USER4 command crossing (bram_jtag.v)  and  the user clock (clock_ctrl.v)
     ========================================================================= */
  SCHEM.user4 = function () {
    S = [];
    hdr(0, 16, "bram_jtag.v — a JTAG command reaching a BRAM on the other clock");
    frame(10, 40, 500, 250, "TCK DOMAIN", { bg: "#fdfdfb" });
    frame(560, 40, 494, 250, "SYSCLK DOMAIN (125 MHz)", { bg: "#fdfdfb" });
    block(40, 70, 190, 46, "96-bit shift register", "capture {ver, target, gwe, err, do_b, do_a, ptr, rdata}", C.CFG, { size: 8.8, cs: 5.8 });
    block(40, 150, 190, 46, "Update-DR (negedge)", "cmd = sr[95:92]", C.CFG, { size: 8.8, cs: 6.4 });
    wire([[135, 116], [135, 150]], { marker: "ah" });
    block(280, 90, 200, 40, "SET_DRIVE · SELECT", "act immediately in TCK", C.CFG, { size: 8.6, cs: 6.4 });
    block(280, 170, 200, 50, "cmd_q · pay_q · tgt_q", "latched, then req_t ← ~req_t", C.CFG, { size: 8.6, cs: 6.4 });
    wire([[230, 173], [255, 173], [255, 110], [280, 110]], { marker: "ah" }); wire([[230, 180], [280, 190]], { marker: "ah" });
    wire([[480, 195], [590, 195]], { s: C.HOT, sw: 1.8, marker: "ahh" }); txt(535, 188, "req_t", { size: 7, mono: true, fill: C.HOT2 });
    const f1 = ff(590, 172, 46, 48, { label: "m0", sub: "ASYNC" }), f2 = ff(660, 172, 46, 48, { label: "m1", sub: "ASYNC" });
    wire([[636, 196], [660, 196]]);
    block(740, 170, 110, 50, "edge detect", "m1 ⊕ req_d", C.CMT, { size: 8.6, cs: 6.4 });
    wire([[706, 196], [740, 196]], { marker: "ah" });
    block(880, 60, 160, 50, "LOAD_PTR", "ptr ← payload", C.BRAM, { size: 8.6, cs: 6.4 });
    block(880, 130, 160, 50, "WRITE / READ", "only if GWE = 0 → init_go[target]", C.BRAM, { size: 8.6, cs: 5.8 });
    block(880, 200, 160, 50, "else err ← 1", "contents locked", C.CFG, { size: 8.6, cs: 6.4 });
    wire([[850, 195], [865, 195], [865, 85], [880, 85]], { marker: "ah" }); wire([[865, 155], [880, 155]], { marker: "ah" }); wire([[865, 225], [880, 225]], { marker: "ah" });
    [["1", "LOAD_PTR", "ptr ← payload[9:0]"], ["2", "WRITE", "mem[ptr] ← payload[17:0], ptr++"], ["3", "READ", "rdata ← mem[ptr] (next scan), ptr++"], ["4", "SET_DRIVE", "selected BRAM's 64 pin values"], ["5", "SELECT", "target ← payload (M7)"]]
      .forEach(([c2, n, d], i) => { const y = 330 + i * 18; txt(30, y, c2, { size: 9, mono: true, w: 700, anchor: "start", fill: C.CFG.t }); txt(50, y, n, { size: 8.6, anchor: "start", w: 640 }); txt(160, y, d, { size: 8, anchor: "start", mono: true, fill: C.MUTE }); });
    txt(0, 440, "UG470 keeps BRAM contents out of the configuration; the toggle + two-flop synchroniser is the standard single-bit CDC handshake.", { size: 8, anchor: "start", fill: C.MUTE });
    return svg(1064, 454, 900);
  };

  const CLK = { mode: 0, ce: 1, div: 0 };
  SCHEM.clock = function () {
    S = [];
    hdr(0, 16, "clock_ctrl.v — one real clock (sysclk), the user clock is the enable gce");
    rect(20, 60, 140, 40, { f: C.BRD.f, s: C.BRD.s, rx: 4 }); txt(90, 84, "TCK (async)", { size: 9, w: 640 });
    const a = ff(200, 56, 40, 48, { label: "s0" }), b = ff(260, 56, 40, 48, { label: "s1" });
    wire([[160, 80], [200, 66]]); wire([[240, 80], [260, 66]]); cap(250, 118, "ASYNC_REG synchroniser");
    const d1 = ff(330, 56, 40, 48, { label: "d" }); wire([[300, 80], [330, 66]]);
    const ga = gate("and", 420, 60, 40, 36, {}); wire([[300, 80], [310, 80], [310, 130], [410, 130], [410, 70], [420, 70]]);
    wire([[370, 80], [400, 80], [400, 86], [420, 86]], { s: C.WIRE }); cap(440, 108, "rise");
    const g2 = gate("and", 500, 60, 40, 36, {}); wire([[460, 78], [500, 70]]);
    rect(360, 150, 110, 30, { f: C.CFG.f, s: C.CFG.s, rx: 4 }); txt(415, 170, "USER1 ce (sync)", { size: 8 });
    wire([[470, 165], [490, 165], [490, 86], [500, 86]], { s: CLK.ce ? C.HOT : C.WIRE, sw: CLK.ce ? 1.6 : 1 });
    const go = gate("or", 580, 60, 40, 44, {}); wire([[540, 78], [580, 72]]);
    rect(360, 200, 190, 30, { f: C.CFG.f, s: C.CFG.s, rx: 4 }); txt(455, 220, "USER1 step / INTEST autostep ↑", { size: 8 });
    wire([[550, 215], [570, 215], [570, 92], [580, 92]]);
    rect(360, 260, 190, 44, { f: C.CMT.f, s: C.CMT.s, rx: 4 }); txt(455, 280, "counter", { size: 9, w: 640, fill: C.CMT.t });
    txt(455, 294, `period 2^(${CLK.div}+8) = ${2 ** (CLK.div + 8)} cycles`, { size: 7, mono: true, fill: C.MUTE });
    const m = mux(680, 60, 30, 250, { label: "mode", ls2: 7 });
    wire([[624, 82], [680, 82]], { s: CLK.mode ? C.WIRE : C.HOT, sw: CLK.mode ? 1 : 2 });
    wire([[550, 282], [680, 282]], { s: CLK.mode ? C.HOT : C.WIRE, sw: CLK.mode ? 2 : 1 });
    cap(695, 330, `clk_mode = ${CLK.mode} (ctrl tile bit 0)`);
    const fg = ff(760, 160, 60, 50, { label: "gce" }); wire([[710, 185], [760, 170]], { s: C.HOT, sw: 2 });
    wire([[820, 185], [1000, 185]], { s: C.HOT, sw: 2, marker: "ahh" }); txt(910, 176, "→ every CLB / BRAM / DSP register", { size: 8, mono: true, fill: C.HOT2 });
    rect(760, 250, 240, 40, { f: C.CMT.f, s: C.CMT.s, rx: 4 }); txt(880, 274, "sysclk 125 MHz · H16 · BUFG", { size: 9, w: 640, fill: C.CMT.t });
    wire([[880, 250], [880, 230], [770, 230], [770, 204], [760, 204]], { s: C.CMT.s });
    const hz = 125e6 / 2 ** (CLK.div + 8);
    frame(20, 360, 1034, 90, "WHAT IT MEANS", { bg: "#fdfdfb" });
    txt(40, 390, CLK.mode ? `free-running: ${hz >= 1000 ? (hz / 1000).toFixed(1) + " kHz" : hz.toFixed(2) + " Hz"} user clock (div ${CLK.div}); hwtest counter-run uses div 16 = 7.45 Hz`
      : `JTAG-stepped: one gce per TCK rising edge while ce = ${CLK.ce}; step/autostep give exactly one`, { size: 9.4, anchor: "start", mono: true, w: 600 });
    txt(40, 414, "gce pulses are ≥ 120 sysclk cycles apart → pynq_z2.xdc gives fabric paths a 120-cycle multicycle (UG949: enables, not generated clocks).", { size: 8, anchor: "start", fill: C.MUTE });
    return svg(1064, 466, 900);
  };
  DEMO.clock = {
    html: `<div class="demo"><h4>Live — <span>clock mode and divider</span></h4><div class="ctl">
      <div class="grp"><button class="sw6" data-clk="mode"><span class="n">MODE</span><span class="v">0</span></button><button class="sw6" data-clk="ce"><span class="n">CE</span><span class="v">1</span></button></div>
      <div class="grp"><label>clk_div</label><input type="range" min="0" max="23" id="clkdiv" value="0"><span class="hexout" id="clkdv">0</span></div></div></div>`,
    wire(redraw) {
      const sync = () => { document.querySelectorAll("[data-clk]").forEach(b => { const v = CLK[b.dataset.clk]; b.classList.toggle("on", !!v); b.querySelector(".v").textContent = v; }); document.getElementById("clkdv").textContent = CLK.div; };
      document.querySelectorAll("[data-clk]").forEach(b => b.onclick = () => { CLK[b.dataset.clk] ^= 1; redraw(); sync(); });
      const r = document.getElementById("clkdiv"); r.value = CLK.div; r.oninput = () => { CLK.div = +r.value; redraw(); sync(); };
      sync();
    }
  };
