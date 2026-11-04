"""Strict LOTRO DAT index reader and append-only copy-on-write B-tree planner.

Does not open archives for writing. Every old record/directory byte stays in
place; a plan changes only the file-size/root header fields and appends data.
"""
from bisect import bisect_left
from pathlib import Path
import hashlib
import struct
import zlib

HEADER_SIZE = 0x400
ENTRY_BASE = 0x1fc
COUNT_OFF = 0x1f8
MAX_KEYS = 61
MIN_DEGREE = 31


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Node:
    def __init__(self, entries, children, raw=None, offset=None):
        self.entries, self.children = list(entries), list(children)
        self.raw, self.offset, self.dirty = raw, offset, raw is None


class Archive:
    def __init__(self, path=None, handle=None):
        self.path = Path(path) if path else None
        self.f = handle if handle is not None else self.path.open("rb")
        self.own = handle is None
        self.header = self.read(0, HEADER_SIZE)
        if self.header[0x140:0x144] != b"BT\0\0":
            raise ValueError("Not a supported DAT archive")
        self.size = struct.unpack_from("<I", self.header, 0x148)[0]
        self.root = struct.unpack_from("<I", self.header, 0x160)[0]
        self.block = struct.unpack_from("<I", self.header, 0x144)[0]
        self.node_size = struct.unpack_from("<I", self.header, 0x1a4)[0] or 2460
        self.f.seek(0, 2)
        if self.f.tell() != self.size or not 2460 <= self.node_size <= 1048576:
            raise ValueError("Archive size or directory allocation mismatch")
        self.cache = {}

    def close(self):
        if self.own:
            self.f.close()

    def read(self, off, size):
        if off < 0 or size < 0:
            raise ValueError("Negative archive range")
        self.f.seek(off)
        data = self.f.read(size)
        if len(data) != size:
            raise ValueError("Truncated archive range")
        return data

    def node(self, ref):
        if isinstance(ref, Node):
            return ref
        allocation, offset = ref
        if offset in self.cache:
            return self.cache[offset]
        if allocation < self.node_size or offset < HEADER_SIZE or offset + self.node_size > self.size:
            raise ValueError("Invalid directory reference")
        raw = self.read(offset, self.node_size)
        if raw[:8] != bytes(8):
            raise ValueError("Fragmented directory nodes are not supported by this writer")
        count = struct.unpack_from("<I", raw, COUNT_OFF)[0]
        if count > MAX_KEYS:
            raise ValueError("Invalid B-tree key count")
        entries = [struct.unpack_from("<8I", raw, ENTRY_BASE + i * 32) for i in range(count)]
        if any(a[1] >= b[1] for a, b in zip(entries, entries[1:])):
            raise ValueError("Unsorted directory entries")
        branches = [struct.unpack_from("<II", raw, 8 + i * 8) for i in range(count + 1)]
        if branches[0][1]:
            if any(sz < self.node_size or not off for sz, off in branches):
                raise ValueError("Invalid internal B-tree node")
            children = branches
        else:
            if any(off for _, off in branches):
                raise ValueError("Invalid leaf B-tree node")
            children = []
        result = Node(entries, children, raw, offset)
        self.cache[offset] = result
        return result

    def find(self, fid):
        ref = (self.node_size, self.root)
        seen = set()
        for _ in range(48):
            n = self.node(ref)
            if n.offset in seen:
                raise ValueError("Directory cycle")
            seen.add(n.offset)
            i = bisect_left([e[1] for e in n.entries], fid)
            if i < len(n.entries) and n.entries[i][1] == fid:
                return n.entries[i]
            if not n.children:
                return None
            ref = n.children[i]
        raise ValueError("B-tree depth limit")

    def entries(self):
        seen = set()
        def walk(ref, low=-1, high=2**32):
            n = self.node(ref)
            if n.offset in seen:
                raise ValueError("Directory cycle or multiple parents")
            seen.add(n.offset)
            last = low
            for i, e in enumerate(n.entries):
                # Fragmented old records can span several allocations. Preserve
                # their directory entry, and validate only the first extent here.
                if not last < e[1] < high or e[2] < HEADER_SIZE or not e[6] or e[2] + min(e[3] + 8, e[6]) > self.size:
                    raise ValueError(f"Invalid directory ordering/record extent: {self.path} entry={e} low={low:x} high={high:x} size={self.size}")
                if n.children:
                    yield from walk(n.children[i], last, e[1])
                yield e
                last = e[1]
            if n.children:
                yield from walk(n.children[-1], last, high)
        return list(walk((self.node_size, self.root)))

    def fingerprint(self):
        entries = self.entries()
        h = hashlib.sha256()
        for e in entries:
            h.update(struct.pack("<8I", *e))
        return {"size": self.size, "header_sha256": digest(self.header),
                "index_sha256": h.hexdigest(), "entry_count": len(entries)}

    def payload(self, fid):
        e = self.find(fid)
        if e is None:
            raise KeyError(f"Record {fid:08x} is absent")
        raw = self.read(e[2], e[3] + 8)
        if raw[:8] != bytes(8) or e[6] < len(raw):
            raise ValueError("Fragmented record is not supported here")
        return raw[8:]

    def decoded(self, fid):
        e = self.find(fid)
        payload = self.payload(fid)
        if e[0] & 1:
            size = struct.unpack_from("<I", payload)[0]
            stream = zlib.decompressobj()
            result = stream.decompress(payload[4:]) + stream.flush()
            if len(result) != size or not stream.eof or stream.unused_data:
                raise ValueError("Compressed record boundary mismatch")
            return result
        return payload


