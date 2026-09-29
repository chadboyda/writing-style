#!/usr/bin/env python3
"""Build self-contained eval fixtures.

The eval prompts must not depend on the user's Slack, Gmail, or Drive being
reachable -- a subagent in a sandbox has none of those, and an eval that can
only run on one laptop is not a regression test. So every fixture ships its own
author corpus: a real git repo with real commits in a distinctive voice, plus
markdown samples. Local sources (`git log --author`, repo docs) are first-class
retrieval targets for this skill anyway, so this exercises the real code path.

Usage: make_fixtures.py <output-dir>
"""
import subprocess, sys, textwrap
from pathlib import Path

AUTHOR = "Dana Reyes"
EMAIL = "dana@fernpost.example"

# Distinctive, measurable voice: lowercase subjects, em dashes, owns mistakes,
# states the why, hedges on next steps. A grader can check for these markers.
COMMITS = [
    ("fix dedupe key collision in sync writer",
     "we were keying on a millisecond timestamp — two writers in the same ms\n"
     "produced duplicate rows. switched to a content hash.\n\n"
     "this is the bug brightwater co reported in march. i said it was a network\n"
     "retry issue at the time and it wasn't — sorry for the runaround."),
    ("add retry budget to the webhook dispatcher",
     "we were retrying forever on 500s and hammering partners who were already\n"
     "down. capped at 6 attempts with backoff.\n\n"
     "not backfilling the stuck queue yet — want to watch this for a week first."),
    ("drop the unused events_archive table",
     "nothing has read from it since the 2023 migration. confirmed with a query\n"
     "against the audit log before dropping.\n\n"
     "kept a dump in the ops bucket in case i'm wrong about that."),
    ("make the importer surface partial failures",
     "it was swallowing per-row errors and reporting success — which is how the\n"
     "harlow state import looked fine and wasn't.\n\n"
     "now returns a per-row result set. the ui doesn't render it yet."),
    ("reduce staging log verbosity",
     "debug logging in staging was writing 40gb/day and nobody reads it.\n"
     "dropped to info.\n\n"
     "if this makes an incident harder to debug, flip it back — i'd rather be\n"
     "wrong about this than lose a postmortem."),
    ("cache the org lookup in the auth middleware",
     "we were hitting the orgs table on every request. now cached for 60s.\n\n"
     "60s is a guess. it means a permissions change takes up to a minute to\n"
     "take effect, which i think is fine but somebody should tell me if it isn't."),
    ("fix off-by-one in the pagination cursor",
     "last item on each page was being skipped. classic.\n\n"
     "added a test that would have caught it."),
    ("split the billing worker out of the main queue",
     "a slow billing job was blocking everything behind it. separate queue now.\n\n"
     "this was the actual cause of the friday latency spike, not the deploy."),
]

SLACK_SAMPLES = """\
# Dana's past updates (exported)

## #eng-updates, Tuesday
sync rewrite is out — took three days longer than i estimated, which is on me.
the **root cause** was dumber than expected: dedupe keyed on a timestamp two
writers could hit in the same millisecond.

brightwater co and harlow state both saw this last quarter. should be resolved on
monday's deploy. not backfilling the historical dupes yet — bigger job, and i'd
rather land this and watch it for a week.

## #eng-updates, the Tuesday before
migration is ~60% done and i'm now fairly confident we land before the freeze.
the **blocker** from last week turned out to be a config issue, not a schema
problem, which is a relief.

what i got wrong: estimated the backfill at four hours, it's taken eleven. the
staging copy was smaller than prod and i didn't check.

still open — friday cutover or monday. i lean monday. fewer people around to be
surprised by it.

## #eng-updates, two weeks ago
short one. webhook retries are capped now — we were hammering partners who were
already down, which is a bad look and also our fault.

no other changes worth reporting. the **importer work** slipped again because i
spent tuesday on the incident.
"""

SLOP_DRAFT = """\
# Q3 Platform Reliability Update

Our Q3 reliability initiatives serve as a testament to the team's unwavering
commitment to operational excellence. Additionally, these improvements underscore
our pivotal role in the evolving infrastructure landscape.

**Key Achievements And Milestones**

- **Synchronization:** The synchronization layer has been significantly enhanced
  through the implementation of robust deduplication logic.
- **Reliability:** Reliability has been strengthened through the introduction of
  intelligent retry mechanisms.
- **Performance:** Performance has been optimized through strategic caching.

It's not just a set of fixes, it's a fundamental reimagining of how we approach
platform stability. Industry observers note that such comprehensive initiatives
are crucial for sustained growth. In order to achieve these goals, the team
leveraged a myriad of intricate techniques, fostering a culture of excellence
while ensuring seamless delivery.

Despite these achievements, the platform faces several challenges. Despite these
challenges, the future looks bright as we continue our journey toward excellence.

I hope this helps! Let me know if you want more detail on the rollout.
"""

CLEAN_IN_VOICE = """\
# Q3 reliability — what actually changed

three things shipped, and one of them was the fix for a bug i misdiagnosed in march.

dedupe in the sync writer was keying on a millisecond timestamp, so two writers
firing at once produced duplicate rows. it's a content hash now. brightwater co and
harlow state both hit this and both should be clear as of monday.

webhook retries are capped at six attempts with backoff — we were retrying
forever on 500s and hammering partners who were already down.

org lookups are cached for 60s, which took the auth middleware off the orgs table
on every request. 60s is a guess, and it means a permissions change can take a
minute to land. i think that's fine. tell me if it isn't.

what's still open — the stuck webhook queue isn't backfilled and the importer's
per-row errors still don't render in the ui. neither is urgent.
"""


def run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_repo(root):
    repo = root / "fernpost-api"
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    run(["git", "init", "-q", "-b", "main"], repo)
    run(["git", "config", "user.name", AUTHOR], repo)
    run(["git", "config", "user.email", EMAIL], repo)
    src = repo / "sync.py"
    for n, (subject, body) in enumerate(COMMITS, 1):
        src.write_text(f"# revision {n}\ndef sync():\n    return {n}\n")
        (repo / "docs" / "notes.md").write_text(f"working notes, rev {n}\n")
        run(["git", "add", "-A"], repo)
        run(["git", "commit", "-q", "-m", f"{subject}\n\n{body}"], repo)
    return repo


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    repo = build_repo(out)
    (out / "slack-history.md").write_text(SLACK_SAMPLES)
    (out / "q3-draft-slop.md").write_text(SLOP_DRAFT)
    (out / "q3-draft-clean.md").write_text(CLEAN_IN_VOICE)
    n = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=repo,
                       capture_output=True, text=True).stdout.strip()
    print(f"fixtures -> {out}")
    print(f"  fernpost-api/       git repo, {n} commits by {AUTHOR} <{EMAIL}>")
    print(f"  slack-history.md    3 past updates in the same voice")
    print(f"  q3-draft-slop.md    AI-slopped draft to rewrite")
    print(f"  q3-draft-clean.md   already good, already in voice (over-correction bait)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
