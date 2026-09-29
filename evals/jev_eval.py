#!/usr/bin/env python3
"""Measure voice match by authorship discrimination, with ground truth.

The claim "this sounds like the author" looks subjective until you make it a
classification problem with a correct answer:

    Hold out writing the generator never saw. Put a candidate passage beside a
    real held-out one, in random order, and ask a calibrated judge which the
    author wrote. If the candidate is a good voice match the judge lands near
    chance. If it is not, the judge picks the real one.

P(judge picks the real passage) is then a score where 0.50 means indistinguishable.
Crucially the target is **two-sided**: 0.06 is as bad as 0.94, just failing in the
other direction.

That is not a refinement, it is the whole point, and it was learned the hard way.
The first version of this scored one-sided and read "lower is better." Measured
that way, two rewrites came in at 0.06 and 0.04 -- a judge shown the author's own
held-out writing beside a generated passage picked the *generated* one as genuinely
authored, almost every time. Generated prose is not merely imitating the voice; it
is more consistently that voice than the person is, because a model reaches for the
most typical version of a style while a real writer is uneven. One-sided scoring
rewards exactly that caricature. So the metric reported is:

    fidelity_error = |p - 0.5| * 2       0.0 perfect, 1.0 worst

with the direction named, because the two failures need opposite fixes: overshoot
means dial the markers down, undershoot means the voice was not captured.

Two guards make the number mean something:

- **Order is randomized per trial** and the mapping is kept out of the judge's
  view, so a judge that always says "A" scores chance rather than winning.
- **A control trial** pits two real held-out passages against each other. The
  judge should score ~0.5 there by construction. If it does not, the judge is
  biased or the passages differ by topic rather than voice, and the main result
  cannot be trusted. The control is run first and reported alongside.

Also scores decomposed voice dimensions, asked as separate parallel questions,
because a single "does this sound like them" score hides which part is wrong.

Judge: TypeSafe Jev (System One). Needs TYPESAFE_API_KEY in the environment or
in a .env beside the skill. Standard library only -- no SDK.

Exit status: 0 completed, 1 judge unavailable, 2 usage error.
"""

import argparse
import json
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

# Decomposed voice dimensions. Each is one well-scoped judgement, per Jev's
# guidance that questions asking for several factors at once get unreliable.
# Weighting stays in code, not in a prompt, so it can be changed without
# rewriting instructions.
DIMENSIONS = {
    "register": ("Does the candidate passage match the reference samples' level of "
                 "formality and word choice?",
                 ["not at all - clearly a different register",
                  "roughly similar but noticeably off",
                  "closely matched"]),
    "rhythm": ("Does the candidate match the reference samples' sentence rhythm - "
               "how much sentence length varies, and how sentences open?",
               ["not at all - uniform or differently paced",
                "roughly similar",
                "closely matched"]),
    "stance": ("Does the candidate match how the reference author positions "
               "themselves - owning mistakes, hedging, stating opinions, "
               "addressing the reader?",
               ["not at all", "roughly similar", "closely matched"]),
    "concreteness": ("Does the candidate match the reference samples' level of "
                     "specificity - named things and real numbers versus abstract "
                     "summary?",
                     ["much vaguer or much denser than the author",
                      "roughly similar", "closely matched"]),
}


