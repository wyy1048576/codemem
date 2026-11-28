"""Score item 1 (run_item1.py): out/item1/<level>/<task>/<arm>-<model>-r<rep>.*

Per run: cost, seconds, turns, tokens by kind (new input, cache write, cache read, output; the answering model
apart from Claude Code's side calls), tool calls, codemem calls (search_code, get_chunk) and their turns, the
checks of Andre's 13:15 entry, and what of the fix was found:
  file in results / function in results: a gold file / gold function among the search_code results (head lines
      `N. path:a-b  name  [id N]`), with the best place; a function matches when its lines overlap the result's
  function seen: at least half its lines reached the model as code by Read or Grep (e2e_score.grep_seen; codemem
      previews not counted)
  file edited / function edited: the final diff touches the file / a line inside the function
Usage: python score_item1.py
"""
from __future__ import annotations

import collections as C
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "item1"
NL = chr(10)
src = (HERE / "e2e_score.py").read_text(encoding="utf8")
exec(src[src.index("def add_range"):src.index("import sys\nCOMMON")])  # add_range, rel, diff_lines, grep_seen, found
Span = C.namedtuple("Span", "path start end symbol")
HEAD = re.compile(r"^\s*(\d+)\.\s+(\S+?):(\d+)-(\d+)\s", re.M)
LOADING = re.compile(r"still loading|cannot embed|keywords only|loading the embedding model", re.I)

tasks = {}
for s in ("e2e-vague8", "e2e-b7"):
    for lv in ("L1", "L2"):
        for x in (HERE / "out" / s / f"tasks-{lv}.jsonl").read_text(encoding="utf8").splitlines():
            if x.strip():
                t = json.loads(x)
                tasks[(lv, t["id"])] = t


def _ts(s: str):
    import datetime
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return NL.join(c.get("text", "") for c in content or [] if isinstance(c, dict))


def codemem_calls(log: Path) -> list[dict]:
    """Every codemem tool call: its turn (assistant message number), name, input and result text."""
    events = [json.loads(x) for x in log.read_text(encoding="utf8").splitlines() if x.strip().startswith("{")]
    calls, by_id, turn = [], {}, 0
    for e in events:
        if e.get("type") == "assistant":
            turn += 1
            for c in e["message"].get("content", []):
                if c.get("type") == "tool_use":
                    rec = {"turn": turn, "name": c["name"], "input": c.get("input"), "result": None, "t0": e.get("timestamp"), "secs": None}
                    by_id[c["id"]] = rec
                    calls.append(rec)
        elif e.get("type") == "user":
            for c in (e.get("message") or {}).get("content", []) if isinstance((e.get("message") or {}).get("content"), list) else []:
                if c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                    rec = by_id[c["tool_use_id"]]
                    rec["result"] = text_of(c.get("content"))
                    if rec["t0"] and e.get("timestamp"):
                        rec["secs"] = (_ts(e["timestamp"]) - _ts(rec["t0"])).total_seconds()
    for i, rec in enumerate(calls):
        rec["next"] = calls[i + 1]["name"] if i + 1 < len(calls) else None
    return calls


rows = []
for sf in sorted(OUT.glob("*/*/*.summary.json")):
    s = json.loads(sf.read_text(encoding="utf8"))
    level, tid, name = sf.parent.parent.name, sf.parent.name, sf.name.removesuffix(".summary.json")
    task = tasks[(level, tid)]
    gold = [Span(g["path"], g["start"], g["end"], g.get("symbol")) for g in task["gold"].get("functions", [])]
    gfiles = set(task["gold"].get("files", []))
    log = sf.parent / f"{name}.jsonl"
    calls = codemem_calls(log)
    cm = [c for c in calls if c["name"].startswith("mcp__codemem__")]
    searches = [c for c in cm if c["name"].endswith("search_code")]
    file_place, fn_place, loading, not_code = None, None, 0, 0
    found_fns = set()
    for c in searches:
        r = c["result"] or ""
        if LOADING.search(r):
            loading += 1
        heads = HEAD.findall(r)
        if not heads or r.lstrip().startswith("{"):
            not_code += 1
        for place, path, a, b in heads:
            place, a, b = int(place), int(a), int(b)
            if path in gfiles and file_place is None:
                file_place = place
            for j, g in enumerate(gold):
                if g.path == path and a <= g.end and g.start <= b:
                    found_fns.add(j)
                    fn_place = place if fn_place is None else min(fn_place, place)
    seen = grep_seen(log)
    edited = diff_lines((sf.parent / f"{name}.diff").read_text(encoding="utf8"))
    hits = [found(g, seen, edited) for g in gold]
    files_edited = {p for p, lines in edited.items() if lines}  # diff_lines: path -> base lines touched
    mu = s.get("model_usage") or {}
    main = s["model"]
    u = next((v for k, v in mu.items() if k.startswith(main)), {})
    side = {k: round(v.get("costUSD", 0), 4) for k, v in mu.items() if not k.startswith(main)}
    rows.append({
        "level": level, "task": tid, "arm": s["arm"], "model": main.replace("claude-", ""), "rep": s["rep"],
        "cost": s.get("cost_usd") or 0, "seconds": s["seconds"], "turns": s.get("turns"),
        # the first search waits for the embedding model to load (track A's runner does that before the clock)
        "first_search_secs": round(searches[0]["secs"], 1) if searches and searches[0]["secs"] is not None else None,
        "seconds_warm": round(s["seconds"] - max(0.0, (searches[0]["secs"] or 0) - 1.0)) if searches else s["seconds"],
        "input_new": u.get("inputTokens", 0), "cache_write": u.get("cacheCreationInputTokens", 0),
        "cache_read": u.get("cacheReadInputTokens", 0), "output": u.get("outputTokens", 0), "side_models": side,
        "search_code": len(searches), "get_chunk": sum(c["name"].endswith("get_chunk") for c in cm),
        "other_codemem": len(cm) - len(searches) - sum(c["name"].endswith("get_chunk") for c in cm),
        "first_search_turn": searches[0]["turn"] if searches else None, "after_search": [c["next"] for c in searches],
        "search_chars": sum(len(c["result"] or "") for c in searches), "loading_note": loading, "not_code": not_code,
        "gold_files": len(gfiles), "gold_fns": len(gold),
        "file_in_results_place": file_place, "fn_in_results": len(found_fns), "fn_in_results_place": fn_place,
        "fn_seen": sum(a for a, _ in hits), "fn_edited": sum(b for _, b in hits), "task_fn_edited": any(b for _, b in hits),
        "file_edited": bool(gfiles & files_edited),
        "changed": bool((sf.parent / f"{name}.diff").read_text(encoding="utf8").strip()),
        "subtype": s.get("subtype"), "cc_version": s.get("claude_code_version"),
        "mcp_status": [m.get("status") for m in s.get("mcp_servers") or []],
        "catchup_seconds": s.get("catchup_seconds"), "catchup_exit": s.get("catchup_exit"),
    })
