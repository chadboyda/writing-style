"""Connective indices: counted from proseweave's own connective inventory.

The categories follow the connective classes of the cohesion literature
(Halliday & Hasan 1976; Quirk et al. 1985; Sanders, Spooren & Noordman 1992;
Louwerse 2001; Graesser et al. 2004). Their members are listed in
data/connectives_en.json, which proseweave's authors compiled independently
from English grammar; no other tool's word lists were used.

Counting is deterministic: each sentence is scanned left to right, the
longest item that fits is taken, and its words are not used again for the
same index. A handful of words are connectives in one sense and not in
another ("so" meaning "therefore" or "very"; "since" meaning "because" or
"from then"). Those occurrences get one Jev Choice each, asked in context;
without Jev the word's tagged class decides, then a fixed default.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import jev as jevmod
from . import text as tk

DATA = Path(__file__).parent / "data" / "connectives_en.json"


@lru_cache(maxsize=1)
def inventory() -> dict:
    return json.loads(DATA.read_text())


def _parse(item: str):
    """'so that|purpose,result' -> (('so', 'that'), 'sense', {'purpose', 'result'});
    'while#sub' -> (('while',), 'sub', None)."""
    if "|" in item:
        words, senses = item.split("|")
        return _words(words), "sense", frozenset(senses.split(","))
    if item.endswith("#sub"):
        return _words(item[:-4]), "sub", None
    return _words(item), None, None


def _words(phrase: str) -> tuple:
    """An item's words as the tokenizer splits running text ("that's" -> "that", "'s"),
    punctuation dropped as it is from the counted tokens."""
    return tuple(w.lower() for w in tk.tokenize(tk.normalize_apostrophes(phrase)) if any(c.isalnum() for c in w))


def build(groups, single_words_only=False, plus=(), sense_mode=None):
    """Item table for one index, keyed by first word, longest item first.

    sense_mode maps a sense-dependent word to "all" (count it in every sense)
    or "none" (never count it); by default the senses written in the item count.
    """
    inv = inventory()
    sense_mode = sense_mode or {}
    items = []
    for g in groups:
        items += inv["groups"][g]["items"]
    if single_words_only:
        items = [i for i in items if len(i.split("|")[0].split("#")[0].split()) == 1]
    for g in plus:
        items += inv["groups"][g]["items"]
    parsed = {}
    for it in items:
        words, kind, senses = _parse(it)
        if kind == "sense":
            m = sense_mode.get(" ".join(words))
            if m == "none":
                continue
            if m == "all":
                kind, senses = None, None
        # the same words may appear with different senses: merge them
        key = (words, kind)
        if key in parsed and senses:
            parsed[key] = parsed[key] | senses
        else:
            parsed.setdefault(key, senses)
    by_first = {}
    for (w, k), s in sorted(parsed.items(), key=lambda x: -len(x[0][0])):
        by_first.setdefault(w[0], []).append((w, k, s))
    return by_first


@lru_cache(maxsize=None)
def _compiled(index: str):
    spec = inventory()["indices"][index]
    return build(spec["groups"], spec.get("single_words_only", False), spec.get("plus", ()),
                 spec.get("senses"))


def sensed_items() -> set[tuple[str, ...]]:
    """Word sequences whose count depends on their sense in context."""
    return {tuple(k.split()) for k in inventory()["senses"]}


# -- clause-introducing uses --------------------------------------------------
# The tagger marks a fixed list of words as subordinators. These words introduce
# a clause in some uses and govern a noun phrase in others (Quirk et al. 1985,
# 14.12: "before she left" / "before noon"), so each occurrence is one Jev Noul.
# Measured: lexical_subordinators 0.86 -> 0.95 (open) and 0.84 -> 0.93
# (article corpus; texts not redistributed), held-out rho; nothing was tuned.
CLAUSE_WORDS = frozenset("before after until till since as than like once because so".split())
CLAUSE_STATE = ("Each question shows one sentence with one word marked [[like this]]. Decide whether the marked "
                "word introduces a clause that has its own verb ('before she left', 'as he spoke', 'than we "
                "expected', 'like I said'), rather than a noun phrase or nothing ('before noon', 'as a child', "
                "'than him').")


def clause_marks(j, sents) -> set[tuple[int, int]]:
    """(sentence, token) of the CLAUSE_WORDS occurrences Jev reads as introducing a clause."""
    qs, where = {}, {}
    for si, s in enumerate(sents):
        raw = [t.raw for t in s]
        for ti, t in enumerate(s):
            if t.raw in CLAUSE_WORDS and not t.mark and ti + 1 < len(s):
                marked = " ".join(("[[" + x + "]]" if k == ti else x) for k, x in enumerate(raw))
                q = f"m{si}_{ti}"
                qs[q] = {"type": "noul", "instructions": f"Sentence: {marked}"}
                where[q] = (si, ti)
    if not qs:
        return set()
    ans = j.ask_many([(CLAUSE_STATE, qs)])[0]
    return {where[q] for q, a in ans.items() if q in where and (jevmod.noul_value(a) or 0.0) >= 0.5}


# -- senses ------------------------------------------------------------------
SENSE_STATE = ("Each question shows one sentence with a word or phrase marked [[like this]]. Choose what the "
               "marked words mean or do in that sentence.")
SENSE_QUESTION = "What does the marked '{it}' mean or do here?"
SENSE_CONTEXT = False   # adding the previous sentence moved no index by more than 0.01 (measured on both validation corpora)


def candidates(sents) -> list[tuple[int, int, str]]:
    """(sentence, token, item) for every occurrence of a sense-dependent item."""
    keys = {}
    for k in sorted(sensed_items()):   # fixed order: question ids (and the Jev cache) must not depend on hash seed
        keys.setdefault(k[0], []).append(k)
    out = []
    for si, s in enumerate(sents):
        raw = [t.raw for t in s]
        for ti in range(len(raw)):
            for k in keys.get(raw[ti], ()):
                if tuple(raw[ti:ti + len(k)]) == k:
                    out.append((si, ti, " ".join(k)))
    return out


def fallback_sense(tok, item: str) -> str:
    sp = inventory()["senses"][item]
    cls = tok.cls
    return sp.get("by_class", {}).get(cls) or sp["default"][0]


def senses_local(sents) -> dict:
    return {(si, ti, it): fallback_sense(sents[si][ti], it) for si, ti, it in candidates(sents)}


def senses_jev(j, sents) -> dict:
    """One Jev Choice per sense-dependent occurrence, in context."""
    inv = inventory()["senses"]
    qs, where = {}, {}
    for n, (si, ti, it) in enumerate(candidates(sents)):
        L = len(it.split())
        raw = [t.raw for t in sents[si]]
        marked = " ".join(raw[:ti] + ["[[" + " ".join(raw[ti:ti + L]) + "]]"] + raw[ti + L:])
        qid = f"s{n}"
        text = f"Sentence: {marked}"
        if SENSE_CONTEXT and si > 0:
            text = "Previous sentence: " + " ".join(t.raw for t in sents[si - 1]) + "\n" + text
        qs[qid] = {"type": "choice", "criteria": inv[it]["options"],
                   "instructions": f"{text}\n{SENSE_QUESTION.format(it=it)}"}
        where[qid] = (si, ti, it)
    out = senses_local(sents)
    if qs:
        ans = j.ask_many([(SENSE_STATE, qs)])[0]
        for qid, key in where.items():
            c = jevmod.choice_value(ans.get(qid))
            if c:
                out[key] = c
    return out


# -- counting ------------------------------------------------------------------
def count(sents, index: str, senses: dict | None) -> int:
    """Occurrences of the index's items. senses=None counts every sense."""
    items = _compiled(index)
    n = 0
    for si, s in enumerate(sents):
        raw = [t.raw for t in s]
        i = 0
        while i < len(raw):
            hit = 0
            for words, kind, allowed in items.get(raw[i], ()):
                L = len(words)
                if tuple(raw[i:i + L]) != words:
                    continue
                if kind == "sub" and not s[i].mark:
                    continue
                if kind == "sense" and senses is not None and senses.get((si, i, " ".join(words))) not in allowed:
                    continue
                hit = L
                break
            if hit:
                n += 1
                i += hit
            else:
                i += 1
    return n


def indices(sents, nwords: int, senses: dict | None) -> dict[str, float]:
    return {ix: (count(sents, ix, senses) / nwords if nwords else 0.0) for ix in inventory()["indices"]}
