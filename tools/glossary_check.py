"""Cross-check the glossary against the names the game itself uses.

Usage:
  python tools/glossary_check.py [<text_dir>] [<glossary_dir>]
  defaults: work/source/text  work/glossary

Reads the dump from tools/dump_text.py and writes
<glossary_dir>/gaps.json: every character, mecha and organization name found
in the game text, with how it matched the glossary:

  exact    same name after normalisation (full-width to ASCII, spaces,
           "・", "＝" and "." removed)
  variant  the base name matches; the game adds an outfit, colour or
           pilot suffix such as "（Ｐスーツ）" or " マックス機"
  partial  the game name is one part of a glossary name (a short form
           such as "ランカ" for "ランカ・リー"), or one name contains the
           other. Check these by hand.
  gap      not in the glossary

Categories: character, mecha (units and packs), organization (mined from
prose, noisy) and object (places and props named in the mission unit lists).

Only names go into gaps.json (Japanese names are allowed in git).
"""

import json
import os
import re
import sys
import unicodedata
from collections import OrderedDict

STRIP = re.compile(r"[\s・＝=\.·･　]")
PAREN = re.compile(r"[（(]([^）)]*)[）)]$")
PILOT_SUFFIX = re.compile(r"^(.*?)\s+(\S+?)(機|仕様)$")
MODEL = re.compile(r"^[A-Za-z]+[A-Za-z0-9\-\.]*\d[A-Za-z0-9\-\.αγⅡⅢ改]*")

# Names in the locate files that are internal labels, not shown to players
INTERNAL = re.compile(r"デモ用|顔絵用|フェイス用|ダミー|^表示名$|削除|テスト|予定|"
                      # Triangle Frontier editor labels: 爆発用 (for the explosion), カメラ位置用,
                      # セリフ用 (for a line of dialogue), 開始演出用..., POINT/GOAL markers
                      r"用$|用\d*$|演出用|カメラ位置用|セリフ用|^ＰＯＩＮＴ|^ＧＯＡＬ$|^ゴール$|"
                      r"^ファイター(味方|敵)$|^扉開閉スイッチ$|^全身マクロス")
# Locate names that are places or objects rather than people
OBJECT = re.compile(r"基地|工場|アジト|ターゲット|地点|ポイント|パーツ|コンテナ|エンジン|空母|装置|欠片|ミラー|兵士$|隊$|^[Ａ-Ｚ]+$|"
                    r"船$|^民間人$")
# Triangle Frontier EBOOT name tables (file offsets in EBOOT.dec.bin, ULJS-00321 v1.01).
# Its units are in the menu CSVs (as in Ultimate Frontier), so only the pilot table is read;
# the EBOOT unit names sit between their descriptions and are left to the CSVs.
EBOOT_PILOTS = (0x3CFDD0, 0x3D4DC0)
EBOOT_UNITS = (0, 0)
# generic AI pilot profiles, editor dummies and parts of a ship (主砲, (前)...)
EBOOT_GENERIC = re.compile(r"^ザコ用|^パイロット[男女]|兵士$|名手$|^鉄壁の人$|^完全無欠$|^エース$|用（|用ダミー|"
                           r"主砲$|副砲$|ミサイル$|機銃$|[（(](前|中|後|左|右|下|中央|右[12１２]|左[12１２])[)）]$|"
                           r"^半身マクロス\d|^半マ|^レーダー内文字$|^正体不明$|^学園\d|（スキル|^ベテラン兵士$|^新米兵士$|"
                           r"^戦艦用")
SPLIT = re.compile(r"[・＝=\s　]")
# generic words caught by ORG_WORD that are not names
ORG_STOP = {"両軍", "敵軍", "友軍", "元軍", "大部隊", "精鋭部隊", "特殊部隊", "特務部隊", "宇宙艦隊",
            "移民船団", "新型可変戦闘機部隊", "特別攻撃部隊"}
OBJECTIVE = re.compile(r"^(.+?)(?:を撃破せよ|を救出せよ|を護衛せよ|を回収せよ)$")
ORG_WORD = re.compile(r"[゠-ヿー一-鿿Ａ-Ｚａ-ｚ０-９]+?(?:軍|艦隊|船団|小隊|部隊|同盟|政府|戦隊)")


def norm(s):
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("‐", "-").replace("−", "-").replace("–", "-")
    return STRIP.sub("", s).lower()


