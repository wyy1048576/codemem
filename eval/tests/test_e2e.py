"""The grader of end-to-end runs: the parts that need no Docker."""

import json
import os
import subprocess
from dataclasses import replace

import pytest

from cmeval import e2e
from cmeval import generate as gen
from cmeval.cli import main
from cmeval.generate import FAIL, PASS, SKIP
from cmeval.tasks import save_tasks

MODIFY = """\
diff --git a/pkg/core.py b/pkg/core.py
index 1111111..2222222 100644
--- a/pkg/core.py
+++ b/pkg/core.py
@@ -1,2 +1,2 @@
 def f():
-    return 1
+    return 2
"""

NEW = """\
diff --git a/pkg/new.py b/pkg/new.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/pkg/new.py
@@ -0,0 +1 @@
+X = 1
"""

DELETE = """\
diff --git a/pkg/old.py b/pkg/old.py
deleted file mode 100644
index 4444444..0000000
--- a/pkg/old.py
+++ /dev/null
@@ -1 +0,0 @@
-Y = 1
"""

RENAME = """\
diff --git a/pkg/a.py b/pkg/b.py
similarity index 100%
rename from pkg/a.py
rename to pkg/b.py
"""

BINARY = """\
diff --git a/data/x.bin b/data/x.bin
new file mode 100644
index 0000000..5555555
Binary files /dev/null and b/data/x.bin differ
"""

MODE = """\
diff --git a/my dir/run.sh b/my dir/run.sh
old mode 100644
new mode 100755
"""

QUOTED = """\
diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"
index 1111111..2222222 100644
--- "a/caf\\303\\251.py"
+++ "b/caf\\303\\251.py"
@@ -1 +1 @@
-a
+b
"""

TEST_PATCH = """\
diff --git a/pkg/tests/test_core.py b/pkg/tests/test_core.py
--- a/pkg/tests/test_core.py
+++ b/pkg/tests/test_core.py
@@ -1 +1,2 @@
 import pkg
+def test_f(): assert pkg.f() == 2
"""


def test_split_patch_gives_one_part_for_each_file():
    patch = MODIFY + NEW + DELETE + RENAME + BINARY + MODE + QUOTED
    parts = e2e.split_patch(patch)
    assert [path for path, _ in parts] == [
        "pkg/core.py", "pkg/new.py", "pkg/old.py", "pkg/b.py", "data/x.bin", "my dir/run.sh", "café.py"]
    assert [text for _, text in parts] == [MODIFY, NEW, DELETE, RENAME, BINARY, MODE, QUOTED]
    assert "".join(text for _, text in parts) == patch


def test_file_paths_before_and_after():
    assert e2e.file_paths(MODIFY) == ("pkg/core.py", "pkg/core.py")
    assert e2e.file_paths(NEW) == (None, "pkg/new.py")
    assert e2e.file_paths(DELETE) == ("pkg/old.py", None)
    assert e2e.file_paths(RENAME) == ("pkg/a.py", "pkg/b.py")
    assert e2e.file_paths(BINARY) == (None, "data/x.bin")


def test_split_patch_keeps_text_before_the_first_diff():
    patch = "From abc\nSubject: fix\n\n" + MODIFY
    parts = e2e.split_patch(patch)
    assert parts[0] == ("", "From abc\nSubject: fix\n\n")
    assert "".join(text for _, text in parts) == patch
    assert e2e.split_patch("") == []


def test_split_patch_does_not_cut_inside_a_hunk():
    # A removed line that looks like a header starts with "-", so it is not at the start of a line.
    patch = MODIFY.replace("-    return 1\n", "-diff --git a/x b/x\n")
    assert len(e2e.split_patch(patch)) == 1


