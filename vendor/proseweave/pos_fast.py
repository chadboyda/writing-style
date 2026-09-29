"""Word-class helpers shared by tagger_classes.py.

  - the Jev question for a token the tagger is unsure of: the option
    definitions are stated once per request, in the state, and each question
    carries only short labels;
  - the 'have' / 'do' decision (auxiliary or main verb), settled locally from
    the words that follow.
"""
from __future__ import annotations

from . import text as tk

# Definitions, stated once in the state.
POS_DEFS = {
    "NOUN": "common noun (dog, idea, mornings, the running of the race)",
    "PROPN": "proper noun: the specific name of a person, place, organisation, day or month "
             "(Mara, London, NASA, Monday)",
    "PRON": "pronoun, INCLUDING possessive pronouns before a noun (his, her, their, my, its) and "
            "relative pronouns (who, which, that meaning 'which')",
    "VERB": "main verb carrying the action or state (walked, think, running, seemed)",
    "AUX": "auxiliary: ANY form of 'be' (is, was, are, been, being - even when it is the only verb, "
           "as in 'she is tired'), 'have' or 'do' helping another verb, and modals (can, will, would, "
           "should, must, might)",
    "ADJ": "adjective (red, older, happy, American)",
    "ADV": "adverb (quickly, very, never, then, here)",
    "DET": "article or determiner (the, a, an, this, those, every, some, no) - but NOT his/her/their, "
           "which are pronouns",
    "ADP": "preposition, including 'to' before a noun (in, of, over, to the shop)",
    "CONJ": "conjunction joining words or clauses (and, but, or, because, if, although, and 'that' "
            "introducing a clause as in 'said that she left')",
    "PART": "particle: 'to' directly before a verb (to go), not / n't, possessive 's, and the "
            "adverb half of a phrasal verb (give UP)",
    "NUM": "number (two, fifth, million, 1998)",
    "OTHER": "anything else (interjection, symbol, foreign word)",
}
POS_LABELS = {
    "NOUN": "common noun", "PROPN": "proper noun", "PRON": "pronoun", "VERB": "main verb",
    "AUX": "auxiliary", "ADJ": "adjective", "ADV": "adverb", "DET": "determiner",
    "ADP": "preposition", "CONJ": "conjunction", "PART": "particle", "NUM": "number", "OTHER": "other",
}
POS_STATE = ("Part-of-speech tagging. Each question shows one sentence with a single word marked "
             "[[like this]]. Classify the marked word by its grammatical role in that sentence, using "
             "these definitions:\n" + "\n".join(f"- {POS_LABELS[k]}: {v}" for k, v in POS_DEFS.items()))

SUBJECT = {"i", "you", "he", "she", "we", "they", "it"}
_OPEN = (("NOUN", "noun"), ("VERB", "verb"), ("ADJ", "adj"), ("ADV", "adv"))
IRREGULAR_PARTICIPLES = {
    "known", "gone", "done", "made", "built", "set", "born", "grown", "shown", "thrown", "drawn", "seen",
    "taken", "given", "written", "driven", "broken", "chosen", "spoken", "held", "found", "led", "left",
    "lost", "paid", "sold", "told", "thought", "brought", "bought", "caught", "taught", "meant", "kept",
    "felt", "begun", "won", "spent", "sent", "understood", "worn", "torn", "hidden", "forgotten"}


def _open_classes(word):
    low = word.lower()
    index = tk.lemma_tables()["lemma_index"]
    return [c for c, key in _OPEN if tk.lemmatize(low, c) in index[key]]


def _participle(w: str) -> bool:
    """Is w a past or present participle of a known verb?"""
    low = w.lower()
    if low in IRREGULAR_PARTICIPLES:
        return True
    if not low.endswith(("ed", "ing", "en")):
        return False
    lem = tk.lemmatize(w, "VERB")
    return lem != low and lem in tk.lemma_tables()["lemma_index"]["verb"]


HAVE_DO = {"have", "has", "had", "having", "do", "does", "did"}
_SKIP = {"not", "n't", "never", "also", "just", "already", "always", "ever", "still", "often",
         "really", "only", "even", "since", "long", "been"}


def _have_do(sent, ti):
    """AUX when a verb form follows (skipping adverbs, 'not' and a subject
    pronoun in questions), else a main verb: 'had left', 'did not go' vs 'had a car'."""
    low = sent[ti].lower()
    for k in range(ti + 1, min(ti + 4, len(sent))):
        w = sent[k].lower()
        if w in _SKIP or w in SUBJECT:
            if w == "been":
                return "AUX"
            continue
        oc = _open_classes(w) if w.isalpha() else []
        if "VERB" in oc and (low.startswith("d") or _participle(w) or w.endswith("ed")):
            return "AUX"
        return "VERB"
    return "VERB"
