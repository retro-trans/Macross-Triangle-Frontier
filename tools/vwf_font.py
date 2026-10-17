"""Variable-width English glyphs for the game fonts of Macross Triangle Frontier.

Two fonts get the English glyphs (docs/vwf.md):
  gpsp3_font14.fnt      14x14 cells, 32 per row (448 px wide): menus, briefings, most text
  mpsp3_font16_slg.fnt  16x16 cells, 24 per row (384 px wide): the campus mode

Glyphs are drawn at 4x (a 56 or 64 px cell) from an outline font, then
box-filtered down to the game's cell and quantised to its four alpha levels
(2 bpp). For each glyph the horizontal sub-pixel phase (0-3 at 4x) that gives
the sharpest result is chosen, so vertical stems land on whole pixels where
the outline allows it.

Font file layout: a 4 bpp atlas of square cells. Every nibble holds two 2 bpp
glyphs: bits 0-1 = even glyph number, bits 2-3 = odd glyph number;
cell = glyph >> 1.

Usage (normally called from tools/vwf_build.py):
  python tools/vwf_font.py --preview out.png [--cell 16]
"""

import argparse
import json
import os
import sys
from collections import namedtuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCALE = 4
FIRST, LAST = 0x20, 0x7F  # ASCII range covered by the width table (96 codes)
# alpha of the four 2 bpp levels, from the font descriptors in the EBOOT
LEVELS = np.array([0x00, 0x5C, 0xC2, 0xFE]) / 255.0

DEFAULT_FONT = r"C:\Windows\Fonts\NotoSansJP-VF.ttf"  # SIL Open Font License 1.1
DEFAULT_WEIGHT = 600
# The menu CSVs have no quoting, so a cell cannot hold an ASCII comma or double
# quote. No game string uses '|' or '`' (docs/vwf.md), so their slots draw a
# comma and a double quote instead; tools/insert_text.py writes them in CSVs.
ALIASES = {"|": ",", "`": '"'}

# cell: px; atlas_w: px; cap_top: first row of capitals; baseline: first row below
# the baseline; space: advance of ' ' in px. Capitals sit on rows cap_top..baseline-1.
Spec = namedtuple("Spec", "name cell atlas_w cap_top baseline space")
SPEC14 = Spec("gpsp3_font14.fnt", 14, 448, 1, 11, 4)       # caps 10 px (as Ultimate / Ace Frontier)
SPEC16 = Spec("mpsp3_font16_slg.fnt", 16, 384, 1, 12, 5)   # caps 11 px, '(' reaches row 0
SPECS = {14: SPEC14, 16: SPEC16}

# Ultimate / Ace Frontier names (the 14 px font)
CELL = SPEC14.cell
BIG = CELL * SCALE
ATLAS_W = SPEC14.atlas_w
HD_PER_ROW = ATLAS_W // BIG   # 8 cells of 56 px in a 448 px row
HD_ROWS_PX = 512              # a 4x page is bound as a 512x512 texture (bufw = atlas width)


def big(spec):
    return spec.cell * SCALE


def hd_per_row(spec):
    return spec.atlas_w // big(spec)


def load_font(path, weight, size, index=0):
    f = ImageFont.truetype(path, size, index=index)
    try:
        axes = f.get_variation_axes()
        f.set_variation_by_axes([weight if a.get("name", b"") in (b"Weight", "Weight") else a["default"]
                                 for a in axes])
    except (OSError, AttributeError):
        pass
    return f


def fit_size(path, weight, index=0, spec=SPEC14):
    """Pick the 4x pixel size whose capital 'H' is (baseline - cap_top) * 4 tall."""
    want = (spec.baseline - spec.cap_top) * SCALE
    best = None
    for size in range(30, 100):
        f = load_font(path, weight, size, index)
        top, bottom = f.getbbox("H", anchor="ls")[1], f.getbbox("H", anchor="ls")[3]
        h = bottom - top
        if best is None or abs(h - want) < abs(best[1] - want):
            best = (size, h)
    return best[0]


PAD = 2  # px of room left of the pen, for glyphs with a negative left bearing


def render_char(font, ch, phase, spec=SPEC14):
    """Coverage of `ch` at 4x with the pen at x = PAD*4 + phase, baseline fixed."""
    b = big(spec)
    img = Image.new("L", (b + 16 + PAD * SCALE, b), 0)
    d = ImageDraw.Draw(img)
    d.text((PAD * SCALE + phase, spec.baseline * SCALE), ch, font=font, fill=255, anchor="ls")
    return np.asarray(img, dtype=np.float64) / 255.0


