"""Redraw the Japanese text in game textures in English (docs/image_redraw.md).

Ported from the Macross Ultimate Frontier project (same engine and GIM format).

Usage:
  python tools/redraw_images.py [--out <overlay>] [--preview <dir>] [--only <substr>] [--no-sheets] [--no-write]

Inputs:
  work/translation/en/images/img_*.json   rows: file, size, jp, en, style, notes, and (from the texture
                               review, docs/image_translation_brief.md) measured items: box, plate, bg,
                               color, align, fallbacks. Gitignored: they hold the Japanese.
  work/ui/redraw_layout.json   styles, rules and per-texture specs; a spec overrides the measured items
  work/source/dat/<file>       original GIM textures

Outputs:
  <overlay>/data/...gim        re-encoded textures (default work/output/redraw/overlay), for
                               muf_archive.py repack --overlay
  <preview>/                   before/after contact sheets + report.json (default work/ui/redraw_preview)

Per texture, every item first erases its box (erase mode), then every item draws its
text. A texture with no spec in the layout gets one from its rows' measured items
(auto_spec()). Text is drawn 4x supersampled from Noto Sans JP (SIL OFL 1.1), fitted to
the box (fit(): a small shrink, then a light squeeze, then the short forms, then a hard
squeeze), and the result is quantized back to the texture's own palette size by
tools/gim.py. Loading-screen tip cards are typeset as a whole (tipcard()); gallery
thumbnails are shrunk from the redrawn stills.
Specs with "keep" are left as they are; specs with "hold" get a preview only.
"""
import argparse
import fnmatch
import glob
import json
import os
import re
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gim  # noqa: E402
import muf_lzss  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = os.path.join(ROOT, "work/translation/en/images")
FONTS = {  # SIL Open Font License 1.1
    "sans": r"C:\Windows\Fonts\NotoSansJP-VF.ttf",
    "serif": r"C:\Windows\Fonts\NotoSerifJP-VF.ttf",
}
SS = 4  # supersampling factor

DEFAULT_STYLE = {
    "font": "sans", "weight": 700, "size": 13, "min_size": 8, "xscale_min": 0.72, "tracking": 0,
    "color": [255, 255, 255, 255], "gradient": None, "outline": None, "glow": None, "shadow": None,
    "italic": 0.0, "align": "center", "valign": "center", "line_gap": 1.15, "caps": False,
    "wrap": False, "max_lines": 1, "dx": 0, "dy": 0, "ss": SS, "bold_px": 0, "opacity": 1.0,
    "line_px": None, "shrink_first": 0.86, "soft_xscale": 0.84,
}

_variants = None
VERSION = "dev"  # --version: replaces {version} in item texts


def src_bytes(path):
    """The original texture, unpacked: Triangle Frontier keeps many plain textures RAIC-packed."""
    return gim.unpack(open(os.path.join(ROOT, "work/source/dat", path), "rb").read())


def variants_of(path):
    """Bundle copies kept apart by tools/muf_archive.py extract (_variants/<bundle>/<path>): the unpacked
    form of a RAIC-packed plain texture."""
    global _variants
    if _variants is None:
        _variants = {}
        man = os.path.join(ROOT, "work/source/dat/_meta/manifest.json")
        if os.path.exists(man):
            for st in json.load(open(man, encoding="utf-8")).get("sets", []):
                for m in st["members"]:
                    if m.get("variant") and m["variant"] not in _variants.get(m["path"], []):
                        _variants.setdefault(m["path"], []).append(m["variant"])
    return _variants.get(path, [])


def write_gim(out, path, nb):
    """Write a redrawn texture into the overlay the way the original is stored: RAIC/RAIB-packed if the
    plain file is, plus every bundle copy (_variants/) that is the same texture unpacked."""
    orig = open(os.path.join(ROOT, "work/source/dat", path), "rb").read()
    data = nb
    if orig[:4] in (muf_lzss.MAGIC, muf_lzss.MAGIC_STORED):
        data = muf_lzss.encode(nb, muf_lzss.member_mode(orig))
    targets = [(path, data)]
    for v in variants_of(path):
        vb = open(os.path.join(ROOT, "work/source/dat", v), "rb").read()
        if vb == gim.unpack(orig):
            targets.append((v, nb))
        else:
            print("  WARNING bundle copy differs, not redrawn:", v)
    for p_, d_ in targets:
        o = os.path.join(out, p_)
        os.makedirs(os.path.dirname(o), exist_ok=True)
        open(o, "wb").write(d_)


_font_cache = {}


def font(name, size, weight):
    key = (name, size, weight)
    if key not in _font_cache:
        f = ImageFont.truetype(FONTS.get(name, name), size)
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
        _font_cache[key] = f
    return _font_cache[key]


# ---------------------------------------------------------------- rows / layout

def load_rows():
    """Every img_*.json under work/translation/en/images. A texture listed twice keeps the rows of the
    first group that has it; img_muf.json (rows imported from MUF for identical textures, whose MUF
    layout specs are in the layout file) comes first, then the others in name order."""
    by_file = {}
    for f in sorted(glob.glob(os.path.join(IMAGES, "img_*.json")), key=lambda f: (not f.endswith("img_muf.json"), f)):
        g = os.path.basename(f)[4:-5]
        d = json.load(open(f, encoding="utf-8"))
        seen = set()
        for i, r in enumerate(d.get("rows", [])):
            if r["file"] in by_file and r["file"] not in seen:
                continue  # already given by another group
            if "keep_original" in r.get("flags", []):
                continue  # Japanese that stays (logos, signs in pictures): listed, not redrawn
            seen.add(r["file"])
            r = dict(r, group=g, index=i)
            by_file.setdefault(r["file"], []).append(r)
    # textures with pixels identical to a reviewed one (tools/tex_tasks.py) take its rows and its spec
    same = os.path.join(ROOT, "work/ui/tex_same.json")
    if os.path.exists(same):
        for src, copies in json.load(open(same, encoding="utf-8")).items():
            for c in copies:
                if src in by_file and c not in by_file and "#" not in c:
                    by_file[c] = [dict(r, file=c, same_as=src) for r in by_file[src]]
    return by_file


