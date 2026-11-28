"""Loop-k: codemem in place of grep, where Sonnet picks how many results to read and may edit in any round.
This is Track B's chosen loop (2026-11-26): merged judge and fix, prompt cache off. See loop_k.md.

Round 1: one call writes the query and picks k in {1, 2, 3, 5, 10} (system_oneshot_k.txt). Each round: a codemem
search shows the top k results not shown before, as raw code; one call (system_loopk.txt) sees them, the notes of
earlier rounds and the full source of the results it picked earlier, and either returns exact edits or the next
query with the next k. Edits are applied only if every `old` text occurs exactly once in its file; otherwise the
reason goes into the next round, which shows the same code again and no new results. Safety cap: MAX_ROUNDS
searches or MAX_COST.

Usage: python e2e_loopk.py TASKS.jsonl TASK_ID REPO_COPY OUT_DIR
Writes OUT_DIR/<LOOP_TAG>.diff and <LOOP_TAG>.summary.json (LOOP_TAG default loopk).
Needs CODEMEM_HOME pointing at the home whose index covers REPO_COPY.
Prompt caching is off by default (LLM_NO_PROMPT_CACHE=1): each call is a new conversation, so a cache write is never
read back and only costs the write premium. LLM_NO_PROMPT_CACHE=0 turns it back on.
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
from codemem.render import format_results
from codemem.search import SearchResponse, _pick_top, make_card
from codemem.service import CodememService

os.environ.setdefault("LLM_NO_PROMPT_CACHE", "1")  # before llm reads it
import llm  # noqa: E402
from aug_retriever import AugRetriever

MAX_ROUNDS = 10
MAX_COST = 3.0
KS = (1, 2, 3, 5, 10)
MAX_PICKED_CHUNKS = 8  # earlier picks shown again, at most this many chunks and MAX_PICKED_CHARS characters
MAX_PICKED_CHARS = 60000
CODE_CAP = 20000  # a result longer than this is cut; a class that long is shown as its skeleton
TAG = os.environ.get("LOOP_TAG", "loopk")
# LOOP_FIXED_K=n ("merged" loop): always n results per round, and the first query comes from the plain one-shot call,
# as in e2e_loop.py, so it differs from that loop only in having one call per round (judge and fix merged).
FIXED_K = int(os.environ["LOOP_FIXED_K"]) if os.environ.get("LOOP_FIXED_K") else None
# LOOP_HOP="5:3,10:2": after each round's search, add call-graph neighbours (callers and callees, codemem's edges) of
# the round's results: the 3 closest to the issue for each of results 1-5, the 2 closest for each of results 6-10.
# Closest = cosine between the neighbour's code vector and the issue's query vector. Left out: results shown
# before or in this round, and hubs (more than HOP_HUB callers). The neighbours are shown after the results, as
# raw code, and can be picked or edited like them.
HOP = [tuple(int(x) for x in band.split(":")) for band in os.environ.get("LOOP_HOP", "").split(",") if band]
HOP_HUB = 50

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
searcher.config, searcher.mode, searcher.guess, searcher.suspects, searcher.max_rounds = service.config, "loop", False, False, MAX_ROUNDS


def k_of(value) -> int:
    return value if value in KS else 10


def code_for(chunk_ids: list[int]) -> str:
    chunks = store.get_chunks(chunk_ids)
    parts, shown = [], []
    for cid in chunk_ids:
        c = chunks.get(cid)
        if c is None or any(p == c.path and s <= c.start_line and c.end_line <= e for p, s, e in shown):
            continue
        lines = (repo / c.path).read_text(encoding="utf8", errors="replace").splitlines()
        part = f"=== {c.path} lines {c.start_line}-{c.end_line} ({c.qualname})\n" + "\n".join(lines[c.start_line - 1:c.end_line])
        if sum(map(len, parts)) + len(part) > MAX_PICKED_CHARS or len(parts) >= MAX_PICKED_CHUNKS:
            break
        parts.append(part)
        shown.append((c.path, c.start_line, c.end_line))
    return "\n\n".join(parts)


def show_full(cards) -> tuple[str, list[bool]]:
    """Numbered results with each chunk's raw code from the index; also, per result, whether it was shown whole."""
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




def hop_cards(cards, seen_ids: set[int]) -> list:
    """The one-hop additions for this round's results (see LOOP_HOP)."""
    global _qvec
    if _qvec is None:
        from aug_retriever import _MemoEmbedder
        _qvec = _MemoEmbedder(service.config.vectors["code"], service.config).embed_queries([task["query"]])[0]
    conn, taken, out = store.conn, set(seen_ids) | {c.chunk_id for c in cards}, []
    for rank, card in enumerate(cards, start=1):
        quota = next((q for last, q in HOP if rank <= last), 0)
        if not quota:
            continue
        nbrs = {r[0] for r in conn.execute("SELECT callee_id FROM edges WHERE caller_id = ?", (card.chunk_id,))}
        nbrs |= {r[0] for r in conn.execute("SELECT caller_id FROM edges WHERE callee_id = ?", (card.chunk_id,))}
        nbrs = [c for c in nbrs - taken
                if conn.execute("SELECT COUNT(*) FROM edges WHERE callee_id = ?", (c,)).fetchone()[0] <= HOP_HUB]
        if not nbrs:
            continue
        best = store.vector_search("code", _qvec, len(nbrs), sorted(nbrs))[:quota]
        chunks = store.get_chunks([h.chunk_id for h in best])
        for h in best:
            if h.chunk_id in chunks and h.chunk_id not in taken:
                taken.add(h.chunk_id)
                out.append(make_card(chunks[h.chunk_id], h.score, service.config))
    return out


