"""The report for a scored run: report.md with the tables for the checkpoint and the team.

It reads only the scored files of a run (meta.json, score-meta.json, scores.jsonl, summary.csv)
and the run's tasks file. No search and no network.

Contents:
- main tables (file, function, class level): each mean with a 95% bootstrap interval;
- paired comparison with a baseline system (default grep-fn-plus, the stronger grep; the naive
  grep-fn stays in every table): mean difference, paired 95% bootstrap interval, Wilcoxon p;
- two primary metrics, fixed before the first results (2026-10-23): function-level MRR and
  function-level tokens to the first right answer, for each primary system. The primary systems
  are a family for each codemem version (PRIMARY_FAMILIES): the MVP family fixed 2026-10-23
  (3 systems), the v3 family fixed 2026-10-25 (cm3-full alone, before any fresh codemem result,
  after the first v3 dev results on 13 small-repo tasks). Their p-values get one Holm correction
  over all primary tests. Every other
  comparison, including other grep variants, is "exploratory" and shows a raw p;
- group tables (means and counts only), the IoU check, latency and size, task counts.

A filter (--where gold_all_python=true) limits the report to the tasks whose tags match. The main
comparison uses only the tasks with all-Python gold (decision of 2026-10-24). The tasks left out
get a short section of their own at the end.

The same inputs always give the same report: tasks are taken in sorted order, the bootstrap
seed is fixed, and the report has no time stamp of its own.
"""

from __future__ import annotations

import csv
import json
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from .files import read_jsonl, write_text_atomic
from .metrics.matching import LEVELS
from .metrics.stats import (RESAMPLES, SEED, WilcoxonResult, bootstrap_ci, differences, holm, wilcoxon)
from .paths import default_configs_dir
from .score import MAIN_IOU, resolve_run, run_tasks
from .tasks import WhereError, check_where_keys, task_matches
from .tasks import parse_where as _parse_where

DEFAULT_BASELINE = "grep-fn-plus"  # the stronger grep (2026-10-23); older runs: --baseline grep-fn
DEFAULT_CUTOFF = "2026-07-01"
ALPHA = 0.05
SMALL_N = 20  # below this, percentile bootstrap intervals are too narrow
HEADLINE = ("recall@1", "recall@5", "recall@10", "mrr", "success@10",
            "recall@budget1000", "recall@budget4000", "tokens_to_first", "not_found_share")
ACCURACY = HEADLINE[:5]
COST = HEADLINE[5:]
LOWER_IS_BETTER = frozenset({"tokens_to_first", "not_found_share"})
COUNTS = frozenset({"tokens_to_first"})  # in tokens, not between 0 and 1
PRIMARY = (("function", "mrr"), ("function", "tokens_to_first"))
# The systems under test for the primary tests: one family for each codemem version, each fixed in
# the design before its fresh results, newest first. The MVP family is the ladder keywords, + code,
# + usage; the v3 family is codemem's default alone (Andrew, 2026-10-25). The family of tests is
# PRIMARY x these systems, so its size never depends on which other systems a run has.
# A run without --primary uses the newest family whose systems are all in it, so a committed run of
# an older version still reports with the plain command. A family with a config file is also checked
# against it: the run's definition of each system must be the fixed one, so a system that only has the
# name cannot take the family's place. (The MVP family is from before this check.)
PRIMARY_FAMILIES = (
    ("codemem v3, fixed 2026-10-25", ("cm3-full",), "codemem-v3-full.toml"),
    ("codemem MVP, fixed 2026-10-23", ("cm-bm25", "cm-bm25-code", "cm-bm25-code-usage"), None),  # configs/baseline.toml
)
PRIMARY_SYSTEMS = PRIMARY_FAMILIES[0][1]  # the current family
GROUP_METRICS = (("function", "mrr"), ("function", "recall@10"), ("file", "recall@10"), ("function", "tokens_to_first"))
# Group cutoffs live here, not in the tasks, so they can change without a new collection.
REPO_SIZE_CUTOFFS = (1000, 5000)  # Python files: small < 1,000, medium 1,000 to 5,000, large > 5,000 (agreed 2026-10-25)
FIX_LINES_CUTOFFS = (10, 50)  # changed code lines: up to 10, 11 to 50, over 50
IOU_METRICS = ("mrr", "recall@10")
IOUS = (0.3, 0.5, 0.7)
LATENCY = (("search_ms_median", "search ms (median)"), ("search_ms_p95", "search ms (p95)"),
           ("build_seconds_mean", "build s (mean)"), ("update_seconds_median", "update s (median)"),
           ("items_reembedded_mean", "items re-embedded (mean)"), ("index_bytes_max", "index MB"),
           ("files_failed_max", "files failed"))
