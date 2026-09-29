"""Cohesion indices: lexical diversity, adjacent overlap, givenness and connectives.

The index families follow the published cohesion research, above all
Crossley, Kyle & McNamara (2016) and Crossley, Kyle & Dascalu (2019). The
formulas follow the index definitions in that literature. No code from other
tools is used; proseweave's data files and their sources are listed in NOTICE.

The inputs are annotated tokens (see `Tok`). Word classes come from Jev via
annotate.py; everything in this file is arithmetic over them. Grammatical facts
that do not depend on context - personal pronoun forms, the articles, the
demonstratives, the coordinators - are closed sets defined here from English
grammar.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from . import text as tk

# -- closed grammatical sets (English grammar) --------------------------------
PRP_FORMS = frozenset("i me my mine myself you your yours yourself yourselves he him his himself "
                      "she her hers herself it its itself we us our ours ourselves they them their "
                      "theirs themselves".split())
GIVENNESS = frozenset("he him his himself she her herself they them their themselves it its".split())
DEMONSTRATIVES = frozenset("this that these those".split())
ARTICLES = frozenset("a an the".split())
COORDINATORS = frozenset("and or but nor yet so for".split())
# Indefinite pronouns count as nouns, following the Penn Treebank convention (NN).
INDEFINITE_NOUNS = frozenset("something anything nothing everything someone anyone everyone noone "
                             "somebody anybody nobody everybody".split())
# WH-adverbs are WRB in the Penn Treebank, not RB, so they are not counted as adverbs.
WH_ADVERBS = frozenset("when where why how whenever wherever".split())
# The Penn Treebank tags negation as an adverb (RB); Universal Dependencies
# calls it a particle. proseweave follows Penn, so "not" counts as an adverb.
NEGATION = frozenset(("not", "n't", "n’t"))

AUX_LEMMA = {"'ll": "will", "'m": "be", "'re": "be", "'s": "be", "'ve": "have", "'d": "would",
             "am": "be", "are": "be", "been": "be", "being": "be", "is": "be", "was": "be",
             "were": "be", "ca": "can", "wo": "will", "did": "do", "does": "do", "had": "have",
             "has": "have", "gets": "get", "got": "get"}
# Object pronouns take their subject form as lemma. "her" is both an object
# (lemma "she") and a possessive determiner (lemma "her"); make_tokens tells
# them apart by what follows. "hers" is the possessive.
PRON_LEMMA = {"me": "i", "him": "he", "her": "she", "us": "we", "them": "they", "hers": "her"}
# Contracted auxiliaries: always auxiliaries, and forms of their full verb.
CONTRACTION_LEMMA = {"'ve": "have", "'ll": "will", "'m": "be", "'re": "be",
                     "’ve": "have", "’ll": "will", "’m": "be", "’re": "be"}
POSSESSED = frozenset(("NOUN", "PROPN", "ADJ", "NUM"))
# Symbols that stand for a word count as that word: "&" (and), "@" (at), "%" (percent).
SYMBOL_WORDS = {"&": "CONJ", "@": "ADP", "%": "NOUN"}


@dataclass
class Tok:
    raw: str             # lowercased surface form
    lemma: str
    cls: str             # coarse class: NOUN PROPN PRON VERB AUX ADJ ADV DET ADP CONJ PART NUM OTHER
    dem: str | None      # for this/that/these/those: det | pron | rel | comp | adv
    mark: bool           # a subordinating conjunction introducing a clause


# The word class a Penn tag belongs to, by its first two letters.
TAG_CLASS = {"NN": "NOUN", "VB": "VERB", "JJ": "ADJ", "RB": "ADV"}


def lemma_for(word: str, cls: str, tag: str | None = None) -> str:
    """Lemma from the word class; with the Penn tag, the rule lemmatizer can
    also tell base forms (a singular noun, an infinitive) from inflected ones."""
    low = word.lower()
    if low in NEGATION:
        return "not"                  # n't is a form of not
    if low in CONTRACTION_LEMMA:
        return CONTRACTION_LEMMA[low]
    if cls == "AUX":
        return AUX_LEMMA.get(low, low)
    if cls == "PRON":
        return PRON_LEMMA.get(low, low)
    if cls in ("NOUN", "VERB", "ADJ", "ADV"):
        # The Penn tag's morphology (base form, tense, degree) only applies when
        # the tag is of the same class. When Jev's re-check has moved a word to
        # another class ("upheld" tagged JJ, decided VERB), lemmatize by the class.
        if tag and TAG_CLASS.get(tag[:2]) == cls:
            from . import syntax
            return syntax.lemma(word, tag, cls).lower()
        if tag:
            if cls in ("ADJ", "NOUN") and tag in ("VBG", "VBN"):
                return low            # a participle used as an adjective or noun is its own lemma
            got = _known(low, tk.lemmatize(word, cls), cls)
            other = TAG_CLASS.get(tag[:2])
            if got == low and other and low not in tk.lemma_tables()["lemma_index"].get(cls.lower(), ()):
                # not a word of the decided class ("investors"/NNS decided VERB): the
                # tag's own class still tells the inflection; its lemma, if known
                from . import syntax
                got = _known(low, syntax.lemma(word, tag, other).lower(), other)
            return got
        return tk.lemmatize(word, cls)
    return low


def _known(low: str, lemma: str, cls: str) -> str:
    """A class-derived lemma for a word whose tag was of another class, kept only if
    it is a known word of that class or a listed exception form ("upheld" -> uphold);
    otherwise the surface form stands (no "tennis" -> "tenni")."""
    if lemma == low:
        return low
    t = tk.lemma_tables()
    pos = cls.lower()
    if lemma in t["lemma_index"].get(pos, ()) or lemma in t["lemma_exc"].get(pos, {}).get(low, ()):
        return lemma
    return low


def make_tokens(sentence: list[str], tags: list[str], dem_roles: dict[int, str],
                fine: list[str] | None = None) -> list[Tok]:
    """Kept tokens of one sentence. Punctuation is not counted as a word.
    `fine` gives each token's Penn tag, for the lemmas."""
    out = []
    for i, (w, c) in enumerate(zip(sentence, tags)):
        if w in SYMBOL_WORDS:
            c = SYMBOL_WORDS[w]
        elif c == "PUNCT" or not any(ch.isalnum() for ch in w):
            continue
        low = w.lower()
        if low in INDEFINITE_NOUNS:
            c = "NOUN"
        elif low in CONTRACTION_LEMMA:
            c = "AUX"                 # 've 'll 'm 're are always auxiliaries
        mark = c == "CONJ" and low not in COORDINATORS and w not in SYMBOL_WORDS    # "&" coordinates
        lemma = lemma_for(w, c, fine[i] if fine else None)
        if low == "her" and i + 1 < len(tags) and tags[i + 1] in POSSESSED:
            lemma = "her"             # possessive: "her book", "her own"
        out.append(Tok(low, lemma, c, dem_roles.get(i) if low in DEMONSTRATIVES else None, mark))
    return out


