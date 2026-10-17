"""Write translated text into the decrypted EBOOT by relocating the strings.

Usage:
  python tools/eboot_insert.py [options] [<translation.json> ...]
    --eboot PATH   decrypted EBOOT     (default work/source/eboot/EBOOT.dec.bin)
    --dump PATH    tools/dump_eboot.py output (default work/source/text/eboot_strings.json)
    --out PATH     patched EBOOT       (default work/output/EBOOT.BIN)
    --expand N     open N x 64 KB for text between .data and .bss
                   (default: as many as the text needs, 0 if it fits)
    --move-all     also relocate every untranslated string with its Japanese
                   bytes (a relocation test: the game must look unchanged)
    --gap-only     put moved text only in the new gap (test of the .bss shift)
    --dry-run      plan and verify, write nothing

Translation files are JSON lists (or {"rows": [...]}) of rows with "id"
("eboot:<file offset>", as in eboot_strings.json and dialogue.json) and "en".
Rows with other ids or without "en" are ignored. The English is written in
Shift-JIS (ASCII stays one byte; the game draws it with full-width glyphs, see
docs/formats.md "Rendering ASCII").

What it does (docs/formats.md "Relocating EBOOT strings"):
  - strings with references move; in-place-only strings (pilot table, inline
    copies) are rewritten in place and must fit their capacity
  - free space = the old slots of moved strings (4-byte aligned, never a slot
    with an address referenced inside it), then the new gap
  - pointer words get the new address, lui/addiu pairs get new immediates,
    relocation entries get the new segment, and every patched HI16 entry is
    moved in front of its own LO16 so the loader's carry is right
  - the gap: .sbss/.bss move up by N x 64 KB, so only HI16 immediates and
    pointer words into .bss change (no LO16 does)
  - check: the PSP loader is simulated (base 0x08804000) on the original and
    the patched file, and every resolved reference must land where expected
"""

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dump_eboot import (Elf, analyze, sext16, ENCODING, LOAD_BASE, PT_LOAD, PT_PRX_RELOC,  # noqa: E402
                        R_MIPS_32, R_MIPS_26, R_MIPS_HI16, R_MIPS_LO16)

CHUNK = 0x10000
ALIGN = 4


def align(x, a=ALIGN):
    return (x + a - 1) // a * a


def load_translations(paths):
    out = {}
    for p in paths:
        rows = json.load(open(p, encoding="utf-8"))
        if isinstance(rows, dict):
            rows = rows.get("rows", [])
        for r in rows:
            if str(r.get("id", "")).startswith("eboot:") and r.get("en"):
                out[r["id"]] = r["en"]
    return out


