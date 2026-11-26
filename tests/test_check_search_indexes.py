"""scripts/check_search_indexes.py: which task file it takes its questions from."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_search_indexes.py"


@pytest.fixture
def check(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_search_indexes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tasks = tmp_path / "eval" / "tasks"
    tasks.mkdir(parents=True)

    def write(name, rows):
        (tasks / name).write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")

    task = lambda i, repo, split="dev": {"id": f"t{i}", "repo": repo, "split": split, "query": f"question {i}"}  # noqa: E731
    write("small.jsonl", [task(1, "a/one"), task(2, "b/two")])
    write("large.jsonl", [task(3, "a/one"), task(4, "a/one", "test"), task(5, "b/two")])
    # a file of another kind, as eval/tasks holds them: prompt texts for tasks, with no repo and no query
    write("prompts.jsonl", [{"id": "t1", "level": "L1", "prompt": "a text"}])
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


def test_the_default_task_file_is_the_one_with_the_most_tasks_for_the_repo(check):
    assert check.task_file("a/one", None).name == "large.jsonl"
    assert check.task_file("a/one", "small").name == "small.jsonl"


def test_a_repo_no_task_file_knows_ends_with_the_repos_they_know(check):
    with pytest.raises(SystemExit) as stop:
        check.task_file("c/three", None)
    assert "a/one, b/two" in str(stop.value)


def test_a_file_of_another_kind_holds_no_question(check):
    assert check.questions(check.task_file("a/one", "prompts"), "a/one", 0) == []
    rows = check.questions(check.task_file("a/one", None), "a/one", 0)
    assert [(r["id"], r["split"], r["n"]) for r in rows] == [("t3", "dev", 0), ("t4", "test", 1)]
