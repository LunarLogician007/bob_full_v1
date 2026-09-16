  /* ============================================================================
     BLOCK-DIAGRAM RENDERER  —  the row/flow layout used by pages without a schematic
     ========================================================================= */
  const DW = 1040;
  function wrapTxt(s, maxc) {
    const w = String(s).split(" "), out = []; let cur = "";
    w.forEach(t => { if ((cur + " " + t).trim().length <= maxc) cur = (cur + " " + t).trim(); else { out.push(cur); cur = t; } });
    if (cur) out.push(cur);
    return out.slice(0, 2);
  }

  function renderRows(d) {
    S = [];
    let y = 14;
    const rows = d.rows || [];
    rows.forEach((row, ri) => {
      if (row.label) {
        txt(2, y + 7, row.label.toUpperCase(), { size: 7.4, anchor: "start", fill: C.FAINT, mono: true, ls: .9 });
        y += 16;
      }
      const items = row.items.filter(Boolean);
      const n = items.length, gap = row.t === "flow" ? 26 : 10;
      const bw = (DW - gap * (n - 1)) / n, bh = 54;
      items.forEach(([name, cap2, drill, kind], i) => {
        const x = i * (bw + gap), k = C[kind || d.k] || C.CLB;
        rect(x, y, bw, bh, {
          f: k.f, s: k.s, sw: drill ? 1.6 : 1, rx: 4,
          dash: kind === "SOFTK" ? "5 3" : null, cls: drill ? "dm" : null
        });
        const nl = wrapTxt(name, Math.max(10, Math.floor(bw / 6.1)));
        const capl = cap2 ? wrapTxt(cap2, Math.max(12, Math.floor(bw / 4.3))) : [];
        let ty = bh / 2 - (nl.length - 1) * 5.5 - capl.length * 4.6 + 3;
        nl.forEach(l => { txt(x + bw / 2, y + ty, l, { size: 9.2, w: 640, fill: k.t }); ty += 11; });
        capl.forEach(l => { txt(x + bw / 2, y + ty + 1, l, { size: 6.9, fill: C.MUTE, mono: true }); ty += 9; });
        if (drill) {
          txt(x + bw - 7, y + 12, "▸", { size: 9, anchor: "end", fill: C.HOT, w: 700 });
          S.push(`<rect class="hit" data-id="${drill}" x="${x}" y="${y}" width="${bw}" height="${bh}" rx="4" fill="transparent" pointer-events="all"/>`);
        }
        if (row.t === "flow" && i < n - 1)
          line(x + bw + 3, y + bh / 2, x + bw + gap - 3, y + bh / 2, { s: "#8e8e86", sw: 1.3, marker: "ah" });
      });
      y += bh;
      if (ri < rows.length - 1) { line(DW / 2, y, DW / 2, y + 14, { s: "#cbcbc3", sw: 1.2 }); y += 14; }
    });
    return svg(DW, y + 8, Math.min(DW, 760));
  }

  /* ============================================================================
     NAVIGATION
     ========================================================================= */
  const ov = document.getElementById("ov");
  const $ = id => document.getElementById(id);
  let stack = [];

  function openPage(id) {
    if (!DET[id]) return;
    if (stack[stack.length - 1] !== id) stack.push(id);
    paint();
  }

  /* redraw only the live schematic — used by the demo controls */
  function redrawSchem(id) {
    if (SCHEM[id]) $("dschem").innerHTML = SCHEM[id]();
  }

  /* a running animation must never outlive the page that owns it, or it would
     keep repainting #dschem after the user has navigated somewhere else */
  function stopAnimations() {
    if (CARRY.timer) { clearInterval(CARRY.timer); CARRY.timer = null; }
  }

  function paint() {
    stopAnimations();
    const id = stack[stack.length - 1], d = DET[id], k = C[d.k] || C.CLB;

    $("dsw").style.background = k.s;
    $("dtitle").textContent = d.title;
    $("dsub").textContent = d.sub || "";

    /* schematic + live controls */
    const sw = $("dschemw");
    if (SCHEM[id]) {
      sw.style.display = "";
      redrawSchem(id);
      const dem = $("ddemo");
      if (DEMO[id]) { dem.innerHTML = DEMO[id].html; DEMO[id].wire(() => redrawSchem(id)); }
      else dem.innerHTML = "";
    } else { sw.style.display = "none"; $("ddemo").innerHTML = ""; }

    /* block diagram */
    const rw = $("drowsw");
    if (d.rows && d.rows.length) {
      rw.style.display = "";
      $("drowshdr").textContent = SCHEM[id] ? "The same block, as a signal flow" : "Block diagram";
      $("ddiag").innerHTML = renderRows(d);
    } else rw.style.display = "none";

    /* breadcrumb */
    const cr = $("dcrumb");
    cr.innerHTML = stack.map((s, i) =>
      i === stack.length - 1
        ? `<span style="color:#35353c">${esc(DET[s].title.split(" — ")[0])}</span>`
        : `<button data-i="${i}">${esc(DET[s].title.split(" — ")[0])}</button><span>›</span>`
    ).join(" ") + (stack.length > 1 ? `<span style="margin-left:auto;color:#b6b6ae">⌫ back · Esc close</span>` : "");
    cr.querySelectorAll("button").forEach(b => b.onclick = () => { stack = stack.slice(0, +b.dataset.i + 1); paint(); });

    /* notes */
    const nw = $("dnotesw");
    if (d.notes && d.notes.length) {
      nw.style.display = "";
      $("dnotes").innerHTML = d.notes.map(n => `<li>${n}</li>`).join("");
    } else nw.style.display = "none";

    /* sub-blocks */
    const dw = $("ddrillw");
    const dr = (d.drill || []).filter(x => DET[x]);
    if (dr.length) {
      dw.style.display = "";
      $("ddrill").innerHTML = dr.map(x =>
        `<button data-go="${x}">${esc(DET[x].title.split(" — ")[0])} ▸</button>`).join("");
      $("ddrill").querySelectorAll("button").forEach(b => b.onclick = () => openPage(b.dataset.go));
    } else dw.style.display = "none";

    $("dlnk").innerHTML = d.stage
      ? `Full detail, papers, repos and pitfalls: <a href="${d.stage}/README.md">${d.stage}/README.md</a>`
      : "";

    ov.classList.add("on");
    ov.scrollTop = 0;
  }

  function closeOv() { stopAnimations(); ov.classList.remove("on"); stack = []; }

  $("out").addEventListener("click", e => {
    const t = e.target.closest("[data-id]"); if (t) openPage(t.dataset.id);
  });
  ["ddiag", "dschem"].forEach(el => $(el).addEventListener("click", e => {
    const t = e.target.closest("[data-id]"); if (t) openPage(t.dataset.id);
  }));
  $("dx").onclick = closeOv;
  ov.addEventListener("click", e => { if (e.target === ov) closeOv(); });
  addEventListener("keydown", e => {
    if (!ov.classList.contains("on")) return;
    if (e.key === "Escape") closeOv();
    if ((e.key === "Backspace" || e.key === "ArrowLeft") && stack.length > 1) { e.preventDefault(); stack.pop(); paint(); }
  });

  /* ── dev sanity check: every hotspot must land on a page ── */
  (function audit() {
    const ids = [...document.querySelectorAll("#out [data-id]")].map(n => n.dataset.id);
    const missing = [...new Set(ids)].filter(i => !DET[i]);
    if (missing.length) console.warn("hotspots with no detail page:", missing);
    const bad = [];
    Object.entries(DET).forEach(([k, d]) => {
      (d.drill || []).forEach(x => { if (!DET[x]) bad.push(k + " → " + x); });
      (d.rows || []).forEach(r => r.items.filter(Boolean).forEach(it => {
        if (it[2] && !DET[it[2]]) bad.push(k + " row → " + it[2]);
      }));
    });
    if (bad.length) console.warn("dangling drill links:", bad);
    const noSchem = Object.keys(SCHEM).filter(k => !DET[k]);
    if (noSchem.length) console.warn("schematics with no page:", noSchem);
    console.log("pages:", Object.keys(DET).length, "| schematics:", Object.keys(SCHEM).length,
      "| live demos:", Object.keys(DEMO).length, "| hotspots:", ids.length);
  })();
</script>
