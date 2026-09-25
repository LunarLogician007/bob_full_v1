// ── the Flow Navigator and the build it drives ────────────────────────────
// Every "Run" button starts the same flow; there is one pipeline, and stopping it
// halfway would mean lying about what a stage proved. What differs is where the
// view goes when it finishes - the report, the Device view, or the bitstream.

const STAGE_LABEL = {
  synth: "Synthesis", pnr: "Place & Route", fasm: "FASM",
  bits: "Bits", timing: "Timing", model: "Model check", write: ".bit",
};

const flow = {
  reset() {
    S.stages = {}; S.messages = []; S.hints = []; S.placement = null; S.result = null;
    for (const n of Object.keys(STAGE_LABEL)) {
      this.dot(n, "wait", "○");
      $("k-" + n).textContent = "";
    }
    dock.render(); props.render(); device.render();
  },

  dot(stage, cls, glyph) {
    const row = document.querySelector(`.item[data-stage="${stage}"] .st`);
    if (row) { row.className = "st " + cls; row.textContent = glyph; }
  },

  spec() {
    if (S.proj) return { project: true };           // the backend builds the open project
    const p = S.project;
    return {
      files: p.files, top: p.top || null, pcf: p.pcf || null, name: p.name || null,
      clock: p.clock, div: p.div, seed: p.seed, pnr: p.pnr,
      hz: p.clock === "run" && p.hz && p.hz !== "div" ? p.hz : null,    // M20
    };
  },

  // -> a promise of true (built) or false, settled when the build is over, so Build &
  // Program can go on to the target only after a .bit exists
  async run(goTo) {
    if (S.busy) return false;
    if (S.proj && !S.proj.top) { logLine("error", "the project has no top module: set one in the Project Manager"); dock.show("log"); tabs.show("project"); return false; }
    if (!S.proj && !S.project.files.length) { logLine("error", "no sources: open an example on the Start page first"); dock.show("log"); return false; }
    // the flow builds the files on disk: an edit not yet saved would build the old text
    if (S.dirty && S.open) {
      await sources.save();
      if (S.dirty) return false;                        // the save failed and said why
      logLine("info", `saved ${S.open} before building`);
    }
    let finish;
    const over = new Promise((r) => { finish = r; });
    S.busy = true;
    S.hints = [];
    this.reset();
    buttons();
    const t0 = performance.now();
    for (const n of Object.keys(STAGE_LABEL)) this.dot(n, "wait", "○");
    this.dot("synth", "run", "◐");
    try {
      await startBuild(this.spec(),
        (ev) => {                                       // a stage finished
          S.stages[ev.name] = ev;
          this.dot(ev.name, ev.ok ? "ok" : "err", ev.ok ? "●" : "✕");
          $("k-" + ev.name).textContent = ev.seconds.toFixed(2) + "s";
          const order = Object.keys(STAGE_LABEL);
          const nxt = order[order.indexOf(ev.name) + 1];
          if (ev.ok && nxt) this.dot(nxt, "run", "◐");
          S.messages = S.messages.concat(ev.messages || []);
          editor.mark(S.messages);
          dock.render(); props.render();
        },
        (ev) => {                                       // the whole thing finished
          S.busy = false; buttons();
          if (ev.event === "failed" || !ev.ok) {
            logLine("error", ev.error || "build failed");
            S.hints = ev.hints || [];
            dock.show(S.messages.length || S.hints.length ? "messages" : "log");
            finish(false);
          } else {
            S.result = ev;
            S.placement = ev.placement;
            logLine("info", `build ok in ${((performance.now() - t0) / 1000).toFixed(2)} s -> ${bitPath()}`);
            device.render();
            if (S.proj) project.load();                 // its Outputs now list the .bit
            if (goTo) tabs.show(goTo);
            dock.show("stages");
            finish(true);
          }
          props.render();
        });
    } catch (e) {
      S.busy = false; buttons();
      logLine("error", String(e.message || e));
      dock.show("log");
      finish(false);
    }
    return over;
  },
};

function bitPath() {
  const w = S.stages.write;
  return w && w.stats ? w.stats.path : null;
}

function buttons() {
  for (const id of ["runsynth", "runimpl", "runbit", "buildprog"]) {
    const n = $(id);
    n.style.opacity = S.busy ? 0.45 : 1;
    n.style.pointerEvents = S.busy ? "none" : "auto";
  }
  // Program stays clickable even when it cannot run: a dead control that says nothing
  // is how "I pressed Program and nothing happened" happens. board.program() reports
  // exactly which part is missing.
  const p = $("program");
  const ready = !S.busy && board.target_bit() && S.target && S.target.open;
  p.style.opacity = S.busy ? 0.45 : 1;
  p.style.pointerEvents = S.busy ? "none" : "auto";
  p.title = ready ? `program ${board.target_bit()}`
    : "needs a target and a bitstream — click to see which is missing";
}

// ── the dock: messages, stages, log ───────────────────────────────────────

