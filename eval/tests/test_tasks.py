import json
import os
from dataclasses import replace

import pytest

from cmeval.tasks import (
    Gold,
    Span,
    Task,
    TaskError,
    assign_split,
    dumps,
    load_tasks,
    save_tasks,
    select,
    validate,
)


def test_valid_task_has_no_problems(make_task):
    assert validate(make_task()) == []


def test_round_trip_and_stable_bytes(make_task, tmp_path):
    tasks = [make_task(), make_task(id="acme__auth-43", fix=replace(make_task().fix, pr_number=43))]
    path = tmp_path / "tasks.jsonl"
    save_tasks(path, tasks)
    first = path.read_bytes()
    loaded = load_tasks(path)
    assert loaded == tasks
    save_tasks(path, loaded)
    assert path.read_bytes() == first
    assert first.count(b"\n") == 2 and b"\r\n" not in first
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o644


def test_json_starts_with_schema_and_keeps_unicode(make_task):
    text = dumps(make_task(query="Café crashes ✓"))
    assert text.startswith('{"schema": 1, "id": "acme__auth-42"')
    assert "Café crashes ✓" in text


def test_from_dict_rejects_unknown_and_missing_fields(make_task):
    data = make_task().to_dict()
    with pytest.raises(TaskError, match="unknown fields: qurey"):
        Task.from_dict({**data, "qurey": "typo"})
    del data["patch"]
    with pytest.raises(TaskError, match="missing fields: patch"):
        Task.from_dict(data)
    data = make_task().to_dict()
    data["gold"]["functions"][0]["lines"] = 3
    with pytest.raises(TaskError, match=r"gold.functions\[0\]: unknown fields: lines"):
        Task.from_dict(data)


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"base_commit": "abc123"}, "40-character"),
        ({"base_commit": "0123456789ABCDEF0123456789ABCDEF01234567"}, "40-character"),
        ({"id": "acme-auth-42"}, "is not <owner>__<repo>-<number>"),
        ({"id": "other__auth-42"}, "does not match repo"),
        ({"repo": "acme"}, "is not owner/name"),
        ({"split": "train"}, "split 'train'"),
        ({"source": "github"}, "source 'github'"),
        ({"query": "  \n"}, "query is empty"),
        ({"patch": ""}, "patch is empty"),
        ({"language": "Python"}, "lowercase"),
        ({"schema": 2}, "schema is 2"),
        ({"tags": {"n_gold_files": True}}, "tags.n_gold_files must be int"),
        ({"tags": {"identifier_in_query": "no"}}, "tags.identifier_in_query must be bool"),
    ],
)
def test_validation_rules(make_task, overrides, expected):
    problems = validate(make_task(**overrides))
    assert any(expected in p for p in problems), problems


def test_unknown_tags_are_allowed(make_task):
    assert validate(make_task(tags={"my_experiment": [1, 2]})) == []


def test_fix_rules(make_task):
    task = make_task()
    assert any("merge_type" in p for p in validate(replace(task, fix=replace(task.fix, merge_type="ff"))))
    assert any("fix.pr_number 7" in p for p in validate(replace(task, fix=replace(task.fix, pr_number=7))))
    assert any("ISO 8601" in p for p in validate(replace(task, fix=replace(task.fix, merged_at="last week"))))


def test_span_rules(make_task):
    gold = Gold(
        files=["auth/sessions.py"],
        functions=[Span("auth/sessions.py", 40, 30), Span("auth/users.py", 1, 2), Span("auth/sessions.py", 0, 2)],
        lines=[Span("auth\\sessions.py", 1, 1)],
    )
    problems = validate(make_task(gold=gold))
    assert any("gold.functions[0]: needs 1 <= start <= end, got 40..30" in p for p in problems)
    assert any("gold.functions[1]: path 'auth/users.py' is not in gold.files" in p for p in problems)
    assert any("gold.functions[2]: needs 1 <= start <= end" in p for p in problems)
    assert any("gold.lines[0]: path 'auth\\\\sessions.py' is not a repo-relative path" in p for p in problems)


def test_gold_file_rules(make_task):
    assert "gold.files is empty" in validate(make_task(gold=Gold()))
    problems = validate(make_task(gold=Gold(files=["a.py", "a.py", "/abs.py", "../up.py"])))
    assert any("'a.py' is listed twice" in p for p in problems)
    assert any("'/abs.py' is not a repo-relative path" in p for p in problems)
    assert any("'../up.py' is not a repo-relative path" in p for p in problems)


