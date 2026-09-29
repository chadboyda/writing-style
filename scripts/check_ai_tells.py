#!/usr/bin/env python3
"""Detect mechanical AI writing tells, arbitrated by the author's own baseline.

Two modes:

    profile  Measure an author's natural rate for each pattern from real samples.
    scan     Check a draft. With --baseline, report only what exceeds the
             author's own rate, so genuine habits survive the edit.

Only patterns a regex can count honestly live here. Judgment calls -- manufactured
significance, vague attribution, soulless-but-clean prose -- stay in
references/ai-tells.md for a human or model to weigh.

Exit status: 0 clean, 1 tells found, 2 usage error.
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------- detectors
#
# gated=True   patterns that are plausibly real author habits (em dashes, bold,
#              emoji). Flagged only when the draft outpaces the author's own rate.
# gated=False  patterns that are never an author's voice in a finished document
#              (chatbot artifacts, cutoff disclaimers, sycophancy). Always flagged.
#
# floor        absolute per-1000-word rate used when no baseline is supplied, or
#              as a lower bound so a sample of one em dash can't license twenty.
#              Calibrated against real human prose, not against zero: writers who
#              like em dashes run 25-35/1k, so a floor near 6 flags people for
#              having a style. Without a baseline these are weak signals and the
#              floors are set to catch only the conspicuous cases.

WORD_RE = re.compile(r"\b[\w'-]+\b")

EMOJI_RE = re.compile(
    "[" "\U0001f300-\U0001faff" "\U00002600-\U000027bf" "\U0001f1e6-\U0001f1ff"
    "\U00002190-\U000021ff" "\U00002b00-\U00002bff" "️" "]"
)

AI_VOCAB = [
    "additionally", "align", "aligns", "aligned", "crucial", "delve", "delves",
    "emphasizing", "enduring", "enhance", "enhances", "enhancing", "foster",
    "fostering", "garner", "garnered", "highlighting", "interplay", "intricate",
    "intricacies", "pivotal", "showcase", "showcases", "showcasing", "tapestry",
    "testament", "underscore", "underscores", "underscoring", "vibrant",
    "seamless", "robust", "leverage", "leveraging", "myriad", "realm",
]

PARTICIPLES = [
    "highlighting", "underscoring", "emphasizing", "ensuring", "reflecting",
    "symbolizing", "contributing", "cultivating", "fostering", "encompassing",
    "showcasing", "solidifying", "cementing", "marking",
]

HEDGES = [
    "could", "might", "may", "possibly", "potentially", "perhaps", "arguably",
    "somewhat", "relatively", "fairly", "seemingly", "generally", "typically",
]


def _phrase_re(phrases):
    return re.compile("|".join(r"\b" + p + r"\b" for p in phrases), re.I)


def _count(rx, text):
    return len(rx.findall(text))


DETECTORS = {}


def detector(key, label, gated, floor, min_count=1, unit="per_1k"):
    def wrap(fn):
        DETECTORS[key] = {
            "key": key, "label": label, "gated": gated, "floor": floor,
            "min_count": min_count, "unit": unit, "fn": fn,
        }
        return fn
    return wrap


@detector("em_dash", "em dash density", gated=True, floor=14.0, min_count=4)
def _em_dash(t):
    return t.count("—") + len(re.findall(r"\s--\s", t))


@detector("curly_quotes", "curly quotes / apostrophes", gated=True, floor=12.0, min_count=5)
def _curly(t):
    return sum(t.count(c) for c in "“”‘’")


@detector("emoji", "emoji", gated=True, floor=2.0, min_count=2)
def _emoji(t):
    return _count(EMOJI_RE, t)


@detector("bold", "boldface density", gated=True, floor=12.0, min_count=4)
def _bold(t):
    return _count(re.compile(r"\*\*[^*\n]+\*\*"), t)


@detector("ai_vocab", "AI vocabulary cluster", gated=True, floor=9.0, min_count=3)
def _vocab(t):
    return _count(_phrase_re(AI_VOCAB), t)


@detector("inline_header_bullets", "inline-header bullets", gated=True, floor=3.0, min_count=3)
def _inline(t):
    return len(re.findall(r"^[ \t]*[-*+][ \t]+\*\*[^*\n]+\*\*:", t, re.M))


@detector("title_case_headings", "Title Case Headings", gated=True, floor=2.0, min_count=2)
def _title_case(t):
    hits = 0
    small = {"a", "an", "and", "the", "or", "of", "to", "in", "for", "on", "with",
             "at", "by", "from", "as", "is", "vs"}
    for line in re.findall(r"^#{1,6}[ \t]+(.+)$", t, re.M):
        words = [w for w in WORD_RE.findall(line) if w.lower() not in small]
        if len(words) < 3:
            continue
        capped = sum(1 for w in words[1:] if w[:1].isupper() and not w.isupper())
        if capped >= max(2, int(len(words[1:]) * 0.7)):
            hits += 1
    return hits


@detector("negative_parallelism", "negative parallelism", gated=False, floor=0.0)
def _negpar(t):
    pats = [
        r"\bnot just\b[^.!?\n]{0,60}?\b(?:but|it'?s|its)\b",
        r"\bnot only\b[^.!?\n]{0,60}?\bbut\b",
        r"\bnot merely\b[^.!?\n]{0,60}?\b(?:but|it'?s)\b",
        r"\bisn'?t just\b[^.!?\n]{0,60}?\b(?:it'?s|but)\b",
        r"\bno [a-z]+, no [a-z]+, just\b",
    ]
    return sum(_count(re.compile(p, re.I), t) for p in pats)


@detector("copula_avoidance", "copula avoidance", gated=True, floor=4.0, min_count=3)
def _copula(t):
    pats = [r"\bserves? as\b", r"\bstands? as\b", r"\bboasts?\b",
            r"\brepresents? a\b", r"\bmarks? a\b"]
    return sum(_count(re.compile(p, re.I), t) for p in pats)


@detector("participial_tail", "participial '-ing' tails", gated=True, floor=4.0, min_count=2)
def _participial(t):
    rx = re.compile(r",\s+(?:" + "|".join(PARTICIPLES) + r")\b", re.I)
    return _count(rx, t)


@detector("filler", "filler phrases", gated=True, floor=4.0, min_count=3)
def _filler(t):
    pats = [
        r"\bin order to\b", r"\bdue to the fact that\b", r"\bat this point in time\b",
        r"\bin the event that\b", r"\bhas the ability to\b", r"\bhave the ability to\b",
        r"\bit is important to note that\b", r"\bit should be noted that\b",
        r"\bwhen it comes to\b", r"\bin terms of\b",
    ]
    return sum(_count(re.compile(p, re.I), t) for p in pats)


@detector("hedge_stack", "stacked hedges", gated=False, floor=0.0)
def _hedge_stack(t):
    rx = re.compile(r"\b(?:" + "|".join(HEDGES) + r")\b", re.I)
    hits = 0
    for sent in re.split(r"(?<=[.!?])\s+", t):
        if len(rx.findall(sent)) >= 3:
            hits += 1
    return hits


@detector("chat_artifacts", "assistant correspondence", gated=False, floor=0.0)
def _chat(t):
    pats = [
        r"\bI hope this helps\b", r"\bLet me know if you\b", r"^\s*Certainly[!,]",
        r"^\s*Of course[!,]", r"\bWould you like me to\b", r"\bHere'?s? (?:is )?a\b.{0,40}\bfor you\b",
        r"\bfeel free to (?:ask|reach out|let me know)\b",
    ]
    return sum(_count(re.compile(p, re.I | re.M), t) for p in pats)


@detector("cutoff_disclaimer", "knowledge-cutoff disclaimer", gated=False, floor=0.0)
def _cutoff(t):
    pats = [
        r"\bas of my (?:last )?(?:training|update|knowledge)\b",
        r"\bwhile specific details are (?:limited|scarce|not)\b",
        r"\bbased on (?:the )?available information\b",
        r"\bmy training data\b", r"\bI don'?t have access to real[- ]time\b",
    ]
    return sum(_count(re.compile(p, re.I), t) for p in pats)


@detector("sycophancy", "sycophancy", gated=False, floor=0.0)
def _syco(t):
    pats = [r"\bGreat question\b", r"\bYou'?re absolutely right\b",
            r"\bThat'?s an excellent point\b", r"\bWhat a (?:great|fantastic)\b",
            r"\bExcellent question\b"]
    return sum(_count(re.compile(p, re.I), t) for p in pats)


@detector("generic_uplift", "generic uplift", gated=True, floor=2.0, min_count=1)
def _uplift(t):
    pats = [r"\bthe future looks bright\b", r"\bexciting times\b",
            r"\bjourney toward\b", r"\ba step in the right direction\b",
            r"\bcontinues to thrive\b", r"\bonly time will tell\b"]
    return sum(_count(re.compile(p, re.I), t) for p in pats)


@detector("false_range", "false ranges", gated=True, floor=3.0, min_count=2)
def _false_range(t):
    return _count(re.compile(r"\bfrom\s+(?:the\s+)?\w[\w\s'-]{2,30}?\s+to\s+(?:the\s+)?\w", re.I), t)


# ---------------------------------------------------------------- text prep

def prepare(raw):
    """Strip frontmatter, fenced code, and inline code before measuring.

    Code is not prose; counting backtick-quoted identifiers as AI vocabulary or
    an ASCII art dash as an em dash would make every technical draft look damning.
    """
    text = re.sub(r"\A---\n.*?\n---\n", "", raw, flags=re.S)
    text = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    text = re.sub(r"`[^`\n]+`", " ", text)
    text = re.sub(r"^\s*>.*$", "", text, flags=re.M)  # quoted material isn't the author's
    return text


def measure(raw):
    text = prepare(raw)
    words = len(WORD_RE.findall(text))
    counts = {k: d["fn"](text) for k, d in DETECTORS.items()}
    return {"words": words, "counts": counts}


def rate(count, words):
    return 0.0 if not words else round(count * 1000.0 / words, 2)


# ---------------------------------------------------------------- modes

def do_profile(paths, out):
    total_words, totals, files, skipped = 0, {k: 0 for k in DETECTORS}, [], []
    for p in paths:
        raw = Path(p).read_text(encoding="utf-8", errors="replace")
        m = measure(raw)
        if m["words"] < 25:
            skipped.append((str(p), m["words"]))
            continue
        total_words += m["words"]
        for k, v in m["counts"].items():
            totals[k] += v
        files.append({"path": str(p), "words": m["words"]})
    if skipped:
        # Never drop a sample without saying so: a profile built from part of the
        # evidence still looks like a complete answer to whoever reads it.
        print(f"profile: SKIPPED {len(skipped)} of {len(paths)} sample(s), under 25 words:",
              file=sys.stderr)
        for path, w in skipped:
            print(f"  skipped  {path}  ({w} words)", file=sys.stderr)
    if total_words == 0:
        print("profile: no usable prose found in samples", file=sys.stderr)
        return 2
    prof = {
        "words": total_words,
        "files": files,
        "rates": {k: rate(v, total_words) for k, v in totals.items()},
    }
    blob = json.dumps(prof, indent=2)
    if out:
        Path(out).write_text(blob + "\n", encoding="utf-8")
        print(f"profile: {total_words} words from {len(files)} sample(s) -> {out}")
        for k, r in sorted(prof["rates"].items(), key=lambda kv: -kv[1]):
            if r:
                print(f"  {DETECTORS[k]['label']:<34} {r:>6.2f} /1k")
    else:
        print(blob)
    return 0


def do_scan(path, baseline, as_json):
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(
        encoding="utf-8", errors="replace")
    m = measure(raw)
    words = m["words"]
    base = {}
    if baseline:
        base = json.loads(Path(baseline).read_text(encoding="utf-8")).get("rates", {})

    findings = []
    for k, d in DETECTORS.items():
        c = m["counts"][k]
        if not c:
            continue
        r = rate(c, words)
        if d["gated"]:
            # A lone instance is punctuation, not a pattern; density only
            # means something once there are a few of them.
            if c < d["min_count"]:
                continue
            # Allow the author their own habit, with 1.5x headroom for a short
            # draft's noise, but never below the absolute floor.
            allowed = max(d["floor"], base.get(k, 0.0) * 1.5) if base else d["floor"]
            if r <= allowed:
                continue
            why = (f"{r:.1f}/1k vs author {base.get(k, 0.0):.1f}/1k"
                   if base else f"{r:.1f}/1k vs floor {allowed:.1f}/1k")
        else:
            allowed, why = 0.0, "never author voice"
        findings.append({"key": k, "label": d["label"], "count": c,
                         "rate": r, "allowed": round(allowed, 2), "why": why})

    findings.sort(key=lambda f: -(f["rate"] - f["allowed"]))
    result = {"words": words, "baseline": bool(base), "findings": findings}

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        src = path if path != "-" else "<stdin>"
        mode = "vs author baseline" if base else "vs absolute floors (no baseline)"
        print(f"{src}: {words} words, {mode}")
        if not findings:
            print("  clean - no mechanical tells above threshold")
        for f in findings:
            print(f"  [{f['count']:>3}x] {f['label']:<34} {f['why']}")
            print(f"         -> references/ai-tells.md, pattern '{f['key']}'")
    return 1 if findings else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="check_ai_tells.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("profile", help="measure an author's baseline from samples")
    p.add_argument("paths", nargs="+")
    p.add_argument("--out", help="write profile JSON here (default: stdout)")

    s = sub.add_parser("scan", help="check a draft for tells")
    s.add_argument("path", help="file to scan, or - for stdin")
    s.add_argument("--baseline", help="profile.json from `profile` mode")
    s.add_argument("--json", action="store_true")

    a = ap.parse_args(argv)
    if a.mode == "profile":
        return do_profile(a.paths, a.out)
    return do_scan(a.path, a.baseline, a.json)


if __name__ == "__main__":
    sys.exit(main())
