# Voice-clip subtitles

During missions the characters talk over the radio: a portrait (the "cut-in") opens and a voice clip plays. The
game has no text for these lines. The patched game shows an English subtitle under the cut-ins while each clip
plays.

Ported from Macross Ultimate Frontier (MUF) 0.7.0 and Ace Frontier (AF) 0.2.0
(`../Macross Ultimate Frontier/docs/voice_subtitles.md`, `../Macross Ace Frontier/docs/voice_subtitles.md`): same
storage, same hooks, same layout. Triangle Frontier's EBOOT is newer code, so the routines were found again from
MUF's (see "EBOOT hooks"); the hook code lives in the room `eboot_insert.py --reserve 4096` leaves, after the VWF
width tables, as in AF.

Status (v0.1.18, 2026-10-17): working in PPSSPP (placeholder ids, then the real English) in the first campaign
mission (see "Testing"). Not tried on real hardware.

## Results

| | Clips |
| --- | --- |
| Voice clips in the work file (`<speaker>/<num>`, 94 speakers) | 18,759 (plus 31 sound effects at the top of `data/sound/voice/`, not subtitled) |
| **With an English subtitle** | **16,957** |
| Silent placeholder clips (no voice in the game) | 1,155 |
| Sound but no words (shouts, grunts, laughs; Whisper 230, translators 31) | 261 |
| Era prologue narration (already English text on screen) | 47 |

**14,596 of the clips are byte-identical to Ultimate Frontier / Ace Frontier clips** (`tools/voice_transcribe.py
--reuse`); their transcripts and the sister projects' reviewed English were reused (12,834 subtitles). The other
4,163 clips were transcribed here with Whisper (faster-whisper large-v3, CUDA, in the MUF venv: 4,201 clips in
35 min, retry pass 21 clips) and translated in 52 slices of 80 rows (`work/translation/en/voice/slices/`,
`docs/voice_translation_brief.md`): 4,123 subtitles. Most of them are TF's two new operators, Exsedol Folmo
(`o7_exd`, 846 clips) and Catherine Glass (`of_ktr`, 863), the Academy player voices (`p__mv0-2`, `p__fv0-2`, 672),
the operators' new lines for TF's missions, and the Macross II and new Frontier pilots (Silvie Gena, Hibiki
Kanzaki, Bobby Margot, Canaria Berstein, Nanase Matsuura). `tools/voice_slice.py show` prints, for an operator or
custom pilot, the English the others already have for the same clip number ("same no."), since they read one
script. Flags on the slice rows: `whisper_doubt` 392, `name_missing` 66, `uncertain` 62, `no_subtitle` 31,
`kept_omission` 4; every flagged row has an English note. Name pass (`tools/voice_fix_names.py`): "Micronizer" as
in the shared operator clips, "VA-C-3 Invader", "Silvie".

Data tools ported from AF for TF's clip ids (`<speaker>/<num>` instead of `v<speaker>_<num>`):
`voice_transcribe.py` (reuse from both sister projects, tag `MUF:` / `AF:`), `voice_rows.py` (TF operators and
custom pilots, FES scripts unpacked), `voice_slice.py` ("same no." hints), `voice_subs_export.py`,
`voice_fix_names.py`. Speakers: `work/translation/en/voice/speakers.en.json` (MUF + AF + 16 TF speakers).

## Pipeline

As in AF (the transcription and translation tools are described with them):

| Step | Tool | Output |
| --- | --- | --- |
| Collect the lines | `tools/voice_subs_export.py` | `work/translation/en/voice/voice_subs.en.json` |
| Append each line to its clip | `tools/voice_subs_at3.py` | overlay `data/sound/voice/<speaker>/<num>.at3` |
| EBOOT hooks that read and draw the line | `tools/voice_subs_patch.py` | patched `EBOOT.BIN` |

The last two run inside `tools/build_iso.py` with `--voice-subs <file>` (step 2b on the VWF EBOOT, step 3c after
the text and image overlays). `--voice-placeholder` writes each clip's id instead, to test the hooks:

```bash
python -I tools/build_iso.py 0.1.18-vtest --images --voice-placeholder
python -I tools/build_iso.py <version> --images --voice-subs work/translation/en/voice/voice_subs.en.json
```

`voice_subs_at3.py` takes AF's input: a list of rows `{"id": "<speaker>/<num>", "en": "<line>"}` (other keys
ignored) or a dict `{id: line}`; later files win, empty lines are skipped. `--placeholder --only <prefix>` limits
the placeholder to ids with that prefix (e.g. `o0_` for the operators).

## The clips

