"""`cmeval e2e score`: tables of an end-to-end run, from its run.json files.

For each setup, two tables. Outcome: runs, discarded runs, flagged runs, the runs that ended at a limit, the
share of completed runs, processed tokens, the agent's seconds, turns, the mean cost from the price table
(prices.py), the mean cost that Claude Code reported (result_event.total_cost_usd), and how the runs ended.
Behaviour (from `steps`): content searches, file searches, files viewed, the share of runs that opened a gold
file, the turn of the first gold open, the turns before the first edit, and, for a setup with codemem or when a
run called codemem: the share of runs that had the block, the share of runs in which the agent called codemem
itself ("used"), the mean of these calls, and the mean turn of the first of them.

A run that ended at the turn limit or the time limit counts as not completed, in every setup, also when its patch
passes the tests (rule of the project lead, 2026-11-28). It stays in tokens, seconds, turns and behaviour. The
record shows it in `end` ("turn limit" or "time limit", from e2e_run.classify_end), in `turn_limit` (the turn at
which the runner stopped the agent) or in integrity.host_timeout (the host stopped the container after the time
limit and its extra time). "at limit" counts these runs among the runs that were not discarded.

The cost of a run is the sum of the prices of its model requests in proxy.jsonl (prices.log_cost). A run without
proxy.jsonl, or with a request that the table cannot price, has no cost. The reported cost is beside it as a
check.

In a setup with a block (e2e_block.py), the pipeline makes one codemem search for the agent before it starts.
steps.codemem_calls counts that search, and steps.first_codemem_turn is 0. The behaviour table leaves it out: the
calls are codemem_calls less identity.block.searches_made_for_agent, and the first turn is the first codemem call
of the main agent. When the record cannot give that turn (the agent called an MCP tool that is not codemem's), it
comes from stream.jsonl of the run folder, and is not known without that file. codemem_share,
codemem_calls_mean and first_codemem_turn_mean count only the agent's own calls (before 2026-11-28 they also
counted the block). codemem_search_share is the share of runs in which the agent called search_code itself.
block_share is the share of runs whose first message began with the block (integrity.block_in_first_message).

A run of a setup with a block (identity.block) whose first message did not begin with the block
(integrity.block_in_first_message false) is treated as discarded, with the reason "no block". run.json does not
change. A record made before these fields existed is not affected.

For a setup with codemem, one more line: the search_code results that carried one of codemem's notes (a search
that fell back, for example to keywords while the model was loading: integrity.codemem_fallback_searches), over
the runs that were not discarded, and the runs whose first search came from keywords only, kept and discarded.
A record made before the count existed gets it from `cmeval e2e recount`.

Discarded runs (also the runs without their block) count only in "runs", "discarded" and the ends. Flagged runs
(for example a cross-check that disagrees) are counted, and are kept out of every number until someone has looked
at them: their measurement is in doubt.

With two or more setups, each setup is compared with the baseline (grep when it exists) on the tasks that both
have: the mean over repetitions for each task and setup, then the mean of the differences (setup - baseline),
for completion, tokens, seconds and the cost from the table. No intervals yet.

Keys of a setup in the summary that came with these rules: at_limit, no_block, cost_mean, reported_cost_mean, and
in behaviour codemem_search_share and block_share. A paired difference has the key cost.

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

from .e2e_steps import CODEMEM_PREFIX, CODEMEM_SEARCH, MCP_PREFIX, TurnCounter, parse_stream
from .files import write_json
from .paths import e2e_dir
from .prices import log_cost

if TYPE_CHECKING:
    from .e2e_screen import CompletionSet

MEASURES = (("completed", "completed"), ("processed_tokens", "tokens"), ("agent_s", "seconds"), ("cost_usd", "cost"))
LIMIT_ENDS = ("turn limit", "time limit")
NO_BLOCK = "no block"


def run_root(run_id: str) -> Path:
    return e2e_dir() / "runs" / run_id


def load_runs(root: Path) -> list[tuple[Path, dict]]:
    """The folder and the run.json of each <task>/<setup>/<rep>/ folder. Folders set aside (<rep>.discarded-<n>)
    are left out."""
    return [(p.parent, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(root.glob("*/*/*/run.json"))
            if p.parent.name.isdigit()]


def load_records(root: Path) -> list[dict]:
    """The run.json of each <task>/<setup>/<rep>/ folder. Folders set aside (<rep>.discarded-<n>) are left out."""
    return [record for _, record in load_runs(root)]


def at_limit(record: dict) -> bool:
    """The run ended at the turn limit or the time limit: by its end, by the runner's turn_limit, or by the host's
    timeout."""
    return (record.get("end") in LIMIT_ENDS or bool(record.get("turn_limit"))
            or bool((record.get("integrity") or {}).get("host_timeout")))


def block_searches(record: dict) -> int:
    """The codemem searches that the pipeline made for the agent (the block). 0 for a setup without a block."""
    block = (record.get("identity") or {}).get("block")
    if not block:
        return 0
    made = block.get("searches_made_for_agent") if isinstance(block, dict) else None
    return made if isinstance(made, int) else 1


def discard_reason(record: dict) -> str | None:
    """Why the score leaves the run out, or None when it counts. A run that the runner discarded keeps its reason.
    A run of a setup with a block whose first message did not begin with the block gets NO_BLOCK."""
    if record.get("discard"):
        return record.get("discard_reason") or "discarded"
    if block_searches(record) and (record.get("integrity") or {}).get("block_in_first_message") is False:
        return NO_BLOCK
    return None


def own_codemem_calls(record: dict) -> int | None:
    """The codemem calls that the main agent made itself: steps.codemem_calls less the block's search."""
    calls = _steps(record, "codemem_calls")
    return None if calls is None else max(calls - block_searches(record), 0)


