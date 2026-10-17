# Voice-clip subtitle translation brief

Read `BASE_RULES.md` first, then the "Names", "Gender" and "Quality bar" parts of `docs/translation_brief.md`. Those rules apply in full. This page adds what is specific to the voice clips.

## What you are translating

Triangle Frontier (TF) shares most of its voice clips with Macross Ultimate Frontier (MUF) and Macross Ace Frontier (AF): 14,596 of its 18,759 voice clips are byte-identical to a sister clip and take that project's reviewed English. **Only the other clips are in the slices.** Some are the same line recorded again (same clip id, about the same length): for those, `show` prints a `ref:` line with the sister clip (`MUF:v<speaker>_<num>` or `AF:...`), its transcript and its English. Use it as a strong hint, not as the answer: the TF clip may say something a bit different, and either transcript may be the misheard one. Where the TF line is clearly the same, keep the sister English (consistency with the shared clips); where it differs, translate what the TF clip says.

The voice subtitles follow the MUF style of the mission text: **no Japanese honorifics** (those are kept only in the campus text). Ranks and titles as in the glossary (オズマ少佐 "Major Ozma", 隊長 "Captain").

During missions, characters talk over the radio. Each line is a voice clip shown with the speaker's portrait (a "cut-in"). The game has no text for these lines, so we transcribed every clip with Whisper (speech recognition). The patched game now shows your English as a subtitle under the cut-in while the clip plays (`docs/voice_subtitles.md`).

**The Japanese you get is a machine transcript, not the script.** It is usually right, but it can contain:
- homophones or wrong kanji (han-tougou doumei "Anti-U.N. Forces" heard as hantou goudoumei, goei "escort" as goen);
- dropped or extra particles, run-together sentences, missing punctuation;
- a mangled name or term (check the glossary and the series);
- for shouts, grunts and non-speech, nonsense or nothing.

Work out what was most plausibly said, using the speaker, the series, the neighbouring rows and the Macross terms, and translate that. Then flag the row:
- `whisper_doubt`: you corrected or guessed at the transcript. Say in `notes`, in English, what you think was misheard (romaji is fine for a word).
- `no_subtitle`: the clip has no words a viewer needs (a pure grunt, a scream, drums, a chant, an unintelligible line). Leave `en` empty.

## Input and output

- Work file (read only): `work/translation/en/voice/voice.json`. Do not edit it.
- Print your slice with `python tools/voice_slice.py show <N>`. Each row shows: row number, clip id, speaker, clip length in seconds, Whisper's own warning flags, the missions whose scripts hold the clip number (a hint only), a skip reason if any, and the transcript.
- Write only your slice file, `work/translation/en/voice/slices/vslice_NNN.en.json` (three digits), UTF-8, with Python `json.dump(..., ensure_ascii=False, indent=1)`:

```json
{"slice": 7, "rows_in_slice": 80, "rows_examined": 80,
 "rows": [
   {"id": "o0_of0/1000", "en": "Enemy fighters incoming!", "flags": [], "notes": ""}
 ],
 "report": {"uncertain": ["row 532: ..."], "whisper_doubt": ["row 540: ..."],
            "kept_omission": [], "missing_glossary": [], "unfinished": []}}
```

- Every row of your slice must be in `rows`, including skipped ones (give them `"en": ""`).
- Run `python tools/voice_slice.py check <N>` and fix every ERROR. Read the warnings.
- **No Japanese characters anywhere in the slice file.** It is committed to git.
- Allowed flags: `uncertain`, `whisper_doubt`, `no_subtitle`, `kept_omission`, `name_missing`, `unfinished`.

## How the rows are grouped

- **Clip ids** are `<speaker>/<num>` (the clip's folder and number), e.g. `o0_of0/1000`.
- **Operators** (`o0_of0`, `o0_of1`, `o0_of2`, `o0_om0`, `os_mis`, `o7_exd`, `of_ktr`): TF has seven operators (Yuu, Claire, Pinon, Itsuki, Misa, and new in TF Exsedol Folmo and Catherine Glass) who read the same script. Most of each operator's clips are shared with MUF/AF, so look up the same number for another operator in `work/translation/en/voice/voice.json` when a row needs context: the operators say the same thing in their own manner (see `speakers.en.json`): Yuu polite, Claire cool and mature, Pinon bossy and tomboyish, Itsuki brisk, Misa a crisp officer, Exsedol an elderly Zentradi scholar, calm and formal, Catherine a crisp, proper N.U.N.S. lieutenant. Numbers 1000+ are mission lines (objectives, enemy reports, warnings); lower numbers are stock lines (mission start, results, encouragement).
- **Custom pilots** (`p0_*`, and new in TF `p__mv0-2` / `p__fv0-2`: the Academy-created player character, male or female, voice type 1-3): same situation, several personalities.
- **Named characters** (`p<series>_<name>`): by series, then speaker, then number. Speaker names are in `work/translation/en/voice/speakers.en.json`.
- Pilot clip numbers mean the same situation for every pilot: 000-020 launch and greetings, 100-198 combat (attacking, taking damage, shooting down, being shot down, warning a partner...), 300-371 skills, partner and results, 600-699 that character's story lines for particular missions.

## Style

- These are radio lines in combat: short, spoken, alive. Write how an English-speaking pilot or operator would say it on the radio. Keep each character's voice (Basara's swagger, Klan's bluster, Max's calm).
- One clip in, one line out. Never merge or split rows.
- Shouts and battle cries: translate them as English battle cries ("Take this!", "Not yet!", "Damn it!"). A clip that is only a grunt or scream gets `no_subtitle`.
- Restore subjects and verbs as BASE_RULES says. Do not soften.
- Names and terms: `work/glossary/`. 統合軍 "U.N. Forces", 新統合軍 "New U.N. Forces", 反統合同盟 "Anti-U.N. Forces", バルキリー "Valkyrie", ゼントラーディ "Zentradi", バジュラ "Vajra", フォールド "fold".
- Never infer gender from a name; use `gender` in `speakers.en.json` and `characters.json`.

## Length

The subtitle box is about 230 px wide (about 38 characters per line) and shows up to three lines at once. A longer line is shown in parts of up to three lines that follow each other while the clip plays. The hard limit is **178 bytes for the whole line**; `check` measures it.

Readers need time: aim for no more than about 15-17 characters per second of the clip (`check` warns above that). A 1-second bark gets a few words; a 5-second operator report can use two lines. Compress the wording when you must, but never drop the end of a sentence.

Write only ASCII. The font also has the ellipsis (…); typographic quotes and dashes are converted. Do not write `{`.

## Report

At the end, report rows examined against rows in each slice, and list the calls you were unsure of (`uncertain`), the transcripts you corrected (`whisper_doubt`), and names missing from the glossary.
