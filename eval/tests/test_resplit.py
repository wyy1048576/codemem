"""cmeval resplit: split a task's change again with the recipe's rule for test files."""

import json
import subprocess

import pytest
from conftest import RemoteRepo

from cmeval import generate as gen
from cmeval import resplit
from cmeval.repos import ensure_clone
from cmeval.tasks import Fix, Gold, Span, dumps, load_tasks, save_tasks

REPO = "acme/db"


def _recipe(**fields):
    base = dict(name="db", repo=REPO, base_image="i", test="t {files} {junit}", test_files=("test/**/*.test",))
    base.update(fields)
    return gen.Recipe(**base)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A repo with a base commit and a fix merged with a merge commit. Returns (repo, base, merge)."""
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "Test")
        monkeypatch.setenv(f"{key}_EMAIL", "test@example.com")
    root = tmp_path / "db"
    root.mkdir()
    repo = RemoteRepo(root)
    repo.git("init", "-q", "-b", "main")
    base = repo.commit({"src/a.cpp": "int a() { return 1; }\n", "src/CMakeLists.txt": "add(a.cpp)\n",
                        "test/sql/a.test": "query I\nSELECT 1\n----\n1\n", "README.md": "db\n"}, "base")
    repo.git("checkout", "-q", "-b", "fix")
    repo.commit({"src/a.cpp": "int a() { return 2; }\n", "src/b.cpp": "int b() { return 3; }\n",
                 "src/CMakeLists.txt": "add(a.cpp)\nadd(b.cpp)\n", "test/sql/a.test": "query I\nSELECT 2\n----\n2\n",
                 "test/sql/b_test.cpp": "// test\n", "data/x.bin": "\x00\x01\x02binary\x00",
                 ".github/workflows/ci.yml": "on: push\n", "requirements.txt": "foo==2\n"}, "the fix")
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "-m", "Merge pull request #7", "fix")
    merge = repo.git("rev-parse", "HEAD")
    ensure_clone(REPO, url=str(root))
    return repo, base, merge


def _code_patch(repo, base, merge):
    """The task's patch as the collector made it: the code files only."""
    return repo.git("diff", base, merge, "--", "src/a.cpp", "src/b.cpp") + "\n"


def _task(make_task, git, base, merge, **overrides):
    fields = dict(id="acme__db-7", repo=REPO, base_commit=base, language="cpp",
                  fix=Fix(pr_number=7, merge_type="merge"), patch=_code_patch(git, base, merge),
                  test_patch=git.git("diff", base, merge, "--", "test/sql/b_test.cpp") + "\n",
                  gold=Gold(files=["src/a.cpp"], functions=[Span("src/a.cpp", 1, 1, "a")], lines=[Span("src/a.cpp", 1, 1)]),
                  tags={"has_test_patch": True})
    fields.update(overrides)
    return make_task(**fields)


def test_match_globs():
    assert resplit.match("test/sql/a.test", ("test/**",)) == "test/**"
    assert resplit.match("pkg/requirements.txt", ("**/requirements*.txt",)) == "**/requirements*.txt"
    assert resplit.match("requirements.txt", ("**/requirements*.txt",)) == "**/requirements*.txt"
    assert resplit.match("src/test/a.test", ("test/**",)) is None


def test_default_test_paths_come_from_test_files():
    assert resplit.default_test_paths(_recipe(test_files=("pandas/tests/**/test_*.py",))) == ("pandas/tests/**",)
    playwright = gen.Recipe(name="p", repo="a/b", base_image="i", suite=(
        gen.Suite(("tests/library/**/*.spec.ts", "tests/page/**/*.spec.ts"), "t"),
        gen.Suite(("tests/mcp/**/*.spec.ts",), "t")))
    assert resplit.default_test_paths(playwright) == ("tests/**",)
    assert resplit.default_test_paths(_recipe(test_files=("**/*_test.go",))) == ()
    assert resplit.rules(_recipe(test_paths=("t/**",))).test_paths == ("t/**",)
    assert resplit.rules(_recipe()).leave_out == resplit.DEFAULT_LEAVE_OUT
    assert resplit.rules(_recipe(leave_out=())).leave_out == ()


def test_resplit_puts_every_file_on_one_side(db, make_task):
    repo, base, merge = db
    task = _task(make_task, repo, base, merge)
    commit, diff = resplit.fix_change(task)
    assert commit == merge
    outcome = resplit.resplit_task(task, diff, resplit.rules(_recipe(test_paths=("test/**", "data/**"))))
    new = outcome.task
    assert outcome.changed
    assert gen.changed_files(new.test_patch) == ["data/x.bin", "test/sql/a.test", "test/sql/b_test.cpp"]
    assert outcome.test_added == ["data/x.bin", "test/sql/a.test"]
    assert gen.changed_files(new.patch) == ["requirements.txt", "src/CMakeLists.txt", "src/a.cpp", "src/b.cpp"]
    assert new.patch.startswith(task.patch)  # the code part is the task's own text
    assert outcome.left_out == [(".github/workflows/ci.yml", "leave_out .github/**")]
    assert outcome.dependency_files == ["requirements.txt"] == new.tags["dependency_files"]
    assert new.tags["resplit"]["fix_added"] == ["requirements.txt", "src/CMakeLists.txt"]
    # Gold labels and difficulty do not move.
    assert new.gold == task.gold and gen.difficulty(new.patch) == gen.difficulty(task.patch)
    assert "GIT binary patch" in new.test_patch