def split_variant(name):
    """'リン・ミンメイ（水着）' -> ('リン・ミンメイ', '水着')."""
    name = name.strip()
    m = PAREN.search(name)
    if m:
        return name[:m.start()].strip(), m.group(1)
    return name, ""


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Index:
    """Glossary names for one category, normalised."""

    def __init__(self, items, suffixes=()):
        self.items = items
        self.suffixes = suffixes
        self.full = {}
        self.parts = {}
        for it in items:
            for n in [it.get("ja", "")] + it.get("aliases", []) + (it.get("ja_aliases") or []):
                if n:
                    self.full.setdefault(norm(n), it)
                    base, _ = split_variant(n)
                    self.full.setdefault(norm(base), it)
                    nfk = unicodedata.normalize("NFKC", base)
                    if not MODEL.match(nfk):
                        for part in SPLIT.split(nfk):
                            if len(part) >= 2:
                                self.parts.setdefault(norm(part), it)
                    # "VF-1J バルキリー" also answers to "VF-1J" and "バルキリー"
                    parts = unicodedata.normalize("NFKC", base).split()
                    if len(parts) > 1 and MODEL.match(parts[0]):
                        self.full.setdefault(norm(parts[0]), it)
                        self.full.setdefault(norm(" ".join(parts[1:])), it)

    def match(self, name):
        n = norm(name)
        if n in self.full:
            return "exact", self.full[n]
        base, var = split_variant(name)
        m = PILOT_SUFFIX.match(unicodedata.normalize("NFKC", base))
        cands = [base]
        numless = re.sub(r"[0-9０-９]+$", "", base)  # 'アリエス１' -> 'アリエス'
        if numless != base and len(numless) >= 2:
            cands.append(numless)
        if m:
            cands.append(m.group(1))
        if "用" in base:  # "ＶＦ－２５用スーパーパック": pack for a model
            cands.append(base.split("用", 1)[1])
        for suf in self.suffixes:  # "ゼントラーディ軍"
            if base.endswith(suf) and len(base) > len(suf) + 1:
                cands.append(base[:-len(suf)])
        for c in cands:
            if norm(c) in self.full and (var or c != base):
                return "variant", self.full[norm(c)]
            parts = unicodedata.normalize("NFKC", c).split()
            if parts and MODEL.match(parts[0]) and norm(parts[0]) in self.full:
                return "variant", self.full[norm(parts[0])]
        nb = norm(base)
        if nb in self.parts:
            return "partial", self.parts[nb]
        if len(nb) >= 2:
            for k, it in self.full.items():
                if len(k) >= 3 and (nb in k or k in nb):
                    return "partial", it
        return "gap", None


def collect(text_dir):
    """Return ({category: OrderedDict(name -> [ids])}, all text normalised)."""
    menu = load(os.path.join(text_dir, "menu_text.json"))
    fes = load(os.path.join(text_dir, "fes_strings.json"))
    locate = load(os.path.join(text_dir, "locate_names.json"))
    eboot_path = os.path.join(text_dir, "eboot_strings.json")
    eboot = load(eboot_path) if os.path.exists(eboot_path) else []
    found = {"character": OrderedDict(), "mecha": OrderedDict(), "organization": OrderedDict(),
             "object": OrderedDict()}

    def add(cat, name, ident):
        name = name.strip().replace("　", " ")
        if name:
            found[cat].setdefault(name, []).append(ident)

    # nn_ext.csv (Nyan-Nyan shop / collection): 0000-0099 pilots grouped under
    # series headers, 1000-1999 units, 6000- figures (pilots, then units from TYPE-14)
    in_units = False
    for e in menu:
        src = e["source"].rsplit("/", 1)[-1]
        if src == "nn_ext.csv":
            k = int(e["key"][-4:])
            if k < 1000:
                if e["jp"].startswith("マクロス") or e["jp"] == "エクストラ":
                    continue  # series header
                add("character", e["jp"], e["id"])
            elif k < 2000:
                if not e["jp"].startswith("■"):  # series header
                    add("mecha", e["jp"], e["id"])
            elif k >= 6000:
                if "ＴＹＰＥ－１４" in e["jp"]:
                    in_units = True
                add("mecha" if in_units else "character", e["jp"], e["id"])
        elif src == "ms_ext.csv":
            add("mecha", e["jp"].split("\\n", 1)[0], e["id"])
        elif src == "pack_ext.csv":
            add("mecha", e["jp"].split("\\n", 1)[0], e["id"])
    # the EBOOT pilot table (and, in Ace Frontier, the unit/object table), by file offset
    for e in eboot:
        off = e["offset"]
        if EBOOT_PILOTS[0] <= off < EBOOT_PILOTS[1]:
            if not INTERNAL.search(e["jp"]) and not EBOOT_GENERIC.search(e["jp"]):
                add("character", e["jp"], e["id"])
        elif EBOOT_UNITS[0] <= off < EBOOT_UNITS[1]:
            if not INTERNAL.search(e["jp"]) and not EBOOT_GENERIC.search(e["jp"]):
                add("object" if OBJECT.search(e["jp"]) else "mecha", e["jp"], e["id"])
    for e in locate:
        if INTERNAL.search(e["jp"]):
            continue
        for part in re.split(r"[＆&/／]", e["jp"]):
            part = part.strip()
            if part and not re.match(r"^[A-Za-z0-9\-\(\)]+$", part):
                add("object" if OBJECT.search(part) else "character", part, e["id"])
    for e in fes:
        m = OBJECTIVE.match(e["jp"].split("\n")[0])
        if m and not m.group(1).startswith(("敵", "友軍", "攻撃", "防衛", "目標", "民間")):
            add("character", m.group(1), e["id"])
    # organizations: words ending in 軍/艦隊/船団/小隊... in prose, plus 「quoted」 names
    for e in menu + fes + eboot:
        if e.get("source", "").endswith("nn_ext.csv"):
            continue
        t = e["jp"]
        for w in ORG_WORD.findall(t):
            if w not in ORG_STOP:
                add("organization", w, e["id"])
        for w in re.findall(r"「([^」]{2,20})」", t):
            # keep katakana terms (names, operations); skip quoted lines of dialogue
            kata = sum(1 for c in w if "゠" <= c <= "ヿ")
            if kata >= 0.6 * len(w) and not re.search(r"[！!？?、。…]|\\n|・・", w):
                add("organization", w, e["id"])
    all_text = norm("\n".join(e["jp"] for e in menu + fes + locate + eboot))
    return found, all_text


