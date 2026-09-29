"""Compact read-only lookup tables for string keys (standard library only).

A table of Python strings costs about 100 bytes per entry as a dict or
frozenset. Here each key is a 64-bit BLAKE2b digest in a sorted array, found
by bisection, and values sit in a parallel typed array: 9-16 bytes per entry.
Building checks that no two keys share a digest, so every stored key is found
exactly; a key that was never stored matches a stored digest with probability
about n / 2**64 (below 1e-13 for the largest table here).

    s = KeySet.build(words)                 'word' in s
    m = KeyMap.build(words, values, "d")    m.get('word'), m['word'], 'word' in m

Tables can be written once at build time (write_tables) and read back with no
sort (read_tables). Tables built and used within one process can key on
Python's own string hash instead (KeyMap.build(..., session=True)), which is
faster to compute and equally unlikely to collide.
"""
from __future__ import annotations

import gzip
import json
import sys
from array import array
from bisect import bisect_left
from hashlib import blake2b

MAGIC = b"PWKT1\n"


def digest(key: str) -> int:
    """The stable 64-bit key digest, used for tables stored in files."""
    return int.from_bytes(blake2b(key.encode("utf-8"), digest_size=8).digest(), "little")


_MASK = (1 << 64) - 1


def session_digest(key: str) -> int:
    """For tables built and used within one process (never written to a file): Python's
    own string hash (64-bit SipHash, keyed per process) for ASCII keys, several times
    faster than the stable digest. Other keys take the stable digest, because CPython
    hashes a string's stored bytes, so 'bk' and U+6B62 hash alike."""
    return hash(key) & _MASK if key.isascii() else digest(key)


class DigestCollision(ValueError):
    pass


def _sorted(keys, values=None, code="i", h=digest):
    """Digests in ascending order (and the values in the same order), with no per-key tuples."""
    d = array("Q", map(h, keys))
    order = sorted(range(len(d)), key=d.__getitem__)
    ds = array("Q", (d[i] for i in order))
    for i in range(1, len(ds)):
        if ds[i] == ds[i - 1]:
            raise DigestCollision("two keys share a 64-bit digest")
    if values is None:
        return ds, None
    vals = values if isinstance(values, (list, array, range)) else list(values)
    return ds, array(code, (vals[i] for i in order))


class KeySet:
    """Membership over a fixed set of strings."""

    __slots__ = ("_d", "_h")

    def __init__(self, digests: array, h=digest):
        self._d, self._h = digests, h

    @classmethod
    def build(cls, keys):
        return cls(_sorted(list(keys))[0])

    def __contains__(self, key) -> bool:
        if not isinstance(key, str):
            return False
        d = self._h(key)
        a = self._d
        i = bisect_left(a, d)
        return i < len(a) and a[i] == d

    def __len__(self) -> int:
        return len(self._d)


class KeyMap:
    """A fixed string -> number mapping, values in a typed array.

    `div`: stored values are integers and the value is stored / div (exact for
    values with that many decimals, e.g. tenths). `memo` > 0 keeps up to that
    many recent lookups in a plain dict, for tables asked about the same few
    hundred words many times per text."""

    __slots__ = ("_d", "_v", "_div", "_memo", "_cap", "_h")

    def __init__(self, digests: array, values: array, div=None, memo: int = 0, h=digest):
        self._d, self._v, self._div, self._h = digests, values, div, h
        self._memo = {} if memo else None
        self._cap = memo

    @classmethod
    def build(cls, keys, values, code: str, div=None, memo: int = 0, session: bool = False):
        """session=True: key with Python's string hash (faster; the table must not be
        written to a file). A digest collision falls back to the stable digest."""
        keys = list(keys)
        if session:
            try:
                d, v = _sorted(keys, values, code, session_digest)
                return cls(d, v, div, memo, session_digest)
            except DigestCollision:
                pass
        d, v = _sorted(keys, values, code)
        return cls(d, v, div, memo)

    def _lookup(self, key):
        if not isinstance(key, str):
            return None
        d = self._h(key)
        a = self._d
        i = bisect_left(a, d)
        if i < len(a) and a[i] == d:
            v = self._v[i]
            return v / self._div if self._div else v
        return None

    def get(self, key, default=None):
        m = self._memo
        if m is None:
            v = self._lookup(key)
        else:
            v = m.get(key, m)
            if v is m:
                v = self._lookup(key)
                if len(m) >= self._cap:
                    m.clear()
                m[key] = v
        return default if v is None else v

    def __getitem__(self, key):
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def __contains__(self, key) -> bool:
        return self.get(key) is not None

    def __len__(self) -> int:
        return len(self._d)


# -- files: sorted digests (and values) as stored, read with no per-entry work ------------

