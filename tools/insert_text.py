"""Write the English into copies of the menu CSVs, unit lists, FES mission scripts,
campus data tables (.gop) and campus event scripts (.asb).

Usage:
  python tools/insert_text.py [--src work/source/dat] [--out DIR] [--dry-run] [<insert.json> ...]
  defaults: work/translation/en/insert.json and insert_campus.json (tools/corpus_slice.py
  export), out = work/output/build/overlay

The output is an overlay tree (data/...) for `tools/muf_archive.py repack --overlay`.
The extracted tree is not touched. Every row is checked against its Japanese source
bytes before it is replaced. Rows marked "lit_nl" (CSV cells, .gop strings) store a
line break as backslash + n in the file; the work files use a real newline, converted
here.

.gop (tools/gop.py): the GENESTRT string at ref "index" is replaced; the table is
rebuilt with the same count and order.

.asb (tools/asb.py): the English is appended to the script's string pool and the push
at ref "push" (code offset) that referenced the Japanese at ref "pool" is repointed.

CSV cells (mission_ext.csv, nn_ext.csv). The game's CSVs have no quoting, so
an ASCII comma or double quote cannot appear in a cell:
  ,  -> |     the VWF font draws these slots as a comma and a double quote
  "  -> `     (tools/vwf_font.py ALIASES), so the CSV must go with that font
The literal two-character "\\n" line break is kept. Characters Shift-JIS has
no code for are replaced by REPLACE below and reported.

FES string pools (data/script/*.fes, docs/formats.md). A string is used by the
instruction  0x0080, <k>, <u16 offset from the pool start>  (k = 0..2), one
per Japanese string. The English is appended after the last string of the
pool and that offset is repointed. The old bytes stay where they are, so no
other offset in the file changes. New offsets must stay below 0x8000 (the
largest original pool is 0x2C28 bytes, so a signed read cannot be ruled out).
"""

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import muf_lzss  # noqa: E402

ENCODING = "cp932"
CSV_MAP = {",": "|", '"': "`"}
REPLACE = {"ō": "ou"}  # o-macron (Seikan Hikō) has no Shift-JIS code
FES_PUSH_STR = 0x0080
FES_POOL_PTR = 0x12
FES_MAX_OFF = 0x8000


def encode(s, where, notes):
    for k, v in REPLACE.items():
        if k in s:
            notes.append("%s: U+%04X -> %r" % (where, ord(k), v))
            s = s.replace(k, v)
    return s.encode(ENCODING)


# ------------------------------------------------------------------ CSV

def csv_text(en):
    for k, v in CSV_MAP.items():
        en = en.replace(k, v)
    return en


def patch_csv(path_in, rows, notes):
    raw = open(path_in, "rb").read()
    text = raw.decode(ENCODING)
    if text.encode(ENCODING) != raw:
        raise ValueError("%s does not round-trip through %s" % (path_in, ENCODING))
    lines = text.split("\r\n")
    for r in rows:
        ref = r["ref"]
        cells = lines[ref["row"]].split(",")
        if cells[0] != ref["key"]:
            raise ValueError("%s: row %d key is %r" % (r["id"], ref["row"], cells[0]))
        if cells[ref["col"]] != r["jp"]:
            raise ValueError("%s: source cell does not match the Japanese in the work file" % r["id"])
        en = csv_text(r["en"])
        if "\r" in en or "\n" in en:
            raise ValueError("%s: a real line break cannot go in a CSV cell (use \\n)" % r["id"])
        encode(en, r["id"], notes)  # check it encodes
        cells[ref["col"]] = en
        lines[ref["row"]] = ",".join(cells)
    out = "\r\n".join(lines)
    data = b""
    for i, line in enumerate(out.split("\r\n")):
        data += (b"\r\n" if i else b"") + encode(line, "line %d" % i, [])
    return data


# ------------------------------------------------------------------ FES

