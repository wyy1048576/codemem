"""The update vs. rebuild check (F3 B4, Decision 5): compare two scored runs of the same tasks.

The runner moves one index forward with updates. That is valid only if an updated index finds
the same code as a fresh build. Run the same tasks with --index-mode update and with
--index-mode rebuild, score both, then compare:
- top 10: at least 95% of tasks must have the same set of top-10 hits, for each system;
- metrics: every metric's mean must differ by less than 0.01, and token counts by less than 1%.

Hits are compared by location (path and lines), never by text: codemem's card text shows a
chunk id, and the ids differ between the two modes by design.

A task with a different top 10 is not always a bug. Two hits with almost the same score can
swap places because of GPU rounding. So each differing hit gets a hint for the person who
reads the report: "near tie", "stale" (not in the code at that commit: a real update bug), or
"check". The report is written to compare-<other run>.md in the first run's folder.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import repos
from .files import read_jsonl, write_text_atomic
from .score import resolve_run
from .tasks import load_tasks

TOP = 10
MIN_SAME_TOP = 0.95
MAX_DIFF = 0.01  # for metrics between 0 and 1
MAX_RELATIVE_DIFF = 0.01  # for metrics that count tokens
COUNT_METRICS = frozenset({"tokens_to_first"})
# Hint "near tie": the hit is just outside the other run's top 10, and its score there is
# within 1% of the score at rank 10.
NEAR_TIE_RANK = 20
NEAR_TIE_GAP = 0.01


class CompareError(RuntimeError):
    """The two runs cannot be compared (not scored, other tasks, other systems)."""


@dataclass
class SystemResult:
    system: str
    tasks: int = 0
    same_top: int = 0
    metric_diffs: list[dict] = field(default_factory=list)  # only the ones over the limit
    largest_diff: float = 0.0
    largest_relative_diff: float = 0.0
    differences: list[dict] = field(default_factory=list)  # one entry for each task with another top 10

    @property
    def share_same_top(self) -> float:
        return self.same_top / self.tasks if self.tasks else 1.0

    @property
    def passed(self) -> bool:
        return self.share_same_top >= MIN_SAME_TOP and not self.metric_diffs


@dataclass
class CompareResult:
    run_a: Path
    run_b: Path
    systems: list[SystemResult]
    report_path: Path

    @property
    def passed(self) -> bool:
        return all(s.passed for s in self.systems)


def _location(hit: dict) -> tuple:
    return hit["path"], hit.get("start_line"), hit.get("end_line")


def _load(run: Path) -> dict:
    try:
        meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        if not (run / "scores.jsonl").is_file():
            raise CompareError(f"{run} is not scored yet: run `cmeval score {run.name}` first")
        lines = {s["name"]: {l["task_id"]: l for l in read_jsonl(run / f"{s['name']}.jsonl")} for s in meta["systems"]}
        scores = read_jsonl(run / "scores.jsonl")
    except (ValueError, KeyError, TypeError) as exc:
        raise CompareError(f"run files in {run} are not valid: {type(exc).__name__}: {exc}") from None
    return {"meta": meta, "lines": lines, "scores": scores}


def _means(scores: list[dict], system: str, task_ids: set[str]) -> dict[tuple, float | None]:
    values: dict[tuple, list[float]] = defaultdict(list)
    for row in scores:
        if row["system"] != system or row["task_id"] not in task_ids or row["metric"] == "excluded":
            continue
        bucket = values[(row["level"], row["iou"], row["metric"])]  # kept even if every value is None
        if row["value"] is not None:
            bucket.append(row["value"])
    return {key: (sum(v) / len(v) if v else None) for key, v in values.items()}


def in_code(repo: str, commit: str, hit: dict) -> bool:
    """True if the hit's file exists at the commit and has the hit's lines."""
    text = repos.read_file(repo, commit, hit["path"])
    if text is None:
        return False
    end = hit.get("end_line")
    return end is None or end <= len(text.splitlines())


def _hint(hit: dict, other_hits: list[dict], exists: bool) -> str:
    if not exists:
        return "stale"
    ranks = {_location(h): i for i, h in enumerate(other_hits, start=1)}
    rank = ranks.get(_location(hit))
    if rank is None or rank > NEAR_TIE_RANK or len(other_hits) < TOP:
        return "check"
    tenth = other_hits[TOP - 1]["score"]
    gap = abs(other_hits[rank - 1]["score"] - tenth) / max(abs(tenth), 1e-12)
    return "near tie" if gap <= NEAR_TIE_GAP else "check"


def _top_difference(line_a: dict, line_b: dict, repo: str, exists: Callable) -> list[dict]:
    """Hits in one top 10 and not the other, with ranks and scores in both runs and a hint."""
    hits_a, hits_b = line_a["hits"], line_b["hits"]
    top_a = {_location(h) for h in hits_a[:TOP]}
    top_b = {_location(h) for h in hits_b[:TOP]}
    rank_a = {_location(h): (i, h["score"]) for i, h in enumerate(hits_a, start=1)}
    rank_b = {_location(h): (i, h["score"]) for i, h in enumerate(hits_b, start=1)}
    rows = []
    for only, hits, other, side in ((top_a - top_b, hits_a, hits_b, "a"), (top_b - top_a, hits_b, hits_a, "b")):
        for hit in hits:
            if _location(hit) not in only:
                continue
            ra, rb = rank_a.get(_location(hit)), rank_b.get(_location(hit))
            rows.append({
                "only_in": side, "path": hit["path"], "start_line": hit.get("start_line"), "end_line": hit.get("end_line"),
                "symbol": hit.get("symbol"), "rank_a": ra and ra[0], "rank_b": rb and rb[0],
                "score_a": ra and ra[1], "score_b": rb and rb[1],
                "hint": _hint(hit, other, exists(repo, line_a["commit"], hit)),
            })
    return rows


def compare(run_a: str | Path, run_b: str | Path, *, tasks_file: str | Path | None = None,
            exists: Callable[[str, str, dict], bool] = in_code) -> CompareResult:
    path_a, path_b = resolve_run(run_a), resolve_run(run_b)
    a, b = _load(path_a), _load(path_b)
    meta_a, meta_b = a["meta"], b["meta"]
    if meta_a.get("tasks_sha256") != meta_b.get("tasks_sha256"):
        raise CompareError("the two runs used different task files")
    names_a, names_b = [s["name"] for s in meta_a["systems"]], [s["name"] for s in meta_b["systems"]]
    if names_a != names_b:
        raise CompareError(f"the two runs have different systems: {names_a} vs. {names_b}")
    tasks_path = Path(tasks_file) if tasks_file is not None else Path(meta_a["tasks_file"])
    if not tasks_path.is_file():
        raise CompareError(f"tasks file {tasks_path} is missing (use --tasks FILE)")
    repo_of = {t.id: t.repo for t in load_tasks(tasks_path)}

    results = []
    for name in names_a:
        lines_a, lines_b = a["lines"][name], b["lines"][name]
        scored_a = {r["task_id"] for r in a["scores"] if r["system"] == name}
        scored_b = {r["task_id"] for r in b["scores"] if r["system"] == name}
        shared = sorted(set(lines_a) & set(lines_b) & scored_a & scored_b)
        result = SystemResult(system=name, tasks=len(shared))
        for task_id in shared:
            line_a, line_b = lines_a[task_id], lines_b[task_id]
            if line_a["commit"] != line_b["commit"]:
                raise CompareError(f"{name}: task {task_id} ran at different commits")
            if {_location(h) for h in line_a["hits"][:TOP]} == {_location(h) for h in line_b["hits"][:TOP]}:
                result.same_top += 1
            else:
                result.differences.append({"task_id": task_id, "commit": line_a["commit"],
                                           "hits": _top_difference(line_a, line_b, repo_of[task_id], exists)})
        means_a, means_b = _means(a["scores"], name, set(shared)), _means(b["scores"], name, set(shared))
        for key in sorted(set(means_a) | set(means_b), key=str):
            va, vb = means_a.get(key), means_b.get(key)
            level, iou, metric = key
            row = {"level": level, "iou": iou, "metric": metric, "a": va, "b": vb}
            if va is None or vb is None:
                if va != vb:  # found in one run and never in the other
                    result.metric_diffs.append({**row, "diff": None, "limit": None})
                continue
            if metric in COUNT_METRICS:
                diff = abs(va - vb) / max(abs(va), abs(vb), 1e-12)
                result.largest_relative_diff = max(result.largest_relative_diff, diff)
                if diff >= MAX_RELATIVE_DIFF:
                    result.metric_diffs.append({**row, "diff": diff, "limit": "1% (relative)"})
            else:
                diff = abs(va - vb)
                result.largest_diff = max(result.largest_diff, diff)
                if diff >= MAX_DIFF:
                    result.metric_diffs.append({**row, "diff": diff, "limit": str(MAX_DIFF)})
        results.append(result)

    report_path = path_a / f"compare-{path_b.name}.md"
    out = CompareResult(path_a, path_b, results, report_path)
    write_text_atomic(report_path, render(out, meta_a, meta_b))
    return out


def _num(value, digits: int = 4) -> str:
    return "-" if value is None else f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def render(result: CompareResult, meta_a: dict, meta_b: dict) -> str:
    a, b = result.run_a.name, result.run_b.name
    lines = [
        "# Update vs. rebuild check (F3 B4, Decision 5)", "",
        f"- A: `{a}` (index mode {meta_a.get('index_mode')})",
        f"- B: `{b}` (index mode {meta_b.get('index_mode')})",
        f"- Rules: for each system, at least {MIN_SAME_TOP:.0%} of tasks have the same set of top-{TOP} hits "
        f"(by location); every metric's mean differs by less than {MAX_DIFF}; token counts by less than "
        f"{MAX_RELATIVE_DIFF:.0%}.", "",
        f"## Result: {'PASS' if result.passed else 'FAIL (read the differences below)'}", "",
        "| system | tasks | same top 10 | largest metric difference | largest token difference | result |",
        "|---|---|---|---|---|---|",
    ]
    for s in result.systems:
        lines.append(f"| {s.system} | {s.tasks} | {s.same_top} ({s.share_same_top:.0%}) | {s.largest_diff:.4f} "
                     f"| {s.largest_relative_diff:.2%} | {'pass' if s.passed else 'FAIL'} |")
    over = [(s.system, d) for s in result.systems for d in s.metric_diffs]
    if over:
        lines += ["", "## Metric means over the limit", "",
                  "| system | level | IoU | metric | A | B | difference | limit |", "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {name} | {d['level']} | {_num(d['iou'], 1)} | {d['metric']} | {_num(d['a'])} | {_num(d['b'])} "
                  f"| {_num(d['diff'])} | {d['limit'] or 'found in one run only'} |" for name, d in over]
    differing = [(s.system, d) for s in result.systems for d in s.differences]
    if differing:
        lines += ["", f"## Tasks with a different top {TOP}", "",
                  "Hints: **near tie** = just outside the other top 10, with a score within 1% of rank 10 there "
                  "(GPU rounding can do this); **stale** = not in the code at this commit (an update bug); "
                  "**check** = look at it by hand."]
        for name, d in differing:
            lines += ["", f"### {name}: {d['task_id']} (commit {d['commit'][:12]})", "",
                      "| only in | hit | symbol | rank A | rank B | score A | score B | hint |", "|---|---|---|---|---|---|---|---|"]
            for h in d["hits"]:
                where = h["path"] if h["start_line"] is None else f"{h['path']}:{h['start_line']}-{h['end_line']}"
                lines.append(f"| {h['only_in'].upper()} | `{where}` | {h['symbol'] or '-'} | {_num(h['rank_a'])} "
                             f"| {_num(h['rank_b'])} | {_num(h['score_a'], 5)} | {_num(h['score_b'], 5)} | {h['hint']} |")
    return "\n".join(lines) + "\n"
