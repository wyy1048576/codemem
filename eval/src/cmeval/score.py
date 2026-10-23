"""Score a saved run: accuracy, tokens, and latency, written next to the run files.

Scoring only reads the run, so a new metric needs no new search. Every IoU threshold is scored
in one pass: 0.5 is the main one, 0.3 and 0.7 are the sensitivity check (Decision 2).

Writes into the run folder:
    scores.jsonl      one row for each (task, system, level, iou, metric)
    summary.csv       means over tasks, plus latency rows (level "-")
    score-meta.json   token counter, model, overhead, estimate flag, IoUs, k values, budgets
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .metrics.accuracy import KS, accuracy_metrics
from .metrics.latency import index_costs, search_latency
from .metrics.matching import LEVELS, excluded, file_units, level_gold, raw_relevance
from .metrics.tokens import BUDGETS, AnthropicCounter, TokenCounter, make_counter, token_metrics
from .files import now, read_jsonl, sha256_file, write_json, write_text_atomic
from .paths import runs_dir
from .retriever import Hit
from .tasks import load_tasks

DEFAULT_IOUS = (0.5, 0.3, 0.7)
MAIN_IOU = 0.5


class ScoreError(RuntimeError):
    """The run cannot be scored (missing files, tasks file changed since the run)."""


@dataclass
class ScoreSummary:
    run_dir: Path
    rows: int
    counter: str
    estimate: bool
    table: list[dict] = field(default_factory=list)  # main numbers per system, for the CLI
    tasks_scored: int = 0
    warnings: list[str] = field(default_factory=list)


def resolve_run(run: str | Path) -> Path:
    path = Path(run)
    if not (path / "meta.json").is_file():
        path = runs_dir() / str(run)
    if not (path / "meta.json").is_file():
        raise ScoreError(f"no run folder with meta.json at {run!r} (or in {runs_dir()})")
    return path


def _check_ious(ious: tuple[float, ...]) -> tuple[float, ...]:
    bad = [i for i in ious if not 0 < i <= 1]
    if bad:
        raise ScoreError(f"IoU thresholds must be in (0, 1], got {bad}")
    rest = sorted(set(ious) - {MAIN_IOU})
    return (MAIN_IOU, *rest)  # the main threshold is always scored, each threshold once


def score(run: str | Path, *, tokens: str = "anthropic", ious: tuple[float, ...] = DEFAULT_IOUS,
          tasks_file: str | Path | None = None,
          counter: TokenCounter | None = None, warn: Callable[[str], None] = lambda message: None,
          progress: Callable[[str], None] = lambda message: None) -> ScoreSummary:
    run_dir = resolve_run(run)
    ious = _check_ious(tuple(ious))
    try:
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        # A run made on another machine names a tasks file path from that machine. Another copy
        # can be given; it must have the same sha256 as the run's.
        tasks_file = Path(tasks_file) if tasks_file is not None else Path(meta["tasks_file"])
        systems = [(s["name"], s["granularity"], s["index_key"]) for s in meta["systems"]]
        run_k = int(meta.get("k", max(KS)))
        lines = {name: read_jsonl(run_dir / f"{name}.jsonl") for name, _, _ in systems}
        index_rows = read_jsonl(run_dir / "index.jsonl")
        tasks_sha = meta["tasks_sha256"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ScoreError(f"run files in {run_dir} are not valid: {type(exc).__name__}: {exc}") from None
    if not tasks_file.is_file():
        raise ScoreError(f"tasks file {tasks_file} is missing (for a run from another machine, use --tasks FILE)")
    if sha256_file(tasks_file) != tasks_sha:
        raise ScoreError(f"tasks file {tasks_file} changed since the run; labels would not match the hits")
    tasks = {t.id: t for t in load_tasks(tasks_file)}
    ks = tuple(k for k in KS if k <= run_k)  # no recall@50 for a run that asked for 10 hits

    # ---- only tasks that every system finished, so all systems are compared on the same tasks
    warnings: list[str] = []
    if meta.get("status") != "done":
        warnings.append(f"run status is {meta.get('status')!r}, not 'done'")
    done_by_system = {name: {l["task_id"] for l in lines[name]} for name, _, _ in systems}
    shared = set.intersection(*done_by_system.values()) if done_by_system else set()
    for name, ids in done_by_system.items():
        if ids - shared:
            warnings.append(f"{name}: {len(ids - shared)} tasks left out because not every system has them")
    for message in warnings:
        warn(message)
    lines = {name: [l for l in rows if l["task_id"] in shared] for name, rows in lines.items()}

    # ---- tokens: every unique hit text, counted once
    own_counter = counter is None
    counter = counter or make_counter(tokens, warn, progress)
    try:
        texts = sorted({h["text"] for name in lines for line in lines[name] for h in line["hits"]})
        counts = dict(zip(texts, counter.count(texts)))
        overhead = counter.overhead if isinstance(counter, AnthropicCounter) else None
    finally:
        if own_counter and isinstance(counter, AnthropicCounter):
            counter.close()

    # ---- per task rows
    rows: list[dict] = []
    for name, granularity, _ in systems:
        for line in lines[name]:
            task = tasks.get(line["task_id"])
            if task is None:
                raise ScoreError(f"{name}: task {line['task_id']} is not in {tasks_file}")
            hits = [Hit.from_dict(h) for h in line["hits"]]
            hit_tokens = [counts[h.text] for h in hits]
            for level in LEVELS:
                level_ious = (None,) if level == "file" else ious
                reason = excluded(task, granularity, level)
                if reason:
                    rows.extend({"task_id": task.id, "system": name, "level": level, "iou": iou,
                                 "metric": "excluded", "value": reason} for iou in level_ious)
                    continue
                gold = level_gold(task, level)
                for iou in level_ious:
                    relevance = raw_relevance(hits, gold, level, iou if iou is not None else MAIN_IOU)
                    units = file_units(hits, relevance) if level == "file" else relevance
                    values = {**accuracy_metrics(units, len(gold), ks), **token_metrics(hit_tokens, relevance, len(gold))}
                    rows.extend({"task_id": task.id, "system": name, "level": level, "iou": iou,
                                 "metric": metric, "value": None if value is None else round(value, 6)}
                                for metric, value in values.items())

    write_text_atomic(run_dir / "scores.jsonl", "".join(json.dumps(row) + "\n" for row in rows))

    # ---- summary
    groups: dict[tuple, list] = defaultdict(list)
    n_excluded: dict[tuple, int] = defaultdict(int)
    for row in rows:
        key = (row["system"], row["level"], row["iou"])
        if row["metric"] == "excluded":
            n_excluded[key] += 1
        else:
            groups[(*key, row["metric"])].append(row["value"])
    summary_rows = []
    for (system, level, iou, metric), values in groups.items():
        present = [v for v in values if v is not None]
        mean = sum(present) / len(present) if present else None
        summary_rows.append({"system": system, "level": level, "iou": iou, "metric": metric,
                             "mean": mean, "n": len(present), "n_excluded": n_excluded[(system, level, iou)]})
        if metric == "found":
            summary_rows.append({"system": system, "level": level, "iou": iou, "metric": "not_found_share",
                                 "mean": None if mean is None else 1 - mean, "n": len(present),
                                 "n_excluded": n_excluded[(system, level, iou)]})
    first_of_group: dict[str, str] = {}
    for name, _, key in systems:
        first_of_group.setdefault(key, name)  # the system that builds and updates the shared index
    for name, _, key in systems:
        latency = {**search_latency([l["search_ms"] for l in lines[name]]), **index_costs(index_rows, first_of_group[key])}
        for metric, value in latency.items():
            summary_rows.append({"system": name, "level": "-", "iou": None, "metric": metric, "mean": value,
                                 "n": len(lines[name]), "n_excluded": 0})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["system", "level", "iou", "metric", "mean", "n", "n_excluded"], lineterminator="\n")
    writer.writeheader()
    writer.writerows(summary_rows)
    write_text_atomic(run_dir / "summary.csv", buffer.getvalue())

    score_meta = {
        "cmeval_version": __version__,
        "scored": now(),
        "run_status": meta.get("status"),
        "tasks_scored": len(shared),
        "warnings": warnings,
        "token_counter": counter.name,
        "token_estimate": counter.estimate,
        "token_overhead": overhead,
        "token_api_calls": getattr(counter, "api_calls", 0),
        "ious": list(ious),
        "main_iou": MAIN_IOU,
        "ks": list(ks),
        "budgets": list(BUDGETS),
        "texts_counted": len(texts),
    }
    write_json(run_dir / "score-meta.json", score_meta)

    # ---- main numbers for the CLI
    means = {(r["system"], r["level"], r["iou"], r["metric"]): r["mean"] for r in summary_rows}
    table = []
    for name, granularity, _ in systems:
        table.append({
            "system": name,
            "file_recall@10": means.get((name, "file", None, "recall@10")),
            "file_mrr": means.get((name, "file", None, "mrr")),
            "function_recall@10": means.get((name, "function", MAIN_IOU, "recall@10")),
            "function_mrr": means.get((name, "function", MAIN_IOU, "mrr")),
            "function_tokens_to_first": means.get((name, "function", MAIN_IOU, "tokens_to_first")),
            "search_ms_median": means.get((name, "-", None, "search_ms_median")),
        })
    return ScoreSummary(run_dir, len(rows), counter.name, counter.estimate, table, len(shared), warnings)