def _grow(b, n, lim=None):
    x, y, w, h = b
    g = [x - n, y - n, w + 2 * n, h + 2 * n]
    if lim:
        lx, ly, lw, lh = lim
        x0, y0 = max(g[0], lx), max(g[1], ly)
        x1, y1 = min(g[0] + g[2], lx + lw), min(g[1] + g[3], ly + lh)
        g = [x0, y0, max(0, x1 - x0), max(0, y1 - y0)]
    return g


def auto_spec(rows):
    """A spec from the measured items of the review rows (docs/image_translation_brief.md):
    erase the old glyph box (grown by 1-2 px, kept inside the plate) by the background kind,
    then draw into the plate, at the old glyphs' height and alignment."""
    items = []
    for ri, r in enumerate(rows):
        for it in r.get("items", []):
            box = [int(round(v)) for v in it["box"]]
            plate = [int(round(v)) for v in it.get("plate", box)]
            bg = it.get("bg", "transparent")
            col = it.get("color") or [255, 255, 255]
            out = {"row": ri, "line": it.get("line", 0)}
            edge = 2 if (it.get("outline") or it.get("glow")) else 1
            eb = it.get("erase_box") or _grow(box, edge, plate)  # an atlas word: erase wider than it draws
            if bg == "transparent":
                er = "clear"
            elif bg in ("flat", "bands"):
                left = box[0] - edge - 1
                sx = left if left >= plate[0] else min(r["size"][0] - 1, box[0] + box[2] + edge)
                er = {"mode": "row", "sample_x": sx}
            elif bg == "hgrad":
                er = "plate"
            elif bg == "vgrad":
                er = "vplate"
            else:  # picture
                er = [{"mode": "inpaint", "color": list(col[:3]), "tol": 70, "grow": edge}]
                for k in ("outline", "glow"):
                    if it.get(k):
                        er.append({"mode": "inpaint", "color": list(it[k][:3]), "tol": 50, "grow": 1})
            out["erase"], out["erase_box"] = er, eb
            h = box[3]
            align = it.get("align", "center")
            if align == "left":
                dx0, dx1 = box[0], plate[0] + plate[2]
            elif align == "right":
                dx0, dx1 = plate[0], box[0] + box[2]
            else:
                cx = box[0] + box[2] / 2
                half = min(cx - plate[0], plate[0] + plate[2] - cx)
                dx0, dx1 = int(round(cx - half)), int(round(cx + half))
            out["box"] = [dx0, box[1], max(1, dx1 - dx0), h]
            size = max(7, int(round(h * 0.95)))
            out.update(size=size, min_size=max(7, int(round(size * 0.8))), align=align, color=list(col[:3]) + [255])
            if it.get("outline"):
                out["outline"] = {"width": 1, "color": list(it["outline"][:3]) + [220]}
            if it.get("glow"):  # a thick coloured edge round a white fill: solid edge + soft glow
                out["outline"] = {"width": 1.3, "color": list(it["glow"][:3]) + [255]}
                out["glow"] = {"radius": 1.3, "strength": 1.6, "color": list(it["glow"][:3]) + [200]}
            if it.get("glow") or it.get("outline"):
                out["weight"] = 800
            if it.get("gradient"):
                out["gradient"] = [list(c[:3]) + [255] for c in it["gradient"]]
            if it.get("italic"):
                out["italic"] = -0.2
            if it.get("fallbacks"):
                out["fallbacks"] = it["fallbacks"]
            if it.get("text") is not None:
                out["text"] = it["text"]
            items.append(out)
    return {"items": items, "_auto": True} if items else None


def load_layout(path):
    return json.load(open(path, encoding="utf-8"))


def items_for(layout, path, rows):
    """The item list for one texture: the first matching rule, overridden by the
    per-file entry (its "set" keys are merged into the rule's)."""
    spec = None
    for rule in layout.get("rules", []):
        pats = rule["match"] if isinstance(rule["match"], list) else [rule["match"]]
        if any(fnmatch.fnmatch(path, p) for p in pats):
            spec = dict(rule)
            break
    own = layout.get("files", {}).get(path)
    if own is not None:
        spec = dict(spec or {})
        merged = dict(spec.get("set", {}))
        merged.update(own.get("set", {}))
        spec.update(own)
        spec["set"] = merged
    if spec is None and rows and rows[0].get("card"):
        spec = {"items": [{"tipcard": True}]}
    if spec is None or ("items" not in spec and not spec.get("keep")):
        auto = auto_spec(rows)
        if auto is not None:
            spec = dict(auto, **{k: v for k, v in (spec or {}).items() if k != "items"})
    if spec is None:
        return None, {}
    items = spec.get("items") or [{}]
    if spec.get("extra_items"):  # drawn on top of the texture's own items (the title-screen version stamp)
        items = list(items) + [dict(i) for i in spec["extra_items"]]
    if spec.get("item_all"):  # the same style keys on every item (one size for a row of tiles)
        items = [dict(i, **spec["item_all"]) for i in items]
    if spec.get("item_set"):  # {"<row>:<line>" or "<line>": {style or box keys}} over the auto items
        items = [dict(i) for i in items]
        for i in items:
            for key in ("%d:%d" % (i.get("row", 0), i.get("line", 0)), str(i.get("line", 0))):
                i.update(spec["item_set"].get(key, {}))
    return items, spec


