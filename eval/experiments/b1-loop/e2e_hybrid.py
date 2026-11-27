"""Hybrid: in each step Sonnet picks the next tool, grep or codemem search, and may edit in any step.

codemem search here is loop-k as in e2e_loopk.py (merged judge and fix, one fresh call per step, prompt cache off),
with k limited to 3, 5 or 10: a step that wants one or two results should use grep instead.

Step 1: one call (system_hybrid_first.txt) chooses the tool. With codemem it also writes the one-shot query and k,
and the search is loop-k's first round (AugRetriever._retrieve). With grep it writes a regular expression and an
optional path. Each step: the tool runs, then one call (system_hybrid.txt) sees the issue, the notes of earlier
steps, the full source of everything it picked earlier and this step's results, and returns one action:
  edit     exact edits, applied only if every `old` text occurs exactly once in its file
  read     the next step shows only the picks in full (after grep, to read a matching function)
  codemem  the next step is a codemem search over results not yet shown: one free-text query, look_in, next_k
  grep     the next step runs `git grep -E` (grep_pattern, grep_path, grep_ignore_case)
grep shows each matching line (at most GREP_LINES, GREP_PER_FILE per file) with its file, line and enclosing
function; picking a grep line pins that function (or the lines around it, outside any function). An edit that does
not apply is retried once: the next step shows the picks again, with this step's results in the edited files added.
Only step 1 writes a structured query (intent, symptom, anchors); a later codemem search takes one free-text query,
searched by meaning (code and usage) and by its words (BM25), plus the same lists limited to each look_in path.
Safety cap: MAX_STEPS steps or MAX_COST.

Usage: python e2e_hybrid.py TASKS.jsonl TASK_ID REPO_COPY OUT_DIR
Writes OUT_DIR/<LOOP_TAG>.diff and <LOOP_TAG>.summary.json (LOOP_TAG default hybrid). REPO_COPY must be a git
repository (run_vague8.py's fresh copy is). Needs CODEMEM_HOME pointing at the home whose index covers REPO_COPY.
"""
from __future__ import annotations

import collections as C
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from codemem.config import load_config
from codemem.render import format_results
from codemem.search import SearchResponse, _pick_top, make_card, rrf
from codemem.service import CodememService

os.environ.setdefault("LLM_NO_PROMPT_CACHE", "1")  # before llm reads it
import llm  # noqa: E402
from aug_retriever import LOOP_POOL, AugRetriever

llm._kind("hybrid_first", "system_hybrid_first.txt", "schema_hybrid_first.json")
llm._kind("hybrid", "system_hybrid.txt", "schema_hybrid.json")

MAX_STEPS = int(os.environ.get("HYBRID_MAX_STEPS", "15"))
MAX_COST = 3.0
KS = (3, 5, 10)
MAX_PICKED_CHUNKS = 8  # as e2e_loopk.py: earlier picks shown again, at most this many and MAX_PICKED_CHARS characters
MAX_PICKED_CHARS = 60000
CODE_CAP = 20000
GREP_LINES = 40  # matching lines shown per grep step
GREP_PER_FILE = 8
GREP_LINE_CHARS = 300
GREP_WINDOW = 25  # a picked grep line outside any function pins this many lines on each side
TAG = os.environ.get("LOOP_TAG", "hybrid")
NO_RESULTS = "[no new results this step: {why}; your picks are shown in full under picked_earlier]"

tasks_file, task_id, repo_arg, out_dir = sys.argv[1:5]
task = next(t for t in (json.loads(x) for x in Path(tasks_file).read_text(encoding="utf8").split("\n") if x.strip())
            if t["id"] == task_id)
repo = Path(repo_arg).resolve()
out = Path(out_dir).resolve()
out.mkdir(parents=True, exist_ok=True)
service = CodememService(repo, config=load_config(repo))
service.repo_root = repo
stats = service.update(full=False)
if service.last_error or stats is None:
    raise SystemExit(f"codemem update failed: {service.last_error}")
store = service.store
searcher = AugRetriever.__new__(AugRetriever)  # only its search helpers; no eval runner
searcher.config, searcher.mode, searcher.guess, searcher.suspects, searcher.max_rounds = service.config, "loop", False, False, MAX_STEPS


def k_of(value) -> int:
    return value if value in KS else 10


def norm_path(text: str) -> str:
    return (text or "").strip().strip("`'\"").replace("\\", "/").removeprefix("./").strip("/")


