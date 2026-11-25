"""Build and validate: the parts that need no Docker."""

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
    assert "one 't/one/a.ts' /work/before-1.0.xml" in script
    assert "two 't/two/b.ts' /work/after-1.1.xml" in script


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
