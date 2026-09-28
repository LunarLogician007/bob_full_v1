"""
software/studio/: the page's own state, run without a browser.

studio.html's script runs under JavaScriptCore (macOS's `osascript -l JavaScript`), its
DOM calls absorbed by a stand-in and /api answered by a fake backend
(tests/studio_page.js). That checks what the backend tests in test_studio.py cannot:
what the page carries from one project to the next. A block design on the canvas
belongs to the project that was open (it used to stay when an example or another
project was opened), and unsaved edits to it are not dropped without asking.
"""

import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

pytestmark = pytest.mark.skipif(sys.platform != "darwin" or shutil.which("osascript") is None,
                                reason="needs macOS's JavaScriptCore (osascript)")


def test_the_block_design_follows_the_project(tmp_path):
    page = open(os.path.join(ROOT, "software", "studio", "studio.html")).read()
    script = "\n".join(re.findall(r"<script>(.*?)</script>", page, re.S))
    out = tmp_path / "out.txt"
    harness = open(os.path.join(ROOT, "tests", "studio_page.js")).read()
    src = tmp_path / "page.js"
    src.write_text(harness.replace("// @@SCRIPT@@", script).replace("@@OUT@@", str(out)))
    r = subprocess.run(["osascript", "-l", "JavaScript", str(src)], capture_output=True, text=True, timeout=60)
    assert out.exists(), r.stderr[-2000:]
    lines = out.read_text().splitlines()
    assert lines and all(ln.startswith("ok") for ln in lines), "\n".join(lines)
    assert len(lines) == 12, "\n".join(lines)
