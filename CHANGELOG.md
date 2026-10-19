# Changelog

## [0.1.25] - 2026-10-19

### Fixed
- **Campaign froze, then crashed, after clearing the Macross Zero era**, and every later attempt to play Campaign
  froze (reported on 0.1.23 with a save). Clearing the era unlocks Survival Mode; the code copies the notice
  ("Survival Mode has been unlocked.") into its message buffer with an inlined fixed-length copy: 16-byte chunks
  from the string's address until an end address it loads from a literal (0x414F6C, the old string + 0x20).
  The EBOOT insertion had moved the English string, so the copy never reached that end and ran through memory.
  Found in PPSSPP with the save: the main thread was stuck in the copy loop at 0x202FD0.
- The same kind of copy, with the end address held in a register, reads the Hangar tip ("When picking
  units/characters in the Hangar…"), so it would have hung the same way. Two more strings are copied with a fixed
  length (the "Standing by" network notice and the wireless-play confirmation): moved, they were cut off without
  a terminator.
- `tools/dump_eboot.py` now flags as `inline_copy` every string whose address code builds with lui/addiu and
  then loads bytes from (4 strings); `tools/eboot_insert.py` keeps those in place and limits them to the
  Japanese length. The Hangar tip and the wireless-play line were shortened to fit (92 and 48 bytes).
- The 不明 name label at vaddr 0x40C6C0, copied as 5 bytes, showed "Unkno" without a terminator; it is now "???"
  (`OCC_EN` in `tools/corpus_slice.py`: per-occurrence English, the other uses of the row keep "Unknown").
- Checked in PPSSPP with the reported save: Campaign shows the pending prizes (new missions, a title), mission
  select loads, and switching eras (Macross Zero, Extra, Survival, Tutorial) works.

## [0.1.24] - 2026-10-18 (test build, not released)

### Fixed
- **Academy schedule: class descriptions broken mid-word** ("Core st / udy of / ... / subjec / ts", running out
  of the box). The box (code 0x254030) cuts a line every box width / (font size + spacing) bytes: one
  Japanese character per cell, so about 7 English letters. `tools/vwf_build.py` now halves that divisor (half a
  cell per byte, as the VWF draws ASCII), so a line holds 14 characters. The `bnez` that guarded the division
  becomes the shift and the `break` behind it a nop. Found with a memory breakpoint on the description string in
  PPSSPP; the only caller of the line cutter 0x130668 is this box.
- The 15 subject descriptions (`gop_sjitem`) re-broken to at most 14 characters per line, 4 lines.
- Checked in PPSSPP (an Academy save in November of year 2): Mech. Eng., EX-Gear Basics and Basic Training
  descriptions wrap between words inside the box. Skill descriptions in Learn Abilities use another routine and
  are unchanged.

### Known
- The Academy header on the New / Load screen is cut to "Academ"; on the Load screen the date of a save is drawn
  over "Mihoshi Academy".

## [0.1.23] - 2026-10-18

### Fixed
- **Black screen with only the date after an Academy practical test** (reported on 0.1.22 with a save state, the
  EX-Gear test of `scd_skl_505`): the campus script insertion repointed every push whose value was the pool
  offset of a translated Japanese string, also numbers passed to non-text built-ins. 262 pushes in 54 scripts
  were changed that way: built-ins 0x15, 0x17, 0x1D (argument 1), 0x22, 0x23, 0x25, 0x31, 0x3E, 0x4F, which take
  ids and flags. In `scd_skl_505`, 0x23 got 0x902 instead of 0x6B (107) and the result scene never started.
  `tools/insert_text.py` now repoints only the arguments of 0x00 (a line) and 0x01 (choices); the 262 pushes keep
  their original values (`docs/formats.md`, "Campus event scripts").
- Checked in PPSSPP: the reported save state, loaded on this build, finishes the test and plays the result
  scene (the same state on 0.1.22 stays black).
- Players on 0.1.22: load a save made before the practical test, or the same state with this build; the bad
  value is only in the script on the disc.

### Build
- `python tools/build_iso.py 0.1.23 --images --in-place --voice-subs work/translation/en/voice/voice_subs.en.json`
  (log `work/output/build_0.1.23.log`), then `tools/relayout_iso.py` as in the release guide. No file moved
  compared to 0.1.22; 54 scripts are a byte or so shorter or longer in place.
- Release image: 1,704,689,664 bytes, SHA-256 `085d09a53dc606c96bf42bb0f52709dc7392175ef953ce4e3c05fc500bf8f311`;
  source commit `287c29c2d1737dcea07714ac91670ebea8514a17`. Patches: full 19,653,553 bytes, 0.1.22 to 0.1.23
  84,741 bytes (`docs/releases/0.1.23/`).

## [0.1.22] - 2026-10-17 (first public release)

### Changed
- **Release images keep the data where it was** (`tools/build_iso.py --in-place`, `tools/muf_archive.py repack
  --in-place`): a changed file or rebuilt bundle that fits in its own slot (up to the next entry, no entry sharing
  it, the newly covered bytes zero in the original) is written over its original bytes instead of appended. The
  voice subtitle tails now fit after their clips (16,694 files in place, 1,307 appended; 428 of 518 bundles in
  place), so macross.dat grows by 13 MB instead of 365 MB and fileset.dat by 14 MB instead of 54 MB. xdelta's
  64 MB source window could not match the moved data: the release patch went from 1.33 GB to 19.6 MB.
- First public release on GitHub (`retro-trans/Macross-Triangle-Frontier`), packaged with Retro Trans Tools.
  Same content as 0.1.21.

### Build
- `python tools/build_iso.py 0.1.22 --images --in-place --voice-subs work/translation/en/voice/voice_subs.en.json`
  (log `work/output/build_0.1.22.log`), then
  `python tools/relayout_iso.py "Macross - Triangle Frontier (Japan).iso" "work/output/Macross Triangle Frontier (EN v0.1.22).iso" "work/output/Macross Triangle Frontier (EN 0.1.22).iso" --write`.
- Release image: 1,704,689,664 bytes, SHA-256 `0b2bee48309c64a8e09342c9c13e56f189d7d08c4e28497634dbde02eabb5979`
  (`docs/releases/0.1.22/BUILD-MANIFEST.json`); source commit `d08cbd153eca8cdfea5a6236b1d30639bb136ccc`.
- Patch `MacrossTriangleFrontier-English-0.1.22.xdelta`: 19,654,323 bytes, built and validated with
  `retro_trans.release`.

## [0.1.21] - 2026-10-17 (test build, not released)

### Added
- **Version stamp on the title screen**, bottom right, as in the Retro Trans Super Robot Wars Z patch:
  "v<version>" over "github.com/retro-trans", white with a dark edge, drawn on the copyright strip
  (`data/menu/top/title05.gim`).
  - `tools/redraw_images.py`: `--version` replaces `{version}` in item texts; a layout entry's `extra_items` are
    drawn on top of the texture's own items. `tools/build_iso.py --images` passes `v<version>`, so every build
    stamps its own number.
- Checked in PPSSPP: the title screen shows "v0.1.21" and "github.com/retro-trans".

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.21).iso`:
  `python tools/build_iso.py 0.1.21 --images --voice-subs work/translation/en/voice/voice_subs.en.json` (log
  `work/output/build_0.1.21.log`). 3,307,216,896 bytes, SHA-256
  `E56E7E6BEFDD52A550AE11A7EABA1439772284A58AFC189B651553E629EE4A46`.

## [0.1.20] - 2026-10-17 (test build, not released)

### Fixed
- **Mission briefings drawn wrong** (reported on "Invasion of the Unknown"): the first line showed the whole
  briefing squeezed, the second line repeated its end. A briefing line is copied into a buffer of 78 bytes plus
  its end mark; the tools allowed 79 (the Ultimate Frontier size), so a full 79-character line lost its end mark
  and ran into the next line. The Japanese briefings never go past 78 bytes on a broken line.
  - `tools/corpus_slice.py`: briefings wrap at 78 bytes (measured in Shift-JIS bytes, so ☆ counts 2). 49
    briefings re-wrapped; 8 that no longer fitted in two lines shortened (u2864, u2893, u2899, u2980, u3010,
    u3141, u3143, u3196).
  - Mission objectives (the two lines above a briefing) re-broken to the Japanese sizes, line 1 <= 40 bytes,
    line 2 <= 44 (9 rows; u2950 and u2989 reworded slightly, u3177 break moved).
  - No line of the patched `mission_ext.csv` is longer than the longest Japanese one.
- `tools/ppsspp_ctl.py`: with `PPSSPP_PID`, a fallback screenshot captures only that process's window.

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.20).iso`:
  `python tools/build_iso.py 0.1.20 --images --voice-subs work/translation/en/voice/voice_subs.en.json` (log
  `work/output/build_0.1.20.log`). 3,307,214,848 bytes, SHA-256
  `C49EB61B65FF081AF1D4C14FD5BC5CDEBD9BC0AB2D4FBCED1E5B9058D17B91CA`.