def span_of(item) -> tuple[str, int, int, str]:
    """A pick is ("chunk", chunk_id) or ("span", path, start, end): its path, lines and label."""
    if item[0] == "chunk":
        c = store.get_chunks([item[1]]).get(item[1])
        return (c.path, c.start_line, c.end_line, c.qualname) if c else ("", 0, 0, "")
    return item[1], item[2], item[3], "lines around a grep match"


def code_for(picks: list[tuple]) -> str:
    parts, shown = [], []
    for item in picks:
        path, start, end, label = span_of(item)
        if not path or any(p == path and s <= start and end <= e for p, s, e in shown):
            continue
        lines = (repo / path).read_text(encoding="utf8", errors="replace").splitlines()
        end = min(end, len(lines))
        part = f"=== {path} lines {start}-{end} ({label})\n" + "\n".join(lines[start - 1:end])
        if sum(map(len, parts)) + len(part) > MAX_PICKED_CHARS or len(parts) >= MAX_PICKED_CHUNKS:
            break
        parts.append(part)
        shown.append((path, start, end))
    return "\n\n".join(parts)


def show_full(cards) -> tuple[str, list[bool]]:
    """As e2e_loopk.py: numbered results with each chunk's raw code; per result, whether it was shown whole."""
    chunks = store.get_chunks([c.chunk_id for c in cards])
    parts, whole = [], []
    for i, card in enumerate(cards, start=1):
        text = format_results(SearchResponse("", ["llm"], [card]))
        head = (f"{i}." + text[2:] if text.startswith("1.") else text).split("\n", 1)[0]
        chunk = chunks.get(card.chunk_id)
        code = chunk.code if chunk else ""
        ok = len(code) <= CODE_CAP
        if not ok:
            if chunk.kind == "class" and chunk.skeleton:
                code = "[class too long to show whole: its skeleton; its methods are results of their own]\n" + chunk.skeleton[:CODE_CAP]
            else:
                code = code[:CODE_CAP] + f"\n[... cut at {CODE_CAP} characters]"
        parts.append(head + "\n" + code)
        whole.append(ok)
    return "\n\n".join(parts), whole


def enclosing(path: str, line: int):
    return store.conn.execute("SELECT chunk_id, qualname FROM chunks WHERE path=? AND start_line<=? AND end_line>=? "
                              "ORDER BY end_line - start_line LIMIT 1", (path, line, line)).fetchone()


def run_grep(pattern: str, path: str, ignore_case: bool) -> tuple[str, list[tuple], dict]:
    """git grep -E over the working tree: numbered matching lines, the pick each line stands for, and counts."""
    meta = {"pattern": pattern, "path": path, "ignore_case": ignore_case}
    if not pattern:
        return "[grep: empty pattern]", [], meta | {"matches": 0}
    if path and not (repo / path).exists():
        return f"[grep: no file or folder {path}]", [], meta | {"matches": 0}
    cmd = ["git", "-c", "core.quotepath=off", "grep", "-n", "-I", "--no-color", "-E"] + (["-i"] if ignore_case else []) \
        + ["-e", pattern, "--"] + ([path] if path else [])
    r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, encoding="utf8", errors="replace", timeout=180)
    if r.returncode > 1:
        return f"[grep error: {r.stderr.strip()[:300]}]", [], meta | {"matches": 0, "error": True}
    hits = [(m[1], int(m[2]), m[3]) for m in (re.match(r"^(.+?):(\d+):(.*)$", x) for x in r.stdout.splitlines()) if m]
    per_file = C.Counter(p for p, _, _ in hits)
    meta |= {"matches": len(hits), "files": len(per_file)}
    if not hits:
        return f"[grep: no matches for {pattern!r}" + (f" in {path}" if path else "") + "]", [], meta
    lines, items, taken, where = [], [], C.Counter(), []
    for p, n, text in hits:
        if len(items) >= GREP_LINES:
            break
        if taken[p] >= GREP_PER_FILE:
            continue
        taken[p] += 1
        row = enclosing(p, n)
        items.append(("chunk", row[0]) if row else ("span", p, max(1, n - GREP_WINDOW), n + GREP_WINDOW))
        text = text.strip()
        text = text[:GREP_LINE_CHARS] + (" [...]" if len(text) > GREP_LINE_CHARS else "")
        where.append(f"{p}:{n}")
        lines.append(f"{len(items)}. {p}:{n} ({'in ' + row[1] if row else 'not in a function'})  {text}")
    head = f"{len(hits)} matching lines in {len(per_file)} files"
    if len(items) < len(hits):
        head += f"; {len(items)} shown (at most {GREP_PER_FILE} per file)"
        more = [f"{p} ({n - taken[p]})" for p, n in per_file.items() if n > taken[p]][:20]
        lines.append("more matches in: " + ", ".join(more))
    meta["shown_lines"] = where
    return head + "\n" + "\n".join(lines), items, meta


