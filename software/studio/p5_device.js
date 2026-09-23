// ── the Device view ───────────────────────────────────────────────────────
// The real grid from device.json, with this design's placement on top. Drawn with
// the same hand-rolled SVG the rest of the project uses - no library, and every
// coordinate comes from the device description rather than a picture of it.

const COLOR = {
  clb:  { fill: "#e8e6df", used: "#b8500f" },
  bram: { fill: "#dfe6ea", used: "#2b6ca3" },
  dsp:  { fill: "#e6e1ea", used: "#6b4a9a" },
  io:   { fill: "#eeece6", used: "#2f7d4f" },
};
const CELL = 30, PAD = 16, GAP = 3;

const device = {
  svgns: "http://www.w3.org/2000/svg",

  n(tag, attrs, txt) {
    const e = document.createElementNS(this.svgns, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (txt != null) e.textContent = txt;
    return e;
  },

  // Grid (x, y) -> pixels. VPR's y grows upward; the screen's grows down.
  px(x, y) {
    const h = S.device.grid.h;
    return [PAD + x * CELL, PAD + (h - 1 - y) * CELL];
  },

  render() {
    const d = S.device;
    if (!d) return;
    const svg = $("floor");
    svg.innerHTML = "";
    const W = PAD * 2 + d.grid.w * CELL, H = PAD * 2 + d.grid.h * CELL;
    if (!this.z) this.z = zoomer(svg, $("devzoom"));
    this.z.setBase(0, 0, W, H);

    const placed = {}, byType = {};
    for (const b of (S.placement ? S.placement.blocks : [])) {
      placed[`${b.x},${b.y}`] = b;
      byType[b.type] = (byType[b.type] || 0) + 1;
    }

    // channels, so the routing has something to sit on
    const chan = this.n("g", { stroke: "var(--rule)", "stroke-width": 0.5, opacity: 0.55 });
    for (let x = 0; x <= d.grid.w; x++) {
      const [px] = this.px(x, 0);
      chan.appendChild(this.n("line", { x1: px - GAP / 2, y1: PAD, x2: px - GAP / 2, y2: H - PAD }));
    }
    for (let y = 0; y <= d.grid.h; y++) {
      const [, py] = this.px(0, y);
      chan.appendChild(this.n("line", { x1: PAD, y1: py - GAP / 2, x2: W - PAD, y2: py - GAP / 2 }));
    }
    svg.appendChild(chan);

    // blocks
    const g = this.n("g", {});
    for (const b of d.blocks) {
      const [x, y] = this.px(b.x, b.y);
      const c = COLOR[b.type] || COLOR.clb;
      const hit = placed[`${b.x},${b.y}`];
      const r = this.n("rect", {
        x: x + GAP / 2, y: y + GAP / 2, width: CELL - GAP, height: CELL - GAP, rx: 2.5,
        fill: hit ? c.used : c.fill,
        stroke: hit ? c.used : "var(--rule)",
        "stroke-width": hit ? 1.2 : 0.6,
        "fill-opacity": hit ? 0.9 : 1,
      });
      r.appendChild(this.n("title", {}, hit ? `${hit.name}\n${b.name} (${b.type}) at ${b.x},${b.y}`
                                           : `${b.name} (${b.type}) at ${b.x},${b.y} - free`));
      g.appendChild(r);
      const label = b.type === "io" ? "" : b.type === "bram" ? "B" : b.type === "dsp" ? "D" : "";
      if (label || ($("showids").checked && hit)) {
        g.appendChild(this.n("text", {
          x: x + CELL / 2, y: y + CELL / 2 + 3.2, "text-anchor": "middle",
          "font-family": "var(--mono)", "font-size": 9.5,
          fill: hit ? "#fff" : "var(--mute)",
        }, $("showids").checked && hit ? hit.name.replace(/^[^_]*_/, "").slice(0, 5) : label));
      }
    }
    svg.appendChild(g);

    // M21: a CLB is N logic elements - draw them as small cells inside the tile, filled
    // when used (a fractured LUT is split, an adder is ruled, a flip-flop is dotted)
    if (d.cluster && S.placement && S.placement.elements && S.placement.elements.length) {
      const n = d.cluster.n, cols = Math.ceil(n / 2), eg = this.n("g", {});
      const cw = (CELL - GAP - 4) / cols, ch = (CELL - GAP - 4) / 2;
      const used = {};
      for (const e of S.placement.elements) used[`${e.x},${e.y},${e.e}`] = e;
      for (const b of d.blocks) {
        if (b.type !== "clb" || !placed[`${b.x},${b.y}`]) continue;
        const [x, y] = this.px(b.x, b.y);
        for (let k = 0; k < n; k++) {
          const u = used[`${b.x},${b.y},${k}`];
          const ex = x + GAP / 2 + 2 + (k % cols) * cw, ey = y + GAP / 2 + 2 + (1 - Math.floor(k / cols)) * ch;
          const r = this.n("rect", { x: ex + 0.6, y: ey + 0.6, width: cw - 1.2, height: ch - 1.2, rx: 0.8,
            fill: u ? "#fff" : "none", "fill-opacity": u ? (u.mode === "frac" ? 0.55 : 0.9) : 0,
            stroke: "#fff", "stroke-width": 0.5, opacity: u ? 1 : 0.45 });
          r.appendChild(this.n("title", {}, u ? `${b.name} element ${k}: ${u.mode}` +
            `${u.ffs ? `, ${u.ffs} flip-flop${u.ffs > 1 ? "s" : ""}` : ""}\n${u.name}` : `${b.name} element ${k} - free`));
          eg.appendChild(r);
        }
      }
      svg.appendChild(eg);
      byType.element = S.placement.elements.length;
    }

    // Routed nets. Each CHANX/CHANY node occupies a channel segment along its own
    // span, so draw the span - joining node centres would suggest point-to-point
    // wires the fabric does not have. A segment used by several nets is darker.
    if ($("shownets").checked && S.placement && S.placement.nets.length) {
      const seg = new Map();
      for (const net of S.placement.nets) {
        for (const n of net.nodes) {
          if (n.kind !== "CHANX" && n.kind !== "CHANY") continue;
          const prev = seg.get(n.id);
          if (prev) { prev.n++; prev.nets.add(net.name); }
          else seg.set(n.id, { n: 1, node: n, nets: new Set([net.name]) });
        }
      }
      const ng = this.n("g", { fill: "none", "stroke-linecap": "round" });
      for (const { n, node, nets } of seg.values()) {
        const [ax, ay] = this.px(node.x0, node.y0);
        const [bx, by] = this.px(node.x1, node.y1);
        const horiz = node.kind === "CHANX";
        // Offset off the block centres so the channel reads as a channel.
        const off = horiz ? -CELL / 2 + 2 : -CELL / 2 + 2;
        const ln = this.n("line", {
          x1: ax + CELL / 2 + (horiz ? -CELL / 2 : off),
          y1: ay + CELL / 2 + (horiz ? off : CELL / 2),
          x2: bx + CELL / 2 + (horiz ? CELL / 2 : off),
          y2: by + CELL / 2 + (horiz ? off : -CELL / 2),
          stroke: "var(--accent-2)",
          "stroke-width": Math.min(1 + n * 0.5, 3),
          opacity: Math.min(0.35 + n * 0.18, 0.95),
        });
        ln.appendChild(this.n("title", {},
          `${node.kind} ${node.id}\n${[...nets].join("\n")}`));
        ng.appendChild(ln);
      }
      svg.appendChild(ng);
    }

    // legend and the one-line summary
    const lg = $("devlegend");
    lg.innerHTML = "";
    for (const t of ["clb", "bram", "dsp", "io"]) {
      if (!d.capacity[t]) continue;
      const s = el("span", null);
      s.innerHTML = `<i style="background:${COLOR[t].used}"></i>${t} ${byType[t] || 0}/${d.capacity[t]}`;
      lg.appendChild(s);
    }
    if (S.placement && S.placement.nets.length) {
      const s = el("span", null);
      s.innerHTML = `<i style="background:var(--accent-2)"></i>${S.placement.nets.length} nets, wirelength ${S.placement.wirelength}`;
      lg.appendChild(s);
    }
    $("devtitle").textContent = `${d.name} — ${d.grid.w} x ${d.grid.h} grid, W = ${d.chan_width}`;
    const pill = $("devpill");
    if (S.placement) {
      pill.textContent = `${S.result ? S.result.design : ""}: ${byType.clb || 0} CLBs placed` +
        (byType.element ? `, ${byType.element} of ${(byType.clb || 0) * d.cluster.n} elements used` : "");
      pill.className = "pill ok";
    } else {
      pill.textContent = "nothing placed yet"; pill.className = "pill";
    }
  },
};
