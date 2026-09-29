"""Every single-text property: basic features, cohesion indices, easability.

Arithmetic stays arithmetic. Word classes and dependency heads come from the
bundled tagger and parser (syntax.py), with Jev deciding the words the tagger is
unsure of. The other judgements text-analysis tools usually get from trained
models - how related two passages are, how familiar a word is - are asked of
Jev (annotate.py). Which route each property uses was decided by validation,
recorded in validation/RESULTS.md.

    proseweave FILE [--json]                        every property of one text
    proseweave profile SAMPLES... --out prof.json   the author's observed ranges
    proseweave compare DRAFT --baseline prof.json   where a draft leaves them

profile/compare use only properties that met the validation bar
(data/validation.json). They locate passages to reread; they are not targets.
Exit status of compare: 0 nothing outside range, 1 something to reread, 2 no
Jev key or usage error.
"""
from __future__ import annotations

import functools
import json
import statistics
import sys
from pathlib import Path

from . import annotate
from . import cohesion
from . import connectives
from . import jev as jevmod
from . import judged
from . import readability
from . import similarity
from . import syntax
from . import tagger_classes
from . import text as tk
from . import zipf


SYNONYM_ROUTE = "wordnet"   # or "jev"; chosen by measurement, see cohesion()


class _WordNetPairs:
    """syn.get((w, t, pos)) -> 1.0 when w is a WordNet synonym of t, like annotate.synonyms."""

    def __init__(self, table):
        self.table = table

    def get(self, key, default=0.0):
        w, t, pos = key
        return 1.0 if tk.synonym_key(t, w) in self.table.get(pos, ()) else default


# --------------------------------------------------------------------------
# small numeric helpers

def pstdev(xs):
    return statistics.pstdev(xs) if len(xs) > 1 else 0.0


def mean(xs):
    return statistics.fmean(xs) if xs else 0.0


def mtld(tokens, threshold=0.72):
    """McCarthy & Jarvis (2010), averaged over a forward and a backward pass.

    Returns 0.0 below 50 tokens, where the measure is not stable.
    """
    if len(tokens) < 50:
        return 0.0

    def one(seq):
        factors, seen, count, ttr = 0.0, set(), 0, 1.0
        for t in seq:
            count += 1
            seen.add(t)
            ttr = len(seen) / count
            if ttr <= threshold:
                factors += 1
                seen, count, ttr = set(), 0, 1.0
        if count:
            factors += (1 - ttr) / (1 - threshold)
        return len(seq) / factors if factors else float(len(seq))

    return (one(tokens) + one(tokens[::-1])) / 2


def _demonstrative_roles_from_tags(sentences, tags):
    """{(sentence, token): role} for this/that/these/those, from the tagger's
    classes, when there is no Jev to ask (see annotate.demonstrative_roles)."""
    out = {}
    for si, (sent, tg) in enumerate(zip(sentences, tags)):
        for ti, w in enumerate(sent):
            if w.lower() not in cohesion.DEMONSTRATIVES:
                continue
            c = tg[ti]
            nxt = tg[ti + 1] if ti + 1 < len(tg) else None
            if c == "DET":
                out[(si, ti)] = "det" if nxt in ("NOUN", "PROPN", "ADJ", "NUM") else "pron"
            elif c == "CONJ":
                out[(si, ti)] = "comp"
            elif c == "ADV":
                out[(si, ti)] = "adv"
            elif c == "PRON" and w.lower() == "that":
                out[(si, ti)] = "rel"
            else:
                out[(si, ti)] = "pron"
    return out


# --------------------------------------------------------------------------
# whole-text Jev questions (wording validated, see validation/)

def _levels(low, low_short, high_short, high):
    return [low, f"Mostly {low_short}, with the occasional exception",
            f"Mostly {high_short}, with the occasional exception", high]


