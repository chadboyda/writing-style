"""Tokens, sentences, tags, lemmas and dependency heads, standard library only.

A tokenizer following the English conventions spaCy documents, and five greedy
averaged-perceptron models sharing one weight file: a two-pass part-of-speech
tagger (the second pass sees the first pass's tags for the words ahead), a
sentence-boundary classifier, an arc-hybrid transition parser (Kuhlmann,
Gomez-Rodriguez & Satta 2011) trained with a dynamic oracle (Goldberg & Nivre
2012, 2013), and a coarse-class (Universal Dependencies) model that reads the
tag, the word and its place in the parse. Lemmas come from the rule
lemmatizer over proseweave's tables, with a short list of learned
corrections. The design follows the published literature on greedy tagging
and parsing; the weights are learned at build time (see tools/syntax/ and
data/SYNTAX_LICENSE.md) and nothing here downloads anything.

    from proseweave import syntax
    toks = syntax.analyse(text)       # Tokens: text, tag, pos, lemma, head, sent_start
    syntax.dep_distances(toks, stop)  # |head - dependent| for content words

Positions count every token, punctuation and line breaks included.
"""
import array
import functools
import gzip
import itertools
import json
import pathlib
import re
import struct
import sys
import unicodedata
import zlib
from bisect import bisect_left
from dataclasses import dataclass

DATA = pathlib.Path(__file__).resolve().parent / "data" / "syntax_en.bin.gz"


# --------------------------------------------------------------------------
# tokens

@dataclass
class Token:
    text: str
    ws: str = ""                # whitespace after the token (" " or "")
    tag: str = ""               # Penn Treebank tag
    head: int = -1              # document-level index of the head; itself for a root
    sent_start: bool = False
    pos: str = ""               # Universal Dependencies class
    lemma: str = ""
    margin: float = float("inf")  # tagger score gap to the runner-up tag

    @property
    def is_space(self) -> bool:
        return not self.text.strip()


# The tokenizer follows the algorithm spaCy documents for English ("How
# spaCy's tokenizer works"): split on spaces; for each chunk, repeatedly peel a
# prefix or a suffix, checking the special cases at each step; then split what
# is left on infixes. The affix inventories below follow that description; the
# abbreviation and emoticon lists are spaCy's (MIT licence). Chunks where this
# still disagrees with spaCy on the build text are listed in the weight file
# ("tok_exc") and taken from there.
_URL = re.compile(r"^(?:(?:https?|ftp)://|www\.)\S+$", re.I)
_EMOTICONS = frozenset(r"""
:) :-) :)) :-)) :))) :-))) (: (-: =) (= :] :-] [: [-: [= =] :o) (o: :} :-} 8) 8-) (-8 ;) ;-) (; (-;
:( :-( :(( :-(( :((( :-((( ): )-: =( >:( :') :'-) :'( :'-( :/ :-/ =/ :| :-| =| :P :-P :p :-p :O :-O
:o :-o :0 :-0 :() >:o :* :-* :3 :-3 =3 :> :-> :X :-X :x :-x :D :-D ;D ;-D =D xD XD xDD XDD 8D 8-D
^_^ ^__^ ^___^ >.< >.> <.< ._. ;_; -_- -__- v.v V.V v_v V_V o_o o_O O_o O_O 0_o o_0 0_0 <3 <33 <333 </3
(^_^) (-_-) (._.) (>_<) (*_*) (¬_¬) ಠ_ಠ ಠ︵ಠ (ಠ_ಠ) ¯\(ツ)/¯
""".split())
_ABBREV = frozenset("""
a.m. p.m. Adm. Bros. co. Co. Corp. D.C. Dr. e.g. E.g. E.G. Gen. Gov. i.e. I.e. I.E. Inc. Jr. Ltd. Md.
Messrs. Mo. Mont. Mr. Mrs. Ms. Ph.D. Prof. Rep. Rev. Sen. St. vs. v.s. Jan. Feb. Mar. Apr. Jun. Jul.
Aug. Sep. Sept. Oct. Nov. Dec. Ala. Ariz. Ark. Calif. Colo. Conn. Del. Fla. Ga. Ill. Ind. Kan. Kans.
Ky. La. Mass. Mich. Minn. Miss. N.C. N.D. N.H. N.J. N.M. N.Y. Neb. Nebr. Nev. Okla. Ore. Pa. S.C.
Tenn. Va. Wash. Wis. Mt.
""".split())
_NT_HOSTS = frozenset("""
do does did is are was were have has had could would should must might need dare ai ca wo sha
""".split())
_CLITIC_HOSTS = {
    "m": {"i"},
    "re": {"you", "we", "they", "who", "what", "there"},
    "ve": {"i", "you", "we", "they", "who", "what", "would", "could", "should", "might", "must"},
    "ll": {"i", "you", "he", "she", "it", "we", "they", "who", "what", "that", "there", "this"},
    "d": {"i", "you", "he", "she", "it", "we", "they", "who", "what", "that", "there", "how", "where"},
}
_PUNCT = set(",:;!?¿¡()[]{}<>_#*&")
_QUOTES = set("'\"”“`‘´’‚„»«「」『』（）〔〕【】《》〈〉")
_CURRENCY = set("$£€¥฿₽﷼₴₠₡₢₣₤₥₦₧₨₩₪₫₭₮₯₰₱₲₳₵₶₷₸₹₺₻₼₾₿")
_PREFIX_CHARS = _PUNCT | _QUOTES | _CURRENCY | set("§%=—–…")
_UNITS = sorted("""
km km² km³ m m² m³ dm dm² dm³ cm cm² cm³ mm mm² mm³ ha µm nm yd in ft kg g mg µg t lb oz m/s km/h kmh
mph hPa Pa mbar mb MB kb KB gb GB tb TB T G M K %
""".split(), key=len, reverse=True)
_ALPHA = r"[^\W\d_]"
_LOWER = r"[a-zß-öø-ÿ]"
_UPPER = r"[A-ZÀ-ÖØ-Þ]"
_INFIX = re.compile(
    r"\.\.+|…"
    r"|(?<=[0-9])[+\-*^](?=[0-9-])"
    rf"|(?<={_LOWER}|['\"”“’‘])\.(?={_UPPER}|['\"”“’‘])"
    rf"|(?<={_ALPHA}),(?={_ALPHA})"
    rf"|(?<={_ALPHA}|[0-9])(?:---|--|——|—|–|-|~)(?={_ALPHA})"
    rf"|(?<={_ALPHA}|[0-9])[:<>=/](?={_ALPHA})")


