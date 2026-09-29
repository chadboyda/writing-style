# Measuring voice and taste

The claim "this sounds like them, and it's good" splits into two questions that
have to be measured separately, because a draft can pass one and fail the other.

## Fidelity: measurable, with ground truth

Voice match is an authorship-verification problem, not a matter of opinion.
Hold out writing the generator never saw. Put a candidate beside a real held-out
passage in random order and ask a calibrated judge which the author wrote.

    fidelity_error = |p - 0.5| * 2        0.0 perfect, 1.0 worst

**Two-sided, and that is the whole point.** The first version of this scored
one-sided — lower p is better — and the numbers looked wonderful. Two rewrites
came in at 0.06 and 0.04, meaning a judge shown the author's own held-out prose
beside a generated passage picked the *generated* one as genuinely authored,
almost every time.

That is not success. Generated prose reaches for the most typical version of a
style, while a real writer is uneven, so the machine ends up more consistently
"them" than they are. One-sided scoring rewards that caricature directly.

Run `evals/jev_eval.py`. It needs `TYPESAFE_API_KEY`; it is standard library only.

### The instrument is validated before it is trusted

Two controls, both required:

- **Slop control.** An obviously machine-written draft must be caught. It scores
  p=1.00 with every voice dimension at 0.00. A metric that cannot detect blatant
  failure cannot be trusted on subtle cases.
- **Real-vs-real control.** Two genuinely authored held-out passages against each
  other should land near 0.5. Measured 0.59 — acceptable. Far from 0.5 would mean
  the judge is biased or the passages differ by topic rather than voice, and the
  main result would be void.

Order is randomized per trial and the mapping withheld, so a judge that always
answers "A" scores chance instead of winning.

## Taste: the gap between the two measures

Fidelity alone does not capture whether writing is *good*. The decisive evidence
is that the two measures disagree, and the disagreement is informative:

| | with_skill | without_skill | raw slop |
|---|---|---|---|
| fidelity_error | 0.87 | 0.94 | 1.00 |
| direction | overshoot | overshoot | undershoot |
| register | 0.89 | 0.94 | 0.00 |
| rhythm | 0.83 | 0.86 | 0.01 |
| stance | 0.97 | 0.99 | 0.00 |
| concreteness | 0.72 | 0.77 | 0.00 |

Both rewrites score 0.83–0.99 on every voice dimension while failing fidelity at
0.87–0.94. **High marker match plus high fidelity error is the signature of
caricature**: every box ticked, and the result still not what the person would
have written. A single blended score would have hidden this completely, which is
why the dimensions are asked as independent parallel questions and never summed.

So taste is not the residue left over after the measurable parts are removed. It
is the specific failure of hitting every marker and still being wrong, and it has
a number.

## Taste, measured: quality ladders and pairwise ranking

An earlier attempt here demanded that each constructed defect move exactly one
quality dimension. Four of five pairs failed that screen and the conclusion drawn
was that structural taste is unmeasurable. **That conclusion was wrong** -- the
isolation requirement was an arbitrary constraint, not a property of writing. You
do not need to know *which* thing got worse. You only need to know the passage
got worse.

So: take good writing, add cumulative damage, and require the metric to reproduce
an ordering that is true by construction. Entanglement stops mattering, because
nothing claims to separate the strands.

Run `evals/taste_eval.py calibrate`.

### Building ladders that hold

Two rounds of adversarial screening were needed, and both failures were in the
ladder design rather than in the idea:

1. **Lexical defects destroy voice.** The first defect menu asked for stock
   vocabulary to be swapped in at the top rung. All five ladders then failed
   voice-checking, correctly: replacing "bolted on" with "integrated" does not
   make the same writer worse, it makes it a different writer, and a judge would
   have been detecting authorship rather than quality. Fixed by making every
   defect **organizational** -- reorder, relocate, duplicate, append, using only
   words already present. Voice preservation becomes mechanical. Four of five
   ladders then passed.
2. **A single relocation is inside editorial noise.** Every checker independently
   flagged rung 1 as not reliably worse; one showed the moved sentence landing in
   a better position than it started. Steps 2->3->4 were certified as declining.
   Fixed by dropping rung 1 so the first step clears a real damage threshold.

The screening is the reason this works. A ladder that passes on the benefit of
the doubt produces confident wrong numbers.

### The null control, which fails loudly

Shown a passage beside a **byte-identical copy**, the judge returns **0.75 to
0.89** for whichever copy sits in slot A. Truth is 0.50. With no real signal it
reads position and nothing else.

