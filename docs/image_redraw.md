# Redrawing the text in textures (v0.1.16, 2026-10-17)

```bash
python tools/build_iso.py <version> --images
python tools/redraw_images.py            # alone: overlay + preview sheets
```

The Japanese drawn into game textures (GIM) is redrawn in English by `tools/redraw_images.py`, with
`tools/gim.py`; both come from the Macross Ultimate Frontier project by way of Ace Frontier (same engine and
texture format). It reads the rows in `work/translation/en/images/img_*.json` (gitignored: they hold the Japanese)
and the layout in `work/ui/redraw_layout.json`, and writes:

| Output | What |
| --- | --- |
| `work/output/redraw/overlay/data/...gim` and `_variants/...` | The re-encoded textures, for `muf_archive.py repack --overlay` (gitignored) |
| `work/ui/redraw_preview/sheet_*.png` | Before/after contact sheets of every texture, after palette reduction (gitignored) |
| `work/ui/redraw_preview/report.json` | Per text item: the text drawn, font size, squeeze, whether a short form was used (no Japanese) |

`--only <part of a path>` redraws a few textures into `<preview>/_only/`; `--no-write` skips the GIM files.
`tools/build_iso.py --images` runs it as step 3b into the build overlay.

## Triangle Frontier specifics

- **Packed textures.** 1,279 plain textures are RAIC/RAIB-packed (XOR 0x72 + LZSS, `tools/muf_lzss.py`).
  `gim.unpack()` reads them; `redraw_images.write_gim()` writes the redrawn texture packed in the original's mode.
- **Bundle copies.** A texture that is also a member of a fileset bundle has an unpacked copy under
  `_variants/<bundle>/<path>` (`tools/muf_archive.py extract`); `write_gim()` writes that copy too. Textures that
  live only in bundles are stored unpacked under their own path, and the repack picks them up from the overlay.
- **Atlases.** Some textures are word atlases (top menu `menu06`, character creation `cha_make05/06`, date
  profile `date_07`, schedule `cmd_menu05`): the game cuts each word out by the old glyph box, so the English is
  drawn inside that box (`plate` = box) and erased a little wider (`erase_box`). In 0.1.15 "Academy" and
  "Set Start" were cropped before this was done.
- **Identical copies.** `work/ui/tex_same.json` (from `tools/tex_tasks.py`) lists textures with the same pixels as a
  reviewed one; `load_rows()` gives them its rows.
- **Kept.** Rows flagged `keep_original` (logos, signs in pictures) are listed but not redrawn.
- **Title-screen stamp.** The layout entry of `data/menu/top/title05.gim` (copyright strip) has `extra_items`
  drawn over the strip without erasing: `{version}` and "github.com/retro-trans", right-aligned at the bottom
  right. `{version}` is `--version` (`tools/build_iso.py` passes `v<version>`).

## Where the rows come from

1. `python tools/tex_port.py --write`: every texture that Ultimate Frontier or Ace Frontier redrew is compared with
   the TF textures (bytes, then pixels). 326 match (254 MUF and 71 AF at the same path, 1 moved); their rows go to
   `img_port.json` and their resolved layout specs to `redraw_layout.json` (`files`, marked `_from`). The series
   logos that MUF keeps are not imported.
2. `python tools/gim.py dir data/<folder> work/ui/gim_png/<name>` decodes the rest to PNG, and
   `python tools/tex_tasks.py --groups 4` leaves out what is kept as it is and packs the rest onto review sheets
   (`work/ui/gim_png/_tasks/`, summary in `summary.json`):

   | Left out | Textures |
   | --- | --- |
   | Character and unit cards (portraits, renders) | 613 |
   | Gallery thumbnails | 513 |
   | Cockpit pilot portraits (`.gfp`) | 511 |
   | Gallery and loading stills (mecha renders, anime frames) | 488 |
   | Imported from MUF/AF | 326 |
   | Already English (subtitle cards, `_eng` banners) | 250 |
   | Campus backgrounds and event pictures | 175 |
   | Special-attack cut-in portraits | 142 |
   | Fully transparent | 21 |

   The 10,068 campus character sprites (`campus/event/chara`) are not decoded at all.
3. Four agents read the 2,167 remaining textures (`docs/image_translation_brief.md`):

   | Group | Folders | Rows |
   | --- | --- | --- |
   | `A` | campus icons and interface, cockpit pieces, first menu folders | 34 |
   | `B` | campaign cards, data select, flight select, gallery viewer | 8 |
   | `C` | gallery records and tabs, hangar, music, result, settings | 43 |
   | `D` | settings, shop, system, title and top menu, network, HUD banners, 88 mission title cards | 185 |

## Result (v0.1.16)

597 textures (618 GIM files with the bundle copies), 818 text items, no overflow; 26 items use a short form.
Coordinator changes after the preview: pilot stats as 3-letter forms everywhere (STA SPD SHT FOC MEL AWK DEF),
campus stat buttons MND / TEC / BOD, wider erase under "Learn Abilities" and the top-menu "Back".

## Tested in game (PPSSPP)

Screenshots in `work/ui/screens_0.1.15/` and `work/ui/screens_0.1.16/` (local): title copyright, main menu
buttons and header, Yuu's tutorial window, pilot select, "Returning to Top Menu" dialog, Academy character
creation (Issue Student ID, the ID card with its fine print, pilot stats, name entry key guide, nickname screen,
confirmation).

Not seen in game yet: the campus schedule, status and date screens, calendar tabs, grade stamps, mission title
cards and HUD banners, gallery, settings, shop, network.

Known: the name-entry keyboard's "symbols" key is still Japanese (it comes from `gop_keyboardlist.gop`, which the
text dump skips).
