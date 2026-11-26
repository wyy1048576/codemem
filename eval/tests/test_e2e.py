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
    assert 'echo "grade 0 $r ' in lines[5]
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
    assert captured.out.strip() == "pandas: 0 of 1 tasks pass the grader check; 0 differ from tests.json, 0 errors"

    # A task whose tests differ is counted, and the exit code is not 0.
    def differs(recipe, tasks, jobs, cpus, progress):
        return [{"id": t.id, "passed": False, "problem": "1 tests differ from tests.json",
                 "tests": {"equal": False}} for t in tasks]

    monkeypatch.setattr(e2e, "grader_check", differs)
    assert main(["e2e", "grader-check", "pandas", "--tasks", str(path)]) == 3
    assert "0 of 1 tasks pass the grader check; 1 differ from tests.json" in capsys.readouterr().out


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
    real_run = gen._run

    def fake_run(cmd, **kwargs):
        if cmd[:2] != ["docker", "run"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        work = cmd[cmd.index("-v") + 1].rsplit(":", 1)[0]
        _git(testbed, "reset", "-q", "--hard")
        _git(testbed, "clean", "-qfdx")
        script = tmp_path / "local.sh"
        script.write_text(open(f"{work}/run.sh").read().replace("/testbed", str(testbed)).replace("/work", work))
        return real_run(["bash", str(script)], **kwargs)

    monkeypatch.setattr(gen, "_run", fake_run)
    monkeypatch.setattr(e2e, "image_exists", lambda tag: True)


def _write_tests(recipe, task, fail_to_pass, pass_to_pass=(), repeats=3):
    """A tests.json as a validation with this recipe writes it."""
    gen.task_dir(recipe, task).mkdir(parents=True, exist_ok=True)
    gen.tests_path(recipe, task).write_text(json.dumps({
        "fingerprint": gen.validation_fingerprint(recipe, task, repeats), "repeats": repeats,
        "fail_to_pass": list(fail_to_pass), "pass_to_pass": list(pass_to_pass)}))


def _local_task(make_task, monkeypatch):
    recipe = _recipe(test=LOCAL_TEST, refresh=("true",))
    task = make_task(patch=MODIFY, test_patch=TEST_PATCH)
    _write_tests(recipe, task, ["t::new"])
    # The image has the label of this recipe and task.
    monkeypatch.setattr(e2e, "image_label", lambda tag: gen.image_fingerprint(recipe, task))
    return recipe, task


def test_grade_locally(make_task, tmp_path, monkeypatch):
    _local_docker(monkeypatch, tmp_path)
    recipe, task = _local_task(make_task, monkeypatch)
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
    _write_tests(broken, task, ["t::new"])
    assert e2e.grade(broken, task, MODIFY, out)["reason"] == "build failed"


def test_grade_refuses_stale_tests_and_images(make_task, tmp_path, monkeypatch):
    recipe = _recipe()
    task = make_task(patch=MODIFY, test_patch=TEST_PATCH)
    monkeypatch.setattr(e2e, "image_exists", lambda tag: True)
    monkeypatch.setattr(e2e, "image_label", lambda tag: gen.image_fingerprint(recipe, task))
    monkeypatch.setattr(gen, "_run", lambda cmd, **kwargs: pytest.fail(f"no container may start: {cmd}"))
    # A tests.json from before fingerprints.
    gen.task_dir(recipe, task).mkdir(parents=True)
    gen.tests_path(recipe, task).write_text(json.dumps(TESTS))
    with pytest.raises(gen.GenerateError, match="run cmeval generate again"):
        e2e.grade(recipe, task, MODIFY, tmp_path / "out")
    # A tests.json from another test command, or from another test patch.
    _write_tests(_recipe(test="pytest -x {files} --junitxml={junit}"), task, ["t::new"])
    with pytest.raises(gen.GenerateError, match="another version of the recipe or the task"):
        e2e.load_tests(recipe, task)
    _write_tests(recipe, make_task(patch=MODIFY, test_patch=TEST_PATCH + "\n"), ["t::new"])
    with pytest.raises(gen.GenerateError, match="another version"):
        e2e.load_tests(recipe, task)
    _write_tests(recipe, task, ["t::new"])
    assert e2e.load_tests(recipe, task)["fail_to_pass"] == ["t::new"]
    # An image without the label, or with the label of another build.
    for label in (None, gen.image_fingerprint(_recipe(build=("make",)), task)):
        monkeypatch.setattr(e2e, "image_label", lambda tag, label=label: label)
        with pytest.raises(gen.GenerateError, match=r"image .* was built from another version"):
            e2e.grade(recipe, task, MODIFY, tmp_path / "out")


def test_grade_locally_with_a_suite_that_times_out(make_task, tmp_path, monkeypatch):
    _local_docker(monkeypatch, tmp_path)
    recipe, task = _local_task(make_task, monkeypatch)
    (tmp_path / "shims" / "timeout").write_text("#!/bin/sh\nexit 124\n")
    record = e2e.grade(recipe, task, MODIFY, tmp_path / "out")
    assert not record["completed"] and record["reason"] == "tests timed out"
    assert "grade 0 124 " in (tmp_path / "out" / "times.txt").read_text()


def test_validate_locally_then_grade(make_task, tmp_path, monkeypatch):
    _local_docker(monkeypatch, tmp_path)
    recipe, task = _local_task(make_task, monkeypatch)
    gen.tests_path(recipe, task).unlink()
    record = gen.validate_task(recipe, task, "cmeval-env/r:x")
    assert record["valid"] and record["reason"] == "ok", record
    assert record["fail_to_pass"] == ["t::new"] and record["fail_to_pass_failed_before"] == 1
    assert record["slowest_test_run_s"] is not None and record["timed_out"] == []
    times = gen.read_times(gen.task_dir(recipe, task) / "work")
    # One line for each suite of each run. The local test command writes its failure to the XML and exits 0.
    assert [(run.name, run.suite, run.exit_code) for run in times] == (
        [(f"{phase}-{i}", 0, 0) for phase in ("before", "after") for i in (1, 2, 3)])
    # The tests.json of the validation is good for the grader.
    assert e2e.grade(recipe, task, MODIFY, tmp_path / "out")["completed"]
    # A refresh that fails gives a fixed reason, and no tests.json.
    record = gen.validate_task(_recipe(test=LOCAL_TEST, refresh=("false",)), task, "cmeval-env/r:x")
    assert not record["valid"] and record["reason"] == "refresh failed"
    assert not gen.tests_path(recipe, task).exists()


def test_grader_check_locally(make_task, tmp_path, monkeypatch):
    _local_docker(monkeypatch, tmp_path)
    recipe, task = _local_task(make_task, monkeypatch)
    seen = []
    records = e2e.grader_check(recipe, [task], progress=seen.append)
    assert records[0]["passed"] and records[0]["problem"] == "ok"
    assert records[0]["gold"]["reason"] == "ok" and records[0]["empty"]["reason"] == "empty change"
    assert (e2e.grader_check_dir(recipe, task) / "gold" / "grade.json").exists()
    assert seen[0].startswith(f"{task.id}  ok  gold: ok  empty: empty change  tests: equal (2 checked)")
    saved = json.loads((e2e.grader_check_dir(recipe, task) / "check.json").read_text())
    assert saved == records[0] and saved["tests"]["equal"] and saved["tests"]["differences"] == []
    # A task without tests.json is left out.
    assert e2e.grader_check(recipe, [make_task(id="acme__auth-7")]) == []


def test_compare_tests():
    gold = {"t::new": PASS, "t::old1": FAIL}
    assert e2e.compare_tests(gold, TESTS, empty=False) == [
        {"test": "t::old1", "list": "pass_to_pass", "saved": PASS, "new": FAIL},
        {"test": "t::old2", "list": "pass_to_pass", "saved": PASS, "new": "missing"}]
    assert e2e.compare_tests({"t::new": PASS, "t::old1": PASS, "t::old2": PASS}, TESTS, empty=False) == []
    # The empty change: only a fail-to-pass test that passes differs. Pass-to-pass tests are not checked.
    assert e2e.compare_tests({"t::new": SKIP, "t::old1": FAIL}, TESTS, empty=True) == []
    assert e2e.compare_tests({"t::new": PASS}, TESTS, empty=True) == [
        {"test": "t::new", "list": "fail_to_pass", "saved": "not pass", "new": PASS}]


def _fake_grades(monkeypatch, gold_results, empty_results):
    """grade() writes the JUnit file of its results and judges them; no container starts."""
    monkeypatch.setattr(gen, "_run", lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1, "", ""))

    def fake_grade(recipe, task, patch, out, cpus=8):
        results = gold_results if patch else empty_results
        out.mkdir(parents=True, exist_ok=True)
        cases = ""
        for test_id, result in results.items():
            classname, name = test_id.split("::")
            child = "" if result == PASS else "<failure/>"
            cases += f'<testcase classname="{classname}" name="{name}">{child}</testcase>'

        (out / "grade.0.xml").write_text(f"<testsuite>{cases}</testsuite>")
        return e2e.verdict(results, e2e.load_tests(recipe, task), empty=not patch)

    monkeypatch.setattr(e2e, "grade", fake_grade)


