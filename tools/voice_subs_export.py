"""Collect the voice subtitles for the build (docs/voice_subtitles.md).

Usage: python tools/voice_subs_export.py [out.json]
Reads the work file (work/translation/en/voice/voice.json; rows marked `muf`
already hold Ultimate Frontier's English, tools/voice_rows.py) and the slices
(work/translation/en/voice/slices/vslice_*.en.json; the slices win), gives each
repeat (`same_as`) the English of the clip it repeats, and writes
[{"id", "en"}] to work/translation/en/voice/voice_subs.en.json (or out.json),
the file tools/build_iso.py --voice-subs takes. Rows with no English (skipped,
no_subtitle, unfinished) are left out.
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VDIR = os.path.join(ROOT, "work", "translation", "en", "voice")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(VDIR, "voice_subs.en.json")
    rows = json.load(open(os.path.join(VDIR, "voice.json"), encoding="utf-8"))["rows"]
    en = {r["id"]: r.get("en", "") for r in rows}
    for p in sorted(glob.glob(os.path.join(VDIR, "slices", "vslice_*.en.json"))):
        for r in json.load(open(p, encoding="utf-8"))["rows"]:
            en[r["id"]] = r.get("en", "")
    for r in rows:
        if r.get("same_as"):
            en[r["id"]] = en.get(r["same_as"], "")
    subs = [{"id": r["id"], "en": en[r["id"]]} for r in rows if en.get(r["id"]) and not r["skip"].startswith(("sound", "era", "no speech"))]
    json.dump(subs, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("%d of %d clips have a subtitle -> %s" % (len(subs), len(rows), out))


if __name__ == "__main__":
    main()