def style_of(layout, item, spec, row=None):
    st = dict(DEFAULT_STYLE)
    names = []
    for src in (spec, item):
        if "style" in src:
            names += src["style"] if isinstance(src["style"], list) else [src["style"]]
    # "style_by_row": {"red": "rat_red", ...} picks a preset from the row's style words
    for word, name in spec.get("style_by_row", {}).items():
        if row is not None and row["style"].lower().startswith(word):
            names.append(name)
            break
    for n in names:
        st.update(layout["styles"][n])
    for src in (spec.get("set", {}), item):
        for k, v in src.items():
            if k in DEFAULT_STYLE:
                st[k] = v
    return st


# ---------------------------------------------------------------- erasing

def rgba(a):
    return np.asarray(a, np.float32)


def erase(arr, box, mode, opt):
    """arr: float32 HxWx4 (straight alpha). Erase box in place."""
    H, W = arr.shape[:2]
    x, y, w, h = box
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    if mode == "keep":
        return
    if mode == "clear":
        arr[y0:y1, x0:x1] = 0
    elif mode == "fill":
        arr[y0:y1, x0:x1] = rgba(opt["color"])
    elif mode in ("plate", "vplate"):
        # linear interpolation across the box from the pixels just outside it
        if mode == "plate":
            a = arr[y0:y1, x0 - 1] if x0 > 0 else None
            b = arr[y0:y1, x1] if x1 < W else None
            a = b if a is None else a
            b = a if b is None else b
            t = (np.arange(x1 - x0, dtype=np.float32) + 1) / (x1 - x0 + 1)
            arr[y0:y1, x0:x1] = a[:, None] * (1 - t)[None, :, None] + b[:, None] * t[None, :, None]
        else:
            a = arr[y0 - 1, x0:x1] if y0 > 0 else None
            b = arr[y1, x0:x1] if y1 < H else None
            a = b if a is None else a
            b = a if b is None else b
            t = (np.arange(y1 - y0, dtype=np.float32) + 1) / (y1 - y0 + 1)
            arr[y0:y1, x0:x1] = a[None] * (1 - t)[:, None, None] + b[None] * t[:, None, None]
    elif mode == "row":
        # every row takes the colour of a sample column (for plates with a vertical gradient)
        sx = opt.get("sample_x", x0 - 1 if x0 > 0 else x1)
        arr[y0:y1, x0:x1] = arr[y0:y1, sx][:, None]
    elif mode == "col":
        sy = opt.get("sample_y", y0 - 1 if y0 > 0 else y1)
        arr[y0:y1, x0:x1] = arr[sy, x0:x1][None]
    elif mode == "copy":
        sx, sy = opt["from"]
        arr[y0:y1, x0:x1] = arr[sy + (y0 - y):sy + (y1 - y), sx + (x0 - x):sx + (x1 - x)].copy()
    elif mode == "inpaint":
        mask = np.zeros((H, W), bool)
        mask[y0:y1, x0:x1] = True
        if "color" in opt:  # only pixels near the text colour (plus a margin)
            c = rgba(opt["color"])[:3]
            near = (np.abs(arr[:, :, :3] - c).max(2) <= opt.get("tol", 60)) & (arr[:, :, 3] > 0)
            m2 = np.zeros((H, W), bool)
            m2[y0:y1, x0:x1] = near[y0:y1, x0:x1]
            g = opt.get("grow", 1)
            if g:
                m2 = np.asarray(Image.fromarray(m2.astype(np.uint8) * 255).filter(
                    ImageFilter.MaxFilter(2 * g + 1))) > 0
            mask = m2 & mask
        inpaint(arr, mask, opt.get("iters", 0))
    elif mode == "frost":
        r = opt.get("blur", 6)
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
        bl = np.asarray(im.filter(ImageFilter.GaussianBlur(r)), np.float32)
        dark = opt.get("dark", 0.5)
        tint = rgba(opt.get("tint", [0, 0, 0]))[:3]
        feather = opt.get("feather", 6)
        m = np.zeros((H, W), np.float32)
        m[y0:y1, x0:x1] = 1
        if feather:
            m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(feather)), np.float32) / 255
            m[y0:y1, x0:x1] = np.maximum(m[y0:y1, x0:x1], opt.get("core", 0.0))
        out = bl.copy()
        out[:, :, :3] = bl[:, :, :3] * (1 - dark) + tint * dark
        arr[:] = arr * (1 - m[:, :, None]) + out * m[:, :, None]
    else:
        raise ValueError("unknown erase mode " + mode)


def inpaint(arr, mask, iters=0):
    """Fill masked pixels from their unmasked neighbours (onion-peel diffusion)."""
    H, W = mask.shape
    known = ~mask
    a = arr.copy()
    a[mask] = 0
    rem = mask.copy()
    k = 0
    while rem.any():
        acc = np.zeros_like(a)
        cnt = np.zeros((H, W), np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            sk = np.zeros((H, W), bool)
            sa = np.zeros_like(a)
            ys = slice(max(0, dy), H + min(0, dy))
            yd = slice(max(0, -dy), H + min(0, -dy))
            xs = slice(max(0, dx), W + min(0, dx))
            xd = slice(max(0, -dx), W + min(0, -dx))
            sk[yd, xd] = known[ys, xs]
            sa[yd, xd] = a[ys, xs]
            acc += sa * sk[:, :, None]
            cnt += sk
        new = rem & (cnt > 0)
        if not new.any():
            break
        a[new] = acc[new] / cnt[new][:, None]
        known = known | new
        rem = rem & ~new
        k += 1
    for _ in range(iters):  # smooth the filled area
        b = a.copy()
        b[1:-1, 1:-1] = (a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]) / 4
        a[mask] = b[mask]
    arr[mask] = a[mask]


# ---------------------------------------------------------------- text

def measure(text, st, size):
    f = font(st["font"], size * st["ss"], st["weight"])
    w = f.getlength(text) + st["tracking"] * st["ss"] * max(0, len(text) - 1)
    return w / st["ss"]


