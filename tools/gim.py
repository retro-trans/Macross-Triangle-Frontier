"""Decode PSP GIM textures (MIG.00.1PSP) to PNG, and encode them back.

Usage:
  python tools/gim.py info <file.gim>
  python tools/gim.py png <file.gim> <out.png>
  python tools/gim.py dir <folder> <outdir> [--sheet]   every .gim under folder -> PNG
                                                         (--sheet also writes contact sheets)
  python tools/gim.py encode <orig.gim> <in.png> <out.gim>
                         re-encode orig.gim with the pixels of in.png (same size)
  python tools/gim.py roundtrip <folder>   decode + encode every .gim, report any byte diff
Supports RGBA5650/5551/4444/8888 and INDEX4/8 with a palette, normal or swizzled
pixel order (16-byte x 8-row blocks). Only the first image level/frame is decoded.

Encoding writes into a copy of the original file: same format, pixel order,
palette format and palette size; padding and headers are untouched. An indexed
texture keeps its own palette when every colour of the new image is in it
(so decode -> encode is byte-identical); otherwise the image is reduced to the
palette size with a k-means seeded by the old palette (docs/formats.md).
A .gfp (cockpit portrait pack) holds several GIMs; `dir` also extracts those. RAIC/RAIB-packed files
(Triangle Frontier plain files) are unpacked first (unpack()).

Block layout: 16-byte file header, then blocks with a 16-byte header
  u16 id, u16 unk, u32 block size, u32 next (offset to first child / next), u32 data offset
id 2 = root, 3 = picture, 4 = image, 5 = palette, 0xFF = file info.
Image/palette data: u16 hdr_len, u16 unk, u16 format, u16 order, u16 width, u16 height,
u16 bpp_align, u16 pitch_align, u16 height_align, ..., u32 @0x1C pixels start (from data start).
"""
import os, struct, sys
from PIL import Image

FMT_BPP = {0: 16, 1: 16, 2: 16, 3: 32, 4: 4, 5: 8, 6: 16, 7: 32}


def _blocks(b, off, end, out):
    while off + 16 <= end:
        bid, _, size, nxt, doff = struct.unpack_from("<HHIII", b, off)
        if size == 0:
            break
        out.append((bid, off, size, doff))
        if bid in (2, 3):  # containers: descend
            _blocks(b, off + doff, off + size, out)
        off += size


def parse(b, base=0):
    if b[base:base + 11] != b"MIG.00.1PSP":
        raise ValueError("not a GIM")
    blocks = []
    _blocks(b, base + 16, len(b), blocks)
    img = pal = None
    for bid, off, size, doff in blocks:
        if bid == 4 and img is None:
            img = off + doff
        elif bid == 5 and pal is None:
            pal = off + doff
    if img is None:
        raise ValueError("no image block")
    return img, pal


