"""Parse and serialize LOTRO text tables (DataID 0x25xxxxxx in client_local_English.dat).

Layout (little-endian), payload starts at the table's own DataID:
    u32 did, u32 1, u8 hash capacity exponent, compact record count
    per record: u64 token, u32 n1, n1 x (compact chars + UTF-16LE),
                u32 n2 (== n1-1), n2 x u32 argument id,
                u8 g, g x (u32 n3, n3 x (compact chars + UTF-16LE))   # argument names
compact: one byte below 0x80, else two bytes (0x80 | hi, lo), max 0x7FFF.
"""
import re
import struct

PLACEHOLDER = re.compile(r"\{(\d+)\}")


class FormatError(ValueError):
    pass


class Record:
    __slots__ = ("token", "pieces", "args", "names")

    def __init__(self, token, pieces, args, names):
        self.token, self.pieces, self.args, self.names = token, pieces, args, names

    def template(self):
        out = [self.pieces[0]] if self.pieces else []
        for i in range(len(self.args)):
            out.append("{%d}" % i)
            out.append(self.pieces[i + 1])
        return "".join(out)


class Table:
    __slots__ = ("did", "u1", "capacity", "records")

    def __init__(self, did, u1, capacity, records):
        self.did, self.u1, self.capacity, self.records = did, u1, capacity, records


def _compact(buf, o):
    b0 = buf[o]
    if b0 & 0x80:
        return ((b0 ^ 0x80) << 8) | buf[o + 1], o + 2
    return b0, o + 1


def _string(buf, o):
    n, o = _compact(buf, o)
    if o + 2 * n > len(buf):
        raise FormatError("string runs past end @%d" % o)
    return buf[o:o + 2 * n].decode("utf-16-le"), o + 2 * n


def parse(buf):
    try:
        did, u1, cap = struct.unpack_from("<IIB", buf, 0)
        count, o = _compact(buf, 9)
        records = []
        for _ in range(count):
            token, n1 = struct.unpack_from("<QI", buf, o)
            o += 12
            if token >> 32 or n1 > 0xFFFF:
                raise FormatError("bad record header @%d" % o)
            pieces = []
            for _ in range(n1):
                s, o = _string(buf, o)
                pieces.append(s)
            n2 = struct.unpack_from("<I", buf, o)[0]
            o += 4
            if n2 != max(n1 - 1, 0):
                raise FormatError("argument count %d does not match %d pieces" % (n2, n1))
            args = list(struct.unpack_from("<%dI" % n2, buf, o))
            o += 4 * n2
            g = buf[o]
            o += 1
            names = []
            for _ in range(g):
                n3 = struct.unpack_from("<I", buf, o)[0]
                o += 4
                group = []
                for _ in range(n3):
                    s, o = _string(buf, o)
                    group.append(s)
                names.append(group)
            records.append(Record(token, pieces, args, names))
    except (struct.error, IndexError, UnicodeDecodeError) as e:
        raise FormatError(str(e))
    if o != len(buf):
        raise FormatError("%d trailing bytes" % (len(buf) - o))
    return Table(did, u1, cap, records)


def _put_compact(out, n):
    if n < 0x80:
        out.append(n)
    elif n <= 0x7FFF:
        out += bytes((0x80 | (n >> 8), n & 0xFF))
    else:
        raise FormatError("string too long (%d chars)" % n)


def _put_string(out, s):
    b = s.encode("utf-16-le")
    _put_compact(out, len(b) // 2)
    out += b


def serialize(t):
    out = bytearray(struct.pack("<IIB", t.did, t.u1, t.capacity))
    _put_compact(out, len(t.records))
    for r in t.records:
        out += struct.pack("<QI", r.token, len(r.pieces))
        for p in r.pieces:
            _put_string(out, p)
        out += struct.pack("<I%dI" % len(r.args), len(r.args), *r.args)
        out.append(len(r.names))
        for group in r.names:
            out += struct.pack("<I", len(group))
            for s in group:
                _put_string(out, s)
    return bytes(out)


def split_template(text, nargs):
    """Turkish template -> pieces. Placeholders {0}..{n-1} must each appear once, in order."""
    found = [int(m.group(1)) for m in PLACEHOLDER.finditer(text)]
    if found != list(range(nargs)):
        raise FormatError("placeholders %s, expected %s" % (found, list(range(nargs))))
    return PLACEHOLDER.split(text)[0::2]