# -- adverbs: when is an adverb a content word? ------------------------------
# The rule is a choice. Several were measured on the validation corpus (see
# validation/RESULTS.md) and the simplest did as well as any.
def _wordnet_adj_derived(lemma: str) -> bool:
    adj = tk.lemma_tables()["lemma_index"]["adj"]
    if lemma in adj:
        return True
    if lemma.endswith("ly"):
        s = lemma[:-2]
        for cand in (s, s + "e", s[:-1] + "y" if s.endswith("i") else s, s + "le", s[:-2] if s.endswith("al") else s):
            if cand in adj:
                return True
    return False


ADVERB_RULES = {
    "wordnet": _wordnet_adj_derived,
    "all": lambda l: True,
    "none": lambda l: False,
}
# proseweave's definition: every adverb is a content word, including not, so
# and never. It measured at least as well as a WordNet-derived rule and needs
# no data.
ADVERB_RULE = "all"


def classify(t: Tok):
    """The word-class lists this token belongs to."""
    c = t.cls
    is_noun = c in ("NOUN", "PROPN")
    is_adj = c == "ADJ"
    is_verb = c in ("VERB", "AUX")
    is_adv = (c == "ADV" and t.raw not in WH_ADVERBS) or t.raw in NEGATION
    is_prp = t.raw in PRP_FORMS
    unattended = t.raw in DEMONSTRATIVES and t.dem == "pron"
    content = is_noun or is_adj or c == "VERB" or (is_adv and ADVERB_RULES[ADVERB_RULE](t.lemma))
    return {
        "all": True, "content": content, "function": not content,
        "noun": is_noun, "adj": is_adj, "verb": c == "VERB", "adv": is_adv,
        "prp": is_prp or unattended, "argument": is_prp or is_noun,
        "unattended": unattended, "attended": t.raw in DEMONSTRATIVES and t.dem == "det",
    }


