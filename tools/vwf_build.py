"""Build the variable-width font (VWF) patch for Macross Triangle Frontier: patched EBOOT + fonts.

Ported from the Macross Ultimate Frontier / Ace Frontier projects (same engine). Triangle
Frontier's text code was rewritten (float pen, shared advance routines), so the patch
sites are new; the 4x mechanism is Ultimate Frontier's. Details: docs/vwf.md.

Usage:
  python tools/vwf_build.py --eboot <EBOOT> [--table-va auto|<hex>] [--out DIR] [--no-hd]
                            [--font F] [--font16 F] [--ttf F] [--ttf-index N]

<EBOOT> is a decrypted EBOOT: the original, or the output of tools/eboot_insert.py run with
--reserve 4096. The two width tables need TABLE_BYTES (1,552) bytes of free, file-backed
memory; eboot_insert writes the reserved address to <EBOOT>.json, which --table-va auto
reads. The rest of the reserve is left for later patches (voice subtitles need 2 KB).

Writes to <out>:
  EBOOT.BIN                                       patched EBOOT (8 bytes per new relocation longer)
  data/extra/gpsp3_font14.fnt                     14 px font, RAIC (the plain macross.dat copy)
  _variants/gameinit/data/extra/gpsp3_font14.fnt  same font, raw (the gameinit bundle member)
  data/extra/mpsp3_font16_slg.fnt                 16 px campus font, RAIC
  vwf_widths.json, vwf_preview*.png
The data/ and _variants/ trees are an overlay for tools/muf_archive.py repack.

How it works:
- English is single-byte ASCII. The printer maps ASCII through the table at 0x3B9ADC (one
  routine, 0x12FD38) to a Shift-JIS code and draws that code's glyph. The 96 codes
  0x20-0x7F are pointed at 96 glyph slots holding rare kanji no game string uses
  (G0..G0+95); our glyphs replace them in both fonts (they share one code list).
- Proportional spacing: the game's bearing tables (descriptor +0x24, used by the small HUD
  fonts) are given to both fonts. Unlike Ultimate / Ace Frontier the font flags stay 0 (the
  text-window code 0x23A594 refuses a font with flags), so the two bearing routines use a
  table whenever the font has one. Two shared routines compute every advance: 0x1300C8
  (float; printer, float width) and 0x1312A8 (int; string width, line truncation). Their
  single-byte branch now calls the bearing routine when the font has a table (helpers in a
  dead function). The glyph-array drawer 0x133788 (lock-on labels) gets Ultimate
  Frontier's advance helper.
- 4x text: each font file gets a 4x page appended (cells of 56 / 64 px). The glyph lookup
  0x132DC0 branches to a dispatcher that, for an English glyph of the 14 or 16 px font,
  points the descriptor's base (+0x3C) at that page and its cells per row (+0x10) at the
  page's, and writes the texture cell size (56 / 64, else the font's own) to +0x18/+0x1A.
  The 36 texture-coordinate loads of +0x08/+0x0C in the five sprite emitters read
  +0x18/+0x1A instead. The sprite keeps its screen size, so only the texture detail changes.
- The EBOOT is a relocatable PRX: no patched word may carry a relocation, jumps are
  PC-relative, and each new table pointer gets an R_MIPS_32 relocation.
"""

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import muf_lzss  # noqa: E402
import vwf_font  # noqa: E402

ASCII_TABLE = 0x3B9ADC    # ASCII 0x20.. -> Shift-JIS code, 2 bytes each (big-endian bytes)
CODES_TABLE = 0x45F02C    # glyph number -> code (descriptor +0x20, both fonts)
GROUP_OFFSETS = 0x462680  # 17 s16: first glyph number of each code group (descriptor +0x1C)
DESC_TABLE = 0x24         # bearing-table pointer in a font descriptor (0x54 bytes)
G0 = 1210                 # group 2, codes 0x9F82..0xE772: 96 kanji that no game string uses


class Font:
    def __init__(self, spec, desc, path, variants):
        self.spec, self.desc, self.path, self.variants = spec, desc, path, variants