- Not yet seen in game: the re-wrapped briefings.

## [0.1.19] - 2026-10-17 (test build, not released)

### Fixed
- **Friendly units shown as enemies in missions** (reported in "Invasion of the Unknown"; also in the first Zero
  mission, and in every build since 0.1.0): wingmen and allies had red "EN" tags in the unit list and red marks
  on the radar, and some allied units were missing. Cause: the EBOOT string 追加装備 ("Add-on Equipment") is not
  only a label but the column name the game looks up in the unit placement files `data/locate/*.csv`. Translated,
  the column was not found and the unit rows were misread. The string now stays Japanese (`NOT_TEXT` in
  `tools/dump_eboot.py`, corpus row u2102 `not_text`); it is never shown in game.
  - Found by testing in PPSSPP against the Japanese game: the `.bss` gap alone (fine), the translated EBOOT
    without the VWF patches (bug), then halves of the string groups.
  - Checked: no other translated EBOOT string stays in Japanese as a whole cell or token in the patched data
    except unreferenced leftovers (old pool bytes in `.fes` / `.asb`), the path files' comment column, and
    フォーメーション (a menu label pair, tested harmless).

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.19).iso`:
  `python tools/build_iso.py 0.1.19 --images --voice-subs work/translation/en/voice/voice_subs.en.json` (log
  `work/output/build_0.1.19.log`). 3,307,214,848 bytes, SHA-256
  `0DBE6B8AB4206D1234B6B28C82691D7C91E6EA4E0E2918386F98A3C7F9282C76`.
- Checked in PPSSPP: first Zero mission, green "FR" tags, allies on the radar and the map, voice subtitles.

## [0.1.18] - 2026-10-17 (test build, not released)

### Added
- **Voice-clip subtitles** (`docs/voice_subtitles.md`): during missions an English line now shows under the cut-in
  portraits while each voice clip plays. 16,957 of 18,759 clips have a subtitle.
  - 14,596 clips are byte-identical to Ultimate Frontier / Ace Frontier clips and reuse their transcripts and
    reviewed English (12,834 subtitles).
  - 4,163 TF clips were transcribed with Whisper and translated in 52 slices by agents
    (`docs/voice_translation_brief.md`): the new operators Exsedol Folmo and Catherine Glass, the Academy player
    voices, the operators' lines for TF's new missions, Silvie Gena, Hibiki Kanzaki, Bobby Margot, Canaria
    Berstein, Nanase Matsuura and new lines of the Frontier cast (4,123 subtitles).
  - Not subtitled: 1,155 silent placeholder clips, 261 shouts and grunts, 47 era-prologue narration clips (the
    prologue already shows English text).
- EBOOT hooks found again in TF's code (`tools/voice_subs_patch.py`): the clip's line is read from a tail
  appended to the clip in macross.dat when its lip-sync file loads, and drawn with the game's text routine
  (12 px, box 232 px) under the cut-ins. Code and state in the eboot_insert reserve after the VWF tables.
- `tools/build_iso.py --voice-subs <file>` / `--voice-placeholder`.

### Changed
- `tools/iso_patch.py` copies replacement files in chunks (the grown macross.dat no longer fits in 32-bit
  Python's memory); `tools/muf_archive.py` aligns appended voice clips to 0x800, as TF's originals.

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.18).iso`:
  `python tools/build_iso.py 0.1.18 --images --voice-subs work/translation/en/voice/voice_subs.en.json` (log
  `work/output/build_0.1.18.log`). 3,307,214,848 bytes (the subtitled clips are appended), SHA-256
  `5644E346E4D66D0CDDCF759FC3C2B74390DCEF4EBF6986CB3B58C37F75C0F6D5`.

