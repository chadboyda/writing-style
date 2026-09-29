"""Source comparison: how much of a text reuses a source's key terms.

This is the rewrite-versus-original case. For a source and a target:

  source_similarity_{lsa,lda,word2vec}  whole-text similarity of target and source
  mag_news_*_keywords_percentage        the share of the target made of the
                                        source's KEYWORDS - terms the source uses
                                        far more than ordinary magazine and news
                                        writing does - for unigrams (all, nouns,
                                        verbs, verbs+nouns, adjectives), n-grams
                                        (2-4) and word-class-masked n-grams

Keyness needs a baseline frequency for each word or phrase. By default it comes
from proseweave's bundled news-and-magazine frequency tables (magnews.py): counts
from an open-licensed corpus of news and magazine-style writing, built with the
same tokenizer, lemmas and word classes as the lists below. Anything below the
tables' floor counts as maximally key. BASELINE = "jev" uses Jev's judgement of
how common each word or phrase is in magazine and news writing instead (no data
file), and "hybrid" blends Jev's judgement into the table values.
proseweave's definition of a keyword: only items the source repeats are
candidates; they are ranked by how much more often the source uses them than
the baseline; the top 10% of the source's types are keywords; n-grams in which
every word is masked are never keywords.

    proseweave source SOURCE TARGET
"""
from __future__ import annotations

import math
from collections import Counter

from . import annotate
from . import cohesion
from . import jev as jevmod
from . import magnews
from . import similarity

# Where keyness gets its baseline: "hybrid" (the bundled frequency tables, with
# Jev's familiarity judgement blended into the single-word values), "table"
# (the tables alone, no Jev calls) or "jev" (Jev alone, no data file).
# On the 60-pair validation set "hybrid" scored best on the selection half and
# on the held-out half (validation/RESULTS.md).
BASELINE = "hybrid"
# hybrid, single words only: ln pm = w * ln pm_table + (1 - w) * (a + b * L),
# where L is Jev's expected familiarity level and (a, b) is a line fitted to
# the tables' own values. Blending n-grams too scored lower.
HYBRID_TABLE_WEIGHT = 0.7
HYBRID_JEV_LINE = (-3.98, 2.57)

# Familiarity level -> occurrences per million words, for the Jev baseline.
# Unigrams span roughly the Zipf scale; multi-word sequences are rarer at every
# level. Level 0 means "does not occur in ordinary writing", which counts as
# infinitely key. (A continuous log-linear mapping of Jev's expected level was
# tried and scored worse on the pair corpus: 3/26 against 4/26.)
UNI_PER_MILLION = [None, 0.3, 2.0, 15.0, 120.0, 2000.0]
NGRAM_PER_MILLION = [None, 0.05, 0.5, 3.0, 20.0, 200.0]
INFINITE = 1_000_000.0

# The mask symbol for word-class-masked n-grams. Kept tokens always contain a
# letter or digit, so no word can be "_" and a masked slot never collides with
# a word (the lemma "x" included).
MASK = "_"
# Curly and straight apostrophes and quotes are the same character to keyness.
QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"'})

MASKS = {  # masked list name -> classes kept (everything else becomes MASK)
    "n": {"noun"}, "adj": {"adj"}, "v": {"verb_all"}, "v_n": {"noun", "verb_all"}, "a_n": {"noun", "adj"},
}


def _unit_lists(L: "cohesion.Lists"):
    """Whole-text unigram lists and per-sentence lemma/class sequences."""
    uni = {"all": [], "noun": [], "adj": [], "verb_all": [], "verb_noun": []}
    per_sent = []
    for p in L.paragraphs:
        for s in p:
            seq = []
            for t in s:
                cl = cohesion.classify(t)
                verb_all = t.cls in ("VERB", "AUX")
                lemma = t.lemma.translate(QUOTES)
                uni["all"].append(lemma)
                if cl["noun"]:
                    uni["noun"].append(lemma)
                if cl["adj"]:
                    uni["adj"].append(lemma)
                if verb_all:
                    uni["verb_all"].append(lemma)
                if cl["noun"] or verb_all:
                    uni["verb_noun"].append(lemma)
                seq.append((lemma, {"noun": cl["noun"], "adj": cl["adj"], "verb_all": verb_all}))
            per_sent.append(seq)
    return uni, per_sent


def _ngram_lists(per_sent, n):
    """Plain and masked n-grams, kept within sentences."""
    out = {"plain": []}
    out.update({m: [] for m in MASKS})
    masks = list(MASKS.items())
    for seq in per_sent:
        if len(seq) < n:
            continue
        # each token's surface under every mask, worked out once
        shown = {"plain": [l for l, _ in seq]}
        for m, keep in masks:
            shown[m] = [l if any(c[k] for k in keep) else MASK for l, c in seq]
        for m, toks in shown.items():
            dest = out[m]
            for i in range(len(seq) - n + 1):
                dest.append(" ".join(toks[i:i + n]))
    return out


