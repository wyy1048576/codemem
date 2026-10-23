import json
from collections import Counter

import pytest
from conftest import FIXTURES, REMOTE_REPO

from cmeval.cli import main
from cmeval.importers.swebench import balanced_order, import_swebench_verified, row_to_task
from cmeval.labels import LABELER_VERSION, LabelError, LabelResult, label_at_commit
from cmeval.tasks import Gold, Unretrievable, load_tasks, validate

SAMPLE = (FIXTURES / "defs_sample.py").read_text()


def fake_row(instance_id, repo="acme/demo", **extra):
    row = {
        "instance_id": instance_id,
        "repo": repo,
        "base_commit": "0123456789abcdef0123456789abcdef01234567",
        "problem_statement": "Something breaks\n\nDetails here.",
        "hints_text": "",
        "patch": f"diff --git a/{instance_id}.py b/{instance_id}.py\n",
        "test_patch": "",
        "created_at": "2023-05-01T10:00:00Z",
        "difficulty": "<15 min fix",
        "version": "1.0",
    }
    row.update(extra)
    return row


def fake_label(repo, commit, patch):
    return LabelResult(Gold(files=["a.py"]), Unretrievable(), "python",
                       {"n_gold_files": 1, "n_gold_classes": 0, "n_gold_functions": 0,
                        "module_level_change": True, "partial_labels": False})


def test_row_to_task_with_real_labels(remote):
    base = remote.commit({"auth/sessions.py": SAMPLE}, "add sessions")
    fixed_text = SAMPLE.replace("            helper(s)\n", "            helper(s, force=True)\n")
    fixed = remote.commit({"auth/sessions.py": fixed_text, "tests/test_sessions.py": "def test_x():\n    pass\n"})
    diff = remote.diff(base, fixed)
    from cmeval.patches import split_patch

    parts = split_patch(diff)
    row = fake_row(
        "acme__demo-7",
        base_commit=base,
        problem_statement="Calling revoke_session leaves sessions open\n<!-- Please fill in\nthe template -->\nSteps: ...",
        hints_text="  ",
        patch=parts["code"],
        test_patch=parts["test"],
    )
    task = row_to_task(row, label_at_commit(REMOTE_REPO, base, row["patch"]))
    assert validate(task) == []
    assert (task.id, task.source, task.split, task.repo, task.base_commit) == ("acme__demo-7", "swebench_verified", "dev", "acme/demo", base)
    assert task.query == "Calling revoke_session leaves sessions open\n\nSteps: ..."  # hidden comment removed
    assert task.hints is None and task.test_patch == parts["test"]
    assert task.issue.created_at == "2023-05-01T10:00:00Z"
    assert (task.fix.pr_number, task.fix.url) == (7, "https://github.com/acme/demo/pull/7")
    assert [s.symbol for s in task.gold.functions] == ["SessionManager.revoke_session"]
    assert task.tags["identifier_in_query"] is True and task.tags["has_test_patch"] is True
    assert task.tags["swebench_difficulty"] == "<15 min fix" and task.tags["query_tokens"] is None
    assert task.language == "python" and task.labeler == LABELER_VERSION


def test_balanced_order_takes_evenly_from_repos():
    rows = ([fake_row(f"big__big-{i}", repo="big/big") for i in range(10)]
            + [fake_row(f"mid__mid-{i}", repo="mid/mid") for i in range(3)]
            + [fake_row("tiny__tiny-1", repo="tiny/tiny")])
    order = balanced_order(rows, seed=0)
    assert len(order) == 14
    first_nine = Counter(r["repo"] for r in order[:9])
    assert first_nine == {"big/big": 5, "mid/mid": 3, "tiny/tiny": 1}
    assert [r["instance_id"] for r in balanced_order(list(reversed(rows)), seed=0)] == [r["instance_id"] for r in order]
    assert [r["instance_id"] for r in balanced_order(rows, seed=1)] != [r["instance_id"] for r in order]


