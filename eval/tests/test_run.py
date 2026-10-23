import json
from pathlib import Path

import pytest
from conftest import REMOTE_REPO

from cmeval import repos
from cmeval import run as run_module
from cmeval.adapters.fake import FakeRetriever
from cmeval.files import FileLock, drop_unfinished_line
from cmeval.metrics.latency import index_costs
from cmeval.cli import main
from cmeval.paths import indexes_dir, runs_dir, worktrees_dir
from cmeval.run import RunError, run
from cmeval.tasks import Fix, Gold, save_tasks

CONFIG = """
[[system]]
name = "fake-a"
adapter = "fake"

[[system]]
name = "fake-b"
adapter = "fake"
granularity = "file"

[[system]]
name = "fake-go"
adapter = "fake"
suffix = ".go"
"""


@pytest.fixture
def setup(remote, tmp_path, monkeypatch, make_task):
    """3 dev tasks whose commit dates are out of ID order, 1 test task, a config, and a record of every system made."""
    shas = []
    for i, date in enumerate(["2021-01-03T00:00:00", "2021-01-01T00:00:00", "2021-01-02T00:00:00"]):
        monkeypatch.setenv("GIT_COMMITTER_DATE", date)
        shas.append(remote.commit({"app.py": f"VERSION = {10 + i}\nversion_name = 'v{i}'\n"}))
    monkeypatch.delenv("GIT_COMMITTER_DATE")

    def task(n, sha, split="dev"):
        return make_task(id=f"acme__demo-{n}", repo=REMOTE_REPO, base_commit=sha, split=split,
                         fix=Fix(pr_number=n), gold=Gold(files=["app.py"]), query="which version")

    tasks_file = tmp_path / "tasks.jsonl"
    save_tasks(tasks_file, [task(1, shas[0]), task(2, shas[1]), task(3, shas[2]), task(9, shas[0], split="test")])
    config_file = tmp_path / "systems.toml"
    config_file.write_text(CONFIG)

    made = {}
    real = run_module.make_system

    def record(spec):
        made[spec.name] = real(spec)
        return made[spec.name]

    monkeypatch.setattr(run_module, "make_system", record)
    return tasks_file, config_file, made


def lines(run_id, system):
    return [json.loads(l) for l in (runs_dir() / run_id / f"{system}.jsonl").read_text().splitlines()]


def test_run_writes_files_in_commit_date_order(setup):
    tasks_file, config_file, made = setup
    summary = run(tasks_file, config_file, "r1")
    assert (summary.tasks, summary.systems, summary.searched, summary.skipped) == (3, 3, 9, 0)
    for name in ("fake-a", "fake-b", "fake-go"):
        assert [l["task_id"] for l in lines("r1", name)] == ["acme__demo-2", "acme__demo-3", "acme__demo-1"]
    first = lines("r1", "fake-a")[0]
    assert first["hits"][0]["path"] == "app.py" and first["search_ms"] >= 0
    meta = json.loads((runs_dir() / "r1" / "meta.json").read_text())
    assert meta["status"] == "done" and meta["split"] == "dev" and len(meta["systems"]) == 3
    assert meta["systems"][0]["index_key"] == meta["systems"][1]["index_key"] != meta["systems"][2]["index_key"]
    assert not (indexes_dir() / "r1").exists()  # deleted at the end
    assert not any("@live-run-r1" in p.name for p in worktrees_dir().iterdir())  # worktree removed


def test_shared_index_is_built_once_and_updated_after(setup):
    tasks_file, config_file, made = setup
    run(tasks_file, config_file, "r1")
    index = [json.loads(l) for l in (runs_dir() / "r1" / "index.jsonl").read_text().splitlines()]
    first_task = [(r["system"], r["mode"]) for r in index if r["task_id"] == "acme__demo-2"]
    assert first_task == [("fake-a", "build"), ("fake-b", "update"), ("fake-go", "build")]
    assert all(r["mode"] == "update" for r in index if r["task_id"] != "acme__demo-2")
    a, b = made["fake-a"], made["fake-b"]
    assert (a.calls.count("build"), a.calls.count("update")) == (1, 2)
    assert (b.calls.count("build"), b.calls.count("update")) == (0, 3)
    assert a.calls.count("search") == 4  # 3 tasks + 1 untimed warm-up