class Patcher:
    def __init__(self, elf, A, entries):
        self.elf, self.A, self.entries = elf, A, entries
        self.img = bytearray(elf.data)
        self.segs = [v for v, _, _ in elf.loads]
        seg1 = self.segs[1]
        self.seg1 = seg1
        self.data_end = max(a + n for name, a, n, f in elf.sections if a >= seg1)  # end of .data*
        self.boundary = align(self.data_end)  # first .bss-side address
        self.bss_start = min(s for s in self._nobits())
        # relocation table as mutable [r_offset, info] in order
        ph = [p for p in elf.phdrs if p[0] == PT_PRX_RELOC][0]
        self.rel_off, self.rel_size = ph[1], ph[4]
        self.table = [list(struct.unpack_from("<II", elf.data, i))
                      for i in range(ph[1], ph[1] + ph[4], 8)]
        self.index = {}
        for i, (r_offset, info) in enumerate(self.table):
            where = self.segs[(info >> 8) & 0xFF] + r_offset
            self.index[where, info & 0xFF] = i
        self.reorder = {}  # HI16 table index -> LO16 table index it must precede

    def _nobits(self):
        e = self.elf
        _, _, _, _, _, shoff, _, _, _, _, shentsize, shnum, _ = struct.unpack_from("<HHIIIIIHHHHHH", e.data, 16)
        for i in range(shnum):
            s = struct.unpack_from("<10I", e.data, shoff + i * shentsize)
            if s[1] == 8 and s[2] & 2:
                yield s[3]

    def word(self, v):
        return struct.unpack_from("<I", self.img, self.elf.off(v))[0]

    def put(self, v, w):
        struct.pack_into("<I", self.img, self.elf.off(v), w & 0xFFFFFFFF)

    def set_imm(self, v, imm):
        self.put(v, (self.word(v) & 0xFFFF0000) | (imm & 0xFFFF))

    def set_seg(self, where, typ, seg):
        i = self.index[where, typ]
        self.table[i][1] = (self.table[i][1] & ~0xFF0000) | (seg << 16)

    # --- the .bss shift ----------------------------------------------------
    def shift_bss(self, S):
        A, seg1, B = self.A, self.seg1, self.boundary
        hi_step = S >> 16
        moved_hi = moved_ptr = 0
        for a in A.ptrs:
            if A.base[a, R_MIPS_32] == seg1 and self.word(a) + seg1 >= B:
                self.put(a, self.word(a) + S)
                moved_ptr += 1
        for h in A.his:
            if A.base[h, R_MIPS_HI16] != seg1:
                continue
            sides = {A.lo_target[u] >= B for u in A.hi_users.get(h, ())}
            if sides == {True}:
                self.set_imm(h, self.word(h) + hi_step)
                moved_hi += 1
            elif len(sides) > 1:
                sys.exit("HI16 at %#x reaches both .data and .bss; cannot shift" % h)
            elif not sides:  # no paired LO16: decide by the 64 KB window it can reach
                lo_edge = ((self.word(h) & 0xFFFF) << 16) + seg1 - 0x8000
                if lo_edge >= B:
                    self.set_imm(h, self.word(h) + hi_step)
                    moved_hi += 1
                elif lo_edge + 0x10000 > B:
                    sys.exit("unpaired HI16 at %#x may point into .bss; cannot shift" % h)
        return moved_hi, moved_ptr

    # --- assemble the ELF ----------------------------------------------------
    def build(self, S, gap_used):
        e = self.elf
        img = self.img
        # relocation table back into the image (with HI16 entries reordered)
        order = [i for i in range(len(self.table)) if i not in self.reorder]
        before = {}
        for h, lo in self.reorder.items():
            before.setdefault(lo, []).append(h)
        out = []
        for i in order:
            out.extend(before.get(i, []))
            out.append(i)
        assert len(out) == len(self.table)
        for k, i in enumerate(out):
            struct.pack_into("<II", img, self.rel_off + 8 * k, *self.table[i])
        if not S:
            return bytes(img)
        seg1_ph = [p for p in e.phdrs if p[0] == PT_LOAD][1]
        file_end1 = seg1_ph[1] + seg1_ph[4]
        insert_at = self.rel_off  # everything from the relocation table on moves by `grow`
        new_filesz = (self.bss_start + S) - self.seg1
        grow = seg1_ph[1] + new_filesz - insert_at
        assert grow >= S and grow % ALIGN == 0
        new = img[:file_end1] + bytes(insert_at + grow - file_end1) + img[insert_at:]
        # gap contents were written into self.gap
        go = seg1_ph[1] + self.boundary - self.seg1
        new[go:go + len(gap_used)] = gap_used
        # ELF header: section header offset
        (shoff,) = struct.unpack_from("<I", new, 0x20)
        struct.pack_into("<I", new, 0x20, shoff + grow)
        phoff, phentsize, phnum = struct.unpack_from("<I", new, 0x1C)[0], *struct.unpack_from("<HH", new, 0x2A)
        for i in range(phnum):
            o = phoff + i * phentsize
            p = list(struct.unpack_from("<8I", new, o))
            if p[0] == PT_LOAD and p[2] == self.seg1:
                p[4], p[5] = new_filesz, p[5] + S
            elif p[1] >= insert_at:
                p[1] += grow
            struct.pack_into("<8I", new, o, *p)
        shentsize, shnum = struct.unpack_from("<HH", new, 0x2E)
        for i in range(shnum):
            o = shoff + grow + i * shentsize
            s = list(struct.unpack_from("<10I", new, o))
            if s[1] == 8 and s[3] >= self.boundary:  # NOBITS after .data
                s[3] += S
                s[4] += grow
            elif s[4] >= insert_at:
                s[4] += grow
            struct.pack_into("<10I", new, o, *s)
        return bytes(new)


