"""Token cost of search results (Decision 6).

Tokens are counted with Anthropic's count_tokens endpoint for the agent-study model, so offline
numbers use the same ruler as the agent study. Only hit text is counted: the fixed overhead of a
request is measured once and subtracted. Every text is counted once and cached on disk by its
sha256, so scoring again needs no network. The API key comes from ANTHROPIC_API_KEY or the macOS
Keychain entry "anthropic-api-key"; it is never printed or written to a file.
"""

from __future__ import annotations

import getpass
import hashlib
import math
import os
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Protocol

from ..paths import token_cache_dir

DEFAULT_MODEL = "claude-opus-5-5"
BUDGETS = (500, 1000, 2000, 4000, 8000)
KEYCHAIN_SERVICE = "anthropic-api-key"
CHARS_PER_TOKEN = 3.5  # rough estimate only; never reported
# count_tokens has a requests-per-minute limit for each organization. The project key allows
# 3,000 or more (12,000 requests in 36 seconds with no refusal, 2026-10-24). Some accounts allow
# only 100 per minute (seen 2026-10-23): for such a key, set CMEVAL_TOKEN_RPM=90.
DEFAULT_RPM = 3000


def configured_rpm() -> int:
    value = os.environ.get("CMEVAL_TOKEN_RPM", str(DEFAULT_RPM))
    if not value.isdigit() or int(value) < 1:
        raise TokenCountError(f"CMEVAL_TOKEN_RPM must be a whole number of requests per minute, got {value!r}")
    return int(value)


class TokenCountError(RuntimeError):
    """count_tokens failed (no key accepted, no network, API error). Scoring stops."""


class TokenCounter(Protocol):
    name: str
    estimate: bool  # True: rough numbers, marked "estimate" and never reported

    def count(self, texts: list[str]) -> list[int]: ...


class EstimateCounter:
    name = "estimate"
    estimate = True

    def count(self, texts: list[str]) -> list[int]:
        return [math.ceil(len(t) / CHARS_PER_TOKEN) for t in texts]


