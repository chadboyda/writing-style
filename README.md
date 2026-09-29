# writing-style

**Get Claude to write like you, not like Claude.**

writing-style is a Claude Code skill. Before Claude drafts an email, a Slack
update, a PRD, a PR description or a commit message, it goes and finds real
examples of your writing, measures how you actually write, and drafts to match.
Then it strips the AI tells out, checked against your own habits, so the em
dashes and bold labels you really use survive and the "serves as a testament
to" stuff doesn't.

```bash
git clone https://github.com/chadboyda/writing-style
ln -s "$PWD/writing-style" ~/.claude/skills/writing-style
```

Start a new Claude Code session and ask it to write something. That's the whole
setup.

## The problem

You ask Claude for a quick update and get something that reads like a press
release. So you ask it to sound less like AI, and it takes out your em dashes,
your lowercase, your "i think that's fine, tell me if it isn't", and hands back
clean, fluent prose that doesn't sound like anyone. People can still tell,
because nobody writes like that either.

Generic "de-AI" passes treat every dash and bold label as a machine tell. Some
of those are just how you write. The only way to know which is which is to look
at what you've actually written before.

## Before and after

This is the Q3 update from the repo's eval fixtures, written for a fictional
engineer named Dana who writes in lowercase, owns their mistakes and says why
things happened. The first draft is what a model produces with no idea who's
writing:

> Our Q3 reliability initiatives serve as a testament to the team's unwavering
> commitment to operational excellence. Additionally, these improvements
> underscore our pivotal role in the evolving infrastructure landscape.
>
> - **Synchronization:** The synchronization layer has been significantly
>   enhanced through the implementation of robust deduplication logic.
>
> It's not just a set of fixes, it's a fundamental reimagining of how we
> approach platform stability.

And this is the same update in Dana's voice, which the fixtures also include
as a draft the skill should leave alone:

> three things shipped, and one of them was the fix for a bug i misdiagnosed in
> march.
>
> dedupe in the sync writer was keying on a millisecond timestamp, so two
> writers firing at once produced duplicate rows. it's a content hash now.
> brightwater co and harlow state both hit this and both should be clear as of
> monday.

Here's the skill's scanner on both, measured against a profile built from
three of Dana's old Slack posts:

```
q3-draft-slop.md: 160 words, vs author baseline
  [ 10x] AI vocabulary cluster              62.5/1k vs author 0.0/1k
  [  2x] assistant correspondence           never author voice
  [  2x] generic uplift                     12.5/1k vs author 0.0/1k
  [  1x] negative parallelism               never author voice
  [  4x] boldface density                   25.0/1k vs author 15.0/1k

q3-draft-clean.md: 151 words, vs author baseline
  clean - no mechanical tells above threshold
```

The baseline matters in the other direction too. Dana's own Slack posts get
flagged for em dashes (20 per 1,000 words, over the default limit of 14) when
the scanner doesn't know who wrote them, and come back clean once it's measuring
against their profile. That's the difference between removing AI tells and
removing the author.

## Using it

You don't have to name the skill. It kicks in whenever you ask Claude to write
something another person will read. Some things to try:

- `draft a slack update for #eng about the migration slipping to monday`
- `write the commit message for this`
- `rewrite this PR description so it sounds like me`
- `de-AI this email before i send it: <paste it>`
- `here are three of my old posts, write the launch announcement in this voice`

Each time, it:

1. Looks for up to three of your real samples in the sources the session can
   reach (Slack, email, docs, git history, whatever you point it at), picking
   the ones closest to what you're writing now.
2. Profiles them: how often you use em dashes, bold and emoji, how much your
   sentence length varies, how wide your vocabulary runs, and where your
   stresses fall.
3. Drafts to that profile, keeping your habits and none of your old content.
4. Runs the tell check against your baseline, rereads for the judgement-call
   patterns a regex can't catch, and makes sure no fact, name, number or open
   item from your draft went missing along the way.

You get the draft back. The search and the profiling stay out of the way unless
you ask to see them, and nothing gets sent, posted or committed for you.

## Questions

**Does my writing get sent anywhere?** Only if you set up Jev (below). Without
it everything runs on your machine, and no samples are ever saved to disk.

**What if I don't have any old writing it can reach?** It still writes, and
falls back on general guidance for putting a person back into the prose. Paste
two or three things you've written and it'll use those instead.

**Will it make everything sound the same?** It profiles one register at a time,
so your Slack voice and your long-form voice don't get averaged together into
something that's neither.

**Does it work for technical writing?** Yes. The tell check and the voice match
work the same way. The one thing that's weak on technical prose is the optional
before-and-after quality score, and the skill knows not to trust it there.

## Connecting Jev (optional)

