import json
import re
from datetime import date

import pytest

from cmeval.collect.candidates import (
    FUNNEL_STEPS,
    GIT_STEPS,
    GITHUB_STEPS,
    CollectError,
    Settings,
    collect_candidates,
    load_settings,
    render_funnel,
    write_candidates,
)
from cmeval.collect.repo_stats import Candidate as RepoEntry
from cmeval.github import GitHub

from conftest import FIXTURES

REPO = "pandas-dev/pandas"
RECORDED = json.loads((FIXTURES / "gh" / "pandas-collect.json").read_text())
CASES = RECORDED["cases"]


class RecordedGitHub:
    """Fake `gh` that answers from the recorded pandas data, the way GitHub would."""

    def __init__(self, prs=None, issues=None):
        self.prs = prs if prs is not None else RECORDED["prs"]
        self.issues = issues if issues is not None else RECORDED["issues"]

    def __call__(self, args, stdin):
        if args[1] == f"repos/{REPO}":
            return json.dumps({"default_branch": "main"})
        query = json.loads(stdin)
        if "search(" in query["query"]:
            start, end = re.search(r"merged:(\S+)\.\.(\S+)", query["variables"]["q"]).groups()
            nodes = [p for p in self.prs if start <= p["mergedAt"][:10] <= end]
            return json.dumps({"data": {"search": {"issueCount": len(nodes), "nodes": nodes,
                                                   "pageInfo": {"hasNextPage": False, "endCursor": None}},
                                        "rateLimit": {"remaining": 4000}}})
        numbers = re.findall(r"i(\d+): issueOrPullRequest", query["query"])
        return json.dumps({"data": {"repository": {f"i{n}": self.issues.get(n) for n in numbers},
                                    "rateLimit": {"remaining": 4000}}})


def settings(**overrides):
    values = dict(name="fresh-test", since=date(2025, 6, 1), until=date(2026, 10, 22), repos=[RepoEntry(REPO)])
    values.update(overrides)
    return Settings(**values)


def run(tmp_path, runner=None, **overrides):
    gh = GitHub(runner=runner or RecordedGitHub(), cache_dir=tmp_path / "cache", min_interval=0)
    return collect_candidates(gh, REPO, settings(**overrides))


def test_funnel_on_recorded_pandas_prs(tmp_path):
    candidates, funnel = run(tmp_path)
    assert list(funnel.counts) == [key for key, _ in FUNNEL_STEPS]
    github_counts = {key: funnel.counts[key] for key, _ in GITHUB_STEPS}
    assert github_counts == {"merged": 10, "opened_after_cutoff": 10, "not_bot": 9, "one_link": 7, "is_issue": 6,
                             "issue_before_pr": 6, "body_ok": 5, "no_leak": 5}
    assert all(funnel.counts[key] is None for key, _ in GIT_STEPS)  # B2 fills these
    by_pr = {c.pr_number: c for c in candidates}
    assert set(by_pr) == {CASES[k] for k in ("both", "list", "regex", "title_renamed", "body_edited")}
    assert by_pr[CASES["both"]].link_method == "both"
    assert by_pr[CASES["list"]].link_method == "list"
    assert by_pr[CASES["regex"]].link_method == "regex"
    assert by_pr[CASES["title_renamed"]].tags["title_edited_after_fix"] is True
    assert by_pr[CASES["body_edited"]].tags["body_edited_after_fix"] is True
    # One PR is "both" in the full data; trimming its body for the fixture cut the regex match.
    assert funnel.link_methods == {"both": 2, "list": 2, "regex": 1}


def test_drop_reasons_name_each_case(tmp_path):
    _, funnel = run(tmp_path)
    reasons = {d["pr"]: d["reason"] for d in funnel.drops}
    assert reasons[CASES["bot"]].startswith("bot author")
    assert reasons[CASES["no_link"]] == "no linked issue"
    assert reasons[CASES["several"]].startswith("several linked issues (#")
    assert reasons[CASES["is_pr"]].startswith("link is a PR")
    assert reasons[CASES["short"]].startswith("short body")
    assert funnel.drop_reasons()["no linked issue"] == 1


def test_candidate_fields(tmp_path):
    candidates, _ = run(tmp_path)
    c = next(c for c in candidates if c.pr_number == CASES["both"])
    assert c.pr_url.endswith(f"/pull/{c.pr_number}") and c.issue_url.endswith(f"/issues/{c.issue_number}")
    assert c.base_ref == "main" and len(c.merge_commit) == 40 and c.commits_total >= len(c.commit_oids) >= 1
    assert c.issue_created_at < c.merged_at
    assert "\n\n" in c.query and "<!--" not in c.query


