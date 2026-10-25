"""Numbers that help us pick the repos for fresh tasks (`cmeval repo-stats`, F4 B0).

For each candidate repo:
- API numbers: default branch, packed size, bytes for each language (GitHub's count, which
  leaves out vendored and generated files).
- A PR funnel: merged PRs after the cutoff, then a count after each cheap filter that needs no
  git. The last count is an upper estimate of the tasks. The collector (B2) drops more tasks
  with checks that need git: the patch must apply, a gold file must exist at the base commit,
  and the file list must match the PR.
- With functions=True, code numbers from a shallow clone of the default branch: the Python
  files that codemem indexes, their lines, and codemem's chunks. Embedding time grows with the
  chunk count.
"""

from __future__ import annotations

import logging
import re
import shutil
import time
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from ..github import GitHub
from ..paths import tmp_dir
from ..repos import RepoError, shallow_clone, slug
from ..status import NullStatus
from ..tasks import clean_query
from .search import is_bot, search_merged_prs

# Loose limit on all changed files of a PR (tests and docs count too). B2 applies the real
# filter: 1 to 5 changed code files.
LOOSE_MAX_FILES = 10
MIN_BODY_CHARS = 100
# Clone for code numbers only when Python is at least this share of the code bytes.
DEFAULT_MIN_PYTHON_SHARE = 0.3
# Backlog estimate of embedding speed: chunks per second on the M5 (MPS).
CHUNKS_PER_SECOND = 31

FUNNEL_STEPS = (
    ("merged", "merged into the default branch in the date range"),
    ("not_bot", "author is not a bot"),
    ("one_issue", "closes exactly one issue, in the same repo"),
    ("issue_before_merge", "the issue was opened before the merge"),
    ("few_files", f"at most {LOOSE_MAX_FILES} changed files (all kinds)"),
    ("body_100", f"issue body has {MIN_BODY_CHARS} or more characters (hidden comments removed)"),
)

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class RepoStatsError(RuntimeError):
    """A bad candidates file, or a clone or count that failed."""


@dataclass
class Candidate:
    name: str
    note: str = ""


@dataclass
class RepoStats:
    repo: str
    note: str
    default_branch: str
    size_kb: int  # packed git size with all history, from the API
    archived: bool
    languages: dict[str, int]  # bytes, largest first
    python_share: float
    funnel: dict[str, int]
    code: dict | None = None  # None when not measured
    code_skipped: str | None = None  # why there are no code numbers


@dataclass
class CodeStats:
    commit: str
    checkout_mb: float
    files: int = 0
    lines: int = 0
    functions: int = 0
    methods: int = 0
    file_headers: int = 0
    skipped_large: int = 0  # files over codemem's max_file_size
    chunks: int = 0
    embed_hours: float = 0.0
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


def load_candidates(path: Path) -> list[Candidate]:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RepoStatsError(f"{path}: not valid TOML ({exc})") from None
    rows = data.get("repo")
    if not isinstance(rows, list) or not rows:
        raise RepoStatsError(f"{path}: needs one or more [[repo]] tables")
    candidates = []
    for i, row in enumerate(rows, start=1):
        name = row.get("name")
        if not isinstance(name, str) or not _REPO_RE.match(name):
            raise RepoStatsError(f"{path}: repo {i}: name must look like owner/name, got {name!r}")
        candidates.append(Candidate(name=name, note=str(row.get("note", ""))))
    names = [c.name.lower() for c in candidates]
    if len(set(names)) != len(names):
        raise RepoStatsError(f"{path}: a repo is listed twice")
    return candidates


def api_stats(gh: GitHub, repo: str) -> dict:
    info = gh.rest(f"repos/{repo}")
    languages = dict(sorted(gh.rest(f"repos/{repo}/languages").items(), key=lambda kv: -kv[1]))
    total = sum(languages.values())
    return {
        "default_branch": info["default_branch"],
        "size_kb": info["size"],
        "archived": info.get("archived", False),
        "languages": languages,
        "python_share": languages.get("Python", 0) / total if total else 0.0,
    }


def pr_funnel(prs: list[dict], repo: str) -> dict[str, int]:
    """Count of PRs left after each step of FUNNEL_STEPS, in order."""
    counts = dict.fromkeys((key for key, _ in FUNNEL_STEPS), 0)
    for pr in prs:
        counts["merged"] += 1
        if is_bot(pr.get("author")):
            continue
        counts["not_bot"] += 1
        refs = pr["closingIssuesReferences"]
        if refs["totalCount"] != 1 or not refs["nodes"]:
            continue
        issue = refs["nodes"][0]
        if issue["repository"]["nameWithOwner"].lower() != repo.lower():
            continue
        counts["one_issue"] += 1
        if not issue["createdAt"] < pr["mergedAt"]:  # ISO 8601 UTC strings sort as times
            continue
        counts["issue_before_merge"] += 1
        if pr["changedFiles"] > LOOSE_MAX_FILES:
            continue
        counts["few_files"] += 1
        if len(clean_query(issue.get("body"))) < MIN_BODY_CHARS:
            continue
        counts["body_100"] += 1
    return counts


