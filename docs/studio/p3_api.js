// ── talking to software/host/studio.py ──────────────────────────────────────────────
// Nothing clever: fetch for requests, EventSource for a build's stage stream.

const S = {
  device: null,          // /api/device
  examples: [],
  project: { files: [], top: null, pcf: null, clock: "jtag", div: 0, seed: 1, pnr: "vpr", name: null },
  open: null,            // path of the file in the editor
  text: {},              // path -> source
  result: null,          // the last finished build
  placement: null,
  stages: {},            // name -> stage record
  messages: [],
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
