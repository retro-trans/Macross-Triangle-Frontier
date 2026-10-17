"""Dump the Japanese text compiled into the decrypted EBOOT, with every reference to it.

Usage:
  python tools/dump_eboot.py [<eboot.dec.bin>] [<out.json>]
  defaults: work/source/eboot/EBOOT.dec.bin  work/source/text/eboot_strings.json

The input is the PPSSPP-decrypted EBOOT (a PRX: ELF type 0xFFA0, see
docs/formats.md "EBOOT text"). The output contains Japanese and is gitignored
(work/source/).

How strings are found:
  The PRX keeps its relocation table (program header type 0x700000A0), so
  every absolute address in the module is listed:
    R_MIPS_32   a pointer word in .data/.rodata (string tables, structs)
    HI16/LO16   a lui + addiu pair in code that builds the address
  The HI16 entries are not stored next to the LO16 they belong to, so each
  LO16 is paired with the lui that really sets its base register, by walking
  the control flow graph backwards. A string is any reference target in the
  data sections that is a NUL-terminated Shift-JIS run with Japanese in it.
  A second pass picks up strings that no pointer reaches directly: fixed-size
  name fields inside struct arrays (pilot table), edited in place only.

Every entry has:
  id        "eboot:<file offset hex>", same ids as tools/build_dialogue.py
  offset    file offset in EBOOT.dec.bin; vaddr = address in the module
  section   ELF section; bytes = length without the NUL terminator
  capacity  bytes available in place, terminator included (up to the next
            non-zero byte)
  jp        the text (real "\\n" line breaks; "%s"/"{...}" are format codes)
  refs      every reference, see docs/formats.md for the fields
  in_place  a field of a struct array (pilot table) or a lookup table
            (`note` says which): edit in place only
  inline_copy  code reads the bytes directly (an inlined strcpy of fixed
            length): moving or lengthening the string is not enough
  tails     ids of the merged Japanese tails inside this string
  inner_refs  addresses referenced inside the string (merged tails of any
            kind, e.g. "B" = the last byte of a final 。): keep the old bytes
  tail_of   set when the string is the tail of a longer one (the compiler
            merged them); editing the longer string changes this one too
"""

import bisect
import collections
import json
import os
import struct
import sys

ENCODING = "cp932"
PT_LOAD = 1
PT_PRX_RELOC = 0x700000A0
R_MIPS_32, R_MIPS_26, R_MIPS_HI16, R_MIPS_LO16 = 2, 4, 5, 6
LOAD_BASE = 0x08804000  # where the game loads; its low half decides the HI16 carry
CALLER_SAVED = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25, 31}
ADDR_OPS = {0x08: "addi", 0x09: "addiu", 0x0D: "ori"}
MEM_OPS = {0x20: "lb", 0x21: "lh", 0x22: "lwl", 0x23: "lw", 0x24: "lbu", 0x25: "lhu",
           0x26: "lwr", 0x28: "sb", 0x29: "sh", 0x2A: "swl", 0x2B: "sw", 0x2E: "swr",
           0x31: "lwc1", 0x39: "swc1", 0x32: "lv.s", 0x36: "lv.q", 0x3A: "sv.s", 0x3E: "sv.q"}
MAX_STRING = 4096
# Lookup tables that decode as text but are read by position: never moved
# Addresses that decode as text but are data. The Ace Frontier entries do not apply to
# Triangle Frontier; add its own here once found.
NOT_TEXT = {0x425EE0: "2 bytes of a data table that happen to decode as a kanji",
            0x462E1C: "8 bytes of a data table that happen to decode as text",
            0x462E34: "3 bytes of a data table that happen to decode as text",
            0x40E940: "CSV column name looked up in data/locate/*.csv (code at 0x195C24): translated, the "
                      "parser loses the column and misreads the unit's side (friendly units shown as "
                      "enemies, 0.1.0-0.1.18)"}
BFS_LIMIT = 30000


