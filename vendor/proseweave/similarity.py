"""Semantic similarity between segments of a text, and between two texts.

The cohesion research literature measures how related neighbouring sentences
and paragraphs are with trained semantic spaces: latent semantic analysis
(LSA), topic models (LDA) and word2vec-style embeddings. Two segments are
compared by summing the vectors of their words and taking the cosine; for a
topic model, by comparing the two topic distributions (1 - Jensen-Shannon
divergence). This module builds on that published method with spaces trained
on openly licensed data (see data/SIMILARITY_NOTICE.md):

  glove    GloVe 6B word vectors (Pennington, Socher & Manning 2014), PDDL
  wlsa     an LSA space trained on WikiText-103 (CC BY-SA 3.0)
  wvec     a word2vec space trained on WikiText-103
  sent     static word vectors fitted so that their average reproduces a
           sentence-embedding model's output (all-MiniLM-L6-v2, Apache 2.0)

Each published index is computed from the one to three space variants that
tracked it best in validation (validation/RESULTS.md), combined as a mean of
standardised scores and put back on the index's usual scale. The LDA-named
indices currently come from the vector spaces too; a topic space ("topic" kind,
compared by 1 - Jensen-Shannon) is supported by the table format. Everything here is standard
library; the vectors live in 4-bit tables under data/, one file per licence.

    from proseweave import similarity
    similarity.segment_indices(lists)           # 12 adjacent-segment indices
    similarity.source_indices(target, source)   # 3 target-vs-source indices
    similarity.sentence_cohesion(text, j)       # 6 sentence/paragraph indices
"""
from __future__ import annotations

import array
import json
import math
import operator
import re
import statistics
import unicodedata
from functools import lru_cache
from pathlib import Path

from .packed import KeyMap, gunzip

DATA = Path(__file__).resolve().parent / "data"
# One file per licence (data/SIMILARITY_NOTICE.md); routes are proseweave's own fitted numbers.
TABLES = [DATA / "similarity_glove.bin.gz", DATA / "similarity_wiki.bin.gz", DATA / "similarity_sent.bin.gz",
          DATA / "similarity_topics.bin.gz"]
ROUTES = DATA / "similarity_routes.json"
STOP_WORDS = DATA / "stop_words_en.txt"


# --------------------------------------------------------------------------
# the table

# -- WordPiece (uncased): the tokenization the sentence space was trained with --------

def _is_punct(ch):
    cp = ord(ch)
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith("P")


def _is_cjk(cp):
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x20000 <= cp <= 0x2A6DF or 0x2A700 <= cp <= 0x2B73F
            or 0x2B740 <= cp <= 0x2B81F or 0x2B820 <= cp <= 0x2CEAF or 0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F)


def _basic_words(text):
    """Lower-case, strip accents, drop control characters, split off punctuation."""
    buf = []
    for ch in text:
        cp = ord(ch)
        cat = unicodedata.category(ch)
        if cp == 0 or cp == 0xFFFD or (cat.startswith("C") and ch not in "\t\n\r"):
            continue
        if ch in " \t\n\r" or cat == "Zs":
            buf.append(" ")
        elif _is_cjk(cp):
            buf.append(f" {ch} ")
        else:
            buf.append(ch)
    words = []
    for w in "".join(buf).lower().split():
        w = "".join(c for c in unicodedata.normalize("NFD", w) if unicodedata.category(c) != "Mn")
        cur = ""
        for c in w:
            if _is_punct(c):
                if cur:
                    words.append(cur)
                words.append(c)
                cur = ""
            else:
                cur += c
        if cur:
            words.append(cur)
    return words


def _wordpiece(word, vocab):
    """Greedy longest-match subwords ("##" marks a continuation); [UNK] if none fits."""
    if len(word) > 100:
        return ["[UNK]"]
    pieces, start = [], 0
    while start < len(word):
        end, cur = len(word), None
        while start < end:
            sub = word[start:end] if start == 0 else "##" + word[start:end]
            if sub in vocab:
                cur = sub
                break
            end -= 1
        if cur is None:
            return ["[UNK]"]
        pieces.append(cur)
        start = end
    return pieces


_WP_CACHE: dict = {}


def wordpiece_tokens(text, vocab, limit=254):
    out = []
    for w in _basic_words(text):
        p = _WP_CACHE.get(w)
        if p is None:
            p = _WP_CACHE[w] = _wordpiece(w, vocab)
        out.extend(p)
    return out[:limit]


_HI = bytes(((b >> 4) - 8) & 0xFF for b in range(256))
_LO = bytes(((b & 15) - 8) & 0xFF for b in range(256))


