#!/usr/bin/env python3
"""
build.py - project.html, the interactive companion of docs/project/REPORT.md.

  python3 docs/project/collect.py     (numbers from the repository -> data.json)
  python3 docs/project/build.py       -> bob_full_v1/project.html

Single source: the text and every table come from REPORT.md (converted here by a small
Markdown converter - the subset the report uses), the numbers from data.json. The views
(timeline, device, configuration streams, flow, verification, hardware, crashes,
problems) read the report's own tables, so the page cannot drift from the report.
The look follows arch.html (docs/arch/p1_head.html).
"""

import html
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


# --- Markdown (the subset REPORT.md uses) ----------------------------------------------------

def slug(text):
    s = re.sub(r"<[^>]+>", "", text).lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s+", "-", s.strip())


def inline(text):
    parts = re.split(r"(`[^`]*`)", text)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) >= 2:
            out.append(f"<code>{html.escape(p[1:-1])}</code>")
            continue
        t = html.escape(p, quote=False)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)

        def link(m):
            label, href = m.group(1), m.group(2)
            if href.startswith("#"):
                return f'<a href="#r-{href[1:]}">{label}</a>'
            if not href.startswith(("http", "/")):
                href = os.path.normpath(os.path.join("docs/project", href)).replace("\\", "/")
            return f'<a href="{html.escape(href)}">{label}</a>'
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, t)
        t = t.replace("\\*", "*")
        out.append(t)
    return "".join(out)


def split_row(line):
    cells = line.strip()
    if cells.startswith("|"):
        cells = cells[1:]
    if cells.endswith("|"):
        cells = cells[:-1]
    # split on | not inside backticks
    out, cur, tick = [], "", False
    for ch in cells:
        if ch == "`":
            tick = not tick
        if ch == "|" and not tick:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


def convert(md):
    """-> (html, sections, tables); sections: [{id, level, title}], tables: {section_no: [{header, rows}]}"""
    lines = md.splitlines()
    out, sections, tables = [], [], {}
    i, section = 0, "0"
    list_stack = []                                   # [(indent, tag)]

    def close_lists(to_indent=-1):
        while list_stack and list_stack[-1][0] > to_indent:
            out.append(f"</li></{list_stack.pop()[1]}>")

    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            close_lists()
            j = i + 1
            code = []
            while j < len(lines) and not lines[j].startswith("```"):
                code.append(lines[j])
                j += 1
            out.append(f'<pre class="code">{html.escape(chr(10).join(code))}</pre>')
            i = j + 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            close_lists()
            level, title = len(m.group(1)), m.group(2).strip()
            sid = "r-" + slug(title)
            n = re.match(r"^(\d+(?:\.\d+)?)\.?\s", title)
            if level == 2 and n:
                section = n.group(1)
            sections.append({"id": sid, "level": level, "title": re.sub(r"[`*]", "", title)})
            out.append(f'<h{level} id="{sid}">{inline(title)}</h{level}>')
            i += 1
            continue
        if ln.strip() == "---":
            close_lists()
            out.append("<hr>")
            i += 1
            continue
        if ln.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            close_lists()
            header = split_row(ln)
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(split_row(lines[j]))
                j += 1
            tables.setdefault(section, []).append({"header": header, "rows": rows})
            h = "".join(f"<th>{inline(c)}</th>" for c in header)
            b = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f'<div class="tw"><table class="md"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>')
            i = j
            continue
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", ln)
        if m:
            indent = len(m.group(1))
            tag = "ol" if m.group(2)[0].isdigit() else "ul"
            if list_stack and indent < list_stack[-1][0]:
                close_lists(indent)
            if not list_stack or indent > list_stack[-1][0]:
                out.append(f"<{tag}><li>")
                list_stack.append((indent, tag))
            else:
                out.append("</li><li>")
            text = m.group(3)
            j = i + 1
            while j < len(lines) and lines[j].strip() and not re.match(r"^\s*([-*]|\d+\.)\s+", lines[j]) \
                    and lines[j].startswith(" " * (indent + 2)) and not lines[j].strip().startswith(("|", "```")):
                text += " " + lines[j].strip()
                j += 1
            out.append(inline(text))
            i = j
            continue
        if not ln.strip():
            if list_stack and i + 1 < len(lines) and re.match(r"^\s+([-*]|\d+\.)\s+", lines[i + 1]):
                i += 1
                continue
            close_lists()
            i += 1
            continue
        close_lists()
        para = [ln.strip()]
        j = i + 1
        while j < len(lines) and lines[j].strip() and not re.match(r"^(#{1,6}\s|```|\s*\||\s*([-*]|\d+\.)\s|---$)", lines[j]):
            para.append(lines[j].strip())
            j += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")
        i = j
    close_lists()
    return "\n".join(out), sections, tables


def chunks(body):
    """the HTML under each heading, up to the next heading of any level: {id: html}"""
    parts = re.split(r'(<h[1-6] id="[^"]+">.*?</h[1-6]>)', body, flags=re.S)
    out, cur = {}, None
    for piece in parts:
        m = re.match(r'<h[1-6] id="([^"]+)">', piece)
        if m:
            cur = m.group(1)
            out[cur] = ""
        elif cur:
            out[cur] += piece
    return out


def build_page(md_name, template_name, out_name, data):
    md = open(os.path.join(HERE, md_name)).read()
    body, sections, tables = convert(md)
    template = open(os.path.join(HERE, template_name)).read()
    blob = json.dumps({"sections": sections, "tables": tables, "data": data,
                       "chunks": chunks(body)}, separators=(",", ":"))
    blob = blob.replace("</", "<\\/")
    page = template.replace("/*__DATA__*/null", blob).replace("<!--__REPORT__-->", body)
    out = os.path.join(ROOT, out_name)
    open(out, "w").write(page)
    js = page.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    open(os.path.join(ROOT, "build", out_name.replace(".html", "_check.js")), "w").write(js)
    print(f"wrote {out_name} ({len(page)} bytes; {len(sections)} headings, "
          f"{sum(len(v) for v in tables.values())} tables)")


def main():
    data = json.load(open(os.path.join(HERE, "data.json")))
    build_page("REPORT.md", "template.html", "project.html", data)
    build_page("GUIDE.md", "template_guide.html", "guide.html", data)


if __name__ == "__main__":
    main()