def _icon(c):
    return c != "°" and unicodedata.category(c) == "So"


def _prefix(w):
    """Length of the prefix to peel off, or 0."""
    for cur in ("US$", "C$", "A$"):
        if w.startswith(cur):
            return len(cur)
    m = re.match(r"\.\.+", w)
    if m:
        return m.end()
    c = w[0]
    if c == "+":
        return 0 if len(w) > 1 and w[1].isdigit() else 1
    if c in _PREFIX_CHARS or _icon(c):
        return 1
    return 0


def _suffix(w):
    """Length of the suffix to peel off, or 0. Of the patterns that match, the
    one starting furthest left wins, as in a single alternation."""
    cands = []
    m = re.search(r"\.\.+$", w)
    if m:
        cands.append(m.start())
    c = w[-1]
    if c in _PUNCT or c in _QUOTES or c == "…" or c in "—–" or _icon(c):
        cands.append(len(w) - 1)
    if w[-2:] in ("'s", "'S", "’s", "’S") and len(w) > 2:
        cands.append(len(w) - 2)
    if c == "+" and len(w) > 1 and w[-2].isdigit():
        cands.append(len(w) - 1)
    if c == "." and len(w) > 1:
        p = w[-2]
        if p.isdigit() or p.islower() or p in "%²-+" or p in _QUOTES or p in _PUNCT \
                or (len(w) > 2 and p.isupper() and w[-3].isupper()) \
                or (len(w) > 2 and p in "FfCcKk" and w[-3] == "°"):
            cands.append(len(w) - 1)
    for cur in _CURRENCY:
        if w.endswith(cur) and len(w) > len(cur) and w[-len(cur) - 1].isdigit():
            cands.append(len(w) - len(cur))
    for u in _UNITS:
        if w.endswith(u) and len(w) > len(u) and w[-len(u) - 1].isdigit():
            cands.append(len(w) - len(u))
            break
    return len(w) - min(cands) if cands else 0


def _special(w):
    """The special-case split of a chunk, or None."""
    if w in _EMOTICONS or w in _ABBREV or re.fullmatch(r"[a-zäöü]\.", w):
        return [w]
    low = w.lower()
    if low in ("cannot", "gonna", "gotta", "wanna"):
        return [w[:3], w[3:]]
    for nt in ("n't", "n’t"):
        if low.endswith(nt) and low[:-3] in _NT_HOSTS:
            return [w[:-3], w[-3:]]
    m = re.fullmatch(r"(.+?)(['’])(m|re|ve|ll|d)", low)
    if m and m.group(1) in _CLITIC_HOSTS[m.group(3)]:
        k = len(m.group(1))
        return [w[:k], w[k:]]
    return None


