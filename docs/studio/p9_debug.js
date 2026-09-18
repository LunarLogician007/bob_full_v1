// ── Pin Planner and the Bitstream browser ─────────────────────────────────
// The two views that make the flow's ends inspectable: which port sits on which
// pad before a build, and what the bitstream actually says after one.

const pinplan = {
  map: null,
  assign: {},

  async load() {
    if (!this.map) this.map = await api("/api/pins");
    this.render();
  },

  ports() {
    // One row per PIN, not per port. vpr_run.write_eblif names every port bit
    // `port[i]` — including a one-bit port, which is `en[0]` and not `en`. Getting that
    // wrong produces a .pcf the flow rejects with "input en[0] has no pin".
    // Widths come from the synth stage; before a build, fall back to the convention.
    const s = S.stages.synth;
    const decl = s && s.stats.ports && typeof s.stats.ports[0] === "object"
      ? s.stats.ports
      : [{ name: "sw", width: 2, dir: "input" }, { name: "btn", width: 4, dir: "input" },
         { name: "led", width: 3, dir: "output" }];
    const out = [];
    for (const p of decl) {
      if (p.name === "clk") continue;            // the clock is not a pad
      for (let i = 0; i < p.width; i++) out.push({ pin: `${p.name}[${i}]`, dir: p.dir });
    }
    return out;
  },

  // An input belongs on a switch or a button, an output on an LED. Any pad works for
  // either (boundary scan reaches all 44), so the rest are always offered.
  pinsFor(dir) {
    if (!this.map) return [];
    const board = Object.keys(this.map.board);
    const want = dir === "output" ? (n) => n.startsWith("LD") : (n) => !n.startsWith("LD");
    const scan = this.map.pads.filter((p) => !p.name).map((p) => `pad${p.pad}`);
    return board.filter(want).concat(board.filter((n) => !want(n)), scan);
  },

  render() {
    const v = $("pinview");
    v.innerHTML = "";
    if (!this.map) return void v.appendChild(el("div", "empty", "loading…"));
    const d = S.device;

    const note = el("div", "empty",
      "Without a pin file the flow uses the convention: " + this.map.convention
      + ". Assign a port to a pad here and studio writes a .pcf the build reads. "
      + "Pads with no board name are reachable by boundary scan only.");
    note.style.maxWidth = "780px";
    v.appendChild(note);

    // the pad ring, drawn where the pads actually are on the die
    const NS = "http://www.w3.org/2000/svg";
    const C = 26, P = 14;
    const svg = document.createElementNS(NS, "svg");
    const W = P * 2 + d.grid.w * C, H = P * 2 + d.grid.h * C;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.style.cssText = "max-width:420px;max-height:340px;margin:10px 0";
    for (const pad of this.map.pads) {
      const x = P + pad.x * C, y = P + (d.grid.h - 1 - pad.y) * C;
      const taken = Object.entries(this.assign).find(([, v2]) => v2 === (pad.name || `pad${pad.pad}`));
      const fill = taken ? "var(--accent)" : pad.kind === "input" ? "#cfe3d6"
        : pad.kind === "output" ? "#f2ddc8" : "var(--rule-2)";
      const r = document.createElementNS(NS, "rect");
      r.setAttribute("x", x + 1.5); r.setAttribute("y", y + 1.5);
      r.setAttribute("width", C - 3); r.setAttribute("height", C - 3);
      r.setAttribute("rx", 3); r.setAttribute("fill", fill);
      r.setAttribute("stroke", taken ? "var(--accent)" : "var(--rule)");
      const t = document.createElementNS(NS, "title");
      t.textContent = `pad${pad.pad}${pad.name ? " = " + pad.name : " (scan only)"}`
        + (taken ? `\n${taken[0]}` : "");
      r.appendChild(t);
      svg.appendChild(r);
      const lab = document.createElementNS(NS, "text");
      lab.setAttribute("x", x + C / 2); lab.setAttribute("y", y + C / 2 + 3);
      lab.setAttribute("text-anchor", "middle");
      lab.setAttribute("font-family", "var(--mono)"); lab.setAttribute("font-size", 7.5);
      lab.setAttribute("fill", taken ? "#fff" : "var(--mute)");
      lab.textContent = pad.name || pad.pad;
      svg.appendChild(lab);
    }
    v.appendChild(svg);

    // one row per pin
    const rows = this.ports();
    const tbl = el("div", null);
    tbl.style.cssText = "max-width:380px;border-top:1px solid var(--rule);padding-top:8px";
    if (!rows.length) {
      tbl.appendChild(el("div", "empty", "Run Synthesis to see this design's ports."));
    }
    for (const { pin, dir } of rows) {
      const r = el("div", "row");
      const lab = el("span", null, pin);
      lab.title = `${dir} · the netlist calls this net ${pin}`;
      r.appendChild(lab);
      const sel = document.createElement("select");
      for (const o of ["(convention)"].concat(this.pinsFor(dir))) {
        const op = document.createElement("option"); op.value = o; op.textContent = o; sel.appendChild(op);
      }
      sel.value = this.assign[pin] || "(convention)";
      sel.onchange = () => {
        if (sel.value === "(convention)") delete this.assign[pin];
        else this.assign[pin] = sel.value;
        this.render();
      };
      const w = el("span", null);
      w.appendChild(sel);
      const d = el("span", null, dir === "output" ? " out" : " in");
      d.style.cssText = "font-family:var(--mono);font-size:9.5px;color:var(--faint);margin-left:5px";
      w.appendChild(d);
      r.appendChild(w);
      tbl.appendChild(r);
    }
    v.appendChild(tbl);

    const bar = el("div", null);
    bar.style.cssText = "display:flex;gap:10px;margin-top:12px;align-items:center";
    const save = el("button", "go sec", "write .pcf and use it");
    save.style.cssText = "margin:0;width:auto;padding:5px 14px";
    save.disabled = !Object.keys(this.assign).length;
    save.onclick = () => this.save();
    bar.appendChild(save);
    const clear = el("button", "go sec", "back to the convention");
    clear.style.cssText = "margin:0;width:auto;padding:5px 14px";
    clear.onclick = () => { this.assign = {}; S.project.pcf = null; S.project.name = null; this.render(); props.render(); };
    bar.appendChild(clear);
    if (S.project.pcf) bar.appendChild(el("span", "pill ok", S.project.pcf));
    v.appendChild(bar);
  },

  async save() {
    try {
      const name = (S.project.top || "design") + "_pins";
      // Only pins this design actually has. Assignments made before Synthesis come from
      // the sw/btn/led fallback, and writing those into a .pcf puts a set_io line there
      // for a port the module does not declare.
      const real = new Set(this.ports().map((p) => p.pin));
      const assign = {}, dropped = [];
      for (const [pin, v] of Object.entries(this.assign)) {
        if (real.has(pin)) assign[pin] = v; else dropped.push(pin);
      }
      if (dropped.length) {
        logLine("info", `not in ${S.project.top || "this design"}, left out of the .pcf: `
          + dropped.join(", "));
        for (const p of dropped) delete this.assign[p];
      }
      if (!Object.keys(assign).length) {
        logLine("error", "nothing to write: run Synthesis, then assign this design's pins");
        dock.show("log");
        return;
      }
      const r = await api("/api/pcf", { name, assign });
      S.project.pcf = r.pcf;
      S.project.name = name;
      logLine("info", `wrote ${r.pcf}; the next build uses it`);
      this.render(); props.render();
    } catch (e) {
      logLine("error", String(e.message || e)); dock.show("log");
    }
  },
};

