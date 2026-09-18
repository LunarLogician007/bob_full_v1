// ── the editor ────────────────────────────────────────────────────────────
// A textarea with transparent text over a highlighted <pre>, which is enough for
// the 8-200 line designs bob takes and keeps the page free of libraries. Error
// markers come from the flow's own diagnostics, so a yosys or iverilog complaint
// lands on the line it names.

const KW = new RegExp("\\b(" + (
  "module|endmodule|input|output|inout|wire|reg|logic|assign|always|always_ff|always_comb|" +
  "posedge|negedge|begin|end|if|else|case|casez|endcase|default|for|while|parameter|localparam|" +
  "integer|genvar|generate|endgenerate|initial|function|endfunction|task|endtask|" +
  "signed|unsigned|automatic|typedef|struct|packed|enum|`define|`include|`ifdef|`endif|`timescale"
).split("|").join("|") + ")\\b", "g");

const editor = {
  marks: {},                                   // line -> severity

  set(path, text) {
    S.open = path; S.text[path] = text;
    $("ta").value = text;
    this.marks = {};
    this.paint();
    if (typeof tabs !== "undefined") tabs.render();   // the tab is named after the file
  },

  get() { return $("ta").value; },

  esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); },

  highlight(src) {
    // One pass, comments and strings first so keywords inside them stay plain.
    const parts = [];
    const re = /(\/\/[^\n]*|\/\*[\s\S]*?\*\/)|("(?:[^"\\]|\\.)*")/g;
    let last = 0, m;
    const code = (s) => this.esc(s)
      .replace(KW, '<span class="kw">$1</span>')
      .replace(/\b(\d+'[bhdo][0-9a-fA-FxzZ_]+|\d+\.\d+|\d+)\b/g, '<span class="num">$1</span>');
    while ((m = re.exec(src))) {
      parts.push(code(src.slice(last, m.index)));
      parts.push(`<span class="${m[1] ? "cm" : "str"}">${this.esc(m[0])}</span>`);
      last = m.index + m[0].length;
    }
    parts.push(code(src.slice(last)));
    return parts.join("");
  },

  paint() {
    const src = $("ta").value;
    const lines = src.split("\n");
    $("hl").innerHTML = this.highlight(src) + "\n";
    const g = $("gut");
    g.innerHTML = "";
    lines.forEach((_, i) => {
      const n = i + 1, sev = this.marks[n];
      const row = el(sev ? "b" : "div", null, String(n));
      row.title = sev ? `${sev} on line ${n}` : "";
      g.appendChild(row);
    });
    $("nsrc").textContent = `${lines.length} lines`;
  },

  mark(messages) {
    this.marks = {};
    for (const m of messages) {
      if (!m.line) continue;
      if (!S.open || !m.file || S.open.endsWith(m.file) || m.file.endsWith(S.open.split("/").pop()))
        this.marks[m.line] = m.severity;
    }
    this.paint();
  },

  goto(line) {
    const ta = $("ta");
    const pos = ta.value.split("\n").slice(0, Math.max(0, line - 1)).join("\n").length;
    ta.focus();
    ta.setSelectionRange(pos, pos);
    const lh = parseFloat(getComputedStyle($("hl")).lineHeight) || 19;
    $("edwrap").scrollTop = Math.max(0, (line - 4) * lh);
    tabs.show("editor");
  },

  wire() {
    const ta = $("ta"), wrap = $("edwrap");
    ta.addEventListener("input", () => {
      S.text[S.open] = ta.value;
      if (!S.dirty) { S.dirty = true; tabs.render(); }
      this.paint();
    });
    ta.addEventListener("scroll", () => { wrap.scrollTop = ta.scrollTop; wrap.scrollLeft = ta.scrollLeft; });
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Tab") {                   // a tab indents, it does not leave the box
        e.preventDefault();
        const s = ta.selectionStart, t = ta.value;
        ta.value = t.slice(0, s) + "    " + t.slice(ta.selectionEnd);
        ta.selectionStart = ta.selectionEnd = s + 4;
        S.text[S.open] = ta.value; this.paint();
      }
    });
  },
};