def _split_word(w, exc=None):
    """Split one space-free chunk: special cases, prefixes and suffixes, infixes."""
    if exc and w in exc:
        return list(exc[w])
    front, back = [], []
    while w:
        sp = _special(w)
        if sp is not None:
            front += sp
            w = ""
            break
        k = _prefix(w) if len(w) > 1 else 0
        if k:
            front.append(w[:k])
            w = w[k:]
            if not w or _special(w) is not None:
                continue
        j = _suffix(w) if len(w) > 1 else 0
        if j and j < len(w):
            back.insert(0, w[-j:])
            w = w[:-j]
        elif not k:
            break
    if w:
        if _URL.match(w):
            front.append(w)
        else:
            pos = 0
            for m in _INFIX.finditer(w):
                if m.start() == 0 and pos == 0:
                    continue
                if m.start() > pos:
                    front.append(w[pos:m.start()])
                front.append(m.group(0))
                pos = m.end()
            if pos < len(w):
                front.append(w[pos:])
    out = [t for t in front + back if t]
    # special cases that span affixes (an emoticon like "):" after "20(2")
    k = 1
    while k + 1 < len(out):
        if out[k] + out[k + 1] in _EMOTICONS:
            out[k:k + 2] = [out[k] + out[k + 1]]
        k += 1
    return out


def tokenize(text: str, exc=None) -> list:
    """Tokens with their trailing whitespace. A single space after a token is
    kept as its `ws`; any other run of whitespace (a line break, a double
    space) becomes a token of its own, as it is in common English pipelines.
    `exc` maps whole chunks to their tokens (default: the weight file's list)."""
    if exc is None:
        exc = models().tok_exc if DATA.exists() else {}
    toks = []
    for m in re.finditer(r"(\S+)(\s*)", text):
        parts = _split_word(m.group(1), exc)
        for p in parts[:-1]:
            toks.append(Token(p))
        space = m.group(2)
        toks.append(Token(parts[-1], " " if space.startswith(" ") else ""))
        rest = space[1:] if space.startswith(" ") else space
        if rest:
            toks.append(Token(rest, ""))
    lead = re.match(r"\s*", text).group(0)
    if lead:
        toks.insert(0, Token(lead))
    return toks


# --------------------------------------------------------------------------
# the models

@functools.lru_cache(maxsize=1 << 16)
def _shape(w):
    s = re.sub(r"[A-Z]", "X", w)
    s = re.sub(r"[a-z]", "x", s)
    s = re.sub(r"[0-9]", "d", s)
    return re.sub(r"(.)\1{2,}", r"\1\1", s)


@functools.lru_cache(maxsize=1 << 16)
def _norm(w):
    if w.isdigit():
        return "!DIGITS" if len(w) != 4 else "!YEAR"
    if not w.strip():
        return "!SP" + str(w.count("\n"))
    return w.lower()


class Perceptron:
    """Averaged perceptron over string features, sparse per class.
    `classes` fixes the order of the score vector."""

    def __init__(self, classes):
        self.classes = list(classes)
        self.w = {}                 # feature -> {class index: weight}
        self._tot = {}              # training only: (feature, class) -> summed weight
        self._ts = {}               # training only: (feature, class) -> last update
        self.i = 0

    def scores(self, feats):
        s = [0.0] * len(self.classes)
        w = self.w
        for f in feats:
            v = w.get(f)
            if v:
                for c, x in v.items():
                    s[c] += x
        return s

    def update(self, truth, guess, feats):
        self.i += 1
        if truth == guess:
            return
        tot, ts, i = self._tot, self._ts, self.i
        for f in feats:
            v = self.w.get(f)
            if v is None:
                v = self.w[f] = {}
            for c, d in ((truth, 1.0), (guess, -1.0)):
                key = (f, c)
                x = v.get(c, 0.0)
                tot[key] = tot.get(key, 0.0) + (i - ts.get(key, 0)) * x
                ts[key] = i
                v[c] = x + d

    def average(self):
        i = max(self.i, 1)
        for f, v in self.w.items():
            for c, x in list(v.items()):
                key = (f, c)
                avg = (self._tot.get(key, 0.0) + (self.i - self._ts.get(key, 0)) * x) / i
                v[c] = avg
        self._tot, self._ts = {}, {}


