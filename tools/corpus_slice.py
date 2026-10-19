"""Slice helpers for the Triangle Frontier translation corpus work/translation/en/corpus.json (tools/build_corpus.py).

  python tools/corpus_slice.py show <N> [--context K]   rows of slice N (+K rows either side, marked '~')
  python tools/corpus_slice.py check <N>|all            validate slices/slice_NN.en.json
  python tools/corpus_slice.py merge [--dry-run]        copy slice files into corpus.json
  python tools/corpus_slice.py export                   write corpus.en.json (no Japanese, for git)
                                                        and insert.json (one row per occurrence)
  python tools/corpus_slice.py width "<English text>" [--size S]   pixel width of a line

Slice file (UTF-8, no Japanese anywhere), every row of the slice, prefilled ones included:
  {"slice": N, "rows_in_slice": n, "rows_examined": n,
   "rows": [{"id": "u0001", "en": "...", "flags": [], "notes": ""}],
   "report": {"uncertain": [], "kept_omission": [], "missing_glossary": [], "unfinished": []}}

check: ids complete; no Japanese; en non-empty unless flagged 'unfinished'; placeholders
(%s %d %02d ..., {x...}) kept; same number of line breaks unless flagged 'reflow'; every
character encodable in Shift-JIS (cp932); max_bytes for in-place strings; no glossary
'avoid' spelling. Widths (warnings): each English line is measured with the VWF advances
(work/ui/vwf_widths.json) and compared with the limit of its group (the widest Japanese
line of that kind of text) or, for UI text, with the row's own Japanese width.
Exit 1 on any error.
"""
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMPUS = "--campus" in sys.argv  # the campus event scripts (tools/build_campus.py)
if CAMPUS:
    sys.argv.remove("--campus")
WORK = os.path.join(ROOT, "work", "translation", "en", "campus.json" if CAMPUS else "corpus.json")
SLDIR = os.path.join(ROOT, "work", "translation", "en", "slices_campus" if CAMPUS else "slices")
CAMPUS_LINES = 3  # campus message window: up to 3 lines
WIDTHS = os.path.join(ROOT, "work", "ui", "vwf_widths.json")
JP = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")
# placeholders that must survive: printf codes, colour codes, [speed:400] [wait:100] tags,
# and the campus player-name code \p (backslash + p)
PH = re.compile(r"%[0-9]*[sdcxX]|\{[a-z]|\[[a-z]+:[0-9]+\]|\\p")
# box width per group in px at 14 px text: the widest Japanese line of that group
# (unpatched game: double-byte 14 px, single-byte 10.5 px). UI groups use the row's own width.
# Triangle Frontier: the AF/MUF values until TF's boxes are measured in game; mission names,
# help and campus UI text use the row's own Japanese width.
GROUP_LIMIT = {"campus": 420, "choice": 420,  # campus window, 16 px font: measured in game (x 46-470)
               "unit_desc": 434, "profile": 441, "ingame": 308,
               "narration": 560,  # narration: 480 px screen at size 12
               "stage_weapon": 322, "skill": 266, "sound_test": 402}
# Briefing lines: TF holds a line in 79 bytes with its NUL (the Japanese first lines reach 78 bytes, never
# more); a 79-character line ran into the next one in 0.1.19 (MK_010: the whole text on line 1). MUF had 80.
# Occurrences that need other English than their row: the EBOOT copies these with a fixed length
# (inline_copy, docs/formats.md), so they must fit the Japanese bytes.
OCC_EN = {"eboot:40C6C0": "???"}  # 不明, copied as 5 bytes (4 + NUL) into a name field
MAX_CHARS = {"briefing": 78}  # characters per wrapped line
UI_SLACK = 1.25  # UI labels: warn above 125 % of the Japanese width (boxes are usually wider)

_adv = None


def adv():
    """Advances of the 14 px font, or in campus mode of the 16 px campus font (tools/vwf_build.py)."""
    global _adv
    if _adv is None:
        w = json.load(open(WIDTHS, encoding="utf-8"))
        _adv = w["font16"]["advance"] if CAMPUS else w["advance"]
    return _adv


def width(s, size=None):
    """Pixel width at `size` px (default: the font's own cell, 16 in campus mode, else 14).
    The player-name code \\p counts as a 10-letter name, tags such as [wait:100] as nothing."""
    cell = 16 if CAMPUS else 14
    size = size or cell
    a = adv()
    s = re.sub(r"%[0-9]*s", "W" * 10, s)
    s = re.sub(r"%[0-9]*d", "999", s)
    s = s.replace("\\p", "W" * 10)
    s = re.sub(r"\[[a-z]+:[0-9]+\]", "", s)
    w = 0
    for c in s:
        if c in a:
            w += size - round((cell - a[c]) * size / cell)
        else:
            w += size
    return w


def jp_width(s):
    return sum(14 if ord(c) > 0x7F else 10.5 for c in s)


