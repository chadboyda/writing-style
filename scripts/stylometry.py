#!/usr/bin/env python3
"""Measure prose rhythm and lexical range, against the author's own baseline.

Companion to check_ai_tells.py. That script counts patterns that look
machine-made; this one measures the shape of the prose itself -- how much
sentence length actually varies, how wide the vocabulary is, whether sentences
keep opening the same way. Sameness is the signal it is built to find, because
uniform rhythm is what a generator produces and what a tired draft drifts toward.

    profile  Measure an author's natural ranges from real samples.
    compare  Measure a draft and report where it sits against that profile.

These numbers locate passages to reread. They do not score writing. There is no
target here for a reading grade, a sentence-length average, a short/long ratio
or a paragraph quota -- a draft that hits a number is not thereby good, and
editing toward one produces exactly the evenness this is meant to catch. Read
what gets flagged; keep what is doing real work.

Pure standard library. Optional extras (wordfreq) light up if installed and are
never required.

Exit status: 0 nothing notable, 1 something worth rereading, 2 usage error.
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

SENT_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]*\s+")
WORD = re.compile(r"\b[\w'-]+\b")

try:                                   # optional: word-rarity signal
    from wordfreq import zipf_frequency
    HAVE_WORDFREQ = True
except ImportError:
    HAVE_WORDFREQ = False

# The beat: stressed syllables, from the vendored proseweave. Optional so this
# script still runs from a copy without vendor/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor"))
try:
    from proseweave import cadence
    HAVE_BEAT = True
except Exception:                      # noqa: BLE001 - any import failure means "off"
    HAVE_BEAT = False


def prepare(raw):
    """Strip frontmatter, fenced code, inline code, and quoted material."""
    t = re.sub(r"\A---\n.*?\n---\n", "", raw, flags=re.S)
    t = re.sub(r"^```.*?^```", "", t, flags=re.S | re.M)
    t = re.sub(r"`[^`\n]+`", " ", t)
    t = re.sub(r"^\s*>.*$", "", t, flags=re.M)      # quotes aren't the author's
    t = re.sub(r"^#{1,6}\s.*$", "", t, flags=re.M)  # headings aren't sentences
    return t


def sentences(text):
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        if not para:
            continue
        for s in SENT_SPLIT.split(para):
            s = s.strip()
            if len(WORD.findall(s)) >= 2:
                out.append(s)
    return out


def paragraphs(text):
    return [p for p in (" ".join(x.split()) for x in re.split(r"\n\s*\n", text))
            if len(WORD.findall(p)) >= 5]


def mtld(tokens, threshold=0.72):
    """Measure of Textual Lexical Diversity, averaged over both directions.

    Reported instead of a raw type-token ratio because TTR falls as a text gets
    longer, which makes two drafts of different lengths incomparable. MTLD does
    not have that problem at length -- but it is badly unstable below roughly a
    hundred tokens, where a text that never crosses the threshold divides by a
    near-zero factor count and reports an absurdly high score. Short messages
    therefore get no score at all rather than a misleading one, which means this
    measure simply does not apply to most Slack posts and commit messages.
    """
    if len(tokens) < 100:
        return None

    def run(seq):
        # The position counter resets with each factor. Dividing by the global
        # index instead collapses TTR permanently after the first reset, so every
        # later token scores as its own factor and MTLD pins to ~1.0 regardless of
        # the text. That bug is invisible on a short sample and obvious the moment
        # a real essay is measured.
        factors, seen, count = 0, set(), 0
        for tok in seq:
            count += 1
            seen.add(tok)
            if len(seen) / count <= threshold:
                factors += 1
                seen.clear()
                count = 0
        if count:
            factors += (1 - len(seen) / count) / (1 - threshold)
        return len(seq) / max(factors, 1e-9)

    return round((run(tokens) + run(tokens[::-1])) / 2, 1)


def cv(values):
    """Coefficient of variation: spread relative to size, so a 40-word-sentence
    writer and a 12-word-sentence writer are on the same scale."""
    if len(values) < 3:
        return None
    m = statistics.mean(values)
    return None if m == 0 else round(statistics.pstdev(values) / m, 3)


def repeated_openings(sents, n=2):
    """Share of sentences whose first n words repeat an earlier opening.

    The guide calls these interchangeable openings. They are invisible sentence
    by sentence and obvious once counted.
    """
    if len(sents) < 4:
        return None, []
    keys = [" ".join(WORD.findall(s.lower())[:n]) for s in sents]
    counts = {}
    for k in keys:
        if k:
            counts[k] = counts.get(k, 0) + 1
    repeats = sum(c - 1 for c in counts.values() if c > 1)
    worst = sorted([(c, k) for k, c in counts.items() if c > 1], reverse=True)[:3]
    return round(repeats / len(keys), 3), [f"{k!r} x{c}" for c, k in worst]


def flat_runs(lengths, tol=2, min_run=4):
    """Longest run of consecutive sentences all within `tol` words of each other.

    A long flat run is the shape of a passage where every claim arrives with the
    same weight -- the thing that makes prose feel machine-even even when no
    individual sentence is wrong.
    """
    if len(lengths) < min_run:
        return 0
    best = run = 1
    for i in range(1, len(lengths)):
        if abs(lengths[i] - lengths[i - 1]) <= tol:
            run += 1
            best = max(best, run)
        else:
            run = 1
    return best


def measure(raw):
    text = prepare(raw)
    sents = sentences(text)
    paras = paragraphs(text)
    tokens = [w.lower() for w in WORD.findall(text)]
    slen = [len(WORD.findall(s)) for s in sents]
    plen = [len(WORD.findall(p)) for p in paras]
    open_rate, worst = repeated_openings(sents)

    m = {
        "words": len(tokens),
        "sentences": len(sents),
        "paragraphs": len(paras),
        "sent_len_mean": round(statistics.mean(slen), 1) if slen else None,
        "sent_len_cv": cv(slen),
        "para_len_cv": cv(plen),
        "mtld": mtld(tokens),
        "repeated_opening_rate": open_rate,
        "longest_flat_run": flat_runs(slen),
    }
    if HAVE_WORDFREQ and tokens:
        z = [zipf_frequency(t, "en") for t in tokens if t.isalpha()]
        z = [x for x in z if x > 0]
        if z:
            m["zipf_mean"] = round(statistics.mean(z), 2)
    m.update(beat(text, len(tokens)))
    m["_worst_openings"] = worst
    return m


def beat(text, n_words):
    """Where the stressed syllables fall.

    Writers order words so stresses alternate rather than collide: against the
    same words shuffled within each sentence, real prose has fewer adjacent
    stresses in 84% of 108 measured texts. How strongly a writer does this is
    theirs. Profiled on one book and matched against a different book by the
    same author, the beat picked the right author of eight 40% of the time,
    where sentence length, its variation, vocabulary range and openings managed
    18% (chance is 12.5%). Against a three-sample range, clash_rate flags 12% of
    the author's own chunks from another book and 31% of other authors'. The
    share of alternating intervals was measured too and dropped: it barely
    differs between authors. Rates are unsteady on short text, so under 150
    words nothing is reported.
    """
    if not HAVE_BEAT or n_words < 150:
        return {}
    try:
        r = cadence.measure(text)["rhythm"]
    except Exception as e:             # noqa: BLE001 - say so, keep the rest
        print(f"stylometry: beat not measured ({type(e).__name__}: {e})", file=sys.stderr)
        return {}
    b, p = r["beat"], r["phrase"]
    return {k: round(v["value"], 3) for k, v in (
        ("stress_clash_rate", b["clash_rate"]),
        ("stress_lapse_rate", b["lapse_rate"]),
        ("ends_on_stress", b["ending_stressed"]),
        ("final_phrase_weight", p["end_weight"]),
    ) if v and v.get("value") is not None}


# Which direction is worth a look, and how far off the author before we say so.
# Bands are deliberately wide: these are prompts to reread, not thresholds to
# optimize against, and a narrow band would manufacture work.
# With a baseline in hand the question is not "is this flatter than the author"
# but "does this match the author", and that is two-sided. A draft at a third of
# their sentence length is as wrong as one at triple it, and the original
# one-directional checks were silent on the first case. sent_len_mean was
# measured and never checked at all, which let a draft averaging 16 words pass
# against an author averaging 54 with the report reading "nothing notable".
# Ratios are draft/author; anything outside the band is worth a look.
MATCH = {
    "sent_len_mean":        (0.60, 1.70, "sentence length"),
    "sent_len_cv":          (0.55, 1.90, "how much sentence length varies"),
    "para_len_cv":          (0.55, 1.90, "how much paragraph length varies"),
    "mtld":                 (0.70, 1.45, "vocabulary range"),
    # The beat (see beat()). Between authors these rates differ by a few
    # points, not by multiples, so the single-sample bands are narrower.
    "stress_clash_rate":    (0.80, 1.25, "how often stressed syllables collide"),
    "stress_lapse_rate":    (0.75, 1.35, "how often the beat drops out (3+ unstressed in a row)"),
    "ends_on_stress":       (0.75, 1.35, "how often sentences land on a stressed syllable"),
    "final_phrase_weight":  (0.80, 1.25, "how much weight the last phrase of a sentence carries"),
}

CHECKS = {
    "sent_len_cv":          ("low",  0.60, "sentence lengths vary less than this author's"),
    "para_len_cv":          ("low",  0.55, "paragraph lengths are more uniform than usual for them"),
    "mtld":                 ("low",  0.70, "narrower vocabulary range than this author's"),  # noqa: E501
    "repeated_opening_rate": ("high", 1.80, "more sentences open the same way than usual"),
    "longest_flat_run":     ("high", 1.60, "a longer run of same-length sentences than usual"),
}
# With no baseline, absolute values notable in their own right. These are NOT
# invented: they are set against corpus/metrics.json, measured from published
# prose whose craft is widely regarded. Each floor sits just outside that
# corpus's p10/p90, so a draft trips one only by being flatter or more repetitive
# than nearly all of it. Guessed thresholds flag competent writers for having a
# style; measured ones do not. Re-derive with corpus/build_corpus.py.
#
#   observed in the reference corpus (n=10):
#     sent_len_cv           p10 0.53   median 0.65   p90 1.51
#     mtld                  p10 74.3   median 110.7  p90 146.2
#     repeated_opening_rate p10 0.10   median 0.16   p90 0.19
#     longest_flat_run      p10 2      median 3.5    p90 5
FLOORS = {"sent_len_cv": ("low", 0.45), "para_len_cv": ("low", 0.30),
          "mtld": ("low", 60.0),
          "repeated_opening_rate": ("high", 0.25), "longest_flat_run": ("high", 6)}


def do_profile(paths, out):
    """Profile an author. Never drop a sample quietly.

    An earlier version skipped anything under five sentences and said nothing
    about it. Handed three real samples it profiled one, reported a confident
    mean built from a third of the evidence, and the caller wrote faithfully to
    a number that was wrong. Silent loss is worse than a hard error, because the
    output still looks like an answer. Anything skipped is now named and
    counted, and the bar is low enough that ordinary chat messages clear it.
    """
    agg, files, skipped = {}, [], []
    for p in paths:
        m = measure(Path(p).read_text(encoding="utf-8", errors="replace"))
        if m["words"] < 40:
            skipped.append((str(p), m["words"]))
            continue
        files.append({"path": str(p), "words": m["words"], "sentences": m["sentences"]})
        for k, v in m.items():
            if k.startswith("_") or v is None:
                continue
            agg.setdefault(k, []).append(v)
    if skipped:
        print(f"profile: SKIPPED {len(skipped)} of {len(paths)} sample(s), under 40 words:",
              file=sys.stderr)
        for path, w in skipped:
            print(f"  skipped  {path}  ({w} words)", file=sys.stderr)
        print("  the profile below is built WITHOUT them", file=sys.stderr)
    if not files:
        print(f"profile: no usable samples - all {len(paths)} were under 40 words",
              file=sys.stderr)
        return 2
    # Record the observed RANGE as well as the mean. A single author varies far
    # more between pieces than a mean suggests -- three real Slack messages from
    # one person measured 20.9, 27.6 and 98.5 words per sentence. Comparing a
    # draft to the mean of those flags the author's own writing as off-voice.
    # The range is what "sounds like them" actually means.
    prof = {"files": files,
            "metrics": {k: round(statistics.mean(v), 3) for k, v in agg.items()},
            "range": {k: [round(min(v), 3), round(max(v), 3)] for k, v in agg.items()},
            "n_samples": len(files)}
    # A person does not have one voice. Measured on one author, chat messages run
    # 21-28 words per sentence and long-form prose runs 13.4 -- shorter,
    # flatter, narrower vocabulary. Profiled together they produce a band from
    # 13 to 98 that can never flag anything. A range this wide almost always
    # means the samples span registers, and the fix is to profile the register
    # being written, not to widen the band.
    slm = prof["range"].get("sent_len_mean")
    if slm and slm[0] > 0 and slm[1] / slm[0] > 2.5:
        print(f"profile: WARNING - sentence length spans {slm[0]} to {slm[1]} "
              f"({slm[1]/slm[0]:.1f}x).", file=sys.stderr)
        print("  That usually means these samples are from different registers "
              "(chat vs published", file=sys.stderr)
        print("  prose, say). A band that wide will not flag anything. Profile the "
              "register you are", file=sys.stderr)
        print("  actually writing in, separately.", file=sys.stderr)

    blob = json.dumps(prof, indent=2)
    if out:
        Path(out).write_text(blob + "\n", encoding="utf-8")
        print(f"profile: {len(files)} of {len(paths)} sample(s) used, "
              f"{sum(f['words'] for f in files)} words -> {out}")
        for k in ("sent_len_mean", "sent_len_cv", "para_len_cv", "mtld",
                  "repeated_opening_rate", "longest_flat_run", "stress_clash_rate",
                  "stress_lapse_rate", "ends_on_stress"):
            if k in prof["metrics"]:
                print(f"  {k:<24} {prof['metrics'][k]}")
    else:
        print(blob)
    return 0


def do_compare(path, baseline, as_json):
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(
        encoding="utf-8", errors="replace")
    m = measure(raw)
    baseline_obj = json.loads(Path(baseline).read_text(encoding="utf-8")) if baseline else None
    base = (baseline_obj or {}).get("metrics", {})

    notes = []
    # Two-sided, against the author's observed range rather than their mean.
    # Needs at least two samples for a range to mean anything; with one, fall
    # back to a wide band around the single observation and say so.
    rng = (baseline_obj or {}).get("range", {})
    nsamp = (baseline_obj or {}).get("n_samples", 0)
    for key, (lo, hi, label) in MATCH.items():
        v, ref = m.get(key), base.get(key)
        if v is None or not ref:
            continue
        if nsamp >= 2 and key in rng:
            rlo, rhi = rng[key]
            # Margin relative to the bound, not to the span. A span-based margin
            # vanishes as an author's range widens: with 21-98 words per sentence
            # observed, 35% of the span put the floor below zero and nothing could
            # ever be flagged. 15% outside each bound holds at any range width.
            floor, ceil = rlo * 0.85, rhi * 1.15
            if v < floor:
                notes.append({"metric": key, "value": v,
                              "note": f"{label} falls below anything this author does",
                              "detail": f"{v} vs their observed {rlo}-{rhi}"})
            elif v > ceil:
                notes.append({"metric": key, "value": v,
                              "note": f"{label} exceeds anything this author does",
                              "detail": f"{v} vs their observed {rlo}-{rhi}"})
        else:
            r = v / ref
            if r < lo or r > hi:
                side = "below" if r < lo else "above"
                notes.append({"metric": key, "value": v,
                              "note": f"{label} is well {side} the single sample available",
                              "detail": f"{v} vs {ref} ({r:.2f}x) - one sample only, weak signal"})
    for key, (direction, factor, why) in CHECKS.items():
        if base and key in MATCH:
            continue          # already covered two-sided above
        v = m.get(key)
        if v is None:
            continue
        if base.get(key):
            ref = base[key]
            limit = ref * factor
            hit = v < limit if direction == "low" else v > limit
            detail = f"{v} vs their {ref}"
        elif key in FLOORS:
            d2, limit = FLOORS[key]
            hit = v < limit if d2 == "low" else v > limit
            detail = f"{v} vs floor {limit}"
        else:
            continue
        if hit:
            notes.append({"metric": key, "value": v, "note": why, "detail": detail})

    result = {"measured": {k: v for k, v in m.items() if not k.startswith("_")},
              "baseline": bool(base), "look_at": notes}
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        src = path if path != "-" else "<stdin>"
        mode = "vs author baseline" if base else "vs absolute floors (no baseline)"
        print(f"{src}: {m['words']} words, {m['sentences']} sentences, {mode}")
        if not notes:
            print("  nothing notable - rhythm and range sit in normal territory")
        for n in notes:
            print(f"  {n['note']}")
            print(f"     {n['metric']} = {n['detail']}")
            if n["metric"] == "repeated_opening_rate" and m["_worst_openings"]:
                print(f"     most repeated: {', '.join(m['_worst_openings'])}")
        if notes:
            print("  -> passages to reread, not defects. See references/purpose-led-cadence.md")
        if any(n["metric"] == "mtld" for n in notes) and m["words"] < 200:
            print("  (mtld under ~200 words is directional only - the gap is real,"
                  " the absolute numbers are not comparable to published norms)")
        if not HAVE_WORDFREQ:
            print("  (word-rarity signal off: `pip install wordfreq` to enable)")
    return 1 if notes else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="stylometry.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("profile", help="measure an author's ranges from samples")
    p.add_argument("paths", nargs="+")
    p.add_argument("--out")
    c = sub.add_parser("compare", help="measure a draft against a profile")
    c.add_argument("path")
    c.add_argument("--baseline")
    c.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    return do_profile(a.paths, a.out) if a.mode == "profile" else \
        do_compare(a.path, a.baseline, a.json)


if __name__ == "__main__":
    sys.exit(main())