def test_drop_files_matches_the_old_and_the_new_path():
    patch = MODIFY + NEW + DELETE + RENAME
    assert e2e.drop_files(patch, {"pkg/new.py"}) == MODIFY + DELETE + RENAME
    assert e2e.drop_files(patch, {"pkg/old.py"}) == MODIFY + NEW + RENAME
    assert e2e.drop_files(patch, {"pkg/a.py"}) == MODIFY + NEW + DELETE
    assert e2e.drop_files(patch, {"pkg/b.py", "pkg/core.py"}) == NEW + DELETE
    assert e2e.drop_files(patch, set()) == patch
    assert e2e.is_empty(e2e.drop_files(MODIFY, {"pkg/core.py"}))
    assert e2e.is_empty("  \n") and not e2e.is_empty(RENAME)


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def test_round_trip_with_real_git(tmp_path, monkeypatch):
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    for name, text in {"core.py": "A = 1\n", "gone.py": "B = 1\n", "moved.py": "C = 1\n" * 20,
                       "test_core.py": "T = 1\n"}.items():
        (root / "pkg" / name).write_text(text)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    (root / "pkg" / "core.py").write_text("A = 2\n")
    (root / "pkg" / "gone.py").unlink()
    (root / "pkg" / "moved.py").rename(root / "pkg" / "renamed.py")
    (root / "pkg" / "added.py").write_text("D = 1\n")
    (root / "pkg" / "test_core.py").write_text("T = 2\n")
    _git(root, "add", "-A")
    patch = _git(root, "diff", "--cached", "--binary", "-M")
    parts = e2e.split_patch(patch)
    assert sorted(path for path, _ in parts) == [
        "pkg/added.py", "pkg/core.py", "pkg/gone.py", "pkg/renamed.py", "pkg/test_core.py"]
    assert "".join(text for _, text in parts) == patch
    # The patch without the test file still applies to the base.
    _git(root, "reset", "-q", "--hard")
    (root / "agent.patch").write_text(e2e.drop_files(patch, {"pkg/test_core.py"}))
    _git(root, "apply", "--check", "agent.patch")


def _recipe(**fields):
    values = dict(name="r", repo="acme/auth", base_image="i", test="pytest {files} --junitxml={junit}",
                  test_files=("pkg/tests/**/test_*.py",), refresh=("python -c 'import pkg'",))
    values.update(fields)
    return gen.Recipe(**values)


def test_grade_script_with_an_agent_patch(make_task):
    script = e2e._grade_script(_recipe(), make_task(test_patch=TEST_PATCH), has_agent_patch=True)
    lines = script.splitlines()
    assert lines[0] == "trap 'chmod -R a+rwX /work' EXIT"
    assert lines[1] == "cd /testbed"
    assert lines[2].startswith("git apply --whitespace=nowarn /work/agent.patch || {")
    assert "echo 'agent patch failed' >> /work/times.txt; exit 3;" in lines[2]
    assert lines[3].startswith("git apply --whitespace=nowarn /work/test.patch || {")
    assert "echo 'test patch failed' >> /work/times.txt" in lines[3]
    assert lines[4] == "python -c 'import pkg' >> /work/refresh.log 2>&1 || echo \"refresh failed\" >> /work/times.txt"
    assert "/work/grade.0.xml" in lines[5] and "'pkg/tests/test_core.py'" in lines[5]
    assert 'echo "grade $rc' in lines[5]
    assert len(lines) == 6


def test_grade_script_without_an_agent_patch(make_task):
    script = e2e._grade_script(_recipe(), make_task(test_patch=TEST_PATCH), has_agent_patch=False)
    assert "agent.patch" not in script
    assert script.splitlines()[2].startswith("git apply --whitespace=nowarn /work/test.patch")


TESTS = {"fail_to_pass": ["t::new"], "pass_to_pass": ["t::old1", "t::old2"]}


def test_verdict_ok():
    record = e2e.verdict({"t::new": PASS, "t::old1": PASS, "t::old2": PASS, "t::other": FAIL}, TESTS)
    assert record["completed"] and record["reason"] == "ok"
    assert (record["fail_to_pass_passed"], record["fail_to_pass_total"]) == (1, 1)
    assert (record["pass_to_pass_passed"], record["pass_to_pass_total"]) == (2, 2)
    assert record["failed_tests"] == [] and not record["passes_without_change"]


