"""The replay of first codemem searches (e2e_replay): the query extraction, the result text, the gold matching,
the cost from the records, and the tables. No codemem program runs here; test_e2e_replay_mcp.py starts a fake
MCP server."""

import json
from collections import Counter

from cmeval import e2e_replay as rp
from cmeval.tasks import Span

RESULT_TEXT = """\
1. pandas/tests/indexing/test_loc.py:3425-3437  test_loc_setitem_int  [id 26651]
   def test_loc_setitem_int():
   |     df = pd.DataFrame({"a": [1, 2]})
2. pandas/core/indexing.py:1200-1260  _LocIndexer._getitem_tuple  [id 900]  best 1210-1230
   def _getitem_tuple(self, tup):
   |     return self._getitem_lowerdim(tup)
3. pandas/core/indexing.py:2000-2010  <imports>  [id 901]
   |     import numpy as np

Note: the embedding model is still loading (the first search after codemem starts); these results come from \
keyword matching only. Search again in a few seconds for results by meaning.

Lost the trail later? Search again in different words."""


def _wire(text: str) -> str:
    return json.dumps({"result": text}, ensure_ascii=False, separators=(",", ":"))


def _assistant(msg_id: str, blocks: list[dict], parent: str | None = None) -> dict:
    return {"type": "assistant", "message": {"id": msg_id, "role": "assistant", "content": blocks},
            "parent_tool_use_id": parent}


def _use(call_id: str, name: str, args: dict) -> dict:
    return {"type": "tool_use", "id": call_id, "name": name, "input": args}


def _result(call_id: str, text: str, parent: str | None = None) -> dict:
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": call_id, "content": text}]}, "parent_tool_use_id": parent}


def _stream(text: str = RESULT_TEXT) -> list[dict]:
    """Turn 1: a Bash call. A subagent searches with codemem (not the main agent). Turn 2: the main agent's
    first search_code call, written as two events of one message with a second tool call. Turns 3 and 4 after."""
    return [
        {"type": "system", "subtype": "init"},
        _assistant("m1", [_use("b1", "Bash", {"command": "ls"})]),
        _result("b1", "pandas\n"),
        _assistant("s1", [_use("sub1", rp.SEARCH_TOOL, {"query": "subagent query"})], parent="task1"),
        _result("sub1", _wire("1. a.py:1-2  f  [id 1]"), parent="task1"),
        _assistant("m2", [_use("c1", rp.SEARCH_TOOL, {"query": "loc row and list of columns", "k": 10,
                                                      "path_prefix": "pandas/core"})]),
        _assistant("m2", [_use("b2", "Bash", {"command": "pwd"})]),
        _result("c1", _wire(text)),
        _result("b2", "/testbed\n"),
        _assistant("m3", [_use("c2", rp.SEARCH_TOOL, {"query": "second search"})]),
        _result("c2", _wire("No results for 'second search'.")),
        _assistant("m4", [{"type": "text", "text": "done"}]),
        {"type": "result", "num_turns": 4},
    ]


def _usage(inp: int, write: int, read: int, out: int) -> dict:
    return {"input_tokens": inp, "cache_creation_input_tokens": write, "cache_read_input_tokens": read,
            "output_tokens": out}


def _proxy() -> list[dict]:
    return [
        {"seq": 1, "method": "HEAD", "path": "/api/hello", "status": 200},
        {"seq": 2, "path": "/v1/messages", "status": 200, "message_id": "m1", "usage": _usage(2, 1000, 9000, 50)},
        {"seq": 3, "path": "/v1/messages", "status": 200, "message_id": "m2", "usage": _usage(2, 100, 10000, 80)},
        {"seq": 4, "path": "/v1/messages", "status": 200, "message_id": "s1", "usage": _usage(5, 500, 0, 10)},
        {"seq": 5, "path": "/v1/messages", "status": 200, "message_id": "m3", "usage": _usage(2, 2000, 10100, 40)},
        {"seq": 6, "path": "/v1/messages", "status": 200, "message_id": "m4", "usage": _usage(2, 100, 12100, 20)},
        {"seq": 7, "path": "/v1/messages", "status": 200, "message_id": "title", "usage": _usage(50, 0, 0, 5)},
    ]


