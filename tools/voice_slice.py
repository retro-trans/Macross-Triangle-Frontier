"""Show or check one 80-row slice of the voice-clip translation (docs/voice_translation_brief.md).

Usage:
  python tools/voice_slice.py show <N> [--context K]   rows of slice N (K rows either side, marked ~)
  python tools/voice_slice.py check <N|all>            validate work/translation/en/voice/slices/vslice_NNN.en.json

show prints, per row: row number, clip id, speaker, clip length, Whisper's
flags, the missions whose scripts hold the clip number (a hint), the reason a
clip is skipped, and the Whisper transcript; for an operator or custom pilot,
the English other operators / pilots already have for the same clip number
("same no.", up to three), and for a clip with a sister clip of the same id, its
transcript and English ("ref").

check: every id of the slice once; no Japanese characters in the file; `en`
empty only with the flag no_subtitle or unfinished, or on a skipped row;
only characters the game font has (ASCII; "..." may be written as an ellipsis);
no '{'; the line fits the subtitle (wrapped to the box, at most 178 bytes in
all its parts); no glossary 'avoid' spelling. It also warns when a line is
long for the clip (more than ~17 characters per second of audio).
Exit code 1 on any error.
"""
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
VDIR = os.path.join(ROOT, "work", "translation", "en", "voice")
JP = re.compile("[%s-%s%s-%s%s-%s]" % tuple(map(chr, (0x3040, 0x30FF, 0x3400, 0x9FFF, 0xFF66, 0xFF9F))))
FLAGS = {"uncertain", "whisper_doubt", "no_subtitle", "kept_omission", "name_missing", "unfinished"}
SLICE = 80


def rows():
    """Rows that go into slices (repeats, `same_as`, are filled at export)."""
    d = json.load(open(os.path.join(VDIR, "voice.json"), encoding="utf-8"))
    return [r for r in d["rows"] if r["row"] <= d["_meta"]["slices"] * SLICE and not r.get("same_as")]


def avoid_list():
    out = []
    for f in glob.glob(os.path.join(ROOT, "work", "glossary", "*.json")):
        if f.endswith("gaps.json"):
            continue
        for v in json.load(open(f, encoding="utf-8")).values():
            if isinstance(v, list):
                for e in v:
                    if isinstance(e, dict):
                        out += [(a, e.get("en", "")) for a in e.get("avoid", []) or [] if a and not JP.search(a)]
    return out


GROUPS = {"operator": ("o0_of0", "o0_of1", "o0_of2", "o0_om0", "os_mis", "o7_exd", "of_ktr"),
          "custom pilot": ("p0_om0", "p0_om1", "p0_om2", "p0_of0", "p0_of1", "p0_of2",
                           "p__mv0", "p__mv1", "p__mv2", "p__fv0", "p__fv1", "p__fv2")}


def same_number():
    """(group, clip number) -> [(speaker, English)] of the clips that already have English:
    the operators read one script, the custom pilots share their clip numbers (a strong hint)."""
    d = json.load(open(os.path.join(VDIR, "voice.json"), encoding="utf-8"))
    out = {}
    for r in d["rows"]:
        for g, prefixes in GROUPS.items():
            if r["prefix"] in prefixes and r.get("en"):
                out.setdefault((g, r["num"]), []).append((r["speaker"], r["en"]))
    return out


def show(n, k=3):
    rs = rows()
    same = same_number()
    lo, hi = (n - 1) * SLICE + 1, n * SLICE
    for r in rs:
        if lo - k <= r["row"] <= hi + k:
            mark = " " if lo <= r["row"] <= hi else "~"
            extra = []
            if r["whisper"]:
                extra.append("whisper:" + ",".join(r["whisper"]))
            if r["skip"]:
                extra.append("SKIP: " + r["skip"])
            if r["missions"]:
                extra.append("missions:" + " ".join(r["missions"]))
            print("%s%5d %-14s %-22s %5.1fs %s" % (mark, r["row"], r["id"], r["speaker"][:22], r["dur"], "  ".join(extra)))
            print("        jp: %s" % r["jp"])
            if r.get("muf_ref"):
                m = r["muf_ref"]
                print("       ref: %s (%.1fs): %s" % (m.get("clip", "MUF " + r["id"]), m["dur"], m["jp"]))
                print("            ref en: %s" % (m["en"] or "(none)"))
            for g, prefixes in GROUPS.items():
                if r["prefix"] in prefixes:
                    for who, en in same.get((g, r["num"]), [])[:3]:
                        print("      same no. (%s): %s" % (who.split()[0], en.replace("\n", " / ")))
            if r.get("en"):
                print("        en: %s" % r["en"])


