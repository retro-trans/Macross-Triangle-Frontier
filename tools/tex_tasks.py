"""Make the texture review tasks (docs/image_translation_brief.md).

Usage:
  python tools/tex_tasks.py [--groups N]

Lists every TF texture that may show Japanese and is not already covered by an imported MUF/AF redraw
(work/ui/tex_port.json), drops the kinds that are kept as they are, folds textures with identical pixels
into one (the others are listed as `same_as`), and splits the rest into review groups with packed sheets:

  work/ui/gim_png/_tasks/task_<G>.json   files, size, folder, same_as, sheets
  work/ui/gim_png/_tasks/<G>_NNN.png     packed review sheets (small textures enlarged 2x/3x)
  work/ui/gim_png/_tasks/summary.json    what was left out and why

Needs the PNGs of `python tools/gim.py dir data/<top>/<folder> work/ui/gim_png/<top>[_<folder>]`.
"""
import glob
import hashlib
import json
import os
import re
import sys

from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PNG = os.path.join(ROOT, "work/ui/gim_png")
OUT = os.path.join(PNG, "_tasks")
# PNG folder -> data path prefix (tools/gim.py dir names files by their path under the folder, "/" -> "__")
FOLDERS = {"menu": "data/menu/", "script": "data/script/", "cockpit": "data/cockpit/", "extra": "data/extra/",
           "campus_icon": "data/campus/icon/", "campus_interface": "data/campus/interface/",
           "campus_event_bg": "data/campus/event/bg/", "campus_event_evpic": "data/campus/event/evpic/"}
LEAVE = [  # (regex on the data path, why it is kept as it is)
    (r"^data/menu/gallery/picture_s/", "gallery thumbnails (pictures; made from the stills)"),
    (r"^data/menu/load/(?!loading|mac_)", "gallery and loading stills (mecha renders, anime frames)"),
    (r"^data/campus/event/(bg|evpic)/", "campus backgrounds and event pictures (art, no captions)"),
    (r"^data/cockpit/gfp/", "cockpit pilot portraits"),
    (r"^data/cockpit/sppl/p", "special-attack cut-in portraits"),
    (r"^data/menu/(face_s|face_m|face_ss|face_l|map_face|mecha_s|mecha_m|mecha_l|arms_s|excard_s)/.*\d",
     "character and unit cards (portraits, renders)"),
    (r"_eng(lish)?(\.gim|_)", "already English (subtitle cards and banners)"),
    (r"/a2a_", "layout-editor preview pictures"),
    (r"_dummy", "dummy textures"),
]


def path_of(folder, name):
    m = re.match(r"(.*\.gfp)_(\d\d)$", name)
    rel = (m.group(1) if m else name).replace("__", "/")
    return FOLDERS[folder] + rel + ("#" + m.group(2) if m else "")


def main():
    groups = int(sys.argv[sys.argv.index("--groups") + 1]) if "--groups" in sys.argv else 5
    port = set(json.load(open(os.path.join(ROOT, "work/ui/tex_port.json"), encoding="utf-8"))["matched"])
    left, items = {}, []
    for folder in FOLDERS:
        for p in sorted(glob.glob(os.path.join(PNG, folder, "*.png"))):
            path = path_of(folder, os.path.basename(p)[:-4])
            if path.split("#")[0] in port:
                left.setdefault("imported from MUF/AF (tools/tex_port.py)", []).append(path)
                continue
            why = next((w for rx, w in LEAVE if re.search(rx, path)), None)
            if why:
                left.setdefault(why, []).append(path)
                continue
            items.append((path, p))
    # identical pixels: review one
    by_hash, uniq = {}, []
    for path, p in items:
        im = Image.open(p).convert("RGBA")
        if im.getextrema()[3][1] == 0:
            left.setdefault("fully transparent", []).append(path)
            continue
        h = hashlib.sha1(im.tobytes() + str(im.size).encode()).hexdigest()
        if h in by_hash:
            by_hash[h]["same_as"].append(path)
            continue
        e = {"file": path, "png": os.path.relpath(p, ROOT).replace(os.sep, "/"), "size": list(im.size), "same_as": []}
        by_hash[h] = e
        uniq.append(e)
    # groups: keep folders together, balance by pixel area
    def folder_key(e):
        return "/".join(e["file"].split("/")[:3])
    uniq.sort(key=lambda e: (folder_key(e), e["file"]))
    total = sum(max(4096, e["size"][0] * e["size"][1]) for e in uniq)
    per, cur, g = total / groups, 0, 0
    names = "ABCDEFGHIJKLMNOP"
    for e in uniq:
        if cur >= per * (g + 1) and g < groups - 1:
            g += 1
        e["group"] = names[g]
        cur += max(4096, e["size"][0] * e["size"][1])
    os.makedirs(OUT, exist_ok=True)
    for f in glob.glob(os.path.join(OUT, "*")):
        os.remove(f)
    for gi in range(groups):
        G = names[gi]
        mine = [e for e in uniq if e["group"] == G]
        sheets = pack(mine, G)
        json.dump({"group": G, "textures": mine, "sheets": sheets},
                  open(os.path.join(OUT, "task_%s.json" % G), "w", encoding="utf-8"), indent=1)
        print("group %s: %d textures (+%d identical), %d sheets, folders %s" % (
            G, len(mine), sum(len(e["same_as"]) for e in mine), len(sheets),
            sorted({folder_key(e)[5:] for e in mine})))
    # identical copies get the reviewed texture's rows (tools/redraw_images.py load_rows)
    json.dump({e["file"]: e["same_as"] for e in uniq if e["same_as"]},
              open(os.path.join(ROOT, "work/ui/tex_same.json"), "w", encoding="utf-8"), indent=1)
    json.dump({k: {"count": len(v), "files": v} for k, v in left.items()},
              open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8"), indent=1)
    for k, v in left.items():
        print("left out: %5d  %s" % (len(v), k))
    print("to review: %d unique textures" % len(uniq))


def pack(entries, G, W=1400, H=1400):
    """Shelf-pack the textures (small ones enlarged) onto sheets with their file names."""
    sheets, cur, x, y, rowh, listed = [], None, 0, 0, 0, []

    def flush():
        if cur is not None:
            name = "%s_%03d.png" % (G, len(sheets))
            cur.save(os.path.join(OUT, name))
            sheets.append({"sheet": "work/ui/gim_png/_tasks/" + name, "files": list(listed)})

    for e in entries:
        im = Image.open(os.path.join(ROOT, e["png"])).convert("RGBA")
        k = 3 if max(im.size) <= 64 else 2 if max(im.size) <= 160 else 1
        if k > 1:
            im = im.resize((im.width * k, im.height * k), Image.NEAREST)
        if im.width > W - 4:
            im.thumbnail((W - 4, H - 20))
        w, h = im.width + 4, im.height + 16
        if cur is None or x + w > W:
            x, y, rowh = 0, y + rowh, 0
        if cur is None or y + h > H:
            flush()
            cur, x, y, rowh, listed = Image.new("RGBA", (W, H), (70, 70, 80, 255)), 0, 0, 0, []
        bg = Image.new("RGBA", im.size, (110, 110, 125, 255))
        bg.alpha_composite(im)
        cur.paste(bg, (x + 2, y + 14))
        label = e["file"].split("/")[-1] + ("" if k == 1 else " x%d" % k)
        ImageDraw.Draw(cur).text((x + 2, y + 1), label[:max(8, w // 6)], fill=(255, 255, 0))
        listed.append(e["file"])
        x += w
        rowh = max(rowh, h)
    flush()
    return sheets


if __name__ == "__main__":
    main()