def wrap(r, en):
    """Lines the build will draw for a re-wrapped row: head lines as written, then the
    rest as one paragraph wrapped greedily at r['wrap']['width'] px (and, for briefings,
    at MAX_CHARS: each line is copied into an 80-byte slot without a bounds check, so a
    longer line corrupts the next one, as found in MUF)."""
    w = r["wrap"]
    maxc = MAX_CHARS.get(r["group"], 9999)
    lines = en.split("\n")
    head, para = lines[:w["head"]], " ".join(x.strip() for x in lines[w["head"]:] if x.strip())
    out, cur = [], ""
    for word in para.split(" "):
        t = (cur + " " + word) if cur else word
        if cur and (width(t) > w["width"] or len(t.encode("cp932", "replace")) > maxc):  # bytes: ☆ is 2
            out.append(cur)
            cur = word
        else:
            cur = t
    if cur:
        out.append(cur)
    return head, out


def limit(r, line_jp):
    if r["group"] in GROUP_LIMIT:
        return GROUP_LIMIT[r["group"]]
    return max(56, jp_width(line_jp) * UI_SLACK)


def load():
    return json.load(open(WORK, encoding="utf-8"))


def show(n, ctx):
    rows = load()["rows"]
    idx = [i for i, r in enumerate(rows) if r["slice"] == n]
    lo, hi = max(0, idx[0] - ctx), min(len(rows), idx[-1] + ctx + 1)
    for r in rows[lo:hi]:
        mark = " " if r["slice"] == n else "~"
        extra = []
        if "max_bytes" in r:
            extra.append("MAX_BYTES=%d" % r["max_bytes"])
        if len(r["occ"]) > 1:
            extra.append("x%d" % len(r["occ"]))
        jl = r["jp"].split("\n")
        if "wrap" in r:
            extra.append("WRAP title_lines=%d max_lines=%d width=%dpx" % (r["wrap"]["head"], r["wrap"]["lines"], r["wrap"]["width"]))
        else:
            extra.append("box~%dpx" % max(limit(r, l) for l in jl))
        if CAMPUS:
            print("%s%s | %s | %-10s | %s | %s %s" % (mark, r["id"], r["scene"], r["speaker"], r["variant"],
                                                     r["status"], " ".join(extra)))
        else:
            print("%s%s | %s | %s | %s %s" % (mark, r["id"], r["group"], r["occ"][0]["id"], r["status"], " ".join(extra)))
        print("      JP: " + r["jp"].replace("\n", "<NL>"))
        if r["en"] and "wrap" in r:
            print("      EN: " + r["en"].replace("\n", "<NL>") + "   [wraps to %d lines]" % len(wrap(r, r["en"])[1]))
        elif r["en"]:
            print("      EN: " + r["en"].replace("\n", "<NL>") + "   [%s px]" % "/".join(str(width(l)) for l in r["en"].split("\n")))


def avoid_list():
    out = []
    for f in glob.glob(os.path.join(ROOT, "work", "glossary", "*.json")):
        if f.endswith("gaps.json"):
            continue
        for v in json.load(open(f, encoding="utf-8")).values():
            if isinstance(v, list):
                for e in v:
                    if isinstance(e, dict):
                        for a in e.get("avoid", []) or []:
                            if a and not JP.search(a) and a not in e.get("en", ""):
                                out.append((a, e.get("en", "")))
    return out


def check(n, rows, avoid):
    errs, warns = [], []
    path = os.path.join(SLDIR, ("slice_%03d.en.json" if CAMPUS else "slice_%02d.en.json") % n)
    if not os.path.exists(path):
        return ["missing " + path], []
    s = json.load(open(path, encoding="utf-8"))
    if JP.search(json.dumps(s, ensure_ascii=False)):
        errs.append("Japanese characters in slice file")
    got = {t["id"]: t for t in s["rows"]}
    want = [r for r in rows if r["slice"] == n]
    for r in want:
        t = got.get(r["id"])
        if not t:
            errs.append("%s missing" % r["id"])
            continue
        en, jp, fl = t.get("en", ""), r["jp"], t.get("flags", [])
        if not en:
            if "unfinished" not in fl:
                errs.append("%s empty en" % r["id"])
            continue
        if sorted(PH.findall(jp)) != sorted(PH.findall(en)):
            errs.append("%s placeholders %s -> %s" % (r["id"], PH.findall(jp), PH.findall(en)))
        if CAMPUS:
            if en.count("\n") + 1 > CAMPUS_LINES:
                warns.append("%s %d lines > %d" % (r["id"], en.count("\n") + 1, CAMPUS_LINES))
        elif "wrap" not in r and jp.count("\n") != en.count("\n") and "reflow" not in fl:
            warns.append("%s line breaks %d -> %d (flag 'reflow' if deliberate)" % (r["id"], jp.count("\n"), en.count("\n")))
        if "\\n" in en:
            errs.append("%s literal backslash-n (this game uses real newlines)" % r["id"])
        try:
            b = len(en.encode("cp932"))
            if "max_bytes" in r and b > r["max_bytes"]:
                errs.append("%s %d bytes > max %d: %r" % (r["id"], b, r["max_bytes"], en))
        except UnicodeEncodeError as e:
            errs.append("%s not Shift-JIS encodable: %r" % (r["id"], en[e.start:e.end]))
            continue
        for a, good in avoid:
            if re.search(r"(?<![A-Za-z])" + re.escape(a) + r"(?![A-Za-z])", en):
                errs.append("%s uses avoided '%s' (use '%s')" % (r["id"], a, good))
        if "wrap" in r:
            head, body = wrap(r, en)
            if len(head) != r["wrap"]["head"] or (head and not head[0].strip()):
                errs.append("%s needs %d title line(s) before the paragraph" % (r["id"], r["wrap"]["head"]))
            if len(body) > r["wrap"]["lines"]:
                warns.append("%s wraps to %d lines > %d at %d px (shorten)" % (
                    r["id"], len(body), r["wrap"]["lines"], r["wrap"]["width"]))
            for line in body:
                if width(line) > r["wrap"]["width"]:
                    warns.append("%s word wider than the box: %r" % (r["id"], line))
            continue
        jl = jp.split("\n")
        for i, line in enumerate(en.split("\n")):
            lim = limit(r, jl[min(i, len(jl) - 1)])
            w = width(line)
            if w > lim:
                warns.append("%s line %d is %d px > %d px: %r" % (r["id"], i + 1, w, lim, line))
    extra = set(got) - {r["id"] for r in want}
    if extra:
        errs.append("ids not in slice: %s" % sorted(extra)[:5])
    return errs, warns


