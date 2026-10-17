"""Find Ultimate Frontier code in the Ace Frontier EBOOT (same engine, other addresses).

Usage:
  python tools/port_match.py <muf_eboot.dec.bin> <af_eboot.dec.bin> <muf_va>[:<words>] ...

For each MUF address, a window of instruction words starting there is compared
with every position in the AF text segment. Words that differ between builds
for reasons other than the code (call targets, lui/addiu of data addresses,
relocated words) are masked. Prints the best AF address, its score and the
runner-up, so a unique match is easy to see.

Used to port tools/vwf_build.py (docs/vwf.md). Needs numpy.
"""
import struct
import sys

import numpy as np


class Elf:
    def __init__(self, path):
        self.d = open(path, "rb").read()
        phoff = struct.unpack_from("<I", self.d, 28)[0]
        ph = [struct.unpack_from("<8I", self.d, phoff + 32 * i) for i in range(struct.unpack_from("<H", self.d, 44)[0])]
        self.text_off, self.text_size = ph[0][1], ph[0][4]
        self.data_va, self.data_off = ph[1][2], ph[1][1]
        shoff = struct.unpack_from("<I", self.d, 32)[0]
        shnum = struct.unpack_from("<H", self.d, 48)[0]
        self.relocs = set()
        for i in range(shnum):
            s = struct.unpack_from("<10I", self.d, shoff + 40 * i)
            if s[1] == 0x700000A0:
                for k in range(s[5] // 8):
                    off, info = struct.unpack_from("<2I", self.d, s[4] + 8 * k)
                    self.relocs.add(off + (self.data_va if (info >> 8) & 0xFF == 1 else 0))
        n = self.text_size // 4
        self.words = np.frombuffer(self.d, dtype="<u4", count=n, offset=self.text_off).copy()
        self.masked = mask(self.words, np.array([4 * i in self.relocs for i in range(n)]))

    def foff(self, va):
        return va + (self.data_off - self.data_va if va >= self.data_va else self.text_off)


def mask(words, reloc):
    op = words >> 26
    out = words.copy()
    jump = (op == 2) | (op == 3)
    out[jump] &= 0xFC000000
    imm = (op == 0x0F) | reloc
    out[imm & ~jump] &= 0xFFFF0000
    return out


def find(muf, af, va, n=24):
    i = va // 4
    pat = muf.masked[i:i + n]
    best = []
    m = af.masked
    score = np.zeros(len(m) - n, dtype=np.int32)
    for k in range(n):
        score += (m[k:len(m) - n + k] == pat[k])
    order = np.argsort(-score)[:2]
    return [(int(j) * 4, int(score[j])) for j in order], n


def main():
    muf, af = Elf(sys.argv[1]), Elf(sys.argv[2])
    for arg in sys.argv[3:]:
        va, _, n = arg.partition(":")
        va = int(va, 16)
        res, n = find(muf, af, va, int(n) if n else 24)
        (a, s), (a2, s2) = res
        print("MUF %06X -> AF %06X  %2d/%d  (next %06X %d)  delta %+X" % (va, a, s, n, a2, s2, a - va))


if __name__ == "__main__":
    main()
