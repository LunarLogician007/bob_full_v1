// ── tabs, sources, settings, and boot ─────────────────────────────────────

const TABS = [
  ["start", "Start"], ["project", "Project"], ["bd", "Block Design"],
  ["editor", "Source"], ["device", "Device"], ["bitstream", "Bitstream"],
  ["pins", "Pins"], ["board", "Board"], ["wave", "Waveform"], ["sources", "Sources"], ["settings", "Settings"],
];

const tabs = {
  which: "editor",
  render() {
    const t = $("tabs");
    t.innerHTML = "";
    for (const [k, label] of TABS) {
      const b = el("div", "tab" + (this.which === k ? " on" : ""));
      b.textContent = (k === "editor" && S.open ? S.open.split("/").pop() : label)
        + (k === "editor" && S.dirty ? " •" : "");
      b.onclick = () => this.show(k);
      t.appendChild(b);
    }
  },
  show(k) {
    this.which = k;
    for (const [n] of TABS) $("pane-" + n).classList.toggle("on", n === k);
    this.render();
    if (k === "device") device.render();
    if (k === "board") board.loadBits().then(() => board.refresh());
    if (k === "sources") sources.render();
    if (k === "pins") pinplan.load();
    if (k === "bitstream") bitstream.load();
    if (k === "settings") settings.render();
    if (k === "project") project.render();
    if (k === "bd") bd.render();
    if (k === "wave") wavev.load();
    if (k === "start") start.render();
  },
};

const sources = {
  files: [],

  async open(path, top) {
    const r = await api("/api/source?path=" + encodeURIComponent(path));
    const base = path.split("/").pop().replace(/\.[^.]+$/, "");
    S.project = { ...S.project, files: [path], top: top || base, name: null, pcf: null };
    editor.set(path, r.text);
    S.dirty = false;
    pinplan.assign = {};                          // pins belong to a design, not the app
    flow.reset();
    tabs.show("editor");
    props.render();
    logLine("info", `opened ${path}`);
  },

  pick(name) {                                   // by example name, kept for the API
    const ex = S.examples.find((e) => e.name === name);
    return ex ? this.open(ex.path, name) : Promise.resolve();
  },

  async save() {
    if (!S.open) return;
    try {
      const r = await api("/api/save", { path: S.open, text: editor.get() });
      S.dirty = false;
      logLine("info", `saved ${r.path}`);
      tabs.render();
      await this.load();
    } catch (e) {
      logLine("error", String(e.message || e)); dock.show("log");
    }
  },

  async create() {
    const name = window.prompt("New design name (letters, digits, _ or -)", "mydesign");
    if (!name) return;
    try {
      const r = await api("/api/new", { name: name.trim() });
      await this.load();
      await this.open(r.path, name.trim());
      logLine("info", `created ${r.path}`);
    } catch (e) {
      logLine("error", String(e.message || e)); dock.show("log");
    }
  },

  async openPrompt() {
    const path = window.prompt("Open a path inside the repo", S.open || "work/");
    if (!path) return;
    try { await this.open(path.trim()); }
    catch (e) { logLine("error", String(e.message || e)); dock.show("log"); }
  },

  async load() {
    try { const b = await api("/api/browse"); this.files = b.files; this.dir = b.designs_dir; }
    catch (e) { this.files = []; }
    if (tabs.which === "sources") this.render();
  },

  card(f) {
    const c = el("div", null);
    const mine = S.project.files.includes(f.path);
    c.style.cssText = "border:1px solid " + (mine ? "var(--accent)" : "var(--rule)")
      + ";border-radius:6px;padding:9px 11px;cursor:pointer;background:"
      + (mine ? "var(--accent-bg)" : "transparent");
    c.onclick = () => this.open(f.path);
    const h = el("div", null, f.name);
    h.style.cssText = "font-weight:580;margin-bottom:3px";
    c.appendChild(h);
    const ex = S.examples.find((e) => e.path === f.path);
    const sub = f.type === "v" || f.type === "sv"
      ? `${f.lines} lines` + (ex ? ` · ${ex.routed ? "routed, wirelength " + ex.wirelength : "not routed yet"}` : "")
      : `${f.type} · ${f.lines} lines`;
    const s = el("div", null, sub);
    s.style.cssText = "font-family:var(--mono);font-size:10.5px;color:var(--mute)";
    c.appendChild(s);
    const p = el("div", null, f.path);
    p.style.cssText = "font-family:var(--mono);font-size:9.5px;color:var(--faint);margin-top:2px";
    c.appendChild(p);
    return c;
  },

  render() {
    const v = $("srcview");
    v.innerHTML = "";

    const bar = el("div", null);
    bar.style.cssText = "display:flex;gap:8px;margin:10px 0 4px;align-items:center;flex-wrap:wrap";
    const btn = (label, fn, sec) => {
      const b = el("button", "go" + (sec ? " sec" : ""), label);
      b.style.cssText = "margin:0;width:auto;padding:5px 13px";
      b.onclick = fn;
      bar.appendChild(b);
      return b;
    };
    btn("New design", () => this.create());
    btn("Open path…", () => this.openPrompt(), true);
    const sv = btn("Save", () => this.save(), true);
    sv.disabled = !S.open;
    if (S.open) bar.appendChild(el("span", "pill" + (S.dirty ? "" : " ok"),
      S.open + (S.dirty ? " · unsaved" : " · saved")));
    v.appendChild(bar);

    const note = el("div", "empty",
      `Your own work goes in ${this.dir || "work/"} — New design scaffolds one from a `
      + "template. Anything inside the repo can be opened by path. ⌘S / Ctrl-S saves.");
    note.style.cssText += ";max-width:760px;padding:6px 0 4px";
    v.appendChild(note);

    for (const [kind, title] of [["design", "Your designs"], ["example", "Examples"]]) {
      const group = this.files.filter((f) => f.kind === kind);
      if (!group.length) continue;
      const h = el("div", null, title);
      h.style.cssText = "font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;"
        + "color:var(--mute);font-weight:600;margin:14px 0 6px";
      v.appendChild(h);
      const t = el("div", null);
      t.style.cssText = "display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px";
      for (const f of group) t.appendChild(this.card(f));
      v.appendChild(t);
    }
  },
};