Every comparison is therefore run in both orders and averaged, which cancels a
symmetric bias exactly. The control runs first and prints above every headline
number, because a single-order version of this measurement would be worthless and
would not look it.

### Results

Against four ladders with known ordering:

| formulation | rank acc | adjacent acc | Spearman rho | position bias | verdict |
|---|---|---|---|---|---|
| plain | 1.00 | 1.00 | 1.00 | 0.14 | VALID |
| reader | 1.00 | 1.00 | 1.00 | 0.15 | VALID |
| craft | 1.00 | 1.00 | 1.00 | 0.16 | VALID |
| editor | 1.00 | 1.00 | 1.00 | 0.14 | VALID |
| specific | 1.00 | 1.00 | 1.00 | 0.43 | weak - fails the bias gate |

Adjacent accuracy is the number that matters, and it includes the hard pair:
rung 0 against rung 1 is the **same length**, a pure reorder with no words
changed. All four valid formulations recover it, four ladders out of four.

### Two wrong yardsticks, and the correction

The judge was first validated against 14 before/after rewrites published by federal
agencies under the Plain Writing Act, and then against winning entries from a
public bad-writing contest. `craft` scored 0.21 and 0.00.
The conclusion drawn was that `craft` is anti-correlated with good writing.

**That was wrong, and the error is instructive.** Neither standard measures taste:

- Federal plain-language rewrites optimise for a general public understanding a
  legal obligation. Short sentences, bullets, low reading level. That is a
  comprehension floor. A craft standard *should* lose to it, because the two are
  not measuring the same thing.
- Contest-winning bad fiction is bad by being **ornate** -- elaborate, high-effort,
  overwrought. That failure mode is nearly absent from the business prose this
  skill handles.

Both were chosen because they were convenient: publicly labelled orderings, easy
to fetch, one of them public domain. Convenience was mistaken for rigour, and
ranking a quality judge by two non-taste standards produced a judge mediocre at
taste.

### The standard that matters

Prose by writers with public craft credibility (`corpus/manifest.json`) against
sincere professional content-marketing prose (a five-source set kept with the
private source list) -- both
real writing on the open web, in the genres this skill actually sits between.
Content marketing is the right antithesis because it fails the way machine-
assisted business writing fails: fluent, confident, formulaic, empty. Not
overwrought. Not bureaucratic.

Accuracy saturates at 1.00 for all five formulations, so margin is the signal:

| formulation | craft vs slop (margin) | federal clarity | ornate bad fiction |
|---|---|---|---|
| **craft** | **0.98** | 0.21 | 0.00 |
| specific | 0.98 | 0.21 | 0.25 |
| plain | 0.88 | 0.71 | 0.25 |
| editor | 0.76 | 0.71 | 0.88 |
| reader | 0.73 | 0.36 | 1.00 |

`craft` separates the craft corpus from SEO copy at 0.96-1.00 on every pair. `editor`,
previously the recommended default, coin-flips on two of four.

`craft` is the default. Its blind spot is real and narrow -- it partly rewards
ornateness, so it is not trusted alone on florid prose, and `editor` is kept as a
cross-check for that case. The answer to a known blind spot is a guard, not
discarding the instrument that is otherwise best at the job.

The stylometry agrees independently, without any judge at all: sentence-length
variation runs a median of 0.65 in the craft corpus and 0.49 in the marketing
corpus. Flatness is measurable.

### The detection limit, stated rather than hidden

Applied to real drafts, the same metric separates what it can and refuses what it
cannot:

    raw slop         -20.7      <- massive, unambiguous separation
    three competent drafts    clustered within +/-0.5

Asked to rank three good drafts of the same update, the four valid formulations
produce **three different orderings**. Three of four put the human author's real
writing first, which is suggestive and nothing more. No claim about skill versus
baseline craft is supportable from this.

That is a resolution limit, and every instrument has one. What this metric
reliably measures:

- **gross quality differences** -- slop against competent writing, enormous margin
- **ordering of degraded versions of one passage** -- perfect across four ladders

What it does not yet resolve:

- fine differences between drafts that are all competent
- comparisons across different authors, where there is no true ordering to recover
  and the formulations openly disagree (0.12 against 0.85 on the same pair)

The useful consequence is that this works as a regression gate today: it will
catch the skill shipping something structurally bad, which is the failure that
actually matters. It will not adjudicate which of two good drafts is better, and
it says so instead of inventing a number.

