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
import re
import subprocess
import sys
import time
from pathlib import Path

from codemem.config import load_config
from codemem.render import format_results
from codemem.search import SearchResponse, _pick_top, make_card
from codemem.service import CodememService

import llm
from aug_retriever import LOOP_SHOWN, AugRetriever

MAX_ROUNDS = 10
MAX_COST = 3.0
MAX_FIX_CHUNKS = 8
MAX_CODE_CHARS = 60000
SHOWN = int(os.environ.get("LOOP_N", LOOP_SHOWN))  # results shown per round (default 50)
# LOOP_CHOOSE_K=1 (with LOOP_FULL): Sonnet picks how many results each round shows, from 1, 2, 3, 5, 10: the first query
# comes from the same call as loop-k (oneshot_k) and the judge returns next_k (system_loop_k.txt). Judge and fix stay
# separate calls; after a fix that fails, the next round uses the judge's next_k.
CHOOSE_K = os.environ.get("LOOP_CHOOSE_K") == "1"
KS = (1, 2, 3, 5, 10)
TAG = os.environ.get("LOOP_TAG", "loop")  # output file prefix
# LOOP_FULL=1: the judge sees each result's raw code from the index (header line + chunk source), not a
# 500-character preview. A chunk longer than CODE_CAP characters is cut; a class that long is shown as its
# skeleton (class line, attributes, method signatures), since its methods are results of their own.
FULL = os.environ.get("LOOP_FULL") == "1"
CODE_CAP = 20000
ROUND_CAP = 200000  # characters of code per round; past it, the remaining results get 500-character previews
# LOOP_CONDENSE_TESTS=1 (with LOOP_FULL): a result the index flags as a test is shown in about 500 characters
# instead of whole, unless the issue mentions tests. The index and the search itself are unchanged.
TEST_CAP = 500
TEST_MAX_CALLEES = 5  # "tests:" line only when the test calls at most this many non-test chunks

tasks_file, task_id, repo_arg, out_dir = sys.argv[1:5]
task = next(t for t in (json.loads(x) for x in Path(tasks_file).read_text(encoding="utf8").split("\n") if x.strip())
            if t["id"] == task_id)
CONDENSE_TESTS = os.environ.get("LOOP_CONDENSE_TESTS") == "1" and not re.search(r"\btests?\b", task["query"], re.I)
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


def condensed_test(chunk, head: str, words: list[str]) -> str:
    """A test result in a few lines: the header, what it tests (when the call edges say so clearly), and up to 3 code
    lines that contain a query word, with their line numbers. About 500 characters."""
    lines = [head, "[test, condensed: the fix step sees it whole if you pick it]"]
    callees = [c for c in store.callees_of(chunk.chunk_id) if not c.is_test]
    if 0 < len(callees) <= TEST_MAX_CALLEES:
        lines.append("tests: " + ", ".join(dict.fromkeys(c.qualname for c in callees)))
    low = [w.lower() for w in words if w]
    hits = [f"L{chunk.start_line + n}: {line.strip()[:120]}" for n, line in enumerate(chunk.code.split("\n"))
            if any(w in line.lower() for w in low)]
    lines += hits[:3]
    return "\n".join(lines)[:TEST_CAP]


def show_full(cards, words: list[str] | None = None) -> tuple[str, list[bool]]:
    """Numbered results with each chunk's raw code from the index; also, per result, whether it was shown whole.
    With CONDENSE_TESTS, a test chunk is shown condensed (condensed_test) and counts as not shown whole."""
    chunks = store.get_chunks([c.chunk_id for c in cards])
    parts, whole, total = [], [], 0
    for i, card in enumerate(cards, start=1):
        text = format_results(SearchResponse("", ["llm"], [card]))
        text = f"{i}." + text[2:] if text.startswith("1.") else text
        head = text.split("\n", 1)[0]
        chunk = chunks.get(card.chunk_id)
        if CONDENSE_TESTS and chunk is not None and chunk.is_test:
            parts.append(condensed_test(chunk, head, words or []))
            whole.append(False)
            continue
        if total > ROUND_CAP:
            parts.append(text[:500])
            whole.append(False)
            continue
        code = chunk.code if chunk else ""
        ok = len(code) <= CODE_CAP
        if not ok:
            if chunk.kind == "class" and chunk.skeleton:
                code = "[class too long to show whole: its skeleton; its methods are results of their own]\n" + chunk.skeleton[:CODE_CAP]
            else:
                code = code[:CODE_CAP] + f"\n[... cut at {CODE_CAP} characters]"
        parts.append(head + "\n" + code)
        whole.append(ok)
        total += len(code)
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


