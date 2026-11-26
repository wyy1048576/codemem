"""The replay: ask the first codemem search of each run again at several numbers of results, and read from the
records what that search cost in the run.

Tracks B and C set the number of results that codemem's search_code returns. This module gives them two
measurements from the runs of track A. It starts no agent.

Part 1, the replay. For each run of a codemem setup:

  1. find the first search_code call of the main agent in stream.jsonl: the query and every other argument
  2. start the codemem program as an MCP server on the task's base commit (the src/ worktree that `cmeval e2e
     index` made) with a private copy of the task's index, as a run starts it (see replay_task)
  3. wait until the index is ready and the embedding model is loaded (codemem_gate.wait_ready, the wait of a
     run's gate)
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
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .codemem_gate import McpClient, McpError, full_search, notes_of, tool_texts, unwrap, wait_ready  # noqa: F401
from .e2e_index import CODEMEM_ENV, REPO_ROOT, codemem_checkout, codemem_commit
from .e2e_steps import TurnCounter, parse_stream, result_text
from .files import write_json, write_text_atomic
from .metrics.matching import excluded, hit_matches
from .paths import e2e_dir
from .proxy import read_log
from .retriever import Hit
from .tasks import Span, Task, load_tasks

SCHEMA = 1
SEARCH_TOOL = "mcp__codemem__search_code"
DEFAULT_KS = (5, 10, 20, 30, 50)
TOOL_DEFAULT_K = 10  # the default of search_code when the agent gives no k
MAX_K = 50  # search_code takes k from 1 to 50
DEFAULT_IOU = 0.5
MESSAGES_PATH = "/v1/messages"
# The texts of codemem's notes, and notes_of, are in codemem_gate.py: the runner reads them too.
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

def parse_results(text: str) -> list[dict]:
    """The result list of a rendered search_code text: rank, path, start and end line, name, chunk id."""
    return [{"rank": int(m[1]), "path": m[2], "start": int(m[3]), "end": int(m[4]), "name": m[5],
             "chunk_id": int(m[6])} for m in _HEAD.finditer(text)]


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
    lines.append(f"- First search in the run answered from keywords only (model loading, or codemem could not "
                 f"embed): {notes['keywords_only']}; index being built: {notes['indexing']}; edits not yet indexed: "
                 f"{notes['not_fresh']}.")
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


# ---- the replay through codemem's MCP server

class ReplayError(McpError):
    pass


READY_POLL_S = 2.0


def server_env(steering: str | None, home: Path) -> dict:
    """The environment of the replay's codemem: what a run gives it (e2e_run.codemem_mcp_config), with the
    host's Hugging Face cache and an empty CODEMEM_HOME. No CODEMEM_ variable of the caller passes."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("CODEMEM_")}
    env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "CODEMEM_HOME": str(home),
                "CODEMEM_MODEL_IDLE_MINUTES": "0", **CODEMEM_ENV})
    if steering and steering != "default":
        env["CODEMEM_STEERING"] = steering
    return env


def _gold_from_entry(entry: dict) -> dict:
    gold = entry["gold"]
    return {"files": gold["files"], "function_excluded": gold["function_excluded"],
            "functions": [Span(f["path"], f["start"], f["end"], f.get("symbol")) for f in gold["functions"]]}


def cli_search(program: Path, src: Path, index: Path, env: dict, args: dict, k: int, timeout: float,
               signals: str | None = None) -> list[dict]:
    """The result list of `codemem search --json` with the arguments of a search_code call."""
    argv = [str(program), "search", "--repo", str(src), "--index-dir", str(index), "-k", str(k), "--json"]
    if signals:
        argv += ["--signals", signals]
    if args.get("path_prefix"):
        argv += ["--path-prefix", str(args["path_prefix"])]
    if args.get("kinds"):
        kinds = args["kinds"]
        argv += ["--kinds", ",".join(kinds) if isinstance(kinds, list) else str(kinds)]
    if args.get("tests"):
        argv += ["--tests", str(args["tests"])]
    argv += ["--", str(args.get("query", ""))]
    proc = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise ReplayError(f"codemem search ended with exit code {proc.returncode}: {proc.stderr.strip()[-500:]}")
    data = json.loads(proc.stdout)
    return [{"rank": i, "path": r["path"], "start": r["start_line"], "end": r["end_line"],
             "name": r.get("qualname"), "chunk_id": r.get("chunk_id")}
            for i, r in enumerate(data.get("results") or [], start=1)]


