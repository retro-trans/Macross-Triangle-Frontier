"""Disassemble a range of the decrypted EBOOT: python tools/disasm.py <eboot> <start_hex> <end_hex>
Marks relocated words with '*'."""
import sys
import capstone
sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
from port_match import Elf  # noqa: E402

e = Elf(sys.argv[1])
a, b = int(sys.argv[2], 16), int(sys.argv[3], 16)
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
for va in range(a, b, 4):
    o = e.foff(va)
    ins = list(md.disasm(e.d[o:o + 4], va))
    t = ("%s %s" % (ins[0].mnemonic, ins[0].op_str)).strip() if ins else "?? %08x" % int.from_bytes(e.d[o:o + 4], "little")
    print("%06X%s %s" % (va, "*" if va in e.relocs else " ", t))