### Known
- Tested in PPSSPP in the first campaign mission only (Yuu, the pilot and partner cut-ins). Not seen in game: the
  new operators, the second voice slot (two clips at once), "2D Display" off, real hardware.
- Voice wording to settle: "Michael" (shared MUF lines) vs "Michel" (one new Alto line) for Misheru; Alto's
  S.M.S. rank; "Charge Guard" in old tutorial takes; names missing from the glossary (VT-1 Ostrich, VA-3 Invader,
  Super Parts, Heavy Weapon Pack, Anima Spiritia, Minmay Defense, Rabbit 1, Eddie).

## [0.1.17] - 2026-10-17 (test build, not released)

### Changed (final campus review)
- Scanned all 24,497 campus lines for variants of glossary terms, honorific forms, untranslated text, spacing
  and punctuation, and rare words not seen in the MUF/AF English (1,674 checked by eye: interjections, stutters,
  cut-off words, series names; no misspelling found). No Japanese is left in the campus English.
- 21 lines aligned:
  - "soft serve" unhyphenated throughout (13 lines; glossary entry added).
  - Claire's 後輩クン / 後輩ちゃん: "kouhai-kun" / "kouhai-chan", kept like -senpai (4 lines; glossary and
    translation brief).
  - Miyuki's laugh "Hehe" in the three lines that had "*giggle*".
- Checked and kept: "Major Ozma" (only where the Japanese has shousa), Michel's "Sis" (his late sister Jessica),
  the 28 lines that start in lower case (sentences that continue from the previous line), every rare honorific
  form (each follows the Japanese, e.g. Yamashiro's "-kun" for girls).
- Translation brief: "Big Sis" for onee-chan, the kouhai rule, "Mr. Hippo-cow".

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.17).iso`: `python tools/build_iso.py 0.1.17 --images` (log
  `work/output/build_0.1.17.log`). 2,928,465,920 bytes, SHA-256
  `9D8E01F71D98A0A94518B15ADB3A6942384AEFCE27277D10D8AD0AF3F8163CC7`.

### Still open (need an in-game look, not a text change)
- Lines that also play under another name plate in one branch (listed in 0.1.10-0.1.14), the dropped empty
  second lines (0.1.9), developer placeholder lines (translated literally).
- Unconfirmed names: Silver Moon, Deep Akihabara, Gyararashi, the "199" store, Frontier Administrative Bureau.

## [0.1.16] - 2026-10-17 (test build, not released)

### Added
- **English textures** (`docs/image_redraw.md`): 597 textures redrawn, 818 text items, none overflowing.
  - 326 textures identical to ones Ultimate Frontier or Ace Frontier redrew take their English and layout
    (`tools/tex_port.py`): system and music buttons, mission title cards, HUD banners, settings, record panels.
  - 271 TF textures reviewed by four agents (`docs/image_translation_brief.md`, `tools/tex_tasks.py`): the
    campus menus (schedule, status, Issue Student ID, the student ID card, character creation, calendar tabs, grade
    stamps, date profile), the top menu and its round buttons, title copyright, 88 new mission title cards, HUD
    banners and countdown pieces, gallery viewer and tabs, settings tabs, shop labels, network rules.
  - Kept as art: series logos, signs in pictures (school gate, Nyan-Nyan seal, staff roll stills).
- Tools: `gim.py` reads RAIC-packed textures; `redraw_images.py` writes them packed and also writes the bundle
  copies (`_variants/`), takes rows for identical copies (`work/ui/tex_same.json`), skips `keep_original` rows and
  accepts an explicit `erase_box`.

### Changed
- `tools/build_iso.py --images` now includes the texture redraw (step 3b).

### Fixed (seen in 0.1.15)
- Atlas words cropped by the game ("Academ" in the top menu header, "Set Star" on the nickname screen): the
  English is drawn inside the old glyph box.
- Mixed full and short pilot stat labels: all seven are 3-letter forms.

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.16).iso`: `python tools/build_iso.py 0.1.16 --images` (log
  `work/output/build_0.1.16.log`). 2,928,465,920 bytes, SHA-256
  `DF8F912DC199F65DA91ADCB98798FFFFCB51B24ACFCE44B957F3CBA64D833931`.
