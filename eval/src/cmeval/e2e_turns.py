"""One table per run, one row per turn of the main agent (`cmeval e2e turns`).

The table follows the whole chain of a run: what the agent called in each turn, how long the turn took, how many
tokens its model request used, and whether it showed, opened or edited a gold file. It reads three files of a run
folder: stream.jsonl (the tool calls and their results), proxy.jsonl (one line per model request, with its clock
and usage) and run.json (the gold files and the totals). clock.txt gives the start of the agent.

What the agent did in each turn comes from e2e_steps.turn_steps, with the rules of count_steps (STEPS_VERSION of
today, which can be newer than the version in run.json).

A turn and a model request are matched by the message id: the stream gives each turn the id of its model answer,
and the proxy logs the id of each answer. The requests are those that the token sums of the proxy count (the
model requests with status 200 and a usage block), so the sum of the rows is the proxy's sum in run.json. When
the log has no message ids, the turns and the requests are matched in order, but only when their counts are the
same; else no turn gets a request. A request that no turn matches (a subagent's request, for example) goes to the
row "other requests". The table says which way it matched, and how many turns and requests have no match.

Seconds (from the proxy's clocks):

  start_s  when the turn's request arrived at the proxy, from the start of the agent (clock.txt; else from the
           first request)
  turn_s   from the turn's request to the next turn's request; for the last turn, to the end of the agent. It
           holds the model's answer and the tool calls of the turn
  model_s  from the request to the last byte of the model's answer
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .e2e_run import read_clock
from .e2e_steps import REPO_ROOT, parse_stream, turn_steps
from .paths import e2e_dir
from .proxy import MESSAGES_PATH, read_log

FORMATS = ("md", "csv", "json")
DEFAULT_WIDTH = 100
MARKS = ("surfaced", "opened", "edited")
# Short names of the token columns.
TOKEN_COLUMNS = {"input_tokens": "input", "output_tokens": "output", "cache_read_input_tokens": "cache_read",
                 "cache_creation_input_tokens": "cache_write"}
COLUMNS = ("turn", "start_s", "turn_s", "model_s", *TOKEN_COLUMNS.values(), "tools", "command", "kinds", *MARKS)


class TurnsError(Exception):
    """A run folder that cannot give a table."""


# ---- finding a run

def run_folder(run_id: str, task_id: str, setup: str | None = None, rep: int | str = 1) -> Path:
    """The folder of one run. `run_id` is a run id in CMEVAL_HOME/e2e/runs, or the path of a run id's folder.
    Without a setup, the task must have runs of one setup only. `rep` can also name the folder of a discarded
    attempt (1.discarded-1)."""
    given = Path(run_id)
    base = given if "/" in run_id and given.is_dir() else e2e_dir() / "runs" / run_id
    task_dir = base / task_id
    if not task_dir.is_dir():
        raise TurnsError(f"no folder {task_dir}")
    if setup is None:
        setups = sorted(d.name for d in task_dir.iterdir() if d.is_dir())
        if len(setups) != 1:
            raise TurnsError(f"{task_dir} has the setups {', '.join(setups) or '(none)'}; give --setup")
        setup = setups[0]
    folder = task_dir / setup / str(rep)
    if not folder.is_dir():
        raise TurnsError(f"no folder {folder}")
    return folder


# ---- one table

def _time(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


def counted_requests(records: list[dict]) -> list[dict]:
    """The model requests whose tokens proxy.summarize counts, in the order of their numbers."""
    found = [r for r in records if r.get("path") == MESSAGES_PATH and r.get("status") == 200 and r.get("usage")]
    return sorted(found, key=lambda r: r.get("seq", 0))


def match_requests(turns: list[dict], requests: list[dict]) -> tuple[list[dict | None], str]:
    """The request of each turn (None when it has none), and how they were matched: "message id", "order" or
    "none"."""
    by_id = {r["message_id"]: r for r in requests if r.get("message_id")}
    if by_id:
        return [by_id.get(t["message_id"]) for t in turns], "message id"
    if requests and len(requests) == len(turns):
        return list(requests), "order"
    return [None] * len(turns), "none"


def _short_path(text: str) -> str:
    return text.removeprefix(REPO_ROOT + "/")


def call_label(call: dict) -> str:
    """The command or query of one tool call, on one line."""
    tool, args = call["tool"], call["input"]
    if tool == "Bash":
        text = str(args.get("command") or "")
    elif tool == "Read":
        text = _short_path(str(args.get("file_path") or ""))
        if args.get("offset") or args.get("limit"):
            text += f" (from {args.get('offset') or 1}, {args.get('limit') or 'all'} lines)"
    elif tool in ("Edit", "Write", "NotebookEdit"):
        text = _short_path(str(args.get("file_path") or args.get("notebook_path") or ""))
    elif tool in ("Grep", "Glob"):
        text = str(args.get("pattern") or "") + (f" in {_short_path(str(args['path']))}" if args.get("path") else "")
    elif tool.startswith("mcp__") and isinstance(args.get("query"), str):
        text = args["query"]
    elif tool in ("Task", "Agent") and args.get("description"):
        text = str(args["description"])
    else:
        text = json.dumps(args, ensure_ascii=False)
    text = re.sub(r"\s+", " ", text).strip()
    return ("(blocked) " if call["blocked"] else "") + text


def tool_name(tool: str) -> str:
    """mcp__codemem__search_code is shown as codemem.search_code."""
    if tool.startswith("mcp__"):
        server, _, name = tool[len("mcp__"):].partition("__")
        return f"{server}.{name}" if name else server
    return tool


def _kinds(calls: list[dict]) -> str:
    counts = Counter()
    for call in calls:
        counts.update(["blocked"] if call["blocked"] else call["kinds"] or ["-"])
    return ", ".join(kind if n == 1 else f"{kind} x{n}" for kind, n in counts.items())


def _tokens(request: dict | None) -> dict:
    if request is None:
        return dict.fromkeys(TOKEN_COLUMNS.values())
    usage = request["usage"]
    return {short: int(usage.get(cls) or 0) for cls, short in TOKEN_COLUMNS.items()}


def build_table(folder: Path, gold_files: list[str] | None = None) -> dict:
    """The table of one run folder: its rows, the row of other requests, the sums, and the check of the sums
    against run.json. The gold files come from run.json unless they are given."""
    folder = Path(folder)
    record = json.loads((folder / "run.json").read_text(encoding="utf-8")) if (folder / "run.json").exists() else {}
    if gold_files is None:
        gold_files = (record.get("identity") or {}).get("gold_files")
    if gold_files is None:
        raise TurnsError(f"{folder}: no gold files in run.json; give the task file with --tasks")
    if not (folder / "stream.jsonl").exists():
        raise TurnsError(f"{folder}: no stream.jsonl")
    turns = turn_steps(parse_stream(folder / "stream.jsonl")["events"], gold_files)
    log = folder / "proxy.jsonl"
    requests = counted_requests(read_log(log)[0]) if log.exists() else []
    matched, how = match_requests(turns, requests)
    clock = read_clock(folder)
    starts = [_time(r.get("start")) for r in requests]
    zero = (datetime.fromtimestamp(clock["agent_start"] / 1e9, timezone.utc) if "agent_start" in clock
            else min((s for s in starts if s), default=None))
    end = datetime.fromtimestamp(clock["agent_end"] / 1e9, timezone.utc) if "agent_end" in clock else None

    firsts: dict[tuple[str, str], int] = {}
    for turn in turns:
        for key in MARKS:
            for g in turn[key]:
                firsts.setdefault((g, key), turn["turn"])
    rows = []
    for i, (turn, request) in enumerate(zip(turns, matched)):
        start = _time(request.get("start")) if request else None
        following = matched[i + 1] if i + 1 < len(matched) else None
        nxt = _time(following.get("start")) if following else (end if i + 1 == len(turns) else None)
        row = {
            "turn": turn["turn"],
            "start_s": round((start - zero).total_seconds(), 1) if start and zero else None,
            "turn_s": round((nxt - start).total_seconds(), 1) if start and nxt else None,
            "model_s": round(request["ms_end"] / 1000, 1) if request and request.get("ms_end") is not None else None,
            **_tokens(request),
            "tools": ", ".join(tool_name(c["tool"]) for c in turn["calls"]) or "(text)",
            "command": " ".join((f"[{k}] " if len(turn["calls"]) > 1 else "") + call_label(c)
                                for k, c in enumerate(turn["calls"], 1)),
            "kinds": _kinds(turn["calls"]),
            "calls": [{"tool": c["tool"], "label": call_label(c), "kinds": c["kinds"], "blocked": c["blocked"]}
                      for c in turn["calls"]],
            "subagent_calls": turn["subagent_calls"],
            "message_id": turn["message_id"],
            "request_seq": request.get("seq") if request else None,
        }
        for key in MARKS:
            row[key] = ("first" if any(firsts[(g, key)] == turn["turn"] for g in turn[key])
                        else "yes" if turn[key] else "")
            row[f"{key}_files"] = list(turn[key])
        rows.append(row)

    used = {id(r) for r in matched if r is not None}
    others = [r for r in requests if id(r) not in used]
    other = {short: sum(int(r["usage"].get(cls) or 0) for r in others) for cls, short in TOKEN_COLUMNS.items()}
    other["requests"] = len(others)
    sums = {short: sum(row[short] or 0 for row in rows) + other[short] for short in TOKEN_COLUMNS.values()}
    sums["processed_tokens"] = sum(sums[short] for short in TOKEN_COLUMNS.values())
    sums.update(
        turns=len(rows),
        turn_s=round(sum(row["turn_s"] or 0 for row in rows), 1),
        model_s=round(sum(row["model_s"] or 0 for row in rows), 1),
        tool_calls=sum(len(row["calls"]) for row in rows),
        **{key: sum(1 for row in rows if row[key]) for key in MARKS},
    )
    return {
        "folder": str(folder),
        "run_id": record.get("run_id"), "task_id": record.get("task_id"), "setup": record.get("setup"),
        "rep": record.get("rep"), "model": record.get("model"), "end": record.get("end"),
        "completed": record.get("completed"), "discard": record.get("discard"),
        "gold_files": list(gold_files),
        "match": {"how": how, "turns": len(turns), "requests": len(requests),
                  "turns_without_request": sum(1 for r in matched if r is None), "other_requests": len(others)},
        "rows": rows,
        "other_requests": other,
        "sums": sums,
        "check": check_totals(sums, record, turns=len(turns)),
    }


def check_totals(sums: dict, record: dict, turns: int) -> dict:
    """The sums of the table against run.json: the proxy's token sums, and the main agent's turns of steps."""
    proxy = (record.get("tokens") or {}).get("proxy")
    if not proxy:
        return {"equal": None, "note": "run.json has no proxy token sums"}
    table = {cls: sums[short] for cls, short in TOKEN_COLUMNS.items()}
    table["processed_tokens"] = sums["processed_tokens"]
    differ = [cls for cls in table if table[cls] != proxy.get(cls)]
    recorded_turns = (record.get("steps") or {}).get("turns")
    if recorded_turns is not None and recorded_turns != turns:
        differ.append(f"turns ({turns} here, {recorded_turns} in run.json)")
    source = (record.get("tokens") or {}).get("source")
    note = "" if source == "proxy" else (f"run.json counts the tokens from source {source}, not from the proxy; "
                                         "the table uses the proxy log")
    return {"equal": not differ, "differ": differ, "source": source, "note": note}


# ---- output

def _cut(text: str, width: int) -> str:
    return text if width <= 0 or len(text) <= width else text[:max(width - 3, 1)] + "..."


def _cell(value) -> str:
    return "" if value is None else str(value).replace("|", "\\|")


def command_cell(row: dict, width: int) -> str:
    """The commands of a turn in `width` characters. Several calls share the width, so each one shows."""
    calls = row["calls"]
    if len(calls) <= 1 or width <= 0:
        return _cut(row["command"], width)
    each = max(width // len(calls) - 4, 12)
    return " ".join(f"[{k}] {_cut(c['label'], each)}" for k, c in enumerate(calls, 1))


def _row_values(row: dict, width: int) -> list:
    return [row.get(c) if c != "command" else command_cell(row, width) for c in COLUMNS]


def _sum_values(table: dict) -> tuple[list, list]:
    other, sums = table["other_requests"], table["sums"]
    other_row = ["other requests", "", "", "", *(other[s] for s in TOKEN_COLUMNS.values()),
                 f"{other['requests']} requests", "", "", "", "", ""]
    sum_row = ["sum", "", sums["turn_s"], sums["model_s"], *(sums[s] for s in TOKEN_COLUMNS.values()),
               f"{sums['tool_calls']} calls", f"processed {sums['processed_tokens']}", "",
               *(sums[k] for k in MARKS)]
    return other_row, sum_row


def _header(table: dict) -> list[str]:
    match = table["match"]
    lines = [f"run {table['run_id']}, task {table['task_id']}, setup {table['setup']}, rep {table['rep']}: "
             f"{table['model']}, end {table['end']}, completed {table['completed']}"
             + (", discarded" if table["discard"] else ""),
             f"gold files: {', '.join(table['gold_files']) or '-'}",
             f"turns and requests matched by {match['how']}: {match['turns']} turns, {match['requests']} requests, "
             f"{match['turns_without_request']} turns without a request, {match['other_requests']} other requests"]
    return lines


def _check_line(table: dict) -> str:
    check = table["check"]
    if check["equal"] is None:
        return f"check: {check['note']}"
    text = ("check: the sums equal the totals of run.json" if check["equal"]
            else f"check: the sums differ from run.json: {', '.join(check['differ'])}")
    return text + (f" ({check['note']})" if check["note"] else "")


def format_table(table: dict, fmt: str = "md", width: int = DEFAULT_WIDTH) -> str:
    if fmt == "json":
        return json.dumps(table, indent=2)
    rows = [_row_values(row, width) for row in table["rows"]]
    other_row, sum_row = _sum_values(table)
    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(COLUMNS)
        writer.writerows([*rows, other_row, sum_row])
        return out.getvalue()
    lines = _header(table) + [""]
    lines.append("| " + " | ".join(COLUMNS) + " |")
    lines.append("|" + "|".join("---:" if c in ("turn", "start_s", "turn_s", "model_s", *TOKEN_COLUMNS.values())
                                else "---" for c in COLUMNS) + "|")
    for values in [*rows, other_row, sum_row]:
        lines.append("| " + " | ".join(_cell(v) for v in values) + " |")
    lines += ["", _check_line(table)]
    return "\n".join(lines) + "\n"


# ---- two runs side by side

PAIR_COLUMNS = ("start_s", "processed", "tools", "command", "gold")


def _gold_letters(row: dict) -> str:
    """S, O and E for surfaced, opened and edited; a star marks the first turn for a gold file."""
    return " ".join(key[0].upper() + ("*" if row[key] == "first" else "") for key in MARKS if row[key])


def _pair_cells(row: dict | None, width: int) -> list:
    if row is None:
        return [""] * len(PAIR_COLUMNS)
    tokens = [row[s] for s in TOKEN_COLUMNS.values()]
    processed = sum(tokens) if None not in tokens else None
    return [row["start_s"], processed, row["tools"], command_cell(row, width), _gold_letters(row)]


def label(table: dict) -> str:
    return f"{table['run_id']}/{table['setup']}/{table['rep']}"


def format_pair(left: dict, right: dict, fmt: str = "md", width: int = 60) -> str:
    """Two tables of one task side by side: one row per turn number."""
    if fmt == "json":
        return json.dumps({"runs": [left, right]}, indent=2)
    names = [label(left), label(right)]
    header = ["turn"] + [f"{n} {c}" for n in ("A", "B") for c in PAIR_COLUMNS]
    count = max(len(left["rows"]), len(right["rows"]))
    rows = [[k + 1, *_pair_cells(left["rows"][k] if k < len(left["rows"]) else None, width),
             *_pair_cells(right["rows"][k] if k < len(right["rows"]) else None, width)] for k in range(count)]
    sums = ["sum"] + [cell for t in (left, right) for cell in
                      ("", t["sums"]["processed_tokens"], f"{t['sums']['tool_calls']} calls", "",
                       " ".join(f"{k[0].upper()} {t['sums'][k]}" for k in MARKS))]
    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(header)
        writer.writerows([*rows, sums])
        return out.getvalue()
    lines = [f"A: {names[0]} ({left['end']}, completed {left['completed']})",
             f"B: {names[1]} ({right['end']}, completed {right['completed']})",
             f"task {left['task_id']}; gold: S surfaced, O opened, E edited, * the first turn for a gold file; "
             "processed: the four token classes of the turn's request; the sum row includes other requests", ""]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join("---:" if c.endswith(("turn", "start_s", "processed")) else "---"
                                for c in header) + "|")
    for values in [*rows, sums]:
        lines.append("| " + " | ".join(_cell(v) for v in values) + " |")
    lines += ["", "A " + _check_line(left), "B " + _check_line(right)]
    return "\n".join(lines) + "\n"
