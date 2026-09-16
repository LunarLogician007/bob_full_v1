  /* ============================================================================
     ROUTING  —  one wire-start mux and one IPIN mux from the real rr graph encoding
     ========================================================================= */
  const RT = { sel: 3, ipin: 2 };
  const RT_IN = ["OPIN clb(4,4).O", "CHANX ← x2 · t0", "CHANX ← x2 · t4", "CHANX ← x2 · t8", "CHANY ↑ y1", "CHANY ↑ y2 · t1",
    "CHANY ↑ y2 · t5", "CHANY ↑ y2 · t9", "CHANY ↓ y2 · t3", "CHANY ↓ y2 · t7", "CHANY ↓ y2 · t11", "CHANY ↑ y5"];

  SCHEM.routing = function () {
    S = [];
    hdr(0, 16, "one CHANX wire of tile (4,4) — 12 driving edges in VPR's graph → a 4-bit bob_mux");
    txt(1058, 16, "▸ CHANGE THE 4 CHAIN BITS BELOW", { size: 7, anchor: "end", fill: C.HOT2, mono: true, w: 600, ls: .5 });
    const N = RT_IN.length, MX = 380, MY = 50, MH = 330, sel = RT.sel;
    RT_IN.forEach((n, i) => {
      const y = MY + 14 + i * ((MH - 28) / (N - 1)), on = sel === i + 1;
      txt(300, y + 3, n, { size: 7.6, anchor: "end", mono: true, fill: on ? C.HOT2 : C.MUTE, w: on ? 700 : 400 });
      wire([[306, y], [MX, y]], { s: on ? C.HOT : "#c8d0d6", sw: on ? 2 : 1 });
      txt(MX + 10, y + 3, String(i + 1), { size: 6.4, anchor: "start", mono: true, fill: on ? C.HOT2 : C.FAINT });
    });
    const zy = MY + MH + 12;
    txt(300, zy + 3, "const 0", { size: 7.6, anchor: "end", mono: true, fill: sel === 0 || sel > N ? C.HOT2 : C.MUTE });
    wire([[306, zy], [MX, zy]], { s: sel === 0 || sel > N ? C.HOT : "#c8d0d6", sw: 1.4 });
    txt(MX + 10, zy + 3, "0", { size: 6.4, anchor: "start", mono: true, fill: C.FAINT });
    const m = mux(MX, MY, 46, MH + 26, { f: "#fdf6ef", s: C.GTX.s, sw: 1.4, label: "13:1", ls2: 8 });
    const out = sel >= 1 && sel <= N ? RT_IN[sel - 1] : "const 0";
    wire([[MX + 46, MY + (MH + 26) / 2], [560, MY + (MH + 26) / 2]], { s: C.HOT, sw: 2.4, marker: "ahh" });
    rect(560, MY + (MH + 26) / 2 - 18, 300, 36, { f: C.GTX.f, s: C.GTX.s, sw: 1.3, rx: 4 });
    txt(710, MY + (MH + 26) / 2 - 2, "CHANX wire · x1…x4, y4 · DEC_DIR", { size: 9, w: 680, fill: C.GTX.t });
    txt(710, MY + (MH + 26) / 2 + 11, "= " + out, { size: 7.4, mono: true, fill: C.HOT2 });
    for (let b = 0; b < 4; b++) {
      const v = (sel >> b) & 1, x = MX - 40 + (3 - b) * 32;
      cell(x, MY + MH + 50, 26, 18, v, { showv: true });
      cap(x + 13, MY + MH + 80, `bit ${b}`);
      line(x + 13, MY + MH + 50, MX + 23, MY + MH + 27, { s: "#d5d9de", sw: .8 });
    }
    txt(MX - 44, MY + MH + 63, "sel =", { size: 8, anchor: "end", mono: true, fill: C.MUTE });
    txt(MX + 100, MY + MH + 64, `value ${sel} → ${sel === 0 ? "const 0 (dark)" : sel <= N ? "input " + (sel - 1) : "out of range → 0"}`, { size: 8.4, anchor: "start", mono: true, w: 640 });

    /* IPIN connection box */
    const IX = 620, IY = 300;
    frame(IX - 20, IY - 30, 450, 150, "IPIN clb(4,4).I[0]  ·  fan-in 4  ·  C1 = 1  ·  3 bits", { bg: "#fdfdfb" });
    const ins = ["const 0", "const 1", "CHANY t2", "CHANY t6", "CHANX t0", "CHANX t8"];
    ins.forEach((n, i) => {
      const y = IY - 6 + i * 18, on = RT.ipin === i;
      txt(IX + 80, y + 3, n, { size: 7.4, anchor: "end", mono: true, fill: on ? C.HOT2 : C.MUTE, w: on ? 700 : 400 });
      wire([[IX + 86, y], [IX + 150, y]], { s: on ? C.HOT : "#c8d0d6", sw: on ? 2 : 1 });
      txt(IX + 154, y + 3, String(i), { size: 6.2, anchor: "start", mono: true, fill: C.FAINT });
    });
    mux(IX + 150, IY - 14, 30, 112, { f: "#fdf6ef", s: C.GTX.s, label: "6:1", ls2: 7 });
    wire([[IX + 180, IY + 42], [IX + 290, IY + 42]], { s: C.HOT, sw: 2, marker: "ahh" });
    txt(IX + 296, IY + 46, "LUT I0", { size: 9, anchor: "start", mono: true, w: 700, fill: C.CLB.t });
    for (let b = 0; b < 3; b++) cell(IX + 300 + (2 - b) * 26, IY + 70, 22, 16, (RT.ipin >> b) & 1, { showv: true });

    txt(0, 500, `Whole fabric: ${BOB.nmux} muxes (IPIN ${BOB.ntype.IPIN} · CHANX ${BOB.ntype.CHANX} · CHANY ${BOB.ntype.CHANY}), ${BOB.mbits} bits.`
      + " Inputs are the driving rr nodes in ascending id — what tools/bob/device.py writes and host/bitstream.py selects.", { size: 8, anchor: "start", fill: C.MUTE });
    txt(0, 514, "CHANX/CHANY fan-in histogram: " + BOB.chanfanin.map(([n, c]) => `${n}×${c}`).join("  ·  "), { size: 7.4, anchor: "start", mono: true, fill: C.FAINT });
    return svg(1064, 528, 900);
  };
  DEMO.routing = {
    html: `<div class="demo"><h4>Live — <span>program the two muxes</span></h4><div class="ctl">
      <div class="grp"><label>wire mux bits</label>${[3, 2, 1, 0].map(b => `<button class="sw6" data-rtb="${b}"><span class="n">b${b}</span><span class="v">0</span></button>`).join("")}</div>
      <div class="grp"><label>IPIN value</label><select id="rtip">${[0, 1, 2, 3, 4, 5].map(v => `<option value="${v}">${v}</option>`).join("")}</select></div>
      <div class="grp" style="margin-left:auto"><span class="hexout">sel =</span><span class="led hi" id="rtled">3</span></div></div></div>`,
    wire(redraw) {
      const sync = () => { document.querySelectorAll("[data-rtb]").forEach(b => { const v = (RT.sel >> +b.dataset.rtb) & 1; b.classList.toggle("on", !!v); b.querySelector(".v").textContent = v; }); document.getElementById("rtled").textContent = RT.sel; };
      document.querySelectorAll("[data-rtb]").forEach(b => b.onclick = () => { RT.sel ^= 1 << +b.dataset.rtb; redraw(); sync(); });
      const s = document.getElementById("rtip"); s.value = RT.ipin; s.onchange = () => { RT.ipin = +s.value; redraw(); };
      sync();
    }
  };

  /* ============================================================================
     CHAIN  —  every chain bit laid out, pick a tile
     ========================================================================= */
  const CH = { pick: "t_x4y4" };
  SCHEM.chain = function () {
    S = [];
    hdr(0, 16, `the ${BOB.chain}-bit configuration chain — bit 0 first on TDI, ctrl | grid tiles row-major | tail`);
    const X0 = 10, WW = 1044, Y = 50, HH = 34, sc = WW / BOB.chain;
    BOB.tiles.forEach(([name, x, y, lo, w, nm]) => {
      const bl = BOB.blocks.find(b => b[2] === x && b[3] === y && b[5] === lo);
      const k = name === "ctrl" ? C.CMT : name === "tail" ? C.HARD : bl ? C[{ clb: "CLB", bram: "BRAM", dsp: "DSP", io: "IO" }[bl[1]]] : C.GTX;
      const on = name === CH.pick;
      rect(X0 + lo * sc, Y, Math.max(w * sc, .6), HH, { f: on ? C.HOT : k.f, s: on ? C.HOT2 : k.s, sw: on ? 1.2 : .3, rx: 0 });
    });
    rect(X0, Y, WW, HH, { s: "#9aa6b2", sw: 1, rx: 2 });
    [0, 2000, 4000, 6000, 8000, BOB.chain].forEach(b => { line(X0 + b * sc, Y + HH, X0 + b * sc, Y + HH + 6, { s: C.FAINT }); cap(X0 + b * sc, Y + HH + 16, String(b)); });
    const t = BOB.tiles.find(r => r[0] === CH.pick) || BOB.tiles[0];
    const [name, x, y, lo, w, nm, mb] = t;
    const bl = BOB.blocks.find(b => b[2] === x && b[3] === y && b[5] === lo);
    frame(10, 120, 500, 170, `TILE ${name}`, { bg: "#fdfdfb" });
    [["grid location", x === null ? "—" : `(${x}, ${y})`], ["chain bits", `[${lo + w - 1} : ${lo}]  (${w} bits)`], ["block fields", bl ? `${bl[0]}: ${w - mb} bits` : "none (routing only)"],
     ["routing muxes", `${nm} muxes · ${mb} bits`]].forEach(([a, b], i) => {
      txt(34, 152 + i * 26, a, { size: 8.6, anchor: "start", fill: C.MUTE });
      txt(170, 152 + i * 26, b, { size: 9.4, anchor: "start", mono: true, w: 700 });
    });
    /* the cell */
    frame(540, 120, 514, 170, "cfg_tile_sr.v — EVERY BIT IS A PAIR OF FLOPS", { bg: "#fdfdfb" });
    const a = ff(600, 170, 70, 60, { label: "sr[k]", sub: "posedge" }), b = ff(760, 170, 70, 60, { label: "cfg[k]", sub: "negedge" });
    wire([[560, 180], [600, 180]], { marker: "ah" }); txt(560, 172, "sr[k+1]", { size: 7, anchor: "start", mono: true, fill: C.MUTE });
    wire([[670, 200], [760, 180]], { marker: "ah" }); txt(700, 176, "commit", { size: 7, mono: true, fill: C.CFG.t });
    wire([[830, 200], [980, 200]], { s: C.HOT, sw: 1.8, marker: "ahh" }); txt(990, 204, "fabric", { size: 8.4, anchor: "start", mono: true, w: 700, fill: C.HOT2 });
    wire([[635, 230], [635, 262], [560, 262]], { marker: "ah" }); txt(566, 256, "→ sr[k-1] … TDO", { size: 7, anchor: "start", mono: true, fill: C.MUTE });
    wire([[830, 214], [850, 214], [850, 250], [690, 250], [690, 214], [670, 214]], { s: C.CFG.s, dash: "3 2" }); txt(770, 262, "capture (readback)", { size: 7, mono: true, fill: C.CFG.t });
    txt(0, 318, "OpenFPGA scan_chain protocol with Aegis' shift + shadow split: the fabric only ever sees cfg, which changes on a CRC-approved commit.", { size: 8, anchor: "start", fill: C.MUTE });
    return svg(1064, 332, 900);
  };
  DEMO.chain = {
    html: `<div class="demo"><h4>Live — <span>pick a tile</span></h4><div class="ctl">
      <div class="grp"><label>tile</label><select id="chsel">${BOB.tiles.map(t => `<option value="${t[0]}">${t[0]}</option>`).join("")}</select></div></div></div>`,
    wire(redraw) { const s = document.getElementById("chsel"); s.value = CH.pick; s.onchange = () => { CH.pick = s.value; redraw(); }; }
  };