def free_fused(query: dict) -> list[tuple[int, float]]:
    """A later codemem search: the free-text query's code, usage and BM25 lists, and code and BM25 lists limited to
    each look_in path (as AugRetriever._round_fused, with the one text standing in for intent, symptom and anchors)."""
    text = query["query"]
    ranked = {f"q_{signal}": searcher._ranked(store, text, signal, LOOP_POOL) for signal in ("code", "usage", "bm25")}
    for i, prefix in enumerate(query["look_in"]):
        ranked[f"in{i}_bm25"] = searcher._ranked(store, text, "bm25", path_prefix=prefix)
        ranked[f"in{i}_code"] = searcher._ranked(store, text, "code", path_prefix=prefix)
    return rrf(ranked, k=service.config.rrf_k)


def apply(edits: list[dict]) -> tuple[bool, str]:
    """As e2e_loopk.py: all or nothing; every old text must occur exactly once in its file."""
    planned: dict[Path, str] = {}
    for e in edits:
        path = repo / norm_path(e["path"])
        if not path.is_file():
            return False, f"no file {e['path']}"
        text = planned.get(path) or path.open(encoding="utf8", newline="").read()
        crlf = "\r\n" in text
        old, new = (e["old"].replace("\r\n", "\n").replace("\n", "\r\n"), e["new"].replace("\r\n", "\n").replace("\n", "\r\n")) \
            if crlf else (e["old"], e["new"])
        if text.count(old) != 1:
            return False, f"the old text occurs {text.count(old)} times in {e['path']}"
        planned[path] = text.replace(old, new)
    for path, text in planned.items():
        with path.open("w", encoding="utf8", newline="") as f:
            f.write(text)
    return True, ""


def prompt_input(history: list[dict], step_no: int, picked_code: str, results: str, tool: str) -> str:
    past = []
    for h in history:
        entry = {"step": h["step"], "tool": h["tool"], "input": h["input"]}
        for key, name in (("k", "k"), ("matches", "grep_matching_lines"), ("analysis", "your_notes"),
                          ("picked", "your_picks"), ("edit_attempt", "edit_attempt")):
            if key in h:
                entry[name] = h[key]
        past.append(entry)
    return (f"Repository: {task['repo']}\n\n<issue>\n{task['query']}\n</issue>\n\n"
            f"<earlier_steps>\n{json.dumps(past, ensure_ascii=False, indent=1)}\n</earlier_steps>\n\n"
            f"<picked_earlier>\n{picked_code}\n</picked_earlier>\n\n"
            f"<results step=\"{step_no}\" tool=\"{tool}\">\n{results}\n</results>")


def grep_input(o: dict) -> dict:
    return {"pattern": o.get("grep_pattern") or "", "path": norm_path(o.get("grep_path")), "ignore_case": bool(o.get("grep_ignore_case"))}


start = time.time()
first_record = llm.extract("hybrid_first", llm.oneshot_input(task["repo"], task["query"]))
cost = first_record.get("cost_usd") or 0.0
fo = first_record["output"]
first = llm.clean(fo, task["query"])
if fo["tool"] == "grep":
    history = [{"step": 1, "tool": "grep", "input": grep_input(fo)}]
else:
    history = [{"step": 1, "tool": "codemem", "k": k_of(fo.get("k")),
                "input": {key: first[key] for key in ("intent", "symptom", "anchors")} | {"look_in": []}}]
