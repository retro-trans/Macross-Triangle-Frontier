"""EBOOT patch: English subtitles for the in-mission voice clips (docs/voice_subtitles.md).

Usage:
  python tools/voice_subs_patch.py <in EBOOT.BIN> <out EBOOT.BIN> --area <EBOOT.ins.bin.json>

Ported from Macross Ace Frontier / Ultimate Frontier (same hooks, same
layout; Triangle Frontier's routines were found again from MUF's, see
docs/voice_subtitles.md "EBOOT hooks").

Run it on the EBOOT that went through tools/eboot_insert.py --reserve 4096 and
tools/vwf_build.py (English needs the VWF font). Code, buffers and config go in
the zeroed room eboot_insert reserves in the gap it opens between .data and
.bss: the two VWF width tables take the first VWF_RESERVE bytes, this patch the
next AREA_SIZE (`reserved_vaddr` in the .json eboot_insert writes). The gap is
part of the file-backed data segment; the PSP has no execute protection.

Where the line comes from
  Each subtitle is stored at the end of its own voice clip,
  data/sound/voice/<speaker>/<num>.at3 in macross.dat (tools/voice_subs_at3.py):

      ... ATRAC3 RIFF file ... | part 1 NUL [part 2 NUL ...] | u16 len | u16 parts | "SB"

When it is read
  The mission script queues a radio line by loading the clip's lip-sync file
  data/sound/vad/<speaker>/<num>.vad into one of two voice slots, with the
  exact-size reader 0x1D370: 0x17A538 fills slot 0, 0x17AFDC slot 1. Both calls
  go to READ_HOOK, which makes that same call, then builds
  data/sound/voice/<speaker>/<num>.at3 (the id is everything between
  "data/sound/vad/" and the first "."), normalises it (0x306BC), looks it up in
  the macross.dat index (0x33D38) and reads only the last TAIL bytes of the clip
  (0x327E0, read at an offset). With an "SB" tail it keeps a pointer to the line
  for that slot. Voice clips are stored raw in macross.dat (stored length 0).

When it is shown
  The game counts a slot's frames (0x17875C) only while its clip plays, from 0
  up to total / step (the .vad's u32 at +0 and u16 at +6); the counters are
  words at slot 0 - 8 and - 4 (-1 when idle). A slot's line shows while its
  counter runs and HOLD frames after. Part i of n shows from i/n of the clip on.

  The mission's 2D layer (0x11ABD4) calls the cut-in module step 0x179FCC at
  0x11AC00. That call goes to DRAW_HOOK, which runs it and then draws the line
  with the game's fit-to-width text routine 0x132724, first in the shadow colour
  1 px down-right, then in the text colour. Box, size, colours and depth are 9
  config words at CFG, so a layout can be tried live in the debugger.

Relocations
  The three replaced words are `jal` with an R_MIPS_26 relocation, which stays
  valid for the new target (the gap is loaded at its link offset like the rest
  of the image). The new code carries no relocation: it finds its load address
  with `bal`. The slot address comes from the game's own call.
"""

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vwf_build import Eboot, R, TABLE_BYTES  # noqa: E402

VWF_RESERVE = (TABLE_BYTES + 15) & ~15       # first part of the reserved room: the two VWF width tables (1,552)
AREA_SIZE = 2048                             # this patch: code, buffers, state, config
READ_WORDS, DRAW_WORDS = 144, 128            # room for READ_HOOK / DRAW_HOOK
TAIL = 0xB8                                  # bytes read from the end of a clip
B_INFO = 0x00                                # lookup result: container path, offset, size, packed
B_READ = (0x18, 0x18 + TAIL)                 # tail of the clip in slot 0 / slot 1
B_SLOT0 = 0x190                              # run-time address of lip-sync slot 0
B_TEXT = 0x194                               # 2 words: the line of slot 0 / 1 (0 = none)
B_HOLD = 0x19C                               # 2 halfwords: part shown (high byte), frames left (low byte)
B_PARTS = 0x1A0                              # 2 halfwords: number of parts
B_CFG = 0x1A8                                # 9 config words
B_END = B_CFG + 9 * 4
assert B_READ[1] + TAIL <= B_SLOT0
HOLD = 24                                    # frames the line stays after the voice ends (< 256)

