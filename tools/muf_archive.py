"""Extract and repack the data archives of Macross Triangle Frontier (PSP).

Copied from the Macross Ace Frontier / Ultimate Frontier projects, same engine.
Triangle Frontier's macross.idx (PIDX0 version 8) names 8 containers:
macross.dat, fileset.dat, cmp_gop.dat, cmp_if.dat, cmp_icon.dat,
cmp_charmake.dat, operator_help.dat and staffroll.dat. Plain files live in
macross.dat and (34 map files) fileset.dat; FSTS bundles (XOR/LZSS-packed
members, tools/muf_lzss.py) live in fileset.dat and the six small containers.
Each container starts with its own PIDX0 v1 head (see docs/formats.md).

Usage:
  python tools/muf_archive.py extract <USRDIR> <out_dir>
  python tools/muf_archive.py repack  <dir> <out_USRDIR> --base <USRDIR>
                                      [--overlay <tree>] [--jobs N]
  python tools/muf_archive.py verify  <USRDIR_a> <USRDIR_b>

extract writes every file to <out_dir>/data/... and the layout to
<out_dir>/_meta/ (the idx, every container head, manifest.json). A bundle
member whose content differs from an earlier copy of the same path goes to
<out_dir>/_variants/<bundle>/<path>.

repack copies every container from --base and appends what changed: a changed
plain file, or a bundle with a changed member (rebuilt; unchanged members keep
their original packed bytes). The idx and the container head are repointed.
Nothing original is overwritten, because original entries can overlap. With no
changes the output is byte-identical to --base. --overlay <tree> takes
data/... (and _variants/...) files from <tree> when they exist there. Overlay
files under DAT_ONLY (voice clips with a subtitle tail) replace only the plain
copy: the copies inside bundles stay as they are (docs/voice_subtitles.md).
"""

import argparse
import hashlib
import json
import os
import struct
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import muf_lzss  # noqa: E402

IDX_NAME = "macross.idx"
DAT_NAME = "macross.dat"
FILESET_NAME = "fileset.dat"
DAT_ALIGN = 0x800
DAT_ONLY = ("data/sound/voice/",)  # overlay files used for macross.dat only
VOICE_ALIGN = 0x800  # streamed voice clips: TF's originals sit on 0x800 (MUF/AF: 0x8000)
FSTS_ALIGN = 0x10
ENTRY_SIZE = 24
FSTS_HEADER = 0x20
FSTS_ENTRY = 16


def align(x, a):
    return (x + a - 1) // a * a


def dat_align(path):
    return VOICE_ALIGN if path.startswith("data/sound/voice/") else DAT_ALIGN


def md5(data):
    return hashlib.md5(data).hexdigest()


def cstr(buf, off):
    return buf[off:buf.index(b"\0", off)].decode("ascii")


class Pidx:
    """PIDX0 header. Used by macross.idx (v2) and the heads of both .dat files (v1).

    0x00 'PIDX0\\0\\0\\0'   0x08 version
    0x0C entry table offset  0x10 entry count
    0x14 root entry count    0x18 fileset table offset  0x1C its size
    0x20 name table offset   0x24 its size
    0x28 container slots up to the entry table, 0x28 bytes each: name offset,
         20 zero bytes, 16-byte id that pairs the index with its .dat file
    """

    def __init__(self, buf):
        if buf[:5] != b"PIDX0":
            raise ValueError("not a PIDX0 header")
        (self.version, self.ent_off, self.ent_count, self.roots,
         self.tbl_off, self.tbl_size, self.name_off, self.name_size) = struct.unpack_from("<8I", buf, 8)
        self.buf = buf

    def name(self, off):
        return cstr(self.buf, self.name_off + off)

    def entry(self, i):
        """(type, name, a, b, c, d). Dir: type 1, a = child count, b = first child.
        File: type 0, a = container name offset, b = offset, c = size, d = stored length of
        a RAIC/RAIB file (Triangle Frontier; c is then the decoded size), 0 for a raw one."""
        return struct.unpack_from("<6I", self.buf, self.ent_off + ENTRY_SIZE * i)

    def entry_pos(self, i):
        return self.ent_off + ENTRY_SIZE * i

    def fileset_records(self):
        """List of (record position, (name, container, offset, size, member count))."""
        if self.tbl_size <= 4:
            return []
        count = struct.unpack_from("<I", self.buf, self.tbl_off)[0]
        ptrs = struct.unpack_from("<%dI" % count, self.buf, self.tbl_off + 4)
        return [(self.tbl_off + p, struct.unpack_from("<5I", self.buf, self.tbl_off + p)) for p in ptrs]

    def walk(self):
        """Yield (entry index, path) for every file in the directory tree."""
        out = []

        def rec(i, prefix):
            t, nm, a, b, _, _ = self.entry(i)
            path = prefix + self.name(nm)
            if t == 1:
                for j in range(b, b + a):
                    rec(j, path + "/")
            else:
                out.append((i, path))

        rec(0, "")
        return out