def test_extra_bots_and_body_limit_are_settings(tmp_path):
    login = next(p for p in RECORDED["prs"] if p["number"] == CASES["both"])["author"]["login"]
    _, funnel = run(tmp_path, extra_bots=[login])
    assert funnel.counts["not_bot"] < 9
    _, funnel = run(tmp_path / "b", min_body_chars=10**6)
    assert funnel.counts["body_ok"] == 0


def test_pr_opened_before_the_cutoff_is_dropped(tmp_path):
    opened = sorted(p["createdAt"] for p in RECORDED["prs"])
    cut = opened[3][:10]  # PRs opened before this day are dropped
    _, funnel = run(tmp_path, since=date.fromisoformat(cut))
    early = sum(1 for p in RECORDED["prs"] if p["createdAt"][:10] < cut and p["mergedAt"][:10] >= cut)
    assert early > 0
    assert funnel.counts["opened_after_cutoff"] == funnel.counts["merged"] - early
    assert any(d["reason"].startswith("fix PR opened before the start date") for d in funnel.drops)


def test_issue_opened_after_the_pr_is_dropped(tmp_path):
    prs = [p for p in RECORDED["prs"] if p["number"] == CASES["both"]]
    number = str(next(iter(prs[0]["closingIssuesReferences"]["nodes"]))["number"])
    late = json.loads(json.dumps(RECORDED["issues"][number]))
    late["createdAt"] = "2030-01-01T00:00:00Z"  # after the PR was opened (and after the merge)
    _, funnel = run(tmp_path, RecordedGitHub(prs=prs, issues={number: late}))
    assert funnel.counts["issue_before_pr"] == 0 and funnel.drops[0]["reason"] == "issue opened after the fix PR"


def test_missing_issue_and_leak(tmp_path):
    prs = [p for p in RECORDED["prs"] if p["number"] == CASES["both"]]
    number = str(next(iter(prs[0]["closingIssuesReferences"]["nodes"]))["number"])
    _, funnel = run(tmp_path, RecordedGitHub(prs=prs, issues={number: None}))
    assert funnel.drops[0]["reason"].startswith("issue not found")

    leaky = json.loads(json.dumps(RECORDED["issues"][number]))
    leaky["body"] += f"\n\nA fix is in #{prs[0]['number']}."
    leaky["userContentEdits"] = {"totalCount": 0, "nodes": []}
    _, funnel = run(tmp_path / "b", RecordedGitHub(prs=prs, issues={number: leaky}))
    assert funnel.counts["no_leak"] == 0 and funnel.drops[0]["reason"].startswith("leak (mentions the fix PR")


def test_write_and_render(tmp_path):
    candidates, funnel = run(tmp_path)
    out = tmp_path / "out"
    write_candidates(out, candidates, funnel)
    rows = [json.loads(line) for line in (out / "candidates.jsonl").read_text().splitlines()]
    assert len(rows) == 5 and rows[0]["repo"] == REPO
    saved = json.loads((out / "funnel.json").read_text())
    assert saved["counts"]["no_leak"] == 5 and saved["drop_reasons"]["no linked issue"] == 1
    table = render_funnel([funnel, funnel])
    assert "| pandas-dev/pandas | 10 | 10 | 9 | 7 | 6 | 6 | 5 | 5 | 2 | 1 | 2 |" in table
    assert "| **Total** | 20 |" in table
    assert "## Git steps" not in table  # B2 did not run


# ---- config


def test_load_settings(tmp_path):
    path = tmp_path / "fresh-x.toml"
    path.write_text('[collect]\nsince = "2026-07-01"\nuntil = "2026-10-22"\nextra_bots = ["helper"]\n\n'
                    '[[repo]]\nname = "acme/demo"\n')
    s = load_settings(path)
    assert s.name == "fresh-x" and s.since == date(2026, 7, 1) and s.min_body_chars == 100
    assert s.extra_bots == ["helper"] and [r.name for r in s.repos] == ["acme/demo"]


@pytest.mark.parametrize("collect, problem", [
    ("", "needs a [collect] table"),
    ('[collect]\nsince = "2026-07-01"\n', "needs until"),
    ('[collect]\nsince = "2026-07-01"\nuntil = "2026-06-01"\n', "before since"),
    ('[collect]\nsince = "2026-07-01"\nuntil = "July"\n', "bad date"),
    ('[collect]\nsince = "2026-07-01"\nuntil = "2026-08-01"\nmin_body = 5\n', "unknown [collect] keys"),
])
def test_load_settings_rejects_bad_configs(tmp_path, collect, problem):
    path = tmp_path / "c.toml"
    path.write_text(collect + '\n[[repo]]\nname = "acme/demo"\n')
    with pytest.raises(CollectError, match=re.escape(problem)):
        load_settings(path)


def test_fresh_v1_config_loads():
    s = load_settings(FIXTURES.parents[1] / "configs" / "fresh-v1.toml")
    assert s.name == "fresh-v1" and len(s.repos) == 7 and s.since == date(2026, 7, 1)