def fes_refs(d, pool, off):
    """Aligned positions of `0x0080, k, off` before the pool."""
    hits = []
    pat = struct.pack("<H", off)
    i = -1
    while True:
        i = d.find(pat, i + 1)
        if i < 0 or i >= pool:
            return hits
        if i % 2 or i < 4:
            continue
        op, k = struct.unpack_from("<2H", d, i - 4)
        if op == FES_PUSH_STR and k <= 2:
            hits.append(i)


def patch_fes(path_in, rows, notes):
    d = bytearray(open(path_in, "rb").read())
    if d[:8] not in (b"FES 3.00", b"FES 3.04", b"FES 3.09"):  # AF 3.00, MUF 3.04, TF 3.09: same pool layout
        raise ValueError("%s is not FES 3.00/3.04/3.09" % path_in)
    pool = struct.unpack_from("<H", d, FES_POOL_PTR)[0]
    added = {}
    for r in rows:
        off = r["ref"]["pool_offset"]
        a = pool + off
        jp = r["jp"].encode(ENCODING)
        if bytes(d[a:a + len(jp) + 1]) != jp + b"\0":
            raise ValueError("%s: pool bytes do not match the Japanese in the work file" % r["id"])
        hits = fes_refs(d, pool, off)
        if len(hits) != 1:
            raise ValueError("%s: %d string references, expected 1" % (r["id"], len(hits)))
        en = encode(r["en"], r["id"], notes)
        if b"\0" in en:
            raise ValueError("%s: NUL in text" % r["id"])
        new = added.get(en)
        if new is None:
            new = len(d) - pool
            d += en + b"\0"
            added[en] = new
        if new >= FES_MAX_OFF:
            raise ValueError("%s: new pool offset 0x%X is too large" % (r["id"], new))
        struct.pack_into("<H", d, hits[0], new)
    return bytes(d)


# ------------------------------------------------------------------ GOP, ASB (Triangle Frontier campus)

def patch_gop(path_in, rows, notes):
    import gop
    g = gop.Gop(open(path_in, "rb").read())
    strings = list(g.strtab()[2])
    for r in rows:
        i = r["ref"]["index"]
        if strings[i] != r["jp"].encode(ENCODING):
            raise ValueError("%s: .gop string does not match the Japanese in the work file" % r["id"])
        strings[i] = encode(r["en"], r["id"], notes)
    return g.rebuild(strings)


ASB_TEXT_FNS = {0x00: (0,), 0x01: (0, 1, 2)}  # show a line (arg 0); show choices (args 0-2)
asb_skipped = []


def patch_asb(path_in, rows, notes):
    """Only pushes that feed a text function are repointed. Other functions (0x15, 0x17, 0x22, 0x23, 0x25,
    0x31, 0x3E, 0x4F, 0x1D arg 1...) take numbers (ids, flags); a number can equal the pool offset of a
    Japanese string by chance, and repointing it broke the scene (0.1.22: function 0x23 in scd_skl_505 got
    0x902 instead of 0x6B, the screen stayed black after the practical test)."""
    import asb
    s = asb.Script(open(path_in, "rb").read())
    st = s.strings()
    text_push = {p for _, fn, args in s.calls() if fn in ASB_TEXT_FNS
                 for k, p in enumerate(args) if p is not None and k in ASB_TEXT_FNS[fn]}
    english, repoint = {}, {}
    for r in rows:
        pool, push = r["ref"]["pool"], r["ref"]["push"]
        if push not in text_push:
            asb_skipped.append((path_in, push))
            continue
        if st.get(pool) != r["jp"].encode(ENCODING):
            raise ValueError("%s: pool string does not match the Japanese in the work file" % r["id"])
        if s.push_value(push) != pool:
            raise ValueError("%s: push at code+0x%X does not reference pool 0x%X" % (r["id"], push, pool))
        en = r["en"]
        english.setdefault(pool, en)
        if english[pool] != en:
            raise ValueError("%s: two translations for one pool string" % r["id"])
        encode(en, r["id"], notes)
        repoint.setdefault(pool, []).append(push)
    return s.rebuild(english, repoint)


PATCHERS = {".csv": None, ".fes": None, ".gop": patch_gop, ".asb": patch_asb}


