// ── the Start page (software UX pass) ─────────────────────────────────────
// What someone opening bob studio for the first time needs on one screen: what the flow
// is, an example to try in one click, their own design (new, open, recent), whether the
// tools are there (./bob doctor, via /api/doctor) and the keys. The page opens here
// unless a project was already open.

const start = {
  doctor: null,

  async render() {
    const v = $("startview");
    v.innerHTML = "";
    const d = S.device;
    v.appendChild(el("h1", null, "bob studio"));
    v.appendChild(el("p", "lede",
      `An FPGA built inside the PYNQ-Z2's FPGA${d ? `: ${d.capacity.clb} CLBs, ${d.capacity.clb * 4} six-input LUTs, `
        + `${d.capacity.bram} block RAMs and ${d.capacity.dsp} DSP slices` : ""}. Write Verilog, press Build & Program, `
        + "and it runs on the board, or on the board in software when none is plugged in."));

    v.appendChild(el("h2", null, "How a design gets onto bob"));
    const steps = el("div", "steps");
    for (const [t, what, tool] of [
      ["1  Write", "Verilog with ports clk, sw, btn, led: those reach the board with no pin file.", "Source"],
      ["2  Synthesis", "yosys turns it into bob's LUTs, flip-flops, adders, BRAM and DSP, then proves it unchanged.", "Run Synthesis"],
      ["3  Place & Route", "VPR (or bob's own router) picks a CLB for each part and wires them.", "Device view"],
      ["4  Bitstream", `The routing becomes ${d ? d.chain_w.toLocaleString("en") : "the"} configuration bits`
        + `${d ? ` in ${d.frames} frames` : ""}, checked against a model.`, ".bit"],
      ["5  Program", "Frames go over JTAG into bob; the LEDs show the design running.", "Board"],
    ]) {
      const s = el("div");
      s.appendChild(el("b", null, t));
      s.appendChild(document.createTextNode(what + " "));
      s.appendChild(el("i", null, tool));
      steps.appendChild(s);
    }
    v.appendChild(steps);

    const cols = el("div", "cols");
    const left = el("div"), right = el("div");
    cols.appendChild(left); cols.appendChild(right);
    v.appendChild(cols);

    left.appendChild(el("h2", null, "Try an example"));
    const list = el("div", "exlist");
    for (const ex of S.examples || []) {
      const r = el("div", "ex");
      r.appendChild(el("span", "nm", ex.name));
      r.appendChild(el("span", "ds", ex.desc || ""));
      const bt = el("span", "bt");
      const o = el("button", "sbtn", "Open");
      o.title = `open ${ex.path} in the editor`;
      o.onclick = () => this.example(ex, false);
      const g = el("button", "sbtn pri", "Build & Program");
      g.title = "open it, run the whole flow and program the target";
      g.onclick = () => this.example(ex, true);
      bt.appendChild(o); bt.appendChild(g);
      r.appendChild(bt);
      list.appendChild(r);
    }
    left.appendChild(list);

    right.appendChild(el("h2", null, "Your own design"));
    const own = el("div", "card");
    own.appendChild(el("p", null, "A project is a folder with your sources, pins and outputs. "
      + "New Project starts one; the Project Manager adds files and picks the top module."));
    const row = el("div", "row2");
    const nb = el("button", "sbtn pri", "New Project…"); nb.onclick = () => project.newWizard();
    const ob = el("button", "sbtn", "Open Project…"); ob.onclick = () => project.openDialog();
    row.appendChild(nb); row.appendChild(ob);
    own.appendChild(row);
    if (S.recent && S.recent.length) {
      const rc = el("div", "recent");
      rc.style.marginTop = "10px";
      rc.appendChild(el("div", null, "Recent")).style.cssText = "color:var(--mute);font-size:11px;margin-bottom:2px";
      for (const p of S.recent.slice(0, 5)) {
        const a = el("a", null, p.split("/").slice(-2).join("/"));
        a.title = p;
        a.onclick = () => project.open(p);
        rc.appendChild(a);
      }
      own.appendChild(rc);
    }
    right.appendChild(own);

    right.appendChild(el("h2", null, "Setup"));
    const doc = el("div", "card");
    doc.appendChild(el("div", "empty", "checking the tools…")).style.padding = "0";
    right.appendChild(doc);
    this.fillDoctor(doc);

    right.appendChild(el("h2", null, "Keys"));
    const k = el("div", "card keys");
    k.innerHTML = "<kbd>⌘/Ctrl</kbd> <kbd>Enter</kbd> build &nbsp;·&nbsp; "
      + "<kbd>⌘/Ctrl</kbd> <kbd>⇧</kbd> <kbd>Enter</kbd> build &amp; program<br>"
      + "<kbd>⌘/Ctrl</kbd> <kbd>S</kbd> save &nbsp;·&nbsp; click a message to jump to its line";
    right.appendChild(k);
  },

  async fillDoctor(box) {
    try {
      if (!this.doctor) this.doctor = await api("/api/doctor");
    } catch (e) {
      box.innerHTML = "";
      box.appendChild(el("p", null, "setup check unavailable: " + (e.message || e)));
      return;
    }
    box.innerHTML = "";
    for (const r of this.doctor) {
      const row = el("div", "doc");
      row.appendChild(el("span", "m " + (r.ok ? "ok" : r.ok === false ? "bad" : "opt"),
        r.ok ? "ok" : r.ok === false ? "fail" : "--"));
      row.appendChild(el("span", null, r.what));
      row.appendChild(el("span", "d", r.detail));
      if (!r.ok && r.fix) row.appendChild(el("span", "fx", "→ " + r.fix));
      box.appendChild(row);
    }
    const t = S.target;
    const tr = el("div", "doc");
    tr.appendChild(el("span", "m " + (t && t.open ? (t.match ? "ok" : "bad") : "opt"),
      t && t.open ? (t.match ? "ok" : "fail") : "--"));
    tr.appendChild(el("span", null, "target"));
    tr.appendChild(el("span", "d", t && t.open
      ? `${t.kind === "fake" ? "software board" : "Pico"} ${t.idcode}${t.match ? "" : " (not bob's IDCODE)"}`
      : "none open: Build & Program uses the software board"));
    box.appendChild(tr);
  },

  // an example: a project that is open would win every build, so close it first
  async example(ex, go) {
    if (S.proj) {
      try { await project.post("close"); } catch (e) { logLine("error", String(e.message || e)); }
    }
    await sources.open(ex.path, ex.name);
    if (go) await buildAndProgram();
  },
};

// Build & Program: the whole flow, then the target. With no target open it uses the
// software board and says so - the step someone new is most likely to miss.
async function buildAndProgram() {
  if (S.busy) return;
  const ok = await flow.run(null);
  if (!ok) return;
  if (!S.target || !S.target.open) {
    logLine("info", "no target open: programming the software board (pick usb in the Board tab for the PYNQ-Z2)");
    try { await api("/api/target", { kind: "fake" }); await board.refresh(); } catch (e) {
      logLine("error", "cannot open the software board: " + (e.message || e));
      dock.show("log");
      return;
    }
  }
  await board.program();
}
