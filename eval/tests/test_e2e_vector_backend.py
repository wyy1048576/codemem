"""The search index of a batch (CMEVAL_CODEMEM_VECTOR_BACKEND). A batch that does not set it is a batch of main:
the same folders, environment of codemem, commands and records. A compact batch has its own index and blocks
(compact/ in the task's folder), names compact wherever codemem runs, and says so in its records. No model, no
index and no container: the codemem program, the search and Claude Code are the fakes of the other e2e tests."""

import json
import os
import re
import shutil
from pathlib import Path

import pytest

import test_e2e_run as run_tests
from cmeval import e2e_block, e2e_index, e2e_replay, e2e_run
from cmeval import generate as gen
from cmeval.cli import main
from cmeval.e2e_run import RunSettings
from cmeval.files import write_json
from cmeval.paths import e2e_dir
from cmeval.tasks import save_tasks

from test_e2e_block import ANSWER, RECIPE, _fake_index, _write_block
from test_e2e_replay_mcp import FAKE, _program, _render, _write_run
from test_e2e_run import FAKE_CODEMEM, PROXY_LINES, TOOL_STREAM, _codemem_install, _events, _git, _local_run, _shim

ENV = "CMEVAL_CODEMEM_VECTOR_BACKEND"
MODEL = "claude-haiku-5-5"
BAD = "CMEVAL_CODEMEM_VECTOR_BACKEND must be one of faiss, compact, not 'exact'"

# What a batch without the switch has on main. The existing tests pin the same values (test_codemem_mcp_config,
# test_cli_index, test_build_blocks_with_a_fake_search, test_run_one_tool_locally, test_replay_end_to_end); these
# tests fail when one of them moves, in its value or its order (the order is in the bytes of mcp.json and run.json).
MAIN_MCP_ENV = {"HF_HOME": "/hf", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                "CODEMEM_HOME": "/home/agent/.codemem", "CODEMEM_MODEL_IDLE_MINUTES": "0",
                "CODEMEM_VECTOR_BACKEND": "faiss", "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4"}
MAIN_GATE_ARGS = ["mcp", "--index-dir", "/cmindex"]  # around /testbed, which the local run moves
MAIN_INDEX_JSON = ["task_id", "repo", "base_commit", "codemem_commit", "seconds", "summary"]
MAIN_BLOCK_FILE = ["schema", "task_id", "level", "query", "k", "text", "sha256", "results", "embedded", "timings",
                   "search_s", "codemem_bin", "codemem_commit", "index", "made_utc"]
MAIN_IDENTITY_CODEMEM = ["commit", "bin", "index", "steering", "index_bytes_before", "index_bytes_after",
                         "index_copy_removed"]
MAIN_IDENTITY_BLOCK = ["file", "sha256", "lines", "search_s", "codemem_commit", "searches_made_for_agent",
                       "first_gold_file_rank", "first_gold_function_rank", "gold_function_excluded", "results"]
MAIN_REPLAY_ENTRY = ["run_id", "task_id", "repo", "recipe", "setup", "rep", "level", "completed", "steering",
                     "run_codemem_commit", "run_index_codemem_commit", "run_index_base_commit", "base_commit", "gold",
                     "call", "in_run", "costs", "replay", "check", "run_dir"]
# The fake codemem server of test_e2e_run, whose index_status also names its search index, as codemem's does: the
# one of FAKE_SEARCH_INDEX, else the one it was told (CODEMEM_VECTOR_BACKEND).
NAMES_ITS_INDEX = run_tests.FAKE_MCP_SERVER.replace(
    'json.dumps({"state": state, "models_loaded": True})',
    'json.dumps({"state": state, "models_loaded": True, "search_index": {"index": os.environ.get('
    '"FAKE_SEARCH_INDEX") or os.environ.get("CODEMEM_VECTOR_BACKEND")}})')
assert NAMES_ITS_INDEX != run_tests.FAKE_MCP_SERVER


