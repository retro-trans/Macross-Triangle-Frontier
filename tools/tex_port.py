"""Import the texture redraws of Ultimate Frontier and Ace Frontier for identical TF textures.

Usage:
  python tools/tex_port.py [--write]

Every texture that MUF or AF redrew (their work/translation/en/images/img_*.json rows) is compared with
every TF texture under work/source/dat/data (unpacked if RAIC-packed): first by bytes, then (same size) by decoded pixels. A TF
texture that matches gets the source project's rows (file renamed to the TF path) and its resolved layout
spec (rule + per-file entry, as tools/redraw_images.py would use it), marked "_from". AF is preferred over
MUF (it is the later review); a byte match over a pixel match; the same path over a moved one.

Writes (with --write):
  work/translation/en/images/img_port.json   imported rows (gitignored: they hold the Japanese)
  work/ui/redraw_layout.json                 styles (shared by MUF and AF) and the imported "files" specs;
                                             existing TF entries without "_from" are kept
  work/ui/tex_port.json                      the match list (no Japanese)
Without --write it only prints the counts.
"""
import glob
import hashlib
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gim  # noqa: E402
import redraw_images as ri  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.dirname(ROOT)
SOURCES = [("AF", os.path.join(PROJECTS, "Macross Ace Frontier")),
           ("MUF", os.path.join(PROJECTS, "Macross Ultimate Frontier"))]  # preference order


def size_of(b, base=0):
    img, _ = gim.parse(b, base)
    return struct.unpack_from("<HH", b, img + 8)


def pix_hash(b):
    return hashlib.sha1(gim.decode(b).tobytes()).hexdigest()


def load_source(name, root):
    by_file = {}
    for f in sorted(glob.glob(os.path.join(root, "work/translation/en/images/img_*.json"))):
        g = os.path.basename(f)[4:-5]
        if g == "logos":  # MUF never reads it: the official series logos are kept
            continue
        for i, r in enumerate(json.load(open(f, encoding="utf-8")).get("rows", [])):
            if "keep_original" in r.get("flags", []):
                continue
            by_file.setdefault(r["file"], []).append(dict(r, _group=g))
    layout = json.load(open(os.path.join(root, "work/ui/redraw_layout.json"), encoding="utf-8"))
    tex = {}
    for path, rows in by_file.items():
        p = os.path.join(root, "work/source/dat", path)
        if not os.path.exists(p):
            continue
        b = open(p, "rb").read()
        try:
            w, h = size_of(b)
        except ValueError:
            continue
        tex[path] = {"rows": rows, "sha": hashlib.sha1(b).hexdigest(), "size": (w, h), "bytes": b}
    return {"name": name, "by_file": by_file, "layout": layout, "tex": tex}


