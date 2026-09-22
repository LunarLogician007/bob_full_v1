#!/usr/bin/env python3
"""
build.py - assemble studio.html from its parts, the way docs/arch/build.py does.

  python3 docs/studio/build.py          -> bob_full_v1/studio.html

p1_head.html is the style (tokens copied from docs/arch/p1_head.html so studio looks
like the rest of the project), p2_body.html the DOM, p3..p11 the behaviour in load
order (p10 projects, p11 the block design, M18). One self-contained file, no external libraries, no network: the page talks only
to software/host/studio.py on localhost.
"""

import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "studio.html")

ORDER = ["p1_head.html", "p2_body.html"]


def build():
    head = open(os.path.join(HERE, "p1_head.html")).read()
    body = open(os.path.join(HERE, "p2_body.html")).read()
    # by part number, so p10 loads after p9 and not before p3
    js = sorted(glob.glob(os.path.join(HERE, "p*.js")),
                key=lambda p: int(os.path.basename(p)[1:].split("_", 1)[0]))
    script = "\n".join(f"/* ---- {os.path.basename(p)} ---- */\n" + open(p).read() for p in js)
    page = (
        "<!doctype html>\n<html lang=\"en\">\n<meta charset=\"utf-8\">\n"
        + head
        + "<body>\n"
        + body
        + "\n<script>\n"
        + script
        + "\n</script>\n</body>\n</html>\n"
    )
    open(OUT, "w").write(page)
    return page, js


def main():
    page, js = build()
    print(f"studio.html  {len(page) // 1024} KB from "
          f"p1_head.html, p2_body.html and {len(js)} script part(s)")
    for p in js:
        print(f"  {os.path.basename(p):20s} {sum(1 for _ in open(p)):5d} lines")


if __name__ == "__main__":
    main()
