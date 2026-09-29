"""Reader for the bundled news-and-magazine frequency tables (standard library only).

The tables (data/mag_news_freq.bin.xz) are counts from an open-licensed corpus
of news and magazine-style writing (Common Pile news and Foodista, CC BY;
English Wikinews, CC BY 2.5; Project Gutenberg, public domain), lemmatized and
word-classed the same way proseweave builds its own lists. See
data/LICENSE_mag_news_freq.md and tools/build_mag_news_freq.py.

    per_million("uni", "climate")        -> float | None
    per_million(("plain", 2), "of the")  -> float | None
    per_million(("v_n", 3), "_ year _")  -> float | None   ("_" is the mask)

Keys use proseweave's lemma convention: the possessive determiners and "an"
are counted under their pronoun or article (their -> they, his -> he, our -> we,
your -> you, an -> a), and curly quotes are the same as straight ones.

None means the item is below the tables' floor: rarer than 0.253 per million
in the corpus, which keyness treats as maximally key.

Each table is a set of sorted id columns, searched in place with bisect, so
loading is one decompression and no per-entry work.
"""
from __future__ import annotations

import json
import lzma
import struct
import sys
import threading
from array import array
from bisect import bisect_left, bisect_right
from pathlib import Path

from .packed import KeyMap

PATH = Path(__file__).resolve().parent / "data" / "mag_news_freq.bin.xz"
_LOCK = threading.Lock()
_T = None
_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})


def _column(raw: memoryview, typecode: str, p: int, n: int):
    """A little-endian column: a view on the decompressed bytes on little-endian
    machines (no copy), a byte-swapped copy elsewhere."""
    size = array(typecode).itemsize
    if sys.byteorder == "little":
        return raw[p:p + n * size].cast(typecode), p + n * size
    a = array(typecode)
    a.frombytes(raw[p:p + n * size])
    a.byteswap()
    return a, p + n * size


def _xz_size(f):
    """Uncompressed size of a single-stream .xz file, from its index; None if unsure."""
    f.seek(0, 2)
    end = f.tell()
    if end < 24:
        return None
    f.seek(end - 12)
    foot = f.read(12)
    if foot[-2:] != b"YZ":
        return None
    back = (int.from_bytes(foot[4:8], "little") + 1) * 4
    f.seek(end - 12 - back)
    idx = f.read(back)
    if not idx or idx[0] != 0:
        return None
    p = 1

    def varint():
        nonlocal p
        v = shift = 0
        while True:
            b = idx[p]
            p += 1
            v |= (b & 0x7F) << shift
            shift += 7
            if b < 0x80:
                return v
    total = 0
    for _ in range(varint()):
        varint()                     # unpadded size
        total += varint()            # uncompressed size
    return total


def _decompress(path: Path):
    """xz-decompress into one buffer of the exact final size, reading and decoding in
    small pieces (no second full-size copy, no whole compressed file in memory)."""
    piece = 1 << 18
    with open(path, "rb") as f:
        size = _xz_size(f)
        f.seek(0)
        if size is None:
            return lzma.decompress(f.read())
        out = bytearray(size)
        d = lzma.LZMADecompressor()
        p = 0
        while not d.eof:
            data = f.read(piece) if d.needs_input else b""
            if not data and d.needs_input:
                break
            chunk = d.decompress(data, max_length=piece)
            out[p:p + len(chunk)] = chunk
            p += len(chunk)
    if p != size or not d.eof:
        raise ValueError(f"{path}: decompressed {p} bytes, index says {size}")
    return out


def _load(path: Path = PATH) -> dict:
    raw = memoryview(_decompress(path))
    if bytes(raw[:4]) != b"PWMN":
        raise ValueError(f"{path} is not a proseweave frequency table")
    hl, vl = struct.unpack_from("<II", raw, 4)
    p = 12
    header = json.loads(bytes(raw[p:p + hl]))
    p += hl
    vocab = bytes(raw[p:p + vl]).decode("utf-8").split("\0")
    ids = KeyMap.build(vocab, range(len(vocab)), "I", session=True)      # word -> id, compact
    del vocab
    p += vl
    tables = {}
    id_code = "H" if header.get("id_bytes", 2) == 2 else "I"
    for name, n, total, entries in header["tables"]:
        cols = []
        for _ in range(n):
            col, p = _column(raw, id_code, p, entries)
            cols.append(col)
        counts, p = _column(raw, "I", p, entries)
        tables[name] = (cols, counts, total)
    return {"ids": ids, "tables": tables, "floor_pm": header["floor_pm"]}


def tables() -> dict:
    global _T
    if _T is None:
        with _LOCK:
            if _T is None:
                _T = _load()
    return _T


def _table_name(kind) -> str:
    if kind == "uni":
        return "uni_all"
    m, n = kind
    return f"{m}_{n}"


def count(kind, item: str) -> tuple[int, int]:
    """(count, table total) for an item; count 0 when it is below the floor."""
    T = tables()
    cols, counts, total = T["tables"][_table_name(kind)]
    ids = T["ids"]
    lo, hi = 0, len(counts)
    words = item.translate(_QUOTES).split(" ")
    if len(words) != len(cols):
        return 0, total
    for col, w in zip(cols, words):
        i = ids.get(w)
        if i is None:
            return 0, total
        lo, hi = bisect_left(col, i, lo, hi), bisect_right(col, i, lo, hi)
        if lo == hi:
            return 0, total
    return counts[lo], total


def per_million(kind, item: str) -> float | None:
    c, total = count(kind, item)
    return c * 1e6 / total if c else None
