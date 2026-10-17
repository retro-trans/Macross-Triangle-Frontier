"""Seed the Triangle Frontier glossary from the two sister projects.

Usage:
  python tools/glossary_seed.py [--muf <dir>] [--af <dir>] [--out work/glossary]
  defaults: ../Macross Ultimate Frontier  ../Macross Ace Frontier

Reads <project>/work/glossary/*.json of Macross Ultimate Frontier (MUF) and
Macross Ace Frontier (AF), and the text dumps of all three games
(work/source/text/*.json, from tools/dump_text.py and tools/dump_eboot.py).

Merge rules (docs/glossary.md):
  - MUF is the base: it is the later glossary and its spellings shipped in
    MUF 0.7.1. MUF's `in_game` becomes `muf_role`.
  - An AF entry with the same `ja` (or `id`) adds `af_role`, `af_uses`,
    `muf_en`, `refers_to` and its `ja_aliases` / `aliases` / `avoid` to the
    MUF entry. Where AF filled a field MUF left empty, AF's value is used.
  - AF-only entries (magazine cameos, mission objects, songs, skills, ranks,
    mission titles) are added as they are.
  - work/glossary/tf_additions.json (hand-kept) adds Triangle's own entries
    and extra Japanese forms of existing ones; tf_added marks them.
  - Every entry gets `tf_uses` (Triangle Frontier text entries outside the
    campus mode that contain the Japanese name or a `ja_aliases` form) and
    `tf_campus_uses` (campus event script lines).
  - Dropped: characters, mission objects and mission titles that MUF or AF
    text names but Triangle Frontier text never does (content Triangle left
    out, such as the magazine-collab missions). Every other entry is kept,
    with tf_uses 0 where Triangle's text does not name it. The dropped
    entries are listed in work/glossary/dropped.json.

Output contains only names and UI terms in Japanese, which the commit rules allow.
"""

import argparse
import copy
import json
import os
import re
import unicodedata
from collections import OrderedDict

STRIP = re.compile(r"[\s・＝=\.·･　]")
FILES = {
    "characters.json": ["characters"],
    "mecha.json": ["packs", "families", "units", "objects"],
    "organizations.json": ["organizations"],
    "locations.json": ["locations"],
    "terms.json": ["lore", "game_system", "skills", "songs", "works", "ranks", "missions", "honorifics"],
}
# Only these groups are pruned: a cast member, mission object or mission title that
# the earlier game's text names and Triangle's never does belongs to content Triangle
# left out. Lore, songs, units and places stay: they can be voice-only, or Triangle
# writes them in another form (see docs/glossary.md).
DROP_GROUPS = {"characters", "objects", "missions"}
LIST_FIELDS = ("ja_aliases", "aliases", "avoid")
# Triangle Frontier EBOOT pilot table (file offsets in EBOOT.dec.bin, ULJS-00321 v1.01)
TF_PILOT_TABLE = (0x3CFDD0, 0x3D4DC0)
# The seven operators (operator_ext.csv descriptions; names in the EBOOT operator list)
TF_OPERATORS = ("ヤマシロ・イツキ", "アキミズ・ユウ", "クレア・スタンフォード", "ピノン・コレット", "早瀬未沙",
                "キャサリン・グラス", "エキセドル・フォルモ")
AF_FIELDS = ("af_role", "af_uses", "muf_en", "refers_to")


def norm(s):
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("‐", "-").replace("−", "-").replace("–", "-")
    return STRIP.sub("", s).lower()


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=OrderedDict)


def texts(project, campus=None):
    """Normalised text entries of one game. campus: None = all, True = campus only,
    False = everything but campus."""
    out = []
    folder = os.path.join(project, "work", "source", "text")
    for name in ("eboot_strings.json", "menu_text.json", "fes_strings.json", "locate_names.json",
                 "campus_strings.json"):
        is_campus = name == "campus_strings.json"
        if campus is not None and campus != is_campus:
            continue
        path = os.path.join(folder, name)
        if os.path.exists(path):
            out += [norm(e["jp"]) for e in load(path)]
    return out


