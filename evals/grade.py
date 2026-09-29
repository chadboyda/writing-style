#!/usr/bin/env python3
"""Grade eval outputs against the assertions in evals.json.

Most assertions here are mechanically checkable, so they get checked rather than
eyeballed -- a regex does not get tired on run 8 and does not talk itself into a
pass. The few that need a reader are marked `manual` and left for the viewer.

Usage: grade.py <iteration-dir> [--evals evals.json] [--fixtures DIR]
Writes grading.json into each run directory.
"""
import argparse, difflib, json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCAN = HERE.parent / "scripts" / "check_ai_tells.py"

AI_VOCAB_BAN = ["testament", "pivotal", "underscore", "underscores", "underscoring",
                "myriad", "seamless", "foster", "fostering", "intricate", "delve",
                "showcasing", "robust", "leveraged", "leveraging"]
CHATBOT = [r"I hope this helps", r"Let me know if", r"feel free to",
           r"Would you like me to"]
NEGPAR = [r"not just\b[^.!?\n]{0,60}?\b(?:but|it'?s)", r"not only\b[^.!?\n]{0,60}?\bbut",
          r"not merely\b[^.!?\n]{0,60}?\b(?:but|it'?s)"]
INLINE_BULLET = r"^[ \t]*[-*+][ \t]+\*\*[^*\n]+\*\*:"
PROCESS_LEAK = [r"^#+\s*(?:sources?|references?|changes? made|what i changed)\b",
                r"\bI (?:searched|consulted|reviewed) (?:your|the user's)\b",
                r"^\s*\*\*(?:Sources?|References?|Changes?)\b"]
CLAIM_SAMPLES = [r"\b(?:based on|matching|drawing on|consistent with) your (?:past |previous |prior )?(?:writing|messages|emails|updates|style)\b",
                 r"\bI (?:found|reviewed|read) your (?:past|previous|prior)\b",
                 r"\byour (?:past|previous) (?:writing|messages|updates) show\b"]
FAKE_LINK = r"(?:https?://|/Users/|slack\.com/archives|docs\.google\.com)"


def rx_any(pats, t, flags=re.I | re.M):
    hits = [p for p in pats if re.search(p, t, flags)]
    return hits