def check_entry(entry: dict, same_commits: bool, bm25: list[dict] | None = None) -> dict:
    """Compare the agent's result list with the replay at the run's k (or with the keyword-only search)."""
    notes = entry["in_run"]["notes"]
    suffix = "" if same_commits else ", other codemem commit"
    if notes is None:
        return {"verdict": "not checked: no result in the run"}
    if notes["keywords_only"]:
        if bm25 is None:
            return {"verdict": "not checked: keywords only in the run"}
        cmp = compare_lists(entry["in_run"]["results"], bm25)
        return {"against": "codemem search --signals bm25", **cmp,
                "verdict": ("same" if cmp["same"] else "differs") + " (keywords only)" + suffix}
    if notes["indexing"] or notes["not_fresh"]:
        return {"verdict": "not checked: the run's index was not complete"}
    at = _at(entry, entry["call"]["k"])
    if at is None:
        return {"verdict": "not checked: no replay"}
    cmp = compare_lists(entry["in_run"]["results"], at["results"])
    return {"against": f"replay at k={entry['call']['k']}", **cmp,
            "verdict": ("same" if cmp["same"] else "differs") + suffix}


def replay_task(entries: list[dict], *, program: Path, program_commit: str | None, src: Path, index: Path,
                index_meta: dict, steering: str | None, ks: list[int], work: Path, log: Path, iou: float,
                ready_timeout: float, call_timeout: float, bm25_check: bool) -> None:
    """Replay the first search of each entry (runs of one task with one steering level) on a private copy of
    the task's index. Sets entry["replay"] and entry["check"]. The index and src/ are never written."""
    copy, home = work / "index", work / "home"
    shutil.copytree(index, copy)
    home.mkdir()
    env = server_env(steering, home)
    client = McpClient([str(program), "mcp", str(src), "--index-dir", str(copy)], env, log)
    try:
        init = client.initialize(call_timeout)
        ready = wait_ready(client, ready_timeout, call_timeout, poll=READY_POLL_S)
        ready.pop("status_text", None)
        for entry in entries:
            gold = _gold_from_entry(entry)
            by_k = {}
            for k in sorted(set(ks) | {entry["call"]["k"]}):
                t0 = time.monotonic()
                result = client.call_tool("search_code", {**entry["call"]["args"], "k": k}, call_timeout)
                text, wire = tool_texts(result)
                results = parse_results(text)
                by_k[str(k)] = {"k": k, "results": results, "score": score_results(results, gold, iou),
                                "text_chars": len(text), "wire_chars": len(wire), "notes": notes_of(text),
                                "is_error": bool(result.get("isError")),
                                "seconds": round(time.monotonic() - t0, 3), "text": text}
            entry["replay"] = {"by_k": by_k, "server": {"name": (init.get("serverInfo") or {}).get("name"),
                                                        "version": (init.get("serverInfo") or {}).get("version"),
                                                        "protocol": init.get("protocolVersion"), **ready},
                               "index": index_meta, "steering": steering}
    finally:
        client.close()
    same = (program_commit is not None and program_commit == index_meta.get("codemem_commit"))
    for entry in entries:
        bm25 = None
        if bm25_check and (entry["in_run"]["notes"] or {}).get("keywords_only"):
            try:
                bm25 = cli_search(program, src, copy, env, entry["call"]["args"], entry["call"]["k"], call_timeout,
                                  signals="bm25")
            except (McpError, OSError, ValueError, subprocess.SubprocessError) as exc:
                entry["check"] = {"verdict": "not checked: keyword search failed", "error": str(exc)}
                continue
        same_commits = same and entry["run_codemem_commit"] == program_commit \
            and entry["run_index_codemem_commit"] == index_meta.get("codemem_commit")
        entry["check"] = check_entry(entry, same_commits, bm25)


# ---- the whole replay

def default_tasks_file(recipe: str) -> Path:
    return REPO_ROOT / "eval" / "tasks" / "e2e" / f"{recipe}.jsonl"


