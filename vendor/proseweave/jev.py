"""Minimal client for TypeSafe's Jev API. Standard library only.

Jev answers typed questions (Choice, Score, Noul) about a text; proseweave uses
it for word classes in context, relatedness, familiarity and the
judgement-scale properties.

    from proseweave.jev import Jev
    j = Jev()                                # raises JevUnavailable with setup help
    answers = j.ask(state, {"q1": {...}})    # one request
    many = j.ask_many([(state, qs), ...])    # parallel, packed under the token budget

The key is looked up in this order: $TYPESAFE_API_KEY, then
~/.config/proseweave/credentials, then ./.env.
Run `proseweave setup` to be asked for one.

Set PROSEWEAVE_CACHE to a directory to cache answers on disk, keyed by the
exact request, so a rerun on the same text makes no requests.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

# Jev's published budget is 64k tokens per request for state plus all questions,
# and 32k for state plus the single longest question. Stay well inside both,
# because token counts here are an estimate.
REQUEST_BUDGET = 40_000
STATE_BUDGET = 24_000
MAX_QUESTIONS = 300
MAX_WORKERS = 12

CREDENTIALS = Path.home() / ".config" / "proseweave" / "credentials"
CACHE_DIR = Path(os.environ["PROSEWEAVE_CACHE"]) if os.environ.get("PROSEWEAVE_CACHE") else None


class JevUnavailable(RuntimeError):
    """No key, or the service cannot be reached. The message says how to fix it."""


def tokens(obj) -> int:
    """Conservative token estimate. Three characters a token: English prose runs
    nearer four, but marked-up questions and short words tokenize worse, and an
    estimate that errs low gets a request rejected rather than slowed down."""
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return len(s) // 3 + 1


class TooLarge(RuntimeError):
    pass


def _read_env_file(path: Path, name: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(name) and "=" in line:
            v = line.split("=", 1)[1].strip().strip("'\"")
            if v:
                return v
    return None


def key_sources() -> list:
    """(label, reader) pairs in lookup order."""
    return [
        ("the TYPESAFE_API_KEY environment variable",
         lambda: os.environ.get("TYPESAFE_API_KEY", "").strip() or None),
        (str(CREDENTIALS), lambda: _read_env_file(CREDENTIALS, "TYPESAFE_API_KEY")),
        (str(Path.cwd() / ".env"), lambda: _read_env_file(Path.cwd() / ".env", "TYPESAFE_API_KEY")),
    ]


def load_key() -> str | None:
    for _, read in key_sources():
        k = read()
        if k:
            return k
    return None


SETUP_HELP = (
    "No Jev API key found. Some of proseweave's measurements use TypeSafe's Jev API\n"
    "(use --no-jev to run without it).\n"
    "Run:  proseweave setup\n"
    "or set TYPESAFE_API_KEY. Keys come from https://console.typesafe.ai"
)


class Jev:
    def __init__(self, key: str | None = None, model: str = MODEL, workers: int = MAX_WORKERS):
        self.key = key or load_key()
        if not self.key:
            raise JevUnavailable(SETUP_HELP)
        self.model = model
        self.workers = workers
        self.input_tokens = 0
        self.requests = 0

    # -- one request -------------------------------------------------------
    def ask(self, state, questions: dict, retries: int = 6) -> dict:
        """Return {question_id: answer}. Answers are Jev's typed results."""
        if not questions:
            return {}
        cached = self._cache_get(state, questions)
        if cached is not None:
            return cached
        body = json.dumps({"state": state, "model": self.model, "questions": questions}).encode()
        req = urllib.request.Request(API, data=body, headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        delay = 1.0
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.loads(r.read())
                usage = data.get("usage") or {}
                self.input_tokens += int(usage.get("input_tokens") or 0)
                self.requests += 1
                answers = data.get("answers") or {}
                self._cache_put(state, questions, answers)
                return answers
            except urllib.error.HTTPError as e:
                if e.code == 401 or e.code == 403:
                    raise JevUnavailable("Jev rejected the API key (HTTP %d). " % e.code + SETUP_HELP)
                if e.code == 402:
                    raise JevUnavailable("Jev refused the request: the TypeSafe account has no API credits "
                                         "(HTTP 402). Add credits at https://console.typesafe.ai/settings/billing")
                if e.code in (429, 500, 502, 503, 504, 520, 522, 524) and attempt < retries - 1:
                    ra = e.headers.get("retry-after") if e.headers else None
                    time.sleep(float(ra) if ra and ra.replace(".", "").isdigit() else delay)
                    delay = min(delay * 2, 30)
                    continue
                detail = e.read()[:300].decode("utf-8", "replace")
                if e.code == 400 and "max_tokens" in detail:
                    raise TooLarge(detail)
                raise RuntimeError(f"Jev error {e.code}: {detail}")
            except urllib.error.URLError as e:
                if attempt < retries - 1:
                    time.sleep(delay)
                    delay = min(delay * 2, 30)
                    continue
                raise JevUnavailable(f"Jev unreachable: {e.reason}")
        raise RuntimeError("Jev: retries exhausted")

    # -- many requests -----------------------------------------------------
    def pack(self, state, questions: dict) -> list[dict]:
        """Split one state's questions into groups that fit the request budget."""
        base = tokens(state)
        if base > STATE_BUDGET:
            raise ValueError(f"state is ~{base} tokens; Jev allows {STATE_BUDGET} here - split it")
        groups, cur, used = [], {}, base
        for qid, q in questions.items():
            t = tokens(q) + 8
            if cur and (used + t > REQUEST_BUDGET or len(cur) >= MAX_QUESTIONS):
                groups.append(cur)
                cur, used = {}, base
            cur[qid] = q
            used += t
        if cur:
            groups.append(cur)
        return groups

    def ask_many(self, jobs: list[tuple]) -> list[dict]:
        """jobs: [(state, questions), ...]. Returns merged answers per job, in order.

        Questions for one state are packed into as few requests as fit, and every
        request runs in parallel - Jev evaluates questions independently, so
        splitting a job across requests changes nothing about the answers.
        """
        flat = []
        for i, (state, qs) in enumerate(jobs):
            for g in self.pack(state, qs):
                flat.append((i, state, g))
        out = [dict() for _ in jobs]
        with cf.ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = {ex.submit(self._ask_splitting, s, g): i for i, s, g in flat}
            for f in cf.as_completed(futs):
                out[futs[f]].update(f.result())
        return out

    def _ask_splitting(self, state, questions: dict) -> dict:
        """Ask; if Jev says the request is too large, halve it and try again."""
        try:
            return self.ask(state, questions)
        except TooLarge:
            if len(questions) < 2:
                raise
            items = list(questions.items())
            mid = len(items) // 2
            a = self._ask_splitting(state, dict(items[:mid]))
            a.update(self._ask_splitting(state, dict(items[mid:])))
            return a

    # -- optional answer cache ($PROSEWEAVE_CACHE) --------------------------
    def _cache_key(self, state, questions):
        blob = json.dumps([self.model, state, questions], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _cache_get(self, state, questions):
        if not CACHE_DIR:
            return None
        f = CACHE_DIR / (self._cache_key(state, questions) + ".json")
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):     # missing, unreadable or partial: a miss
            return None

    def _cache_put(self, state, questions, answers):
        if not CACHE_DIR:
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        f = CACHE_DIR / (self._cache_key(state, questions) + ".json")
        # Write beside the target, then rename: readers see the old file or the
        # whole new one, never a half-written one.
        fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, prefix=f.stem, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(json.dumps(answers))
            os.replace(tmp, f)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


# -- reading answers -------------------------------------------------------
def score_value(ans: dict, levels: int) -> float | None:
    """Expected level of a Score answer, 0..levels-1, from its probabilities."""
    if not ans:
        return None
    probs = ans.get("probabilities")
    if isinstance(probs, dict) and probs:
        tot = sum(float(v) for v in probs.values()) or 1.0
        return sum(int(k) * float(v) for k, v in probs.items()) / tot
    s = ans.get("score")
    return float(s) if s is not None else None


def noul_value(ans: dict) -> float | None:
    v = (ans or {}).get("noul")
    return float(v) if v is not None else None


def choice_value(ans: dict):
    return (ans or {}).get("choice")
