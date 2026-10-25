"""From candidates to gradable tasks (F4 B2): base commit, patch, checks, labels, split.

These steps need the full clone of the repo. We compute the patch ourselves from the base
commit (Decision 7), so the patch and the snapshot always match, and the labeler gives gold
labels with the same rules as for SWE-bench tasks.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path

from .. import __version__, repos
from ..github import GitHub
from ..labels import LABELER_VERSION, LabelError, identifier_in_query, label_at_commit
from ..patches import parse_patch, split_lines, split_patch
from ..repos import RepoError
from ..files import now, write_json
from ..tasks import Fix, Issue, Task, assign_split, save_tasks, validate
from .candidates import FUNNEL_STEPS, GIT_STEPS, Candidate, Funnel, Settings

GIT_KEYS = tuple(key for key, _ in GIT_STEPS)
BATCH_SIZE = 50
MAX_PR_FILES = 100  # one page of the files connection; such PRs are far over the code-file limit anyway

PR_FILES_FIELDS = "files(first: %d) { totalCount nodes { path } }" % MAX_PR_FILES


class Skip(Exception):
    """This candidate does not become a task. args: (funnel step, reason)."""


def pr_files_query(repo: str, numbers: list[int]) -> str:
    owner, name = repo.split("/")
    parts = [f"p{n}: pullRequest(number: {n}) {{ {PR_FILES_FIELDS} }}" for n in numbers]
    return ('query { rateLimit { cost remaining } repository(owner: "%s", name: "%s") { %s } }'
            % (owner, name, "\n".join(parts)))


def fetch_pr_files(gh: GitHub, repo: str, numbers, batch: int = BATCH_SIZE) -> dict[int, list[str] | None]:
    """PR number -> the paths GitHub lists for the PR, or None for more than MAX_PR_FILES files."""
    wanted = sorted(set(numbers))
    found: dict[int, list[str] | None] = {}
    for start in range(0, len(wanted), batch):
        part = wanted[start:start + batch]
        repository = gh.graphql(pr_files_query(repo, part), allow_missing=True).get("repository") or {}
        for n in part:
            files = (repository.get(f"p{n}") or {}).get("files") or {"totalCount": 0, "nodes": []}
            found[n] = None if files["totalCount"] > MAX_PR_FILES else [f["path"] for f in files["nodes"]]
    return found


def merge_base(repo: str, cand: Candidate) -> tuple[str, str]:
    """(base commit, merge type) for a merged PR (Decision 7)."""
    if not cand.merge_commit:
        raise Skip("base_found", "merge commit not found")
    try:
        found = repos.parents(repo, cand.merge_commit)
    except RepoError:
        raise Skip("base_found", "merge commit not found") from None
    if len(found) >= 2:
        return found[0], "merge"
    if not found:
        raise Skip("base_found", "merge commit has no parent")
    n = cand.commits_total
    if n > 1 and len(cand.commit_subjects) == n and repos.subjects(repo, cand.merge_commit, n) == cand.commit_subjects:
        # A rebase merge puts the N PR commits on the branch with their messages unchanged.
        try:
            return repos.ancestor(repo, cand.merge_commit, n), "rebase"
        except RepoError:
            raise Skip("base_found", "rebase base not found") from None
    return found[0], "squash"


def patch_paths(patch: str) -> set[str]:
    """The paths a patch touches, as GitHub lists them: the new path, or the old path of a deleted file."""
    return {change.new_path or change.old_path for change in parse_patch(patch)}


def gold_file_stats(repo: str, base: str, paths: list[str]) -> tuple[int, int]:
    """(bytes, lines) of the largest gold file at the base commit."""
    biggest = (0, 0)
    for path in paths:
        text = repos.read_file(repo, base, path) or ""
        biggest = max(biggest, (len(text.encode("utf-8")), len(split_lines(text))))
    return biggest


def candidate_to_task(cand: Candidate, settings: Settings, pr_files: list[str] | None,
                      py_files: Callable[[str, str], int] | None = None) -> Task:
    """One task, or Skip with the funnel step and the reason.

    A git error on this candidate becomes a Skip of the step it happened in, so one bad
    candidate does not stop the collection of the others.
    """
    step = [GIT_KEYS[0]]  # the step in progress, updated by _candidate_to_task
    try:
        return _candidate_to_task(cand, settings, pr_files, py_files or count_py_files, step)
    except RepoError as exc:
        raise Skip(step[0], f"git error ({str(exc)[:80]})") from None


def count_py_files(repo: str, commit: str) -> int:
    """Python files in the repo at a commit (the repo size tag)."""
    return sum(1 for path in repos.tracked_files(repo, commit) if path.endswith(".py"))


def _candidate_to_task(cand: Candidate, settings: Settings, pr_files: list[str] | None,
                       py_files: Callable[[str, str], int], step: list[str]) -> Task:
    repo = cand.repo
    base, merge_type = merge_base(repo, cand)
    step[0] = "files_match"
    if pr_files is None:  # before the diff: such PRs are big, and their diff is slow
        raise Skip("files_match", f"more than {MAX_PR_FILES} files")
    full = repos.diff(repo, base, cand.merge_commit)
    ours = patch_paths(full)
    if ours != set(pr_files):
        raise Skip("files_match", f"file list differs ({len(ours ^ set(pr_files))} paths)")
    parts = split_patch(full)
    code = parts["code"]
    step[0] = "applies"
    if code and (message := repos.apply_check(repo, base, code)):
        raise Skip("applies", f"patch does not apply ({message.splitlines()[0][:80]})")
    step[0] = "size_ok"
    changes = parse_patch(code) if code else []
    n_files, n_lines = len(changes), sum(c.added + c.removed for c in changes)
    if n_files == 0:
        raise Skip("size_ok", "no code files")
    if n_files > settings.max_code_files:
        raise Skip("size_ok", f"too many code files ({n_files})")
    if n_lines > settings.max_code_lines:
        raise Skip("size_ok", f"too many changed lines ({n_lines})")
    step[0] = "labeled"
    try:
        label = label_at_commit(repo, base, code)
    except LabelError as exc:
        raise Skip("labeled", f"label error ({str(exc)[:80]})") from None
    if not label.gold.files:
        raise Skip("labeled", "only new files")

    gold = set(label.gold.files)
    languages = sorted({c.language for c in changes if c.old_path in gold and c.language})
    biggest_bytes, biggest_lines = gold_file_stats(repo, base, label.gold.files)
    owner, name = repo.split("/")
    task_id = f"{owner}__{name}-{cand.pr_number}"
    task = Task(
        id=task_id, source="fresh", split=assign_split(task_id), repo=repo, base_commit=base,
        language=label.language, query=cand.query, hints=cand.hints,
        issue=Issue(number=cand.issue_number, url=cand.issue_url, created_at=cand.issue_created_at),
        fix=Fix(pr_number=cand.pr_number, url=cand.pr_url, merged_at=cand.merged_at, merge_type=merge_type),
        patch=code, test_patch=parts["test"] or None, gold=label.gold, unretrievable=label.unretrievable,
        tags={
            **label.tags,
            "has_test_patch": bool(parts["test"]),
            "identifier_in_query": identifier_in_query(cand.query, label.gold),
            "query_tokens": None,
            **cand.tags,
            "link_method": cand.link_method,
            "fix_opened_at": cand.pr_created_at,
            "n_code_files": n_files,  # changed code files in the fix, new files included
            "code_lines_changed": n_lines,  # added plus removed lines in those files
            "gold_languages": languages,
            "gold_all_python": languages == ["python"],
            # codemem skips files over its max_file_size (1 MB today); these find the tasks it affects
            "max_gold_file_bytes": biggest_bytes,
            "max_gold_file_lines": biggest_lines,
            # repo size at this task's commit, for the small / medium / large groups in the report
            "repo_py_files": py_files(repo, base),
        },
        labeler=LABELER_VERSION,
    )
    problems = validate(task)
    if problems:
        raise Skip("labeled", f"invalid task ({problems[0][:80]})")
    return task


def build_tasks(gh: GitHub, candidates: list[Candidate], settings: Settings, funnel: Funnel, *,
                progress: Callable[[str], None] = lambda message: None) -> list[Task]:
    """Tasks for one repo's candidates. Fills the git steps of the funnel."""
    if not candidates:
        funnel.counts.update(dict.fromkeys(GIT_KEYS, 0))
        return []
    repo = candidates[0].repo
    progress(f"{repo}: clone (once) and PR file lists")
    repos.ensure_clone(repo)
    files = fetch_pr_files(gh, repo, [c.pr_number for c in candidates])
    sizes: dict[str, int] = {}  # tasks that share a base commit share the repo size

    def py_files(repo_: str, commit: str) -> int:
        if commit not in sizes:
            sizes[commit] = count_py_files(repo_, commit)
        return sizes[commit]

    passed = dict.fromkeys(GIT_KEYS, 0)
    tasks = []
    for i, cand in enumerate(candidates, start=1):
        try:
            tasks.append(candidate_to_task(cand, settings, files.get(cand.pr_number), py_files))
            reached = len(GIT_KEYS)
        except Skip as skip:
            step, reason = skip.args
            funnel.drop({"number": cand.pr_number}, step, reason)
            reached = GIT_KEYS.index(step)
        for key in GIT_KEYS[:reached]:
            passed[key] += 1
        if i % 100 == 0 or i == len(candidates):
            progress(f"{repo}: {i} of {len(candidates)} candidates checked, {len(tasks)} tasks")
    funnel.counts.update(passed)
    return tasks