- 0.1.15 was the first texture build (SHA-256 `1453306D...05DA0D`); superseded.

### Known
- The name-entry keyboard's symbols key is still Japanese (`gop_keyboardlist.gop`).
- Not yet seen in game: campus schedule/status/date screens, title cards, HUD banners, gallery, settings, shop.
- Open wording: gallery tab "Academy Life" (the art beside it says SCHOOL LIFE); the Macross F movie copyright
  holder line; grade stamps fell back to letters A / B / C.

## [0.1.14] - 2026-10-17 (test build, not released)

### Added
- **Campus batch 14, slices 271–293** (1,647 lines): the rest of the everyday scenes (Ranka, Sheryl, Yui
  Hoshimura, Yuu Akimizu) and the scheduled event series scd_arm (enlistment test to the final operation) and
  scd_ciz (civilian branch). **All 24,497 campus lines are English**; all 338 campus slices pass with 0 errors
  and 0 warnings.
- Glossary: Zentradi Sesame Balls, Maintenance Course.

### Changed
- Evacuation broadcasts c20693, c21038, c21066 open with "This is the Macross Frontier Administrative Bureau."
  (organizations.json), in place of "government".
- c16818: taiiku "P.E.".

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.14).iso`: `python tools/build_iso.py 0.1.14` (log
  `work/output/build_0.1.14.log`). 2,889,758,720 bytes, SHA-256
  `5479F812203F468F3765105051341A18D5627A45CD16EE4E7A6EA2A2D49A182F`. 48,406 campus references in 1,016 scripts.

### Known (for the final campus review)
- Frontier Administrative Bureau is still needs_research in organizations.json; "downtown Frontier" for
  Frontier shigai (c20765) has no glossary entry.
- c20447 (Akimizu's "Good work, \p-kun.") also closes the female branch of nml_yuu_006; script slip, kept.

## [0.1.13] - 2026-10-17 (test build, not released)

### Added
- **Campus batch 13, slices 246–270** (1,658 lines): everyday scenes of Luca, Michel, Miyuki Shirakawa, Nanase,
  Pinon and the first of Ranka's. All 315 campus slices pass with 0 errors and 0 warnings. 22,851 of 24,497
  campus lines are English (93%).
- Glossary: Chilled Galaxy Noodles, Super-Spicy Maguro Chili-Chili Bowl, rainbow carrot bun.

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.13).iso`: `python tools/build_iso.py 0.1.13` (log
  `work/output/build_0.1.13.log`). 2,889,660,416 bytes, SHA-256
  `41E7A9D2D8FF963382B520478CBEC6764BFC49A85928F4366C01E26446101373`. 45,922 campus references in 997 scripts.

### Known (for the final campus review)
- More lines whose occurrences carry a different speaker plate in one branch (c17831, c17858, c18630, c18668,
  c18686, c18806, c18414); translated for the speaker of their real uses.
- Miyuki's kusukusu is "Hehe" here but "*giggle*" in c10537.

## [0.1.12] - 2026-10-17 (test build, not released)

### Added
- **Campus batch 12, slices 221–245** (1,682 lines): everyday scenes of Claire, Gary, Hilda, Itsuki Yamashiro,
  Yuuto Kagura, Klan, Luis and the first of Luca's. All 290 campus slices pass with 0 errors and 0 warnings.
  21,193 of 24,497 campus lines are English (87%).
- Glossary: Starlight Natto.

### Changed
- c16823/c16844: taiiku "P.E." as in the other campus slices.

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.12).iso`: `python tools/build_iso.py 0.1.12` (log
  `work/output/build_0.1.12.log`). 2,889,578,496 bytes, SHA-256
  `8616FB1E32A359D83EAC9D700D63A5CF67F2E6135B319B894387111B7DDF4CF2`. 43,545 campus references in 964 scripts.

### Known (for the final campus review)
- Player monologue lines that also play under an NPC name plate (c16176 Claire, c16284 Gary, c17342 Klan's shout
  under no plate, c17757/c17797 under Luca): script leftovers; check in game.
- hoken taiiku is "health class" in Gary's joke (c16378) and "Health and P.E." in Hilda's scenes.

## [0.1.11] - 2026-10-17 (test build, not released)

### Added
- **Campus batch 11, slices 196–220** (1,761 lines): the rest of Yui Hoshimura's friendship scenes, all of Yuu
  Akimizu's, and the first everyday scenes of Alto, Brera and Claire. All 265 campus slices pass with 0 errors and
  0 warnings. 19,511 of 24,497 campus lines are English (80%).
- Glossary: Chiba Sound (Macross 7 Song Energy unit), Janice Merin, Miranda Merin (mentioned only, unverified).

### Changed
- c04141/c04142: "the artificial island" lowercase in dialogue, as the glossary says (matches c14024).

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.11).iso`: `python tools/build_iso.py 0.1.11` (log
  `work/output/build_0.1.11.log`). 2,889,463,808 bytes, SHA-256
  `C7202FA8EEACCF234B203563247D0F70213C5A01A514661C47E15F11CC32B568`. 40,864 campus references in 915 scripts.