def fit(texts, box, st):
    """Pick text, lines, size and xscale: (lines, size, xscale, overflow, text index).

    Two passes, each over every candidate text in order (the translation, then its
    fallbacks): 1) shrink the font a little (to shrink_first x size) without
    squeezing, then squeeze lightly (down to soft_xscale) at any size down to
    min_size; 2) squeeze hard (down to xscale_min). So a short form is preferred
    to a hard squeeze, and the full text to a short form when it fits pass 1."""
    bw, bh = box[2], box[3]
    floor = max(st["min_size"], int(st["size"] * st["shrink_first"] + 0.999))
    soft = max(st["xscale_min"], st["soft_xscale"])
    passes = [[(s, 1.0) for s in range(st["size"], floor - 1, -1)] +
              [(s, soft) for s in range(st["size"], st["min_size"] - 1, -1)],
              [(s, st["xscale_min"]) for s in range(st["size"], st["min_size"] - 1, -1)]]
    cands = []
    for text in texts:
        if st["caps"]:
            text = text.upper()
        variants = [text.split("\n")]
        if st["wrap"] and "\n" not in text:
            words = text.split(" ")
            for k in range(1, len(words)):
                variants.append([" ".join(words[:k]), " ".join(words[k:])])
        cands.append((text, variants))
    for plan in passes:
        for ti, (text, variants) in enumerate(cands):
            for size, squeeze in plan:
                for lines in variants:
                    if len(lines) > max(st["max_lines"], len(text.split("\n"))):
                        continue
                    lh = st["line_px"] or size * st["line_gap"]
                    if size * 0.75 + lh * (len(lines) - 1) > bh + 2 and len(lines) > 1:
                        continue
                    w = max(measure(l, st, size) for l in lines) + abs(st["italic"]) * size
                    if w <= bw:
                        return lines, size, 1.0, False, ti
                    if squeeze < 1 and w * squeeze <= bw:
                        return lines, size, bw / w, False, ti
    lines = cands[-1][1][0]
    size = st["min_size"]
    w = max(measure(l, st, size) for l in lines)
    return lines, size, max(bw / w, 0.3), True, len(texts) - 1


def mask_layer(img, r, kind):
    if r <= 0:
        return img
    if kind == "max":
        n = int(round(r)) * 2 + 1
        return img.filter(ImageFilter.MaxFilter(n))
    return img.filter(ImageFilter.GaussianBlur(r))


def draw_text(arr, box, lines, size, xscale, st):
    """Composite the text into arr (float32 RGBA) inside box."""
    ss = st["ss"]
    x, y, bw, bh = box
    pad = 2 + int(max((st["outline"] or {}).get("width", 0), (st["glow"] or {}).get("radius", 0) * 2,
                      abs((st["shadow"] or {}).get("dx", 0)) + abs((st["shadow"] or {}).get("dy", 0))) + 1)
    cw, ch = bw + 2 * pad, bh + 2 * pad
    # supersampled canvas, horizontally pre-stretched by 1/xscale
    sw, sh = int(round(cw * ss / xscale)), ch * ss
    m = Image.new("L", (sw, sh), 0)
    d = ImageDraw.Draw(m)
    f = font(st["font"], size * ss, st["weight"])
    cap_top, cap_bot = f.getbbox("H")[1], f.getbbox("H")[3]
    cap = cap_bot - cap_top
    lh = (st["line_px"] or size * st["line_gap"]) * ss
    total = cap + lh * (len(lines) - 1)
    if st["valign"] == "top":
        top = pad * ss
    elif st["valign"] == "bottom":
        top = (pad + bh) * ss - total
    else:
        top = (pad * ss + (bh * ss - total) / 2)
    top += st["dy"] * ss
    for i, line in enumerate(lines):
        lw = (f.getlength(line) + st["tracking"] * ss * max(0, len(line) - 1))
        inner = bw * ss / xscale
        if st["align"] == "left":
            lx = 0
        elif st["align"] == "right":
            lx = inner - lw
        else:
            lx = (inner - lw) / 2
        lx += pad * ss / xscale + st["dx"] * ss / xscale
        ly = top + i * lh - cap_top
        if st["tracking"]:
            cx = lx
            for ch_ in line:
                d.text((cx, ly), ch_, font=f, fill=255)
                cx += f.getlength(ch_) + st["tracking"] * ss
        else:
            d.text((lx, ly), line, font=f, fill=255)
    if st["bold_px"]:
        m = mask_layer(m, st["bold_px"] * ss / 2, "max")
    if st["italic"]:
        sh_ = st["italic"]
        m = m.transform(m.size, Image.AFFINE, (1, sh_, -sh_ * sh / 2, 0, 1, 0), Image.BICUBIC)
    layers = []  # (mask at 1x, colour or gradient)

    def down(img):
        return np.asarray(img.resize((cw, ch), Image.BOX), np.float32) / 255

    fill = down(m)
    if st["glow"]:
        g = st["glow"]
        gm = mask_layer(m, g.get("spread", 0) * ss, "max") if g.get("spread") else m
        gm = down(gm.filter(ImageFilter.GaussianBlur(g["radius"] * ss)))
        layers.append((np.clip(gm * g.get("strength", 1.5), 0, 1), g["color"]))
    if st["shadow"]:
        s = st["shadow"]
        sm = Image.new("L", m.size, 0)
        sm.paste(mask_layer(m, s.get("width", 0) * ss, "max"), (int(s.get("dx", 1) * ss / xscale), int(s.get("dy", 1) * ss)))
        if s.get("blur"):
            sm = sm.filter(ImageFilter.GaussianBlur(s["blur"] * ss))
        layers.append((down(sm), s["color"]))
    if st["outline"]:
        o = st["outline"]
        om = mask_layer(m, o["width"] * ss, "max")
        if o.get("blur"):
            om = om.filter(ImageFilter.GaussianBlur(o["blur"] * ss))
        layers.append((down(om), o["color"]))
    if st["gradient"]:
        g0, g1 = rgba(st["gradient"][0]), rgba(st["gradient"][1])
        yy = (np.arange(ch, dtype=np.float32) - pad) / max(1, bh - 1)
        # gradient runs over the text's cap height, not the whole box
        t0 = (top / ss - pad) / bh
        t1 = (top + total) / ss / bh - pad / bh
        t = np.clip((yy - t0) / max(1e-3, t1 - t0), 0, 1)
        col = g0[None, :] * (1 - t)[:, None] + g1[None, :] * t[:, None]
        layers.append((fill, col[:, None, :] * np.ones((1, cw, 1), np.float32)))
    else:
        layers.append((fill, st["color"]))
    H, W = arr.shape[:2]
    X0, Y0 = x - pad, y - pad
    sx0, sy0 = max(0, -X0), max(0, -Y0)
    sx1, sy1 = min(cw, W - X0), min(ch, H - Y0)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    dst = arr[Y0 + sy0:Y0 + sy1, X0 + sx0:X0 + sx1]
    clip = st.get("clip")
    for a, col in layers:
        a = a[sy0:sy1, sx0:sx1] * st["opacity"]
        col = rgba(col)
        if col.ndim == 3:
            col = col[sy0:sy1, sx0:sx1]
            ca = a * col[:, :, 3] / 255
            crgb = col[:, :, :3]
        else:
            ca = a * col[3] / 255
            crgb = col[None, None, :3]
        da = dst[:, :, 3] / 255
        oa = ca + da * (1 - ca)
        with np.errstate(invalid="ignore", divide="ignore"):
            rgb = (crgb * ca[:, :, None] + dst[:, :, :3] * (da * (1 - ca))[:, :, None]) / oa[:, :, None]
        rgb = np.where(oa[:, :, None] > 0, rgb, dst[:, :, :3])
        dst[:, :, :3] = rgb
        dst[:, :, 3] = oa * 255
    if clip:  # keep the drawing inside the box
        pass


