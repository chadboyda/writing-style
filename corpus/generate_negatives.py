#!/usr/bin/env python3
"""Generate machine-written negatives across model families via OpenRouter.

Negatives from a single model family teach a detector that family's tics rather
than genericness itself, and only a held-out family can tell those apart. This
draws from several vendors and capability tiers so `taste_score.py generalize`
has something real to hold out.

The brief is deliberately NEUTRAL. An earlier round asked models to write
something impersonal and produced negatives that were trivially detectable --
every marker collapsed, because the instruction was essentially "write badly".
What matters is what a model produces when it is genuinely trying, so these are
asked to write well and given no hint that the output is a negative.

Needs OPENROUTER_API_KEY in the environment or a .env beside the skill.
Standard library only.

Usage:
    generate_negatives.py --dataset ds.json --out negs.json [--per-model 8]
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://openrouter.ai/api/v1/chat/completions"

# Spread across vendors AND capability tiers. Small older models matter here:
# they produce the flattest, most template-shaped prose, which is the far end of
# the distribution this detector has to cover.
MODELS = [
    "meta-llama/llama-3.1-8b-instruct",
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemma-2-27b-it",
    "openai/gpt-4o-mini",
    "deepseek/deepseek-chat-v3.1",
    "cohere/command-r7b-12-2024",
    "qwen/qwen-2.5-coder-32b-instruct",
    "nousresearch/hermes-4-405b",
]

BRIEFS = [
    ("explainer", "Write a clear, well-crafted piece on the same subject for a general "
                  "audience, at roughly the same length."),
    ("polish", "Rewrite this passage to be clearer and more polished for publication, "
               "keeping the subject and the information, at roughly the same length."),
]


def load_key():
    import os
    k = os.environ.get("OPENROUTER_API_KEY")
    if k:
        return k
    for d in (Path(__file__).resolve().parent.parent, Path.cwd()):
        f = d / ".env"
        if f.exists():
            for line in f.read_text().splitlines():
                if line.startswith("OPENROUTER_API_KEY"):
                    return line.split("=", 1)[1].strip().strip("'\"")
    return None


def generate(key, model, prompt, retries=3):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 900,
        "temperature": 0.8,
    }).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/chadboyda/writing-style",
        "X-Title": "writing-style corpus",
    })
    delay = 2.0
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
            return d["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and attempt < retries - 1:
                time.sleep(delay); delay *= 2; continue
            return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(delay); delay *= 2; continue
            return None
    return None


def clean(t):
    """Strip the preamble models add when handed a writing task."""
    t = re.sub(r"^\s*(here'?s?|here is|sure[,!]|certainly[,!]|of course[,!])[^\n]*\n+",
               "", t, flags=re.I)
    t = re.sub(r"^#+\s.*\n+", "", t)           # a title is not prose
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-model", type=int, default=8)
    ap.add_argument("--models", nargs="*", default=MODELS)
    a = ap.parse_args()

    key = load_key()
    if not key:
        print("no OPENROUTER_API_KEY", file=sys.stderr)
        return 1

    ds = json.loads(Path(a.dataset).read_text())
    ex = [r for r in ds if r["label"] == 1]
    out, done = [], {}
    if Path(a.out).exists():
        out = json.loads(Path(a.out).read_text())
        for r in out:
            done[(r["generator"], r["mirrors"])] = True

    for mi, model in enumerate(a.models):
        fam = model.split("/")[0]
        made = 0
        for i in range(a.per_model):
            src = ex[(mi * a.per_model + i) % len(ex)]
            if (model, src["id"]) in done:
                made += 1; continue
            bid, brief = BRIEFS[i % len(BRIEFS)]
            prompt = f"{brief}\n\n---\n{src['text']}\n---"
            txt = generate(key, model, prompt)
            if not txt:
                continue
            txt = clean(txt)
            if len(txt.split()) < 100:
                continue
            out.append({"id": f"or_{fam}_{src['id']}", "label": 0,
                        "category": "hard-negative-machine", "pole": "anti-exemplar",
                        "generator": model, "family": fam, "framing": bid,
                        "mirrors": src["id"], "words": len(txt.split()), "text": txt})
            made += 1
            Path(a.out).write_text(json.dumps(out, indent=2))
        print(f"  {model:<42} {made}/{a.per_model}", file=sys.stderr)

    Path(a.out).write_text(json.dumps(out, indent=2))
    from collections import Counter
    print(f"\n{len(out)} negatives across {len(set(r['generator'] for r in out))} models",
          file=sys.stderr)
    for k, n in sorted(Counter(r["family"] for r in out).items()):
        print(f"  {k:<16} {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
