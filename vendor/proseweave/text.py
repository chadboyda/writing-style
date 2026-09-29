"""Tokens, sentences, paragraphs and lemmas, in the standard library.

Every index in proseweave is built from these annotations. They follow
spaCy's English conventions closely, without any model on disk:

  - curly apostrophes and single quotes (’ ‘) are read as the straight
    apostrophe ('), so "don’t" and "don't" give the same tokens;
  - tokenization follows spaCy's English rules: contractions split (do + n't),
    hyphens between letters split, leading and trailing punctuation detached,
    common abbreviations kept whole;
  - sentence boundaries follow terminal punctuation, paragraph breaks and an
    abbreviation list;
  - lemmas use the rule-lemmatizer algorithm spaCy describes, over its
    WordNet-derived tables (data/lemma_en.json.gz), which is deterministic once
    the word class is known.

The one thing a table cannot supply is the word class of an ambiguous word in
context. That comes from the bundled tagger, with Jev deciding the words it is
unsure of (see tagger_classes.py); `closed_class()` covers the words whose
class is fixed by the tagset regardless of context.

Data licences: the spaCy tables are MIT; the lemma tables derive from WordNet
3.0 (Princeton WordNet licence). See NOTICE.
"""
from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass, field
from functools import cached_property, lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"

from .packed import read_tables  # noqa: E402


@lru_cache(maxsize=1)
def stop_words() -> frozenset:
    return frozenset((DATA / "stop_words_en.txt").read_text().split())


@lru_cache(maxsize=1)
def lemma_tables() -> dict:
    with gzip.open(DATA / "lemma_en.json.gz", "rb") as f:
        t = json.loads(f.read())
    # the index (known lemmas per class) is digest-sorted sets: tools/pack_tables.py
    t["lemma_index"] = read_tables(DATA / "lemma_index_en.bin.gz")
    return t


_SYNONYMS = None


def synonyms() -> dict:
    """{"noun"|"verb": set of synonym_key(lemma, synonym)} from WordNet 3.0 (cached):
    `synonym_key(a, b) in synonyms()["noun"]` when noun b is a synonym of a."""
    global _SYNONYMS
    if _SYNONYMS is None:
        _SYNONYMS = read_tables(DATA / "synonyms_en.bin.gz")
    return _SYNONYMS


def synonym_key(lemma: str, other: str) -> str:
    return lemma + "\0" + other


# --------------------------------------------------------------------------
# tokenization

ABBREVIATIONS = frozenset("""
mr mrs ms dr prof st jr sr vs etc e.g i.e u.s u.k u.n a.m p.m no mt gen col lt sgt capt cmdr rep sen
gov pres rev hon jan feb mar apr jun jul aug sep sept oct nov dec inc ltd co corp dept univ approx
est fig vol pp ed eds al cf ca
""".split())

CONTRACTIONS = ("n't", "'s", "'re", "'ve", "'ll", "'d", "'m")
SPECIAL_NT = {"can't": ("ca", "n't"), "won't": ("wo", "n't"), "shan't": ("sha", "n't"), "cannot": ("can", "not")}
APOSTROPHES = str.maketrans({"’": "'", "‘": "'"})


def normalize_apostrophes(text: str) -> str:
    """Curly apostrophes and single quotes (’ ‘) as the straight apostrophe."""
    return text.translate(APOSTROPHES)
LEAD = "\"'“‘([{«<*_"
TRAIL = "\"'”’)]}»>.,;:!?*_…"
INFIX = re.compile(r"(?<=[A-Za-z])(—|–|--+|-|/|~)(?=[A-Za-z])")


def _split_chunk(chunk: str) -> list[str]:
    out_front, out_back = [], []
    while chunk and chunk[0] in LEAD:
        out_front.append(chunk[0])
        chunk = chunk[1:]
    while chunk:
        if chunk.endswith("..."):
            out_back.insert(0, "...")
            chunk = chunk[:-3]
            continue
        last = chunk[-1]
        if last in TRAIL:
            # keep a period that belongs to an abbreviation or an initial
            if last == "." and (chunk[:-1].lower().rstrip(".") in ABBREVIATIONS
                                or re.fullmatch(r"(?:[A-Za-z]\.)+[A-Za-z]?", chunk)
                                or re.fullmatch(r"[A-Z]", chunk[:-1])):
                break
            out_back.insert(0, last)
            chunk = chunk[:-1]
            continue
        break
    mid = []
    if chunk:
        low = chunk.lower()
        if low in SPECIAL_NT:
            a, b = SPECIAL_NT[low]
            mid = [chunk[:len(a)], chunk[len(a):]] if low != "cannot" else [chunk[:3], chunk[3:]]
        else:
            for c in CONTRACTIONS:
                if low.endswith(c) and len(chunk) > len(c):
                    mid = [chunk[:-len(c)], chunk[-len(c):]]
                    break
            if not mid:
                parts = INFIX.split(chunk)
                mid = [p for p in parts if p]
    return out_front + mid + out_back


def tokenize(text: str) -> list[str]:
    toks = []
    for chunk in normalize_apostrophes(text).split():
        toks.extend(_split_chunk(chunk))
    return toks


def is_alpha(tok: str) -> bool:
    return tok.isalpha()


# --------------------------------------------------------------------------
# paragraphs and sentences

def paragraphs(text: str, single_newline: bool = False) -> list[str]:
    """Blank-line paragraphs by default; single_newline=True treats every
    newline as a paragraph break."""
    parts = text.split("\n") if single_newline else re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


_END = re.compile(r"[.!?]+[\"'”’)\]]*$")