def first_codemem_turn_in_stream(events: list[dict]) -> int | None:
    """The turn of the main agent's first codemem call in the stream, or None. Turns as in e2e_steps."""
    counter = TurnCounter()
    for event in events:
        counter.feed(event)
        if event.get("type") != "assistant" or event.get("parent_tool_use_id"):
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and \
                    str(block.get("name", "")).startswith(CODEMEM_PREFIX):
                return counter.turns
    return None


def own_first_codemem_turn(record: dict, folder: Path | None = None) -> int | None:
    """The turn of the main agent's first own codemem call, or None. Without a block it is
    steps.first_codemem_turn. With a block, steps.first_mcp_turn when every MCP tool that the agent called is
    codemem's, else the turn from stream.jsonl in `folder`. None when neither can say."""
    if not block_searches(record):
        return _steps(record, "first_codemem_turn")
    tools = _steps(record, "tool_calls")
    if isinstance(tools, dict):
        mcp = [t for t in tools if t.startswith(MCP_PREFIX)]
        if not any(t.startswith(CODEMEM_PREFIX) for t in mcp):
            return None
        if all(t.startswith(CODEMEM_PREFIX) for t in mcp):
            return _steps(record, "first_mcp_turn")
    stream = folder / "stream.jsonl" if folder is not None else None
    if stream is None or not stream.exists():
        return None
    return first_codemem_turn_in_stream(parse_stream(stream)["events"])


def derive(record: dict, folder: Path | None) -> dict:
    """A copy of the record with the values that come from its folder, under "_derived": the cost from the price
    table and the turn of the agent's first own codemem call. The copy is only in memory."""
    cost = log_cost(folder / "proxy.jsonl") if folder is not None else None
    return {**record, "_derived": {"cost_usd": cost["usd"] if cost else None,
                                   "first_own_codemem_turn": own_first_codemem_turn(record, folder)}}


def _derived(record: dict, key: str):
    derived = record.get("_derived")
    if isinstance(derived, dict) and key in derived:
        return derived[key]
    return own_first_codemem_turn(record) if key == "first_own_codemem_turn" else None