SHARED_COSTS = frozenset({"build_seconds_mean", "update_seconds_median", "items_reembedded_mean",
                          "index_bytes_max", "files_failed_max"})


class ReportError(RuntimeError):
    """The run cannot be reported (not scored, wrong split, unknown baseline)."""


@dataclass
class Comparison:
    system: str
    level: str
    metric: str
    n: int
    baseline_mean: float | None
    system_mean: float | None
    diff: float | None
    ci: tuple[float, float] | None
    test: WilcoxonResult
    primary: bool = False
    p_holm: float | None = None
    found: dict[str, int] | None = None  # tokens_to_first: found by both, system only, baseline only, neither


@dataclass
class ReportResult:
    run_dir: Path
    report_path: Path
    tasks_scored: int
    warnings: list[str] = field(default_factory=list)
    primary: list[Comparison] = field(default_factory=list)
    filter: str | None = None  # the --where conditions, as written
    left_out: int = 0  # scored tasks that the filter left out


# ---- loading


def _load(run_dir: Path) -> dict:
    try:
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        score_meta_path = run_dir / "score-meta.json"
        if not score_meta_path.is_file() or not (run_dir / "scores.jsonl").is_file():
            raise ReportError(f"{run_dir} is not scored yet: run `cmeval score {run_dir.name}` first")
        score_meta = json.loads(score_meta_path.read_text(encoding="utf-8"))
        scores = read_jsonl(run_dir / "scores.jsonl")
        with (run_dir / "summary.csv").open(encoding="utf-8", newline="") as f:
            summary = list(csv.DictReader(f))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise ReportError(f"run files in {run_dir} are not valid: {type(exc).__name__}: {exc}") from None
    return {"meta": meta, "score_meta": score_meta, "scores": scores, "summary": summary}


class Scores:
    """Per-task values from scores.jsonl: values[(system, level, iou, metric)][task_id]."""

    def __init__(self, rows: list[dict]):
        self.values: dict[tuple, dict[str, float | None]] = defaultdict(dict)
        self.excluded: dict[tuple, dict[str, str]] = defaultdict(dict)  # (system, level) -> task -> reason
        self.task_ids: set[str] = set()
        for row in rows:
            self.task_ids.add(row["task_id"])
            iou = row["iou"]
            if row["metric"] == "excluded":
                if iou is None or iou == MAIN_IOU:
                    self.excluded[(row["system"], row["level"])][row["task_id"]] = row["value"]
                continue
            self.values[(row["system"], row["level"], iou, row["metric"])][row["task_id"]] = row["value"]
            if row["metric"] == "found":
                not_found = None if row["value"] is None else 1 - row["value"]
                self.values[(row["system"], row["level"], iou, "not_found_share")][row["task_id"]] = not_found

    def get(self, system: str, level: str, metric: str, iou: float | None = MAIN_IOU) -> dict[str, float | None]:
        return self.values.get((system, level, None if level == "file" else iou, metric), {})

    def vector(self, system: str, level: str, metric: str, task_ids=None, iou: float | None = MAIN_IOU) -> list[float]:
        """Values in sorted task order, without None. task_ids limits the tasks."""
        values = self.get(system, level, metric, iou)
        ids = sorted(values if task_ids is None else set(task_ids) & set(values))
        return [values[t] for t in ids if values[t] is not None]