# ---- the first search

def test_first_search_is_the_main_agents_first_call():
    found = rp.first_search(_stream())
    assert found["call_id"] == "c1"
    assert found["message_id"] == "m2"
    assert found["turn"] == 2
    assert found["args"] == {"query": "loc row and list of columns", "k": 10, "path_prefix": "pandas/core"}
    assert found["tool_calls_in_turn"] == 2
    assert found["result"] == _wire(RESULT_TEXT)
    assert found["is_error"] is False


def test_no_search_gives_none():
    events = [e for e in _stream() if not (e["type"] == "assistant" and e["message"]["id"] in ("m2", "m3"))]
    assert rp.first_search(events) is None


def test_result_as_a_list_of_text_blocks():
    events = _stream()
    events[7] = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "c1", "content": [{"type": "text", "text": RESULT_TEXT}]}]}}
    assert rp.first_search(events)["result"] == RESULT_TEXT


def test_run_k_reads_k_like_the_tool():
    assert rp.run_k({}) == 10
    assert rp.run_k({"k": "20"}) == 20
    assert rp.run_k({"k": 500}) == 50
    assert rp.run_k({"k": 0}) == 1
    assert rp.run_k({"k": "many"}) == 10


# ---- the result text

def test_unwrap_the_json_form_and_keep_plain_text():
    assert rp.unwrap(_wire(RESULT_TEXT)) == RESULT_TEXT
    assert rp.unwrap(RESULT_TEXT) == RESULT_TEXT
    assert rp.unwrap('{"result": "x", "other": 1}') == '{"result": "x", "other": 1}'
    assert rp.unwrap("[1, 2]") == "[1, 2]"


def test_parse_results_reads_each_head_line():
    results = rp.parse_results(RESULT_TEXT)
    assert [(r["rank"], r["path"], r["start"], r["end"], r["chunk_id"]) for r in results] == [
        (1, "pandas/tests/indexing/test_loc.py", 3425, 3437, 26651),
        (2, "pandas/core/indexing.py", 1200, 1260, 900),
        (3, "pandas/core/indexing.py", 2000, 2010, 901),
    ]
    assert results[1]["name"] == "_LocIndexer._getitem_tuple"
    assert results[2]["name"] == "<imports>"
    assert rp.parse_results("No results for 'x'.") == []


def test_notes():
    assert rp.notes_of(RESULT_TEXT) == {"keywords_only": True, "indexing": False, "not_fresh": False}
    assert rp.full_search(rp.notes_of("1. a.py:1-2  f  [id 1]"))
    building = "Note: the codemem index is still being built (40% done); results may be incomplete."
    assert rp.notes_of(building)["indexing"]


# ---- gold matching

def _gold(files, functions=(), excluded=None):
    return {"files": list(files), "functions": list(functions), "function_excluded": excluded}


def test_score_file_and_function_hits():
    results = rp.parse_results(RESULT_TEXT)
    gold = _gold(["pandas/core/indexing.py"], [Span("pandas/core/indexing.py", 1190, 1270, "f")])
    assert rp.score_results(results, gold) == {
        "gold_file_hit": True, "all_gold_files_hit": True, "gold_files_found": 1, "gold_function_hit": True,
        "gold_functions_found": 1, "first_gold_rank": 2}


def test_score_function_by_iou_and_miss():
    results = [{"rank": 1, "path": "a.py", "start": 10, "end": 30, "name": "f", "chunk_id": 1}]
    # 10-30 against 15-30: IoU 16/21 = 0.76
    assert rp.score_results(results, _gold(["a.py"], [Span("a.py", 15, 30)]))["gold_function_hit"] is True
    # 10-30 against 25-60: IoU 6/51
    assert rp.score_results(results, _gold(["a.py"], [Span("a.py", 25, 60)]))["gold_function_hit"] is False
    assert rp.score_results(results, _gold(["a.py"], [Span("a.py", 25, 60)]), iou=0.1)["gold_function_hit"]