def _files(root: Path) -> dict[str, bytes]:
    """Every file below root and its bytes."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _index_setup(remote, make_task, tmp_path, monkeypatch):
    """One valid task of a recipe and a fake codemem program in a git checkout, as in test_cli_index. Returns the
    arguments of `cmeval e2e index`, the recipe, the task and the file of the program's calls."""
    recipe_file = tmp_path / "demo.toml"
    recipe_file.write_text('repo = "acme/demo"\nbase_image = "x"\ntest = "pytest"\n')
    recipe = gen.load_recipe(recipe_file)
    task = make_task(id="acme__demo-42", repo="acme/demo", base_commit=remote.shas[0])
    task_file = tmp_path / "tasks.jsonl"
    save_tasks(task_file, [task])
    gen.task_dir(recipe, task).mkdir(parents=True)
    gen.tests_path(recipe, task).write_text("{}")
    checkout = tmp_path / "codemem"
    (checkout / "src").mkdir(parents=True)
    (checkout / "src" / "a.py").write_text("A = 1\n")
    _git(checkout, "init", "-q")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-qm", "codemem")
    (checkout / ".venv" / "bin").mkdir(parents=True)
    calls = tmp_path / "calls.txt"
    _shim(checkout / ".venv" / "bin", "codemem", FAKE_CODEMEM.format(calls=calls))
    monkeypatch.setenv("CMEVAL_CODEMEM_BIN", str(checkout / ".venv" / "bin" / "codemem"))
    monkeypatch.setenv("CODEMEM_HOME", str(tmp_path / "codemem-home"))
    return ["e2e", "index", str(recipe_file), "--tasks", str(task_file)], recipe, task, calls


def _compact_index(task, recipe=RECIPE) -> dict:
    """What `cmeval e2e index` with the switch at compact leaves beside the exact index: compact/index/ and
    compact/index.json."""
    root = e2e_index.index_root(recipe, task, "compact")
    (root / "index").mkdir(parents=True)
    (root / "index" / "compact-index.bin").write_bytes(b"c" * 10)
    meta = {"task_id": task.id, "repo": task.repo, "base_commit": task.base_commit, "codemem_commit": "abc",
            "seconds": 1.0, "summary": "indexed 3 files", "vector_backend": "compact"}
    (root / "index.json").write_text(json.dumps(meta))
    return meta


def _codemem_run(make_task, tmp_path, monkeypatch, *, backend=None, search_index=None):
    """A local run of the setup codemem (tool and the block) with the fake that names its search index. backend:
    the switch (None: not set); for compact, the compact index and its block are beside the exact ones."""
    monkeypatch.setattr(run_tests, "FAKE_MCP_SERVER", NAMES_ITS_INDEX)
    if search_index:
        monkeypatch.setenv("FAKE_SEARCH_INDEX", search_index)
    lines = [{**r, "opens_with_text": True} for r in PROXY_LINES]
    recipe, task, _, graded = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events(TOOL_STREAM),
                                         proxy_lines=lines)
    _codemem_install(tmp_path, monkeypatch, recipe, task)  # the exact index
    exact_block, _ = _write_block(task)
    meta = None
    if backend:
        monkeypatch.setenv(ENV, backend)
    if backend == "compact":
        meta = _compact_index(task, recipe)
        _write_block(task)
    seen = {}
    run_tests._spy_docker_run(monkeypatch, seen)
    out = e2e_run.run_dir("b1", task.id, "codemem", 1)
    record = e2e_run.run_one(recipe, task, setup="codemem", model=MODEL, rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))
    return {"record": record, "out": out, "seen": seen, "meta": meta, "task": task, "recipe": recipe,
            "exact_block": exact_block, "graded": graded,
            "servers": [json.loads(line) for line in (tmp_path / "server-calls.log").read_text().splitlines()
                        if '"argv"' in line]}


# ---- a batch that does not set the switch

