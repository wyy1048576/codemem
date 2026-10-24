import json

import pytest
from conftest import REMOTE_REPO

from cmeval.cli import main
from cmeval.merge import MergeError, merge
from cmeval.paths import runs_dir
from cmeval.report import report
from cmeval.run import run
from cmeval.score import score
from cmeval.tasks import Fix, Gold, save_tasks

BASE = '[[system]]\nname = "fake-a"\nadapter = "fake"\n\n[[system]]\nname = "fake-b"\nadapter = "fake"\n'
EXTRA = '[[system]]\nname = "fake-c"\nadapter = "fake"\n\n[[system]]\nname = "fake-a"\nadapter = "fake"\n'


class CharCounter:
    name = "chars"
    estimate = False

    def count(self, texts):
        return [len(t) for t in texts]


@pytest.fixture
def runs(remote, tmp_path, make_task):
    """Run "base" (fake-a, fake-b) and run "extra" (fake-c, fake-a) on the same 3 tasks."""
    tasks = [make_task(id=f"acme__demo-{n}", repo=REMOTE_REPO, base_commit=sha, split="dev", fix=Fix(pr_number=n),
                       gold=Gold(files=["app.py"]), query="which version") for n, sha in enumerate(remote.shas, 1)]
    tasks_file = tmp_path / "tasks.jsonl"
    save_tasks(tasks_file, tasks)
    configs = {}
    for name, text in (("base", BASE), ("extra", EXTRA)):
        configs[name] = tmp_path / f"{name}.toml"
        configs[name].write_text(text)
        run(tasks_file, configs[name], name)
    return tasks_file, configs


def lines(run_id, system):
    return [json.loads(l) for l in (runs_dir() / run_id / f"{system}.jsonl").read_text().splitlines()]


def test_merge_adds_the_new_systems_and_keeps_both_runs(runs):
    before = {name: (runs_dir() / "base" / f"{name}.jsonl").read_bytes() for name in ("fake-a", "fake-b")}
    new_dir = merge("base", "extra", "merged")
    meta = json.loads((new_dir / "meta.json").read_text())
    assert [s["name"] for s in meta["systems"]] == ["fake-a", "fake-b", "fake-c"]  # fake-a stays the base one
    assert [p["run_id"] for p in meta["merged_from"]] == ["base", "extra"]
    assert meta["merged_from"][1]["systems"] == ["fake-c"] and meta["status"] == "done"
    assert lines("merged", "fake-c") == lines("extra", "fake-c")
    for name, data in before.items():
        assert (new_dir / f"{name}.jsonl").read_bytes() == data == (runs_dir() / "base" / f"{name}.jsonl").read_bytes()
    assert {r["system"] for r in [json.loads(l) for l in (new_dir / "index.jsonl").read_text().splitlines()]} == {
        "fake-a", "fake-b", "fake-c"}
    assert not (new_dir / "scores.jsonl").exists()  # score it next


def test_a_merged_run_can_be_scored_and_reported(runs):
    merge("base", "extra", "merged")
    summary = score("merged", counter=CharCounter())
    assert summary.tasks_scored == 3 and {r["system"] for r in summary.table} == {"fake-a", "fake-b", "fake-c"}
    result = report("merged", baseline="fake-a", primary=["fake-b", "fake-c"], resamples=200)
    text = result.report_path.read_text()
    assert "Merged part: fake-c from run `extra`" in text and "merged from separate runs" in text
    assert not any("sessions" in w for w in result.warnings)  # the parts are listed instead


def test_merge_refusals(runs, tmp_path, make_task):
    tasks_file, configs = runs
    with pytest.raises(MergeError, match="in both runs"):
        merge("base", "extra", "m1", systems=["fake-a"])
    with pytest.raises(MergeError, match="not in run extra"):
        merge("base", "extra", "m1", systems=["nope"])
    with pytest.raises(MergeError, match="no system that is not in"):
        merge("base", "base", "m1")
    merge("base", "extra", "m1")
    with pytest.raises(MergeError, match="exists already"):
        merge("base", "extra", "m1")
    with pytest.raises(MergeError, match="may only use"):
        merge("base", "extra", "bad id")
    run(tasks_file, configs["extra"], "short", limit_per_repo=1)  # only 1 of the 3 tasks
    with pytest.raises(MergeError, match="2 tasks of base are missing"):
        merge("base", "short", "m2")
    meta_path = runs_dir() / "extra" / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta_path.write_text(json.dumps({**meta, "k": 10}))
    with pytest.raises(MergeError, match="different k"):
        merge("base", "extra", "m3")
    meta_path.write_text(json.dumps({**meta, "index_mode": "rebuild"}))
    with pytest.raises(MergeError, match="different index_mode"):
        merge("base", "extra", "m5")
    meta_path.write_text(json.dumps({**meta, "status": "failed"}))
    with pytest.raises(MergeError, match="only finished runs"):
        merge("base", "extra", "m4")
    assert not (runs_dir() / "m2").exists() and not (runs_dir() / "m4").exists()  # nothing half made


def test_cli_merge(runs, capsys):
    assert main(["merge", "base", "extra", "--run-id", "merged"]) == 0
    out = capsys.readouterr().out
    assert "systems: fake-a, fake-b, fake-c" in out and "cmeval score merged" in out
    assert main(["merge", "base", "extra", "--run-id", "merged"]) == 1


def test_a_mixed_part_of_a_merged_run_is_still_flagged(runs):
    path = runs_dir() / "base" / "meta.json"
    meta = json.loads(path.read_text())
    meta["sessions"] = [{"cmeval_git": {"sha": "a" * 40}, "machine": {"platform": "mac"}},
                        {"cmeval_git": {"sha": "a" * 40}, "machine": {"platform": "windows"}}]
    path.write_text(json.dumps(meta))
    merge("base", "extra", "merged")
    score("merged", counter=CharCounter())
    warnings = report("merged", baseline="fake-a", primary=["fake-b", "fake-c"], resamples=200).warnings
    assert [w for w in warnings if "sessions" in w] == [
        "run base was made in 2 sessions with different code or machines: mac at aaaaaaaaaaaa; windows at aaaaaaaaaaaa"]
