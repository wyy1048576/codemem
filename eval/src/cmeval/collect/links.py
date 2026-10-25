"""Which issue does a PR fix? Two methods, both run on every PR.

- "list": GitHub's own record (`closingIssuesReferences`). GitHub fills it from closing words in
  the PR description and from links set by hand on the PR page.
- "regex": SWE-bench's rule (`extract_resolved_issues` in swebench/collect/utils.py). It reads
  the PR title, the PR body, and the messages of all PR commits, removes HTML comments, and
  keeps "<word> #N" and "<word> <repo issue URL>N" where the word is a closing keyword.

Each link records which method found it, so the report can say how the task set relates to
SWE-bench's method, and a strict SWE-bench subset is one filter.
"""

from __future__ import annotations

import re

# Same set as SWE-bench's PR_KEYWORDS.
PR_KEYWORDS = frozenset({"close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"})
_COMMENTS_RE = re.compile(r"(?s)<!--.*?-->")


def issues_pattern(repo: str) -> re.Pattern:
    """SWE-bench's pattern: a word, white space, then "#" or the repo's issue URL, then the number."""
    markers = [r"\#", re.escape(f"https://github.com/{repo}/issues/")]
    return re.compile(rf"(\w+)\s+(?:{'|'.join(markers)})(\d+)")


def pr_text(pr: dict) -> str:
    """Title, body, and commit messages, as SWE-bench joins them, without HTML comments."""
    text = pr.get("title") or ""
    text += "\n" + (pr.get("body") or "")
    commits = (pr.get("commits") or {}).get("nodes") or []
    text += "\n" + "\n".join(node["commit"]["message"] for node in commits)
    return _COMMENTS_RE.sub("", text)


def regex_links(pr: dict, repo: str) -> set[int]:
    return {int(number) for word, number in issues_pattern(repo).findall(pr_text(pr))
            if word.lower() in PR_KEYWORDS}


def list_links(pr: dict, repo: str) -> set[int]:
    """Issues in GitHub's closing list that are in the same repo."""
    nodes = (pr.get("closingIssuesReferences") or {}).get("nodes") or []
    return {node["number"] for node in nodes if node["repository"]["nameWithOwner"].lower() == repo.lower()}


def find_links(pr: dict, repo: str) -> dict[int, str]:
    """Issue number -> "list", "regex", or "both", over the union of the two methods."""
    by_list, by_regex = list_links(pr, repo), regex_links(pr, repo)
    return {number: "both" if number in by_list and number in by_regex else "list" if number in by_list else "regex"
            for number in sorted(by_list | by_regex)}
