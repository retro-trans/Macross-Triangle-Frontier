"""Build the campus (Academy mode) translation work file from the event scripts.

Usage: python tools/build_campus.py [--dry-run]

Reads data/campus/event/script/*/*.asb (tools/asb.py) and the character table
data/campus/gop/gop_char.gop. Every text push that is an argument of a display call
becomes an occurrence; each distinct Japanese line becomes ONE row (first occurrence
order: script by script, line by line), with every place it occurs in "occ".

Context for translators, per row:
  speaker   who says it: the argument of the last call 0x1D (the name plate) before the
            line: 0 = no name plate (the player, or narration), else the record of
            gop_char.gop in order (SPEAKERS),
            "choice" for menu choices (call 0x01), "-" when unknown
  scene     the script file
  variant   the label the line is in: ..._male / ..._female (player gender), default...
Slices of 80 rows (BASE_RULES), never across a script boundary when avoidable
(a slice closes at a script end once it holds 60+ rows).

Output: work/translation/en/campus.json (gitignored: contains Japanese).
Existing English/flags/notes are carried over by the Japanese text.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asb  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "work", "source", "dat", "data", "campus", "event", "script")
OUT = os.path.join(ROOT, "work", "translation", "en", "campus.json")
SLICE_ROWS, SLICE_MIN_AT_SCENE_END = 80, 60
BLANK = "　".encode("cp932")
# gop_char.gop records in order (speaker id = index). English short names as the
# name plate will show them (the plate text itself comes from gop_char, translated in
# the corpus); generic roles in plain English.
SPEAKERS = ["PLAYER/none", "Kagura", "Gary", "Luis", "Shirakawa", "Hilda", "Hoshimura", "Yamashiro", "Akimizu",
            "Claire", "Pinon", "Alto", "Michel", "Luca", "Nanase", "Ranka", "Sheryl", "Klan", "Ozma", "Bobby",
            "Canaria", "Brera", "Cathy", "Grace", "Klan", "Pilot Student A",
            "Pilot Student B", "Pilot Students", "Female Student A", "Female Student B",
            "Female Student C", "Quiet Girl", "Lively Girl", "Stylish Girl", "??? (man)", "??? (woman)",
            "Princess Alto", "A Girl?", "Michael", "Catherine", "Audience", "Thug", "Male Teacher",
            "Young Woman", "Clerk A", "Nyan-Nyan Clerk", "Ranka Fan (man)", "Ranka Fan (woman)", "CM",
            "Commentary", "Operator", "Commander", "Citizen A", "Citizen B", "Citizen C", "Yasaburo",
            "Ranzo", "President Glass", "Scout", "Monica", "Mina", "Ram", "Ship Broadcast", "Newscaster",
            "Ranka & Sheryl"]


def speaker_name(v):
    if v is None:
        return "-"
    if 0 <= v < len(SPEAKERS):
        return SPEAKERS[v]
    return "id%d" % v


def labels_of(s):
    """[(code start, code end, label name)] from the label table."""
    st = s.strings()
    out = []
    for i in range(s.lab_n):
        name_off, _, _, start, size = struct.unpack_from("<5I", s.data, s.lab_off + 0x14 * i)
        out.append((start, start + size, st.get(name_off, b"").decode("ascii", "replace")))
    return out


def variant_of(labels, pos):
    best = ""
    for a, b, name in labels:
        if a <= pos < b:
            best = name
    for v in ("_male", "_female"):
        if best.endswith(v):
            return v[1:]
    return best.rsplit("_", 1)[-1] if best else ""


def main():
    dry = "--dry-run" in sys.argv
    occ = []
    for f, s in asb.iter_scripts(SCRIPTS):
        scene = os.path.basename(f)[:-4]
        rel = "data/campus/event/script/%s/%s.asb" % (os.path.basename(os.path.dirname(f)), scene)
        st = s.strings()
        labels = labels_of(s)
        speaker = None
        for pos, fn, args in s.calls():
            vals = [s.push_value(p) if p is not None else None for p in args]
            if fn == 0x1D and vals and vals[0] is not None:  # name plate: speaker id
                speaker = vals[0]
            for k, (p, v) in enumerate(zip(args, vals)):
                if p is None or v not in st:
                    continue
                raw = st[v]
                if raw == BLANK or not any(b > 0x7F for b in raw):
                    continue
                kind = "choice" if fn == 0x01 else "line"
                occ.append((raw.decode("cp932"), {
                    "id": "%s:%04x:%x" % (scene, v, p), "scene": scene,
                    "ref": {"file": rel, "pool": v, "push": p},
                    "speaker": "choice" if kind == "choice" else speaker_name(speaker),
                    "variant": variant_of(labels, pos), "fn": fn}))
    rows, by_jp = [], {}
    for jp, o in occ:
        if jp not in by_jp:
            by_jp[jp] = {"group": "choice" if o["speaker"] == "choice" else "campus", "jp": jp, "occ": [],
                         "scene": o["scene"], "speaker": o["speaker"], "variant": o["variant"]}
            rows.append(by_jp[jp])
        by_jp[jp]["occ"].append(o)
    old = {}
    if os.path.exists(OUT):
        old = {r["jp"]: r for r in json.load(open(OUT, encoding="utf-8"))["rows"]}
    sl, n_in, prev_scene = 0, 0, None
    for i, r in enumerate(rows, 1):
        scene_change = r["scene"] != prev_scene
        if sl == 0 or n_in >= SLICE_ROWS or (scene_change and n_in >= SLICE_MIN_AT_SCENE_END):
            sl, n_in = sl + 1, 0
        prev_scene = r["scene"]
        n_in += 1
        r["row"], r["slice"], r["id"] = i, sl, "c%05d" % i
        o = old.get(r["jp"], {})
        r["en"], r["flags"], r["notes"] = o.get("en", ""), o.get("flags", []), o.get("notes", "")
        r["status"] = o.get("status", "todo") if r["en"] else "todo"
    print("rows %d (occurrences %d), slices %d, chars %d" % (len(rows), len(occ), sl, sum(len(r["jp"]) for r in rows)))
    by_dir = {}
    for r in rows:
        k = r["scene"][:3]
        by_dir.setdefault(k, [0, 0])
        by_dir[k][0] += 1
        by_dir[k][1] += len(r["jp"])
    print("by script folder (rows, chars):", by_dir)
    if dry:
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"_meta": {"version": "0.1.0", "slice_rows": SLICE_ROWS, "speakers": SPEAKERS}, "rows": rows},
                  f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
