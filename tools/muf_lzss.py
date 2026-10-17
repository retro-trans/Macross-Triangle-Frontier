"""LZSS codec used by fileset.dat members in Macross Ultimate Frontier (PSP).

Every member starts with an 8-byte header:
    +0  4 bytes  magic, XORed with 0x72:
                 20 33 3B 31 = "RAIC"  compressed (LZSS)
                 20 33 3B 30 = "RAIB"  stored (no compression)
    +4  u32 LE   uncompressed size (not XORed)
    +8  ...      payload, every byte XORed with 0x72

The LZSS stream is the classic LZSS.C by Haruhiko Okumura (1989):
N=4096 window, F=18 max match, THRESHOLD=2, ring buffer starts at N-F
(0xFEE). Flag bytes are read LSB first, bit set = literal byte, bit clear =
two-byte reference: offset = b0 | (b1 & 0xF0) << 4, length = (b1 & 0x0F) + 3.
The window starts zero-filled (not space-filled as in the original LZSS.C)
and the lookahead starts non-zero (see LOOKAHEAD_FILL). With those two
changes this encoder reproduces all of the game's compressed members byte
for byte.
"""

import struct

MAGIC = b"\x20\x33\x3b\x31"  # RAIC, compressed
MAGIC_STORED = b"\x20\x33\x3b\x30"  # RAIB, stored
XOR_KEY = 0x72
N = 4096
F = 18
THRESHOLD = 2
NIL = N
FILL = 0x00  # initial window content
# The game's encoder did not clear its lookahead buffer between files, so
# bytes past the end of a very short input were not zero. Any non-zero value
# reproduces every original member (it only matters for inputs under ~36 bytes).
LOOKAHEAD_FILL = 0xFF

_XOR_TABLE = bytes(i ^ XOR_KEY for i in range(256))


def member_mode(blob):
    """'C' for RAIC (compressed), 'B' for RAIB (stored)."""
    if blob[:4] == MAGIC:
        return "C"
    if blob[:4] == MAGIC_STORED:
        return "B"
    raise ValueError("unknown member header %s" % blob[:4].hex())


def decode(blob):
    """Decode a fileset member of either mode."""
    if member_mode(blob) == "B":
        size = struct.unpack_from("<I", blob, 4)[0]
        if len(blob) - 8 != size:
            raise ValueError("stored member size mismatch")
        return blob[8:].translate(_XOR_TABLE)
    return decompress(blob)


def encode(data, mode="C"):
    if mode == "B":
        return MAGIC_STORED + struct.pack("<I", len(data)) + data.translate(_XOR_TABLE)
    return compress(data)


def decompress(blob):
    if blob[:4] != MAGIC:
        raise ValueError("not a RAIC/LZSS member")
    size = struct.unpack_from("<I", blob, 4)[0]
    src = blob[8:].translate(_XOR_TABLE)
    win = bytearray([FILL]) * N
    r = N - F
    out = bytearray()
    i = 0
    n = len(src)
    while len(out) < size and i < n:
        flags = src[i]
        i += 1
        for bit in range(8):
            if len(out) >= size or i >= n:
                break
            if flags >> bit & 1:
                c = src[i]
                i += 1
                out.append(c)
                win[r] = c
                r = (r + 1) & (N - 1)
            else:
                lo = src[i]
                hi = src[i + 1]
                i += 2
                off = lo | (hi & 0xF0) << 4
                for k in range((hi & 0x0F) + THRESHOLD + 1):
                    c = win[(off + k) & (N - 1)]
                    out.append(c)
                    win[r] = c
                    r = (r + 1) & (N - 1)
    if len(out) != size:
        raise ValueError("truncated LZSS stream (%d of %d bytes)" % (len(out), size))
    return bytes(out)