### Known (for the final campus review)
- c15933/c15941: bracketed inner monologue under Brera's name plate, translated as the player's thought.
- c15172: the book title has "menace" (kyoui) where "wonder" may be meant; kept literal.
- Alto's "Mihaeru" is "Michael", Michel's nickname "Michel" (as in slices 309 and 337).

## [0.1.10] - 2026-10-17 (test build, not released)

### Added
- **Campus batch 10, slices 171–195** (1,825 lines): the end of Pinon's outings, Ranka's and Sheryl's friendship
  scenes (story, endings and outings) and the start of Yui Hoshimura's. All 240 campus slices pass with 0 errors
  and 0 warnings. 17,752 of 24,497 campus lines are English (72%).

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.10).iso`: `python tools/build_iso.py 0.1.10` (log
  `work/output/build_0.1.10.log`). 2,889,342,976 bytes, SHA-256
  `272469EC3F84A91E49D7A1D85CABF2FE0F4528114D8C6C547AAB56365714FAA6`. 37,786 campus references in 885 scripts.

### Known (for the final campus review)
- Ranka's kabaushi-kun/-san is "Mr. Hippo-cow" (honorific on an animal, not a name).
- c13373 plays ten times in frd_rnk_110, mostly at scene cuts under varying name plates; c14005 (Sheryl) plays
  under Nanase's name plate in frd_she_102. Both look like script leftovers; check in game.
- "Artificial Island" capitalised in c04142, lowercase in its twin c14024.
- Sheryl's recipe book "Handpicked! Galactic Sweets Paradise" is not in the glossary.

## [0.1.9] - 2026-10-17 (test build, not released)

### Added
- **Campus batch 9, slices 146–170** (1,868 lines): friendship scenes of Miyuki Shirakawa (to her ending and
  outings), Nanase (through her outings) and Pinon (through her outings). All 215 campus slices pass with 0 errors
  and 0 warnings. 15,927 of 24,497 campus lines are English (65%).
- Glossary: Galaxy Parfait, "art department" (Nanase's word, distinct from the Art Course), Sheryl's single
  "What 'bout my star?".

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.9).iso`: `python tools/build_iso.py 0.1.9` (log
  `work/output/build_0.1.9.log`). 2,889,242,624 bytes, SHA-256
  `6BAED4755960D1E2C07906B1C6F5E5DCEB6DEE6A1567C5A4CAC97FAAEB4A7E54`. 34,848 campus references in 867 scripts.

### Known (for the final campus review)
- Some lines end with an empty second line (a full-width space); translators dropped it. Check in game that no
  scene relies on it.
- Developer placeholder lines (affinity-ending filler for Shirakawa, Nanase, Pinon) are translated literally.
- Silver Moon and Deep Akihabara rows are flagged uncertain until the names are confirmed.
- Pinon's onii-chan/onee-chan are "Big Bro" / "Big Sis"; the brief gives "Sis" for onee-san.

## [0.1.8] - 2026-10-17 (test build, not released)

### Added
- **Campus batch 8, slices 121–145** (1,759 lines): friendship scenes of Luca and Michel and the start of
  Shirakawa. All 190 campus slices pass with 0 errors and 0 warnings. 14,059 of 24,497 campus lines are English
  (57%).

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.8).iso`: `python tools/build_iso.py 0.1.8` (log
  `work/output/build_0.1.8.log`). 2,889,146,368 bytes, SHA-256
  `61B456F478D88B4A4F3BF7D34989CF12E8AF2DA3823D9DA43447AB99FA66D2FF`. 31,546 campus references in 853 scripts.

### Known (for the final campus review)
- "soft serve" / "soft-serve" both occur.

## [0.1.7] - 2026-10-17 (test build, not released)

### Added
- **Campus batch 7, slices 96–120** (1,854 lines): friendship scenes of Kagura, Klan and Luis, and the start of
  Luca. All 165 campus slices pass with 0 errors and 0 warnings. 12,300 of 24,497 campus lines are English (50%).
- Glossary: raibu (live performances) is "concert" (Luis's street shows "gig"; 23 rows aligned), "Nyan-Nyan Dance",
  L.A.I., Jessica (Michel's sister), "macronized" for Klan at Zentradi size.

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.7).iso`: `python tools/build_iso.py 0.1.7` (log
  `work/output/build_0.1.7.log`). 2,889,029,632 bytes, SHA-256
  `FB1557B7F4CD0E1491FA5389358C0843B2FF322DEB6C764C600A0E3C73816022`. 28,598 campus references in 832 scripts.

## [0.1.6] - 2026-10-17 (test build, not released)

### Added
- **Campus batch 6, slices 71–95** (1,829 lines): friendship scenes of Gary, Hilda, Yamashiro and the start of
  Kagura. All 140 campus slices pass with 0 errors and 0 warnings. 10,463 of 24,497 campus lines are English (43%).
- Glossary: Observation Pier, Super Chili-Chili Dog. Hilda's stretching rule is 'Hurts-Good' throughout.

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.6).iso`: `python tools/build_iso.py 0.1.6` (log
  `work/output/build_0.1.6.log`). 2,888,857,600 bytes, SHA-256
  `582B55EF068811F47BC2CB63CD2CD772F12BDDD135F00FF63D3E251A17444E17`. 24,730 campus references in 785 scripts.

## [0.1.5] - 2026-10-17 (test build, not released)

### Added
- **Campus batch 5, slices 46–70** (1,874 lines): the last side events (Sheryl, Yui, Yuu) and the first
  friendship scenes (Alto, Claire, Gary). All 115 campus slices pass with 0 errors and 0 warnings. 8,634 of 24,497
  campus lines are English (35%).
- Glossary: "Folmo" (the shopping mall; "Formo" avoided, 4 rows fixed), "artificial island".

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.5).iso`: `python tools/build_iso.py 0.1.5` (log
  `work/output/build_0.1.5.log`). 2,888,716,288 bytes, SHA-256
  `C6F73E7C57932F276521A29114DAA6B170C0A9E3F0D0320D628146A60C6146D5`. 20,690 campus references in 749 scripts.