const bitstream = {
  data: null,

  async load() {
    const bit = bitPath();
    const v = $("bitview");
    if (!bit) { v.innerHTML = ""; v.appendChild(el("div", "empty", "Generate a bitstream first.")); return; }
    try { this.data = await api("/api/fasm?bit=" + encodeURIComponent(bit)); }
    catch (e) { logLine("error", String(e.message || e)); return; }
    this.render();
  },

  render() {
    const v = $("bitview"), d = this.data;
    v.innerHTML = "";
    if (!d) return;
    const head = el("div", null);
    head.style.cssText = "display:flex;gap:16px;flex-wrap:wrap;margin:10px 0;align-items:center";
    for (const [k, val] of [["features", d.features], ["chain", d.width + " bits"],
                            ["frames", d.frames.length], ["CRC", d.crc],
                            ["BRAM", d.brams.length ? d.brams.join(", ") : "none"]]) {
      const s = el("span", "pill", `${k} ${val}`);
      head.appendChild(s);
    }
    v.appendChild(head);

    // the frame map: one cell per frame, shaded by how many bits it sets
    const used = d.frames.filter((f) => f.set).length;
    v.appendChild(el("div", "lg", `${used} of ${d.frames.length} frames carry bits; `
      + `each is ${d.width / d.frames.length} bits. Columns follow the FAR map.`));
    const grid = el("div", null);
    grid.style.cssText = "display:flex;flex-wrap:wrap;gap:2px;margin:8px 0 14px;max-width:760px";
    const max = Math.max(1, ...d.frames.map((f) => f.set));
    for (const f of d.frames) {
      const c = el("div", null);
      const a = f.set / max;
      c.style.cssText = `width:13px;height:13px;border-radius:2px;background:${
        f.set ? `color-mix(in srgb, var(--accent) ${Math.round(20 + a * 80)}%, var(--rule-2))`
              : "var(--rule-2)"};border:1px solid var(--rule)`;
      c.title = `frame ${f.index}: ${f.set} bits set\n${f.hex.slice(0, 32)}…`;
      grid.appendChild(c);
    }
    v.appendChild(grid);

    const pre = document.createElement("pre");
    pre.style.cssText = "font-family:var(--mono);font-size:11px;line-height:1.5;margin:0;"
      + "max-height:340px;overflow:auto;background:var(--rule-2);padding:10px;border-radius:5px";
    pre.textContent = d.fasm;
    v.appendChild(pre);
  },
};