def test_check_task_shows_the_tests_that_differ(make_task, monkeypatch):
    recipe, task = _recipe(), make_task(patch=MODIFY, test_patch=TEST_PATCH)
    f2p = ["t::new1", "t::new2", "t::new3"]
    _write_tests(recipe, task, f2p, ["t::old"])
    # The real fix completes the task. With the empty change one fail-to-pass test passes now: the
    # old check passed this task, because not every test passed.
    _fake_grades(monkeypatch, {t: PASS for t in f2p + ["t::old"]}, {"t::new1": PASS, "t::new2": FAIL, "t::old": PASS})
    record = e2e.check_task(recipe, task)
    assert record["gold"]["completed"] and not record["empty"]["passes_without_change"]
    assert not record["passed"] and record["problem"] == "1 tests differ from tests.json"
    assert record["tests"] == {"equal": False, "checked": 7, "differ": 1, "real_fix_differ": 0, "empty_differ": 1,
                               "differences": [{"change": "empty", "test": "t::new1", "list": "fail_to_pass",
                                                "saved": "not pass", "new": PASS}]}
    assert record["image_id"] is None and record["image_build"] is None
    line = e2e.format_check(record)
    assert "tests: 1 differ (real fix 0, empty 1): t::new1 (empty) not pass -> pass  " in line
    assert json.loads((e2e.grader_check_dir(recipe, task) / "check.json").read_text()) == record


