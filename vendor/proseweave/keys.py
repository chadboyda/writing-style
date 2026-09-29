"""First-run setup: connect proseweave to Jev.

Some of proseweave's measurements (word classes in context, relatedness,
familiarity and the judgement-scale properties) use TypeSafe's Jev API, which
needs an API key. This asks for one, checks it works, and stores it.

    proseweave setup                 ask for a key (input is hidden)
    proseweave check                 report status; exit 0 if a working key is set
    proseweave setup --from-stdin    read the key from stdin instead of prompting
    proseweave setup --import-env F  copy TYPESAFE_API_KEY out of an existing .env

The key is written to ~/.config/proseweave/credentials, readable only by you.
It is never printed, and nothing here sends it anywhere except TypeSafe's API.
"""
from __future__ import annotations

import argparse
import getpass
import os
import stat
import sys
from pathlib import Path

from .jev import CREDENTIALS, Jev, JevUnavailable, _read_env_file, key_sources, load_key

CONSOLE = "https://console.typesafe.ai"

INTRO = f"""
proseweave measures prose - how sentences connect, how concrete the vocabulary
is, how a rewrite compares with its original. Some measurements use TypeSafe's
Jev API, which needs a key; `--no-jev` runs without one.

Get a key at {CONSOLE}, then paste it below. Input is hidden and the key is
stored only in {CREDENTIALS} (readable by you alone).
"""


def verify(key: str) -> tuple[bool, str]:
    try:
        j = Jev(key=key)
        a = j.ask("The cat sat on the mat.",
                  {"ok": {"type": "noul", "instructions": "Does the text mention an animal?"}})
    except JevUnavailable as e:
        return False, str(e).splitlines()[0]
    except Exception as e:  # network, 5xx
        return False, f"could not reach Jev: {e}"
    return ("ok" in a), "key works"


def store(key: str) -> None:
    CREDENTIALS.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(CREDENTIALS.parent, stat.S_IRWXU)
    # Write with owner-only permissions from the first byte.
    fd = os.open(CREDENTIALS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"TYPESAFE_API_KEY={key}\n")
    os.chmod(CREDENTIALS, stat.S_IRUSR | stat.S_IWUSR)


def where_key_is() -> str | None:
    for label, read in key_sources():
        if read():
            return label
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="proseweave setup", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report status; exit 0 if a working key is set")
    ap.add_argument("--from-stdin", action="store_true", help="read the key from stdin")
    ap.add_argument("--import-env", metavar="FILE", help="copy TYPESAFE_API_KEY out of an existing .env")
    a = ap.parse_args(argv)

    if a.check:
        key = load_key()
        if not key:
            print("Jev: not set up. Run: proseweave setup")
            return 1
        ok, msg = verify(key)
        print(f"Jev: {'ready' if ok else 'NOT working'} ({msg}; key from {where_key_is()})")
        return 0 if ok else 1

    if a.import_env:
        key = _read_env_file(Path(a.import_env).expanduser(), "TYPESAFE_API_KEY")
        if not key:
            print(f"No TYPESAFE_API_KEY in {a.import_env}")
            return 1
    elif a.from_stdin:
        key = sys.stdin.readline().strip()
    else:
        existing = load_key()
        if existing:
            ok, msg = verify(existing)
            if ok:
                print(f"Jev is already set up ({where_key_is()}). Nothing to do.")
                return 0
            print(f"A key is set but it does not work ({msg}). Let's replace it.")
        print(INTRO)
        if not sys.stdin.isatty():
            print("This needs an interactive terminal. Run `proseweave setup` in one,\n"
                  "or pipe the key in with `proseweave setup --from-stdin`.")
            return 1
        key = getpass.getpass("Jev API key: ").strip()

    if not key:
        print("No key entered.")
        return 1
    ok, msg = verify(key)
    if not ok:
        print(f"That key did not work: {msg}. Nothing was saved.")
        return 1
    store(key)
    print(f"Saved. Jev is ready - the key is in {CREDENTIALS} (mode 600).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