_DIRECT_QUESTIONS = {
    "narrativity": (
        "How story-like is the text - people or agents doing things, events unfolding in time, everyday "
        "words - as opposed to expository or informational writing?",
        _levels("Purely informational or expository; no story at all", "informational writing",
                "storytelling", "A story throughout: characters, events, time moving forward")),
    "word_concreteness": (
        "How concrete is the vocabulary - words for things you can see, touch and picture - as opposed "
        "to abstract ideas?",
        _levels("Almost entirely abstract ideas and concepts", "abstract words", "concrete words",
                "Almost entirely physical things you could see or touch")),
}


# --------------------------------------------------------------------------
# the document

_WARNED = []


def _jev_fallback(method):
    """If Jev becomes unavailable mid-analysis (no credits, key rejected,
    unreachable), warn once on stderr and redo the work on the local routes:
    the tagger alone, local connective senses, vector-only similarity. The
    result is the no-key property set, never a crash."""
    @functools.wraps(method)
    def run(self, *a, **kw):
        # Only the outermost call falls back, so one call never mixes Jev and
        # local values.
        self._depth = getattr(self, "_depth", 0) + 1
        try:
            return method(self, *a, **kw)
        except jevmod.JevUnavailable as e:
            if self.j is None or self._depth > 1:
                raise
            if not _WARNED:
                _WARNED.append(True)
                first = str(e).splitlines()[0]
                sys.stderr.write(f"proseweave: Jev unavailable ({first}); using local routes only\n")
            self.j = None
            self._tags = self._lists = self._source_lists = None
            return method(self, *a, **kw)
        finally:
            self._depth -= 1
    return run


