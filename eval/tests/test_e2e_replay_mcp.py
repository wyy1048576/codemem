"""The replay through an MCP server (e2e_replay.replay). A fake codemem program stands in for the real one: it
answers the MCP handshake, index_status and search_code over stdio, and `codemem search --json`. It writes the
arguments and the environment it got to a log, and it writes a file into its index folder, so the tests can see
that the replay gives it a copy."""

import json
import os
import stat
import sys

import pytest

from cmeval import e2e_replay as rp
from cmeval.cli import main
from cmeval.files import write_json
from cmeval.paths import e2e_dir

FAKE = r'''
import json, os, sys

args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"argv": args, "steering": os.environ.get("CODEMEM_STEERING"),
                          "home": os.environ.get("CODEMEM_HOME"), "backend": os.environ.get("CODEMEM_VECTOR_BACKEND"),
                          "offline": os.environ.get("HF_HUB_OFFLINE")}) + "\n")


def results(k, prefix=None):
    out = []
    for i in range(1, k + 1):
        if i == 3:
            out.append(("auth/sessions.py", 33, 34, "SessionManager.revoke_session", 100 + i))
        else:
            out.append(((prefix or "other/") + f"f{i}.py", 1, 5, f"f{i}", 100 + i))
    return out


def render(a):
    k = max(1, min(int(a.get("k", 10)), 50))
    lines = []
    for i, (path, start, end, name, cid) in enumerate(results(k, a.get("path_prefix")), 1):
        lines += [f"{i}. {path}:{start}-{end}  {name}  [id {cid}]", f"   def {name}():", "   |     pass"]
    return "\n".join(lines)


if args[0] == "mcp":
    index = args[args.index("--index-dir") + 1]
    open(os.path.join(index, "written-by-server"), "w").write("x")
    status_calls = searches = 0
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        if msg["method"] == "initialize":
            result = {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                      "serverInfo": {"name": "codemem", "version": "0.0-fake"}}
        elif msg["method"] == "tools/call" and msg["params"]["name"] == "index_status":
            status_calls += 1
            state = "updating" if status_calls == 1 else "ready"
            text = f"state: {state}\n\n" + json.dumps({"state": state, "progress": None, "chunks": 3, "stale": None})
            result = {"content": [{"type": "text", "text": text}], "structuredContent": {"result": text}}
        elif msg["method"] == "tools/call" and msg["params"]["name"] == "search_code":
            searches += 1
            text = render(msg["params"]["arguments"])
            if searches == 1:
                text += "\n\nNote: the embedding model is still loading (the first search after codemem starts)."
            text += "\n\nLost the trail later? Search again in different words."
            result = {"content": [{"type": "text", "text": text}], "structuredContent": {"result": text},
                      "isError": False}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "no"}}),
                  flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}), flush=True)
elif args[0] == "search":
    k = int(args[args.index("-k") + 1])
    prefix = args[args.index("--path-prefix") + 1] if "--path-prefix" in args else None
    cards = [{"path": p, "start_line": s, "end_line": e, "qualname": n, "chunk_id": c}
             for p, s, e, n, c in results(k, prefix)]
    print(json.dumps({"query": args[-1], "signals": ["bm25"], "timings": {}, "results": cards}))
'''

ITEM_TEXT = "{i}. {path}:{start}-{end}  {name}  [id {cid}]\n   def {name}():\n   |     pass"
LOADING = "\n\nNote: the embedding model is still loading (the first search after codemem starts); keywords only."


def _render(k: int, prefix: str | None = None) -> str:
    lines = []
    for i in range(1, k + 1):
        if i == 3:
            path, start, end, name = "auth/sessions.py", 33, 34, "SessionManager.revoke_session"
        else:
            path, start, end, name = f"{prefix or 'other/'}f{i}.py", 1, 5, f"f{i}"
        lines.append(ITEM_TEXT.format(i=i, path=path, start=start, end=end, name=name, cid=100 + i))
    return "\n".join(lines)


def _wire(text: str) -> str:
    return json.dumps({"result": text}, ensure_ascii=False, separators=(",", ":"))


