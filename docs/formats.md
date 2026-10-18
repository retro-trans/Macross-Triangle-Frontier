# Data formats: Macross Triangle Frontier (PSP, ULJS-00321, Japan v1.01)

Triangle Frontier (TF) runs on the same engine as Macross Ultimate Frontier (MUF) and Ace Frontier (AF). MUF's
`../Macross Ultimate Frontier/docs/formats.md` describes the formats in detail; this page lists what was checked
on TF and where it differs.

## Disc

`Macross - Triangle Frontier (Japan).iso`, 1,676,050,432 bytes, CRC32 `1729ad6c`. PARAM.SFO: DISC_ID
ULJS00321, DISC_VERSION 1.01, APP_VER 01.00. Not yet checked against Redump.

| File | Size |
|---|---|
| `PSP_GAME/SYSDIR/EBOOT.BIN` | 6,081,936 (encrypted `~PSP`) |
| `PSP_GAME/SYSDIR/BOOT.BIN` | 6,081,600, all zero (no plain copy) |
| `PSP_GAME/USRDIR/macross.idx` | 1,116,106 (PIDX0 version 8) |
| `PSP_GAME/USRDIR/macross.dat` | 891,957,248 |
| `PSP_GAME/USRDIR/fileset.dat` | 285,357,488 |
| `PSP_GAME/USRDIR/cmp_gop.dat`, `cmp_if.dat`, `cmp_icon.dat`, `cmp_charmake.dat`, `operator_help.dat`, `staffroll.dat` | small containers, PIDX0 head + FSTS bundles (new in TF) |
| `PSP_GAME/INSDIR/000` | 289,816,352, PGD-encrypted: the optional data install. Not examined yet; check before any repack |
| `PSP_GAME/USRDIR/data/movie/m_title.pmf`, `data/sound/bgm/*.at3` (107) | plain ISO files |

## Extracting

```bash
python -I tools/muf_archive.py extract work/source/iso work/source/dat
python -I tools/dump_eboot.py
python -I tools/dump_text.py
```

Copy `EBOOT.BIN` and all `USRDIR/*.dat` plus `macross.idx` out of the ISO into `work/source/iso/` first
(7-Zip). Extraction takes about 3 minutes: 33,755 plain files in macross.dat, 34 plain files and 2,345 bundles
(294,660 members) in fileset.dat, 7 bundles in the six small containers; 65,374 unique files.

Differences from MUF/AF, handled in `tools/muf_archive.py extract`:

- **8 containers.** `macross.idx` is PIDX0 version 8. After the header sit 8 container slots of 0x20 bytes
  (name offset, 12 zero bytes, 16-byte id) at 0x30; the entry table starts at 0x130. The containers are
  macross.dat, fileset.dat, cmp_gop.dat, cmp_if.dat, cmp_icon.dat, cmp_charmake.dat, operator_help.dat and
  staffroll.dat. File entries and fileset records name their container.
- **Plain files in fileset.dat.** 34 map files (`data/map/add_far/...`) are stored plain in fileset.dat, not
  in a bundle. Each container's own PIDX head lists its plain files (checked by offset and size) and its bundles.
- **Differing bundle copies.** In MUF/AF a path always had one content. In TF 960 bundle members differ from the
  plain or earlier copy of the same path; extract keeps them under `work/source/dat/_variants/<bundle>/<path>`
  and marks them `variant` in `_meta/manifest.json`.
- **Overlapping entries.** Some original plain files overlap in their container (an entry's range runs into
  the next one's), so rewriting a file in place is unsafe.

## Repacking

`python -I tools/muf_archive.py repack work/source/dat <out_usrdir> --base work/source/iso --overlay <tree>`
copies every container from the original and **appends** what changed: a changed plain file (0x800-aligned,
0x800 for voice clips, as the originals), or a bundle with a changed member, rebuilt with the unchanged members' original packed
bytes. The idx entry or fileset record and the container's own head are repointed (heads are mapped by path for
plain files, by original (offset, size, count) for bundles). A path held by several bundles is updated in all
of them. Checked: an unchanged repack is byte-identical to the disc files (all 9), and a repack with one changed
plain file, one bundle member (in 5 bundles) and one cmp_if.dat member re-extracts with exactly those 7 of
328,995 entries changed.

## EBOOT