def load_key():
    """TYPESAFE_API_KEY, else the key `weave.py setup` stored, else a .env (proseweave's lookup)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor"))
    from proseweave.jev import load_key as _shared
    return _shared()


def ask(key, state, questions, retries=4):
    body = json.dumps({"state": state, "model": MODEL,
                       "questions": questions}).encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    delay = 1.5
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            detail = e.read()[:300].decode("utf-8", "replace")
            raise SystemExit(f"judge error {e.code}: {detail}")
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise SystemExit(f"judge unreachable: {e}")
    raise SystemExit("judge: retries exhausted")


def clip(t, limit=2600):
    t = re.sub(r"\n{3,}", "\n\n", t.strip())
    return t if len(t) <= limit else t[:limit] + "\n[...]"


def trial(key, refs, real, candidate, rng):
    """One forced choice. Returns P(judge picked the genuinely-authored passage)."""
    real_is_a = rng.random() < 0.5
    a, b = (real, candidate) if real_is_a else (candidate, real)
    state = (f"REFERENCE WRITING, known to be by the author:\n\n{clip(refs)}\n\n"
             f"---\n\nPASSAGE A:\n\n{clip(a)}\n\n---\n\nPASSAGE B:\n\n{clip(b)}")
    q = {"same_author": {
        "type": "choice",
        "instructions": ("One of these two passages was written by the same person "
                         "who wrote the reference writing. The other was not. Judge "
                         "on voice - rhythm, register, stance, habits - not on "
                         "subject matter, since both may discuss the same topics. "
                         "Which passage is by the reference author?"),
        "criteria": {"passage_a": "Passage A is by the reference author",
                     "passage_b": "Passage B is by the reference author"}}}
    ans = ask(key, state, q)["answers"]["same_author"]
    probs = ans.get("probabilities", {})
    p_real = probs.get("passage_a", 0.0) if real_is_a else probs.get("passage_b", 0.0)
    return {"p_real": round(float(p_real), 4),
            "confidence": ans.get("confidence"),
            "real_was": "A" if real_is_a else "B",
            "picked": ans.get("choice")}


def fidelity(mean_p):
    """Two-sided: distance from chance, and which way it failed."""
    err = round(abs(mean_p - 0.5) * 2, 3)
    if err < 0.25:
        direction = "indistinguishable"
    elif mean_p < 0.5:
        direction = "OVERSHOOT - reads as more the author than the author"
    else:
        direction = "UNDERSHOOT - voice not captured"
    return err, direction


def score_dimensions(key, refs, candidate):
    state = (f"REFERENCE WRITING by the author:\n\n{clip(refs)}\n\n"
             f"---\n\nCANDIDATE PASSAGE:\n\n{clip(candidate)}")
    qs = {k: {"type": "score", "instructions": instr, "criteria": crit}
          for k, (instr, crit) in DIMENSIONS.items()}
    ans = ask(key, state, qs)["answers"]
    out = {}
    for k in DIMENSIONS:
        a = ans.get(k, {})
        top = len(DIMENSIONS[k][1]) - 1
        out[k] = {"score": a.get("score"), "normalized": round(a.get("score", 0) / top, 3),
                  "confidence": a.get("confidence")}
    return out


def read(p):
    return Path(p).read_text(encoding="utf-8", errors="replace")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jev_eval.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refs", nargs="+", required=True,
                    help="author samples the generator WAS allowed to see")
    ap.add_argument("--heldout", nargs="+", required=True,
                    help="real author writing the generator never saw")
    ap.add_argument("--candidate", action="append", required=True,
                    metavar="LABEL=PATH", help="repeatable, e.g. with_skill=out.md")
    ap.add_argument("--trials", type=int, default=4,
                    help="forced choices per candidate (order reshuffled each time)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    key = load_key()
    if not key:
        print("no TYPESAFE_API_KEY in environment or .env", file=sys.stderr)
        return 1

    rng = random.Random(a.seed)
    refs = "\n\n---\n\n".join(read(p) for p in a.refs)
    held = [read(p) for p in a.heldout]
    cands = {}
    for spec in a.candidate:
        label, _, path = spec.partition("=")
        cands[label] = read(path)

    report = {"control": None, "candidates": {}}

    # Control first: real vs real. Anything far from 0.5 invalidates the rest.
    if len(held) >= 2:
        ctrl = [trial(key, refs, held[0], held[1], rng) for _ in range(a.trials)]
        ps = [t["p_real"] for t in ctrl]
        report["control"] = {"mean_p": round(statistics.mean(ps), 3), "trials": ctrl}

    for label, text in cands.items():
        ts = [trial(key, refs, held[i % len(held)], text, rng)
              for i in range(a.trials)]
        ps = [t["p_real"] for t in ts]
        mp = statistics.mean(ps)
        err, direction = fidelity(mp)
        report["candidates"][label] = {
            "mean_p_judge_picks_real": round(mp, 3),
            "fidelity_error": err,
            "direction": direction,
            "stdev": round(statistics.pstdev(ps), 3) if len(ps) > 1 else 0.0,
            "trials": ts,
            "dimensions": score_dimensions(key, refs, text),
        }

    if a.json:
        print(json.dumps(report, indent=2))
        return 0

    print("Authorship discrimination. p=0.50 is indistinguishable; fidelity_error")
    print("is two-sided |p-0.5|*2, so overshoot and undershoot both count as failure.")
    if report["control"]:
        c = report["control"]["mean_p"]
        flag = "ok" if 0.3 <= c <= 0.7 else "BIASED - main result unreliable"
        print(f"\n  control (real vs real): {c:.2f}   [{flag}]")
    print()
    for label, r in report["candidates"].items():
        print(f"  {label:<16} p={r['mean_p_judge_picks_real']:.2f} "
              f"(sd {r['stdev']:.2f}, n={a.trials})  "
              f"fidelity_error={r['fidelity_error']:.2f}")
        print(f"  {'':<16} {r['direction']}")
        d = r["dimensions"]
        cells = "  ".join(f"{k}={d[k]['normalized']:.2f}" for k in DIMENSIONS)
        print(f"  {'':<16} voice dimensions (1.00 = matched): {cells}")
        print()
    print("  fidelity_error 0.0 is perfect. Dimensions are independent parallel")
    print("  judgements, not a composite - read them separately. Note that a high")
    print("  dimension score with a high fidelity_error means the markers were hit")
    print("  too hard: matched on every axis, and therefore a caricature.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