def write_task_set(out: Path, tasks: list[Task], funnels: list[Funnel], settings: Settings, config: Path) -> None:
    """The task file (all repos, oldest fix first within a repo) and its meta file next to it."""
    from ..importers.swebench import label_stats
    from ..run import _eval_git

    tasks = sorted(tasks, key=lambda t: (t.repo, t.fix.merged_at or "", t.id))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    save_tasks(out, tasks)
    stats = label_stats(tasks)
    stats["tasks_per_split"] = dict(sorted(Counter(t.split for t in tasks).items()))
    stats["share_gold_all_python"] = round(sum(bool(t.tags.get("gold_all_python")) for t in tasks) / (len(tasks) or 1), 3)
    stats["merge_types"] = dict(sorted(Counter(t.fix.merge_type for t in tasks).items()))
    write_json(out.with_suffix(".meta.json"), {
        "config": Path(config).name,
        "since": settings.since.isoformat(), "until": settings.until.isoformat(),
        "settings": {"min_body_chars": settings.min_body_chars, "extra_bots": settings.extra_bots,
                     "max_code_files": settings.max_code_files, "max_code_lines": settings.max_code_lines},
        "cmeval_version": __version__, "cmeval_git": _eval_git(), "labeler": LABELER_VERSION, "created": now(),
        "funnel_steps": [{"key": k, "text": text} for k, text in FUNNEL_STEPS],
        "repos": {f.repo: {"base_branch": f.base_branch, "counts": f.counts, "link_methods": f.link_methods,
                           "drop_reasons": f.drop_reasons()} for f in funnels},
        "stats": stats,
    })
