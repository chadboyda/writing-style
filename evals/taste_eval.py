#!/usr/bin/env python3
"""Measure writing quality by pairwise comparison against a known ordering.

The problem with scoring taste per-dimension is that writing defects are
entangled: an earlier attempt here tried to build degradations that moved exactly
one quality dimension, four of five failed adversarial screening, and the wrong
conclusion was drawn -- that structural quality is unmeasurable. The isolation
requirement was the mistake, not the measurement.

This measures the whole instead. A quality ladder takes a good passage and adds
cumulative damage: rung 0 untouched, rung 4 carrying four defects. The ORDERING
is known by construction, and nothing has to be isolated for that to hold. A
working taste metric must reproduce it.

    calibrate  Run ladders through several judge formulations; report which
               formulations actually recover the known ordering, and how well.
    score      Use a validated formulation to rank real candidates.

Validity is not assumed, it is measured, and a formulation that fails is reported
as failing rather than quietly used:

  rank accuracy   share of pairs ordered correctly (0.5 = coin flip)
  Spearman rho    correlation of fitted strength against true rung order
  adjacent acc    accuracy on neighbouring rungs only -- the hard cases, since
                  rung 0 vs rung 4 is easy and inflates the headline number
  position bias   gap between the two presentation orders; large means the judge
                  is reading position rather than prose

Strengths come from a Bradley-Terry fit over the pairwise probabilities, so a
single latent quality scale is recovered rather than a pile of local votes.

Judge: TypeSafe Jev. Needs TYPESAFE_API_KEY. Standard library only.
"""

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jev_eval import ask, load_key, clip  # noqa: E402

# Competing judge formulations, all asked in ONE call per pair because Jev
# evaluates questions in parallel against the same state. Testing several and
# keeping whichever recovers the ordering is the point: a rubric that sounds
# right and ranks badly is worse than useless, and only the ladder can tell them
# apart.
# Validated against the standard this skill actually serves: prose by writers with
# public craft credibility, against sincere professional content-marketing prose.
# Both poles are real writing on the open web (corpus/manifest.json and a
# five-source content-marketing set whose source list is kept privately).
# Accuracy saturates at 1.00 for every formulation, so
# the discriminator is MARGIN -- how decisively the judge separates them.
#
#   formulation  craft-vs-slop   federal plain-    ornate bad
#                (margin)        language pairs    fiction
#   -------------------------------------------------------------
#   craft            0.98            0.21            0.00
#   specific         0.98            0.21            0.25
#   plain            0.88            0.71            0.25
#   editor           0.76            0.71            0.88
#   reader           0.73            0.36            1.00
#
# An earlier version of this file crowned `editor` on the strength of the middle
# and right columns. That was wrong, and the mistake is worth keeping written
# down: neither of those columns is a taste standard. Federal plain-language
# rewrites optimise for legal comprehension by a general public -- a clarity
# floor. Contest-winning bad fiction is bad by being ORNATE, which is a failure mode
# essentially absent from business prose. Ranking a quality judge by how it
# handles two non-taste standards produced a judge that is mediocre at taste.
#
# `craft` is the most decisive judge of the distinction that matters here, and its
# blind spot is known and narrow: it partly rewards ornateness, so it should not
# be trusted alone on purple prose. That is what the stylometry checks and the
# tell catalogue are for. The answer to a known blind spot is a guard, not
# discarding the instrument that is otherwise best at the job.
DEFAULT_FORMULATION = "craft"
GENERAL_PURPOSE = ("craft", "specific")     # highest margin on craft-vs-slop
ORNATENESS_GUARD = "editor"                 # cross-check when prose runs florid

FORMULATIONS = {
    "plain": "Which passage is better written?",
    "reader": ("Which passage would a careful, busy reader find more useful and "
               "easier to trust?"),
    "craft": ("Which passage shows more craft: emphasis that the surrounding text "
              "has earned, claims sitting next to the reasons that make them "
              "intelligible, certainty proportional to the evidence, and an ending "
              "that does work rather than performing a close?"),
    "editor": ("You are an experienced editor. Which of these two drafts would you "
               "publish with fewer changes?"),
    "specific": ("Which passage is more specific and concrete -- naming real things, "
                 "keeping conditions and caveats attached to the claims they "
                 "qualify -- rather than summarising in the abstract?"),
}