READ_SITES = [0x17A538, 0x17AFDC]            # jal 0x1D370: the clip's .vad, slot 0 / slot 1
DRAW_SITES = [0x11AC00]                      # jal 0x179FCC: cut-in step in the mission's 2D layer
SLOT_SIZE = 0x30                             # lip-sync slots are 0x30 bytes apart;
COUNTER = -8                                 # their frame counters are words at slot 0 - 8 + 4k
F_READ_EXACT = 0x1D370     # (path, buf, size) -> 1 if the file has exactly `size` bytes   (MUF 0x21A00)
F_NORMALIZE = 0x306BC      # (dst, src, max): the path form the archive index uses         (MUF 0x37C60)
F_LOOKUP = 0x33D38         # (path, info) -> 0 if not in macross.dat                       (MUF 0x3A9B8)
F_READ_AT = 0x327E0        # (container, buf, offset, size, 1) -> <0 on error              (MUF 0x39560)
F_LAYER_END = 0x179FCC     # cut-in module step; takes no arguments                       (MUF 0x1A024C)
F_TEXT = 0x132724          # (MUF 0x15ABC0) fit-to-width text routine:
#                            (str, x, y, size, size2, box w, z, colour, [sp0] font, [sp4] align, [sp8] line step)
VOICE_DIR = 0x403A30       # "data/sound/voice/" in .rodata
VAD_PREFIX_LEN = len("data/sound/vad/")

# set by layout(): link addresses inside the reserved area
READ_CAVE = DRAW_CAVE = BUF = CFG = None


def layout(area):
    global READ_CAVE, DRAW_CAVE, BUF, CFG
    READ_CAVE = (area, area + READ_WORDS * 4)
    DRAW_CAVE = (READ_CAVE[1], READ_CAVE[1] + DRAW_WORDS * 4)
    BUF = DRAW_CAVE[1]
    CFG = BUF + B_CFG
    assert BUF + B_END <= area + AREA_SIZE


# x, y, size, box width, alignment mode (0 = centred on (x, y) both ways, 3 = centred on x below y,
# 2 = left from x, 1 = right-aligned at x). The box (x 124-356) sits between the HP bars and the
# weapons panel; the game shrinks a line that is wider than the box.
# colour (ABGR), shadow colour, line step (0 = size * 1.25), sprite depth (z: 0xFFFF is nearest,
# so the line also shows over the "enemy appeared" banners)
CONFIG = [240, 228, 12, 232, 0, 0xFFFFFFFF, 0xFF000000, 13, 0xFFFF]


class Asm:
    """Two-pass MIPS assembler for the few instructions we need."""

    def __init__(self, base):
        self.base, self.items, self.labels = base, [], {}

    def label(self, name):
        self.labels[name] = self.base + 4 * len(self.items)

    def op(self, fn):
        self.items.append(fn)

    def assemble(self):
        return [fn(self.base + 4 * i, self.labels) & 0xFFFFFFFF for i, fn in enumerate(self.items)]


def _r(rs, rt, rd, sa, fn):
    return (R[rs] << 21) | (R[rt] << 16) | (R[rd] << 11) | (sa << 6) | fn


def _i(op, rs, rt, imm):
    return (op << 26) | (R[rs] << 21) | (R[rt] << 16) | (imm & 0xFFFF)


def _br(pc, labels, target):
    off = (labels[target] - (pc + 4)) >> 2
    if not -0x8000 <= off < 0x8000:
        raise ValueError("branch out of range")
    return off & 0xFFFF