# ---------------------------------------------------------------- per texture

def text_for(item, rows, spec=None):
    """Candidate texts: the translation (or the item's "text"), then its fallbacks.
    "prefer_replace": [[old, new], ...] on the spec puts a spelled-out form first
    (row notes such as "spell out 'Forward' if it fits")."""
    r = rows[item.get("row", 0)]
    if "text" in item:
        t = item["text"]
    else:
        t = r["en"]
        if "line" in item:
            t = t.split("\n")[item["line"]]
    t = t.replace("{version}", VERSION)  # the build's version (title-screen stamp)
    out = [t] + list(item.get("fallbacks", []))
    pref = t
    for a, b in (spec or {}).get("prefer_replace", []):
        pref = pref.replace(a, b)
    return ([pref] if pref != t else []) + out


def share_choices(layout, by_file):
    """For items with the same "share" key, the first candidate text that fits all of them."""
    need = {}
    for path, rows in by_file.items():
        items, spec = items_for(layout, path, rows)
        for it in items or []:
            grp = it.get("share")
            if not grp:
                continue
            W, H = rows[0]["size"]
            st = style_of(layout, it, spec, rows[it.get("row", 0)])
            box = it.get("box", spec.get("box", [0, 0, W, H]))
            need[grp] = max(need.get(grp, 0), fit(text_for(it, rows, spec), box, st)[4])
    choice = dict(layout.get("shared_text", {}))
    choice.update(need)
    return choice


TIP_COLORS = {"w": [248, 248, 248, 255], "y": [244, 248, 0, 255], "g": [16, 248, 0, 255],
              "o": [255, 168, 40, 255], "h1": [248, 236, 0, 255], "h2": [16, 248, 0, 255],
              "h3": [0, 224, 255, 255]}
TIP_DIALOGUE = {"title_y": 16, "title_x": [104, 474], "y0": 52, "pitch": 14, "speaker_x": 101,
                "colon_x": 133, "text_x": 139, "right": 446, "next_y": 262}


def _runs(text, base):
    """'a [y]b[/] c' -> [(a, base), (b, y), (c, base)]."""
    out, pos, cur = [], 0, base
    for m in re.finditer(r"\[(\w+)\]|\[/\]", text):
        if m.start() > pos:
            out.append((text[pos:m.start()], cur))
        cur = m.group(1) or base
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], cur))
    return out


