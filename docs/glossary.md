# Glossary

Version 0.1.0 (2026-10-16). Files live in `work/glossary/`:

| File | Contents |
|---|---|
| `characters.json` | 129 characters: the 59 pilot-table names, 7 operators, the original cast, supporting cast |
| `mecha.json` | 125 units, 13 packs, 9 families, 12 mission objects |
| `organizations.json` | 54 militaries, factions, squadrons, bands and fleets |
| `locations.json` | 29 planets, cities, ships-as-places and campus-mode places |
| `terms.json` | lore (63), game-system terms (68), skills (32), songs (58), works (16), ranks (18), mission titles (44), honorifics (7) |
| `tf_additions.json` | **Hand-kept.** Triangle Frontier's own entries and extra Japanese forms of inherited entries |
| `gaps.json` | Output of `tools/glossary_check.py`: every name the game uses and how it matched |
| `dropped.json` | Inherited entries left out because Triangle's text never names them |

## Where it came from

Triangle Frontier (TF) is the third game on the Ace Frontier (AF) / Ultimate Frontier (MUF) engine, and its
cast is almost exactly MUF's (see [formats.md](formats.md#content-compared-with-ultimate-and-ace-frontier)). The
glossary is generated, not copied by hand:

```bash
python -I tools/glossary_seed.py     # merge MUF + AF + tf_additions.json, count uses in the TF text
python -I tools/glossary_check.py    # match the names the TF text uses against the result
```

`tools/glossary_seed.py` reads `../Macross Ultimate Frontier/work/glossary/` and
`../Macross Ace Frontier/work/glossary/`:

- **MUF is the base.** Its spellings shipped in MUF 0.7.1. MUF's `in_game` becomes `muf_role`.
- **AF adds** `af_role`, `af_uses`, `muf_en`, `refers_to`, its `ja_aliases` / `aliases` / `avoid`, and the
  AF-only groups (mission objects, skills, ranks, mission titles, more songs). Where AF and MUF notes differ, AF's
  note is kept as `af_notes`.
- **`tf_additions.json` adds** Triangle's own entries (Macross II wingmen, the Metal Siren, the Tornado Pack,
  campus places...) and Japanese forms that TF writes differently (金竜 for 金龍, 空母アスカⅡ, ゴーストＶ－９...).
  Edit this file, never the generated ones: a re-seed rewrites them.
- **Dropped** (8 entries plus 60 AF mission titles, listed in `dropped.json`): characters, mission objects and
  mission titles that MUF or AF text names but TF text never does. These are the magazine-collab cameos (Nishioka,
  Hamamura Tsushin, Bakataru Kato, Kuranishi) and AF missions TF does not have. Lore, songs, units and places are
  never dropped: they can be voice-only, or TF writes them another way.

## Spelling policy

Same as MUF and AF, so the three patches read alike:

1. **Macross Wiki (macross.fandom.com) wins** for names. Where the wiki contradicts itself, the entry is
   `needs_check` and `notes` explains the choice.
2. **No Robotech names.** They are in `avoid` lists.
3. **Given name first** for Japanese names (Alto Saotome, Hikaru Ichijyo). Chinese-order names keep the surname
   first (Lynn Minmay).
4. **No macrons or umlauts:** the game font has no glyphs for them. Shin Kudo, VB-6 Konig Monster, Saori Kujo.
5. **Episode titles:** official English episode titles; where MUF already chose a wording, MUF's wording wins.
6. **Songs:** MUF's English title when MUF had the song, else the Macross Wiki article title.
7. **MUF's shipped English wins for identical strings** (`muf_tm` in notes): "Zolan Star Patrol",
   "Carrier Asuka II", "Large Vajra Mothership", "Ghost V-9", "Battle Pod", "Blue Wind".

Decided in MUF and not to be reopened: Vrlitwhai Kridanik, Quamzin Kravshera, Milia Fallyna Jenius, Jeffrey
Wilder, Gepelnitchi, Vermillion Flight, "New U.N. Forces" vs "New U.N. Spacy", Hoilie, Golg Boddole Zer (titles) /
Boddole Zer, Shin Kudo.

## Fields

Inherited fields keep their MUF/AF meaning (`en`, `ja`, `ja_aliases`, `aliases`, `avoid`, `gender`, `status`,
`muf_role`, `af_role`, `af_uses`). New in TF:

- `tf_uses`: TF text entries outside the campus mode (EBOOT, menu CSVs, mission scripts, unit lists) that
  contain the Japanese name or a `ja_aliases` form. 0 does not mean unused: TF also has voice clips.
- `tf_campus_uses`: campus event-script lines that contain it. Campus text uses given names (ピノンちゃん,
  ヒルダ先生), so the original characters carry their given names as `ja_aliases`. Short forms can over-count.