def test_verdict_tests_failed():
    record = e2e.verdict({"t::new": PASS, "t::old1": SKIP}, TESTS)
    assert not record["completed"] and record["reason"] == "tests failed"
    assert record["failed_tests"] == ["t::old1", "t::old2"]
    assert record["pass_to_pass_passed"] == 0


def test_verdict_failed_steps_and_no_results():
    for step in ("changes do not apply", "hidden tests do not apply", "build failed"):
        record = e2e.verdict({}, TESTS, failed_step=step)
        assert not record["completed"] and record["reason"] == step
    # A build that failed loses even when the tests pass.
    record = e2e.verdict({"t::new": PASS, "t::old1": PASS, "t::old2": PASS}, TESTS, failed_step="build failed")
    assert not record["completed"] and record["reason"] == "build failed"
    record = e2e.verdict({}, TESTS)
    assert not record["completed"] and record["reason"] == "no test results"


def test_verdict_empty_change():
    record = e2e.verdict({"t::new": FAIL, "t::old1": PASS, "t::old2": PASS}, TESTS, empty=True)
    assert not record["completed"] and record["reason"] == "empty change"
    assert not record["passes_without_change"]
    record = e2e.verdict({"t::new": PASS, "t::old1": PASS, "t::old2": PASS}, TESTS, empty=True)
    assert not record["completed"] and record["reason"] == "empty change"
    assert record["passes_without_change"]


def test_failed_step_from_times():
    assert e2e._failed_step("agent patch failed\n") == "changes do not apply"
    assert e2e._failed_step("test patch failed\n") == "hidden tests do not apply"
    assert e2e._failed_step("refresh failed\ngrade 1 2000\n") == "build failed"
    assert e2e._failed_step("grade 0 2000\n") is None


def test_grade_needs_tests_json(make_task, tmp_path):
    with pytest.raises(gen.GenerateError, match="no tests.json"):
        e2e.grade(_recipe(), make_task(test_patch=TEST_PATCH), MODIFY, tmp_path / "out")


def test_cli_grader_check(make_task, tmp_path, monkeypatch, capsys):
    recipe = gen.load_recipe("pandas")
    fix = make_task().fix
    ready = make_task(id="pandas-dev__pandas-1", repo=recipe.repo, test_patch=TEST_PATCH, fix=replace(fix, pr_number=1))
    other = make_task(id="pandas-dev__pandas-2", repo=recipe.repo, test_patch=TEST_PATCH, fix=replace(fix, pr_number=2))
    path = tmp_path / "tasks.jsonl"
    save_tasks(path, [ready, other])
    assert main(["e2e", "grader-check", "pandas", "--tasks", str(path)]) == 1
    assert "has tests.json" in capsys.readouterr().err

    gen.task_dir(recipe, ready).mkdir(parents=True)
    gen.tests_path(recipe, ready).write_text(json.dumps(TESTS))
    seen = {}

    def fake_check(recipe, tasks, jobs, cpus, progress):
        seen.update(ids=[t.id for t in tasks], jobs=jobs, cpus=cpus)
        return [{"id": t.id, "passed": False, "problem": "x"} for t in tasks]

    monkeypatch.setattr(e2e, "grader_check", fake_check)
    assert main(["e2e", "grader-check", "pandas", "--tasks", str(path), "--jobs", "2", "--cpus", "4"]) == 3
    captured = capsys.readouterr()
    assert seen == {"ids": ["pandas-dev__pandas-1"], "jobs": 2, "cpus": 4}
    assert "1 tasks have no tests.json" in captured.err
    assert captured.out.strip() == "pandas: 0 of 1 tasks pass the grader check"


# The test command of the local grading tests. It checks that the hidden test file is in place,
# and gives one test that passes only with the fix. The quotes go through the same layers as a
# real recipe's command.
LOCAL_TEST = ("grep -q test_f {files} && if grep -q 'return 2' pkg/core.py; then o=''; else o='<failure/>'; fi && "
              "echo \"<testsuite><testcase classname='t' name='new'>$o</testcase></testsuite>\" > {junit}")


