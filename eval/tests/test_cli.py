from dataclasses import replace

import pytest

from cmeval.cli import main
from cmeval.tasks import dumps, save_tasks


def test_help_lists_commands(capsys):
    with pytest.raises(SystemExit) as info:
        main(["--help"])
    assert info.value.code == 0
    out = capsys.readouterr().out
    for name in ("validate", "import", "collect", "review", "run", "score", "report", "repo-stats", "dashboard"):
        assert name in out


def test_planned_command_exits_2(capsys):
    assert main(["review", "runs/x"]) == 2
    assert "cmeval review: not built yet" in capsys.readouterr().err


def test_validate_good_file(make_task, tmp_path, capsys):
    path = tmp_path / "tasks.jsonl"
    other = make_task(id="acme__auth-43", split="dev", fix=replace(make_task().fix, pr_number=43))
    save_tasks(path, [make_task(), other])
    assert main(["validate", str(path)]) == 0
    out = capsys.readouterr().out
    assert "2 tasks, valid" in out
    assert "split: dev 1, test 1" in out
    assert "source: fresh 2" in out


def test_validate_bad_file(make_task, tmp_path, capsys):
    path = tmp_path / "tasks.jsonl"
    path.write_text(dumps(make_task(split="train")) + "\n", encoding="utf-8")
    assert main(["validate", str(path)]) == 1
    err = capsys.readouterr().err
    assert "tasks.jsonl:1 (acme__auth-42): split 'train'" in err
    assert "not valid (1 problems)" in err


def test_validate_missing_file(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "nope.jsonl")]) == 1
    assert "no such file" in capsys.readouterr().err


def test_repo_stats_writes_tables_and_json(tmp_path, monkeypatch, capsys):
    import json

    import cmeval.github

    answers = {
        "repos/acme/demo": {"default_branch": "main", "size": 1000, "archived": False},
        "repos/acme/demo/languages": {"Python": 2000},
    }
    empty_page = {"data": {"search": {"issueCount": 0, "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}},
                           "rateLimit": {"remaining": 4000}}}

    def runner(args, stdin):
        return json.dumps(empty_page if args[1] == "graphql" else answers[args[1]])

    real = cmeval.github.GitHub
    monkeypatch.setattr(cmeval.github, "GitHub", lambda refresh=False, progress=None: real(runner=runner, min_interval=0))
    out = tmp_path / "stats"
    code = main(["repo-stats", "--repo", "acme/demo", "--since", "2026-07-01", "--until", "2026-07-02", "--out", str(out)])
    assert code == 0
    printed = capsys.readouterr()
    assert "| acme/demo | main | 1 | 0.0 | 100% | Python 100% |" in printed.out
    assert "| acme/demo | not asked (--functions) |" in printed.out
    assert (out / "stats.md").read_text() in printed.out
    data = json.loads((out / "stats.json").read_text())
    assert data["since"] == "2026-07-01" and data["repos"][0]["funnel"]["merged"] == 0
    assert data["api_calls"] == 3


def test_repo_stats_needs_repos_and_good_dates(tmp_path, capsys):
    assert main(["repo-stats"]) == 1
    assert "--candidates" in capsys.readouterr().err
    assert main(["repo-stats", "--repo", "acme/demo", "--since", "July"]) == 1
    assert "repo-stats:" in capsys.readouterr().err


def test_collect_dry_run_writes_nothing_and_full_run_writes(tmp_path, monkeypatch, capsys):
    import json

    import cmeval.github
    from cmeval.paths import collect_dir

    config = tmp_path / "fresh-t.toml"
    config.write_text('[collect]\nsince = "2026-07-01"\nuntil = "2026-07-02"\n\n[[repo]]\nname = "acme/demo"\n')
    empty = {"data": {"search": {"issueCount": 0, "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}},
                      "rateLimit": {"remaining": 4000}}}

    def runner(args, stdin):
        return json.dumps(empty if args[1] == "graphql" else {"default_branch": "main"})

    real = cmeval.github.GitHub
    monkeypatch.setattr(cmeval.github, "GitHub", lambda **kw: real(runner=runner, min_interval=0, **kw))
    assert main(["collect", str(config), "--dry-run"]) == 0
    out = capsys.readouterr()
    assert "| acme/demo | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |" in out.out and "dry run" in out.err
    assert not (collect_dir() / "fresh-t").exists()

    assert main(["collect", str(config), "--out", str(tmp_path / "tasks" / "fresh-t.jsonl")]) == 0
    assert (collect_dir() / "fresh-t" / "acme__demo" / "candidates.jsonl").exists()
    assert (tmp_path / "tasks" / "fresh-t.jsonl").exists() and (tmp_path / "tasks" / "fresh-t.meta.json").exists()
    assert (collect_dir() / "fresh-t" / "acme__demo" / "funnel.json").exists()

    assert main(["collect", str(config), "--repo", "other/repo"]) == 1
    assert "not in" in capsys.readouterr().err

    from cmeval.paths import status_dir
    from cmeval.status import read_all

    dry, full = sorted((job for job in read_all(status_dir()) if job["job"] == "collect"), key=lambda job: job["started"])
    assert (full["name"], full["state"], full["done"], full["total"], full["unit"]) == ("fresh-t", "done", 1, 1, "repos")
    assert full["result"]["tasks"] == 0 and dry["result"]["tasks"] is None


def test_repo_stats_status_shows_retries_and_failures(tmp_path, monkeypatch, capsys):
    import json

    import cmeval.github
    from cmeval.github import GitHubError
    from cmeval.paths import status_dir
    from cmeval.status import read_all

    answers = {
        "repos/acme/demo": {"default_branch": "main", "size": 1000, "archived": False},
        "repos/acme/demo/languages": {"Python": 2000},
    }
    empty_page = {"data": {"search": {"issueCount": 0, "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}},
                           "rateLimit": {"remaining": 4000}}}
    failures = ["gh api failed: HTTP 502"]  # the first call fails once, then works

    def runner(args, stdin):
        if failures:
            raise GitHubError(failures.pop())
        if args[1] == "repos/gone/repo":
            raise GitHubError("gh api failed: HTTP 404")
        return json.dumps(empty_page if args[1] == "graphql" else answers[args[1]])

    real = cmeval.github.GitHub
    monkeypatch.setattr(cmeval.github, "GitHub",
                        lambda refresh=False, progress=None: real(runner=runner, min_interval=0, sleep=lambda s: None,
                                                                  progress=progress))
    args = ["--since", "2026-07-01", "--until", "2026-07-02", "--out", str(tmp_path / "stats")]
    assert main(["repo-stats", "--repo", "acme/demo", *args]) == 0
    assert "trying again" in capsys.readouterr().err  # retry messages are no longer lost
    assert main(["repo-stats", "--repo", "gone/repo", *args]) == 1
    good, bad = sorted(read_all(status_dir()), key=lambda job: job["started"])
    assert (good["job"], good["name"], good["state"], good["done"], good["total"]) == \
        ("repo-stats", "2026-07-01 to 2026-07-02", "done", 1, 1)
    assert good["retries"] == 1 and any("trying again" in line for line in good["log"])
    assert bad["state"] == "failed" and "HTTP 404" in bad["error"]