class Space:
    """One semantic space: a vocabulary (rows in frequency order) and its vectors.

    Vector spaces hold 4-bit values with one float scale per row; the topic
    model holds each word's largest topic shares as (topic, share) byte pairs."""

    def __init__(self, meta: dict, blob: memoryview, offset: int):
        self.name = meta["name"]
        self.kind = meta["kind"]                  # "vec" or "topic"
        self.dims = meta["dims"]
        words = meta.pop("words")
        n = len(words)
        self.index = _index_for(words)            # word -> row, compact (packed.KeyMap)
        prob = meta.pop("prob", None)             # unigram probability per row, where SIF weights need it
        self.prob = array.array("d", prob) if prob else None
        self.tokenizer = meta.get("tokenizer")    # "wordpiece" for the sentence space
        self.head = meta.get("head")              # optional residual layer after pooling
        self.mean = meta.get("mean")              # common direction of the space
        self.pcs = meta.get("pcs", [])            # its leading principal axes
        self.scale = array.array("f")
        self.scale.frombytes(bytes(blob[offset:offset + 4 * n]))
        offset += 4 * n
        if self.kind == "topic":
            self.topk = meta["topk"]
            size = n * self.topk * 2
            self.mat = bytes(blob[offset:offset + size])
        else:
            size = (n * self.dims + 1) // 2
            if self.dims % 2 == 0:
                # rows start on whole bytes: keep the 4-bit values packed and unpack a
                # row the first time a text uses its word (row())
                self.packed = blob[offset:offset + size]      # a view: the file's buffer stays, no copy
                self.mat = None
            else:
                vals = bytearray(size * 2)
                step = 1 << 18
                for a in range(0, size, step):
                    pk = blob[offset + a:offset + min(size, a + step)].tobytes()
                    vals[2 * a:2 * a + 2 * len(pk):2] = pk.translate(_HI)
                    vals[2 * a + 1:2 * a + 2 * len(pk):2] = pk.translate(_LO)
                del vals[n * self.dims:]
                self.mat = memoryview(vals).cast("b")     # signed 4-bit values, one byte each
            self._rows = {}
        self.end = offset + size

    ROW_MEMO = 10_000

    def row(self, i: int):
        """Row i's values (signed ints), unpacked once and kept while the memo has room."""
        d = self.dims
        if self.mat is not None:
            return self.mat[i * d:(i + 1) * d]
        r = self._rows.get(i)
        if r is None:
            h = d // 2
            pk = self.packed[i * h:(i + 1) * h].tobytes()
            b = bytearray(d)
            b[0::2] = pk.translate(_HI)
            b[1::2] = pk.translate(_LO)
            r = memoryview(b).cast("b")
            if len(self._rows) >= self.ROW_MEMO:
                self._rows.clear()
            self._rows[i] = r
        return r


_INDEXES: dict = {}


def _index_for(words):
    """One compact word -> row map per distinct vocabulary (spaces trained on the same
    corpus share theirs). Its memo keeps the few hundred words a text uses as a dict."""
    key = (len(words), words[0] if words else "", words[-1] if words else "")
    got = _INDEXES.get(key)
    if got is None or got[0] != words:
        got = (words, KeyMap.build(words, range(len(words)), "i", memo=20_000, session=True))
        _INDEXES[key] = got
    return got[1]


@lru_cache(maxsize=1)
def tables() -> dict:
    spaces = {}
    for path in TABLES:
        if not path.exists():
            continue
        raw = gunzip(path)
        nl = raw.index(b"\n")
        header = json.loads(raw[:nl].decode("utf-8"))
        blob = memoryview(raw)[nl + 1:]
        off = 0
        for meta in header["spaces"]:
            sp = Space(meta, blob, off)
            spaces[sp.name] = sp
            off = sp.end
    _INDEXES.clear()          # the maps live on in their spaces; the vocabulary lists can go
    routes = json.loads(ROUTES.read_text(encoding="utf-8"))
    stop = frozenset(STOP_WORDS.read_text(encoding="utf-8").split())
    return {"spaces": spaces, "routes": routes, "stop": stop}


# --------------------------------------------------------------------------
# segment vectors

def _weights(sp: Space, variant: dict, stop: frozenset):
    """Per-word weight for a space variant: stop words and the most frequent
    words can be left out, and SIF-style down-weighting a / (a + p(w)) applied."""
    drop = variant.get("drop_top", 0)
    use_stop = variant.get("stop", True)
    sif = variant.get("sif", 0.0)

    def w(word):
        i = sp.index.get(word)
        if i is None or i < drop or (use_stop and word in stop):
            return None, 0.0
        s = sp.scale[i]
        if sif and sp.prob:
            s *= sif / (sif + sp.prob[i])
        return i, s
    return w


