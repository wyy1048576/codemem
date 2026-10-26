import json
import re
from datetime import date

import pytest

from cmeval import repos
from cmeval.collect.candidates import Candidate, Funnel, Settings
from cmeval.collect.tasks_build import (
    MAX_PR_FILES,
    Skip,
    build_tasks,
    candidate_to_task,
    fetch_pr_files,
    merge_base,
    patch_paths,
    write_task_set,
)
from cmeval.github import GitHub
from cmeval.tasks import assign_split, load_tasks

from conftest import REMOTE_REPO

CORE = """\
import os


def load(path):
    with open(path) as f:
        return f.read()


class Store:
    def get(self, key):
        return self.data[key]
"""

CORE_FIXED = CORE.replace("        return self.data[key]", "        return self.data.get(key)")


def settings(**overrides):
    values = dict(name="fresh-t", since=date(2026, 7, 1), until=date(2026, 10, 22))
    values.update(overrides)
    return Settings(**values)


def candidate(merge_commit, n_commits=1, subjects=None, pr=7, **overrides):
    values = dict(
        repo=REMOTE_REPO, pr_number=pr, pr_url=f"https://github.com/{REMOTE_REPO}/pull/{pr}",
        pr_created_at="2026-07-02T00:00:00Z", merged_at="2026-07-03T00:00:00Z", base_ref="main",
        merge_commit=merge_commit, commit_oids=[], commit_subjects=subjects or ["fix"] * n_commits,
        commits_total=n_commits, changed_files=1, issue_number=3,
        issue_url=f"https://github.com/{REMOTE_REPO}/issues/3", issue_created_at="2026-07-01T00:00:00Z",
        query="Store.get raises KeyError\n\nWith a missing key, `Store.get` raises instead of returning None.",
        hints=None, link_method="both", tags={"body_edited_after_fix": False, "title_edited_after_fix": False},
    )
    values.update(overrides)
    return Candidate(**values)


@pytest.fixture
def history(remote):
    """The remote repo with pkg/core.py on main, cloned again so the clone sees every commit."""
    base = remote.commit({"pkg/core.py": CORE}, "add core")
    return remote, base


# ---- merge types


def test_squash_merge(history):
    remote, base = history
    squash = remote.commit({"pkg/core.py": CORE_FIXED}, "Fix Store.get (#7)")
    assert merge_base(REMOTE_REPO, candidate(squash)) == (base, "squash")


def test_merge_commit_uses_the_first_parent(history):
    remote, base = history
    remote.git("checkout", "-q", "-b", "fix")
    remote.commit({"pkg/core.py": CORE_FIXED}, "fix one")
    remote.commit({"pkg/other.py": "X = 1\n"}, "fix two")
    remote.git("checkout", "-q", "main")
    remote.commit({"README.md": "readme\n"}, "unrelated work on main")
    main_before = remote.git("rev-parse", "HEAD")
    remote.git("merge", "-q", "--no-ff", "-m", "Merge pull request #7", "fix")
    merge = remote.git("rev-parse", "HEAD")
    assert merge_base(REMOTE_REPO, candidate(merge, n_commits=2)) == (main_before, "merge")


def test_rebase_merge_goes_back_n_commits(history):
    remote, base = history
    remote.commit({"pkg/core.py": CORE_FIXED}, "Use dict.get")
    last = remote.commit({"pkg/other.py": "X = 1\n"}, "Add other")
    cand = candidate(last, n_commits=2, subjects=["Use dict.get", "Add other"])
    assert merge_base(REMOTE_REPO, cand) == (base, "rebase")


def test_several_pr_commits_with_other_subjects_is_a_squash(history):
    remote, base = history
    squash = remote.commit({"pkg/core.py": CORE_FIXED}, "Fix Store.get (#7)")
    cand = candidate(squash, n_commits=3, subjects=["wip", "more wip", "review fixes"])
    assert merge_base(REMOTE_REPO, cand) == (base, "squash")


def test_unknown_merge_commit_is_skipped(history):
    with pytest.raises(Skip) as info:
        merge_base(REMOTE_REPO, candidate("f" * 40))
    assert info.value.args == ("base_found", "merge commit not found")
    with pytest.raises(Skip):
        merge_base(REMOTE_REPO, candidate(None))


# ---- candidate to task