def test_import_skips_bad_rows_and_writes_files(tmp_path):
    rows = [fake_row(f"acme__demo-{i}") for i in range(1, 6)] + [fake_row(f"other__lib-{i}", repo="other/lib") for i in range(1, 4)]
    order = balanced_order(rows, seed=0)
    bad = order[0]["instance_id"]

    def label_fn(repo, commit, patch):
        if patch == order[0]["patch"]:
            raise LabelError("auth/x.py:3: diff expects 'a', base has 'b'")
        return fake_label(repo, commit, patch)

    out = tmp_path / "tasks" / "swebv-dev3.jsonl"
    report = import_swebench_verified(n=3, seed=0, out=out, rows=rows, label_fn=label_fn)
    assert report.skipped == [{"id": bad, "reason": "auth/x.py:3: diff expects 'a', base has 'b'"}]
    expected = sorted((r["repo"], r["instance_id"]) for r in order[1:4])
    assert [(t.repo, t.id) for t in report.tasks] == expected  # the next rows replace the bad one
    assert [t.id for t in load_tasks(out)] == [t.id for t in report.tasks]
    meta = json.loads(out.with_suffix(".meta.json").read_text())
    assert meta["n"] == 3 and meta["skipped"][0]["id"] == bad and meta["stats"]["tasks"] == 3
    assert meta["dataset"] == "SWE-bench/SWE-bench_Verified" and len(meta["revision"]) == 40


def test_import_skips_patches_without_code_files():
    rows = [fake_row("acme__demo-1")]

    def no_code(repo, commit, patch):
        return LabelResult(Gold(), Unretrievable(), None, {})

    report = import_swebench_verified(n=1, rows=rows, label_fn=no_code)
    assert report.tasks == [] and "no code file" in report.skipped[0]["reason"]


def test_cli_import_arguments(capsys):
    with pytest.raises(SystemExit) as info:
        main(["import", "swebench-verified", "--help"])
    assert info.value.code == 0 and "--revision" in capsys.readouterr().out
    with pytest.raises(SystemExit) as info:
        main(["import", "imagenet"])
    assert info.value.code == 2


def test_import_skips_rows_that_give_invalid_tasks():
    rows = [fake_row("acme__demo-1", problem_statement="<!-- only the template -->"), fake_row("acme__demo-2")]
    report = import_swebench_verified(n=1, rows=rows, label_fn=fake_label)
    assert [t.id for t in report.tasks] == ["acme__demo-2"]
    assert report.skipped == [{"id": "acme__demo-1", "reason": "invalid task: query is empty"}]


def test_import_skips_unparsable_patches(remote):
    rows = [fake_row("acme__demo-1", base_commit=remote.shas[0], patch="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,3 +1,3 @@\n-x\n")]
    report = import_swebench_verified(n=1, rows=rows)
    assert report.tasks == [] and "cannot be parsed" in report.skipped[0]["reason"]


def test_task_patch_keeps_code_files_only(remote):
    base = remote.shas[-1]
    fixed = remote.commit({"app.py": "VERSION = 9\n", "CHANGES.rst": "fixed\n"})
    row = fake_row("acme__demo-3", base_commit=base, patch=remote.diff(base, fixed))
    task = row_to_task(row, label_at_commit(REMOTE_REPO, base, row["patch"]))
    assert "app.py" in task.patch and "CHANGES.rst" not in task.patch


def test_short_import_does_not_replace_the_task_file(tmp_path):
    out = tmp_path / "swebv-dev2.jsonl"
    out.write_text("committed answer key\n")
    rows = [fake_row("acme__demo-1"), fake_row("acme__demo-2", problem_statement="")]
    report = import_swebench_verified(n=2, out=out, rows=rows, label_fn=fake_label)
    assert len(report.tasks) == 1 and report.written is False
    assert out.read_text() == "committed answer key\n" and not out.with_suffix(".meta.json").exists()