def addiu(rt, rs, imm): return lambda pc, L: _i(0x09, rs, rt, imm)
def slti(rt, rs, imm): return lambda pc, L: _i(0x0A, rs, rt, imm)
def andi(rt, rs, imm): return lambda pc, L: _i(0x0C, rs, rt, imm)
def ori(rt, rs, imm): return lambda pc, L: _i(0x0D, rs, rt, imm)
def lui(rt, imm): return lambda pc, L: _i(0x0F, "zero", rt, imm)
def lw(rt, off, base): return lambda pc, L: _i(0x23, base, rt, off)
def lbu(rt, off, base): return lambda pc, L: _i(0x24, base, rt, off)
def lhu(rt, off, base): return lambda pc, L: _i(0x25, base, rt, off)
def sw(rt, off, base): return lambda pc, L: _i(0x2B, base, rt, off)
def sh(rt, off, base): return lambda pc, L: _i(0x29, base, rt, off)
def sb(rt, off, base): return lambda pc, L: _i(0x28, base, rt, off)
def addu(rd, rs, rt): return lambda pc, L: _r(rs, rt, rd, 0, 0x21)
def subu(rd, rs, rt): return lambda pc, L: _r(rs, rt, rd, 0, 0x23)
def or_(rd, rs, rt): return lambda pc, L: _r(rs, rt, rd, 0, 0x25)
def slt(rd, rs, rt): return lambda pc, L: _r(rs, rt, rd, 0, 0x2A)
def sll(rd, rt, sa): return lambda pc, L: _r("zero", rt, rd, sa, 0x00)
def srl(rd, rt, sa): return lambda pc, L: _r("zero", rt, rd, sa, 0x02)
def multu(rs, rt): return lambda pc, L: _r(rs, rt, "zero", 0, 0x19)
def mflo(rd): return lambda pc, L: _r("zero", "zero", rd, 0, 0x12)
def jr(rs): return lambda pc, L: _r(rs, "zero", "zero", 0, 0x08)
def jalr(rs): return lambda pc, L: _r(rs, "zero", "ra", 0, 0x09)
def move(rd, rs): return addu(rd, rs, "zero")
def nop(): return lambda pc, L: 0
def beq(rs, rt, t): return lambda pc, L: _i(0x04, rs, rt, _br(pc, L, t))
def bne(rs, rt, t): return lambda pc, L: _i(0x05, rs, rt, _br(pc, L, t))
def blez(rs, t): return lambda pc, L: _i(0x06, rs, "zero", _br(pc, L, t))
def bltz(rs, t): return lambda pc, L: (0x01 << 26) | (R[rs] << 21) | _br(pc, L, t)
def bal(t): return lambda pc, L: (0x01 << 26) | (0x11 << 16) | _br(pc, L, t)
def b(t): return beq("zero", "zero", t)


def li32(a, reg, value):
    a.op(lui(reg, (value >> 16) & 0xFFFF))
    a.op(ori(reg, reg, value & 0xFFFF))


def runtime(a, reg, link_addr, delta):
    """reg = run-time address of `link_addr` (delta = load delta)."""
    li32(a, reg, link_addr)
    a.op(addu(reg, reg, delta))


def call(a, delta, target):
    """jalr to link address `target`; the next op is the delay slot."""
    runtime(a, "t9", target, delta)
    a.op(jalr("t9"))


def prologue(a, here, delta, frame):
    """Save ra/s0-s3 at the top of a `frame`-byte frame, put the load delta in `delta`."""
    a.op(addiu("sp", "sp", -frame))
    a.op(sw("ra", frame - 4, "sp"))
    a.op(sw("s0", frame - 20, "sp"))
    a.op(sw("s1", frame - 16, "sp"))
    a.op(sw("s2", frame - 12, "sp"))
    a.op(sw("s3", frame - 8, "sp"))
    a.op(bal(here))
    a.op(nop())
    a.label(here)
    li32(a, "at", a.labels[here])
    a.op(subu(delta, "ra", "at"))