def downsample(cov):
    h, w = cov.shape
    w4 = w // SCALE * SCALE
    return cov[:, :w4].reshape(h // SCALE, SCALE, w4 // SCALE, SCALE).mean(axis=(1, 3))


def quantise(a):
    # nearest alpha level, with a slight boost so 1 px strokes keep full weight
    a = np.clip(a * 1.15, 0, 1)
    return np.abs(a[..., None] - LEVELS[None, None, :]).argmin(axis=-1).astype(np.uint8)


def build_glyph(font, ch, with_pos=False, spec=SPEC14):
    """Return (2 bpp cell x cell array, advance in px[, (phase, shift)])."""
    cell = spec.cell
    if ch == " ":
        z = np.zeros((cell, cell), np.uint8)
        return (z, spec.space, (0, 0)) if with_pos else (z, spec.space)
    best = None
    for phase in range(SCALE):
        small = downsample(render_char(font, ch, phase, spec))
        cols = np.where(small.max(axis=0) > 0.05)[0]
        if cols.size == 0:
            continue
        # the cell starts at the pen (keeps the left bearing), or further left
        # when the ink overhangs the pen (j, y...)
        shift = min(int(cols.min()), PAD)
        small = small[:, shift:]
        q = quantise(small)
        # sharpness: favour pixels that are fully on or off
        a = LEVELS[q]
        score = (a * a).sum() / max(a.sum(), 1e-6)
        if best is None or score > best[0]:
            best = (score, q, phase, shift)
    _, q, phase, shift = best
    cols = np.where(q.max(axis=0) > 0)[0]
    ink = int(cols.max()) + 1 if cols.size else 0
    if ink > cell:
        print("warning: %r is %d px wide, clipped to %d" % (ch, ink, cell), file=sys.stderr)
    out = np.zeros((cell, cell), np.uint8)
    out[:, :min(cell, q.shape[1])] = q[:, :cell]
    # advance from the font's own metrics (keeps the designed side bearings),
    # measured from the left edge of the ink we kept
    advance = int(round((PAD * SCALE + phase + font.getlength(ch)) / SCALE)) - shift
    advance = max(1, min(cell, advance))
    return (out, advance, (phase, shift)) if with_pos else (out, advance)


def build_hd_glyph(font, ch, phase, shift, advance, spec=SPEC14):
    """The same glyph at 4x (a 4*cell square 2 bpp cell), with the pen and cell origin
    of the native glyph. The game places glyphs on whole native pixels with the rounded
    advance, so the rounding error (up to half a native pixel = 2 px at 4x) would all
    fall to the right of the letter. Half of it is moved to the left instead, which
    keeps the spacing even at 4x."""
    b = big(spec)
    if ch == " ":
        return np.zeros((b, b), np.uint8)
    true4 = PAD * SCALE + phase + font.getlength(ch) - shift * SCALE   # unrounded advance at 4x
    d = int(round((advance * SCALE - true4) / 2))
    cov = render_char(font, ch, phase, spec)
    cov = np.roll(cov, d, axis=1)
    cov = cov[:, shift * SCALE:shift * SCALE + b]
    out = np.zeros((b, b), np.uint8)
    q = np.abs(cov[..., None] - LEVELS[None, None, :]).argmin(axis=-1).astype(np.uint8)
    out[:, :q.shape[1]] = q
    return out


def build_set(path=DEFAULT_FONT, weight=DEFAULT_WEIGHT, index=0, hd=False, spec=SPEC14):
    """Glyphs and advances for ASCII 0x20-0x7F. With hd=True also the 4x cells."""
    size = fit_size(path, weight, index, spec)
    font = load_font(path, weight, size, index)
    glyphs, widths, hd_glyphs = [], [], []
    for c in range(FIRST, LAST + 1):
        ch = chr(c) if c < 0x7F else "\u2026"  # 0x7F (DEL) slot holds an ellipsis
        ch = ALIASES.get(ch, ch)
        g, w, (phase, shift) = build_glyph(font, ch, with_pos=True, spec=spec)
        glyphs.append(g)
        widths.append(w)
        if hd:
            hd_glyphs.append(build_hd_glyph(font, ch, phase, shift, w, spec))
    info = {"font": os.path.basename(path), "index": index, "weight": weight, "size_4x": size,
            "cell": spec.cell}
    return (glyphs, widths, info, hd_glyphs) if hd else (glyphs, widths, info)


# ------------------------------------------------------------- 4x page

def hd_page(hd_glyphs, spec=SPEC14):
    """4 bpp page (atlas width x 512 rows) with the main atlas's two-layer packing:
    local glyph L sits in cell L >> 1, in bits 0-1 for even L and bits 2-3 for odd L."""
    b, per_row = big(spec), hd_per_row(spec)
    img = np.zeros((HD_ROWS_PX, spec.atlas_w), np.uint8)
    for L, g in enumerate(hd_glyphs):
        r, c = divmod(L >> 1, per_row)
        ys, xs = slice(r * b, r * b + b), slice(c * b, c * b + b)
        img[ys, xs] |= (g << 2) if L & 1 else g
    return write_atlas(img)


def hd_preview(path, hd_glyphs, widths, samples, spec=SPEC14):
    """Sample lines drawn from the 4x cells at 4x advances (what PPSSPP shows at 4x)."""
    b = big(spec)
    rows = []
    for s in samples:
        total = sum(widths[ord(c) - FIRST] for c in s) * SCALE
        canvas = np.zeros((b, total + b), np.float64)
        x = 0
        for c in s:
            a = LEVELS[hd_glyphs[ord(c) - FIRST]]
            canvas[:, x:x + b] = np.maximum(canvas[:, x:x + b], a)
            x += widths[ord(c) - FIRST] * SCALE
        rows.append(canvas[:, :x])
    w = max(r.shape[1] for r in rows) + 32
    img = np.zeros((len(rows) * (b + 16) + 16, w, 3), np.float64)
    img[:] = (0.10, 0.14, 0.22)
    for i, r in enumerate(rows):
        y = 16 + i * (b + 16)
        a = r[:, :, None]
        img[y:y + b, 16:16 + r.shape[1]] = img[y:y + b, 16:16 + r.shape[1]] * (1 - a) + a
    Image.fromarray((img * 255).astype(np.uint8)).save(path)


# ------------------------------------------------------------- atlas access

def read_atlas(data, spec=SPEC14):
    d = np.frombuffer(data, np.uint8)
    px = np.empty(d.size * 2, np.uint8)
    px[0::2] = d & 15
    px[1::2] = d >> 4
    return px.reshape(-1, spec.atlas_w)


def write_atlas(img):
    px = img.reshape(-1)
    return ((px[1::2] << 4) | px[0::2]).astype(np.uint8).tobytes()


def cell_slice(g, spec=SPEC14):
    cell = g >> 1
    r, c = divmod(cell, spec.atlas_w // spec.cell)
    n = spec.cell
    return slice(r * n, r * n + n), slice(c * n, c * n + n)


def get_glyph(img, g, spec=SPEC14):
    ys, xs = cell_slice(g, spec)
    sub = img[ys, xs]
    return (sub >> 2) & 3 if g & 1 else sub & 3


def put_glyph(img, g, a, spec=SPEC14):
    ys, xs = cell_slice(g, spec)
    sub = img[ys, xs]
    if g & 1:
        img[ys, xs] = (sub & 3) | (a << 2)
    else:
        img[ys, xs] = (sub & 12) | a


# ------------------------------------------------------------- preview

def render_line(text, glyphs, widths, spec=SPEC14):
    """Lay out `text` like the patched game: advance = width table."""
    x = 0
    n = spec.cell
    total = sum(widths[ord(c) - FIRST] for c in text)
    canvas = np.zeros((n, total + n), np.float64)
    for c in text:
        g = glyphs[ord(c) - FIRST]
        a = LEVELS[g]
        canvas[:, x:x + n] = np.maximum(canvas[:, x:x + n], a)
        x += widths[ord(c) - FIRST]
    return canvas[:, :x]


def preview(path, glyphs, widths, samples, zoom=3, spec=SPEC14):
    n = spec.cell
    rows = []
    for s in samples:
        line = render_line(s, glyphs, widths, spec)
        rows.append(line)
    w = max(r.shape[1] for r in rows) + 8
    img = np.zeros((len(rows) * (n + 4) + 4, w, 3), np.float64)
    img[:] = (0.10, 0.14, 0.22)  # dark blue, like the game's windows
    for i, r in enumerate(rows):
        y = 4 + i * (n + 4)
        a = r[:, :, None]
        img[y:y + n, 4:4 + r.shape[1]] = img[y:y + n, 4:4 + r.shape[1]] * (1 - a) + a
    out = Image.fromarray((img * 255).astype(np.uint8))
    out.resize((out.width * zoom, out.height * zoom), Image.NEAREST).save(path)


SAMPLES = [
    "The quick brown fox jumps over the lazy dog.",
    "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG!",
    "Alto Saotome, Sheryl Nome, Ranka Lee, Klan Klang",
    "VF-25F Messiah (Alto)  YF-29 Durandal (Alto)",
    "Destroy the enemy forces. Time: 03:45 / 100%",
    "\"Don't you know? Ranka Lee's song's coming!\"",
    "0123456789 +-*/=<>?@#$%^_[]{}|~`;:,.'\u2026",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--font", default=DEFAULT_FONT)
    ap.add_argument("--weight", type=int, default=DEFAULT_WEIGHT)
    ap.add_argument("--index", type=int, default=0, help="face index in a .ttc collection")
    ap.add_argument("--cell", type=int, default=14, choices=sorted(SPECS), help="game font cell size")
    ap.add_argument("--preview", help="write a preview PNG")
    ap.add_argument("--hd-preview", help="write a preview PNG of the 4x cells")
    ap.add_argument("--json", help="write the width table as JSON")
    args = ap.parse_args()
    spec = SPECS[args.cell]
    glyphs, widths, info, hd = build_set(args.font, args.weight, args.index, hd=True, spec=spec)
    print(info, "widths:", widths)
    samples = [s.replace("\u2026", chr(0x7F)) for s in SAMPLES]
    if args.preview:
        preview(args.preview, glyphs, widths, samples, spec=spec)
    if args.hd_preview:
        hd_preview(args.hd_preview, hd, widths, samples, spec=spec)
    if args.json:
        json.dump({"info": info, "widths": widths}, open(args.json, "w"), indent=1)


if __name__ == "__main__":
    main()
