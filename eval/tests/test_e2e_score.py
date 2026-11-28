import json

import pytest

from cmeval import e2e_score
from cmeval.e2e_score import format_score, score
from cmeval.paths import e2e_dir

BLOCK = {"searches_made_for_agent": 1}


def _record(task_id, setup, rep=1, *, end="finished", completed=True, discard=False, tokens=1000, seconds=60.0,
            flags=(), steps=None, identity=None, integrity=None, cost=None, **extra):
    return {"task_id": task_id, "setup": setup, "rep": rep, "end": end, "completed": None if discard else completed,
            "discard": discard, "discard_reason": "usage limit" if discard else None, "flags": list(flags),
            "tokens": {"processed_tokens": tokens}, "time": {"agent_s": seconds}, "steps": steps or {"turns": 10},
            "identity": identity or {}, "integrity": integrity or {},
            "result_event": {"total_cost_usd": cost}, **extra}


def _write(run_id, record, files=None):
    out = e2e_dir() / "runs" / run_id / record["task_id"] / record["setup"] / str(record["rep"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps(record))
    for name, text in (files or {}).items():
        (out / name).write_text(text)
    return out


def _jsonl(lines):
    return "".join(json.dumps(line) + "\n" for line in lines)


# ---- rule 1: a run at the turn or time limit counts as not completed

def test_runs_at_a_limit_count_as_not_completed():
    _write("lim", _record("t1", "grep", 1))
    _write("lim", _record("t1", "grep", 2, end="turn limit", turn_limit={"at_turn": 150, "how": "docker exec kill"}))
    _write("lim", _record("t2", "grep", end="time limit", tokens=5000, seconds=3000.0))
    _write("lim", _record("t3", "grep", end="error", integrity={"host_timeout": True}))
    _write("lim", _record("t4", "grep", end="usage limit", discard=True))
    for task_id in ("t1", "t2", "t3"):
        _write("lim", _record(task_id, "other"))
    summary = score("lim")
    grep = summary["setups"]["grep"]
    # Every patch passed, but three runs ended at a limit. The discarded run is not one of them.
    assert (grep["runs"], grep["discarded"], grep["at_limit"], grep["completed_share"]) == (5, 1, 3, 0.25)
    # The runs at a limit stay in tokens and seconds.
    assert grep["tokens_mean"] == 2000 and grep["seconds_mean"] == pytest.approx(795.0)
    assert summary["setups"]["other"]["at_limit"] == 0
    # Paired: t1 1.0 - 0.5, t2 1.0 - 0.0, t3 1.0 - 0.0.
    assert summary["paired"][0]["completed"] == pytest.approx((0.5 + 1 + 1) / 3)
    text = format_score(summary)
    assert "at limit completed" in text
    assert any(line.split()[:6] == ["grep", "5", "1", "0", "3", "0.25"] for line in text.splitlines())


def test_completed_value_of_a_run_at_a_limit():
    assert e2e_score._value({"end": "time limit", "completed": True}, "completed") == 0.0
    assert e2e_score._value({"end": "finished", "turn_limit": {"at_turn": 150}, "completed": True}, "completed") == 0.0
    assert e2e_score._value({"end": "finished", "completed": True}, "completed") == 1.0
    assert e2e_score._value({"end": "finished", "turn_limit": None, "completed": None}, "completed") is None


# ---- rule 2: the cost from the price table, with the reported cost beside it

def _proxy(*usages, model="claude-sonnet-5-5"):
    return _jsonl([{"seq": i, "path": "/v1/messages", "status": 200, "model": model, "usage": u}
                   for i, u in enumerate(usages, 1)])


def test_cost_from_the_price_table_and_the_reported_cost():
    usage = {"input_tokens": 100_000, "output_tokens": 10_000, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 0}
    # Sonnet: 100,000 input tokens cost 0.20 USD, 10,000 output tokens cost 0.10 USD.
    _write("cost", _record("t1", "grep", cost=0.3), {"proxy.jsonl": _proxy(usage)})
    _write("cost", _record("t2", "grep", cost=0.5), {"proxy.jsonl": _proxy(usage, usage)})
    _write("cost", _record("t1", "other", cost=0.2), {"proxy.jsonl": _proxy({**usage, "output_tokens": 0})})
    # No proxy log: no cost, and the run is left out of the mean of the table cost only.
    _write("cost", _record("t2", "other", cost=0.4))
    summary = score("cost")
    grep, other = summary["setups"]["grep"], summary["setups"]["other"]
    assert grep["cost_mean"] == pytest.approx(0.45) and grep["reported_cost_mean"] == pytest.approx(0.4)
    assert other["cost_mean"] == pytest.approx(0.2) and other["reported_cost_mean"] == pytest.approx(0.3)
    # Paired over the tasks where both setups have a cost: only t1, 0.2 - 0.3.
    assert summary["paired"][0]["cost"] == pytest.approx(-0.1)
    text = format_score(summary)
    assert "cost $   rep. $" in text and "cost -0.1000" in text


# ---- rule 3: the "used" columns count the agent's own calls, not the block

STREAM = [
    {"type": "system", "subtype": "init"},
    {"type": "assistant", "message": {"id": "m1", "content": [{"type": "tool_use", "id": "c1", "name": "mcp__other__x",
                                                               "input": {}}]}},
    {"type": "assistant", "parent_tool_use_id": "task1",
     "message": {"id": "s1", "content": [{"type": "tool_use", "id": "c2", "name": "mcp__codemem__search_code",
                                          "input": {}}]}},
    {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "next"}]}},
    {"type": "assistant", "message": {"id": "m2", "content": [{"type": "tool_use", "id": "c3",
                                                               "name": "mcp__codemem__search_code", "input": {}}]}},
]


