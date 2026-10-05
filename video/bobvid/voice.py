"""Narration: macOS `say` -> WAV, one file per sentence, cached by content.

A narration block is a list of sentences. Each is spoken to its own WAV, so the subtitle
can change exactly when the voice reaches the next sentence; the block's WAV is their
concatenation with a short gap, and `block()` returns where each sentence starts and ends.

Text may carry {shown|spoken} pairs: the caption shows the left side, the voice reads the
right. SPOKEN below fixes the words `say` would read wrongly, in the voice only.
"""

import hashlib
import os
import re
import subprocess
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "..", ".cache", "voice")

VOICE = os.environ.get("BOB_VOICE", "Daniel")
RATE = int(os.environ.get("BOB_RATE", "172"))      # words per minute
SR = 24000
GAP = 0.32                                         # seconds between sentences
TAIL = 0.45                                        # seconds after the last one

# Whole-word replacements applied to the spoken text only (order matters: longer first).
SPOKEN = [
    (r"\bDirtyJTAG\b", "Dirty J-tag"),
    (r"\bJTAG\b", "J-tag"),
    (r"\bPYNQ-Z2\b", "Pink Z 2"),
    (r"\bXC7Z020\b", "X C 7 Z 0 20"),
    (r"\bCFGLUT5s?\b", "config-lut-five"),
    (r"\bLUT6_2\b", "lut 6 2"),
    (r"\bLUT(\d)", r"lut \1"),
    (r"\bLUTs\b", "luts"),
    (r"\bLUT\b", "lut"),
    (r"\bLUTRAM\b", "lut ram"),
    (r"\bMUXF(\d)\b", r"mux F \1"),
    (r"\bMUXCY\b", "mux C Y"),
    (r"\bXORCY\b", "X-or C Y"),
    (r"\bBRAMs\b", "bee-rams"),
    (r"\bBRAM\b", "bee-ram"),
    (r"\bRAMB18\b", "ram B 18"),
    (r"\bDSP48E1\b", "D S P 48 E 1"),
    (r"\bUG(\d)(\d\d)\b", r"U G \1 \2"),
    (r"\byosys\b", "yo-sis"),
    (r"\bFASM\b", "fazzum"),
    (r"\bbitgen\b", "bit-gen"),
    (r"\bOpenFPGA\b", "Open F P G A"),
    (r"\bAegis\b", "Ee-jis"),
    (r"\bZUMA\b", "Zooma"),
    (r"\bPathFinder\b", "Path Finder"),
    (r"\bfabric_gen\b", "fabric gen"),
    (r"\bdevice\.py\b", "device dot pie"),
    (r"\bdevice\.json\b", "device dot jason"),
    (r"\.v\b", " dot V"),
    (r"\bFDRE\b", "F D R E"),
    (r"\bFDSE\b", "F D S E"),
    (r"\bSRVAL\b", "S R val"),
    (r"\bFDRI\b", "F D R I"),
    (r"\bFDRO\b", "F D R O"),
    (r"\bGRESTORE\b", "G restore"),
    (r"\bAGHIGH\b", "A G high"),
    (r"\bGHIGH_B\b", "G high bar"),
    (r"\bLFRM\b", "L F R M"),
    (r"\bWCFG\b", "W C F G"),
    (r"\bRCFG\b", "R C F G"),
    (r"\bRCRC\b", "R C R C"),
    (r"\bDESYNC\b", "de-sync"),
    (r"\bIDCODE\b", "I D code"),
    (r"\bUSERCODE\b", "user code"),
    (r"\bJPROGRAM\b", "J program"),
    (r"\bJSTART\b", "J start"),
    (r"\bCFG_IN\b", "config in"),
    (r"\bCFG_OUT\b", "config out"),
    (r"\bCFG_CTRL\b", "config control"),
    (r"\bCHAIN_IN\b", "chain in"),
    (r"\bCHAIN_OUT\b", "chain out"),
    (r"\bUSER(\d)\b", r"user \1"),
    (r"\bINTEST\b", "in-test"),
    (r"\bEXTEST\b", "ex-test"),
    (r"\bINIT_B\b", "init bar"),
    (r"\bINIT\b", "init"),
    (r"\bgce\b", "G C E"),
    (r"\bsysclk\b", "sys-clock"),
    (r"\bTCK\b", "T C K"),
    (r"\bO6\b", "O 6"),
    (r"\bO5\b", "O 5"),
    (r"\bfc\b", "F C"),
    (r"\bFs\b", "F S"),
    (r"\brr\b", "R R"),
    (r"\bdd\b", "D D"),
    (r"\bns\b", "nanoseconds"),
    (r"\bMHz\b", "megahertz"),
    (r"\bkHz\b", "kilohertz"),
    (r"(\d) × (\d)", r"\1 by \2"),
    (r"(\d)×(\d)", r"\1 by \2"),
    (r"→", " to "),
    (r"\bvs\b", "versus"),
    (r"\be\.g\.", "for example"),
    (r"\bi\.e\.", "that is"),
]

_PAIR = re.compile(r"\{([^{}|]*)\|([^{}]*)\}")


def shown(text):
    return _PAIR.sub(lambda m: m.group(1), text)


def spoken(text):
    s = _PAIR.sub(lambda m: "\x00" + m.group(2) + "\x01", text)
    out, i = [], 0
    # leave the explicit spoken parts untouched; fix everything else
    for part in re.split(r"(\x00[^\x01]*\x01)", s):
        if part.startswith("\x00"):
            out.append(part[1:-1])
        else:
            for pat, rep in SPOKEN:
                part = re.sub(pat, rep, part)
            out.append(part)
    return "".join(out)


def sentences(text):
    """Split a passage into sentences, keeping {a|b} pairs whole."""
    text = " ".join(text.split())
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(‘“{])", text)
    return [p for p in parts if p.strip()]


def _wav_len(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def say(text):
    """One sentence -> cached WAV path, duration."""
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.sha1(f"{VOICE}|{RATE}|{SR}|{text}".encode()).hexdigest()[:16]
    path = os.path.join(CACHE, f"s_{key}.wav")
    if not os.path.exists(path):
        tmp = path + ".tmp.wav"
        subprocess.run(["say", "-v", VOICE, "-r", str(RATE), "-o", tmp,
                        "--file-format=WAVE", f"--data-format=LEI16@{SR}", text],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.replace(tmp, path)
    return path, _wav_len(path)


def block(text):
    """A passage -> (wav path, total seconds, [(shown sentence, start, end)])."""
    sents = sentences(text)
    pieces, timing, t = [], [], 0.0
    for s in sents:
        p, d = say(spoken(s))
        pieces.append(p)
        timing.append((shown(s), t, t + d))
        t += d + GAP
    total = t - GAP + TAIL
    key = hashlib.sha1("|".join(pieces).encode()).hexdigest()[:16]
    path = os.path.join(CACHE, f"b_{key}.wav")
    if not os.path.exists(path):
        frames = []
        for i, p in enumerate(pieces):
            with wave.open(p) as w:
                frames.append(w.readframes(w.getnframes()))
            gap = GAP if i < len(pieces) - 1 else TAIL
            frames.append(b"\x00\x00" * int(SR * gap))
        tmp = path + ".tmp.wav"
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(b"".join(frames))
        os.replace(tmp, path)
    return path, total, timing
