"""zipf_mean / zipf_std from an open word-frequency table, with Jev for rare words.

zipf_mean/std: the mean and population SD of Zipf values over the first 500
alphabetic non-stop tokens, counting those the table knows. Zipf is log10 frequency per billion
words; tokens are lowercased; the table is data/zipf_en.bin.gz: 147k words seen
at least 5 times in 120M words of CC BY and public-domain text
(data/LICENSE_zipf_en.md; built by tools/build_zipf_table.py).

With Jev, words among those 500 that the table has seen rarely (Zipf below 2)
or not at all - about 9 per document - also get Jev's familiarity judgement
(annotate.familiarity), mapped onto the Zipf scale: a rare word's value is the
average of the two, and an unknown word is included only if Jev rates it at
least somewhat familiar (level 1 or above).
"""
from __future__ import annotations

import pathlib
import statistics

from .packed import read_tables

DATA = pathlib.Path(__file__).resolve().parent / "data" / "zipf_en.bin.gz"
RARE = 2.0
FAM_TO_ZIPF = (1.56, 0.82)        # zipf ~ a + b * familiarity level (0-5), fitted on even texts
_TABLE = None


def table():
    """word -> Zipf value: a read-only mapping (get, [], in) over the packed table
    (tools/pack_tables.py; values stored as tenths and returned exactly)."""
    global _TABLE
    if _TABLE is None:
        _TABLE = read_tables(DATA)["zipf"]
    return _TABLE


def zipf_features(content_words: list[str], j=None, limit: int = 500) -> dict[str, float]:
    """content_words: alphabetic non-stop tokens in text order. j: a jev.Jev, or None."""
    t = table()
    words = [w.lower() for w in content_words[:limit]]
    fam = {}
    if j is not None:
        from . import annotate
        rare = sorted({w for w in words if t.get(w, 0) < RARE})
        if rare:
            fam = annotate.familiarity(j, rare)
    a, b = FAM_TO_ZIPF
    vals = []
    for w in words:
        f = fam.get(w)
        if w in t:
            v = t[w]
            if v < RARE and f is not None:
                v = 0.5 * v + 0.5 * (a + b * f)
        elif f is not None and f >= 1:
            v = a + b * f
        else:
            continue
        vals.append(v)
    return {"zipf_mean": statistics.fmean(vals) if vals else 0.0,
            "zipf_std": statistics.pstdev(vals) if vals else 0.0}