# font table 0x4626A4: font14, em, es, en, slg
FONTS = [
    Font(vwf_font.SPEC14, 0x462808, "data/extra/gpsp3_font14.fnt",
         ["_variants/gameinit/data/extra/gpsp3_font14.fnt"]),
    Font(vwf_font.SPEC16, 0x4626B8, "data/extra/mpsp3_font16_slg.fnt", []),
]
TABLE_ENTRY = 8
TABLE_BYTES = len(FONTS) * 97 * TABLE_ENTRY   # per font: guard entry (index -1) + 96
DEFAULT_TTF = os.path.join("work", "fonts", "GenEiLateGo_v2.ttc")  # okoneya.jp, SIL OFL 1.1

# code caves: relocation-free runs inside functions nothing references (tools/find_caves.py)
CAVE_DISPATCH = (0x1309EC, 52)   # in unused 0x130944
CAVE_ADV_F = (0x130944, 21)      # in unused 0x130944
CAVE_ADV_I = (0x13099C, 19)      # in unused 0x130944
CAVE_GLYPH = (0x130D64, 38)      # in unused 0x130CDC

LOOKUP = 0x132DC0                # glyph lookup: addiu sp,-0x30 / sw ra,0x24(sp) (= MUF 0x15787C)
BEARING_F = 0x130014             # (font, char, &L, &R, f12 size): float bearings
BEARING_I = 0x12FF40             # (font, char, size, &L, &R): rounded int bearings

# texture-coordinate loads in the five sprite emitters (0x132F04, 0x13311C, 0x133324,
# 0x1335F4 and 0x1397F8): (vaddr, register, base, offset)
EMITTER_LOADS = [
    (0x132F7C, "v1", "s1", 8), (0x132F88, "t3", "s1", 0xC), (0x132FFC, "v1", "s1", 8),
    (0x133008, "t3", "s1", 0xC), (0x133078, "v1", "s1", 8), (0x133084, "t3", "s1", 0xC),
    (0x1331A0, "v0", "s1", 8), (0x1331A8, "v1", "s1", 0xC), (0x133208, "v1", "s1", 8),
    (0x133210, "t3", "s1", 0xC), (0x133284, "t2", "s1", 8), (0x13328C, "t3", "s1", 0xC),
    (0x1333B4, "v0", "s2", 8), (0x1333BC, "v1", "s2", 0xC), (0x13342C, "v1", "s2", 8),
    (0x133434, "t3", "s2", 0xC), (0x133480, "v1", "s2", 8), (0x13348C, "t3", "s2", 0xC),
    (0x1334E0, "t2", "s2", 8), (0x1334E8, "t3", "s2", 0xC), (0x133554, "t2", "s2", 8),
    (0x13355C, "t3", "s2", 0xC), (0x133658, "t2", "s0", 8), (0x133660, "t3", "s0", 0xC),
    (0x139888, "t3", "s2", 8), (0x139890, "v0", "s2", 0xC), (0x139918, "v0", "s2", 8),
    (0x139920, "v1", "s2", 0xC), (0x1399A4, "t3", "s2", 8), (0x1399AC, "t2", "s2", 0xC),
    (0x139A1C, "v1", "s2", 8), (0x139A24, "t2", "s2", 0xC), (0x139A88, "a0", "s2", 0xC),
    (0x139A90, "t1", "s2", 8), (0x139B00, "t3", "s2", 8), (0x139B08, "v1", "s2", 0xC),
]

# ------------------------------------------------------------- tiny assembler
R = {n: i for i, n in enumerate("zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 "
                                "s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra".split())}


def _r(rs, rt, rd, sa, fn):
    return (R[rs] << 21) | (R[rt] << 16) | (R[rd] << 11) | (sa << 6) | fn


def _i(op, rs, rt, imm):
    return (op << 26) | (R[rs] << 21) | (R[rt] << 16) | (imm & 0xFFFF)


def _off(pc, target):
    off = (target - (pc + 4)) >> 2
    if not -0x8000 <= off < 0x8000:
        raise ValueError("branch out of range %x -> %x" % (pc, target))
    return off


def _cop1(fmt, ft, fs, fd, fn):
    return (0x11 << 26) | (fmt << 21) | (ft << 16) | (fs << 11) | (fd << 6) | fn