def test_candidate_to_task(history):
    remote, base = history
    squash = remote.commit({"pkg/core.py": CORE_FIXED, "tests/test_core.py": "def test_get():\n    pass\n",
                            "docs/news.rst": "fixed\n"}, "Fix Store.get (#7)")
    paths = ["pkg/core.py", "tests/test_core.py", "docs/news.rst"]
    task = candidate_to_task(candidate(squash), settings(), paths)
    assert task.id == "acme__demo-7" and task.split == assign_split("acme__demo-7") and task.source == "fresh"
    assert task.base_commit == base and task.fix.merge_type == "squash" and task.language == "python"
    assert [f.symbol for f in task.gold.functions] == ["Store.get"]
    assert task.gold.files == ["pkg/core.py"]
    assert "tests/test_core.py" in task.test_patch and "docs/news.rst" not in task.patch + task.test_patch
    tags = task.tags
    assert tags["gold_languages"] == ["python"] and tags["gold_all_python"] is True
    assert tags["max_gold_file_bytes"] == len(CORE.encode()) and tags["max_gold_file_lines"] == CORE.count("\n")
    assert tags["identifier_in_query"] is True and tags["has_test_patch"] is True
    assert tags["link_method"] == "both" and tags["fix_opened_at"] == "2026-07-02T00:00:00Z"
    assert tags["n_code_files"] == 1 and tags["code_lines_changed"] == 2
    assert tags["repo_py_files"] == 2  # app.py and pkg/core.py at the base commit


def test_file_list_must_match_the_pr(history):
    remote, _ = history
    squash = remote.commit({"pkg/core.py": CORE_FIXED}, "fix")
    with pytest.raises(Skip) as info:
        candidate_to_task(candidate(squash), settings(), ["pkg/core.py", "pkg/missing.py"])
    assert info.value.args[0] == "files_match"
    with pytest.raises(Skip, match="more than"):
        candidate_to_task(candidate(squash), settings(), None)


def test_size_filters(history):
    remote, _ = history
    docs = remote.commit({"docs/a.rst": "a\n"}, "docs only")
    with pytest.raises(Skip) as info:
        candidate_to_task(candidate(docs), settings(), ["docs/a.rst"])
    assert info.value.args == ("size_ok", "no code files")

    many = {f"pkg/m{i}.py": f"X = {i}\n" for i in range(3)}
    remote.commit(many, "add modules")
    changed = remote.commit({k: v.replace("X", "Y") for k, v in many.items()}, "rename X")
    with pytest.raises(Skip, match="too many code files"):
        candidate_to_task(candidate(changed), settings(max_code_files=2), list(many))
    with pytest.raises(Skip, match="too many changed lines"):
        candidate_to_task(candidate(changed), settings(max_code_lines=5), list(many))


def test_only_new_files_has_nothing_to_find(history):
    remote, _ = history
    added = remote.commit({"pkg/new.py": "def f():\n    pass\n"}, "add new module")
    with pytest.raises(Skip) as info:
        candidate_to_task(candidate(added), settings(), ["pkg/new.py"])
    assert info.value.args == ("labeled", "only new files")


def test_gold_in_another_language_is_kept_but_not_all_python(history):
    remote, _ = history
    remote.commit({"src/fast.c": "int add(int a, int b) {\n    return a + b;\n}\n"}, "add C")
    fixed = remote.commit({"src/fast.c": "int add(int a, int b) {\n    return b + a;\n}\n"}, "fix C")
    task = candidate_to_task(candidate(fixed), settings(), ["src/fast.c"])
    assert task.tags["gold_languages"] == ["c"] and task.tags["gold_all_python"] is False
    assert task.tags["partial_labels"] is False  # the labeler reads C since cmeval-labels/4
    assert [s.symbol for s in task.gold.functions] == ["add"]


def test_patch_paths_use_new_names_and_deleted_old_names():
    patch = (
        "diff --git a/a.py b/b.py\nsimilarity index 90%\nrename from a.py\nrename to b.py\n"
        "diff --git a/gone.py b/gone.py\ndeleted file mode 100644\n--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
    )
    assert patch_paths(patch) == {"b.py", "gone.py"}


# ---- GitHub file lists and the whole repo


def files_runner(files_by_pr):
    calls = []

    def runner(args, stdin):
        numbers = [int(n) for n in re.findall(r"p(\d+): pullRequest", json.loads(stdin)["query"])]
        calls.append(numbers)
        repository = {f"p{n}": {"files": {"totalCount": len(files_by_pr[n]), "nodes": [{"path": p} for p in files_by_pr[n]]}}
                      for n in numbers}
        return json.dumps({"data": {"repository": repository, "rateLimit": {"remaining": 4000}}})

    return runner, calls


def test_fetch_pr_files_in_batches(tmp_path):
    files = {n: [f"f{n}.py"] for n in range(1, 61)}
    files[5] = [f"x{i}.py" for i in range(MAX_PR_FILES + 1)]
    runner, calls = files_runner(files)
    found = fetch_pr_files(GitHub(runner=runner, cache_dir=tmp_path, min_interval=0), "acme/demo", files, batch=50)
    assert [len(c) for c in calls] == [50, 10]
    assert found[1] == ["f1.py"] and found[5] is None


