# Translation brief: Macross Triangle Frontier (v0.1.0)

Read `BASE_RULES.md` first; its rules apply in full. This page adds what is specific to this game. The sister
projects **Macross Ultimate Frontier** (MUF) and **Macross Ace Frontier** (AF) run on the same engine and are
translated already; this game reuses their glossary and, where the Japanese is identical, their English.

## Work file and your output (everything except campus scenes)

- `work/translation/en/corpus.json`: **one row per distinct Japanese string** outside the campus event scripts
  (menus, system and network messages, mission names, objectives and briefings, weapons, units, skills, titles,
  profiles, the Nyan-Nyan collection, mission script lines, unit names, and the campus data tables: era
  narration, event and gallery titles, schedule help, operator help, staff roll). Each row lists every place it
  occurs (`occ`), so it is translated once. Rows are in source order: neighbours are the same menu, list or
  scene. **Do not edit corpus.json.**
- `python -I tools/corpus_slice.py show <N> --context 10` prints your slice. `~` marks context rows, `<NL>` a
  newline. Each row shows its group, its first occurrence, status and limit:
  - `box~NNNpx`: the width the line should fit, in pixels at 14 px text with the game's English font.
  - `WRAP ...`: the text is re-wrapped at build time (see "Line breaks").
  - `MAX_BYTES=n`: a fixed-size field (pilot table). The English must fit in n bytes (ASCII = 1).
  - `xK`: the string is used K times.
- Rows with `status: tm` are prefilled from the MUF or AF translation. **Review them**: keep them, or fix them if
  they are wrong for this game or contradict the glossary. Half the rows are prefilled.
- Write `work/translation/en/slices/slice_NN.en.json` (NN = two digits) with Python
  `json.dump(obj, f, ensure_ascii=False, indent=1)`, including **every** row of the slice, prefilled ones too:

```json
{"slice": 3, "rows_in_slice": 80, "rows_examined": 80,
 "rows": [{"id": "u0412", "en": "...", "flags": [], "notes": ""}],
 "report": {"uncertain": [], "kept_omission": [], "missing_glossary": [], "unfinished": []}}
```

- **No Japanese anywhere in the slice file** (it goes to git). Notes describe the Japanese in English; use romaji
  only when you must.
- Run `python -I tools/corpus_slice.py check <N>` and fix every ERROR. Warnings are widths and line counts:
  compress what is over (abbreviate, shorter words, drop filler), never drop the end of a sentence or a fact.
  `python -I tools/corpus_slice.py width "text"` measures a line. UI box widths are estimates from the Japanese
  width; a short label a little over is acceptable if the meaning needs it (flag `uncertain`).
- `flags`: `uncertain`, `kept_omission`, `name_missing`, `unfinished`, `reflow` (you deliberately changed the
  number of line breaks of a non-WRAP row), `overflow` (still too long after compressing; say so in notes).

## Line breaks

All corpus text uses real newline characters (`"\n"` in JSON). Never write a literal backslash-n; the
insertion tool converts where a file needs it.

- **Normal rows:** keep the same number of lines as the Japanese, broken at a natural point.
- **WRAP rows** (mission briefings, unit descriptions, pilot and operator profiles): the Japanese is
  hard-wrapped at a fixed width. Ignore its breaks: write one paragraph (`title_lines=0`), or the unit name, one
  newline, then one paragraph (`title_lines=1`). The build wraps it; the check says how many lines it takes,
  which must not exceed `max_lines`. Briefings: at most 78 bytes per line (Shift-JIS bytes: ☆ and other
  symbols count 2), 2 lines; a longer line runs into the next one in game (the whole text on line 1).
- **Mission objectives** (`mission_ext.csv` strMission): line 1 at most 40 bytes, line 2 at most 44, a single line
  at most 46, as the Japanese.
- **Narration** (`gop_campaignevent`): one row = one screen line, as in MUF; a sentence often runs over several
  rows. Cut the English at the matching point. One row in, one row out.

## Style by group