class Tagger:
    """Greedy left-to-right tagging. With `model2`, a second pass re-tags each
    word seeing the first pass's tags for the words that follow it."""

    def __init__(self, model=None, tagdict=None, model2=None):
        self.model = model
        self.model2 = model2
        self.tagdict = tagdict or {}

    @staticmethod
    def features(words, i, p1, p2, ahead=None):
        w = words[i]
        lw = _norm(w)
        prev = _norm(words[i - 1]) if i > 0 else "!START"
        prev2 = _norm(words[i - 2]) if i > 1 else "!START"
        nxt = _norm(words[i + 1]) if i + 1 < len(words) else "!END"
        nxt2 = _norm(words[i + 2]) if i + 2 < len(words) else "!END"
        sh = _shape(w)
        f = ["b", "w=" + lw, "s4=" + lw[-4:], "s3=" + lw[-3:], "s2=" + lw[-2:], "s1=" + lw[-1:],
             "p1=" + lw[:1], "p2=" + lw[:2], "p3=" + lw[:3], "sh=" + sh[:6], "shf=" + sh[:10],
             "hy=" + str("-" in w) + str(any(c.isdigit() for c in w)),
             "t1=" + p1, "t2=" + p2, "t12=" + p1 + "|" + p2,
             "t1w=" + p1 + "|" + lw, "t1s3=" + p1 + "|" + lw[-3:], "pw=" + prev, "ps3=" + prev[-3:],
             "ppw=" + prev2, "nw=" + nxt, "ns3=" + nxt[-3:], "nnw=" + nxt2, "cap=" + str(w[:1].isupper()) + p1,
             "pw_w=" + prev + "|" + lw, "w_nw=" + lw + "|" + nxt, "pw_nw=" + prev + "|" + nxt,
             "t1_nw=" + p1 + "|" + nxt]
        if ahead is not None:
            a1 = ahead[i + 1] if i + 1 < len(ahead) else "!END"
            a2 = ahead[i + 2] if i + 2 < len(ahead) else "!END"
            f += ["a1=" + a1, "a2=" + a2, "a12=" + a1 + "|" + a2, "t1a1=" + p1 + "|" + a1,
                  "a1w=" + a1 + "|" + lw, "a1s3=" + a1 + "|" + lw[-3:], "a1nw=" + a1 + "|" + nxt,
                  "t1wa1=" + p1 + "|" + lw + "|" + a1]
        return f

    def _pass(self, model, words, ahead=None, margins=None):
        tags = []
        p1 = p2 = "!START"
        classes = model.classes
        for i, w in enumerate(words):
            m = float("inf")
            if not w.strip():
                t = "_SP"
            else:
                t = self.tagdict.get(w)
                if t is None:
                    s = model.scores(self.features(words, i, p1, p2, ahead))
                    order = sorted(range(len(s)), key=s.__getitem__, reverse=True)
                    t = classes[order[0]]
                    if len(order) > 1:
                        m = s[order[0]] - s[order[1]]
            if margins is not None:
                margins.append(m)
            tags.append(t)
            p2, p1 = p1, t
        return tags

    def tag(self, words, margins=None):
        """Penn tags; pass a list as `margins` to receive, per word, the score
        gap between the chosen tag and the runner-up (inf where the tag
        dictionary decides)."""
        if self.model2 is None:
            return self._pass(self.model, words, margins=margins)
        return self._pass(self.model2, words, self._pass(self.model, words), margins=margins)


class Segmenter:
    """Does a sentence start at this token? Tokens after a line break or a
    stop are the usual candidates; the model learns which of them do."""

    def __init__(self, model=None, kind="full"):
        self.model = model
        self.feats = self.features_base if kind == "base" else self.features

    @staticmethod
    def features_base(toks, tags, i):
        # toks: (word, space before it) for the non-space words
        w, t = toks[i][0], tags[i]
        sp = toks[i][1]
        pw, pt = (toks[i - 1][0], tags[i - 1]) if i > 0 else ("!START", "!START")
        ppw = toks[i - 2][0] if i > 1 else "!START"
        nw, nt = (toks[i + 1][0], tags[i + 1]) if i + 1 < len(toks) else ("!END", "!END")
        lw, lp, ln = _norm(w), _norm(pw), _norm(nw)
        sh = _shape(w)[:4]
        return ["b", "sp=" + sp, "w=" + lw, "t=" + t, "pw=" + lp, "pt=" + pt, "nw=" + ln, "nt=" + nt,
                "sh=" + sh, "psh=" + _shape(pw)[:4], "ppw=" + _norm(ppw),
                "pw_sh=" + lp + "|" + sh, "pt_t=" + pt + "|" + t, "sp_t=" + sp + "|" + t,
                "sp_pt=" + sp + "|" + pt, "sp_sh=" + sp + "|" + sh, "sp_pw=" + sp + "|" + lp,
                "pw_w=" + lp + "|" + lw, "pt_t_nt=" + pt + "|" + t + "|" + nt,
                "sp_pt_t=" + sp + "|" + pt + "|" + t, "ppw_pw_sh=" + _norm(ppw) + "|" + lp + "|" + sh]

    @staticmethod
    def features(toks, tags, i):
        """The base set plus the next word's shape and the word pairs."""
        w, sp = toks[i]
        pw = toks[i - 1][0] if i > 0 else "!START"
        nw = toks[i + 1][0] if i + 1 < len(toks) else "!END"
        lw, lp, ln = _norm(w), _norm(pw), _norm(nw)
        sh, nsh = _shape(w)[:4], _shape(nw)[:4]
        return Segmenter.features_base(toks, tags, i) + [
            "nsh=" + nsh, "sh_nsh=" + sh + "|" + nsh, "w_nw=" + lw + "|" + ln,
            "sp_w=" + sp + "|" + lw, "sp_pw_w=" + sp + "|" + lp + "|" + lw]

    def starts(self, toks, tags):
        out = [True]
        for i in range(1, len(toks)):
            s = self.model.scores(self.feats(toks, tags, i))
            out.append(s[1] > s[0])
        return out


SHIFT, LEFT, RIGHT = 0, 1, 2