def test_the_new_patches_apply_at_the_base_commit(db, make_task, tmp_path):
    repo, base, merge = db
    task = _task(make_task, repo, base, merge)
    new = resplit.resplit_task(task, resplit.fix_change(task)[1], resplit.rules(_recipe(test_paths=("test/**", "data/**")))).task
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(repo.root), str(work)], check=True)
    subprocess.run(["git", "checkout", "-q", base], cwd=work, check=True)
    for name, text in (("test.patch", new.test_patch), ("fix.patch", new.patch)):
        (tmp_path / name).write_text(text)
        subprocess.run(["git", "apply", str(tmp_path / name)], cwd=work, check=True)
    assert (work / "data/x.bin").read_bytes() == b"\x00\x01\x02binary\x00"
    assert (work / "src/CMakeLists.txt").read_text() == "add(a.cpp)\nadd(b.cpp)\n"


def test_a_task_with_nothing_to_add_stays_byte_identical(db, make_task):
    repo, base, merge = db
    task = _task(make_task, repo, base, merge)
    # Every non-code file is a test file or left out, and the test patch already has the tests.
    full_tests = repo.git("diff", base, merge, "--", "test", "data") + "\n"
    task = _task(make_task, repo, base, merge, test_patch=full_tests)
    rules = resplit.rules(_recipe(test_paths=("test/**", "data/**"), leave_out=(".github/**", "src/CMakeLists.txt",
                                                                                 "requirements.txt")))
    outcome = resplit.resplit_task(task, resplit.fix_change(task)[1], rules)
    assert not outcome.changed and outcome.task is task


def test_a_task_whose_code_files_differ_is_not_split(db, make_task):
    repo, base, merge = db
    task = _task(make_task, repo, base, merge, patch=repo.git("diff", base, merge, "--", "src/a.cpp") + "\n")
    outcomes, _ = resplit.resplit_tasks(_recipe(), [task])
    assert outcomes[0].problem and outcomes[0].task is task


def test_a_rebase_merge_finds_its_last_commit(db, make_task):
    repo, base, _ = db
    # Two commits on main after the base, the second completes the fix.
    repo.git("checkout", "-q", "-b", "rebased", base)
    first = repo.commit({"src/a.cpp": "int a() { return 2; }\n"}, "part 1")
    second = repo.commit({"src/b.cpp": "int b() { return 3; }\n"}, "part 2")
    other = "acme/rebased"
    ensure_clone(other, url=str(repo.root))
    subprocess.run(["git", "--git-dir", str(resplit.repos.clone_path(other)), "symbolic-ref", "HEAD", "refs/heads/rebased"],
                   check=True)
    task = _task(make_task, repo, base, second, id="acme__rebased-7", repo=other, test_patch=None,
                 fix=Fix(pr_number=7, merge_type="rebase"))
    assert first != second and resplit.fix_change(task)[0] == second


def test_resplit_file_writes_the_repo_tasks_and_a_meta_file(db, make_task, tmp_path):
    repo, base, merge = db
    task = _task(make_task, repo, base, merge)
    other = make_task()  # another repo: not in the output
    source = tmp_path / "in.jsonl"
    save_tasks(source, [task, other])
    recipe = _recipe(test_paths=("test/**", "data/**"))
    dry = resplit.resplit_file(recipe, source, None)
    assert dry.out is None and not (tmp_path / "out.jsonl").exists()
    result = resplit.resplit_file(recipe, source, tmp_path / "out.jsonl")
    written = load_tasks(tmp_path / "out.jsonl")
    assert [t.id for t in written] == [task.id] and written[0].test_patch == result.tasks[0].test_patch
    meta = json.loads((tmp_path / "out.meta.json").read_text())
    assert meta["kind"] == "resplit" and meta["recipe"] == "db" and meta["changed"] == 1
    assert meta["test_files_added"] == 2 and meta["fix_files_added"] == 2 and meta["with_dependency_files"] == 1
    assert meta["files_left_out"] == {"leave_out .github/**": 1} and meta["not_split"] == {}
    assert meta == {**meta, "source": "in.jsonl", "with_test_patch_before": 1, "with_test_patch_after": 1}
    with pytest.raises(resplit.ResplitError, match="write over"):
        resplit.resplit_file(recipe, source, source)


def test_an_unchanged_row_keeps_its_bytes_in_the_file(db, make_task, tmp_path):
    repo, base, merge = db
    task = _task(make_task, repo, base, merge, patch=repo.git("diff", base, merge, "--", "src/a.cpp") + "\n")
    source = tmp_path / "in.jsonl"
    save_tasks(source, [task])
    resplit.resplit_file(_recipe(), source, tmp_path / "out.jsonl")  # not split: the code files differ
    assert (tmp_path / "out.jsonl").read_text() == dumps(task) + "\n" == source.read_text()


def test_duckdb_recipe_test_files():
    recipe = gen.load_recipe("duckdb")
    assert recipe.test_paths == ("test/**", "data/**", "tools/shell/tests/**")

    class T:
        test_patch = "".join(f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1 +1 @@\n+x\n"
                             for f in ("test/sql/a.test", "test/sql/b.test_slow", "test/configs/c.json",
                                       "test/api/d.cpp", "tools/shell/tests/test_e.py", "tools/shell/tests/conftest.py"))

    assert gen.task_test_files(recipe, T) == ["test/sql/a.test", "test/sql/b.test_slow", "tools/shell/tests/test_e.py"]
    # The test command takes the files as they are and writes the JUnit file itself.
    assert "{files}" in recipe.suites[0].test and "{junit}" in recipe.suites[0].test
