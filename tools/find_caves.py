"""List functions in the decrypted EBOOT that nothing references (candidate code caves).

Usage: python tools/find_caves.py <eboot> [<lo_hex> <hi_hex>] [--min WORDS]

A function start is a jal target or the word after 'jr $ra' + delay slot that begins
with 'addiu $sp, $sp, -N'. A function counts as referenced when its start (or any
address inside it) is:
  - the target of a jal / j anywhere in the text segment,
  - the value of a relocated 32-bit word (R_MIPS_32: function pointer tables),
  - built by a relocated lui + addiu/ori pair (HI16/LO16) anywhere in the text,
  - the target of a branch from outside the function.
Prints unreferenced functions with their size and how many relocated words they hold
(a cave must not contain relocated words, or the loader rewrites them).
"""
import struct
import sys

sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
from port_match import Elf  # noqa: E402


def main():
    e = Elf(sys.argv[1])
    lo = int(sys.argv[2], 16) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else 0
    hi = int(sys.argv[3], 16) if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else e.text_size
    minw = int(sys.argv[sys.argv.index("--min") + 1]) if "--min" in sys.argv else 16
    w = e.words
    n = len(w)
    refs = set()
    starts = set()
    # jal / j
    for i, x in enumerate(w):
        op = x >> 26
        if op in (2, 3):
            t = (x & 0x3FFFFFF) << 2
            refs.add(t)
            if op == 3:
                starts.add(t)
    # relocated 32-bit words anywhere (data and text)
    for va in e.relocs:
        o = e.foff(va)
        if o + 4 <= len(e.d):
            v = struct.unpack_from("<I", e.d, o)[0]
            if v < e.text_size:
                refs.add(v)
    # lui/addiu pairs with relocations (approximate: pair each relocated lui with the
    # next relocated low-16 user of the same register within 32 instructions)
    for i, x in enumerate(w):
        if x >> 26 == 0x0F and 4 * i in e.relocs:
            rt = (x >> 16) & 31
            hi16 = x & 0xFFFF
            for j in range(i + 1, min(n, i + 32)):
                y = w[j]
                if 4 * j in e.relocs and (y >> 21) & 31 == rt and (y >> 26) in (0x09, 0x0D, 0x23, 0x21, 0x25, 0x24, 0x20, 0x31):
                    imm = y & 0xFFFF
                    if y >> 26 == 0x0D:
                        v = (hi16 << 16) | imm
                    else:
                        v = ((hi16 << 16) + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF
                    refs.add(v)
                    break
    # function starts after jr ra
    for i in range(n - 2):
        if w[i] == 0x03E00008 and (w[i + 2] & 0xFFFF0000) == 0x27BD0000 and (w[i + 2] & 0x8000):
            starts.add(4 * (i + 2))
    ss = sorted(s for s in starts if lo <= s < hi)
    allst = sorted(starts)
    # branches: target -> set of source addresses
    btarget = {}
    for i, x in enumerate(w):
        op = x >> 26
        rt = (x >> 16) & 31
        if op in (4, 5, 6, 7, 0x14, 0x15, 0x16, 0x17) or (op == 1 and rt in (0, 1, 2, 3, 0x10, 0x11, 0x12, 0x13)):
            off = x & 0xFFFF
            off = off - 0x10000 if off & 0x8000 else off
            btarget.setdefault(4 * i + 4 + 4 * off, []).append(4 * i)
    import bisect
    for k, s in enumerate(ss):
        idx = bisect.bisect_right(allst, s)
        end = allst[idx] if idx < len(allst) else e.text_size
        if (end - s) // 4 < minw:
            continue
        inside = [a for a in refs if s <= a < end]
        ext_br = [t for t in btarget if s <= t < end and any(not (s <= src < end) for src in btarget[t])]
        if inside or ext_br:
            continue
        nrel = sum(1 for a in range(s, end, 4) if a in e.relocs)
        # longest run of words without relocations
        run = best = 0
        for a in range(s, end, 4):
            run = 0 if a in e.relocs else run + 1
            best = max(best, run)
        print("%06X-%06X %4d words, %3d relocated, longest clean run %4d words" % (s, end, (end - s) // 4, nrel, best))


if __name__ == "__main__":
    main()