class Parser:
    """Arc-hybrid transitions over one sentence, the root at the end of the buffer."""

    def __init__(self, model=None):
        self.model = model

    @staticmethod
    def features(words, tags, n, stack, b, heads, lefts, rights):
        def tok(i):
            return (words[i], tags[i]) if 0 <= i < n else (("!ROOT", "!ROOT") if i == n else ("-", "-"))

        s0 = stack[-1] if stack else -1
        s1 = stack[-2] if len(stack) > 1 else -1
        s2 = stack[-3] if len(stack) > 2 else -1
        n0, n1, n2 = b, (b + 1 if b + 1 <= n else -1), (b + 2 if b + 2 <= n else -1)
        s0w, s0t = tok(s0)
        s1w, s1t = tok(s1)
        s2w, s2t = tok(s2)
        n0w, n0t = tok(n0)
        n1w, n1t = tok(n1)
        n2w, n2t = tok(n2)

        def kid(lst, i, k):
            if i < 0 or i >= n:
                return -1
            c = lst[i]
            return c[k] if -len(c) <= k < len(c) else -1

        s0l1, s0l2 = kid(lefts, s0, 0), kid(lefts, s0, 1)
        s0r1, s0r2 = kid(rights, s0, -1), kid(rights, s0, -2)
        n0l1, n0l2 = kid(lefts, n0, 0), kid(lefts, n0, 1)
        s0l1t, s0l2t, s0r1t, s0r2t = tok(s0l1)[1], tok(s0l2)[1], tok(s0r1)[1], tok(s0r2)[1]
        n0l1t, n0l2t = tok(n0l1)[1], tok(n0l2)[1]
        s0l1w, s0r1w, n0l1w = tok(s0l1)[0], tok(s0r1)[0], tok(n0l1)[0]
        d = n0 - s0 if s0 >= 0 else 0
        d = str(d) if d < 5 else ("5-9" if d < 10 else "10+")
        s0v = f"{len(lefts[s0]) if 0 <= s0 < n else 0}/{len(rights[s0]) if 0 <= s0 < n else 0}"
        n0v = str(len(lefts[n0])) if 0 <= n0 < n else "0"
        depth = str(min(len(stack), 5))
        # punctuation seen between s0 and n0
        pb = "0"
        if 0 <= s0 < n0 <= n:
            for k in range(s0 + 1, min(n0, n)):
                if tags[k] in (",", ":", "."):
                    pb = tags[k]
                    break
        return [
            "b", "d=" + depth,
            "s0w=" + s0w, "s0t=" + s0t, "s0wt=" + s0w + "|" + s0t,
            "s1w=" + s1w, "s1t=" + s1t, "s1wt=" + s1w + "|" + s1t, "s2t=" + s2t,
            "n0w=" + n0w, "n0t=" + n0t, "n0wt=" + n0w + "|" + n0t,
            "n1w=" + n1w, "n1t=" + n1t, "n1wt=" + n1w + "|" + n1t, "n2t=" + n2t, "n2w=" + n2w,
            "s0wt_n0wt=" + s0w + s0t + "|" + n0w + n0t, "s0wt_n0w=" + s0w + s0t + "|" + n0w,
            "s0w_n0wt=" + s0w + "|" + n0w + n0t, "s0wt_n0t=" + s0w + s0t + "|" + n0t,
            "s0t_n0wt=" + s0t + "|" + n0w + n0t, "s0w_n0w=" + s0w + "|" + n0w, "s0t_n0t=" + s0t + "|" + n0t,
            "n0t_n1t=" + n0t + "|" + n1t,
            "n0t_n1t_n2t=" + n0t + "|" + n1t + "|" + n2t, "s0t_n0t_n1t=" + s0t + "|" + n0t + "|" + n1t,
            "s1t_s0t_n0t=" + s1t + "|" + s0t + "|" + n0t, "s2t_s1t_s0t=" + s2t + "|" + s1t + "|" + s0t,
            "s1t_s0t=" + s1t + "|" + s0t, "s1w_s0w=" + s1w + "|" + s0w, "s1t_n0t=" + s1t + "|" + n0t,
            "s0t_s0l1t_n0t=" + s0t + "|" + s0l1t + "|" + n0t, "s0t_s0r1t_n0t=" + s0t + "|" + s0r1t + "|" + n0t,
            "s0t_n0t_n0l1t=" + s0t + "|" + n0t + "|" + n0l1t, "s0t_s0l1t_s0l2t=" + s0t + "|" + s0l1t + "|" + s0l2t,
            "s0t_s0r1t_s0r2t=" + s0t + "|" + s0r1t + "|" + s0r2t, "n0t_n0l1t_n0l2t=" + n0t + "|" + n0l1t + "|" + n0l2t,
            "s0l1w=" + s0l1w, "s0r1w=" + s0r1w, "n0l1w=" + n0l1w, "s0l1t=" + s0l1t, "s0r1t=" + s0r1t,
            "n0l1t=" + n0l1t,
            "dist_s0w=" + d + "|" + s0w, "dist_s0t=" + d + "|" + s0t, "dist_n0w=" + d + "|" + n0w,
            "dist_n0t=" + d + "|" + n0t, "dist_s0t_n0t=" + d + "|" + s0t + "|" + n0t,
            "s0v=" + s0v + "|" + s0t, "s0wv=" + s0v + "|" + s0w, "n0v=" + n0v + "|" + n0t,
            "n0wv=" + n0v + "|" + n0w, "pb=" + pb + "|" + s0t + "|" + n0t,
        ]

    @staticmethod
    def valid(stack, b, n):
        v = []
        if b < n:
            v.append(SHIFT)
        if stack and (b < n or len(stack) == 1):
            v.append(LEFT)
        if len(stack) > 1:
            v.append(RIGHT)
        return v

    def parse(self, words, tags):
        """Heads within the sentence (the root points at itself)."""
        n = len(words)
        words = [_norm(w) for w in words]
        heads = [-1] * n
        lefts = [[] for _ in range(n)]
        rights = [[] for _ in range(n)]
        stack, b = [], 0
        while stack or b < n:
            v = self.valid(stack, b, n)
            s = self.model.scores(self.features(words, tags, n, stack, b, heads, lefts, rights))
            a = max(v, key=s.__getitem__)
            b = _apply(a, stack, b, n, heads, lefts, rights)
        return [h if h != n else i for i, h in enumerate(heads)]