def code_stats(repo: str, branch: str, *, url: str | None = None,
               progress: Callable[[str], None] = lambda message: None) -> CodeStats:
    """Shallow-clone the branch, count what codemem would index, and delete the clone."""
    try:
        from codemem.chunker import chunk_source
        from codemem.config import Config
        from codemem.indexer import walk_python_files
    except ImportError:
        raise RepoStatsError("code numbers need codemem: run `uv sync --extra codemem` in eval/") from None

    start = time.monotonic()
    root = tmp_dir() / f"repo-stats-{slug(repo)}"
    shutil.rmtree(root, ignore_errors=True)
    root.parent.mkdir(parents=True, exist_ok=True)
    progress(f"{repo}: shallow clone of {branch}")
    try:
        try:
            commit = shallow_clone(repo, branch, root, url=url)
        except RepoError as exc:
            raise RepoStatsError(f"{repo}: {exc}") from None
        checkout_bytes = sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and ".git" not in p.parts)
        stats = CodeStats(commit=commit, checkout_mb=round(checkout_bytes / 1e6, 1))
        config = Config()
        files = walk_python_files(root, config)
        progress(f"{repo}: chunking {len(files)} Python files")
        chunker_log = logging.getLogger("codemem.chunker")
        old_level = chunker_log.level
        chunker_log.setLevel(logging.ERROR)  # one warning for each file with a parse error is too much
        try:
            for rel, path in files.items():
                data = path.read_bytes()
                if len(data) > config.max_file_size:
                    stats.skipped_large += 1
                    continue
                stats.files += 1
                stats.lines += data.count(b"\n")
                for chunk in chunk_source(data, rel):
                    stats.chunks += 1
                    if chunk.kind == "function":
                        stats.functions += 1
                    elif chunk.kind == "method":
                        stats.methods += 1
                    elif chunk.kind == "file_header":
                        stats.file_headers += 1
        finally:
            chunker_log.setLevel(old_level)
        stats.embed_hours = round(stats.chunks / CHUNKS_PER_SECOND / 3600, 2)
        stats.seconds = round(time.monotonic() - start, 1)
        return stats
    finally:
        shutil.rmtree(root, ignore_errors=True)


def collect_stats(gh: GitHub, candidates: list[Candidate], since: date, until: date, *,
                  functions: bool = False, min_python_share: float = DEFAULT_MIN_PYTHON_SHARE,
                  progress: Callable[[str], None] = lambda message: None,
                  code_fn: Callable[..., CodeStats] = code_stats, status: NullStatus | None = None) -> list[RepoStats]:
    status = status or NullStatus()
    status.total(len(candidates), "repos")
    results = []
    for number, candidate in enumerate(candidates, start=1):
        repo = candidate.name
        status.stage(f"repo {number}/{len(candidates)}: {repo}")
        api = api_stats(gh, repo)
        prs = search_merged_prs(gh, repo, api["default_branch"], since, until, progress=progress)
        stats = RepoStats(repo=repo, note=candidate.note, funnel=pr_funnel(prs, repo), **api)
        if not functions:
            stats.code_skipped = "not asked (--functions)"
        elif api["python_share"] < min_python_share:
            stats.code_skipped = f"Python is {api['python_share']:.0%} of the code (below {min_python_share:.0%})"
        else:
            stats.code = asdict(code_fn(repo, api["default_branch"], progress=progress))
        results.append(stats)
        progress(f"{repo}: done ({stats.funnel['body_100']} possible tasks)")
        status.advance()
    return results


def _top_languages(languages: dict[str, int], n: int = 3) -> str:
    total = sum(languages.values()) or 1
    return ", ".join(f"{name} {count / total:.0%}" for name, count in list(languages.items())[:n])


def render_markdown(results: list[RepoStats], since: date, until: date) -> str:
    lines = [f"# Repo stats, {since.isoformat()} to {until.isoformat()}", ""]
    lines += ["## Size and languages", "",
              "| Repo | Branch | Packed MB | Code MB (GitHub) | Python | Top languages |",
              "|---|---|---:|---:|---:|---|"]
    for r in results:
        code_mb = sum(r.languages.values()) / 1e6
        archived = " (archived)" if r.archived else ""
        lines.append(f"| {r.repo}{archived} | {r.default_branch} | {r.size_kb / 1000:,.0f} | {code_mb:,.1f} "
                     f"| {r.python_share:.0%} | {_top_languages(r.languages)} |")
    lines += ["", "## PR funnel", "", "Count of PRs left after each step:", ""]
    for i, (_, text) in enumerate(FUNNEL_STEPS, start=1):
        lines.append(f"{i}. {text}")
    lines += ["", "The last column is an upper estimate of the tasks. The collector drops more tasks with "
              "checks that need git.", "",
              "| Repo | " + " | ".join(str(i) for i in range(1, len(FUNNEL_STEPS) + 1)) + " |",
              "|---|" + "---:|" * len(FUNNEL_STEPS)]
    for r in results:
        lines.append(f"| {r.repo} | " + " | ".join(f"{r.funnel[key]:,}" for key, _ in FUNNEL_STEPS) + " |")
    lines += ["", "## Code that codemem indexes (shallow clone of the default branch)", "",
              f"Embedding hours = chunks / {CHUNKS_PER_SECOND} per second (backlog estimate for the M5).", "",
              "| Repo | Commit | Checkout MB | .py files | Lines | Functions | Methods | Chunks | Embed hours |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        c = r.code
        if c is None:
            lines.append(f"| {r.repo} | {r.code_skipped} | | | | | | | |")
            continue
        lines.append(f"| {r.repo} | {c['commit'][:12]} | {c['checkout_mb']:,.0f} | {c['files']:,} | {c['lines']:,} "
                     f"| {c['functions']:,} | {c['methods']:,} | {c['chunks']:,} | {c['embed_hours']:.1f} |")
    return "\n".join(lines) + "\n"