def test_unset_paths_and_environments_are_those_of_main(make_task, tmp_path):
    task = make_task()
    assert ENV not in os.environ
    assert e2e_index.vector_backend() == "faiss" and e2e_index.named_vector_backend() is None
    root = Path(os.environ["CMEVAL_HOME"]) / "e2e" / "indexes" / "r" / task.id
    assert e2e_index.index_root(RECIPE, task) == e2e_index.task_root(RECIPE, task) == root
    assert e2e_index.src_root(RECIPE, task) == root / "src"
    assert e2e_block.block_path(RECIPE, task, "L1") == root / "block-L1.json"
    assert e2e_index.codemem_env(e2e_index.vector_backend()) == {"CODEMEM_VECTOR_BACKEND": "faiss"}
    env = e2e_replay.server_env(None, tmp_path / "home")
    assert {k: v for k, v in env.items() if k.startswith(("CODEMEM_", "HF_HUB", "TRANSFORMERS_"))} == {
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "CODEMEM_HOME": str(tmp_path / "home"),
        "CODEMEM_MODEL_IDLE_MINUTES": "0", "CODEMEM_VECTOR_BACKEND": "faiss"}


def test_unset_build_is_the_build_of_main(remote, make_task, tmp_path, monkeypatch, capsys):
    args, recipe, task, calls = _index_setup(remote, make_task, tmp_path, monkeypatch)
    monkeypatch.setenv("CODEMEM_VECTOR_BACKEND", "compact")  # the shell's own setting does not reach the build
    assert main(args) == 0
    root = Path(os.environ["CMEVAL_HOME"]) / "e2e" / "indexes" / "demo" / task.id
    assert calls.read_text().split() == ["index", str(root / "src"), "--index-dir", str(root / "index")]
    assert Path(f"{calls}.env").read_text().split() == ["faiss", str(tmp_path / "codemem-home")]
    assert list(json.loads((root / "index.json").read_text())) == MAIN_INDEX_JSON
    assert sorted(p.name for p in root.iterdir()) == ["index", "index.json", "index.log", "src"]
    assert capsys.readouterr().out == f"demo: 1 of 1 indexes ready in {root.parent}\n"


def test_unset_block_is_the_block_of_main(make_task):
    task = make_task()
    root, meta = _fake_index(task)
    seen = []

    def fake_search(program, src, index, env, args, k, timeout):
        seen.append((src, index.parent.parent, env["CODEMEM_VECTOR_BACKEND"], sorted(p.name for p in index.iterdir())))
        return ANSWER

    made = e2e_block.build_blocks(RECIPE, task, {"L0": task.query.strip()}, program=Path("/x/codemem"), commit=None,
                                  search=fake_search)
    assert seen == [(root / "src", root, "faiss", ["index.sqlite"])] and made["L0"][1] is None
    block = json.loads((root / "block-L0.json").read_text())
    assert list(block) == MAIN_BLOCK_FILE and block["index"] == meta
    assert sorted(p.name for p in root.iterdir()) == ["block-L0.json", "index", "index.json", "src"]


def test_unset_run_writes_the_files_and_record_of_main(make_task, tmp_path, monkeypatch):
    run = _codemem_run(make_task, tmp_path, monkeypatch)
    record, out = run["record"], run["out"]
    assert record["integrity"]["setup_ok"] and not record["discard"] and record["flags"] == []
    mcp = json.loads((out / "mcp.json").read_text())["mcpServers"]["codemem"]
    gate = json.loads((out / "cmgate.json").read_text())
    assert list(mcp["env"].items()) == list(gate["env"].items()) == list(MAIN_MCP_ENV.items())
    assert gate["argv"][1:2] + gate["argv"][3:] == MAIN_GATE_ARGS and [s["backend"] for s in run["servers"]] == [
        "faiss"]
    assert list(record["identity"]["codemem"]) == MAIN_IDENTITY_CODEMEM
    assert list(record["identity"]["block"]) == MAIN_IDENTITY_BLOCK
    root = e2e_index.task_root(run["recipe"], run["task"])
    assert record["identity"]["codemem"]["index"] == json.loads((root / "index.json").read_text())
    assert record["identity"]["block"]["file"] == str(root / "block-L0.json")
    assert run["seen"]["files"] == ["index.sqlite", "vectors", "vectors/code.faiss"]  # the copy of the exact index
    # The warm server's index_status names its search index (as codemem's does), and the record keeps it.
    assert record["integrity"]["codemem_warm"]["status"]["search_index"] == {"index": "faiss"}