def scan_clean(path):
    r = subprocess.run([sys.executable, str(SCAN), "scan", str(path)],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stdout.strip().splitlines()


def lower_ratio(t):
    """Fraction of sentence-ish starts that are lowercase - Dana's signature."""
    starts = re.findall(r"(?:^|(?<=[.!?]\s))([A-Za-z])", t, re.M)
    if not starts:
        return 0.0
    return sum(1 for c in starts if c.islower()) / len(starts)


def grade(eval_id, name, text, path, fixtures):
    """-> list of {text, passed, evidence}. `None` passed = needs a human."""
    out, add = [], lambda t, p, e: out.append(
        {"text": t, "passed": p, "evidence": e})
    words = len(re.findall(r"\b[\w'-]+\b", text))

    if eval_id == 0:
        subj = next((l.strip() for l in text.splitlines() if l.strip()), "")
        subj = re.sub(r"^[`#>*\-\s]+", "", subj).strip().strip("`")
        first = next((c for c in subj if c.isalpha()), "")
        add("Subject line is lowercase (matches all 8 prior commits)",
            bool(first) and first.islower(), f"subject: {subj!r}")
        add("Subject line has no trailing period",
            not subj.endswith("."), f"ends with {subj[-1:]!r}")
        add("Body explains why the bug mattered, not just what changed", None,
            "needs a reader")
        leaks = rx_any(PROCESS_LEAK, text)
        add("Output is the commit message itself, not a report on sources searched",
            not leaks, f"process-leak patterns: {leaks or 'none'}")
        ok, rep = scan_clean(path)
        add("check_ai_tells.py scan exits 0 (no mechanical tells)", ok,
            "; ".join(rep[1:3]) or "clean")

    elif eval_id == 1:
        found = [w for w in AI_VOCAB_BAN if re.search(r"\b" + w + r"\b", text, re.I)]
        add("AI vocabulary removed (testament/pivotal/underscore/myriad/seamless/foster)",
            not found, f"found: {found or 'none'}")
        c = rx_any(CHATBOT, text)
        add("Chatbot sign-off removed", not c, f"found: {c or 'none'}")
        n = rx_any(NEGPAR, text)
        add("Negative parallelism removed", not n, f"found: {n or 'none'}")
        nb = len(re.findall(INLINE_BULLET, text, re.M))
        add("Inline-header bullet list removed or restructured", nb == 0,
            f"{nb} inline-header bullets remain")
        em = text.count("—")
        add("PRESERVES em dashes (Dana's baseline habit at ~31/1k, not a tell for her)",
            em >= 2, f"{em} em dashes ({round(em*1000/max(words,1),1)}/1k)")
        lr, nbold = lower_ratio(text), len(re.findall(r"\*\*[^*\n]+\*\*", text))
        add("PRESERVES lowercase-prose or bold-label habit from her history",
            lr > 0.5 or nbold >= 2,
            f"lowercase-start ratio {lr:.2f}, {nbold} bold spans")
        leaks = rx_any(PROCESS_LEAK, text)
        add("Output is the rewritten draft, not a changelog of edits",
            not leaks, f"process-leak patterns: {leaks or 'none'}")
        # The de-slop pass is pure removal pressure, so the thing most likely to
        # go wrong is not a surviving tell but a vanished fact. Check directly.
        # Check against what the SOURCE DRAFT contained, not against the author's
        # history. The skill's rule is "carry over voice, not content" -- demanding
        # that the rewrite import customer names and dates from slack-history.md
        # would be grading it for breaking that rule.
        subs = {"the dedupe/sync item": r"dedup|sync|duplicat",
                "the retry item": r"retr(?:y|ies)|webhook",
                "the caching/performance item": r"cach|perf|faster|speed"}
        missing = [k for k, rx in subs.items() if not re.search(rx, text, re.I)]
        add("Retains all three items from the source draft (dedupe, retries, caching)",
            not missing, f"missing: {missing or 'none'}")
        # No length floor. It was tried and it rewards padding: a thin source
        # honestly rewritten is short, and a word-count target invites importing
        # detail to fill the gap. Substance is item coverage, above.
        add("Flags any specifics imported from the samples rather than the source", None,
            f"needs a reader ({words} words; source draft is 165)")

    elif eval_id == 2:
        cs = rx_any(CLAIM_SAMPLES, text)
        add("Does not claim to have read or matched the user's past writing",
            not cs, f"found: {cs or 'none'}")
        fl = re.findall(FAKE_LINK, text)
        add("Does not fabricate source links or file paths", not fl,
            f"found: {fl or 'none'}")
        ok, rep = scan_clean(path)
        add("check_ai_tells.py scan exits 0 (no mechanical tells)", ok,
            "; ".join(rep[1:3]) or "clean")
        reason = bool(re.search(r"weekend|saturday|sunday|on[- ]call|off the clock", text, re.I))
        add("States the actual reason (weekend incidents), not vague 'operational excellence'",
            reason, "weekend rationale present" if reason else "no weekend rationale found")

    elif eval_id == 3:
        orig = (fixtures / "q3-draft-clean.md").read_text(encoding="utf-8")
        ratio = difflib.SequenceMatcher(None, orig.split(), text.split()).ratio()

        # "Give it a once-over" is legitimately ambiguous: a revised draft and a
        # review memo are both valid deliverables. Grading a review against
        # "retains the original wording" measures the wrong thing and punishes
        # the better answer, so detect which was produced and grade that.
        review_markers = [r"don'?t rewrite", r"leave it (?:as|alone)", r"reads like you",
                          r"^#+\s*(?:once[- ]over|review|notes|feedback)",
                          r"^\s*(?:draft|current)\s*:", r"^>\s",
                          r"\bsuggest\b", r"\bbefore you post\b", r"\bready to go\b"]
        # The decisive signal is not vocabulary but addressee. A revised Q3 update
        # is a standalone document about the quarter; a review talks TO the author
        # about their draft. Second person is what separates them.
        you = len(re.findall(r"\byou(?:'?re|'?ll|'?ve|r)?\b", text, re.I))
        you_rate = you * 1000.0 / max(words, 1)
        is_review = ratio < 0.4 and (you_rate >= 8.0 or len(rx_any(review_markers, text)) >= 2)

        if is_review:
            # Structural, not lexical: a review that returns no replacement draft
            # has by construction declined to rewrite. Phrasing varies too much
            # ("don't rewrite", "mostly ready to go", "looks good, two edits") for
            # a keyword list to be anything but brittle.
            # Not length-as-proxy-for-restraint: a good review is legitimately
            # longer than the draft, because it explains. What it should not do is
            # balloon. Past roughly 2.5x, a review of a 154-word status update has
            # stopped editing and started rewriting the author's job for them.
            mult = len(text.split()) / max(len(orig.split()), 1)
            add("Review stays proportionate to the draft (under 2.5x its length)",
                mult < 2.5,
                f"{len(text.split())} words vs {len(orig.split())} in the draft ({mult:.1f}x)")
            # The author's habits must survive inside the *suggested replacements*.
            sugg = "\n".join(re.findall(r"^>\s?(.*)$", text, re.M))
            add("PRESERVES em dashes / lowercase style in its suggested replacements",
                (sugg.count("\u2014") > 0 or lower_ratio(sugg) > 0.5) if sugg.strip()
                else True,
                f"{len(sugg.split())} words quoted back, lowercase ratio {lower_ratio(sugg):.2f}"
                if sugg.strip() else "no block suggestions offered")
            # Points get delimited by whatever the writer reached for: a heading,
            # a number, or a bold lead-in opening a paragraph. Count all three.
            n_items = (len(re.findall(r"^#{2,}\s", text, re.M))
                       + len(re.findall(r"^\s*\d+[.)]\s", text, re.M))
                       + len(re.findall(r"^\*\*[^*\n]+\*\*", text, re.M)))
            add("Changes proposed are specific and few, not a full reflow",
                1 <= n_items <= 8, f"{n_items} discrete points raised")
            add("Notes are correct and worth making", None, "needs a reader")
        else:
            add("Revision mode: does not rewrite wholesale - retains majority of original wording",
                ratio >= 0.5, f"token similarity to original: {ratio:.2f}")
            em_o, em_n = orig.count("\u2014"), text.count("\u2014")
            add("PRESERVES em dashes present in the original",
                em_n >= max(1, em_o - 1), f"original {em_o} -> output {em_n}")
            lr_o, lr_n = lower_ratio(orig), lower_ratio(text)
            add("PRESERVES the lowercase prose style of the original",
                lr_n >= lr_o - 0.25, f"original {lr_o:.2f} -> output {lr_n:.2f}")

        newv = [w for w in AI_VOCAB_BAN
                if re.search(r"\b" + w + r"\b", text, re.I)
                and not re.search(r"\b" + w + r"\b", orig, re.I)]
        nb = len(re.findall(INLINE_BULLET, text, re.M))
        add("Does not introduce AI vocabulary or inline-header bullets that were not there",
            not newv and nb == 0, f"new vocab {newv or 'none'}, {nb} inline bullets")
        add("Mode chosen suits the request", None,
            f"graded as {'REVIEW' if is_review else 'REVISION'} (similarity {ratio:.2f}, second-person {you_rate:.1f}/1k)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("iteration")
    ap.add_argument("--evals", default=str(HERE / "evals.json"))
    ap.add_argument("--fixtures", required=True)
    a = ap.parse_args()
    spec = json.loads(Path(a.evals).read_text())
    fixtures, it = Path(a.fixtures), Path(a.iteration)
    rows = []
    for e in spec["evals"]:
        for cfg in ("with_skill", "without_skill"):
            d = it / f"eval-{e['id']}" / cfg
            out = d / "outputs" / "output.md"
            if not out.exists():
                rows.append((e["id"], e["name"], cfg, None, None, "MISSING"))
                continue
            text = out.read_text(encoding="utf-8", errors="replace")
            exps = grade(e["id"], e["name"], text, out, fixtures)
            auto = [x for x in exps if x["passed"] is not None]
            p = sum(1 for x in auto if x["passed"])
            blob = {"eval_id": e["id"], "eval_name": e["name"], "config": cfg,
                    "expectations": exps,
                    "summary": {"passed": p, "failed": len(auto) - p, "total": len(auto),
                                "pass_rate": round(p / len(auto), 4) if auto else 0.0},
                    "auto_passed": p, "auto_total": len(auto),
                    "manual_pending": len(exps) - len(auto)}
            (d / "grading.json").write_text(json.dumps(blob, indent=2) + "\n")
            # skill-creator's aggregator expects <config>/run-N/grading.json with a
            # `summary` block, so mirror it there rather than reshaping our own layout.
            run = d / "run-1"
            run.mkdir(exist_ok=True)
            (run / "grading.json").write_text(json.dumps(blob, indent=2) + "\n")
            rows.append((e["id"], e["name"], cfg, p, len(auto), ""))
    print(f"{'eval':<28} {'config':<15}{'auto':>10}")
    for eid, name, cfg, p, t, err in rows:
        score = err or (f"{p}/{t}" if t else "-")
        print(f"{name:<28} {cfg:<15}{score:>10}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
