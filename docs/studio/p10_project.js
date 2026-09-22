// ── projects: New Project, Open Project, the Project Manager (M18) ───────────────
// A project is a folder anywhere on disk with a .bobproj file in it; software/bob/project.py
// owns it and the backend keeps one open. The page never edits the project file itself:
// every change is a POST that comes back with the project as it now is.

S.proj = null;                   // /api/project -> project, or null when working on loose files
S.recent = [];

// A modal dialog. body(box) fills it; buttons are [label, fn, secondary]. fn returning
// false keeps the dialog open (a refused name, say).
function dialog(title, body, buttons) {
  const m = el("div", "modal"), d = el("div", "dlg");
  d.appendChild(el("h2", null, title));
  const bd = el("div", "bd"), ft = el("div", "ft");
  d.appendChild(bd); d.appendChild(ft); m.appendChild(d);
  const close = () => m.remove();
  const err = el("div", null);
  err.style.cssText = "color:var(--err);font-size:11.5px;margin-top:8px;font-family:var(--mono)";
  body(bd, close);
  bd.appendChild(err);
  for (const [label, fn, sec] of buttons) {
    const b = el("button", "go" + (sec ? " sec" : ""), label);
    b.onclick = async () => {
      if (!fn) return close();
      try { err.textContent = ""; if ((await fn()) !== false) close(); }
      catch (e) { err.textContent = String(e.message || e); }
    };
    ft.appendChild(b);
  }
  m.onclick = (e) => { if (e.target === m) close(); };
  document.body.appendChild(m);
  const first = d.querySelector("input");
  if (first) first.focus();
  return { close, err };
}

// A folder browser over /api/fs. mode "folder" picks the folder shown; mode "files" picks
// files matching exts (several, with multi). onPick(paths) returns when the pick is done.
function fsBrowser(box, { mode, exts, multi, start, onChange }) {
  const st = { path: start || "", picked: [] };
  const where = el("input"); where.type = "text";
  const list = el("div", "fsl");
  box.appendChild(where); box.appendChild(list);
  const go = async (p) => {
    const r = await api("/api/fs?path=" + encodeURIComponent(p || ""));
    st.path = r.path; where.value = r.path; list.innerHTML = "";
    const row = (ic, label, cls, fn, dbl) => {
      const d = el("div", cls || null);
      d.appendChild(el("span", "ic", ic)); d.appendChild(el("span", null, label));
      d.onclick = fn; if (dbl) d.ondblclick = dbl;
      list.appendChild(d);
      return d;
    };
    if (r.parent) row("↑", "..", null, () => go(r.parent));
    for (const q of [["⌂", "home", r.home], ["◆", "bob repo", r.repo]])
      if (q[2] !== r.path) row(q[0], q[1], null, () => go(q[2]));
    for (const d of r.dirs) row(d.project ? "▣" : "▸", d.name + "/", null, () => go(d.path));
    for (const f of r.files) {
      if (mode !== "files" || !exts.some((x) => f.name.endsWith(x))) {
        if (mode === "folder" && f.name.endsWith(".bobproj")) row("▣", f.name, null, () => {});
        continue;
      }
      const d = row("·", f.name, st.picked.includes(f.path) ? "sel" : null, () => {
        if (st.picked.includes(f.path)) st.picked = st.picked.filter((x) => x !== f.path);
        else st.picked = multi ? st.picked.concat([f.path]) : [f.path];
        d.classList.toggle("sel", st.picked.includes(f.path));
        if (!multi) for (const o of list.children) if (o !== d) o.classList.remove("sel");
        onChange && onChange(st);
      });
    }
    onChange && onChange(st);
  };
  where.onkeydown = (e) => { if (e.key === "Enter") go(where.value).catch((x) => logLine("error", x.message)); };
  go(start).catch(() => go(""));
  return st;
}