def read_runs(run_ids: list[str], *, tasks_files: list[Path] | None = None, iou: float = DEFAULT_IOU,
              progress: Callable[[str], None] = lambda m: None) -> tuple[list[dict], Counter, list[str]]:
    """The entries of every run of a codemem setup with a first search_code call, the counts of runs left out
    by reason, and warnings. The tasks come from tasks_files, or from eval/tasks/e2e/<recipe>.jsonl."""
    runs_root = e2e_dir() / "runs"
    given = {t.id: t for path in tasks_files or [] for t in load_tasks(path)}
    by_recipe: dict[str, dict[str, Task]] = {}
    entries, skipped, warnings = [], Counter(), []
    for run_id in run_ids:
        root = runs_root / run_id
        if not root.is_dir():
            skipped["run id not found"] += 1
            warnings.append(f"no run folder {root}")
            continue
        for path in sorted(p for p in root.glob("*/*/*/run.json") if p.parent.name.isdigit()):
            record = json.loads(path.read_text(encoding="utf-8"))
            record.setdefault("run_id", run_id)
            if record.get("discard"):
                skipped["discarded run"] += 1
                continue
            if not (record.get("identity") or {}).get("codemem"):
                skipped["setup without codemem"] += 1
                continue
            stream = path.parent / "stream.jsonl"
            if not stream.exists():
                skipped["no stream.jsonl"] += 1
                continue
            events = parse_stream(stream)["events"]
            search = first_search(events)
            if search is None:
                skipped["no search_code call of the main agent"] += 1
                continue
            proxy = path.parent / "proxy.jsonl"
            records = read_log(proxy)[0] if proxy.exists() else None
            if tasks_files:
                task = given.get(record.get("task_id"))
            else:
                recipe = record.get("recipe") or ""
                if recipe not in by_recipe:
                    file = default_tasks_file(recipe)
                    by_recipe[recipe] = {t.id: t for t in load_tasks(file)} if file.exists() else {}
                task = by_recipe[recipe].get(record.get("task_id"))
            entry = run_entry(record, events, records, search, task, iou)
            entry["run_dir"] = str(path.parent)
            where = f"{entry['run_id']} {entry['task_id']} rep {entry['rep']}"
            if task is None:
                warnings.append(f"{where}: task not in the task files; gold files from run.json, no function gold")
            elif entry["run_index_base_commit"] and entry["run_index_base_commit"] != task.base_commit:
                warnings.append(f"{where}: the run's index is of base commit {entry['run_index_base_commit'][:12]}, "
                                f"the task's is {task.base_commit[:12]}")
            entries.append(entry)
        progress(f"{run_id}: {sum(1 for e in entries if e['run_id'] == run_id)} runs with a first search")
    return entries, skipped, warnings