const settings = {
  render() {
    const v = $("setview");
    v.innerHTML = "";
    const d = S.device;
    const p = el("div", "empty");
    p.style.maxWidth = "680px";
    p.innerHTML = d
      ? `Every number on the right comes from <code>software/bob/device.json</code>, which
         <code>software/bob/device.py</code> generates along with the fabric RTL, the VPR
         architecture, the FASM map and the host tools. studio never writes it: to change the
         device, edit <code>device.py</code> and run <code>make rrgraph</code>, then
         <code>make device</code>.<br><br>
         This device is <b>${d.name}</b>: ${d.capacity.clb} CLBs, ${d.capacity.bram} BRAM,
         ${d.capacity.dsp} DSP, ${d.pads} pads, channel width ${d.chan_width},
         ${d.muxes} routing muxes, ${d.chain_w} configuration bits in ${d.frames} frames.
         The free-running guest clock tops out at
         ${(d.clock.sysclk_hz / Math.pow(2, d.clock.div_min_shift) / 1000).toFixed(0)} kHz
         (125 MHz / 2<sup>${d.clock.div_min_shift}</sup>), which is what makes the fabric's
         timing exception honest.`
      : "loading…";
    v.appendChild(p);
  },
};

function topbar() {
  const d = S.device, t = S.target;
  if (d) $("devmeta").textContent =
    `${d.name} · ${d.capacity.clb} CLB · ${d.chain_w} bits · ${d.frames} frames`;
  const led = $("tgtled"), txt = $("tgttxt");
  if (!t || !t.open) { led.className = "led"; txt.textContent = "no target"; return; }
  led.className = "led " + (t.stale ? "" : t.match ? "good" : "bad");
  txt.textContent = (t.kind === "fake" ? "software board" : "Pico") + " " + t.idcode
    + (t.stale ? " (busy)" : "");
}

async function boot() {
  editor.wire();
  wavev.wire();
  tabs.render();
  dock.render();

  $("runsynth").onclick = () => flow.run(null);
  $("runimpl").onclick = () => flow.run("device");
  $("runbit").onclick = () => flow.run(null);
  $("opentgt").onclick = () => tabs.show("board");
  $("newproj").onclick = () => project.newWizard();
  $("openproj").onclick = () => project.openDialog();
  $("program").onclick = () => board.program();
  $("buildprog").onclick = () => buildAndProgram();
  $("partial").onclick = () => board.partial();
  $("readback").onclick = () => board.verify();
  $("capture").onclick = () => board.capture();
  $("refresh").onclick = () => board.refresh();
  $("autopoll").onchange = (e) => board.watch(e.target.checked);
  $("shownets").onchange = () => device.render();
  $("showids").onchange = () => device.render();
  for (const n of document.querySelectorAll(".item[data-go]"))
    n.onclick = () => tabs.show(n.dataset.go);
  for (const n of document.querySelectorAll(".item[data-stage]"))
    n.onclick = () => dock.show("stages");
  // ⌘S / Ctrl-S saves the editor, as it does everywhere else
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {     // build; with shift, and program
      e.preventDefault();
      if (e.shiftKey) buildAndProgram(); else flow.run(null);
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      if (tabs.which === "bd") bd.save().catch((x) => logLine("error", x.message));
      else sources.save();
    }
  });
  $("btheme").onclick = () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const next = cur === "dark" ? "light" : cur === "light" ? "dark"
      : (matchMedia("(prefers-color-scheme: dark)").matches ? "light" : "dark");
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("bob-studio-theme", next); } catch (e) { /* private window */ }
    device.render();
  };
  try {
    const th = localStorage.getItem("bob-studio-theme");
    if (th) document.documentElement.setAttribute("data-theme", th);
  } catch (e) { /* private window: the media query decides */ }

  try {
    S.device = await api("/api/device");
    S.examples = await api("/api/examples");
    await sources.load();
    await project.load();
    topbar(); props.render(); device.render(); settings.render();
    logLine("info", `${S.device.name}: ${S.device.capacity.clb} CLBs, ${S.device.frames} frames`);
    if (S.proj) tabs.show("project");      // the backend kept a project open across a reload
    else { await sources.pick("counter"); tabs.show("start"); }   // first look: the Start page
    await board.loadBits();
    await board.refresh();
  } catch (e) {
    logLine("error", "cannot reach the backend: " + (e.message || e));
    dock.show("log");
  }
  buttons();
}

document.addEventListener("DOMContentLoaded", boot);