def sentences(tokens: list[str]) -> list[list[str]]:
    """Split a paragraph's tokens into sentences at terminal punctuation."""
    out, cur = [], []
    for i, t in enumerate(tokens):
        cur.append(t)
        if t in (".", "!", "?", "...", "…") or (_END.search(t) and not t[:-1].lower().rstrip(".") in ABBREVIATIONS
                                                 and len(t) > 1 and not t[0].isalpha()):
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            # absorb closing quotes/brackets into the sentence they close
            if nxt and nxt in "\"'”’)]}»":
                continue
            if nxt is None or nxt[:1].isupper() or nxt[:1] in "\"'“‘([" or nxt[:1].isdigit():
                out.append(cur)
                cur = []
        elif t in "\"'”’)]}»" and cur[:-1] and cur[-2] in (".", "!", "?", "...", "…"):
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if nxt is None or nxt[:1].isupper() or nxt[:1] in "\"'“‘(":
                out.append(cur)
                cur = []
    if cur:
        out.append(cur)
    return out


@dataclass
class Doc:
    text: str
    units: list = field(default_factory=list)      # para -> sent -> syntax.Token

    def _shape(self, get):
        return [[[get(t) for t in s] for s in p] for p in self.units]

    @cached_property
    def paragraphs(self) -> list[list[list[str]]]:
        """para -> sent -> token texts, curly apostrophes straightened."""
        return self._shape(lambda t: normalize_apostrophes(t.text))

    @cached_property
    def sentences(self) -> list[list[str]]:
        return [s for p in self.paragraphs for s in p]

    @cached_property
    def tokens(self) -> list[str]:
        return [t for s in self.sentences for t in s]

    @cached_property
    def sentence_tokens(self) -> list:
        """sent -> syntax.Token (tag, lemma, margin, head)."""
        return [s for p in self.units for s in p]


def parse(text: str, single_newline_paragraphs: bool = False) -> Doc:
    """Paragraphs of sentences of tokens, from the bundled tokenizer and
    sentence segmenter (syntax.py). A paragraph break (a newline, or with
    single_newline_paragraphs=False a blank line) always ends a sentence.
    The text is parsed with curly apostrophes straightened, as the cohesion
    indices' conventions expect; the basic-feature counts use the raw text
    (Analysis.parsed)."""
    from . import syntax
    d = Doc(text=text)
    para, sent = [], []

    def close_sentence():
        # A "sentence" with no word in it (a closing quote the segmenter set
        # before the next sentence, cut off by a paragraph break) stays with the
        # sentence it closes.
        if sent and para and not any(ch.isalnum() for t in sent for ch in t.text):
            para[-1].extend(sent)
        elif sent:
            para.append(sent)

    for t in syntax.analyse(normalize_apostrophes(text)):
        if t.is_space:
            if "\n" in t.text and (single_newline_paragraphs or re.search(r"\n\s*\n", t.text)):
                close_sentence()
                if para:
                    d.units.append(para)
                para, sent = [], []
            continue
        if t.sent_start and sent:
            close_sentence()
            sent = []
        sent.append(t)
    close_sentence()
    if para:
        d.units.append(para)
    return d


# --------------------------------------------------------------------------
# lemmas: a rule lemmatizer over spaCy's English tables

def lemmatize(word: str, upos: str) -> str:
    """Lemma for a word given its coarse class (NOUN, VERB, ADJ, ADV, ...).

    Follows spaCy's rule-lemmatizer algorithm: exceptions first, then suffix rules whose
    output is a known word in the WordNet index, then the out-of-vocabulary
    rule output, then the word itself. spaCy additionally treats morphological
    base forms (singular nouns, infinitives, positive adjectives) as their own
    lemma; without a morphological analyser that is approximated by "the word
    is already in the index for its class".
    """
    pos = upos.lower()
    t = lemma_tables()
    low = word.lower()
    if pos == "propn":
        return word
    index = t["lemma_index"].get(pos)
    exc = t["lemma_exc"].get(pos, {})
    rules = t["lemma_rules"].get(pos, [])
    if not index and not exc and not rules:
        return low
    index = index or frozenset()
    forms, oov = [], []
    for old, new in rules:
        if low.endswith(old):
            form = low[: len(low) - len(old)] + new
            if not form:
                continue
            if form in index or not form.isalpha():
                if form not in forms:
                    forms.append(form)
            else:
                oov.append(form)
    # spaCy inserts each exception at position 0 in turn, so the LAST listed
    # exception ends up first (better -> well, not good).
    for form in exc.get(low, []):
        if form not in forms:
            forms.insert(0, form)
    if forms:
        return forms[0]
    # No rule reached a known word: spaCy would have called this a base form
    # from its tag (a singular noun, an infinitive). A word already in the index
    # is the closest thing to that without a morphological analyser.
    if low in index:
        return low
    if oov:
        return oov[0]
    return low


# Words whose Universal Dependencies class does not depend on context.
_CLOSED = {}
for _w in "am is are was were be been being can could may might must shall should will would".split():
    _CLOSED[_w] = "AUX"
for _w in "i me my mine myself you your yours yourself yourselves he him his himself she her hers herself " \
          "it its itself we us our ours ourselves they them their theirs themselves".split():
    _CLOSED[_w] = "PRON"
for _w in "the a an".split():
    _CLOSED[_w] = "DET"
for _w in "and or nor".split():
    _CLOSED[_w] = "CONJ"
for _w in "of".split():
    _CLOSED[_w] = "ADP"


def closed_class(word: str) -> str | None:
    return _CLOSED.get(word.lower())