def names_of(e):
    out = []
    for n in [e.get("ja", "")] + list(e.get("ja_aliases") or []):
        n = re.sub(r"[（(][^）)]*[）)]$", "", n).strip()  # 'リン・ミンメイ（水着）' -> base name
        if n and len(norm(n)) >= 2:
            out.append(norm(n))
    return out


def uses(e, corpus):
    ns = names_of(e)
    if not ns:
        return 0
    return sum(1 for t in corpus if any(n in t for n in ns))


def items_of(group):
    """A group is a list, or (MUF terms skills/songs) {"_note": ..., "items": [...]}."""
    if isinstance(group, dict):
        return group.get("items", [])
    return group or []


def key_of(e):
    return e.get("ja") or e.get("id")


def merge_entry(muf, af):
    out = copy.deepcopy(muf)
    if "in_game" in out:
        out["muf_role"] = out.pop("in_game")
    for f in LIST_FIELDS:
        vals = list(out.get(f) or [])
        for v in af.get(f) or []:
            if v not in vals:
                vals.append(v)
        if vals or f in out:
            out[f] = vals
    for f, v in af.items():
        if f in AF_FIELDS:
            out[f] = v
        elif f not in out or out[f] in ("", None, []):
            out[f] = v
    if af.get("notes") and af["notes"] != out.get("notes") and af["notes"] not in (out.get("notes") or ""):
        out["af_notes"] = af["notes"]
    return out


def apply_additions(fname, group, merged, additions):
    """Add the hand-kept Triangle entries and Japanese forms (work/glossary/tf_additions.json)."""
    stem = fname[:-5]
    for a in additions.get("aliases", []):
        if a["file"] != stem or a["group"] != group:
            continue
        e = next((x for x in merged if x.get("ja") == a["ja"]), None)
        if e is None:
            raise ValueError("tf_additions alias target not found: %s/%s %s" % (stem, group, a["ja"]))
        for f in ("ja_aliases", "aliases"):
            vals = list(e.get(f) or [])
            vals += [v for v in a.get(f, []) if v not in vals]
            if vals:
                e[f] = vals
        if a.get("notes_add"):
            e["notes"] = ((e.get("notes") or "") + " " + a["notes_add"]).strip()
        e["tf_added"] = True
    existing = {x.get("ja") for x in merged}
    new = additions.get("entries", {}).get("%s/%s" % (stem, group), [])
    for e in new:
        if e["ja"] in existing:
            raise ValueError("tf_additions entry already in the glossary: %s" % e["ja"])
        e = copy.deepcopy(e)
        e["tf_added"] = True
        merged.append(e)
    return len(new)


def tf_role(e, pilots, campus_uses):
    """'pilot table' / 'operator' / 'campus' from the TF text; keeps a hand-set tf_role."""
    if e.get("tf_role"):
        return e["tf_role"]
    ns = set(names_of(e))
    roles = []
    if ns & pilots:
        roles.append("pilot table")
    if ns & {norm(o) for o in TF_OPERATORS}:
        roles.append("operator")
    if campus_uses:
        roles.append("campus")
    return ", ".join(roles)