NOP = 0
def move(rd, rs): return _r(rs, "zero", rd, 0, 0x21)
def addu(rd, rs, rt): return _r(rs, rt, rd, 0, 0x21)
def subu(rd, rs, rt): return _r(rs, rt, rd, 0, 0x23)
def sll(rd, rt, sa): return _r("zero", rt, rd, sa, 0x00)
def sra(rd, rt, sa): return _r("zero", rt, rd, sa, 0x03)
def mult(rs, rt): return _r(rs, rt, "zero", 0, 0x18)
def div(rs, rt): return _r(rs, rt, "zero", 0, 0x1A)
def mflo(rd): return _r("zero", "zero", rd, 0, 0x12)
def jr(rs): return _r(rs, "zero", "zero", 0, 0x08)
def addiu(rt, rs, imm): return _i(0x09, rs, rt, imm)
def andi(rt, rs, imm): return _i(0x0C, rs, rt, imm)
def ori(rt, rs, imm): return _i(0x0D, rs, rt, imm)
def lui(rt, imm): return _i(0x0F, "zero", rt, imm)
def sltiu(rt, rs, imm): return _i(0x0B, rs, rt, imm)
def lw(rt, off, base): return _i(0x23, base, rt, off)
def lh(rt, off, base): return _i(0x21, base, rt, off)
def lhu(rt, off, base): return _i(0x25, base, rt, off)
def sw(rt, off, base): return _i(0x2B, base, rt, off)
def sh(rt, off, base): return _i(0x29, base, rt, off)
def lwc1(ft, off, base): return (0x31 << 26) | (R[base] << 21) | (ft << 16) | (off & 0xFFFF)
def add_s(fd, fs, ft): return _cop1(0x10, ft, fs, fd, 0x00)
def sub_s(fd, fs, ft): return _cop1(0x10, ft, fs, fd, 0x01)
def mul_s(fd, fs, ft): return _cop1(0x10, ft, fs, fd, 0x02)
def mtc1(rt, fs): return (0x11 << 26) | (0x04 << 21) | (R[rt] << 16) | (fs << 11)
def beq(rs, rt, pc, target): return _i(0x04, rs, rt, _off(pc, target))
def bne(rs, rt, pc, target): return _i(0x05, rs, rt, _off(pc, target))
def b(pc, target): return beq("zero", "zero", pc, target)
def beqz(rs, pc, target): return beq(rs, "zero", pc, target)
def bal(pc, target): return (0x01 << 26) | (0x11 << 16) | (_off(pc, target) & 0xFFFF)


class Asm:
    """Straight-line code with forward labels: emit(word or callable(pc, labels))."""

    def __init__(self, pc):
        self.pc, self.items, self.labels = pc, [], {}

    def __call__(self, w):
        self.items.append(w)

    def label(self, name):
        self.labels[name] = self.pc + 4 * len(self.items)

    def words(self):
        return [w(self.pc + 4 * i, self.labels) if callable(w) else w for i, w in enumerate(self.items)]


# ------------------------------------------------------------- ELF helpers