def test_score_every_gold_file_and_no_function_gold():
    results = [{"rank": 1, "path": "b.py", "start": 1, "end": 2, "name": "g", "chunk_id": 2},
               {"rank": 2, "path": "a.py", "start": 1, "end": 2, "name": "f", "chunk_id": 1}]
    score = rp.score_results(results, _gold(["a.py", "c.py"], excluded="no gold at this level"))
    assert score["gold_file_hit"] and not score["all_gold_files_hit"]
    assert score["gold_files_found"] == 1 and score["first_gold_rank"] == 2
    assert score["gold_function_hit"] is None and score["gold_functions_found"] is None
    assert rp.score_results([], _gold(["a.py"]))["first_gold_rank"] is None


def test_gold_of_task(make_task):
    task = make_task()
    gold = rp.gold_of(task)
    assert gold["files"] == task.gold.files
    assert gold["function_excluded"] is None and gold["functions"] == task.gold.functions
    task.tags["partial_labels"] = True
    assert rp.gold_of(task) == {"files": task.gold.files, "functions": [], "function_excluded": "partial labels"}


def test_compare_lists():
    a = rp.parse_results(RESULT_TEXT)
    assert rp.compare_lists(a, a) == {"same": True, "shared": 3, "of": 3}
    assert rp.compare_lists(a, a[::-1]) == {"same": False, "shared": 3, "of": 3}
    assert rp.compare_lists(a, a[:1]) == {"same": False, "shared": 1, "of": 3}


# ---- part 2

def test_run_costs_from_stream_and_proxy():
    events = _stream()
    search = rp.first_search(events)
    costs = rp.run_costs(events, _proxy(), search)
    assert costs["result_chars"] == len(_wire(RESULT_TEXT))
    assert costs["result_text_chars"] == len(RESULT_TEXT)
    assert (costs["search_turn"], costs["turns"], costs["turns_after"]) == (2, 4, 2)
    # Next request m3 has 12102 input tokens; m2 had 10102 and wrote 80. The subagent and title requests are out.
    # The growth is split between the search result and the Bash result ("/testbed\n") by characters.
    growth, wire = 12102 - 10102 - 80, len(_wire(RESULT_TEXT))
    assert search["turn_result_chars"] == wire + len("/testbed\n")
    assert costs["result_tokens_estimate"] == round(growth * wire / (wire + 9))
    assert "split by" in costs["result_tokens_method"]
    assert costs["later_requests"] == 2
    assert costs["cache_read_share_mean"] == round((10100 / 12102 + 12100 / 12202) / 2, 4)
    assert costs["cache_read_share_pooled"] == round(22200 / 24304, 4)
    assert costs["resent_tokens_estimate"] == costs["result_tokens_estimate"] * 2


def test_run_costs_one_call_and_missing_proxy():
    events = [e for e in _stream() if not (e["type"] == "assistant" and e["message"]["content"][0].get("id") == "b2")]
    search = rp.first_search(events)
    assert search["tool_calls_in_turn"] == 1
    costs = rp.run_costs(events, _proxy(), search)
    assert costs["result_tokens_estimate"] == 12102 - 10102 - 80
    assert costs["result_tokens_method"] == "input growth"
    assert rp.run_costs(events, None, search)["proxy_note"] == "no proxy log"
    missing = [r for r in _proxy() if r.get("message_id") != "m2"]
    assert "not in the proxy log" in rp.run_costs(events, missing, search)["proxy_note"]


# ---- the entry and the tables

def _record(level: str, recipe: str = "pandas", task_id: str = "acme__demo-1") -> dict:
    return {"run_id": f"r-{level}", "task_id": task_id, "recipe": recipe, "repo": "acme/demo", "setup": "tool",
            "rep": 1, "completed": True,
            "identity": {"prompt_level": level, "gold_files": ["auth/sessions.py"],
                         "codemem": {"commit": "abc", "steering": "default",
                                     "index": {"codemem_commit": "abc", "base_commit": "b" * 40}}}}