def test_check_task_cuts_a_long_list(make_task, monkeypatch):
    recipe, task = _recipe(), make_task(patch=MODIFY, test_patch=TEST_PATCH)
    p2p = [f"t::old{i}" for i in range(60)]
    _write_tests(recipe, task, ["t::new"], p2p)
    # The pass-to-pass tests fail on this image with the real fix.
    _fake_grades(monkeypatch, {"t::new": PASS}, {})
    record = e2e.check_task(recipe, task)
    assert record["problem"] == "the real fix does not complete the task; 60 tests differ from tests.json"
    assert record["tests"]["differ"] == 60 and len(record["tests"]["differences"]) == e2e.MAX_FAILED_SHOWN
    assert record["tests"]["differences"][0]["new"] == "missing"
    assert e2e.format_check(record).endswith(", and 57 more  " + f"{record['seconds']} s")


def test_check_task_names_the_build_of_the_image(make_task, monkeypatch):
    recipe, task = _recipe(), make_task(patch=MODIFY, test_patch=TEST_PATCH)
    _write_tests(recipe, task, ["t::new"])
    _fake_grades(monkeypatch, {"t::new": PASS}, {"t::new": FAIL})
    gen.builds_path(recipe, task).write_text(json.dumps([{"image_id": "sha256:a"}, {"image_id": "sha256:b"}]))
    monkeypatch.setattr(e2e, "image_id", lambda tag: "sha256:b")
    record = e2e.check_task(recipe, task)
    assert record["passed"] and record["image_id"] == "sha256:b" and record["image_build"] == 2
    # An error is saved too.
    monkeypatch.setattr(e2e, "grade", lambda *a, **k: (_ for _ in ()).throw(gen.GenerateError("no image")))
    record = e2e.check_task(recipe, task)
    assert record["error"] and "tests" not in record
    assert json.loads((e2e.grader_check_dir(recipe, task) / "check.json").read_text())["problem"] == "error: no image"
    assert "tests: -" in e2e.format_check(record)