def _write_run(folder, task, *, level, setup="tool", args=None, text=None, steering="default"):
    folder.mkdir(parents=True)
    codemem = {"commit": "abc", "steering": steering,
               "index": {"codemem_commit": "abc", "base_commit": task.base_commit}} if setup == "tool" else None
    record = {"run_id": folder.parents[2].name, "task_id": task.id, "repo": task.repo, "recipe": "demo",
              "setup": setup, "rep": 1, "completed": False, "discard": False,
              "identity": {"prompt_level": level, "gold_files": task.gold.files, "codemem": codemem}}
    write_json(folder / "run.json", record)
    events = [{"type": "system", "subtype": "init"}]
    if args is not None:
        events += [
            {"type": "assistant", "message": {"id": "m1", "content": [
                {"type": "tool_use", "id": "c1", "name": rp.SEARCH_TOOL, "input": args}]}, "parent_tool_use_id": None},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "c1",
                                                      "content": _wire(text)}]}, "parent_tool_use_id": None},
            {"type": "assistant", "message": {"id": "m2", "content": [{"type": "text", "text": "done"}]},
             "parent_tool_use_id": None},
        ]
    (folder / "stream.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    usage = lambda inp, read, out: {"input_tokens": inp, "cache_creation_input_tokens": 0,  # noqa: E731
                                    "cache_read_input_tokens": read, "output_tokens": out}
    proxy = [{"seq": 1, "path": "/v1/messages", "status": 200, "message_id": "m1", "usage": usage(10, 1000, 20)},
             {"seq": 2, "path": "/v1/messages", "status": 200, "message_id": "m2", "usage": usage(10, 2000, 5)}]
    (folder / "proxy.jsonl").write_text("".join(json.dumps(r) + "\n" for r in proxy))


def _program(path, script: str) -> None:
    """An executable that runs a Python script. A shell script starts it: the path of this Python can have a
    space, which a #! line cannot hold."""
    path.with_suffix(".py").write_text(script)
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{path.with_suffix(".py")}" "$@"\n')
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def setup(tmp_path, make_task, monkeypatch):
    """Two runs of a codemem setup (L0 keywords only in the run, L1 a full search with a path prefix and k=5),
    one run of the grep setup, the task's index, the task file and the fake program."""
    monkeypatch.setattr(rp, "READY_POLL_S", 0.01)
    task = make_task()
    runs = e2e_dir() / "runs"
    _write_run(runs / "r0" / task.id / "tool" / "1", task, level="L0",
               args={"query": "revoke sessions", "k": 10}, text=_render(10) + LOADING)
    _write_run(runs / "r0" / task.id / "grep" / "1", task, level="L0", setup="grep")
    _write_run(runs / "r1" / task.id / "tool" / "1", task, level="L1",
               args={"query": "-dash first", "k": 5, "path_prefix": "auth/"}, text=_render(5, "auth/"),
               steering="strong")
    root = e2e_dir() / "indexes" / "demo" / task.id
    (root / "index").mkdir(parents=True)
    (root / "index" / "store.db").write_text("index")
    (root / "src").mkdir()
    write_json(root / "index.json", {"task_id": task.id, "base_commit": task.base_commit, "codemem_commit": "abc"})
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps(task.to_dict()) + "\n")
    program = tmp_path / "fake" / ".venv" / "bin" / "codemem"
    program.parent.mkdir(parents=True)
    _program(program, FAKE)
    log = tmp_path / "fake.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("CODEMEM_STEERING", "none")  # the caller's own setting must not reach codemem
    return {"task": task, "tasks": tasks, "program": program, "log": log, "index": root / "index",
            "work": tmp_path / "work", "out": tmp_path / "out" / "replay.json"}


