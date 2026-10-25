"""GitHub API access through the `gh` command line, with an on-disk response cache.

`gh` holds the login, so no token goes into our code or files. Each response is stored as one
JSON file named by the sha256 of the request, so a second run of the same request needs no
network. The collector asks for fixed date windows, so a cached answer stays correct. Use
refresh=True to ask GitHub again.

A long collection run meets short GitHub failures (502, 504, time-outs, secondary rate limits).
Those are tried again a few times, and each try is reported through `progress`. All other
errors stop at once.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from .files import write_json
from .paths import gh_cache_dir

# Stop before GitHub stops us. A GraphQL search page costs 1 to 2 points of 5,000 per hour.
MIN_REMAINING = 200
# Space live calls a little: GitHub has secondary limits on bursts of requests.
DEFAULT_MIN_INTERVAL = 0.25
DEFAULT_TRIES = 4
RETRY_WAITS = (15, 60, 120)  # seconds before the second, third, and fourth try
_TRANSIENT_RE = re.compile(r"HTTP 50[234]|secondary rate limit|timed out|timeout|connection reset|unexpected EOF"
                           r"|unexpected end of JSON input",
                           re.IGNORECASE)

Runner = Callable[[list[str], str | None], str]


class GitHubError(RuntimeError):
    """A gh call failed, GitHub returned errors, or the rate limit is almost used up."""


def gh_runner(args: list[str], stdin: str | None) -> str:
    """Run `gh` with args and return its stdout.

    gh exits with 1 when a GraphQL answer has errors, even when the answer also has data (for
    example one missing issue in a batch). Such an answer is returned, and the caller decides.
    """
    try:
        proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True)
    except FileNotFoundError:
        raise GitHubError("the gh command is not installed (https://cli.github.com)") from None
    if proc.returncode != 0:
        try:
            answer = json.loads(proc.stdout)
        except json.JSONDecodeError:
            answer = None
        if isinstance(answer, dict) and "data" in answer:
            return proc.stdout
        raise GitHubError(f"gh {' '.join(args[:2])} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def cache_key(kind: str, request: str, variables: dict | None = None) -> str:
    text = json.dumps([kind, request, variables or {}], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class GitHub:
    def __init__(self, runner: Runner | None = None, cache_dir: Path | None = None,
                 min_interval: float = DEFAULT_MIN_INTERVAL, refresh: bool = False, tries: int = DEFAULT_TRIES,
                 progress: Callable[[str], None] = lambda message: None,
                 sleep: Callable[[float], None] = time.sleep):
        self.runner = runner or gh_runner
        self.cache_dir = cache_dir or gh_cache_dir()
        self.min_interval = min_interval
        self.refresh = refresh
        self.tries = tries
        self.progress = progress
        self.sleep = sleep
        self.api_calls = 0
        self.cache_hits = 0
        self.retries = 0
        self._last_call = 0.0

    def graphql(self, query: str, variables: dict | None = None, *, allow_missing: bool = False) -> dict:
        """The `data` part of a GraphQL response. Add `rateLimit { remaining }` to the query to guard the limit.

        allow_missing=True accepts NOT_FOUND errors (for example a deleted issue in a batch): the
        missing parts are None in the data. All other errors raise GitHubError.
        """
        body = json.dumps({"query": query, "variables": variables or {}})

        def errors(response: dict) -> list[dict]:
            return [e for e in response.get("errors") or []
                    if not (allow_missing and e.get("type") == "NOT_FOUND")]

        response, cached = self._cached("graphql", query, variables, ["api", "graphql", "--input", "-"], body,
                                        keep=lambda r: not errors(r))
        if errors(response):
            messages = "; ".join(e.get("message", str(e)) for e in errors(response))
            raise GitHubError(f"GraphQL errors: {messages}")
        data = response.get("data") or {}
        remaining = (data.get("rateLimit") or {}).get("remaining")
        # Only a live answer tells how many points are left now; a cached one tells the past.
        if not cached and remaining is not None and remaining < MIN_REMAINING:
            raise GitHubError(f"GraphQL rate limit almost used up ({remaining} points left); run again after the reset")
        return data

    def rest(self, path: str):
        """The parsed JSON of a REST GET, for example rest("repos/home-assistant/core")."""
        return self._cached("rest", path, None, ["api", path], None, keep=lambda r: True)[0]

    def _cached(self, kind: str, request: str, variables: dict | None, args: list[str], stdin: str | None,
                keep: Callable[[object], bool]) -> tuple[object, bool]:
        """(response, True if it came from the cache)."""
        path = self.cache_dir / f"{cache_key(kind, request, variables)}.json"
        if path.exists() and not self.refresh:
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["response"], True
        response = self._call(args, stdin)
        if keep(response):  # never cache an error answer
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            write_json(path, {"kind": kind, "request": request, "variables": variables, "response": response})
        return response, False

    def _call(self, args: list[str], stdin: str | None):
        """The parsed answer of one live call, with retries for short failures."""
        for attempt in range(1, self.tries + 1):
            wait = self._last_call + self.min_interval - time.monotonic()
            if wait > 0:
                self.sleep(wait)
            self._last_call = time.monotonic()
            try:
                out = self.runner(args, stdin)
                try:
                    response = json.loads(out)
                except json.JSONDecodeError:
                    raise GitHubError(f"gh {' '.join(args[:2])} returned text that is not JSON: {out[:200]!r}") from None
                # GitHub can also report a time-out inside an answer ("Something went wrong ... timeout").
                errors = response.get("errors") if isinstance(response, dict) else None
                messages = [e.get("message", "") for e in errors or [] if e.get("type") != "NOT_FOUND"]
                if any(_TRANSIENT_RE.search(m) for m in messages):
                    raise GitHubError(f"GraphQL errors: {'; '.join(messages)}")
            except GitHubError as exc:
                if attempt == self.tries or not _TRANSIENT_RE.search(str(exc)):
                    raise
                pause = RETRY_WAITS[min(attempt - 1, len(RETRY_WAITS) - 1)]
                self.retries += 1
                self.progress(f"GitHub: {exc}; trying again in {pause} s (try {attempt + 1} of {self.tries})")
                self.sleep(pause)
                continue
            self.api_calls += 1
            return response
        raise AssertionError("unreachable")