class Analysis:
    """One text, annotated once, with every property computed from it.

    `j` is a jev.Jev; pass None to get only the properties that need no
    judgement (the rest are left out, never guessed). Without Jev, word classes
    come from the tagger alone.
    """

    def __init__(self, text: str, j=None):
        self.text = text
        self.j = j
        # The cohesion indices treat every newline as a paragraph break; the
        # basic features use blank lines. Sentences are the same either way, so
        # parse once on newlines and take blank-line paragraphs from the raw
        # text where needed.
        self.doc = tk.parse(text, single_newline_paragraphs=True)
        self.blank_paragraphs = tk.paragraphs(text)
        self.stop = tk.stop_words()
        self._tags = None

    # -- annotations ------------------------------------------------------
    # Tokens whose tagger margin (best score less the runner-up, in the model's
    # stored units) is below this are asked of Jev.
    TAG_MARGIN = 200

    @property
    def tags(self):
        """Word class per token, per sentence, cached: the bundled tagger, with
        Jev deciding the open-class words it is unsure of."""
        if self._tags is None:
            st = self.doc.sentence_tokens       # the parse: Penn tags, margins, coarse classes
            self._tags = tagger_classes.pos_tags(self.j, self.doc.sentences, margin=self.TAG_MARGIN,
                                                 fine=[[(t.tag, t.margin) for t in s] for s in st],
                                                 upos=[[t.pos for t in s] for s in st])
        return self._tags

    def content_tokens(self):
        """Alphabetic, non-stop tokens with their class: what the basic features count."""
        out = []
        tags = self.tags
        for si, s in enumerate(self.doc.sentences):
            for ti, w in enumerate(s):
                if w.isalpha() and w.lower() not in self.stop:
                    out.append((w, tags[si][ti] if tags else None))
        return out

    # -- properties computed locally ---------------------------------------
    @property
    def parsed(self):
        """Tokens and sentences from the bundled parser (syntax.py), cached."""
        if getattr(self, "_parsed", None) is None:
            self._parsed = list(syntax.analyse(self.text))     # the parse text.parse shares
        return self._parsed

    def parsed_sentences(self):
        sents = []
        for t in self.parsed:
            if t.sent_start or not sents:
                sents.append([])
            sents[-1].append(t)
        return sents

    def basic_local(self) -> dict:
        # computed once per text: basic() and easability() both use it
        if getattr(self, "_basic_local", None) is None:
            self._basic_local = self._basic_local_uncached()
        return dict(self._basic_local)

    def _basic_local_uncached(self) -> dict:
        """Counts over the parser's tokens and sentences: tokens are alphabetic
        and not stop words; sentence length counts alphabetic tokens, and
        sentences with none are left out of the length statistics. Readability
        uses the conventional counts (readability.py)."""
        sents = self.parsed_sentences()
        toks = [t.text.lower() for t in self.parsed if t.text.isalpha() and t.text.lower() not in self.stop]
        sl = [sum(1 for t in s if t.text.isalpha()) for s in sents]
        sl = [x for x in sl if x]
        m = mean(sl)
        return {
            "n_tokens": len(toks),
            "n_types": len(set(toks)),
            "n_sentences": len(sents),
            "n_paragraphs": len(self.blank_paragraphs),
            "type_token_ratio": len(set(toks)) / max(len(toks), 1),
            "mtld_score": mtld(toks),
            "sent_len_mean": m,
            "sent_len_std": pstdev(sl),
            "sent_len_cv": pstdev(sl) / (m + 1e-8) if sl else 0.0,
            **readability.scores(self.text),
            "text_length": len(self.text),
            "word_count": len(self.text.split()),
            **self.dependency(),
        }

    def dependency(self) -> dict:
        """Dependency distance from the bundled parser (syntax.py): mean and
        spread of |head - dependent| over alphabetic non-stop words, positions
        counted over every token, punctuation and line breaks included."""
        if getattr(self, "_dep", None) is None:
            d = syntax.dep_distances(self.parsed, self.stop)
            self._dep = {"dep_distance_mean": mean(d), "dep_distance_std": pstdev(d)}
        return self._dep

    def content_tokens_nojev(self):
        return [(w, None) for s in self.doc.sentences for w in s
                if w.isalpha() and w.lower() not in self.stop]

    def word_classes(self) -> dict:
        """Share of content tokens in each open word class."""
        ct = self.content_tokens()
        n = max(len(ct), 1)
        return {f"{k}_ratio": sum(1 for _, t in ct if t == up) / n
                for k, up in (("noun", "NOUN"), ("verb", "VERB"), ("adj", "ADJ"), ("adv", "ADV"))}

    # -- properties that need Jev judgements --------------------------------
    def word_frequency(self) -> dict:
        """zipf_mean / zipf_std over the first 500 content tokens, from the
        bundled frequency table (zipf.py); with Jev, rare and unseen words also
        get Jev's familiarity judgement."""
        return zipf.zipf_features([w for w, _ in self.content_tokens_nojev()], self.j)

    @_jev_fallback
    def properties(self) -> dict:
        """Every single-text property."""
        d = self.basic()
        d.update(self.cohesion())
        d.update(self.easability(d))
        return d

    def semantic_cohesion(self) -> dict:
        """Adjacent sentences and adjacent paragraphs, from sentence-pair
        similarities (similarity.py: fitted word vectors, blended with Jev's
        STS-scale rating of each pair when there is a key)."""
        return similarity.sentence_cohesion(self.text, self.j)

    @_jev_fallback
    def basic(self) -> dict:
        d = self.basic_local()
        d.update(self.word_classes())
        d.update(self.word_frequency())
        d.update(self.semantic_cohesion())
        return d

    # -- easability components, on a 0-100 scale ----------------------------
    @_jev_fallback
    def easability(self, local: dict | None = None) -> dict:
        """The easability components described by Graesser, McNamara &
        Kulikowich (2011), on the scale of the LLM judge used for validation
        (judged.py): narrativity, word_concreteness, syntactic_simplicity,
        referential_cohesion, deep_cohesion and overall_quality, each a fitted
        combination of whole-text Jev Score answers and local indices.

        referential_cohesion_construct and deep_cohesion_construct follow the
        published definitions directly (adjacent-sentence overlap; causal and
        logical connectives) and need no Jev.

        `local` is the rest of this text's properties, if already computed.
        Without Jev, syntactic_simplicity is Flesch reading ease clipped to
        0-100 and only the construct properties are added.
        """
        if local is None:
            local = {**self.basic(), **self.cohesion()}
        out = {"syntactic_simplicity": max(0.0, min(100.0, self.basic_local()["flesch_reading_ease"]))}
        m = judged.model()
        cz = m["construct"]["z"]
        for name, keys in m["construct"]["indices"].items():
            if all(local.get(k) is not None for k in keys):
                out[name] = 50 + 10 * mean([(local[k] - cz[k][0]) / (cz[k][1] or 1.0) for k in keys])
        if self.j is None:
            return out
        qs = {k: {"type": "score", "instructions": q, "criteria": lv} for k, (q, lv) in _DIRECT_QUESTIONS.items()}
        # One whole-text request for the two direct scores, then judged.py's
        # question bank on the whole text and on each ~300-word chunk.
        whole, answers, *chunks = self.j.ask_many([(self.text, qs)] + judged.jobs(self.text))
        x = dict(local)
        for k in _DIRECT_QUESTIONS:
            v = jevmod.score_value(whole.get(k), 4)
            x[k] = None if v is None else v / 3 * 100
        out.update(judged.compose(answers, x, self.text, chunks))
        return out

    # -- cohesion indices ---------------------------------------------------
    def _build_lists(self, paragraphs, tags, fine=None):
        """cohesion.Lists from paragraphs of sentences, their classes and
        (optionally) their Penn tags, which the lemmas then use."""
        sents = [s for p in paragraphs for s in p]
        if self.j is not None:
            dem = annotate.demonstrative_roles(self.j, sents)
        else:
            dem = _demonstrative_roles_from_tags(sents, tags)
        paras, si = [], 0
        for p in paragraphs:
            ps = []
            for s in p:
                roles = {ti: r for (s_i, ti), r in dem.items() if s_i == si}
                ps.append(cohesion.make_tokens(s, tags[si], roles, fine[si] if fine else None))
                si += 1
            paras.append(ps)
        lists = cohesion.Lists(paras)
        # Words like "before" or "as" introduce a clause in some uses only:
        # Jev decides each occurrence (connectives.clause_marks).
        if self.j is not None:
            for si, ti in connectives.clause_marks(self.j, lists.sents):
                lists.sents[si][ti].mark = True
        return lists

    @_jev_fallback
    def cohesion_lists(self):
        """The word-class lists for this text, built once."""
        if getattr(self, "_lists", None) is None:
            self._lists = self._build_lists(self.doc.paragraphs, self.tags,
                                            [[t.tag for t in s] for s in self.doc.sentence_tokens])
        return self._lists

    @_jev_fallback
    def source_lists(self):
        """The lists compared with a source text's (source.py): the main pipeline's
        tokens, sentences, Penn tags and lemmas, with word classes from
        tagger_classes' rules over the Penn tags (and Jev's re-check) rather than
        the coarse model. The keyness table (tools/build_mag_news_freq.py) is
        counted from these same lists."""
        if getattr(self, "_source_lists", None) is None:
            st = self.doc.sentence_tokens
            fine = [[(t.tag, t.margin) for t in s] for s in st]
            tags = tagger_classes.pos_tags(self.j, self.doc.sentences, margin=self.TAG_MARGIN, fine=fine, upos=None)
            self._source_lists = self._build_lists(self.doc.paragraphs, tags, [[t.tag for t in s] for s in st])
        return self._source_lists

    @_jev_fallback
    def cohesion(self) -> dict:
        """The 168 single-text cohesion indices (cohesion.py). Without Jev they
        use the tagger's word classes alone."""
        sents = self.doc.sentences
        L = self.cohesion_lists()
        out = {}
        out.update(cohesion.ttr_family(L))
        out.update(cohesion.overlap_family(L))
        out.update(cohesion.givenness(L))
        out.update(cohesion.closed_connectives(L))
        raw = [t.raw for t in L.tokens]
        out["coordinating_conjuncts"] = cohesion.sd(
            sum(1 for w in raw if w in {"yet", "so", "nor", "however", "therefore"}), L.nwords)

        # Connectives with open-ended membership: counted from proseweave's own
        # inventory (data/connectives_en.json). Jev settles only the words whose
        # connective sense depends on context ("so", "since", "as", "while", ...),
        # one Choice per occurrence; without Jev the word's class decides. Asking
        # Jev to count connectives per sentence measured 0.06-0.71 on these
        # indices and missed the bar.
        senses = connectives.senses_jev(self.j, L.sents) if self.j is not None else connectives.senses_local(L.sents)
        out.update(connectives.indices(L.sents, L.nwords, senses))

        # Synonym overlap: for each type in a segment, the tokens of the next
        # segment that are the same word or a synonym of it, per segment pair.
        # Synonymy comes from WordNet (data/synonyms_en.bin.gz): the Jev route,
        # asking whether each word pair can mean the same thing, measured
        # 0.67-0.79 and missed the bar (validation/RESULTS.md).
        levels = {"sent": L.sent, "para": L.para}
        if SYNONYM_ROUTE == "jev":
            pairs = set()
            for lv, lists in levels.items():
                for k, pos in (("noun", "noun"), ("verb", "verb")):
                    segs = lists[k]
                    for i in range(len(segs) - 1):
                        for w in set(segs[i]):
                            for t in segs[i + 1]:
                                pairs.add((w, t, pos))
            syn = annotate.synonyms(self.j, pairs)
        else:
            wn = tk.synonyms()
            syn = _WordNetPairs(wn)
        for lv, lists in levels.items():
            for k, pos in (("noun", "noun"), ("verb", "verb")):
                segs = lists[k]
                n = len(segs)
                if n < 2:
                    out[f"syn_overlap_{lv}_{k}"] = 0.0
                    continue
                c = 0.0
                for i in range(n - 1):
                    for w in set(segs[i]):
                        for t in segs[i + 1]:
                            c += 1.0 if w == t else syn.get((w, t, pos), 0.0)
                out[f"syn_overlap_{lv}_{k}"] = c / (n - 1)
        # Segment similarity (LSA, LDA, word2vec in the research literature):
        # adjacent sentences and paragraphs compared in openly licensed
        # semantic spaces (similarity.py).
        out.update(similarity.segment_indices(L))
        return out