| Group | What | Style |
| --- | --- | --- |
| `mission` | Mission names, objectives, victory/defeat conditions, survival-mode names | Titles in Title Case; anime episode titles use the glossary (`terms.json` → `missions`). Objectives imperative and short ("Destroy all enemies."). |
| `briefing` | Mission briefing (`mission_ext.csv` strStory) | Crisp military briefing voice. |
| `narration` | Era prologues and epilogues | Documentary, a little grand. Year in Western digits; "A.D." only where the Japanese starts with 西暦. |
| `profile` | Pilot and operator profiles | Third person, lively. |
| `unit_desc`, `stage_weapon` | Unit and weapon names with descriptions | Spec-sheet voice. Names from `mecha.json`; `（一般機）` = "(Standard)". |
| `ingame` | Mission script lines: objectives, tutorial | Tutorial lines speak to the player ("Hold L to guard."). |
| `quote` | Nyan-Nyan player titles (NNSHOP 5000-5299) | Epithets as short Title Case noun phrases; famous lines at full force ("Listen to my song!", "Kira☆"). |
| `help`, `campus_ui` | Campus-mode help, schedule, stat boosts, places, event and gallery titles, operator help | Concise. Event and gallery titles in Title Case. Operator help is spoken by an operator: keep the voice. Keep `[speed:N]` / `[wait:N]` tags where they are. Honorifics as below. |
| `skill`, `title`, `rank`, `ui`, `sound_test`, `locate`, `pilot_table` | Menus, help, system messages, titles, unlocks, credits, unit names | Concise, Title Case for labels, full plain sentences for messages ("Save the data?"). Credits: real people given name first. Pilot table within MAX_BYTES. |

## Kinds of text

| Kind | Where | Notes |
| --- | --- | --- |
| Menus, system messages, skills, ranks, gallery | EBOOT | As in AF/MUF. Many strings are identical to MUF: reuse its English after review. |
| Mission briefings and objectives | `mission_ext.csv`, EBOOT, mission scripts | 176 of MUF's briefings return unchanged. |
| Unit, pack, pilot, operator, BGM descriptions; Nyan-Nyan collection | menu CSVs | |
| Mission unit names | unit lists | Glossary `en`. |
| **Campus (Academy) mode** | `data/campus/event/script/*.asb` | New in TF, about 37,000 lines of school-life dialogue. Rules below. |

## Honorifics (decided 2026-10-16)

**In the campus text, keep the Japanese honorifics.** The campus mode is a school story among Japanese-named
classmates and teachers, and the user chose to keep its forms of address. Write them in romaji after the name,
joined by a hyphen, lowercase:

| Japanese | English | Examples from the campus text |
| --- | --- | --- |
| 〜さん | -san | ルイスさん → Luis-san, シェリルさん → Sheryl-san |
| 〜ちゃん | -chan | ピノンちゃん → Pinon-chan, ランカちゃん → Ranka-chan, ナナちゃん → Nana-chan |
| 〜君, 〜くん | -kun | ミシェル君 → Michel-kun, 早乙女君 → Saotome-kun, カグラ君 → Kagura-kun |
| 〜先生 | -sensei | ヒルダ先生 → Hilda-sensei, ヤマシロ先生 → Yamashiro-sensei |
| 〜先輩 | -senpai | クラン先輩 → Klan-senpai, クレア先輩 → Claire-senpai |
| 〜様, 〜さま | -sama | シェリル様 → Sheryl-sama |
| 〜殿 | -dono | アキミズ殿 → Akimizu-dono |

- **Keep the name the speaker uses.** Surname or given name, as in the Japanese: 早乙女君 is "Saotome-kun", not
  "Alto-kun"; ヤマシロ先生 is "Yamashiro-sensei". Spell the name part as in the glossary (`en`, short form):
  ミシェル is "Michel", ルカ "Luca", クラン "Klan".
- **On their own, as a form of address**, 先生 and 先輩 become "Sensei" and "Senpai", capitalised ("Sensei!",
  "Morning, Senpai."). Used as a common noun they are translated: "the teachers", "my seniors".
- **Standalone 君 is not an honorific.** Without a name in front it means "you": translate it.
- **Leave out a honorific the Japanese does not have.** Bare names stay bare (アルト → "Alto"). Do not add one for
  rhythm, and do not drop one that is there to save room: compress elsewhere.
- **Ranks and job titles are not honorifics.** オズマ隊長, オズマ少佐, グラス中尉, ジェフリー艦長 are English
  titles as in the rest of the game (`terms.json` → `ranks`; army style, as MUF: "Major", "Lieutenant",
  "Captain").
- **Kinship words are translated**, as MUF did ("Sis"): お兄ちゃん / 兄さん → "Big Bro" or the name, お姉さん →
  "Sis" or "miss" (a stranger), 店員さん → "the clerk". Pick what the scene calls for and note non-obvious calls.
  お姉ちゃん, paired with "Big Bro", is "Big Sis" (Pinon, Ranka).
- **Claire's 後輩クン / 後輩ちゃん** for the player is kept like -senpai: "kouhai-kun" / "kouhai-chan" (decided
  2026-10-17, campus review). 後輩 as a common noun is translated ("junior", "underclassman").
- **Animals.** カバ牛君 / カバ牛さん (Ranka) is "Mr. Hippo-cow": the honorific rule is for people's names.
- **Scope.** This rule is for the campus text. Campaign, mission and voice-subtitle text follow the MUF style
  (shipped without honorifics: "Ms. Hayase"). When a campus line is shown in a campaign context, or the reverse,
  follow the text it belongs to and flag the row `uncertain`.
