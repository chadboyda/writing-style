"""Linguistic judgements, supplied by Jev.

Text-analysis tools usually get these from trained models: vector spaces for
how related two passages are, frequency tables for how familiar a word is, a
classifier for what a demonstrative is doing. Each is a snap judgement a knowledgeable reader makes in a
second, which is what Jev is built for, so each becomes one small typed
question and the answers are composed in code.

Every function takes a `jev.Jev` and returns plain Python values. Nothing here
needs anything beyond the standard library.
"""
from __future__ import annotations

from . import jev as jevmod

# -- relatedness between two passages ----------------------------------------
# Worded on the STS benchmark's 0-5 scale, the scale sentence-embedding models
# are commonly trained to reproduce. Measured on held-out texts, this wording
# tracked mean adjacent-sentence embedding similarity at rho 0.83, where a
# question about discourse relatedness managed 0.66. A 10-level version was
# tried and did worse.
REL_LEVELS = [
    "Completely dissimilar: different subjects entirely",
    "Not equivalent, but on the same general topic",
    "Not equivalent, but they share some details or name some of the same things",
    "Roughly equivalent, though some important information differs",
    "Mostly equivalent; only unimportant details differ",
    "Completely equivalent: they mean the same thing",
]
REL_STATE = ("Semantic textual similarity. Each question gives two passages, A and B. Rate how similar "
             "they are in meaning, the way the STS benchmark does: shared subject matter, shared details, "
             "and shared information all count.")


def relatedness(j: "jevmod.Jev", pairs: list[tuple[str, str]]) -> list[float]:
    """0..1 similarity for each (a, b) pair, from one Score question per pair."""
    qs = {f"r{i}": {"type": "score",
                    "instructions": f"Passage A: {a}\n\nPassage B: {b}\n\nHow similar in meaning are A and B?",
                    "criteria": REL_LEVELS}
          for i, (a, b) in enumerate(pairs)}
    if not qs:
        return []
    ans = j.ask_many([(REL_STATE, qs)])[0]
    top = len(REL_LEVELS) - 1
    return [(jevmod.score_value(ans.get(f"r{i}"), len(REL_LEVELS)) or 0.0) / top for i in range(len(pairs))]


# -- demonstratives: determiner, pronoun, or something else ----------------
DEM_OPTIONS = {
    "det": "a determiner in front of a noun it points to ('THIS idea', 'those people')",
    "pron": "a stand-alone demonstrative pronoun pointing at something ('THIS is wrong', 'I saw THAT')",
    "rel": "'that' as a relative pronoun introducing a description of a noun ('the book THAT I read')",
    "comp": "'that' introducing a clause after a verb, adjective or noun ('she said THAT she left')",
    "adv": "an adverb meaning 'so' or 'to that degree' ('not THAT big')",
}
DEM_STATE = ("Each question shows a sentence with one word marked [[like this]] - this, that, these or "
             "those. Decide what job the marked word is doing in that sentence.")


def demonstrative_roles(j, sentences):
    """{(sentence, token): role} for every this/that/these/those."""
    qs, where = {}, {}
    for si, sent in enumerate(sentences):
        for ti, w in enumerate(sent):
            if w.lower() in ("this", "that", "these", "those"):
                marked = " ".join(("[[" + x + "]]" if k == ti else x) for k, x in enumerate(sent))
                qid = f"d{si}_{ti}"
                qs[qid] = {"type": "choice", "instructions": f"Sentence: {marked}\nWhat job is the marked word doing?",
                           "criteria": DEM_OPTIONS}
                where[qid] = (si, ti)
    if not qs:
        return {}
    ans = j.ask_many([(DEM_STATE, qs)])[0]
    return {where[q]: jevmod.choice_value(ans.get(q)) or "pron" for q in where}


# -- synonymy ----------------------------------------------------------------
SYN_STATE = "Each question names two English words. Decide whether they can mean the same thing."


def synonyms(j, pairs: set[tuple[str, str, str]]) -> dict[tuple[str, str, str], float]:
    """P(synonym) for each (word_a, word_b, class) pair; identical words are not asked."""
    qs, keys = {}, {}
    for i, (a, b, pos) in enumerate(sorted(pairs)):
        if a == b:
            continue
        qid = f"y{i}"
        qs[qid] = {"type": "noul",
                   "instructions": f"Can the {pos} '{a}' and the {pos} '{b}' mean the same thing - are they "
                                   f"synonyms in at least one ordinary sense?"}
        keys[qid] = (a, b, pos)
    if not qs:
        return {}
    ans = j.ask_many([(SYN_STATE, qs)])[0]
    return {keys[q]: jevmod.noul_value(ans.get(q)) or 0.0 for q in keys}


# -- word familiarity ------------------------------------------------------
FAM_LEVELS = [
    "A word most adults have never come across",
    "A rare or specialist word you meet only in particular fields",
    "An uncommon word you might meet in a newspaper now and then",
    "A familiar word you read or hear most weeks",
    "A word you meet every day",
    "One of the most common words in the language",
]
FAM_STATE = ("Word familiarity. Each question names one English word. Judge how often an ordinary "
             "adult reader meets it, across everything they read and hear.")


PHRASE_LEVELS = [
    "A combination that essentially never appears in ordinary writing",
    "A rare combination, specific to particular subjects",
    "A phrase you might see now and then",
    "A familiar phrase in magazines and newspapers",
    "A very common phrase you see constantly",
    "One of the most common word combinations in English (of the, in a, it is)",
]
PHRASE_STATE = ("Phrase frequency. Each question names a word or a short sequence of words (base forms). "
                "Judge how often that exact sequence appears in ordinary magazine and newspaper writing.")


def phrase_familiarity(j: "jevmod.Jev", phrases: list[str]) -> dict[str, float]:
    """Expected level (0..5) of how common each word or word sequence is in
    magazine and news writing - the baseline frequency keyness is measured against."""
    uniq = sorted(set(phrases))
    qs = {f"g{i}": {"type": "score", "instructions": f"How common is '{p}'?", "criteria": PHRASE_LEVELS}
          for i, p in enumerate(uniq)}
    if not qs:
        return {}
    ans = j.ask_many([(PHRASE_STATE, qs)])[0]
    return {p: jevmod.score_value(ans.get(f"g{i}"), len(PHRASE_LEVELS)) for i, p in enumerate(uniq)}


def familiarity(j: "jevmod.Jev", words: list[str]) -> dict[str, float]:
    """Expected familiarity level (0..5) per distinct word."""
    uniq = sorted(set(w.lower() for w in words))
    qs = {f"f{i}": {"type": "score", "instructions": f"How familiar is the word '{w}'?",
                    "criteria": FAM_LEVELS} for i, w in enumerate(uniq)}
    if not qs:
        return {}
    ans = j.ask_many([(FAM_STATE, qs)])[0]
    return {w: jevmod.score_value(ans.get(f"f{i}"), len(FAM_LEVELS)) for i, w in enumerate(uniq)}
