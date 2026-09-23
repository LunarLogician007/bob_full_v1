#!/usr/bin/env python3
"""
build.py - assemble arch.html (the interactive bob die slice) from its parts.

  python3 docs/arch/build.py        -> bob_full_v1/arch.html

p1_head.html and p9_nav.js are the style, primitives and navigation of
architecture-v2.html, copied verbatim and patched here, so the look is identical.
data.json is the real M7 device (regenerate with --data after make device).
"""

import glob
import json
import re
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def dump_data():
    sys.path.insert(0, os.path.join(ROOT, "software", "bob"))
    import collections
    import device
    d = device.Device()
    rr = d.rr
    mux, bits = collections.Counter(), collections.Counter()
    for m in d.muxes.values():
        mux[m.tile] += 1
        bits[m.tile] += m.width
    data = {
        "chain": d.chain_width, "W": d.width, "H": d.height, "chanw": d.arch["chan_width"],
        "heights": {c["type"]: c["height"] for c in d.arch["columns"]},
        "nmux": len(d.muxes), "mbits": sum(m.width for m in d.muxes.values()),
        "ntype": dict(collections.Counter(rr.nodes[m.node].type if m.node in rr.nodes else "EIN"
                                          for m in d.muxes.values())),
        "lut_k": d.lut_k,
        "cluster": {"n": d.cluster["n"], "i": d.cluster["i"], "xbar": d.cluster["xbar"],
                    "xbar_n": len(d.xbar_sources(0, 0)), "xbar_w": d.xbar_width(),
                    "ele_w": d.element_width(), "clb_w": d.tile_types["clb"].width},
        "tiles": [[t.name, t.x, t.y, t.chain_lo, t.width, mux.get(t.name, 0), bits.get(t.name, 0)] for t in d.tiles],
        "blocks": [[b.name, b.type, b.x, b.y, b.index, b.chain_lo] for b in d.blocks],
        "pads": {p["pad"]: p["name"] for p in d.board_inputs + d.board_outputs},
        "chanfanin": sorted(collections.Counter(len(m.inputs) for m in d.muxes.values()
                                                if m.node in rr.nodes and rr.nodes[m.node].type != "IPIN").items()),
        "ipinfanin": sorted(collections.Counter(len(m.inputs) for m in d.muxes.values()
                                                if m.node in rr.nodes and rr.nodes[m.node].type == "IPIN").items()),
        # The user-clock numbers the timing card quotes. They live here so the page
        # cannot disagree with the XDC: M16 raised the gap from 256 to 512 cycles and
        # the page still said 256 until this was generated rather than typed.
        "clock": {"gap": 1 << device.GCE_MIN_GAP_SHIFT,
                  "gap_shift": device.GCE_MIN_GAP_SHIFT,
                  "xdc_mc": device.XDC_SYSCLK_MULTICYCLE,        # M21: no longer the gap
                  "div_shift": device.DIV_MIN_SHIFT,
                  "max_hz": device.SYSCLK_HZ / 2 ** device.DIV_MIN_SHIFT,
                  "sysclk_ns": 1e9 / device.SYSCLK_HZ},
        "nclb": sum(1 for b in d.blocks if b.type == "clb"),
        "npad": len(d.board_inputs) + len(d.board_outputs) or d.npad,
    }
    open(os.path.join(HERE, "data.json"), "w").write(json.dumps(data, separators=(",", ":")))


EXTRA_CSS = """
  /* ───────────────────────── provenance table (bob) ───────────────────────── */
  .kv { width: 100%; border-collapse: collapse; font-size: 12.5px }
  .kv td { padding: 7px 10px; border-bottom: 1px solid var(--rule-2); vertical-align: top; line-height: 1.45 }
  .kv td:first-child { width: 34%; font-family: var(--mono); font-size: 11.5px; color: var(--ink) }
  .kv td:last-child { color: #35353c }
  .kv code, .notes code { font-family: var(--mono); font-size: 11.5px; background: #f4f3ef; padding: 1px 5px; border-radius: 4px }
  .kv tr:last-child td { border-bottom: none }
"""

