"""The replay: ask the first codemem search of each run again at several numbers of results, and read from the
records what that search cost in the run.

Tracks B and C set the number of results that codemem's search_code returns. This module gives them two
measurements from the runs of track A. It starts no agent.

Part 1, the replay. For each run of a codemem setup:

  1. find the first search_code call of the main agent in stream.jsonl: the query and every other argument
  2. start the codemem program as an MCP server on the task's base commit (the src/ worktree that `cmeval e2e
     index` made) with a private copy of the task's index, as a run starts it (see replay_task)
  3. wait until the index is ready and the embedding model is loaded
  4. call search_code with the same arguments at each number of results k. Only k changes
  5. read the result list from the text and match it to the task's gold files and functions

The replay calls the MCP tool itself, so the ranking is codemem's own. The tool takes k from its caller.

The check. The replay also asks the search at the k of the run, and compares the result list with the list
that the agent got. In many runs the first search came while the embedding model was still loading; codemem
then answers from keywords only and says so in a note. For such a run the check asks the command line
`codemem search --signals bm25` instead, which calls the same search function with keywords only.

Part 2, from the records only: the characters of the first search_code result as the model got it, the
turns of the main agent after it, and for each later model request the share of its input tokens that were
cache reads (proxy.jsonl). The tokens of the result are an estimate: the growth of the input from the request
that made the call to the next request, less the output of the first. When that turn made more than one tool
call (in the pilot runs the agent always sent a Bash call with its first search), the growth is split over the
results by their characters.

Gold matching (the rules of metrics/matching.py):
  gold file      a result's path is a gold file
  every gold     each gold file is the path of a result
  gold function  a result lies inside a gold function, or overlaps it with line IoU >= the threshold. Null when
                 the task has no function gold or partial labels
  first rank     the rank of the first result whose path is a gold file
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter

from .e2e_steps import TurnCounter, result_text
from .metrics.matching import excluded, hit_matches
from .retriever import Hit
from .tasks import Task

SCHEMA = 1
SEARCH_TOOL = "mcp__codemem__search_code"
DEFAULT_KS = (5, 10, 20, 30, 50)
TOOL_DEFAULT_K = 10  # the default of search_code when the agent gives no k
MAX_K = 50  # search_code takes k from 1 to 50
DEFAULT_IOU = 0.5
MESSAGES_PATH = "/v1/messages"
# Texts of codemem's notes (prompts.py and render.py of codemem). A note says that the result is not the full search.
KEYWORDS_ONLY_MARK = "the embedding model is still loading"
INDEXING_MARK = "the codemem index is still being built"
NOT_FRESH_MARK = "Search again in a few seconds, or use grep for those files."
# One result: "3. path/to/file.py:120-137  Class.method  [id 4711]", and "  best 125-130" for a long chunk.
_HEAD = re.compile(r"^(\d+)\. (.+?):(\d+)-(\d+)  (.*?)  \[id (\d+)\](?:  best (\d+)-(\d+))?[ \t]*$", re.MULTILINE)
LEVELS = ("L0", "L1", "L2")
RANK_BUCKETS = ((1, 1), (2, 5), (6, 10), (11, 20), (21, 30), (31, 50))


# ---- the first search of a run

def first_search(events: list[dict]) -> dict | None:
    """The first search_code call of the main agent, or None. Returns the call id, the id of the model message
    that made it, its turn (1-based, as e2e_steps counts turns), its arguments, the number of tool calls in that
    message and the characters of all their results, the result text as the model got it (None when the stream
    has no result), and is_error. A tool result comes after its call in the stream."""
    counter = TurnCounter()
    found = None
    for event in events:
        counter.feed(event)
        if found or event.get("type") != "assistant" or event.get("parent_tool_use_id"):
            continue
        message = event.get("message") or {}
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == SEARCH_TOOL:
                args = block.get("input") if isinstance(block.get("input"), dict) else {}
                found = {"call_id": block.get("id"), "message_id": message.get("id"), "turn": counter.turns,
                         "args": dict(args), "tool_calls_in_turn": 0, "turn_result_chars": 0, "result": None,
                         "is_error": None}
                break
    if found is None:
        return None
    calls = {found["call_id"]}
    for event in events:
        message = event.get("message") or {}
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if (event.get("type") == "assistant" and block.get("type") == "tool_use" and found["message_id"]
                    and message.get("id") == found["message_id"]):
                calls.add(block.get("id"))
            if event.get("type") == "user" and block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                text = result_text(block)
                found["turn_result_chars"] += len(text)
                if block.get("tool_use_id") == found["call_id"]:
                    found["result"], found["is_error"] = text, bool(block.get("is_error"))
    found["tool_calls_in_turn"] = len(calls)
    return found


def run_k(args: dict) -> int:
    """The number of results that the agent's call asked for, as search_code reads it."""
    try:
        k = int(args.get("k", TOOL_DEFAULT_K))
    except (TypeError, ValueError):
        k = TOOL_DEFAULT_K
    return max(1, min(k, MAX_K))