class Elf:
    def __init__(self, data):
        self.data = data
        if data[:4] != b"\x7fELF":
            sys.exit("not a decrypted ELF (expected \\x7fELF); see docs/formats.md")
        (self.type, _, _, self.entry, phoff, shoff, _, _, phentsize, phnum,
         shentsize, shnum, shstrndx) = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
        self.phdrs = [struct.unpack_from("<8I", data, phoff + i * phentsize) for i in range(phnum)]
        self.loads = [(p[2], p[1], p[4]) for p in self.phdrs if p[0] == PT_LOAD]  # vaddr, offset, filesz
        raw = [struct.unpack_from("<10I", data, shoff + i * shentsize) for i in range(shnum)]
        names = raw[shstrndx][4]
        self.sections = []  # name, addr, size, flags
        for s in raw:
            name = data[names + s[0]:data.index(b"\0", names + s[0])].decode()
            if s[2] & 2 and s[1] != 8 and s[5]:  # SHF_ALLOC, not NOBITS
                self.sections.append((name, s[3], s[5], s[2]))
        self.sections.sort(key=lambda x: x[1])
        self._starts = [s[1] for s in self.sections]

    def off(self, vaddr):
        for v, o, n in self.loads:
            if v <= vaddr < v + n:
                return o + vaddr - v
        return None

    def section(self, vaddr):
        i = bisect.bisect_right(self._starts, vaddr) - 1
        if i >= 0:
            name, addr, size, flags = self.sections[i]
            if vaddr < addr + size:
                return self.sections[i]
        return None

    def word(self, vaddr):
        return struct.unpack_from("<I", self.data, self.off(vaddr))[0]

    def relocs(self):
        segs = [v for v, _, _ in self.loads]
        out = []
        for p in self.phdrs:
            if p[0] != PT_PRX_RELOC:
                continue
            for i in range(p[1], p[1] + p[4], 8):
                r_offset, info = struct.unpack_from("<II", self.data, i)
                # (where, type, base of the segment the stored value is relative to)
                out.append((segs[(info >> 8) & 0xFF] + r_offset, info & 0xFF, segs[(info >> 16) & 0xFF]))
        return out


def sext16(x):
    return x - 0x10000 if x & 0x8000 else x


# --- MIPS (Allegrex) control flow, just enough to pair HI16 with LO16 -------

def written_reg(w):
    """GPR written by instruction w (None if none or unknown)."""
    op = w >> 26
    if op == 0:
        fn = w & 0x3F
        if fn in (0x08, 0x0C, 0x0D, 0x0F, 0x11, 0x13, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D,
                  0x2E, 0x2F):  # jr syscall break sync mthi mtlo mult/div madd/msub
            return None
        return (w >> 11) & 31
    if op == 0x03:
        return 31
    if 0x08 <= op <= 0x0F or 0x20 <= op <= 0x26 or op == 0x30:
        return (w >> 16) & 31
    if op == 0x01 and ((w >> 16) & 31) in (0x10, 0x11, 0x12, 0x13):
        return 31  # bltzal and friends
    if op in (0x11, 0x12) and ((w >> 21) & 31) in (0, 2, 3):
        return (w >> 16) & 31  # mfc1 / cfc1 / mfv / mfvc
    if op == 0x1C and (w & 0x3F) in (0x20, 0x21):
        return (w >> 11) & 31  # clz / clo
    if op == 0x1F:
        fn = w & 0x3F
        return (w >> 16) & 31 if fn in (0x00, 0x04) else (w >> 11) & 31  # ext/ins, seb/seh/...
    return None