def test_unset_run_does_not_check_the_search_index(make_task, tmp_path, monkeypatch):
    """Without the switch the setup check is that of main: a warm server that names another search index passes."""
    run = _codemem_run(make_task, tmp_path, monkeypatch, search_index="compact")
    assert run["record"]["integrity"]["setup_ok"] and not run["record"]["discard"]


# ---- the switch at compact

def test_compact_build_has_a_folder_of_its_own(remote, make_task, tmp_path, monkeypatch, capsys):
    args, recipe, task, calls = _index_setup(remote, make_task, tmp_path, monkeypatch)
    monkeypatch.setenv("CODEMEM_VECTOR_BACKEND", "faiss")  # the shell's own setting does not reach the build
    assert main(args) == 0  # the exact index, with a block beside it
    root = e2e_index.task_root(recipe, task)
    (root / "block-L0.json").write_text("{}")
    exact = {name: data for name, data in _files(root).items() if not name.startswith("src")}
    capsys.readouterr()

    monkeypatch.setenv(ENV, "compact")
    assert main(args) == 0
    compact = root / "compact"
    assert calls.read_text().splitlines()[-1].split() == ["index", str(root / "src"), "--index-dir",
                                                          str(compact / "index")]
    assert Path(f"{calls}.env").read_text().splitlines()[-1].split() == ["compact", str(tmp_path / "codemem-home")]
    meta = json.loads((compact / "index.json").read_text())
    assert list(meta) == MAIN_INDEX_JSON + ["vector_backend"] and meta["vector_backend"] == "compact"
    assert sorted(p.name for p in compact.iterdir()) == ["index", "index.json", "index.log"]
    assert {name: data for name, data in _files(root).items() if not name.startswith(("src", "compact"))} == exact
    assert e2e_index.index_state(recipe, task) == "ok" and e2e_index.index_state(recipe, task, "faiss") == "ok"
    assert capsys.readouterr().out == f"demo: 1 of 1 compact indexes (<task id>/compact/) ready in {root.parent}\n"

    # The same commits: skipped. --force builds the compact index again and deletes only the compact blocks.
    (compact / "block-L0.json").write_text("{}")
    assert main(args) == 0 and len(calls.read_text().splitlines()) == 2
    assert "acme__demo-42: skipped, the compact index exists for codemem" in capsys.readouterr().err
    assert main(args + ["--force"]) == 0 and len(calls.read_text().splitlines()) == 3
    assert not (compact / "block-L0.json").exists() and (root / "block-L0.json").read_text() == "{}"
    # A build of the exact index leaves the compact folder as it was.
    compact_files = _files(compact)
    monkeypatch.delenv(ENV)
    assert main(args + ["--force"]) == 0
    assert not (root / "block-L0.json").exists() and _files(compact) == compact_files
    assert list(json.loads((root / "index.json").read_text())) == MAIN_INDEX_JSON


def test_an_index_of_the_other_form_is_not_ok(make_task, monkeypatch):
    task = make_task()
    root, meta = _fake_index(task)
    (root / "compact" / "index").mkdir(parents=True)
    (root / "compact" / "index.json").write_text(json.dumps(meta))  # an index.json of the exact form
    monkeypatch.setenv(ENV, "compact")
    assert e2e_index.index_state(RECIPE, task) == "another form"
    with pytest.raises(gen.GenerateError, match=r"compact \(another form\); run cmeval e2e index r first"):
        e2e_block.build_blocks(RECIPE, task, {"L0": "q"}, program=Path("/x"), commit=None, search=lambda *a: ANSWER)
    (root / "compact" / "index.json").write_text(json.dumps({**meta, "vector_backend": "compact"}))
    assert e2e_index.index_state(RECIPE, task) == "ok"
    monkeypatch.delenv(ENV)
    assert e2e_index.index_state(RECIPE, task) == "ok"
    (root / "index.json").write_text(json.dumps({**meta, "vector_backend": "compact"}))
    assert e2e_index.index_state(RECIPE, task) == "another form"