def main():
    text_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join("work", "source", "text")
    gdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join("work", "glossary")
    chars = load(os.path.join(gdir, "characters.json"))["characters"]
    mecha_g = load(os.path.join(gdir, "mecha.json"))
    orgs = load(os.path.join(gdir, "organizations.json"))["organizations"]
    indexes = {
        "character": Index(chars),
        "mecha": Index(mecha_g["units"] + mecha_g["packs"] + mecha_g.get("families", []) + mecha_g.get("objects", [])),
        "organization": Index(orgs, suffixes=("軍", "艦隊")),
    }
    indexes["object"] = indexes["mecha"]
    # lore, game terms, works and places: a fallback for names the other files lack
    terms = load(os.path.join(gdir, "terms.json"))
    locs = load(os.path.join(gdir, "locations.json"))["locations"]
    term_items = [it for k, v in terms.items() if k != "_meta"
                  for it in (v.get("items", []) if isinstance(v, dict) else v)]
    indexes["term"] = Index(term_items + locs)
    found, all_text = collect(text_dir)
    report = OrderedDict()
    summary = OrderedDict()
    for cat, names in found.items():
        rows = []
        for name, ids in names.items():
            level, it = indexes[cat].match(name)
            other = None
            # a unit name can also be a character (ゲペルニッチ) and the reverse
            for other_cat in ("character", "mecha", "organization", "term"):
                if level not in ("gap", "partial"):
                    break
                if indexes[other_cat] is indexes[cat]:
                    continue
                l2, it2 = indexes[other_cat].match(name)
                if l2 in ("exact", "variant"):
                    level, it, other = l2, it2, other_cat
            row = OrderedDict([("game", name), ("match", level)])
            if it:
                row["glossary_ja"] = it.get("ja")
                row["glossary_en"] = it.get("en")
                if other:
                    row["glossary_file"] = other
            row["count"] = len(ids)
            row["seen_in"] = ids[:5]
            rows.append(row)
        order = {"gap": 0, "partial": 1, "variant": 2, "exact": 3}
        rows.sort(key=lambda r: (order[r["match"]], -r["count"]))
        report[cat] = rows
        summary[cat] = {lvl: sum(1 for r in rows if r["match"] == lvl) for lvl in order}
    # glossary entries that appear nowhere in the dumped text (they may still be
    # in the EBOOT or in images; or the glossary uses another reading)
    used = {r["glossary_ja"] for rows in list(report.values()) for r in rows
            if r.get("glossary_ja") and r["match"] != "partial"}
    used |= {it["ja"] for it in chars + mecha_g["units"] + mecha_g["packs"] + orgs
             if norm(split_variant(it["ja"])[0]) in all_text}
    for cat, items in (("character", chars), ("mecha", mecha_g["units"] + mecha_g["packs"]),
                       ("organization", orgs)):
        report[cat + "_unused_glossary"] = [it["ja"] for it in items if it["ja"] not in used]
    out = OrderedDict([("_meta", OrderedDict([
        ("generated_by", "tools/glossary_check.py"),
        ("note", "Names the game text uses, matched against the glossary. 'gap' = missing from the glossary; "
                 "'partial' = check by hand. The organization list is mined from prose with a pattern, so "
                 "it holds false hits (generic words); review before adding anything."),
        ("summary", summary)]))])
    out.update(report)
    path = os.path.join(gdir, "gaps.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(summary))
    print("wrote", path)


if __name__ == "__main__":
    main()