def compare(key, a_text, b_text):
    """One pairwise call carrying every formulation. Returns {name: P(A better)}."""
    state = (f"PASSAGE A:\n\n{clip(a_text)}\n\n---\n\nPASSAGE B:\n\n{clip(b_text)}")
    qs = {name: {"type": "choice", "instructions": instr,
                 "criteria": {"passage_a": "Passage A", "passage_b": "Passage B"}}
          for name, instr in FORMULATIONS.items()}
    ans = ask(key, state, qs)
    out = {}
    for name in FORMULATIONS:
        p = ans["answers"].get(name, {}).get("probabilities", {})
        out[name] = float(p.get("passage_a", 0.5))
    return out


def bradley_terry(items, pairs, iters=250):
    """MM algorithm over expected wins. pairs: list of (i, j, p_i_beats_j)."""
    n = len(items)
    idx = {k: i for i, k in enumerate(items)}
    wins = [0.0] * n
    played = [[0.0] * n for _ in range(n)]
    for a, b, p in pairs:
        i, j = idx[a], idx[b]
        wins[i] += p
        wins[j] += 1 - p
        played[i][j] += 1
        played[j][i] += 1
    s = [1.0] * n
    for _ in range(iters):
        new = []
        for i in range(n):
            denom = sum(played[i][j] / (s[i] + s[j]) for j in range(n) if j != i)
            new.append(wins[i] / denom if denom > 0 else s[i])
        m = sum(new) / n
        s = [max(x / m, 1e-9) for x in new]
    return {k: round(math.log(s[idx[k]]), 4) for k in items}


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    if n < 3:
        return None
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 3) if den else None


def null_control(key, ladders):
    """Show a passage against ITSELF. Truth is 0.5 by construction.

    This is the gate the whole method rests on, and it fails loudly: asked to
    choose between a passage and a byte-identical copy, the judge returns 0.75 to
    0.89 in favour of whichever copy sits in slot A. With no real signal it reads
    position and nothing else.

    That does not sink the measurement, because every comparison is run in both
    orders and averaged, which cancels a symmetric bias exactly. It does mean a
    single-order score is worthless, so this control runs first and its result is
    printed next to every headline number. Anyone reusing this harness without
    the order swap should see what they would be measuring.
    """
    out = {}
    for lad in ladders:
        t = next(r["text"] for r in lad["rungs"] if r["level"] == 0)
        raw = compare(key, t, t)
        deb = {f: (raw[f] + (1 - compare(key, t, t)[f])) / 2 for f in [next(iter(FORMULATIONS))]}
        out[lad["source_id"]] = {"single_order": {k: round(v, 3) for k, v in raw.items()},
                                 "debiased_sample": round(list(deb.values())[0], 3)}
    return out


def calibrate(key, ladders, verbose=True):
    per_form = {f: {"correct": 0, "total": 0, "adj_correct": 0, "adj_total": 0,
                    "bias": [], "rhos": []} for f in FORMULATIONS}
    for lad in ladders:
        rungs = sorted(lad["rungs"], key=lambda r: r["level"])
        levels = [r["level"] for r in rungs]
        texts = {r["level"]: r["text"] for r in rungs}
        pairs_by_form = {f: [] for f in FORMULATIONS}
        for a in range(len(levels)):
            for b in range(a + 1, len(levels)):
                la, lb = levels[a], levels[b]
                fwd = compare(key, texts[la], texts[lb])   # lower rung = better
                rev = compare(key, texts[lb], texts[la])
                for f in FORMULATIONS:
                    p_better = (fwd[f] + (1 - rev[f])) / 2   # position-debiased
                    per_form[f]["bias"].append(abs(fwd[f] - (1 - rev[f])))
                    pairs_by_form[f].append((la, lb, p_better))
                    ok = p_better > 0.5
                    per_form[f]["correct"] += ok
                    per_form[f]["total"] += 1
                    if lb - la == 1:
                        per_form[f]["adj_correct"] += ok
                        per_form[f]["adj_total"] += 1
        for f in FORMULATIONS:
            st = bradley_terry(levels, pairs_by_form[f])
            rho = spearman([-l for l in levels], [st[l] for l in levels])
            if rho is not None:
                per_form[f]["rhos"].append(rho)
        if verbose:
            print(f"  scored ladder {lad['source_id']}", file=sys.stderr)

    out = {}
    for f, d in per_form.items():
        out[f] = {
            "rank_accuracy": round(d["correct"] / max(d["total"], 1), 3),
            "adjacent_accuracy": round(d["adj_correct"] / max(d["adj_total"], 1), 3),
            "mean_spearman": round(statistics.mean(d["rhos"]), 3) if d["rhos"] else None,
            "position_bias": round(statistics.mean(d["bias"]), 3) if d["bias"] else None,
            "comparisons": d["total"],
        }
    return out


