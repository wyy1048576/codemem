"""`cmeval e2e score`: tables of an end-to-end run, from its run.json files.

For each setup, two tables. Outcome: runs, discarded runs, the share of completed runs, processed tokens, the
agent's seconds, turns, and how the runs ended. Behaviour (from `steps`): content searches, file searches,
files viewed, the share of runs that opened a gold file, the turn of the first gold open, the turns before the
first edit, and, for a setup with codemem or when a run called codemem: the share of runs that called it, its
mean calls, and the mean turn of the first call.

Discarded runs count only in "runs", "discarded" and the ends. Flagged runs (for example a cross-check that
disagrees) are counted, and are kept out of every number until someone has looked at them: their measurement
is in doubt.

With two or more setups, each setup is compared with the baseline (grep when it exists) on the tasks that both
have: the mean over repetitions for each task and setup, then the mean of the differences (setup - baseline).
No intervals yet.

With screen files (e2e_screen.py), the completion numbers count only the tasks that the screen calls fair: a
task with unfair hidden tests, or one that is not decided, leaves them. Tokens, time, turns and behaviour keep
every task. A conservative variant, as a sensitivity number, also leaves out every fair task that had an
"unfair" read.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from .files import write_json
from .paths import e2e_dir

if TYPE_CHECKING:
    from .e2e_screen import CompletionSet

MEASURES = (("completed", "completed"), ("processed_tokens", "tokens"), ("agent_s", "seconds"))


def run_root(run_id: str) -> Path:
    return e2e_dir() / "runs" / run_id


def load_records(root: Path) -> list[dict]:
    """The run.json of each <task>/<setup>/<rep>/ folder. Folders set aside (<rep>.discarded-<n>) are left out."""
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.glob("*/*/*/run.json"))
            if p.parent.name.isdigit()]


def _value(record: dict, measure: str) -> float | None:
    if measure == "completed":
        return None if record.get("completed") is None else float(record["completed"])
    if measure == "processed_tokens":
        return record.get("tokens", {}).get("processed_tokens")
    return record.get("time", {}).get(measure)


def _mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def _steps(record: dict, *keys):
    """A value in the record's steps, or None. Older records do not have every field."""
    value = record.get("steps") or {}
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def behaviour(kept: list[dict]) -> dict:
    """The means of the search behaviour of some runs. A run without a field is left out of its mean."""
    viewed = [_steps(r, "views", "files_viewed") for r in kept]
    opened = [_steps(r, "gold_opened") if _steps(r, "gold_opened") is not None else _steps(r, "gold_file_read")
              for r in kept]
    codemem = [_steps(r, "codemem_calls") for r in kept]
    return {
        "content_searches_mean": _mean([_steps(r, "searches", "content") for r in kept]),
        "file_searches_mean": _mean([_steps(r, "searches", "files") for r in kept]),
        "files_viewed_mean": _mean([len(v) if isinstance(v, list) else None for v in viewed]),
        "gold_opened_share": _mean([None if v is None else float(v) for v in opened]),
        "first_gold_open_mean": _mean([_steps(r, "first_gold_opened_turn") for r in kept]),
        "turns_before_first_edit_mean": _mean([_steps(r, "turns_before_first_edit") for r in kept]),
        "codemem_calls_mean": _mean(codemem),
        "codemem_share": _mean([None if c is None else float(c > 0) for c in codemem]),
        "first_codemem_turn_mean": _mean([_steps(r, "first_codemem_turn") for r in kept]),
    }