def _value(record: dict, measure: str) -> float | None:
    if measure == "completed":
        if at_limit(record):
            return 0.0
        return None if record.get("completed") is None else float(record["completed"])
    if measure == "processed_tokens":
        return record.get("tokens", {}).get("processed_tokens")
    if measure == "cost_usd":
        return _derived(record, "cost_usd")
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
    """The means of the search behaviour of some runs. A run without a field is left out of its mean. The codemem
    numbers count only the calls that the agent made itself, not the block's search."""
    viewed = [_steps(r, "views", "files_viewed") for r in kept]
    opened = [_steps(r, "gold_opened") if _steps(r, "gold_opened") is not None else _steps(r, "gold_file_read")
              for r in kept]
    codemem = [own_codemem_calls(r) for r in kept]
    searches = [None if not isinstance(_steps(r, "mcp_tools"), dict) else _steps(r, "mcp_tools").get(CODEMEM_SEARCH, 0)
                for r in kept]
    return {
        "content_searches_mean": _mean([_steps(r, "searches", "content") for r in kept]),
        "file_searches_mean": _mean([_steps(r, "searches", "files") for r in kept]),
        "files_viewed_mean": _mean([len(v) if isinstance(v, list) else None for v in viewed]),
        "gold_opened_share": _mean([None if v is None else float(v) for v in opened]),
        "first_gold_open_mean": _mean([_steps(r, "first_gold_opened_turn") for r in kept]),
        "turns_before_first_edit_mean": _mean([_steps(r, "turns_before_first_edit") for r in kept]),
        "codemem_calls_mean": _mean(codemem),
        "codemem_share": _mean([None if c is None else float(c > 0) for c in codemem]),
        "first_codemem_turn_mean": _mean([_derived(r, "first_own_codemem_turn") for r in kept]),
        "codemem_search_share": _mean([None if c is None else float(c > 0) for c in searches]),
        "block_share": _mean([float((r.get("integrity") or {}).get("block_in_first_message") is True) for r in kept]),
    }