# ---- numbers


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _fmt(value: float | None, metric: str = "", signed: bool = False) -> str:
    if value is None:
        return "-"
    sign = "+" if signed else ""
    return f"{value:{sign},.0f}" if metric in COUNTS else f"{value:{sign}.3f}"


def _fmt_ci(ci: tuple[float, float] | None, metric: str = "", signed: bool = False) -> str:
    return "" if ci is None else f" [{_fmt(ci[0], metric, signed)}, {_fmt(ci[1], metric, signed)}]"


def _fmt_p(p: float | None) -> str:
    return "-" if p is None else "<0.001" if p < 0.001 else f"{p:.3f}"


def _label(metric: str) -> str:
    return f"{metric} (lower is better)" if metric in LOWER_IS_BETTER else metric


def _compare(scores: Scores, system: str, baseline: str, level: str, metric: str, **kw) -> Comparison:
    a, b = scores.get(system, level, metric), scores.get(baseline, level, metric)
    ids = sorted(t for t in set(a) & set(b) if a[t] is not None and b[t] is not None)
    x, y = [a[t] for t in ids], [b[t] for t in ids]
    d = differences(x, y)
    found = None
    if metric == "tokens_to_first":
        fa, fb = scores.get(system, level, "found"), scores.get(baseline, level, "found")
        both = sorted(set(fa) & set(fb))
        found = Counter("both" if fa[t] and fb[t] else "system only" if fa[t] else "baseline only" if fb[t]
                        else "neither" for t in both if fa[t] is not None and fb[t] is not None)
        found = {key: found.get(key, 0) for key in ("both", "system only", "baseline only", "neither")}
    return Comparison(system, level, metric, len(ids), _mean(y), _mean(x), _mean(d), bootstrap_ci(d, **kw),
                      wilcoxon(d), found=found)


def default_primary(names: list[str], has_codemem: bool, config_text: str | None = None) -> tuple[str, tuple[str, ...]]:
    """(label, systems) for the primary tests when --primary is not given.

    A run with no codemem system has none. A codemem run gets the newest family whose systems are all
    in it. A codemem run that fits no family is an error: a renamed system must never drop the
    primary tests without notice. If the family has a config file, the run's definitions (from its
    config_text) must equal the fixed ones.
    """
    if not has_codemem:
        return "none (no codemem system in this run)", ()
    for label, family, config_file in PRIMARY_FAMILIES:
        if all(name in names for name in family):
            if config_file:
                _check_definitions(family, config_file, config_text)
            return label, family
    known = "; ".join(f"{label}: {', '.join(family)}" for label, family, _ in PRIMARY_FAMILIES)
    raise ReportError(f"no primary family fits this run's systems {names} (known families: {known}); "
                      "choose them with --primary")


def _check_definitions(family: tuple[str, ...], config_file: str, config_text: str | None) -> None:
    """Each system of the family must be defined in the run as in configs/<config_file>."""
    fixed = {spec["name"]: spec for spec in tomllib.loads((default_configs_dir() / config_file).read_text("utf-8"))["system"]}
    try:
        used = {spec["name"]: spec for spec in tomllib.loads(config_text or "").get("system", [])}
    except tomllib.TOMLDecodeError:
        used = {}
    changed = [name for name in family if used.get(name) != fixed[name]]
    if changed:
        raise ReportError(f"{changed} in this run are not defined as in configs/{config_file} (the fixed primary family); "
                          "choose the primary systems with --primary")


# ---- the filter


def parse_where(conditions: list[str] | None) -> list[tuple[str, object]]:
    """tasks.parse_where, with its errors as ReportError."""
    try:
        return _parse_where(conditions)
    except WhereError as exc:
        raise ReportError(str(exc)) from None


