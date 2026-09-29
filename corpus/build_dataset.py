#!/usr/bin/env python3
"""Fetch the labelled corpus and cut it into comparable excerpts.

Takes the discovered URL list, retrieves each article into the gitignored cache,
and emits one excerpt per source at a common length. Excerpts rather than whole
articles because length and genre would otherwise be free signal: a judge that
learns "long means good" has learned nothing about writing.

Text is never committed. The dataset written here lives in the workspace; only
the manifest and the derived numbers belong in the repository.

The committed corpus/dataset/manifest.json is a public index (id, category,
pole) with no URLs, so it cannot drive a rebuild. The full source list is kept
privately; pass it by path.

Usage: build_dataset.py --manifest full-manifest.json --out dataset.json [--words 220]
       WRITING_STYLE_DATASET_MANIFEST=full-manifest.json build_dataset.py --out dataset.json
"""
import argparse, hashlib, json, os, re, sys, urllib.error, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_corpus as BC  # reuse html_to_text + entity handling

CACHE = HERE / "cache"
UA = "Mozilla/5.0 (compatible; writing-style-corpus/1.0; research use)"
MANIFEST_ENV = "WRITING_STYLE_DATASET_MANIFEST"
PRIVATE_NOTE = (
    "The full source list (URLs) for the taste dataset is kept privately; the "
    "committed corpus/dataset/manifest.json is an index of ids, categories and "
    "poles only. Pass the full manifest with --manifest PATH or "
    f"{MANIFEST_ENV}=PATH.")


def load_candidates(path):
    """Accept a bare list of sources or a {"sources": [...]} manifest."""
    data = json.loads(Path(path).read_text())
    cands = data["sources"] if isinstance(data, dict) else data
    if not all("url" in c for c in cands):
        sys.exit(f"{path} has no URLs. {PRIVATE_NOTE}")
    return cands


def fetch(url, refresh=False):
    f = CACHE / f"{hashlib.sha256(url.encode()).hexdigest()[:16]}.txt"
    if f.exists() and not refresh:
        return f.read_text(encoding="utf-8"), "cached"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
    except Exception as e:
        return None, f"fail: {type(e).__name__}"
    t = BC.html_to_text(raw)
    if len(t.split()) < 400:
        return None, f"thin ({len(t.split())}w)"
    f.write_text(t, encoding="utf-8")
    return t, "fetched"


def excerpt(text, target):
    """Contiguous whole paragraphs near the target length, skipping the opening,
    which is usually nav residue, bylines, or a subscribe box."""
    paras = [l.strip() for l in text.split("\n") if len(l.split()) > 20]
    if len(paras) < 3:
        return None
    best, bd = None, 10**9
    for i in range(1, min(len(paras) - 1, 25)):
        buf, n = [], 0
        for p in paras[i:i + 6]:
            buf.append(p); n += len(p.split())
            if n >= target: break
        if n < target * 0.6: continue
        if abs(n - target) < bd:
            best, bd = "\n\n".join(buf), abs(n - target)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates", nargs="?", help="same as --manifest")
    ap.add_argument("--manifest", default=os.environ.get(MANIFEST_ENV))
    ap.add_argument("--out", required=True)
    ap.add_argument("--words", type=int, default=220)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    path = a.candidates or a.manifest
    if not path:
        ap.error(PRIVATE_NOTE)
    CACHE.mkdir(exist_ok=True)
    cands = load_candidates(path)

    rows, fails = [], []
    for i, c in enumerate(cands, 1):
        pole = "exemplar" if str(c.get("pole", "")).startswith("exemplar") else "anti-exemplar"
        text, status = fetch(c["url"], a.refresh)
        if text is None:
            fails.append({"url": c["url"], "status": status, "category": c.get("category")})
            continue
        ex = excerpt(text, a.words)
        if not ex:
            fails.append({"url": c["url"], "status": "no usable excerpt",
                          "category": c.get("category")})
            continue
        rows.append({"id": hashlib.sha256(c["url"].encode()).hexdigest()[:12],
                     "url": c["url"], "author": c.get("author", ""),
                     "category": c.get("category", ""), "pole": pole,
                     "label": 1 if pole == "exemplar" else 0,
                     "words": len(ex.split()), "text": ex})
        if i % 20 == 0:
            print(f"  {i}/{len(cands)} processed", file=sys.stderr)

    Path(a.out).write_text(json.dumps(rows, indent=2))
    pos = sum(r["label"] for r in rows)
    print(f"\ndataset: {len(rows)} excerpts  ({pos} exemplar / {len(rows)-pos} anti)", file=sys.stderr)
    print(f"failed:  {len(fails)}", file=sys.stderr)
    from collections import Counter
    for k, n in sorted(Counter(f["status"].split()[0] for f in fails).items()):
        print(f"  {k:<10} {n}", file=sys.stderr)
    med_pos = sorted(r["words"] for r in rows if r["label"] == 1)
    med_neg = sorted(r["words"] for r in rows if r["label"] == 0)
    if med_pos and med_neg:
        print(f"median words  exemplar {med_pos[len(med_pos)//2]}  "
              f"anti {med_neg[len(med_neg)//2]}  (close means length is not the signal)",
              file=sys.stderr)
    Path(a.out + ".failures.json").write_text(json.dumps(fails, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
