"""Word classes from the stdlib tagger in syntax.py, mapped to proseweave's classes.

syntax.Tagger gives a Penn Treebank tag per token, and syntax's coarse-class
model a Universal Dependencies class learned with the parse (so an auxiliary
'have' and a main-verb 'be' come out as the common English parsers label
them). `pos_tags` maps those to proseweave's classes: CCONJ and SCONJ are CONJ,
INTJ, SYM and X are OTHER. Without the coarse classes, the rules below apply
proseweave's own conventions (pos_fast.POS_DEFS): any form of 'be' is AUX,
possessives are pronouns, 'to' before a verb is a particle. Optionally, tokens
whose tagger margin (best score minus second best) is low are asked of Jev,
with pos_fast's question.
"""
from __future__ import annotations

from . import jev as jevmod
from . import pos_fast
from . import syntax
from . import text as tk

BE = {"be", "am", "is", "are", "was", "were", "been", "being", "'s", "’s", "'re", "’re", "'m", "’m"}
SUBORD = {"because", "if", "although", "though", "whether", "unless", "whereas", "that", "while", "once"}
PTB = {"NN": "NOUN", "NNS": "NOUN", "NNP": "PROPN", "NNPS": "PROPN", "PRP": "PRON", "PRP$": "PRON",
       "WP": "PRON", "WP$": "PRON", "EX": "PRON", "WDT": "PRON", "MD": "AUX", "JJ": "ADJ", "JJR": "ADJ",
       "JJS": "ADJ", "RB": "ADV", "RBR": "ADV", "RBS": "ADV", "WRB": "ADV", "DT": "DET", "PDT": "DET",
       "CC": "CONJ", "RP": "PART", "POS": "PART", "CD": "NUM", "UH": "OTHER", "FW": "OTHER", "SYM": "OTHER",
       "LS": "OTHER", "XX": "OTHER", "ADD": "OTHER", "AFX": "ADJ", "NFP": "PUNCT", "HYPH": "PUNCT"}
UD = {"CCONJ": "CONJ", "SCONJ": "CONJ", "INTJ": "OTHER", "SYM": "OTHER", "X": "OTHER", "SPACE": "PUNCT"}
# Tags whose class the rules decide even when the coarse classes are given. A
# CONJ here counts as a clause marker, and the coarse model's SCONJ for
# when/how/where (WRB) or CCONJ for both/either (DT, CC) follows word class,
# not the clause-marking relation the subordinator index counts.
RULE_TAGS = frozenset(("IN", "WRB", "DT", "CC"))


def ptb_tags(words: list[str]) -> list[tuple[str, float]]:
    """(tag, margin) per word, from both tagger passes; margin is inf where
    the tag dictionary decides."""
    margins = []
    tags = syntax.models().tagger.tag(words, margins)
    return list(zip(tags, margins))


def to_class(words, i, tag) -> str:
    w = words[i]
    low = w.lower()
    if not any(c.isalnum() for c in w):
        return "PUNCT"
    fixed = tk.closed_class(w)
    if fixed:
        return fixed
    if low in ("not", "n't", "n’t"):
        return "PART"
    if tag.startswith("VB"):
        if low in BE:
            return "AUX"
        if low in pos_fast.HAVE_DO:
            return pos_fast._have_do(words, i)
        return "VERB"
    if tag == "IN":
        return "CONJ" if low in SUBORD else "ADP"
    if tag == "TO":
        return "PART"      # pos_tags decides PART vs ADP from the next token's tag
    return PTB.get(tag, "PUNCT" if not w[:1].isalnum() else "OTHER")


JEV_MIN_CONFIDENCE = 0.8


def pos_tags(j, sentences: list[list[str]], margin: float | None = None,
             open_only: bool = True, fine=None, upos=None) -> list[list[str]]:
    """proseweave classes per token. With `margin`, tokens the tagger is unsure
    of (margin below it) are asked of Jev instead. `fine` supplies each
    sentence's (Penn tag, margin) pairs and `upos` its coarse classes, both
    already computed by the parse; without `upos` the rules above decide."""
    tags, qs, where = [], {}, {}
    for si, s in enumerate(sentences):
        pt = fine[si] if fine is not None else ptb_tags(s)
        row = []
        for ti, (t, m) in enumerate(pt):
            if upos is not None and t not in RULE_TAGS:
                c = UD.get(upos[si][ti], upos[si][ti])
            else:
                c = to_class(s, ti, t)
                if t == "TO":
                    c = "PART" if ti + 1 < len(pt) and pt[ti + 1][0].startswith("VB") else "ADP"
            row.append(c)
            if margin is not None and j is not None and m < margin and s[ti][:1].isalpha() \
                    and not tk.closed_class(s[ti]) \
                    and not (open_only and s[ti].lower() in tk.stop_words()):
                marked = " ".join(("[[" + x + "]]" if k == ti else x) for k, x in enumerate(s))
                q = f"p{si}_{ti}"
                qs[q] = {"type": "choice", "instructions": f"Sentence: {marked}\nWhat part of speech is the marked word?",
                         "criteria": pos_fast.POS_LABELS}
                where[q] = (si, ti)
        tags.append(row)
    if qs:
        ans = j.ask_many([(pos_fast.POS_STATE, qs)])[0]
        for q, (si, ti) in where.items():
            a = ans.get(q) or {}
            c = jevmod.choice_value(a)
            # Jev overrides the tagger only when it is confident: a split decision
            # would flip from run to run, and the tagger's guess is as good.
            if c and float((a.get("probabilities") or {}).get(c, 1.0)) >= JEV_MIN_CONFIDENCE:
                tags[si][ti] = c
    return tags