def main():
    cmd = sys.argv[1]
    if cmd == "show":
        ctx = int(sys.argv[sys.argv.index("--context") + 1]) if "--context" in sys.argv else 5
        show(int(sys.argv[2]), ctx)
    elif cmd == "width":
        size = int(sys.argv[sys.argv.index("--size") + 1]) if "--size" in sys.argv else 14
        for line in sys.argv[2].split("\\n"):
            print(width(line, size), "px:", line)
    elif cmd == "check":
        rows = load()["rows"]
        avoid = avoid_list()
        nums = sorted({r["slice"] for r in rows}) if sys.argv[2] == "all" else [int(sys.argv[2])]
        bad = False
        for n in nums:
            e, w = check(n, rows, avoid)
            print("slice %02d: %d errors, %d warnings" % (n, len(e), len(w)))
            for x in e:
                print("  ERROR", x)
            for x in w:
                print("  warn ", x)
            bad |= bool(e)
        sys.exit(1 if bad else 0)
    elif cmd == "merge":
        d = load()
        by = {r["id"]: r for r in d["rows"]}
        n = 0
        for f in sorted(glob.glob(os.path.join(SLDIR, "slice_*.en.json"))):  # corpus or campus slices
            for t in json.load(open(f, encoding="utf-8"))["rows"]:
                r = by.get(t["id"])
                if r is None:
                    print("unknown id", t["id"], f)
                    continue
                if r["status"] == "not_text":  # data that decodes as text (dump_eboot NOT_TEXT): never written
                    continue
                if t.get("en") and (r["en"] != t["en"] or r["status"] != "done"):
                    n += 1
                r["en"], r["flags"], r["notes"] = t.get("en", ""), t.get("flags", []), t.get("notes", "")
                if r["en"]:
                    r["status"] = "done"
        print("updated %d rows; done %d/%d" % (n, sum(r["status"] == "done" for r in d["rows"]), len(d["rows"])))
        if "--dry-run" not in sys.argv:
            with open(WORK, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
    elif cmd == "export":
        d = load()
        safe = {"_meta": d["_meta"], "rows": [
            dict({k: v for k, v in r.items() if k not in ("jp", "occ")},
                 occ=[{k: v for k, v in o.items() if k != "src_jp"} for o in r.get("occ", [])])
            for r in d["rows"]]}
        if JP.search(json.dumps(safe, ensure_ascii=False)):
            sys.exit("ERROR: Japanese left in export")
        with open(WORK[:-5] + ".en.json", "w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False, indent=1)
        ins = []
        for r in d["rows"]:
            if r["en"] and r["status"] != "not_text":
                en = r["en"]
                if "wrap" in r:  # the build-time wrap the check measured (docs/translation_brief.md)
                    head, body = wrap(r, en)
                    en = "\n".join(head + body) + ("\n" if r["wrap"]["tail_newline"] else "")
                for o in r["occ"]:
                    row = {"id": o["id"], "jp": r["jp"], "ref": o["ref"], "en": OCC_EN.get(o["id"], en)}
                    if o.get("lit_nl"):  # CSV cells and .gop strings store a line break as backslash + n
                        row["lit_nl"] = True
                    if o.get("src_jp"):  # the source text differs from the row's Japanese (a mistyped break)
                        row["src_jp"] = o["src_jp"]
                    ins.append(row)
        name = "insert_campus.json" if CAMPUS else "insert.json"
        with open(os.path.join(os.path.dirname(WORK), name), "w", encoding="utf-8") as f:
            json.dump({"rows": ins}, f, ensure_ascii=False, indent=1)
        print("wrote %s (%d rows) and %s (%d occurrences)" % (
            os.path.basename(WORK)[:-5] + ".en.json", len(safe["rows"]), name, len(ins)))


if __name__ == "__main__":
    main()
