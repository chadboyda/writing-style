#!/usr/bin/env python3
"""Fetch the reference corpus and derive empirical ranges for the style checks.

The thresholds in scripts/stylometry.py started as guesses. This replaces them
with measurements: fetch prose whose craft is widely regarded, measure it, and
use the observed spread as the range that counts as normal. A floor invented at
a desk flags people for having a style; a floor derived from writers who
demonstrably have one does not.

Text is fetched to corpus/cache/, which is gitignored. Only derived numbers are
committed -- this repository stores measurements of other people's writing, never
copies of it. Run with --refresh to re-fetch.

The default manifest is the public craft corpus, corpus/manifest.json. Other
source lists, such as the low-craft comparison set, are kept privately; pass one
with --manifest PATH or WRITING_STYLE_CORPUS_MANIFEST=PATH.

Usage:
    build_corpus.py [--refresh] [--manifest PATH] [--out corpus/metrics.json]
"""

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import stylometry  # noqa: E402

UA = "Mozilla/5.0 (compatible; writing-style-corpus/1.0; research use)"
BLOCK = re.compile(r"<(script|style|nav|header|footer|aside|form)\b.*?</\1>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")
ENT = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'",
       "&nbsp;": " ", "&mdash;": "—", "&ndash;": "–", "&rsquo;": "’",
       "&lsquo;": "‘", "&ldquo;": "“", "&rdquo;": "”", "&hellip;": "..."}


def html_to_text(html):
    t = BLOCK.sub(" ", html)
    t = re.sub(r"</(p|div|li|h[1-6]|blockquote)>", "\n\n", t, flags=re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = TAG.sub(" ", t)
    for k, v in ENT.items():
        t = t.replace(k, v)
    t = t.replace("\u00ad", "")              # literal soft hyphen
    t = re.sub(r"&#\d+;", " ", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    # drop nav-ish fragments: short lines with no sentence punctuation
    keep = [ln for ln in t.split("\n")
            if len(ln.split()) > 8 or re.search(r"[.!?]", ln)]
    return "\n".join(keep).strip()


def fetch(url, cache, refresh):
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    f = cache / f"{key}.txt"
    if f.exists() and not refresh:
        return f.read_text(encoding="utf-8"), "cached"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read().decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        return None, f"failed: {e}"
    text = html_to_text(raw)
    if len(text.split()) < 300:
        return None, f"too short after extraction ({len(text.split())} words)"
    f.write_text(text, encoding="utf-8")
    return text, "fetched"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--manifest",
                    default=os.environ.get("WRITING_STYLE_CORPUS_MANIFEST", str(HERE / "manifest.json")))
    ap.add_argument("--out", default=str(HERE / "metrics.json"))
    a = ap.parse_args()

    man = json.loads(Path(a.manifest).read_text())
    if not all("url" in s for s in man["sources"]):
        print(f"{a.manifest} has no URLs to fetch. Full source lists are kept "
              "privately; pass one with --manifest PATH or WRITING_STYLE_CORPUS_MANIFEST=PATH.",
              file=sys.stderr)
        return 2
    cache = HERE / "cache"
    cache.mkdir(exist_ok=True)

    rows, failures = [], []
    for src in man["sources"]:
        text, status = fetch(src["url"], cache, a.refresh)
        if text is None:
            failures.append({"url": src["url"], "author": src.get("author", src.get("id", "?")), "status": status})
            print(f"  skip  {src.get('author', src.get('id','?')):<20} {status}", file=sys.stderr)
            continue
        m = stylometry.measure(text)
        rows.append({"author": src.get("author", src.get("id", "?")), "genre": src.get("genre", ""),
                     "url": src["url"], "words": m["words"],
                     **{k: m[k] for k in ("sent_len_mean", "sent_len_cv", "para_len_cv",
                                          "mtld", "repeated_opening_rate",
                                          "longest_flat_run") if m.get(k) is not None}})
        print(f"  ok    {src.get('author', src.get('id','?')):<20} {m['words']:>6}w  "
              f"cv={m.get('sent_len_cv')}  mtld={m.get('mtld')}  "
              f"open={m.get('repeated_opening_rate')}  flat={m.get('longest_flat_run')} [{status}]",
              file=sys.stderr)

    if len(rows) < 4:
        print(f"only {len(rows)} sources usable - not enough to derive ranges", file=sys.stderr)
        return 2

    def spread(key):
        vals = sorted(r[key] for r in rows if key in r)
        if len(vals) < 4:
            return None
        n = len(vals)
        return {"n": n, "min": round(vals[0], 3), "max": round(vals[-1], 3),
                "median": round(statistics.median(vals), 3),
                "p10": round(vals[max(0, int(n * 0.10))], 3),
                "p90": round(vals[min(n - 1, int(n * 0.90))], 3)}

    metrics = {
        "note": ("Derived from the manifest. Percentiles describe how writers with "
                 "craft credibility actually vary; p10/p90 are the useful edges. "
                 "These describe a range, they are not targets - editing prose "
                 "toward a median produces the evenness stylometry.py exists to find."),
        "sources_measured": len(rows),
        "failures": failures,
        "per_source": rows,
        "ranges": {k: spread(k) for k in
                   ("sent_len_mean", "sent_len_cv", "para_len_cv", "mtld",
                    "repeated_opening_rate", "longest_flat_run")},
    }
    Path(a.out).write_text(json.dumps(metrics, indent=2) + "\n")
    print(f"\nwrote {a.out}: {len(rows)} sources, {len(failures)} failed", file=sys.stderr)
    for k, v in metrics["ranges"].items():
        if v:
            print(f"  {k:<24} p10={v['p10']:<8} median={v['median']:<8} p90={v['p90']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