### Known (for the final campus review)
- "junior-kun" / "junior-chan" for Claire's 後輩クン (maybe "kouhai-kun"); "Artificial Island" capitalised in
  place labels but lowercase in dialogue; the store "199" is unverified.

## [0.1.4] - 2026-10-17 (test build, not released)

### Added
- **Campus batch 4, slices 21–45** (1,867 lines): the rest of the character side-events (Klan, Cathy, Luis, Luca,
  Michel, Shirakawa, Nanase, the ending scenes, Ozma, Pinon, Ranka, Sheryl). 5 agents; all 90 campus slices pass
  with 0 errors and 0 warnings. 6,760 of 24,497 campus lines are English (28%).
- Glossary: "Diamond Crevasse" (song), "rainbow carrots" (Nanase's carrots).

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.4).iso`: `python tools/build_iso.py 0.1.4` (log
  `work/output/build_0.1.4.log`). 2,888,372,224 bytes, SHA-256
  `380BF3212053A9EADF56ADD60610F7E6722E898C278ED1CDB85B0D22E8B299E5`. 16,209 campus references in 608 scripts.
  Not played (side events trigger later in Academy mode).

## [0.1.3] - 2026-10-17 (test build, not released)

Campus batch 3: the common route.

### Added
- **Campus slices 298–322** (1,963 lines): the common route every player goes through (Nyan-Nyan, Ozma's
  warning, Sports Day, Cathy's recruiting visit, the Sheryl autograph raffle, Christmas, Valentine's Day, White
  Day, the Culture Fest café, Ranka and Sheryl transferring in, Grace's first meeting, summer break and the
  career surveys). 5 agents; all 65 campus slices so far pass with 0 errors and 0 warnings. 4,893 of 24,497
  campus lines are now English.
- Glossary decisions: the pilot parameters 体力 Stamina, 速度 Speed, 格闘 Melee, 防御 Defense, 射撃 Shooting,
  集中 Focus, 覚醒 Awakening (also the ID-card labels for the texture redraw); Luis's nickname for the player,
  "Fresh Boy" / "Fresh Girl".

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.3).iso`: `python tools/build_iso.py 0.1.3` (log
  `work/output/build_0.1.3.log`). 2,888,093,696 bytes, SHA-256
  `01A1BDE5E3A83248F2FCF6355864E709CEE85B0DE0FD9275F47949FD73D456B4`. 11,860 campus references in 508 scripts.
  Not played: the common-route scenes come after the opening checked in 0.1.2.

### Known
- Unverified names: ギャララシ "Gyararashi" (a plush creature tied to Mylene), ピノピノ "Pino-Pino" (Yui's
  nickname for Pinon).

## [0.1.2] - 2026-10-17 (test build, not released)

Campus batch 2: the story scenes a new Academy player meets first.

### Added
- **Campus slices 294–297 and 323–338** (1,430 lines): the start of the common route (meeting Alto, Michel,
  Luca, Nanase, the teachers, Klan, Ranka at Nyan-Nyan), the festival, skill-test and S.M.S. routes, the trial
  course (the first scenes of Academy mode) and the test scenes. 5 agents; all 40 campus slices so far pass the
  check with 0 errors and 0 warnings. 2,930 of 24,497 campus lines are now English.
- Glossary decisions: 隊長 "Captain" (a squad leader's title; 少佐 stays "Major"), 座学 "Lectures",
  特殊座学 "Special Lectures", 実技 "Practical Training", 基礎 "Basic Training", 体育祭 "Sports Day",
  実技テスト "Practical Test", 芸術科 "Art Course", 超時空飯店 "Super Dimension Restaurant". 14 earlier rows were
  aligned (Captain Ozma, Sports Day).

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.2).iso`: `python tools/build_iso.py 0.1.2` (log
  `work/output/build_0.1.2.log`). 2,888,001,536 bytes, SHA-256
  `776911585DC894B464514D44EC17CE74977BA6494093D09632155B240E9C1919`. 8,289 campus references in 500 scripts.
- **Played in PPSSPP into the first Academy scene** (`work/ui/screens_0.1.2/`, local): character creation, the
  ID card birthday "2042/1/1", and the opening monologue in English, three lines in the window, sharp at 4x.

## [0.1.1] - 2026-10-17 (test build, not released)

Campus batch 1 of the staged campus translation.

### Added
- **Campus scenes, batch 1:** campus slices 1–20 (1,500 of 24,497 lines; the character side-events `ext_*`
  of Alto, Brera, Bobby, Claire, Canaria, the "???" woman, Gary, Hilda, Yamashiro, Kagura and Klan), translated by
  5 agents. All pass `corpus_slice.py check --campus`: 0 errors, 0 warnings. 5,928 references in 480 scripts.
- Glossary: hippo-cow, maguro bun, refresh (campus running gags).

### Changed
- **Campus window width measured in game:** about 420 px in the 16 px font (text from x 46 to 470), not the
  448 px estimate. The checker and the brief use 420; 4 lines were refit.
- Dates: 年 / 月 / 日 after numbers are now "/", "/" and a space (the ID card showed "2042Year1Month1Day").

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.1).iso`: `python tools/build_iso.py 0.1.1` (log
  `work/output/build_0.1.1.log`). 2,887,866,368 bytes, SHA-256
  `EEE4250B311988B8F1856557227558788C29E08097CF6F57CD39C8B3C61C1A54`.