CARD_EXTRA = """      <div id="dsrcw"><div class="sect">Where it comes from</div><table class="kv" id="dsrc"></table></div>
      <div id="dwhyw"><div class="sect">Why that source</div><ul class="notes" id="dwhy"></ul></div>
      <div id="dfilesw"><div class="sect">Files that implement / use it</div><table class="kv" id="dfiles"></table></div>
      <div id="dtbw"><div class="sect">Verified by</div><table class="kv" id="dtb"></table></div>
"""

NAV_PATCH_OLD = """    $("dlnk").innerHTML = d.stage"""
NAV_PATCH_NEW = """    const kv = (w, t, rows) => {
      if (rows && rows.length) { $(w).style.display = ""; $(t).innerHTML = rows.map(([a, b]) => `<tr><td>${a}</td><td>${b}</td></tr>`).join(""); }
      else $(w).style.display = "none";
    };
    kv("dsrcw", "dsrc", d.src); kv("dfilesw", "dfiles", d.files); kv("dtbw", "dtb", d.tb);
    if (d.why && d.why.length) { $("dwhyw").style.display = ""; $("dwhy").innerHTML = d.why.map(n => `<li>${n}</li>`).join(""); }
    else $("dwhyw").style.display = "none";

    $("dlnk").innerHTML = d.stage"""


def build():
    head = open(os.path.join(HERE, "p1_head.html")).read()
    head = head.replace("<title>FPGA Architecture — Interactive Die Floorplan &amp; Schematics</title>",
                        '<meta charset="utf-8">\n<title>bob — Interactive Die Slice</title>')
    data_json = json.load(open(os.path.join(HERE, "data.json")))
    nclb = sum(1 for b in data_json["blocks"] if b[1] == "clb")
    tag = open(os.path.join(ROOT, "hw", "build.cfg")).read()
    tag = (re.search(r"^tag\s*=\s*(\S+)", tag, re.M) or [None, "?"])[1]
    head = head.replace('<span class="brand">FPGA Top-Level Architecture</span>',
                        f'<span class="brand">bob — FPGA inside the XC7Z020 · {tag} fabric ({nclb} CLBs)</span>')
    head = head.replace("  /* ───────────────────────── print", EXTRA_CSS + "\n  /* ───────────────────────── print")
    head = head.replace('      <div class="lnk" id="dlnk"></div>', CARD_EXTRA + '      <div class="lnk" id="dlnk"></div>')
    for key in ("</style>", 'id="dsrc"', "const DEFS"):
        assert key in head, key
    nav = open(os.path.join(HERE, "p9_nav.js")).read()
    assert NAV_PATCH_OLD in nav
    nav = nav.replace(NAV_PATCH_OLD, NAV_PATCH_NEW)
    nav = nav.replace('`Full detail, papers, repos and pitfalls: <a href="${d.stage}/README.md">${d.stage}/README.md</a>`',
                      '`Deeper reading in the repo: <a href="${d.stage}">${d.stage}</a>`')
    data = open(os.path.join(HERE, "data.json")).read()
    parts = [open(p).read() for p in sorted(glob.glob(os.path.join(HERE, "p[2-8]*.js")))]
    body = "\n  const BOB = " + data + ";\n" + "\n".join(parts) + "\n" + nav
    out = os.path.join(ROOT, "arch.html")
    open(out, "w").write(head + body)
    js = body.rsplit("</script>", 1)[0]
    open(os.path.join(ROOT, "build", "arch_check.js"), "w").write(js)
    print(f"wrote {out} ({len(head) + len(body)} bytes, {len(parts)} parts)")


if __name__ == "__main__":
    if "--data" in sys.argv:
        dump_data()
    build()