def verdict(m):
    """A formulation is usable only if it beats chance on the HARD cases."""
    if m["mean_spearman"] is None:
        return "no data"
    if m["adjacent_accuracy"] >= 0.75 and m["mean_spearman"] >= 0.9 and m["position_bias"] < 0.35:
        return "VALID"
    if m["adjacent_accuracy"] >= 0.6 and m["mean_spearman"] >= 0.7:
        return "weak"
    return "FAILS"


def main():
    ap = argparse.ArgumentParser(prog="taste_eval.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("calibrate")
    c.add_argument("--ladders", required=True)
    c.add_argument("--out")
    s = sub.add_parser("score")
    s.add_argument("--formulation", required=True)
    s.add_argument("--candidate", action="append", required=True, metavar="LABEL=PATH")
    a = ap.parse_args()

    key = load_key()
    if not key:
        print("no TYPESAFE_API_KEY", file=sys.stderr)
        return 1

    if a.mode == "calibrate":
        lads = json.loads(Path(a.ladders).read_text())
        lads = lads["ladders"] if isinstance(lads, dict) else lads
        lads = [l for l in lads if l.get("usable", True)]
        if not lads:
            print("no usable ladders", file=sys.stderr)
            return 2
        null = null_control(key, lads)
        worst = max(max(v["single_order"].values()) for v in null.values())
        print("Null control - a passage against an identical copy, truth is 0.50")
        for sid, v in null.items():
            print(f"  {sid:<12} single-order: " +
                  "  ".join(f"{k}={x:.2f}" for k, x in v["single_order"].items()))
        print(f"  worst single-order reading {worst:.2f}: the judge reads POSITION when")
        print("  signal is absent, so every score below is averaged over both orders.")
        print("  A single-order version of this measurement would be meaningless.")

        res = calibrate(key, lads)
        res["_null_control"] = null
        print(f"\nJudge formulations vs {len(lads)} ladders with known ordering")
        print(f"{'formulation':<12} {'rank':>6} {'adjacent':>9} {'rho':>7} {'posbias':>8}  verdict")
        for f, m in sorted(((k, v) for k, v in res.items() if not k.startswith("_")),
                           key=lambda kv: -(kv[1]["adjacent_accuracy"])):
            print(f"{f:<12} {m['rank_accuracy']:>6.2f} {m['adjacent_accuracy']:>9.2f} "
                  f"{(m['mean_spearman'] if m['mean_spearman'] is not None else 0):>7.2f} "
                  f"{(m['position_bias'] or 0):>8.2f}  {verdict(m)}")
        print("\nadjacent accuracy is the honest number: distinguishing rung 2 from")
        print("rung 3 is the real task. 0.50 is a coin flip.")
        print("\nSCOPE: validated for ranking versions of the SAME passage. Ranking")
        print("different authors against each other is NOT validated -- asked to")
        print("compare two good passages by different writers, these formulations")
        print("disagree with each other (0.12 vs 0.85 on the same pair), because")
        print("there is no true ordering for them to recover.")
        if a.out:
            Path(a.out).write_text(json.dumps(res, indent=2) + "\n")
        return 0

    cands = {}
    for spec in a.candidate:
        lbl, _, path = spec.partition("=")
        cands[lbl] = Path(path).read_text(encoding="utf-8", errors="replace")
    names = list(cands)
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            fwd = compare(key, cands[names[i]], cands[names[j]])[a.formulation]
            rev = compare(key, cands[names[j]], cands[names[i]])[a.formulation]
            pairs.append((names[i], names[j], (fwd + (1 - rev)) / 2))
    st = bradley_terry(names, pairs)
    print(f"Quality ranking, formulation '{a.formulation}' (higher is better)")
    for k, v in sorted(st.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<18} {v:+.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