def _calls(log) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_replay_end_to_end(setup, monkeypatch):
    monkeypatch.setattr(rp, "codemem_commit", lambda checkout: "abc")
    setup["work"].mkdir()
    summary, out, text = rp.replay(["r0", "r1"], ks=[5, 10], tasks_files=[setup["tasks"]],
                                   program=setup["program"], out=setup["out"], work_root=setup["work"])
    assert out == setup["out"] and out.with_suffix(".md").read_text() == text
    assert json.loads(out.read_text())["ks"] == [5, 10]
    assert summary["skipped"] == {"setup without codemem": 1}
    assert summary["codemem"]["commit"] == "abc"
    assert summary["codemem"]["env"]["CODEMEM_VECTOR_BACKEND"] == "faiss"
    r0, r1 = summary["runs"]

    # r0: the same arguments at each k; the gold function is the 3rd result
    assert set(r0["replay"]["by_k"]) == {"5", "10"}
    at5 = r0["replay"]["by_k"]["5"]
    assert len(at5["results"]) == 5 and at5["score"]["first_gold_rank"] == 3
    assert at5["score"]["gold_function_hit"] is True
    assert at5["text_chars"] < at5["wire_chars"]
    assert r0["replay"]["server"]["warmup_searches"] == 2
    assert r0["replay"]["server"]["version"] == "0.0-fake"
    # r0 was keywords only in the run: the check asks codemem search --signals bm25
    assert r0["check"]["verdict"] == "same (keywords only)"
    # r1: its own k (5) and path prefix; the check compares with the replay at k=5
    assert r1["replay"]["by_k"]["10"]["results"][0]["path"] == "auth/f1.py"
    assert r1["check"]["verdict"] == "same" and r1["check"]["against"] == "replay at k=5"

    calls = _calls(setup["log"])
    servers = [c for c in calls if c["argv"][0] == "mcp"]
    assert len(servers) == 2  # one for each steering level
    assert {c["steering"] for c in servers} == {None, "strong"}
    assert all(c["backend"] == "faiss" and c["offline"] == "1" for c in servers)
    assert all(c["argv"][1].endswith("/src") and c["argv"][3] != str(setup["index"]) for c in servers)
    searches = [c for c in calls if c["argv"][0] == "search"]
    assert len(searches) == 1 and searches[0]["argv"][-2:] == ["--", "revoke sessions"]
    assert "--signals" in searches[0]["argv"]
    # the index stays as it was; the copies are gone
    assert sorted(p.name for p in setup["index"].iterdir()) == ["store.db"]
    assert list(setup["work"].iterdir()) == []
    assert (out.parent / "replay-logs").is_dir()

    assert "**A gold file is among the results**" in text
    assert "| all | 2 | 2/2 (100%) | 2/2 (100%) | 2/2 (100%) |" in text
    assert "same (keywords only) 1" in text


def test_replay_marks_other_commits_and_missing_index(setup):
    summary, _, _ = rp.replay(["r0"], ks=[5], tasks_files=[setup["tasks"]], program=setup["program"],
                              out=setup["out"], bm25_check=False)
    assert summary["runs"][0]["check"]["verdict"] == "not checked: keywords only in the run"
    summary, _, _ = rp.replay(["r1"], ks=[5], tasks_files=[setup["tasks"]], program=setup["program"],
                              out=setup["out"])
    assert summary["runs"][0]["check"]["verdict"] == "same, other codemem commit"  # the fake has no git commit
    summary, _, text = rp.replay(["r1"], ks=[5], tasks_files=[setup["tasks"]], program=setup["program"],
                                 out=setup["out"], index_root=setup["work"])
    assert "no index at" in summary["runs"][0]["replay"]["error"]
    assert "No run was replayed." in text and "Replay failed: 1 runs" in text


def test_records_only_starts_no_program(setup):
    summary, _, text = rp.replay(["r0", "r1"], tasks_files=[setup["tasks"]], records_only=True, out=setup["out"])
    assert not setup["log"].exists()
    assert summary["codemem"] is None and all(e["replay"] is None for e in summary["runs"])
    assert "**The first search_code result in the run**" in text and "**A gold file" not in text


def test_bad_k_is_refused(setup):
    with pytest.raises(rp.ReplayError):
        rp.replay(["r0"], ks=[0, 10], records_only=True, out=setup["out"])
    with pytest.raises(rp.ReplayError):
        rp.replay(["r0"], ks=[60], records_only=True, out=setup["out"])


def test_server_that_stops_fails_the_task(setup, tmp_path):
    broken = tmp_path / "broken"
    _program(broken, "import sys\nsys.exit(3)\n")
    summary, _, _ = rp.replay(["r0"], ks=[5], tasks_files=[setup["tasks"]], program=broken, out=setup["out"])
    assert "stopped" in summary["runs"][0]["replay"]["error"]


def test_cli(setup, capsys):
    code = main(["e2e", "replay", "r0", "r1", "--k", "5", "--k", "20", "--tasks", str(setup["tasks"]),
                 "--codemem-bin", str(setup["program"]), "--out", str(setup["out"])])
    assert code == 0
    printed = capsys.readouterr()
    assert "| group | runs | in the run | k=5 | k=20 |" in printed.out
    assert "2 runs, 0 failed" in printed.err
    assert main(["e2e", "replay", "r0", "--codemem-bin", "/no/such/codemem", "--out", str(setup["out"])]) == 1


def test_default_program_from_the_environment(setup, monkeypatch):
    monkeypatch.setenv("CMEVAL_CODEMEM_BIN", str(setup["program"]))
    assert main(["e2e", "replay", "r1", "--k", "5", "--tasks", str(setup["tasks"]), "--out", str(setup["out"])]) == 0
    assert os.path.exists(setup["out"])
