"""Align one MUF function with its AF counterpart and map MUF addresses into it.

Usage:
  python tools/port_align.py <muf_eboot> <af_eboot> <muf_start> <muf_end> <af_start> <af_end> [<muf_va> ...]
  python tools/port_align.py ... --dump <out.txt>    side-by-side listing of the whole alignment

Masked instruction words (tools/port_match.py) are aligned with difflib. Each
MUF address is mapped to the AF address in the same 'equal' block, with the
two instructions printed so the match can be checked by eye.
"""
import difflib
import sys

import capstone

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from port_match import Elf  # noqa: E402

MD = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)


def dis(e, va):
    o = e.foff(va)
    for ins in MD.disasm(e.d[o:o + 4], va):
        return ("%s %s" % (ins.mnemonic, ins.op_str)).strip()
    return "?"


def align(m, a, ms, me, as_, ae):
    s = list(m.masked[ms // 4:me // 4])
    t = list(a.masked[as_ // 4:ae // 4])
    sm = difflib.SequenceMatcher(None, s, t, autojunk=False)
    return sm.get_opcodes()


def main():
    args = sys.argv[1:]
    dump = None
    if "--dump" in args:
        k = args.index("--dump")
        dump = args[k + 1]
        del args[k:k + 2]
    m, a = Elf(args[0]), Elf(args[1])
    ms, me, as_, ae = (int(x, 16) for x in args[2:6])
    ops = align(m, a, ms, me, as_, ae)
    if dump:
        with open(dump, "w", encoding="utf-8") as f:
            for tag, i1, i2, j1, j2 in ops:
                n = max(i2 - i1, j2 - j1)
                for k in range(n):
                    mv = ms + 4 * (i1 + k) if i1 + k < i2 else None
                    av = as_ + 4 * (j1 + k) if j1 + k < j2 else None
                    f.write("%s %-6s %-40s | %-6s %s\n" % (
                        {"equal": " ", "replace": "~", "delete": "-", "insert": "+"}[tag],
                        "%06X" % mv if mv is not None else "", dis(m, mv) if mv is not None else "",
                        "%06X" % av if av is not None else "", dis(a, av) if av is not None else ""))
    for x in args[6:]:
        va = int(x, 16)
        i = (va - ms) // 4
        for tag, i1, i2, j1, j2 in ops:
            if i1 <= i < i2:
                if tag == "equal":
                    av = as_ + 4 * (j1 + i - i1)
                    print("MUF %06X %-34s -> AF %06X %s" % (va, dis(m, va), av, dis(a, av)))
                else:
                    print("MUF %06X %-34s -> (in a %s block, MUF %06X-%06X / AF %06X-%06X)" % (
                        va, dis(m, va), tag, ms + 4 * i1, ms + 4 * i2, as_ + 4 * j1, as_ + 4 * j2))
                break


if __name__ == "__main__":
    main()
