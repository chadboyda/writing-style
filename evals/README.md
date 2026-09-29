# Eval suite

Four test cases, each run twice — once with the skill, once without — so the
numbers say something about the skill rather than about the model.

```bash
# 1. build fixtures (self-contained; no Slack/Gmail/Drive needed)
python3 evals/fixtures/make_fixtures.py <workspace>/fixtures

# 1b. create run dirs holding ONLY each eval's declared files
python3 evals/setup_runs.py <workspace>/iteration-N --fixtures <workspace>/fixtures

# 2. run the 8 agents (4 evals x with_skill/without_skill), saving each
#    deliverable to <workspace>/iteration-N/eval-<id>/<config>/outputs/output.md

# 3. grade
python3 evals/grade.py <workspace>/iteration-N --fixtures <workspace>/fixtures

# 4. aggregate + view
python3 -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name writing-style
python3 eval-viewer/generate_review.py <workspace>/iteration-N \
    --benchmark <workspace>/iteration-N/benchmark.json --static <workspace>/review.html
```

Steps 2 and 4 use scripts from the `skill-creator` skill.

## The four cases

| Eval | Tests | Why it exists |
| --- | --- | --- |
| `voice-match-from-git` | Finds `git log --author`, matches commit voice | The core retrieval path on a terminal surface |
| `humanize-preserving-habits` | Strips AI tells **while keeping** em dashes and bold | The merge test — see below |
| `no-samples-fallback` | Composes with nothing retrievable | Must not fabricate sources or claim to have read samples |
| `over-correction-guard` | Leaves an already-good draft alone | Catches over-correction by a generic de-slopping pass |

`humanize-preserving-habits` is the one that matters. The fixture author's (synthetic)
Slack history runs em dashes at ~20/1k and uses bold labels. A naive de-slopping
pass strips both, which removes the author along with the machine. The assertions
check for tell removal *and* habit survival, so an over-eager rewrite fails.

`over-correction-guard` is its mirror: a draft that is already clean and already
in voice, to catch a skill that cannot leave well enough alone.

## Fixtures

`make_fixtures.py` builds a real git repo with 8 commits in a distinctive voice,
plus Slack samples, an AI-slopped draft, and a clean in-voice draft. Nothing
depends on a live connector, so the suite runs anywhere and is reproducible.

## What iteration 1 found

The suite's first real value was catching three miscalibrations in this repo,
not in the model:

1. **`em_dash` floor was 6.0/1k.** The fixture author wrote at 31/1k in the fixtures of that iteration. A floor
   that flags a real writer for having a style is the exact failure the baseline
   rule exists to prevent. Raised to 14.0.
2. **Grader assumed "once-over" meant a revised draft.** Both runs correctly
   returned review notes instead, and got marked down for it. Now detects
   review vs revision mode from second-person density.
3. **Two assertions were regexes over semantics** ("advises against a rewrite").
   Rewritten as structural checks, with the genuinely subjective part left for a
   human.
4. **Fixtures were copied into every run directory.** This one was caught by the
   eval agents themselves. The no-samples case had a full author corpus sitting in
   it, so it tested nothing it claimed to; the humanize case had the reference
   answer next to the input. Both agents noticed and said so — but an eval whose
   validity rests on the agent declining to read what you handed it is not an
   eval. `setup_runs.py` now enforces the `files` contract, and those two cases
   were re-run.
5. **The skill compressed a Q3 update to 70 words.** The most important finding,
   and it only surfaced once the contamination above was cleared. SKILL.md had
   25 patterns of "remove this" plus a detector to run last, and almost no
   counter-pressure to keep substance — and the shortest text always scans
   cleanest. The rewrite dropped the customer names, the deploy timing and the
   open-items list, scoring 6/9 against the baseline's 9/9: **actively worse than
   no skill at all.** Fixed with a "Subtraction, not compression" section in the
   final pass — but the first version of that fix was wrong. It said "match the
   author's scale," which is a word-count target, and word-count targets invite
   padding. The agent's own report showed the 70-word output had a defensible
   reason: the source draft held only three facts, and it *refused* to import the
   specifics from `slack-history.md` under the carry-voice-not-content rule. The
   corrected guidance treats length as a symptom to investigate rather than a
   target, and resolves the underlying ambiguity explicitly (see below).
   Trajectory across three runs: 70w (refused import) → 179w (silent import) →
   139w (imports, flagged).
