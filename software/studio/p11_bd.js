// ── the block design canvas (M18) ────────────────────────────────────────────────
// Vivado's IP integrator, drawn in plain SVG. Blocks come from the palette (IP cores,
// the project's own modules, the board's pins); dragging from one port to another makes
// a wire; the table under the canvas holds each wire as text (cnt.q[2:1] -> board.led[1:0])
// so a bit select is typed, not drawn. software/bob/bd.py checks it and writes the
// wrapper; nothing here decides whether a design is legal.

const BD_W = 176, BD_HEAD = 34, BD_ROW = 18;

const bd = {
  rel: null,             // bd/<name>.bd, relative to the project
  doc: null,             // the .bd as JSON
  ports: {},             // block id -> [{name, dir, width}] at its current parameters
  palette: null,
  sel: null,             // selected block id, or {wire: index}
  dirty: false,
  check: null,           // the last /api/bd/check
  drag: null,
  topAfter: true,        // Generate wrapper also sets it as the top

  forget() { this.rel = null; this.doc = null; this.ports = {}; this.sel = null; this.check = null; this.dirty = false; },

  async open(rel) {
    if (this.dirty && this.rel && this.rel !== rel && !window.confirm(`${this.rel} has unsaved changes. Open ${rel} anyway?`)) return;
    const r = await api("/api/bd?rel=" + encodeURIComponent(rel));
    this.rel = rel; this.doc = r.bd; this.sel = null; this.check = null; this.dirty = false;
    this.doc.board = this.doc.board || {};
    this.ports = {};
    await this.loadPalette();
    await Promise.all(this.doc.blocks.map((b) => this.fetchPorts(b)));
    tabs.show("bd");
    logLine("info", `opened block design ${rel}`);
  },

  async loadPalette() {
    try { this.palette = await api("/api/bd/palette"); }
    catch (e) { logLine("error", e.message); this.palette = { ip: [], modules: [], board: { ports: [], pads: [] } }; }
  },

  async fetchPorts(b) {
    try {
      const q = `kind=${b.kind}&type=${encodeURIComponent(b.type)}&params=${encodeURIComponent(JSON.stringify(b.params || {}))}`;
      this.ports[b.id] = (await api("/api/ports?" + q)).ports;
    } catch (e) {
      this.ports[b.id] = [];
      logLine("error", `${b.id}: ${e.message}`); dock.show("log");
    }
  },

  // ── the board's two pseudo-blocks: its inputs on the left, its outputs on the right ──
  // The board's extra pins: board-named ones (SW0 ... LD2) and scan-only pads, kept in the
  // .bd as {in_pins: ["SW0", "pad5"], out_pins: ["LD1"]}. Older files list pads as numbers.
  extraPins(dir) {
    const bb = this.doc.board;
    const k = dir === "input" ? "in" : "out";
    return (bb[k + "_pins"] || []).concat((bb[k + "_pads"] || []).map((n) => "pad" + n));
  },

  boardBlocks() {
    const bb = this.doc.board;
    const ins = [{ name: "sw", dir: "output", width: 2 }, { name: "btn", dir: "output", width: 4 }]
      .concat(this.extraPins("input").map((n) => ({ name: n, dir: "output", width: 1 })));
    const outs = [{ name: "led", dir: "input", width: 3 }]
      .concat(this.extraPins("output").map((n) => ({ name: n, dir: "input", width: 1 })));
    return [
      { id: "board", key: "board_in", label: "board inputs", ty: "switches, buttons, pads", x: bb.ix ?? 20, y: bb.iy ?? 40, ports: ins, cls: "board" },
      { id: "board", key: "board_out", label: "board outputs", ty: "LEDs, pads", x: bb.ox ?? 980, y: bb.oy ?? 40, ports: outs, cls: "board" },
    ];
  },

  shapes() {
    const out = this.boardBlocks();
    for (const b of this.doc.blocks) {
      out.push({ id: b.id, key: b.id, label: b.id, ty: `${b.kind === "ip" ? "IP " : ""}${b.type}`
        + (Object.keys(b.params || {}).length ? " #(" + Object.entries(b.params).map(([k, v]) => `${k}=${v}`).join(",") + ")" : ""),
        x: b.x ?? 300, y: b.y ?? 60, ports: (this.ports[b.id] || []), cls: b.kind, blk: b });
    }
    for (const s of out) {
      s.ins = s.ports.filter((p) => p.dir === "input" && p.name !== "clk");
      s.outs = s.ports.filter((p) => p.dir === "output");
      s.clk = s.ports.some((p) => p.name === "clk");
      s.h = BD_HEAD + Math.max(s.ins.length, s.outs.length, 1) * BD_ROW + 8;
    }
    return out;
  },

  portXY(shapes, blockId, port) {
    for (const s of shapes) {
      if (s.id !== blockId) continue;
      let i = s.ins.findIndex((p) => p.name === port);
      if (i >= 0) return { x: s.x, y: s.y + BD_HEAD + i * BD_ROW + 9 };
      i = s.outs.findIndex((p) => p.name === port);
      if (i >= 0) return { x: s.x + BD_W, y: s.y + BD_HEAD + i * BD_ROW + 9 };
    }
    return null;
  },

  parse(text) {
    const m = /^(\w+)\.(\w+)(?:\[(\d+)(?::(\d+))?\])?$/.exec(String(text || "").trim());
    return m ? { blk: m[1], port: m[2], hi: m[3] != null ? +m[3] : null, lo: m[4] != null ? +m[4] : (m[3] != null ? +m[3] : null) } : null;
  },

  bad(where) {                                   // is this endpoint or block named by a check error?
    if (!this.check) return false;
    return this.check.errors.some((e) => e.where === where || e.where.startsWith(where + "[") || e.where.startsWith(where + "."));
  },

  // ── drawing ───────────────────────────────────────────────────────────────
  render() {
    this.renderTop(); this.renderPalette(); this.renderSide(); this.renderWires();
    const svg = $("bdsvg");
    svg.innerHTML = "";
    $("bdname").textContent = this.doc ? this.doc.name : "";
    if (!this.doc) {
      const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
      t.setAttribute("x", 40); t.setAttribute("y", 60);
      t.setAttribute("style", "font:13px var(--sans);fill:var(--faint)");
      t.textContent = S.proj ? "No block design open: Create Block Design in the Project Manager, or open one there."
        : "Open or create a project first: block designs belong to a project.";
      svg.appendChild(t);
      return;
    }
    const NS = "http://www.w3.org/2000/svg";
    const mk = (tag, attrs, parent) => {
      const n = document.createElementNS(NS, tag);
      for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
      (parent || svg).appendChild(n);
      return n;
    };
    const shapes = this.shapes();
    let maxX = 1200, maxY = 700;
    for (const s of shapes) { maxX = Math.max(maxX, s.x + BD_W + 40); maxY = Math.max(maxY, s.y + s.h + 40); }
    if (!this.z) this.z = zoomer(svg, null);
    this.z.setBase(0, 0, maxX, maxY);

    // wires under blocks
    this.doc.wires.forEach((w, i) => {
      const a = this.parse(w.src), b = this.parse(w.dst);
      if (!a || !b) return;
      const p = this.portXY(shapes, a.blk, a.port), q = this.portXY(shapes, b.blk, b.port);
      if (!p || !q) return;
      const dx = Math.max(40, Math.abs(q.x - p.x) / 2);
      const width = a.hi != null ? a.hi - a.lo + 1 : ((shapes.find((s) => s.id === a.blk && s.outs.some((o) => o.name === a.port)) || { outs: [] }).outs.find((o) => o.name === a.port) || { width: 1 }).width;
      const path = mk("path", { d: `M${p.x},${p.y} C${p.x + dx},${p.y} ${q.x - dx},${q.y} ${q.x},${q.y}`,
        class: "wire" + (width > 1 ? " bus" : "") + (this.bad(w.dst) || this.bad(w.src) ? " bad" : "") });
      if (this.sel && this.sel.wire === i) path.setAttribute("style", "stroke:var(--accent)");
      const tt = mk("title", {}, path); tt.textContent = `${w.src} → ${w.dst}`;
      path.onclick = (e) => { e.stopPropagation(); this.sel = { wire: i }; this.render(); };
    });

    for (const s of shapes) {
      const g = mk("g", { class: `blk ${s.cls}` + (this.sel === s.key ? " sel" : ""), transform: `translate(${s.x},${s.y})` });
      mk("rect", { class: "body", x: 0, y: 0, width: BD_W, height: s.h, rx: 6 }, g);
      mk("rect", { class: "head", x: 1, y: 1, width: BD_W - 2, height: BD_HEAD - 6, rx: 5 }, g);
      const t1 = mk("text", { x: 8, y: 14 }, g); t1.textContent = s.label;
      const t2 = mk("text", { x: 8, y: 25, class: "ty" }, g); t2.textContent = s.ty.length > 30 ? s.ty.slice(0, 29) + "…" : s.ty;
      if (s.clk) { const c = mk("text", { x: BD_W - 8, y: 14, class: "ty", "text-anchor": "end" }, g); c.textContent = "⏲ clk"; }
      const port = (p, i, side) => {
        const y = BD_HEAD + i * BD_ROW + 9;
        const ep = `${s.id}.${p.name}`;
        const pg = mk("g", { class: "port" + (this.bad(ep) ? " bad" : "") }, g);
        const cx = side === "in" ? 0 : BD_W;
        const c = mk("circle", { cx, cy: y, r: 5 }, pg);
        const lab = mk("text", { x: side === "in" ? 10 : BD_W - 10, y: y + 4, "text-anchor": side === "in" ? "start" : "end" }, pg);
        lab.textContent = p.width > 1 ? `${p.name}[${p.width - 1}:0]` : p.name;
        const tt = mk("title", {}, pg); tt.textContent = `${ep} — ${p.dir}, ${p.width} bit${p.width > 1 ? "s" : ""}`;
        c.onmousedown = (e) => { e.stopPropagation(); this.startWire(e, { ep, side, width: p.width, x: s.x + cx, y: s.y + y }); };
        c.onmouseup = (e) => { e.stopPropagation(); this.endWire({ ep, side, width: p.width }); };
      };
      s.ins.forEach((p, i) => port(p, i, "in"));
      s.outs.forEach((p, i) => port(p, i, "out"));
      g.onmousedown = (e) => this.startMove(e, s);
      g.onclick = (e) => { e.stopPropagation(); };
    }
    svg.onclick = () => { if (this.sel) { this.sel = null; this.render(); } };
  },

  svgPoint(e) { return this.z.point(e); },

  startMove(e, s) {
    const p0 = this.svgPoint(e);
    const ox = s.x, oy = s.y;
    let moved = false;
    const move = (ev) => {
      const p = this.svgPoint(ev);
      const nx = Math.max(0, Math.round((ox + p.x - p0.x) / 10) * 10), ny = Math.max(0, Math.round((oy + p.y - p0.y) / 10) * 10);
      if (nx === s.x && ny === s.y) return;
      moved = true;
      if (s.key === "board_in") { this.doc.board.ix = nx; this.doc.board.iy = ny; }
      else if (s.key === "board_out") { this.doc.board.ox = nx; this.doc.board.oy = ny; }
      else { s.blk.x = nx; s.blk.y = ny; }
      s.x = nx; s.y = ny;
      this.dirty = true;
      this.render();
    };
    const up = () => {
      document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up);
      if (!moved) { this.sel = s.key; this.render(); }
      else this.renderTop();
    };
    document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
  },

  startWire(e, from) {
    this.drag = from;
    const svg = $("bdsvg");
    const ghost = document.createElementNS("http://www.w3.org/2000/svg", "path");
    ghost.setAttribute("class", "ghost");
    svg.appendChild(ghost);
    const move = (ev) => {
      const p = this.svgPoint(ev);
      ghost.setAttribute("d", `M${from.x},${from.y} L${p.x},${p.y}`);
    };
    const up = () => {
      document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up);
      ghost.remove();
      setTimeout(() => { this.drag = null; }, 0);
    };
    document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
  },

  endWire(to) {
    const from = this.drag;
    if (!from || from.ep === to.ep) return;
    if (from.side === to.side) {
      logLine("error", `${from.ep} and ${to.ep} are both ${from.side === "in" ? "inputs" : "outputs"}: a wire goes from an output to an input`);
      dock.show("log");
      return;
    }
    const src = from.side === "out" ? from : to, dst = from.side === "out" ? to : from;
    let s = src.ep, d = dst.ep;
    if (src.width !== dst.width) {                 // take the low bits; the table edits them
      const w = Math.min(src.width, dst.width);
      if (src.width > w) s += w === 1 ? "[0]" : `[${w - 1}:0]`;
      if (dst.width > w) d += w === 1 ? "[0]" : `[${w - 1}:0]`;
      logLine("info", `${src.ep} is ${src.width} bits, ${dst.ep} is ${dst.width}: wired ${s} → ${d}; edit the selects in the wire table`);
    }
    this.doc.wires.push({ src: s, dst: d });
    this.dirty = true; this.check = null;
    this.render();
  },

  // ── editing ───────────────────────────────────────────────────────────────
  uniqueId(base) {
    const used = new Set(this.doc.blocks.map((b) => b.id));
    base = base.replace(/[^A-Za-z0-9_]/g, "_").replace(/^ip_/, "").replace(/^([^A-Za-z])/, "u_$1");
    // the backend refuses Verilog keywords too; a _N suffix keeps every one of them clear
    for (let k = 0; ; k++) { const id = `${base}_${k}`; if (!used.has(id)) return id; }
  },

  async add(kind, type, params) {
    if (!this.doc) return;
    const n = this.doc.blocks.length;
    const b = { id: this.uniqueId(type), kind, type, params: { ...(params || {}) },
      x: 260 + (n % 3) * 230, y: 40 + Math.floor(n / 3) * 150 + (n % 3) * 20 };
    this.doc.blocks.push(b);
    await this.fetchPorts(b);
    this.sel = b.id; this.dirty = true; this.check = null;
    this.render();
  },

  // A board pin as its own port: the board's named pins (SW0/SW1/BTN0..3 in, LD0..2 out) or a
  // pad with no switch or LED, reachable by boundary scan only.
  addPin(dir) {
    const b = this.palette ? this.palette.board : { pins: { input: [], output: [] }, pads: [] };
    const used = new Set([...this.extraPins("input"), ...this.extraPins("output")]);
    let picked = null;
    dialog(dir === "input" ? "Add a board input" : "Add a board output", (box) => {
      const group = (title, names) => {
        box.appendChild(el("label", "f", title));
        const g = el("div");
        g.style.cssText = "display:flex;flex-wrap:wrap;gap:6px";
        for (const n of names) {
          const c = el("button", "go sec", n);
          c.style.cssText = "margin:0;width:auto;padding:3px 10px;font-family:var(--mono);font-size:11.5px";
          c.disabled = used.has(n);
          c.title = used.has(n) ? "already on the board block" : "";
          c.onclick = () => { picked = n; for (const o of box.querySelectorAll("button")) o.classList.toggle("sec", o !== c); };
          g.appendChild(c);
        }
        box.appendChild(g);
      };
      group(dir === "input" ? "Board pins (switches and buttons)" : "Board pins (LEDs)", b.pins[dir] || []);
      group(`Scan-only pads (no switch or LED; pad${b.clk_pad ?? 0} carries the clock)`, b.pads.map((n) => "pad" + n));
    }, [["Cancel", null, true], ["Add", async () => {
      if (!picked) throw new Error("pick a pin");
      const k = dir === "input" ? "in_pins" : "out_pins";
      this.doc.board[k] = (this.doc.board[k] || []).concat([picked]);
      this.dirty = true;
      this.render();
    }]]);
  },

  removePin(name) {
    const bb = this.doc.board;
    for (const k of ["in_pins", "out_pins"]) bb[k] = (bb[k] || []).filter((n) => n !== name);
    for (const k of ["in_pads", "out_pads"]) bb[k] = (bb[k] || []).filter((n) => "pad" + n !== name);
    this.doc.wires = this.doc.wires.filter((w) => w.src !== "board." + name && w.dst !== "board." + name);
    this.dirty = true; this.check = null;
    this.render();
  },

  removeSelected() {
    if (!this.sel || !this.doc) return;
    if (typeof this.sel === "object") {
      this.doc.wires.splice(this.sel.wire, 1);
    } else if (!this.sel.startsWith("board")) {
      const id = this.sel;
      this.doc.blocks = this.doc.blocks.filter((b) => b.id !== id);
      this.doc.wires = this.doc.wires.filter((w) => !w.src.startsWith(id + ".") && !w.dst.startsWith(id + "."));
      delete this.ports[id];
    }
    this.sel = null; this.dirty = true; this.check = null;
    this.render();
  },

  rename(oldId, newId) {
    newId = newId.trim();
    if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(newId) || newId.includes("__")) { logLine("error", `${newId}: a block name is a Verilog identifier without __`); dock.show("log"); return false; }
    if (this.doc.blocks.some((b) => b.id === newId)) { logLine("error", `there is already a block ${newId}`); dock.show("log"); return false; }
    const b = this.doc.blocks.find((x) => x.id === oldId);
    b.id = newId;
    const fix = (t) => t.startsWith(oldId + ".") ? newId + t.slice(oldId.length) : t;
    for (const w of this.doc.wires) { w.src = fix(w.src); w.dst = fix(w.dst); }
    this.ports[newId] = this.ports[oldId]; delete this.ports[oldId];
    this.sel = newId; this.dirty = true;
    return true;
  },

  async save() {
    if (!this.doc) return;
    await api("/api/bd", { rel: this.rel, bd: this.doc });
    this.dirty = false;
    logLine("info", `saved ${this.rel}`);
    this.renderTop();
  },

  async validate() {
    if (!this.doc) return;
    this.check = await api("/api/bd/check", { bd: this.doc });
    const n = this.check.errors.length, w = this.check.warnings.length;
    for (const e of this.check.errors) logLine("error", `${this.doc.name}: ${e.where}: ${e.msg}`);
    for (const e of this.check.warnings) logLine("warning", `${this.doc.name}: ${e.where}: ${e.msg}`);
    logLine(n ? "error" : "info", `validate ${this.doc.name}: ${n} error(s), ${w} warning(s)`);
    if (n) dock.show("log");
    this.render();
    return n === 0;
  },

  async generate() {
    if (!this.doc) return;
    if (!(await this.validate())) return;
    const r = await api("/api/bd/generate", { rel: this.rel, bd: this.doc, top: this.topAfter });
    this.dirty = false;
    project.apply(r);
    const g = r.generated;
    logLine("info", `generated ${g.wrapper} (${g.blocks} blocks, ${g.wires} wires)`
      + (g.pcf ? `, pins in ${g.pcf}` : ", no pin file needed (sw/btn/led)")
      + (this.topAfter ? `; top is now ${g.top}` : ""));
    dock.show("log");
    this.render();
  },

  // ── the panels around the canvas ────────────────────────────────────────────
  renderTop() {
    const t = $("bdtop");
    t.innerHTML = "";
    if (!this.doc) return;
    t.appendChild(el("strong", null, this.doc.name));
    t.appendChild(el("span", "pill", this.rel));
    const btn = (label, fn, sec) => {
      const b = el("button", "go" + (sec ? " sec" : ""), label);
      b.onclick = () => fn().catch((e) => { logLine("error", e.message); dock.show("log"); });
      t.appendChild(b);
    };
    btn("Save", () => this.save(), true);
    btn("Validate", () => this.validate(), true);
    if (this.z) {
      const zs = el("span");
      zs.style.cssText = "display:flex;gap:4px;align-items:center;margin-left:6px";
      this.z.controls(zs);
      t.appendChild(zs);
    }
    btn("Generate wrapper", () => this.generate());
    const l = el("label", "sw");
    const c = el("input"); c.type = "checkbox"; c.checked = this.topAfter; c.onchange = () => { this.topAfter = c.checked; };
    l.appendChild(c); l.appendChild(document.createTextNode("set as top"));
    t.appendChild(l);
    t.appendChild(el("span", "pill" + (this.dirty ? "" : " ok"), this.dirty ? "unsaved" : "saved"));
    if (this.check) t.appendChild(el("span", "pill " + (this.check.errors.length ? "err" : "ok"),
      this.check.errors.length ? `${this.check.errors.length} error(s)` : "valid"));
  },

  renderPalette() {
    const v = $("bdpal");
    v.innerHTML = "";
    if (!this.doc || !this.palette) return;
    const item = (label, sub, fn, title) => {
      const d = el("div", "pi");
      d.appendChild(el("span", null, label)); d.appendChild(el("span", null, sub));
      if (title) d.title = title;
      d.onclick = () => Promise.resolve(fn()).catch((e) => logLine("error", e.message));
      v.appendChild(d);
    };
    v.appendChild(el("h4", null, "Board"));
    item("+ input pin", "SW BTN pad", () => this.addPin("input"), "a switch, a button or a scan-only pad as its own port");
    item("+ output pin", "LD pad", () => this.addPin("output"), "an LED or a scan-only pad as its own port");
    v.appendChild(el("h4", null, "IP catalog"));
    for (const ip of this.palette.ip) {
      const defs = {};
      for (const p of ip.params) defs[p.name] = p.default;
      item(ip.ip, ip.params.map((p) => p.name).join(" "), () => this.add("ip", ip.ip, defs), ip.desc);
    }
    v.appendChild(el("h4", null, "Project modules"));
    const mods = this.palette.modules.filter((m) => !m.error);
    if (this.palette.modules.some((m) => m.error)) v.appendChild(el("div", "empty", this.palette.modules.find((m) => m.error).error));
    if (!mods.length) { const e = el("div", "empty", "none yet: add or create a .v in the Project Manager"); e.style.padding = "4px 12px"; v.appendChild(e); }
    for (const m of mods) item(m.name, `${m.ports.length} ports`, () => this.add("module", m.name, {}), m.file);
    const r = el("div", "pi"); r.appendChild(el("span", null, "↻ refresh")); r.appendChild(el("span", null, ""));
    r.onclick = async () => { await this.loadPalette(); this.render(); };
    v.appendChild(r);
  },

  renderSide() {
    const v = $("bdside");
    v.innerHTML = "";
    if (!this.doc) return;
    const b = typeof this.sel === "string" ? this.doc.blocks.find((x) => x.id === this.sel) : null;
    if (b) {
      v.appendChild(el("h4", null, "Block"));
      v.appendChild(el("label", null, "name"));
      const n = el("input"); n.value = b.id;
      n.onchange = () => { if (this.rename(b.id, n.value)) this.render(); else n.value = b.id; };
      v.appendChild(n);
      v.appendChild(el("label", null, `${b.kind === "ip" ? "IP core" : "module"}: ${b.type}`));
      const ip = b.kind === "ip" && this.palette ? this.palette.ip.find((x) => x.ip === b.type) : null;
      if (ip && ip.desc) { const d = el("div", "empty", ip.desc); d.style.padding = "2px 0"; v.appendChild(d); }
      const mod = b.kind === "module" && this.palette ? this.palette.modules.find((m) => m.name === b.type) : null;
      const params = ip ? ip.params.map((p) => [p.name, p.default, p.text]) : mod ? Object.entries(mod.params || {}).map(([k, d]) => [k, d, ""]) : [];
      for (const [k, def, text] of params) {
        v.appendChild(el("label", null, `${k}${text ? " — " + text : ""} (default ${def})`));
        const i = el("input"); i.type = "number"; i.value = b.params[k] ?? def;
        i.onchange = async () => {
          if (i.value === "" || +i.value === def && b.kind === "module") delete b.params[k];
          else b.params[k] = parseInt(i.value, 10);
          this.dirty = true; this.check = null;
          await this.fetchPorts(b);
          this.render();
        };
        v.appendChild(i);
      }
      const ports = this.ports[b.id] || [];
      v.appendChild(el("label", null, "ports"));
      const pl = el("div");
      pl.style.cssText = "font-family:var(--mono);font-size:11px;color:var(--ink-2)";
      pl.textContent = ports.map((p) => `${p.dir === "input" ? "in " : "out"} ${p.name}${p.width > 1 ? `[${p.width - 1}:0]` : ""}`).join("\n");
      pl.style.whiteSpace = "pre";
      v.appendChild(pl);
      const del = el("button", "go sec", "Delete block");
      del.onclick = () => this.removeSelected();
      v.appendChild(del);
      return;
    }
    if (this.sel === "board_in" || this.sel === "board_out") {
      const dir = this.sel === "board_in" ? "input" : "output";
      v.appendChild(el("h4", null, this.sel === "board_in" ? "Board inputs" : "Board outputs"));
      const note = el("div", "empty", "The buses (sw, btn, led) are always here. Pins added "
        + "as their own ports are listed below; removing one removes its wires.");
      note.style.padding = "2px 0 6px";
      v.appendChild(note);
      for (const n of this.extraPins(dir)) {
        const r = el("div");
        r.style.cssText = "display:flex;justify-content:space-between;font-family:var(--mono);font-size:11.5px;padding:2px 0";
        r.appendChild(el("span", null, n));
        const x = el("a", null, "remove");
        x.style.cssText = "color:var(--err);cursor:pointer;font-size:10.5px";
        x.onclick = () => this.removePin(n);
        r.appendChild(x);
        v.appendChild(r);
      }
      const add = el("button", "go sec", dir === "input" ? "+ input pin" : "+ output pin");
      add.onclick = () => this.addPin(dir);
      v.appendChild(add);
      return;
    }
    if (this.sel && typeof this.sel === "object") {
      const w = this.doc.wires[this.sel.wire];
      v.appendChild(el("h4", null, "Wire"));
      if (w) v.appendChild(el("div", null, `${w.src} → ${w.dst}`));
      const del = el("button", "go sec", "Delete wire");
      del.onclick = () => this.removeSelected();
      v.appendChild(del);
      return;
    }
    v.appendChild(el("h4", null, "Design"));
    const sum = el("div");
    sum.style.cssText = "font-size:11.5px;color:var(--ink-2);line-height:1.5";
    sum.innerHTML = `${this.doc.blocks.length} block(s), ${this.doc.wires.length} wire(s).<br>`
      + "Drag from a port to a port to wire. Click a block to set its parameters; Delete removes the selection. "
      + "<b>clk</b> reaches every clk port by itself. The wrapper's ports are clk, sw[1:0], btn[3:0], "
      + "led[2:0] and any pads you add, so a design on the board's switches and LEDs needs no pin file.";
    v.appendChild(sum);
    if (this.check) {
      v.appendChild(el("h4", null, "Check"));
      if (!this.check.errors.length && !this.check.warnings.length) v.appendChild(el("div", "wa", "no errors, no warnings"));
      for (const e of this.check.errors) v.appendChild(el("div", "er", `${e.where}: ${e.msg}`));
      for (const e of this.check.warnings) v.appendChild(el("div", "wa", `${e.where}: ${e.msg}`));
    }
  },

  renderWires() {
    const v = $("bdwires");
    v.innerHTML = "";
    if (!this.doc) return;
    if (!this.doc.wires.length) { v.appendChild(el("div", "empty", "no wires yet")); return; }
    this.doc.wires.forEach((w, i) => {
      const r = el("div", "wr" + (this.bad(w.dst) || this.bad(w.src) ? " bad" : ""));
      const a = el("input"); a.value = w.src;
      const b = el("input"); b.value = w.dst;
      a.onchange = () => { w.src = a.value.trim(); this.dirty = true; this.check = null; this.render(); };
      b.onchange = () => { w.dst = b.value.trim(); this.dirty = true; this.check = null; this.render(); };
      const x = el("a", null, "✕");
      x.style.cssText = "cursor:pointer;color:var(--err);text-align:center";
      x.onclick = () => { this.doc.wires.splice(i, 1); this.dirty = true; this.check = null; this.render(); };
      r.appendChild(a); r.appendChild(el("span", null, "→")); r.appendChild(b); r.appendChild(x);
      v.appendChild(r);
    });
  },
};

document.addEventListener("keydown", (e) => {
  if (tabs.which !== "bd" || !bd.sel) return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); bd.removeSelected(); }
});