Unlike MUF and AF (`data/sound/voice/v<prefix>_<num>.at3`), Triangle Frontier keeps one folder per speaker:

```
data/sound/voice/<speaker>/<num>.at3      ATRAC3 clip (18,786, in 94 folders; e.g. p7_mln/000.at3)
data/sound/vad/<speaker>/<num>.vad        lip-sync file, members of the me_* fileset bundles
```

The clip id is `<speaker>/<num>`: the game builds both paths from it with `data/sound/vad/%s.vad` and
`data/sound/voice/%s.at3` (a leading `#` in the script's id is skipped). `<speaker>` is the cut-in portrait's
face id, as in MUF (`work/translation/en/voice/speakers.en.json`).

In `macross.dat` every clip is a plain file, **stored raw** (RIFF, idx stored length +20 = 0; no RAIC clips), on
0x800 boundaries. 1,204 clips are also members of the `cv_*` fileset bundles (18 per character, played from
memory); those copies are not changed: `tools/muf_archive.py` uses overlay files under `data/sound/voice/` for
`macross.dat` only (`DAT_ONLY`), so the bundles do not grow. The hook reads the `macross.dat` copy.

The optional data install (`PSP_GAME/INSDIR/000`, copied to `ms0:/PSP/SAVEDATA/ULJS00321DATA/000`) replaces
`fileset.dat` only (the read routine 0x327E0 checks the container name `fileset.dat`), so it does not hide the
clip tails.

## Where the line is stored

At the end of its own clip, after the RIFF data, in `macross.dat`:

```
... RIFF ATRAC3 clip ... | part 1 NUL [part 2 NUL ...] | u16 len | u16 parts | "SB"
```

`len` counts all parts with their NULs. The RIFF size field is not changed, so the player never reads the tail.
A clip with a line is appended to `macross.dat` by `muf_archive.py repack` (0x800-aligned like the originals;
`VOICE_ALIGN` was 0x8000 in the MUF/AF copy of the tool, which would waste about 280 MB over all clips), and its
idx entry and container head get the new offset (+12), size (+16) and stored length 0 (+20). Nothing is loaded
into memory except the 0xB8 bytes the hook reads.

## EBOOT hooks (`tools/voice_subs_patch.py`)

| Routine | TF | MUF | How found |
| --- | --- | --- | --- |
| exact-size file read (path, buf, size) | 0x1D370 | 0x21A00 | the call at the slot loads; same body, file size 0x31690 and read 0x32BB8 |
| path normalise (dst, src, max) | 0x306BC | 0x37C60 | `port_match.py` 24/24 |
| `macross.dat` index lookup (path, info: container, offset, size, stored length) | 0x33D38 | 0x3A9B8 | called by the file-size routine 0x3162C like MUF 0x38550; entry +8/+12/+16/+20 copied to info +0..+12 |
| read at an offset (container, buf, offset, size, t0 = 1) | 0x327E0 | 0x39560 | called by the read routine 0x32BB8 with the lookup result, as MUF 0x39740 calls 0x39560; checks the data install first |
| lip-sync slot 0 load (`jal` replaced) | 0x17A538 | 0x1A0A14 | `port_match.py` 24/24; slot 0 at 0x1CB43C (link address) |
| lip-sync slot 1 load (`jal` replaced) | 0x17AFDC | 0x1A38E4 | `data/sound/vad/%s.VAD` reference, `a1 = slot 0 + 0x30`, `a2 = 0x30` |
| lip-sync frame counter | 0x17875C | 0x1A0AD0 | same loop; counters at slot 0 - 8 / - 4 (set to -1 when idle) |
| mission 2D layer, cut-in step call (`jal` replaced) | 0x11AC00 (in 0x11ABD4) | 0x140D68 (in 0x140D3C) | the only caller of the step; same structure |
| cut-in module step | 0x179FCC | 0x1A024C | `port_match.py` 24/24 |
| text routine (fit to width) | 0x132724 | 0x15ABC0 | same arguments (docs/vwf.md: one of TF's fit-to-width printers) |
| `"data/sound/voice/"` | 0x403A30 | 0x3947A0 | |
| `"data/sound/vad/%s.vad"` / `"%s.VAD"` | 0x40C6B8 / 0x40C6D0 | 0x3B0B68 / 0x3B0BD4 | |

Addresses are link addresses (vaddr). In the decrypted EBOOT the text segment starts at file offset 0xA0, so the
`.rodata` strings are at file offset vaddr + 0xA0 (e.g. `data/sound/vad/%s.vad` at 0x40C758).

**Read.** Both `.vad` loads go to READ_HOOK. It makes the same call, then builds `data/sound/voice/<id>.at3`
(everything between `data/sound/vad/` and the first `.`, so the `/` of the id is kept), normalises it, looks it up
in the `macross.dat` index and, if the clip is stored raw, reads its last 0xB8 bytes. With an `SB` tail it keeps
a pointer to the line and its number of parts for that slot. It also remembers where slot 0 is (from the game's
own pointer, so the .bss shift of `eboot_insert.py` does not matter).

**When.** The game counts a slot's frames only while its clip plays, from 0 to length / step. A slot's line shows
while its counter runs and for 24 frames after. Part i of n shows from i/n of the clip on.

**Draw.** The cut-in step call in the mission's 2D layer goes to DRAW_HOOK: it runs the step, then draws the line
with the text routine twice, a black shadow 1 px down-right, then white. Same parameters as MUF and AF: centre
(240, 228), alignment 0, 12 px VWF (font 0, the 14 px font), box 232 px, line step 13 px, depth 0xFFFF. They are 9
config words at `CFG`, so a layout can be tried live through the PPSSPP debugger.

**Space used.** `tools/eboot_insert.py --reserve 4096` leaves zeroed, file-backed room in the gap it opens between
`.data` and `.bss` (address in `EBOOT.ins.bin.json`, `reserved_vaddr`). The two VWF width tables take the first
1,552 bytes (`vwf_build.TABLE_BYTES`), this patch the next 2 KB. In the 0.1.18 test build (reserve at 0x47A950):
READ_HOOK 136 words at 0x47AF60, DRAW_HOOK 117 words at 0x47B1A0, buffers and state at 0x47B3A0, config at
0x47B548; 496 bytes of the reserve stay free. The three replaced words are `jal` with an R_MIPS_26 relocation,
which stays valid for the new target; the new code carries no relocation (it finds its load address with `bal`).

## Length

At 12 px the box holds about 38 characters per line. A line is wrapped to 232 px with the VWF advances
(`vwf_widths.json` of the VWF build), at most 3 lines per part; a longer line becomes 2-3 parts. The whole line
must fit in 178 bytes. `…` is written as 0x7F (the VWF ellipsis), `{` is refused (colour code).

## Limits

- Only clips the mission script queues into the two lip-sync slots get a subtitle. Clips played another way
  (menus, character select voice samples, campus scenes, the era prologue) do not.
- Two lines spoken at once show one subtitle, slot 0 first. Parts follow the clip at even steps.
- The read routine 0x327E0 is TF's own (it checks the data install and goes through 0x326A0); no stutter was seen
  in PPSSPP, not measured on hardware.
- With the game's "2D Display" option off, whether subtitles still show was not checked.
- Not tested on real hardware.

## Testing

PPSSPP (portable copy in `work/local/ppsspp`, OpenGL, 4x), driven with `tools/ppsspp_ctl.py`. A placeholder build
(`python -I tools/build_iso.py 0.1.18-vtest --images --voice-placeholder`) was played from boot into the first
campaign mission. Screenshots: `work/ui/screens_voice/` (local).

Played on 2026-10-17: title, Start Game, Yuu's main-menu tutorial lines, Campaign, character, operator and
flight-type select, the Macross Zero era narration, then the first two sorties of the era. Checked by
screenshots and by reading the hook state through the debugger (`memory.read`: slot pointer, line pointers,
counters, hold):

- The clip id shows under the cut-ins while the clip speaks and is gone after (hold of 24 frames), the cut-in
  window still open: intro camera (`p0_om0/102`, Yuuto), two cut-ins open (`p0_of0/304`, Miyuki), the
  operator over the "Enemy Appeared" / "Target Withdrew" banners (`o0_of0/1000`, `o0_of0/062`, `o0_of0/1251`),
  an enemy ace (`ph_nor/161`, Nora), and during play with the flight HUD (`o0_of0/427`): the line sits between
  the HP bars and the weapons panel as in MUF and AF.
- Ids with a `/` work: the hook's path `data/sound/voice/<speaker>/<num>.at3` is found in the index.
- Only slot 0 was seen in use in these two sorties; the slot-1 hook (0x17AFDC) is in place (checked `jal`,
  relocation and arguments) but did not run.

Screenshots: `work/ui/screens_voice/` (local), `NN_..._speaking` / `NN_after` pairs.

Size: the placeholder build appends all 18,786 clips (433 MB) to `macross.dat` (891,957,248 -> 1,324,773,376
bytes); the test ISO was 3,356,995,584 bytes (the 0.1.17 ISO without voice: 2,928,465,920). `iso_patch.py` now
copies replacement files in chunks: 32-bit Python could not read the grown `macross.dat` into memory. A build
with real lines appends only the subtitled clips.