def _apply(a, stack, b, n, heads, lefts, rights):
    if a == SHIFT:
        stack.append(b)
        return b + 1
    s0 = stack.pop()
    if a == LEFT:
        heads[s0] = b
        if b < n:
            lefts[b].insert(0, s0)
    else:
        h = stack[-1]
        heads[s0] = h
        rights[h].append(s0)
    return b


# --------------------------------------------------------------------------
# loading and the pipeline

_MODELS = None


def feature_key(f: str) -> int:
    """Stable 32-bit key for a feature name. A handful of stored features share
    a key (merged at build time); an unseen feature matches a stored key about
    once in ten thousand lookups."""
    return zlib.crc32(f.encode("utf-8"))


class Packed:
    """Trained weights as stored (see tools/syntax/pack_binary.py): sorted 32-bit
    feature keys, and per key a run of (class, int16 weight) pairs. Weights
    stay at their integer scale; argmax does not need them divided back."""

    def __init__(self, classes, keys, off, cls, w):
        self.classes = classes
        self.keys, self.off, self.cls, self.w = keys, off, cls, w
        # Feature name -> its weights, looked up once. With few classes a
        # feature's weights are kept as a dense row, so scoring is one column sum.
        self._runs = {}
        self._dense = len(classes) <= 4
        self._zero = (0,) * len(classes)

    MEMO_LIMIT = 20000

    def _run(self, f):
        keys = self.keys
        key = feature_key(f)
        i = bisect_left(keys, key)
        if i < len(keys) and keys[i] == key:
            a, b = self.off[i], self.off[i + 1]
            run = tuple(zip(self.cls[a:b], self.w[a:b]))
        else:
            run = ()
        if self._dense:
            row = [0] * len(self.classes)
            for c, wt in run:
                row[c] += wt
            run = tuple(row) if run else self._zero
        if len(self._runs) >= self.MEMO_LIMIT:
            self._runs.clear()
        self._runs[f] = run
        return run

    def scores(self, feats):
        runs = self._runs
        if self._dense:
            get = runs.get
            rows = [get(f) or self._run(f) for f in feats]
            return [sum(col) for col in zip(*rows)] if rows else list(self._zero)
        s = [0] * len(self.classes)
        for f in feats:
            run = runs.get(f)
            if run is None:
                run = self._run(f)
            for c, wt in run:
                s[c] += wt
        return s


def _read(fh):
    if fh.read(6) != b"PWSYN5":
        raise ValueError(f"{DATA} is not a proseweave syntax model")
    (n,) = struct.unpack("<I", fh.read(4))
    head = json.loads(fh.read(n))
    out = {}
    for m in head["order"]:
        spec = head["models"][m]
        arrs = []
        for code, size in zip("IBBh", spec["sizes"]):
            a = array.array(code)
            a.frombytes(fh.read(size))
            if sys.byteorder == "big" and code not in "B":
                a.byteswap()
            arrs.append(a)
        keys, lens, cls, w = arrs
        off = array.array("I", [0])
        off.extend(itertools.accumulate(lens))          # row lengths -> row offsets
        out[m] = Packed(spec["classes"], keys, off, cls, w)
    return head, out


class Models:
    """Everything in the weight file: the tagger (one or two passes), the
    segmenter, the parser, the coarse-class model and the lemma corrections."""

    def __init__(self, head, m):
        self.tagger = Tagger(m["tagger"], head.get("tagdict"), m.get("tagger2"))
        self.segmenter = Segmenter(m["segmenter"], head.get("seg_features", "full"))
        self.parser = Parser(m["parser"])
        self.upos = m.get("upos")
        self.lemma_fix = head.get("lemma_fix", {})
        self.tok_exc = head.get("tok_exc", {})

    def __iter__(self):             # tagger, segmenter, parser = models()
        return iter((self.tagger, self.segmenter, self.parser))

    def __getitem__(self, k):
        return (self.tagger, self.segmenter, self.parser)[k]


