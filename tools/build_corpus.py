"""Build the translation work file: every distinct Japanese string of Triangle Frontier
outside the campus event scripts, once (those go to tools/build_campus.py).

Usage: python tools/build_corpus.py [--dry-run]

Sources (tools/dump_text.py, tools/dump_eboot.py; work/source/text/):
  eboot_strings.json   menus, system and network messages, mission names and objectives,
                       weapons, units, skills, titles, unlock conditions, gallery, songs
  menu_text.json       data/menu/text/*.csv: briefings, unit/pack/pilot/operator/BGM
                       descriptions, Nyan-Nyan collection
  fes_strings.json     mission script strings (objectives, tutorial)
  locate_names.json    mission unit display names
  gop_strings.json     campus data tables: era narration, event and gallery titles, places,
                       skills, help, operator help, staff roll

Each distinct Japanese string becomes ONE row with every place it occurs in "occ".
Rows are in source order, so neighbours give context. CSV cells and .gop strings store a
line break as the two characters backslash + n; here it is a real newline (converted back
on insertion, occ "lit_nl": true). Story-like groups are cut into slices of 80 rows (BASE_RULES), UI
groups into slices of up to 4,500 characters / 320 rows (as in AF and MUF).

Prefill (status "tm"): where Macross Ultimate Frontier or Macross Ace Frontier has
translated the identical Japanese, its English is copied; translators review it.

Output: work/translation/en/corpus.json (gitignored: contains Japanese). Existing
English/flags/notes are carried over by the Japanese text.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT = os.path.join(ROOT, "work", "source", "text")
OUT = os.path.join(ROOT, "work", "translation", "en", "corpus.json")
MUF_TR = os.path.join(ROOT, "..", "Macross Ultimate Frontier", "work", "translation", "en")
AF_TR = os.path.join(ROOT, "..", "Macross Ace Frontier", "work", "translation", "en")
JPW = re.compile(r"[぀-ヿ㐀-鿿]")
INTERNAL = re.compile(r"デモ用|顔絵用|フェイス用|ダミー|^削除$|テスト|予定|用$|演出用|セリフ用|カメラ位置用")
STORY = {"mission", "narration", "profile", "unit_desc", "ingame", "briefing", "quote", "help"}
SLICE_ROWS_STORY = 80
SLICE_CHARS, SLICE_ROWS = 4500, 320
MIN_SLICE = 20
NL = chr(10)
BS_N = chr(92) + "n"  # the two characters backslash + n
FW_N = "\uffe5\uff4e"  # full-width yen + n: one briefing has it where a line break belongs

# EBOOT file offset ranges -> group (docs/formats.md)
RANGES = [
    (0x3CFDD0, 0x3D4DC0, "pilot_table"),
    (0x3F3588, 0x3F79C0, "mission"),
    (0x3F79C0, 0x3FBCA0, "stage_weapon"),
    (0x3FBCA0, 0x3FE900, "unit_desc"),
    (0x400340, 0x402440, "skill"),
    (0x410EDC, 0x412BA0, "rank"),
    (0x412BA0, 0x415048, "title"),
    (0x41B004, 0x41BC20, "sound_test"),
]
CSV_GROUP = {
    ("mission_ext.csv", "strMission"): "mission",
    ("mission_ext.csv", "strStory"): "briefing",
    ("ms_ext.csv", "strDescription"): "unit_desc",
    ("pack_ext.csv", "strDescription"): "unit_desc",
    ("pilot_ext.csv", "strDescription"): "profile",
    ("operator_ext.csv", "strDescription"): "profile",
    ("bgm_ext.csv", "strDescription"): "sound_test",
}
GOP_GROUP = {
    "gop_campaignevent": "narration",
    "gop_opehelp": "help",
    "gop_help": "help",
    "gop_charboost": "help",
    "gop_skill": "skill",
    "gop_staffroll": "sound_test",
}


def group_of(off):
    for lo, hi, g in RANGES:
        if lo <= off < hi:
            return g
    return "ui"


def nn_group(key):
    k = int(key[-4:])
    return "quote" if 5000 <= k < 5300 else "ui"


def tm():
    """Japanese -> English from the MUF and AF translations (MUF first: it shipped later)."""
    out = {}
    for path in [os.path.join(MUF_TR, f) for f in ("dialogue.json", "ui.json", "internal_labels.json",
                                                    "ui_insert.json")] + [os.path.join(AF_TR, "corpus.json")]:
        if not os.path.exists(path):
            continue
        d = json.load(open(path, encoding="utf-8"))
        for r in (d["rows"] if isinstance(d, dict) else d):
            if r.get("jp") and r.get("en"):
                jp = r["jp"].replace(BS_N, NL)
                out.setdefault(jp, r["en"].replace(BS_N, NL))
    return out


def load(name):
    return json.load(open(os.path.join(TEXT, name), encoding="utf-8"))


def main():
    dry = "--dry-run" in sys.argv
    occ = []
    skipped = {"no_japanese": 0, "tail": 0, "internal": 0}
    for x in sorted(load("eboot_strings.json"), key=lambda e: e["offset"]):
        if x.get("tail_of"):
            skipped["tail"] += 1
            continue
        if not JPW.search(x["jp"]):
            skipped["no_japanese"] += 1
            continue
        o = {"id": x["id"], "ref": {"file": "EBOOT.BIN", "offset": x["offset"], "bytes": x["bytes"]}}
        if x.get("in_place") or x.get("inline_copy"):
            o["max_bytes"] = x["capacity"] - 1
        if x.get("note"):  # not text (dump_eboot NOT_TEXT): kept so row ids stay stable, never translated
            o["not_text"] = x["note"]
        occ.append((group_of(x["offset"]), x["jp"], o))
    for x in load("menu_text.json"):
        name = x["source"].rsplit("/", 1)[-1]
        g = nn_group(x["key"]) if name == "nn_ext.csv" else CSV_GROUP.get((name, x["field"]), "ui")
        if not JPW.search(x["jp"]):
            skipped["no_japanese"] += 1
            continue
        o = {"id": "csv:" + x["id"], "lit_nl": BS_N in x["jp"] or FW_N in x["jp"]}
        if FW_N in x["jp"]:  # a mistyped line break (u3200): wrap like the others, check against the source
            o["src_jp"] = x["jp"]
        occ.append((g, x["jp"].replace(BS_N, NL).replace(FW_N, NL), dict(o, **{
                                                   "ref": {"file": x["source"], "row": x["row"], "col": x["col"],
                                                           "key": x["key"]}})))
    for x in load("fes_strings.json"):
        occ.append(("ingame", x["jp"], {"id": "fes:" + x["id"], "ref": {"file": x["source"], "offset": x["offset"],
                                                                        "pool_offset": x["pool_offset"],
                                                                        "bytes": x["bytes"]}}))
    for x in load("locate_names.json"):
        if INTERNAL.search(x["jp"]):
            skipped["internal"] += 1
            continue
        if not JPW.search(x["jp"]):
            skipped["no_japanese"] += 1
            continue
        occ.append(("locate", x["jp"], {"id": "locate:" + x["id"], "lit_nl": BS_N in x["jp"],
                                        "ref": {"file": x["source"], "row": x["row"], "col": x["col"],
                                                "key": x["key"]}}))
    for x in load("gop_strings.json"):
        stem = x["source"].rsplit("/", 1)[-1][:-4]
        occ.append((GOP_GROUP.get(stem, "campus_ui"), x["jp"].replace(BS_N, NL),
                    {"id": "gop:" + x["id"], "lit_nl": BS_N in x["jp"],
                     "ref": {"file": x["source"], "index": x["index"], "key": x["key"]}}))

    rows, by_jp = [], {}
    for grp, jp, o in occ:
        if jp not in by_jp:
            by_jp[jp] = {"group": grp, "jp": jp, "occ": []}
            rows.append(by_jp[jp])
        r = by_jp[jp]
        r["occ"].append(o)
        if "max_bytes" in o:
            r["max_bytes"] = min(r.get("max_bytes", 9999), o["max_bytes"])

    # re-wrapped text: hard-wrapped Japanese (often mid-word) is written as one paragraph
    # and wrapped at build time; wrap = {head, lines, width px at 14 px}
    for r in rows:
        body = r["jp"].split(NL)
        tail = body[-1] == ""
        if tail:
            body = body[:-1]
        head = 0
        if r["group"] == "briefing" and len(body) >= 2:
            pass
        elif r["group"] == "profile" and len(body) >= 2 and max(map(len, body)) >= 25:
            pass
        elif r["group"] == "unit_desc" and len(body) >= 3 and max(map(len, body[1:])) >= 25:
            head = 1
        else:
            continue
        r["wrap"] = {"head": head, "lines": len(body) - head, "tail_newline": tail}
    for g in ("briefing", "profile", "unit_desc"):
        w = [len(l) for r in rows if r["group"] == g and "wrap" in r for l in r["jp"].split(NL)[r["wrap"]["head"]:]]
        for r in rows:
            if r["group"] == g and "wrap" in r:
                r["wrap"]["width"] = max(w) * 14

    mem = tm()
    old = {}
    if os.path.exists(OUT):
        old = {r["jp"]: r for r in json.load(open(OUT, encoding="utf-8"))["rows"]}
    sl, chars, n_in, story_prev = 0, 0, 0, None
    for i, r in enumerate(rows, 1):
        story = r["group"] in STORY
        full = (n_in >= SLICE_ROWS_STORY) if story else (chars + len(r["jp"]) > SLICE_CHARS or n_in >= SLICE_ROWS)
        if sl == 0 or full or story != story_prev:
            sl, chars, n_in = sl + 1, 0, 0
        story_prev = story
        chars += len(r["jp"])
        n_in += 1
        r["row"], r["slice"], r["id"] = i, sl, "u%04d" % i
        o = old.get(r["jp"], {})
        if any("not_text" in x for x in r["occ"]):
            r["en"], r["flags"], r["notes"], r["status"] = "", [], r["occ"][0]["not_text"], "not_text"
        elif o.get("en"):
            r["en"], r["flags"], r["notes"], r["status"] = o["en"], o.get("flags", []), o.get("notes", ""), o.get("status", "done")
        elif r["jp"] in mem:
            r["en"], r["flags"], r["notes"], r["status"] = mem[r["jp"]], [], "prefilled from the MUF/AF translation", "tm"
        else:
            r["en"], r["flags"], r["notes"], r["status"] = "", [], "", "todo"

    sizes = {}
    for r in rows:
        sizes[r["slice"]] = sizes.get(r["slice"], 0) + 1
    remap, n = {}, 0
    for k in sorted(sizes):
        if sizes[k] >= MIN_SLICE or n == 0:
            n += 1
        remap[k] = n
    for r in rows:
        r["slice"] = remap[r["slice"]]
    sl = n

    groups = {}
    for r in rows:
        g = groups.setdefault(r["group"], [0, 0, 0])
        g[0] += 1
        g[1] += r["status"] == "tm"
        g[2] += len(r["jp"])
    print("rows %d (occurrences %d), slices %d, chars %d" % (len(rows), len(occ), sl, sum(len(r["jp"]) for r in rows)))
    print("group: rows / prefilled / chars")
    for g, (n, t, c) in sorted(groups.items(), key=lambda kv: -kv[1][0]):
        print("  %-13s %5d %5d %6d" % (g, n, t, c))
    print("skipped", skipped, " prefilled", sum(r["status"] == "tm" for r in rows),
          " in-place limited", sum("max_bytes" in r for r in rows),
          " re-wrapped", {g: sum(1 for r in rows if r["group"] == g and "wrap" in r) for g in ("briefing", "profile", "unit_desc")})
    per = {}
    for r in rows:
        per.setdefault(r["slice"], [r["group"], 0, 0])
        per[r["slice"]][1] += 1
        per[r["slice"]][2] += r["status"] == "todo"
    print("slices:", ", ".join("%d:%s %d (%d todo)" % (k, v[0], v[1], v[2]) for k, v in sorted(per.items())))
    if dry:
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"_meta": {"version": "0.1.0", "slice_rows_story": SLICE_ROWS_STORY, "slice_chars": SLICE_CHARS,
                             "slice_rows": SLICE_ROWS}, "rows": rows}, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