def _lists_for(L):
    """_unit_lists and the 2-4-gram lists of one text, built once per Lists."""
    c = getattr(L, "_source_lists", None)
    if c is None:
        uni, per_sent = _unit_lists(L)
        c = (uni, per_sent, {n: _ngram_lists(per_sent, n) for n in (2, 3, 4)})
        L._source_lists = c
    return c


def _keywords(items: list[str], per_million, top_perc=0.1):
    """per_million(item) -> the baseline's occurrences per million, or None (never seen)."""
    if not items:
        return set()
    freq = Counter(items)
    n = len(items)
    cands = []
    for item, c in freq.items():            # insertion order = first occurrence
        if c < 2 or set(item.split()) == {MASK}:
            continue
        tf = c / n
        rf_pm = per_million(item)
        pd = INFINITE if not rf_pm else (tf - rf_pm / 1e6) * 100 / (rf_pm / 1e6)
        cands.append((item, pd, tf))
    cands.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return {c[0] for c in cands[: int(len(set(items)) * top_perc)]}


def _proportion(target: list[str], keywords: set) -> float:
    return cohesion.sd(sum(1 for x in target if x in keywords), len(target))


def _visible(g: str) -> str:
    """A masked n-gram's visible words: what Jev is asked about."""
    return " ".join(w for w in g.split() if w != MASK)


def _baseline(j, su, src_ng):
    """(unigram, n-gram) functions returning the baseline's per-million estimate."""
    table_uni = lambda w: magnews.per_million("uni", w)                      # noqa: E731
    table_ng = lambda m, n, g: magnews.per_million((m, n), g)                # noqa: E731
    if BASELINE == "table" or j is None:
        return table_uni, table_ng

    # Jev's judgement for every candidate the source repeats, asked once.
    need_uni = set()
    for k in su:
        need_uni |= {w for w, c in Counter(su[k]).items() if c >= 2}
    uni_lvl = annotate.phrase_familiarity(j, sorted(need_uni))
    if BASELINE == "hybrid":
        a, b = HYBRID_JEV_LINE
        w = HYBRID_TABLE_WEIGHT

        def hybrid_uni(word):
            t, level = table_uni(word), uni_lvl.get(word)
            if not t or level is None:
                return t                      # below the floor stays maximally key
            return math.exp(w * math.log(t) + (1 - w) * (a + b * level))
        return hybrid_uni, table_ng

    need_ng = set()
    for n in src_ng:
        for m, lst in src_ng[n].items():
            for g, c in Counter(lst).items():
                if c >= 2 and set(g.split()) != {MASK}:
                    need_ng.add(g if m == "plain" else _visible(g))
    ng_lvl = annotate.phrase_familiarity(j, sorted(need_ng))

    def level_pm(level, table):
        return None if level is None else table[max(0, min(5, round(level)))]

    return (lambda w: level_pm(uni_lvl.get(w), UNI_PER_MILLION),
            lambda m, n, g: level_pm(ng_lvl.get(g if m == "plain" else _visible(g)), NGRAM_PER_MILLION))


def compare(j, source_an, target_an) -> dict:
    """source_an, target_an: analysis.Analysis objects sharing the same Jev client."""
    Ls, Lt = source_an.source_lists(), target_an.source_lists()
    su, ss, src_ng = _lists_for(Ls)
    tu, ts, tgt_ng = _lists_for(Lt)
    try:
        uni_pm, ng_pm = _baseline(j, su, src_ng)
    except jevmod.JevUnavailable:      # no credits or no service: the tables alone
        uni_pm, ng_pm = _baseline(None, su, src_ng)

    out = {}
    names = {"all": "uni", "noun": "n_uni", "verb_all": "v_uni", "verb_noun": "v_n_uni", "adj": "adj_uni"}
    for k, nm in names.items():
        kw = _keywords(su[k], uni_pm)
        out[f"mag_news_{nm}_keywords_percentage"] = _proportion(tu[k], kw)
    word = {2: "bi", 3: "tri", 4: "quad"}
    for n, w in word.items():
        tgt = tgt_ng[n]
        for m, lst in src_ng[n].items():
            kw = _keywords(lst, lambda g, m=m, n=n: ng_pm(m, n, g))
            key = f"mag_news_{w}_keywords_percentage" if m == "plain" else f"mag_news_{m}_{w}_keywords_percentage"
            out[key] = _proportion(tgt[m], kw)

    out.update(similarity.source_indices(Lt.flat["all"], Ls.flat["all"]))
    return out