def test_compact_blocks_are_beside_the_compact_index(make_task, monkeypatch):
    task = make_task()
    query = task.query.strip()
    root, _ = _fake_index(task)
    exact_block, exact_path = _write_block(task)
    exact_bytes = exact_path.read_bytes()
    meta = _compact_index(task)
    monkeypatch.setenv(ENV, "compact")
    seen = []

    def fake_search(program, src, index, env, args, k, timeout):
        seen.append((src, index.parent.parent, env["CODEMEM_VECTOR_BACKEND"], sorted(p.name for p in index.iterdir())))
        return ANSWER

    made = e2e_block.build_blocks(RECIPE, task, {"L0": query}, program=Path("/x/codemem"), commit=None,
                                  search=fake_search)
    # The search: the task's src/, a copy of the compact index, and codemem told to search with it.
    assert seen == [(root / "src", root / "compact", "compact", ["compact-index.bin"])] and made["L0"][1] is None
    path = root / "compact" / "block-L0.json"
    block = json.loads(path.read_text())
    assert list(block) == MAIN_BLOCK_FILE and block["index"] == meta
    assert e2e_block.read_block(RECIPE, task, "L0", query, None) == (block, path)
    assert exact_path.read_bytes() == exact_bytes
    assert sorted(p.name for p in (root / "compact").iterdir()) == ["block-L0.json", "index", "index.json"]

    # A batch without the switch reads the exact block as before, and refuses a compact block in its place.
    monkeypatch.delenv(ENV)
    assert e2e_block.read_block(RECIPE, task, "L0", query, None) == (exact_block, exact_path)
    shutil.copy(path, exact_path)
    with pytest.raises(gen.GenerateError, match=re.escape(
            "was made on the compact search index, and this batch searches with the faiss one "
            "(CMEVAL_CODEMEM_VECTOR_BACKEND); make it again with cmeval e2e block r --force")):
        e2e_block.read_block(RECIPE, task, "L0", query, None)
    # And a compact batch refuses an exact block in its place.
    monkeypatch.setenv(ENV, "compact")
    path.write_bytes(exact_bytes)
    with pytest.raises(gen.GenerateError, match="was made on the faiss search index, and this batch searches with "
                                                "the compact one"):
        e2e_block.read_block(RECIPE, task, "L0", query, None)


def test_compact_run(make_task, tmp_path, monkeypatch):
    run = _codemem_run(make_task, tmp_path, monkeypatch, backend="compact")
    record, out = run["record"], run["out"]
    assert record["integrity"]["setup_ok"] and not record["discard"] and record["flags"] == []
    # The server of the run is told compact, in the gate's config and in mcp.json; nothing else changes.
    mcp = json.loads((out / "mcp.json").read_text())["mcpServers"]["codemem"]
    gate = json.loads((out / "cmgate.json").read_text())
    assert list(mcp["env"].items()) == list(gate["env"].items()) == list(
        {**MAIN_MCP_ENV, "CODEMEM_VECTOR_BACKEND": "compact"}.items())
    assert gate["argv"][1:2] + gate["argv"][3:] == MAIN_GATE_ARGS and [s["backend"] for s in run["servers"]] == [
        "compact"]
    # The run's copy is of the compact index, and the block is the compact one.
    assert run["seen"]["files"] == ["compact-index.bin"]
    root = e2e_index.task_root(run["recipe"], run["task"])
    codemem, block = record["identity"]["codemem"], record["identity"]["block"]
    assert list(codemem) == MAIN_IDENTITY_CODEMEM[:4] + ["vector_backend"] + MAIN_IDENTITY_CODEMEM[4:]
    assert codemem["vector_backend"] == "compact" and codemem["index"] == run["meta"]
    assert list(block) == MAIN_IDENTITY_BLOCK[:5] + ["vector_backend"] + MAIN_IDENTITY_BLOCK[5:]
    assert block["vector_backend"] == "compact" and block["file"] == str(root / "compact" / "block-L0.json")
    assert record["integrity"]["codemem_warm"]["status"]["search_index"] == {"index": "compact"}
    assert (out / "prompt.txt").read_text().startswith(e2e_block.HEADER)