def _select(tasks: dict, task_ids: list[str], conditions: list[tuple[str, object]]) -> list[str]:
    """The scored tasks that match every condition. Unknown keys and an empty result are errors."""
    try:
        check_where_keys([tasks[t] for t in task_ids if t in tasks], conditions, what="scored task")
    except WhereError as exc:
        raise ReportError(str(exc)) from None
    kept = [t for t in task_ids if t in tasks and task_matches(tasks[t], conditions)]
    if not kept:
        raise ReportError("no scored task matches the filter")
    return kept


# ---- groups


def _groups(tasks: dict, task_ids: list[str], cutoff: date) -> dict[str, dict[str, list[str]]]:
    """Group name -> {group value -> task ids}. Size groups keep their natural order (small, medium,
    large); the others are sorted. A task without the tag is "unknown" (for example SWE-bench tasks)."""
    def created(task) -> str:
        raw = task.issue.created_at
        if not raw:
            return "unknown"
        when = datetime.fromisoformat(raw)
        when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        return f"before {cutoff}" if when.astimezone(timezone.utc).date() < cutoff else f"on or after {cutoff}"

    def tag(name: str):
        def read(task) -> str:
            value = task.tags.get(name)
            return "unknown" if value is None else str(value).lower()
        return read

    def repo_size(task) -> str:
        n = task.tags.get("repo_py_files")
        small, large = REPO_SIZE_CUTOFFS
        if n is None:
            return "unknown"
        return f"small (< {small:,})" if n < small else f"medium ({small:,} to {large:,})" if n <= large else f"large (> {large:,})"

    def fix_lines(task) -> str:
        n = task.tags.get("code_lines_changed")
        low, high = FIX_LINES_CUTOFFS
        if n is None:
            return "unknown"
        return f"up to {low}" if n <= low else f"{low + 1} to {high}" if n <= high else f"over {high}"

    def gold_files(task) -> str:
        n = task.tags.get("n_gold_files")
        return "unknown" if n is None else "1" if n <= 1 else "2 or more"

    small, large = REPO_SIZE_CUTOFFS
    low, high = FIX_LINES_CUTOFFS
    ordered = {  # group name -> (key, natural order of its values, or None to sort)
        "identifier in query": (tag("identifier_in_query"), None),
        "repo": (lambda t: t.repo, None),
        "language": (lambda t: t.language, None),
        "issue date": (created, None),
        "gold all Python": (tag("gold_all_python"), None),
        "repo size (Python files)": (
            repo_size, [f"small (< {small:,})", f"medium ({small:,} to {large:,})", f"large (> {large:,})"]),
        "fix size (changed code lines)": (fix_lines, [f"up to {low}", f"{low + 1} to {high}", f"over {high}"]),
        "gold files": (gold_files, ["1", "2 or more"]),
    }
    out: dict[str, dict[str, list[str]]] = {}
    for name, (key, order) in ordered.items():
        groups: dict[str, list[str]] = defaultdict(list)
        for task_id in task_ids:
            groups[key(tasks[task_id]) if task_id in tasks else "unknown"].append(task_id)
        rank = {value: i for i, value in enumerate(order or [])}
        out[name] = dict(sorted(groups.items(), key=lambda kv: (rank.get(kv[0], len(rank)), kv[0])))
    return out


# ---- the report