def _local_docker(monkeypatch, tmp_path):
    """Run run.sh in a local folder instead of a container: /testbed and /work become folders in
    tmp_path, and a `timeout` stand-in drops its limits. The folder is reset before each run."""
    testbed = tmp_path / "testbed"
    (testbed / "pkg" / "tests").mkdir(parents=True)
    (testbed / "pkg" / "core.py").write_text("def f():\n    return 1\n")
    (testbed / "pkg" / "tests" / "test_core.py").write_text("import pkg\n")
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    _git(testbed, "init", "-q")
    _git(testbed, "add", "-A")
    _git(testbed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    shims = tmp_path / "shims"
    shims.mkdir()
    (shims / "timeout").write_text('#!/bin/sh\nshift 3\nexec "$@"\n')
    (shims / "timeout").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shims}:{os.environ['PATH']}")
    real_run = e2e._run

    def fake_run(cmd, **kwargs):
        if cmd[:2] != ["docker", "run"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        work = cmd[cmd.index("-v") + 1].rsplit(":", 1)[0]
        _git(testbed, "reset", "-q", "--hard")
        _git(testbed, "clean", "-qfdx")
        script = tmp_path / "local.sh"
        script.write_text(open(f"{work}/run.sh").read().replace("/testbed", str(testbed)).replace("/work", work))
        return real_run(["bash", str(script)], **kwargs)

    monkeypatch.setattr(e2e, "_run", fake_run)
    monkeypatch.setattr(e2e, "image_exists", lambda tag: True)


def _local_task(make_task):
    recipe = _recipe(test=LOCAL_TEST, refresh=("true",))
    task = make_task(patch=MODIFY, test_patch=TEST_PATCH)
    gen.task_dir(recipe, task).mkdir(parents=True)
    gen.tests_path(recipe, task).write_text(json.dumps({"fail_to_pass": ["t::new"], "pass_to_pass": []}))
    return recipe, task


def test_grade_locally(make_task, tmp_path, monkeypatch):
    _local_docker(monkeypatch, tmp_path)
    recipe, task = _local_task(make_task)
    out = tmp_path / "out"

    record = e2e.grade(recipe, task, MODIFY, out)
    assert record["completed"] and record["reason"] == "ok", (out / "grade.0.log").read_text()
    assert record["test_run_s"] is not None
    assert json.loads((out / "grade.json").read_text()) == record

    # The agent's own version of the test file is dropped, so the hidden one is used.
    own_test = TEST_PATCH.replace("+def test_f(): assert pkg.f() == 2\n", "+pass\n")
    record = e2e.grade(recipe, task, MODIFY + own_test, out)
    assert record["completed"]
    assert e2e.patch_files((out / "agent.patch").read_text()) == {"pkg/core.py"}

    record = e2e.grade(recipe, task, "", out)
    assert not record["completed"] and record["reason"] == "empty change"
    assert not record["passes_without_change"] and record["failed_tests"] == ["t::new"]
    assert not (out / "agent.patch").read_text()

    record = e2e.grade(recipe, task, MODIFY.replace("    return 1", "    return 9"), out)
    assert record["reason"] == "changes do not apply"

    broken = _recipe(test=LOCAL_TEST, refresh=("false",))
    assert e2e.grade(broken, task, MODIFY, out)["reason"] == "build failed"


def test_grader_check_locally(make_task, tmp_path, monkeypatch):
    _local_docker(monkeypatch, tmp_path)
    recipe, task = _local_task(make_task)
    seen = []
    records = e2e.grader_check(recipe, [task], progress=seen.append)
    assert records[0]["passed"] and records[0]["problem"] == "ok"
    assert records[0]["gold"]["reason"] == "ok" and records[0]["empty"]["reason"] == "empty change"
    assert (e2e.grader_check_dir(recipe, task) / "gold" / "grade.json").exists()
    assert seen[0].startswith(f"{task.id}  ok  gold: ok  empty: empty change")
    # A task without tests.json is left out.
    assert e2e.grader_check(recipe, [make_task(id="acme__auth-7")]) == []
