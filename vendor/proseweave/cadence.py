"""Cadence measurements: the rhythm of a text in reading order, for building diagnostics.

Cadence is how the rhythm of the writing helps a reader follow the thought
and feel its emphasis: sentence length, but also where the pauses fall, how
sentences begin and how quickly ideas arrive. This module measures those
things locally, in context, since two texts can share a length distribution
and read nothing alike. The output is numbers only (plus character offsets,
so a caller can quote): no text, no interpretation, no score, and no ideal
sentence length, paragraph ratio, alternation or reading grade.

    from proseweave import cadence
    m = cadence.measure(text)          # columns, local patterns, rhythm
    a = cadence.align(before, after)   # aligned passages of two versions

`measure` gives every sentence and paragraph in reading order as columns
(equal-length lists per field; see measure()), local patterns as spans with
their numbers (flat stretches, runs of long or short sentences, repeated
structure against repeated terminology, unconnected runs, sentences dense
with relations, emphasis points, paragraph rhythm; thresholds are the
document's own percentiles), and rhythm at three levels in syllables: the
beat of stressed and unstressed syllables, the phrase, and where paragraphs
land (see rhythm()). Every statistic that depends on order carries the same
statistic over shuffled versions of the text and a z against them, so a
caller can tell a pattern in the order from what any order would give.

Content types are small codes (TYPE_CODES): 0 prose, 1 heading, 2 list_item,
3 quotation, 4 code, 5 table. Non-prose blocks stay in the timeline with their
code; only prose sentences enter the statistics, patterns and rhythm.

Local only: the bundled parse, tagger classes, lemmas, syllable and stress
tables (data/syllables_en.bin.gz, data/stress_en.bin.gz, from CMUdict) and
connective inventory. Nothing here asks Jev or uses the network.
"""
from __future__ import annotations

import difflib
import random
import re
import statistics
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from . import cohesion
from . import connectives
from . import readability
from . import syntax
from . import text as tk
from .packed import read_tables

DATA = Path(__file__).resolve().parent / "data"

PROSE, HEADING, LIST_ITEM, QUOTATION, CODE, TABLE = "prose", "heading", "list_item", "quotation", "code", "table"
CONTENT_TYPES = (PROSE, HEADING, LIST_ITEM, QUOTATION, CODE, TABLE)
# type_code in the output: 0 prose, 1 heading, 2 list_item, 3 quotation, 4 code, 5 table
TYPE_CODES = {t: i for i, t in enumerate(CONTENT_TYPES)}

WINDOW = 5                 # rolling window, in sentences
FLAT_RUN = 5               # flat stretches: consecutive sentences
LENGTH_RUN = 4             # runs of long or short sentences
REPEAT_RUN = 3             # repeated structure or terminology, unconnected runs
SKELETON_SIMILAR = 0.2     # normalised edit distance at or below which two skeletons count as alike
SKELETON_MIN = 6           # skeletons shorter than this are too generic to compare
MIN_PROSE = 8              # fewer prose sentences: only emphasis points are located
DENSE_MARKERS = 3

PAUSES = {",", ";", ":", "—", "–", "--", "(", ")", "…", "..."}
REFERRING = {"this": "demonstrative", "that": "demonstrative", "these": "demonstrative",
             "those": "demonstrative", "such": "demonstrative", "it": "pronoun", "they": "pronoun",
             "he": "pronoun", "she": "pronoun", "we": "pronoun", "its": "pronoun", "their": "pronoun",
             "his": "pronoun", "her": "pronoun", "them": "pronoun", "there": "pronoun"}
CONTENT_CLASSES = {"NOUN", "PROPN", "VERB", "ADJ"}
# Connective groups read as relation markers: the logical, temporal and
# discourse relations. Plain "and", emphasis words and the causal or
# intentional vocabulary ("cause", "goal") are left out; they do not mark how
# one clause relates to another.
RELATION_GROUPS = ("additive", "similarity", "alternative", "apposition", "contrast", "concession",
                   "exception", "cause", "result", "condition", "purpose", "temporal", "sequence",
                   "summary", "transition", "subordinator")
SKIP_ITEMS = {("or",)}
CLITICS = {"n't", "'s", "'re", "'ve", "'ll", "'d", "'m"}
# Skeleton symbols: a nominal chunk, a verb group, an adverb, a preposition.
SKELETON_CLASS = {"NOUN": "N", "PROPN": "N", "PRON": "N", "NUM": "N", "DET": "N", "ADJ": "N",
                  "VERB": "V", "AUX": "V", "PART": "V", "ADV": "A", "ADP": "P", "OTHER": "N"}
SKELETON_PUNCT = {",": ",", ";": ";", ":": ":", "—": "—", "–": "—", "--": "—", "(": "(", ")": ")"}


# --------------------------------------------------------------------------
# blocks: content types from the raw lines

_FENCE = re.compile(r"^\s{0,3}(```|~~~)")
_ATX = re.compile(r"^\s{0,3}#{1,6}(\s|$)")
_SETEXT = re.compile(r"^\s{0,3}(=+|-+)\s*$")
_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_ITEM = re.compile(r"^\s*(?:[-*+•‣◦]|\d{1,3}[.)])\s+\S")
_QUOTE = re.compile(r"^\s{0,3}>")
_INDENT = re.compile(r"^( {4}|\t)\S")
_QUOTED = re.compile(r"“[^”]*”|\"[^\"]*\"|«[^»]*»")
_TERMINAL = set(".!?:;,…")