seen: set[int] = set()
picks, calls, tools, fixed, retry = [], C.Counter({"first": 1}), C.Counter(), None, False
for step_no in range(1, MAX_STEPS + 1):
    h = history[-1]
    tools[h["tool"]] += 1
    items, item_paths = [], []
    if h["tool"] == "codemem":
        if step_no == 1:
            cards, _ = searcher._retrieve(store, task["query"], first, False, h["k"])
        else:
            fused = free_fused(h["input"])
            fresh = _pick_top([item for item in fused if item[0] not in seen], h["k"], store.get_chunks)
            cards = [make_card(chunk, score, service.config) for chunk, score in fresh]
        shown, whole = show_full(cards) if cards else (NO_RESULTS.format(why="codemem found no results not shown before"), [])
        seen.update(c.chunk_id for c in cards)
        items, item_paths = [("chunk", c.chunk_id) for c in cards], [c.path for c in cards]
        h.update(shown=[[c.path, c.start_line, c.end_line] for c in cards], shown_whole=whole)
    elif h["tool"] == "grep":
        shown, items, meta = run_grep(**h["input"])
        item_paths = [span_of(it)[0] for it in items]
        h.update(matches=meta["matches"], grep_shown=meta.get("shown_lines", []))
    else:  # read, or the retry after an edit that did not apply
        shown = NO_RESULTS.format(why=h.pop("why"))
    picked_code = code_for(picks)
    h["picked_shown"] = [line[4:] for line in picked_code.split("\n") if line.startswith("=== ")]
    record = llm.extract("hybrid", prompt_input(history, step_no, picked_code, shown, h["tool"]))
    cost += record.get("cost_usd") or 0.0
    calls["step"] += 1
    o = record["output"]
    analysis = o["analysis"].strip()
    new_picks = [items[p - 1] for p in dict.fromkeys(o["picks"]) if isinstance(p, int) and 1 <= p <= len(items)]
    picks += [it for it in new_picks if it not in picks]
    h.update(action=o["action"], analysis=analysis,
             picked=[f"{span_of(it)[0]}:{span_of(it)[3]}" for it in new_picks])
    if o["action"] == "edit" and o["edits"]:
        ok, why = apply(o["edits"])
        if ok:
            h["edit_attempt"] = "applied"
            fixed = {"step": step_no, "explanation": analysis, "edits": len(o["edits"])}
            break
        h["edit_attempt"] = f"did not apply: {why}"
        paths = {norm_path(e["path"]) for e in o["edits"]}
        picks += [it for it, p in zip(items, item_paths) if p in paths and it not in picks]
    elif o["action"] == "edit":
        h["edit_attempt"] = "did not apply: no edits given"
    retry = h.get("edit_attempt", "").startswith("did not apply") and not retry
    if cost > MAX_COST:
        break
    if retry:
        history.append({"step": step_no + 1, "tool": "read", "input": {}, "why": "your last edit did not apply"})
    elif o["action"] in ("read", "edit"):  # an edit that failed twice in a row also just shows the picks again
        history.append({"step": step_no + 1, "tool": "read", "input": {},
                        "why": "you chose read" if o["action"] == "read" else "your last edit did not apply"})
    elif o["action"] == "grep":
        history.append({"step": step_no + 1, "tool": "grep", "input": grep_input(o)})
    else:
        look_in = list(dict.fromkeys(x.strip() for x in o["look_in"] if isinstance(x, str) and x.strip()))[:llm.MAX_LOOK_IN]
        query = {"query": o["query"].strip() or analysis,
                 "look_in": [p for p in (searcher._prefix(store, x) for x in look_in) if p]}
        history.append({"step": step_no + 1, "tool": "codemem", "input": query, "k": k_of(o.get("next_k"))})

service.close()
if history[-1].get("why") is not None:
    history[-1].pop("why")
patch = subprocess.run(["git", "diff"], cwd=repo, capture_output=True, text=True, encoding="utf8").stdout
(out / f"{TAG}.diff").write_text(patch, encoding="utf8")
summary = {"arm": "hybrid-grep-codemem", "judge_sees": "raw code", "task": task_id, "fixed": fixed, "rounds": sum(tools.values()), "tools": dict(tools), "ks": [h["k"] for h in history if h["tool"] == "codemem" and "shown" in h],
           "calls": dict(calls), "sonnet_calls": sum(calls.values()), "cost_usd": round(cost, 4), "seconds": round(time.time() - start),
           "diff_stat": subprocess.run(["git", "diff", "--stat"], cwd=repo, capture_output=True, text=True).stdout.strip(),
           "history": history}
(out / f"{TAG}.summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf8")
print(json.dumps({k: v for k, v in summary.items() if k != "history"}, indent=1))
for h in history:
    print(f"step {h['step']}: {h['tool']} {json.dumps(h['input'], ensure_ascii=False)[:160]} -> action={h.get('action')} "
          f"picked={h.get('picked')} {h.get('edit_attempt', '')}")