def test_rebuild_mode_builds_for_every_task(setup):
    tasks_file, config_file, made = setup
    run(tasks_file, config_file, "r1", index_mode="rebuild")
    assert made["fake-a"].calls.count("build") == 3 and made["fake-b"].calls.count("build") == 0


def test_test_split_needs_to_be_asked_for(setup):
    tasks_file, config_file, _ = setup
    run(tasks_file, config_file, "rt", split="test")
    assert [l["task_id"] for l in lines("rt", "fake-a")] == ["acme__demo-9"]


def test_resume_continues_without_duplicates(setup):
    tasks_file, config_file, made = setup
    run(tasks_file, config_file, "r1", limit_per_repo=1)
    assert [l["task_id"] for l in lines("r1", "fake-a")] == ["acme__demo-2"]
    summary = run(tasks_file, config_file, "r1")
    assert (summary.searched, summary.skipped) == (6, 3)
    assert [l["task_id"] for l in lines("r1", "fake-a")] == ["acme__demo-2", "acme__demo-3", "acme__demo-1"]
    assert json.loads((runs_dir() / "r1" / "meta.json").read_text())["resumed"] == 1


def test_resume_after_a_hard_stop(setup):
    """A power loss during a write and a stop during a checkout: the next run cleans up and finishes."""
    tasks_file, config_file, _ = setup
    run(tasks_file, config_file, "r1", limit_per_repo=1, keep_indexes=True)
    with (runs_dir() / "r1" / "fake-a.jsonl").open("a") as f:
        f.write('{"task_id": "acme__demo-3", "hi')  # unfinished line
    live = repos.checkout(REMOTE_REPO, lines("r1", "fake-b")[0]["commit"], name="run-r1")
    (live / "half-checked-out.py").write_text("")  # move_to refuses a worktree with changes
    git_dir = Path(repos._git("rev-parse", "--absolute-git-dir", cwd=live).stdout.strip())
    (git_dir / "index.lock").write_text("")
    run(tasks_file, config_file, "r1")
    for name in ("fake-a", "fake-b", "fake-go"):
        assert [l["task_id"] for l in lines("r1", name)] == ["acme__demo-2", "acme__demo-3", "acme__demo-1"]
    assert not live.exists()


def test_a_stopped_build_is_built_again(setup, monkeypatch):
    tasks_file, config_file, _ = setup
    real_build = FakeRetriever.build

    def stopped(self, repo, index_dir):
        real_build(self, repo, index_dir)
        raise KeyboardInterrupt  # stopped after the index folder exists, before its row is written

    monkeypatch.setattr(FakeRetriever, "build", stopped)
    with pytest.raises(KeyboardInterrupt):
        run(tasks_file, config_file, "r1")
    leftover = next((indexes_dir() / "r1" / "acme__demo").iterdir()) / "left-by-the-stopped-build"
    leftover.write_text("")
    monkeypatch.setattr(FakeRetriever, "build", real_build)
    run(tasks_file, config_file, "r1")
    index = [json.loads(l) for l in (runs_dir() / "r1" / "index.jsonl").read_text().splitlines()]
    first_task = [(r["system"], r["mode"]) for r in index if r["task_id"] == "acme__demo-2"]
    assert first_task == [("fake-a", "build"), ("fake-b", "update"), ("fake-go", "build")]
    assert not leftover.exists()  # built again from an empty folder


def index_rows(run_id):
    return [json.loads(l) for l in (runs_dir() / run_id / "index.jsonl").read_text().splitlines()]