def report(run: str | Path, *, baseline: str = DEFAULT_BASELINE, split: str = "dev", cutoff: str = DEFAULT_CUTOFF,
           primary: list[str] | tuple[str, ...] | None = None, where: list[str] | None = None,
           tasks_file: str | Path | None = None, resamples: int = RESAMPLES, seed: int = SEED) -> ReportResult:
    conditions = parse_where(where)
    run_dir = resolve_run(run)
    data = _load(run_dir)
    meta, score_meta = data["meta"], data["score_meta"]
    if meta.get("split") != split:
        raise ReportError(f"run {run_dir.name} is on the {meta.get('split')} split; pass --split {meta.get('split')}"
                          " (the test split is only reported when asked for, Decision 1)")
    try:
        cutoff_date = date.fromisoformat(cutoff)
    except ValueError:
        raise ReportError(f"cutoff {cutoff!r} is not a date (YYYY-MM-DD)") from None
    systems = [(s["name"], s["granularity"], s["index_key"]) for s in meta["systems"]]
    names = [name for name, _, _ in systems]
    if baseline not in names:
        raise ReportError(f"baseline {baseline!r} is not a system of this run; choose from {names}")
    _, tasks = run_tasks(meta, tasks_file)
    all_ids = sorted({row["task_id"] for row in data["scores"]})
    task_ids = _select(tasks, all_ids, conditions) if conditions else all_ids
    kept = set(task_ids)
    # Every table below reads these scores, so the filter applies to all of them.
    scores = Scores([row for row in data["scores"] if row["task_id"] in kept])
    left_out = Scores([row for row in data["scores"] if row["task_id"] not in kept])
    kw = {"resamples": resamples, "seed": seed}
    granularity = {name: g for name, g, _ in systems}
    # The default primary systems are the codemem systems of the design. A run with no codemem
    # system at all (a grep-only run) has no primary tests; a codemem run must name them right.
    has_codemem = any(s.get("adapter") == "codemem" for s in meta["systems"])
    if primary is not None:
        primary_label, under_test = "chosen with --primary", list(dict.fromkeys(primary))
    else:
        primary_label, family_systems = default_primary(names, has_codemem, meta.get("config_text"))
        under_test = list(family_systems)
    bad = [n for n in under_test if n not in names or n == baseline or granularity[n] == "file"]
    if bad:
        raise ReportError(f"primary systems {bad} are not function-level systems of this run other than the "
                          f"baseline; the run has {names} (choose them with --primary)")

    # paired comparisons; the primary family is fixed by the design, not by the results
    comparisons: list[Comparison] = []
    for name in names:
        if name == baseline:
            continue
        for level in LEVELS:
            if level != "file" and (granularity[name] == "file" or granularity[baseline] == "file"):
                continue
            for metric in HEADLINE:
                comparisons.append(_compare(scores, name, baseline, level, metric, **kw))
    family = [c for c in comparisons if (c.level, c.metric) in PRIMARY and c.system in under_test]
    for c, p in zip(family, holm([c.test.p for c in family])):
        c.primary, c.p_holm = True, p

    warnings = _warnings(meta, score_meta, data["summary"], all_ids)  # all scored tasks, not only the kept ones
    where_text = ", ".join(where or []) or None
    text = _render(run_dir, meta, score_meta, systems, baseline, scores, task_ids, tasks, comparisons, family,
                   warnings, cutoff_date, kw, data["summary"],
                   filtered=(where_text, all_ids, left_out) if conditions else None,
                   no_primary=not has_codemem and primary is None, primary_label=primary_label)
    path = run_dir / "report.md"
    write_text_atomic(path, text)
    return ReportResult(run_dir, path, len(task_ids), warnings, family, where_text, len(all_ids) - len(task_ids))


