"""The run sample: which fair tasks of each repo are run, and in what order (docs/plan/runs.md, section 3).

The sample is drawn once, before the first run, and the file is committed. It does not change after that.

The tier of a task is generate.tier of its real fix: easy (the labels easy and medium of generate.difficulty),
medium (the label hard of the first collection, tasks/e2e/<recipe>.jsonl), and hard (the second collection,
tasks/e2e/<recipe>-large.jsonl, holds only such fixes). The label of a task is generate.difficulty.

Only a task that the screen calls fair is drawn. The status comes from e2e_screen.completion_set: each read is
checked against the task's content hash of today (with its facts), so a stale read does not count.

The draw, for each repo and tier:
  - Each task is ranked by the sha256 of "<seed>:<repo>:<task id>", as subset.draw does. The rank depends only on
    the seed, the repo and the id, so the same inputs and seed always give the same order.
  - Tasks of the test split come before tasks of the dev split. Each group is in rank order.
  - In the easy tier, the numbers follow the label pattern medium, easy, medium, medium, easy, medium (runs.md
    section 3), and the pattern starts again after number 6. So numbers 7 and 8 are medium and easy, and the 8
    ready tasks of runs.md section 2 are 5 medium and 3 easy. Each label has its own queue in the order above.
    When the queue of a label is empty, the next task of the other label takes the number. A note says so for
    numbers 1 to 6, the ones that are run. The label pattern comes before the split: a dev task of the wanted label comes before a test task of the
    other label.
  - Every fair task gets a number, so the spares are fixed too.

One task per issue: two fair tasks of a repo can fix the same issue (the same issue text and often the same hidden
test). Before the draw, the fair tasks of a repo are grouped by their issue (see issue_key). The task with the lowest
pull request number of each group stays. The others are not drawn: they take no number and no place in a tier, and
they are not run. Their rows have duplicate_of, the id of the task that stays.

The tasks that are run: 6 easy, 4 medium and 4 hard. A repo with fewer than 4 fair hard tasks runs more medium
ones, so that medium and hard together are 8. A repo that is still short in a tier runs all it has.

Output: one JSON row for each fair task (repo, id, tier, label, split, number, run, has_prompts, duplicate_of),
sorted by repo, tier and number. has_prompts is true when the prompt files hold an L1 and an L2 text for the task.
duplicate_of is null, except on a dropped duplicate: there it is the id that stays, number is null and the row comes
after the numbered rows of its tier. Beside it, a .meta.json with the seed, the sha256 of each input, the date, the
command line, the counts of each repo and the dropped duplicates.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .e2e_screen import completion_set, load_facts
from .files import now, read_jsonl, sha256_file, write_json, write_text_atomic
from .generate import difficulty, tier
from .tasks import Task, load_tasks

EVAL_ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = EVAL_ROOT / "tasks"
TASK_GLOB = "e2e/*.jsonl"
# pilot18.jsonl is left out: b7.jsonl reads the same 18 tasks again under screen-rules-v1, and the two files
# cannot be loaded together (they hold the same task and read numbers).
DEFAULT_SCREENS = ("b7.jsonl", "b10a.jsonl", "ruff1.jsonl")
PROMPT_GLOB = "vague-*-v3.jsonl"  # the prompt files of vague-rules-v3.md
PROMPT_LEVELS = ("L1", "L2")

TIERS = ("easy", "medium", "hard")
RUN = {"easy": 6, "medium": 4, "hard": 4}
MEDIUM_AND_HARD = 8  # runs.md section 3: a repo short of hard tasks runs more medium ones, up to this sum
EASY_PATTERN = ("medium", "easy", "medium", "medium", "easy", "medium")


class SampleError(ValueError):
    """The sample cannot be drawn or written."""


def issue_key(task: Task) -> tuple[str, str]:
    """What identifies the issue of a task: the issue URL, else the issue number, else the issue text without the
    white space at its ends. Compare keys only inside one repo."""
    if task.issue.url:
        return ("url", task.issue.url.strip().lower())
    if task.issue.number is not None:
        return ("number", str(task.issue.number))
    return ("query", task.query.strip())


def pr_number(task: Task) -> int:
    """The pull request number of the fix: fix.pr_number, else the number at the end of the id."""
    if task.fix.pr_number is not None:
        return task.fix.pr_number
    match = re.search(r"(\d+)$", task.id)
    if match is None:
        raise SampleError(f"{task.id}: no pull request number")
    return int(match.group(1))


def one_per_issue(tasks: list[Task]) -> tuple[list[Task], dict[str, str]]:
    """The tasks of one repo with one task per issue, and the dropped ones: id -> the id that stays. The task with
    the lowest pull request number of each issue stays."""
    groups: dict[tuple[str, str], list[Task]] = {}
    for task in tasks:
        groups.setdefault(issue_key(task), []).append(task)
    dropped = {}
    for group in groups.values():
        first, *others = sorted(group, key=lambda t: (pr_number(t), t.id))
        dropped.update({t.id: first.id for t in others})
    return [t for t in tasks if t.id not in dropped], dropped


def rank(seed: str, repo: str, task_id: str) -> str:
    return hashlib.sha256(f"{seed}:{repo}:{task_id}".encode("utf-8")).hexdigest()


def seeded(tasks: list[Task], seed: str) -> list[Task]:
    """The tasks of one repo: the test split first, then the dev split, each group in rank order."""
    return sorted(tasks, key=lambda t: (t.split != "test", rank(seed, t.repo, t.id), t.id))


def easy_order(tasks: list[Task], seed: str) -> tuple[list[Task], list[str]]:
    """The easy tier in the order of EASY_PATTERN, and a note for each of the first 6 numbers that has the other
    label. Later numbers are spares, so a label that runs out there gets no note."""
    queues = {label: seeded([t for t in tasks if difficulty(t.patch) == label], seed) for label in ("medium", "easy")}
    order, filled = [], {}
    for number in range(1, len(tasks) + 1):
        want = EASY_PATTERN[(number - 1) % len(EASY_PATTERN)]
        other = "easy" if want == "medium" else "medium"
        label = want if queues[want] else other
        order.append(queues[label].pop(0))
        if label != want and number <= len(EASY_PATTERN):
            filled.setdefault(want, []).append(number)
    notes = [f"easy tier: numbers {_numbers(numbers)} have the label {'easy' if want == 'medium' else 'medium'}, "
             f"because no task with the label {want} is left" for want, numbers in filled.items()]
    return order, notes


def _numbers(numbers: list[int]) -> str:
    return ", ".join(str(n) for n in numbers)


def run_targets(fair: dict[str, int]) -> dict[str, int]:
    """How many tasks of each tier the plan runs: RUN, and more medium when the hard tier has fewer than 4."""
    hard = min(fair.get("hard", 0), RUN["hard"])
    return {**RUN, "medium": max(RUN["medium"], MEDIUM_AND_HARD - hard)}


def run_counts(fair: dict[str, int]) -> dict[str, int]:
    """How many tasks of each tier are run: the target, or all fair tasks when a tier has fewer."""
    return {name: min(fair.get(name, 0), target) for name, target in run_targets(fair).items()}


@dataclass
class RepoSample:
    repo: str
    rows: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict:
        tiers = {}
        drawn = [r for r in self.rows if r["duplicate_of"] is None]
        target = run_targets({name: sum(1 for r in drawn if r["tier"] == name) for name in TIERS})
        for name in TIERS:
            rows = [r for r in drawn if r["tier"] == name]
            run = sum(1 for r in rows if r["run"])
            tiers[name] = {"fair": len(rows), "target": target[name], "run": run, "spare": len(rows) - run,
                           "test": sum(1 for r in rows if r["split"] == "test"),
                           "dev": sum(1 for r in rows if r["split"] == "dev"),
                           "labels": {label: sum(1 for r in rows if r["label"] == label)
                                      for label in sorted({r["label"] for r in rows})}}
        return {"tiers": tiers,
                "run_without_prompts": [r["id"] for r in self.rows if r["run"] and not r["has_prompts"]],
                "duplicates": {r["id"]: r["duplicate_of"] for r in self.rows if r["duplicate_of"] is not None},
                "notes": self.notes}


def sample_repo(repo: str, tasks: list[Task], seed: str, prompted: set[str]) -> RepoSample:
    """Number the fair tasks of one repo in each tier, and mark the ones that are run. A second task of an issue
    gets no number (one_per_issue)."""
    by_tier: dict[str, list[Task]] = {name: [] for name in TIERS}
    result = RepoSample(repo)
    in_tiers = []
    for task in tasks:
        if tier(task.patch) is None:
            result.notes.append(f"{task.id}: the real fix is larger than the hard tier; left out")
        else:
            in_tiers.append(task)
    kept, dropped = one_per_issue(in_tiers)
    for task in kept:
        by_tier[tier(task.patch)].append(task)
    order = {name: seeded(group, seed) for name, group in by_tier.items()}
    order["easy"], notes = easy_order(by_tier["easy"], seed)
    result.notes += notes
    fair = {name: len(group) for name, group in by_tier.items()}
    target, run = run_targets(fair), run_counts(fair)
    if target["medium"] > RUN["medium"]:
        result.notes.append(f"medium tier: the target is {target['medium']}, because the hard tier runs "
                            f"{run['hard']} (medium and hard together are {MEDIUM_AND_HARD})")
    for name in TIERS:
        if run[name] < target[name]:
            result.notes.append(f"{name} tier: {fair[name]} fair tasks, fewer than the target of {target[name]}; "
                                f"all of them are run")
    duplicates = sorted((t for t in in_tiers if t.id in dropped), key=lambda t: (pr_number(t), t.id))
    for name in TIERS:
        numbered = list(enumerate(order[name], start=1))
        numbered += [(None, task) for task in duplicates if tier(task.patch) == name]
        for number, task in numbered:
            result.rows.append({"repo": repo, "id": task.id, "tier": name, "label": difficulty(task.patch),
                                "split": task.split, "number": number,
                                "run": number is not None and number <= run[name],
                                "has_prompts": task.id in prompted, "duplicate_of": dropped.get(task.id)})
    return result


def draw(tasks: list[Task], fair: set[str], seed: str, prompted: set[str],
         repos: list[str] | None = None) -> list[RepoSample]:
    """The sample of each repo. Without `repos`, every repo with a fair task, sorted by name. A repo is named as
    owner/name or by its name alone, without case."""
    by_repo: dict[str, list[Task]] = {}
    for task in tasks:
        if task.id in fair:
            by_repo.setdefault(task.repo, []).append(task)
    if not by_repo:
        raise SampleError("no task is fair in the screen files")
    names = sorted(by_repo)
    if repos:
        known = {}
        for name in names:
            known[name.lower()] = known[name.split("/")[-1].lower()] = name
        unknown = [r for r in repos if r.lower() not in known]
        if unknown:
            raise SampleError(f"no fair task in {unknown}; repos with fair tasks: {names}")
        names = sorted({known[r.lower()] for r in repos})
    return [sample_repo(name, by_repo[name], seed, prompted) for name in names]


def load_prompts(paths: list[Path]) -> set[str]:
    """The ids of the tasks that have a text for each level of PROMPT_LEVELS in the prompt files."""
    levels: dict[str, set[str]] = {}
    for path in paths:
        if not Path(path).exists():
            raise SampleError(f"{path}: no such prompt file")
        try:
            rows = read_jsonl(Path(path))
        except ValueError as exc:
            raise SampleError(str(exc)) from None
        for row in rows:
            if isinstance(row, dict) and str(row.get("prompt") or "").strip():
                levels.setdefault(str(row.get("id")), set()).add(str(row.get("level")))
    return {task_id for task_id, have in levels.items() if set(PROMPT_LEVELS) <= have}


def sample_text(samples: list[RepoSample]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for s in samples for row in s.rows)


def _name(path: Path) -> str:
    """The path from the eval folder when the file is in it, else the full path."""
    path = Path(path).resolve()
    try:
        return path.relative_to(EVAL_ROOT).as_posix()
    except ValueError:
        return str(path)


def _hashes(paths: list[Path]) -> list[dict]:
    return [{"path": _name(p), "sha256": sha256_file(p)} for p in paths]


@dataclass
class SampleResult:
    out: Path
    samples: list[RepoSample]
    written: bool  # False when the file holds this sample already
    stale_reads: int


def run_sample(out: Path | str, *, seed: str, task_files: list[Path] | None = None,
               screens: list[Path] | None = None, facts: Path | None = None, prompts: list[Path] | None = None,
               repos: list[str] | None = None, command: str = "", force: bool = False) -> SampleResult:
    """Draw the sample and write it with its meta file. The defaults are every task file of tasks/e2e,
    DEFAULT_SCREENS, tasks/screen/facts.jsonl and the files of PROMPT_GLOB. A file that holds another sample is
    not written over without `force`, because the list is fixed after the first run."""
    out = Path(out)
    meta_path = out.with_suffix(".meta.json")
    if not seed.strip():
        raise SampleError("give a seed, for example runs-v1")
    task_files = [Path(p) for p in task_files] if task_files else sorted(TASKS_DIR.glob(TASK_GLOB))
    screens = [Path(p) for p in screens] if screens else [TASKS_DIR / "screen" / n for n in DEFAULT_SCREENS]
    prompts = [Path(p) for p in prompts] if prompts else sorted(TASKS_DIR.glob(PROMPT_GLOB))
    facts_path = Path(facts) if facts else TASKS_DIR / "screen" / "facts.jsonl"
    for path in [*task_files, *screens]:
        if not path.exists():
            raise SampleError(f"{path}: no such file")
    if out.resolve() in {p.resolve() for p in [*task_files, *screens, *prompts, facts_path]}:
        raise SampleError(f"{out} is an input; choose another --out")

    tasks = [t for path in task_files for t in load_tasks(path)]
    screen = completion_set(screens, tasks, load_facts(facts_path) if facts_path.exists() else {})
    samples = draw(tasks, screen.fair, seed, load_prompts(prompts), repos)
    text = sample_text(samples)
    stale = sum(s.stale for s in screen.status.values())
    if out.exists():
        if out.read_text(encoding="utf-8") == text:
            return SampleResult(out, samples, False, stale)
        if not force:
            raise SampleError(f"{out} holds another sample. The list is fixed after the first run; give --force "
                              f"only if no run has used it")

    from .run import _eval_git  # the commit of the code that drew the sample

    meta = {  # complete before any file is written
        "kind": "run-sample",
        "seed": seed,
        "plan": "docs/plan/runs.md section 3",
        "draw": "per repo and tier: test split first, then dev; each group by the lowest sha256 of "
                "'<seed>:<repo>:<task id>'; the easy tier follows the label pattern " + ", ".join(EASY_PATTERN) +
                ", again from the start after number 6",
        "run_per_tier": RUN,
        "medium_and_hard": MEDIUM_AND_HARD,
        "fair_rule": "status fair in e2e_screen.completion_set; reads with another content hash (with facts) are stale",
        "issue_rule": "one task per issue in each repo: the fair tasks with the same issue (issue URL, else issue "
                      "number, else the issue text) keep the lowest pull request number; the others are not drawn",
        "duplicates": {s.repo: s.counts()["duplicates"] for s in samples if s.counts()["duplicates"]},
        "stale_reads": stale,
        "inputs": {"task_files": _hashes(task_files), "screens": _hashes(screens),
                   "facts": _hashes([facts_path]) if facts_path.exists() else [], "prompts": _hashes(prompts)},
        "repos": {s.repo: s.counts() for s in samples},
        "rows": sum(len(s.rows) for s in samples),
        "command": command,
        "cmeval_version": __version__,
        "cmeval_git": _eval_git(),
        "created": now(),
    }
    write_text_atomic(out, text)
    write_json(meta_path, meta)
    return SampleResult(out, samples, True, stale)


def format_table(samples: list[RepoSample]) -> str:
    lines = []
    for s in samples:
        counts = s.counts()
        lines += [s.repo, f"  {'tier':<7} {'fair':>4} {'target':>6} {'run':>4} {'spare':>5}  {'test':>4} {'dev':>4}  labels"]
        for name in TIERS:
            c = counts["tiers"][name]
            labels = ", ".join(f"{label} {n}" for label, n in c["labels"].items()) or "-"
            lines.append(f"  {name:<7} {c['fair']:>4} {c['target']:>6} {c['run']:>4} {c['spare']:>5}  {c['test']:>4} {c['dev']:>4}  "
                         f"{labels}")
        missing = counts["run_without_prompts"]
        lines.append(f"  run tasks without L1 and L2: {len(missing)}" + (f" ({', '.join(missing)})" if missing else ""))
        dupes = counts["duplicates"]
        lines.append(f"  not run, another task of the same issue: {len(dupes)}"
                     + (f" ({', '.join(f'{d} -> {k}' for d, k in dupes.items())})" if dupes else ""))
        lines += [f"  note: {n}" for n in s.notes]
    return "\n".join(lines)