# ---- a saved change (cmeval e2e grade)

def test_diff_problem():
    assert e2e.diff_problem("") is None and e2e.diff_problem("\n") is None
    for good in (MODIFY, NEW, DELETE, RENAME, BINARY, MODE, QUOTED, MODIFY + TEST_PATCH):
        assert e2e.diff_problem(good) is None, good
    plain = MODIFY.split("\n", 2)[2]  # the same change without its "diff --git" and index lines
    plain = plain.split("\n", 1)[1]
    assert "not a git diff" in e2e.diff_problem(plain)
    no_prefix = MODIFY.replace("a/pkg", "pkg").replace("b/pkg", "pkg")
    assert "no a/ prefix" in e2e.diff_problem(no_prefix)
    only_lines = MODIFY.replace("--- a/pkg", "--- pkg")
    assert "no a/ or b/ prefix" in e2e.diff_problem(only_lines)
    # A removed line that starts with "-- " (a SQL comment) is inside a hunk, not a file header.
    sql = MODIFY.replace("-    return 1\n", "--- old comment\n")
    assert e2e.diff_problem(sql) is None


def test_format_grade():
    record = e2e.verdict({"t::new": PASS, "t::old1": PASS}, TESTS)
    assert e2e.format_grade("acme__auth-42", "grep", record) == (
        "acme__auth-42 grep: not completed, tests failed; fail-to-pass 1/1, pass-to-pass 1/2; failed: t::old2")
    many = {"fail_to_pass": [f"t::new{i}" for i in range(5)], "pass_to_pass": ["t::" + "x" * 100]}
    line = e2e.format_grade("a", "b", e2e.verdict({}, many, empty=True))
    assert line.startswith("a b: not completed, empty change; fail-to-pass 0/5, pass-to-pass 0/1; failed: ")
    assert line.endswith("t::new0, t::new1, t::new2, and 3 more")
    # Before the tests ran, every test is "failed": the line names none.
    line = e2e.format_grade("a", "b", e2e.verdict({}, many, failed_step="changes do not apply"))
    assert line == "a b: not completed, changes do not apply; fail-to-pass 0/5, pass-to-pass 0/1"
    record = dict(e2e.verdict({"t::new": PASS, "t::old1": PASS, "t::old2": PASS}, TESTS),
                  dropped_test_files=["pkg/tests/test_core.py"])
    assert e2e.format_grade("a", "b", record) == (
        "a b: completed, ok; fail-to-pass 1/1, pass-to-pass 2/2; test files dropped from the diff: "
        "pkg/tests/test_core.py")


def test_grade_saved_locally(make_task, tmp_path, monkeypatch):
    _local_docker(monkeypatch, tmp_path)
    recipe, task = _local_task(make_task, monkeypatch)
    own_test = TEST_PATCH.replace("+def test_f(): assert pkg.f() == 2\n", "+pass\n")
    diff = tmp_path / "change.diff"
    diff.write_text(MODIFY + own_test)
    out = tmp_path / "grades" / task.id / "change"

    record = e2e.grade_saved(recipe, task, diff, out)
    assert record["completed"] and record["task_id"] == task.id and record["patch_file"] == str(diff.resolve())
    assert record["dropped_test_files"] == ["pkg/tests/test_core.py"]
    assert (out / "input.patch").read_text() == MODIFY + own_test
    assert e2e.patch_files((out / "agent.patch").read_text()) == {"pkg/core.py"}
    assert json.loads((out / "grade.json").read_text()) == record
    # A second grade of the same folder is allowed: it is a grade folder.
    assert e2e.grade_saved(recipe, task, diff, out)["completed"]

    diff.write_text(MODIFY.replace("a/pkg", "pkg").replace("b/pkg", "pkg"))
    with pytest.raises(gen.GenerateError, match="no a/ prefix"):
        e2e.grade_saved(recipe, task, diff, out)
    other = tmp_path / "notes"
    other.mkdir()
    (other / "keep.txt").write_text("x")
    diff.write_text(MODIFY)
    with pytest.raises(gen.GenerateError, match="not a grade folder"):
        e2e.grade_saved(recipe, task, diff, other)
    assert (other / "keep.txt").exists()