def models():
    """The models, loaded once on first use."""
    global _MODELS
    if _MODELS is None:
        with gzip.open(DATA, "rb") as fh:
            _MODELS = Models(*_read(fh))
    return _MODELS


# --------------------------------------------------------------------------
# coarse classes and lemmas

# Penn tag -> (default Universal Dependencies class, morphological features),
# following the published Penn-to-UD conversion tables.
TAG_MAP = {
    "NN": ("NOUN", {"Number": "Sing"}), "NNS": ("NOUN", {"Number": "Plur"}),
    "NNP": ("PROPN", {"Number": "Sing"}), "NNPS": ("PROPN", {"Number": "Plur"}),
    "VB": ("VERB", {"VerbForm": "Inf"}), "VBD": ("VERB", {"VerbForm": "Fin", "Tense": "Past"}),
    "VBG": ("VERB", {"VerbForm": "Part", "Tense": "Pres", "Aspect": "Prog"}),
    "VBN": ("VERB", {"VerbForm": "Part", "Tense": "Past", "Aspect": "Perf"}),
    "VBP": ("VERB", {"VerbForm": "Fin", "Tense": "Pres"}),
    "VBZ": ("VERB", {"VerbForm": "Fin", "Tense": "Pres", "Number": "Sing", "Person": "3"}),
    "MD": ("AUX", {"VerbType": "Mod"}), "JJ": ("ADJ", {"Degree": "Pos"}), "JJR": ("ADJ", {"Degree": "Cmp"}),
    "JJS": ("ADJ", {"Degree": "Sup"}), "RB": ("ADV", {"Degree": "Pos"}), "RBR": ("ADV", {"Degree": "Cmp"}),
    "RBS": ("ADV", {"Degree": "Sup"}), "WRB": ("ADV", {}), "DT": ("DET", {}), "PDT": ("DET", {}),
    "PRP": ("PRON", {}), "PRP$": ("PRON", {}), "WP": ("PRON", {}), "WP$": ("PRON", {}), "WDT": ("PRON", {}),
    "EX": ("PRON", {}), "IN": ("ADP", {}), "RP": ("ADP", {}), "TO": ("PART", {"VerbForm": "Inf"}),
    "POS": ("PART", {}), "CC": ("CCONJ", {}), "CD": ("NUM", {}), "UH": ("INTJ", {}), "FW": ("X", {}),
    "LS": ("X", {}), "XX": ("X", {}), "ADD": ("X", {}), "AFX": ("ADJ", {}), "SYM": ("SYM", {}),
    "$": ("SYM", {}), "#": ("SYM", {}), "NFP": ("PUNCT", {}), "HYPH": ("PUNCT", {}), "_SP": ("SPACE", {}),
}


class Upos:
    """Coarse class from the Penn tag, the word and its place in the parse:
    whether a 'have' or 'do' is an auxiliary, a 'that' a determiner or a
    pronoun, an 'as' a preposition or a conjunction."""

    @staticmethod
    def features(words, tags, heads, kids, i):
        w, t = _norm(words[i]), tags[i]
        h = heads[i]
        ht = tags[h] if h != i else "!ROOT"
        d = "root" if h == i else ("L" if h < i else "R")
        nt = tags[i + 1] if i + 1 < len(tags) else "!END"
        pt = tags[i - 1] if i else "!START"
        kt = "|".join(sorted({tags[k][:2] for k in kids[i]}))[:24]
        tw = t + "|" + w
        return ["b", "t=" + t, "tw=" + tw, "tw_nt=" + tw + "|" + nt, "tw_pt=" + tw + "|" + pt,
                "tw_ht=" + tw + "|" + ht, "tw_d=" + tw + "|" + d, "tw_ht_d=" + tw + "|" + ht + "|" + d,
                "tw_k=" + tw + "|" + kt, "t_ht_d=" + t + "|" + ht + "|" + d, "t_k=" + t + "|" + kt,
                "hw=" + tw + "|" + (_norm(words[h]) if h != i else "!ROOT")]


def _lemma_tables():
    try:
        from . import text as tk
    except ImportError:             # run outside the package
        from proseweave import text as tk
    return tk.lemma_tables()


def _base_form(pos, tag):
    """The rule lemmatizer's base-form test, over the morphology the tag implies."""
    m = TAG_MAP.get(tag, (None, {}))[1]
    if pos == "noun" and m.get("Number") == "Sing":
        return True
    if pos == "verb" and m.get("VerbForm") == "Inf":
        return True
    if pos == "verb" and m.get("VerbForm") == "Fin" and m.get("Tense") == "Pres" and "Number" not in m:
        return True
    if pos == "adj" and m.get("Degree") == "Pos":
        return True
    return m.get("VerbForm") == "Inf" or m.get("Degree") == "Pos"