def _is_table(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") or s.count("|") >= 2


def blocks(text: str) -> list[dict]:
    """[{type, start, end}] in reading order: blank-line paragraphs, with
    Markdown and plain-text cues deciding the content type. A text with no
    blank lines at all takes every line as a paragraph."""
    lines, pos = [], 0
    for ln in text.splitlines(keepends=True):
        lines.append((pos, pos + len(ln.rstrip("\r\n")), ln.rstrip("\r\n")))
        pos += len(ln)
    per_line = not re.search(r"\n[ \t]*\n", text) and len([l for l in lines if l[2].strip()]) > 1
    out, cur = [], None

    def close():
        nonlocal cur
        if cur is not None:
            out.append(cur)
        cur = None

    i = 0
    while i < len(lines):
        s, e, ln = lines[i]
        if not ln.strip():
            close()
            i += 1
            continue
        if _FENCE.match(ln):
            close()
            fence = _FENCE.match(ln).group(1)
            j = i + 1
            while j < len(lines) and not lines[j][2].lstrip().startswith(fence):
                j += 1
            end = lines[min(j, len(lines) - 1)][1]
            out.append({"type": CODE, "start": s, "end": end})
            i = j + 1
            continue
        if _ATX.match(ln):
            close()
            out.append({"type": HEADING, "start": s, "end": e})
            i += 1
            continue
        if _SETEXT.match(ln) and cur is not None and cur["type"] == PROSE and cur.get("lines") == 1:
            cur["type"] = HEADING
            close()
            i += 1
            continue
        if _RULE.match(ln):
            close()
            i += 1
            continue
        if _ITEM.match(ln):
            close()
            cur = {"type": LIST_ITEM, "start": s, "end": e, "lines": 1}
            i += 1
            continue
        if _QUOTE.match(ln):
            if cur is None or cur["type"] != QUOTATION:
                close()
                cur = {"type": QUOTATION, "start": s, "end": e, "lines": 0}
            cur["end"], cur["lines"] = e, cur["lines"] + 1
            i += 1
            continue
        if _is_table(ln):
            if cur is None or cur["type"] != TABLE:
                close()
                cur = {"type": TABLE, "start": s, "end": e, "lines": 0}
            cur["end"], cur["lines"] = e, cur["lines"] + 1
            i += 1
            continue
        if _INDENT.match(ln) and cur is None:
            j = i
            while j + 1 < len(lines) and (_INDENT.match(lines[j + 1][2]) or not lines[j + 1][2].strip()):
                j += 1
            while not lines[j][2].strip():
                j -= 1
            out.append({"type": CODE, "start": s, "end": lines[j][1]})
            i = j + 1
            continue
        if cur is not None and cur["type"] in (PROSE, LIST_ITEM) and not per_line:
            cur["end"], cur["lines"] = e, cur["lines"] + 1        # a wrapped line or a list item's continuation
        else:
            close()
            cur = {"type": PROSE, "start": s, "end": e, "lines": 1}
        i += 1
    close()
    for k, b in enumerate(out):
        b.pop("lines", None)
        if b["type"] != PROSE:
            continue
        body = text[b["start"]:b["end"]].strip()
        if _looks_like_title(body) and k + 1 < len(out):
            b["type"] = HEADING
        elif body[:1] in "\"“«" and sum(len(m) for m in _QUOTED.findall(body)) >= 0.6 * len(body):
            b["type"] = QUOTATION           # a paragraph that is mostly one quotation
    return out


def _looks_like_title(body: str) -> bool:
    if "\n" in body:
        return False
    words = body.split()
    if not words or len(words) > 10:
        return False
    last = body.rstrip("\"'”’)]»")[-1:] if body.rstrip("\"'”’)]»") else ""
    if last in _TERMINAL or body[-1] in _TERMINAL:
        return False
    return body[0].isupper() or body[0].isdigit()


# --------------------------------------------------------------------------
# the parse, regrouped into blocks and sentences

_RELATIONS = None


def _relations():
    global _RELATIONS
    if _RELATIONS is None:
        by_first = {}
        for g in RELATION_GROUPS:
            for first, items in connectives.build([g]).items():
                for words, kind, senses in items:
                    if words in SKIP_ITEMS:
                        continue
                    by_first.setdefault(first, []).append((words, kind, senses, g))
        for v in by_first.values():
            v.sort(key=lambda x: -len(x[0]))
        _RELATIONS = by_first
    return _RELATIONS


def _sense_ok(cls: str, words: tuple, senses) -> bool:
    """The local reading of a sense-dependent connective: the word's class,
    then the inventory's default (connectives.fallback_sense)."""
    item = " ".join(words)
    if item not in connectives.inventory()["senses"]:
        return True
    return connectives.fallback_sense(SimpleNamespace(cls=cls), item) in senses


def _markers(words: list[str], classes: list[str], tags: list[str]) -> list[dict]:
    """Connectives, subordinators and relatives, left to right, longest first."""
    rel = _relations()
    out, i = [], 0
    while i < len(words):
        w = words[i]
        hit = None
        for ws, kind, senses, g in rel.get(w, ()):
            L = len(ws)
            if tuple(words[i:i + L]) != ws:
                continue
            if kind == "sub" and classes[i] != "CONJ":
                continue
            if kind == "sense" and not _sense_ok(classes[i], ws, senses):
                continue
            hit = (L, g)
            break
        if hit:
            out.append({"marker": " ".join(words[i:i + hit[0]]), "kind": hit[1], "at": i})
            i += hit[0]
            continue
        if classes[i] == "CONJ" and w not in cohesion.COORDINATORS and w.isalpha():
            out.append({"marker": w, "kind": "subordinator", "at": i})
        elif tags[i] in ("WDT", "WP", "WP$") and i > 0:
            out.append({"marker": w, "kind": "relative", "at": i})
        i += 1
    return out


def _skeleton(words, classes, tags, markers) -> str:
    at = {m["at"]: m["kind"] for m in markers}
    seq = []
    for i, (w, c) in enumerate(zip(words, classes)):
        if i in at:
            k = at[i]
            sym = "REL" if k == "relative" else "SUB" if k in ("subordinator", "cause", "condition", "concession",
                                                              "temporal", "purpose", "exception") else "LINK"
        elif c == "CONJ":
            sym = "CC" if w in cohesion.COORDINATORS else "SUB"
        elif c == "PUNCT":
            sym = SKELETON_PUNCT.get(w)
            if sym is None:
                continue
        else:
            sym = SKELETON_CLASS.get(c, "N")
        if not seq or seq[-1] != sym:
            seq.append(sym)
    return " ".join(seq)


def _edit(a: list, b: list) -> float:
    """Levenshtein distance between two symbol lists, over the longer length."""
    if not a and not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1] / max(len(a), len(b))


def _is_word(t: str) -> bool:
    return any(ch.isalnum() for ch in t) and t.lower() not in CLITICS