class Plan:
    def __init__(self, archive):
        self.archive = archive
        self.nodes = {}
        self.root = self.node((archive.node_size, archive.root))
        self.tail = bytearray()
        self.records = []
        self.directory_nodes_written = 0

    def node(self, ref):
        if isinstance(ref, Node):
            return ref
        allocation, offset = ref
        if offset not in self.nodes:
            old = self.archive.node(ref)
            self.nodes[offset] = Node(old.entries, old.children, old.raw, old.offset)
        return self.nodes[offset]

    def allocate(self, data):
        off = self.archive.size + len(self.tail)
        allocation = (len(data) + 3) & ~3
        if off + allocation >= 2**32:
            raise ValueError("No room for append before 32-bit offset limit")
        self.tail += data + bytes(allocation - len(data))
        return allocation, off

    def split(self, parent, index):
        child = self.node(parent.children[index])
        if len(child.entries) != MAX_KEYS:
            raise ValueError("Only split a full node")
        left = Node(child.entries[:30], child.children[:31] if child.children else [])
        right = Node(child.entries[31:], child.children[31:] if child.children else [])
        parent.entries.insert(index, child.entries[30])
        parent.children[index:index + 1] = [left, right]
        parent.dirty = True

    def insert(self, node, entry):
        i = bisect_left([e[1] for e in node.entries], entry[1])
        if i < len(node.entries) and node.entries[i][1] == entry[1]:
            raise ValueError("Duplicate DataID")
        node.dirty = True
        if not node.children:
            node.entries.insert(i, entry)
            return
        child = self.node(node.children[i])
        if len(child.entries) == MAX_KEYS:
            self.split(node, i)
            if entry[1] > node.entries[i][1]:
                i += 1
        child = self.node(node.children[i])
        node.children[i] = child
        self.insert(child, entry)

    def replace(self, node, entry):
        i = bisect_left([e[1] for e in node.entries], entry[1])
        node.dirty = True
        if i < len(node.entries) and node.entries[i][1] == entry[1]:
            node.entries[i] = entry
        elif node.children:
            child = self.node(node.children[i])
            node.children[i] = child
            self.replace(child, entry)
        else:
            raise ValueError("Replacement DataID was not found")

    def add_record(self, fid, decoded, template, replace=False):
        master_offset = 4 if fid >> 20 in (0x1f0, 0x470) else 0
        if len(decoded) < master_offset + 4 or struct.unpack_from("<I", decoded, master_offset)[0] != fid:
            raise ValueError("Record master ID mismatch")
        old = self.archive.find(fid)
        if bool(old) != replace:
            raise ValueError("Unexpected existing/missing DataID")
        compressed = bool(template[0] & 1)
        payload = struct.pack("<I", len(decoded)) + zlib.compress(decoded, 9) if compressed else decoded
        allocation, off = self.allocate(bytes(8) + payload)
        e = list(template)
        e[1], e[2], e[3], e[6], e[7] = fid, off, len(payload), allocation, 0
        entry = tuple(e)
        if replace:
            self.replace(self.root, entry)
        else:
            if len(self.root.entries) == MAX_KEYS:
                self.root = Node([], [self.root])
                self.split(self.root, 0)
            self.insert(self.root, entry)
        self.records.append({"fid": f"{fid:08x}", "operation": "replace" if replace else "add",
                             "decoded_bytes": len(decoded), "decoded_sha256": digest(decoded),
                             "payload_bytes": len(payload), "payload_sha256": digest(payload),
                             "entry": list(entry), "old_entry": list(old) if old else None})

    def emit(self, ref):
        n = self.node(ref)
        if not n.dirty:
            return ref if not isinstance(ref, Node) else (self.archive.node_size, n.offset)
        raw = bytearray(n.raw if n.raw is not None else bytes(self.archive.node_size))
        raw[:2460] = bytes(2460)
        for i, child in enumerate(n.children):
            struct.pack_into("<II", raw, 8 + i * 8, *self.emit(child))
        struct.pack_into("<I", raw, COUNT_OFF, len(n.entries))
        for i, entry in enumerate(n.entries):
            struct.pack_into("<8I", raw, ENTRY_BASE + i * 32, *entry)
        self.directory_nodes_written += 1
        return self.allocate(bytes(raw))

    def finish(self):
        _, root = self.emit(self.root)
        header = bytearray(self.archive.header)
        struct.pack_into("<I", header, 0x148, self.archive.size + len(self.tail))
        struct.pack_into("<I", header, 0x160, root)
        changed = {i for i, (a, b) in enumerate(zip(header, self.archive.header)) if a != b}
        if not changed <= set(range(0x148, 0x14c)) | set(range(0x160, 0x164)):
            raise ValueError("Unexpected header edit")
        return bytes(header), bytes(self.tail), self.records