- Checked by reading `ext_alt_001.asb` and `ext_kln_005.asb` back out of the built archive: English lines and
  `\p` in place. Not seen in game yet: side events trigger later in Academy mode. In 0.1.0, Academy mode was
  played into its first scene (character creation in English; the scene still Japanese).

### Known
- The first Academy scenes are story scenes (`scd_*`, campus slices 288–338), not in batch 1; batch 2 starts there.

## [0.1.0] - 2026-10-17 (test build, not released)

First translated build: everything except the campus (Academy) event scenes is in English, with the
proportional font and 4x text. Textures and voice are still Japanese.

### Added
- **Translation of all non-scene text.** `work/translation/en/corpus.json` (built by the new
  `tools/build_corpus.py`) holds every distinct Japanese string outside the campus event scripts once: 5,894 rows,
  8,744 places in the EBOOT, the menu CSVs, the mission scripts (FES 3.09), the unit lists and the campus data
  tables (`.gop`: era narration, names, event and gallery titles, schedule and operator help, staff roll).
  - 2,946 rows were prefilled from the Ultimate / Ace Frontier translations (identical Japanese) and reviewed.
    The rest were translated in 45 slices by 11 agents (`docs/translation_brief.md`); one more agent reviewed
    consistency (44 rows fixed). All slices pass `tools/corpus_slice.py check`: 0 errors.
  - 3 EBOOT "strings" are data that decode as text (vaddr 0x425EE0, 0x462E1C, 0x462E34): kept as `not_text`.
  - Briefings: every wrapped line is at most 79 characters and 2 lines (the 80-byte slot found in MUF);
    19 briefings were refit. One briefing (u3200) has a mistyped full-width break in the source; it is wrapped
    like the others and checked against the source bytes (`src_jp`).
  - Help boxes that neither wrap nor squeeze (operator window about 333 px, campus help line 365 px in the 16 px
    font): 7 lines refit.
- **Campus groundwork** (`docs/formats.md`):
  - `tools/asb.py`: the campus event-script bytecode (all 1,022 scripts parse; every Japanese string is a call
    argument; call 0x1D is the name plate) and insertion by appending to the pool and repointing pushes.
  - `tools/gop.py`: the campus data tables (GENESTRT string table rebuilt by index).
  - `tools/build_campus.py`: `work/translation/en/campus.json`, 24,497 distinct lines in 338 slices, each with
    its speaker, scene and male/female variant. `tools/corpus_slice.py --campus` shows and checks campus slices
    (16 px widths, `\p` kept).
  - `\p` in campus lines is the **player's name**, not a page break (corrects the entry below).
- **Insertion** (`tools/insert_text.py`): CSV cells and `.gop` strings with a literal backslash-n, FES 3.09,
  `.gop` tables (the packed plain copy and the 28 unpacked bundle copies), `.asb` scripts. A dummy run over every
  occurrence (8,744 + 48,406) inserts cleanly.
- **Archives** (`tools/muf_archive.py`): repack for TF's 8 containers, appending what changed and repointing the
  index and container heads. An unchanged repack is byte-identical; a 3-file change re-extracts with exactly
  those entries changed.
- **Variable-width English font and 4x text** (`tools/vwf_build.py`, `tools/vwf_font.py`, `docs/vwf.md`), ported
  from Ultimate / Ace Frontier to TF's rewritten text code: ASCII 0x20–0x7F gets proportional GenEi LateGo v2
  glyphs (glyph slots 1210–1305, unused by every TF string) in the 14 px font **and in the 16 px campus font**
  (`mpsp3_font16_slg.fnt`), with a 4x glyph page appended to each font for PPSSPP's 2x/4x rendering. Patches: the
  two shared advance routines (float 0x1300C8, int 0x1312A8, via helpers in a dead function), the bearing
  routines, the ASCII table routine, `(` `[` in the printer, the 3D-label glyph-array drawer, and Ultimate
  Frontier's glyph-lookup dispatcher plus 36 emitter loads. The font flags stay 0 (the operator / campus text
  window refuses flagged fonts). Needs `eboot_insert.py --reserve 4096` (tables 1,552 bytes; 2,544 left).
  Checked in PPSSPP at 4x: menus, operator window, campus character creation, character select (squeeze-to-fit),
  narration, a campaign mission (HUD names, 3D labels); Japanese unchanged.
- `work/ui/vwf_widths.json`: `font16.advance` for the campus font (the 14 px advances are unchanged).

### Fixed
- `tools/muf_archive.py repack`: a changed plain RAIC/RAIB file now gets its decoded size and its stored length
  (entry +20) in macross.idx and the container head. The old stored length cut the file short in game.
- `tools/build_iso.py`: reserve 4096 bytes and copy the whole VWF font overlay (both fonts, the `gameinit` copy).
- `tools/ppsspp_ctl.py`: a minimized PPSSPP window is restored before a window capture.