def segment_vector(sp: Space, words, weight) -> list[float]:
    """Sum of the word vectors of a segment (words not in the space are skipped)."""
    acc = [0.0] * sp.dims
    d = sp.dims
    mat = sp.mat
    if sp.kind == "topic":
        k2 = sp.topk * 2
        for word in words:
            i, s = weight(word)
            if i is None or not s:
                continue
            for j in range(i * k2, (i + 1) * k2, 2):
                acc[mat[j]] += s * mat[j + 1]
        return acc
    row = sp.row
    for word in words:
        i, s = weight(word)
        if i is None or not s:
            continue
        r = row(i)
        for k in range(d):
            acc[k] += s * r[k]
    return acc


def postprocess(sp: Space, vec, mass: float, variant: dict):
    """Optionally centre a summed vector (subtract the words' total weight times the space's mean vector)
    and remove its leading principal axes. Both are linear, so doing it to the sum
    equals doing it to every word vector (Mu & Viswanath 2018)."""
    if variant.get("center") or variant.get("abtt"):
        vec = [x - mass * m for x, m in zip(vec, sp.mean)]
    for u in sp.pcs[:variant.get("abtt", 0)]:
        d = sum(x * y for x, y in zip(vec, u))
        vec = [x - d * y for x, y in zip(vec, u)]
    return vec


def variant_vector(sp: Space, words, variant: dict, stop: frozenset) -> list[float]:
    """A segment's summed vector under a space variant, post-processed if the variant says so."""
    weight = _weights(sp, variant, stop)
    vec = segment_vector(sp, words, weight)
    if sp.kind == "vec" and (variant.get("center") or variant.get("abtt")):
        mass = 0.0
        for w in words:
            i, s = weight(w)
            if i is not None:
                mass += s / sp.scale[i]
        vec = postprocess(sp, vec, mass, variant)
    return vec


def cosine(u, v):
    num = sum(a * b for a, b in zip(u, v))
    nu = math.sqrt(sum(a * a for a in u))
    nv = math.sqrt(sum(b * b for b in v))
    return num / (nu * nv) if nu and nv else None


def js_similarity(u, v):
    """1 - Jensen-Shannon divergence (log base 2) of two topic-count vectors."""
    su, sv = sum(u), sum(v)
    if su <= 0 or sv <= 0:
        return None
    p = [x / su for x in u]
    q = [x / sv for x in v]
    js = 0.0
    for a, b in zip(p, q):
        m = (a + b) / 2
        if a > 0:
            js += 0.5 * a * math.log2(a / m)
        if b > 0:
            js += 0.5 * b * math.log2(b / m)
    val = 1 - js
    return val if val >= 0 else None


def _adjacent(vecs, win, fn):
    """Mean similarity of each segment with the next one (win=1) or the next two
    concatenated (win=2); a segment pair with no usable words is skipped."""
    n = len(vecs)
    if n < win + 1:
        return 0.0
    vals = []
    for i in range(n - win):
        right = vecs[i + 1] if win == 1 else [a + b for a, b in zip(vecs[i + 1], vecs[i + 2])]
        x = fn(vecs[i], right)
        if x is not None:
            vals.append(x)
    return sum(vals) / len(vals) if vals else 0.0


def _combine(route: dict, raw: dict) -> float:
    """Mean of standardised component scores, mapped back to the index's scale."""
    z = [(raw[c["key"]] - c["mean"]) / c["sd"] for c in route["parts"]]
    return route["a"] + route["b"] * (sum(z) / len(z))


# --------------------------------------------------------------------------
# public entry points

def segment_indices(lists) -> dict:
    """lsa/lda/word2vec _{1,2}_all_{sent,para}: adjacent-segment similarity over
    each sentence's and each paragraph's lemmas (cohesion.Lists)."""
    T = tables()
    raw = {}
    levels = {"sent": lists.sent["all"], "para": lists.para["all"]}
    needed = {c["key"] for r in T["routes"].values() if r.get("family") == "segment" for c in r["parts"]}
    by_variant = {}
    for key in needed:
        space, variant, lv, win = key.split("|")
        by_variant.setdefault((space, variant, lv), set()).add(int(win))
    for (space, variant, lv), wins in by_variant.items():
        sp = T["spaces"][space]
        var = T["routes"]["_variants"][variant]
        vecs = [variant_vector(sp, seg, var, T["stop"]) for seg in levels[lv]]
        fn = js_similarity if sp.kind == "topic" else cosine
        for win in wins:
            raw[f"{space}|{variant}|{lv}|{win}"] = _adjacent(vecs, win, fn)
    return {p: _combine(r, raw) for p, r in T["routes"].items()
            if not p.startswith("_") and r.get("family") == "segment"}