def test_a_stopped_update_is_marked_and_left_out_of_latency(setup, monkeypatch):
    tasks_file, config_file, _ = setup
    run(tasks_file, config_file, "r1", limit_per_repo=1, keep_indexes=True)
    real_update = FakeRetriever.update

    def stopped(self, repo, index_dir):
        real_update(self, repo, index_dir)
        raise KeyboardInterrupt  # stopped during the update for the second task

    monkeypatch.setattr(FakeRetriever, "update", stopped)
    with pytest.raises(KeyboardInterrupt):
        run(tasks_file, config_file, "r1", keep_indexes=True)
    monkeypatch.setattr(FakeRetriever, "update", real_update)
    run(tasks_file, config_file, "r1")
    rows = [r for r in index_rows("r1") if r["system"] == "fake-a"]
    assert [(r["task_id"], r["mode"], r.get("resumed", False)) for r in rows] == [
        ("acme__demo-2", "build", False), ("acme__demo-3", "update", True), ("acme__demo-1", "update", False),
    ]
    by_task = {r["task_id"]: r["report"]["seconds"] for r in rows}
    assert index_costs(rows, "fake-a")["update_seconds_median"] == by_task["acme__demo-1"]  # the resumed row is left out


def test_an_update_after_a_finished_build_counts_once(setup, monkeypatch):
    tasks_file, config_file, _ = setup
    real_search = FakeRetriever.search

    def stopped(self, query, k):
        if query == "which version":
            raise KeyboardInterrupt  # stopped after the build row, before the first timed search
        return real_search(self, query, k)

    monkeypatch.setattr(FakeRetriever, "search", stopped)
    with pytest.raises(KeyboardInterrupt):
        run(tasks_file, config_file, "r1")
    monkeypatch.setattr(FakeRetriever, "search", real_search)
    run(tasks_file, config_file, "r1")
    rows = [r for r in index_rows("r1") if r["system"] == "fake-a"]
    assert [(r["task_id"], r["mode"]) for r in rows][:2] == [("acme__demo-2", "build"), ("acme__demo-2", "update")]
    updates = sorted(r["report"]["seconds"] for r in rows if r["task_id"] != "acme__demo-2")
    costs = index_costs(rows, "fake-a")
    assert costs["build_seconds_mean"] == rows[0]["report"]["seconds"]
    assert costs["update_seconds_median"] == pytest.approx(sum(updates) / 2)  # the repeat for demo-2 is left out


def test_a_second_process_on_the_same_run_id_is_refused(setup):
    tasks_file, config_file, _ = setup
    (runs_dir() / "r1").mkdir(parents=True)
    other = FileLock(runs_dir() / "r1" / "run.lock")
    assert other.acquire()  # another process works on r1
    with pytest.raises(RunError, match="in use by another cmeval process"):
        run(tasks_file, config_file, "r1")
    other.release()
    assert run(tasks_file, config_file, "r1").searched == 9


def test_resume_with_other_code_is_refused(setup, monkeypatch):
    tasks_file, config_file, _ = setup
    run(tasks_file, config_file, "r1", limit_per_repo=1)
    real_git = run_module._eval_git
    monkeypatch.setattr(run_module, "_eval_git", lambda: {"sha": "0" * 40, "dirty": False})
    with pytest.raises(RunError, match="other inputs \\(cmeval code\\)"):
        run(tasks_file, config_file, "r1")
    monkeypatch.setattr(run_module, "_eval_git", real_git)
    real_key = FakeRetriever.index_key
    monkeypatch.setattr(FakeRetriever, "index_key", lambda self: "other-device")
    with pytest.raises(RunError, match="system code or index settings"):
        run(tasks_file, config_file, "r1")
    monkeypatch.setattr(FakeRetriever, "index_key", real_key)
    run(tasks_file, config_file, "r1")
    meta = json.loads((runs_dir() / "r1" / "meta.json").read_text())
    assert len(meta["sessions"]) == 2 and all("machine" in s and "cmeval_git" in s for s in meta["sessions"])