def _median(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def score(run_id: str, screen: CompletionSet | None = None) -> dict:
    """The tables of one run. Also written to score.json in the run folder. With `screen`, completion counts only
    the runs of fair tasks."""
    root = run_root(run_id)
    if not root.is_dir():
        raise FileNotFoundError(f"no run folder {root}")
    records = load_records(root)
    fair = screen.fair if screen is not None else None
    strict = screen.fair_strict if screen is not None else None
    setups: dict[str, dict] = {}
    for name in sorted({r["setup"] for r in records}):
        rows = [r for r in records if r["setup"] == name]
        usable = [r for r in rows if not r.get("discard")]
        kept = [r for r in usable if not r.get("flags")]
        tokens = [_value(r, "processed_tokens") for r in kept]
        seconds = [_value(r, "agent_s") for r in kept]
        setups[name] = {
            "runs": len(rows),
            "discarded": len(rows) - len(usable),
            "flagged": len(usable) - len(kept),
            "completed_share": _mean([_value(r, "completed") for r in kept if fair is None or r["task_id"] in fair]),
            "tokens_mean": _mean(tokens), "tokens_median": _median(tokens),
            "seconds_mean": _mean(seconds), "seconds_median": _median(seconds),
            "turns_mean": _mean([r.get("steps", {}).get("turns") for r in kept]),
            "ends": dict(Counter(r["end"] for r in rows)),
            "behaviour": behaviour(kept),
            "codemem": any((r.get("identity") or {}).get("codemem") for r in rows),
        }
        if fair is not None:
            setups[name]["completion_runs"] = sum(1 for r in kept if r["task_id"] in fair)
            setups[name]["completed_share_strict"] = _mean([_value(r, "completed") for r in kept
                                                           if r["task_id"] in strict])
    baseline = "grep" if "grep" in setups else next(iter(setups), None)
    paired = [paired_difference(records, name, baseline, fair) for name in setups if name != baseline]
    summary = {"run_id": run_id, "records": len(records), "baseline": baseline, "setups": setups, "paired": paired}
    if screen is not None:
        task_ids = sorted({r["task_id"] for r in records})
        left = {t: screen.status_of(t) for t in task_ids if t not in fair}
        summary["screen"] = {"files": screen.files, "tasks": len(task_ids), "fair": len(task_ids) - len(left),
                             "fair_strict": sum(1 for t in task_ids if t in strict), "left_out": left}
    write_json(root / "score.json", summary)
    return summary


def paired_difference(records: list[dict], setup: str, baseline: str, fair: set[str] | None = None) -> dict:
    """Mean over tasks of (task mean in `setup` - task mean in `baseline`), for each measure. With `fair`,
    completion is over the fair tasks only."""
    by_task: dict[str, dict[str, list[dict]]] = {}
    for r in records:
        if not r.get("discard") and not r.get("flags") and r["setup"] in (setup, baseline):
            by_task.setdefault(r["task_id"], {}).setdefault(r["setup"], []).append(r)
    result: dict = {"setup": setup, "baseline": baseline}
    both = [runs for runs in by_task.values() if setup in runs and baseline in runs]
    result["tasks"] = len(both)
    if fair is not None:
        result["completed_tasks"] = sum(1 for task, runs in by_task.items()
                                        if task in fair and setup in runs and baseline in runs)
    for measure, label in MEASURES:
        diffs = []
        for task, runs in by_task.items():
            if setup not in runs or baseline not in runs:
                continue
            if measure == "completed" and fair is not None and task not in fair:
                continue
            a = _mean([_value(r, measure) for r in runs[setup]])
            b = _mean([_value(r, measure) for r in runs[baseline]])
            if a is not None and b is not None:
                diffs.append(a - b)
        result[label] = _mean(diffs)
    return result


def _fmt(value, digits: int = 1) -> str:
    return "-" if value is None else f"{value:,.{digits}f}"


def format_score(summary: dict) -> str:
    lines = [f"run {summary['run_id']}: {summary['records']} runs"]
    screen = summary.get("screen")
    if screen:
        why = Counter(screen["left_out"].values())
        text = f"  screen {', '.join(screen['files'])}: completion counts {screen['fair']} of {screen['tasks']} tasks"
        if why:
            text += f"; {len(screen['left_out'])} left out (" + ", ".join(f"{s} {n}" for s, n in sorted(why.items())) + ")"
        lines.append(text + "; tokens, time and behaviour count every task")
        lines.append(f"  conservative (no unfair read at all): completion over {screen['fair_strict']} tasks: "
                     + ", ".join(f"{name} {_fmt(s.get('completed_share_strict'), 2)}"
                                 for name, s in summary["setups"].items()))
    lines.append(f"  {'setup':12} {'runs':>5} {'disc.':>5} {'flag.':>5} {'completed':>9} {'tokens mean':>12} "
                 f"{'tokens med.':>12} {'s mean':>8} {'s med.':>8} {'turns':>6}")
    for name, s in summary["setups"].items():
        lines.append(f"  {name:12} {s['runs']:>5} {s['discarded']:>5} {s['flagged']:>5} "
                     f"{_fmt(s['completed_share'], 2):>9} {_fmt(s['tokens_mean'], 0):>12} "
                     f"{_fmt(s['tokens_median'], 0):>12} {_fmt(s['seconds_mean']):>8} {_fmt(s['seconds_median']):>8} "
                     f"{_fmt(s['turns_mean']):>6}")
        lines.append("    ends: " + ", ".join(f"{end} {n}" for end, n in sorted(s["ends"].items())))
    for p in summary["paired"]:
        over = f" (over {p['completed_tasks']} fair tasks)" if "completed_tasks" in p else ""
        lines.append(f"  {p['setup']} - {p['baseline']} over {p['tasks']} tasks: completed {_fmt(p['completed'], 2)}{over}, "
                     f"tokens {_fmt(p['tokens'], 0)}, seconds {_fmt(p['seconds'])}")
    codemem = any(s.get("codemem") or (s["behaviour"]["codemem_calls_mean"] or 0) > 0
                  for s in summary["setups"].values())
    lines.append("  behaviour (means over kept runs):")
    lines.append(f"  {'setup':12} {'content s.':>10} {'file s.':>8} {'viewed':>7} {'gold open':>9} {'open turn':>9} "
                 f"{'pre-edit':>8}" + (f" {'used':>5} {'codemem':>8} {'1st call':>8}" if codemem else ""))
    for name, s in summary["setups"].items():
        b = s["behaviour"]
        lines.append(f"  {name:12} {_fmt(b['content_searches_mean']):>10} {_fmt(b['file_searches_mean']):>8} "
                     f"{_fmt(b['files_viewed_mean']):>7} {_fmt(b['gold_opened_share'], 2):>9} "
                     f"{_fmt(b['first_gold_open_mean']):>9} {_fmt(b['turns_before_first_edit_mean']):>8}"
                     + (f" {_fmt(b['codemem_share'], 2):>5} {_fmt(b['codemem_calls_mean']):>8} "
                        f"{_fmt(b.get('first_codemem_turn_mean')):>8}" if codemem else ""))
    return "\n".join(lines)