### Build
- `work/output/Macross Triangle Frontier (EN v0.1.0).iso`: `python tools/build_iso.py 0.1.0 --tr
  work/translation/en/insert.json` (log `work/output/build_0.1.0.log`). 2,886,404,096 bytes (grown files are
  appended; `relayout_iso.py` not run yet), SHA-256 `87EA1FECF070B24EBD6D7FFF760A54F7537FDACB05296F6947B076DD6377A034`.
  EBOOT 2,850 strings relocated, loader check ok.
- Played in PPSSPP (OpenGL, 4x) from boot into the first Zero mission (`work/ui/screens_0.1.0/`, local): autosave
  notice, operator help (Yuu), character select, era narration, the tutorial notice, mission select and
  information panel, the briefing, the "Proceed?" prompt, the HUD pilot names in flight.

### Known
- Text drawn into textures is still Japanese: the title submenu (Game Start / Data Install), menu bubbles, tab
  labels, button guides, the mission-info labels, HUD banners, the title copyright lines.
- Campus event scenes are still Japanese (next stage, in batches). The campus message window width (448 px in the
  16 px font) is an estimate until a scene is checked in game.
- Voice clips have no subtitles yet. Not tried at 1x or on real hardware.

## Translation brief and honorifics - 2026-10-16

### Decided
- **Honorifics are kept in the campus (Academy) text** (user decision): -san, -chan, -kun, -sensei, -senpai,
  -sama, -dono after the name, in romaji with a hyphen ("Pinon-chan", "Hilda-sensei", "Klan-senpai"); "Sensei" /
  "Senpai" alone as a form of address. Campaign, mission and voice text keep the MUF style without them. Ranks and
  job titles stay English; kinship words are translated.

### Added
- `docs/translation_brief.md` v0.1.0: TF rules on top of `BASE_RULES.md`, with the honorifics rules, campus-text
  rules (male/female scene versions, the unnamed player character, inner monologue, `\p` page breaks), names,
  gender, character set. The work-file section follows once the corpus tools exist.
- Glossary: `terms.json` → `honorifics` (7 entries, from `tf_additions.json`); `docs/glossary.md` records the
  decision and drops it from the open items.

## Glossary and tools - 2026-10-16

No build yet; the first build will be 0.1.0.

### Added
- **Project layout** as in `AGENTS.md`: `work/{output,glossary,ui,translation/en,source,local}`, `docs`, `tools`,
  `incoming`. `.gitignore` copied from Macross Ace Frontier (ISO, extracted data, Japanese working files).
- **Glossary 0.1.0** (`work/glossary/`, `docs/glossary.md`), generated by the new `tools/glossary_seed.py` from
  the Macross Ultimate Frontier glossary (base) and the Macross Ace Frontier glossary, plus the hand-kept
  `work/glossary/tf_additions.json`:
  - 129 characters, 125 units, 13 packs, 9 families, 12 mission objects, 54 organizations, 29 locations,
    63 lore terms, 68 game terms, 32 skills, 58 songs, 16 works, 18 ranks, 44 mission titles.
  - New per entry: `tf_uses`, `tf_campus_uses`; for characters `tf_role` (59 in the pilot table, 7 operators,
    campus).
  - Triangle additions: the Macross II wingmen (Saori Kujo, Amy Rock, Nastasha Toto: provisional surnames) and
    Ingues; Luca's Ghosts Simon, John and Peter; YF-25 Prophecy, VF-25A Messiah, VA-1SS Metal Siren, Proto Metal
    Siren, Queadluun-Quilqua, SNN Valkyrie, Hound Vajra, Tornado Pack; Antares Squadron, Faerie Squadron; campus
    places (Griffith Park, Central Park, Silver Moon, Arlington Cemetery, St. Maria Academy) and courses; the
    zodiac callsigns; The False Songstress and Macross II as works. Japanese forms TF writes differently were
    added to existing entries (金竜, 空母アスカⅡ, ゴーストＶ－９, given names for the campus cast...).
  - Dropped as absent from TF: the four magazine-collab cameos, 4 AF mission objects, 60 AF mission titles
    (`work/glossary/dropped.json`).
  - Gap check: characters 1 gap (a generic label), mecha 8 and objects 5 (collection items and generic objects
    for the UI translation). Open items are listed in `docs/glossary.md`.
- Tools copied from Macross Ace Frontier and adapted to TF:
  - `muf_archive.py`: **extract** reads the 8 containers named by the version-8 index (macross.dat,
    fileset.dat with 34 plain files, and the six small `cmp_*` / `operator_help` / `staffroll` containers) and
    keeps 960 differing bundle copies under `_variants/`. **Repack is not adapted** and refuses a TF manifest.
  - `dump_text.py`: FES 3.09, and the campus event scripts (`campus_strings.json`).
  - `dump_eboot.py`: AF-only "not text" addresses removed.
  - `glossary_check.py`: TF pilot table, editor-label filter, lore/terms/locations as a fallback match.
  - `muf_lzss.py`, `strip_jp.py`, `disasm.py` unchanged.
- `docs/formats.md`: TF disc, archive, EBOOT and campus-script notes, and how TF's content compares with
  Ultimate and Ace Frontier.

### Source
- Disc: `Macross - Triangle Frontier (Japan).iso`, ULJS00321 v1.01, 1,676,050,432 bytes, CRC32 `1729ad6c`.
- EBOOT decrypted with a portable PPSSPP copy in `work/local/ppsspp/`.

### Known
- `PSP_GAME/INSDIR/000` (PGD-encrypted install data, 290 MB) is not examined.
- The campus scripts' bytecode, speaker display and the `campus/interface/*.tbl` UI files are not decoded.
- The Redump entry for the image is not checked yet.