const project = {
  async load() {
    try {
      const r = await api("/api/project");
      this.apply(r);
    } catch (e) { logLine("error", String(e.message || e)); }
  },

  apply(r) {
    S.proj = r.project;
    S.recent = r.recent || [];
    $("projname").textContent = S.proj ? S.proj.name : "";
    if (S.proj) S.project = { ...S.project, top: S.proj.top, name: S.proj.name };
    if (tabs.which === "project") this.render();
    props.render();
    buttons();
  },

  async post(action, body) {
    const r = await api("/api/project/" + action, body || {});
    this.apply(r);
    return r;
  },

  // ── New Project: name and location, then sources, constraints and the top ──
  newWizard() {
    let step = 0;
    const st = { name: "", location: "", sources: [], pcfs: [] };
    const titles = ["Project name and location", "Add sources", "Add constraints", "Top module"];
    const m = el("div", "modal"), d = el("div", "dlg");
    const h = el("h2"), bd = el("div", "bd"), ft = el("div", "ft");
    d.appendChild(h); d.appendChild(bd); d.appendChild(ft); m.appendChild(d);
    document.body.appendChild(m);
    const err = el("div");
    err.style.cssText = "color:var(--err);font-size:11.5px;margin-top:8px;font-family:var(--mono)";

    const draw = () => {
      h.textContent = `New Project — ${titles[step]}`;
      bd.innerHTML = ""; ft.innerHTML = ""; err.textContent = "";
      const steps = el("div", "steps");
      titles.forEach((t, i) => { steps.appendChild(i === step ? el("b", null, `${i + 1}. ${t}`) : el("span", null, `${i + 1}. ${t}`)); });
      bd.appendChild(steps);
      if (step === 0) {
        bd.appendChild(el("label", "f", "Project name (a Verilog identifier: letters, digits, _)"));
        const n = el("input"); n.type = "text"; n.value = st.name || "project_1";
        n.oninput = () => { st.name = n.value.trim(); where.textContent = `${st.location}/${st.name}/${st.name}.bobproj`; };
        bd.appendChild(n);
        bd.appendChild(el("label", "f", "Location — the project folder is made inside it"));
        const where = el("div", "pill");
        where.style.cssText += ";display:inline-block;margin:6px 0 0";
        fsBrowser(bd, { mode: "folder", start: st.location || "", onChange: (s) => {
          st.location = s.path; where.textContent = `${st.location}/${n.value.trim()}/${n.value.trim()}.bobproj`;
        } });
        bd.appendChild(where);
        st.name = n.value.trim();
        setTimeout(() => n.focus(), 0);
      } else if (step === 1 || step === 2) {
        const pcf = step === 2;
        bd.appendChild(el("div", "empty", pcf
          ? "Pin files (.pcf) say which port bit goes to which pin. Skip this if your top uses "
            + "clk, sw[1:0], btn[3:0], led[2:0] — or let a block design write one. Files are copied into constrs/."
          : "Pick Verilog files to copy into src/. You can also skip this, then make a block "
            + "design or a new file from the Project Manager."));
        const chosen = el("div", "pill");
        chosen.style.cssText += ";display:inline-block;margin-top:8px";
        const key = pcf ? "pcfs" : "sources";
        fsBrowser(bd, { mode: "files", exts: pcf ? [".pcf"] : [".v", ".sv", ".vh"], multi: true,
          start: st.lastDir || "", onChange: (s) => {
            st.lastDir = s.path;
            st["pick_" + key] = s.picked;
            chosen.textContent = `${(st[key].length + s.picked.length)} file(s) chosen`;
          } });
        bd.appendChild(chosen);
      } else {
        bd.appendChild(el("div", "empty", "The project is made. Choose the top module now, "
          + "or later from the Project Manager (right-click → Set as top)."));
        const mods = (S.proj && S.proj.modules) || [];
        if (S.proj && S.proj.modules_error) bd.appendChild(el("div", "er", S.proj.modules_error));
        const list = el("div", "fsl");
        if (!mods.length) list.appendChild(el("div", null, "(no modules yet)"));
        for (const mo of mods) {
          const r = el("div", S.proj.top === mo.name ? "sel" : null);
          r.appendChild(el("span", "ic", "▭"));
          r.appendChild(el("span", null, `${mo.name}   (${mo.ports.length} ports)`));
          r.onclick = async () => { try { await project.post("top", { module: mo.name }); draw(); } catch (e) { err.textContent = e.message; } };
          list.appendChild(r);
        }
        bd.appendChild(list);
      }
      bd.appendChild(err);

      const btn = (label, fn, sec) => {
        const b = el("button", "go" + (sec ? " sec" : ""), label);
        b.onclick = async () => { try { err.textContent = ""; await fn(); } catch (e) { err.textContent = String(e.message || e); } };
        ft.appendChild(b);
      };
      if (step < 3) btn("Cancel", async () => m.remove(), true);
      if (step === 0) btn("Create project", async () => {
        await project.post("new", { location: st.location, name: st.name });
        logLine("info", `created ${S.proj.path}`);
        step = 1; draw();
      });
      if (step === 1 || step === 2) {
        const key = step === 2 ? "pcfs" : "sources";
        btn("Skip", async () => { step += 1; draw(); }, true);
        btn("Add and continue", async () => {
          for (const f of st["pick_" + key] || []) await project.post("add", { path: f, copy: true });
          st[key] = st[key].concat(st["pick_" + key] || []);
          step += 1; draw();
        });
      }
      if (step === 3) btn("Finish", async () => { m.remove(); tabs.show("project"); });
    };
    draw();
  },

  openDialog() {
    let picked = null;
    dialog("Open Project", (box) => {
      if (S.recent.length) {
        box.appendChild(el("label", "f", "Recent"));
        const r = el("div", "fsl");
        for (const p of S.recent) {
          const d = el("div"); d.appendChild(el("span", "ic", "▣")); d.appendChild(el("span", null, p));
          d.onclick = () => { picked = p; for (const o of r.children) o.classList.toggle("sel", o === d); };
          d.ondblclick = () => this.open(p).then(() => document.querySelector(".modal").remove());
          r.appendChild(d);
        }
        box.appendChild(r);
      }
      box.appendChild(el("label", "f", "Or browse to a .bobproj"));
      fsBrowser(box, { mode: "files", exts: [".bobproj"], multi: false, start: "",
        onChange: (s) => { if (s.picked.length) picked = s.picked[0]; } });
    }, [["Cancel", null, true], ["Open", async () => {
      if (!picked) throw new Error("pick a project first");
      await this.open(picked);
    }]]);
  },

  async open(path) {
    await this.post("open", { path });
    logLine("info", `opened ${S.proj.path}`);
    flow.reset();
    tabs.show("project");
    if (S.proj.block_designs.length && typeof bd !== "undefined") bd.forget();
  },

  addDialog(kind) {
    const pcf = kind === "pcf";
    let picked = [];
    let copy = true;
    dialog(pcf ? "Add constraints" : "Add sources", (box) => {
      fsBrowser(box, { mode: "files", exts: pcf ? [".pcf"] : [".v", ".sv", ".vh"], multi: true,
        start: S.proj ? S.proj.dir : "", onChange: (s) => { picked = s.picked; } });
      const l = el("label", "sw");
      const c = el("input"); c.type = "checkbox"; c.checked = true; c.onchange = () => { copy = c.checked; };
      l.appendChild(c); l.appendChild(document.createTextNode(" copy into the project folder"));
      l.style.marginTop = "10px";
      box.appendChild(l);
    }, [["Cancel", null, true], ["Add", async () => {
      if (!picked.length) throw new Error("pick at least one file");
      for (const f of picked) await this.post("add", { path: f, copy });
      logLine("info", `added ${picked.length} file(s)`);
    }]]);
  },

  createDialog() {
    let name = "";
    dialog("Create a source file", (box) => {
      box.appendChild(el("label", "f", "Module / file name (src/<name>.v)"));
      const n = el("input"); n.type = "text"; n.value = "my_module"; name = n.value;
      n.oninput = () => { name = n.value.trim(); };
      box.appendChild(n);
    }, [["Cancel", null, true], ["Create", async () => {
      await this.post("create", { name });
      const f = S.proj.files.sources.find((x) => x.rel === `src/${name}.v`);
      if (f) await this.edit(f.path);
    }]]);
  },

  newBdDialog() {
    let name = "";
    dialog("Create Block Design", (box) => {
      box.appendChild(el("label", "f", "Design name (bd/<name>.bd; the wrapper will be <name>_wrapper)"));
      const n = el("input"); n.type = "text"; n.value = (S.proj ? S.proj.name : "design") + "_bd"; name = n.value;
      n.oninput = () => { name = n.value.trim(); };
      box.appendChild(n);
    }, [["Cancel", null, true], ["Create", async () => {
      const r = await api("/api/bd/new", { name });
      this.apply(r);
      await bd.open(r.rel);
    }]]);
  },

  async edit(path) {
    const r = await api("/api/source?path=" + encodeURIComponent(path));
    editor.set(path, r.text);
    S.dirty = false;
    tabs.show("editor");
  },

  menu(ev, items) {
    ev.preventDefault();
    for (const o of document.querySelectorAll(".ctx")) o.remove();
    const c = el("div", "ctx");
    c.style.left = ev.clientX + "px"; c.style.top = ev.clientY + "px";
    for (const [label, fn] of items) {
      const d = el("div", null, label);
      d.onclick = async () => { c.remove(); try { await fn(); } catch (e) { logLine("error", e.message); dock.show("log"); } };
      c.appendChild(d);
    }
    document.body.appendChild(c);
    setTimeout(() => document.addEventListener("click", () => c.remove(), { once: true }), 0);
  },

  render() {
    const v = $("projview");
    v.innerHTML = "";
    const p = S.proj;
    const bar = el("div");
    bar.style.cssText = "display:flex;gap:8px;margin:4px 0 8px;flex-wrap:wrap;align-items:center";
    const btn = (label, fn, sec, dis) => {
      const b = el("button", "go" + (sec ? " sec" : ""), label);
      b.style.cssText = "margin:0;width:auto;padding:5px 12px";
      b.disabled = !!dis;
      b.onclick = () => { try { const r = fn(); if (r && r.catch) r.catch((e) => { logLine("error", e.message); dock.show("log"); }); } catch (e) { logLine("error", e.message); } };
      bar.appendChild(b);
    };
    btn("New Project…", () => this.newWizard());
    btn("Open Project…", () => this.openDialog(), true);
    if (p) {
      btn("Add sources…", () => this.addDialog("src"), true);
      btn("Create file…", () => this.createDialog(), true);
      btn("Add constraints…", () => this.addDialog("pcf"), true);
      btn("Create Block Design…", () => this.newBdDialog(), true);
      btn("Close project", () => this.post("close").then(() => { flow.reset(); }), true);
    }
    v.appendChild(bar);
    $("projtitle").textContent = p ? `Project Manager — ${p.name}` : "Project Manager";
    if (!p) {
      const e = el("div", "empty");
      e.style.maxWidth = "720px";
      e.innerHTML = "No project is open, so the flow builds the file in the editor, as before. "
        + "<b>New Project</b> makes a folder anywhere on disk holding <code>src/</code>, "
        + "<code>bd/</code>, <code>ip/</code>, <code>constrs/</code>, <code>build/</code> and a "
        + "<code>.bobproj</code> file; <b>Open Project</b> brings it back later.";
      v.appendChild(e);
      if (S.recent.length) {
        const t = el("div", "tree");
        t.appendChild(el("h4", null, "Recent projects"));
        for (const r of S.recent) {
          const d = el("div", "ti");
          d.appendChild(el("span", "nm", r.split("/").pop()));
          d.appendChild(el("span", "sub", r));
          d.onclick = () => this.open(r).catch((x) => logLine("error", x.message));
          t.appendChild(d);
        }
        v.appendChild(t);
      }
      return;
    }

    const t = el("div", "tree");
    const info = el("div", "sub");
    info.style.cssText = "font-family:var(--mono);font-size:10.5px;color:var(--faint)";
    info.textContent = p.path;
    t.appendChild(info);

    const topFile = (p.modules || []).find((m) => m.name === p.top);
    const item = (f, extra, menuItems, onOpen) => {
      const d = el("div", "ti" + (f.exists ? "" : " miss") + (extra.top ? " top" : ""));
      d.appendChild(el("span", "nm", f.rel.split("/").pop()));
      d.appendChild(el("span", "sub", (extra.sub || "") + "  " + f.rel));
      const acts = el("span", "acts");
      for (const [label, fn] of menuItems.slice(0, 2)) {
        const a = el("a", null, label);
        a.onclick = (e) => { e.stopPropagation(); Promise.resolve(fn()).catch((x) => { logLine("error", x.message); dock.show("log"); }); };
        acts.appendChild(a);
      }
      d.appendChild(acts);
      d.onclick = () => onOpen && Promise.resolve(onOpen()).catch((x) => logLine("error", x.message));
      d.oncontextmenu = (e) => this.menu(e, menuItems);
      t.appendChild(d);
    };

    t.appendChild(el("h4", null, `Design Sources (${p.files.sources.length})`
      + (p.top ? ` — top: ${p.top}` : " — no top set")));
    if (p.modules_error) { const e = el("div", "er", p.modules_error); e.style.cssText = "color:var(--err);font-family:var(--mono);font-size:11px"; t.appendChild(e); }
    for (const f of p.files.sources) {
      const mods = (p.modules || []).filter((m) => m.file && (m.file === f.path || f.path.endsWith("/" + m.file) || m.file.endsWith(f.rel)));
      const isTop = topFile && mods.some((m) => m.name === p.top);
      const menuItems = [["open", () => this.edit(f.path)]];
      for (const m of mods) menuItems.push([`Set ${m.name} as top`, () => this.post("top", { module: m.name })]);
      menuItems.push(["Remove from project", () => this.post("remove", { rel: f.rel })]);
      item(f, { top: isTop, sub: mods.map((m) => m.name + (m.name === p.top ? " (top)" : "")).join(", ") },
        menuItems, () => this.edit(f.path));
    }
    if (p.modules && p.modules.length) {
      const r = el("div", "ti");
      r.appendChild(el("span", "sub", "top module:"));
      const s = document.createElement("select");
      s.style.cssText = "font:inherit;font-family:var(--mono);font-size:11.5px";
      const none = document.createElement("option"); none.value = ""; none.textContent = "(choose)"; s.appendChild(none);
      for (const m of p.modules) { const o = document.createElement("option"); o.value = m.name; o.textContent = m.name; s.appendChild(o); }
      s.value = p.top || "";
      s.onchange = () => s.value && this.post("top", { module: s.value }).catch((x) => logLine("error", x.message));
      r.appendChild(s);
      t.appendChild(r);
    }

    t.appendChild(el("h4", null, `Constraints (${p.files.constraints.length})`
      + (p.active_pcf ? ` — active: ${p.active_pcf}` : " — none active: sw/btn/led convention")));
    for (const f of p.files.constraints) {
      const act = p.active_pcf === f.rel;
      item(f, { top: act, sub: act ? "active" : "" },
        [["open", () => this.edit(f.path)],
         [act ? "Deactivate" : "Make active", () => this.post("pcf", { rel: act ? null : f.rel })],
         ["Remove from project", () => this.post("remove", { rel: f.rel })]],
        () => this.edit(f.path));
    }

    t.appendChild(el("h4", null, `Block Designs (${p.files.block_designs.length})`));
    for (const f of p.files.block_designs) {
      item(f, { sub: "" },
        [["open", () => bd.open(f.rel)],
         ["Remove from project", () => this.post("remove", { rel: f.rel })]],
        () => bd.open(f.rel));
    }

    t.appendChild(el("h4", null, "Outputs"));
    const o = el("div", "ti");
    o.appendChild(el("span", "nm", p.bit ? p.bit.split("/").pop() : "(not built yet)"));
    o.appendChild(el("span", "sub", p.bit || `${p.dir}/build/`));
    t.appendChild(o);
    const s = p.settings;
    const sv = el("div", "sub");
    sv.style.cssText = "font-family:var(--mono);font-size:10.5px;color:var(--mute);padding:6px 8px";
    sv.textContent = `settings: pnr ${s.pnr}, clock ${s.clock}${s.clock === "run" ? " div " + s.div : ""}, seed ${s.seed} — change them on the right`;
    t.appendChild(sv);
    v.appendChild(t);
  },
};