def branch_kind(w, pc):
    """(kind, target) for a branch or jump, else None.
    kind: 'cond', 'likely', 'jump' (unconditional), 'call', 'ijump' (jr), 'icall' (jalr)."""
    op = w >> 26
    rel = (pc + 4 + (sext16(w & 0xFFFF) << 2)) & 0xFFFFFFFF
    if op == 0x02:
        return "jump", ((pc + 4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
    if op == 0x03:
        return "call", ((pc + 4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
    if op == 0:
        if w & 0x3F == 0x08:
            return "ijump", None
        if w & 0x3F == 0x09:
            return "icall", None
        return None
    if op in (0x04, 0x05, 0x06, 0x07):
        if op == 0x04 and (w >> 16) & 0x3FF == 0:  # beq $0,$0 = b
            return "jump", rel
        return "cond", rel
    if op in (0x14, 0x15, 0x16, 0x17):
        return "likely", rel
    if op == 0x01:
        rt = (w >> 16) & 31
        if rt in (0x00, 0x01):
            return "cond", rel
        if rt in (0x02, 0x03):
            return "likely", rel
        if rt in (0x10, 0x11, 0x12, 0x13):
            return "call", rel
        return None
    if op in (0x11, 0x12) and (w >> 21) & 31 == 0x08:  # bc1x / bvx
        return ("likely" if (w >> 17) & 1 else "cond"), rel
    return None


class Code:
    def __init__(self, elf, code_targets):
        self.elf = elf
        self.ranges = [(a, a + n) for name, a, n, f in elf.sections if f & 4]
        self.kind = {}
        self.into = collections.defaultdict(list)  # target -> delay slots that jump there
        self.entries = set(code_targets)  # jump-table targets: predecessors unknown
        for lo, hi in self.ranges:
            for pc in range(lo, hi, 4):
                k = branch_kind(elf.word(pc), pc)
                if k:
                    self.kind[pc] = k[0]
                    if k[0] == "call":
                        self.entries.add(k[1])
                    elif k[1] is not None:
                        self.into[k[1]].append(pc + 4)

    def in_code(self, pc):
        return any(lo <= pc < hi for lo, hi in self.ranges)

    def preds(self, pc):
        """[(pred, crosses_call)]"""
        out = [(d, False) for d in self.into.get(pc, ())]
        p = pc - 4
        if self.in_code(p):
            if p in self.kind:
                out.append((p, False))  # pc is the delay slot of p
            else:
                k = self.kind.get(p - 4)
                if k is None or k == "cond":
                    out.append((p, False))
                elif k in ("call", "icall"):
                    out.append((p, True))
                # jump / ijump: no fall-through; likely: handled below
        if self.kind.get(pc - 8) == "likely":
            out.append((pc - 8, False))  # not taken: delay slot skipped
        return out

    def reaching_lui(self, pc, reg, his):
        """lui instructions (with a HI16 reloc) that can set `reg` for the
        instruction at pc. Returns (set of lui addresses, clean flag)."""
        found, clean = set(), True
        seen = set()
        todo = [(p, c) for p, c in self.preds(pc)]
        while todo:
            p, crosses = todo.pop()
            if crosses and reg in CALLER_SAVED:
                clean = False
                continue
            if p in seen:
                continue
            seen.add(p)
            if len(seen) > BFS_LIMIT:
                return found, False
            w = self.elf.word(p)
            if written_reg(w) == reg:
                if w >> 26 == 0x0F and p in his:
                    found.add(p)
                else:
                    clean = False
                continue
            if p in self.entries:
                clean = False  # function start or switch case: some callers unknown
            nxt = self.preds(p)
            if not nxt:
                clean = False
            todo.extend(nxt)
        return found, clean


# --- text recognition --------------------------------------------------------

def decode_text(raw):
    """Decoded text if raw is plausible game text with Japanese in it, else None."""
    if not raw or len(raw) > MAX_STRING:
        return None
    try:
        s = raw.decode(ENCODING)
    except UnicodeDecodeError:
        return None
    jp = 0
    for ch in s:
        o = ord(ch)
        if ch == "\n" or 0x20 <= o < 0x7F:
            continue
        if o < 0x20 or 0x7F <= o <= 0x9F or 0xE000 <= o <= 0xF8FF or 0xFF61 <= o <= 0xFF9F:
            return None  # control, private use (0xA0/0xFD-0xFF bytes), half-width kana
        jp += 1
    return s if jp else None


def looks_like_data(data, o, raw, s):
    """Short hits that are numbers rather than text: a kanji next to stray
    ASCII bytes (float or pointer words), or one character inside an array of
    u16 values (switch tables)."""
    wide = sum(1 for c in s if ord(c) >= 0x80)
    if kana_count(s) == 0 and len(s) <= 4 and (any(ord(c) < 0x80 and c != " " for c in s) or
                                               (wide < 2 and " " in s)):
        return True
    if len(raw) == 2:
        words = [data[o + k:o + k + 4] for k in range(-16, 20, 4) if k]
        u16 = sum(1 for w in words if len(w) == 4 and w[1] >= 0x80 and w[2:] == bytes(2))
        return u16 >= 5
    return False


def kana_count(s):
    return sum(1 for c in s if 0x3041 <= ord(c) <= 0x30FF or 0xFF10 <= ord(c) <= 0xFF5A)


def plausible_unreferenced(raw, s):
    """Stricter test for strings no reference points at (float data decodes as
    random kanji): kana or full-width letters, or only common (JIS level 1)
    kanji without ASCII."""
    if kana_count(s) >= 2:
        return True
    if any(ord(c) < 0x80 and c != " " for c in s) or len(s) < 2:
        return False
    i = 0
    while i < len(raw):
        b = raw[i]
        if b >= 0x81:
            if raw[i:i + 2] >= b"\x98\x9f":  # JIS level 2 kanji and above
                return False
            i += 2
        else:
            i += 1
    return True


def char_starts(raw):
    out, i = set(), 0
    while i < len(raw):
        out.add(i)
        i += 2 if (0x81 <= raw[i] <= 0x9F or 0xE0 <= raw[i] <= 0xFC) else 1
    return out


# --- main ------------------------------------------------------------------

def find_tables(locs):
    """Runs of pointer words with a constant stride: {loc: (start, stride, index, count)}."""
    locs = sorted(locs)
    out, i = {}, 0
    while i < len(locs):
        j = i + 1
        if j < len(locs) and locs[j] - locs[i] <= 0x400:
            stride = locs[j] - locs[i]
            while j + 1 < len(locs) and locs[j + 1] - locs[j] == stride:
                j += 1
            if j - i + 1 >= 3 or stride == 4:
                for k in range(i, j + 1):
                    out[locs[k]] = (locs[i], stride, k - i, j - i + 1)
                i = j + 1
                continue
        i += 1
    return out


class Analysis:
    """Relocations of a module, with every LO16 paired to its lui.

    rels      [(where, type, segment base)] in table order
    base      {(where, type): segment base the stored value is relative to}
    lo_target {LO16 address: absolute target}, lo_his {LO16: [lui addresses]}
    hi_users  {lui: set of LO16}, order_lo {HI16: the LO16 the loader pairs it with}
    """


def analyze(elf):
    A = Analysis()
    rels = A.rels = elf.relocs()
    base = {(a, t): b for a, t, b in rels}
    his = {a for a, t, b in rels if t == R_MIPS_HI16}
    los = [a for a, t, b in rels if t == R_MIPS_LO16]
    ptrs = [a for a, t, b in rels if t == R_MIPS_32]

    def ptr_target(a):  # stored values are relative to the target segment
        return (elf.word(a) + base[a, R_MIPS_32]) & 0xFFFFFFFF
    A.ptr_target = ptr_target
    code = Code(elf, [ptr_target(a) for a in ptrs if elf.section(ptr_target(a)) and elf.section(ptr_target(a))[3] & 4])

    # pair every LO16 with its lui
    stats = A.stats = collections.Counter()
    lo_target, lo_his, lo_clean = {}, {}, {}
    hi_users = collections.defaultdict(set)
    for a in los:
        w = elf.word(a)
        reg = (w >> 21) & 31
        if reg == 0:
            lo_target[a], lo_his[a], lo_clean[a] = (sext16(w & 0xFFFF) + base[a, R_MIPS_LO16]) & 0xFFFFFFFF, [], True
            continue
        found, clean = code.reaching_lui(a, reg, his)
        values = {elf.word(h) & 0xFFFF for h in found}
        if len(values) != 1:
            stats["lo16_unresolved"] += 1
            continue
        stats["lo16_paired" if clean else "lo16_paired_partial"] += 1
        hi = values.pop()
        lo_target[a] = ((hi << 16) + sext16(w & 0xFFFF) + base[a, R_MIPS_LO16]) & 0xFFFFFFFF
        if any(base[h, R_MIPS_HI16] != base[a, R_MIPS_LO16] for h in found):
            stats["lo16_segment_mismatch"] += 1
        lo_his[a], lo_clean[a] = sorted(found), clean
        for h in found:
            hi_users[h].add(a)

    # sanity check: the loader takes the HI16 carry from the next LO16 in the
    # relocation list; that must agree with the pairing found here
    def carry(lo, seg):
        return (sext16(lo) + ((LOAD_BASE + seg) & 0xFFFF) + 0x8000) >> 16
    order_lo, nxt = {}, None
    for a, t, b in reversed(rels):
        if t == R_MIPS_LO16:
            nxt = a
        elif t == R_MIPS_HI16:
            order_lo[a] = nxt
    for h, users in hi_users.items():
        seg = base[h, R_MIPS_HI16]
        c = {carry(elf.word(u) & 0xFFFF, seg) for u in users}
        stats["hi16_carry_ok" if c == {carry(elf.word(order_lo[h]) & 0xFFFF, seg)} else "hi16_carry_mismatch"] += 1
    A.base, A.his, A.los, A.ptrs = base, his, los, ptrs
    A.lo_target, A.lo_his, A.lo_clean, A.hi_users, A.order_lo = lo_target, lo_his, lo_clean, hi_users, order_lo
    return A


def dump(path):
    elf = Elf(open(path, "rb").read())
    data = elf.data
    A = analyze(elf)
    stats, ptrs, ptr_target = A.stats, A.ptrs, A.ptr_target
    lo_target, lo_his, lo_clean, hi_users, order_lo = A.lo_target, A.lo_his, A.lo_clean, A.hi_users, A.order_lo
    data_secs = [s for s in elf.sections if not s[3] & 4]

    def is_data(v):
        s = elf.section(v)
        return s is not None and not s[3] & 4

    # collect references by target address
    refs = collections.defaultdict(list)
    tables = find_tables(ptrs)
    for a in ptrs:
        r = {"kind": "ptr", "vaddr": a, "offset": elf.off(a), "section": elf.section(a)[0]}
        if a in tables:
            start, stride, idx, count = tables[a]
            r["table"] = {"start": start, "stride": stride, "index": idx, "count": count}
        refs[ptr_target(a)].append(r)
    for a, t in lo_target.items():
        op = elf.word(a) >> 26
        r = {"kind": "code", "insn": ADDR_OPS.get(op) or MEM_OPS.get(op) or "op%02x" % op,
             "lo": a, "lo_offset": elf.off(a), "hi": lo_his[a],
             "hi_offset": [elf.off(h) for h in lo_his[a]]}
        shared = sorted({lo_target[u] for h in lo_his[a] for u in hi_users[h]} - {t})
        if shared:
            r["hi_shared"] = len(shared)
        other = sorted({order_lo[h] for h in lo_his[a]} - {a})
        if other:
            r["loader_lo"] = other  # the LO16 the loader takes the HI16 carry from
        if not lo_clean[a]:
            r["certain"] = False
        refs[t].append(r)

    # strings at reference targets
    entries = {}

    def text_at(v):
        o = elf.off(v)
        if o is None:
            return None, None
        end = data.find(b"\0", o, o + MAX_STRING + 1)
        if end < 0:
            return None, None
        return data[o:end], decode_text(data[o:end])

    targets = sorted(set(refs) | {ptr_target(a) for a in ptrs})

    def capacity(v, n):
        """In-place room: zero bytes after the string, but never past the
        next address something points at."""
        o = elf.off(v) + n
        sec = elf.section(v)
        limit = elf.off(sec[1] + sec[2])
        i = bisect.bisect_right(targets, v + n)  # skip addresses inside the string
        if i < len(targets) and targets[i] < sec[1] + sec[2]:
            limit = min(limit, elf.off(targets[i]))
        while o < limit and data[o] == 0:
            o += 1
        return o - elf.off(v)

    def add(v, raw, s, tail_of=None):
        o = elf.off(v)
        e = {"id": "eboot:%06X" % o, "offset": o, "vaddr": v, "section": elf.section(v)[0],
             "bytes": len(raw), "capacity": capacity(v, len(raw)), "jp": s, "refs": []}
        if tail_of is not None:
            e["tail_of"] = "eboot:%06X" % elf.off(tail_of)
        entries[v] = e
        return e

    rejected = collections.Counter()
    interior = []
    for v in sorted(refs):
        if not is_data(v):
            continue
        usable = refs[v]
        # a string needs a pointer or an address load; a plain lw/sw alone is
        # a data access that happens to land on text-like bytes
        if not any(r["kind"] == "ptr" or r["insn"] in ADDR_OPS.values() for r in usable):
            continue
        raw, s = text_at(v)
        o = elf.off(v)
        if s is None or looks_like_data(data, o, raw, s):
            continue
        if o > 0 and data[o - 1] != 0 and v != elf.section(v)[1]:
            interior.append((v, raw, s, usable))
            continue
        add(v, raw, s)["refs"] = usable

    # tails of merged strings: the reference points inside a longer string
    for v, raw, s, usable in interior:
        o = elf.off(v)
        start = o
        while start > 0 and data[start - 1] != 0 and o - start < MAX_STRING:
            start -= 1
        sv = v - (o - start)
        whole = data[start:data.index(b"\0", o)]
        ws = decode_text(whole)
        if ws is None:  # binary data right before the string: it starts here
            add(v, raw, s)["refs"] = usable
            continue
        if (o - start) not in char_starts(whole):
            rejected["interior"] += 1
            continue
        if sv not in entries:
            add(sv, whole, ws)
        add(v, raw, s, tail_of=sv)["refs"] = usable
        entries[sv].setdefault("tails", []).append("eboot:%06X" % o)

    # strings no reference reaches (fixed-size fields in struct arrays)
    covered = set()
    for v, e in entries.items():
        covered.update(range(v, v + e["bytes"]))
    for name, addr, size, flags in data_secs:
        o0 = elf.off(addr)
        o = o0
        end = o0 + size
        while o < end:
            if data[o] == 0 or (o - o0) % 4:
                o += 1
                continue
            z = data.find(b"\0", o, end)
            if z < 0:
                break
            v = addr + (o - o0)
            raw = data[o:z]
            if data[o - 1] == 0 and v not in covered:
                s = decode_text(raw)
                if s and plausible_unreferenced(raw, s) and not looks_like_data(data, o, raw, s):
                    add(v, raw, s)
            o = z + 1

    # unreferenced fields in a struct array: the field is as wide as its
    # narrowest instance (a following int field can be zero in some records)
    lone = sorted(v for v, e in entries.items() if not e["refs"] and "tails" not in e)
    i = 0
    while i < len(lone):
        j = i
        while j + 2 < len(lone) and lone[j + 2] - lone[j + 1] == lone[i + 1] - lone[i]:
            j += 1
        run = lone[i:j + 2] if j + 1 < len(lone) else lone[i:i + 1]
        stride = run[1] - run[0] if len(run) > 1 else 0
        if len(run) == 2 and stride > 0x200:  # two unrelated lone strings, not a struct array
            run, stride = run[:1], 0
        width = min(entries[v]["capacity"] for v in run)
        if stride and run[0] - stride in entries:  # the table base record has references
            run = [run[0] - stride] + run
        for v in run:
            entries[v]["capacity"] = min(entries[v]["capacity"], width)
            if len(run) > 1:
                entries[v]["in_place"] = True
        i += len(run)

    for v, e in entries.items():
        inner = targets[bisect.bisect_right(targets, v):bisect.bisect_right(targets, v + e["bytes"])]
        if inner:
            e["inner_refs"] = inner

    out = [entries[v] for v in sorted(entries)]
    for e in out:
        e["refs"].sort(key=lambda r: r.get("vaddr", r.get("lo")))
    stats["strings"] = len(out)
    stats["strings_ptr_only"] = sum(1 for e in out if e["refs"] and all(r["kind"] == "ptr" for r in e["refs"]))
    stats["strings_with_code_refs"] = sum(1 for e in out if any(r["kind"] == "code" for r in e["refs"]))
    stats["strings_unreferenced"] = sum(1 for e in out if not e["refs"] and "tails" not in e)
    stats["strings_tail_merged"] = sum(1 for e in out if "tail_of" in e)
    stats["code_refs_hi_shared"] = sum(1 for e in out for r in e["refs"] if r.get("hi_shared"))
    for e in out:
        if any(r["kind"] == "code" and r["insn"] not in ADDR_OPS.values() for r in e["refs"]):
            e["inline_copy"] = True
        if e["vaddr"] in NOT_TEXT:
            e["in_place"] = True
            e["note"] = NOT_TEXT[e["vaddr"]]
    stats["strings_inline_copy"] = sum(1 for e in out if e.get("inline_copy"))
    stats["code_refs_uncertain"] = sum(1 for e in out for r in e["refs"] if r.get("certain") is False)
    stats["interior_refs_rejected"] = rejected["interior"]
    return out, stats


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join("work", "source", "eboot", "EBOOT.dec.bin")
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join("work", "source", "text", "eboot_strings.json")
    out, stats = dump(src)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for k in sorted(stats):
        print("%-28s %d" % (k, stats[k]))
    print("characters %d -> %s" % (sum(len(e["jp"]) for e in out), dst))


if __name__ == "__main__":
    main()