def _encode_stream(data):
    """Okumura LZSS.C Encode(), binary-tree match finder, ported 1:1."""
    text_buf = bytearray([FILL]) * (N - F) + bytearray([LOOKAHEAD_FILL]) * (2 * F - 1)
    lson = [NIL] * (N + 1)
    rson = [NIL] * (N + 257)
    dad = [NIL] * (N + 1)
    match = [0, 0]  # position, length

    def insert_node(r):
        cmp = 1
        key = r
        p = N + 1 + text_buf[key]
        rson[r] = lson[r] = NIL
        match[1] = 0
        while True:
            if cmp >= 0:
                if rson[p] != NIL:
                    p = rson[p]
                else:
                    rson[p] = r
                    dad[r] = p
                    return
            else:
                if lson[p] != NIL:
                    p = lson[p]
                else:
                    lson[p] = r
                    dad[r] = p
                    return
            i = 1
            while i < F:
                cmp = text_buf[key + i] - text_buf[p + i]
                if cmp != 0:
                    break
                i += 1
            if i > match[1]:
                match[0] = p
                match[1] = i
                if i >= F:
                    break
        dad[r] = dad[p]
        lson[r] = lson[p]
        rson[r] = rson[p]
        dad[lson[p]] = r
        dad[rson[p]] = r
        if rson[dad[p]] == p:
            rson[dad[p]] = r
        else:
            lson[dad[p]] = r
        dad[p] = NIL

    def delete_node(p):
        if dad[p] == NIL:
            return
        if rson[p] == NIL:
            q = lson[p]
        elif lson[p] == NIL:
            q = rson[p]
        else:
            q = lson[p]
            if rson[q] != NIL:
                while True:
                    q = rson[q]
                    if rson[q] == NIL:
                        break
                rson[dad[q]] = lson[q]
                dad[lson[q]] = dad[q]
                lson[q] = lson[p]
                dad[lson[p]] = q
            rson[q] = rson[p]
            dad[rson[p]] = q
        dad[q] = dad[p]
        if rson[dad[p]] == p:
            rson[dad[p]] = q
        else:
            lson[dad[p]] = q
        dad[p] = NIL

    out = bytearray()
    code_buf = bytearray(17)
    code_buf[0] = 0
    code_buf_ptr = 1
    mask = 1
    s = 0
    r = N - F
    pos = 0
    length = 0
    while length < F and pos < len(data):
        text_buf[r + length] = data[pos]
        length += 1
        pos += 1
    if length == 0:
        return bytes(out)
    for i in range(1, F + 1):
        insert_node(r - i)
    insert_node(r)
    while True:
        if match[1] > length:
            match[1] = length
        if match[1] <= THRESHOLD:
            match[1] = 1
            code_buf[0] |= mask
            code_buf[code_buf_ptr] = text_buf[r]
            code_buf_ptr += 1
        else:
            code_buf[code_buf_ptr] = match[0] & 0xFF
            code_buf[code_buf_ptr + 1] = ((match[0] >> 4) & 0xF0) | (match[1] - (THRESHOLD + 1))
            code_buf_ptr += 2
        mask = (mask << 1) & 0xFF
        if mask == 0:
            out += code_buf[:code_buf_ptr]
            code_buf[0] = 0
            code_buf_ptr = 1
            mask = 1
        last_match_length = match[1]
        i = 0
        while i < last_match_length and pos < len(data):
            c = data[pos]
            pos += 1
            delete_node(s)
            text_buf[s] = c
            if s < F - 1:
                text_buf[s + N] = c
            s = (s + 1) & (N - 1)
            r = (r + 1) & (N - 1)
            insert_node(r)
            i += 1
        while i < last_match_length:
            i += 1
            delete_node(s)
            s = (s + 1) & (N - 1)
            r = (r + 1) & (N - 1)
            length -= 1
            if length:
                insert_node(r)
        if length <= 0:
            break
    if code_buf_ptr > 1:
        out += code_buf[:code_buf_ptr]
    return bytes(out)


def compress(data):
    return MAGIC + struct.pack("<I", len(data)) + _encode_stream(data).translate(_XOR_TABLE)
