"""Campus data tables (.gop) of Macross Triangle Frontier: list chunks and strings, rebuild.

Usage:
  python tools/gop.py chunks <file.gop>     list the chunks
  python tools/gop.py strings <file.gop>    list the GENESTRT strings with their index

File: a RAIC member (tools/muf_lzss.py). Decoded, a list of chunks:
  8-byte tag, u32 data size, u32 0, then the data (tags seen: "GOP GFIN", "GOP GMET",
  "GOP GREC", "GENESTRT", ...).
GENESTRT (the string table):
  u32 count, u32 0x10, u32 string data offset (from the start of the chunk data),
  u32 chunk data size, then count + 1 x u32 offsets into the string data (the last
  one is the end of the string data), padding,
  then NUL-terminated Shift-JIS strings in index order, the chunk
  padded to 16 bytes. Other chunks refer to a string by its index,
  so the table can be rebuilt with new strings (same count and order) without
  touching the rest of the file.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import muf_lzss  # noqa: E402

ENCODING = "cp932"


class Gop:
    def __init__(self, raw):
        self.raw = raw
        self.packed = raw[:4] in (muf_lzss.MAGIC, muf_lzss.MAGIC_STORED)
        self.mode = muf_lzss.member_mode(raw) if self.packed else None
        self.data = muf_lzss.decode(raw) if self.packed else raw
        self.chunks = []  # (pos, tag, size)
        pos = 0
        while pos + 16 <= len(self.data):
            tag = self.data[pos:pos + 8]
            size = struct.unpack_from("<I", self.data, pos + 8)[0]
            if not tag.strip(b"\0") or size > len(self.data):
                break
            self.chunks.append((pos, tag.decode("ascii", "replace"), size))
            pos += 16 + size
        self.tail = self.data[pos:]

    def strtab(self):
        """(chunk pos, header tuple, [bytes]) of the GENESTRT chunk."""
        for pos, tag, size in self.chunks:
            if tag == "GENESTRT":
                d = pos + 16
                count, unk, sdata, ssize = struct.unpack_from("<4I", self.data, d)
                offs = struct.unpack_from("<%dI" % count, self.data, d + 16)
                base = d + sdata
                out = []
                for o in offs:
                    end = self.data.index(b"\0", base + o)
                    out.append(self.data[base + o:end])
                return pos, (count, unk, sdata, ssize), out
        return None

    def rebuild(self, strings):
        """Replace the GENESTRT strings (list of bytes, same count). Returns the packed file."""
        pos, (count, unk, sdata, _), old = self.strtab()
        if len(strings) != count:
            raise ValueError("string count changed")
        blob = bytearray()
        offs = []
        for s in strings:
            offs.append(len(blob))
            blob += s + b"\0"
        offs.append(len(blob))  # the table ends with the end offset of the string data
        body = struct.pack("<4I", count, unk, sdata, 0) + struct.pack("<%dI" % len(offs), *offs)
        if len(body) > sdata:
            raise ValueError("offset table overruns the string data")
        body += bytes(sdata - len(body)) + blob
        body += bytes(-len(body) % 16)
        body = body[:12] + struct.pack("<I", len(body)) + body[16:]  # 4th field: chunk data size
        size_old = [c[2] for c in self.chunks if c[0] == pos][0]
        chunk = self.data[pos:pos + 8] + struct.pack("<2I", len(body), 0) + body
        new = self.data[:pos] + chunk + self.data[pos + 16 + size_old:]
        return muf_lzss.encode(new, self.mode) if self.packed else new


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cmd, path = sys.argv[1], sys.argv[2]
    g = Gop(open(path, "rb").read())
    if cmd == "chunks":
        for pos, tag, size in g.chunks:
            print("%06X %-8s %d" % (pos, tag, size))
        print("tail", len(g.tail))
    elif cmd == "strings":
        st = g.strtab()
        for i, s in enumerate(st[2] if st else []):
            print(i, s.decode(ENCODING, "replace").replace("\n", "/"))


if __name__ == "__main__":
    main()
