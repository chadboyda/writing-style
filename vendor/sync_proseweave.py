#!/usr/bin/env python3
"""Refresh the vendored copy of proseweave from a proseweave checkout.

The skill ships proseweave inside this repository (vendor/proseweave/) so that
anyone with access to the skill can use it, whether or not they can reach the
proseweave repository. The copy is pinned: vendor/PROSEWEAVE_VERSION records
the commit it came from. Edit proseweave in its own repository, commit there,
then run this.

    python3 vendor/sync_proseweave.py [PROSEWEAVE_CHECKOUT]   copy (default: a sibling proseweave checkout)
    python3 vendor/sync_proseweave.py --check [CHECKOUT]      exit 1 if the copy has drifted

Only the package itself (src/proseweave), LICENSE and NOTICE are copied.
"""
from __future__ import annotations

import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEST = HERE / "proseweave"
PIN = HERE / "PROSEWEAVE_VERSION"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def _commit(src: Path) -> str:
    out = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True)
    dirty = subprocess.run(["git", "-C", str(src), "status", "--porcelain", "--", "src", "LICENSE", "NOTICE"],
                           capture_output=True, text=True).stdout.strip()
    sha = out.stdout.strip() or "unknown"
    return sha + (" (with uncommitted changes)" if dirty else "")


def _differs(a: Path, b: Path) -> list[str]:
    cmp = filecmp.dircmp(a, b, ignore=["__pycache__", ".DS_Store"])
    out = [str(Path(cmp.left) / n) for n in cmp.left_only + cmp.right_only + cmp.diff_files]
    for sub in cmp.subdirs.values():
        out += _differs(Path(sub.left), Path(sub.right))
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    check = "--check" in argv
    rest = [a for a in argv if a != "--check"]
    src = Path(rest[0]).expanduser() if rest else HERE.parent.parent / "proseweave"
    pkg = src / "src" / "proseweave"
    if not pkg.is_dir():
        print(f"no proseweave package at {pkg}", file=sys.stderr)
        return 2
    if check:
        drift = _differs(pkg, DEST) if DEST.exists() else [str(DEST)]
        for f in ("LICENSE", "NOTICE"):
            if not filecmp.cmp(src / f, HERE / f"{f}.proseweave", shallow=False):
                drift.append(f)
        for d in drift:
            print("differs:", d)
        print("vendored copy is current" if not drift else f"{len(drift)} difference(s)")
        return 1 if drift else 0
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(pkg, DEST, ignore=IGNORE)
    shutil.copy2(src / "LICENSE", HERE / "LICENSE.proseweave")
    shutil.copy2(src / "NOTICE", HERE / "NOTICE.proseweave")
    PIN.write_text(_commit(src) + "\n", encoding="utf-8")
    print(f"vendored proseweave {PIN.read_text().strip()} -> {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