def _warnings(meta: dict, score_meta: dict, summary: list[dict], task_ids: list[str]) -> list[str]:
    out = []
    if meta.get("status") != "done":
        out.append(f"run status is {meta.get('status')!r}, not 'done': not every task was searched")
    out += [f"scoring: {w}" for w in score_meta.get("warnings", [])]
    if score_meta.get("token_estimate"):
        out.append("TOKEN NUMBERS ARE ROUGH ESTIMATES: never report them (score again with an API key)")
    for row in summary:
        if row["metric"] == "files_failed_max" and row["mean"] and float(row["mean"]) > 0:
            out.append(f"{row['system']}: up to {float(row['mean']):.0f} files could not be indexed")
    # Each run (or each part of a merged run) must come from one code version on one machine.
    # The parts of a merged run may differ from each other: the header lists them.
    parts = meta.get("merged_from") or [{"run_id": meta.get("run_id"), "sessions": meta.get("sessions")}]
    for part in parts:
        sessions = part.get("sessions") or []
        kinds = {(json.dumps(s.get("cmeval_git"), sort_keys=True), (s.get("machine") or {}).get("platform"))
                 for s in sessions}
        if len(kinds) > 1:
            out.append(f"run {part.get('run_id')} was made in {len(sessions)} sessions with different code or machines: "
                       + "; ".join(f"{(s.get('machine') or {}).get('platform')} at "
                                   f"{((s.get('cmeval_git') or {}).get('sha') or '')[:12]}" for s in sessions))
    ended, scored = meta.get("ended"), score_meta.get("scored")
    if ended and scored and datetime.fromisoformat(ended) > datetime.fromisoformat(scored):
        out.append("the run changed after it was scored: score it again")
    if score_meta.get("tasks_scored") not in (None, len(task_ids)):
        out.append(f"score-meta.json says {score_meta['tasks_scored']} tasks, scores.jsonl has {len(task_ids)}: score it again")
    return out


def _group_table(lines: list[str], scores: Scores, names: list[str], granularity: dict, groups: dict[str, list[str]]) -> None:
    """Means and counts for each group, one table for each group metric."""
    for level, metric in GROUP_METRICS:
        shown = [n for n in names if level == "file" or granularity[n] != "file"]
        lines += [f"{level.capitalize()} {_label(metric)}:", "", "| group | tasks | " + " | ".join(shown) + " |",
                  "|---" * (len(shown) + 2) + "|"]
        for group, ids in groups.items():
            cells = []
            for name in shown:
                values = scores.vector(name, level, metric, ids)
                cells.append(f"{_fmt(_mean(values), metric)} ({len(values)})")
            lines.append(f"| {group} | {len(ids)} | " + " | ".join(cells) + " |")
        lines.append("")


