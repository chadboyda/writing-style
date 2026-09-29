"""proseweave command line.

    proseweave FILE [--json] [--no-jev]              every property of one text
    proseweave analyze FILE [--json] [--no-jev]      the same, spelled out
    proseweave profile SAMPLES... --out prof.json    the author's observed ranges
    proseweave compare DRAFT --baseline prof.json    where a draft leaves them
    proseweave source SOURCE TARGET                  source-comparison properties
    proseweave cadence FILE [--json] [--window N]    cadence measurements (no key)
    proseweave setup                                 store a Jev API key
    proseweave check                                 is a working key set?

Exit status of compare: 0 nothing outside range, 1 something to reread,
2 no Jev key or usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from . import analysis
from . import cadence
from . import keys
from . import source as source_mod
from .jev import Jev, JevUnavailable

COMMANDS = ("analyze", "profile", "compare", "source", "cadence", "setup", "check")


def _jev_or_none():
    try:
        return Jev()
    except JevUnavailable as e:
        print(str(e), file=sys.stderr)
        return None


def _read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="proseweave", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"proseweave {__version__}")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")

    pa = sub.add_parser("analyze", help="every property of one text (the default)")
    pa.add_argument("file")
    pa.add_argument("--json", action="store_true")
    pa.add_argument("--no-jev", action="store_true", help="only the properties that need no key")

    pp = sub.add_parser("profile", help="observed ranges over the author's samples")
    pp.add_argument("files", nargs="+")
    pp.add_argument("--out", required=True)

    pc = sub.add_parser("compare", help="where a draft leaves those ranges")
    pc.add_argument("draft")
    pc.add_argument("--baseline", required=True)
    pc.add_argument("--all", action="store_true", help="every flag, not the two strongest per family")
    pc.add_argument("--json", action="store_true")

    ps = sub.add_parser("source", help="source-comparison properties of TARGET against SOURCE")
    ps.add_argument("source")
    ps.add_argument("target")

    pk = sub.add_parser("cadence", help="cadence measurements: sentence and paragraph rhythm (no key)")
    pk.add_argument("file")
    pk.add_argument("--json", action="store_true", help="every measurement (the default prints a summary)")
    pk.add_argument("--window", type=int, default=cadence.WINDOW, help="rolling window, in sentences (default 5)")

    sub.add_parser("setup", help="store a Jev API key (see `proseweave setup --help`)", add_help=False)
    sub.add_parser("check", help="report whether a working Jev key is set")
    return ap


def _analyze(a) -> int:
    j = None
    if not a.no_jev:
        j = _jev_or_none()
        if j is None:
            return 2
    an = analysis.Analysis(_read(a.file), j)
    res = an.properties()
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        for k, v in res.items():
            print(f"{k:<30} {v:.4f}" if isinstance(v, float) else f"{k:<30} {v}")
    return 0


def _profile(a) -> int:
    j = _jev_or_none()
    if j is None:
        return 2
    prof = analysis.profile([_read(f) for f in a.files], j)
    Path(a.out).write_text(json.dumps(prof, indent=1) + "\n", encoding="utf-8")
    print(f"{len(prof['range'])} properties profiled over {prof['samples']} samples -> {a.out}")
    return 0


def _compare(a) -> int:
    j = _jev_or_none()
    if j is None:
        return 2
    prof = json.loads(_read(a.baseline))
    flags = analysis.compare(_read(a.draft), prof, j)
    if a.json:
        print(json.dumps(flags, indent=1))
    else:
        # Many indices in one family move together (108 are word-overlap
        # variants), so the default view shows the two strongest per family.
        if a.all:
            shown = flags
        else:
            seen, shown = {}, []
            for f in flags:
                seen[f["family"]] = seen.get(f["family"], 0) + 1
                if seen[f["family"]] <= 2:
                    shown.append(f)
        for f in shown:
            print(f"{f['side']:<5} {f['property']:<36} {f['value']:.3f} vs their "
                  f"{f['range'][0]:.3f}-{f['range'][1]:.3f}  ({f['question']})")
        if len(flags) > len(shown):
            print(f"... {len(flags) - len(shown)} more (--all)")
        if not flags:
            print("inside the author's observed range on every validated property")
    return 1 if flags else 0


def _source(a) -> int:
    j = _jev_or_none()
    if j is None:
        return 2
    s = analysis.Analysis(_read(a.source), j)
    t = analysis.Analysis(_read(a.target), j)
    print(json.dumps(source_mod.compare(j, s, t), indent=1))
    return 0


def _cadence(a) -> int:
    if a.window < 2:
        print("--window must be at least 2", file=sys.stderr)
        return 2
    m = cadence.measure(_read(a.file), window=a.window)
    print(json.dumps(m, separators=(",", ":")) if a.json else cadence.format_text(m))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "setup":
        return keys.main(argv[1:])
    if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "analyze")
    ap = _parser()
    a = ap.parse_args(argv)
    if a.cmd is None:
        ap.print_help()
        return 2
    if a.cmd == "check":
        return keys.main(["--check"])
    return {"analyze": _analyze, "profile": _profile, "compare": _compare, "source": _source,
            "cadence": _cadence}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