def verbatim(values, source: str) -> list[str]:
    return [v for v in dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip()) if v in source][:llm.MAX_ANCHORS]


start = time.time()
first_record = llm.extract("oneshot_k" if CHOOSE_K else "oneshot", llm.oneshot_input(task["repo"], task["query"]))
k = (first_record["output"].get("k") if first_record["output"].get("k") in KS else 10) if CHOOSE_K else SHOWN
ks = []
oneshot_cost = first_record.get("cost_usd") or 0.0  # the query-writing call; counted in cost_usd
first = llm.clean(first_record["output"], task["query"])
cards, _ = searcher._retrieve(store, task["query"], first, False, k)
query = {key: first[key] for key in ("intent", "symptom", "anchors")} | {"look_in": []}
history = [{"round": 1, "query": query}]
seen: set[int] = set()
seen_text, picks, cost, calls, fixed = "", [], oneshot_cost, C.Counter(), None
for round_no in range(1, MAX_ROUNDS + 1):
    if round_no > 1:
        fused = searcher._round_fused(store, query)
        fresh = _pick_top([item for item in fused if item[0] not in seen], k, store.get_chunks)
        cards = [make_card(chunk, score, service.config) for chunk, score in fresh]
    calls["codemem_rounds"] += 1
    if not cards:
        break
    if FULL:
        shown, whole = show_full(cards, query.get("anchors") or [w for w in re.findall(r"[A-Za-z_][\w.-]{3,}", task["query"])])
        history[-1]["shown_whole"] = whole
    else:
        shown = searcher._show(cards)
    seen.update(c.chunk_id for c in cards)
    history[-1]["shown"] = [[c.path, c.start_line, c.end_line] for c in cards]
    seen_text += "\n" + shown
    ks.append(k)
    record = llm.extract(("loop_full_k" if CHOOSE_K else "loop_full") if FULL else "loop", llm.loop_input(task["repo"], task["query"], history, round_no, shown))
    cost += record.get("cost_usd") or 0.0
    calls["judge"] += 1
    judged = llm.clean_loop(record["output"], task["query"], seen_text, len(cards))
    picked = [cards[p - 1] for p in judged["picks"]]
    round_picks = [c.chunk_id for c in picked]
    picks += [c for c in round_picks if c not in picks]
    history[-1].update(analysis=judged["analysis"], picked=[f"{c.path}:{c.qualname}" for c in picked], found=judged["found"])
    nxt = {key: judged[key] for key in ("intent", "symptom", "anchors", "look_in")}
    if CHOOSE_K:
        k = record["output"].get("next_k") if record["output"].get("next_k") in KS else 10
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
summary = {"arm": "codemem-loop", "shown_per_round": "chosen" if CHOOSE_K else SHOWN, "ks": ks, "judge_sees": "raw code" if FULL else "500-character previews",
           "oneshot_cost_usd": round(oneshot_cost, 4), "task": task_id, "fixed": fixed, "rounds": len(history), "calls": dict(calls),
           "sonnet_calls": calls["judge"] + calls["fix"], "cost_usd": round(cost, 4), "seconds": round(time.time() - start),
           "diff_stat": subprocess.run(["git", "diff", "--stat"], cwd=repo, capture_output=True, text=True).stdout.strip(),
           "history": history}
(out / f"{TAG}.summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf8")
print(json.dumps({k: v for k, v in summary.items() if k != "history"}, indent=1))
for h in history:
    print(f"round {h['round']}: found={h.get('found')} picked={h.get('picked')}\n  fix: {h.get('fix_attempt', '-')[:400]}")
