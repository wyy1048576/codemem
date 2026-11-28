"""The block of codemem results at the top of the first message (the setups codemem and upfront): the parts that
need no model, no index and no container. The search is a fake that gives a made-up answer of `codemem search
--json`; the runs use the local run of test_e2e_run."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from cmeval import e2e_block, e2e_index, e2e_replay, e2e_run, e2e_steps
from cmeval import generate as gen
from cmeval.cli import main
from cmeval.e2e_run import RunSettings
from cmeval.tasks import save_tasks

from test_e2e_run import INIT, PROXY_LINES, STREAM, TOOL_INIT, TOOL_STREAM, _batch_task_file, _codemem_install, \
    _events, _local_run, _shim

MODEL = "claude-haiku-5-5"
RECIPE = gen.Recipe(name="r", repo="acme/auth", base_image="i", test="pytest {files}")
# A made-up answer of `codemem search --json`. The gold of make_task is the file auth/sessions.py and the function
# SessionManager.revoke_session at lines 33 to 34: result 2 is in the gold file (its class), result 3 is on the
# gold function.
ANSWER = {"query": "q", "signals": ["bm25", "code"],
          "timings": {"bm25": 0.01, "embed_query:jina-code": 0.2, "code": 0.03, "fuse": 0.001, "total": 0.25},
          "results": [
              {"path": "auth/tokens.py", "start_line": 12, "end_line": 30, "qualname": "TokenStore.revoke",
               "score": 0.0331},
              {"path": "auth/sessions.py", "start_line": 10, "end_line": 80, "qualname": "SessionManager",
               "score": 0.0325},
              {"path": "auth/sessions.py", "start_line": 33, "end_line": 34,
               "qualname": "SessionManager.revoke_session", "score": 0.0320},
              {"path": "auth/__init__.py", "start_line": 1, "end_line": 8, "qualname": "<block>", "score": 0.0161},
          ]}
TEXT = ("Possibly relevant code, from a search by meaning (it may be wrong):\n"
        "auth/tokens.py:12  TokenStore.revoke\n"
        "auth/sessions.py:10  SessionManager\n"
        "auth/sessions.py:33  SessionManager.revoke_session\n"
        "auth/__init__.py:1  <block>\n")
L2 = e2e_run.PromptSet(level="L2", texts={"acme__auth-42": "Fix login after reset.\n"}, source="vague.jsonl")


@pytest.fixture(autouse=True)
def no_codemem_program(monkeypatch):
    """The setup upfront has no codemem program in its preconditions. Its runs compare the block with the commit
    of the program that the eval names (e2e_block.codemem_program_commit); here that is no git checkout."""
    monkeypatch.setattr(e2e_run, "codemem_program_commit", lambda: None)


def _write_block(task, level="L0", query=None, answer=ANSWER, commit=None, **changes):
    """A block file as `cmeval e2e block` writes it, for the run's prompt text (or another query), on the task's
    index as it is now (none: None). The codemem of the tests is no git checkout, so its commit is None."""
    query = e2e_run.prompt_text(task, L2 if level == "L2" else None) if query is None else query
    block = e2e_block.make_block(task, level, query, answer, search_s=12.5, program=Path("/x/codemem"),
                                 commit=commit, index=e2e_index.read_index_meta(RECIPE, task))
    block.update(changes)
    path = e2e_block.block_path(RECIPE, task, level)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(block))
    return block, path


def _fake_index(task):
    """What `cmeval e2e index` leaves for a task: index/, src/ and index.json."""
    root = e2e_index.index_root(RECIPE, task)
    (root / "index").mkdir(parents=True)
    (root / "index" / "index.sqlite").write_bytes(b"x" * 100)
    (root / "src").mkdir()
    meta = {"task_id": task.id, "repo": task.repo, "base_commit": task.base_commit, "codemem_commit": "abc"}
    (root / "index.json").write_text(json.dumps(meta))
    return root, meta


# ---- the block and the first message

def test_block_text(make_task):
    task = make_task()
    block = e2e_block.make_block(task, "L0", task.query.strip(), ANSWER, search_s=1.0, program=None, commit=None,
                                 index=None)
    assert block["text"] == TEXT
    assert block["sha256"] == hashlib.sha256(TEXT.encode()).hexdigest() and block["k"] == 20
    assert block["embedded"] and block["timings"] == ANSWER["timings"]
    assert block["results"][2] == {"rank": 3, "path": "auth/sessions.py", "start": 33, "end": 34,
                                   "name": "SessionManager.revoke_session", "score": 0.0320}
    keywords = e2e_block.make_block(task, "L0", "q", {**ANSWER, "timings": {"bm25": 0.01, "total": 0.02}},
                                    search_s=1.0, program=None, commit=None, index=None)
    assert not keywords["embedded"] and keywords["text"] == TEXT


def test_first_message_of_codemem_and_upfront(make_task):
    task = make_task()
    plain = e2e_run.make_prompt(task)
    # grep and tool: the prompt of frame v1 as it was (test_prompt_frame_v1 has its bytes).
    assert plain == e2e_run.FRAME_V1.format(query=task.query.strip())
    # The block, one empty line, then the prompt exactly as the other setups get it.
    assert e2e_run.make_prompt(task, None, TEXT) == TEXT + "\n" + plain
    assert e2e_run.make_prompt(task, None, TEXT).startswith(
        "Possibly relevant code, from a search by meaning (it may be wrong):\nauth/tokens.py:12  TokenStore.revoke\n")
    assert TEXT.endswith("<block>\n") and (TEXT + "\n" + plain).count("<block>\n\nThe repository in the current") == 1
    assert e2e_run.make_prompt(task, L2, TEXT) == TEXT + "\n" + e2e_run.make_prompt(task, L2)
    # The query of the block's search is the level's text without the frame.
    assert e2e_run.prompt_text(task) == task.query.strip()
    assert e2e_run.prompt_text(task, L2) == "Fix login after reset."


def test_read_block_refuses_what_a_run_cannot_use(make_task):
    task = make_task()
    query = task.query.strip()

    def refused(match, level="L0", text=query, commit=None):
        with pytest.raises(gen.GenerateError, match=match):
            e2e_block.read_block(RECIPE, task, level, text, commit)

    refused(r"acme__auth-42: the block at L0 \(.*block-L0.json\) does not exist; make it with cmeval e2e block r")
    block, path = _write_block(task)
    assert e2e_block.read_block(RECIPE, task, "L0", query, None) == (block, path)
    path.write_text("")
    refused("is empty or not a block of this task and level")
    _write_block(task, results=[], text=e2e_block.HEADER + "\n")
    refused("is empty or not a block of this task and level")
    _write_block(task, answer={**ANSWER, "timings": {"bm25": 0.01, "total": 0.02}})
    refused(r"was made without the embedding model \(codemem's timings have no embed_query: key\)")
    _write_block(task)
    refused("was made from another prompt text than this run's", text="Fix login after reset.")
    refused("the block at L2 .* does not exist", level="L2", text="Fix login after reset.")
    _write_block(task, text=TEXT.replace(":12 ", ":13 "))
    refused("has a text that does not match its sha256")
    assert e2e_block.block_problem(RECIPE, task, "L0", query, None).endswith("make it with cmeval e2e block r")
    # A stale block: made by another codemem commit, or on another build of the task's index.
    _write_block(task, commit="463171c")
    assert e2e_block.read_block(RECIPE, task, "L0", query, "463171c")[0]["codemem_commit"] == "463171c"
    refused(r"was made by codemem 463171c, and the codemem program of the runs is at 5a5b5c5; make it again with "
            r"cmeval e2e block r --force", commit="5a5b5c5")
    root, meta = _fake_index(task)
    refused("was made on another build of the task's index", commit="463171c")  # made before there was an index
    _write_block(task)
    assert e2e_block.read_block(RECIPE, task, "L0", query, None)[0]["index"] == meta
    (root / "index.json").write_text(json.dumps({**meta, "seconds": 99.0}))  # built again
    refused(r"was made on another build of the task's index .*; make it again with cmeval e2e block r --force")


def test_record_entry_and_gold_ranks(make_task):
    task = make_task()
    block, path = _write_block(task, commit="463171c")
    assert e2e_block.record_entry(block, path, task) == {
        "file": str(path), "sha256": block["sha256"], "lines": 4, "search_s": 12.5, "codemem_commit": "463171c",
        "searches_made_for_agent": 1, "first_gold_file_rank": 2, "first_gold_function_rank": 3,
        "gold_function_excluded": None,
        "results": [{"rank": 1, "path": "auth/tokens.py", "line": 12, "name": "TokenStore.revoke"},
                    {"rank": 2, "path": "auth/sessions.py", "line": 10, "name": "SessionManager"},
                    {"rank": 3, "path": "auth/sessions.py", "line": 33, "name": "SessionManager.revoke_session"},
                    {"rank": 4, "path": "auth/__init__.py", "line": 1, "name": "<block>"}]}
    assert e2e_block.gold_ranks(block["results"][:1], task) == {
        "first_gold_file_rank": None, "first_gold_function_rank": None, "gold_function_excluded": None}
    partial = e2e_block.gold_ranks(block["results"], make_task(tags={"partial_labels": True}))
    assert partial == {"first_gold_file_rank": 2, "first_gold_function_rank": None,
                       "gold_function_excluded": "partial labels"}


# ---- making the blocks

def test_build_blocks_with_a_fake_search(make_task):
    task = make_task()
    root, meta = _fake_index(task)
    calls = []

    def fake_search(program, src, index, env, args, k, timeout):
        keys = ("CODEMEM_VECTOR_BACKEND", "HF_HUB_OFFLINE", "CODEMEM_HOME")
        calls.append({"src": src, "index": index, "args": args, "k": k, "env": {key: env.get(key) for key in keys},
                      "files": sorted(p.name for p in index.iterdir())})
        return ANSWER

    queries = {"L0": task.query.strip(), "L2": "Fix login after reset."}
    made = e2e_block.build_blocks(RECIPE, task, queries, program=Path("/x/codemem"), commit="463171c",
                                  search=fake_search)
    # One search per level: the level's text, 20 results, no filter, on a private copy of the index.
    assert [(c["args"], c["k"]) for c in calls] == [({"query": task.query.strip()}, 20),
                                                     ({"query": "Fix login after reset."}, 20)]
    assert all(c["src"] == root / "src" and c["index"].parent.name.startswith(".block-") for c in calls)
    assert calls[0]["files"] == ["index.sqlite"] and calls[0]["env"]["CODEMEM_VECTOR_BACKEND"] == "faiss"
    assert calls[0]["env"]["HF_HUB_OFFLINE"] == "1"
    assert calls[0]["env"]["CODEMEM_HOME"].startswith(str(root / ".block-"))
    # The copy is gone, the index is as it was, and the blocks are beside it.
    assert sorted(p.name for p in root.iterdir()) == ["block-L0.json", "block-L2.json", "index", "index.json", "src"]
    assert [p.name for p in (root / "index").iterdir()] == ["index.sqlite"]
    for level, query in queries.items():
        block, _ = e2e_block.read_block(RECIPE, task, level, query, "463171c")
        assert made[level] == (block, None) and block["text"] == TEXT and block["index"] == meta
        assert block["codemem_commit"] == "463171c" and block["search_s"] >= 0 and block["query"] == query
    # A block that a run could not use does not replace the file: the good block stays as it was.
    before = e2e_block.block_path(RECIPE, task, "L0").read_bytes()
    keywords = {**ANSWER, "timings": {"bm25": 0.01, "total": 0.02}}
    again = e2e_block.build_blocks(RECIPE, task, {"L0": queries["L0"]}, program=Path("/x/codemem"), commit="463171c",
                                   search=lambda *args: keywords)
    assert again["L0"][0]["embedded"] is False and "was made without the embedding model" in again["L0"][1]
    assert e2e_block.block_path(RECIPE, task, "L0").read_bytes() == before
    assert sorted(p.name for p in root.iterdir()) == ["block-L0.json", "block-L2.json", "index", "index.json", "src"]
    with pytest.raises(gen.GenerateError, match=r"no index for base commit 0123456789ab .*\(missing\); run cmeval "
                                                r"e2e index r first"):
        e2e_block.build_blocks(RECIPE, make_task(id="acme__auth-7"), queries, program=Path("/x"), commit=None,
                               search=fake_search)


def test_cli_block(make_task, tmp_path, monkeypatch, capsys):
    recipe_file = tmp_path / "r.toml"
    recipe_file.write_text('repo = "acme/auth"\nbase_image = "x"\ntest = "pytest"\n')
    one = make_task()
    two = make_task(id="acme__auth-43", fix=replace(one.fix, pr_number=43))
    task_file = tmp_path / "tasks.jsonl"
    save_tasks(task_file, [one, two])
    for task in (one, two):
        gen.task_dir(RECIPE, task).mkdir(parents=True)
        gen.tests_path(RECIPE, task).write_text("{}")
    _fake_index(one)  # the second task has no index
    prompts = tmp_path / "vague.jsonl"
    prompts.write_text("".join(json.dumps({"id": one.id, "level": level, "prompt": text}) + "\n"
                               for level, text in (("L1", "Logins fail after a reset.\n"),
                                                   ("L2", "Fix login after reset."))))
    program = tmp_path / "codemem" / ".venv" / "bin" / "codemem"
    program.parent.mkdir(parents=True)
    _shim(program.parent, "codemem", "#!/bin/sh\nexit 9\n")  # never run: the fake search stands in for it
    monkeypatch.setenv("CMEVAL_CODEMEM_BIN", str(program))
    asked, answer = [], dict(ANSWER)

    def fake_search(program, src, index, env, args, k, timeout, signals=None):
        asked.append((args["query"], k))
        return answer

    monkeypatch.setattr(e2e_replay, "cli_search_json", fake_search)
    args = ["e2e", "block", str(recipe_file), "--tasks", str(task_file)]
    levels = (("L0", one.query.strip()), ("L1", "Logins fail after a reset."), ("L2", "Fix login after reset."))

    assert main(args) == 1
    assert "the block at L1 needs --prompts FILE" in capsys.readouterr().err and asked == []

    assert main(args + ["--prompts", str(prompts)]) == 1  # the second task has no index
    captured = capsys.readouterr()
    assert asked == [(query, 20) for _, query in levels]
    assert "acme__auth-43 has no L1, L2 prompt in vague.jsonl; no block at that level" in captured.err
    assert "acme__auth-43: failed: acme__auth-43: no index for base commit" in captured.err
    assert "acme__auth-42 L2: 4 results in" in captured.err and "r: 3 of 4 blocks ready" in captured.out
    for level, query in levels:
        block, _ = e2e_block.read_block(RECIPE, one, level, query, None)
        assert block["text"] == TEXT and block["codemem_bin"] == str(program)

    # A block that a run can use is skipped. --force makes it again.
    asked.clear()
    assert main(args + ["--prompts", str(prompts), "--id", one.id]) == 0
    assert asked == [] and capsys.readouterr().err.count("skipped, the block exists") == 3
    assert main(args + ["--prompt-level", "L0", "--id", one.id, "--force"]) == 0
    assert asked == [(one.query.strip(), 20)]
    capsys.readouterr()

    # A search without the embedding model gives a block that no run can use. It does not replace the good block,
    # so the next call skips it.
    answer["timings"] = {"bm25": 0.01, "total": 0.02}
    assert main(args + ["--prompt-level", "L0", "--id", one.id, "--force"]) == 1
    assert ("acme__auth-42 L0: made, but a run cannot use it, and the file was not changed"
            in capsys.readouterr().err)
    answer["timings"] = ANSWER["timings"]
    asked.clear()
    assert main(args + ["--prompt-level", "L0", "--id", one.id]) == 0 and asked == []
    assert e2e_block.read_block(RECIPE, one, "L0", one.query.strip(), None)[0]["embedded"]
    # A rebuild of the index makes every block of the task stale, and the next call makes them again.
    meta_path = e2e_index.index_root(RECIPE, one) / "index.json"
    meta_path.write_text(json.dumps({**json.loads(meta_path.read_text()), "seconds": 5.0}))
    assert main(args + ["--prompt-level", "L0", "--id", one.id]) == 0 and len(asked) == 1

    # --sample: only the tasks of this repo that the run sample runs.
    sample = tmp_path / "sample.jsonl"
    sample.write_text("".join(json.dumps(row) + "\n" for row in (
        {"repo": "acme/auth", "id": one.id, "run": True}, {"repo": "acme/auth", "id": two.id, "run": False},
        {"repo": "acme/other", "id": "acme__other-1", "run": True})))
    asked.clear()
    assert main(args + ["--prompt-level", "L0", "--sample", str(sample), "--force"]) == 0
    assert asked == [(one.query.strip(), 20)] and two.id not in capsys.readouterr().err
    assert e2e_block.sample_ids(sample, "acme/auth") == {one.id}
    sample.write_text('{"id": "x"}\n')
    assert main(args + ["--prompt-level", "L0", "--sample", str(sample)]) == 1
    assert "line 1: not a row of a run sample" in capsys.readouterr().err


# ---- the setups

def test_setups_codemem_and_upfront(make_task):
    grep, tool = e2e_run.get_setup("grep"), e2e_run.get_setup("tool")
    codemem, upfront = e2e_run.get_setup("codemem"), e2e_run.get_setup("upfront")
    assert codemem.block and upfront.block and not grep.block and not tool.block
    assert (codemem.mcp_config, codemem.mcp_servers, codemem.checks, codemem.codemem) == \
        (tool.mcp_config, tool.mcp_servers, tool.checks, True)
    assert (upfront.mcp_config, upfront.mcp_servers, upfront.checks, upfront.codemem) == \
        (grep.mcp_config, grep.mcp_servers, grep.checks, False)
    assert e2e_run.check_setup(INIT, upfront, MODEL) == [] and e2e_run.check_setup(TOOL_INIT, codemem, MODEL) == []
    assert e2e_run.check_setup(TOOL_INIT, upfront, MODEL) == e2e_run.check_setup(TOOL_INIT, grep, MODEL) != []


def test_plan_runs_with_the_two_setups(make_task):
    a, b = make_task(id="acme__auth-1"), make_task(id="acme__auth-2")
    # grep and tool: the setup that goes first moves from task to task and at each repetition.
    assert [(t.id[-1], s, r) for t, s, r in e2e_run.plan_runs([a, b], ["grep", "tool"], 2)] == [
        ("1", "grep", 1), ("1", "tool", 1), ("2", "tool", 1), ("2", "grep", 1),
        ("1", "tool", 2), ("1", "grep", 2), ("2", "grep", 2), ("2", "tool", 2)]
    four = e2e_run.plan_runs([a], ["grep", "tool", "codemem", "upfront"], 2)
    assert [(s, r) for _, s, r in four] == [("grep", 1), ("tool", 1), ("codemem", 1), ("upfront", 1),
                                            ("tool", 2), ("codemem", 2), ("upfront", 2), ("grep", 2)]


def test_count_steps_counts_the_block_as_one_search_before_turn_1():
    gold = ["auth/sessions.py"]
    for stream in (STREAM, TOOL_STREAM):
        plain = e2e_steps.count_steps(_events(stream), gold)
        assert e2e_steps.count_steps(_events(stream), gold, block_paths=None) == plain  # grep and tool
        block = e2e_steps.count_steps(_events(stream), gold, block_paths=["auth/tokens.py", "auth/sessions.py"])
        assert block["codemem_calls"] == plain["codemem_calls"] + 1 and block["mcp_tools"] == plain["mcp_tools"]
        assert block["first_codemem_turn"] == 0 and block["first_gold_surfaced_turn"] == 0 and block["gold_surfaced"]
        assert block["gold"]["auth/sessions.py"] == {**plain["gold"]["auth/sessions.py"], "surfaced": 0}
        assert {k for k in plain if plain[k] != block[k]} <= {"codemem_calls", "first_codemem_turn", "gold",
                                                              "first_gold_surfaced_turn"}
        # A block without the gold file: one more search, and the gold is surfaced when the agent finds it.
        other = e2e_steps.count_steps(_events(stream), gold, block_paths=["auth/tokens.py"])
        assert other["first_gold_surfaced_turn"] == plain["first_gold_surfaced_turn"]
        assert other["codemem_calls"] == plain["codemem_calls"] + 1 and other["first_codemem_turn"] == 0
    grep, tool = (e2e_steps.count_steps(_events(s), gold) for s in (STREAM, TOOL_STREAM))
    assert (grep["codemem_calls"], grep["first_codemem_turn"], grep["first_gold_surfaced_turn"]) == (0, None, 1)
    assert (tool["codemem_calls"], tool["first_codemem_turn"]) == (5, 1)


# ---- runs

def test_run_one_upfront_locally(make_task, tmp_path, monkeypatch):
    lines = [{**r, "opens_with_text": True} for r in PROXY_LINES]
    recipe, task, calls, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events(),
                                             proxy_lines=lines)
    block, block_file = _write_block(task)
    out = e2e_run.run_dir("r1", task.id, "upfront", 1)
    record = e2e_run.run_one(recipe, task, setup="upfront", model=MODEL, rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))
    assert record["integrity"]["setup_ok"] and not record["discard"] and record["flags"] == []
    assert record["completed"] is True and len(graded) == 1
    # grep's container: no codemem mount, no gate, no MCP server.
    run = next(c for c in calls if c[:2] == ["docker", "run"])
    assert run.count("-v") == 2 and json.loads((out / "mcp.json").read_text()) == {"mcpServers": {}}
    assert "cmgate" not in (out / "agent.sh").read_text() and not (out / "cmgate.json").exists()
    assert record["identity"]["codemem"] is None and record["integrity"]["codemem_warm"] is None
    # The first message: the block, one empty line, then grep's prompt. Claude Code got it as its prompt.
    prompt = (out / "prompt.txt").read_text()
    assert prompt == TEXT + "\n" + e2e_run.make_prompt(task)
    assert (tmp_path / "argv.txt").read_text().startswith("-p\n" + TEXT + "\nThe repository in the current")
    assert record["identity"]["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
    # The record.
    entry = record["identity"]["block"]
    assert entry == e2e_block.record_entry(block, block_file, task)
    assert (entry["sha256"], entry["file"], entry["lines"], entry["search_s"]) == (block["sha256"], str(block_file),
                                                                                    4, 12.5)
    assert entry["searches_made_for_agent"] == 1 and entry["results"][0]["path"] == "auth/tokens.py"
    assert record["integrity"]["block_in_first_message"] is True
    # The block is one codemem search before turn 1, and the gold file in it is surfaced at turn 0.
    grep_steps = e2e_run.count_steps(_events(), task.gold.files)
    assert record["steps"]["codemem_calls"] == grep_steps["codemem_calls"] + 1 == 1
    assert record["steps"]["first_codemem_turn"] == 0 and record["steps"]["first_gold_surfaced_turn"] == 0
    # The search is in no clock of the run.
    assert set(record["time"]["prep_steps_s"]) == {"remove_config", "copy_swap", "ready"}
    assert record["time"]["codemem_warm_s"] is None


@pytest.mark.parametrize("opens, flag", [(False, "block not in the first message"),
                                         (None, "block not checked: no model request in the proxy log")])
def test_run_one_upfront_flags_a_first_message_without_the_block(make_task, tmp_path, monkeypatch, opens, flag):
    lines = PROXY_LINES if opens is None else [{**r, "opens_with_text": opens} for r in PROXY_LINES]
    recipe, task, _, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events(), proxy_lines=lines)
    _write_block(task)
    out = e2e_run.run_dir("r1", task.id, "upfront", 1)
    record = e2e_run.run_one(recipe, task, setup="upfront", model=MODEL, rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))
    assert record["flags"] == [flag] and record["integrity"]["block_in_first_message"] is opens
    assert not record["discard"] and len(graded) == 1  # graded; the flag keeps it out of the score's numbers


def test_block_opened():
    assert e2e_run.block_opened([]) is None
    assert e2e_run.block_opened([{"seq": 1, "path": "/api/hello"}]) is None
    lines = [{"seq": 3, "path": "/v1/messages", "opens_with_text": False},
             {"seq": 2, "path": "/v1/messages", "opens_with_text": True},
             {"seq": 1, "path": "/v1/messages/count_tokens", "opens_with_text": False}]
    assert e2e_run.block_opened(lines) is True  # one /v1/messages request began with the block
    assert e2e_run.block_opened(lines[:1]) is False
    # a request that Claude Code makes for itself before the conversation does not count against the run
    side_first = [{"seq": 1, "path": "/v1/messages", "opens_with_text": False},
                  {"seq": 2, "path": "/v1/messages", "opens_with_text": True}]
    assert e2e_run.block_opened(side_first) is True


def test_run_one_codemem_locally(make_task, tmp_path, monkeypatch):
    lines = [{**r, "opens_with_text": True} for r in PROXY_LINES]
    recipe, task, _, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events(TOOL_STREAM),
                                         proxy_lines=lines)
    _codemem_install(tmp_path, monkeypatch, recipe, task)
    block, block_file = _write_block(task)
    out = e2e_run.run_dir("r1", task.id, "codemem", 1)
    record = e2e_run.run_one(recipe, task, setup="codemem", model=MODEL, rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))
    # tool's run: the gate, the warm server and its checks.
    assert record["integrity"]["setup_ok"] and not record["discard"] and record["flags"] == []
    assert record["integrity"]["codemem_warm"]["ok"] and record["identity"]["codemem"]["steering"] == "default"
    assert "codemem_warm" in record["time"]["prep_steps_s"]
    assert json.loads((out / "mcp.json").read_text())["mcpServers"]["codemem"]["alwaysLoad"] is True
    # plus the block.
    assert (out / "prompt.txt").read_text() == TEXT + "\n" + e2e_run.make_prompt(task)
    assert record["identity"]["block"] == e2e_block.record_entry(block, block_file, task)
    assert record["integrity"]["block_in_first_message"] is True
    tool_steps = e2e_run.count_steps(_events(TOOL_STREAM), task.gold.files)
    assert record["steps"]["codemem_calls"] == tool_steps["codemem_calls"] + 1 == 6
    assert record["steps"]["mcp_tools"] == tool_steps["mcp_tools"] and record["steps"]["first_codemem_turn"] == 0


def test_run_one_stops_before_it_starts_without_its_block(make_task, tmp_path, monkeypatch):
    task = make_task()
    monkeypatch.setattr(e2e_run, "image_exists", lambda tag: True)
    gen.task_dir(RECIPE, task).mkdir(parents=True)
    gen.tests_path(RECIPE, task).write_text("{}")
    out = tmp_path / "out"

    def refused(match, setup="upfront", prompts=None):
        with pytest.raises(gen.GenerateError, match=match):
            e2e_run.run_one(RECIPE, task, setup=setup, model=MODEL, rep=1, out=out, prompts=prompts)
        assert not out.exists()

    refused("the block at L0 .* does not exist")  # missing
    _, path = _write_block(task)
    path.write_text("")
    refused("is empty or not a block")  # empty
    _write_block(task, answer={**ANSWER, "timings": {"bm25": 0.01, "total": 0.01}})
    refused("was made without the embedding model")  # keywords only
    _write_block(task)
    refused("the block at L2 .* does not exist", prompts=L2)  # the block of L0 is not the block of L2
    _write_block(task, level="L2", query="An older rewrite.")
    refused("was made from another prompt text", prompts=L2)
    _codemem_install(tmp_path, monkeypatch, RECIPE, task)  # codemem: tool's preconditions pass, then the block's
    e2e_block.block_path(RECIPE, task, "L0").unlink()
    refused("the block at L0 .* does not exist", setup="codemem")


def test_batch_does_not_start_while_a_block_cannot_be_used(make_task, tmp_path, monkeypatch, capsys):
    tasks = [make_task(id=f"acme__auth-{i}") for i in (1, 2)]
    started = []
    monkeypatch.setattr(e2e_run, "run_one", lambda *args, **kwargs: started.append(kwargs["setup"]))
    _write_block(tasks[0])
    with pytest.raises(gen.GenerateError, match=r"1 of 2 tasks have no block that a run can use; the first: "
                                                r"acme__auth-2: the block at L0 .* does not exist"):
        e2e_run.run_batch(RECIPE, tasks, run_id="b3", setups=["grep", "upfront"], model=MODEL)
    assert started == []
    path, _ = _batch_task_file(make_task, tmp_path)
    assert main(["e2e", "run", "pandas", "--tasks", str(path), "--run-id", "b4", "--setup", "grep", "--setup",
                 "upfront"]) == 1
    assert "e2e run: 2 of 2 tasks have no block that a run can use" in capsys.readouterr().err and started == []


def test_recount_counts_the_block_again(make_task):
    task = make_task()
    block, path = _write_block(task)
    record = {"task_id": task.id, "setup": "upfront", "rep": 1, "steps": {}, "integrity": {},
              "identity": {"gold_files": task.gold.files, "codemem": None,
                           "block": e2e_block.record_entry(block, path, task)}}
    out = e2e_run.run_dir("s9", task.id, "upfront", 1)
    out.mkdir(parents=True)
    (out / "run.json").write_text(json.dumps(record))
    (out / "stream.jsonl").write_text(STREAM.read_text())
    assert e2e_run.recount("s9", progress=lambda message: None) == 1
    steps = json.loads((out / "run.json").read_text())["steps"]
    paths = [r["path"] for r in block["results"]]
    assert steps == {**e2e_run.count_steps(_events(), task.gold.files, block_paths=paths), "num_turns_result": None}
    assert (steps["codemem_calls"], steps["first_codemem_turn"], steps["first_gold_surfaced_turn"]) == (1, 0, 0)