def check(n, rs=None, avoid=None):
    import voice_subs_at3 as A
    A.ADV = json.load(open(os.path.join(ROOT, "work", "output", "build", "vwf", "vwf_widths.json"), encoding="utf-8"))["advance"]
    rs = rs or rows()
    avoid = avoid if avoid is not None else avoid_list()
    errs, warns = [], []
    path = os.path.join(VDIR, "slices", "vslice_%03d.en.json" % n)
    if not os.path.exists(path):
        return ["missing " + path], []
    s = json.load(open(path, encoding="utf-8"))
    if JP.search(json.dumps(s, ensure_ascii=False)):
        errs.append("Japanese characters in the slice file")
    got = {}
    for t in s.get("rows", []):
        if t["id"] in got:
            errs.append("duplicate id " + t["id"])
        got[t["id"]] = t
    want = [r for r in rs if (n - 1) * SLICE < r["row"] <= n * SLICE]
    for r in want:
        t = got.get(r["id"])
        if not t:
            errs.append("row %d %s missing" % (r["row"], r["id"]))
            continue
        en, flags = t.get("en", ""), set(t.get("flags", []))
        if flags - FLAGS:
            errs.append("row %d unknown flags %s" % (r["row"], sorted(flags - FLAGS)))
        if not en:
            if not (flags & {"no_subtitle", "unfinished"}) and not r["skip"]:
                errs.append("row %d: empty en needs the flag no_subtitle or unfinished" % r["row"])
            continue
        bad = sorted(set(c for c in en if not (0x20 <= ord(c) < 0x7F or c in "…—–‘’“”\n")))
        if bad:
            errs.append("row %d: characters the font lacks: %s" % (r["row"], "".join(bad)))
            continue
        if "{" in en:
            errs.append("row %d: '{' starts a colour code" % r["row"])
        try:
            size = len(A.tail(A.parts_of(A.wrap(en)))) - 6
        except Exception as e:
            errs.append("row %d: %s" % (r["row"], e))
            continue
        if size > A.MAX_TEXT:
            errs.append("row %d: %d bytes, the limit is %d: shorten" % (r["row"], size, A.MAX_TEXT))
        if r["dur"] and len(en) > 17 * r["dur"] + 12:
            warns.append("row %d: %d characters for %.1f s of audio" % (r["row"], len(en), r["dur"]))
        for a, good in avoid:
            if re.search(r"\b%s\b" % re.escape(a), en):
                errs.append("row %d: '%s' is on the avoid list (use '%s')" % (r["row"], a, good))
    if s.get("rows_examined") != len(want):
        warns.append("rows_examined %s, rows in slice %d" % (s.get("rows_examined"), len(want)))
    return errs, warns


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, arg = sys.argv[1], sys.argv[2]
    if cmd == "show":
        k = int(sys.argv[sys.argv.index("--context") + 1]) if "--context" in sys.argv else 3
        show(int(arg), k)
        return
    rs, avoid = rows(), avoid_list()
    total = -(-len(rs) // SLICE)
    ns = range(1, total + 1) if arg == "all" else [int(arg)]
    bad = 0
    for n in ns:
        if arg == "all" and not os.path.exists(os.path.join(VDIR, "slices", "vslice_%03d.en.json" % n)):
            continue
        errs, warns = check(n, rs, avoid)
        for e in errs:
            print("slice %d ERROR %s" % (n, e))
        for w in warns:
            print("slice %d warn  %s" % (n, w))
        bad += bool(errs)
        if not errs:
            print("slice %d ok (%d warnings)" % (n, len(warns)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