def gunzip(path) -> bytearray:
    """Decompress a single-member .gz file into one buffer of its exact size (from the
    gzip trailer), reading and inflating in small pieces, so neither the compressed file
    nor a second full-size copy is ever held."""
    import zlib
    piece = 1 << 18
    with open(path, "rb") as f:
        f.seek(-4, 2)
        size = int.from_bytes(f.read(4), "little")
        f.seek(0)
        out = bytearray(size)
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        p = 0
        while not d.eof:
            data = d.unconsumed_tail or f.read(piece)
            if not data:
                break
            chunk = d.decompress(data, piece)
            if p + len(chunk) > size:
                break
            out[p:p + len(chunk)] = chunk
            p += len(chunk)
    if p != size or not d.eof:
        with open(path, "rb") as f:
            return bytearray(gzip.decompress(f.read()))     # multi-member or over 4 GB: the plain way
    return out


def _le(a: array) -> bytes:
    if sys.byteorder != "little":
        a = array(a.typecode, a)
        a.byteswap()
    return a.tobytes()


def _from_le(code: str, raw, p: int, n: int):
    a = array(code)
    size = a.itemsize * n
    a.frombytes(raw[p:p + size])
    if sys.byteorder != "little":
        a.byteswap()
    return a, p + size


class TextKeys:
    """A table to be written with its keys as text, in digest order, instead of the
    digests: the file compresses about as well as a word list, and reading it hashes
    each key once (no sort). For tables whose words cost more than 8 bytes to store."""

    def __init__(self, keys, values=None, code=None, div=None):
        keys = list(keys)
        order = sorted(range(len(keys)), key=lambda i: digest(keys[i]))
        self.keys = [keys[i] for i in order]
        vals = None if values is None else list(values)
        self.values = None if vals is None else array(code, (vals[i] for i in order))
        self.div = div
        ds = [digest(k) for k in self.keys]
        if any(a == b for a, b in zip(ds, ds[1:])):
            raise ValueError("two keys share a 64-bit digest; use a longer digest")


def _hash_text(blob, n: int) -> array:
    """Digests of the n newline-separated keys in blob, as a Q array, hashed a slice of
    keys at a time into one preallocated buffer (no full list of keys or digests)."""
    buf = bytes(blob)
    out = bytearray(8 * n)
    piece = 1 << 16
    start = i = 0
    while start <= len(buf) and i < n:
        end = buf.find(b"\n", min(len(buf), start + piece))
        if end < 0:
            end = len(buf)
        keys = buf[start:end].split(b"\n")
        out[8 * i:8 * (i + len(keys))] = b"".join([blake2b(k, digest_size=8).digest() for k in keys])
        i += len(keys)
        start = end + 1
    if i != n:
        raise ValueError(f"packed table: {i} keys, expected {n}")
    a = array("Q")
    a.frombytes(out)
    if sys.byteorder != "little":
        a.byteswap()
    return a


def write_tables(path, tables: dict, meta: dict | None = None) -> None:
    """tables: name -> KeySet | KeyMap (built with .build) | TextKeys. Deterministic gzip output."""
    head, blobs = [], []
    for name, t in tables.items():
        if getattr(t, "_h", digest) is not digest:
            raise ValueError(f"{name}: a session-keyed table cannot be written to a file")
        if isinstance(t, TextKeys):
            text = "\n".join(t.keys).encode("utf-8")
            h = {"name": name, "n": len(t.keys), "text_bytes": len(text)}
            blobs.append(text)
            if t.values is not None:
                h.update(code=t.values.typecode, div=t.div)
                blobs.append(_le(t.values))
            head.append(h)
        elif isinstance(t, KeySet):
            head.append({"name": name, "n": len(t._d)})
            blobs.append(_le(t._d))
        else:
            head.append({"name": name, "n": len(t._d), "code": t._v.typecode, "div": t._div})
            blobs += [_le(t._d), _le(t._v)]
    h = json.dumps({"tables": head, "meta": meta or {}}, sort_keys=True).encode("utf-8")
    raw = MAGIC + len(h).to_bytes(4, "little") + h + b"".join(blobs)
    with open(path, "wb") as f:
        f.write(gzip.compress(raw, compresslevel=9, mtime=0))


def read_tables(path, memo: dict | None = None, with_meta: bool = False):
    """name -> KeySet | KeyMap, as written by write_tables (and the file's meta dict
    too with with_meta=True). memo: name -> memo size."""
    raw = memoryview(gunzip(path))
    if bytes(raw[:len(MAGIC)]) != MAGIC:
        raise ValueError(f"{path} is not a proseweave packed table")
    p = len(MAGIC)
    hl = int.from_bytes(raw[p:p + 4], "little")
    p += 4
    head = json.loads(bytes(raw[p:p + hl]))
    p += hl
    out = {}
    for t in head["tables"]:
        if "text_bytes" in t:
            d = _hash_text(raw[p:p + t["text_bytes"]], t["n"])
            p += t["text_bytes"]
        else:
            d, p = _from_le("Q", raw, p, t["n"])
        if "code" in t:
            v, p = _from_le(t["code"], raw, p, t["n"])
            out[t["name"]] = KeyMap(d, v, t.get("div"), (memo or {}).get(t["name"], 0))
        else:
            out[t["name"]] = KeySet(d)
    return (out, head.get("meta", {})) if with_meta else out
