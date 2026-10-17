# Contributing

Keep translation files under `work/translation/<language-code>/`, shared terminology under `work/glossary/`,
and font and layout data under `work/ui/`. Preserve row IDs, control codes, placeholders (`\p` is the player's
name in the campus text) and glossary spellings. Read adjacent lines and the [translation rules](BASE_RULES.md)
and [brief](docs/translation_brief.md); record uncertainty in the row's notes instead of inventing context. Check
a slice with `python tools/corpus_slice.py check <N>` (campus: `--campus`), a voice slice with
`python tools/voice_slice.py check <N>`.

Japanese script text is never committed. The working files with Japanese (`work/translation/**/*.json` without
`.en`) are generated locally from your own disc; commit only the `*.en.json` copies
(`python tools/corpus_slice.py export`, `python tools/strip_jp.py`). Names and UI terms in Japanese are allowed in
the glossary.

Include the row IDs, changed English, the source ISO version and what you checked in game. Add an entry to
`CHANGELOG.md`. Give local test builds an unused `0.x.y` version. Screenshots may be attached to an issue for a
visual bug; do not commit disc data, extracted files, saves, voice clips or local test images.

Test in PPSSPP from a fresh boot and a normal save; save states keep old text and fonts in memory. Report offline
checks (widths, file verification) and in-game testing separately.