def _parse(text: str, analysis=None):
    """Blocks, sentences and paragraphs from proseweave's own parse."""
    from .analysis import Analysis
    an = analysis if analysis is not None else Analysis(text, None)
    norm = tk.normalize_apostrophes(text)
    offsets, pos = {}, 0
    for t in syntax.analyse(norm):
        offsets[id(t)] = pos
        pos += len(t.text) + len(t.ws)
    flat = []
    for sent, cls in zip(an.doc.sentence_tokens, an.tags):
        for t, c in zip(sent, cls):
            if id(t) in offsets:
                flat.append((t, c, offsets[id(t)]))
    blks = blocks(norm)
    stop = tk.stop_words()

    # assign each token to its block; a sentence never crosses a block
    groups, bi = [], 0
    cur_key = None
    for t, c, s in flat:
        while bi < len(blks) and s >= blks[bi]["end"]:
            bi += 1
        if bi >= len(blks) or s < blks[bi]["start"]:
            continue
        whole = blks[bi]["type"] in (CODE, TABLE, HEADING)
        if cur_key is None or cur_key != bi or (t.sent_start and not whole):
            groups.append((bi, []))
            cur_key = bi
        groups[-1][1].append((t, c, s))
    # a "sentence" with no word in it stays with the one before
    merged = []
    for b, toks in groups:
        if merged and merged[-1][0] == b and not any(_is_word(t.text) for t, _, _ in toks):
            merged[-1][1].extend(toks)
        else:
            merged.append((b, toks))

    used = sorted({b for b, _ in merged})
    para_of = {b: k for k, b in enumerate(used)}
    sentences, prev_lem = [], None
    for b, toks in merged:
        words = [t.text.lower() for t, _, _ in toks]
        classes = [c for _, c, _ in toks]
        tags = [t.tag for t, _, _ in toks]
        wc = sum(1 for w in words if _is_word(w))
        if not wc:
            continue
        start, end = toks[0][2], toks[-1][2] + len(toks[-1][0].text)
        lem = {(t.lemma or t.text).lower() for t, c, _ in toks
               if c in CONTENT_CLASSES and t.text.isalpha() and t.text.lower() not in stop}
        # pauses: position is the share of the sentence's words before the mark
        pauses, seen = [], 0
        for k, w in enumerate(words):
            if _is_word(w):
                seen += 1
            elif w in PAUSES and not (w in ("…", "...") and k == len(words) - 1):
                pauses.append({"mark": w, "at": round(seen / wc, 2)})
        wi = [k for k, w in enumerate(words) if _is_word(w)]
        opening = [{"lemma": (toks[k][0].lemma or words[k]).lower(), "cls": classes[k]} for k in wi[:2]]
        mk = _markers(words, classes, tags)
        # nouns among the first three words, with their character spans
        terms = {}
        for k in wi[:3]:
            if classes[k] in TERM_CLASSES and words[k] not in stop and words[k].isalpha():
                terms.setdefault((toks[k][0].lemma or words[k]).lower(),
                                 (toks[k][2], toks[k][2] + len(toks[k][0].text)))
        first3 = set(terms)
        overlap = len(lem & prev_lem) if prev_lem is not None else None
        ref = REFERRING.get(words[wi[0]]) if wi else None
        btype = blks[b]["type"]
        sentences.append({
            "index": len(sentences), "paragraph": para_of[b], "type": btype,
            "start": start, "end": end, "words": wc,
            "pauses": {"count": len(pauses), "marks": pauses},
            "opening": opening, "opening_signature": " ".join(f"{o['lemma']}/{o['cls']}" for o in opening),
            "skeleton": _skeleton(words, classes, tags, mk),
            "relations": [{"marker": m["marker"], "kind": m["kind"]} for m in mk],
            "link": {"overlap": overlap, "overlap_ratio": (round(overlap / len(lem), 3) if lem and overlap is not None
                                                           else (0.0 if overlap is not None else None)),
                     "opens_with": ref},
            "_lemmas": lem, "_open_lemmas": first3, "_open_terms": terms,
            "_toks": [(w, c, t.ws) for w, c, (t, _, _) in zip(words, classes, toks)],
        })
        prev_lem = lem
    for k, s in enumerate(sentences):
        nxt = sentences[k + 1]["paragraph"] if k + 1 < len(sentences) else None
        prv = sentences[k - 1]["paragraph"] if k else None
        s["is_paragraph_final"] = nxt != s["paragraph"]
        s["is_standalone"] = s["is_paragraph_final"] and prv != s["paragraph"]
    paragraphs = []
    for b in used:
        ss = [s for s in sentences if s["paragraph"] == para_of[b]]
        if not ss:
            continue
        paragraphs.append({"index": para_of[b], "type": blks[b]["type"], "start": blks[b]["start"],
                           "end": blks[b]["end"], "words": sum(s["words"] for s in ss),
                           "sentences": len(ss), "lengths": [s["words"] for s in ss],
                           "first_sentence": ss[0]["index"], "_fp": set().union(*(s["_lemmas"] for s in ss))})
    return an, blks, sentences, paragraphs


# --------------------------------------------------------------------------
# numbers

def _pct(xs, q):
    """Linear-interpolated percentile, q in 0-100."""
    if not xs:
        return 0.0
    v = sorted(xs)
    k = (len(v) - 1) * q / 100
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _cv(xs):
    if len(xs) < 2:
        return 0.0
    m = statistics.fmean(xs)
    return statistics.pstdev(xs) / m if m else 0.0