const dock = {
  which: "stages",

  tabs() {
    const t = $("docktabs");
    t.innerHTML = "";
    const counts = {
      messages: S.messages.length,
      stages: Object.keys(S.stages).length,
      log: S.log.length,
    };
    for (const k of ["messages", "stages", "log"]) {
      const b = el("div", "tab" + (this.which === k ? " on" : ""));
      b.textContent = k[0].toUpperCase() + k.slice(1);
      if (counts[k]) b.appendChild(el("span", "pill", String(counts[k])));
      b.onclick = () => this.show(k);
      t.appendChild(b);
    }
  },

  show(k) { this.which = k; this.render(); },

  render() {
    this.tabs();
    const b = $("dockbody");
    b.innerHTML = "";
    if (this.which === "messages") {
      for (const h of S.hints || []) {                 // what to do about it (ux.hints)
        const row = el("div", "msg hint");
        row.appendChild(el("span", "sev", "→"));
        row.appendChild(el("span", "loc", "hint"));
        row.appendChild(el("span", "txt", h));
        b.appendChild(row);
      }
      if (!S.messages.length && !(S.hints || []).length) return void b.appendChild(el("div", "empty", "No diagnostics."));
      for (const m of S.messages) {
        const row = el("div", "msg " + m.severity);
        row.appendChild(el("span", "sev", m.severity === "error" ? "✕" : m.severity === "warning" ? "!" : "·"));
        if (m.file && m.line) {
          const loc = el("span", "loc", `${m.file.split("/").pop()}:${m.line}`);
          loc.onclick = () => editor.goto(m.line);
          row.appendChild(loc);
        }
        row.appendChild(el("span", "txt", m.text));
        row.appendChild(el("span", "src", m.source || ""));
        b.appendChild(row);
      }
    } else if (this.which === "stages") {
      const names = Object.keys(STAGE_LABEL).filter((n) => S.stages[n]);
      if (!names.length) return void b.appendChild(el("div", "empty", "Run the flow to see its stages (⌘/Ctrl Enter)."));
      if (bitPath() && !S.busy) {                       // the next step, where the eye already is
        const nb = el("div", "nextbar");
        nb.appendChild(el("span", null, `✓ built ${bitPath().split("/").pop()}`));
        nb.appendChild(el("span", "sp"));
        const go = el("button", "sbtn pri", "Program Device ▸");
        go.onclick = () => (S.target && S.target.open ? board.program() : buildAndProgram());
        nb.appendChild(go);
        b.appendChild(nb);
      }
      for (const n of names) {
        const s = S.stages[n];
        const row = el("div", "stg");
        row.appendChild(el("span", "sev " + (s.ok ? "" : "error"), s.ok ? "✓" : "✕"));
        row.appendChild(el("span", "nm", n));
        row.appendChild(el("span", "tm", s.seconds.toFixed(2) + "s"));
        row.appendChild(el("span", "dt", s.detail));
        row.title = s.detail;
        b.appendChild(row);
      }
    } else {
      if (!S.log.length) return void b.appendChild(el("div", "empty", "Nothing logged yet."));
      for (const l of S.log.slice().reverse()) {
        const row = el("div", "msg " + (l.kind === "error" ? "error" : "info"));
        row.appendChild(el("span", "sev", l.kind === "error" ? "✕" : "·"));
        row.appendChild(el("span", "loc", l.t));
        row.appendChild(el("span", "txt", l.text));
        b.appendChild(row);
      }
    }
  },
};

// ── the properties pane ───────────────────────────────────────────────────

