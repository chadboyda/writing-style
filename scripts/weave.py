#!/usr/bin/env python3
"""The skill's entry point to proseweave, the cohesion and readability library.

proseweave is vendored in this repository (vendor/proseweave, pinned in
vendor/PROSEWEAVE_VERSION), so nothing needs installing:

    python3 scripts/weave.py FILE [--json] [--no-jev]          every property of one text
    python3 scripts/weave.py profile SAMPLES... --out cohesion.json
    python3 scripts/weave.py compare DRAFT --baseline cohesion.json
    python3 scripts/weave.py source ORIGINAL REWRITE
    python3 scripts/weave.py setup | check                      connect Jev / is a key set?
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vendor"))

from proseweave.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