def source_indices(target_lemmas, source_lemmas) -> dict:
    """source_similarity_{lsa,lda,word2vec}: the whole target against the whole source."""
    T = tables()
    raw = {}
    for p, r in T["routes"].items():
        if p.startswith("_") or r.get("family") != "source":
            continue
        for c in r["parts"]:
            space, variant = c["key"].split("|")[:2]
            sp = T["spaces"][space]
            var = T["routes"]["_variants"][variant]
            a = variant_vector(sp, target_lemmas, var, T["stop"])
            b = variant_vector(sp, source_lemmas, var, T["stop"])
            fn = js_similarity if sp.kind == "topic" else cosine
            v = fn(a, b)
            raw[c["key"]] = v if v is not None else c["mean"]
    return {p: _combine(r, raw) for p, r in T["routes"].items()
            if not p.startswith("_") and r.get("family") == "source"}


# -- sentence-embedding cohesion ----------------------------------------------
# Sentences break where a sentence-embedding pipeline breaks them: after
# terminal punctuation followed by space, never at a bare line break.

ABBREV = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "v", "e.g", "i.e", "inc", "ltd",
          "co", "corp", "vol", "fig", "al", "u.s", "u.k", "jan", "feb", "mar", "apr", "jun", "jul",
          "aug", "sep", "sept", "oct", "nov", "dec", "gen", "col", "lt", "sgt", "capt", "rev", "gov",
          "sen", "rep", "ft", "mt", "approx", "dept", "est", "pp", "ch", "ed", "eds", "cf", "ca"}
_END = re.compile(r'[.!?…]+["\'”’)\]]*(?=\s)')
_WORD_BEFORE = re.compile(r'(?:^|[\s(\[“"‘-])([A-Za-z.]+)$')
_TOK = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def split_sentences(text: str, stop: frozenset = frozenset()) -> list[str]:
    out, start = [], 0
    for m in _END.finditer(text):
        end = m.end()
        punct = m.group(0)
        word = _WORD_BEFORE.search(text[start:m.start()])
        rest = text[end:].lstrip()
        if punct.startswith(".") and len(punct.rstrip("\"'”’)]")) == 1:
            if word and word.group(1).lower().rstrip(".") in ABBREV:
                continue
            if rest and rest[0].islower():
                continue
            nxt = re.match(r"[A-Za-z]+", rest)
            if (word and len(word.group(1)) == 1 and word.group(1).isupper() and nxt
                    and nxt.group(0).lower() not in stop):
                continue    # a middle initial: "David X. Li"
        s = text[start:end].strip()
        if s:
            out.append(s)
        start = end
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


def _sentence_vectors(sents, T):
    """{space name: unit vector per sentence} for the spaces the pair blend uses."""
    out = {}
    for name, variant in T["routes"]["_pair"]["vectors"].items():
        sp = T["spaces"][name]
        weight = _weights(sp, T["routes"]["_variants"][variant], T["stop"])
        bias = sp.index.get("<s>")
        vs = []
        if sp.tokenizer == "wordpiece":
            for s in sents:
                # Curly and straight apostrophes are one character, as everywhere in
                # proseweave. The teacher model tokenizes ’ separately, so this moves
                # results slightly (at most ~0.007 per index; per-pair r 0.8151 ->
                # 0.8145); kept deliberately for consistency.
                s = s.replace("’", "'").replace("‘", "'")
                v = segment_vector(sp, wordpiece_tokens(s, sp.index) + ["<s>"], weight)
                vs.append(_unit(_head(sp, _unit(v)) if sp.head else v))
            out[name] = vs
            continue
        for s in sents:
            toks = _TOK.findall(s.lower().replace("’", "'").replace("‘", "'"))
            v = segment_vector(sp, toks, weight)
            ws = [weight(t) for t in toks]
            n = sum(1 for i, _ in ws if i is not None)
            if bias is not None:     # the fitted sentence space has a sentence-level offset row
                b = sp.row(bias)
                s_b = sp.scale[bias]
                v = [(x + s_b * y) / (n + 1) for x, y in zip(v, b)]
            else:
                mass = sum(s / sp.scale[i] for i, s in ws if i is not None)   # total word weight
                v = postprocess(sp, v, mass, T["routes"]["_variants"][variant])
            vs.append(_unit(v))
        out[name] = vs
    return out


