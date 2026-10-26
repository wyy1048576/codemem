import json

import pytest

from cmeval.cli import main
from cmeval.subset import SubsetError, draw, subset
from cmeval.tasks import Fix, load_tasks, save_tasks


@pytest.fixture
def source(tmp_path, make_task):
    """12 dev tasks in acme/a (8 all-Python), 3 in acme/b, and 2 test tasks."""
    tasks = []
    for i in range(12):
        tasks.append(make_task(id=f"acme__a-{i}", repo="acme/a", fix=Fix(pr_number=i), split="dev",
                               tags={"gold_all_python": i < 8}))
    for i in range(3):
        tasks.append(make_task(id=f"acme__b-{100 + i}", repo="acme/b", fix=Fix(pr_number=100 + i), split="dev",
                               tags={"gold_all_python": True}))
    for i in range(2):
        tasks.append(make_task(id=f"acme__a-{200 + i}", repo="acme/a", fix=Fix(pr_number=200 + i), split="test",
                               tags={"gold_all_python": True}))
    path = tmp_path / "tasks.jsonl"
    save_tasks(path, tasks)
    return path


def test_the_draw_is_fixed_by_the_seed_and_per_repo():
    ids = [f"x-{i}" for i in range(20)]
    assert draw(ids, 5, "s1", "acme/a") == draw(list(reversed(ids)), 5, "s1", "acme/a")  # input order does not matter
    assert draw(ids, 5, "s1", "acme/a") != draw(ids, 5, "s2", "acme/a")
    assert draw(ids[:3], 5, "s1", "acme/a") == ids[:3]  # fewer than n: all of them
    assert draw(ids, 5, "s1", "acme/a") != draw(ids, 5, "s1", "acme/b")  # each repo has its own draw


def test_subset_writes_tasks_and_meta(source, tmp_path):
    out = tmp_path / "sub.jsonl"
    result = subset(source, out, per_repo=5, seed="s1", where=["gold_all_python=true"])
    tasks = load_tasks(out)
    assert sorted({t.repo for t in tasks}) == ["acme/a", "acme/b"]
    assert sum(t.repo == "acme/a" for t in tasks) == 5 and sum(t.repo == "acme/b" for t in tasks) == 3
    assert all(t.split == "dev" and t.tags["gold_all_python"] for t in tasks)
    assert result.available == {"acme/a": 8, "acme/b": 3} and result.short == ["acme/b"]
    meta = json.loads(out.with_suffix(".meta.json").read_text())
    assert meta["seed"] == "s1" and meta["per_repo"] == 5 and meta["where"] == ["gold_all_python=true"]
    assert meta["chosen"] == {"acme/a": 5, "acme/b": 3} and len(meta["source_sha256"]) == 64
    again = tmp_path / "again.jsonl"
    subset(source, again, per_repo=5, seed="s1", where=["gold_all_python=true"])
    assert again.read_bytes() == out.read_bytes()  # the same inputs give the same file


def test_repos_limit_the_draw(source, tmp_path):
    result = subset(source, tmp_path / "sub.jsonl", per_repo=2, seed="s1", repos=["acme/b"])
    assert {t.repo for t in result.tasks} == {"acme/b"} and len(result.tasks) == 2


def test_repo_order_and_case_do_not_change_the_file(source, tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    subset(source, a, per_repo=2, seed="s1", repos=["acme/a", "acme/b"])
    subset(source, b, per_repo=2, seed="s1", repos=["ACME/B", "acme/a", "acme/b"])
    assert a.read_bytes() == b.read_bytes()


def test_subset_never_writes_over_its_source(source):
    before = source.read_bytes()
    with pytest.raises(SubsetError, match="write over the source"):
        subset(source, source, per_repo=2, seed="s1")
    with pytest.raises(SubsetError, match="write over the source"):
        subset(source, source.with_suffix(".json"), per_repo=2, seed="s1")  # same meta file name
    assert source.read_bytes() == before


def test_subset_refusals(source, tmp_path):
    with pytest.raises(SubsetError, match="no task matches"):
        subset(source, tmp_path / "x.jsonl", per_repo=2, seed="s1", where=["language=rust"])
    with pytest.raises(SubsetError, match="no task has"):
        subset(source, tmp_path / "x.jsonl", per_repo=2, seed="s1", where=["gold_python=true"])
    with pytest.raises(SubsetError, match="no matching dev task in"):
        subset(source, tmp_path / "x.jsonl", per_repo=2, seed="s1", repos=["acme/nope"])
    with pytest.raises(SubsetError, match="per_repo"):
        subset(source, tmp_path / "x.jsonl", per_repo=0, seed="s1")


def test_cli_subset(source, tmp_path, capsys):
    out = tmp_path / "sub.jsonl"
    assert main(["subset", str(source), "--out", str(out), "--per-repo", "5", "--seed", "s1",
                 "--where", "gold_all_python=true"]) == 0
    printed = capsys.readouterr().out
    assert "8 tasks" in printed and "acme/b: 3 of 3 matching tasks  (fewer than asked)" in printed
    assert main(["subset", str(source), "--out", str(out), "--per-repo", "5", "--seed", "s1", "--where", "bad"]) == 1