## An external anchor for "good"

`corpus/` holds a manifest of freely-readable prose whose craft is widely
regarded, with `build_corpus.py` fetching to a gitignored cache and committing
only derived numbers. The repository stores measurements of other people's
writing, never copies of it.

Its job is to stop thresholds being invented. The absolute floors in
`scripts/stylometry.py` now sit just outside the observed p10/p90 of that corpus,
so a draft trips one only by being flatter or more repetitive than nearly all of
it:

| measure | corpus p10 | median | p90 |
|---|---|---|---|
| sentence-length CV | 0.53 | 0.65 | 1.51 |
| MTLD | 74.3 | 110.7 | 146.2 |
| repeated openings | 0.10 | 0.16 | 0.19 |
| longest flat run | 2 | 3.5 | 5 |

It earned its place immediately by exposing a bug. Every source measured MTLD
1.0, which is impossible for multi-thousand-word essays: the implementation
divided by the global token index instead of resetting the per-factor counter, so
lexical diversity pinned to ~1.0 for any text. Invisible on short samples,
obvious against real essays. Fixed; repetitive filler now scores 6.2 and real
prose 173.

The selection encodes a particular taste and is meant to be edited. Swap the
manifest for writers you actually admire and re-derive.

## What this does not establish

- One author persona, one document genre.
- The corpus is 10 essays, skewed toward technical and long-form English prose.
  A different manifest would move the floors.
- Only one taste dimension has usable constructed ground truth. The structural
  ones remain unmeasured, not measured-and-passed.
- A calibrated judge is not a reader. Per the protocol in
  `references/purpose-led-cadence.md`, an automated judge's preferences must be
  compared against human decisions and the disagreements reported. That has not
  been done, and until it is, these numbers are a tripwire rather than proof.
- Small n. Discrimination trials default to a handful per candidate.

## The taste model

An absolute score for a single passage, from atomic judgements combined by fitted
weights. Unlike the pairwise judge it needs no comparison partner, so it can run
at the moment a draft is being written.

`evals/taste_score.py`. Corpus: **158 passages across twelve registers**.
Exemplars are Pulitzer and National Magazine Award winners, standing critics and
award-recognised essayists. Anti-exemplars are SEO content, SaaS thought
leadership, engagement bait, content farms and press releases. Excerpts are cut
to a common length so a model cannot win by learning that long means good:
median 223 words against 221.

### The result that mattered: easy negatives were hiding everything

The first model scored **AUC 0.993** and was solving a trivial problem. Tested
against 30 machine-written passages covering the same subjects as the exemplars
-- fluent, correct, on-topic, anonymous -- it rejected **zero of thirty**.

    exemplars       0.772
    HARD negatives  0.674   <- indistinguishable from exemplars
    easy negatives  0.294

Telling an award-winning essayist from SEO copy is easy. Telling them from a
competent paraphrase of their own passage is the actual job, and nothing in the original twelve dimensions
asked whether a person had made a *choice*.

A second battery was added that does: is there a sensory scene rather than a
category; does the writer risk something a cautious editor would cut; do the
details read as noticed rather than looked up; does any sentence go somewhere
unpredictable; could any competent writer have produced this with no loss.

On matched pairs -- same subject, one human one machine -- these separate
cleanly: sensory_scene +0.32, personal_risk +0.27, cares_about_subject +0.23,
unusual_syntax +0.20, interchangeable_author -0.16. Hard-negative accuracy went
from 0.00 to **0.967**.

### Two axes, because they measure different things

Combining the batteries produced a model worse at both jobs than either alone:

| battery | dims | human-vs-machine AUC | quality-ladder rho |
|---|---|---|---|
| presence | 10 | 0.979 | **-0.450** |
| execution | 7 | 0.953 | **+0.800** |
| blended | 17 | 0.987 | +0.400 |

The presence battery is *anti-correlated* with craft execution. That is not a
defect in the questions -- scrambling a passage's structure does not remove its
author, so those questions correctly report a person still present in a badly
organised piece. A single blended number hides which of the two failures a draft
actually has, so both are reported and neither is averaged into the other.

If one number is needed, use **execution**: the only battery above 0.95 on
machine detection and above 0.8 on craft ordering.

    presence   execution
       0.612       0.707   real human work update
       0.658       0.679   skill output
       0.721       0.666   baseline output
       0.238       0.041   AI slop

