"""Make a patched copy of the game ISO by replacing individual files.

Usage:
  python tools/iso_patch.py <original.iso> <out.iso> <iso_path>=<file> [...]
  e.g. PSP_GAME/SYSDIR/EBOOT.BIN=work/output/vwf/PSP_GAME/SYSDIR/EBOOT.BIN

Everything not replaced stays byte-identical. A replacement that fits in the
sectors of the original file is written in place; a bigger one is appended at
the end of the image. Then its ISO 9660 directory record (extent and size) and,
when the image grows, the volume size in the primary volume descriptor are
updated.
"""

import os
import shutil
import struct
import sys

SECTOR = 2048


def both32(v):
    return struct.pack("<I", v) + struct.pack(">I", v)


def find_record(f, path):
    """Return (byte offset of the directory record, extent, size) for an ISO path."""
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    if pvd[1:6] != b"CD001":
        raise ValueError("not an ISO 9660 image")
    root = pvd[156:156 + 34]
    ext, size = struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0]
    parts = [p for p in path.upper().split("/") if p]
    for depth, name in enumerate(parts):
        found = None
        pos = 0
        f.seek(ext * SECTOR)
        data = f.read(size)
        while pos < len(data):
            ln = data[pos]
            if ln == 0:  # records do not cross sectors
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            rec = data[pos:pos + ln]
            nlen = rec[32]
            rname = rec[33:33 + nlen].decode("ascii", "replace").upper().split(";")[0]
            if rname == name:
                found = (ext * SECTOR + pos, struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0])
                break
            pos += ln
        if not found:
            raise FileNotFoundError(path)
        if depth < len(parts) - 1:
            _, ext, size = found
    return found


def _copy(f, local, n):
    """Write file `local` (n bytes) at the current position, in chunks (32-bit Python
    cannot hold a grown macross.dat in memory)."""
    with open(local, "rb") as g:
        while n:
            chunk = g.read(min(n, 1 << 24))
            if not chunk:
                raise IOError("%s is shorter than expected" % local)
            f.write(chunk)
            n -= len(chunk)


def patch(src, out, replacements):
    shutil.copyfile(src, out)
    with open(out, "r+b") as f:
        for iso_path, local in replacements:
            n = os.path.getsize(local)
            rec_off, ext, size = find_record(f, iso_path)
            old_sectors = (size + SECTOR - 1) // SECTOR
            if n <= old_sectors * SECTOR:
                new_ext = ext
                f.seek(ext * SECTOR)
                _copy(f, local, n)
                f.write(bytes(old_sectors * SECTOR - n))
                where = "in place"
            else:
                f.seek(0, 2)
                end = f.tell()
                new_ext = (end + SECTOR - 1) // SECTOR
                f.seek(new_ext * SECTOR)
                _copy(f, local, n)
                f.write(bytes((-n) % SECTOR))
                where = "appended at sector %d" % new_ext
            f.seek(rec_off + 2)
            f.write(both32(new_ext) + both32(n))
            print("%s: %d -> %d bytes, %s" % (iso_path, size, n, where))
        f.seek(0, 2)
        sectors = f.tell() // SECTOR
        f.seek(16 * SECTOR + 80)
        f.write(both32(sectors))


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    reps = []
    for arg in sys.argv[3:]:
        iso_path, local = arg.split("=", 1)
        reps.append((iso_path, local))
    patch(sys.argv[1], sys.argv[2], reps)


if __name__ == "__main__":
    main()