def test_codemem_numbers_leave_out_the_block():
    with_block = {"codemem": {"commit": "abc"}, "block": BLOCK}
    seen = {"block_in_first_message": True}
    # The agent made no codemem call: the block's search is the only one in the steps.
    _write("own", _record("t1", "codemem", identity=with_block, integrity=seen,
                          steps={"turns": 5, "codemem_calls": 1, "first_codemem_turn": 0, "first_mcp_turn": None,
                                 "tool_calls": {"Bash": 4}, "mcp_tools": {}}))
    # Two own calls; every MCP call was codemem's, so first_mcp_turn is the turn of the first own call.
    _write("own", _record("t2", "codemem", identity=with_block, integrity=seen,
                          steps={"turns": 8, "codemem_calls": 3, "first_codemem_turn": 0, "first_mcp_turn": 4,
                                 "tool_calls": {"mcp__codemem__search_code": 1, "mcp__codemem__get_symbol": 1},
                                 "mcp_tools": {"mcp__codemem__search_code": 1, "mcp__codemem__get_symbol": 1}}))
    # Another MCP tool came first: the turn comes from stream.jsonl (the subagent's call is not the agent's).
    other_tools = {"turns": 3, "codemem_calls": 2, "first_codemem_turn": 0, "first_mcp_turn": 1,
                   "tool_calls": {"mcp__other__x": 1, "mcp__codemem__search_code": 1},
                   "mcp_tools": {"mcp__other__x": 1, "mcp__codemem__search_code": 1}}
    _write("own", _record("t3", "codemem", identity=with_block, integrity=seen, steps=other_tools),
           {"stream.jsonl": _jsonl(STREAM)})
    # The same without stream.jsonl: the turn is not known.
    _write("own", _record("t4", "codemem", identity=with_block, integrity=seen, steps=other_tools))
    # A setup without a block keeps its steps as they are.
    _write("own", _record("t1", "tool", identity={"codemem": {"commit": "abc"}, "block": None},
                          integrity={"block_in_first_message": None},
                          steps={"turns": 5, "codemem_calls": 2, "first_codemem_turn": 3, "tool_calls": {},
                                 "mcp_tools": {"mcp__codemem__get_symbol": 2}}))
    summary = score("own")
    codemem, tool = summary["setups"]["codemem"]["behaviour"], summary["setups"]["tool"]["behaviour"]
    assert codemem["codemem_share"] == 0.75 and codemem["codemem_calls_mean"] == 1.0
    assert codemem["first_codemem_turn_mean"] == pytest.approx((4 + 2) / 2)
    assert codemem["codemem_search_share"] == 0.75 and codemem["block_share"] == 1.0
    assert (tool["codemem_share"], tool["codemem_calls_mean"], tool["first_codemem_turn_mean"]) == (1.0, 2.0, 3.0)
    assert tool["codemem_search_share"] == 0.0 and tool["block_share"] == 0.0
    text = format_score(summary)
    assert "block  used  codemem 1st call" in text
    assert next(line for line in text.splitlines() if line.startswith("  codemem ") and "0.75" in line).endswith(
        "1.00  0.75      1.0      3.0")


def test_first_codemem_turn_in_stream():
    assert e2e_score.first_codemem_turn_in_stream(STREAM) == 2
    assert e2e_score.first_codemem_turn_in_stream(STREAM[:3]) is None


# ---- rule 4: a run without its block is left out, as a discarded run is

def test_a_run_without_its_block_is_discarded():
    with_block = {"codemem": {"commit": "abc"}, "block": BLOCK}
    for task_id in ("t1", "t2"):
        _write("nob", _record(task_id, "grep", tokens=1000))
    _write("nob", _record("t1", "codemem", tokens=800, identity=with_block,
                          integrity={"block_in_first_message": True}))
    _write("nob", _record("t2", "codemem", tokens=10**6, completed=False, identity=with_block,
                          integrity={"block_in_first_message": False}, flags=["block not in the first message"]))
    # No model request: the run cannot say. It keeps its flag and is not discarded.
    _write("nob", _record("t3", "codemem", identity=with_block, integrity={"block_in_first_message": None},
                          flags=["block not checked: no model request in the proxy log"]))
    # A record made before the block existed is not affected.
    _write("nob", _record("t4", "codemem", tokens=600, identity={"codemem": {"commit": "abc"}}, integrity={}))
    summary = score("nob")
    codemem = summary["setups"]["codemem"]
    assert (codemem["runs"], codemem["discarded"], codemem["no_block"], codemem["flagged"]) == (4, 1, 1, 1)
    assert codemem["tokens_mean"] == 700 and codemem["completed_share"] == 1.0
    assert summary["paired"][0]["tasks"] == 1 and summary["paired"][0]["tokens"] == -200
    assert e2e_score.discard_reason(_record("t2", "codemem", identity=with_block,
                                            integrity={"block_in_first_message": False})) == "no block"
    assert e2e_score.discard_reason(_record("t2", "codemem", discard=True, identity=with_block,
                                            integrity={"block_in_first_message": False})) == "usage limit"
    assert "ends: finished 4; 1 discarded without their block" in format_score(summary)
    # run.json is not changed.
    path = e2e_dir() / "runs" / "nob" / "t2" / "codemem" / "1" / "run.json"
    assert json.loads(path.read_text())["discard"] is False
