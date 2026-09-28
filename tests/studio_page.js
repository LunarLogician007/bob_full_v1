// studio_page.js - what tests/test_studio_page.py runs studio.html's script inside.
//
// The test puts the page's script at the SCRIPT marker and a results file at OUT.
// Under JavaScriptCore (osascript -l JavaScript) there is no DOM: every document, window
// and storage call lands on __any(), which absorbs it. /api goes to the fake backend
// below. Promise jobs run once the script has been evaluated, so the scenarios write
// their results to a file rather than returning them.

ObjC.import("Foundation");
const __NS = $;                          // JXA's bridge; the page declares its own $
{
  const __any = () => new Proxy(function () {}, {
    get(t, k) {
      if (k === Symbol.toPrimitive) return () => "";
      if (k === "then") return undefined;             // never mistaken for a promise
      if (k === Symbol.iterator) return function* () {};
      if (k === "length") return 0;
      return __any();
    },
    set() { return true; }, apply() { return __any(); }, construct() { return __any(); },
  });
  var CONFIRM = true;                    // what window.confirm answers
  var document = __any(), localStorage = __any(), navigator = __any(), matchMedia = __any(),
      EventSource = __any(), fetch = __any(), location = __any(), history = __any();
  var window = new Proxy({}, { get: (t, k) => k === "confirm" ? () => CONFIRM : k === "pywebview" ? undefined : __any() });
  var setTimeout = () => 0, setInterval = () => 0, clearInterval = () => {}, requestAnimationFrame = () => 0;
  var console = { log() {} };

// @@SCRIPT@@

  // --- the fake backend: three projects, one open at a time -------------------------
  const PROJ = {
    "/p/A/A.bobproj": { name: "A", path: "/p/A/A.bobproj", block_designs: ["bd/a_bd.bd"] },
    "/p/N/N.bobproj": { name: "N", path: "/p/N/N.bobproj", block_designs: [] },
    "/r/traffic/traffic.bobproj": { name: "traffic", path: "/r/traffic/traffic.bobproj", block_designs: ["bd/traffic_bd.bd"] },
  };
  let OPEN = null;
  const asJson = (p) => p && {                          // Project.to_json's shape
    ...p, top: null, sources: [], constraints: [], active_pcf: null, bit: null, modules: [],
    dir: p.path.replace(/\/[^/]*$/, ""), settings: { pnr: "vpr", clock: "jtag", div: 0, seed: 1, hz: "div" },
    files: { sources: [], constraints: [], block_designs: p.block_designs.map((rel) => ({ rel, path: rel, exists: true })) },
  };
  api = async function (path, body) {
    if (path === "/api/project/open") { OPEN = PROJ[body.path]; return { project: asJson(OPEN), recent: [] }; }
    if (path === "/api/project/close") { OPEN = null; return { project: null, recent: [] }; }
    if (path.startsWith("/api/bd?rel=")) {
      const rel = decodeURIComponent(path.split("=")[1]);
      if (!OPEN || !OPEN.block_designs.includes(rel)) throw new Error(`${rel} is not one of the project's block designs`);
      return { rel, bd: { bd: 1, name: rel.replace(/^bd\/|\.bd$/g, ""), wires: [],
                          blocks: [{ id: "b", kind: "ip", type: "toggle", params: {} }] } };
    }
    if (path === "/api/bd/palette") return { ip: [], modules: [], board: { ports: [], pads: [], pins: { input: [], output: [] } } };
    if (path.startsWith("/api/ports")) return { ports: [] };
    if (path.startsWith("/api/source")) return { text: "module x; endmodule" };
    return {};
  };

  // --- the scenarios ----------------------------------------------------------------
  const settle = async () => { for (let i = 0; i < 100; i++) await null; };
  const out = [];
  const check = (what, ok) => out.push((ok ? "ok    " : "FAIL  ") + what);
  const TRAFFIC = { name: "traffic", path: "work/examples/traffic/traffic.bobproj", project: "/r/traffic/traffic.bobproj" };
  const COUNTER = { name: "counter", path: "work/examples/counter/counter.v" };
  (async () => {
    try {
      await project.open("/p/A/A.bobproj"); await bd.open("bd/a_bd.bd");
      check("A's block design is on the canvas", bd.doc && bd.doc.name === "a_bd");
      await start.example(TRAFFIC, false);
      check("a block-design example opens as its project", S.proj && S.proj.name === "traffic");
      check("its block design replaces A's", bd.doc && bd.doc.name === "traffic_bd" && bd.rel === "bd/traffic_bd.bd");
      check("and the Block Design tab shows it", tabs.which === "bd");

      await start.example(COUNTER, false);
      check("a one-file example closes the project", S.proj === null);
      check("and leaves no block design behind", bd.doc === null && bd.rel === null && bd.palette === null);

      await project.open("/p/A/A.bobproj"); await bd.open("bd/a_bd.bd");
      await project.open("/p/N/N.bobproj");
      check("a project with no block design drops A's", bd.doc === null);

      await project.open("/p/A/A.bobproj"); await bd.open("bd/a_bd.bd");
      await project.post("close");
      check("Close project drops the block design", bd.doc === null);

      tabs.show("bd");                                  // opened while the tab shows
      await project.open("/p/A/A.bobproj");
      tabs.show("bd"); await settle();
      check("the Block Design tab opens the project's design by itself", bd.doc && bd.doc.name === "a_bd");

      bd.dirty = true; CONFIRM = false;
      try { await start.example(TRAFFIC, false); } catch (e) { /* refused: the page logs it */ }
      check("unsaved edits, discard refused: A and its edits stay", S.proj.name === "A" && bd.doc.name === "a_bd" && bd.dirty);
      CONFIRM = true;
      await start.example(TRAFFIC, false);
      check("unsaved edits, discard accepted: the example opens", S.proj.name === "traffic" && bd.doc.name === "traffic_bd" && !bd.dirty);

      const before = bd.doc;
      tabs.show("bd");
      await project.open(TRAFFIC.project); tabs.show("bd"); await settle();
      check("the same project reopened: its design is read afresh", bd.doc && bd.doc.name === "traffic_bd" && bd.doc !== before);
    } catch (e) { out.push("EXCEPTION " + e + "\n" + e.stack); }
    __NS.NSString.alloc.initWithUTF8String(out.join("\n"))
      .writeToFileAtomicallyEncodingError("@@OUT@@", true, __NS.NSUTF8StringEncoding, null);
  })();
}
