"""Readability formulas with the conventional word, sentence and syllable counts.

The formulas are the published ones:

  Flesch Reading Ease (Flesch 1948)     206.835 - 1.015 * words/sentences - 84.6 * syllables/words
  Flesch-Kincaid Grade (Kincaid 1975)   0.39 * words/sentences + 11.8 * syllables/words - 15.59
  Automated Readability Index (1967)    4.71 * characters/words + 0.5 * words/sentences - 21.43

and the counts follow the conventions most readability tools use, so the scores
are comparable with theirs:

  words      whitespace-separated after removing punctuation. Hyphens are
             removed, so "well-known" is one word. Apostrophes are kept only
             where they begin a contraction ending (t, s, d, ve, ll, re).
  sentences  maximal runs that start at a word boundary and contain no . ! or ?,
             each with its trailing terminators; runs of two words or fewer are
             not counted (headings, list markers), with a minimum of one.
  syllables  the vowel count of a word's first pronunciation in the CMU
             Pronouncing Dictionary; for words it lacks, the number of US
             English hyphenation points (Liang's algorithm over the TeX
             patterns) plus one.
  characters every non-space character (punctuation included), for ARI, over
             whitespace-separated words.

Data: data/syllables_en.bin.gz (CMU Pronouncing Dictionary 0.7a, BSD) and
data/hyph_en_US.dic.gz (US English hyphenation patterns, BSD-style). See
data/LICENSE_syllables.md.
"""
from __future__ import annotations

import gzip
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"

_CONTRACTION_END = r"[tsd]|ve|ll|re"
_STRAY_APOSTROPHE = re.compile(r"'(?!" + _CONTRACTION_END + ")")
_PUNCT_KEEP_APOSTROPHE = re.compile(r"[^\w\s']")
_SENTENCE = re.compile(r"\b[^.!?]+[.!?]*", re.UNICODE)
_SPACE = re.compile(r"\s")


def words(text: str) -> list[str]:
    """Words with punctuation removed (contraction apostrophes kept)."""
    return _PUNCT_KEEP_APOSTROPHE.sub("", _STRAY_APOSTROPHE.sub("", text)).split()


def sentence_count(text: str) -> int:
    if not text:
        return 0
    runs = _SENTENCE.findall(text)
    return max(1, sum(1 for r in runs if len(words(r)) > 2))


# -- syllables ------------------------------------------------------------------
@lru_cache(maxsize=1)
def _dictionary():
    """word -> syllable count (CMUdict), a packed read-only map (tools/pack_tables.py)."""
    from .packed import read_tables
    return read_tables(DATA / "syllables_en.bin.gz")["syllables"]


@lru_cache(maxsize=1)
def _patterns() -> tuple[dict, int]:
    """Liang patterns: letters -> the digit values between (and around) them."""
    pats, longest = {}, 0
    lines = gzip.decompress((DATA / "hyph_en_US.dic.gz").read_bytes()).decode("utf-8").splitlines()
    for line in lines[1:]:                      # line 1 names the encoding
        line = line.strip()
        if not line or line.startswith("%") or line.split(" ")[0].isupper():
            continue                            # comments and LEFTHYPHENMIN-style settings
        letters, values = [], [0]
        for ch in line:
            if ch.isdigit():
                values[-1] = int(ch)
            else:
                letters.append(ch)
                values.append(0)
        key = "".join(letters)
        pats[key] = values
        longest = max(longest, len(key))
    return pats, longest


def hyphenation_points(word: str, left: int = 2, right: int = 2) -> list[int]:
    """Positions p (a break before word[p]) that Liang's algorithm allows, at
    least `left` letters from the start and `right` from the end."""
    pats, longest = _patterns()
    w = "." + word.lower() + "."
    points = [0] * (len(w) + 1)
    for i in range(len(w)):
        for j in range(i + 1, min(len(w), i + longest) + 1):
            v = pats.get(w[i:j])
            if v:
                for k, x in enumerate(v):
                    if x > points[i + k]:
                        points[i + k] = x
    # points[b] is the value at the boundary before w[b]; w[b] is word[b - 1]
    return [b - 1 for b in range(len(w)) if points[b] % 2 and left <= b - 1 <= len(word) - right]


def syllables(word: str) -> int:
    n = _dictionary().get(word)
    if n is not None:
        return n
    return len(hyphenation_points(word)) + 1


def syllable_count(text: str) -> int:
    return sum(syllables(w) for w in words(text.lower()))


# -- the formulas -----------------------------------------------------------------
def scores(text: str) -> dict:
    n_words = len(words(text))
    n_sents = sentence_count(text)
    wps = n_words / n_sents if n_sents else 0.0
    spw = syllable_count(text) / n_words if n_words else 0.0
    raw_words = len(text.split())
    cpw = len(_SPACE.sub("", text)) / raw_words if raw_words else 0.0
    return {
        "flesch_reading_ease": 0.0 if not (wps and spw) else 206.835 - 1.015 * wps - 84.6 * spw,
        "flesch_kincaid_grade": 0.0 if not (wps and spw) else 0.39 * wps + 11.8 * spw - 15.59,
        "automated_readability_index": 0.0 if not (cpw and wps) else 4.71 * cpw + 0.5 * wps - 21.43,
    }