def main():
    write = "--write" in sys.argv
    srcs = [load_source(n, r) for n, r in SOURCES]
    by_sha, by_size = {}, {}
    for s in srcs:
        for path, t in s["tex"].items():
            by_sha.setdefault(t["sha"], []).append((s, path))
            by_size.setdefault(t["size"], []).append((s, path))
    pix_cache = {}

    def src_pix(s, path):
        k = (s["name"], path)
        if k not in pix_cache:
            pix_cache[k] = pix_hash(s["tex"][path]["bytes"])
        return pix_cache[k]

    tf_root = os.path.join(ROOT, "work/source/dat")
    tf_files = sorted(os.path.relpath(p, tf_root).replace("\\", "/")
                      for p in glob.glob(os.path.join(tf_root, "data/**/*.gim"), recursive=True))
    matches = {}
    for path in tf_files:
        b = gim.unpack(open(os.path.join(tf_root, path), "rb").read())
        cands = [(s, sp, "bytes") for s, sp in by_sha.get(hashlib.sha1(b).hexdigest(), [])]
        if not cands and not path.startswith("data/campus/"):  # campus mode is TF's own (10k+ event stills)
            try:
                size = size_of(b)
            except ValueError:
                continue
            same = by_size.get(size)
            if same:
                ph = pix_hash(b)
                cands = [(s, sp, "pixels") for s, sp in same if src_pix(s, sp) == ph]
        if not cands:
            continue
        order = {s["name"]: i for i, s in enumerate(srcs)}
        cands.sort(key=lambda c: (c[2] != "bytes", c[1] != path, order[c[0]["name"]]))
        s, sp, how = cands[0]
        matches[path] = {"src": s["name"], "src_file": sp, "how": how, "moved": sp != path, "_s": s}

    rows_out, files_out, thumbs = [], {}, {}
    for path, m in sorted(matches.items()):
        s, sp = m["_s"], m["src_file"]
        rows = s["by_file"][sp]
        for r in rows:
            r = {k: v for k, v in r.items() if k not in ("_group",)}
            r["file"] = path
            r["port"] = "%s %s (%s)" % (s["name"], sp, r.get("muf_file") and "via MUF" or "")
            r["port"] = r["port"].replace(" ()", "")
            rows_out.append(r)
        items, spec = ri.items_for(s["layout"], sp, [dict(r) for r in rows])
        if spec:
            spec = {k: v for k, v in spec.items() if k != "match"}
            spec["_from"] = "%s %s" % (s["name"], sp)
            files_out[path] = spec
        for th, still in s["layout"].get("thumbnails", {}).items():
            if still == sp:
                thumbs.setdefault(path, []).append(th)
    # thumbnails whose TF copies are matched too
    tf_thumbs = {}
    for path, m in matches.items():
        for th in thumbs.get(path, []):
            tf_th = next((p for p, mm in matches.items() if mm["src_file"] == th and mm["src"] == m["src"]), None)
            if tf_th:
                tf_thumbs[tf_th] = path

    from collections import Counter
    c = Counter((m["src"], m["how"], m["moved"]) for m in matches.values())
    print("TF textures:", len(tf_files), " matched:", len(matches), " rows:", len(rows_out), " specs:", len(files_out),
          " thumbnails:", len(tf_thumbs))
    for k, v in sorted(c.items()):
        print("  %-4s %-6s %s  %d" % (k[0], k[1], "moved" if k[2] else "same path", v))
    srcs_unmatched = {s["name"]: sorted(set(s["tex"]) - {m["src_file"] for m in matches.values() if m["src"] == s["name"]})
                      for s in srcs}
    for n, u in srcs_unmatched.items():
        print("  %s redrawn textures with no TF match: %d" % (n, len(u)))
    if not write:
        return
    os.makedirs(ri.IMAGES, exist_ok=True)
    json.dump({"group": "port", "note": "Rows imported by tools/tex_port.py from MUF/AF for identical textures.",
               "rows": rows_out}, open(os.path.join(ri.IMAGES, "img_port.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    lp = os.path.join(ROOT, "work/ui/redraw_layout.json")
    old = json.load(open(lp, encoding="utf-8")) if os.path.exists(lp) else {}
    base = srcs[0]["layout"]
    layout = {
        "_doc": "Texture redraw layout (docs/image_redraw.md). 'files' entries with _from were imported by "
                "tools/tex_port.py from MUF/AF; others are TF's own.",
        "styles": dict(base["styles"], **old.get("styles", {})),
        "rules": old.get("rules", []),
        "files": dict({k: v for k, v in old.get("files", {}).items() if "_from" not in v}),
        "thumbnails": dict(old.get("thumbnails", {}), **tf_thumbs),
    }
    for k, v in files_out.items():
        layout["files"].setdefault(k, v)
    json.dump(layout, open(lp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"matched": {k: {kk: vv for kk, vv in v.items() if kk != "_s"} for k, v in sorted(matches.items())},
               "source_unmatched": srcs_unmatched},
              open(os.path.join(ROOT, "work/ui/tex_port.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote img_port.json, redraw_layout.json, tex_port.json")


if __name__ == "__main__":
    main()
