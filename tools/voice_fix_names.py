"""Unify names across the voice slices (run after the translators, as BASE_RULES says).

Usage: python tools/voice_fix_names.py [--apply]
Without --apply it prints what would change. The table holds the spellings the
translators chose differently; the right one is the glossary's
(work/glossary/*.json), or the most used one where the glossary has none.
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXES = [
    (r"\bEifos\b", "AFOS"),                              # terms.json: AFOS (A.F.O.S.)
    (r"\bElgarsoln\b", "Elgersoln"),                      # mecha.json
    (r"\bKoenig Monster\b", "Konig Monster"),             # mecha.json ASCII form
    (r"\bKlan Klang(?:'s)? (?:Team|team|squad|Squad)\b", "Klan Klang's team"),
    (r"\bNunu\b", "Nene"),                               # Pixie Squad: Nene Rora (Whisper heard "Nunu")
    (r"\bGerwalk\b", "GERWALK"),                         # as in the dialogue translation
    # Triangle Frontier
    (r"\b[Mm]icronization device\b", "Micronizer"),      # the shared MUF operator clips of the same numbers
    (r"\bVAC-3 Invader\b", "VA-C-3 Invader"),            # mecha.json (VA-C-3 Invader Kai)
    (r"\bSylvie\b", "Silvie"),                           # characters.json: Silvie Gena ("Sylvie" is avoid)
]


def main():
    apply = "--apply" in sys.argv
    n = 0
    for p in sorted(glob.glob(os.path.join(ROOT, "work/translation/en/voice/slices/vslice_*.en.json"))):
        d = json.load(open(p, encoding="utf-8"))
        changed = False
        for r in d["rows"]:
            new = r.get("en", "")
            for pat, rep in FIXES:
                new = re.sub(pat, rep, new)
            if new != r.get("en", ""):
                print("%s %s: %s -> %s" % (os.path.basename(p), r["id"], r["en"], new))
                r["en"] = new
                changed = True
                n += 1
        if apply and changed:
            json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%d rows %s" % (n, "changed" if apply else "would change"))


if __name__ == "__main__":
    main()
