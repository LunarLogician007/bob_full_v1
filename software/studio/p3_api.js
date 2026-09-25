// ── talking to software/host/studio.py ──────────────────────────────────────────────
// Nothing clever: fetch for requests, EventSource for a build's stage stream.

const S = {
  device: null,          // /api/device
  examples: [],
  project: { files: [], top: null, pcf: null, clock: "jtag", div: 0, seed: 1, pnr: "vpr", hz: "div", name: null },
  open: null,            // path of the file in the editor
  text: {},              // path -> source
  result: null,          // the last finished build
  placement: null,
  stages: {},            // name -> stage record
  messages: [],
  hints: [],             // what to do about a failed build (ux.hints, from the backend)
  log: [],
  target: null,
  busy: false,
  job: null,
};

const $ = (id) => document.getElementById(id);
const el = (tag, cls, txt) => { const n = document.createElement(tag); if (cls) n.className = cls; if (txt != null) n.textContent = txt; return n; };

async function api(path, body) {
  const opt = body === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const t = await r.text();
  let j = null;
  try { j = t ? JSON.parse(t) : null; } catch (e) { throw new Error(`${path}: ${t.slice(0, 200)}`); }
  if (!r.ok) throw new Error((j && j.error) || `${path}: HTTP ${r.status}`);
  return j;
}

// In the desktop app (./bob studio, pywebview) the page can open the system's file dialogs;
// in a browser tab this is null and the in-page folder browser does the job.
function native() { return (window.pywebview && window.pywebview.api) || null; }

function logLine(kind, text) {
  S.log.push({ t: new Date().toLocaleTimeString(), kind, text });
  if (dock.which === "log") dock.render();
}

// Start a build and stream its stages. onStage/onDone are called as they arrive.
function startBuild(spec, onStage, onDone) {
  return api("/api/build", spec).then((j) => {
    S.job = j.job;
    const es = new EventSource(`/api/events/${j.job}`);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.event === "stage") onStage(ev);
      else if (ev.event === "done" || ev.event === "failed") { es.close(); onDone(ev); }
      else if (ev.event === "start") logLine("info", `build ${ev.design} (top ${ev.top})`);
    };
    es.onerror = () => { es.close(); onDone({ event: "failed", error: "the event stream closed" }); };
    return j.job;
  });
}

// ── zoom and pan for an SVG view (block design, device, waveform) ──────────────────
// The view draws its content in its own units and tells the zoomer how big that is
// (base). The zoomer owns the viewBox: +/- and the fit button, Ctrl/⌘-wheel or a
// trackpad pinch zooms about the pointer, a plain wheel scrolls, and dragging the empty
// background pans. `bar` is where the -, %, + and fit controls go.
function zoomer(svg, bar, { panOnDrag = true, onChange = null } = {}) {
  const z = { view: null, base: [0, 0, 100, 100], fitted: true };
  const label = el("span", "pill", "100%");
  const apply = () => {
    const v = z.view || z.base;
    svg.setAttribute("viewBox", v.map((n) => n.toFixed(2)).join(" "));
    label.textContent = Math.round(100 * z.base[2] / v[2]) + "%";
    if (onChange) onChange(v);
  };
  z.setBase = (x, y, w, h) => {
    z.base = [x, y, w, h];
    if (z.fitted || !z.view) z.view = null;
    apply();
  };
  z.fit = () => { z.view = null; z.fitted = true; apply(); };
  z.zoom = (f, px, py) => {                       // f > 1 zooms in, about (px, py) in view units
    const v = (z.view || z.base).slice();
    if (px == null) { px = v[0] + v[2] / 2; py = v[1] + v[3] / 2; }
    const w = Math.min(z.base[2] * 8, Math.max(z.base[2] / 40, v[2] / f));
    const k = w / v[2];
    z.view = [px - (px - v[0]) * k, py - (py - v[1]) * k, v[2] * k, v[3] * k];
    z.fitted = false;
    apply();
  };
  z.pan = (dx, dy) => {
    const v = (z.view || z.base).slice();
    z.view = [v[0] + dx, v[1] + dy, v[2], v[3]];
    z.fitted = false;
    apply();
  };
  z.point = (e) => {                              // a mouse event -> view units
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  };
  z.controls = (host) => {
    host = host || bar;
    if (!host) return;
    const b = (t, title, fn) => {
      const n = el("button", "go sec", t);
      n.style.cssText = "margin:0;width:auto;padding:2px 9px;font-size:12px";
      n.title = title; n.onclick = fn;
      host.appendChild(n);
    };
    b("−", "zoom out (Ctrl/⌘ + wheel)", () => z.zoom(1 / 1.25));
    host.appendChild(label);
    b("+", "zoom in (Ctrl/⌘ + wheel)", () => z.zoom(1.25));
    b("fit", "show everything", () => z.fit());
  };
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const v = z.view || z.base;
    if (e.ctrlKey || e.metaKey) {
      const p = z.point(e);
      z.zoom(Math.exp(-e.deltaY * 0.0025), p.x, p.y);
    } else {
      const r = svg.getBoundingClientRect();
      z.pan(e.deltaX * v[2] / r.width, e.deltaY * v[3] / r.height);
    }
  }, { passive: false });
  if (panOnDrag) {
    svg.addEventListener("mousedown", (e) => {
      if (e.target !== svg && !e.target.classList.contains("bg")) return;   // only the empty background
      const p0 = z.point(e);
      const move = (ev) => {
        const p = z.point(ev);
        z.pan(p0.x - p.x, p0.y - p.y);
      };
      const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
  }
  z.controls();
  return z;
}
