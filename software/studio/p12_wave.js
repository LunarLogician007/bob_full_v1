// ── the waveform viewer: a logic analyser on the pads (M19) ──────────────────────────
// software/host/padwave.py takes the samples through JTAG - INTEST autostep, one sample per
// user clock (step), or SAMPLE while the design runs (live) - and this draws them. Zoom is
// on the time axis only, as in any logic analyser: Ctrl/⌘-wheel or the buttons zoom about
// the pointer, a plain wheel or a drag scrolls, and the cursor reads every signal's value.

const WAVE_NAME_W = 150, WAVE_ROW = 26, WAVE_TOP = 28;

const wavev = {
  sigs: null,            // /api/wave/signals
  sel: null,             // Set of chosen signal names
  cap: null,             // the last capture
  x0: 0, span: null,     // visible window, in samples
  cursor: null,
  busy: false,
  opts: { mode: "step", depth: 256, trig: "", cond: "rise", pre: 25, stim: "hold", vector: 0 },

  async load() {
    try {
      this.sigs = await api("/api/wave/signals");
      if (!this.sel) this.sel = new Set(this.sigs.signals.filter((s) => s.board).map((s) => s.name));
    } catch (e) { logLine("error", e.message); }
    this.render();
  },

  async run() {
    if (this.busy) return;
    if (!S.target || !S.target.open) { logLine("error", "open a target first (Board tab, or --probe)"); dock.show("log"); return; }
    const o = this.opts;
    const body = {
      mode: o.mode, depth: +o.depth, sel: [...this.sel], pre: o.pre / 100,
      trigger: o.trig ? { signal: o.trig, cond: o.cond } : null,
      stimulus: o.stim === "hold" ? { kind: "hold", vector: o.vector } : { kind: o.stim, seed: Date.now() % 100000 },
      timeout: 10,
    };
    if (!body.sel.length) { logLine("error", "choose at least one signal"); dock.show("log"); return; }
    this.busy = true; this.render();
    try {
      this.cap = await api("/api/wave/capture", body);
      this.x0 = 0; this.span = null; this.cursor = this.cap.trigger;
      logLine("info", `captured ${this.cap.depth} samples (${this.cap.mode}) in ${this.cap.seconds} s`
        + (this.cap.trigger != null ? `, trigger at ${this.cap.trigger}` : "")
        + (this.cap.mode === "live" ? `, ${this.cap.rate} samples/s` : ""));
    } catch (e) {
      logLine("error", String(e.message || e)); dock.show("log");
    }
    this.busy = false;
    this.render();
  },

  // ── the window on the time axis ──
  view() {
    const n = this.cap ? this.cap.depth : 1;
    const span = Math.max(4, Math.min(n, this.span || n));
    const x0 = Math.max(0, Math.min(n - span, this.x0));
    return { x0, span, n };
  },
  zoom(f, at) {
    const v = this.view();
    const c = at == null ? v.x0 + v.span / 2 : at;
    const span = Math.max(4, Math.min(v.n, v.span / f));
    this.x0 = c - (c - v.x0) * (span / v.span);
    this.span = span;
    this.render();                                 // the controls show the window too
  },
  fit() { this.x0 = 0; this.span = null; this.render(); },

  // ── controls ──
  render() {
    const top = $("wavetop");
    top.innerHTML = "";
    const o = this.opts;
    const field = (label, node) => {
      const w = el("label", "sw");
      w.appendChild(document.createTextNode(label + " "));
      w.appendChild(node);
      top.appendChild(w);
      return node;
    };
    const select = (opts, val, fn) => {
      const s = document.createElement("select");
      s.style.cssText = "font:inherit;font-size:11.5px";
      for (const [v, t] of opts) { const op = document.createElement("option"); op.value = v; op.textContent = t; s.appendChild(op); }
      s.value = val; s.onchange = () => { fn(s.value); this.render(); };
      return s;
    };
    const num = (val, min, max, fn) => {
      const i = document.createElement("input");
      i.type = "number"; i.min = min; i.max = max; i.value = val; i.style.cssText = "width:64px;font:inherit;font-size:11.5px";
      i.onchange = () => { fn(Math.max(min, Math.min(max, parseInt(i.value || "0", 10)))); };
      return i;
    };
    field("mode", select([["step", "step (1 sample / user clock)"], ["live", "live (SAMPLE, real time)"]], o.mode, (v) => { o.mode = v; }));
    field("depth", num(o.depth, 2, (this.sigs && this.sigs.max_depth) || 4096, (v) => { o.depth = v; }));
    const names = this.sigs ? this.sigs.signals.map((s) => s.name) : [];
    field("trigger", select([["", "none (start now)"]].concat(names.map((n) => [n, n])), o.trig, (v) => { o.trig = v; }));
    if (o.trig) {
      field("when", select([["rise", "rises"], ["fall", "falls"], ["high", "is 1"], ["low", "is 0"], ["change", "changes"]], o.cond, (v) => { o.cond = v; }));
      field("pre %", num(o.pre, 0, 90, (v) => { o.pre = v; }));
    }
    if (o.mode === "step") {
      field("inputs", select([["hold", "hold these"], ["random", "random"], ["pins", "the real switches"]], o.stim, (v) => { o.stim = v; }));
      if (o.stim === "hold") {
        const box = el("span");
        box.style.cssText = "display:flex;gap:4px";
        ["SW0", "SW1", "BTN0", "BTN1", "BTN2", "BTN3"].forEach((n, k) => {
          const b = el("button", "go" + (o.vector >> k & 1 ? "" : " sec"), n);
          b.style.cssText = "margin:0;width:auto;padding:1px 6px;font-size:10.5px;font-family:var(--mono)";
          b.onclick = () => { o.vector ^= 1 << k; this.render(); };
          box.appendChild(b);
        });
        top.appendChild(box);
      }
    }
    const go = el("button", "go", this.busy ? "capturing…" : "Run capture");
    go.style.cssText = "margin:0;width:auto;padding:4px 14px";
    go.disabled = this.busy;
    go.onclick = () => this.run();
    top.appendChild(go);
    const vcd = el("a", "pill", "export .vcd");
    vcd.href = "/api/wave/vcd";
    vcd.onclick = async (e) => {                  // the app window has no downloads: save natively
      if (!native()) return;
      e.preventDefault();
      const text = await (await fetch("/api/wave/vcd")).text();
      const path = await native().save_text((this.cap.design || "pads") + ".vcd", text);
      if (path) logLine("info", `saved ${path}`);
    };
    vcd.style.cssText += ";cursor:pointer;text-decoration:none;color:var(--run)" + (this.cap ? "" : ";opacity:.4;pointer-events:none");
    top.appendChild(vcd);
    const zs = el("span");
    zs.style.cssText = "display:flex;gap:4px;align-items:center;margin-left:auto";
    const zb = (t, title, fn) => { const b = el("button", "go sec", t); b.title = title; b.style.cssText = "margin:0;width:auto;padding:2px 9px"; b.onclick = fn; zs.appendChild(b); };
    zb("−", "zoom out (Ctrl/⌘ + wheel)", () => this.zoom(1 / 1.5));
    const v = this.view();
    zs.appendChild(el("span", "pill", this.cap ? `${Math.round(v.span)} of ${v.n}` : "—"));
    zb("+", "zoom in (Ctrl/⌘ + wheel)", () => this.zoom(1.5));
    zb("fit", "the whole capture", () => this.fit());
    top.appendChild(zs);

    this.renderList();
    this.draw();
  },

  renderList() {
    const v = $("wavelist");
    v.innerHTML = "";
    if (!this.sigs) { v.appendChild(el("div", "empty", "loading…")); return; }
    const info = el("div", "empty", this.sigs.design
      ? `design ${this.sigs.design} (clock ${this.sigs.clock})` : "no design programmed from the studio yet: signals are named by the sw/btn/led convention");
    info.style.padding = "4px 10px 8px";
    v.appendChild(info);
    const group = (title, list) => {
      v.appendChild(el("h4", null, title));
      for (const s of list) {
        const r = el("label", "sw");
        r.style.cssText = "padding:2px 10px;font-family:var(--mono);font-size:11px";
        const c = el("input"); c.type = "checkbox"; c.checked = this.sel.has(s.name);
        c.onchange = () => { if (c.checked) this.sel.add(s.name); else this.sel.delete(s.name); };
        r.appendChild(c);
        r.appendChild(document.createTextNode(" " + s.name + (s.port ? `  ${s.port}` : "")));
        v.appendChild(r);
      }
    };
    group("Board pins", this.sigs.signals.filter((s) => s.board));
    const named = this.sigs.signals.filter((s) => !s.board && s.port);
    if (named.length) group("Design pads", named);
    group("Other pads (scan only)", this.sigs.signals.filter((s) => !s.board && !s.port));
  },

  draw() {
    const svg = $("wavesvg");
    svg.innerHTML = "";
    const NS = "http://www.w3.org/2000/svg";
    const mk = (tag, a, parent) => { const n = document.createElementNS(NS, tag); for (const [k, x] of Object.entries(a || {})) n.setAttribute(k, x); (parent || svg).appendChild(n); return n; };
    const W = Math.max(400, svg.clientWidth || 900);
    const cap = this.cap;
    if (!cap) {
      svg.setAttribute("viewBox", `0 0 ${W} 120`);
      const t = mk("text", { x: 20, y: 40, style: "font:12.5px var(--sans);fill:var(--faint)" });
      t.textContent = "Choose signals and press Run capture. step: one sample per user clock through INTEST "
        + "(the design must be built with clock jtag). live: SAMPLE while it runs on its own clock.";
      return;
    }
    const rows = cap.signals.length;
    const H = WAVE_TOP + rows * WAVE_ROW + 24;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.style.height = H + "px";
    const v = this.view();
    const plotW = W - WAVE_NAME_W - 10;
    const xOf = (i) => WAVE_NAME_W + (i - v.x0) / v.span * plotW;
    this.xToSample = (x) => v.x0 + (x - WAVE_NAME_W) / plotW * v.span;

    mk("rect", { x: 0, y: 0, width: W, height: H, class: "bg", fill: "transparent" });
    // time axis
    const step = Math.pow(10, Math.floor(Math.log10(Math.max(1, v.span / 8))));
    const tick = [1, 2, 5, 10].map((m) => m * step).find((s) => v.span / s <= 12) || step * 10;
    for (let i = Math.ceil(v.x0 / tick) * tick; i <= v.x0 + v.span; i += tick) {
      const x = xOf(i);
      mk("line", { x1: x, x2: x, y1: WAVE_TOP - 6, y2: H - 20, stroke: "var(--rule-2)" });
      const t = mk("text", { x, y: WAVE_TOP - 10, "text-anchor": "middle", style: "font:10px var(--mono);fill:var(--mute)" });
      const ti = Math.min(cap.depth - 1, Math.round(i));
      t.textContent = cap.unit === "s" ? (cap.t[ti] * 1000).toFixed(0) + "ms" : String(i - (cap.trigger || 0));
    }
    // signals
    const lo = Math.max(0, Math.floor(v.x0)), hi = Math.min(cap.depth, Math.ceil(v.x0 + v.span) + 1);
    cap.signals.forEach((s, r) => {
      const y0 = WAVE_TOP + r * WAVE_ROW, yH = y0 + 5, yL = y0 + WAVE_ROW - 7;
      if (r % 2) mk("rect", { x: 0, y: y0, width: W, height: WAVE_ROW, fill: "var(--rule-2)", opacity: 0.45, class: "bg" });
      const nm = mk("text", { x: 8, y: y0 + 16, style: "font:11px var(--mono);fill:var(--ink)" });
      nm.textContent = s.name + (s.port ? ` ${s.port}` : "");
      let d = "", last = null;
      for (let i = lo; i < hi; i++) {
        const b = cap.samples[i][r];
        const y = b ? yH : yL, x = xOf(i);
        if (last === null) d += `M${x},${y}`;
        else if (b !== last) d += `L${x},${last ? yH : yL}L${x},${y}`;
        last = b;
      }
      if (last !== null) d += `L${xOf(hi)},${last ? yH : yL}`;
      mk("path", { d, fill: "none", stroke: "var(--ok)", "stroke-width": 1.5 });
    });
    if (cap.trigger != null && cap.trigger >= v.x0 && cap.trigger <= v.x0 + v.span) {
      const x = xOf(cap.trigger);
      mk("line", { x1: x, x2: x, y1: WAVE_TOP - 4, y2: H - 20, stroke: "var(--err)", "stroke-dasharray": "4 3" });
      const t = mk("text", { x: x + 3, y: H - 8, style: "font:10px var(--mono);fill:var(--err)" });
      t.textContent = `T ${cap.trigger_on.signal} ${cap.trigger_on.cond}`;
    }
    if (this.cursor != null && this.cursor >= v.x0 && this.cursor <= v.x0 + v.span) {
      const k = Math.round(this.cursor), x = xOf(k);
      mk("line", { x1: x, x2: x, y1: WAVE_TOP - 4, y2: H - 20, stroke: "var(--accent)" });
      const when = cap.unit === "s" ? `${(cap.t[k] * 1000).toFixed(1)} ms` : `clock ${k - (cap.trigger || 0)}`;
      const vals = cap.signals.map((s, r) => `${s.name}=${cap.samples[k][r]}`).join("  ");
      $("waveread").textContent = `sample ${k} · ${when}` + (cap.mode === "step" ? ` · inputs ${cap.vectors[k].toString(2).padStart(6, "0")}` : "") + "   " + vals;
    }
  },

  wire() {
    const svg = $("wavesvg");
    svg.addEventListener("wheel", (e) => {
      if (!this.cap) return;
      e.preventDefault();
      const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
      const p = pt.matrixTransform(svg.getScreenCTM().inverse());
      if (e.ctrlKey || e.metaKey) this.zoom(Math.exp(-e.deltaY * 0.004), this.xToSample(p.x));
      else { const v = this.view(); this.x0 = v.x0 + (e.deltaX || e.deltaY) / 600 * v.span; this.draw(); }
    }, { passive: false });
    svg.addEventListener("mousedown", (e) => {
      if (!this.cap) return;
      const r = svg.getBoundingClientRect(), v0 = this.view(), x0 = e.clientX;
      let moved = false;
      const move = (ev) => {
        const dx = (ev.clientX - x0) / r.width * (svg.viewBox.baseVal.width);
        if (Math.abs(ev.clientX - x0) > 3) moved = true;
        this.x0 = v0.x0 - dx / (svg.viewBox.baseVal.width - WAVE_NAME_W - 10) * v0.span;
        this.draw();
      };
      const up = (ev) => {
        document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up);
        if (!moved) {                             // a click puts the cursor there
          const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
          const p = pt.matrixTransform(svg.getScreenCTM().inverse());
          this.cursor = Math.max(0, Math.min(this.cap.depth - 1, Math.round(this.xToSample(p.x))));
          this.draw();
        }
      };
      document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
    });
    window.addEventListener("resize", () => { if (tabs.which === "wave") this.draw(); });
  },
};