def find_api_key() -> str | None:
    """ANTHROPIC_API_KEY, else the macOS Keychain entry. None if neither exists."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    if sys.platform == "darwin":
        proc = subprocess.run(
            ["security", "find-generic-password", "-a", getpass.getuser(), "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _RateLimiter:
    """Spaces calls so at most rpm start in any minute. Shared by all worker threads."""

    def __init__(self, rpm: int):
        self.interval = 60.0 / rpm if rpm > 0 else 0.0
        self.lock = threading.Lock()
        self.next = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next)
            self.next = start + self.interval
        if start > now:
            time.sleep(start - now)


class AnthropicCounter:
    estimate = False

    def __init__(self, model: str = DEFAULT_MODEL, *, api_key: str | None = None, client=None,
                 cache_dir: Path | None = None, workers: int = 4, rpm: int | None = None,
                 progress: Callable[[str], None] = lambda message: None):
        self.model = model
        self.name = f"anthropic:{model}"
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, max_retries=5)  # retries 429 and 5xx
        self.client = client
        self.workers = workers
        self.limiter = _RateLimiter(configured_rpm() if rpm is None else rpm)
        self.progress = progress
        cache_dir = cache_dir or token_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cache_dir / f"{model}.sqlite")
        self.db.execute("CREATE TABLE IF NOT EXISTS counts (sha TEXT PRIMARY KEY, tokens INTEGER NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.commit()
        self.api_calls = 0
        self._overhead: int | None = None

    def _count_raw(self, text: str) -> int:
        """Input tokens of one user message holding text, as the API reports them (overhead included).

        The API refuses a message of whitespace only, so such a text is counted after an "a"
        (1 token) and the "a" is taken off again.
        """
        if not text.strip():
            return self._count_raw("a" + text) - 1
        self.limiter.wait()
        try:
            response = self.client.messages.count_tokens(model=self.model, messages=[{"role": "user", "content": text}])
        except Exception as exc:  # the SDK's typed errors; never include the key
            raise TokenCountError(
                f"count_tokens failed ({type(exc).__name__}: {exc}). Check the API key and network, "
                "or score with --tokens estimate (marked, never reported)."
            ) from None
        self.api_calls += 1
        return response.input_tokens

    @property
    def overhead(self) -> int:
        """Tokens the API adds around any message: count("a") - 1, measured once and cached."""
        if self._overhead is None:
            row = self.db.execute("SELECT value FROM meta WHERE key = 'overhead'").fetchone()
            if row:
                self._overhead = int(row[0])
            else:
                self._overhead = self._count_raw("a") - 1
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('overhead', ?)", (str(self._overhead),))
                self.db.commit()
        return self._overhead

    def count(self, texts: list[str]) -> list[int]:
        overhead = self.overhead
        shas = {t: _sha(t) for t in dict.fromkeys(texts) if t}  # unique, in input order
        cached = {}
        for sha in shas.values():
            row = self.db.execute("SELECT tokens FROM counts WHERE sha = ?", (sha,)).fetchone()
            if row:
                cached[sha] = row[0]
        missing = [t for t, sha in shas.items() if sha not in cached]
        if missing:
            self.progress(f"counting tokens for {len(missing)} new texts ({len(shas) - len(missing)} cached)")

            def save(text: str, raw: int) -> None:
                cached[shas[text]] = max(0, raw - overhead)
                # Saved at once: an interrupted run keeps every count it already paid for.
                self.db.execute("INSERT OR REPLACE INTO counts VALUES (?, ?)", (shas[text], cached[shas[text]]))

            saved: set = set()
            error: BaseException | None = None
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                futures = {pool.submit(self._count_raw, text): text for text in missing}
                try:
                    for done, future in enumerate(as_completed(futures), start=1):
                        save(futures[future], future.result())
                        saved.add(future)
                        if done % 50 == 0 or done == len(missing):
                            self.db.commit()
                            self.progress(f"counted {done}/{len(missing)}")
                except BaseException as exc:
                    for future in futures:
                        future.cancel()  # requests not started yet are dropped
                    error = exc
            # The pool has shut down, so every request that was running has finished. Keep the
            # ones that succeeded after the failure, too: they were already paid for.
            if error is not None:
                for future, text in futures.items():
                    if future not in saved and not future.cancelled() and future.exception() is None:
                        save(text, future.result())
            self.db.commit()
            if error is not None:
                raise error
        return [cached[shas[t]] if t else 0 for t in texts]

    def close(self) -> None:
        self.db.close()


def make_counter(kind: str, warn=lambda message: None, progress=lambda message: None) -> TokenCounter:
    """"anthropic" (needs an API key) or "estimate" (rough, only when asked for by name).

    No key with "anthropic" is an error, not a quiet fallback: a fallback would replace real
    token numbers from an earlier scoring with estimates.
    """
    if kind == "estimate":
        warn("token numbers are estimates: never report them")
        return EstimateCounter()
    if kind != "anthropic":
        raise ValueError(f"token counter {kind!r} must be 'anthropic' or 'estimate'")
    key = find_api_key()
    if key is None:
        raise TokenCountError(
            "no Anthropic API key: set ANTHROPIC_API_KEY or add the macOS Keychain entry 'anthropic-api-key'. "
            "Or score with --tokens estimate (marked, never reported)."
        )
    return AnthropicCounter(api_key=key, progress=progress)


def token_metrics(hit_tokens: list[int], relevance: list[set[int]], n_gold: int,
                  budgets: tuple[int, ...] = BUDGETS) -> dict[str, float | None]:
    """tokens_to_first, found, and recall@budget<B>, over the raw hits in rank order."""
    out: dict[str, float | None] = {}
    total = 0
    out["tokens_to_first"], out["found"] = None, 0.0
    for tokens, rel in zip(hit_tokens, relevance):
        total += tokens
        if rel:
            out["tokens_to_first"], out["found"] = float(total), 1.0
            break
    for budget in budgets:
        spent, found = 0, set()
        for tokens, rel in zip(hit_tokens, relevance):
            if spent + tokens > budget:
                break  # whole hits only
            spent += tokens
            found |= rel
        out[f"recall@budget{budget}"] = len(found) / n_gold
    return out