def parse_fsts(buf):
    magic, count, hdr, name_off, name_size = struct.unpack_from("<4s4I", buf, 0)
    if magic != b"FSTS" or hdr != FSTS_HEADER:
        raise ValueError("bad FSTS header")
    members = []
    for i in range(count):
        noff, off, usize, csize = struct.unpack_from("<4I", buf, FSTS_HEADER + FSTS_ENTRY * i)
        members.append((cstr(buf, name_off + noff), off, usize, csize))
    return members, name_off, name_size


def build_fsts(members):
    """members: list of (path, packed blob). Returns the FSTS bytes."""
    count = len(members)
    names = b"".join(p.encode("ascii") + b"\0" for p, _ in members)
    name_off = FSTS_HEADER + FSTS_ENTRY * count
    out = bytearray(struct.pack("<4s4I12x", b"FSTS", count, FSTS_HEADER, name_off, len(names)))
    out += bytes(FSTS_ENTRY * count)
    out += names
    noff = 0
    for i, (path, blob) in enumerate(members):
        out += bytes(align(len(out), FSTS_ALIGN) - len(out))
        usize = struct.unpack_from("<I", blob, 4)[0]
        struct.pack_into("<4I", out, FSTS_HEADER + FSTS_ENTRY * i, noff, len(out), usize, len(blob))
        noff += len(path) + 1
        out += blob
    out += bytes(align(len(out), FSTS_ALIGN) - len(out))
    return bytes(out)


def safe_join(root, path):
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts) or ":" in path or "\\" in path:
        raise ValueError("unsafe path in archive: %r" % path)
    return os.path.join(root, *parts)


def write_file(root, path, data):
    dest = safe_join(root, path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)


# ---------------------------------------------------------------- extract

def container_names(idx):
    """Names of the container slots (Triangle Frontier: 8 slots of 0x20 bytes at 0x30,
    each a name offset, 12 zero bytes and a 16-byte id)."""
    names = []
    pos = 0x30
    while pos + 0x20 <= idx.ent_off:
        names.append(idx.name(struct.unpack_from("<I", idx.buf, pos)[0]))
        pos += 0x20
    return names


def read_head(path, first):
    with open(path, "rb") as f:
        return Pidx(f.read(first))


def head_files(head):
    """(offset, size) of every file entry in a container head."""
    out = set()
    for i in range(head.ent_count):
        t, _, _, off, size, _ = head.entry(i)
        if t == 0:
            out.add((off, size))
    return out


