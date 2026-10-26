"""Issues as they were when the fix PR was opened (Decision 8), and the query built from them.

GitHub keeps every version of an issue body (`userContentEdits`, newest first; `diff` holds the
full text of that version, and the oldest entry is the original). Title changes are "renamed"
events. So we can rebuild the title and body at any moment. A later edit can describe the fix,
so the query uses the versions from just before the fix PR was opened.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..github import GitHub
from ..tasks import clean_query
from .search import is_bot

BATCH_SIZE = 50  # 50 issues with history and comments cost 2 GraphQL points

ISSUE_FIELDS = """
__typename
... on Issue {
  number
  url
  title
  body
  createdAt
  userContentEdits(first: 100) { totalCount nodes { editedAt deletedAt diff } }
  timelineItems(first: 50, itemTypes: [RENAMED_TITLE_EVENT]) {
    totalCount
    nodes { ... on RenamedTitleEvent { createdAt previousTitle currentTitle } }
  }
  comments(first: 100) { totalCount nodes { createdAt author { __typename login } body } }
}
"""

_SHA_WORD_RE = re.compile(r"\b[0-9a-f]{7,40}\b")


def issues_query(repo: str, numbers: list[int]) -> str:
    owner, name = repo.split("/")
    parts = [f"i{n}: issueOrPullRequest(number: {n}) {{ {ISSUE_FIELDS} }}" for n in numbers]
    return ('query { rateLimit { cost remaining } repository(owner: "%s", name: "%s") { %s } }'
            % (owner, name, "\n".join(parts)))


def fetch_issues(gh: GitHub, repo: str, numbers: Iterable[int], batch: int = BATCH_SIZE) -> dict[int, dict | None]:
    """Number -> issue (or a {"__typename": "PullRequest"} for a PR), None when GitHub has nothing.

    Numbers are sorted, so the same set gives the same batches and the cache answers a second run.
    """
    wanted = sorted(set(numbers))
    found: dict[int, dict | None] = {}
    for start in range(0, len(wanted), batch):
        part = wanted[start:start + batch]
        repository = gh.graphql(issues_query(repo, part), allow_missing=True).get("repository") or {}
        for n in part:
            found[n] = repository.get(f"i{n}")
    return found


def body_at(issue: dict, when: str) -> tuple[str, bool, bool]:
    """(body at `when`, edited after `when`, that version's text is missing). Times are ISO 8601 UTC strings.

    With no edit after `when`, the current body is the body at `when`. Older versions are not
    needed then; that matters because GitHub did not store the text of edits from before
    about 2018 (their `diff` is null).
    """
    edits = sorted((e for e in issue["userContentEdits"]["nodes"] if e.get("editedAt")),
                   key=lambda e: e["editedAt"])
    if not any(e["editedAt"] > when for e in edits):
        return issue.get("body") or "", False, False
    before = [e for e in edits if e["editedAt"] <= when]
    version = before[-1] if before else edits[0]  # no version before `when`: use the oldest one
    missing = version.get("deletedAt") is not None or version.get("diff") is None
    return version.get("diff") or "", True, missing


def title_at(issue: dict, when: str) -> tuple[str, bool]:
    """(title at `when`, renamed after `when`)."""
    renames = sorted((n for n in issue["timelineItems"]["nodes"] if n), key=lambda n: n["createdAt"])
    later = [n for n in renames if n["createdAt"] > when]
    if later:
        return later[0]["previousTitle"], True
    return issue["title"], False


def hints_before(issue: dict, when: str, extra_bots: Iterable[str] = ()) -> str | None:
    """Comments by people (not bots) created before `when`, hidden comments removed. Stored, not used."""
    texts = [clean_query(c.get("body")) for c in issue["comments"]["nodes"]
             if c["createdAt"] < when and not is_bot(c.get("author"), extra_bots)]
    texts = [t for t in texts if t]
    return "\n\n".join(texts) or None


def build_query(title: str, body: str) -> str:
    """The issue title and body in the task format ("<title>\\n\\n<body>"), hidden comments removed."""
    return f"{title.strip()}\n\n{clean_query(body)}".strip()


def leak(query: str, pr: dict) -> str | None:
    """Why the query gives away the fix, or None: it names the fix PR or a commit of the fix.

    A PR is named as #N, as a /pull/N link, or as gh-N or GH-N (the form cpython uses).
    """
    number = pr["number"]
    if re.search(rf"(?<![\w&])#{number}\b|/pull/{number}\b|(?<![\w-])gh-{number}\b", query, re.IGNORECASE):
        return f"mentions the fix PR #{number}"
    shas = [c["commit"]["oid"] for c in (pr.get("commits") or {}).get("nodes") or []]
    if pr.get("mergeCommit"):
        shas.append(pr["mergeCommit"]["oid"])
    for word in _SHA_WORD_RE.findall(query.lower()):
        if any(sha.startswith(word) for sha in shas):
            return f"mentions the fix commit {word}"
    return None