def _read_plane(b, d):
    fmt, order, w, h = struct.unpack_from("<HHHH", b, d + 4)
    start = struct.unpack_from("<I", b, d + 0x1C)[0]
    bpp = FMT_BPP[fmt]
    pitch = (w * bpp + 7) // 8
    pitch = (pitch + 15) & ~15
    hh = (h + 7) & ~7 if order else h
    raw = bytearray(b[d + start: d + start + pitch * hh])
    if len(raw) < pitch * hh:
        raw += bytes(pitch * hh - len(raw))
    if order:  # unswizzle
        out = bytearray(len(raw))
        bw = pitch // 16
        i = 0
        for by in range(hh // 8):
            for bx in range(bw):
                for y in range(8):
                    dst = (by * 8 + y) * pitch + bx * 16
                    out[dst:dst + 16] = raw[i:i + 16]
                    i += 16
        raw = out
    return fmt, w, h, pitch, bytes(raw)


def _colors(fmt, raw, n):
    cols = []
    if fmt == 3:
        for i in range(n):
            r, g, bb, a = raw[i * 4:i * 4 + 4]
            cols.append((r, g, bb, a))
        return cols
    for i in range(n):
        v = struct.unpack_from("<H", raw, i * 2)[0]
        if fmt == 0:
            cols.append(((v & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, ((v >> 11) & 31) * 255 // 31, 255))
        elif fmt == 1:
            cols.append(((v & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, ((v >> 10) & 31) * 255 // 31, 255 if v >> 15 else 0))
        else:
            cols.append(((v & 15) * 17, ((v >> 4) & 15) * 17, ((v >> 8) & 15) * 17, (v >> 12) * 17))
    return cols


def decode(b, base=0):
    img, pal = parse(b, base)
    fmt, w, h, pitch, raw = _read_plane(b, img)
    im = Image.new("RGBA", (w, h))
    px = im.load()
    if fmt in (4, 5):
        pfmt, pw, _, _, praw = _read_plane(b, pal)
        palette = _colors(pfmt, praw, pw)
        for y in range(h):
            row = raw[y * pitch:(y + 1) * pitch]
            for x in range(w):
                if fmt == 4:
                    v = row[x >> 1]
                    idx = (v >> 4) if x & 1 else (v & 15)
                else:
                    idx = row[x]
                px[x, y] = palette[idx] if idx < len(palette) else (0, 0, 0, 0)
    elif fmt in (0, 1, 2, 3):
        bpp = FMT_BPP[fmt] // 8
        for y in range(h):
            cols = _colors(fmt, raw[y * pitch:y * pitch + w * bpp], w)
            for x in range(w):
                px[x, y] = cols[x]
    else:
        raise ValueError("unsupported format %d" % fmt)
    return im


def _swizzle(raw, pitch, hh):
    out = bytearray(len(raw))
    i = 0
    for by in range(hh // 8):
        for bx in range(pitch // 16):
            for y in range(8):
                src = (by * 8 + y) * pitch + bx * 16
                out[i:i + 16] = raw[src:src + 16]
                i += 16
    return bytes(out)


def _write_plane(b, d, raw):
    """Write an unswizzled plane (as _read_plane returns it) back into bytearray b."""
    order = struct.unpack_from("<H", b, d + 6)[0]
    fmt, w, h, pitch, old = _read_plane(b, d)
    start = struct.unpack_from("<I", b, d + 0x1C)[0]
    hh = len(old) // pitch
    data = _swizzle(raw, pitch, hh) if order else raw
    end = min(len(b), d + start + len(data))
    b[d + start:end] = data[:end - d - start]


def _pack_colors(fmt, cols):
    if fmt == 3:
        return b"".join(bytes(c) for c in cols)
    out = bytearray()
    for r, g, bb, a in cols:
        if fmt == 0:
            v = round(r * 31 / 255) | round(g * 63 / 255) << 5 | round(bb * 31 / 255) << 11
        elif fmt == 1:
            v = round(r * 31 / 255) | round(g * 31 / 255) << 5 | round(bb * 31 / 255) << 10 | (a >= 128) << 15
        else:
            v = round(r / 17) | round(g / 17) << 4 | round(bb / 17) << 8 | round(a / 17) << 12
        out += struct.pack("<H", v)
    return bytes(out)


def read_indexed(b, base=0):
    """(fmt, w, h, indices as a w*h bytearray, palette as a list of RGBA tuples)."""
    img, pal = parse(b, base)
    fmt, w, h, pitch, raw = _read_plane(b, img)
    if fmt not in (4, 5):
        raise ValueError("format %d has no palette" % fmt)
    pfmt, pw, _, _, praw = _read_plane(b, pal)
    idx = bytearray(w * h)
    for y in range(h):
        row = raw[y * pitch:(y + 1) * pitch]
        if fmt == 5:
            idx[y * w:(y + 1) * w] = row[:w]
        else:
            for x in range(w):
                v = row[x >> 1]
                idx[y * w + x] = (v >> 4) if x & 1 else (v & 15)
    return fmt, w, h, idx, _colors(pfmt, praw, pw)


def encode_indexed(b, idx, palette, base=0):
    """Return a copy of GIM b with new pixel indices and palette, in the same format,
    pixel order and palette layout. Bytes outside the w x h area (pitch and height
    padding, headers, file info) are kept as they are."""
    out = bytearray(b)
    img, pal = parse(b, base)
    fmt, w, h, pitch, raw = _read_plane(b, img)
    pfmt, pw, _, _, praw = _read_plane(b, pal)
    if len(palette) > pw:
        raise ValueError("palette has %d colours, the texture holds %d" % (len(palette), pw))
    raw = bytearray(raw)
    for y in range(h):
        r = idx[y * w:(y + 1) * w]
        if fmt == 5:
            raw[y * pitch:y * pitch + w] = r
        else:
            for x in range(0, w, 2):
                lo = r[x]
                hi = r[x + 1] if x + 1 < w else raw[y * pitch + (x >> 1)] >> 4
                raw[y * pitch + (x >> 1)] = (lo & 15) | (hi & 15) << 4
    _write_plane(out, img, bytes(raw))
    pal_bytes = bytearray(praw)
    packed = _pack_colors(pfmt, list(palette))
    pal_bytes[:len(packed)] = packed
    _write_plane(out, pal, bytes(pal_bytes))
    return bytes(out)


def _nearest(cols, pal):
    """Index of the nearest palette colour for each RGBA row of cols (numpy arrays).
    Colour distance is weighted by alpha so fully transparent colours all match."""
    import numpy as np
    c = cols.astype(np.float32)
    p = np.asarray(pal, np.float32)
    ca, pa = c[:, 3:4] / 255, p[:, 3] / 255
    best = np.zeros(len(c), np.int64)
    bestd = np.full(len(c), np.inf, np.float32)
    for k in range(len(p)):
        d = (((c[:, :3] * ca - p[k, :3] * pa[k]) ** 2).sum(1) + 2.0 * (c[:, 3] - p[k, 3]) ** 2)
        m = d < bestd
        best[m], bestd[m] = k, d[m]
    return best, bestd


def quantize(im, n, ref_idx=None, ref_pal=None, iters=12):
    """Reduce an RGBA image to at most n colours.

    When every colour is already in ref_pal, ref_pal is kept and each pixel keeps its
    ref_idx entry where that still has the right colour (so an unchanged image encodes
    to the same bytes). Otherwise a weighted k-means over the image's distinct colours
    picks the palette, seeded with ref_pal so the art keeps its own colours."""
    import numpy as np
    a = np.asarray(im.convert("RGBA"), np.uint8).reshape(-1, 4)
    if ref_pal is not None:
        rp = np.asarray(ref_pal, np.uint8)
        lut = {}
        for k in range(len(rp) - 1, -1, -1):
            lut[tuple(rp[k])] = k
        ri = np.frombuffer(bytes(ref_idx), np.uint8) if ref_idx is not None else None
        cols, inv = np.unique(a, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        if all(tuple(c) in lut for c in cols):
            first = np.array([lut[tuple(c)] for c in cols], np.int64)[inv]
            if ri is not None:
                keep = (ri < len(rp))
                keep[keep] = (rp[ri[keep]] == a[keep]).all(1)
                first[keep] = ri[keep]
            return bytearray(first.astype(np.uint8).tobytes()), [tuple(int(v) for v in c) for c in rp]
    # Fully transparent pixels get one exact palette entry of their own (the old
    # palette's transparent colour, at its old index), so k-means can never turn
    # them into a faint alpha 1 colour; the other colours share the rest.
    a = a.copy()
    clear = a[:, 3] == 0
    tcol, tk = (0, 0, 0, 0), 0
    for k, c in enumerate(ref_pal or []):
        if c[3] == 0:
            tcol, tk = tuple(c), k
            break
    a[clear] = tcol
    cols, inv, cnt = np.unique(a, axis=0, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    if len(cols) <= n:
        pal = [tuple(int(v) for v in c) for c in cols]
        idx, _ = _nearest(cols, pal)
        idx[(cols[:, 3] == 0)] = [pal.index(tuple(int(v) for v in c)) for c in cols[cols[:, 3] == 0]]
        return bytearray(idx[inv].astype(np.uint8).tobytes()), pal
    has_clear = bool(clear.any())
    opaque = cols[:, 3] > 0
    oc, ow = cols[opaque], cnt[opaque].astype(np.float32)
    m_ = n - 1 if has_clear else n
    seed = [tuple(c) for k, c in enumerate(ref_pal or []) if not (has_clear and k == tk)][:m_]
    if len(seed) < m_:  # add the most common remaining colours
        for i in np.argsort(-ow):
            if len(seed) >= m_:
                break
            c = tuple(int(v) for v in oc[i])
            if c not in seed:
                seed.append(c)
    while len(seed) < m_:
        seed.append(seed[-1] if seed else (0, 0, 0, 255))
    cent = np.asarray(seed, np.float32)
    for _ in range(iters):
        lab, _ = _nearest(oc, cent)
        for k in range(m_):
            m = lab == k
            if m.any():
                cent[k] = (oc[m].astype(np.float32) * ow[m, None]).sum(0) / ow[m].sum()
    pal = [tuple(int(round(v)) for v in c) for c in cent]
    if has_clear:
        pal.insert(min(tk, len(pal)), tcol)
    lab, _ = _nearest(cols, pal)
    if has_clear:
        lab[cols[:, 3] == 0] = pal.index(tcol)
    return bytearray(lab[inv].astype(np.uint8).tobytes()), pal


def encode(b, im, base=0):
    """Re-encode GIM b with the pixels of RGBA image im (same size), keeping the
    texture's format, swizzle and palette size. Indexed textures are quantized to
    their palette size (see quantize)."""
    img, pal = parse(b, base)
    fmt, w, h, pitch, raw = _read_plane(b, img)
    if im.size != (w, h):
        raise ValueError("image is %dx%d, texture is %dx%d" % (im.size + (w, h)))
    if fmt in (4, 5):
        _, _, _, ref_idx, ref_pal = read_indexed(b, base)
        idx, palette = quantize(im, len(ref_pal), ref_idx, ref_pal)
        return encode_indexed(b, idx, palette, base)
    if fmt not in (0, 1, 2, 3):
        raise ValueError("unsupported format %d" % fmt)
    out = bytearray(b)
    raw = bytearray(raw)
    px = list(im.convert("RGBA").getdata())
    bpp = FMT_BPP[fmt] // 8
    for y in range(h):
        raw[y * pitch:y * pitch + w * bpp] = _pack_colors(fmt, px[y * w:(y + 1) * w])
    _write_plane(out, img, bytes(raw))
    return bytes(out)


def unpack(b):
    """A RAIC/RAIB-packed file (Triangle Frontier plain files, tools/muf_lzss.py) decoded; others as they are."""
    if b[:4] in (b"\x20\x33\x3b\x31", b"\x20\x33\x3b\x30"):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import muf_lzss
        try:
            return muf_lzss.decode(b)
        except ValueError:  # one map texture has an odd RAIB header; left as it is
            return b
    return b


def gims_in(path):
    b = unpack(open(path, "rb").read())
    if path.endswith(".gim"):
        return [(0, b)]
    out, i = [], 0
    while True:
        i = b.find(b"MIG.00.1PSP", i)
        if i < 0:
            return out
        out.append((i, b))
        i += 16


def main():
    cmd = sys.argv[1]
    if cmd == "info":
        b = unpack(open(sys.argv[2], "rb").read())
        img, pal = parse(b)
        fmt, order, w, h = struct.unpack_from("<HHHH", b, img + 4)
        print("format %d order %d %dx%d palette %s" % (fmt, order, w, h, pal is not None))
    elif cmd == "png":
        decode(unpack(open(sys.argv[2], "rb").read())).save(sys.argv[3])
    elif cmd == "encode":
        b = open(sys.argv[2], "rb").read()
        open(sys.argv[4], "wb").write(encode(b, Image.open(sys.argv[3])))
    elif cmd == "roundtrip":
        n = bad = 0
        for dp, _, fs in os.walk(sys.argv[2]):
            for f in sorted(fs):
                if not f.endswith(".gim"):
                    continue
                p = os.path.join(dp, f)
                b = open(p, "rb").read()
                try:
                    im = decode(b)
                except Exception:
                    continue
                n += 1
                if encode(b, im) != b:
                    bad += 1
                    print("DIFF", p)
        print("round trip: %d textures, %d differ" % (n, bad))
    elif cmd == "dir":
        src, dst = sys.argv[2], sys.argv[3]
        os.makedirs(dst, exist_ok=True)
        done, bad, ims = 0, 0, []
        for dp, _, fs in os.walk(src):
            for f in sorted(fs):
                if not f.endswith((".gim", ".gfp")):
                    continue
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, src).replace(os.sep, "__")
                for k, (base, b) in enumerate(gims_in(p)):
                    try:
                        im = decode(b, base)
                        name = rel + ("" if f.endswith(".gim") else "_%02d" % k) + ".png"
                        im.save(os.path.join(dst, name))
                        ims.append((name, im))
                        done += 1
                    except Exception as e:
                        bad += 1
        print("decoded %d, failed %d" % (done, bad))
        if "--sheet" in sys.argv:
            from PIL import ImageDraw
            per, cell = 24, 256
            for s in range(0, len(ims), per):
                sheet = Image.new("RGB", (cell * 6, (cell + 14) * 4), (40, 40, 40))
                d = ImageDraw.Draw(sheet)
                for i, (n, im) in enumerate(ims[s:s + per]):
                    t = im.copy()
                    t.thumbnail((cell, cell))
                    x, y = (i % 6) * cell, (i // 6) * (cell + 14)
                    sheet.paste(t, (x, y + 14), t)
                    d.text((x + 2, y), n[-40:], fill=(255, 255, 0))
                sheet.save(os.path.join(dst, "_sheet_%03d.png" % (s // per)))


if __name__ == "__main__":
    main()