def test_build_tasks_fills_the_git_steps_and_writes_the_set(history, tmp_path):
    remote, _ = history
    fix = remote.commit({"pkg/core.py": CORE_FIXED}, "Fix Store.get (#7)")
    docs = remote.commit({"docs/a.rst": "a\n"}, "docs (#8)")
    runner, _ = files_runner({7: ["pkg/core.py"], 8: ["docs/a.rst"]})
    gh = GitHub(runner=runner, cache_dir=tmp_path / "cache", min_interval=0)
    funnel = Funnel(repo=REMOTE_REPO, base_branch="main", since="2026-07-01", until="2026-10-22")
    s = settings()
    tasks = build_tasks(gh, [candidate(fix), candidate(docs, pr=8)], s, funnel)
    assert [t.id for t in tasks] == ["acme__demo-7"]
    assert {k: funnel.counts[k] for k in ("base_found", "files_match", "applies", "size_ok", "labeled")} == \
        {"base_found": 2, "files_match": 2, "applies": 2, "size_ok": 1, "labeled": 1}
    assert funnel.drops == [{"pr": 8, "step": "size_ok", "reason": "no code files"}]

    out = tmp_path / "tasks" / "fresh-t.jsonl"
    write_task_set(out, tasks, [funnel], s, tmp_path / "fresh-t.toml")
    assert [t.id for t in load_tasks(out)] == ["acme__demo-7"]
    meta = json.loads(out.with_suffix(".meta.json").read_text())
    assert meta["repos"][REMOTE_REPO]["counts"]["labeled"] == 1 and meta["stats"]["share_gold_all_python"] == 1.0
    assert meta["stats"]["merge_types"] == {"squash": 1} and meta["config"] == "fresh-t.toml"


def test_build_tasks_reports_candidates_checked(history, tmp_path):
    from cmeval.status import JobStatus

    remote, _ = history
    fix = remote.commit({"pkg/core.py": CORE_FIXED}, "Fix Store.get (#7)")
    docs = remote.commit({"docs/a.rst": "a\n"}, "docs (#8)")
    runner, _ = files_runner({7: ["pkg/core.py"], 8: ["docs/a.rst"]})
    gh = GitHub(runner=runner, cache_dir=tmp_path / "cache", min_interval=0)
    funnel = Funnel(repo=REMOTE_REPO, base_branch="main", since="2026-07-01", until="2026-10-22")
    with JobStatus("collect", "fresh-t", folder=tmp_path / "status", interval=60) as status:
        build_tasks(gh, [candidate(fix), candidate(docs, pr=8)], settings(), funnel, status=status)
    assert status.data["parts"] == {REMOTE_REPO: {"done": 2, "total": 2}}
    assert status.data["done"] == 0  # the job's own count is repos; the CLI advances it


def test_apply_check_on_the_bare_clone(history):
    remote, base = history
    fixed = remote.commit({"pkg/core.py": CORE_FIXED}, "fix")
    good = remote.diff(base, fixed)
    bad = good.replace("-        return self.data[key]", "-        return self.items[key]")
    assert repos.apply_check(REMOTE_REPO, base, good) is None
    assert "patch does not apply" in repos.apply_check(REMOTE_REPO, base, bad)


def test_a_git_error_drops_only_that_candidate(history, tmp_path, monkeypatch):
    remote, _ = history
    fix = remote.commit({"pkg/core.py": CORE_FIXED}, "Fix Store.get (#7)")
    other = remote.commit({"pkg/core.py": CORE_FIXED + "\n\nY = 2\n"}, "Add Y (#9)")
    real_diff = repos.diff

    def diff(repo, old, new):
        if new == other:
            raise repos.RepoError("git diff failed: bad object")
        return real_diff(repo, old, new)

    monkeypatch.setattr(repos, "diff", diff)
    runner, _ = files_runner({7: ["pkg/core.py"], 9: ["pkg/core.py"]})
    gh = GitHub(runner=runner, cache_dir=tmp_path / "cache", min_interval=0)
    funnel = Funnel(repo=REMOTE_REPO, base_branch="main", since="2026-07-01", until="2026-10-22")
    tasks = build_tasks(gh, [candidate(fix), candidate(other, pr=9)], settings(), funnel)
    assert [t.id for t in tasks] == ["acme__demo-7"]
    assert funnel.drops == [{"pr": 9, "step": "files_match", "reason": "git error (git diff failed: bad object)"}]
    assert funnel.counts["base_found"] == 2 and funnel.counts["files_match"] == 1
