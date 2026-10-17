"""Rebuild a patched ISO in the original disc layout (release images).

Usage:
  python tools/relayout_iso.py <original.iso> <built.iso> <out.iso> [--write]

tools/iso_patch.py appends every file that outgrew its sectors at the end of the
image, which leaves the old copy behind. With the big archives (macross.dat
680 MB, fileset.dat 292 MB) that nearly doubles the ISO and puts the new data
far from the original bytes, so an xdelta patch cannot match it.

This tool writes the files in their original order instead. Each file takes the
built ISO's bytes and its original slot. A file that no longer fits pushes the
files after it back by whole 16-sector (32 KB) blocks, the disc's own
alignment. Files that are not moved keep their sector, the gaps stay zero, and
the image grows only by what the files grew. Directory records and the volume
size are rewritten. The directories and path tables are before the first file,
so they do not move. The game opens files by path (no sce_lbn access), so moved
files load as before.

Without --write it prints the plan. With --write it builds <out.iso> and then
checks that every file in it is byte-identical to the built ISO.
"""

import hashlib
import os
import struct
import sys

SECTOR = 2048
ALIGN = 16


def both32(v):
    return struct.pack("<I", v) + struct.pack(">I", v)


def files(f):
    """{path: (record offset, extent, size)} for every file, plus directory extents."""
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    if pvd[1:6] != b"CD001":
        raise ValueError("not an ISO 9660 image")
    out, dirs = {}, []

    def walk(ext, size, prefix):
        dirs.append(ext)
        f.seek(ext * SECTOR)
        data = f.read(size)
        pos = 0
        while pos < len(data):
            ln = data[pos]
            if ln == 0:
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            e, s = struct.unpack_from("<I", data, pos + 2)[0], struct.unpack_from("<I", data, pos + 10)[0]
            nl = data[pos + 32]
            name = data[pos + 33:pos + 33 + nl]
            if name not in (b"\x00", b"\x01"):
                path = prefix + name.decode("ascii").split(";")[0]
                if data[pos + 25] & 2:
                    walk(e, s, path + "/")
                else:
                    out[path] = (ext * SECTOR + pos, e, s)
            pos += ln

    walk(struct.unpack_from("<I", pvd, 158)[0], struct.unpack_from("<I", pvd, 166)[0], "")
    return out, max(dirs), struct.unpack_from("<I", pvd, 80)[0]


def sectors(n):
    return (n + SECTOR - 1) // SECTOR


def plan(orig, built):
    """List of (path, new extent, size in built ISO) in original order, and total sectors."""
    o, odir, ovol = files(orig)
    b, _, _ = files(built)
    if set(o) != set(b):
        raise ValueError("the two images list different files")
    order = sorted(o, key=lambda p: o[p][1])
    if o[order[0]][1] <= odir:
        raise ValueError("a file starts before the last directory")
    shift, rows = 0, []
    for i, path in enumerate(order):
        ext = o[path][1]
        nxt = o[order[i + 1]][1] if i + 1 < len(order) else ovol
        size = b[path][2]
        new = ext + shift
        extra = sectors(size) - (nxt - ext)
        if extra > 0:
            shift += -(-extra // ALIGN) * ALIGN
        rows.append((path, new, size))
    last = rows[-1]
    return rows, max(ovol + shift, last[1] + sectors(last[2]))


def build(orig_path, built_path, out_path):
    with open(orig_path, "rb") as orig, open(built_path, "rb") as built:
        rows, total = plan(orig, built)
        b, _, _ = files(built)
        first = min(r[1] for r in rows)
        with open(out_path, "wb") as out:
            built.seek(0)
            out.write(built.read(first * SECTOR))  # descriptors, path tables, directories
            for path, ext, size in rows:
                if out.tell() > ext * SECTOR:
                    raise ValueError("layout overlap at " + path)
                out.write(bytes(ext * SECTOR - out.tell()))
                built.seek(b[path][1] * SECTOR)
                left = size
                while left:
                    chunk = built.read(min(left, 1 << 22))
                    out.write(chunk)
                    left -= len(chunk)
                out.write(bytes((-size) % SECTOR))
            out.write(bytes(total * SECTOR - out.tell()))
            for path, ext, size in rows:
                out.seek(b[path][0] + 2)
                out.write(both32(ext) + both32(size))
            out.seek(16 * SECTOR + 80)
            out.write(both32(total))


def digest(f, ext, size):
    h = hashlib.sha256()
    f.seek(ext * SECTOR)
    left = size
    while left:
        chunk = f.read(min(left, 1 << 22))
        h.update(chunk)
        left -= len(chunk)
    return h.hexdigest()


def verify(built_path, out_path):
    with open(built_path, "rb") as built, open(out_path, "rb") as out:
        b, _, _ = files(built)
        n, _, vol = files(out)
        if os.path.getsize(out_path) != vol * SECTOR:
            raise ValueError("volume size does not match the file size")
        for path in sorted(b):
            if digest(built, b[path][1], b[path][2]) != digest(out, n[path][1], n[path][2]):
                raise ValueError("content differs: " + path)
        return len(b)


def main():
    args = [a for a in sys.argv[1:] if a != "--write"]
    if len(args) != 3:
        sys.exit(__doc__)
    orig_path, built_path, out_path = args
    with open(orig_path, "rb") as orig, open(built_path, "rb") as built:
        rows, total = plan(orig, built)
        o, _, _ = files(orig)
    moved = [(p, o[p][1], e) for p, e, _ in rows if e != o[p][1]]
    print("%d files, %d moved; %d -> %d sectors (%d bytes)" % (
        len(rows), len(moved), os.path.getsize(orig_path) // SECTOR, total, total * SECTOR))
    for p, old, new in moved[:5]:
        print("  %s: %d -> %d" % (p, old, new))
    if len(moved) > 5:
        print("  ... %d more" % (len(moved) - 5))
    if "--write" not in sys.argv:
        print("dry run; add --write to build", out_path)
        return
    if os.path.exists(out_path):
        sys.exit("output exists: " + out_path)
    build(orig_path, built_path, out_path)
    print("wrote", out_path)
    print("verified %d files against %s" % (verify(built_path, out_path), built_path))


if __name__ == "__main__":
    main()