# ------------------------------------------------------------------ main

def main():
    args = sys.argv[1:]

    def opt(name, default):
        if name in args:
            i = args.index(name)
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default
    src = opt("--src", os.path.join("work", "source", "dat"))
    out = opt("--out", os.path.join("work", "output", "build", "overlay"))
    dry = "--dry-run" in args
    files = [a for a in args if not a.startswith("--")] or [
        p for p in (os.path.join("work", "translation", "en", "insert.json"),
                    os.path.join("work", "translation", "en", "insert_campus.json")) if os.path.exists(p)]

    rows = []
    for p in files:
        j = json.load(open(p, encoding="utf-8"))
        rows += j["rows"] if isinstance(j, dict) else j
    by_file = {}
    for r in rows:
        f = r.get("ref", {}).get("file", "")
        if r.get("en") and os.path.splitext(f)[1] in PATCHERS:
            if r.get("lit_nl"):  # the file stores a line break as backslash + n
                r = dict(r, jp=r["jp"].replace("\n", "\\n"), en=r["en"].replace("\n", "\\n"))
            if r.get("src_jp"):  # the source cell differs from the work file's Japanese (a mistyped break)
                r = dict(r, jp=r["src_jp"])
            by_file.setdefault(f, []).append(r)

    notes = []
    grown = 0
    n_variants = 0
    variants = {}  # path -> [_variants/<bundle>/<path>] (tools/muf_archive.py extract)
    manifest = os.path.join(src, "_meta", "manifest.json")
    if os.path.exists(manifest):
        for st in json.load(open(manifest, encoding="utf-8")).get("sets", []):
            for m in st["members"]:
                if m.get("variant") and m["variant"] not in variants.get(m["path"], []):
                    variants.setdefault(m["path"], []).append(m["variant"])
    for f in sorted(by_file):
        path_in = os.path.join(src, *f.split("/"))
        old = open(path_in, "rb").read()
        ext = os.path.splitext(f)[1]
        new = {".csv": patch_csv, ".fes": patch_fes}.get(ext) or PATCHERS[ext]
        new = new(path_in, by_file[f], notes)
        grown += len(new) - len(old)
        if f.endswith(".csv"):
            print("%-36s %4d rows  %7d -> %7d bytes" % (f, len(by_file[f]), len(old), len(new)))
        if not dry:
            path_out = os.path.join(out, *f.split("/"))
            os.makedirs(os.path.dirname(path_out), exist_ok=True)
            open(path_out, "wb").write(new)
            # bundle copies kept apart by extract (_variants/): for the campus .gop tables they are
            # the same file unpacked (the plain copy in macross.dat is RAIC-packed); write them too
            for v in variants.get(f, []):
                orig_v = open(os.path.join(src, *v.split("/")), "rb").read()
                if orig_v == old:
                    data_v = new
                elif old[:4] in (muf_lzss.MAGIC, muf_lzss.MAGIC_STORED) and muf_lzss.decode(old) == orig_v:
                    data_v = muf_lzss.decode(new)
                else:
                    raise ValueError("%s: bundle copy %s is not this file (packed or unpacked)" % (f, v))
                path_v = os.path.join(out, *v.split("/"))
                os.makedirs(os.path.dirname(path_v), exist_ok=True)
                open(path_v, "wb").write(data_v)
                n_variants += 1
    for ext in (".fes", ".gop", ".asb"):
        n = sum(1 for f in by_file if f.endswith(ext))
        n_rows = sum(len(v) for f, v in by_file.items() if f.endswith(ext))
        print("%s: %d rows in %d files" % (ext[1:].upper(), n_rows, n))
    print("total growth %d bytes; %d bundle copies written" % (grown, n_variants))
    if asb_skipped:
        print("ASB: %d pushes left as they are (a number for a non-text function, not a string)" % len(asb_skipped))
    for n in notes:
        print("replaced", n)
    print("dry run, nothing written" if dry else "wrote overlay to " + out)


if __name__ == "__main__":
    main()