def epilogue(a, frame):
    a.op(lw("ra", frame - 4, "sp"))
    a.op(lw("s0", frame - 20, "sp"))
    a.op(lw("s1", frame - 16, "sp"))
    a.op(lw("s2", frame - 12, "sp"))
    a.op(lw("s3", frame - 8, "sp"))
    a.op(jr("ra"))
    a.op(addiu("sp", "sp", frame))


def build_read_hook():
    """READ_HOOK0/1(a0 = .vad path, a1 = lip-sync slot, a2 = 0x30): same result as 0x1D370."""
    F = 0x70                                 # frame: sp+0x10 slot, +0x14 result, +0x20.. path
    a = Asm(READ_CAVE[0])
    a.label("read_hook0")
    a.op(b("r_common"))
    a.op(addiu("t8", "zero", 0))
    a.label("read_hook1")
    a.op(addiu("t8", "zero", 1))
    a.label("r_common")
    prologue(a, "r_here", "s2", F)
    a.op(sw("t8", 0x10, "sp"))
    a.op(move("s0", "a0"))
    a.op(move("s1", "a1"))
    call(a, "s2", F_READ_EXACT)             # the game's own .vad read
    a.op(nop())
    a.op(sw("v0", 0x14, "sp"))              # its result is ours
    runtime(a, "s3", BUF, "s2")
    # remember where slot 0 is; clear this slot's line; s1 = this slot's tail buffer
    a.op(lw("t8", 0x10, "sp"))
    a.op(beq("t8", "zero", "r_slot0"))
    a.op(addiu("t0", "s3", B_READ[0]))
    a.op(addiu("s1", "s1", -SLOT_SIZE))
    a.op(addiu("t0", "s3", B_READ[1]))
    a.label("r_slot0")
    a.op(sw("s1", B_SLOT0, "s3"))
    a.op(move("s1", "t0"))
    a.op(sll("t1", "t8", 2))
    a.op(addu("t1", "t1", "s3"))
    a.op(sw("zero", B_TEXT, "t1"))
    a.op(sll("t1", "t8", 1))
    a.op(addu("t1", "t1", "s3"))
    a.op(sh("zero", B_HOLD, "t1"))
    a.op(sh("zero", B_PARTS, "t1"))
    # path = "data/sound/voice/" + clip + ".at3", on the stack
    runtime(a, "t1", VOICE_DIR, "s2")
    a.op(addiu("t2", "sp", 0x20))
    a.label("r_dir")
    a.op(lbu("t3", 0, "t1"))
    a.op(addiu("t1", "t1", 1))
    a.op(sb("t3", 0, "t2"))
    a.op(bne("t3", "zero", "r_dir"))
    a.op(addiu("t2", "t2", 1))
    a.op(addiu("t2", "t2", -1))
    a.op(addiu("t1", "s0", VAD_PREFIX_LEN))
    a.op(addiu("t4", "zero", ord(".")))
    a.label("r_id")
    a.op(lbu("t3", 0, "t1"))
    a.op(addiu("t1", "t1", 1))
    a.op(beq("t3", "t4", "r_ext"))
    a.op(nop())
    a.op(beq("t3", "zero", "r_ext"))
    a.op(nop())
    a.op(sb("t3", 0, "t2"))
    a.op(b("r_id"))
    a.op(addiu("t2", "t2", 1))
    a.label("r_ext")
    for i, ch in enumerate(b".at3\0"):
        a.op(addiu("t3", "zero", ch))
        a.op(sb("t3", i, "t2"))
    # normalise into the tail buffer, look it up in macross.dat
    a.op(move("a0", "s1"))
    a.op(addiu("a1", "sp", 0x20))
    call(a, "s2", F_NORMALIZE)
    a.op(addiu("a2", "zero", TAIL))
    a.op(move("a0", "s1"))
    call(a, "s2", F_LOOKUP)
    a.op(addiu("a1", "s3", B_INFO))
    a.op(beq("v0", "zero", "r_ret"))
    a.op(lw("t1", B_INFO + 12, "s3"))       # packed size: voice clips are stored, not packed
    a.op(bne("t1", "zero", "r_ret"))
    a.op(lw("t0", B_INFO + 8, "s3"))        # file size
    a.op(slti("t1", "t0", TAIL + 1))
    a.op(bne("t1", "zero", "r_small"))
    a.op(move("a3", "t0"))
    a.op(addiu("a3", "zero", TAIL))
    a.label("r_small")
    a.op(lw("a2", B_INFO + 4, "s3"))
    a.op(addu("a2", "a2", "t0"))
    a.op(subu("a2", "a2", "a3"))            # offset of the last a3 bytes
    a.op(move("s0", "a3"))
    a.op(lw("a0", B_INFO, "s3"))
    a.op(move("a1", "s1"))
    call(a, "s2", F_READ_AT)
    a.op(addiu("t0", "zero", 1))
    a.op(bltz("v0", "r_ret"))
    # parse the tail: ... text NUL | u16 len | u16 frames | 'S' 'B'
    a.op(addu("t1", "s1", "s0"))            # t1 = end of what was read
    a.op(lbu("t2", -2, "t1"))
    a.op(addiu("t3", "zero", ord("S")))
    a.op(bne("t2", "t3", "r_ret"))
    a.op(lbu("t2", -1, "t1"))
    a.op(addiu("t3", "zero", ord("B")))
    a.op(bne("t2", "t3", "r_ret"))
    a.op(lbu("t4", -6, "t1"))
    a.op(lbu("t5", -5, "t1"))
    a.op(sll("t5", "t5", 8))
    a.op(or_("t4", "t4", "t5"))             # t4 = text length with its NUL
    a.op(subu("t1", "t1", "t4"))
    a.op(addiu("t1", "t1", -6))             # t1 = text
    a.op(slt("t6", "t1", "s1"))
    a.op(bne("t6", "zero", "r_ret"))
    a.op(lw("t8", 0x10, "sp"))
    a.op(addu("t9", "t1", "t4"))
    a.op(lbu("t7", 2, "t9"))                # number of parts (u16, maybe unaligned: low byte is enough)
    a.op(sll("t9", "t8", 1))
    a.op(addu("t9", "t9", "s3"))
    a.op(sh("t7", B_PARTS, "t9"))
    a.op(sll("t8", "t8", 2))
    a.op(addu("t8", "t8", "s3"))
    a.op(sw("t1", B_TEXT, "t8"))
    a.label("r_ret")
    a.op(lw("v0", 0x14, "sp"))
    epilogue(a, F)
    words = a.assemble()
    if READ_CAVE[0] + 4 * len(words) > READ_CAVE[1]:
        raise ValueError("read hook does not fit its cave: %d words" % len(words))
    return words, a.labels


