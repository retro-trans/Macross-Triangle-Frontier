"""Write the git-safe copy of a translation work file.

Usage: python tools/strip_jp.py [work/translation/en/dialogue.json ...]
For each work file X.json, writes X.en.json with the Japanese ("jp") removed
and fails if any Japanese script is left in the output. Japanese names inside
the glossary are allowed by project rules, but translation files must have
none, so any kana/kanji in the output is an error.
"""
import json, os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JP = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")


def strip(path):
    d = json.load(open(path, encoding="utf-8"))
    rows = [{k: v for k, v in r.items() if k != "jp"} for r in d["rows"]]
    out = {"_meta": d.get("_meta", {}), "rows": rows}
    text = json.dumps(out, ensure_ascii=False, indent=1)
    bad = [r["id"] for r in rows if JP.search(json.dumps(r, ensure_ascii=False))]
    if bad:
        print("ERROR: Japanese left in %d rows, e.g. %s" % (len(bad), bad[:5]))
        return False
    dst = path[:-5] + ".en.json"
    open(dst, "w", encoding="utf-8").write(text)
    print("wrote", dst, len(rows), "rows")
    return True


if __name__ == "__main__":
    paths = sys.argv[1:] or [os.path.join(ROOT, "work/translation/en/dialogue.json")]
    sys.exit(0 if all(strip(p) for p in paths) else 1)
