"""Build and validate: the parts that need no Docker."""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from cmeval import generate as gen
from cmeval.generate import FAIL, PASS, SKIP


def _patch(*files, lines=1):
    body = "".join("+x\n" for _ in range(lines))
    return "".join(f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1 +1 @@\n{body}" for f in files)


def test_difficulty_classes():
    assert gen.difficulty(_patch("a.py", lines=15)) == "easy"
    assert gen.difficulty(_patch("a.py", lines=16)) == "medium"
    assert gen.difficulty(_patch("a.py", "b.py", lines=50)) == "medium"
    assert gen.difficulty(_patch("a.py", "b.py", lines=51)) == "hard"
    assert gen.difficulty(_patch("a.py", "b.py", "c.py")) == "hard"


def test_exclude_newer_is_the_sunday_of_the_week():
    monday = 1790553600  # 2026-09-28 00:00 UTC, a Monday
    assert gen.exclude_newer(monday) == "2026-10-04T23:59:59Z"
    assert gen.exclude_newer(monday + 6 * 86400 + 3600) == "2026-10-04T23:59:59Z"
    assert gen.exclude_newer(monday + 7 * 86400) == "2026-10-11T23:59:59Z"


def test_load_recipe_pandas():
    recipe = gen.load_recipe("pandas")
    assert recipe.repo == "pandas-dev/pandas"
    assert recipe.name == "pandas"
    assert "{files}" in recipe.test and "{junit}" in recipe.test
    # A test file that does not import before the fix must not stop the other files.
    assert "--continue-on-collection-errors" in recipe.test


def test_load_recipe_playwright():
    recipe = gen.load_recipe("playwright")
    assert len(recipe.suites) == 3
    # A fixed number of workers, so test time does not depend on the host's processors.
    assert all("--workers=4" in suite.test for suite in recipe.suites)
    # CI turns on retries.
    assert all("CI=" not in suite.test for suite in recipe.suites) and "CI" not in dict(recipe.env)


def test_load_recipe_rejects_unknown_fields(tmp_path):
    path = tmp_path / "x.toml"
    path.write_text('repo = "a/b"\nbase_image = "i"\ntest = "t"\nsetup = []\n')
    with pytest.raises(gen.GenerateError, match="unknown fields: setup"):
        gen.load_recipe(path)


def test_recipe_with_suites_and_env(tmp_path):
    path = tmp_path / "x.toml"
    path.write_text(
        'repo = "a/b"\nbase_image = "i"\n[env]\nB = "2"\nA = "1"\n'
        '[[suite]]\ntest_files = ["t/one/**"]\ntest = "one {files} {junit}"\n'
        '[[suite]]\ntest_files = ["t/two/**"]\ntest = "two {files} {junit}"\n'
    )
    recipe = gen.load_recipe(path)
    assert recipe.env == (("A", "1"), ("B", "2"))

    class T:
        test_patch = _patch("t/one/a.ts", "t/two/b.ts", "t/three/c.ts")

    assert gen.task_test_files(recipe, T) == ["t/one/a.ts", "t/two/b.ts"]
    script = gen._script(recipe, T, repeats=1)
    assert """bash -c 'one '"'"'t/one/a.ts'"'"' /work/before-1.0.xml'""" in script
    assert """bash -c 'two '"'"'t/two/b.ts'"'"' /work/after-1.1.xml'""" in script
    assert 'echo "before-1 0 $r ' in script and 'echo "after-1 1 $r ' in script


def test_recipe_test_and_fix_paths_do_not_change_fingerprints(tmp_path, make_task):
    path = tmp_path / "x.toml"
    path.write_text('repo = "a/b"\nbase_image = "i"\ntest = "t"\ntest_paths = ["test/**"]\nfix_paths = ["src/**"]\n')
    recipe = gen.load_recipe(path)
    assert recipe.test_paths == ("test/**",) and recipe.fix_paths == ("src/**",)
    plain = replace(recipe, test_paths=(), fix_paths=())
    task = make_task()
    assert gen.image_fingerprint(recipe, task) == gen.image_fingerprint(plain, task)
    assert gen.validation_fingerprint(recipe, task, 3) == gen.validation_fingerprint(plain, task, 3)


def test_recipe_needs_test_or_suites(tmp_path):
    path = tmp_path / "x.toml"
    path.write_text('repo = "a/b"\nbase_image = "i"\n')
    with pytest.raises(gen.GenerateError, match="give 'test'"):
        gen.load_recipe(path)


def test_test_files_follow_the_recipe_globs():
    recipe = gen.Recipe(name="r", repo="a/b", base_image="i", test="t", test_files=("pkg/tests/**/test_*.py",))

    class T:
        test_patch = _patch("pkg/tests/test_a.py", "pkg/tests/io/test_b.py", "pkg/tests/base/ops.py", "pkg/tests/data/x.csv")

    assert gen.task_test_files(recipe, T) == ["pkg/tests/io/test_b.py", "pkg/tests/test_a.py"]


def test_parse_junit(tmp_path):
    path = tmp_path / "r.xml"
    path.write_text(
        "<testsuites><testsuite>"
        '<testcase classname="m.TestA" name="test_ok"/>'
        '<testcase classname="m.TestA" name="test_bad"><failure message="x"/></testcase>'
        '<testcase classname="m.TestA" name="test_err"><error message="x"/></testcase>'
        '<testcase classname="m.TestA" name="test_skip"><skipped message="x"/></testcase>'
        '<testcase classname="m.TestA" name="test_twice"><error message="x"/></testcase>'
        '<testcase classname="m.TestA" name="test_twice"/>'
        "</testsuite></testsuites>"
    )
    assert gen.parse_junit(path) == {
        "m.TestA::test_ok": PASS, "m.TestA::test_bad": FAIL, "m.TestA::test_err": FAIL,
        "m.TestA::test_skip": SKIP, "m.TestA::test_twice": FAIL,
    }


def test_judge_valid():
    before = [{"a": FAIL, "b": PASS, "s": SKIP}] * 3
    after = [{"a": PASS, "b": PASS, "s": SKIP, "new": PASS}] * 3
    verdict = gen.judge(before, after)
    assert verdict.valid
    assert verdict.fail_to_pass == ["a", "new"]
    assert verdict.pass_to_pass == ["b"]


def test_judge_no_fail_to_pass():
    runs = [{"a": PASS}] * 3
    verdict = gen.judge(runs, runs)
    assert not verdict.valid and verdict.reason == "no test went from failing to passing"


def test_judge_broken_test():
    verdict = gen.judge([{"a": FAIL, "b": PASS}] * 3, [{"a": PASS, "b": FAIL}] * 3)
    assert not verdict.valid and verdict.broken == ["b"]


def test_judge_flaky_test():
    after = [{"a": PASS, "b": PASS}, {"a": PASS, "b": FAIL}, {"a": PASS, "b": PASS}]
    verdict = gen.judge([{"a": FAIL, "b": PASS}] * 3, after)
    assert not verdict.valid and verdict.flaky == ["b"]


def test_judge_a_run_without_results():
    verdict = gen.judge([{"a": FAIL}, {}, {"a": FAIL}], [{"a": PASS}] * 3)
    assert not verdict.valid and verdict.reason == "a test run gave no results"


def test_admission_needs_six_of_ten_in_time():
    recipe = gen.Recipe(name="r", repo="a/b", base_image="i", test="t", timeout_min=10)
    ok = {"valid": True, "slowest_test_run_s": 100.0}
    slow = {"valid": True, "slowest_test_run_s": 700.0}
    bad = {"valid": False}
    assert gen.admission(recipe, [ok] * 6 + [bad] * 4)["admitted"]
    assert not gen.admission(recipe, [ok] * 5 + [slow] + [bad] * 4)["admitted"]


def test_judge_with_runs_that_differ():
    # Before the fix, "a" fails, is skipped, and is missing: it never passes, so it is not flaky.
    before = [{"a": FAIL, "b": PASS, "c": FAIL}, {"a": SKIP, "b": PASS, "c": PASS}, {"b": PASS, "c": FAIL}]
    after = [{"a": PASS, "b": PASS, "c": PASS}, {"a": PASS, "b": PASS, "c": PASS}, {"a": PASS, "b": PASS, "c": PASS}]
    verdict = gen.judge(before, after)
    assert verdict.fail_to_pass == ["a"] and verdict.pass_to_pass == ["b"]
    # "c" passed in one run before the fix: flaky.
    assert verdict.flaky == ["c"] and not verdict.valid
    assert (verdict.failed_before, verdict.skipped_before, verdict.missing_before) == (1, 1, 1)


def test_judge_skip_before_pass_after():
    before = [{"a": SKIP, "b": PASS}] * 3
    after = [{"a": PASS, "b": PASS}] * 3
    verdict = gen.judge(before, after)
    assert verdict.valid and verdict.fail_to_pass == ["a"]
    assert (verdict.failed_before, verdict.skipped_before, verdict.missing_before) == (0, 1, 0)
    # A test that is skipped before and after is in no list.
    verdict = gen.judge([{"a": FAIL, "s": SKIP}] * 3, [{"a": PASS, "s": SKIP}] * 3)
    assert verdict.fail_to_pass == ["a"] and verdict.pass_to_pass == [] and verdict.flaky == []


def test_judge_flaky_after_in_one_run():
    after = [{"a": PASS}, {"a": PASS}, {"a": SKIP}]
    verdict = gen.judge([{"a": FAIL}] * 3, after)
    assert not verdict.valid and verdict.flaky == ["a"]


DELETE_TEST = """\
diff --git a/pkg/tests/test_old.py b/pkg/tests/test_old.py
deleted file mode 100644
index 4444444..0000000
--- a/pkg/tests/test_old.py
+++ /dev/null
@@ -1 +0,0 @@
-def test_x(): pass
"""

RENAME_TEST = """\
diff --git a/pkg/tests/test_a.py b/pkg/tests/test_b.py
similarity index 100%
rename from pkg/tests/test_a.py
rename to pkg/tests/test_b.py
"""

SPACE_TEST = """\
diff --git a/pkg/tests/my dir/test_s.py b/pkg/tests/my dir/test_s.py
--- a/pkg/tests/my dir/test_s.py
+++ b/pkg/tests/my dir/test_s.py
@@ -1 +1 @@
+x
"""


def test_test_files_leave_out_deleted_files():
    recipe = gen.Recipe(name="r", repo="a/b", base_image="i", test="t", test_files=("pkg/tests/**/test_*.py",))

    class T:
        test_patch = _patch("pkg/tests/test_c.py") + DELETE_TEST + RENAME_TEST + SPACE_TEST

    assert gen.task_test_files(recipe, T) == ["pkg/tests/my dir/test_s.py", "pkg/tests/test_b.py",
                                              "pkg/tests/test_c.py"]
    # The fix's size still counts a deleted file.
    assert gen.changed_files(DELETE_TEST + _patch("a.py")) == ["a.py", "pkg/tests/test_old.py"]
    assert gen.difficulty(DELETE_TEST) == "easy"


def test_test_run_line_without_files_does_nothing():
    recipe = gen.Recipe(name="r", repo="a/b", base_image="i", test="t {files}", test_files=("tests/**",))

    class T:
        test_patch = _patch("docs/x.md")

    assert gen.test_run_line(recipe, T, "grade") == ":"


IMAGE_FIELDS = {"repo": "c/d", "base_image": "j", "base_setup": ("apt-get x",), "env": (("A", "1"),),
                "deps_files": ("r.txt",), "deps": ("pip install x",), "build": ("make",)}
TEST_FIELDS = {"test": "u {files}", "test_files": ("x/**",), "refresh": ("make again",), "parser": "other",
               "timeout_min": 20, "suite": (gen.Suite(("t/**",), "s {files}"),)}


def test_every_recipe_field_changes_the_right_fingerprint(make_task):
    recipe = gen.Recipe(name="r", repo="a/b", base_image="i", test="t {files} {junit}")
    task = make_task(test_patch=_patch("t/test_a.py"))
    image, validation = gen.image_fingerprint(recipe, task), gen.validation_fingerprint(recipe, task, 3)
    # test_paths and fix_paths only shape the task data (cmeval resplit); the patches are in the fingerprint.
    data_fields = {"name", "test_paths", "fix_paths"}
    assert set(IMAGE_FIELDS) | set(TEST_FIELDS) == set(gen.Recipe.__dataclass_fields__) - data_fields
    for name, value in IMAGE_FIELDS.items():
        other = replace(recipe, **{name: value})
        assert gen.image_fingerprint(other, task) != image, name
        assert gen.validation_fingerprint(other, task, 3) != validation, name
    for name, value in TEST_FIELDS.items():
        other = replace(recipe, **{name: value})
        assert gen.image_fingerprint(other, task) == image, name
        assert gen.validation_fingerprint(other, task, 3) != validation, name
    # The recipe's name is only the folder and the tag.
    assert gen.validation_fingerprint(replace(recipe, name="q"), task, 3) == validation
    # Task fields: the commit changes both; the patches and the number of runs change the validation only.
    other_commit = make_task(test_patch=task.test_patch, base_commit="f" * 40)
    assert gen.image_fingerprint(recipe, other_commit) != image
    for other in (make_task(test_patch=task.test_patch, patch=task.patch + "+y\n"),
                  make_task(test_patch=_patch("t/test_b.py"))):
        assert gen.image_fingerprint(recipe, other) == image
        assert gen.validation_fingerprint(recipe, other, 3) != validation
    assert gen.validation_fingerprint(recipe, task, 5) != validation
    assert gen.validation_fingerprint(recipe, task, 3) == validation


# ---- validation and build with a stand-in for docker

def _junit(results):
    child = {FAIL: "<failure/>", SKIP: "<skipped/>", PASS: ""}
    cases = "".join(f'<testcase classname="{test_id.split("::")[0]}" name="{test_id.split("::")[1]}">'
                    f"{child[outcome]}</testcase>" for test_id, outcome in results.items())
    return f"<testsuite>{cases}</testsuite>"


def _container(before, after, codes=None, times_extra="", bad_xml=()):
    """What run.sh would write: one JUnit file and one times line for each run (suite 0)."""
    def write(work):
        lines = []
        for phase, runs in (("before", before), ("after", after)):
            for i, results in enumerate(runs, 1):
                name = f"{phase}-{i}"
                (work / f"{name}.0.xml").write_text("<testsuite><testcase" if name in bad_xml else _junit(results))
                lines.append(f"{name} 0 {(codes or {}).get(name, 0)} {1000 * i}")
        (work / "times.txt").write_text(times_extra + "\n".join(lines) + "\n")
    return write


def _fake_docker(monkeypatch, container=None, labels=None, raise_on_run=None):
    """Replace _run. `container(work)` writes the outputs of a docker run. `labels` maps a tag to its label."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:2] == ["docker", "run"]:
            if raise_on_run:
                raise raise_on_run
            if container:
                container(Path(cmd[cmd.index("-v") + 1].rsplit(":", 1)[0]))
        if cmd[:3] == ["docker", "image", "inspect"]:
            label = (labels or {}).get(cmd[-1])
            if label is None:
                return subprocess.CompletedProcess(cmd, 0, "null\n", "")
            return subprocess.CompletedProcess(cmd, 0, json.dumps({gen.FINGERPRINT_LABEL: label}) + "\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(gen, "_run", fake_run)
    return calls


def _recipe(**fields):
    values = dict(name="r", repo="acme/auth", base_image="i", test="pytest {files} --junitxml={junit}",
                  test_files=("pkg/tests/**/test_*.py",), timeout_min=10)
    values.update(fields)
    return gen.Recipe(**values)


GOOD_BEFORE = [{"t::new": FAIL, "t::old": PASS}] * 3
GOOD_AFTER = [{"t::new": PASS, "t::old": PASS}] * 3


def test_validate_task_writes_tests_with_the_fingerprint(make_task, monkeypatch):
    recipe, task = _recipe(), make_task(test_patch=_patch("pkg/tests/test_a.py"))
    calls = _fake_docker(monkeypatch, _container(GOOD_BEFORE, GOOD_AFTER))
    record = gen.validate_task(recipe, task, "tag")
    assert record["valid"] and record["fingerprint"] == gen.validation_fingerprint(recipe, task, 3)
    tests = json.loads(gen.tests_path(recipe, task).read_text())
    assert tests == {"fingerprint": record["fingerprint"], "repeats": 3, "fail_to_pass": ["t::new"],
                     "pass_to_pass": ["t::old"]}
    # One suite with files, three runs on each side, and one more limit.
    [(run, kwargs)] = [(c, k) for c, k in calls if c[:2] == ["docker", "run"]]
    assert kwargs["timeout"] == 10 * 60 * (2 * 3 * 1 + 1)
    assert run[run.index("--name") + 1].startswith("cmeval-validate-")
    # The slowest suite run took 3 s; with one suite the slowest whole run is the same.
    assert record["slowest_test_run_s"] == 3.0 and record["slowest_whole_run_s"] == 3.0


def test_validate_task_limit_counts_suites_with_files(make_task, monkeypatch):
    recipe = _recipe(test="", suite=(gen.Suite(("a/**",), "x {files}"), gen.Suite(("b/**",), "y {files}"),
                                     gen.Suite(("c/**",), "z {files}")))
    task = make_task(test_patch=_patch("a/t.ts", "b/t.ts"))
    calls = _fake_docker(monkeypatch)
    gen.validate_task(recipe, task, "tag", repeats=2)
    [kwargs] = [k for c, k in calls if c[:2] == ["docker", "run"]]
    assert kwargs["timeout"] == 10 * 60 * (2 * 2 * 2 + 1)


def test_a_suite_that_times_out_in_one_run_makes_the_task_invalid(make_task, monkeypatch):
    recipe, task = _recipe(), make_task(test_patch=_patch("pkg/tests/test_a.py"))
    _fake_docker(monkeypatch, _container(GOOD_BEFORE, GOOD_AFTER))
    gen.validate_task(recipe, task, "tag")
    assert gen.tests_path(recipe, task).exists()
    # The same results, but suite 0 of the second run after the fix stopped at its limit.
    _fake_docker(monkeypatch, _container(GOOD_BEFORE, GOOD_AFTER, codes={"after-2": 124}))
    record = gen.validate_task(recipe, task, "tag")
    assert not record["valid"] and record["reason"] == "a test run timed out"
    assert record["timed_out"] == ["after-2.0"] and record["fail_to_pass"] == ["t::new"]
    # The test lists of the earlier validation are gone.
    assert not gen.tests_path(recipe, task).exists()
    _fake_docker(monkeypatch, _container(GOOD_BEFORE, GOOD_AFTER, codes={"before-1": 137}))
    assert gen.validate_task(recipe, task, "tag")["reason"] == "a test run timed out"


def test_validate_task_reasons(make_task, monkeypatch):
    recipe, task = _recipe(), make_task(test_patch=_patch("pkg/tests/test_a.py"))
    for marker in ("test patch failed", "fix patch failed", "refresh failed"):
        # The last line of times.txt is a test run, not the step that failed.
        _fake_docker(monkeypatch, _container(GOOD_BEFORE, GOOD_AFTER, times_extra=f"{marker}\n"))
        record = gen.validate_task(recipe, task, "tag")
        assert not record["valid"] and record["reason"] == marker
    _fake_docker(monkeypatch, _container(GOOD_BEFORE, GOOD_AFTER, bad_xml=("after-3",)))
    record = gen.validate_task(recipe, task, "tag")
    assert not record["valid"] and record["junit_unreadable"] == 1 and "JUnit" in record["reason"]
    # Skip before, pass after: valid, and the count shows it.
    _fake_docker(monkeypatch, _container([{"t::new": SKIP}] * 3, [{"t::new": PASS}] * 3))
    record = gen.validate_task(recipe, task, "tag")
    assert record["valid"] and record["fail_to_pass_skipped_before"] == 1
    assert record["fail_to_pass_failed_before"] == record["fail_to_pass_missing_before"] == 0


def test_validate_task_removes_the_container(make_task, monkeypatch):
    recipe, task = _recipe(), make_task(test_patch=_patch("pkg/tests/test_a.py"))
    calls = _fake_docker(monkeypatch, raise_on_run=subprocess.TimeoutExpired("docker", 1))
    record = gen.validate_task(recipe, task, "tag")
    assert not record["valid"] and record["reason"] == "the container passed its time limit"
    name = calls[0][0][calls[0][0].index("--name") + 1]
    assert calls[-1][0] == ["docker", "rm", "-f", name]
    calls = _fake_docker(monkeypatch, raise_on_run=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        gen.validate_task(recipe, task, "tag")
    assert calls[-1][0][:3] == ["docker", "rm", "-f"]


@pytest.fixture
def no_source(monkeypatch):
    """build_task_image without a clone: the source step does nothing."""
    monkeypatch.setattr(gen, "build_base", lambda recipe: "base")
    monkeypatch.setattr(gen, "_export_source", lambda repo, commit, dest: dest.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(gen.repos, "commit_time", lambda repo, commit: 1790553600)
    monkeypatch.setattr(gen, "nearest_tag", lambda repo, commit: None)


def test_build_task_image_follows_the_label(make_task, monkeypatch, no_source):
    recipe, task = _recipe(), make_task()
    tag, fingerprint = gen.task_tag(recipe, task), gen.image_fingerprint(recipe, task)

    def builds(calls):
        return [c for c, _ in calls if c[:2] == ["docker", "build"]]

    calls = _fake_docker(monkeypatch, labels={tag: fingerprint})
    assert gen.build_task_image(recipe, task) == (tag, 0.0) and not builds(calls)
    for label in (None, "0" * 16):  # no label, or the label of another build
        calls = _fake_docker(monkeypatch, labels={tag: label})
        gen.build_task_image(recipe, task)
        [build] = builds(calls)
        assert build[build.index("--label") + 1] == f"{gen.FINGERPRINT_LABEL}={fingerprint}"
        assert "--no-cache" not in build
    calls = _fake_docker(monkeypatch, labels={tag: fingerprint})
    gen.build_task_image(recipe, task, force=True)
    [build] = builds(calls)
    assert "--no-cache" in build


def test_docker_build_has_a_limit(make_task, monkeypatch, no_source):
    def slow(cmd, **kwargs):
        if cmd[:2] == ["docker", "build"]:
            assert kwargs["timeout"] == gen.BUILD_TIMEOUT_MIN * 60
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        return subprocess.CompletedProcess(cmd, 1, "", "")

    monkeypatch.setattr(gen, "_run", slow)
    with pytest.raises(gen.GenerateError, match="passed its limit of 60 min"):
        gen.build_task_image(_recipe(), make_task())


def test_generate_task_uses_a_saved_record_only_with_its_fingerprint(make_task, monkeypatch):
    recipe, task = _recipe(), make_task(test_patch=_patch("pkg/tests/test_a.py"))
    seen = []
    monkeypatch.setattr(gen, "build_task_image", lambda recipe, task, force=False: ("tag", 1.0))

    def fake_validate(recipe, task, tag, repeats, cpus):
        seen.append(repeats)
        return {"valid": False, "reason": "x", "fingerprint": gen.validation_fingerprint(recipe, task, repeats)}

    monkeypatch.setattr(gen, "validate_task", fake_validate)
    gen.generate_task(recipe, task)
    gen.generate_task(recipe, task)
    assert seen == [3]
    gen.generate_task(recipe, task, repeats=5)
    gen.generate_task(replace(recipe, refresh=("make",)), task, repeats=5)
    gen.generate_task(recipe, task, repeats=5, force=True)
    assert seen == [3, 5, 5, 5]
    # A saved record from before fingerprints is not used.
    saved = gen.task_dir(recipe, task) / "result.json"
    saved.write_text(json.dumps({"id": task.id, "valid": True}))
    gen.generate_task(recipe, task, repeats=5)
    assert seen == [3, 5, 5, 5, 5]


def test_generate_task_checks_the_image_of_a_valid_record(make_task, monkeypatch):
    recipe, task = _recipe(), make_task(test_patch=_patch("pkg/tests/test_a.py"))
    saved = gen.task_dir(recipe, task) / "result.json"
    saved.parent.mkdir(parents=True)
    saved.write_text(json.dumps({"id": task.id, "valid": True,
                                 "fingerprint": gen.validation_fingerprint(recipe, task, 3)}))
    gen.tests_path(recipe, task).write_text("{}")
    _fake_docker(monkeypatch, labels={gen.task_tag(recipe, task): gen.image_fingerprint(recipe, task)})
    assert gen.generate_task(recipe, task) == json.loads(saved.read_text())
    # The image is gone: the old record and tests.json go, and the build fails here.
    def no_build(recipe, task, force=False):
        raise gen.GenerateError("no docker")

    monkeypatch.setattr(gen, "build_task_image", no_build)
    _fake_docker(monkeypatch)
    record = gen.generate_task(recipe, task)
    assert record["reason"] == "error: no docker"
    assert not saved.exists() and not gen.tests_path(recipe, task).exists()