def rule_lemma(word, tag, pos):
    """Rule lemmatizer: base forms as themselves, then exceptions, then suffix
    rules whose output is a known word, then the out-of-vocabulary output."""
    univ = pos.lower()
    if univ in ("", "eol", "space"):
        return word.lower()
    t = _lemma_tables()
    index = t["lemma_index"].get(univ)
    # A verb tagged as a base form (VB, VBP) is trusted only if it is a known verb
    # base; a tagging slip on an inflected form ("upheld" as VBP) goes to the
    # exceptions and rules below, whose answer is kept only if it is a known verb.
    slip = False
    if _base_form(univ, tag):
        if univ != "verb" or not index or word.lower() in index:
            return word.lower()
        slip = True
    exc = t["lemma_exc"].get(univ, {})
    rules = t["lemma_rules"].get(univ, [])
    if not index and not exc and not rules:
        return word if univ == "propn" else word.lower()
    index = index or ()
    low = word.lower()
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
    for form in exc.get(low, []):
        if form not in forms:
            forms.insert(0, form)
    if not forms:
        forms = oov or [low]
    if slip and forms[0] not in index and forms[0] not in exc.get(low, ()):
        return low
    return forms[0]


def lemma(word, tag, pos, fix=None):
    fix = models().lemma_fix if fix is None else fix
    got = fix.get(f"{word.lower()}|{pos}|{tag}")
    return got if got is not None else rule_lemma(word, tag, pos)


@functools.lru_cache(maxsize=16)
def analyse(text: str) -> tuple:
    """annotate_text, cached: every module reading the same text shares one parse."""
    return tuple(annotate_text(text))


def annotate_text(text: str) -> list:
    """Tokens with tag, sentence starts, heads, coarse class and lemma."""
    m = models()
    return _classes_and_lemmas(annotate(tokenize(text), m.tagger, m.segmenter, m.parser), m)


def _classes_and_lemmas(toks, m):
    idx = [i for i, t in enumerate(toks) if not t.is_space]
    pos_of = {i: k for k, i in enumerate(idx)}
    words = [toks[i].text for i in idx]
    tags = [toks[i].tag for i in idx]
    heads = [pos_of.get(toks[i].head, k) for k, i in enumerate(idx)]
    kids = [[] for _ in idx]
    for k, h in enumerate(heads):
        if h != k:
            kids[h].append(k)
    for k, i in enumerate(idx):
        t = toks[i]
        if m.upos is not None:
            s = m.upos.scores(Upos.features(words, tags, heads, kids, k))
            t.pos = m.upos.classes[max(range(len(s)), key=s.__getitem__)]
        else:
            t.pos = TAG_MAP.get(t.tag, ("PUNCT" if not t.text[:1].isalnum() else "X",))[0]
        t.lemma = lemma(t.text, t.tag, t.pos, m.lemma_fix)
    for t in toks:
        if t.is_space:
            t.pos, t.lemma = "SPACE", t.text
    return toks


def annotate(toks, tagger, segmenter, parser, starts=None):
    """Fill tag, sent_start and head on a token list in place."""
    margins = []
    tags = tagger.tag([t.text for t in toks], margins)
    for t, g, mg in zip(toks, tags, margins):
        t.tag, t.margin = g, mg
    words = [i for i, t in enumerate(toks) if not t.is_space]
    if not words:
        return toks
    if starts is None:
        seq = []
        for k, i in enumerate(words):
            prev = words[k - 1] if k else -1
            gap = "".join(toks[j].text for j in range(prev + 1, i))
            seq.append((toks[i].text, "n" + str(min(gap.count("\n"), 2)) if gap else
                        ("s" if prev >= 0 and toks[prev].ws else "0")))
        starts = segmenter.starts(seq, [toks[i].tag for i in words])
    sents, cur = [], []
    for k, i in enumerate(words):
        if starts[k] and cur:
            sents.append(cur)
            cur = []
        cur.append(i)
    sents.append(cur)
    for idx in sents:
        hs = parser.parse([toks[i].text for i in idx], [toks[i].tag for i in idx])
        toks[idx[0]].sent_start = True
        for k, h in enumerate(hs):
            toks[idx[k]].head = idx[h]
    # a line break or extra space hangs off the token before it
    for i, t in enumerate(toks):
        if t.is_space:
            t.head = i - 1 if i else i
    return toks


def parse(text: str) -> list:
    m = models()
    return annotate(tokenize(text), m.tagger, m.segmenter, m.parser)


def dep_distances(toks, stop_words) -> list:
    """|head - dependent| over alphabetic, non-stop tokens that are not roots."""
    return [abs(i - t.head) for i, t in enumerate(toks)
            if t.text.isalpha() and t.text.lower() not in stop_words and t.head != i]