def extract(usrdir, out):
    idx_buf = open(os.path.join(usrdir, IDX_NAME), "rb").read()
    idx = Pidx(idx_buf)
    meta = os.path.join(out, "_meta")
    os.makedirs(meta, exist_ok=True)
    with open(os.path.join(meta, IDX_NAME), "wb") as f:
        f.write(idx_buf)

    # Plain files. Ultimate/Ace Frontier keep them all in macross.dat; Triangle
    # Frontier also has 34 map files stored plain in fileset.dat.
    by_cont = {}
    for i, path in idx.walk():
        _, _, cont, off, size, _ = idx.entry(i)
        by_cont.setdefault(idx.name(cont), []).append((off, i, path, size))
    records = idx.fileset_records()
    rec_by_cont = {}
    for k, (_, (nm, cont, off, size, count)) in enumerate(records):
        rec_by_cont.setdefault(idx.name(cont), []).append((off, k, idx.name(nm), size, count))

    containers = sorted(set(by_cont) | set(rec_by_cont), key=lambda n: (n != DAT_NAME, n != FILESET_NAME, n))
    written = {}
    variants = 0
    plain = []
    sets = []
    sizes = {}
    for cname in containers:
        cpath = os.path.join(usrdir, cname)
        offs = [t[0] for t in by_cont.get(cname, [])] + [t[0] for t in rec_by_cont.get(cname, [])]
        head = read_head(cpath, min(offs))
        with open(os.path.join(meta, cname + ".head.bin"), "wb") as f:
            f.write(head.buf)
        hfiles = head_files(head)
        hrecs = {r[1][2:] for r in head.fileset_records()}
        with open(cpath, "rb") as dat:
            for off, i, path, size in sorted(by_cont.get(cname, [])):
                if (off, size) not in hfiles:
                    raise ValueError("%s head disagrees with idx for %s" % (cname, path))
                dat.seek(off)
                data = dat.read(size)
                h = md5(data)
                if written.get(path, h) != h:
                    raise ValueError("two different contents for %s" % path)
                if path not in written:
                    write_file(out, path, data)
                    written[path] = h
                plain.append({"entry": i, "container": cname, "path": path, "offset": off,
                              "size": size, "md5": h})
            for off, k, name, size, count in sorted(rec_by_cont.get(cname, [])):
                if (off, size, count) not in hrecs:
                    raise ValueError("%s head disagrees with idx for set %s" % (cname, name))
                dat.seek(off)
                buf = dat.read(size)
                members, _, _ = parse_fsts(buf)
                entry = {"record": k, "container": cname, "name": name, "offset": off, "size": size,
                         "members": []}
                for path, moff, usize, csize in members:
                    blob = buf[moff:moff + csize]
                    data = muf_lzss.decode(blob)
                    if len(data) != usize:
                        raise ValueError("size mismatch in %s" % path)
                    h = md5(data)
                    member = {"path": path, "mode": muf_lzss.member_mode(blob),
                              "offset": off + moff, "csize": csize, "md5": h}
                    if written.get(path, h) != h:
                        # Triangle Frontier: a few bundle copies differ from the plain
                        # file of the same path. Keep them apart under _variants/.
                        member["variant"] = "_variants/%s/%s" % (name, path)
                        write_file(out, member["variant"], data)
                        variants += 1
                    elif path not in written:
                        write_file(out, path, data)
                        written[path] = h
                    entry["members"].append(member)
                sets.append(entry)
            dat.seek(0, 2)
            sizes[cname] = dat.tell()
        print("%-18s %6d plain files, %5d sets, %6d members" % (
            cname, len(by_cont.get(cname, [])), len(rec_by_cont.get(cname, [])),
            sum(len(s["members"]) for s in sets if s["container"] == cname)))
    print("%d unique files in total, %d bundle members differ from the plain file (_variants/)"
          % (len(written), variants))

    manifest = {
        "format": "muf_archive 2 (Triangle Frontier, multi-container)",
        "containers": containers,
        "sizes": sizes,
        "plain_files": plain,
        "sets": sets,
    }
    with open(os.path.join(meta, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=0)


# ---------------------------------------------------------------- repack

def _encode_job(args):
    path, mode = args
    with open(path, "rb") as f:
        return muf_lzss.encode(f.read(), mode)


def repack(src, out, base, jobs=None, overlay=None):
    """Triangle Frontier repack: append, never move.

    Every container is copied from <base> (the original USRDIR) unchanged. A plain file
    whose content changed is appended at the end of its container; a bundle with a
    changed member is rebuilt (unchanged members keep their original packed bytes) and
    appended. The idx entry / fileset record and the container's own PIDX head are
    repointed. Nothing original is overwritten: original entries can overlap, so in-place
    writes are unsafe. With no changes the output is byte-identical to <base>.
    """
    meta = os.path.join(src, "_meta")
    manifest = json.load(open(os.path.join(meta, "manifest.json"), encoding="utf-8"))
    if "containers" not in manifest:
        raise SystemExit("not a Triangle Frontier manifest; re-run extract")
    idx = bytearray(open(os.path.join(meta, IDX_NAME), "rb").read())
    idx_p = Pidx(bytes(idx))
    os.makedirs(out, exist_ok=True)

    def src_file(path, variant=None, fileset=False):
        if overlay and not (fileset and path.startswith(DAT_ONLY)):
            o = safe_join(overlay, variant or path)
            if os.path.isfile(o):
                return o
        return safe_join(src, variant or path)

    heads = {}
    for c in manifest["containers"]:
        buf = bytearray(open(os.path.join(meta, c + ".head.bin"), "rb").read())
        h = Pidx(bytes(buf))
        paths = {p: i for i, p in h.walk()} if h.ent_count else {}  # bundle-only heads list no files
        heads[c] = (buf, h, paths, {r[1][2:]: r[0] for r in h.fileset_records()})

    plan = {c: [] for c in manifest["containers"]}  # container -> [(kind, item, data)]
    for f in manifest["plain_files"]:
        data = open(src_file(f["path"]), "rb").read()
        if md5(data) != f["md5"]:
            plan[f["container"]].append(("plain", f, data))
    encode = {}
    changed_sets = []
    for st in manifest["sets"]:
        todo = []
        for m in st["members"]:
            path = src_file(m["path"], m.get("variant"), fileset=True)
            if md5(open(path, "rb").read()) != m["md5"]:
                todo.append(m)
                encode[(path, m["mode"])] = None
        if todo:
            changed_sets.append((st, {id(m) for m in todo}))
    if encode:
        keys = list(encode)
        with Pool(jobs) as pool:
            for k, blob in zip(keys, pool.imap(_encode_job, keys, chunksize=1)):
                encode[k] = blob
    idx_recs = idx_p.fileset_records()

    for c in manifest["containers"]:
        src_c = os.path.join(base, c)
        dst_c = os.path.join(out, c)
        head_buf, head, head_paths, head_recs = heads[c]
        mine = [t for t in plan[c]]
        sets_here = [(st, ids) for st, ids in changed_sets if st["container"] == c]
        with open(src_c, "rb") as fi, open(dst_c, "wb") as fo:
            while True:
                chunk = fi.read(1 << 24)
                if not chunk:
                    break
                fo.write(chunk)
            pos = fo.tell()
            for _, f, data in mine:
                pos = align(pos, dat_align(f["path"]))
                fo.seek(pos)
                fo.write(data)
                # entry +12 offset, +16 size, +20 stored length: a plain RAIC/RAIB member is
                # listed with its decoded size and its stored length (the game reads that many
                # bytes and decodes them), a raw file with its size and 0, as in the originals
                size, stored = len(data), 0
                if data[:4] in (muf_lzss.MAGIC, muf_lzss.MAGIC_STORED):
                    size, stored = struct.unpack_from("<I", data, 4)[0], len(data)
                struct.pack_into("<3I", idx, idx_p.entry_pos(f["entry"]) + 12, pos, size, stored)
                struct.pack_into("<3I", head_buf, head.entry_pos(head_paths[f["path"]]) + 12, pos, size, stored)
                pos += len(data)
            for st, ids in sets_here:
                fi.seek(st["offset"])
                orig = fi.read(st["size"])
                members, _, _ = parse_fsts(orig)
                blobs = []
                for m, (path, moff, usize, csize) in zip(st["members"], members):
                    if id(m) in ids:
                        blobs.append((path, encode[(src_file(m["path"], m.get("variant"), True), m["mode"])]))
                    else:
                        blobs.append((path, orig[moff:moff + csize]))
                fsts = build_fsts(blobs)
                pos = align(pos, DAT_ALIGN)
                fo.seek(pos)
                fo.write(fsts)
                key = (st["offset"], st["size"], len(st["members"]))
                struct.pack_into("<3I", idx, idx_recs[st["record"]][0] + 8, pos, len(fsts), len(blobs))
                struct.pack_into("<3I", head_buf, head_recs[key] + 8, pos, len(fsts), len(blobs))
                pos += len(fsts)
            if mine or sets_here:
                end = align(pos, DAT_ALIGN)
                fo.seek(end - 1)
                fo.write(b"\0")  # pad to a whole sector, as the originals end
            fo.seek(0)
            fo.write(head_buf)
        print("%-18s %5d plain files appended, %4d bundles rebuilt" % (c, len(mine), len(sets_here)))
    with open(os.path.join(out, IDX_NAME), "wb") as f:
        f.write(idx)


# ---------------------------------------------------------------- verify

def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(a, b):
    ok = True
    names = [IDX_NAME] + sorted(n for n in os.listdir(a) if n.endswith(".dat"))
    for name in names:
        ha, hb = file_md5(os.path.join(a, name)), file_md5(os.path.join(b, name))
        print("%-12s %s %s %s" % (name, ha, hb, "OK" if ha == hb else "DIFFERENT"))
        ok &= ha == hb
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("extract")
    p.add_argument("usrdir")
    p.add_argument("out")
    p = sub.add_parser("repack")
    p.add_argument("src")
    p.add_argument("out")
    p.add_argument("--base", required=True, help="original USRDIR (all containers are copied from it)")
    p.add_argument("--jobs", type=int, default=None)
    p.add_argument("--overlay", help="tree whose data/... files replace the extracted ones")
    p = sub.add_parser("verify")
    p.add_argument("a")
    p.add_argument("b")
    args = ap.parse_args()
    if args.cmd == "extract":
        extract(args.usrdir, args.out)
    elif args.cmd == "repack":
        repack(args.src, args.out, args.base, args.jobs, args.overlay)
    else:
        sys.exit(0 if verify(args.a, args.b) else 1)


if __name__ == "__main__":
    main()
