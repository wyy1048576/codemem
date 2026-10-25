"""From merged PRs to candidates: a PR, its one linked issue, and the query (F4 B1).

`cmeval collect` runs these steps for each repo in a collection config. A funnel keeps the count
after each step and the reason for each PR it drops (the "yield funnel" for the report). B2
reads the candidates, adds the base commit, the patch, and the labels, and writes the tasks.
"""

from __future__ import annotations

import json
import tomllib
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from ..files import write_json, write_text_atomic
from ..github import GitHub
from ..tasks import clean_query
from .issues import body_at, build_query, fetch_issues, hints_before, leak, title_at
from .links import find_links
from .repo_stats import Candidate as RepoEntry
from .repo_stats import RepoStatsError, load_candidates
from .search import is_bot, search_merged_prs

GITHUB_STEPS = (
    ("merged", "merged into the default branch in the date range"),
    ("opened_after_cutoff", "the fix PR was opened on or after the start date (its code was not public before)"),
    ("not_bot", "author is not a bot"),
    ("one_link", "links exactly one issue in the same repo (GitHub's list or the SWE-bench regex)"),
    ("is_issue", "the link is an issue that exists (not a PR)"),
    ("issue_before_pr", "the issue was opened before the fix PR (not written after the fix)"),
    ("body_ok", "body (as of when the fix PR was opened) has the minimum length"),
    ("no_leak", "query does not name the fix PR or a fix commit"),
)
# B2, in tasks_build.py: these need the full clone.
GIT_STEPS = (
    ("base_found", "base commit found from the merge type (Decision 7)"),
    ("files_match", "our patch touches exactly the PR's files"),
    ("applies", "the code patch applies at the base commit"),
    ("size_ok", "1 to max_code_files code files and at most max_code_lines changed code lines"),
    ("labeled", "labeled, with at least one gold file that exists at the base commit"),
)
FUNNEL_STEPS = GITHUB_STEPS + GIT_STEPS


class CollectError(RuntimeError):
    """A bad collection config."""


@dataclass
class Settings:
    name: str  # the config file name without .toml, for example fresh-v1
    since: date
    until: date
    min_body_chars: int = 100
    extra_bots: list[str] = field(default_factory=list)
    max_code_files: int = 5
    max_code_lines: int = 200
    repos: list[RepoEntry] = field(default_factory=list)


@dataclass
class Candidate:
    repo: str
    pr_number: int
    pr_url: str
    pr_created_at: str
    merged_at: str
    base_ref: str
    merge_commit: str | None
    commit_oids: list[str]
    commit_subjects: list[str]  # first message lines, oldest first; B2 uses them to find a rebase merge
    commits_total: int
    changed_files: int
    issue_number: int
    issue_url: str
    issue_created_at: str
    query: str
    hints: str | None
    link_method: str  # list | regex | both
    tags: dict = field(default_factory=dict)


@dataclass
class Funnel:
    repo: str
    base_branch: str
    since: str
    until: str
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(k for k, _ in FUNNEL_STEPS))
    drops: list[dict] = field(default_factory=list)  # {"pr", "step", "reason"}
    link_methods: dict[str, int] = field(default_factory=dict)  # among the candidates

    def drop(self, pr: dict, step: str, reason: str) -> None:
        self.drops.append({"pr": pr["number"], "step": step, "reason": reason})

    def drop_reasons(self) -> dict[str, int]:
        return dict(Counter(d["reason"].split(" (")[0] for d in self.drops))


def load_settings(path: Path) -> Settings:
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        repos = load_candidates(path)
    except tomllib.TOMLDecodeError as exc:
        raise CollectError(f"{path}: not valid TOML ({exc})") from None
    except RepoStatsError as exc:
        raise CollectError(str(exc)) from None
    table = data.get("collect")
    if not isinstance(table, dict):
        raise CollectError(f"{path}: needs a [collect] table")
    unknown = set(table) - {"since", "until", "min_body_chars", "extra_bots", "max_code_files", "max_code_lines"}
    if unknown:
        raise CollectError(f"{path}: unknown [collect] keys: {', '.join(sorted(unknown))}")
    try:
        since, until = date.fromisoformat(str(table["since"])), date.fromisoformat(str(table["until"]))
    except KeyError as exc:
        raise CollectError(f"{path}: [collect] needs {exc.args[0]}") from None
    except ValueError as exc:
        raise CollectError(f"{path}: bad date ({exc})") from None
    if until < since:
        raise CollectError(f"{path}: until is before since")
    min_body = table.get("min_body_chars", 100)
    bots = table.get("extra_bots", [])
    limits = {key: table.get(key, default) for key, default in (("max_code_files", 5), ("max_code_lines", 200))}
    for key, value in {"min_body_chars": min_body, **limits}.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise CollectError(f"{path}: {key} must be a whole number")
    if not isinstance(bots, list) or not all(isinstance(b, str) for b in bots):
        raise CollectError(f"{path}: extra_bots must be a list of logins")
    return Settings(name=path.stem, since=since, until=until, min_body_chars=min_body, extra_bots=bots,
                    repos=repos, **limits)