def build_draw_hook():
    """DRAW_HOOK(): run 0x179FCC, then show the line of the slot that is speaking."""
    F = 0x30                                 # frame: sp+0..8 stack arguments, +0x18 line
    a = Asm(DRAW_CAVE[0])
    a.label("draw_hook")
    prologue(a, "d_here", "s1", F)
    call(a, "s1", F_LAYER_END)
    a.op(nop())
    runtime(a, "s0", BUF, "s1")
    a.op(lw("t7", B_SLOT0, "s0"))           # t7 = lip-sync slot 0 (0 until the first clip)
    a.op(beq("t7", "zero", "d_ret"))
    a.op(move("s2", "zero"))                # s2 = slot k
    a.label("d_slot")
    a.op(sll("t0", "s2", 2))
    a.op(addu("t0", "t0", "s0"))
    a.op(lw("t1", B_TEXT, "t0"))            # t1 = line of slot k
    a.op(beq("t1", "zero", "d_next"))
    a.op(sw("t1", 0x18, "sp"))
    # speaking: total != 0 and 0 < counter and counter * step < total
    a.op(sll("t2", "s2", 2))
    a.op(addu("t2", "t2", "t7"))
    a.op(lw("t3", COUNTER, "t2"))           # counter of slot k
    a.op(sll("t4", "s2", 4))
    a.op(sll("t5", "s2", 5))
    a.op(addu("t4", "t4", "t5"))            # 0x30 * k
    a.op(addu("t4", "t4", "t7"))
    a.op(lw("t5", 0, "t4"))                 # total
    a.op(lhu("t6", 6, "t4"))                # step
    a.op(multu("t3", "t6"))
    a.op(mflo("t6"))                        # t6 = counter * step
    a.op(sll("t8", "s2", 1))
    a.op(addu("t8", "t8", "s0"))            # t8 + B_HOLD = part/hold of slot k
    a.op(blez("t3", "d_quiet"))
    a.op(slt("t9", "t6", "t5"))
    a.op(beq("t9", "zero", "d_quiet"))
    a.op(lhu("t0", B_PARTS, "t8"))          # (delay) parts
    # part = the largest i < parts with counter*step*parts >= total*i
    a.op(multu("t6", "t0"))
    a.op(mflo("t6"))
    a.op(move("t2", "zero"))                # i
    a.op(move("t3", "t5"))                  # total * (i + 1)
    a.label("d_part")
    a.op(addiu("t9", "t2", 1))
    a.op(slt("t9", "t9", "t0"))
    a.op(beq("t9", "zero", "d_part_ok"))
    a.op(slt("t9", "t6", "t3"))
    a.op(bne("t9", "zero", "d_part_ok"))
    a.op(addu("t3", "t3", "t5"))
    a.op(b("d_part"))
    a.op(addiu("t2", "t2", 1))
    a.label("d_part_ok")
    a.op(sll("t9", "t2", 8))
    a.op(ori("t9", "t9", HOLD))
    a.op(b("d_show"))
    a.op(sh("t9", B_HOLD, "t8"))
    a.label("d_quiet")
    a.op(lhu("t9", B_HOLD, "t8"))
    a.op(andi("t2", "t9", 0xFF))
    a.op(blez("t2", "d_next"))
    a.op(addiu("t9", "t9", -1))
    a.op(sh("t9", B_HOLD, "t8"))
    a.label("d_show")
    # skip to the part shown: (hold >> 8) NULs into the line
    a.op(lhu("t9", B_HOLD, "t8"))
    a.op(srl("t9", "t9", 8))
    a.op(lw("t1", 0x18, "sp"))
    a.label("d_skip")
    a.op(beq("t9", "zero", "d_skipped"))
    a.op(nop())
    a.op(lbu("t2", 0, "t1"))
    a.op(addiu("t1", "t1", 1))
    a.op(bne("t2", "zero", "d_skip"))
    a.op(nop())
    a.op(b("d_skip"))
    a.op(addiu("t9", "t9", -1))
    a.label("d_skipped")
    a.op(sw("t1", 0x18, "sp"))
    a.op(addiu("s3", "zero", 1))            # pass 1: shadow (+1, +1); pass 0: text
    a.label("d_pass")
    runtime(a, "t9", CFG, "s1")
    a.op(lw("a1", 0, "t9"))
    a.op(lw("a2", 4, "t9"))
    a.op(addu("a1", "a1", "s3"))
    a.op(addu("a2", "a2", "s3"))
    a.op(lw("a3", 8, "t9"))
    a.op(move("t0", "a3"))
    a.op(lw("t1", 12, "t9"))
    a.op(lw("v0", 16, "t9"))
    a.op(sw("v0", 4, "sp"))                 # [sp4] alignment mode
    a.op(lw("v0", 28, "t9"))
    a.op(sw("v0", 8, "sp"))                 # [sp8] line step
    a.op(sw("zero", 0, "sp"))               # [sp0] font 0 (14 px, VWF)
    a.op(lw("t2", 32, "t9"))                # sprite depth
    a.op(beq("s3", "zero", "d_col"))
    a.op(lw("t3", 20, "t9"))                # text colour
    a.op(lw("t3", 24, "t9"))                # shadow colour
    a.label("d_col")
    call(a, "s1", F_TEXT)
    a.op(lw("a0", 0x18, "sp"))              # (delay) the line
    a.op(bne("s3", "zero", "d_pass"))
    a.op(addiu("s3", "s3", -1))
    a.op(b("d_ret"))                        # one line at a time
    a.op(nop())
    a.label("d_next")
    a.op(addiu("s2", "s2", 1))
    a.op(slti("t0", "s2", 2))
    a.op(bne("t0", "zero", "d_slot"))
    a.op(nop())
    a.label("d_ret")
    epilogue(a, F)
    words = a.assemble()
    if DRAW_CAVE[0] + 4 * len(words) > DRAW_CAVE[1]:
        raise ValueError("draw hook does not fit its cave: %d words" % len(words))
    return words, a.labels