const props = {
  row(parent, k, v) {
    const r = el("div", "row");
    r.appendChild(el("span", null, k));
    r.appendChild(el("span", null, v == null ? "—" : String(v)));
    parent.appendChild(r);
  },

  meter(parent, label, used, total) {
    const m = el("div", "meter");
    const frac = total ? used / total : 0;
    if (frac > 0.8) m.classList.add("hot");
    const lab = el("div", "lab");
    lab.appendChild(el("span", null, label));
    lab.appendChild(el("b", null, `${used} / ${total}`));
    m.appendChild(lab);
    const bg = el("div", "bg"), fg = el("div", "fg");
    fg.style.width = (frac * 100).toFixed(1) + "%";
    bg.appendChild(fg); m.appendChild(bg);
    parent.appendChild(m);
  },

  render() {
    const d = S.device, box = $("props");
    // With a project open the settings are the project's, and changing one saves it.
    const p = S.proj ? { ...S.proj.settings, top: S.proj.top, name: S.proj.name } : S.project;
    box.innerHTML = "";
    if (S.proj) {
      this.row(box, "project", S.proj.name);
      this.row(box, "top", S.proj.top || "(none)");
      this.row(box, "sources", String(S.proj.sources.length));
      this.row(box, "pins", S.proj.active_pcf ? S.proj.active_pcf.split("/").pop() : "convention");
    } else {
      this.row(box, "design", p.name || p.top || "—");
      this.row(box, "sources", p.files.length ? p.files.map((f) => f.split("/").pop()).join(", ") : "—");
    }
    const put = (key, val) => {
      if (S.proj) project.post("settings", { [key]: val }).catch((e) => { logLine("error", e.message); dock.show("log"); });
      else { p[key] = val; this.render(); }
    };

    const sel = (key, opts) => {
      const r = el("div", "row");
      r.appendChild(el("span", null, key));
      const s = document.createElement("select");
      for (const o of opts) { const op = document.createElement("option"); op.value = o; op.textContent = o; s.appendChild(op); }
      s.value = p[key];
      s.onchange = () => put(key, s.value);
      const w = el("span", null); w.appendChild(s); r.appendChild(w);
      box.appendChild(r);
    };
    const num = (key, min, max) => {
      const r = el("div", "row");
      r.appendChild(el("span", null, key));
      const i = document.createElement("input");
      i.type = "number"; i.min = min; i.max = max; i.value = p[key];
      i.onchange = () => { const v = Math.max(min, Math.min(max, parseInt(i.value || "0", 10))); i.value = v; put(key, v); };
      const w = el("span", null); w.appendChild(i); r.appendChild(w);
      box.appendChild(r);
    };
    sel("pnr", ["vpr", "python"]);
    const cc = S.proj && S.proj.clock_constraint;
    if (cc && cc.period_ns) {
      // M20: the project's .sdc sets the free-running clock; the build checks the design against it
      this.row(box, "clock", `${cc.mhz.toFixed(3)} MHz (.sdc)`);
    } else {
      sel("clock", ["jtag", "run"]);
      // M20: "auto" runs the design as fast as its own timing allows (the Timing stage says how fast)
      if (p.clock === "run") sel("hz", ["div", "auto"]);
      if (!(p.clock === "run" && p.hz === "auto")) num("div", 0, 31);
    }
    num("seed", 1, 9999);
    if (p.clock === "run" && d && !(cc && cc.period_ns)) {
      if (p.hz === "auto") {
        const t = S.stages.timing && S.stages.timing.stats;
        this.row(box, "guest clock", t && t.hz ? (t.hz / 1e6).toFixed(3) + " MHz" : "from timing");
      } else {
        const hz = d.clock.sysclk_hz / Math.pow(2, p.div + d.clock.div_min_shift);
        this.row(box, "guest clock", hz >= 1000 ? (hz / 1000).toFixed(2) + " kHz" : hz.toFixed(2) + " Hz");
      }
    }

    const u = $("util");
    u.innerHTML = "";
    if (!d) return;
    const by = {};
    for (const b of (S.placement ? S.placement.blocks : [])) by[b.type] = (by[b.type] || 0) + 1;
    // what synthesis asked for (LUTs, flip-flops, carry bits), then what placement used
    const use = S.stages.synth && S.stages.synth.stats && S.stages.synth.stats.usage;
    for (const r of use || []) if (!/BRAM|DSP/.test(r.name)) this.meter(u, r.name, r.used, r.cap);
    for (const t of ["clb", "bram", "dsp", "io"]) if (d.capacity[t]) this.meter(u, t.toUpperCase(), by[t] || 0, d.capacity[t]);
    if (S.placement) this.row(u, "wirelength", S.placement.wirelength);
    if (S.stages.fasm) this.row(u, "features", S.stages.fasm.stats.features);
    if (S.stages.pnr) this.row(u, "engine", S.stages.pnr.stats.engine + (S.stages.pnr.stats.reused ? " (cached)" : ""));
    if (S.stages.timing && S.stages.timing.stats) {           // M20: the design's own timing
      const t = S.stages.timing.stats;
      this.row(u, "critical path", `${t.cpd_ns} ns`);
      this.row(u, "Fmax", `${(t.fmax_hz / 1e6).toFixed(2)} MHz${t.provisional ? " (prov.)" : ""}`);
      if (t.hz) this.row(u, "user clock", `${(t.hz / 1e6).toFixed(3)} MHz`);
      if (t.slack_ns != null) {                             // a constrained clock: Vivado's WNS
        this.row(u, "slack", `${t.slack_ns >= 0 ? "+" : ""}${t.slack_ns.toFixed(3)} ns ${t.slack_ns >= 0 ? "(met)" : "(FAILED)"}`);
      }
    }
    if (bitPath()) this.row(u, "bitstream", bitPath().split("/").pop());

    const dp = $("devprops");
    dp.innerHTML = "";
    this.row(dp, "device", d.name);
    this.row(dp, "grid", `${d.grid.w} x ${d.grid.h}`);
    this.row(dp, "LUT K", d.lut_k);
    this.row(dp, "channel W", d.chan_width);
    this.row(dp, "routing muxes", d.muxes);
    this.row(dp, "config bits", d.chain_w);
    this.row(dp, "frames", d.frames);
    this.row(dp, "pads", d.pads);
  },
};
