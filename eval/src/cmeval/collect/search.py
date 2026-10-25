"""Merged PRs of a repo in a date range, through the GitHub GraphQL search.

The search returns at most 1,000 results for each query. So the range is cut into windows
(7 days by default), and a window with more results is cut in half until each part fits.
Dates are whole UTC days; both ends are included.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from datetime import date, timedelta

from ..github import GitHub, GitHubError

SEARCH_CAP = 1000
# 50, not the maximum of 100: pages with long PR bodies and commit messages made GitHub time out (502).
PAGE_SIZE = 50

# Bot accounts that are not GitHub Apps (Apps have __typename "Bot" or a "[bot]" login).
KNOWN_BOTS = frozenset({"dependabot", "renovate", "pre-commit-ci", "github-actions", "codecov", "mergify",
                        "allcontributors", "pyup-bot", "greenkeeper", "imgbot", "snyk-bot", "k8s-ci-robot"})

# The commit messages are part of the text that SWE-bench's link regex reads (collect/links.py).
PR_FIELDS = """
id
number
url
title
body
createdAt
mergedAt
baseRefName
changedFiles
mergeCommit { oid }
author { __typename login }
commits(first: 100) { totalCount nodes { commit { oid message } } }
closingIssuesReferences(first: 5) {
  totalCount
  nodes { number url createdAt body repository { nameWithOwner } }
}
"""

SEARCH_QUERY = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: %d, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest { %s } }
  }
  rateLimit { cost remaining resetAt }
}
""" % (PAGE_SIZE, PR_FIELDS)


def date_windows(since: date, until: date, days: int = 7) -> list[tuple[date, date]]:
    """Windows of `days` days from since to until, both included. The last window can be shorter."""
    if until < since:
        return []
    windows = []
    start = since
    while start <= until:
        end = min(start + timedelta(days=days - 1), until)
        windows.append((start, end))
        start = end + timedelta(days=1)
    return windows


def search_string(repo: str, base: str, start: date, end: date) -> str:
    # sort:created-asc gives a fixed order, so pages do not change between calls.
    return f"repo:{repo} is:pr is:merged base:{base} merged:{start.isoformat()}..{end.isoformat()} sort:created-asc"


def is_bot(author: dict | None, extra: Iterable[str] = ()) -> bool:
    """True for GitHub Apps, "[bot]" logins, and known bot accounts (plus `extra` logins).

    A deleted account (None) is not a bot.
    """
    if not author:
        return False
    login = (author.get("login") or "").lower()
    return (author.get("__typename") == "Bot" or login.endswith("[bot]") or login in KNOWN_BOTS
            or login in {name.lower() for name in extra})


def _pages(gh: GitHub, q: str) -> Iterator[tuple[int, list[dict]]]:
    after = None
    while True:
        result = gh.graphql(SEARCH_QUERY, {"q": q, "after": after})["search"]
        yield result["issueCount"], [n for n in result["nodes"] if n]  # non-PR nodes come back as {}
        if not result["pageInfo"]["hasNextPage"]:
            return
        after = result["pageInfo"]["endCursor"]


def _window_prs(gh: GitHub, repo: str, base: str, start: date, end: date) -> list[dict]:
    pages = _pages(gh, search_string(repo, base, start, end))
    count, first = next(pages)
    if count > SEARCH_CAP:
        if start == end:
            raise GitHubError(f"{repo}: more than {SEARCH_CAP} merged PRs on {start}; the search cannot list them all")
        middle = start + (end - start) // 2
        return (_window_prs(gh, repo, base, start, middle)
                + _window_prs(gh, repo, base, middle + timedelta(days=1), end))
    prs = list(first)
    for _, page in pages:
        prs.extend(page)
    return prs


def search_merged_prs(gh: GitHub, repo: str, base: str, since: date, until: date, *, days: int = 7,
                      progress: Callable[[str], None] = lambda message: None) -> list[dict]:
    """Every PR merged into `base` from since to until (both included), oldest window first."""
    prs: list[dict] = []
    for start, end in date_windows(since, until, days):
        prs.extend(_window_prs(gh, repo, base, start, end))
        progress(f"{repo}: {len(prs)} merged PRs up to {end}")
    return prs