- `tf_role` (characters): `pilot table` (the EBOOT pilot table), `operator` (the 7 operators), `campus`, or a
  hand-written role for additions.
- `tf_added`: the entry or some of its Japanese forms come from `tf_additions.json`.

## TF notes

- **Academy (campus) mode** is new and large: 1,022 event scripts, about 37,000 lines (formats.md). It is a
  school life sim at Mihoshi Academy (美星学園) with the Frontier cast and the AF/MUF originals as classmates and
  teachers (ヒルダ先生, ゲイリー先生, ヤマシロ先生, ピノン先生). New place names: Griffith Park, Central Park,
  Silver Moon (a café), Arlington Cemetery, St. Maria Academy. Courses: 航宙科 (pilot students), 芸能科.
  Honorifics are kept there (see below).
- **Macross II** missions (M2_*) bring Silvie Gena's wingmen. The anime gives only first names (Saori, Amy,
  Nastasha); TF adds surnames: 九條 沙織, エイミー・ロック, ナスターシャ・トート.
- **The False Songstress** missions (MK_*) add the YF-25 Prophecy, the Hound Vajra and the Tornado Pack.
- **Luca's Ghosts** are Simon, John and Peter (wiki and MUF), not "Johannes" / "Petro".
- **ME_810 / ME_820** field an enemy team with zodiac callsigns (アリエス１ = Aries 1 ... ピスケス４).
- The four player pilots have names in TF (Yuuto Kagura, Gary Murdoch, Miyuki Shirakawa, Hilda V. Bergen), as in
  MUF. In campus mode the player creates their own character.

## Honorifics (decided 2026-10-16)

The user decided to **keep Japanese honorifics in the campus text**: Pinon-chan, Hilda-sensei, Luis-san,
Klan-senpai, Michel-kun, Sheryl-sama. They are written in romaji after the name, joined by a hyphen, lowercase;
alone as a form of address, "Sensei" and "Senpai". Campaign, mission and voice text keep the MUF style (MUF shipped
without honorifics: "Ms. Hayase"). Ranks and job titles (隊長, 少佐, 艦長) stay English titles, and kinship words
(お兄ちゃん, 姉さん) are translated. `terms.json` → `honorifics` holds the seven forms (さん, ちゃん, 君/くん, 先生,
先輩, 様/さま, 殿); the full rules are in [translation_brief.md](translation_brief.md#honorifics-decided-2026-10-16).
Their `tf_campus_uses` are rough: the counter skips one-character forms (君, 殿) and counts set phrases.

## Open items

| Item | Status | What is needed |
|---|---|---|
| ナスターシャ・トート | needs_check | Reading of トート (Toto / Tote / Thoth) |
| 九條 沙織, エイミー・ロック | provisional | Surnames are TF-only; no source spelling |
| ダルフィム | needs_research | Collection item (nn_ext 6241); not on the wiki |
| 航宙科, 芸能科 | provisional | Wording of the Mihoshi course names in the official English Frontier releases |
| Hound Vajra, Proto Metal Siren, Concert Ship, Remote-Controlled Valkyrie | provisional | Plain translations, no wiki page |
| ＶＳＦ, 半身マクロス, ゴルグ・ガンツ・チャーツ | open | Inherited from AF/MUF, still without English |
| 7 song titles, 5 skills, 4 mission titles | open | Inherited open AF entries; translate with the UI |
| 29 characters used in TF | needs_check / provisional | Inherited from MUF/AF unchanged (minor Macross 7 / Frontier / II cast) |
| TF mission titles | not catalogued | TF's own mission names (EBOOT 0x3F3588 block) are not glossary entries yet; only the 44 shared with AF are |

## Checking against the game text

`glossary_check.py` reads the TF menu CSVs (as in MUF), the EBOOT pilot table (0x3CFDD0–0x3D4DC0), the mission
scripts and the unit lists, and matches every name against characters, mecha and organizations, then lore, terms
and locations. Editor labels (爆発用, カメラ位置用, セリフ用, POINT/GOAL markers) are skipped. Current result:
characters 1 gap (a generic "patrol leader"), mecha 8 gaps (collection items such as Missile Destroyer and Minmay
Doll, which the UI translation covers), objects 5 gaps (generic: factory, hideout, Parts BOX). The organization
list is mined from prose with a pattern; its 18 gaps are generic words (enemy forces, all units, walking mode) and
need no entry.

## Sources

- TF on the Macross Wiki: https://macross.fandom.com/wiki/Macross_Triangle_Frontier (roster, Academy Mode)
- Entry sources are linked in each entry's `sources`. The wiki blocks plain fetches; it was read in a browser.
- Macross II wingmen: MyAnimeList character pages (Saori, Amy), linked in the entries.
