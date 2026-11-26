"""End-to-end search loop: codemem in place of grep, plus a fix step. Runs until a fix is applied.

Each round: a codemem search (round 1 = the one-shot query; later rounds = Sonnet's next query, showing only
results not seen before), then Sonnet judges the 50 results (system_loop.txt). When it says found, a fix call
(system_fix.txt) gets the full source of the picked code and either returns exact edits or explains why the fix
is not there. Edits are applied only if every `old` text occurs exactly once in its file; otherwise, or when Sonnet
cannot fix, its explanation and next query go into the following round. Safety cap: MAX_ROUNDS searches or MAX_COST.

Usage: python e2e_loop.py TASKS.jsonl TASK_ID REPO_COPY OUT_DIR
Needs CODEMEM_HOME pointing at the home whose index covers REPO_COPY.
"""
from __future__ import annotations

import collections as C
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from codemem.config import load_config
from codemem.search import _pick_top, make_card
from codemem.service import CodememService

import llm
from aug_retriever import LOOP_SHOWN, AugRetriever

MAX_ROUNDS = 10
MAX_COST = 3.0
MAX_FIX_CHUNKS = 8
MAX_CODE_CHARS = 60000
SHOWN = int(os.environ.get("LOOP_N", LOOP_SHOWN))  # results shown per round (default 50)
TAG = os.environ.get("LOOP_TAG", "loop")  # output file prefix

tasks_file, task_id, repo_arg, out_dir = sys.argv[1:5]
task = next(t for t in (json.loads(x) for x in Path(tasks_file).read_text(encoding="utf8").split("\n") if x.strip())
            if t["id"] == task_id)
repo = Path(repo_arg).resolve()
out = Path(out_dir).resolve()
out.mkdir(parents=True, exist_ok=True)
service = CodememService(repo, config=load_config(repo))
service.repo_root = repo
stats = service.update(full=False)  # bring the index up to this copy (cheap when it already matches)
if service.last_error or stats is None:
    raise SystemExit(f"codemem update failed: {service.last_error}")
store = service.store
searcher = AugRetriever.__new__(AugRetriever)  # only its search helpers; no eval runner
searcher.config, searcher.mode, searcher.guess, searcher.suspects, searcher.max_rounds = service.config, "loop", False, False, MAX_ROUNDS


def code_for(chunk_ids: list[int]) -> str:
    chunks = store.get_chunks(chunk_ids)
    parts, shown = [], []
    for cid in chunk_ids:
        c = chunks.get(cid)
        if c is None or any(p == c.path and s <= c.start_line and c.end_line <= e for p, s, e in shown):
            continue
        lines = (repo / c.path).read_text(encoding="utf8", errors="replace").splitlines()
        part = f"=== {c.path} lines {c.start_line}-{c.end_line} ({c.qualname})\n" + "\n".join(lines[c.start_line - 1:c.end_line])
        if sum(map(len, parts)) + len(part) > MAX_CODE_CHARS or len(parts) >= MAX_FIX_CHUNKS:
            break
        parts.append(part)
        shown.append((c.path, c.start_line, c.end_line))
    return "\n\n".join(parts)


def apply(edits: list[dict]) -> tuple[bool, str]:
    """All or nothing: every old text must occur exactly once in its file."""
    planned: dict[Path, str] = {}
    for e in edits:
        path = repo / e["path"].strip().replace("\\", "/").removeprefix("./")
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


def verbatim(values, source: str) -> list[str]:
    return [v for v in dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip()) if v in source][:llm.MAX_ANCHORS]


start = time.time()
first = llm.clean(llm.extract("oneshot", llm.oneshot_input(task["repo"], task["query"]))["output"], task["query"])
cards, _ = searcher._retrieve(store, task["query"], first, False, SHOWN)
query = {key: first[key] for key in ("intent", "symptom", "anchors")} | {"look_in": []}
history = [{"round": 1, "query": query}]
seen: set[int] = set()
seen_text, picks, cost, calls, fixed = "", [], 0.0, C.Counter(), None
for round_no in range(1, MAX_ROUNDS + 1):
    if round_no > 1:
        fused = searcher._round_fused(store, query)
        fresh = _pick_top([item for item in fused if item[0] not in seen], SHOWN, store.get_chunks)
        cards = [make_card(chunk, score, service.config) for chunk, score in fresh]
    calls["codemem_rounds"] += 1
    if not cards:
        break
    shown = searcher._show(cards)
    seen.update(c.chunk_id for c in cards)
    history[-1]["shown"] = [[c.path, c.start_line, c.end_line] for c in cards]
    seen_text += "\n" + shown
    record = llm.extract("loop", llm.loop_input(task["repo"], task["query"], history, round_no, shown))
    cost += record.get("cost_usd") or 0.0
    calls["judge"] += 1
    judged = llm.clean_loop(record["output"], task["query"], seen_text, len(cards))
    picked = [cards[p - 1] for p in judged["picks"]]
    round_picks = [c.chunk_id for c in picked]
    picks += [c for c in round_picks if c not in picks]
    history[-1].update(analysis=judged["analysis"], picked=[f"{c.path}:{c.qualname}" for c in picked], found=judged["found"])
    nxt = {k: judged[k] for k in ("intent", "symptom", "anchors", "look_in")}
    if judged["found"] and picks:
        code = code_for(round_picks + [c for c in picks if c not in round_picks])
        seen_text += "\n" + code
        record = llm.extract("fix", llm.fix_input(task["repo"], task["query"], history, code))
        cost += record.get("cost_usd") or 0.0
        calls["fix"] += 1
        fix = record["output"]
        history[-1]["fix_shown"] = [line[4:] for line in code.split("\n") if line.startswith("=== ")]
        if fix["can_fix"] and fix["edits"]:
            ok, why = apply(fix["edits"])
            if ok:
                history[-1]["fix_attempt"] = "applied: " + fix["explanation"]
                fixed = {"round": round_no, "explanation": fix["explanation"], "edits": len(fix["edits"])}
                break
            history[-1]["fix_attempt"] = f"edits did not apply ({why}): " + fix["explanation"]
        else:
            history[-1]["fix_attempt"] = "could not fix: " + fix["explanation"]
        nxt = {"intent": fix["intent"], "symptom": fix["symptom"],
               "anchors": verbatim(fix["anchors"], task["query"] + seen_text), "look_in": fix["look_in"][:llm.MAX_LOOK_IN]}
    if cost > MAX_COST:
        break
    nxt["look_in"] = [p for p in (searcher._prefix(store, x) for x in nxt["look_in"]) if p]
    query = nxt
    history.append({"round": round_no + 1, "query": query})

service.close()
patch = subprocess.run(["git", "diff"], cwd=repo, capture_output=True, text=True, encoding="utf8").stdout
(out / f"{TAG}.diff").write_text(patch, encoding="utf8")
summary = {"arm": "codemem-loop", "shown_per_round": SHOWN, "task": task_id, "fixed": fixed, "rounds": len(history), "calls": dict(calls),
           "sonnet_calls": calls["judge"] + calls["fix"], "cost_usd": round(cost, 4), "seconds": round(time.time() - start),
           "diff_stat": subprocess.run(["git", "diff", "--stat"], cwd=repo, capture_output=True, text=True).stdout.strip(),
           "history": history}
(out / f"{TAG}.summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf8")
print(json.dumps({k: v for k, v in summary.items() if k != "history"}, indent=1))
for h in history:
    print(f"round {h['round']}: found={h.get('found')} picked={h.get('picked')}\n  fix: {h.get('fix_attempt', '-')[:400]}")