Decrypted the same way as MUF/AF: a portable PPSSPP copy (`work/local/ppsspp/`, copied from the AF project,
`DumpFileTypes = 3`) boots the ISO and writes `memstick/PSP/SYSTEM/DUMP/ULJS00321_EBOOT.BIN` (6,081,936 bytes,
`\x7FELF`, type 0xFFA0 PRX). The copy is kept at `work/source/eboot/EBOOT.dec.bin` (gitignored).
`python -I tools/dump_eboot.py` finds 2,943 Japanese strings (39,219 characters). Three of them are data that
happen to decode as text (vaddr 0x425EE0, 0x462E1C, 0x462E34; `NOT_TEXT` in the tool): relocating them breaks
two pointers, so the corpus keeps them as `not_text` rows that are never written. A fourth, 追加装備 (vaddr
0x40E940, code at 0x195C24), is text but also a key: the parser of `data/locate/*.csv` finds that column by its
Japanese header. Translated (0.1.0-0.1.18), the column was lost and the unit rows misread, so friendly units
came up as enemies in missions ("EN" tags, red on the radar). It is `NOT_TEXT` too since 0.1.19. Found by
bisecting the EBOOT strings in PPSSPP (`.bss` gap alone, text without VWF, then string groups).
`tools/eboot_insert.py
--reserve 3072` relocates the rest; a test with dummy English for all 2,850 text strings passes its loader
simulation (one 64 KB gap, reserve at vaddr 0x47A700).

Main tables (file offsets in the decrypted EBOOT):

| Offset | Content |
|---|---|
| 0x3CC7E4 | save / load messages |
| 0x3CFDD0 | pilot table: named pilots, campus slots (学園1..8), generic AI profiles |
| 0x3F3588 | mission names and objectives, weapon names and descriptions, unit names and descriptions (1,024 strings) |
| 0x3FED34 | large enemies, EX-Gear, time of day, factions, autosave messages, the 7 operators, colours |
| 0x400340 | skills and their descriptions |
| 0x405A68 | main menu help (campus mode, campaign, character creation) |
| 0x4084D0 | network play messages, gallery captions |
| 0x410EDC | ranks |
| 0x415888 | password entry |
| 0x41B004 | song weapons |

## Text dump

| File | Entries | Characters | Content |
|---|---|---|---|
| `eboot_strings.json` | 2,943 | 39,219 | everything listed above |
| `menu_text.json` | 2,270 | 63,157 | `data/menu/text/*.csv`: mission_ext (briefings), ms_ext (units), pack_ext, pilot_ext, nn_ext (Nyan-Nyan collection), and new in TF: bgm_ext, operator_ext |
| `fes_strings.json` | 313 | 9,168 | mission scripts (`FES 3.09`; string pool pointer at 0x12 as in 3.00/3.04) |
| `locate_names.json` | 1,403 | 11,335 | mission unit lists: display name, unit, pilot id |
| `gop_strings.json` | 2,208 | 25,930 | **new**: campus data tables (era narration, names, events, help, staff roll) |
| `campus_strings.json` | 37,136 | 708,559 | **new**: campus event scripts |

All contain Japanese and stay in `work/source/` (gitignored).

### Campus event scripts

`data/campus/event/script/{ext,frd,nml,scd}/*.asb`, 1,022 files, stored plain in macross.dat but each one is a
RAIC member (XOR 0x72 + LZSS, `tools/muf_lzss.py`). Decoded: a 4-byte zero, the file name at 0x04, then seven
u32 at 0x24; the 5th (0x34) is the string pool offset, the 6th its size, the 7th the decoded size. The pool
holds the labels (`@ext_alt_001_default_male`...) and every line as a NUL-terminated Shift-JIS string with real
newline bytes; a literal `\p` stands for the player's name (`\p君`, `よお、\p`). Many lines exist twice, once for a male and once for a female player
character. The file names carry a character code (`alt` Alto, `she` Sheryl, `rnk` Ranka, `pnn` Pinon, `yui`,
`hld` Hilda...).

The header's 7 u32 are: label table offset (0x44), label count, code offset, code size, pool offset, pool size,
file size. Labels are 0x14 bytes: pool offset of the name, two flags, code offset, code size.

**Bytecode** (`tools/asb.py`; all 1,022 scripts parse to their exact end): a stack machine.
`01 <u32>` pushes an immediate (numbers and string pool offsets alike); `29 <u32 fn> <u8 argc>` calls a
built-in with argc pushed arguments; `21`/`22 <u32>` jump / jump if false; `27 <u32>`; `05 24 <n> <n×u32>` is the
jump table after a choice, other `05 <4 bytes>` load a variable; `13 <2 bytes>` stores one; `00 02-04 06-0A 18
1B-20 2B` have no operand. Every one of the 38,147 Japanese pool strings is an argument of a call: function 0x00
shows a line, 0x01 offers 2-3 choices, others take variants of a line or the `　` placeholder. Function
0x1D sets the **name plate**: its argument is a speaker id, the record index in `gop_char.gop` (0 = no plate:
the player or narration, 1 Kagura, ... 11 Alto, ...).

