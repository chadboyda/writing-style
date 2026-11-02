"""Minimal client for TypeSafe's Jev API. Standard library only.

Jev answers typed questions (Choice, Score, Noul) about a text; proseweave uses
it for word classes in context, relatedness, familiarity and the
judgement-scale properties.

    from proseweave.jev import Jev
    j = Jev()                                # raises JevUnavailable with setup help
    answers = j.ask(state, {"q1": {...}})    # one request
    many = j.ask_many([(state, qs), ...])    # parallel, packed under the token budget

Images: pass `assets` ({ref: image_asset(png_bytes)}) and cite each ref in the
state; the request then carries Jev's image header. Images are experimental on
TypeSafe's side.

    ref = new_ref(png)                       # derived from the bytes: stable across runs
    resp = j.ask_full({"shot": ref}, qs, assets={ref: image_asset(png, "png")})

`ask_full` returns the whole response (answers, usage, model) plus the
latency. Pass `on_usage` to see every billed request: it is called once per
request with the provider's own usage numbers, so a caller can price and
budget on what Jev reported, never on an estimate. proseweave sets no prices.

The key is looked up in this order: $TYPESAFE_API_KEY, then
~/.config/proseweave/credentials, then ./.env.
Run `proseweave setup` to be asked for one.

Set PROSEWEAVE_CACHE to a directory to cache answers on disk, keyed by the
exact request (images included), so a rerun on the same text makes no requests.
Use new_ref(bytes) for image refs: a random ref makes every request new.
"""
from __future__ import annotations

import base64
import concurrent.futures as cf
import hashlib
import json
import os
import socket
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
USER_AGENT = "proseweave (+https://github.com/chadboyda/proseweave)"
IMAGE_HEADER = "TypeSafe-Danger-Zone-Images"   # Jev reads image assets only with this header set
IMAGE_FORMATS = ("png", "jpg")

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


def new_ref(data: bytes | None = None) -> str:
    """An asset reference to cite in the state. Given the image bytes, the ref is
    derived from them, so the same image gets the same ref on every run and the
    answer cache can hit; with no bytes it is a fresh random id."""
    if data is not None:
        return "img-" + hashlib.sha256(data).hexdigest()[:32]
    return str(uuid.uuid4())


def image_asset(data: bytes, fmt: str = "png") -> dict:
    """Encoded image bytes -> one Jev image asset. Jev wants each side >= 280 px;
    resizing is the caller's job (proseweave has no image library)."""
    fmt = "jpg" if fmt.lower() in ("jpg", "jpeg") else fmt.lower()
    if fmt not in IMAGE_FORMATS:
        raise ValueError(f"image format {fmt!r}: Jev takes {IMAGE_FORMATS}")
    return {"type": "image", "format": fmt, "data_base64": base64.b64encode(data).decode("ascii")}


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
    def __init__(self, key: str | None = None, model: str = MODEL, workers: int = MAX_WORKERS,
                 on_usage=None, user_agent: str = USER_AGENT, timeout: float = 120):
        """on_usage(event) runs after every billed request (never for a cache hit) with
        {"model", "usage", "input_tokens", "latency_s", "questions", "images", "tag"};
        usage is the provider's dict exactly as returned. An exception it raises
        propagates, so a budget check there stops the caller."""
        self.key = key or load_key()
        if not self.key:
            raise JevUnavailable(SETUP_HELP)
        self.model = model
        self.workers = workers
        self.on_usage = on_usage
        self.user_agent = user_agent
        self.timeout = timeout
        self.input_tokens = 0
        self.requests = 0

    # -- one request -------------------------------------------------------
    def ask(self, state, questions: dict, retries: int = 6, assets: dict | None = None, tag: str = "") -> dict:
        """Return {question_id: answer}. Answers are Jev's typed results."""
        return self.ask_full(state, questions, retries=retries, assets=assets, tag=tag)["answers"]

    def ask_full(self, state, questions: dict, retries: int = 6, assets: dict | None = None,
                 tag: str = "") -> dict:
        """The whole response: {"answers", "usage", "model", ...} plus "latency_s" and "cached".
        A cache hit has usage {} and cached True."""
        if not questions:
            return {"answers": {}, "usage": {}, "model": None, "latency_s": 0.0, "cached": False}
        cached = self._cache_get(state, questions, assets)
        if cached is not None:   # the cache keeps answers only: the answering model is unknown here
            return {"answers": cached, "usage": {}, "model": None, "latency_s": 0.0, "cached": True}
        payload = {"state": state, "model": self.model, "questions": questions}
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                   "User-Agent": self.user_agent}
        if assets:
            payload["assets"] = assets
            headers[IMAGE_HEADER] = "true"
        req = urllib.request.Request(API, data=json.dumps(payload).encode(), headers=headers)
        delay = 1.0
        for attempt in range(retries):
            try:
                t0 = time.perf_counter()
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read())
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
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
                # a slow reply raises a bare timeout (urllib wraps only the connect in URLError): retry it too
                if attempt < retries - 1:
                    time.sleep(delay)
                    delay = min(delay * 2, 30)
                    continue
                raise JevUnavailable(f"Jev unreachable: {getattr(e, 'reason', None) or e!r}")
            else:
                # outside the try: an error in the hook (its own network call) must not resend a paid request
                latency = time.perf_counter() - t0
                usage = data.get("usage") or {}
                billed = int(usage.get("input_tokens") or 0)
                self.input_tokens += billed
                self.requests += 1
                answers = data.get("answers") or {}
                self._cache_put(state, questions, answers, assets)   # paid for: keep it even if the hook stops us
                if self.on_usage is not None:
                    self.on_usage({"model": data.get("model") or self.model, "usage": usage,
                                   "input_tokens": billed, "latency_s": latency, "questions": len(questions),
                                   "images": len(assets or {}), "tag": tag})
                data["answers"] = answers
                data["latency_s"] = latency
                data["cached"] = False
                return data
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
        ex = cf.ThreadPoolExecutor(max_workers=self.workers)
        try:
            futs = {ex.submit(self._ask_splitting, s, g): i for i, s, g in flat}
            for f in cf.as_completed(futs):
                out[futs[f]].update(f.result())
        except BaseException:
            # one failure (a budget stop in on_usage, a bad key) ends the batch: queued
            # requests are cancelled instead of being sent and billed
            ex.shutdown(wait=True, cancel_futures=True)
            raise
        ex.shutdown(wait=True)
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
    def _cache_key(self, state, questions, assets=None):
        # Without assets the key is what it always was, so existing caches stay valid.
        parts = [self.model, state, questions] + ([assets] if assets else [])
        blob = json.dumps(parts, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _cache_get(self, state, questions, assets=None):
        if not CACHE_DIR:
            return None
        f = CACHE_DIR / (self._cache_key(state, questions, assets) + ".json")
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):     # missing, unreadable or partial: a miss
            return None

    def _cache_put(self, state, questions, answers, assets=None):
        if not CACHE_DIR:
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        f = CACHE_DIR / (self._cache_key(state, questions, assets) + ".json")
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