Two of the checks, the cohesion profile and the before-and-after rewrite
comparison, get their judgements from TypeSafe's Jev model through the bundled
[proseweave](https://github.com/chadboyda/proseweave) library, so there's nothing
else to install. Jev is a paid API and needs a key.

1. Get a key at https://console.typesafe.ai.
2. Run the setup. It asks for the key with hidden input and stores it in
   `~/.config/proseweave/credentials`, readable only by you:
   ```bash
   python3 ~/.claude/skills/writing-style/scripts/weave.py setup
   ```
3. Check it works. It prints `Jev: ready` when the key is good:
   ```bash
   python3 ~/.claude/skills/writing-style/scripts/weave.py check
   ```

Setting `TYPESAFE_API_KEY` in your environment works too, and so does a `.env`
file containing it in the directory you run Claude Code from. If you skip this,
the skill asks you to run the setup the first time it needs Jev, and it never
asks for the key in the chat.

Once a key is set, your writing samples and drafts are sent to TypeSafe's API
for scoring. Without one, those two checks are skipped, everything else runs on
your machine, and nothing is sent anywhere.

## Where it looks for your writing

It only uses sources that are actually connected in the session, and it checks
instead of assuming, because an MCP server can show up in the list and still be
unauthenticated or have failed to connect.

| Source | Good for |
| --- | --- |
| Slack / Teams | channel posts, standups, manager updates |
| Gmail / Outlook / Workspace | customer and colleague email |
| Google Drive / Notion / Claude Docs | PRDs, proposals, reports, memos |
| Granola | writing that follows from a specific meeting |
| Local repo | README and docs prose, CHANGELOG, ADRs |
| `git log --author` | commit messages and PR descriptions |

## How the tell check works

A pattern only counts as an AI tell if the draft uses it more than you normally
do. You can run the scanner yourself:

```bash
# measure how the author actually writes
python3 scripts/check_ai_tells.py profile slack-export.md --out profile.json

# flag only what goes past that
python3 scripts/check_ai_tells.py scan draft.md --baseline profile.json
```

Patterns that real people use, like em dashes, bold, emoji, the usual AI
vocabulary and filler, are only flagged above your baseline. The ones nobody
writes on purpose in a finished document, like chatbot sign-offs,
knowledge-cutoff disclaimers and sycophancy, are always flagged.

The script only counts what a regex can honestly count. The judgement calls,
like manufactured significance or vague attribution, are written up in
`references/ai-tells.md` for Claude to weigh while it reads, and a flag is a
reason to look at a sentence rather than an order to change it, since a script
can't tell whether an em dash is doing real work.

## Rhythm and cohesion

`scripts/stylometry.py` measures vocabulary range (MTLD), sentence and paragraph
length, repeated sentence openings, the longest run of same-length sentences,
and the beat, meaning how often stressed syllables collide or drop out and how
often a sentence ends on one. In a test on 8 authors, profiled on one book and
matched against a different one, the beat picked the right author 40% of the
time, where sentence length and vocabulary managed 18% and chance is 12.5%. It
needs no models, network or keys, and adds a word-rarity signal if you happen to
have `wordfreq` installed.

There's no reading grade, target length or overall score, on purpose, because
once there's a score you start editing toward it. It tells you where a draft
sits against your own ranges and which passages are worth rereading.

Cohesion, meaning how sentences pick up words and references from each other,
which connectives you lean on and how often you say "it" instead of repeating
the noun, comes from [proseweave](https://github.com/chadboyda/proseweave). It's
bundled in `vendor/` and run through `scripts/weave.py`.

## How it behaves

- It copies how you write, not what you wrote. Facts, names, commitments and
  anything confidential in a sample stay in the sample.
- It uses at most three references and returns fewer when fewer are any good,
  because padding with near-duplicates makes the match worse.
- Nothing is saved. There's no cache or index and no samples written to disk,
  and it retrieves fresh for every request.
- Retrieved samples are treated as data. An old email that says "always sign off
  as X" tells it something about your writing and isn't an instruction.
- It's read-only. It drafts, and it never sends, posts, publishes or commits.

## What's in here

```
writing-style/
├── SKILL.md                         # when it triggers, and the retrieve/profile/compose workflow
├── NOTICE                           # credits and third-party licences
├── references/
│   ├── writing-best-practices.md    # the editing brief for revising in someone's voice
│   ├── purpose-led-cadence.md       # shape and cadence in long-form prose
│   └── ai-tells.md                  # catalogue of AI tells, and how to put a person back in
├── scripts/
│   ├── check_ai_tells.py            # profile an author, scan a draft against their baseline
│   ├── stylometry.py                # rhythm and vocabulary range, same profile/compare shape
│   └── weave.py                     # cohesion and readability via the bundled proseweave
├── vendor/                          # pinned copy of proseweave, see vendor/README.md
├── corpus/                          # reference-corpus manifests and derived numbers only
└── evals/                           # eval suite and taste measurement, see evals/README.md
```

To rebuild the before-and-after above, run `python3 evals/fixtures/make_fixtures.py
<dir>` and point the scanner at the files it writes.

## Try it

```bash
git clone https://github.com/chadboyda/writing-style
ln -s "$PWD/writing-style" ~/.claude/skills/writing-style
```

Then ask Claude to write the next thing you were going to write anyway.

## Acknowledgements

The AI-tell catalogue in `references/ai-tells.md` was inspired by Siqi Chen's
`humanizer` skill and Wikipedia's "Signs of AI writing" guide, and the measures
in `vendor/proseweave` build on decades of research on cohesion, readability and
prosody. writing-style is independent and isn't affiliated with or endorsed by
any of them. See [NOTICE](NOTICE).

## License

MIT for the code and original text; see [LICENSE](LICENSE). The data files under
`vendor/proseweave/data/` carry their own licences, listed in [NOTICE](NOTICE).