def plan_and_patch(elf, A, entries, tr, move_all, expand, gap_only=False, reserve=0):
    P = Patcher(elf, A, entries)
    seg0, seg1 = P.segs
    report = {"inplace": 0, "moved": 0, "errors": []}

    # what goes where
    inplace, move = [], []
    for e in entries:
        new = tr.get(e["id"])
        raw = new.encode(ENCODING) if new is not None else None
        if raw is not None and b"\0" in raw:
            report["errors"].append("%s: NUL in text" % e["id"])
            continue
        in_place_only = not e["refs"] or e.get("inline_copy") or e.get("in_place")
        if in_place_only:
            if raw is not None:
                if len(raw) + 1 > e["capacity"]:
                    report["errors"].append("%s: %d bytes, only %d in place" % (e["id"], len(raw) + 1, e["capacity"]))
                else:
                    inplace.append((e, raw))
            continue
        if raw is None and move_all:
            raw = e["jp"].encode(ENCODING)
        if raw is not None:
            move.append((e, raw))
    if report["errors"]:
        return None, report

    # free slots: old homes of moved strings
    moving = {e["vaddr"] for e, _ in move}
    slots = []
    for e, _ in move:
        if "inner_refs" in e:  # something points inside: the old bytes stay
            continue
        slots.append([e["vaddr"], align(e["vaddr"] + e["bytes"] + 1)])
    slots.sort()
    merged = []
    for a, b in slots:
        if merged and merged[-1][1] >= a:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    free_old = sum(b - a for a, b in merged)

    # place, largest first, sharing identical text
    order = sorted(move, key=lambda m: -len(m[1]))
    where, by_text = {}, {}
    gap = bytearray()
    for e, raw in order:
        if raw in by_text:
            where[e["vaddr"]] = by_text[raw]
            continue
        need = len(raw) + 1
        best = None
        for s in ([] if gap_only else merged):
            room = s[1] - s[0]
            if room >= need and (best is None or room < best[1] - best[0]):
                best = s
        if best is not None:
            addr = best[0]
            best[0] = align(best[0] + need)
        else:
            addr = P.boundary + len(gap)
            gap += raw + b"\0"
            gap += bytes(align(len(gap)) - len(gap))
        where[e["vaddr"]] = addr
        by_text[raw] = addr
    if reserve:  # zeroed room for other patches (the VWF width table), 16-byte aligned
        gap += bytes((-(P.boundary + len(gap))) % 16)
        report["reserved"] = (P.boundary + len(gap), reserve)
        gap += bytes(reserve)
    spare = P.bss_start - P.boundary  # padding before .sbss, usable once file-backed
    need_chunks = max(1, (len(gap) - spare + CHUNK - 1) // CHUNK) if gap else 0
    S = (need_chunks if expand is None else expand) * CHUNK
    if gap and len(gap) > spare + S or gap and not S:
        report["errors"].append("text needs %d bytes past the old slots; --expand %d is too small"
                                % (len(gap), S // CHUNK))
        return None, report

    # 1. .bss shift (decided on the original references)
    if S:
        report["shift_hi16"], report["shift_ptr"] = P.shift_bss(S)

    # 2. clear old slots of moved strings, write in-place text
    for a, b in slots:
        P.img[elf.off(a):elf.off(b)] = bytes(b - a)
    for e, raw in inplace:
        o = e["offset"]
        P.img[o:o + e["bytes"] + 1] = bytes(e["bytes"] + 1)
        P.img[o:o + len(raw)] = raw
        report["inplace"] += 1

    # 3. moved text in the old slots (gap text is placed by build())
    for e, raw in move:
        addr = where[e["vaddr"]]
        if addr < P.boundary:
            o = elf.off(addr)
            P.img[o:o + len(raw) + 1] = raw + b"\0"

    # 4. repoint references
    for e, raw in move:
        addr = where[e["vaddr"]]
        k = 1 if addr >= seg1 else 0
        rel = addr - P.segs[k]
        for r in e["refs"]:
            if r["kind"] == "ptr":
                P.put(r["vaddr"], rel)
                P.set_seg(r["vaddr"], R_MIPS_32, k)
                continue
            P.set_imm(r["lo"], rel)
            P.set_seg(r["lo"], R_MIPS_LO16, k)
            for h in r["hi"]:
                P.set_imm(h, (rel + 0x8000) >> 16)
                P.set_seg(h, R_MIPS_HI16, k)
                if A.order_lo[h] != r["lo"]:
                    P.reorder[P.index[h, R_MIPS_HI16]] = P.index[r["lo"], R_MIPS_LO16]
        report["moved"] += 1

    report.update(free_old=free_old, gap_bytes=len(gap), expand=S // CHUNK,
                  in_old_slots=sum(1 for v in where.values() if v < P.boundary),
                  in_gap=sum(1 for v in where.values() if v >= P.boundary))
    return (P.build(S, bytes(gap)), where, S, P), report


# --- verification: simulate the PSP loader --------------------------------

def load_image(data, base=LOAD_BASE):
    """Relocate like the PSP/PPSSPP loader. Returns (elf, image bytes by vaddr)."""
    elf = Elf(data)
    segs = [v for v, _, _ in elf.loads]
    mem = bytearray(max(v + n for v, _, n in elf.loads))
    for v, o, n in elf.loads:
        mem[v:v + n] = data[o:o + n]
    ph = [p for p in elf.phdrs if p[0] == PT_PRX_RELOC][0]
    tab = [struct.unpack_from("<II", data, i) for i in range(ph[1], ph[1] + ph[4], 8)]
    orig = bytes(mem)
    next_lo, nxt = [None] * len(tab), None  # the loader pairs a HI16 with the next LO16
    for n in range(len(tab) - 1, -1, -1):
        next_lo[n] = nxt
        if tab[n][1] & 0xFF == R_MIPS_LO16:
            nxt = n

    def rd(m, a):
        return struct.unpack_from("<I", m, a)[0]
    for n, (r_offset, info) in enumerate(tab):
        t = info & 0xFF
        a = segs[(info >> 8) & 0xFF] + r_offset
        to = base + segs[(info >> 16) & 0xFF]
        w = rd(mem, a)
        if t == R_MIPS_32:
            w += to
        elif t == R_MIPS_26:
            w = (w & 0xFC000000) | ((w + (to >> 2)) & 0x03FFFFFF)
        elif t == R_MIPS_HI16:
            lo = 0
            if next_lo[n] is not None:
                r2, i2 = tab[next_lo[n]]
                lo = sext16(rd(orig, segs[(i2 >> 8) & 0xFF] + r2) & 0xFFFF)
            full = ((w & 0xFFFF) << 16) + lo + to
            w = (w & 0xFFFF0000) | (((full - sext16(full & 0xFFFF)) >> 16) & 0xFFFF)
        elif t == R_MIPS_LO16:
            w = (w & 0xFFFF0000) | ((w + to) & 0xFFFF)
        struct.pack_into("<I", mem, a, w & 0xFFFFFFFF)
    return mem


def verify(orig_data, new_data, A, where, S, boundary, expect_text):
    """Every resolved reference must land on the same object as before (moved
    strings at their new home, .bss shifted by S)."""
    m0, m1 = load_image(orig_data), load_image(new_data)

    def rd(m, a):
        return struct.unpack_from("<I", m, a)[0]

    def code_addr(m, lo, his):
        return {((rd(m, h) & 0xFFFF) << 16) + sext16(rd(m, lo) & 0xFFFF) for h in his}

    def expected(target):
        link = target - LOAD_BASE
        if link in where:
            return where[link] + LOAD_BASE
        if link >= boundary:
            return target + S
        return target
    bad = []
    for a in A.ptrs:
        if rd(m1, a) != expected(rd(m0, a)):
            bad.append("ptr %#x: %#x -> %#x" % (a, rd(m0, a), rd(m1, a)))
    for lo, his in A.lo_his.items():
        if not his:
            continue
        t0, t1 = code_addr(m0, lo, his), code_addr(m1, lo, his)
        if len(t0) != 1 or {expected(x) for x in t0} != t1:
            bad.append("code %#x: %s -> %s" % (lo, [hex(x) for x in t0], [hex(x) for x in t1]))
    for old, raw in expect_text.items():
        a = where.get(old, old)
        got = bytes(m1[a:a + len(raw) + 1])
        if got != raw + b"\0":
            bad.append("text at %#x (was %#x) differs" % (a, old))
    return bad


def main():
    args = sys.argv[1:]

    def opt(name, default=None):
        if name in args:
            i = args.index(name)
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default
    eboot = opt("--eboot", os.path.join("work", "source", "eboot", "EBOOT.dec.bin"))
    dump = opt("--dump", os.path.join("work", "source", "text", "eboot_strings.json"))
    out = opt("--out", os.path.join("work", "output", "EBOOT.BIN"))
    expand = opt("--expand")
    expand = int(expand) if expand is not None else None
    reserve = int(opt("--reserve", "0"))
    move_all = "--move-all" in args
    dry = "--dry-run" in args
    files = [a for a in args if not a.startswith("--")]

    data = open(eboot, "rb").read()
    elf = Elf(data)
    entries = json.load(open(dump, encoding="utf-8"))
    for e in entries:
        if data[e["offset"]:e["offset"] + e["bytes"]] != e["jp"].encode(ENCODING):
            sys.exit("%s does not match %s; run tools/dump_eboot.py again" % (dump, eboot))
    tr = load_translations(files)
    known = {e["id"] for e in entries}
    unknown = sorted(set(tr) - known)
    if unknown:
        print("ignored %d ids not in the dump (e.g. %s)" % (len(unknown), unknown[0]))
    A = analyze(elf)
    res, report = plan_and_patch(elf, A, entries, tr, move_all, expand, "--gap-only" in args, reserve)
    for err in report["errors"]:
        print("ERROR", err)
    if res is None:
        sys.exit(1)
    new, where, S, P = res
    expect = {}
    by_id = {e["id"]: e for e in entries}
    for e in entries:
        if e["id"] in tr:
            expect[e["vaddr"]] = tr[e["id"]].encode(ENCODING)
        elif e["vaddr"] in where:
            expect[e["vaddr"]] = e["jp"].encode(ENCODING)
    bad = verify(data, new, A, where, S, P.boundary, expect)
    for k in ("moved", "inplace", "in_old_slots", "in_gap", "free_old", "gap_bytes", "expand",
              "shift_hi16", "shift_ptr"):
        if k in report:
            print("%-14s %s" % (k, report[k]))
    print("translated     %d of %d strings" % (len(set(tr) & known), len(by_id)))
    print("size           %d -> %d bytes" % (len(data), len(new)))
    if bad:
        print("VERIFY FAILED: %d references" % len(bad))
        for b in bad[:20]:
            print("  " + b)
        sys.exit(1)
    print("verify         ok (loader simulated; all paired references land on their object)")
    if "reserved" in report:
        print("reserved       %d bytes at vaddr 0x%X" % (report["reserved"][1], report["reserved"][0]))
    if not dry:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        open(out, "wb").write(new)
        print("wrote", out)
        info = {"reserved_vaddr": report.get("reserved", [None])[0], "reserved_bytes": reserve,
                "expand_chunks": report.get("expand", 0)}
        json.dump(info, open(out + ".json", "w"), indent=1)


if __name__ == "__main__":
    main()