class Eboot:
    def __init__(self, data):
        self.d = bytearray(data)
        if self.d[:4] != b"\x7fELF":
            raise ValueError("EBOOT is not a decrypted ELF")
        phoff = struct.unpack_from("<I", self.d, 28)[0]
        ph = [struct.unpack_from("<8I", self.d, phoff + 32 * i) for i in range(struct.unpack_from("<H", self.d, 44)[0])]
        self.text_off = ph[0][1]
        self.data_off, self.data_va, self.data_filesz = ph[1][1], ph[1][2], ph[1][4]
        self.reloc_sites = self._reloc_sites()

    def _sections(self):
        shoff = struct.unpack_from("<I", self.d, 32)[0]
        shnum = struct.unpack_from("<H", self.d, 48)[0]
        return shoff, [list(struct.unpack_from("<10I", self.d, shoff + 40 * i)) for i in range(shnum)]

    def _reloc_sites(self):
        _, secs = self._sections()
        sites = set()
        for s in secs:
            if s[1] == 0x700000A0:
                for k in range(s[5] // 8):
                    off, info = struct.unpack_from("<2I", self.d, s[4] + 8 * k)
                    sites.add(off + (self.data_va if (info >> 8) & 0xFF == 1 else 0))
        return sites

    def foff(self, va):
        return va + (self.data_off - self.data_va if va >= self.data_va else self.text_off)

    def word(self, va):
        return struct.unpack_from("<I", self.d, self.foff(va))[0]

    def disasm(self, va):
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
        o = self.foff(va)
        for ins in md.disasm(bytes(self.d[o:o + 4]), va):
            return ("%s %s" % (ins.mnemonic, ins.op_str)).strip()
        return "?"

    def put_word(self, va, w, expect=None):
        if va in self.reloc_sites:
            raise ValueError("refusing to patch relocated word at %x" % va)
        if expect is not None and self.disasm(va) != expect:
            raise ValueError("unexpected instruction at %x: %r (wanted %r)" % (va, self.disasm(va), expect))
        struct.pack_into("<I", self.d, self.foff(va), w)

    def put_bytes(self, va, data):
        for a in range(va & ~3, va + len(data), 4):
            if a in self.reloc_sites:
                raise ValueError("refusing to overwrite relocated word at %x" % a)
        o = self.foff(va)
        self.d[o:o + len(data)] = data

    def append_reloc(self, r_offset, info):
        """Append one PSP relocation to the last relocation section and segment."""
        shoff, secs = self._sections()
        last = max((i for i, s in enumerate(secs) if s[1] == 0x700000A0), key=lambda i: secs[i][4])
        end = secs[last][4] + secs[last][5]
        self.d[end:end] = struct.pack("<2I", r_offset, info)
        for i, s in enumerate(secs):
            if i == last:
                s[5] += 8
            elif s[4] >= end and s[1] != 8:
                s[4] += 8
        shoff += 8
        struct.pack_into("<I", self.d, 32, shoff)
        for i, s in enumerate(secs):
            struct.pack_into("<10I", self.d, shoff + 40 * i, *s)
        phoff = struct.unpack_from("<I", self.d, 28)[0]
        phnum = struct.unpack_from("<H", self.d, 44)[0]
        for i in range(phnum):
            p = list(struct.unpack_from("<8I", self.d, phoff + 32 * i))
            if p[0] == 0x700000A0:
                if p[1] + p[4] != end:
                    raise ValueError("reloc segment does not end where the last reloc section ends")
                p[4] += 8
                struct.pack_into("<8I", self.d, phoff + 32 * i, *p)


# ------------------------------------------------------------- the patch

def glyph_slots(eb):
    offs = struct.unpack_from("<17h", eb.d, eb.foff(GROUP_OFFSETS))
    codes = [struct.unpack_from(">H", eb.d, eb.foff(CODES_TABLE) + 2 * i)[0] for i in range(offs[16])]
    if not (offs[2] <= G0 and G0 + 96 <= offs[3]) or codes[G0] != 0x9F82 or codes[G0 + 95] != 0xE772:
        raise ValueError("glyph code table is not the original one")
    return codes[G0:G0 + 96]


def adv_f_code(pc):
    """Float advance 0x1300C8, single-byte char in a double-byte font. Entered from 0x13016C
    with s0 = char, s1 = font, v1 = flags, f20 = f12 = size, f0 = 0.75. Returns to the
    flag tail 0x130110 with f12 = advance (and v1 = flags)."""
    a = Asm(pc)
    a(lw("at", DESC_TABLE, "s1"))            # font has a width table?
    a(lambda p, L: beqz("at", p, L["orig"]))
    a(move("a0", "s1"))
    a(move("a1", "s0"))
    a(move("a2", "sp"))
    a(lambda p, L: bal(p, BEARING_F))
    a(addiu("a3", "sp", 4))
    a(lwc1(0, 0, "sp"))
    a(lwc1(1, 4, "sp"))
    a(lhu("v1", 0, "s1"))
    a(add_s(0, 0, 1))
    a(lambda p, L: b(p, 0x130110))
    a(sub_s(12, 20, 0))                       # advance = size - (L + R)
    a.label("orig")
    a(lambda p, L: b(p, 0x130110))
    a(mul_s(12, 20, 0))                       # size * 0.75, as before
    return a.words()


def adv_i_code(pc):
    """Int advance 0x1312A8, single-byte char in a double-byte font. Entered from 0x131338
    with a0 = s1 = font, s0 = char, a2 = s2 = size, a3 = flags. Returns to the flag tail
    0x1312F0 with a2 = advance and a3 = flags."""
    a = Asm(pc)
    a(lw("at", DESC_TABLE, "s1"))            # font has a width table?
    a(lambda p, L: beqz("at", p, L["orig"]))
    a(move("a1", "s0"))
    a(move("a3", "sp"))
    a(lambda p, L: bal(p, BEARING_I))
    a(addiu("t0", "sp", 4))
    a(lw("v0", 0, "sp"))
    a(lw("v1", 4, "sp"))
    a(lhu("a3", 0, "s1"))
    a(addu("v0", "v0", "v1"))
    a(lambda p, L: b(p, 0x1312F0))
    a(subu("a2", "s2", "v0"))                 # advance = size - (L + R)
    a.label("orig")
    a(lambda p, L: b(p, 0x13133C))            # back to the original size * 0.75 code
    a(mtc1("a2", 0))                          # the instruction the branch replaced
    return a.words()


def glyph_adv_code(pc):
    """t7 = advance of glyph t7 (0x4000 flag allowed) at size t8, font t9. Uses $at.
    (Ultimate Frontier's helper, with the cell size read from the font.)"""
    a = Asm(pc)
    a(andi("t7", "t7", 0x3FFF))
    a(addiu("t7", "t7", -G0))
    a(sltiu("at", "t7", 96))
    a(lambda p, L: beqz("at", p, L["full"]))
    a(lw("at", DESC_TABLE, "t9"))
    a(lambda p, L: beqz("at", p, L["full"]))
    a(sll("t7", "t7", 3))
    a(addu("at", "at", "t7"))
    a(lw("t7", 0, "at"))                      # L
    a(lw("at", 4, "at"))                      # R
    a(addu("t7", "t7", "at"))
    a(mult("t7", "t8"))
    a(lw("at", 8, "t9"))                      # cell
    a(mflo("t7"))
    a(sra("t9", "at", 1))
    a(addu("t7", "t7", "t9"))
    a(div("t7", "at"))
    a(mflo("t7"))
    a(jr("ra"))
    a(subu("t7", "t8", "t7"))                 # advance = size - round((L+R) * size / cell)
    a.label("full")
    a(jr("ra"))
    a(move("t7", "t8"))
    return a.words()


def code_patches(caves):
    """(vaddr, new word, original instruction as capstone prints it). MUF addresses in comments."""
    p = []

    def at(va, new, orig):
        p.append((va, new, orig))

    # bearing routines 0x12FF40 / 0x130014: use the table whenever the font has one, without
    # flag 0x20 (the campus / operator text window 0x23A594 refuses a font whose flags are not 0)
    at(0x12FF80, addiu("v0", "zero", 0x20), "andi $v0, $v0, 0x20")
    at(0x130054, addiu("v0", "zero", 0x20), "andi $v0, $v0, 0x20")
    # ASCII -> Shift-JIS 0x12FD38 (MUF: inline in the printer, 0x159C2C/34)
    at(0x12FD40, addiu("v0", "zero", 0x100), "addiu $v0, $zero, 0x40")    # '`' is no longer special
    at(0x12FD4C, sltiu("a0", "v1", 0x60), "sltiu $a0, $v1, 0x5b")         # table covers 0x20-0x7F
    # float advance 0x1300C8 (printer pen, float string width; MUF printer 0x159B84)
    at(0x13016C, b(0x13016C, caves["adv_f"]), "andi $a0, $v1, 0xffff")
    at(0x130170, NOP, "andi $v1, $a0, 0x60")
    # int advance 0x1312A8 (string width 0x13150C, line truncation 0x1313FC; MUF 0x15917C, 0x1594FC)
    at(0x131338, b(0x131338, caves["adv_i"]), "mtc1 $a2, $f0")
    # printer 0x131828: '(' '[' drawn at the pen, not half a cell to the left (MUF 0x159ED4)
    at(0x131E90, move("a2", "v1"), "subu $a2, $v1, $a0")
    # glyph-array drawer 0x133788 (lock-on labels; MUF 0x1586B8): half-width glyph drawn
    # full size, advance from the helper (0x1338C4, 0x1338C8, 0x1338E0 carry relocations)
    at(0x1338A4, sw("a0", 0x28, "sp"), "add.s $f0, $f1, $f0")           # keep the font pointer
    at(0x1338B4, NOP, "trunc.w.s $f0, $f0")
    at(0x1338C0, move("t0", "s2"), "mfc1 $t0, $f0")                     # width = size
    at(0x1338CC, lh("t7", -2, "s1"), "mtc1 $zero, $f1")                 # this glyph
    at(0x1338D0, move("t8", "s2"), "mul.s $f2, $f20, $f0")
    at(0x1338D4, bal(0x1338D4, caves["glyph"]), "c.le.s $f1, $f2")
    at(0x1338D8, lw("t9", 0x28, "sp"), "nop")
    at(0x1338DC, b(0x1338DC, 0x1338EC), "bc1f 0x1339f8")
    at(0x1338E4, NOP, "add.s $f0, $f2, $f0")
    at(0x1338E8, NOP, "trunc.w.s $f0, $f0")
    at(0x1338EC, move("v0", "t7"), "mfc1 $v0, $f0")
    return p


def dispatcher_code(pc, hd_offs):
    """Entered from LOOKUP with a0 = font, a1 = glyph, a2/a3 = &column/&row.
    hd_offs: {cell: byte offset of the 4x page in that font's file}."""
    body = LOOKUP + 8
    a = Asm(pc)
    a(addiu("sp", "sp", -0x20))
    a(sw("ra", 0x10, "sp"))
    a(sw("s0", 0x14, "sp"))
    a(move("s0", "a0"))
    a(lw("t0", 8, "a0"))
    a(lw("t1", 0xC, "a0"))
    a(sh("t0", 0x18, "a0"))                   # texture cell = the font's own cell
    a(sh("t1", 0x1A, "a0"))
    a(addiu("t3", "a1", -G0))                 # page-local glyph number
    a(sltiu("t4", "t3", 96))
    a(lambda p, L: beqz("t4", p, L["normal"]))
    first = True
    for spec in (vwf_font.SPEC14, vwf_font.SPEC16):
        off = hd_offs[spec.cell]
        a(addiu("t2", "zero", spec.cell))     # (delay slot of the previous branch)
        a(lui("t8", off >> 16))
        a(ori("t8", "t8", off & 0xFFFF))
        a(addiu("t5", "zero", vwf_font.big(spec)))
        if first:
            a(lambda p, L: beq("t0", "t2", p, L["hd"]))
        else:
            a(lambda p, L: bne("t0", "t2", p, L["normal"]))
        a(addiu("t7", "zero", vwf_font.hd_per_row(spec)))   # (delay slot)
        first = False
    a.label("hd")
    a(sh("t5", 0x18, "a0"))
    a(sh("t5", 0x1A, "a0"))
    a(lw("t6", 0x3C, "a0"))
    a(lw("t9", 0x10, "a0"))
    a(sw("t6", 0x18, "sp"))
    a(sw("t9", 0x1C, "sp"))
    a(addu("t6", "t6", "t8"))
    a(sw("t6", 0x3C, "a0"))                   # base -> the 4x page
    a(sw("t7", 0x10, "a0"))                   # cells per row of the 4x page
    a(move("a1", "t3"))
    a(addiu("sp", "sp", -0x30))               # the two instructions LOOKUP lost
    a(lambda p, L: bal(p, body))
    a(sw("ra", 0x24, "sp"))                   # delay slot: the body returns here
    a(lw("t6", 0x18, "sp"))
    a(lw("t9", 0x1C, "sp"))
    a(sw("t6", 0x3C, "s0"))
    a(lambda p, L: b(p, L["done"]))
    a(sw("t9", 0x10, "s0"))
    a.label("normal")
    a(addiu("sp", "sp", -0x30))
    a(lambda p, L: bal(p, body))
    a(sw("ra", 0x24, "sp"))
    a.label("done")
    a(lw("ra", 0x10, "sp"))
    a(lw("s0", 0x14, "sp"))
    a(jr("ra"))
    a(addiu("sp", "sp", 0x20))
    return a.words()


def put_code(eb, cave, words):
    va, room = cave
    if len(words) > room:
        raise ValueError("code does not fit the cave at 0x%X (%d > %d words)" % (va, len(words), room))
    for i, w in enumerate(words):
        eb.put_word(va + 4 * i, w)
    return len(words)


def hd_patches(eb, hd_offs):
    n = put_code(eb, CAVE_DISPATCH, dispatcher_code(CAVE_DISPATCH[0], hd_offs))
    eb.put_word(LOOKUP, b(LOOKUP, CAVE_DISPATCH[0]), "addiu $sp, $sp, -0x30")
    eb.put_word(LOOKUP + 4, NOP, "sw $ra, 0x24($sp)")
    for va, rt, base, off in EMITTER_LOADS:
        eb.put_word(va, lh(rt, 0x18 if off == 8 else 0x1A, base),
                    "lw $%s, %s($%s)" % (rt, "8" if off == 8 else "0xc", base))
    return n


def read_font(path):
    data = open(path, "rb").read()
    if data[:4] in (muf_lzss.MAGIC, muf_lzss.MAGIC_STORED):
        data = muf_lzss.decode(data)
    return data


def write_file(out, rel, data):
    p = os.path.join(out, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(data)
    return p


def build(eboot_path, table_va, reserved, font_paths, out, weight, ttf, ttf_index, hd):
    eb = Eboot(open(eboot_path, "rb").read())
    codes = glyph_slots(eb)
    if not (eb.data_va <= table_va and table_va + TABLE_BYTES <= eb.data_va + eb.data_filesz):
        raise ValueError("table vaddr 0x%X is not file-backed data" % table_va)
    if any(eb.d[eb.foff(table_va):eb.foff(table_va) + TABLE_BYTES]):
        raise ValueError("table area at 0x%X is not empty (use eboot_insert --reserve)" % table_va)
    if reserved is not None and reserved < TABLE_BYTES:
        raise ValueError("reserve of %d bytes is smaller than the %d the tables need" % (reserved, TABLE_BYTES))

    widths_json = {}
    hd_offs = {}
    samples = [s.replace("…", chr(0x7F)) for s in vwf_font.SAMPLES]
    tva = table_va
    for k, f in enumerate(FONTS):
        spec = f.spec
        if hd:
            glyphs, widths, info, hd_glyphs = vwf_font.build_set(ttf, weight, ttf_index, hd=True, spec=spec)
        else:
            glyphs, widths, info = vwf_font.build_set(ttf, weight, ttf_index, spec=spec)
        # font: our glyphs into slots G0..G0+95, then the 4x page
        font_in = read_font(font_paths[k])
        atlas = vwf_font.read_atlas(font_in, spec)
        for i, g in enumerate(glyphs):
            vwf_font.put_glyph(atlas, G0 + i, g, spec)
        font_bytes = vwf_font.write_atlas(atlas)
        if len(font_bytes) != len(font_in):
            raise ValueError("font %s: unexpected size" % spec.name)
        if hd:
            if len(font_bytes) % 16:
                raise ValueError("font %s: 4x page would not be 16-byte aligned" % spec.name)
            hd_offs[spec.cell] = len(font_bytes)
            font_bytes += vwf_font.hd_page(hd_glyphs, spec)
            info["hd_page_offset"] = hd_offs[spec.cell]
        info["font_bytes"] = len(font_bytes)
        write_file(out, f.path, muf_lzss.encode(font_bytes, "C"))
        for v in f.variants:
            write_file(out, v, font_bytes)

        # width table: guard entry (index -1) + 96 entries (L = 0, R = cell - advance)
        table = struct.pack("<2i", 0, 0) + b"".join(struct.pack("<2i", 0, spec.cell - w) for w in widths)
        eb.put_bytes(tva, table)
        # descriptor: table pointer (value relative to the data segment). The flags stay 0:
        # the text-window code 0x23A594 only takes a font whose flags are 0.
        flags = struct.unpack_from("<H", eb.d, eb.foff(f.desc))[0]
        if flags != 0 or eb.word(f.desc + DESC_TABLE) != 0 or eb.word(f.desc + 8) != spec.cell:
            raise ValueError("font descriptor 0x%X is not the original one" % f.desc)
        eb.put_word(f.desc + DESC_TABLE, tva + TABLE_ENTRY - eb.data_va)
        # R_MIPS_32, word in segment 1 (data), value relative to segment 1
        eb.append_reloc(f.desc + DESC_TABLE - eb.data_va, 2 | (1 << 8) | (1 << 16))
        tva += len(table)

        base = os.path.join(out, "vwf_preview%s" % ("" if spec.cell == 14 else "_%d" % spec.cell))
        vwf_font.preview(base + ".png", glyphs, widths, samples, spec=spec)
        if hd:
            vwf_font.hd_preview(base + "_hd.png", hd_glyphs, widths, samples, spec=spec)
        widths_json[spec.cell] = (info, widths)
        print("%-22s glyph slots %d-%d, %s" % (spec.name, G0, G0 + 95, info))

    # ASCII -> code table
    if eb.d[eb.foff(ASCII_TABLE):eb.foff(ASCII_TABLE) + 4] != b"\x81\x40\x81\x49":
        raise ValueError("ASCII table is not the original one")
    eb.put_bytes(ASCII_TABLE, b"".join(struct.pack(">H", c) for c in codes))

    caves = {"adv_f": CAVE_ADV_F[0], "adv_i": CAVE_ADV_I[0], "glyph": CAVE_GLYPH[0]}
    used = [put_code(eb, CAVE_ADV_F, adv_f_code(CAVE_ADV_F[0])),
            put_code(eb, CAVE_ADV_I, adv_i_code(CAVE_ADV_I[0])),
            put_code(eb, CAVE_GLYPH, glyph_adv_code(CAVE_GLYPH[0]))]
    for va, w, orig in code_patches(caves):
        eb.put_word(va, w, orig)
    print("helpers: %d words at 0x%X, %d at 0x%X, %d at 0x%X"
          % (used[0], CAVE_ADV_F[0], used[1], CAVE_ADV_I[0], used[2], CAVE_GLYPH[0]))
    if hd:
        n = hd_patches(eb, hd_offs)
        print("4x text: pages at %s, dispatcher %d words at 0x%X, %d emitter loads"
              % (", ".join("0x%X (%d px)" % (o, c) for c, o in sorted(hd_offs.items())), n,
                 CAVE_DISPATCH[0], len(EMITTER_LOADS)))

    os.makedirs(out, exist_ok=True)
    eboot_out = os.path.join(out, "EBOOT.BIN")
    open(eboot_out, "wb").write(eb.d)
    i14, w14 = widths_json[14]
    i16, w16 = widths_json[16]
    json.dump({"info": i14, "glyph_base": G0, "table_vaddr": table_va, "table_bytes": TABLE_BYTES,
               "codes": ["%04X" % c for c in codes], "advance": w14,
               "font16": {"info": i16, "advance": w16}},
              open(os.path.join(out, "vwf_widths.json"), "w"), indent=1)
    left = None if reserved is None else reserved - TABLE_BYTES
    print("width tables: %d bytes at 0x%X%s" % (TABLE_BYTES, table_va,
                                                  "" if left is None else ", %d bytes of the reserve left" % left))
    if left is not None and left < 2048:
        print("warning: less than 2 KB of the reserve left for later patches (use --reserve 4096)")
    print("wrote", eboot_out, "and the font overlay in", out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eboot", required=True)
    ap.add_argument("--table-va", default="auto", help="vaddr of %d free bytes, or 'auto' (<eboot>.json)" % TABLE_BYTES)
    ap.add_argument("--font", default=os.path.join("work", "source", "dat", "data", "extra", "gpsp3_font14.fnt"))
    ap.add_argument("--font16", default=os.path.join("work", "source", "dat", "data", "extra", "mpsp3_font16_slg.fnt"))
    ap.add_argument("--out", default=os.path.join("work", "output", "vwf"))
    ap.add_argument("--weight", type=int, default=vwf_font.DEFAULT_WEIGHT)
    ap.add_argument("--ttf", default=DEFAULT_TTF)
    ap.add_argument("--ttf-index", type=int, default=0)
    ap.add_argument("--no-hd", action="store_true", help="native glyphs only (no 4x pages)")
    a = ap.parse_args()
    reserved = None
    if a.table_va == "auto":
        info = json.load(open(a.eboot + ".json"))
        tva, reserved = info["reserved_vaddr"], info.get("reserved_bytes")
        if not tva:
            sys.exit("no reserved space in %s.json: run eboot_insert.py --reserve 4096" % a.eboot)
    else:
        tva = int(a.table_va, 16)
    build(a.eboot, tva, reserved, [a.font, a.font16], a.out, a.weight, a.ttf, a.ttf_index, hd=not a.no_hd)


if __name__ == "__main__":
    main()