# --------------------------------------------------------------------------
# profile / compare: the author's observed range, and where a draft leaves it

VALIDATION = Path(__file__).resolve().parent / "data" / "validation.json"
SKIP_FAMILIES = {"count"}   # raw sizes measure how much was written, not how


def trusted() -> dict:
    """Properties that met the validation bar (validation/RESULTS.md)."""
    v = json.loads(VALIDATION.read_text(encoding="utf-8"))
    return {p: x for p, x in v.items() if x["valid"] and x["family"] not in SKIP_FAMILIES}


def profile(texts, j) -> dict:
    keep = trusted()
    rows = [Analysis(t, j).properties() for t in texts]
    rng = {}
    for p in keep:
        vals = [r[p] for r in rows if isinstance(r.get(p), (int, float))]
        if vals:
            rng[p] = [round(min(vals), 4), round(statistics.median(vals), 4), round(max(vals), 4)]
    return {"samples": len(texts), "range": rng}


def compare(text, prof, j) -> list:
    """Trusted properties where the draft sits outside the samples' observed range.

    The range is widened by 15% of its span, and the span is never taken as less
    than a quarter of the median: a few samples that happen to agree are not a
    hard wall.
    Sorted by how far outside, in spans.
    """
    keep = trusted()
    res = Analysis(text, j).properties()
    out = []
    for p, (lo, med, hi) in prof["range"].items():
        v = res.get(p)
        if p not in keep or not isinstance(v, (int, float)):
            continue
        span = max(hi - lo, 0.25 * abs(med), 1e-9)
        if lo - 0.15 * span <= v <= hi + 0.15 * span:
            continue
        side = "below" if v < lo else "above"
        dist = (lo - v if v < lo else v - hi) / span
        out.append({"property": p, "family": keep[p]["family"], "question": keep[p]["question"],
                    "value": round(v, 4), "range": [lo, hi], "side": side, "spans": round(dist, 2)})
    return sorted(out, key=lambda x: -x["spans"])
