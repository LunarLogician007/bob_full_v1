#!/usr/bin/env python3
"""Render the film.

  build.py --list                     the chapters
  build.py --preview [ch03 ...]       480p15 into out/preview/, stills and a contact sheet
  build.py --final   [ch03 ...]       1080p30 into out/chNN.mp4 (partial files deleted after)
  build.py --join                     out/bob_explained.mp4 + .srt from the final chapters

Run with the bobvideo env's python (see README.md). Facts first: python3 facts.py.
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCENES = os.path.join(HERE, "scenes")
OUT = os.path.join(HERE, "out")
MEDIA = os.path.join(HERE, ".cache", "media")
BIN = os.path.dirname(sys.executable)


def tool(name):
    p = os.path.join(BIN, name)
    return p if os.path.exists(p) else name


def chapters():
    out = []
    for f in sorted(glob.glob(os.path.join(SCENES, "ch[0-9][0-9]_*.py"))):
        src = open(f).read()
        cls = re.search(r"^class (Ch\d\d\w+)\(BobScene\)", src, re.M).group(1)
        ch = os.path.basename(f)[:4]
        title = re.search(r'TITLE = "(.*?)"', src).group(1)
        out.append((ch, f, cls, title))
    return out


def pick(names):
    all_ = chapters()
    if not names:
        return all_
    return [c for c in all_ if c[0] in names or c[0][2:] in names]


def render(ch, path, cls, quality):
    args = [tool("manim"), "--media_dir", MEDIA, "--disable_caching", "-v", "WARNING", "--progress_bar", "none"]
    if quality == "preview":
        args += ["-ql"]
    else:
        args += ["--resolution", "1920,1080", "--frame_rate", "30"]
    args += [path, cls]
    print(f"[{ch}] rendering {quality} ...", flush=True)
    subprocess.run(args, check=True, cwd=HERE)
    res = "480p15" if quality == "preview" else "1080p30"
    mod = os.path.splitext(os.path.basename(path))[0]
    vid = os.path.join(MEDIA, "videos", mod, res, f"{cls}.mp4")
    if not os.path.exists(vid):
        sys.exit(f"[{ch}] no output at {vid}")
    return vid, os.path.join(MEDIA, "videos", mod, res)


def duration(path):
    r = subprocess.run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def srt_starts(ch):
    p = os.path.join(HERE, "script", f"{ch}.srt")
    if not os.path.exists(p):
        return []
    ts = re.findall(r"^(\d\d):(\d\d):(\d\d),(\d\d\d) -->", open(p).read(), re.M)
    return [int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000 for h, m, s, ms in ts]


def stills(ch, vid):
    """One still 1.2 s into every caption, and a contact sheet of them."""
    d = os.path.join(OUT, "stills", ch)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    paths = []
    for i, t in enumerate(srt_starts(ch)):
        p = os.path.join(d, f"{i:03d}.png")
        subprocess.run([tool("ffmpeg"), "-v", "error", "-y", "-ss", f"{t + 1.2:.2f}", "-i", vid,
                        "-frames:v", "1", "-vf", "scale=854:-2", p], check=True)
        if os.path.exists(p):
            paths.append(p)
    try:
        from PIL import Image
    except ImportError:
        return
    if not paths:
        return
    ims = [Image.open(p) for p in paths]
    w, h = ims[0].size
    cols = 3
    rows = (len(ims) + cols - 1) // cols
    for page in range(0, rows, 4):
        sheet = Image.new("RGB", (w * cols, h * min(4, rows - page)), "black")
        for k, im in enumerate(ims[page * cols:(page + 4) * cols]):
            sheet.paste(im, ((k % cols) * w, (k // cols) * h))
        sheet.save(os.path.join(d, f"sheet_{page // 4}.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--join", action="store_true")
    ap.add_argument("chapters", nargs="*")
    a = ap.parse_args()

    if a.list or not (a.preview or a.final or a.join):
        for ch, f, cls, title in chapters():
            fin = os.path.join(OUT, f"{ch}.mp4")
            state = f"{duration(fin) / 60:5.1f} min" if os.path.exists(fin) else "  (not rendered)"
            print(f"{ch}  {title:42s} {state}")
        return

    os.makedirs(OUT, exist_ok=True)
    for ch, f, cls, title in pick(a.chapters) if (a.preview or a.final) else []:
        if a.preview:
            vid, _ = render(ch, f, cls, "preview")
            d = os.path.join(OUT, "preview")
            os.makedirs(d, exist_ok=True)
            dst = os.path.join(d, f"{ch}.mp4")
            shutil.copyfile(vid, dst)
            stills(ch, dst)
            print(f"[{ch}] {duration(dst) / 60:.1f} min -> {os.path.relpath(dst, HERE)}")
        if a.final:
            vid, resdir = render(ch, f, cls, "final")
            dst = os.path.join(OUT, f"{ch}.mp4")
            shutil.move(vid, dst)
            shutil.rmtree(resdir, ignore_errors=True)       # partial movie files
            stills(ch, dst)
            print(f"[{ch}] {duration(dst) / 60:.1f} min -> {os.path.relpath(dst, HERE)}")

    if a.join:
        parts = [(ch, os.path.join(OUT, f"{ch}.mp4")) for ch, _, _, _ in chapters()]
        missing = [ch for ch, p in parts if not os.path.exists(p)]
        if missing:
            sys.exit(f"render these first: {' '.join(missing)}")
        lst = os.path.join(OUT, "concat.txt")
        with open(lst, "w") as fh:
            for _, p in parts:
                fh.write(f"file '{p}'\n")
        film = os.path.join(OUT, "bob_explained.mp4")
        subprocess.run([tool("ffmpeg"), "-v", "error", "-y", "-f", "concat", "-safe", "0",
                        "-i", lst, "-c", "copy", "-movflags", "+faststart", film], check=True)
        os.remove(lst)
        # one .srt for the whole film
        n, off, out = 1, 0.0, []
        for ch, p in parts:
            src = os.path.join(HERE, "script", f"{ch}.srt")
            for blk in open(src).read().strip().split("\n\n"):
                lines = blk.splitlines()
                if len(lines) < 3:
                    continue
                a_, b_ = [_shift(t, off) for t in lines[1].split(" --> ")]
                out.append(f"{n}\n{a_} --> {b_}\n" + "\n".join(lines[2:]) + "\n")
                n += 1
            off += duration(p)
        with open(os.path.join(OUT, "bob_explained.srt"), "w") as fh:
            fh.write("\n".join(out))
        print(f"film: {duration(film) / 60:.1f} min -> {os.path.relpath(film, HERE)}")


def _shift(t, off):
    h, m, rest = t.split(":")
    s, ms = rest.split(",")
    v = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000 + off
    ms = int(round(v * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


if __name__ == "__main__":
    main()