def _render(run_dir, meta, score_meta, systems, baseline, scores: Scores, task_ids, tasks, comparisons, family,
            warnings, cutoff, kw, summary, filtered=None, no_primary=False, primary_label="") -> str:
    names = [name for name, _, _ in systems]
    granularity = {name: g for name, g, _ in systems}
    git = meta.get("cmeval_git") or {}
    codemem = next((s["describe"].get("codemem_git") for s in meta["systems"] if s.get("adapter") == "codemem"), None)
    lines = [
        f"# Results: {meta.get('run_id') or run_dir.name}", "",  # the run id, also for a copied folder
        f"- Tasks: `{Path(meta.get('tasks_file', '')).name}` (sha256 {meta.get('tasks_sha256', '')[:12]}), "
        f"split {meta.get('split')}, {len(task_ids)} tasks scored",
        f"- Systems: {', '.join(names)}; baseline for the paired tests: {baseline}",
        f"- Index mode: {meta.get('index_mode')}; hits per search: {meta.get('k')}",
        f"- Code: cmeval {git.get('sha', '')[:12]}{' (uncommitted changes)' if git.get('dirty') else ''}"
        + (f", codemem {(codemem or {}).get('sha', '')[:12]}{' (uncommitted changes)' if (codemem or {}).get('dirty') else ''}"
           if codemem else ""),
        f"- Machine: {(meta.get('machine') or {}).get('platform')}",
        f"- Tokens: {score_meta.get('token_counter')}, request overhead of {score_meta.get('token_overhead')} tokens "
        f"taken off each count; scored {score_meta.get('scored')}",
        f"- Intervals: 95% percentile bootstrap, {kw['resamples']:,} resamples, seed {kw['seed']}",
    ]
    if filtered:
        where_text, all_ids, _ = filtered
        lines.insert(2, f"- Filter: {where_text}: {len(task_ids)} of {len(all_ids)} scored tasks "
                        f"({len(all_ids) - len(task_ids)} left out; see 'Tasks left out by the filter')")
    for part in meta.get("merged_from") or []:
        lines.append(f"- Merged part: {', '.join(part['systems'])} from run `{part['run_id']}` "
                     f"(cmeval {((part.get('cmeval_git') or {}).get('sha') or '')[:12]}, "
                     f"{(part.get('machine') or {}).get('platform')}, ended {part.get('ended')})")
    if meta.get("split") == "dev":
        lines.append("- Dev split: these numbers guide development. p-values here are guidance only.")
    if warnings:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in warnings]

    # ---- main tables
    lines += ["", "## Main results", ""]
    small = len(task_ids) < SMALL_N
    if small:
        lines.append(f"Only {len(task_ids)} tasks: percentile bootstrap intervals are too narrow at this size.\n")
    for level in ("file", "function", "class"):
        title = "File level" if level == "file" else f"{level.capitalize()} level (IoU {MAIN_IOU})"
        for part, metrics in (("accuracy", ACCURACY), ("tokens", COST)):
            lines += [f"### {title}: {part}", "", "| system | tasks | " + " | ".join(map(_label, metrics)) + " |",
                      "|---" * (len(metrics) + 2) + "|"]
            for name in names:
                if level != "file" and granularity[name] == "file":
                    lines.append(f"| {name} | - | " + " | ".join("n/a" for _ in metrics) + " |")
                    continue
                n = len(scores.vector(name, level, "mrr"))
                cells = []
                for metric in metrics:
                    values = scores.vector(name, level, metric)
                    cells.append(_fmt(_mean(values), metric) + _fmt_ci(bootstrap_ci(values, **kw), metric))
                lines.append(f"| {name} | {n} | " + " | ".join(cells) + " |")
            lines.append("")
    lines.append("tokens_to_first is the mean over the tasks where the system found the right item, so each "
                 "system's mean is over its own set of tasks. not_found_share shows how many it missed.")

    # ---- paired comparisons
    lines += ["", f"## Paired comparison with {baseline}", "",
              f"Difference = system - {baseline} on the same tasks. A confidence interval and a p-value can "
              "disagree: the interval is about the mean, the Wilcoxon test is about signed ranks.", "",
              "### Primary metrics" + ("" if no_primary else f" (Holm correction over all {len(family)} tests, significant at {ALPHA})"), ""]
    if no_primary:
        lines.append("No primary systems in this run (it has no codemem system): every comparison is exploratory.")
    elif family:
        lines += [f"Primary systems: {', '.join(dict.fromkeys(c.system for c in family))} ({primary_label}).", "",
                  f"| system | metric | tasks | {baseline} | system | difference [95% CI] | Wilcoxon p | Holm p | significant |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for c in family:
            significant = "yes" if c.p_holm is not None and c.p_holm <= ALPHA and c.test.p is not None else "no"
            lines.append(f"| {c.system} | {c.level} {_label(c.metric)} | {c.n} | {_fmt(c.baseline_mean, c.metric)} "
                         f"| {_fmt(c.system_mean, c.metric)} | {_fmt(c.diff, c.metric, True)}{_fmt_ci(c.ci, c.metric, True)} "
                         f"| {_fmt_p(c.test.p)} ({c.test.method}) | {_fmt_p(c.p_holm)} | {significant} |")
        lines += ["", "Tokens to the first right function are paired on the tasks both systems found:", "",
                  f"| system | found by both | system only | {baseline} only | neither |", "|---|---|---|---|---|"]
        for c in family:
            if c.found is not None:
                lines.append(f"| {c.system} | {c.found['both']} | {c.found['system only']} | "
                             f"{c.found['baseline only']} | {c.found['neither']} |")
    else:
        lines.append(f"n/a: the baseline {baseline} has no function-level results.")
    lines += ["", "### Exploratory (raw p, no correction)", ""]
    for level in ("file", "function", "class"):
        rows = [c for c in comparisons if c.level == level and not c.primary]
        if not rows:
            continue
        lines += [f"#### {level.capitalize()} level", "",
                  "| system | metric | tasks | difference [95% CI] | Wilcoxon p |", "|---|---|---|---|---|"]
        for c in rows:
            lines.append(f"| {c.system} | {_label(c.metric)} | {c.n} | {_fmt(c.diff, c.metric, True)}"
                         f"{_fmt_ci(c.ci, c.metric, True)} | {_fmt_p(c.test.p)} |")
        lines.append("")

    # ---- groups
    lines += ["## Groups (means and task counts, no intervals)", ""]
    for grouping, groups in _groups(tasks, task_ids, cutoff).items():
        if len(groups) == 1:
            (only, ids), = groups.items()
            lines += [f"- {grouping}: all {len(ids)} tasks are '{only}', so there is no table.", ""]
            continue
        lines += [f"### By {grouping}", ""]
        _group_table(lines, scores, names, granularity, groups)

    # ---- IoU check
    lines += ["## IoU check (function level)", "", "| system | " + " | ".join(
        f"{m} @ IoU {iou}" for m in IOU_METRICS for iou in IOUS) + " |", "|---" * (len(IOU_METRICS) * len(IOUS) + 1) + "|"]
    for name in names:
        if granularity[name] == "file":
            continue
        lines.append(f"| {name} | " + " | ".join(_fmt(_mean(scores.vector(name, "function", m, iou=iou)), m)
                                            for m in IOU_METRICS for iou in IOUS) + " |")

    # ---- latency and size
    latency = {(r["system"], r["metric"]): r["mean"] for r in summary if r["level"] == "-"}
    owner: dict[str, str] = {}
    for name, _, key in systems:
        owner.setdefault(key, name)
    lines += ["", "## Latency and size", "", "| system | " + " | ".join(label for _, label in LATENCY) + " |",
              "|---" * (len(LATENCY) + 1) + "|"]
    for name, _, key in systems:
        cells = []
        for metric, _ in LATENCY:
            if metric in SHARED_COSTS and owner[key] != name:
                cells.append(f"same as {owner[key]}")
                continue
            raw = latency.get((name, metric))
            value = float(raw) if raw not in (None, "") else None
            if metric == "index_bytes_max" and value is not None:
                value = value / 1e6
            cells.append("-" if value is None else f"{value:,.1f}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append("\nIndex MB = 10^6 bytes. Systems with the same index settings share one index.")
    if filtered:
        lines.append(f"Latency and size come from summary.csv, over all {len(filtered[1])} scored tasks: the filter does not apply to them.")
    if meta.get("merged_from"):
        lines.append("This run is merged from separate runs, so search times of different parts come from different sessions.")

    # ---- task counts
    lines += ["", "## Task counts", "", f"{len(task_ids)} tasks scored. Tasks left out at each level:", "",
              "| system | level | left out | reasons |", "|---|---|---|---|"]
    for name in names:
        for level in LEVELS:
            reasons = Counter(scores.excluded.get((name, level), {}).values())
            if reasons:
                text = ", ".join(f"{reason}: {count}" for reason, count in sorted(reasons.items()))
                lines.append(f"| {name} | {level} | {sum(reasons.values())} | {text} |")

    # ---- tasks left out by the filter (for the gold_all_python filter: the "not supported" group)
    if filtered:
        where_text, all_ids, left_out = filtered
        out_ids = sorted(set(all_ids) - set(task_ids))
        lines += ["", "## Tasks left out by the filter", "",
                  f"{len(out_ids)} scored tasks do not match {where_text}. Means and counts only, no intervals.", ""]
        if out_ids:
            _group_table(lines, left_out, names, granularity, {"left out": out_ids})
    return "\n".join(lines) + "\n"
