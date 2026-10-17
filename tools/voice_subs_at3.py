"""Append English subtitle lines to the voice clips (docs/voice_subtitles.md).

Usage:
  python tools/voice_subs_at3.py --out <overlay dir> <subs.json> [...]
  python tools/voice_subs_at3.py --out <overlay dir> --placeholder [--only PREFIX]

Writes <overlay>/data/sound/voice/<clip>.at3 = the original clip + a tail

    part 1 NUL [part 2 NUL ...] | u16 len (all parts and NULs) | u16 parts | "SB"

that the EBOOT patch (tools/voice_subs_patch.py) reads when the clip is queued
and shows while the clip plays. The RIFF header is not changed, so the player
stops at the end of the audio.

A clip id is the path under data/sound/voice/ without ".at3": in Triangle
Frontier "<speaker>/<num>", e.g. "p7_mln/000" (the %s of the game's
data/sound/vad/%s.vad path). The clips are raw RIFF files in macross.dat, so
the tail lands in the stored bytes the hook reads; muf_archive.py repack writes
the new offset and size (stored length 0) and leaves the copies in the cv_*
fileset bundles alone (DAT_ONLY).

subs.json: a list of rows {"id": "<clip>", "en": "<line>"} (other keys are
ignored) or a dict {clip: line} (voice_subs_export.py writes
work/translation/en/voice/voice_subs.en.json). Later files win. Rows with an
empty "en" are skipped.

The line is wrapped to the subtitle box (CONFIG in voice_subs_patch.py) with
the VWF widths. A line of more than MAX_LINES lines is cut into parts of at
most MAX_LINES lines, shown one after the other at even steps of the clip.
All parts together must fit in TAIL - 6 bytes.

--placeholder writes "<clip id>" for every voice clip (to test the hooks
without a translation); --only PREFIX limits it to ids that start with PREFIX
(e.g. "o0_" for the operators).
"""

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_subs_patch as P  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOICE = os.path.join(ROOT, "work", "source", "dat", "data", "sound", "voice")
SIZE, BOX_W, LINE_STEP = P.CONFIG[2], P.CONFIG[3], P.CONFIG[7]
MAX_LINES = 3
MAX_TEXT = P.TAIL - 6       # the patch reads the last TAIL bytes of the clip


ADV = None  # VWF advance per ASCII 0x20-0x7F at 14 px (vwf_widths.json)


def width(s):
    """Pixel width at SIZE, the way the game scales the VWF advances (docs/vwf.md)."""
    w = 0
    for ch in s:
        o = ord(ch)
        w += SIZE - round((14 - ADV[o - 0x20]) * SIZE / 14) if 0x20 <= o < 0x80 else SIZE
    return w


def wrap(text):
    """Greedy wrap to BOX_W; keeps explicit newlines."""
    out = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            cand = word if not line else line + " " + word
            if line and width(cand) > BOX_W:
                out.append(line)
                line = word
            else:
                line = cand
        out.append(line)
    return out


ASCII_FIX = {"…": "\x7f", "—": "-", "–": "-", "‘": "'", "’": "'",
             "“": '"', "”": '"', " ": " "}


def encode(text):
    text = "".join(ASCII_FIX.get(c, c) for c in text)
    if "{" in text:
        raise ValueError("'{' starts a colour code: %r" % text)
    return text.encode("cp932")


def parts_of(lines):
    """Cut wrapped lines into parts of at most MAX_LINES lines, as even as possible."""
    n = -(-len(lines) // MAX_LINES)
    out, i = [], 0
    for p in range(n):
        k = -(-(len(lines) - i) // (n - p))
        out.append(lines[i:i + k])
        i += k
    return out


def tail(parts):
    body = b"".join(encode("\n".join(p)) + b"\0" for p in parts)
    return body + struct.pack("<HH", len(body), len(parts)) + b"SB"


def load_subs(paths):
    subs = {}
    for p in paths:
        d = json.load(open(p, encoding="utf-8"))
        if isinstance(d, dict):
            subs.update({k: v for k, v in d.items() if v})
        else:
            subs.update({r["id"]: r["en"] for r in d if r.get("en")})
    return subs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("subs", nargs="*")
    ap.add_argument("--out", required=True)
    ap.add_argument("--placeholder", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--widths", default=os.path.join(ROOT, "work", "output", "build", "vwf", "vwf_widths.json"))
    a = ap.parse_args()
    global ADV
    ADV = json.load(open(a.widths, encoding="utf-8"))["advance"]

    clips = sorted(os.path.relpath(os.path.join(d, f), VOICE)[:-4].replace(os.sep, "/")
                   for d, _, fs in os.walk(VOICE) for f in fs if f.endswith(".at3"))
    if a.placeholder:
        # voice clips only (<speaker>/<num>); the sound effects at the top have no .vad
        subs = {c: c for c in clips if "/" in c and c.startswith(a.only)}
    else:
        subs = load_subs(a.subs)
    out_dir = os.path.join(a.out, "data", "sound", "voice")
    os.makedirs(out_dir, exist_ok=True)
    long_lines, too_long, written = [], [], 0
    for cid, en in sorted(subs.items()):
        if ".." in cid.split("/") or cid.startswith("/"):
            raise ValueError("bad clip id %r" % cid)
        src = os.path.join(VOICE, *(cid + ".at3").split("/"))
        if not os.path.exists(src):
            print("no clip", cid)
            continue
        data = open(src, "rb").read()
        parts = parts_of(wrap(en))
        if len(parts) > 1:
            long_lines.append((cid, len(parts), en))
        t = tail(parts)
        if len(t) - 6 > MAX_TEXT:
            too_long.append((cid, len(t) - 6, en))
            continue
        dst = os.path.join(out_dir, *(cid + ".at3").split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(data + t)
        written += 1
    print("%d clips with a subtitle -> %s" % (written, out_dir))
    if long_lines:
        print("%d lines are shown in parts of up to %d lines" % (len(long_lines), MAX_LINES))
    if too_long:
        print("%d lines do not fit in %d bytes and were left out:" % (len(too_long), MAX_TEXT))
        for cid, n, en in too_long:
            print("  %s (%d bytes): %s" % (cid, n, en))


if __name__ == "__main__":
    main()