- **Width.** Honorifics cost 4-7 characters. Count them in; never cut the end of a sentence to make room.

## Campus work file and your output

- `work/translation/en/campus.json`: one row per distinct campus line (24,497 rows, 338 slices), in script
  order. **Do not edit it.**
- `python -I tools/corpus_slice.py show <N> --context 10 --campus` prints slice N. Each row shows the scene
  (script file), the **speaker** (from the name plate; `PLAYER/none` = the player, or narration with no plate;
  `choice` = a menu choice the player picks; generic roles such as `Clerk A` in plain English), the variant
  (`male` / `female` = the player's gender in that scene) and `xK` (used K times).
- Write `work/translation/en/slices_campus/slice_NNN.en.json` (**three** digits) in the same format as the
  corpus slices, every row of the slice. No Japanese in the file.
- `python -I tools/corpus_slice.py check <N> --campus`: fix every ERROR (a lost `\p` is an error); warnings are
  lines over 420 px (16 px font) or more than 3 lines.

## Campus text specifics

- **Male and female player.** Many scenes exist twice, once for each player gender (labels `..._male` /
  `..._female`). Translate each version on its own terms; the player's gender is known inside a version, so
  "he"/"she" for the player is fine there and only there.
- **The player character** is created by the player. Never give them a name; anyone addressing them uses what the
  Japanese uses.
- **Inner monologue** is written in （…）: keep the brackets as plain parentheses "( ... )".
- **Choices** are short lines between scenes (デザイン重視 "Focus on design"): imperative or noun phrase, short.
- **`\p` is the player's name** (backslash + p; in JSON write `"\\p"`). The game replaces it with the name the
  player chose: `よお、\p` → "Hey, \p.", `\p君` → "\p-kun". Keep every `\p`; place it where the name goes in
  English. Never write a name in its place, and never give it a gender outside a male/female-only scene.
- **Line breaks:** the message window holds up to 3 lines of about 420 px in the 16 px campus font (measured in game). Break
  where English reads naturally; the line count may differ from the Japanese (up to 3).
- **Register:** lively, colloquial school talk (BASE_RULES). Teachers (Hilda, Gary, Yamashiro, Pinon-sensei) and
  officers keep their own voice.

## Names and terms

`work/glossary/` is the authority. Use `en`; never an `avoid` spelling. `ja_aliases` maps the short forms TF uses
(ピノン, ヒルダ, 金竜, ゴーストＶ－９...).

- Decided, not to be reopened: Vrlitwhai Kridanik, Quamzin Kravshera, Milia Fallyna Jenius, Jeffrey Wilder,
  Gepelnitchi, Golg Boddole Zer / Boddole Zer, Gamlin Kizaki, Michael Blanc (Michel when the Japanese says
  ミシェル), Luca Angeloni, Shin Kudo, Hoilie.
- 統合軍 → "U.N. Forces"; 新統合軍 → "New U.N. Forces"; 反統合同盟(軍) → "Anti-U.N. Forces"; ゼントラーディ軍 →
  "Zentradi forces" / "the Zentradi"; バロータ軍 → "Varauta Army".
- The four player pilots have MUF's names in TF (Yuuto Kagura, Gary Murdoch, Miyuki Shirakawa, Hilda V. Bergen).
- New TF names (Macross II wingmen, Metal Siren, campus places): see `docs/glossary.md`. Entries with status
  `provisional` or `needs_check` may still change; flag rows that use them.
- Missing name: translate as well as you can, flag `name_missing`, list it in `report.missing_glossary`.

## Gender

Never infer gender from a name. Use `gender` in `characters.json`. Anyone not in the glossary gets neutral
wording; the player too, except inside a male- or female-only campus scene.

## Character set and codes

Shift-JIS only, plain ASCII wherever possible (as AF). Also allowed: `…` `☆` `♪` `×` `○` `△` `□` and arrows,
`Ⅱ` `Ⅲ`, `α` `γ`. No `é`, `ō`, em dash. Full-width letters and digits become ASCII (`ＶＦ－２５Ｆ` → `VF-25F`).
Keep placeholders (`%s`, `%d`), control codes, `\p`, button symbols and asset labels exactly as they are.

## Quality bar (from BASE_RULES)

- Restore subjects and verbs that Japanese drops when the context settles them; check who asks whom.
- Full strength: no softening.
- Before each row, settle who speaks to whom and what it answers. Report non-obvious calls in
  `report.uncertain`.
- Flag every row where you kept an omission (`kept_omission`).
- Report rows examined vs rows in slice.