def fallbacks(rows: list[dict]) -> dict | None:
    """The fallback searches of codemem in some runs of one setup, or None when no run has the count."""
    def count(r):
        value = (r.get("integrity") or {}).get("codemem_fallback_searches")
        return value if isinstance(value, dict) else None

    if not any(count(r) for r in rows):
        return None
    usable = [r for r in rows if discard_reason(r) is None]
    counted = [count(r) for r in usable if count(r)]
    notes = Counter()
    for c in counted:
        notes.update(c.get("by_note") or {})
    return {
        "runs": len(counted),
        "runs_without_count": sum(1 for r in usable if count(r) is None and (r.get("identity") or {}).get("codemem")),
        "searches": sum(c["searches"] for c in counted),
        "fell_back": sum(c["fell_back"] for c in counted),
        "keywords_only": sum(c["keywords_only"] for c in counted),
        "by_note": dict(sorted(notes.items())),
        "runs_with_fallback": sum(1 for c in counted if c["fell_back"]),
        "first_keywords_only_runs": sum(1 for c in counted if c.get("first_keywords_only")),
        "first_keywords_only_discarded": sum(1 for r in rows if discard_reason(r) and (count(r) or {}).get(
            "first_keywords_only")),
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
    records = [derive(record, folder) for folder, record in load_runs(root)]
    fair = screen.fair if screen is not None else None
    strict = screen.fair_strict if screen is not None else None
    setups: dict[str, dict] = {}
    for name in sorted({r["setup"] for r in records}):
        rows = [r for r in records if r["setup"] == name]
        usable = [r for r in rows if discard_reason(r) is None]
        kept = [r for r in usable if not r.get("flags")]
        tokens = [_value(r, "processed_tokens") for r in kept]
        seconds = [_value(r, "agent_s") for r in kept]
        setups[name] = {
            "runs": len(rows),
            "discarded": len(rows) - len(usable),
            "no_block": sum(1 for r in rows if discard_reason(r) == NO_BLOCK),
            "flagged": len(usable) - len(kept),
            "at_limit": sum(1 for r in usable if at_limit(r)),
            "completed_share": _mean([_value(r, "completed") for r in kept if fair is None or r["task_id"] in fair]),
            "tokens_mean": _mean(tokens), "tokens_median": _median(tokens),
            "seconds_mean": _mean(seconds), "seconds_median": _median(seconds),
            "turns_mean": _mean([r.get("steps", {}).get("turns") for r in kept]),
            "cost_mean": _mean([_value(r, "cost_usd") for r in kept]),
            "reported_cost_mean": _mean([(r.get("result_event") or {}).get("total_cost_usd") for r in kept]),
            "ends": dict(Counter(r["end"] for r in rows)),
            "behaviour": behaviour(kept),
            "codemem": any((r.get("identity") or {}).get("codemem") for r in rows),
            "codemem_fallbacks": fallbacks(rows),
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
    completion is over the fair tasks only. A run at a limit counts as not completed."""
    by_task: dict[str, dict[str, list[dict]]] = {}
    for r in records:
        if discard_reason(r) is None and not r.get("flags") and r["setup"] in (setup, baseline):
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
    lines.append(f"  {'setup':12} {'runs':>5} {'disc.':>5} {'flag.':>5} {'at limit':>8} {'completed':>9} "
                 f"{'tokens mean':>12} {'tokens med.':>12} {'s mean':>8} {'s med.':>8} {'turns':>6} {'cost $':>8} "
                 f"{'rep. $':>8}")
    for name, s in summary["setups"].items():
        lines.append(f"  {name:12} {s['runs']:>5} {s['discarded']:>5} {s['flagged']:>5} {s.get('at_limit', 0):>8} "
                     f"{_fmt(s['completed_share'], 2):>9} {_fmt(s['tokens_mean'], 0):>12} "
                     f"{_fmt(s['tokens_median'], 0):>12} {_fmt(s['seconds_mean']):>8} {_fmt(s['seconds_median']):>8} "
                     f"{_fmt(s['turns_mean']):>6} {_fmt(s.get('cost_mean'), 4):>8} "
                     f"{_fmt(s.get('reported_cost_mean'), 4):>8}")
        ends = "    ends: " + ", ".join(f"{end} {n}" for end, n in sorted(s["ends"].items()))
        if s.get("no_block"):
            ends += f"; {s['no_block']} discarded without their block"
        lines.append(ends)
        if f := s.get("codemem_fallbacks"):
            notes = ", ".join(f"{k} {n}" for k, n in f["by_note"].items()) or "none"
            text = (f"    codemem fallbacks: {f['fell_back']} of {f['searches']} searches had a note ({notes}) in "
                    f"{f['runs_with_fallback']} of {f['runs']} runs; first search from keywords only: "
                    f"{f['first_keywords_only_runs']} runs, and {f['first_keywords_only_discarded']} discarded runs")
            if f["runs_without_count"]:
                text += f"; {f['runs_without_count']} runs without the count (run cmeval e2e recount)"
            lines.append(text)
    for p in summary["paired"]:
        over = f" (over {p['completed_tasks']} fair tasks)" if "completed_tasks" in p else ""
        lines.append(f"  {p['setup']} - {p['baseline']} over {p['tasks']} tasks: completed {_fmt(p['completed'], 2)}{over}, "
                     f"tokens {_fmt(p['tokens'], 0)}, seconds {_fmt(p['seconds'])}, cost {_fmt(p.get('cost'), 4)}")
    codemem = any(s.get("codemem") or (s["behaviour"]["codemem_calls_mean"] or 0) > 0
                  for s in summary["setups"].values())
    lines.append("  behaviour (means over kept runs):")
    lines.append(f"  {'setup':12} {'content s.':>10} {'file s.':>8} {'viewed':>7} {'gold open':>9} {'open turn':>9} "
                 f"{'pre-edit':>8}" + (f" {'block':>5} {'used':>5} {'codemem':>8} {'1st call':>8}" if codemem else ""))
    for name, s in summary["setups"].items():
        b = s["behaviour"]
        lines.append(f"  {name:12} {_fmt(b['content_searches_mean']):>10} {_fmt(b['file_searches_mean']):>8} "
                     f"{_fmt(b['files_viewed_mean']):>7} {_fmt(b['gold_opened_share'], 2):>9} "
                     f"{_fmt(b['first_gold_open_mean']):>9} {_fmt(b['turns_before_first_edit_mean']):>8}"
                     + (f" {_fmt(b.get('block_share'), 2):>5} {_fmt(b['codemem_share'], 2):>5} "
                        f"{_fmt(b['codemem_calls_mean']):>8} "
                        f"{_fmt(b.get('first_codemem_turn_mean')):>8}" if codemem else ""))
    return "\n".join(lines)
