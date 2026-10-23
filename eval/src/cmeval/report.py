"""The report for a scored run: report.md with the tables for the checkpoint and the team.

It reads only the scored files of a run (meta.json, score-meta.json, scores.jsonl, summary.csv)
and the run's tasks file. No search and no network.

Contents:
- main tables (file, function, class level): each mean with a 95% bootstrap interval;
- paired comparison with a baseline system (default grep-fn-plus, the stronger grep; the naive
  grep-fn stays in every table): mean difference, paired 95% bootstrap interval, Wilcoxon p;
- two primary metrics, fixed before the first results (2026-10-23): function-level MRR and
  function-level tokens to the first right answer. Their p-values get one Holm correction
  over all primary tests. Every other comparison is "exploratory" and shows a raw p;
- group tables (means and counts only), the IoU check, latency and size, task counts.

The same inputs always give the same report: tasks are taken in sorted order, the bootstrap
seed is fixed, and the report has no time stamp of its own.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from .files import read_jsonl, write_text_atomic
from .metrics.matching import LEVELS
from .metrics.stats import (RESAMPLES, SEED, WilcoxonResult, bootstrap_ci, differences, holm, wilcoxon)
from .score import MAIN_IOU, resolve_run, run_tasks

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
GROUP_METRICS = (("function", "mrr"), ("function", "recall@10"), ("file", "recall@10"), ("function", "tokens_to_first"))
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


# ---- groups


def _groups(tasks: dict, task_ids: list[str], cutoff: date) -> dict[str, dict[str, list[str]]]:
    def created(task) -> str:
        raw = task.issue.created_at
        if not raw:
            return "unknown"
        when = datetime.fromisoformat(raw)
        when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        return f"before {cutoff}" if when.astimezone(timezone.utc).date() < cutoff else f"on or after {cutoff}"

    def tag(task) -> str:
        value = task.tags.get("identifier_in_query")
        return "unknown" if value is None else str(value).lower()

    keys = {"identifier in query": tag, "repo": lambda t: t.repo, "language": lambda t: t.language,
            "issue date": created}
    out: dict[str, dict[str, list[str]]] = {}
    for name, key in keys.items():
        groups: dict[str, list[str]] = defaultdict(list)
        for task_id in task_ids:
            groups[key(tasks[task_id]) if task_id in tasks else "unknown"].append(task_id)
        out[name] = dict(sorted(groups.items()))
    return out


# ---- the report


def report(run: str | Path, *, baseline: str = DEFAULT_BASELINE, split: str = "dev", cutoff: str = DEFAULT_CUTOFF,
           tasks_file: str | Path | None = None, resamples: int = RESAMPLES, seed: int = SEED) -> ReportResult:
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
    scores = Scores(data["scores"])
    task_ids = sorted(scores.task_ids)
    kw = {"resamples": resamples, "seed": seed}
    granularity = {name: g for name, g, _ in systems}
    line_systems = [name for name in names if granularity[name] != "file"]

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
    family = [c for c in comparisons if (c.level, c.metric) in PRIMARY and c.system in line_systems]
    for c, p in zip(family, holm([c.test.p for c in family])):
        c.primary, c.p_holm = True, p

    warnings = _warnings(meta, score_meta, data["summary"], task_ids)
    text = _render(run_dir, meta, score_meta, systems, baseline, scores, task_ids, tasks, comparisons, family,
                   warnings, cutoff_date, kw, data["summary"])
    path = run_dir / "report.md"
    write_text_atomic(path, text)
    return ReportResult(run_dir, path, len(task_ids), warnings, family)


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
    sessions = [] if meta.get("merged_from") else meta.get("sessions") or []  # a merge lists its parts instead
    kinds = {(json.dumps(s.get("cmeval_git"), sort_keys=True), (s.get("machine") or {}).get("platform")) for s in sessions}
    if len(kinds) > 1:
        out.append(f"the run was made in {len(sessions)} sessions with different code or machines: "
                   + "; ".join(f"{(s.get('machine') or {}).get('platform')} at {(s.get('cmeval_git') or {}).get('sha', '')[:12]}"
                               for s in sessions))
    ended, scored = meta.get("ended"), score_meta.get("scored")
    if ended and scored and datetime.fromisoformat(ended) > datetime.fromisoformat(scored):
        out.append("the run changed after it was scored: score it again")
    if score_meta.get("tasks_scored") not in (None, len(task_ids)):
        out.append(f"score-meta.json says {score_meta['tasks_scored']} tasks, scores.jsonl has {len(task_ids)}: score it again")
    return out


def _render(run_dir, meta, score_meta, systems, baseline, scores: Scores, task_ids, tasks, comparisons, family,
            warnings, cutoff, kw, summary) -> str:
    names = [name for name, _, _ in systems]
    granularity = {name: g for name, g, _ in systems}
    git = meta.get("cmeval_git") or {}
    codemem = next((s["describe"].get("codemem_git") for s in meta["systems"] if s.get("adapter") == "codemem"), None)
    lines = [
        f"# Results: {run_dir.name}", "",
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
              f"### Primary metrics (Holm correction over all {len(family)} tests, significant at {ALPHA})", ""]
    if family:
        lines += [f"| system | metric | tasks | {baseline} | system | difference [95% CI] | Wilcoxon p | Holm p | significant |",
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
    return "\n".join(lines) + "\n"
