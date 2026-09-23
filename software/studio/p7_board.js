// ── Program and Debug ─────────────────────────────────────────────────────
// A target is either the Pico on PMODA or the board in software. The software one
// answers from software/bob/model.py, so the whole flow works with no hardware - and
// the panel says so, including how far behind real time its guest clock is.

const board = {
  poll: null,
  bits: [],
  chosen: null,          // the .bit the Board pane will program

  async open(kind) {
    if (!kind) { tabs.show("board"); logLine("info", "pick a target in the Board tab"); return; }
    try {
      const t = await api("/api/target", { kind });
      logLine("info", `target ${t.kind}: IDCODE ${t.idcode}`
        + (t.match ? "" : ` — MISMATCH, expected ${t.expected}: the PL holds a different bob build`));
      await this.refresh();
      tabs.show("board");
    } catch (e) {
      logLine("error", `cannot open ${kind}: ${e.message || e}`);
      dock.show("log");
      tabs.show("board");
    }
  },

  async loadBits() {
    try { this.bits = await api("/api/bits"); } catch (e) { this.bits = []; }
    if (!this.chosen && this.bits.length) {
      // prefer this design's bitstream, else whatever was built last
      const mine = this.bits.find((b) => b.top === S.project.top || b.name === S.project.name);
      this.chosen = (mine || this.bits[0]).path;
    }
  },

  // What the Board pane will program: this session's build wins, else the picked one.
  target_bit() { return bitPath() || this.chosen; },

  // Program never silently does nothing: if it cannot, it says which part is missing.
  async program(bit) {
    bit = bit || this.target_bit();
    const problems = [];
    if (!S.target || !S.target.open) problems.push("no target is open — pick usb or fake in the Board tab");
    if (!bit) problems.push("no bitstream — run Generate Bitstream, or pick one in the Board tab");
    if (problems.length) {
      for (const p of problems) logLine("error", p);
      dock.show("log");
      tabs.show("board");
      return;
    }
    try {
      const r = await api("/api/program", { bit, mode: "frames" });
      logLine(r.ok ? "info" : "error", `program ${bit}: ${r.message}`);
      await this.loadBits();
      await this.refresh();
      tabs.show("board");
      dock.show("log");
    } catch (e) {
      logLine("error", `program ${bit}: ${e.message || e}`);
      dock.show("log");
    }
  },

  async verify() {
    const bit = bitPath();
    if (!bit) return void logLine("error", "no bitstream to verify against");
    try {
      const r = await api("/api/readback", { bit });
      logLine(r.ok ? "info" : "error", `readback: ${r.message}`);
    } catch (e) { logLine("error", String(e.message || e)); }
    dock.show("log");
    tabs.show("board");
  },

  async capture() {
    try {
      const c = await api("/api/capture", {});
      S.capture = c.ok ? c : null;
      logLine(c.ok ? "info" : "error", `CAPTURE: ${c.message}`);
      this.render();
    } catch (e) { logLine("error", String(e.message || e)); dock.show("log"); }
    tabs.show("board");
  },

  async partial() {
    const bit = bitPath();
    if (!bit) return void logLine("error", "build a bitstream first");
    try {
      const r = await api("/api/partial", { bit });
      logLine(r.ok ? "info" : "error", `partial: ${r.message}`);
      await this.refresh();
    } catch (e) { logLine("error", String(e.message || e)); }
    dock.show("log");
  },

  async refresh() {
    // A poll can fail while the board is busy - the software one holds its lock
    // while it simulates guest clocks - and a busy board is not a missing one. Keep
    // what we last knew and say so, rather than reporting the target gone.
    try {
      S.target = await api("/api/board");
    } catch (e) {
      if (S.target && S.target.open) S.target = { ...S.target, stale: true };
      else S.target = { open: false, error: String(e.message || e) };
    }
    this.render();
    topbar();
    buttons();
  },

  render() {
    const t = S.target, v = $("boardview");
    v.innerHTML = "";
    const pill = $("boardpill");
    if (!t || !t.open) {
      pill.textContent = "no target"; pill.className = "pill";
      v.appendChild(this.controls());
      v.appendChild(el("div", "empty",
        "No target open. `usb` is the Pico on PMODA; `fake` is the board in software, "
        + "which needs no hardware. Building a design does not load it — Program does."));
      return;
    }
    pill.textContent = t.kind === "fake" ? "software board" : "Pico on PMODA";
    pill.className = "pill " + (t.match ? "ok" : "err");
    v.appendChild(this.controls());

    const box = el("div", null);
    box.style.cssText = "display:flex;gap:26px;flex-wrap:wrap;margin-top:12px;align-items:flex-start";

    // LEDs and switches, as the board has them
    const leds = el("div", null);
    leds.appendChild(el("div", "row", "")).remove();
    const lrow = el("div", null);
    lrow.style.cssText = "display:flex;gap:14px;align-items:center;margin-bottom:12px";
    const nled = 3;
    for (let i = nled - 1; i >= 0; i--) {
      const on = t.leds != null && ((t.leds >> i) & 1);
      const c = el("div", null);
      c.style.cssText = "text-align:center;font-family:var(--mono);font-size:10px;color:var(--mute)";
      const d = el("div", "led" + (on ? " on" : ""));
      d.style.cssText += ";width:16px;height:16px;margin:0 auto 4px";
      c.appendChild(d); c.appendChild(el("div", null, "LD" + i));
      lrow.appendChild(c);
    }
    const done = el("div", null);
    done.style.cssText = "text-align:center;font-family:var(--mono);font-size:10px;color:var(--mute)";
    const dd = el("div", "led" + (t.status && t.status.done ? " good" : ""));
    dd.style.cssText += ";width:16px;height:16px;margin:0 auto 4px";
    done.appendChild(dd); done.appendChild(el("div", null, "DONE"));
    lrow.appendChild(done);
    leds.appendChild(lrow);

    const sw = el("div", null);
    sw.style.cssText = "display:flex;gap:14px;align-items:center;font-family:var(--mono);font-size:11px;color:var(--ink-2)";
    sw.appendChild(el("span", null, `SW ${t.sw == null ? "—" : t.sw.toString(2).padStart(2, "0")}`));
    sw.appendChild(el("span", null, `BTN ${t.btn == null ? "—" : t.btn.toString(2).padStart(4, "0")}`));
    leds.appendChild(sw);
    box.appendChild(leds);

    // the numbers behind it
    const info = el("div", null);
    info.style.cssText = "min-width:240px";
    const add = (k, val) => {
      const r = el("div", "row");
      r.appendChild(el("span", null, k));
      r.appendChild(el("span", null, val == null ? "—" : String(val)));
      info.appendChild(r);
    };
    add("target", t.kind);
    add("IDCODE", t.idcode + (t.match ? " ✓" : " ✕ expected " + t.expected));
    if (t.status && !t.status.error) {
      add("DONE", t.status.done);
      for (const k of ["crc_error", "committed", "gwe", "gsr"]) if (k in t.status) add(k, t.status[k]);
    } else if (t.status) {
      add("status", t.status.error.slice(0, 60));
    }
    if (t.simulated) {
      add("guest clocks", t.clocks);
      if (t.skipped) add("clocks skipped", t.skipped);
      if (t.edge_ms) add("ms per guest clock", t.edge_ms);
    }
    box.appendChild(info);
    v.appendChild(box);

    // CAPTURE, as a small logic analyser over the fabric's own registers
    if (S.capture) {
      const cap = el("div", null);
      cap.style.cssText = "margin-top:18px";
      const h = el("div", null, `CAPTURE — ${S.capture.ones} of ${S.capture.nclb} element outputs set`);
      h.style.cssText = "font-size:12px;color:var(--ink-2);margin-bottom:6px";
      cap.appendChild(h);
      const g = el("div", null);
      g.style.cssText = "display:flex;flex-wrap:wrap;gap:2px;max-width:560px";
      S.capture.bits.forEach((b, i) => {
        const c = el("div", null);
        c.style.cssText = `width:12px;height:12px;border-radius:2px;border:1px solid var(--rule);`
          + `background:${b ? "var(--accent)" : "var(--rule-2)"}`;
        c.title = `CLB register ${i} = ${b}`;
        g.appendChild(c);
      });
      cap.appendChild(g);
      v.appendChild(cap);
    }

    if (t.simulated && t.skipped) {
      const note = el("div", "empty",
        "This is the board in software: one guest clock costs a model.settle() over "
        + `${S.device ? S.device.muxes : "the"} routing muxes, so it runs behind the rate the design asks for `
        + `(${t.skipped.toLocaleString()} edges skipped). The real board does not.`);
      note.style.maxWidth = "620px";
      v.appendChild(note);
    }
  },

  // Target choice and the bitstream to program, as controls rather than a prompt.
  controls() {
    const wrap = el("div", null);
    wrap.style.cssText = "display:flex;gap:10px;align-items:center;flex-wrap:wrap;"
      + "margin:12px 0 4px;padding-bottom:12px;border-bottom:1px solid var(--rule)";

    wrap.appendChild(el("span", null, "target"));
    for (const kind of ["usb", "fake"]) {
      const on = S.target && S.target.open && S.target.kind === kind;
      const b = el("button", "go" + (on ? "" : " sec"), kind === "usb" ? "Pico (usb)" : "software (fake)");
      b.style.cssText = "margin:0;width:auto;padding:4px 12px";
      b.onclick = () => this.open(kind);
      wrap.appendChild(b);
    }

    const sep = el("span", null, "bitstream");
    sep.style.marginLeft = "10px";
    wrap.appendChild(sep);

    const sel = document.createElement("select");
    sel.style.cssText = "font:inherit;font-size:11.5px;padding:3px 5px;max-width:260px;"
      + "background:var(--paper);color:var(--ink);border:1px solid var(--rule);border-radius:4px";
    const session = bitPath();
    if (session) {
      const o = document.createElement("option");
      o.value = session; o.textContent = session.split("/").pop() + "  (just built)";
      sel.appendChild(o);
    }
    for (const b of this.bits) {
      if (b.path === session) continue;
      const o = document.createElement("option");
      o.value = b.path;
      o.textContent = b.name + (b.top && b.top !== b.name ? `  (${b.top})` : "")
        + (b.clock === "run" ? "  · free-running" : "");
      sel.appendChild(o);
    }
    if (!sel.childElementCount) {
      const o = document.createElement("option");
      o.value = ""; o.textContent = "nothing built yet";
      sel.appendChild(o);
    }
    sel.value = this.target_bit() || "";
    sel.onchange = () => { this.chosen = sel.value; this.render(); };
    wrap.appendChild(sel);

    const go = el("button", "go", "Program");
    go.style.cssText = "margin:0;width:auto;padding:4px 16px";
    go.onclick = () => this.program(sel.value);
    wrap.appendChild(go);

    const b = this.bits.find((x) => x.path === sel.value);
    if (b && b.sources) {
      const src = el("span", "pill", b.sources.join(", "));
      src.title = `top ${b.top} · clock ${b.clock}` + (b.pcf ? ` · ${b.pcf}` : "");
      wrap.appendChild(src);
    }
    return wrap;
  },

  watch(on) {
    if (this.poll) { clearInterval(this.poll); this.poll = null; }
    if (on) this.poll = setInterval(() => this.refresh(), 900);
  },
};