class Lists:
    """Every word-class list at whole-text, sentence and paragraph granularity."""

    KEYS = ("all", "content", "function", "noun", "adj", "verb", "adv", "prp", "argument")

    def __init__(self, paragraphs: list[list[list[Tok]]]):
        self.paragraphs = paragraphs
        self.sents = [s for p in paragraphs for s in p]
        self.flat = {k: [] for k in self.KEYS}
        self.sent = {k: [] for k in self.KEYS}
        self.para = {k: [] for k in self.KEYS}
        self.unattended, self.attended, self.tokens = [], [], []
        for p in paragraphs:
            pl = {k: [] for k in self.KEYS}
            for s in p:
                sl = {k: [] for k in self.KEYS}
                for t in s:
                    self.tokens.append(t)
                    cl = classify(t)
                    for k in self.KEYS:
                        if cl[k]:
                            sl[k].append(t.lemma)
                            pl[k].append(t.lemma)
                            self.flat[k].append(t.lemma)
                    if cl["unattended"]:
                        self.unattended.append(t.raw)
                    if cl["attended"]:
                        self.attended.append(t.raw)
                for k in self.KEYS:
                    self.sent[k].append(sl[k])
            for k in self.KEYS:
                self.para[k].append(pl[k])
        self.nwords = len(self.flat["all"])


def sd(a, b):
    return a / b if b else 0.0


def mattr(xs, w=50):
    if len(xs) < w + 1:
        return sd(len(set(xs)), len(xs))
    return statistics.fmean(len(set(xs[i:i + w])) / w for i in range(len(xs) - w + 1))


def ngrams(xs, n):
    return [" ".join(xs[i:i + n]) for i in range(len(xs) - n + 1)]


def ttr_family(L: Lists) -> dict:
    f = L.flat
    ttr = lambda xs: sd(len(set(xs)), len(xs))
    b, t3 = ngrams(f["all"], 2), ngrams(f["all"], 3)
    return {
        "lemma_ttr": ttr(f["all"]), "lemma_mattr": mattr(f["all"]),
        "lexical_density_tokens": sd(len(f["content"]), len(f["all"])),
        "lexical_density_types": sd(len(set(f["content"])), len(set(f["all"]))),
        "content_ttr": ttr(f["content"]), "function_ttr": ttr(f["function"]),
        "function_mattr": mattr(f["function"]),
        "noun_ttr": ttr(f["noun"]), "verb_ttr": ttr(f["verb"]), "adj_ttr": ttr(f["adj"]),
        "adv_ttr": ttr(f["adv"]), "prp_ttr": ttr(f["prp"]), "argument_ttr": ttr(f["argument"]),
        "bigram_lemma_ttr": ttr(b), "trigram_lemma_ttr": ttr(t3),
    }