Low presence with high execution is tidy anonymous prose, which is the most
common way generated writing fails.

### What is still not established

- Hard negatives were generated for this evaluation rather than found in the
  wild, and by the same model family being evaluated. Machine prose from other
  sources may differ.
- 30 hard negatives is a small class; the 0.967 has wide error bars.
- No human has been asked whether they agree with these rankings. The model is
  validated against constructed and attested orderings, not against readers.
- Every register is English and skews technical and literary.

## Two distributions inside "machine prose", and only one is easy

The hard-negative result above (0.00 to 0.967) used negatives generated by asking
a model to write something impersonal. That was measuring a distribution the
skill never actually produces.

Generating a second set under a neutral brief — "write a clear explainer on this
subject", "tidy this draft for publication", with instructions to write *well* —
across three model tiers, then holding each generator out of training:

| held-out generator | n | rejected | AUC vs exemplars |
|---|---|---|---|
| told-to-be-bland | 30 | **1.00** | 0.993 |
| sonnet, neutral brief | 12 | 0.58 | 0.772 |
| haiku, neutral brief | 12 | 0.58 | 0.666 |
| opus, neutral brief | 12 | **0.25** | 0.626 |

The dimension means explain it:

| dimension | human | told bland | told to write well |
|---|---|---|---|
| specific_detail | 0.88 | 0.19 | **0.76** |
| sensory_scene | 0.52 | 0.13 | **0.43** |
| cares_about_subject | 0.82 | 0.53 | **0.74** |
| noticed_not_looked_up | 0.52 | 0.24 | **0.45** |

Told to be bland, a model drops every marker and is trivial to catch. Told to
write well **while paraphrasing existing human text**, it inherits the human's
specifics, scenes and subject, and nearly matches on every axis.

That second case is what this skill produces. It rewrites a draft it was given.
So the distribution the detector is weakest on is precisely the one that matters,
and the earlier 0.967 was an artefact of asking for the wrong negatives.

Honest numbers with both distributions in the corpus — 194 passages, 72 exemplar
against 122 negatives from five sources: **accuracy 0.789, AUC 0.900**.

The open problem is not corpus size. It is that none of the seventeen dimensions
distinguishes *inherited* particularity from *observed* particularity. A
paraphrase keeps the details and loses the reason they were chosen, and nothing
here asks whether a detail is load-bearing or decorative.

### Relative beats absolute on the hard case

Twenty-four human passages against their own paraphrases, leave-one-PAIR-out so
neither side of a test pair is ever in training:

| judgement | score |
|---|---|
| absolute, scoring each passage alone | AUC 0.823 |
| **paired, human against its own paraphrase** | **0.917** |

A paraphrase keeps its source's topic and much of its content, so its absolute
score lands in an ambiguous band. Comparing the two directly is much easier —
and comparing is what this skill can always do, since it was handed the draft it
rewrote. `taste_score.py compare --before --after` is therefore the accurate
deployment mode, and it reports which axis dropped and which specific dimensions
the rewrite lost.

Battery 3 was a failed hypothesis, kept here because the negative result is
informative. It asked whether particularity is load-bearing — whether the writer
knows why each detail is present — on the theory that a paraphrase keeps details
and loses their motivation. Those seven dimensions score AUC 0.684 on the
paraphrase pairs, the weakest of the three batteries, and only
`summary_of_something` separates at all (-0.15). Battery 2 alone matches the full
24-dimension set on paired judgement at 0.917.

### Where this actually stands

| task | performance |
|---|---|
| craft against SEO/marketing copy | AUC 0.99 |
| craft against prose told to be bland | AUC 0.99 |
| quality ordering within one author (ladders) | Spearman +0.80 |
| craft against a competent paraphrase, **paired** | 0.917 |
| craft against a competent paraphrase, **absolute** | AUC 0.82 |
| corpus-wide, all five negative sources | accuracy 0.789, AUC 0.900 |

Corpus: 194 passages. Exemplars are Pulitzer and National Magazine Award winners,
standing critics and award-recognised essayists across seven registers.
Negatives come from five distinct sources: collected SEO content, SaaS thought
leadership, engagement bait, content farms and press releases; prose generated
under an explicit be-bland brief; and prose generated under a neutral
write-it-well brief at three model tiers.

## Cross-family negatives: does genericness generalise?