def test_compact_run_is_discarded_when_codemem_searched_with_another_index(make_task, tmp_path, monkeypatch):
    run = _codemem_run(make_task, tmp_path, monkeypatch, backend="compact", search_index="faiss")
    record = run["record"]
    assert record["discard"] and run["graded"] == [] and record["completed"] is None
    assert record["discard_reason"] == ("setup check failed: codemem searched with the search index faiss, and the "
                                        "batch names compact (CMEVAL_CODEMEM_VECTOR_BACKEND)")


def test_faiss_named_is_the_exact_form_and_the_record_says_so(make_task, tmp_path, monkeypatch):
    run = _codemem_run(make_task, tmp_path, monkeypatch, backend="faiss")
    record, out = run["record"], run["out"]
    assert record["integrity"]["setup_ok"] and not record["discard"]
    mcp = json.loads((out / "mcp.json").read_text())["mcpServers"]["codemem"]
    assert list(mcp["env"].items()) == list(MAIN_MCP_ENV.items())
    root = e2e_index.task_root(run["recipe"], run["task"])
    assert record["identity"]["codemem"]["vector_backend"] == "faiss"
    assert record["identity"]["block"]["vector_backend"] == "faiss"
    assert record["identity"]["block"]["file"] == str(root / "block-L0.json")
    assert run["seen"]["files"] == ["index.sqlite", "vectors", "vectors/code.faiss"]


def test_codemem_checks_of_the_search_index():
    fallbacks = {"first": None, "first_keywords_only": False}
    warm = {"ok": True, "status": {"state": "ready", "search_index": {"setting": "faiss", "index": "faiss"}}}
    assert e2e_run.codemem_checks(warm, fallbacks) == e2e_run.codemem_checks(warm, fallbacks, "faiss") == []
    assert e2e_run.codemem_checks(warm, fallbacks, "compact") == [
        "codemem searched with the search index faiss, and the batch names compact (CMEVAL_CODEMEM_VECTOR_BACKEND)"]
    silent = {"ok": True, "status": {"state": "ready"}}  # an index_status without search_index
    assert e2e_run.codemem_checks(silent, fallbacks) == []
    assert e2e_run.codemem_checks(silent, fallbacks, "compact") == [
        "codemem searched with the search index None, and the batch names compact (CMEVAL_CODEMEM_VECTOR_BACKEND)"]
    assert e2e_run.codemem_checks({"ok": False, "error": "x"}, fallbacks, "compact") == [
        "codemem warm-up failed: x"]


def test_a_bad_value_is_refused_before_anything_is_built_or_run(remote, make_task, tmp_path, monkeypatch, capsys):
    args, recipe, task, calls = _index_setup(remote, make_task, tmp_path, monkeypatch)
    monkeypatch.setenv(ENV, "exact")
    assert main(args) == 1 and BAD in capsys.readouterr().err and not calls.exists()
    assert main(["e2e", "block", args[2], "--tasks", args[4], "--prompt-level", "L0"]) == 1
    assert BAD in capsys.readouterr().err
    for setup in ("grep", "tool"):
        assert main(["e2e", "run", args[2], "--tasks", args[4], "--run-id", "x", "--setup", setup, "--dry-run"]) == 1
        assert BAD in capsys.readouterr().err
    with pytest.raises(gen.GenerateError, match=re.escape(BAD)):
        e2e_run.run_batch(recipe, [task], run_id="x", setups=["grep"], model=MODEL)
    out = tmp_path / "out"
    with pytest.raises(gen.GenerateError, match=re.escape(BAD)):
        e2e_run.run_one(recipe, task, setup="grep", model=MODEL, rep=1, out=out)
    assert not out.exists() and not (e2e_dir() / "runs").exists()
    assert main(["e2e", "replay", "none", "--records-only", "--out", str(tmp_path / "replay.json")]) == 1
    assert BAD in capsys.readouterr().err