def seed(muf_dir, af_dir, out_dir, tf_dir):
    eboot = load(os.path.join(tf_dir, "work", "source", "text", "eboot_strings.json"))
    pilots = {norm(re.sub(r"[（(][^）)]*[）)]$", "", x["jp"])) for x in eboot
              if TF_PILOT_TABLE[0] <= x["offset"] < TF_PILOT_TABLE[1]}
    add_path = os.path.join(out_dir, "tf_additions.json")
    additions = load(add_path) if os.path.exists(add_path) else {}
    corpora = {
        "tf": texts(tf_dir, campus=False),
        "tf_campus": texts(tf_dir, campus=True),
        "muf": texts(muf_dir),
        "af": texts(af_dir),
    }
    os.makedirs(out_dir, exist_ok=True)
    dropped = OrderedDict()
    summary = OrderedDict()
    for fname, groups in FILES.items():
        muf = load(os.path.join(muf_dir, "work", "glossary", fname))
        af = load(os.path.join(af_dir, "work", "glossary", fname))
        out = OrderedDict()
        out["_meta"] = copy.deepcopy(af.get("_meta") or muf.get("_meta"))
        for group in groups:
            m_items = items_of(muf.get(group))
            a_items = items_of(af.get(group))
            if not m_items and not a_items and "%s/%s" % (fname[:-5], group) not in additions.get("entries", {}):
                continue
            a_by_key = OrderedDict()
            for e in a_items:
                a_by_key.setdefault(key_of(e), e)
            merged = []
            seen = set()
            for e in m_items:
                k = key_of(e)
                a = a_by_key.get(k)
                if a is None and e.get("id"):
                    a = next((x for x in a_items if x.get("id") == e["id"]), None)
                if a is not None:
                    merged.append(merge_entry(e, a))
                    seen.add(id(a))
                else:
                    e = copy.deepcopy(e)
                    if "in_game" in e:
                        e["muf_role"] = e.pop("in_game")
                    merged.append(e)
            n_af_only = 0
            for e in a_items:
                if id(e) not in seen:
                    merged.append(copy.deepcopy(e))
                    n_af_only += 1
            n_tf = apply_additions(fname, group, merged, additions)
            kept = []
            for e in merged:
                e["tf_uses"] = uses(e, corpora["tf"])
                e["tf_campus_uses"] = uses(e, corpora["tf_campus"])
                if fname == "characters.json":
                    e["tf_role"] = tf_role(e, pilots, e["tf_campus_uses"])
                if e["tf_uses"] == 0 and e["tf_campus_uses"] == 0 and group in DROP_GROUPS:
                    elsewhere = uses(e, corpora["muf"]) + uses(e, corpora["af"])
                    if elsewhere:
                        dropped.setdefault(fname[:-5] + "/" + group, []).append(
                            OrderedDict([("ja", e.get("ja")), ("en", e.get("en")),
                                         ("muf_af_uses", elsewhere)]))
                        continue
                kept.append(e)
            out[group] = kept
            summary["%s/%s" % (fname[:-5], group)] = OrderedDict([
                ("muf", len(m_items)), ("af", len(a_items)), ("af_only", n_af_only), ("tf_new", n_tf),
                ("kept", len(kept)), ("dropped", len(merged) - len(kept)),
                ("tf_used", sum(1 for e in kept if e["tf_uses"] or e["tf_campus_uses"]))])
        meta = out["_meta"]
        meta["version"] = "0.1.0"
        meta["updated"] = "2026-10-16"
        meta["seeded_from"] = ("Macross Ultimate Frontier glossary (base) + Macross Ace Frontier glossary, "
                               "merged by tools/glossary_seed.py")
        fields = meta.setdefault("fields", OrderedDict())
        fields["tf_uses"] = ("How many Triangle Frontier text entries outside the campus mode (EBOOT, menu CSVs, "
                             "mission scripts, unit lists) contain the Japanese name or a ja_aliases form. "
                             "0 = not in the dumped text; it can still be heard in voice clips")
        fields["tf_campus_uses"] = "How many campus event script lines contain the name"
        fields["muf_role"] = "Role in Macross Ultimate Frontier, kept from the MUF glossary"
        if fname == "characters.json":
            fields["tf_role"] = ("Role in Triangle Frontier: pilot table / operator / campus / mentioned. "
                                 "Empty = not set yet")
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
            f.write("\n")
    with open(os.path.join(out_dir, "dropped.json"), "w", encoding="utf-8") as f:
        json.dump(OrderedDict([("_meta", OrderedDict([
            ("generated_by", "tools/glossary_seed.py"),
            ("note", "MUF/AF glossary entries whose name appears in MUF or AF text but nowhere in Triangle "
                     "Frontier text. Left out of the TF glossary; restore one if it turns up (voice, images)."),
        ]))] + list(dropped.items())), f, ensure_ascii=False, indent=1)
        f.write("\n")
    return summary


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parent = os.path.dirname(here)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--muf", default=os.path.join(parent, "Macross Ultimate Frontier"))
    ap.add_argument("--af", default=os.path.join(parent, "Macross Ace Frontier"))
    ap.add_argument("--out", default=os.path.join(here, "work", "glossary"))
    args = ap.parse_args()
    summary = seed(args.muf, args.af, args.out, here)
    for k, v in summary.items():
        print("%-28s %s" % (k, " ".join("%s=%d" % kv for kv in v.items())))


if __name__ == "__main__":
    main()
