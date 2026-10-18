# Variable-width font (VWF) and 4x text

Ported from Macross Ultimate Frontier (`../Macross Ultimate Frontier/docs/vwf.md`) and Ace Frontier
(`../Macross Ace Frontier/docs/vwf.md`): same glyphs (GenEi LateGo v2, drawn at 4x and downsampled), same
proportional mode, Ultimate Frontier's 4x mechanism. Triangle Frontier's text code was rewritten (float pen,
shared advance routines, a fit-to-width printer), so every patch site is new. Triangle Frontier also has a second
text font, the 16 px campus font, which gets the same treatment. Built by `tools/vwf_build.py`.

Status (2026-10-16, not in a build yet): works in PPSSPP (OpenGL, 4x rendering) on a test disc with ASCII test
strings: main menu help bar, operator window, character select, campus character creation (16 px font), era
narration, briefing, a campaign mission (HUD names and the 3D name labels). Not tried at 1x or on real hardware.

## Build order

The two width tables need 1,552 bytes of free, file-backed memory. `tools/eboot_insert.py --reserve 4096` leaves
zeroed room in the gap it opens for the English text (it writes the address to `<out>.json`), and
`vwf_build.py` runs on that output. The tables take the start of the reserve; 2,544 bytes stay free for later
patches (voice subtitles need 2 KB). `vwf_build.py` warns when less than 2 KB is left.

```bash
python -I tools/eboot_insert.py --reserve 4096 --out work/output/build/EBOOT.ins.bin work/translation/en/insert.json
```

```bash
python -I tools/vwf_build.py --eboot work/output/build/EBOOT.ins.bin --out work/output/build/vwf
```

`tools/build_iso.py` runs both and copies the font overlay (`data/` and `_variants/` of the vwf folder) into its
overlay.

Output in `--out`:

| File | What |
| --- | --- |
| `EBOOT.BIN` | patched EBOOT (16 bytes longer: two new relocations) |
| `data/extra/gpsp3_font14.fnt` | 14 px font, RAIC-packed: the plain copy in macross.dat |
| `_variants/gameinit/data/extra/gpsp3_font14.fnt` | the same font unpacked: the copy in the `gameinit` bundle of fileset.dat |
| `data/extra/mpsp3_font16_slg.fnt` | 16 px campus font, RAIC-packed (macross.dat only) |
| `vwf_widths.json`, `vwf_preview*.png` | advances and previews of both fonts |

`work/ui/vwf_widths.json` holds the advances per character: `advance` for the 14 px font (as before) and
`font16.advance` for the campus font.

## Data

| Item | Triangle Frontier | (MUF) |
| --- | --- | --- |
| font table (5 pointers: font14, em, es, en, slg) | 0x4626A4 | 0x3FAD14 (4) |
| font14 descriptor (0x54 bytes, font index 0) | 0x462808 | 0x3FAE20 |
| campus font descriptor (`mpsp3_font16_slg.fnt`, index 4, loaded on demand) | 0x4626B8 | — |
| bearing-table pointer | descriptor +0x24 | +0x24 |
| group offsets / codes (shared by both fonts) | +0x1C → 0x462680 / +0x20 → 0x45F02C | +0x1C / +0x20 |
| ASCII → Shift-JIS table (.rodata) | 0x3B9ADC | 0x347E4C |
| glyph slots | 1210–1305 (codes 0x9F82–0xE772) | same |
| width tables (guard entry + 96 × (L, R), each) | start of the eboot_insert reserve | 0x2A4CCC |

The descriptor layout and the code list are Ultimate Frontier's. The glyph slots were checked against every
character of the six text dumps (`eboot_strings`, `menu_text`, `fes_strings`, `gop_strings`, `locate_names`,
`campus_strings`: 2,136 distinct characters) and against all `.tbl` and `.csv` files of the extracted tree: none
uses them. TF's ASCII table maps `$ < > @ ^` to full-width `＄＜＞＠＾` (MUF: β, Ⅰ, Ⅱ, ㌔, ν); they now draw as
ASCII like the rest.

Each descriptor gets a pointer to its table (L = 0, R = cell − advance) and a new R_MIPS_32 relocation (word and
value in segment 1). **The font flags stay 0**, unlike Ultimate / Ace Frontier (flag 0x20): the text-window code
at 0x23A594 (operator window, campus help) only accepts a font whose flags are 0, and with flag 0x20 the operator
text disappeared. The bearing routines are patched to use a table whenever the font has one instead.

## Code patches