def test_replay_takes_the_search_index_of_each_run(make_task, tmp_path, monkeypatch):
    monkeypatch.setattr(e2e_replay, "READY_POLL_S", 0.01)
    task = make_task()
    runs = e2e_dir() / "runs"
    for run_id in ("x0", "c0"):
        _write_run(runs / run_id / task.id / "tool" / "1", task, level="L0", args={"query": "revoke", "k": 5},
                   text=_render(5))
    path = runs / "c0" / task.id / "tool" / "1" / "run.json"
    record = json.loads(path.read_text())
    record["identity"]["codemem"]["vector_backend"] = "compact"
    write_json(path, record)
    task_dir = e2e_dir() / "indexes" / "demo" / task.id
    metas = {}
    for root, form in ((task_dir, {}), (task_dir / "compact", {"vector_backend": "compact"})):
        (root / "index").mkdir(parents=True)
        (root / "index" / "store.db").write_text(root.name)
        metas[root.name] = {"task_id": task.id, "base_commit": task.base_commit, "codemem_commit": "abc", **form}
        write_json(root / "index.json", metas[root.name])
    (task_dir / "src").mkdir()
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps(task.to_dict()) + "\n")
    program = tmp_path / "fake" / ".venv" / "bin" / "codemem"
    program.parent.mkdir(parents=True)
    _program(program, FAKE)
    log = tmp_path / "fake.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    out = tmp_path / "out" / "replay.json"

    summary, _, _ = e2e_replay.replay(["x0", "c0"], ks=[5], tasks_files=[tasks], program=program, out=out)
    exact, compact = summary["runs"]
    assert list(exact) == MAIN_REPLAY_ENTRY and compact["vector_backend"] == "compact"
    assert exact["replay"]["index"] == metas[task.id] and compact["replay"]["index"] == metas["compact"]
    assert exact["check"]["verdict"].startswith("same") and compact["check"]["verdict"].startswith("same")
    servers = [json.loads(line) for line in log.read_text().splitlines() if '"mcp"' in line]
    assert sorted(s["backend"] for s in servers) == ["compact", "faiss"]
    assert all(s["argv"][1] == str(task_dir / "src") for s in servers)
    assert sorted(p.name for p in (out.parent / "replay-logs").iterdir()) == [f"{task.id}-default-compact.log",
                                                                             f"{task.id}-default.log"]
    assert summary["warnings"] == [] and summary["codemem"]["env"]["CODEMEM_VECTOR_BACKEND"] == "faiss"
    assert [(task_dir / f / "index" / "store.db").read_text() for f in ("", "compact")] == [task.id, "compact"]

    # A replay of the compact runs alone shows the environment that their codemem got.
    summary, _, _ = e2e_replay.replay(["c0"], ks=[5], tasks_files=[tasks], program=program, out=out)
    assert summary["codemem"]["env"]["CODEMEM_VECTOR_BACKEND"] == "compact" and summary["warnings"] == []
    # The variable does not change a replay, and the replay says so.
    monkeypatch.setenv(ENV, "compact")
    summary, _, _ = e2e_replay.replay(["x0", "c0"], ks=[5], tasks_files=[tasks], records_only=True, out=out)
    assert summary["warnings"] == ["CMEVAL_CODEMEM_VECTOR_BACKEND is compact, which does not change a replay: 1 runs "
                                   "were made on another search index, and are replayed on it"]
    monkeypatch.delenv(ENV)
    # A compact run whose compact index is missing, or holds the exact form, is not replayed.
    write_json(task_dir / "compact" / "index.json", metas[task.id])
    summary, _, _ = e2e_replay.replay(["c0"], ks=[5], tasks_files=[tasks], program=program, out=out)
    assert summary["runs"][0]["replay"]["error"] == (f"the index at {task_dir / 'compact'} holds the faiss search "
                                                     "index, not the compact one of the runs")
    (task_dir / "compact" / "index.json").unlink()
    summary, _, _ = e2e_replay.replay(["c0"], ks=[5], tasks_files=[tasks], program=program, out=out)
    assert summary["runs"][0]["replay"]["error"] == (
        f"no compact index at {task_dir / 'compact'} (index/ and index.json, and src/ in {task_dir}); run cmeval e2e "
        "index demo with CMEVAL_CODEMEM_VECTOR_BACKEND=compact")