_qvec = None
start = time.time()
first_record = llm.extract("oneshot" if FIXED_K else "oneshot_k", llm.oneshot_input(task["repo"], task["query"]))
cost = first_record.get("cost_usd") or 0.0
first = llm.clean(first_record["output"], task["query"])
k = FIXED_K or k_of(first_record["output"].get("k"))
cards, _ = searcher._retrieve(store, task["query"], first, False, k)
query = {key: first[key] for key in ("intent", "symptom", "anchors")} | {"look_in": []}
history = [{"round": 1, "query": query, "k": k}]
seen: set[int] = set()
seen_text, picks, calls, fixed, retry = "", [], C.Counter({"oneshot": 1}), None, False
for round_no in range(1, MAX_ROUNDS + 1):
    if retry:  # the last edit did not apply: show the same code again (pinned picks), no new results
        cards = []
    elif round_no > 1:
        fused = searcher._round_fused(store, query)
        fresh = _pick_top([item for item in fused if item[0] not in seen], k, store.get_chunks)
        cards = [make_card(chunk, score, service.config) for chunk, score in fresh]
    calls["codemem_rounds"] += 1
    if not cards and not retry:
        break
    if HOP and cards:
        added = hop_cards(cards, seen)
        history[-1]["hop_added"] = len(added)
        cards = cards + added
    shown, whole = show_full(cards) if cards else ("[no new results this round: your last edit did not apply; the code is shown again under picked_earlier]", [])
    picked_code = code_for(picks)
    seen.update(c.chunk_id for c in cards)
    history[-1].update(shown=[[c.path, c.start_line, c.end_line] for c in cards], shown_whole=whole,
                       picked_shown=[line[4:] for line in picked_code.split("\n") if line.startswith("=== ")])
    seen_text += "\n" + shown + "\n" + picked_code
    record = llm.extract("loopk", llm.loopk_input(task["repo"], task["query"], history, round_no, picked_code, shown))
    cost += record.get("cost_usd") or 0.0
    calls["loopk"] += 1
    o = record["output"]
    judged = llm.clean_loop(o | {"found": o["action"] == "edit", "guessed_location": []}, task["query"], seen_text, len(cards))
    picked = [cards[p - 1] for p in judged["picks"]]
    picks += [c.chunk_id for c in picked if c.chunk_id not in picks]
    history[-1].update(action=o["action"], analysis=judged["analysis"], picked=[f"{c.path}:{c.qualname}" for c in picked])
    if o["action"] == "edit" and o["edits"]:
        ok, why = apply(o["edits"])
        if ok:
            history[-1]["edit_attempt"] = "applied"
            fixed = {"round": round_no, "explanation": judged["analysis"], "edits": len(o["edits"])}
            break
        history[-1]["edit_attempt"] = f"did not apply: {why}"
        # show the code it tried to edit again: this round's results in the edited files join the picks
        paths = {e["path"].strip().replace("\\", "/").removeprefix("./") for e in o["edits"]}
        picks += [c.chunk_id for c in cards if c.path in paths and c.chunk_id not in picks]
    elif o["action"] == "edit":
        history[-1]["edit_attempt"] = "did not apply: no edits given"
    retry = history[-1].get("edit_attempt", "").startswith("did not apply") and not retry
    if cost > MAX_COST:
        break
    k = FIXED_K or k_of(o.get("next_k"))
    query = {key: judged[key] for key in ("intent", "symptom", "anchors", "look_in")}
    query["look_in"] = [p for p in (searcher._prefix(store, x) for x in query["look_in"]) if p]
    history.append({"round": round_no + 1, "query": query, "k": k})

service.close()
patch = subprocess.run(["git", "diff"], cwd=repo, capture_output=True, text=True, encoding="utf8").stdout
(out / f"{TAG}.diff").write_text(patch, encoding="utf8")
summary = {"arm": "codemem-loop-merged" if FIXED_K else "codemem-loop-k", "fixed_k": FIXED_K, "hop": os.environ.get("LOOP_HOP"), "judge_sees": "raw code", "task": task_id, "fixed": fixed, "rounds": len(history),
           "ks": [h["k"] for h in history if "shown" in h], "calls": dict(calls), "sonnet_calls": calls["oneshot"] + calls["loopk"],
           "cost_usd": round(cost, 4), "seconds": round(time.time() - start),
           "diff_stat": subprocess.run(["git", "diff", "--stat"], cwd=repo, capture_output=True, text=True).stdout.strip(),
           "history": history}
(out / f"{TAG}.summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf8")
print(json.dumps({k: v for k, v in summary.items() if k != "history"}, indent=1))
for h in history:
    print(f"round {h['round']}: k={h['k']} action={h.get('action')} picked={h.get('picked')} {h.get('edit_attempt', '')}")
