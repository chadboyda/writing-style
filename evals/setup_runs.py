#!/usr/bin/env python3
"""Create run directories containing ONLY the files each eval declares.

Iteration 1 shipped every fixture into every run directory, which quietly broke
two evals: the no-samples case had a full author corpus sitting in it, and the
humanize case had the reference answer. Both agents noticed and said so, but an
eval whose validity depends on the agent declining to look at what you handed it
is not measuring anything. `files` in evals.json is the contract; this enforces it.

Usage: setup_runs.py <iteration-dir> --fixtures <dir> [--only 1,2]
"""
import argparse, json, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("iteration")
    ap.add_argument("--fixtures", required=True)
    ap.add_argument("--evals", default=str(HERE / "evals.json"))
    ap.add_argument("--only", help="comma-separated eval ids; default all")
    a = ap.parse_args()

    spec = json.loads(Path(a.evals).read_text())
    fixtures, it = Path(a.fixtures), Path(a.iteration)
    only = {int(x) for x in a.only.split(",")} if a.only else None

    for e in spec["evals"]:
        if only is not None and e["id"] not in only:
            continue
        for cfg in ("with_skill", "without_skill"):
            work = it / f"eval-{e['id']}" / cfg / "work"
            if work.exists():
                shutil.rmtree(work)
            work.mkdir(parents=True)
            (it / f"eval-{e['id']}" / cfg / "outputs").mkdir(parents=True, exist_ok=True)
            for name in e["files"]:
                src = fixtures / name.rstrip("/")
                if not src.exists():
                    print(f"  !! {e['name']}: declared file missing: {name}", file=sys.stderr)
                    continue
                dst = work / src.name
                shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
        got = e["files"] or ["(intentionally empty)"]
        print(f"eval-{e['id']} {e['name']:<28} {', '.join(got)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