def collect_candidates(gh: GitHub, repo: str, settings: Settings, *,
                       progress: Callable[[str], None] = lambda message: None) -> tuple[list[Candidate], Funnel]:
    base = gh.rest(f"repos/{repo}")["default_branch"]
    prs = search_merged_prs(gh, repo, base, settings.since, settings.until, progress=progress)
    funnel = Funnel(repo=repo, base_branch=base, since=settings.since.isoformat(), until=settings.until.isoformat())
    counts = funnel.counts
    counts["merged"] = len(prs)

    linked: list[tuple[dict, int, str]] = []
    opened = people = 0
    since = settings.since.isoformat()
    for pr in prs:
        if pr["createdAt"][:10] < since:  # phase 2 runs agents on these tasks; their training data ends before `since`
            funnel.drop(pr, "opened_after_cutoff", f"fix PR opened before the start date ({pr['createdAt'][:10]})")
            continue
        opened += 1
        if is_bot(pr.get("author"), settings.extra_bots):
            funnel.drop(pr, "not_bot", f"bot author ({pr['author']['login']})")
            continue
        people += 1
        links = find_links(pr, repo)
        if not links:
            funnel.drop(pr, "one_link", "no linked issue")
        elif len(links) > 1:
            funnel.drop(pr, "one_link", f"several linked issues ({', '.join(f'#{n}' for n in links)})")
        else:
            (number, method), = links.items()
            linked.append((pr, number, method))
    counts["opened_after_cutoff"] = opened
    counts["not_bot"] = people
    counts["one_link"] = len(linked)

    progress(f"{repo}: fetching {len(linked)} linked issues")
    issues = fetch_issues(gh, repo, [number for _, number, _ in linked])
    candidates: list[Candidate] = []
    for key in ("is_issue", "issue_before_pr", "body_ok", "no_leak"):
        counts[key] = 0
    for pr, number, method in linked:
        issue = issues.get(number)
        if issue is None:
            funnel.drop(pr, "is_issue", f"issue not found (#{number})")
            continue
        if issue.get("__typename") != "Issue":
            funnel.drop(pr, "is_issue", f"link is a PR, not an issue (#{number})")
            continue
        counts["is_issue"] += 1
        if not issue["createdAt"] < pr["createdAt"]:  # ISO 8601 UTC strings sort as times
            funnel.drop(pr, "issue_before_pr", "issue opened after the fix PR")
            continue
        counts["issue_before_pr"] += 1
        body, body_after, missing = body_at(issue, pr["createdAt"])
        if missing:
            funnel.drop(pr, "body_ok", "body version not stored by GitHub")
            continue
        if len(clean_query(body)) < settings.min_body_chars:
            funnel.drop(pr, "body_ok", f"short body ({len(clean_query(body))} characters)")
            continue
        counts["body_ok"] += 1
        title, title_after = title_at(issue, pr["createdAt"])
        query = build_query(title, body)
        reason = leak(query, pr)
        if reason:
            funnel.drop(pr, "no_leak", f"leak ({reason})")
            continue
        counts["no_leak"] += 1
        commits = pr.get("commits") or {}
        candidates.append(Candidate(
            repo=repo, pr_number=pr["number"], pr_url=pr["url"], pr_created_at=pr["createdAt"],
            merged_at=pr["mergedAt"], base_ref=pr["baseRefName"],
            merge_commit=(pr.get("mergeCommit") or {}).get("oid"),
            commit_oids=[c["commit"]["oid"] for c in commits.get("nodes") or []],
            commit_subjects=[(c["commit"]["message"].splitlines() or [""])[0] for c in commits.get("nodes") or []],
            commits_total=commits.get("totalCount", 0), changed_files=pr["changedFiles"],
            issue_number=number, issue_url=issue["url"], issue_created_at=issue["createdAt"],
            query=query, hints=hints_before(issue, pr["createdAt"], settings.extra_bots), link_method=method,
            tags={"body_edited_after_fix": body_after, "title_edited_after_fix": title_after},
        ))
    funnel.link_methods = dict(Counter(c.link_method for c in candidates))
    progress(f"{repo}: {len(candidates)} candidates")
    return candidates, funnel


def write_candidates(out_dir: Path, candidates: list[Candidate], funnel: Funnel) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(asdict(c), ensure_ascii=False) + "\n" for c in candidates)
    write_text_atomic(out_dir / "candidates.jsonl", lines)
    write_json(out_dir / "funnel.json", {**asdict(funnel), "drop_reasons": funnel.drop_reasons()})


def _table(funnels: list[Funnel], steps, first: int, extra: tuple[str, ...] = ()) -> list[str]:
    lines = [f"{i}. {text}" for i, (_, text) in enumerate(steps, start=first)]
    lines += ["", "| Repo | " + " | ".join(str(i) for i in range(first, first + len(steps)))
              + "".join(f" | {name}" for name in extra) + " |",
              "|---|" + "---:|" * (len(steps) + len(extra))]
    rows = [(f.repo, f) for f in funnels]
    for name, f in rows:
        methods = [f.link_methods.get(m, 0) for m in ("list", "regex", "both")] if extra else []
        lines.append(f"| {name} | " + " | ".join(f"{f.counts[k]:,}" for k, _ in steps)
                     + "".join(f" | {n:,}" for n in methods) + " |")
    if len(funnels) > 1:
        total = [sum(f.counts[k] for f in funnels) for k, _ in steps]
        methods = [sum(f.link_methods.get(m, 0) for f in funnels) for m in ("list", "regex", "both")] if extra else []
        lines.append("| **Total** | " + " | ".join(f"{n:,}" for n in total) + "".join(f" | {n:,}" for n in methods) + " |")
    return lines


def render_funnel(funnels: list[Funnel]) -> str:
    """The GitHub steps, and the git steps when B2 ran. Each count is the PRs left after that step."""
    lines = ["## GitHub steps", "", "Count of PRs left after each step:", ""]
    lines += _table(funnels, GITHUB_STEPS, 1, ("Link: list", "regex", "both"))
    if funnels and all(f.counts[GIT_STEPS[0][0]] is not None for f in funnels):
        lines += ["", "## Git steps (full clone)", "", "Count of PRs left after each step:", ""]
        lines += _table(funnels, GIT_STEPS, len(GITHUB_STEPS) + 1)
    return "\n".join(lines) + "\n"