Earlier negatives came from one vendor. A detector trained that way could have
learned one family's tics rather than genericness, and only a held-out family can
tell the difference. Generated 64 more through OpenRouter across seven vendors
and several capability tiers, all under the neutral write-it-well brief:
Llama 3.1 8B and 3.3 70B, Gemma 2 27B, GPT-4o-mini, DeepSeek v3.1, Command-R 7B,
Qwen 2.5 32B, Hermes 4 405B.

Holding each family entirely out of training, with the decision threshold fitted
on training scores only:

| held-out family | n | AUC | rejected @ fitted thr |
|---|---|---|---|
| told-to-be-bland | 30 | 0.989 | 1.00 |
| openai | 8 | 0.924 | 0.50 |
| google | 8 | 0.891 | 0.50 |
| meta-llama | 16 | 0.844 | 0.50 |
| cohere | 8 | 0.804 | 0.38 |
| sonnet | 12 | 0.787 | 0.17 |
| haiku | 12 | 0.682 | 0.42 |
| opus | 11 | 0.673 | 0.18 |
| nousresearch | 8 | 0.665 | 0.38 |
| deepseek | 8 | 0.566 | 0.00 |
| qwen | 8 | 0.556 | 0.12 |

**Median held-out AUC 0.787.** Adding cross-family negatives is what produced
this: before they existed, the worst held-out generator was caught 25% of the
time; several families now sit above 0.84. Genericness does generalise across
vendors, but not uniformly. In this sample of 8 passages each, the DeepSeek and
Qwen outputs were the hardest to separate, and against those the detector was
barely above chance. Eight passages per family is too few to rank vendors.

Two engineering notes that changed the numbers without changing the model:

- **Class balancing.** With 185 negatives against 72 exemplars an unweighted fit
  leans toward "machine", dragging exemplars to the threshold. Weighting by
  inverse frequency fixed that and left every AUC unchanged, which is the
  giveaway that it was a calibration problem rather than a discrimination one.
- **Fitted thresholds.** The 0.5 cut was arbitrary and, after balancing, in the
  wrong place. The operating point is now chosen by Youden's J on training scores
  only. AUC and threshold are reported separately so rejection rates can be read
  fairly rather than treated as the headline.

### Honest summary

| task | performance |
|---|---|
| craft vs SEO / marketing copy | AUC 0.99 |
| craft vs prose told to be bland | AUC 0.99 |
| quality ordering within one author | Spearman +0.80 |
| **craft vs competent paraphrase, paired** | **0.917** |
| craft vs competent paraphrase, absolute | AUC 0.82 |
| **unseen vendor family, median** | **AUC 0.787** |
| corpus-wide, 12 negative sources | accuracy 0.747, AUC 0.863 |

The paired comparison is the strongest and most deployable result, and it is the
mode this skill can always use.

## Register blindness: the model fails where this skill is used most

Exemplar pole expanded from 72 passages to 228 across 21 registers, with
credentials that are external rather than asserted — Pulitzers, National Magazine
Awards, MacArthur fellowships, Best American selections, standing staff and
critical positions. Talese on Sinatra, Junod on Rogers, Cramer on Ted Williams.

Corpus-wide this improved things modestly: accuracy 0.747 to 0.787, AUC 0.863 to
0.869, median held-out family AUC 0.787 to 0.779 (all within noise of each
other). The useful result was not the aggregate. It was the breakdown:

| register | exemplar recall |
|---|---|
| literary essay, memoir, sports, speeches | **1.00** |
| profile, conflict reporting, humour | 0.91–0.92 |
| obituary, medicine, music, food/travel | 0.83–0.89 |
| criticism, science, longform, history | 0.70–0.80 |
| business, nature, political essay | 0.58–0.60 |
| **technical writing** | **0.25–0.30** |

The model is close to perfect on literary registers and barely better than
guessing on good technical prose. The cause is in the dimensions: they reward
sensory scenes, personal risk, unusual syntax and noticed-not-looked-up detail.
Excellent technical writing is precise and deliberately restrained. It has none
of those markers, so it reads to this model exactly like competent machine prose.

**This matters more than any aggregate number here**, because the writing this
skill is actually used on — commit messages, PR descriptions, runbooks, status
updates — sits squarely in the register the model is worst at. An absolute score
on a technical draft should not be acted on. The before-and-after comparison
remains usable there, since both sides share the register and the bias cancels.

Fixing it needs dimensions that capture craft in restrained prose: precision
about what is and is not known, pitching abstraction at the right level,
anticipating where a reader will get lost, saying the non-obvious thing about a
system. None of the 24 dimensions asks any of that.
