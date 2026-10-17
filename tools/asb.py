"""Campus event scripts (.asb) of Macross Triangle Frontier: parse, list text, rebuild.

Usage:
  python tools/asb.py stats [<script_dir>]       parse every script, report string references
  python tools/asb.py show <file.asb>            disassemble one script (debugging)

File (docs/formats.md "Campus event scripts"): a RAIC member (tools/muf_lzss.py).
Decoded:
  0x00  u32 0
  0x04  file name, NUL-padded
  0x24  7 x u32: label table offset (0x44), label count, code offset, code size,
        string pool offset, pool size, file size
  0x44  label table, 0x14 bytes per label (name offset in the pool, flags, code offset, size)
  code  stack bytecode (below)
  pool  NUL-terminated Shift-JIS strings; labels, names and every line of text

Bytecode, as far as needed to find the text (all 1,022 scripts parse to their exact end):
  01 <u32>               push an immediate (numbers AND string pool offsets)
  29 <u32 fn> <u8 argc>  call a built-in with argc pushed arguments
  21 / 22 <u32>          jump / jump if false (code offset)
  27 <u32>               (operand, not a string)
  05 24 <n> <n x u32>    switch after a choice: n code offsets
  05 <4 bytes>           variable load (05 07 00 02 00)
  13 <2 bytes>           variable store
  00 02-04 06-0a 1b-20 18 2b   no operand (stack and compare ops)

A text line is referenced by a push of its pool offset that is an argument of a
call. String arguments are recognised by the called function and argument slot
(TEXT_ARGS); every push of a Japanese string's offset is reported, so stats
shows whether anything is left unexplained.

Rebuild (rebuild()): the English is appended to the end of the pool and the
push operands that referenced the Japanese are repointed; the Japanese stays in
place (unreferenced). Code size and offsets do not change. The header's pool size
and file size are updated, and the result is re-encoded as a RAIC member.
"""

import collections
import glob
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import muf_lzss  # noqa: E402

ENCODING = "cp932"
OPLEN = {0x01: 4, 0x29: 5, 0x21: 4, 0x22: 4, 0x27: 4, 0x05: 4, 0x13: 2}
OPLEN.update({op: 0 for op in (0x00, 0x02, 0x03, 0x04, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x18,
                               0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x2B)})


class Script:
    def __init__(self, raw):
        self.raw = raw
        self.data = bytearray(muf_lzss.decode(raw))
        (self.lab_off, self.lab_n, self.code_off, self.code_size,
         self.pool_off, self.pool_size, self.size) = struct.unpack_from("<7I", self.data, 0x24)
        if self.pool_off + self.pool_size != self.size or self.size != len(self.data):
            raise ValueError("unexpected .asb header")
        self.mode = muf_lzss.member_mode(raw)

    @property
    def code(self):
        return bytes(self.data[self.code_off:self.code_off + self.code_size])

    def strings(self):
        """OrderedDict pool offset -> raw bytes."""
        out = collections.OrderedDict()
        off = 0
        pool = bytes(self.data[self.pool_off:self.pool_off + self.pool_size])
        for s in pool.split(b"\0")[:-1]:
            out[off] = s
            off += len(s) + 1
        return out

    def ops(self):
        """Yield (pos in code, op, operand bytes)."""
        code = self.code
        i = 0
        while i < len(code):
            op = code[i]
            if op == 0x05 and code[i + 1] == 0x24:
                n = 3 + 4 * code[i + 2]
            elif op in OPLEN:
                n = 1 + OPLEN[op]
            else:
                raise ValueError("unknown opcode %02X at code+0x%X" % (op, i))
            yield i, op, code[i + 1:i + n]
            i += n
        if i != len(code):
            raise ValueError("code does not end on an instruction")

    def calls(self):
        """Yield (call pos, fn, [push pos or None per argument]). Pushes are matched to calls
        with a stack of pending pushes; other ops reset nothing (arguments are always
        pushed directly before their call in these scripts)."""
        pending = []
        for pos, op, arg in self.ops():
            if op == 0x01:
                pending.append(pos)
            elif op == 0x29:
                fn, argc = struct.unpack("<IB", arg)
                args = pending[-argc:] if argc else []
                if len(args) < argc:
                    args = [None] * (argc - len(args)) + args
                if argc:
                    del pending[-argc:]
                yield pos, fn, args
            elif op in (0x21, 0x22, 0x05, 0x13, 0x00, 0x2B):
                pending.clear()

    def push_value(self, pos):
        return struct.unpack_from("<I", self.data, self.code_off + pos + 1)[0]

    def text_refs(self):
        """{pool offset of a Japanese string: [(push pos, fn, arg index)]} and the pushes of
        Japanese offsets that are not call arguments."""
        strings = self.strings()
        jp = {o for o, s in strings.items() if any(b > 0x7F for b in s)}
        refs = collections.defaultdict(list)
        seen = set()
        for _, fn, args in self.calls():
            for k, p in enumerate(args):
                if p is None:
                    continue
                v = self.push_value(p)
                if v in jp:
                    refs[v].append((p, fn, k))
                    seen.add(p)
        loose = [p for p, op, _ in self.ops() if op == 0x01 and self.push_value(p) in jp and p not in seen]
        return refs, loose

    def rebuild(self, english, repoint):
        """english: {pool offset: str}; repoint: {pool offset: [push pos]} (from text_refs).
        Appends each English string to the pool and repoints its pushes."""
        data = bytearray(self.data)
        pool_end = self.pool_off + self.pool_size
        tail = bytearray()
        for off, text in english.items():
            new = self.pool_size + len(tail)
            tail += text.encode(ENCODING) + b"\0"
            for p in repoint[off]:
                struct.pack_into("<I", data, self.code_off + p + 1, new)
        data[pool_end:pool_end] = tail
        struct.pack_into("<2I", data, 0x38, self.pool_size + len(tail), len(data))
        return muf_lzss.encode(bytes(data), self.mode)


def iter_scripts(root):
    for f in sorted(glob.glob(os.path.join(root, "*", "*.asb"))):
        yield f, Script(open(f, "rb").read())


def stats(root):
    fn_use = collections.Counter()
    multi = collections.Counter()
    loose_total = 0
    unref = 0
    n_jp = 0
    for f, s in iter_scripts(root):
        refs, loose = s.text_refs()
        loose_total += len(loose)
        jp = [o for o, b in s.strings().items() if any(x > 0x7F for x in b)]
        n_jp += len(jp)
        for o in jp:
            if o not in refs:
                unref += 1
            multi[len(refs.get(o, []))] += 1
            for _, fn, k in refs.get(o, []):
                fn_use[(fn, k)] += 1
    print("Japanese strings %d, unreferenced %d, loose pushes %d" % (n_jp, unref, loose_total))
    print("references per string:", sorted(multi.items()))
    print("(function, argument) taking Japanese strings:", fn_use.most_common())


def show(path):
    s = Script(open(path, "rb").read())
    strings = s.strings()
    for pos, op, arg in s.ops():
        note = ""
        if op == 0x01:
            v = struct.unpack("<I", arg)[0]
            if v in strings:
                note = "  ; " + strings[v].decode(ENCODING, "replace")[:40].replace("\n", "/")
        print("%05X  %02X %-20s%s" % (pos, op, arg.hex(" "), note))


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "stats":
        stats(sys.argv[2] if len(sys.argv) > 2 else os.path.join("work", "source", "dat", "data", "campus",
                                                                 "event", "script"))
    elif sys.argv[1] == "show":
        show(sys.argv[2])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