def tipcard(arr, rows, it, layout, spec):
    """Loading-screen tip card (mac00001-mac00005): the whole text is typeset again.

    Cards 1-4 are a dialogue: speaker column, colon, text, one line every 14 px from y 52, a title
    at y 16 and "Next - ..." at y 262; card 5 has headings and bullets at the y positions in its
    spec ("ys"). The English keeps the Japanese line positions, so the dashed separators stay.
    The old lettering (bright fill with a black edge) is inpainted, a soft dark shade is laid under
    the old and new lines, and the English is drawn with the same colours and a black edge."""
    H, W = arr.shape[:2]
    card = rows[0]["card"]
    g = dict(TIP_DIALOGUE, **spec.get("geom", {}))
    st = style_of(layout, it, spec, rows[0])
    st.update(outline={"width": 1, "color": [0, 0, 0, 255]}, align="left")
    lines = card["lines"]
    ys = g.get("ys") or [g["y0"] + g["pitch"] * k for k in range(len(lines))]
    has_speaker = any(l.get("speaker") is not None for l in lines if not l.get("sep"))
    tx = g["text_x"] if has_speaker else g.get("bullet_x", 104)
    avail = g["right"] - tx
    body = [(l, y) for l, y in zip(lines, ys) if not l.get("sep")]

    def width(text, size):
        return sum(measure(t, st, size) for t, _ in _runs(text, "w"))

    size = None
    for sz in range(g.get("size", 10), 7, -1):
        if all(width(l["text"], sz) * g.get("xscale_min", 0.8) <= avail - (5 if l["text"].startswith("  ") else 0)
               for l, _ in body):
            size = sz
            break
    size = size or 8
    layer = np.zeros_like(arr)
    rep = []

    def put(text, x, y, right, sz, base, extra=None):
        s2 = dict(st, size=sz, **(extra or {}))
        runs = _runs(text, base)
        total = sum(measure(t, s2, sz) for t, _ in runs)
        xs = min(1.0, (right - x) / total) if total else 1.0
        cx = float(x)
        for t, c in runs:
            w = measure(t, s2, sz) * xs
            s3 = dict(s2, color=TIP_COLORS.get(c, TIP_COLORS["w"]))
            draw_text(layer, [int(round(cx)), y, int(w) + 3, 10], [t], sz, xs, s3)
            cx += w
        rep.append({"text": re.sub(r"\[/?\w*\]", "", text), "size": sz, "xscale": round(xs, 3), "overflow": xs < 0.7})

    bands = []
    t0, t1 = g["title_x"]
    put(card["title"], t0, g["title_y"] + 1, t1, g.get("title_size", 12), "w", {"weight": 800})
    bands.append(g["title_y"])
    for l, y in body:
        indent = 5 if l["text"].startswith("  ") else 0
        text = l["text"].strip(" ")
        if l.get("speaker"):
            put(l["speaker"], g["speaker_x"], y, g["colon_x"] - 1, size, "w")
            put(":", g["colon_x"], y, g["colon_x"] + 5, size, "w")
        x0 = (tx if l.get("speaker") is not None else (g["speaker_x"] if has_speaker else tx)) + indent
        if l.get("color", "w").startswith("h"):
            x0 = g.get("heading_x", x0)
        put(text, x0, y, g["right"], size, l.get("color", "w"))
        bands.append(y)
    if card.get("next"):
        put(card["next"], g["speaker_x"], g["next_y"], g["right"], size, "w")
        bands.append(g["next_y"])
    for y in g.get("extra_bands", []):
        bands.append(y)
    # old lettering: pixels of the text colours with a black edge, inside the text bands
    c = arr[:, :, :3]
    r_, g_, b_ = c[:, :, 0], c[:, :, 1], c[:, :, 2]
    mx, mn = c.max(2), c.min(2)
    textcol = ((mn > 185) & (mx - mn < 40)) | ((r_ > 190) & (g_ > 190) & (b_ < 90)) |               ((g_ > 180) & (r_ < 90) & (b_ < 90)) | ((r_ > 210) & (g_ > 110) & (g_ < 215) & (b_ < 100)) |               ((b_ > 200) & (g_ > 180) & (r_ < 90))
    xa, xb = g.get("erase_x", [g["speaker_x"] - 4 if has_speaker else 95, W - 2])
    dark = mx < g.get("dark", 90)
    near_dark = np.asarray(Image.fromarray(dark.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0
    cand = textcol & near_dark
    band = np.zeros((H, W), bool)
    full = np.zeros((H, W), bool)  # title and "Next" lines: the whole span of old lettering
    wide = (g["title_y"], g["next_y"])  # title and "Next" lines have wide full-width gaps
    spans = [(max(0, y - 2), min(H, y + 11), xa, 34 if y in wide else g.get("max_gap", 20)) for y in bands]
    spans.append((max(0, g["title_y"] - 3), g["title_y"] + 15, g["title_x"][0] - 6, 34))
    for y0, y1, x0, max_gap in spans:
        # the line's own lettering: the runs of columns with lettering (gaps up to max_gap px) that
        # start within 60 px of the line's left edge; runs further right are portrait detail
        cols = cand[y0:y1].sum(0) >= 1
        x, gap, seg = x0, 0, None
        while x < xb:
            if cols[x]:
                if seg is None:
                    if x > x0 + 60:
                        break
                    seg = x
                gap, last = 0, x
            elif seg is not None:
                gap += 1
                if gap > max_gap:
                    band[y0:y1, seg:min(W, last + 3)] = True
                    if max_gap > 30:
                        full[y0 + 1:y1 - 1, seg - 1:min(W, last + 9)] = True
                    seg = None
            x += 1
        if seg is not None:
            band[y0:y1, seg:min(W, last + 3)] = True
            if max_gap > 30:
                full[y0 + 1:y1 - 1, seg - 1:min(W, last + 9)] = True
    if card.get("next"):  # the old "Next - ..." line sits on the plain bottom strip
        y = g["next_y"]
        full[y - 1:y + 10, g["speaker_x"] - 2:g.get("next_erase_to", 252)] = True
    fill = cand & band
    fm = Image.fromarray(fill.astype(np.uint8) * 255)
    near_fill = np.asarray(fm.filter(ImageFilter.MaxFilter(3))) > 0
    mask = (np.asarray(fm.filter(ImageFilter.MaxFilter(3))) > 0) | (dark & near_fill & band) | full
    inpaint(arr, mask, 2)
    shade_src = np.maximum(mask.astype(np.float32), (layer[:, :, 3] > 25).astype(np.float32))
    sm = Image.fromarray((shade_src * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * g.get("shade_grow", 3) + 1))
    sm = np.asarray(sm.filter(ImageFilter.GaussianBlur(g.get("shade_blur", 3))), np.float32) / 255
    sm = np.clip(sm * 1.3, 0, 1) * g.get("shade", 0.55)
    blurred = np.asarray(Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA").filter(ImageFilter.GaussianBlur(2)), np.float32)
    tint = np.array(g.get("tint", [8, 8, 16]), np.float32)
    arr[:, :, :3] = arr[:, :, :3] * (1 - sm[:, :, None]) + (tint * 0.6 + blurred[:, :, :3] * 0.4) * sm[:, :, None]
    la = layer[:, :, 3:4] / 255
    arr[:, :, :3] = layer[:, :, :3] * la + arr[:, :, :3] * (1 - la)
    return rep


def redraw(path, rows, layout, shared_choice):
    b = src_bytes(path)
    before = gim.decode(b)
    items, spec = items_for(layout, path, rows)
    if items is None:
        return None, before, [{"file": path, "error": "no layout"}]
    if spec.get("keep"):
        return None, before, [{"file": path, "kept": spec["keep"]}]
    arr = np.asarray(before, np.float32).copy()
    W, H = before.size
    report = []
    jobs = []
    for it in items:
        if it.get("keep"):
            report.append({"file": path, "row": "%s:%d" % (rows[it.get("row", 0)]["group"], rows[it.get("row", 0)]["index"]),
                           "kept": it["keep"]})
            continue
        if it.get("tipcard"):  # tip card: erases and draws by itself (tipcard)
            continue
        st = style_of(layout, it, spec, rows[it.get("row", 0)])
        box = it.get("box", spec.get("box", [0, 0, W, H]))
        ebox = it.get("erase_box", box)
        emode = it.get("erase", spec.get("erase", "clear"))
        eopt = it.get("erase_opt", spec.get("erase_opt", {}))
        modes = emode if isinstance(emode, list) else [emode]
        for m_ in modes:  # one mode, or a list of modes applied in turn
            mo, op = (m_["mode"], m_) if isinstance(m_, dict) else (m_, eopt)
            for eb in (ebox if ebox and isinstance(ebox[0], list) else [ebox]):
                erase(arr, eb, mo, op)
        if it.get("no_text"):
            continue
        jobs.append((it, st, box))
    for it in items:
        if it.get("tipcard"):
            for r in tipcard(arr, rows, it, layout, spec):
                report.append(dict(r, file=path, row="%s:%d" % (rows[0]["group"], rows[0]["index"])))
    for it, st, box in jobs:
        texts = text_for(it, rows, spec)
        grp = it.get("share")
        if grp and grp in shared_choice:
            texts = texts[shared_choice[grp]:] if isinstance(shared_choice[grp], int) else [shared_choice[grp]] + texts
        if texts[0] == "" or it.get("blank"):
            report.append({"file": path, "text": "", "box": box})
            continue
        lines, size, xs, over, _ = fit(texts, box, st)
        if "force_size" in it:
            size = it["force_size"]
        draw_text(arr, box, lines, size, xs, st)
        report.append({"file": path, "row": "%s:%d" % (rows[it.get("row", 0)]["group"], rows[it.get("row", 0)]["index"]),
                       "text": "\n".join(lines), "size": size, "xscale": round(xs, 3), "overflow": over,
                       "box": box, "fallback": "\n".join(lines) != (texts[0].upper() if st["caps"] else texts[0])})
    after = Image.fromarray(np.clip(np.round(arr), 0, 255).astype(np.uint8), "RGBA")
    return after, before, report


def thumbnail(src_im, old):
    """Gallery thumbnail: the whole redrawn 480x272 still shrunk to the thumbnail size
    (the originals are made the same way), keeping the old thumbnail's alpha."""
    th = src_im.convert("RGB").resize(old.size, Image.LANCZOS).convert("RGBA")
    th.putalpha(old.getchannel("A"))
    return th


# ---------------------------------------------------------------- shared text

VARIANTS = [  # (regex on the file name, what the variants are)
    (r"^(.*)_([bw])\.gim$", "_b / _w: black and white copies of one label (cursor on / off)"),
    (r"^(.*)_(on|off)\.gim$", "_on / _off"),
    (r"^(menu_0\d)(_light)?\.gim$", "shop menu item: normal / _light (highlighted)"),
    (r"^con_(font|window)_(\d\d)_?(.*)\.gim$", "control config: con_font (grey) / con_window (white on black) with the same label"),
]


def shared_report(by_file, layout):
    """Which textures carry the same English: variant pairs, identical texts, mission
    title cards, thumbnails. Written to <preview>/shared_text.json."""
    import re
    groups = {}
    for path, rows in by_file.items():
        name = os.path.basename(path)
        for rx, what in VARIANTS:
            m = re.match(rx, name)
            if m:
                key = (what, os.path.dirname(path), m.group(1) if "con_" not in rx else m.group(2) + (m.group(3) or "").replace("_", ""))
                groups.setdefault(key, []).append(path)
                break
    variants = [{"kind": k[0], "files": sorted(v), "en": sorted({by_file[f][0]["en"] for f in v})}
                for k, v in sorted(groups.items()) if len(v) > 1]
    same = {}
    for path, rows in by_file.items():
        for r in rows:
            for t in r["en"].split("\n"):
                same.setdefault(t.strip().lower(), set()).add(path)
    same_text = {t: sorted(v) for t, v in sorted(same.items()) if len(v) > 1 and t}
    titles = {p: r[0]["en"] for p, r in by_file.items() if re.search(r"fesrat_m/.*_title\.gim$", p)}
    dup_titles = {}
    for p, t in titles.items():
        dup_titles.setdefault(t, []).append(p)
    return {
        "variant_pairs": variants,
        "on_off_pairs": [v for v in variants if v["kind"].startswith("_on")],
        "same_english": same_text,
        "mission_title_cards": {"count": len(titles), "same_style": "white heavy gothic, 36 px, dark edge (style 'title')",
                                "repeated_titles": {t: sorted(v) for t, v in dup_titles.items() if len(v) > 1}},
        "thumbnails": layout.get("thumbnails", {}),
    }


# ---------------------------------------------------------------- sheets

def contact_sheets(pairs, out, per=None):
    from PIL import ImageDraw as D
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if f.startswith("sheet_") and f.endswith(".png"):
            os.remove(os.path.join(out, f))
    W, MAXH = 1000, 1600
    bg = (92, 92, 104, 255)
    sheet, x, y, rowh, n = None, 0, 0, 0, 0
    names = []

    def flush():
        nonlocal sheet, n
        if sheet is not None:
            p = os.path.join(out, "sheet_%03d.png" % n)
            sheet.crop((0, 0, W, y + rowh + 4)).convert("RGB").save(p)
            names.append(p)
            n += 1
        sheet = None

    for label, before, after in pairs:
        big = max(before.width, before.height)
        sc = 1 if before.width > 240 or before.height > 120 else (2 if before.width > 70 or big > 50 else 3)
        if 2 * before.width * sc + 10 > W:
            sc = 1
        bi = before.resize((before.width * sc, before.height * sc), Image.NEAREST)
        ai = after.resize((after.width * sc, after.height * sc), Image.NEAREST)
        side = bi.width * 2 + 6 <= W
        w = (bi.width * 2 + 8 if side else bi.width + 4)
        h = (bi.height if side else bi.height * 2 + 4) + 14
        w = max(w, min(W, 6 * len(label) + 4))
        if sheet is None:
            sheet, x, y, rowh = Image.new("RGBA", (W, MAXH), bg), 0, 0, 0
        if x + w > W:
            x, y, rowh = 0, y + rowh + 4, 0
        if y + h > MAXH:
            flush()
            sheet, x, y, rowh = Image.new("RGBA", (W, MAXH), bg), 0, 0, 0
        d = D.Draw(sheet)
        d.text((x + 2, y), label, fill=(255, 255, 0))
        sheet.alpha_composite(bi, (x + 2, y + 13))
        if side:
            sheet.alpha_composite(ai, (x + 6 + bi.width, y + 13))
        else:
            sheet.alpha_composite(ai, (x + 2, y + 15 + bi.height))
        x += w + 6
        rowh = max(rowh, h)
    flush()
    return names


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "work/output/redraw/overlay"))
    ap.add_argument("--preview", default=os.path.join(ROOT, "work/ui/redraw_preview"))
    ap.add_argument("--layout", default=os.path.join(ROOT, "work/ui/redraw_layout.json"))
    ap.add_argument("--only", help="only files whose path contains this")
    ap.add_argument("--no-sheets", action="store_true")
    ap.add_argument("--no-write", action="store_true", help="previews only, no GIMs")
    ap.add_argument("--version", default="dev", help="text for {version} (tools/build_iso.py passes its own)")
    a = ap.parse_args()
    global VERSION
    VERSION = a.version
    layout = load_layout(a.layout)
    by_file = load_rows()
    shared = share_choices(layout, by_file)
    pairs, report, done, errs, held = [], [], {}, [], {}
    files = sorted(by_file)
    # thumbnails last: they shrink redrawn stills
    thumbs = layout.get("thumbnails", {})
    for path in files:
        if a.only and a.only not in path:
            continue
        if path in thumbs:
            continue
        after, before, rep = redraw(path, by_file[path], layout, shared)
        report += rep
        if after is None:
            errs += [r for r in rep if "error" in r]
            if any("kept" in r for r in rep):
                pairs.append((path.replace("data/", "") + " (kept)", before, before))
            continue
        spec = items_for(layout, path, by_file[path])[1]
        if spec.get("hold"):
            held[path] = spec["hold"]
            report.append({"file": path, "held": spec["hold"]})
        done[path] = after
        pairs.append((path.replace("data/", "") + (" (held)" if spec.get("hold") else ""), before, after))
    for path, src in thumbs.items():
        if src not in by_file or (a.only and a.only not in path and a.only not in src):
            continue
        b = src_bytes(path)
        before = gim.decode(b)
        after = done.get(src)
        if after is None:
            after = redraw(src, by_file[src], layout, shared)[0]
        if after is None:  # the still is kept as it is, so is its thumbnail
            pairs.append((path.replace("data/", "") + " (kept)", before, before))
            report.append({"file": path, "kept": "thumbnail of a kept still"})
            continue
        th = thumbnail(after, before)
        done[path] = th
        pairs.append((path.replace("data/", "") + " (from %s)" % os.path.basename(src), before, th))
        report.append({"file": path, "thumbnail_of": src})
    # encode
    encoded = {}
    if not a.no_write:
        for path, im in done.items():
            if path in held:
                continue
            nb = gim.encode(src_bytes(path), im)
            encoded[path] = nb
            write_gim(a.out, path, nb)
    # quantized look in the previews
    qpairs = []
    for label, before, after in pairs:
        path = "data/" + label.split(" (")[0]
        if path in encoded:
            after = gim.decode(encoded[path])
        qpairs.append((label, before, after))
    os.makedirs(a.preview, exist_ok=True)
    if not a.only:
        json.dump(report, open(os.path.join(a.preview, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(shared_report(by_file, layout), open(os.path.join(a.preview, "shared_text.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    if not a.no_sheets:
        names = contact_sheets(qpairs, a.preview if not a.only else os.path.join(a.preview, "_only"))
        print("sheets:", len(names))
    over = [r for r in report if r.get("overflow")]
    fb = [r for r in report if r.get("fallback")]
    print("textures %d (held %d, kept as art %d), items %d, fallbacks %d, overflow %d, no layout %d" % (
        len(done), len(held), len([r for r in report if "kept" in r]), len([r for r in report if "text" in r]),
        len(fb), len(over), len(errs)))
    for p_, why in held.items():
        print("  HELD (not written)", p_, "-", why)
    for r in over:
        print("  OVERFLOW", r["file"], repr(r["text"]))
    for e in errs[:40]:
        print("  NO LAYOUT", e["file"])


if __name__ == "__main__":
    main()