def overlap(segs):
    """Six adjacent-overlap values for one list of segments.

    For each segment and the next (window 1), or the next two (window 2): the
    overlapping types over the segment's types, over the number of segment
    pairs, and the share of pairs with any overlap at all.
    """
    n = len(segs)
    if n < 2:
        return (0.0,) * 6
    c1 = c2 = d1 = d2 = b1 = b2 = 0
    sets = [set(s) for s in segs]
    for i in range(n - 1):
        T = sets[i]
        d1 += len(T)
        o1 = {w for w in T if w in sets[i + 1]}
        c1 += len(o1)
        b1 += bool(o1)
        if i <= n - 3:
            d2 += len(T)
            o2 = {w for w in T if w in sets[i + 1] or w in sets[i + 2]}
            c2 += len(o2)
            b2 += bool(o2)
    return (sd(c1, d1), sd(c1, n - 1), sd(b1, n - 1), sd(c2, d2), sd(c2, n - 2), sd(b2, n - 2))


SUFFIX = {"all": "all", "content": "cw", "function": "fw", "noun": "noun", "verb": "verb",
          "adj": "adj", "adv": "adv", "prp": "pronoun", "argument": "argument"}


def overlap_family(L: Lists) -> dict:
    out = {}
    for level, lists in (("sent", L.sent), ("para", L.para)):
        for k, suf in SUFFIX.items():
            v = overlap(lists[k])
            x = f"{suf}_{level}"
            out[f"adjacent_overlap_{x}"] = v[0]
            out[f"adjacent_overlap_{x}_div_seg"] = v[1]
            out[f"adjacent_overlap_binary_{x}"] = v[2]
            out[f"adjacent_overlap_2_{x}"] = v[3]
            out[f"adjacent_overlap_2_{x}_div_seg"] = v[4]
            out[f"adjacent_overlap_binary_2_{x}"] = v[5]
    return out


def repeated(xs):
    from collections import Counter
    c = Counter(xs)
    return sum(v for v in c.values() if v > 1)


def givenness(L: Lists) -> dict:
    giv = [l for l in L.flat["all"] if l in GIVENNESS]
    both = len(giv) + len(L.unattended)
    return {
        "pronoun_density": sd(both, L.nwords),
        "pronoun_noun_ratio": sd(both, len(L.flat["noun"])),
        "repeated_content_lemmas": sd(repeated(L.flat["content"]), L.nwords),
        "repeated_content_and_pronoun_lemmas": sd(repeated(L.flat["content"]) + repeated(giv)
                                                  + repeated(L.unattended), L.nwords),
    }


def closed_connectives(L: Lists) -> dict:
    """Connective indices defined by closed grammatical sets: counted exactly."""
    raw = [t.raw for t in L.tokens]
    n = L.nwords
    cnt = lambda s: sum(1 for w in raw if w in s)
    return {
        "determiners": sd(cnt(ARTICLES | DEMONSTRATIVES), n),
        "all_demonstratives": sd(cnt(DEMONSTRATIVES), n),
        "attended_demonstratives": sd(len(L.attended), n),
        "unattended_demonstratives": sd(len(L.unattended), n),
        "basic_connectives": sd(cnt({"and", "nor", "but", "or", "yet", "so"}), n),
        "conjunctions": sd(cnt({"and", "but"}), n),
        "disjunctions": sd(cnt({"or"}), n),
        "lexical_subordinators": sd(sum(1 for t in L.tokens if t.mark), n),
    }


def segment_similarity(sim, segs, window):
    """Mean similarity of each segment with the next one (window 1) or the next two
    concatenated (window 2)."""
    n = len(segs)
    if n < window + 1:
        return 0.0
    vals = []
    for i in range(n - window):
        right = segs[i + 1] if window == 1 else segs[i + 1] + segs[i + 2]
        v = sim(segs[i], right)
        if v is not None:
            vals.append(v)
    return statistics.fmean(vals) if vals else 0.0