def replay_entries(entries: list[dict], *, program: Path, ks: list[int], index_root: Path, log_dir: Path,
                   work_root: Path | None = None, iou: float = DEFAULT_IOU, ready_timeout: float = 900,
                   call_timeout: float = 180, bm25_check: bool = True,
                   progress: Callable[[str], None] = lambda m: None) -> dict:
    """Replay the entries, one MCP server for each task and steering level. Returns the program, its commit and
    the environment that codemem got. A task that fails gets replay.error in its entries."""
    program_commit = codemem_commit(codemem_checkout(program))
    log_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[tuple, list[dict]] = {}
    for entry in entries:
        groups.setdefault((entry["recipe"], entry["task_id"], entry["steering"]), []).append(entry)
    env_shown = None
    for n, ((recipe, task_id, steering), group) in enumerate(sorted(groups.items(), key=lambda g: str(g[0])), 1):
        root = index_root / str(recipe) / str(task_id)
        try:
            meta = json.loads((root / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = None
        error = None
        if meta is None or not (root / "index").is_dir() or not (root / "src").is_dir():
            error = f"no index at {root} (index/, src/ and index.json); run cmeval e2e index {recipe}"
        elif group[0]["base_commit"] and meta.get("base_commit") != group[0]["base_commit"]:
            error = f"the index at {root} is of base commit {str(meta.get('base_commit'))[:12]}, not the task's"
        if error is None:
            work = Path(tempfile.mkdtemp(prefix="cmeval-replay-", dir=work_root))
            t0 = time.monotonic()
            try:
                replay_task(group, program=program, program_commit=program_commit, src=root / "src",
                            index=root / "index", index_meta=meta, steering=steering, ks=ks, work=work,
                            log=log_dir / f"{task_id}-{steering}.log", iou=iou, ready_timeout=ready_timeout,
                            call_timeout=call_timeout, bm25_check=bm25_check)
                env_shown = env_shown or {k: v for k, v in server_env(steering, work / "home").items()
                                          if k.startswith(("CODEMEM_", "HF_", "TRANSFORMERS_"))}
            except (McpError, OSError, ValueError, subprocess.SubprocessError, shutil.Error) as exc:
                error = str(exc)
            finally:
                shutil.rmtree(work, ignore_errors=True)
            seconds = round(time.monotonic() - t0)
        if error is not None:
            for entry in group:
                entry["replay"], entry["check"] = {"error": error}, {"verdict": "not checked: replay failed"}
            progress(f"[{n}/{len(groups)}] {task_id} ({steering}): failed: {error}")
        else:
            progress(f"[{n}/{len(groups)}] {task_id} ({steering}): {len(group)} runs replayed in {seconds} s")
    return {"bin": str(program), "commit": program_commit, "env": env_shown}


def report(summary: dict) -> str:
    """The Markdown of a replay: the runs and checks, the tables of part 1, the table of part 2."""
    entries, ks = summary["runs"], summary["ks"]
    head = [f"# Replay of first codemem searches ({summary['created']})", "",
            f"Run ids: {', '.join(summary['run_ids'])}. Numbers of results: {', '.join(map(str, ks))}. "
            f"Function match: inside, or line IoU >= {summary['iou']}."]
    if summary.get("codemem"):
        head.append(f"codemem: {summary['codemem']['bin']} at commit {summary['codemem']['commit']}.")
    head.append("")
    parts = ["\n".join(head), check_summary(entries, Counter(summary["skipped"]))]
    if summary["warnings"]:
        parts.append("**Warnings**\n\n" + "\n".join(f"- {w}" for w in summary["warnings"]) + "\n")
    if summary.get("codemem"):
        parts.append(replay_tables(entries, ks))
    parts.append(cost_table(entries))
    return "\n".join(parts)


def replay(run_ids: list[str], *, ks: list[int] | tuple[int, ...] = DEFAULT_KS, tasks_files: list[Path] | None = None,
           program: Path | None = None, index_root: Path | None = None, out: Path | None = None,
           records_only: bool = False, iou: float = DEFAULT_IOU, ready_timeout: float = 900,
           call_timeout: float = 180, bm25_check: bool = True, work_root: Path | None = None,
           progress: Callable[[str], None] = lambda m: None) -> tuple[dict, Path, str]:
    """Read the runs, replay their first searches (unless records_only), and write the JSON file and the
    Markdown file beside it. Returns the summary, the JSON path and the Markdown."""
    ks = sorted(set(ks))
    if not ks or ks[0] < 1 or ks[-1] > MAX_K:
        raise ReplayError(f"each number of results must be from 1 to {MAX_K}")
    created = datetime.now(timezone.utc)
    out = out or e2e_dir() / "replay" / f"replay-{created:%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    entries, skipped, warnings = read_runs(run_ids, tasks_files=tasks_files, iou=iou, progress=progress)
    codemem = None
    if not records_only and entries:
        if program is None:
            raise ReplayError("no codemem program")
        codemem = replay_entries(entries, program=program, ks=ks, index_root=index_root or e2e_dir() / "indexes",
                                 log_dir=out.with_name(out.stem + "-logs"), work_root=work_root, iou=iou,
                                 ready_timeout=ready_timeout, call_timeout=call_timeout, bm25_check=bm25_check,
                                 progress=progress)
    summary = {"schema": SCHEMA, "created": created.isoformat(timespec="seconds"), "run_ids": list(run_ids),
               "ks": ks, "iou": iou, "records_only": records_only, "codemem": codemem, "skipped": dict(skipped),
               "warnings": warnings, "runs": entries}
    write_json(out, summary)
    text = report(summary)
    write_text_atomic(out.with_suffix(".md"), text)
    return summary, out, text