5b. **"Voice, not content" is ambiguous when the samples cover the same work.**
   The draft says "robust deduplication logic"; the author's own Slack post names
   the millisecond-collision root cause and the two affected customers. Using
   those is grounding, not invention — but they may be stale, and the skill can't
   verify. SKILL.md now permits the import with two conditions: only for details
   the draft already gestures at, and the reply must name what was pulled forward
   and from where. A length floor in the eval encoded the same error and was
   removed; substance is checked by item coverage instead.
6. **Five assertion corrections across one iteration.** Worth its own note. Each
   time an output looked wrong, the measurement was wrong: a floor stricter than
   human prose, a mode assumption, two regexes over semantics, and finally a
   substance check that demanded the rewrite import facts from the author's
   history — grading the skill for violating its own "carry voice, not content"
   rule. Writing honest assertions for subjective writing tasks is harder than
   writing the skill.

Assertion counts are not a score to maximize. When an output looks wrong but
reads right, suspect the assertion first.

## Measured against the guide's own protocol

`references/purpose-led-cadence.md` prescribes how to evaluate a guidance change.
This suite does not yet meet it, and the gaps are worth naming rather than
discovering later:

| The guide asks for | Status |
| --- | --- |
| Compare with and without, comparable conditions | Done — that is the with_skill/without_skill split |
| False-positive checks where repetition genuinely helps | Partly — `over-correction-guard` is exactly this, but it is one case |
| Material the guidance was **not** developed around | Not done — one author persona, and the cadence guide was developed against a book this suite never touches |
| Concealed version labels, varied order | Not done — the grader knows which config it is reading |
| Ties and mixed outcomes allowed | Not done — assertions are binary pass/fail |
| Accuracy, completeness, usefulness, voice, readability judged separately | Not done — collapsed into one pass rate |
| Automated judge compared against human decisions, disagreements reported | Not done — no human review pass has been run |

The last one matters most. A pass rate here says the outputs satisfied assertions
a model wrote; it does not say a reader preferred them. `review.html` exists so a
human can disagree, and until someone does, treat the numbers as a regression
tripwire rather than evidence of quality.

## Known gaps

- **No timing or token data.** The runner in use did not surface
  `total_tokens`/`duration_ms` per run, so those benchmark columns read 0.
- **Single run per cell.** No variance estimate; a flaky eval would not show up.
- **One author persona.** Voice matching is only tested against one baseline.
- **No long-form coverage.** The four cases are all short-form. The cadence guide
  governs essays, reports and chapters — multi-section structure, cross-section
  repetition, whether a section earns its place — and none of that is tested.
  A smoke test (`smoke-longform/`) confirms the guide is read and applied, which
  is not the same as confirming it helps.

  What the smoke test actually established, on a planted five-section report:
  the reference load order held (SKILL.md, then writing-best-practices, then
  purpose-led-cadence *before composing*, then ai-tells for the final pass);
  a section-contribution map was built before any prose was touched; the planted
  duplicate was found and argued from the draft's own heading ("showed the same
  thing"); and the second case was **kept** for a stated boundary reason rather
  than cut, which is the behaviour the guide asks for and the opposite of what a
  de-duplication rule would do. It also flagged its own inferences instead of
  inventing around them.

  What it did not establish: that any of this produces a better report. One run,
  no baseline, and the flaws were planted by the same person reading the result.

  One cost worth watching: that run loaded three reference files for a 218-word
  document. Progressive disclosure is supposed to prevent exactly that. Section
  count alone may be the wrong trigger for the cadence guide, but one data point
  is not enough to retune on — note it, and see whether it recurs.
- **Mixed provenance in iteration 1.** Evals 1 and 2 were re-run under enforced
  file scoping; evals 0 and 3 were not, having used only sources their (corrected)
  declarations allow.