def test_cli_grade(make_task, tmp_path, monkeypatch, capsys):
    _local_docker(monkeypatch, tmp_path)
    recipe, task = _local_task(make_task, monkeypatch)
    monkeypatch.setattr(gen, "load_recipe", lambda name: recipe)
    tasks = tmp_path / "tasks.jsonl"
    save_tasks(tasks, [task, make_task(id="other__repo-42", repo="other/repo")])
    good = tmp_path / "good.patch"
    good.write_text(MODIFY)

    assert main(["e2e", "grade", "r", "--tasks", str(tasks), "--patch", str(good), "--id", task.id]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"{task.id} good: completed, ok; fail-to-pass 1/1, pass-to-pass 0/0"
    assert out[1].startswith("r: 1 of 1 graded changes completed, 0 errors; records in ")
    assert (e2e.grades_dir() / "r" / task.id / "good" / "grade.json").exists()

    # A file needs exactly one --id.
    assert main(["e2e", "grade", "r", "--tasks", str(tasks), "--patch", str(good)]) == 1
    assert "exactly one --id" in capsys.readouterr().err

    # A folder: <task id>/<label>.patch files, a change that fails, one of another repo, one of no task.
    folder = tmp_path / "diffs"
    (folder / task.id).mkdir(parents=True)
    (folder / task.id / "grep.diff").write_text(MODIFY)
    (folder / task.id / "loop.diff").write_text(MODIFY.replace("    return 2", "    return 3"))
    (folder / "other__repo-42.patch").write_text(MODIFY)
    (folder / "notes.txt").write_text("not a patch")
    out_dir = tmp_path / "out"
    assert main(["e2e", "grade", "r", "--tasks", str(tasks), "--patch", str(folder), "--out", str(out_dir)]) == 3
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert lines[0] == f"{task.id} grep: completed, ok; fail-to-pass 1/1, pass-to-pass 0/0"
    assert lines[1] == f"{task.id} loop: not completed, tests failed; fail-to-pass 0/1, pass-to-pass 0/0; failed: t::new"
    assert lines[2] == f"r: 1 of 2 graded changes completed, 0 errors; records in {out_dir}"
    assert "1 changes skipped: their task is not of acme/auth: other__repo-42" in captured.err
    assert json.loads((out_dir / task.id / "loop" / "grade.json").read_text())["reason"] == "tests failed"

    # --id picks tasks of a folder; a task that is not in the file and a diff that is not a git diff are errors.
    (folder / "acme__auth-9.patch").write_text(MODIFY)
    assert main(["e2e", "grade", "r", "--tasks", str(tasks), "--patch", str(folder), "--id", "acme__auth-9"]) == 1
    assert "acme__auth-9 acme__auth-9: error: no task acme__auth-9 in" in capsys.readouterr().out
    bad = tmp_path / "bad.patch"
    bad.write_text("--- a/pkg/core.py\n+++ b/pkg/core.py\n@@ -1 +1 @@\n-a\n+b\n")
    assert main(["e2e", "grade", "r", "--tasks", str(tasks), "--patch", str(bad), "--id", task.id]) == 1
    assert "not a git diff" in capsys.readouterr().out

    # A missing image names the command that builds it again.
    monkeypatch.setattr(e2e, "image_exists", lambda tag: False)
    assert main(["e2e", "grade", "r", "--tasks", str(tasks), "--patch", str(good), "--id", task.id]) == 1
    assert f"--id {task.id} --rebuild" in capsys.readouterr().out