def _entry(task, level: str, recipe: str, ranks: dict[int, int | None], text: str = RESULT_TEXT) -> dict:
    events = _stream(text)
    search = rp.first_search(events)
    entry = rp.run_entry(_record(level, recipe), events, _proxy(), search, task)
    by_k = {}
    for k, rank in ranks.items():
        results = [{"rank": 1, "path": "x.py", "start": 1, "end": 2, "name": "x", "chunk_id": 1}]
        if rank is not None:
            results.append({"rank": rank, "path": "auth/sessions.py", "start": 33, "end": 35,
                            "name": "SessionManager.revoke_session", "chunk_id": 2})
        by_k[str(k)] = {"results": results, "score": rp.score_results(results, rp.gold_of(task)),
                        "text_chars": 100 * k, "wire_chars": 110 * k}
    entry["replay"] = {"by_k": by_k}
    entry["check"] = {"verdict": "same"}
    return entry


def test_run_entry_fields(make_task):
    entry = _entry(make_task(), "L1", "pandas", {})
    assert entry["level"] == "L1" and entry["repo"] == "pandas" and entry["steering"] == "default"
    assert entry["call"]["k"] == 10 and entry["call"]["args"]["path_prefix"] == "pandas/core"
    assert entry["in_run"]["notes"]["keywords_only"] is True
    assert len(entry["in_run"]["results"]) == 3
    assert entry["in_run"]["score"]["gold_file_hit"] is False  # the task's gold is auth/sessions.py
    assert entry["gold"]["functions"][0]["symbol"] == "SessionManager.revoke_session"


def test_run_entry_without_task_uses_the_record():
    events = _stream()
    entry = rp.run_entry(_record("L0"), events, None, rp.first_search(events), None)
    assert entry["gold"]["files"] == ["auth/sessions.py"]
    assert entry["gold"]["function_excluded"] == "task not in the task files"
    assert entry["in_run"]["score"]["gold_function_hit"] is None


def test_replay_tables(make_task):
    task = make_task()
    entries = [_entry(task, "L0", "pandas", {5: None, 10: 7}), _entry(task, "L1", "pandas", {5: 2, 10: 2}),
               _entry(task, "L0", "playwright", {5: None, 10: None})]
    text = rp.replay_tables(entries, [5, 10])
    lines = text.splitlines()
    assert "**A gold file is among the results**" in lines
    assert "| group | runs | in the run | k=5 | k=10 |" in lines
    assert "| all | 3 | 0/3 (0%) | 1/3 (33%) | 2/3 (67%) |" in lines
    assert "| pandas | 2 | 0/2 (0%) | 1/2 (50%) | 2/2 (100%) |" in lines
    assert "| L0 | 2 | 0/2 (0%) | 0/2 (0%) | 1/2 (50%) |" in lines
    assert "| playwright L0 | 1 | 0/1 (0%) | 0/1 (0%) | 0/1 (0%) |" in lines
    assert any(line.startswith("| all | 3 | ") and line.endswith("| 500 | 1,000 |") for line in lines)
    # rank ranges at the largest k: rank 7 (6-10), rank 2 (2-5), not found
    assert "| all | 3 | 0 | 1 | 1 | 0 | 0 | 0 | 1 |" in lines


def test_replay_tables_leave_out_failed_replays(make_task):
    entry = _entry(make_task(), "L0", "pandas", {5: 1})
    entry["replay"] = {"error": "server did not start"}
    assert rp.replay_tables([entry], [5]) == "No run was replayed.\n"


def test_cost_table_and_check_summary(make_task):
    task = make_task()
    entries = [_entry(task, "L0", "pandas", {}), _entry(task, "L1", "pandas", {})]
    text = rp.cost_table(entries)
    row = next(line for line in text.splitlines() if line.startswith("| all |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[:3] == ["all", "2", f"{len(_wire(RESULT_TEXT)):,}"]
    assert cells[5] == "2.0"  # turns after
    summary = rp.check_summary(entries, Counter({"no search_code call": 3}))
    assert "Left out, no search_code call: 3." in summary
    assert "keywords only (model loading): 2" in summary
    assert "same 2" in summary