| TF | MUF | Change |
| --- | --- | --- |
| 0x12FD40, 0x12FD4C | 0x159C2C/34 | ASCII → Shift-JIS routine 0x12FD38 (one routine in TF): table covers 0x20–0x7F, `` ` `` no longer special |
| 0x12FF80, 0x130054 | — | bearing routines 0x12FF40 (int) and 0x130014 (float): flag-0x20 test → always true; the table-pointer test stays |
| 0x13016C (0x130170 nop) | 0x159B84 | float advance 0x1300C8 (printer pen, float string width 0x1301EC): single-byte char of a font with a table → helper 0x130944 (15 words), which calls 0x130014; size × 0.75 otherwise, as before |
| 0x131338 | 0x15917C, 0x1594FC | int advance 0x1312A8 (string width 0x13150C, widest line 0x131620, fit-to-width printers 0x132724 / 0x13260C / 0x1316C0): same, helper 0x13099C (14 words) calling 0x12FF40 |
| 0x131E90 | 0x159ED4 | printer 0x131828: `(` `[` drawn at the pen, not half a cell to the left |
| 0x254108, 0x254110 | — | campus text box 0x254030 (schedule subject descriptions): the line cutter 0x130668 gets box width / (size + spacing) bytes per line, one Japanese character per cell; `bnez`/`break` around the division become `srl v1,v1,1`/`nop`, so a line holds twice as many bytes (14 English characters) |
| 0x1338A4, 0x1338B4, 0x1338C0, 0x1338CC–0x1338EC | 0x158818–0x158888 | glyph-array drawer 0x133788 (3D name labels): half-width glyph drawn at full size, advance from helper 0x130D64 (MUF's 22-word helper, cell read from the font) |

All three helpers sit in unreferenced functions (`tools/find_caves.py`: 0x130944 and 0x130CDC), in
relocation-free runs. The space character goes through the table like any other (4 px at 14, 5 px at 16), so the
printer and the width routines agree.

Not needed in TF: MUF's "single-byte glyph drawn × 0.8" (TF already draws it full size), separate string-width
and truncation patches (TF's width routines call the two shared advance routines), the `{` `}` path patch.

**Truncation.** TF never truncates: the line-truncation routine 0x1313FC has no callers. Text that is too wide
for its box is squeezed instead: 0x132724 (66 call sites) and its relatives measure the widest line with
0x131620 and shrink the character width to fit. The squeeze uses the patched int advance, so English is squeezed
by the right amount.

## 4x text

As in Ultimate Frontier ("HD text"), each font file gets a 4x page appended, and the glyph lookup is wrapped:

| Font | File size | 4x page |
| --- | --- | --- |
| `gpsp3_font14.fnt` | 341,824 → 456,512 | at 0x53740: 448 × 512 px, 8 cells of 56 px per row |
| `mpsp3_font16_slg.fnt` | 445,440 → 543,744 | at 0x6CC00: 384 × 512 px, 6 cells of 64 px per row |

Both pages keep the main atlas's two-layer packing (local glyph L in cell L >> 1, layer L & 1) and the font's
bind parameters (TBW 448 / 384, TSIZE 512 × 512), so the lookup body binds them unchanged.

| Where | Change |
| --- | --- |
| 0x132DC0 / 0x132DC4 | the glyph lookup's first two words (`addiu sp,-0x30` / `sw ra,0x24(sp)`) become `b 0x1309EC` / `nop`. The lookup is identical to MUF 0x15787C. |
| 0x1309EC | dispatcher, 48 words, in the unused function 0x130944 (52 relocation-free words) |
| 36 loads in the sprite emitters 0x132F04, 0x13311C, 0x133324, 0x1335F4, 0x1397F8 | `lw rX, 8(desc)` / `lw rY, 0xC(desc)` become `lh rX, 0x18(desc)` / `lh rY, 0x1A(desc)` |

The dispatcher writes the font's own cell size to descriptor +0x18/+0x1A (read nowhere else; the font loader
0x133A64 uses +0x08..+0x14). For an English glyph (1210–1305) of the 14 or 16 px font it writes 56 / 64
instead, points +0x3C at the 4x page (base + file offset of the page) and +0x10 at its cells per row, runs the
lookup body with the page-local glyph number and restores both fields. The emitters take the texture cell from
+0x18/+0x1A; the sprite's screen size still comes from the text size, so layout does not change. The fifth
emitter 0x1397F8 is the outline variant (half-cell pieces, menu help bar): its "half a cell + 1 texel" becomes
"half + 1/4 native texel" at 4x, which does not show.

The fonts are loaded into a buffer sized from the file (0x1D450), so the larger files load as they are. In
PPSSPP the 16 px font loads when the campus mode or a campus screen opens.

## Storage of the fonts

The plain copies of the fonts in macross.dat are RAIC members (XOR 0x72 + LZSS, `tools/muf_lzss.py`), and
fileset.dat's `gameinit` bundle holds a second, separately packed copy of the 14 px font. `vwf_build.py` reads a
RAIC or raw input and writes both copies.

A macross.idx / container-head entry of a packed plain file holds the decoded size at +16 and **the stored
(packed) length at +20** (0 for a raw file). The game reads that many bytes and decodes them. `muf_archive.py
repack` used to write only offset and size, so a re-packed file kept the old stored length: the end of the 16 px
font was not read and its 4x glyphs showed noise. Repack now writes all three fields (this matters for every
packed plain file in an overlay, e.g. campus `.gop` tables and `.asb` scripts).

## Glyphs

`tools/vwf_font.py` draws both sets from GenEi LateGo v2 (`work/fonts/GenEiLateGo_v2.ttc`, SIL OFL 1.1; licence
in `work/fonts/GenEiLatin_LICENSE.txt`), as Ultimate and Ace Frontier ship:

| Font | Caps | Baseline | Space | Advances |
| --- | --- | --- | --- | --- |
| 14 px (`SPEC14`) | rows 1–10 | row 11 | 4 | identical to Ace Frontier's (`work/ui/vwf_widths.json`) |
| 16 px (`SPEC16`) | rows 1–11 | row 12 | 5 | lower case 5–13, capitals 5–14, digits 6–9 |

TF's own full-width Latin sits on rows 2–11 of the 14 px font; the English caps stay on rows 1–10 as in the
sister games, because one row lower would cut the descenders at 4x. CSV aliases as in MUF: `|` draws a comma and
`` ` `` a double quote (`ALIASES`).

## Limits

- Glyphs sit on whole native pixels: a rounding step shows as a small gap at 4x, mostly in squeezed text
  ("Mi yuki", "(V WF)").
- Only ASCII 0x20–0x7F is proportional. The small HUD fonts (em, es, en: "TYPE-14", the timer) are unchanged.
- Text that does not fit is squeezed (see Truncation), not cut. Some boxes do neither: the campus help line and
  the bottom help bar run past their box, and the operator window does not wrap; the text needs explicit line
  breaks and must fit (measure with `work/ui/vwf_widths.json`; campus help at 16 px ≈ 365 px wide).
- The name-entry keyboard (`gop_keyboardlist`) has full-width letters, so a name the player types stays
  full-width.
- `{` starts a colour code where the caller enables them.
- Text drawn into textures is not affected.
- The extra font data (112 KB for the 14 px font, 96 KB for the campus font) loaded fine in every screen tested;
  campus event scenes were not reached.

## How it was tested

Test disc: `tools/eboot_insert.py --reserve 4096` with a few ASCII test strings (main-menu help, pilot names of
the character select, `eboot:3CFDD0` / `3D2A60` / `4117D8`), `vwf_build.py`, an overlay with ASCII test strings in
`gop_opehelp.gop` (all six copies) and `gop_help.gop` (both copies) and in `data/locate/ma_010.csv` (mission unit
names, through `tools/insert_text.py`), `muf_archive.py repack`, `iso_patch.py` (all 8 containers and the idx).
PPSSPP portable (`work/local/ppsspp`, OpenGL, `InternalResolution = 4`, window 1920 × 1088 so that window captures
show the 4x render), driven by `tools/ppsspp_ctl.py`. Screenshots in `work/ui/screens_vwf/` (local):

| Screenshot | What it shows |
| --- | --- |
| `01_menu_help_campaign.png`, `03_menu_help_options.png` | help bar centred (2x window) |
| `02_menu_help_campus_centred_overflow.png` | a too-long help line: centred, runs off both sides evenly |
| `04_menu_help_japanese_unchanged.png` | Japanese help unchanged |
| `05_menu_help_4x.png` | the help bar at 4x |
| `06_operator_window_typewriter_4x.png`, `07_operator_window_english.png` | operator window (14 px, typewriter) |
| `08_campus_help_16px_4x.png` … `11_campus_name_entry_help.png` | campus help line in the 16 px font, stats digits |
| `12_pilot_names_centred_squeezed_4x.png` | pilot names centred, a long one squeezed to fit |
| `13_era_narration_mixed_ascii_digits.png` | ASCII digits inside Japanese narration |
| `15_briefing_ascii_tabs_4x.png` | the game's own ASCII tab labels |
| `16_mission_hud_wingman_name.png`, `17_mission_3d_label_glyph_array.png` | mission HUD name list and a 3D name label (glyph-array path) |
| `14_mission_labels_japanese_before.png` | the same labels in Japanese |

Bisection on the way: an EBOOT with only the descriptor changes (no code patches) already lost the operator
text, which led to the flags finding above.
