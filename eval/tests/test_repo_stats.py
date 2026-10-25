import json
from datetime import date, timedelta

import pytest

from cmeval.collect import repo_stats
from cmeval.collect.repo_stats import (
    FUNNEL_STEPS,
    Candidate,
    CodeStats,
    RepoStatsError,
    collect_stats,
    load_candidates,
    pr_funnel,
    render_markdown,
)
from cmeval.collect.search import SEARCH_CAP, date_windows, is_bot, search_merged_prs
from cmeval.github import GitHub, GitHubError

from conftest import FIXTURES

HA_PAGE = json.loads((FIXTURES / "gh" / "ha-search-page.json").read_text())
HA_PRS = HA_PAGE["data"]["search"]["nodes"]


def page(count, nodes, cursor=None):
    return {"data": {"search": {"issueCount": count, "nodes": nodes,
                                "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}},
                     "rateLimit": {"cost": 1, "remaining": 4000}}}


class SearchRunner:
    """Fake `gh` for the search: answers from a function of the search string and cursor."""

    def __init__(self, answer, rest=None):
        self.answer = answer
        self.rest = rest or {}
        self.queries = []

    def __call__(self, args, stdin):
        if args[1] != "graphql":
            return json.dumps(self.rest[args[1]])
        variables = json.loads(stdin)["variables"]
        self.queries.append((variables["q"], variables["after"]))
        return json.dumps(self.answer(variables["q"], variables["after"]))


def make_gh(tmp_path, runner):
    return GitHub(runner=runner, cache_dir=tmp_path / "cache", min_interval=0)


# ---- search


def test_date_windows_cover_the_range_without_gaps_or_overlap():
    windows = date_windows(date(2026, 7, 1), date(2026, 7, 20), days=7)
    assert windows[0][0] == date(2026, 7, 1) and windows[-1][1] == date(2026, 7, 20)
    assert windows[-1] == (date(2026, 7, 15), date(2026, 7, 20))  # the last window is shorter
    for (_, end), (start, _) in zip(windows, windows[1:]):
        assert start == end + timedelta(days=1)
    assert date_windows(date(2026, 7, 2), date(2026, 7, 1)) == []
    assert date_windows(date(2026, 7, 1), date(2026, 7, 1)) == [(date(2026, 7, 1), date(2026, 7, 1))]


def test_search_follows_pages(tmp_path):
    def answer(q, after):
        return page(3, [{"number": 1}, {"number": 2}], "c1") if after is None else page(3, [{"number": 3}, {}])

    runner = SearchRunner(answer)
    prs = search_merged_prs(make_gh(tmp_path, runner), "acme/demo", "main", date(2026, 7, 1), date(2026, 7, 3))
    assert [pr["number"] for pr in prs] == [1, 2, 3]  # the empty node (not a PR) is dropped
    q = runner.queries[0][0]
    assert "repo:acme/demo" in q and "base:main" in q and "merged:2026-07-01..2026-07-03" in q
    assert "sort:created-asc" in q


def test_search_splits_a_window_over_the_cap(tmp_path):
    def answer(q, after):
        dates = q.split("merged:")[1].split()[0]
        if dates == "2026-07-01..2026-07-04":
            return page(SEARCH_CAP + 1, [])
        return page(1, [{"number": dates}])

    runner = SearchRunner(answer)
    prs = search_merged_prs(make_gh(tmp_path, runner), "acme/demo", "main", date(2026, 7, 1), date(2026, 7, 4))
    assert [pr["number"] for pr in prs] == ["2026-07-01..2026-07-02", "2026-07-03..2026-07-04"]


def test_search_stops_when_one_day_is_over_the_cap(tmp_path):
    runner = SearchRunner(lambda q, after: page(SEARCH_CAP + 1, []))
    with pytest.raises(GitHubError, match="2026-07-01"):
        search_merged_prs(make_gh(tmp_path, runner), "acme/demo", "main", date(2026, 7, 1), date(2026, 7, 1))


def test_is_bot():
    assert is_bot({"__typename": "Bot", "login": "renovate"})
    assert is_bot({"__typename": "User", "login": "github-actions[bot]"})
    assert is_bot({"__typename": "User", "login": "Dependabot"})
    assert not is_bot({"__typename": "User", "login": "bdraco"})
    assert not is_bot(None)  # a deleted account


# ---- funnel


def test_funnel_on_recorded_home_assistant_page():
    funnel = pr_funnel(HA_PRS, "home-assistant/core")
    assert list(funnel) == [key for key, _ in FUNNEL_STEPS]
    assert funnel == {
        "merged": 10,
        "not_bot": 9,  # renovate
        "one_issue": 6,  # no issue, two issues, issue in home-assistant/frontend
        "issue_before_merge": 5,  # issue opened after the merge
        "few_files": 4,  # 25 changed files
        "body_100": 3,  # body is a hidden comment and one short line
    }


def test_funnel_repo_name_is_not_case_sensitive():
    assert pr_funnel(HA_PRS, "Home-Assistant/Core")["one_issue"] == 6


# ---- candidates file


def test_load_candidates(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('[[repo]]\nname = "acme/demo"\nnote = "small"\n\n[[repo]]\nname = "acme/other"\n')
    assert load_candidates(path) == [Candidate("acme/demo", "small"), Candidate("acme/other", "")]


@pytest.mark.parametrize("text, problem", [
    ("", "needs one or more"),
    ('[[repo]]\nname = "demo"\n', "owner/name"),
    ('[[repo]]\nname = "a/b"\n[[repo]]\nname = "A/B"\n', "twice"),
    ("[[repo]\n", "not valid TOML"),
])
def test_load_candidates_rejects_bad_files(tmp_path, text, problem):
    path = tmp_path / "c.toml"
    path.write_text(text)
    with pytest.raises(RepoStatsError, match=problem):
        load_candidates(path)


def test_candidates_file_in_configs_loads():
    names = [c.name for c in load_candidates(FIXTURES.parents[1] / "configs" / "fresh-candidates.toml")]
    assert "home-assistant/core" in names and len(names) == 16


# ---- the whole command, without network

REST = {
    "repos/home-assistant/core": {"default_branch": "dev", "size": 921000, "archived": False},
    "repos/home-assistant/core/languages": {"Shell": 5_000, "Python": 135_000_000},
    "repos/acme/go": {"default_branch": "main", "size": 5000, "archived": True},
    "repos/acme/go/languages": {"Go": 9_000_000, "Python": 1_000_000},
}


def fake_code_stats(repo, branch, progress=None):
    return CodeStats(commit="ab" * 20, checkout_mb=500.0, files=10, lines=1000, functions=5, methods=7,
                     file_headers=3, chunks=15, embed_hours=0.0)


def test_collect_stats_and_markdown(tmp_path):
    runner = SearchRunner(lambda q, after: HA_PAGE if "home-assistant" in q else page(0, []), rest=REST)
    gh = make_gh(tmp_path, runner)
    results = collect_stats(gh, [Candidate("home-assistant/core", "big"), Candidate("acme/go")],
                            date(2026, 7, 1), date(2026, 7, 7), functions=True, code_fn=fake_code_stats)
    ha, go = results
    assert ha.default_branch == "dev" and ha.python_share > 0.99
    assert list(ha.languages) == ["Python", "Shell"]  # largest first
    assert "base:dev" in runner.queries[0][0]
    assert ha.funnel["body_100"] == 3 and ha.code["chunks"] == 15
    assert go.code is None and "10%" in go.code_skipped  # under the Python share, so no clone

    md = render_markdown(results, date(2026, 7, 1), date(2026, 7, 7))
    assert "# Repo stats, 2026-07-01 to 2026-07-07" in md
    assert "| home-assistant/core | 10 | 9 | 6 | 5 | 4 | 3 |" in md
    assert "acme/go (archived)" in md
    assert "| home-assistant/core | abababababab | 500 | 10 | 1,000 | 5 | 7 | 15 | 0.0 |" in md


def test_code_stats_counts_what_codemem_indexes(remote):
    pytest.importorskip("codemem")
    remote.commit({
        "pkg/mod.py": "import os\n\n\ndef f():\n    return 1\n\n\nclass A:\n    def m(self):\n        pass\n",
        "build/skip.py": "def skipped():\n    pass\n",  # codemem never indexes build/
        "README.md": "not Python\n",
    })
    stats = repo_stats.code_stats("acme/demo", "main", url=f"file://{remote.root}")
    assert stats.commit == remote.shas[-1]
    assert stats.files == 2  # app.py and pkg/mod.py
    assert stats.functions == 1 and stats.methods == 1
    assert stats.chunks == stats.functions + stats.methods + stats.classes + stats.blocks
    assert stats.classes == 1 and stats.blocks >= 1  # class A; `import os` is top-level code
    assert not list((repo_stats.tmp_dir()).glob("repo-stats-*"))  # the clone is deleted


def test_code_stats_bad_branch_raises_and_cleans_up(remote):
    pytest.importorskip("codemem")
    with pytest.raises(RepoStatsError, match="acme/demo"):
        repo_stats.code_stats("acme/demo", "no-such-branch", url=f"file://{remote.root}")
    assert not list((repo_stats.tmp_dir()).glob("repo-stats-*"))