JEV_PAIRS_PER_1000_WORDS = 100


def _head(sp, v):
    """out = v + W2 relu(W1 v + b1) + b2"""
    h = sp.head
    hid = [max(0.0, b + sum(map(operator.mul, row, v))) for row, b in zip(h["w1"], h["b1"])]
    return [x + b + sum(map(operator.mul, row, hid)) for x, row, b in zip(v, h["w2"], h["b2"])]


def sentence_cohesion(text: str, j=None) -> dict:
    """semantic_cohesion_{mean,std,min,max} over adjacent sentences and
    paragraph_cohesion_{mean,std} over adjacent blank-line paragraphs.

    Each sentence pair's similarity is a fixed linear blend of the cosines in
    the vector spaces and, when a Jev client is given, Jev's STS-scale rating
    of the pair asked in both orders. A paragraph is the average of its
    sentences' unit vectors, so paragraph similarity follows from the sentence
    pairs: cos(mean A, mean B) = mean k(a, b) / sqrt(mean k(a, a') mean k(b, b'))."""
    T = tables()
    pair = T["routes"]["_pair"]
    stop = T["stop"]
    sents = split_sentences(text, stop)
    paras = [split_sentences(p.strip(), stop) for p in text.split("\n\n")]
    paras = [p for p in paras if p]
    uniq = list(dict.fromkeys(sents + [s for p in paras for s in p]))
    pos = {s: i for i, s in enumerate(uniq)}
    vecs = _sentence_vectors(uniq, T)

    # Pairs in priority order: adjacent sentences, then sentences of adjacent
    # paragraphs, then sentences within a paragraph. Jev rates the first
    # JEV_PAIRS_PER_1000_WORDS (scaled to the text's length); the rest use the
    # vectors-only blend, which is fitted to the same target.
    ordered = list(zip(sents, sents[1:]))
    for i in range(len(paras) - 1):
        ordered += [(a, b) for a in paras[i] for b in paras[i + 1]]
    for P in paras:
        ordered += [(P[i], P[k]) for i in range(len(P)) for k in range(i + 1, len(P))]
    seen, pairs = set(), []
    for a, b in ordered:
        if a != b and (a, b) not in seen and (b, a) not in seen:
            seen.add((a, b))
            pairs.append((a, b))

    jev = {}
    if j is not None:
        from . import annotate
        budget = max(50, int(JEV_PAIRS_PER_1000_WORDS * len(text.split()) / 1000))
        asked = pairs[:budget]
        both = asked + [(b, a) for a, b in asked]
        vals = annotate.relatedness(j, both)
        n = len(asked)
        jev = {asked[i]: (vals[i] + vals[n + i]) / 2 for i in range(n)}

    memo = {}

    def k(a, b):
        if a == b:
            return 1.0
        if (b, a) in memo:
            return memo[(b, a)]
        if (a, b) in memo:
            return memo[(a, b)]
        feats = {name: sum(x * y for x, y in zip(vs[pos[a]], vs[pos[b]])) for name, vs in vecs.items()}
        r = jev.get((a, b), jev.get((b, a)))
        if r is None:
            blend = pair["vectors_only"]
        else:
            blend = pair["with_jev"]
            feats["jev"] = r
        v = blend["bias"] + sum(w * feats[f] for f, w in blend["weights"].items())
        memo[(a, b)] = v
        return v

    adj = [k(sents[i], sents[i + 1]) for i in range(len(sents) - 1)]
    out = {
        "semantic_cohesion_mean": statistics.fmean(adj) if adj else 0.0,
        "semantic_cohesion_std": statistics.pstdev(adj) if adj else 0.0,
        "semantic_cohesion_min": min(adj) if adj else 0.0,
        "semantic_cohesion_max": max(adj) if adj else 0.0,
    }
    self_k = [statistics.fmean(k(a, b) for a in P for b in P) for P in paras]
    psims = []
    for i in range(len(paras) - 1):
        cross = statistics.fmean(k(a, b) for a in paras[i] for b in paras[i + 1])
        psims.append(cross / math.sqrt(max(self_k[i], 1e-6) * max(self_k[i + 1], 1e-6)))
    out["paragraph_cohesion_mean"] = statistics.fmean(psims) if psims else 0.0
    out["paragraph_cohesion_std"] = statistics.pstdev(psims) if psims else 0.0
    return out