**Only the arguments of 0x00 (a line) and 0x01 (choices) are text.** Pushes are untyped, so a number passed to
another built-in can equal the pool offset of a Japanese string by chance: 262 such pushes feed 0x15, 0x17, 0x1D
(argument 1), 0x22, 0x23, 0x25, 0x31, 0x3E and 0x4F, which take ids and flags (0x23: values 0-108). Up to 0.1.22
the insertion repointed them too; in `scd_skl_505` 0x23 got 0x902 instead of 0x6B and the scene after the EX-Gear
practical test stayed black with only the date. Since 0.1.23 `patch_asb` repoints only text-function arguments.

**Insertion** (`tools/insert_text.py`): the English is appended to the pool and the push operands are
repointed. Code size and offsets do not change; the header's pool and file sizes are updated, and the script is
re-encoded as RAIC. A test with dummy English for all 48,406 references in 1,016 scripts runs clean.

### Campus data tables (.gop)

`data/campus/gop/*.gop` (49 files, RAIC members): chunks of an 8-byte tag, u32 size, u32 0 and the data:
`GOP GFIN`, `GOP GMET` (column metadata), `GOP GREC` (records), `GENESTRT` (strings), `GOP GDAT`, `GENEEOF `.
`GENESTRT`: u32 count, 0x10, string data offset, chunk size, then count + 1 offsets (the last one is the end of
the string data), then the strings, padded to 16 bytes. Records refer to strings by index, so `tools/gop.py`
rebuilds the table with new strings and the rest of the file unchanged (the decoded rebuild of all 49 files with
the original strings is identical).

Strings before the `TABLE` marker are data; after it come the source `.xls` name and column descriptions, never
shown. The data strings (2,208, `gop_strings.json`) hold the era narration (`gop_campaignevent`), character
names and profiles (`gop_char`, also the speaker list), event and gallery titles, places, schedule and help
text, skills, the operator help with `[speed:N]` / `[wait:N]` tags (`gop_opehelp`) and the staff roll. Some
store a line break as backslash + n, others as a real newline (`lit_nl` per occurrence in the corpus).
`gop_keyboardlist` (the name-entry character sets) is not text.

The campus UI also has `campus/interface/**/*.tbl` (55) and textures: no Japanese text in the `.tbl` files.

## Content compared with Ultimate and Ace Frontier

Checked on 2026-10-16 by comparing the text dumps of the three games.

- **Missions:** TF has 315 mission records (`mission_ext.csv`); MUF has 216. 176 of MUF's 216 briefings are in
  TF word for word. The 40 that are not include MUF's AFOS story finale (MH), the enemy-side campaigns
  (Zentradi MZ_3xx, Protodeviln MD_3xx, Vajra MY_3xx), the Guld mission (MX), MUF's training and extra missions
  (ME_0xx–1xx, including the Famitsu/Dengeki magazine collabs) and a few Plus/7 missions.
- **New in TF:** Macross II (M2_*, 9), The False Songstress (MK_*, 8), 49 new extra missions (ME_300–830:
  conversion training, the zodiac team...), 102 survival/marathon records (MW_*), new training scripts
  (`mq_*.fes`, no briefing records), and the campus mode.
- **Ace Frontier:** AF's mission text was rewritten for MUF; only 3 of AF's 244 long EBOOT strings appear in TF
  word for word. AF's missions live on through MUF's versions.
- **Cast:** every MUF and AF character named in their game text is in TF's text except the four magazine-collab
  cameos. TF adds the Macross II wingmen (Saori, Amy, Nastasha) and Ingues.

So TF is not a superset: it keeps most of MUF, drops MUF's AFOS ending, the enemy-side campaigns and the magazine
missions, and adds Macross II, the first Frontier movie, many extra missions and the campus mode.

## Reuse from MUF and AF

The MUF translation (`ui.json`, `dialogue.json`, `internal_labels.json`) and the AF corpus are usable as a
translation memory: most unit, collection and label strings TF shares with MUF have shipped English
(`muf_tm` in the glossary notes).