def test_a_cleanup_error_keeps_the_real_error(setup, monkeypatch):
    tasks_file, config_file, _ = setup

    def cannot_remove(worktree):
        raise repos.RepoError("worktree is locked")

    monkeypatch.setattr(run_module.repos, "remove_worktree", cannot_remove)
    monkeypatch.setattr(run_module.repos, "head", lambda worktree: "0" * 40)
    with pytest.raises(RunError, match="worktree is at 0000"):
        run(tasks_file, config_file, "r1")
    assert "worktree is at" in json.loads((runs_dir() / "r1" / "meta.json").read_text())["error"]


def test_drop_unfinished_line(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_bytes(b"")
    assert not drop_unfinished_line(path)
    path.write_bytes(b'{"a": 1}\n')
    assert not drop_unfinished_line(path) and path.read_bytes() == b'{"a": 1}\n'
    path.write_bytes(b'{"a": 1}\n{"b"')
    assert drop_unfinished_line(path) and path.read_bytes() == b'{"a": 1}\n'
    path.write_bytes(b'{"b"')
    assert drop_unfinished_line(path) and path.read_bytes() == b""
    assert not drop_unfinished_line(tmp_path / "missing.jsonl")


def test_resume_with_other_inputs_is_refused(setup):
    tasks_file, config_file, _ = setup
    run(tasks_file, config_file, "r1", limit_per_repo=1)
    config_file.write_text(CONFIG + "\n# changed\n")
    with pytest.raises(RunError, match="exists with other inputs .*config_sha256"):
        run(tasks_file, config_file, "r1")
    config_file.write_text(CONFIG)  # same config again; another index mode is still refused
    with pytest.raises(RunError, match=r"other inputs \(index_mode\)"):
        run(tasks_file, config_file, "r1", index_mode="rebuild")


def test_leak_check_stops_the_run(setup, monkeypatch):
    tasks_file, config_file, _ = setup
    monkeypatch.setattr(run_module.repos, "head", lambda worktree: "0" * 40)
    with pytest.raises(RunError, match="worktree is at 0000"):
        run(tasks_file, config_file, "r1")
    meta = json.loads((runs_dir() / "r1" / "meta.json").read_text())
    assert meta["status"] == "failed" and "worktree is at" in meta["error"]


def test_broken_hit_contract_stops_the_run(setup):
    tasks_file, config_file, _ = setup
    config_file.write_text('[[system]]\nname = "bad"\nadapter = "fake"\nscript = { "which version" = [ { path = "app.py" } ] }\n')
    with pytest.raises(RunError, match="bad: hit 0 .*without line numbers"):
        run(tasks_file, config_file, "r1")


def test_keep_indexes(setup):
    tasks_file, config_file, _ = setup
    run(tasks_file, config_file, "r1", keep_indexes=True)
    assert (indexes_dir() / "r1" / "acme__demo").is_dir()


def test_bad_run_id_and_index_mode(setup):
    tasks_file, config_file, _ = setup
    with pytest.raises(RunError, match="run id"):
        run(tasks_file, config_file, "has space")
    with pytest.raises(RunError, match="index mode"):
        run(tasks_file, config_file, "r1", index_mode="sometimes")


def test_cli_run(setup, capsys):
    tasks_file, _, _ = setup
    smoke = Path(__file__).parents[1] / "configs" / "smoke.toml"
    assert main(["run", "--tasks", str(tasks_file), "--config", str(smoke), "--run-id", "cli1"]) == 0
    out = capsys.readouterr()
    assert "3 tasks x 2 systems: 6 searches done" in out.out and "[repo 1/1] acme/demo" in out.err
    assert main(["run", "--tasks", str(tasks_file), "--config", str(smoke), "--run-id", "bad id"]) == 1