def test_cli_block_and_dry_run_with_compact(make_task, tmp_path, monkeypatch, capsys):
    recipe_file = tmp_path / "r.toml"
    recipe_file.write_text('repo = "acme/auth"\nbase_image = "x"\ntest = "pytest"\n')
    task = make_task()
    task_file = tmp_path / "tasks.jsonl"
    save_tasks(task_file, [task])
    gen.task_dir(RECIPE, task).mkdir(parents=True)
    gen.tests_path(RECIPE, task).write_text("{}")
    root, _ = _fake_index(task)
    program = tmp_path / "blocks" / ".venv" / "bin" / "codemem"
    program.parent.mkdir(parents=True)
    _shim(program.parent, "codemem", "#!/bin/sh\nexit 9\n")  # never run: the fake search stands in for it
    monkeypatch.setenv("CMEVAL_CODEMEM_BIN", str(program))
    asked = []

    def fake_search(program, src, index, env, args, k, timeout, signals=None):
        asked.append((index.parent.parent.name, env["CODEMEM_VECTOR_BACKEND"]))
        return ANSWER

    monkeypatch.setattr(e2e_replay, "cli_search_json", fake_search)
    args = ["e2e", "block", str(recipe_file), "--tasks", str(task_file), "--prompt-level", "L0"]
    monkeypatch.setenv(ENV, "compact")
    assert main(args) == 1 and asked == []  # no compact index yet
    assert "(missing); run cmeval e2e index r first" in capsys.readouterr().err
    _compact_index(task)
    assert main(args) == 0 and asked == [("compact", "compact")]
    assert capsys.readouterr().out == f"r: 1 of 1 blocks ready beside the compact indexes (<task id>/compact/) in " \
                                      f"{root.parent}\n"
    assert (root / "compact" / "block-L0.json").exists() and not (root / "block-L0.json").exists()
    assert main(args) == 0 and len(asked) == 1  # skipped: a run can use it
    monkeypatch.delenv(ENV)
    assert main(args) == 0 and asked[1:] == [(task.id, "faiss")]
    assert capsys.readouterr().out.endswith(f"blocks ready beside the indexes in {root.parent}\n")
    assert (root / "block-L0.json").exists() and (root / "compact" / "block-L0.json").exists()

    # The dry run of a batch shows the state of the index of its own form.
    _codemem_install(tmp_path, monkeypatch, RECIPE, task)  # writes the exact index.json again
    dry = ["e2e", "run", str(recipe_file), "--tasks", str(task_file), "--run-id", "d1", "--setup", "tool",
           "--dry-run"]
    assert main(dry) == 0 and capsys.readouterr().out.splitlines()[0] == f"{task.id} tool 1 todo index ok"
    monkeypatch.setenv(ENV, "compact")
    assert main(dry) == 0 and capsys.readouterr().out.splitlines()[0] == f"{task.id} tool 1 todo index ok"
    (root / "compact" / "index.json").write_text(json.dumps({"base_commit": task.base_commit}))
    assert main(dry) == 0 and capsys.readouterr().out.splitlines()[0] == f"{task.id} tool 1 todo index another form"
