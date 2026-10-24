"""GitHub API access through the `gh` command line, with an on-disk response cache.

`gh` holds the login, so no token goes into our code or files. Each response is stored as one
JSON file named by the sha256 of the request, so a second run of the same request needs no
network. The collector asks for fixed date windows, so a cached answer stays correct. Use
refresh=True to ask GitHub again.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from .files import write_json
from .paths import gh_cache_dir

# Stop before GitHub stops us. A GraphQL search page costs 1 point of 5,000 per hour.
MIN_REMAINING = 200
# Space live calls a little: GitHub has secondary limits on bursts of requests.
DEFAULT_MIN_INTERVAL = 0.25

Runner = Callable[[list[str], str | None], str]


class GitHubError(RuntimeError):
    """A gh call failed, GitHub returned errors, or the rate limit is almost used up."""


def gh_runner(args: list[str], stdin: str | None) -> str:
    """Run `gh` with args and return its stdout."""
    try:
        proc = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True)
    except FileNotFoundError:
        raise GitHubError("the gh command is not installed (https://cli.github.com)") from None
    if proc.returncode != 0:
        raise GitHubError(f"gh {' '.join(args[:2])} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def cache_key(kind: str, request: str, variables: dict | None = None) -> str:
    text = json.dumps([kind, request, variables or {}], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class GitHub:
    def __init__(self, runner: Runner | None = None, cache_dir: Path | None = None,
                 min_interval: float = DEFAULT_MIN_INTERVAL, refresh: bool = False):
        self.runner = runner or gh_runner
        self.cache_dir = cache_dir or gh_cache_dir()
        self.min_interval = min_interval
        self.refresh = refresh
        self.api_calls = 0
        self.cache_hits = 0
        self._last_call = 0.0

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        """The `data` part of a GraphQL response. Add `rateLimit { remaining }` to the query to guard the limit."""
        body = json.dumps({"query": query, "variables": variables or {}})
        response = self._cached("graphql", query, variables, ["api", "graphql", "--input", "-"], body)
        if response.get("errors"):
            messages = "; ".join(e.get("message", str(e)) for e in response["errors"])
            raise GitHubError(f"GraphQL errors: {messages}")
        data = response.get("data") or {}
        remaining = (data.get("rateLimit") or {}).get("remaining")
        if remaining is not None and remaining < MIN_REMAINING:
            raise GitHubError(f"GraphQL rate limit almost used up ({remaining} points left); run again after the reset")
        return data

    def rest(self, path: str):
        """The parsed JSON of a REST GET, for example rest("repos/home-assistant/core")."""
        return self._cached("rest", path, None, ["api", path], None)

    def _cached(self, kind: str, request: str, variables: dict | None, args: list[str], stdin: str | None):
        path = self.cache_dir / f"{cache_key(kind, request, variables)}.json"
        if path.exists() and not self.refresh:
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        wait = self._last_call + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
        out = self.runner(args, stdin)
        self.api_calls += 1
        try:
            response = json.loads(out)
        except json.JSONDecodeError:
            raise GitHubError(f"gh {' '.join(args[:2])} returned text that is not JSON: {out[:200]!r}") from None
        if kind == "graphql" and response.get("errors"):
            return response  # never cache an error
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        write_json(path, {"kind": kind, "request": request, "variables": variables, "response": response})
        return response