# ---- the text of a search_code result

def unwrap(text: str) -> str:
    """The rendered text of a result. The MCP server of codemem 041124e answered {"result": "<text>"}, and
    Claude Code gave the model that JSON. A plain text stays as it is."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return text
    if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], str):
        return data["result"]
    return text


def parse_results(text: str) -> list[dict]:
    """The result list of a rendered search_code text: rank, path, start and end line, name, chunk id."""
    return [{"rank": int(m[1]), "path": m[2], "start": int(m[3]), "end": int(m[4]), "name": m[5],
             "chunk_id": int(m[6])} for m in _HEAD.finditer(text)]


def notes_of(text: str) -> dict:
    """Which of codemem's notes a result has. keywords_only: the model was loading. indexing: the index was
    being built. not_fresh: some edits were not in the index yet."""
    return {"keywords_only": KEYWORDS_ONLY_MARK in text, "indexing": INDEXING_MARK in text,
            "not_fresh": NOT_FRESH_MARK in text}


def full_search(notes: dict) -> bool:
    return not any(notes.values())


# ---- gold

def gold_of(task: Task) -> dict:
    """The gold files and functions of a task, and why its function level is not scored (or None)."""
    reason = excluded(task, "line", "function")
    return {"files": list(task.gold.files), "functions": [] if reason else list(task.gold.functions),
            "function_excluded": reason}


def score_results(results: list[dict], gold: dict, iou: float = DEFAULT_IOU) -> dict:
    """Match a result list to the gold of a task."""
    files = set(gold["files"])
    paths = [r["path"] for r in results]
    first = next((r["rank"] for r in results if r["path"] in files), None)
    found_files = files & set(paths)
    found_functions = None
    if gold["function_excluded"] is None:
        hits = [Hit(path=r["path"], start_line=r["start"], end_line=r["end"]) for r in results]
        found_functions = sum(1 for span in gold["functions"] if any(hit_matches(h, span, iou) for h in hits))
    return {
        "gold_file_hit": first is not None,
        "all_gold_files_hit": bool(files) and found_files == files,
        "gold_files_found": len(found_files),
        "gold_function_hit": None if found_functions is None else found_functions > 0,
        "gold_functions_found": found_functions,
        "first_gold_rank": first,
    }


def compare_lists(a: list[dict], b: list[dict]) -> dict:
    """Whether two result lists are the same (path and lines, in order), and the share of shared results."""
    key = lambda r: (r["path"], r["start"], r["end"])  # noqa: E731
    ka, kb = [key(r) for r in a], [key(r) for r in b]
    shared = len(set(ka) & set(kb))
    return {"same": ka == kb, "shared": shared, "of": max(len(ka), len(kb))}


# ---- part 2: the cost of the first search in the run

def _input_tokens(usage: dict) -> int:
    return sum(usage.get(c) or 0 for c in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


def run_costs(events: list[dict], proxy_records: list[dict] | None, search: dict) -> dict:
    """What the first search cost in the run, from the stream and the proxy log (see the module text)."""
    counter = TurnCounter()
    order: list[str] = []
    for event in events:
        if counter.feed(event):
            order.append((event.get("message") or {}).get("id"))
    wire = search.get("result")
    out = {
        "result_chars": len(wire) if wire is not None else None,
        "result_text_chars": len(unwrap(wire)) if wire is not None else None,
        "search_turn": search["turn"],
        "turns": counter.turns,
        "turns_after": counter.turns - search["turn"],
        "result_tokens_estimate": None,
        "result_tokens_method": None,
        "later_requests": None,
        "cache_read_share_mean": None,
        "cache_read_share_pooled": None,
        "resent_tokens_estimate": None,
        "proxy_note": None,
    }
    if proxy_records is None:
        out["proxy_note"] = "no proxy log"
        return out
    main_ids = set(order)
    requests = sorted((r for r in proxy_records if r.get("path") == MESSAGES_PATH and r.get("status") == 200
                       and isinstance(r.get("usage"), dict) and r.get("message_id") in main_ids),
                      key=lambda r: r.get("seq", 0))
    at = next((i for i, r in enumerate(requests) if r.get("message_id") == search["message_id"]), None)
    if at is None:
        out["proxy_note"] = "the request of the search turn is not in the proxy log"
        return out
    this, later = requests[at]["usage"], [r["usage"] for r in requests[at + 1:]]
    shares = [u.get("cache_read_input_tokens", 0) / _input_tokens(u) for u in later if _input_tokens(u)]
    out["later_requests"] = len(later)
    if shares:
        out["cache_read_share_mean"] = round(statistics.fmean(shares), 4)
        out["cache_read_share_pooled"] = round(sum(u.get("cache_read_input_tokens", 0) for u in later)
                                               / sum(_input_tokens(u) for u in later), 4)
    if later and wire is not None:
        growth = _input_tokens(later[0]) - _input_tokens(this) - (this.get("output_tokens") or 0)
        share = len(wire) / search["turn_result_chars"] if search.get("turn_result_chars") else 1.0
        estimate = round(growth * share)
        out["result_tokens_estimate"] = estimate
        out["result_tokens_method"] = ("input growth" if search["tool_calls_in_turn"] == 1 else
                                       f"input growth of {search['tool_calls_in_turn']} tool results, split by "
                                       "their characters")
        out["resent_tokens_estimate"] = estimate * len(later)
    return out


# ---- the entry of one run

def run_entry(record: dict, events: list[dict], proxy_records: list[dict] | None, search: dict,
              task: Task | None, iou: float = DEFAULT_IOU) -> dict:
    """Everything about one run that the records give: who it is, the call, what the agent got, the cost."""
    identity = record.get("identity") or {}
    codemem = identity.get("codemem") or {}
    if task is not None:
        gold = gold_of(task)
    else:  # the files are in the record; the functions are only in the task file
        gold = {"files": list(identity.get("gold_files") or []), "functions": [],
                "function_excluded": "task not in the task files"}
    wire = search.get("result")
    text = unwrap(wire) if wire is not None else None
    results = parse_results(text) if text is not None else []
    notes = notes_of(text) if text is not None else None
    return {
        "run_id": record.get("run_id"),
        "task_id": record.get("task_id"),
        "repo": record.get("recipe") or record.get("repo"),
        "recipe": record.get("recipe"),
        "setup": record.get("setup"),
        "rep": record.get("rep"),
        "level": identity.get("prompt_level"),
        "completed": record.get("completed"),
        "steering": codemem.get("steering"),
        "run_codemem_commit": codemem.get("commit"),
        "run_index_codemem_commit": (codemem.get("index") or {}).get("codemem_commit"),
        "run_index_base_commit": (codemem.get("index") or {}).get("base_commit"),
        "base_commit": task.base_commit if task is not None else None,
        "gold": {"files": gold["files"],
                 "functions": [{"path": s.path, "start": s.start, "end": s.end, "symbol": s.symbol}
                               for s in gold["functions"]],
                 "function_excluded": gold["function_excluded"]},
        "call": {"args": search["args"], "k": run_k(search["args"]), "turn": search["turn"],
                 "tool_calls_in_turn": search["tool_calls_in_turn"], "is_error": search["is_error"]},
        "in_run": {"results": results, "notes": notes, "score": score_results(results, gold, iou)},
        "costs": run_costs(events, proxy_records, search),
        "replay": None,
        "check": None,
    }


# ---- tables

def _groups(entries: list[dict]) -> list[tuple[str, list[dict]]]:
    """All runs, then each repo, each level, and each repo and level."""
    repos = sorted({e["repo"] for e in entries if e["repo"]})
    levels = [lv for lv in LEVELS if any(e["level"] == lv for e in entries)]
    levels += sorted({e["level"] for e in entries if e["level"] and e["level"] not in LEVELS})
    out = [("all", entries)]
    out += [(repo, [e for e in entries if e["repo"] == repo]) for repo in repos]
    out += [(lv, [e for e in entries if e["level"] == lv]) for lv in levels]
    if len(repos) > 1 or len(levels) > 1:
        for repo in repos:
            for lv in levels:
                part = [e for e in entries if e["repo"] == repo and e["level"] == lv]
                if part:
                    out.append((f"{repo} {lv}", part))
    return out


def _count(values: list[bool | None]) -> str:
    known = [v for v in values if v is not None]
    if not known:
        return "-"
    hits = sum(1 for v in known if v)
    return f"{hits}/{len(known)} ({100 * hits / len(known):.0f}%)"


def _mean(values, digits: int = 0) -> str:
    known = [v for v in values if v is not None]
    if not known:
        return "-"
    value = statistics.fmean(known)
    return f"{value:,.{digits}f}"


def _at(entry: dict, k: int) -> dict | None:
    replay = entry.get("replay") or {}
    return (replay.get("by_k") or {}).get(str(k))


def _replay_table(title: str, entries: list[dict], ks: list[int], cell, in_run=None) -> list[str]:
    head = ["group", "runs"] + (["in the run"] if in_run else []) + [f"k={k}" for k in ks]
    lines = [f"**{title}**", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for name, part in _groups(entries):
        row = [name, str(len(part))]
        if in_run:
            row.append(in_run(part))
        row += [cell([_at(e, k) for e in part]) for k in ks]
        lines.append("| " + " | ".join(row) + " |")
    return lines + [""]


def _score_cell(field: str):
    return lambda cells: _count([(c["score"][field] if c and "score" in c else None) for c in cells])


def _rank_table(entries: list[dict], k: int) -> list[str]:
    head = ["group", "runs"] + [f"{lo}" if lo == hi else f"{lo}-{hi}" for lo, hi in RANK_BUCKETS] + ["not found"]
    lines = [f"**Rank of the first gold file at k={k}** (runs per rank range)", "",
             "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for name, part in _groups(entries):
        cells = [_at(e, k) for e in part]
        ranks = [c["score"]["first_gold_rank"] for c in cells if c and "score" in c]
        row = [name, str(len(ranks))]
        row += [str(sum(1 for r in ranks if r is not None and lo <= r <= hi)) for lo, hi in RANK_BUCKETS]
        row.append(str(sum(1 for r in ranks if r is None)))
        lines.append("| " + " | ".join(row) + " |")
    return lines + [""]


def replay_tables(entries: list[dict], ks: list[int]) -> str:
    """The tables of part 1, in Markdown. "in the run": what the agent got from its own first search."""
    done = [e for e in entries if e.get("replay") and not e["replay"].get("error")]
    if not done:
        return "No run was replayed.\n"
    run_cell = lambda field: lambda part: _count([e["in_run"]["score"][field] for e in part])  # noqa: E731
    lines = _replay_table("A gold file is among the results", done, ks, _score_cell("gold_file_hit"),
                          run_cell("gold_file_hit"))
    lines += _replay_table("Every gold file is among the results", done, ks, _score_cell("all_gold_files_hit"),
                           run_cell("all_gold_files_hit"))
    lines += _replay_table("A gold function is among the results (runs of tasks with function gold)", done, ks,
                           _score_cell("gold_function_hit"), run_cell("gold_function_hit"))
    lines += _replay_table("Mean characters of the rendered search_code output", done, ks,
                           lambda cells: _mean([c.get("text_chars") for c in cells if c]),
                           lambda part: _mean([e["costs"]["result_text_chars"] for e in part]))
    lines += _replay_table("Mean characters as the model gets them (the JSON form of codemem 041124e)", done, ks,
                           lambda cells: _mean([c.get("wire_chars") for c in cells if c]),
                           lambda part: _mean([e["costs"]["result_chars"] for e in part]))
    lines += _rank_table(done, max(ks))
    return "\n".join(lines)


def cost_table(entries: list[dict]) -> str:
    """The table of part 2, in Markdown."""
    head = ["group", "runs", "result chars (as the model got it)", "result chars (text)", "result tokens (est.)",
            "turns after", "later requests", "cache-read share of later input (mean)", "resent tokens (est.)"]
    lines = ["**The first search_code result in the run** (means over runs)", "",
             "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for name, part in _groups(entries):
        costs = [e["costs"] for e in part]
        share = _mean([c["cache_read_share_mean"] for c in costs], 3)
        lines.append("| " + " | ".join([
            name, str(len(part)), _mean([c["result_chars"] for c in costs]),
            _mean([c["result_text_chars"] for c in costs]), _mean([c["result_tokens_estimate"] for c in costs]),
            _mean([c["turns_after"] for c in costs], 1), _mean([c["later_requests"] for c in costs], 1), share,
            _mean([c["resent_tokens_estimate"] for c in costs])]) + " |")
    return "\n".join(lines) + "\n"


def check_summary(entries: list[dict], skipped: Counter) -> str:
    """The runs left out, the notes of the run's first search, and the result of the check."""
    lines = ["**Runs and checks**", ""]
    lines.append(f"- Runs with a first search_code call: {len(entries)}.")
    for reason, n in sorted(skipped.items()):
        lines.append(f"- Left out, {reason}: {n}.")
    notes = Counter()
    for e in entries:
        for name, on in (e["in_run"]["notes"] or {}).items():
            notes[name] += bool(on)
    lines.append(f"- First search in the run answered from keywords only (model loading): {notes['keywords_only']}; "
                 f"index being built: {notes['indexing']}; edits not yet indexed: {notes['not_fresh']}.")
    checks = Counter()
    for e in entries:
        check = e.get("check") or {}
        checks[check.get("verdict", "not checked")] += 1
    lines.append("- Check against the run's own result list: "
                 + ", ".join(f"{verdict} {n}" for verdict, n in sorted(checks.items())) + ".")
    errors = [e for e in entries if (e.get("replay") or {}).get("error")]
    if errors:
        lines.append(f"- Replay failed: {len(errors)} runs (see `replay.error` in the JSON file).")
    return "\n".join(lines) + "\n"
