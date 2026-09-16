  /* ============================================================================
     SCHEMATIC + DEMO REGISTRIES  (same contract as architecture-v2.html)
     ========================================================================= */
  const SCHEM = {}, DEMO = {};
  const CARRY = { timer: null };           // stopAnimations() in the navigation expects it

  function val(x, y, v, o = {}) {
    const unk = v === null || v === undefined, on = v === 1;
    rect(x - 7.5, y - 7.5, 15, 15, { f: unk ? "#f2f2ee" : (on ? "#fdefe2" : "#f1f4f6"), s: unk ? "#dcdcd4" : (on ? C.HOT2 : "#c0c7ce"), sw: 1, rx: 3.5 });
    txt(x, y + 3.6, unk ? "·" : String(v), { size: 8.4, mono: true, w: 700, fill: unk ? C.FAINT : (on ? C.HOT2 : C.MUTE) });
    if (o.label) txt(x, y - 11.5, o.label, { size: 6.2, mono: true, fill: C.FAINT, ls: .3 });
  }

  /* ============================================================================
     LUT6 (lutk.sv, K = 6)  —  live 64:1 multiplexer
     ========================================================================= */
  const popc = n => { let c = 0; while (n) { c += n & 1; n >>= 1; } return c; };
  const LUTFN = {
    xor:  { name: "6-input XOR (parity)", eq: "O6 = I0 ⊕ I1 ⊕ I2 ⊕ I3 ⊕ I4 ⊕ I5", f: i => popc(i) & 1 },
    and:  { name: "6-input AND", eq: "O6 = I0 · I1 · I2 · I3 · I4 · I5", f: i => (i === 63 ? 1 : 0) },
    add:  { name: "carry propagate (BOB_ADD)", eq: "O6 = I0 ⊕ I1   (sum = O6 ⊕ CIN)", f: i => (i & 1) ^ ((i >> 1) & 1) },
    maj:  { name: "majority vote", eq: "O6 = 1 when four or more inputs are high", f: i => (popc(i) >= 4 ? 1 : 0) },
    mux:  { name: "2:1 multiplexer (designs.py mux)", eq: "O6 = I2 ? I1 : I0", f: i => ((i >> 2) & 1 ? (i >> 1) & 1 : i & 1) },
    rand: { name: "random truth table", eq: "no structure at all — the LUT does not care", f: () => (Math.random() < .5 ? 1 : 0) }
  };
  const LUT = { a: [1, 1, 0, 1, 0, 1], fn: "xor", init: new Array(64).fill(0) };
  const lutIdx = () => LUT.a.reduce((n, b, i) => n | (b << i), 0);
  function lutLoad(k) { LUT.fn = k; const f = LUTFN[k].f; for (let i = 0; i < 64; i++) LUT.init[i] = f(i); }
  lutLoad("xor");
  function lutHex() {
    let s = "";
    for (let d = 15; d >= 0; d--) { let v = 0; for (let b = 0; b < 4; b++) v |= LUT.init[d * 4 + b] << b; s += v.toString(16).toUpperCase(); }
    return s;
  }

  SCHEM.lut = function () {
    S = [];
    const CX = 78, CW = 27, CH = 5.4, P = 6.2, Y0 = 48, idx = lutIdx();
    const cellY = i => Y0 + i * P;
    const nodeC = [Array.from({ length: 64 }, (_, i) => cellY(i) + CH / 2)];
    for (let s = 1; s <= 6; s++) nodeC[s] = Array.from({ length: 64 >> s }, (_, j) => (nodeC[s - 1][2 * j] + nodeC[s - 1][2 * j + 1]) / 2);
    const ST = [{ x: 132, w: 14, h: 11 }, { x: 186, w: 15, h: 13 }, { x: 244, w: 16, h: 17 }, { x: 306, w: 18, h: 22 }, { x: 374, w: 20, h: 28 }, { x: 448, w: 24, h: 36 }];
    const stRight = s => ST[s - 1].x + ST[s - 1].w, outX = s => (s === 0 ? CX + CW : stRight(s)), RAIL_Y = 470;
    hdr(0, 16, "lutk.sv at K = 6 — one 64:1 multiplexer, six routed inputs, sixty-four chain bits");
    txt(1058, 16, "▸ THE ORANGE PATH IS THE ONE ACTIVE ROUTE", { size: 7, anchor: "end", fill: C.HOT2, mono: true, w: 600, ls: .5 });
    for (let s = 1; s <= 6; s++) {
      const st = ST[s - 1], rx = st.x + st.w / 2, on = LUT.a[s - 1];
      line(rx, Y0 - 6, rx, RAIL_Y - 14, { s: on ? C.HOT : "#d2d6da", sw: on ? 1.6 : 1 });
      txt(rx, RAIL_Y, "I" + (s - 1), { size: 8.6, mono: true, w: 700, fill: on ? C.HOT2 : C.FAINT });
      val(rx, RAIL_Y + 15, on);
      cap(rx, RAIL_Y + 32, "IPIN mux");
    }
    const live = [];
    for (let s = 1; s <= 6; s++) {
      const st = ST[s - 1];
      for (let j = 0; j < (64 >> s); j++) {
        const my = nodeC[s][j] - st.h / 2;
        for (let k = 0; k < 2; k++) {
          const src = 2 * j + k, sy = nodeC[s - 1][src], sx = outX(s - 1), dy = my + st.h * (k ? .74 : .26), dx = st.x, mx = sx + (dx - sx) * .55;
          const pts = [[sx, sy], [mx, sy], [mx, dy], [dx, dy]];
          if ((idx >> (s - 1)) === src) live.push(pts); else wire(pts, { s: "#ccd3d9", sw: .55 });
        }
      }
    }
    live.forEach(p => wire(p, { s: C.HOT, sw: 2 }));
    for (let i = 0; i < 64; i++) {
      cell(CX, cellY(i), CW, CH, LUT.init[i], { hot: i === idx });
      if (i % 8 === 0) txt(CX - 7, cellY(i) + CH, String(i), { size: 5.6, anchor: "end", fill: C.FAINT, mono: true });
    }
    rect(CX, Y0, CW, 64 * P - (P - CH), { s: "#9aa6b2", sw: 1, rx: 2 });
    txt(CX + CW / 2, Y0 - 9, "INIT", { size: 6.6, mono: true, fill: C.MUTE, w: 600 });
    txt(CX + CW / 2, Y0 - 1.5, "[63:0]", { size: 6.6, mono: true, fill: C.MUTE, w: 600 });
    [[0, 31, "INIT[31:0] → O5"], [32, 63, "INIT[63:32]"]].forEach(([a, b, lbl]) => {
      const y1 = cellY(a), y2 = cellY(b) + CH, bx = 62;
      path(`M${bx + 5},${y1} L${bx},${y1} L${bx},${y2} L${bx + 5},${y2}`, { s: "#c2c8ce", sw: 1 });
      txt(bx - 6, (y1 + y2) / 2, lbl, { size: 6.2, mono: true, fill: C.FAINT, rot: -90, ls: .4 });
    });
    for (let s = 1; s <= 6; s++) {
      const st = ST[s - 1];
      for (let j = 0; j < (64 >> s); j++) {
        const my = nodeC[s][j] - st.h / 2, on = (idx >> s) === j;
        mux(st.x, my, st.w, st.h, { f: on ? "#fdf0e4" : "#fff", s: on ? C.HOT2 : "#a8b0b8", sw: on ? 1.4 : .8, label: st.h >= 16 ? "2:1" : null, ls2: 6, lf: on ? C.HOT2 : C.FAINT });
        if (on) dot(st.x + st.w / 2, my + st.h, { r: 2, s: C.HOT2 });
      }
      cap(st.x + st.w / 2, Y0 - 20, (64 >> s) + "×");
      cap(st.x + st.w / 2, Y0 - 12, (64 >> (s - 1)) + ":" + (64 >> s));
    }
    const o6y = nodeC[6][0], o6 = LUT.init[idx];
    const ob = buf(492, o6y - 9, 17, 18, { s: C.HOT2, f: "#fdf0e4" });
    wire([[stRight(6), o6y], [492, o6y]], { s: C.HOT, sw: 2 });
    wire([[ob.out[0], o6y], [536, o6y]], { s: C.HOT, sw: 2 });
    txt(542, o6y + 4, "O6", { size: 10, anchor: "start", mono: true, w: 700, fill: C.HOT2 });
    val(590, o6y, o6);
    cap(542, o6y + 18, "→ carry S · FF D · O", { anchor: "start" });
    const o5y = nodeC[5][0], o5 = LUT.init[idx & 31];
    wire([[stRight(5), o5y], [504, o5y], [504, o5y - 22], [536, o5y - 22]], { s: C.GRN, sw: 1.5, dash: "4 3" });
    dot(stRight(5), o5y, { s: C.GRN });
    txt(542, o5y - 18, "O5", { size: 10, anchor: "start", mono: true, w: 700, fill: C.GRN });
    val(590, o5y - 22, o5);
    cap(542, o5y - 4, "fracturable tap · OPIN O5", { anchor: "start" });
    const PX = 700, PW = 364;
    frame(PX, 44, PW, 250, "WHAT THE CHAIN ACTUALLY STORES", { bg: "#fdfdfb" });
    txt(PX + 18, 74, LUTFN[LUT.fn].name.toUpperCase(), { size: 9, anchor: "start", w: 680, ls: .6 });
    txt(PX + 18, 90, LUTFN[LUT.fn].eq, { size: 8, anchor: "start", fill: C.MUTE, mono: true });
    const hex = lutHex(), hx = PX + 18, hy = 108, dw = 15.4, activeNib = 15 - (idx >> 2);
    txt(hx, hy + 24, "INIT =", { size: 8.6, anchor: "start", mono: true, fill: C.MUTE });
    txt(hx + 40, hy + 24, "64'h", { size: 8.6, anchor: "start", mono: true, fill: C.FAINT });
    for (let d = 0; d < 16; d++) {
      const x = hx + 68 + d * dw, on = d === activeNib;
      rect(x, hy + 9, dw - 1.4, 20, { f: on ? "#fdefe2" : "#f6f7f8", s: on ? C.HOT2 : "#e0e4e8", sw: on ? 1.3 : .7, rx: 3 });
      txt(x + (dw - 1.4) / 2, hy + 23, hex[d], { size: 9.6, mono: true, w: 700, fill: on ? C.HOT2 : C.INK });
    }
    cap(hx + 68, hy + 40, "chain bits clb.chain_lo + 0 … 63 (device.json)", { anchor: "start" });
    const bits = [5, 4, 3, 2, 1, 0].map(i => LUT.a[i]).join("");
    txt(PX + 18, 186, "SELECTED ADDRESS", { size: 7.4, anchor: "start", fill: C.FAINT, mono: true, ls: .9 });
    txt(PX + 18, 206, `I[5:0] = ${bits}₂ = ${idx}`, { size: 11, anchor: "start", mono: true, w: 700 });
    txt(PX + 18, 226, `O6 = INIT[${idx}] = ${o6}`, { size: 11, anchor: "start", mono: true, w: 700, fill: o6 ? C.GRN : C.MUTE });
    txt(PX + 18, 246, `O5 = INIT[${idx & 31}] = ${o5}`, { size: 9, anchor: "start", mono: true, fill: C.MUTE });
    txt(PX + 18, 274, "host/bitstream.py LUT.* builds these tables; yosys abc", { size: 8, anchor: "start", fill: C.MUTE });
    txt(PX + 18, 286, "-lut 6 produces them for synthesised designs (M8).", { size: 8, anchor: "start", fill: C.MUTE });
    frame(PX, 312, PW, 96, "ON THE HOST XC7Z020", { bg: "#fdfdfb" });
    [["64", "configuration flip-flops (+64 shadow)"], ["≈21", "host LUTs for the 64:1 tree"], ["2", "host LUT levels on a real LUT6 + MUXF7/F8"], ["K", "one parameter: K=4 costs 16 bits"]]
      .forEach(([n, d], i) => { const y = 336 + i * 18; txt(PX + 46, y, n, { size: 10, anchor: "end", mono: true, w: 700, fill: C.CLB.t }); txt(PX + 56, y, d, { size: 8, anchor: "start", fill: C.MUTE }); });
    txt(0, 524, "Source: AMD UG474 LUT6_2 fracture; RTL hw/src/clb/lutk.sv, proven equal to bob's hardware-tested lut6.sv by tests/test_lutk.py.", { size: 8, anchor: "start", fill: C.MUTE });
    return svg(1064, 540, 900);
  };

  DEMO.lut = {
    html: `<div class="demo"><h4>Live — <span>flip the inputs, change the function</span></h4><div class="ctl">
        <div class="grp"><label>INPUTS</label>${[0, 1, 2, 3, 4, 5].map(i => `<button class="sw6" data-lut-a="${i}"><span class="n">I${i}</span><span class="v">0</span></button>`).join("")}</div>
        <div class="grp"><label>FUNCTION</label><select id="lutfn">${Object.entries(LUTFN).map(([k, v]) => `<option value="${k}">${v.name}</option>`).join("")}</select></div>
        <div class="grp"><button class="act" id="lutrand">Randomise inputs</button></div>
        <div class="grp" style="margin-left:auto"><span class="hexout">O6 =</span><span class="led" id="lutled">0</span></div></div></div>`,
    wire(redraw) {
      const sync = () => {
        document.querySelectorAll("[data-lut-a]").forEach(b => { const i = +b.dataset.lutA; b.classList.toggle("on", !!LUT.a[i]); b.querySelector(".v").textContent = LUT.a[i]; });
        const o = LUT.init[lutIdx()], led = document.getElementById("lutled"); led.textContent = o; led.classList.toggle("hi", !!o);
      };
      document.querySelectorAll("[data-lut-a]").forEach(b => b.onclick = () => { LUT.a[+b.dataset.lutA] ^= 1; redraw(); sync(); });
      const sel = document.getElementById("lutfn"); sel.value = LUT.fn;
      sel.onchange = () => { lutLoad(sel.value); redraw(); sync(); };
      document.getElementById("lutrand").onclick = () => { for (let i = 0; i < 6; i++) LUT.a[i] = Math.random() < .5 ? 1 : 0; redraw(); sync(); };
      sync();
    }
  };

  /* ============================================================================
     CLB (clb.sv)  —  the whole BLE, live: flags, inputs, one clock edge
     ========================================================================= */
  const BLE = { i0: 1, i1: 0, cin: 1, ce: 1, sr: 0, q: 0, fn: "add",
    f: { ff_en: 1, ff_rstval: 0, ff_ce_en: 1, ff_sr_en: 1, cy_en: 1, cy_di_sel: 0, ff_d_sel: 0 }, gsr: 0, gwe: 1 };
  function bleEval() {
    const i = BLE.i0 | (BLE.i1 << 1), t = LUTFN[BLE.fn].f;
    const o6 = t(i), o5 = t(i & 31), f = BLE.f;
    const di = f.cy_di_sel ? o5 : BLE.i0;
    const comb = f.cy_en ? (o6 ^ BLE.cin) : (f.ff_d_sel ? o5 : o6);
    const cout = f.cy_en ? (o6 ? BLE.cin : di) : 0;
    const o = f.ff_en ? BLE.q : comb;
    return { o6, o5, di, comb, cout, o };
  }
  function bleClock() {
    const e = bleEval(), f = BLE.f;
    if (BLE.gsr) BLE.q = f.ff_rstval;
    else if (!BLE.gwe) { /* hold */ }
    else if (f.ff_sr_en && BLE.sr) BLE.q = f.ff_rstval;
    else if (!f.ff_ce_en || BLE.ce) BLE.q = e.comb;
  }

  SCHEM.clb = function () {
    S = [];
    const e = bleEval(), f = BLE.f, hot = (v) => v ? C.HOT : "#9aa6b2";
    hdr(0, 16, "clb.sv — IPIN muxes → LUT6 → carry → FDRE/FDSE → O / O5 / COUT");
    txt(1058, 16, "▸ VALUES ARE LIVE — CHANGE THEM BELOW", { size: 7, anchor: "end", fill: C.HOT2, mono: true, w: 600, ls: .5 });
    frame(10, 34, 1044, 430, "ONE CLB TILE  ·  71 BLOCK BITS + ITS ROUTING MUXES", { bg: "#fdfdfb" });

    /* routed input pins */
    const pins = [["I0", BLE.i0], ["I1", BLE.i1], ["I2", 0], ["I3", 0], ["I4", 0], ["I5", 0]];
    pins.forEach(([n, v], k) => {
      const y = 66 + k * 30;
      mux(40, y, 22, 22, { label: "4", ls2: 6.4 });
      cap(51, y - 3, k === 0 ? "IPIN mux" : "");
      wire([[62, y + 11], [168, y + 11]], { s: hot(v), sw: v ? 1.8 : 1.1, marker: "ah" });
      txt(76, y + 8, n, { size: 7.4, mono: true, anchor: "start", fill: C.MUTE });
      val(146, y + 11, v);
    });
    rect(170, 60, 96, 190, { f: C.CLB.f, s: C.CLB.s, sw: 1.3, rx: 4 });
    txt(218, 140, "LUT6", { size: 12, w: 700, fill: C.CLB.t });
    txt(218, 156, "INIT[63:0]", { size: 7, mono: true, fill: C.MUTE });
    txt(218, 170, LUTFN[BLE.fn].eq.split("(")[0], { size: 6.2, mono: true, fill: C.MUTE });
    txt(276, 102, "O6", { size: 7.6, mono: true, anchor: "start", w: 700 }); val(304, 98, e.o6);
    txt(276, 222, "O5", { size: 7.6, mono: true, anchor: "start", w: 700, fill: C.GRN }); val(304, 218, e.o5);

    /* carry: MUXCY + XORCY */
    const cy = f.cy_en;
    wire([[266, 110], [420, 110]], { s: hot(e.o6), sw: 1.4 });
    gate("xor", 420, 96, 40, 30, { s: cy ? C.DSP.s : "#c7ccd1" });
    cap(440, 136, "XORCY");
    wire([[512, 505], [512, 470]], { s: "#fff" });
    const mcy = mux(376, 300, 26, 48, { label: "CY", s: cy ? C.DSP.s : "#c7ccd1" });
    cap(410, 362, "MUXCY", { anchor: "start" });
    wire([[340, 110], [340, 290], [389, 290], [389, 300]], { s: hot(e.o6), sw: 1 });
    txt(352, 286, "S=O6", { size: 6.4, mono: true, anchor: "start", fill: C.FAINT });
    wire([[330, 324], [376, 324]], { s: hot(e.di), sw: 1.2 });
    txt(250, 328, f.cy_di_sel ? "DI = O5" : "DI = I0", { size: 7, mono: true, anchor: "start", fill: C.MUTE }); val(352, 306, e.di);
    wire([[389, 440], [389, 348]], { s: hot(BLE.cin), sw: 1.6, marker: "ah" });
    txt(398, 436, "CIN ← CLB below (direct)", { size: 7, anchor: "start", mono: true, fill: C.DSP.t }); val(372, 430, BLE.cin);
    wire([[402, 324], [440, 324], [440, 44]], { s: hot(e.cout), sw: 1.6, marker: "ah" });
    txt(448, 52, "COUT → CLB above", { size: 7, anchor: "start", mono: true, fill: C.DSP.t }); val(430, 60, e.cout);
    wire([[389, 290], [389, 270], [410, 270], [410, 118], [420, 118]], { s: hot(BLE.cin), sw: 1, dash: "3 2" });

    /* D select + FF */
    const dm = mux(520, 150, 26, 60, { label: "D", ls2: 7 });
    wire([[464, 111], [500, 111], [500, 165], [520, 165]], { s: hot(e.o6 ^ BLE.cin), sw: 1.2 });
    wire([[266, 230], [500, 230], [500, 195], [520, 195]], { s: hot(e.o5), sw: 1 });
    cap(533, 222, f.cy_en ? "sum" : (f.ff_d_sel ? "O5" : "O6"));
    const fb = ff(600, 150, 70, 64, { label: f.ff_rstval ? "FDSE" : "FDRE", sub: "q_reg" });
    wire([[546, 180], [600, 160]], { s: hot(e.comb), sw: 1.6 });
    val(574, 150, e.comb, { label: "D" });
    wire([[560, 250], [635, 250], [635, 214]], { s: hot(BLE.ce), sw: 1.1 }); txt(520, 254, `CE ${f.ff_ce_en ? "(routed)" : "(ignored)"}`, { size: 6.8, mono: true, anchor: "start", fill: C.MUTE });
    wire([[560, 270], [655, 270], [655, 214]], { s: hot(BLE.sr), sw: 1.1 }); txt(520, 280, `SR ${f.ff_sr_en ? "(routed)" : "(ignored)"}`, { size: 6.8, mono: true, anchor: "start", fill: C.MUTE });
    wire([[570, 300], [590, 300], [590, 207], [600, 207]], { s: C.CMT.s, sw: 1.1 }); txt(520, 304, "sysclk · gce · GSR · GWE", { size: 6.8, mono: true, anchor: "start", fill: C.CMT.t });
    val(700, 140, BLE.q, { label: "q" });

    /* output mux */
    const om = mux(760, 150, 26, 60, { label: "O", ls2: 7 });
    wire([[670, 182], [760, 165]], { s: hot(BLE.q), sw: 1.2 });
    wire([[546, 180], [560, 180], [560, 120], [740, 120], [740, 195], [760, 195]], { s: hot(e.comb), sw: 1 });
    cap(773, 222, f.ff_en ? "ff_en = 1 → q" : "ff_en = 0 → comb");
    wire([[786, 180], [880, 180]], { s: hot(e.o), sw: 2, marker: "ah" });
    txt(890, 184, "O  → OPIN", { size: 9.4, anchor: "start", mono: true, w: 700, fill: C.CLB.t }); val(990, 180, e.o);
    wire([[304, 232], [304, 390], [880, 390]], { s: C.GRN, sw: 1.3, dash: "4 3", marker: "ahg" });
    txt(890, 394, "O5 → OPIN", { size: 9.4, anchor: "start", mono: true, w: 700, fill: C.GRN }); val(990, 390, e.o5);

    /* the 7 flags as chain cells */
    const fl = ["ff_en", "ff_rstval", "ff_ce_en", "ff_sr_en", "cy_en", "cy_di_sel", "ff_d_sel"];
    txt(600, 440, "clb word [70:64] =", { size: 7.6, anchor: "start", mono: true, fill: C.MUTE });
    fl.forEach((n, k) => { cell(708 + k * 44, 430, 40, 14, f[n], { showv: true }); cap(728 + k * 44, 456, n, { size: 5.8 }); });

    txt(0, 492, "UG474 semantics: SR beats CE (FDRE/FDSE), CO = S ? CI : DI, sum = S ⊕ CI. Every flag is a chain bit; the eight input pins are rr-graph IPIN muxes.", { size: 8, anchor: "start", fill: C.MUTE });
    return svg(1064, 506, 900);
  };

  DEMO.clb = {
    html: `<div class="demo"><h4>Live — <span>set pins and flags, then clock the flip-flop</span></h4><div class="ctl">
      <div class="grp"><label>PINS</label>${["i0", "i1", "cin", "ce", "sr"].map(k => `<button class="sw6" data-ble="${k}"><span class="n">${k.toUpperCase()}</span><span class="v">0</span></button>`).join("")}</div>
      <div class="grp"><label>FLAGS</label>${["ff_en", "ff_rstval", "ff_ce_en", "ff_sr_en", "cy_en", "cy_di_sel", "ff_d_sel"].map(k => `<button class="sw6" style="width:auto;padding:0 7px" data-blef="${k}"><span class="n">${k}</span><span class="v">0</span></button>`).join("")}</div>
      <div class="grp"><label>LUT</label><select id="blefn">${Object.entries(LUTFN).filter(([k]) => k !== "rand").map(([k, v]) => `<option value="${k}">${v.name}</option>`).join("")}</select></div>
      <div class="grp"><button class="act" id="bleclk">gce pulse (clock)</button><button class="act" id="blegsr">GSR</button></div>
      <div class="grp" style="margin-left:auto"><span class="hexout">O =</span><span class="led" id="bleled">0</span></div></div></div>`,
    wire(redraw) {
      const sync = () => {
        document.querySelectorAll("[data-ble]").forEach(b => { const v = BLE[b.dataset.ble]; b.classList.toggle("on", !!v); b.querySelector(".v").textContent = v; });
        document.querySelectorAll("[data-blef]").forEach(b => { const v = BLE.f[b.dataset.blef]; b.classList.toggle("on", !!v); b.querySelector(".v").textContent = v; });
        const o = bleEval().o, led = document.getElementById("bleled"); led.textContent = o; led.classList.toggle("hi", !!o);
      };
      document.querySelectorAll("[data-ble]").forEach(b => b.onclick = () => { BLE[b.dataset.ble] ^= 1; redraw(); sync(); });
      document.querySelectorAll("[data-blef]").forEach(b => b.onclick = () => { BLE.f[b.dataset.blef] ^= 1; redraw(); sync(); });
      const sel = document.getElementById("blefn"); sel.value = BLE.fn; sel.onchange = () => { BLE.fn = sel.value; redraw(); sync(); };
      document.getElementById("bleclk").onclick = () => { bleClock(); redraw(); sync(); };
      document.getElementById("blegsr").onclick = () => { BLE.q = BLE.f.ff_rstval; redraw(); sync(); };
      sync();
    }
  };

  /* ============================================================================
     CARRY — a 4-bit adder up one CLB column, with M8's generator CLB
     ========================================================================= */
  const ADD = { a: [1, 0, 1, 1], b: [1, 1, 0, 0], ci: 0 };
  SCHEM.carry = function () {
    S = [];
    hdr(0, 16, "a column of BOB_ADD cells — S = A ⊕ B in the LUT, MUXCY / XORCY in the CLB, carry by VPR direct");
    const X = 360, TH = 70, G = 22, bottom = 470;
    let c = ADD.ci, sum = 0;
    rect(X, bottom - TH, 240, TH, { f: C.CLB.f, s: C.CLB.s, sw: 1.1, rx: 4 });
    txt(X + 120, bottom - TH + 24, "GENERATOR CLB  (row 1)", { size: 9, w: 680, fill: C.CLB.t });
    txt(X + 120, bottom - TH + 40, "LUT = 0 → cout = DI = I0 = carry-in", { size: 7, mono: true, fill: C.MUTE });
    val(X + 120, bottom - TH + 56, c, { label: "" });
    txt(X - 12, bottom - TH / 2, "carry-in (const or routed)", { size: 7, anchor: "end", mono: true, fill: C.MUTE });
    for (let k = 0; k < 4; k++) {
      const y = bottom - (k + 2) * (TH + G) + G, s = ADD.a[k] ^ ADD.b[k], o = s ^ c, co = s ? c : ADD.a[k];
      wire([[X + 120, y + TH + G], [X + 120, y + TH]], { s: c ? C.HOT : "#9aa6b2", sw: 2, marker: c ? "ahh" : "ah" });
      rect(X, y, 240, TH, { f: C.CLB.f, s: C.CLB.s, sw: 1.1, rx: 4 });
      rect(X, y, 240, TH, { f: "url(#tile)", rx: 4 });
      txt(X + 10, y + 16, `CLB (x, ${k + 2})  ·  bit ${k}`, { size: 8.4, anchor: "start", w: 680, fill: C.CLB.t });
      gate("xor", X + 16, y + 26, 30, 24, {}); txt(X + 31, y + 62, "LUT S", { size: 6, mono: true, fill: C.FAINT });
      mux(X + 90, y + 24, 20, 34, { label: "CY", ls2: 5.6 });
      gate("xor", X + 150, y + 26, 30, 24, {}); txt(X + 165, y + 62, "XORCY", { size: 6, mono: true, fill: C.FAINT });
      val(X - 40, y + 30, ADD.a[k], { label: "A" }); val(X - 18, y + 30, ADD.b[k], { label: "B" });
      val(X + 60, y + 38, s, { label: "S" });
      wire([[X + 186, y + 38], [X + 300, y + 38]], { s: o ? C.HOT : "#9aa6b2", sw: 1.6, marker: "ah" });
      txt(X + 310, y + 42, `SUM${k}`, { size: 9, anchor: "start", mono: true, w: 700 }); val(X + 360, y + 38, o);
      sum |= o << k; c = co;
    }
    const ty = bottom - 6 * (TH + G) + G + TH;
    wire([[X + 120, ty + G], [X + 120, ty + 4]], { s: c ? C.HOT : "#9aa6b2", sw: 2, marker: "ah" });
    txt(X + 132, ty + 10, `COUT = ${c}  (a tap CLB makes it routable)`, { size: 7.4, anchor: "start", mono: true, fill: C.DSP.t });
    const A = ADD.a.reduce((n, b, i) => n | (b << i), 0), Bv = ADD.b.reduce((n, b, i) => n | (b << i), 0);
    frame(760, 60, 290, 150, "RESULT", { bg: "#fdfdfb" });
    txt(780, 96, `${A} + ${Bv} + ${ADD.ci}`, { size: 16, anchor: "start", mono: true, w: 700 });
    txt(780, 126, `= ${sum + (c << 4)}  (sum ${sum}, cout ${c})`, { size: 12, anchor: "start", mono: true, fill: C.GRN, w: 700 });
    txt(780, 160, "each bit is one CLB with cy_en = 1,", { size: 8, anchor: "start", fill: C.MUTE });
    txt(780, 174, "init = xor2 (xnor2 when subtracting)", { size: 8, anchor: "start", fill: C.MUTE });
    txt(0, 500, "Sources: UG474 CARRY4 equations; yosys arith_map.v pattern (tools/bob/synth/bob_map.v); generator/tap CLBs: tools/bob/place.py (M8).", { size: 8, anchor: "start", fill: C.MUTE });
    return svg(1064, 514, 880);
  };
  DEMO.carry = {
    html: `<div class="demo"><h4>Live — <span>toggle the operands and carry-in</span></h4><div class="ctl">
      <div class="grp"><label>A</label>${[0, 1, 2, 3].map(i => `<button class="sw6" data-add="a${i}"><span class="n">A${i}</span><span class="v">0</span></button>`).join("")}</div>
      <div class="grp"><label>B</label>${[0, 1, 2, 3].map(i => `<button class="sw6" data-add="b${i}"><span class="n">B${i}</span><span class="v">0</span></button>`).join("")}</div>
      <div class="grp"><button class="sw6" data-add="ci"><span class="n">CI</span><span class="v">0</span></button></div></div></div>`,
    wire(redraw) {
      const get = k => k === "ci" ? ADD.ci : ADD[k[0]][+k[1]];
      const sync = () => document.querySelectorAll("[data-add]").forEach(b => { const v = get(b.dataset.add); b.classList.toggle("on", !!v); b.querySelector(".v").textContent = v; });
      document.querySelectorAll("[data-add]").forEach(b => b.onclick = () => { const k = b.dataset.add; if (k === "ci") ADD.ci ^= 1; else ADD[k[0]][+k[1]] ^= 1; redraw(); sync(); });
      sync();
    }
  };