def rolling(lengths: list[int], window: int = WINDOW) -> list[dict]:
    """Mean, SD and CV of sentence length over a centred window of `window`
    sentences (shifted inward at the edges)."""
    n = len(lengths)
    w = max(1, min(window, n))
    out = []
    for i in range(n):
        a = max(0, min(i - w // 2, n - w))
        seg = lengths[a:a + w]
        m = statistics.fmean(seg)
        sd = statistics.pstdev(seg) if len(seg) > 1 else 0.0
        out.append({"mean": round(m, 2), "sd": round(sd, 2), "cv": round(sd / m, 3) if m else 0.0})
    return out


# --------------------------------------------------------------------------
# local patterns: runs located against the document's own distribution

FUNCTION_CLASSES = {"DET", "PRON", "AUX", "ADP", "CONJ", "PART", "NUM", "PUNCT", "OTHER"}
TERM_CLASSES = {"NOUN", "PROPN"}
BY_OPENING, BY_SKELETON = 0, 1        # repeated_structure.by


def _runs(ok: list[bool], min_len: int) -> list[tuple[int, int]]:
    """(start, end) inclusive of maximal runs of True at least min_len long."""
    out, a = [], None
    for i, v in enumerate(ok + [False]):
        if v and a is None:
            a = i
        elif not v and a is not None:
            if i - a >= min_len:
                out.append((a, i - 1))
            a = None
    return out


def _pair_runs(ok_pair: list[bool], min_sents: int) -> list[tuple[int, int]]:
    """ok_pair[i] says item i links to item i+1; runs of linked items."""
    out, a = [], None
    for i, v in enumerate(ok_pair + [False]):
        if v and a is None:
            a = i
        elif not v and a is not None:
            if i - a + 1 >= min_sents:
                out.append((a, i))
            a = None
    return out


def _same_opening(o1, o2):
    """(same, by_term): whether two openings match, and whether the match rests
    on a noun (repeated terminology) rather than on the frame of the sentence.
    A function word alone ("The", "It") is not an opening; it takes the next
    word too. A content word ("Imagine", "Sometimes") is one on its own."""
    if not o1 or not o2 or o1[0] != o2[0]:
        return False, False
    if o1[0]["cls"] in FUNCTION_CLASSES:
        if len(o1) < 2 or len(o2) < 2 or o1[1] != o2[1]:
            return False, False
        return True, o1[1]["cls"] in TERM_CLASSES
    return True, o1[0]["cls"] in TERM_CLASSES


def _opening_sim(o1, o2) -> float:
    """1.0 when the first two words match (lemma and class), 0.5 when only the
    first does, 0.0 otherwise."""
    if not o1 or not o2 or o1[0] != o2[0]:
        return 0.0
    return 1.0 if len(o1) > 1 and len(o2) > 1 and o1[1] == o2[1] else 0.5


def _cols(rows: list[dict], keys) -> dict:
    return {k: [r[k] for r in rows] for k in keys}


def _patterns(sents, paras, window):
    """Local patterns over the prose sentences, as index spans and numbers.
    Runs never cross a heading, list, quotation, code or table."""
    prose = [k for k, s in enumerate(sents) if s["type"] == PROSE]
    L = [sents[k]["words"] for k in prose]
    segs, cur = [], []
    for j, k in enumerate(prose):
        if cur and k != prose[cur[-1]] + 1:
            segs.append(cur)
            cur = []
        cur.append(j)
    if cur:
        segs.append(cur)
    # local CV: every full window of `window` sentences inside a segment
    w = max(2, window)
    wins = [(seg[i], seg[i + w - 1], _cv([L[j] for j in seg[i:i + w]]))
            for seg in segs for i in range(len(seg) - w + 1)]
    th = {}
    if L:
        wcv = [c for _, _, c in wins] or [r["cv"] for r in rolling(L, window)]
        ov = [sents[k]["link"]["overlap_ratio"] for k in prose if sents[k]["link"]["overlap_ratio"] is not None]
        th = {"p10": _pct(L, 10), "p25": _pct(L, 25), "median": _pct(L, 50), "p75": _pct(L, 75),
              "p90": _pct(L, 90), "local_cv_p20": _pct(wcv, 20), "local_cv_median": _pct(wcv, 50),
              "overlap_ratio_p25": _pct(ov, 25)}
    computed = len(prose) >= MIN_PROSE
    rows = {k: [] for k in ("flat_stretches", "long_runs", "short_runs", "repeated_structure", "repeated_terminology",
                            "disconnected_runs", "dense_relations", "emphasis_points", "short_paragraphs",
                            "even_paragraph_runs")}

    def run(js, **kw):
        return {"start": prose[js[0]], "end": prose[js[-1]], **kw}

    if computed:
        p20, mcv = th["local_cv_p20"], th["local_cv_median"]
        # a sentence is in a flat stretch when a window holding it varies less
        # than 80% of this document's windows, and by less than half the
        # document's typical window
        in_flat = [False] * len(prose)
        for a, b, c in wins:
            if c <= min(p20, 0.5 * mcv) + 1e-9:
                for j in range(a, b + 1):
                    in_flat[j] = True
        low_ov = th["overlap_ratio_p25"]
        for seg in segs:
            for a, b in _runs([in_flat[j] for j in seg], FLAT_RUN):
                js = seg[a:b + 1]
                own = _cv([L[j] for j in js])
                if own <= 0.5 * mcv + 1e-9:
                    rows["flat_stretches"].append(run(js, run_cv=round(own, 3)))
            for key, test in (("long_runs", lambda x: x >= th["p75"] - 1e-9),
                              ("short_runs", lambda x: x <= th["p25"] + 1e-9)):
                for a, b in _runs([test(L[j]) for j in seg], LENGTH_RUN):
                    rows[key].append(run(seg[a:b + 1]))
            # short sentences with no relation marker, each after the first
            # sharing little with the sentence before and not opening on a reference
            ok = []
            for n_, j in enumerate(seg):
                s = sents[prose[j]]
                short = L[j] <= th["p25"] + 1e-9 and not s["relations"]
                linked = n_ > 0 and ok and ok[-1] and (
                    (s["link"]["overlap_ratio"] or 0.0) > low_ov + 1e-9 or s["link"]["opens_with"])
                ok.append(short and not linked)
            for a, b in _runs(ok, REPEAT_RUN):
                rows["disconnected_runs"].append(run(seg[a:b + 1]))
            # repeated structure (same opening frame, or near-identical skeleton)
            # vs repeated terminology (same noun at the opening, structure varying)
            struct, term, why = [], [], []
            for a, b in zip(seg, seg[1:]):
                s1, s2 = sents[prose[a]], sents[prose[b]]
                k1, k2 = s1["skeleton"].split(), s2["skeleton"].split()
                alike = (len(k1) >= SKELETON_MIN and len(k2) >= SKELETON_MIN
                         and 1 - s2["_skeleton_sim"] <= SKELETON_SIMILAR + 1e-9)
                same_open, noun_open = _same_opening(s1["opening"], s2["opening"])
                shared = s1["_open_lemmas"] & s2["_open_lemmas"]
                struct.append(alike or (same_open and not noun_open))
                term.append(bool(shared) and not alike)
                why.append((same_open, shared, s2["_skeleton_sim"]))
            for a, b in _pair_runs(struct, REPEAT_RUN):
                sims = [why[i][2] for i in range(a, b)]
                rows["repeated_structure"].append(run(
                    seg[a:b + 1], by=BY_OPENING if all(why[i][0] for i in range(a, b)) else BY_SKELETON,
                    skeleton_sim=round(statistics.fmean(sims), 3)))
            for a, b in _pair_runs(term, REPEAT_RUN):
                # the shared noun where it first appears, so a caller can quote it.
                # Taken from the run's first pair: a noun shared only by a later
                # pair need not occur in the run's first sentence at all.
                first = sorted(why[a][1])[0]
                ts, te = sents[prose[seg[a]]]["_open_terms"][first]
                sims = [why[i][2] for i in range(a, b)]
                rows["repeated_terminology"].append(run(seg[a:b + 1], term_start=ts, term_end=te,
                                                        skeleton_sim=round(statistics.fmean(sims), 3)))
        for j, k in enumerate(prose):
            n_rel = len(sents[k]["relations"])
            if L[j] >= th["p90"] - 1e-9 and n_rel >= DENSE_MARKERS:
                rows["dense_relations"].append({"sentence": k, "relations": n_rel})
    # emphasis points: a sentence at most half the median length of its three
    # neighbours either side, or a one-sentence paragraph at or below the
    # document's median length (where most paragraphs are one sentence, a long
    # one is the norm, not a point of emphasis)
    med_all = th.get("median", 0)
    for j, k in enumerate(prose):
        s = sents[k]
        nb = [L[i] for i in range(max(0, j - 3), min(len(prose), j + 4)) if i != j]
        med = statistics.median(nb) if len(nb) >= 2 else None
        shorter = med is not None and L[j] <= 0.5 * med
        if shorter or (s["is_standalone"] and L[j] <= med_all):
            rows["emphasis_points"].append({"sentence": k, "neighbour_median": med,
                                            "shorter_than_neighbours": shorter})
    # paragraph rhythm
    pp = [p for p in paras if p["type"] == PROSE]
    pw = [p["words"] for p in pp]
    if pw:
        th["paragraph_words_median"] = _pct(pw, 50)
        th["paragraph_words_cv"] = _cv(pw)
    if len(pp) >= 3 and computed:
        pmed = th["paragraph_words_median"]
        for i in range(1, len(pp) - 1):
            p, a, b = pp[i], pp[i - 1], pp[i + 1]
            if p["sentences"] == 1 or p["index"] != a["index"] + 1 or b["index"] != p["index"] + 1:
                continue            # one-sentence paragraphs are emphasis points
            if p["words"] <= 0.5 * min(a["words"], b["words"]) and min(a["words"], b["words"]) >= pmed:
                rows["short_paragraphs"].append({"paragraph": p["index"]})
        pcv = th["paragraph_words_cv"]
        if len(pp) >= 6 and pcv > 0:
            win = [_cv(pw[i:i + 4]) <= 0.35 * pcv and all(pp[i + d + 1]["index"] == pp[i + d]["index"] + 1
                                                         for d in range(3)) for i in range(len(pp) - 3)]
            i = 0
            while i < len(win):
                if not win[i]:
                    i += 1
                    continue
                j = i
                while j + 1 < len(win) and win[j + 1]:
                    j += 1
                grp = pp[i:j + 4]
                rows["even_paragraph_runs"].append({"start": grp[0]["index"], "end": grp[-1]["index"],
                                                    "run_cv": round(_cv([g["words"] for g in grp]), 3)})
                i = j + 4
    fields = {"flat_stretches": ("start", "end", "run_cv"), "long_runs": ("start", "end"),
              "short_runs": ("start", "end"), "repeated_structure": ("start", "end", "by", "skeleton_sim"),
              "repeated_terminology": ("start", "end", "term_start", "term_end", "skeleton_sim"),
              "disconnected_runs": ("start", "end"), "dense_relations": ("sentence", "relations"),
              "emphasis_points": ("sentence", "neighbour_median", "shorter_than_neighbours"),
              "short_paragraphs": ("paragraph",), "even_paragraph_runs": ("start", "end", "run_cv")}
    in_flat_n = sum(r["end"] - r["start"] + 1 for r in rows["flat_stretches"])
    pat = {k: _cols(v, fields[k]) for k, v in rows.items()}
    pat["counts"] = {k: len(v) for k, v in rows.items()}
    pat["flat_stretch_share"] = round(in_flat_n / len(prose), 3) if prose else 0.0
    pat["computed"] = computed
    pat["thresholds"] = {k: round(v, 3) for k, v in th.items()}
    return pat, prose


# --------------------------------------------------------------------------
# rhythm: beat, phrase, landing and contour, in syllables

NULL_SHUFFLES = 20          # shuffles behind each null
NULL_SEED = 1729            # fixed, so every null (and its z) repeats exactly
STRESSED_CLASSES = {"NOUN", "PROPN", "VERB", "ADJ", "ADV", "NUM", "OTHER"}   # a monosyllable of these is stressed
NT_NO_SYLLABLE = {"do", "ca", "wo", "sha", "ai"}      # don't, can't, won't, shan't, ain't: n't adds no syllable
PHRASE_BREAKS = {",", ";", ":", "—", "–", "--", "(", ")"}
ENDING_BINS = 3             # final_stress_offset: 0, 1, 2 or more


@lru_cache(maxsize=1)
def _stress_table():
    """word -> primary-stress mask (bit i = syllable i), for words of two or more
    syllables not stressed on the first (data/stress_en.bin.gz, from CMUdict)."""
    return read_tables(DATA / "stress_en.bin.gz")["stress"]


def word_stress(word: str, cls: str, prev: str | None = None) -> list[int]:
    """1 (stressed) or 0 per syllable of one token, lowercased.

    Syllables come from readability.syllables (CMUdict, then hyphenation). A word
    of two or more syllables takes its stress from its first CMUdict
    pronunciation, or on its first syllable when the dictionary lacks it. A
    monosyllable is stressed when its word class is a content class and
    unstressed when it is a function word. A number is one stressed syllable;
    n't is one unstressed syllable (none in don't, can't, won't); other clitics
    ('s, 'll, ...) and punctuation have none."""
    if word in CLITICS:
        return [0] if word == "n't" and prev not in NT_NO_SYLLABLE else []
    if not any(ch.isalpha() for ch in word):
        return [1] if any(ch.isdigit() for ch in word) else []
    n = max(1, readability.syllables(word))
    if n == 1:
        return [1 if cls in STRESSED_CLASSES else 0]
    m = _stress_table().get(word, 1)
    return [(m >> i) & 1 for i in range(n)]


def _words_stress(s) -> list[list[int]]:
    out, prev = [], None
    for w, c, _ in s["_toks"]:
        st = word_stress(w, c, prev)
        if st:
            out.append(st)
        prev = w
    return out


def _phrases(s) -> list[int]:
    """Syllables per phrase: the sentence split at , ; : dashes and parentheses
    (a hyphen counts only with a space after it)."""
    out, cur, prev = [], 0, None
    for w, c, ws in s["_toks"]:
        if w in PHRASE_BREAKS or (w == "-" and ws):
            if cur:
                out.append(cur)
            cur = 0
        else:
            cur += len(word_stress(w, c, prev))
        prev = w
    if cur:
        out.append(cur)
    return out


def _intervals(seq) -> list[int]:
    idx = [i for i, x in enumerate(seq) if x]
    return [b - a for a, b in zip(idx, idx[1:])]


def _beat(sentences_words) -> tuple:
    """(clash, alternation, lapse, ending_stressed) over sentences given as
    lists of per-word stress lists, read as one stream in order."""
    seq, ends = [], []
    for ws in sentences_words:
        flat = [x for w in ws for x in w]
        seq.extend(flat)
        if flat:
            ends.append(flat[-1])
    iv = _intervals(seq)
    n = len(iv) or 1
    return (sum(1 for x in iv if x == 1) / n, sum(1 for x in iv if x in (2, 3)) / n,
            sum(1 for x in iv if x >= 4) / n, statistics.fmean(ends) if ends else 0.0)


def _npvi(xs):
    pairs = [(a, b) for a, b in zip(xs, xs[1:]) if a + b]
    return 100 * statistics.fmean(abs(a - b) / ((a + b) / 2) for a, b in pairs) if pairs else 0.0


def _end_weight(phrase_lists):
    r = [p[-1] / statistics.fmean(p) for p in phrase_lists if len(p) >= 2]
    return statistics.median(r) if r else None


def _landing(paras_syl):
    """Median over paragraphs of (final, initial) sentence syllables over the
    paragraph's median sentence."""
    fin = [p[-1] / statistics.median(p) for p in paras_syl if statistics.median(p)]
    ini = [p[0] / statistics.median(p) for p in paras_syl if statistics.median(p)]
    return (statistics.median(fin) if fin else None, statistics.median(ini) if ini else None)


def _lag1(xs):
    if len(xs) < 3:
        return 0.0
    m = statistics.fmean(xs)
    d = [x - m for x in xs]
    e = sum(v * v for v in d)
    return sum(a * b for a, b in zip(d, d[1:])) / e if e else 0.0


def _vs_null(value, null):
    """{"value", "null_mean", "z"}: z is the value's distance from the shuffled
    versions, in their SDs (0 when they do not vary)."""
    if value is None:
        return {"value": None, "null_mean": None, "z": None}
    null = [v for v in null if v is not None]
    mu = statistics.fmean(null) if null else value
    sd = statistics.pstdev(null) if len(null) > 1 else 0.0
    return {"value": round(value, 3), "null_mean": round(mu, 3), "z": round((value - mu) / sd, 2) if sd else 0.0}


def _moving(xs, window, fn):
    """fn over a centred window of `window` values, shifted inward at the edges."""
    n = len(xs)
    w = max(1, min(window, n))
    out = []
    for i in range(n):
        a = max(0, min(i - w // 2, n - w))
        out.append(fn(xs[a:a + w]))
    return out


def rhythm(sents, paras, prose, window: int = WINDOW) -> dict:
    """Rhythm over the prose sentences, at three levels plus the contour.

    Every statistic that depends on order is reported as {"value", "null_mean",
    "z"}: the same text shuffled NULL_SHUFFLES times (fixed seed) at the level
    the statistic reads, and how far the real order sits from those shuffles in
    their standard deviations. A z near 0 says the order carries nothing the
    shuffles do not; none of these is a quality score, and none has an ideal.

    beat      the stress stream (1 per stressed syllable). Intervals between
              successive stresses: clash_rate is the share of 1 (stress on
              stress), alternation_share the share of 2 or 3 (the alternating
              pulse), lapse_rate the share of 4 or more (three or more
              unstressed syllables in a row); the three shares sum to 1.
              ending_stressed is the share of
              sentences whose last syllable is stressed. Null: words shuffled
              within each sentence, each keeping its own stress.
    phrase    phrases are split at , ; : dashes and parentheses.
              phrase_contrast is the normalised pairwise variability index
              (nPVI) of successive phrase lengths in syllables (0 when
              neighbours are equal; higher as neighbours differ); null: phrase
              order shuffled across the text. end_weight is the median, over
              sentences of two or more phrases, of the last phrase over the
              sentence's mean phrase (above 1 when sentences end on a longer
              phrase); null: phrases shuffled within each sentence.
              endings gives the share of sentences ending 0, 1 and 2 or more
              syllables after their last stress (not order-based).
    landing   per paragraph of three or more prose sentences, the final and
              the initial sentence's syllables over the paragraph's median
              (paragraphs.final_ratio, initial_ratio); here, the medians over
              paragraphs. Null: sentences shuffled within each paragraph.
    contour   smooth (moving mean of sentence syllables over `window`) and
              local_variation (moving CV), by sentence; alternation, the lag-1
              autocorrelation of sentence syllables (negative when long and
              short sentences alternate, positive when neighbours are alike).
              Null: sentence order shuffled.
    """
    rng = random.Random(NULL_SEED)
    P = [sents[k] for k in prose]
    words_st = [_words_stress(s) for s in P]
    syl = [sum(len(w) for w in ws) for ws in words_st]
    phrases = [_phrases(s) for s in P]

    real = _beat(words_st)
    null_beat = []
    for _ in range(NULL_SHUFFLES):
        shuffled = []
        for ws in words_st:
            ws = list(ws)
            rng.shuffle(ws)
            shuffled.append(ws)
        null_beat.append(_beat(shuffled))
    names = ("clash_rate", "alternation_share", "lapse_rate", "ending_stressed")
    beat = {"syllables": sum(syl), "stresses": sum(sum(map(sum, ws)) for ws in words_st),
            **{n: _vs_null(real[i], [b[i] for b in null_beat]) for i, n in enumerate(names)}}

    stream = [x for p in phrases for x in p]
    null_c, null_e = [], []
    for _ in range(NULL_SHUFFLES):
        sh = list(stream)
        rng.shuffle(sh)
        null_c.append(_npvi(sh))
        within = []
        for p in phrases:
            p = list(p)
            rng.shuffle(p)
            within.append(p)
        null_e.append(_end_weight(within))
    offsets = [s["_final_offset"] for s in P]
    phrase = {"phrases": len(stream),
              "phrase_contrast": _vs_null(_npvi(stream) if len(stream) > 1 else None, null_c),
              "end_weight": _vs_null(_end_weight(phrases), null_e),
              "endings": [round(offsets.count(b) / len(offsets), 3) if offsets else 0.0 for b in range(ENDING_BINS)]}

    by_para = {}
    for s, n in zip(P, syl):
        by_para.setdefault(s["paragraph"], []).append(n)
    groups = [v for v in by_para.values() if len(v) >= 3]
    real_l = _landing(groups)
    null_l = []
    for _ in range(NULL_SHUFFLES):
        sh = []
        for g in groups:
            g = list(g)
            rng.shuffle(g)
            sh.append(g)
        null_l.append(_landing(sh))
    landing = {"paragraphs": len(groups),
               "final_ratio": _vs_null(real_l[0], [x[0] for x in null_l]),
               "initial_ratio": _vs_null(real_l[1], [x[1] for x in null_l])}

    null_a = []
    for _ in range(NULL_SHUFFLES):
        sh = list(syl)
        rng.shuffle(sh)
        null_a.append(_lag1(sh))
    smooth = _moving(syl, window, statistics.fmean) if syl else []
    sd = _moving(syl, window, lambda x: statistics.pstdev(x) if len(x) > 1 else 0.0) if syl else []
    contour = {"window": window, "sentence": prose, "smooth": [round(x, 2) for x in smooth],
               "local_variation": [round(d / m, 3) if m else 0.0 for d, m in zip(sd, smooth)],
               "alternation": _vs_null(_lag1(syl) if len(syl) >= 3 else None, null_a)}
    return {"beat": beat, "phrase": phrase, "landing": landing, "contour": contour,
            "_syl": syl, "_phrases": phrases, "_by_para": by_para}


# --------------------------------------------------------------------------
# measure

SENTENCE_FIELDS = ("index", "paragraph", "type_code", "start", "end", "words", "syllables", "stresses",
                   "final_stress_offset", "phrase_start", "phrases", "pause_count", "pause_positions",
                   "relations", "overlap_ratio", "opening_sim_prev", "skeleton_sim_prev", "opens_with_reference",
                   "is_paragraph_final", "is_standalone")
PARAGRAPH_FIELDS = ("index", "type_code", "start", "end", "words", "sentences", "first_sentence",
                    "final_ratio", "initial_ratio")


def measure(text: str, window: int = WINDOW, analysis=None) -> dict:
    """Cadence measurements of one text, all numbers.

    {"summary", "sentences", "paragraphs", "phrases", "patterns", "rhythm"}.
    `sentences` and `paragraphs` are columns: equal-length lists keyed by field.
    Sentence fields:

      index, paragraph        position in reading order, and its paragraph
      type_code               content type (TYPE_CODES)
      start, end              character offsets into `text`, to quote it
      words, syllables        length in words and in syllables
      stresses                stressed syllables (see word_stress)
      final_stress_offset     syllables after the last stress: 0 (ends on a
                              stress), 1, or 2 for two or more
      phrase_start, phrases   where its phrase lengths begin in
                              phrases.syllables, and how many there are
      pause_count             internal pause marks: , ; : — – ( ) …
      pause_positions         where each falls, as the share of the sentence's
                              words before it (0 = the start, 1 = the end)
      relations               connectives, subordinators and relatives carried
      overlap_ratio           share of its content lemmas also in the previous
                              sentence (null for the first)
      opening_sim_prev        1 when its first two words match the previous
                              sentence's (lemma and class), 0.5 when only the
                              first does, 0 otherwise
      skeleton_sim_prev       1 minus the normalised edit distance between its
                              clause skeleton and the previous sentence's (a
                              coarse word-class sequence keeping subordinators,
                              coordinators, relatives and internal punctuation)
      opens_with_reference    opens on a pronoun or demonstrative
      is_paragraph_final, is_standalone   ends its paragraph; is one alone

    Paragraph fields: index, type_code, start, end, words, sentences,
    first_sentence, and final_ratio / initial_ratio (see rhythm(); null for a
    paragraph of fewer than three prose sentences).

    The *_prev fields compare with the previous sentence in reading order,
    whatever its type. `phrases.syllables` holds every sentence's phrase
    lengths, flat. `patterns` gives local patterns over the prose as sentence
    (or paragraph) spans with their numbers, located against the document's
    own percentiles (`patterns.thresholds`); they count words. `rhythm` is
    beat, phrase, landing and contour, in syllables (see rhythm()).
    `analysis` may be an existing Analysis of the same text, to share its parse.
    """
    an, blks, sents, paras = _parse(text, analysis)
    prev = None
    for s in sents:
        s["_skeleton_sim"] = 1 - _edit(s["skeleton"].split(), prev["skeleton"].split()) if prev else None
        s["_opening_sim"] = _opening_sim(s["opening"], prev["opening"]) if prev else None
        seq = [x for w in _words_stress(s) for x in w]
        last = max((i for i, x in enumerate(seq) if x), default=None)
        s["_syllables"], s["_stresses"] = len(seq), sum(seq)
        s["_final_offset"] = min(ENDING_BINS - 1, len(seq) - 1 - last if last is not None else len(seq))
        s["_phrase_list"] = _phrases(s)
        prev = s
    pat, prose = _patterns(sents, paras, window)
    rh = rhythm(sents, paras, prose, window)
    ratios = {}
    for p, v in rh.pop("_by_para").items():
        if len(v) >= 3 and statistics.median(v):
            ratios[p] = (round(v[-1] / statistics.median(v), 3), round(v[0] / statistics.median(v), 3))
    rh.pop("_syl"), rh.pop("_phrases")
    flat, rows = [], []
    for s in sents:
        rows.append({"index": s["index"], "paragraph": s["paragraph"], "type_code": TYPE_CODES[s["type"]],
                     "start": s["start"], "end": s["end"], "words": s["words"], "syllables": s["_syllables"],
                     "stresses": s["_stresses"], "final_stress_offset": s["_final_offset"],
                     "phrase_start": len(flat), "phrases": len(s["_phrase_list"]),
                     "pause_count": s["pauses"]["count"], "pause_positions": [p["at"] for p in s["pauses"]["marks"]],
                     "relations": len(s["relations"]), "overlap_ratio": s["link"]["overlap_ratio"],
                     "opening_sim_prev": s["_opening_sim"],
                     "skeleton_sim_prev": None if s["_skeleton_sim"] is None else round(s["_skeleton_sim"], 3),
                     "opens_with_reference": bool(s["link"]["opens_with"]),
                     "is_paragraph_final": s["is_paragraph_final"], "is_standalone": s["is_standalone"]})
        flat.extend(s["_phrase_list"])
    prow = [{"index": p["index"], "type_code": TYPE_CODES[p["type"]], "start": p["start"], "end": p["end"],
             "words": p["words"], "sentences": p["sentences"], "first_sentence": p["first_sentence"],
             "final_ratio": ratios.get(p["index"], (None, None))[0],
             "initial_ratio": ratios.get(p["index"], (None, None))[1]} for p in paras]
    th = pat["thresholds"]
    return {
        "summary": {"sentences": len(sents), "prose_sentences": len(prose), "paragraphs": len(paras),
                    "type_counts": [sum(1 for p in paras if p["type"] == t) for t in CONTENT_TYPES],
                    "words": sum(s["words"] for s in sents),
                    "prose_words": sum(sents[k]["words"] for k in prose),
                    "prose_syllables": rh["beat"]["syllables"],
                    "prose_length_percentiles": {k: th[k] for k in ("p10", "p25", "median", "p75", "p90") if k in th},
                    "local_cv": {"p20": th.get("local_cv_p20", 0.0), "median": th.get("local_cv_median", 0.0)},
                    "one_line_paragraphs": bool(not re.search(r"\n[ \t]*\n", text) and text.count("\n") > 1)},
        "sentences": _cols(rows, SENTENCE_FIELDS),
        "paragraphs": _cols(prow, PARAGRAPH_FIELDS),
        "phrases": {"syllables": flat},
        "patterns": pat,
        "rhythm": rh,
    }


# --------------------------------------------------------------------------
# before / after alignment

ALIGN_MIN = 0.3       # content-word Jaccard at or above which two passages align
CONVERT_MIN = 0.45    # stricter, for passages that changed content type
LIST = "list"         # alignment unit: a run of list items
STATUS_CODES = {"unchanged": 0, "edited": 1, "split": 2, "merged": 3, "converted": 4, "inserted": 5, "deleted": 6}


def _units(text, m):
    """Alignment units: each paragraph, with a run of list items as one list."""
    stop = tk.stop_words()
    P, S = m["paragraphs"], m["sentences"]
    units = []
    for i in range(len(P["index"])):
        t = CONTENT_TYPES[P["type_code"][i]]
        if t == LIST_ITEM and units and units[-1]["type"] == LIST and units[-1]["paragraphs"][-1] == i - 1:
            u = units[-1]
        else:
            u = {"type": LIST if t == LIST_ITEM else t, "paragraphs": [], "items": 0}
            units.append(u)
        u["paragraphs"].append(i)
        u["items"] += t == LIST_ITEM
    for u in units:
        first = P["first_sentence"][u["paragraphs"][0]]
        last = P["first_sentence"][u["paragraphs"][-1]] + P["sentences"][u["paragraphs"][-1]] - 1
        u["sentences"] = (first, last)
        body = text[S["start"][first]:S["end"][last]]
        u["fp"] = frozenset(tk.lemmatize(w, "NOUN") for w in re.findall(r"[A-Za-z]+", body.lower())
                            if w not in stop and len(w) > 2)
        u["key"] = " ".join(sorted(u["fp"])) + "|" + u["type"]
        u["chars"] = (S["start"][first], S["end"][last])
    return units


def _sim(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def _compatible(ta, tb):
    return ta == tb or {ta, tb} in ({PROSE, LIST}, {PROSE, QUOTATION})


def _align_region(A, B):
    """Monotone alignment of units A and B allowing 1-1, 1-2 and 2-1 matches,
    and units left unmatched on either side."""
    n, m = len(A), len(B)
    NEG = float("-inf")
    best = [[NEG] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0

    def score(xs, ys):
        ta, tb = {u["type"] for u in xs}, {u["type"] for u in ys}
        if len(ta) != 1 or len(tb) != 1 or not _compatible(next(iter(ta)), next(iter(tb))):
            return None
        s = _sim(frozenset().union(*(u["fp"] for u in xs)), frozenset().union(*(u["fp"] for u in ys)))
        return s if s >= (ALIGN_MIN if xs[0]["type"] == ys[0]["type"] else CONVERT_MIN) else None

    for i in range(n + 1):
        for j in range(m + 1):
            v = best[i][j]
            if v == NEG:
                continue
            for di, dj in ((1, 0), (0, 1), (1, 1), (1, 2), (2, 1)):
                a, b = i + di, j + dj
                if a > n or b > m:
                    continue
                gain = 0.0
                if di and dj:
                    s = score(A[i:a], B[j:b])
                    if s is None:
                        continue
                    gain = 1.0 + s - 0.05 * (di + dj - 2)
                if v + gain > best[a][b]:
                    best[a][b] = v + gain
                    back[a][b] = (i, j)
    out, i, j = [], n, m
    while (i, j) != (0, 0):
        pi, pj = back[i][j]
        out.append((list(range(pi, i)), list(range(pj, j))))
        i, j = pi, pj
    return out[::-1]


def _type_code(units):
    return (TYPE_CODES[LIST_ITEM] if units[0]["type"] == LIST else TYPE_CODES[units[0]["type"]]) if units else -1


def align(before_text: str, after_text: str, window: int = WINDOW) -> dict:
    """Aligned passages of two versions of a text, as numbers.

    Paragraphs are aligned on their content words: identical passages first
    (difflib), then the rest by similarity, allowing a paragraph to split in two
    or two to merge. Headings, lists, code and tables are matched only to their
    own type; prose may match a list or a quotation it became. Returns
    {"before", "after", "passages"}: each version's measurements, and the
    passages as columns:

      status              STATUS_CODES
      similarity          content-word Jaccard of the two sides (null when one is empty)
      b_para_start, b_para_end, b_sent_start, b_sent_end   the before side's
                          paragraph and sentence spans (-1 when empty); a_* the same after
      b_type, a_type      content type code of each side (-1 when empty; a list is list_item)
      b_parts, a_parts    paragraphs or lists on each side (a split is 1 -> 2)
      b_items, a_items    list items on each side
    """
    mb, ma = measure(before_text, window), measure(after_text, window)
    ub, ua = _units(before_text, mb), _units(after_text, ma)
    sm = difflib.SequenceMatcher(None, [u["key"] for u in ub], [u["key"] for u in ua], autojunk=False)
    pairs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            pairs.extend(([i], [j]) for i, j in zip(range(i1, i2), range(j1, j2)))
        else:
            pairs.extend(([i1 + x for x in xs], [j1 + y for y in ys])
                         for xs, ys in _align_region(ub[i1:i2], ua[j1:j2]))
    rows = []
    for xs, ys in pairs:
        X, Y = [ub[i] for i in xs], [ua[j] for j in ys]
        if not X:
            status = "inserted"
        elif not Y:
            status = "deleted"
        elif X[0]["type"] != Y[0]["type"]:
            status = "converted"
        elif len(X) < len(Y):
            status = "split"
        elif len(X) > len(Y):
            status = "merged"
        elif before_text[X[0]["chars"][0]:X[-1]["chars"][1]] == after_text[Y[0]["chars"][0]:Y[-1]["chars"][1]]:
            status = "unchanged"
        else:
            status = "edited"
        sim = (_sim(frozenset().union(*(u["fp"] for u in X)), frozenset().union(*(u["fp"] for u in Y)))
               if X and Y else None)
        row = {"status": STATUS_CODES[status], "similarity": None if sim is None else round(sim, 3)}
        for p, U in (("b", X), ("a", Y)):
            row.update({f"{p}_para_start": U[0]["paragraphs"][0] if U else -1,
                        f"{p}_para_end": U[-1]["paragraphs"][-1] if U else -1,
                        f"{p}_sent_start": U[0]["sentences"][0] if U else -1,
                        f"{p}_sent_end": U[-1]["sentences"][1] if U else -1,
                        f"{p}_type": _type_code(U), f"{p}_parts": len(U), f"{p}_items": sum(u["items"] for u in U)})
        rows.append(row)
    keys = ["status", "similarity"] + [f"{p}_{k}" for p in "ba" for k in
                                       ("para_start", "para_end", "sent_start", "sent_end", "type", "parts", "items")]
    return {"before": mb, "after": ma, "passages": _cols(rows, keys)}


# --------------------------------------------------------------------------
# text output (numbers only)

def _nz(x):
    return "-" if x["value"] is None else f"{x['value']:g} (shuffled {x['null_mean']:g}, z {x['z']:g})"


def format_text(m: dict) -> str:
    s, p, r = m["summary"], m["patterns"], m["rhythm"]
    b, ph, la, co = r["beat"], r["phrase"], r["landing"], r["contour"]
    pc = s["prose_length_percentiles"]
    out = [f"sentences            {s['sentences']} ({s['prose_sentences']} prose, {s['prose_syllables']} syllables)",
           f"paragraphs           {s['paragraphs']} (" + ", ".join(
               f"{n} {t}" for t, n in zip(CONTENT_TYPES, s["type_counts"]) if n) + ")",
           "prose length, words  " + (", ".join(f"{k} {v:g}" for k, v in pc.items()) if pc else "-"),
           f"beat clash           {_nz(b['clash_rate'])}",
           f"beat alternation     {_nz(b['alternation_share'])}",
           f"beat lapse           {_nz(b['lapse_rate'])}",
           f"ends stressed        {_nz(b['ending_stressed'])}",
           f"phrase contrast      {_nz(ph['phrase_contrast'])}",
           f"end weight           {_nz(ph['end_weight'])}",
           f"landing final        {_nz(la['final_ratio'])}",
           f"landing initial      {_nz(la['initial_ratio'])}",
           f"sentence alternation {_nz(co['alternation'])}"]
    if not p["computed"]:
        out.append(f"patterns             fewer than {MIN_PROSE} prose sentences: emphasis points only")
    out.append(f"flat_stretch_share   {p['flat_stretch_share']:g}")
    for k, v in p["counts"].items():
        out.append(f"{k:<26} {v}")
    return "\n".join(out)