def jal_word(target):
    return (0x03 << 26) | ((target >> 2) & 0x3FFFFFF)


def patch(data, area):
    eb = Eboot(data)
    layout(area)
    read_words, read_labels = build_read_hook()
    draw_words, draw_labels = build_draw_hook()
    if bytes(eb.d[eb.foff(VOICE_DIR):eb.foff(VOICE_DIR) + 18]) != b"data/sound/voice/\0":
        raise ValueError("no 'data/sound/voice/' string at %x" % VOICE_DIR)
    if not (eb.data_va <= area and area + AREA_SIZE <= eb.data_va + eb.data_filesz):
        raise ValueError("area 0x%X is not file-backed data" % area)
    if any(eb.d[eb.foff(area):eb.foff(area) + AREA_SIZE]):
        raise ValueError("area at 0x%X is not empty (eboot_insert --reserve 4096?)" % area)
    for a in range(area, area + AREA_SIZE, 4):
        if a in eb.reloc_sites:
            raise ValueError("relocated word in the area at %x" % a)
    for base, words in ((READ_CAVE[0], read_words), (DRAW_CAVE[0], draw_words)):
        for i, w in enumerate(words):
            eb.put_word(base + 4 * i, w)
    for i, w in enumerate(CONFIG):
        eb.put_word(CFG + 4 * i, w & 0xFFFFFFFF)
    hooks = [(READ_SITES[0], F_READ_EXACT, read_labels["read_hook0"]),
             (READ_SITES[1], F_READ_EXACT, read_labels["read_hook1"])] + \
            [(s, F_LAYER_END, draw_labels["draw_hook"]) for s in DRAW_SITES]
    for va, target, hook in hooks:
        if va not in eb.reloc_sites:
            raise ValueError("%x has no relocation" % va)
        if eb.word(va) != jal_word(target):
            raise ValueError("%x is not jal %x" % (va, target))
        struct.pack_into("<I", eb.d, eb.foff(va), jal_word(hook))
    return bytes(eb.d), [(READ_CAVE[0], len(read_words)), (DRAW_CAVE[0], len(draw_words))]


def main():
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("eboot")
    ap.add_argument("out")
    ap.add_argument("--area", required=True, help="the .json eboot_insert.py wrote next to its output")
    a = ap.parse_args()
    info = json.load(open(a.area))
    if not info.get("reserved_vaddr") or info.get("reserved_bytes", 0) < VWF_RESERVE + AREA_SIZE:
        sys.exit("need eboot_insert.py --reserve 4096 (at least %d; got %s)"
                 % (VWF_RESERVE + AREA_SIZE, info.get("reserved_bytes")))
    area = info["reserved_vaddr"] + VWF_RESERVE
    data, blocks = patch(open(a.eboot, "rb").read(), area)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "wb").write(data)
    print("voice subtitles: code %s, data at %x, config at %x, read hooks at %s, draw hook at %s"
          % (", ".join("%d words at %x" % (n, b) for b, n in blocks), BUF, CFG,
             ", ".join("%x" % s for s in READ_SITES), ", ".join("%x" % s for s in DRAW_SITES)))


if __name__ == "__main__":
    main()