def test_load_reports_every_problem_by_line(make_task, tmp_path):
    good = dumps(make_task())
    bad_sha = dumps(make_task(id="acme__auth-43", fix=replace(make_task().fix, pr_number=43), base_commit="nope"))
    path = tmp_path / "tasks.jsonl"
    path.write_text("\n".join([good, "{not json", bad_sha, good]) + "\n", encoding="utf-8")
    with pytest.raises(TaskError) as info:
        load_tasks(path)
    problems = info.value.problems
    assert any(p.startswith("tasks.jsonl:2: invalid JSON") for p in problems)
    assert any(p.startswith("tasks.jsonl:3 (acme__auth-43): base_commit") for p in problems)
    assert any("tasks.jsonl:4: duplicate id 'acme__auth-42' (first on line 1)" in p for p in problems)


def test_save_refuses_invalid_tasks_and_leaves_no_file(make_task, tmp_path):
    path = tmp_path / "tasks.jsonl"
    with pytest.raises(TaskError):
        save_tasks(path, [make_task(), make_task()])  # duplicate id
    with pytest.raises(TaskError):
        save_tasks(path, [make_task(split="train")])
    assert list(tmp_path.iterdir()) == []


def test_load_skips_blank_lines(make_task, tmp_path):
    path = tmp_path / "tasks.jsonl"
    path.write_text("\n" + dumps(make_task()) + "\n\n", encoding="utf-8")
    assert len(load_tasks(path)) == 1


# ---- splits


def test_assign_split_is_pinned():
    # These values must never change: changing them would move tasks between dev and test.
    assert assign_split("django__django-15814") == "test"
    assert assign_split("psf__requests-1234") == "test"
    assert assign_split("vllm-project__vllm-20000") == "dev"
    assert assign_split("acme__auth-42") == "test"


def test_assign_split_share_is_about_20_percent():
    n = 10_000
    dev = sum(assign_split(f"acme__repo-{k}") == "dev" for k in range(n))
    assert abs(dev / n - 0.20) < 0.01


def test_assign_split_depends_only_on_id_and_seed():
    ids = [f"acme__repo-{k}" for k in range(200)]
    forward = {i: assign_split(i) for i in ids}
    backward = {i: assign_split(i) for i in reversed(ids)}
    assert forward == backward
    other_seed = {i: assign_split(i, seed="other") for i in ids}
    assert other_seed != forward
    assert all(assign_split(i, dev_percent=0) == "test" for i in ids)
    assert all(assign_split(i, dev_percent=100) == "dev" for i in ids)


def test_select(make_task):
    dev = make_task(split="dev")
    test = make_task(id="acme__auth-43", fix=replace(make_task().fix, pr_number=43))
    assert select([dev, test], "dev") == [dev]
    assert select([dev, test], "test") == [test]
    assert select([dev, test], None) == [dev, test]
    with pytest.raises(ValueError):
        select([dev], "train")


def test_clean_query():
    from cmeval.tasks import clean_query

    assert clean_query("Title\n\n<!-- hidden -->Body") == "Title\n\nBody"
    assert clean_query("<!--\nmulti\nline\n-->\nBody\n```\ncode <!-- kept? no: hidden too -->\n```") == "Body\n```\ncode \n```"
    assert clean_query("  Stack trace:\n  File \"x.py\", line 3\n") == 'Stack trace:\n  File "x.py", line 3'
    assert clean_query(None) == "" and clean_query("") == ""


def test_load_reports_unhashable_values_instead_of_crashing(make_task, tmp_path):
    data = make_task().to_dict()
    data["id"] = ["acme__auth-42"]
    data["gold"]["functions"][0]["path"] = {"not": "a path"}
    path = tmp_path / "tasks.jsonl"
    path.write_text(json.dumps(data) + "\n" + json.dumps(data) + "\n", encoding="utf-8")
    with pytest.raises(TaskError) as info:
        load_tasks(path)
    problems = "\n".join(info.value.problems)
    assert "is not <owner>__<repo>-<number>" in problems
    assert "gold.functions[0]: path" in problems