(OUT / "score.json").write_text(json.dumps(rows, indent=1), encoding="utf8")

print("level model arm runs | cost seconds turns | new-in cache-write cache-read output | searches get_chunk | "
      "loading-notes not-code | gold fns edited / tasks with a gold fn edited / tasks with a gold file edited / changed")
for lv in ("L1", "L2"):
    for model in sorted({r["model"] for r in rows}):
        for arm in ("grep", "tool", "detailed", "pr85"):
            rs = [r for r in rows if r["level"] == lv and r["model"] == model and r["arm"] == arm]
            if not rs:
                continue
            S = lambda k: sum(r[k] or 0 for r in rs)  # noqa: E731
            print(f"{lv} {model:10} {arm:8} {len(rs):2} | ${S('cost'):.3f} {S('seconds'):5} (warm {S('seconds_warm'):5}) {S('turns'):4} | "
                  f"{S('input_new'):7} {S('cache_write'):8} {S('cache_read'):9} {S('output'):6} | {S('search_code'):3} {S('get_chunk'):3} | "
                  f"{S('loading_note')} {S('not_code')} | {S('fn_edited')}/{S('gold_fns')} {S('task_fn_edited')} {S('file_edited')} {S('changed')}")


def pairs(arm: str, base: str = "grep", model: str = "haiku-5-5") -> None:
    """Pairs by task and level: the arm lower / equal / higher than the base, per measure."""
    by = {(r["level"], r["task"], r["arm"]): r for r in rows if r["model"] == model and r["rep"] == 1}
    keys = sorted({(lv, t) for lv, t, a in by if a == arm and (lv, t, base) in by})
    print(f"\n{arm} against {base}, {model}, {len(keys)} pairs: lower / equal / higher")
    for m in ("cost", "turns", "seconds_warm", "input_new", "cache_write", "cache_read", "output", "fn_edited", "fn_seen"):
        lo = sum(by[(*k, arm)][m] < by[(*k, base)][m] for k in keys)
        eq = sum(by[(*k, arm)][m] == by[(*k, base)][m] for k in keys)
        print(f"  {m:13} {lo:2} / {eq:2} / {len(keys) - lo - eq:2}")


def checks(model: str = "haiku-5-5") -> None:
    cm = [r for r in rows if r["model"] == model and r["arm"] != "grep"]
    print(f"\nchecks, {len(cm)} codemem runs: mcp connected {sum(r['mcp_status'] == ['connected'] for r in cm)}; "
          f"index update ok {sum(r['catchup_exit'] == 0 for r in cm)}; searches {sum(r['search_code'] for r in cm)} in "
          f"{sum(r['search_code'] > 0 for r in cm)} runs; with a loading note {sum(r['loading_note'] for r in cm)}; "
          f"not code {sum(r['not_code'] for r in cm)}; side models {sorted({k for r in rows for k in r['side_models']})}")
    for arm in ("tool", "detailed"):
        rs = [r for r in cm if r["arm"] == arm]
        if not rs:
            continue
        s = [r for r in rs if r["search_code"]]
        print(f"  {arm}: searched in {len(s)} of {len(rs)} runs; first search at turn {sorted(r['first_search_turn'] for r in s)}; "
              f"gold file in results {sum(r['file_in_results_place'] is not None for r in s)}, at place {sorted(r['file_in_results_place'] for r in s if r['file_in_results_place'])}; "
              f"gold fn in results {sum(r['fn_in_results'] > 0 for r in s)}; next step after a search {dict(C.Counter(x for r in s for x in r['after_search']))}")


for a in ("tool", "detailed"):
    pairs(a)
pairs("detailed", "tool")
checks()
