import json
import re

from cmeval.collect.issues import body_at, build_query, fetch_issues, hints_before, issues_query, leak, title_at
from cmeval.github import GitHub

OPENED = "2026-07-10T00:00:00Z"  # when the fix PR was opened


def issue(body="now", edits=(), renames=(), comments=(), title="Now title"):
    """edits: (editedAt, text) pairs in any order; GitHub returns them newest first."""
    nodes = [{"editedAt": t, "deletedAt": None, "diff": text} for t, text in sorted(edits, reverse=True)]
    return {
        "__typename": "Issue", "title": title, "body": body,
        "userContentEdits": {"totalCount": len(nodes), "nodes": nodes},
        "timelineItems": {"nodes": [{"createdAt": t, "previousTitle": a, "currentTitle": b} for t, a, b in renames]},
        "comments": {"nodes": [{"createdAt": t, "author": a, "body": b} for t, a, b in comments]},
    }


# ---- body and title at a moment


def test_body_never_edited_is_the_current_body():
    assert body_at(issue(body="original"), OPENED) == ("original", False, False)


def test_body_edited_only_before_the_pr_is_the_current_body():
    # GitHub did not store old edit texts (diff is null); they are not needed here
    old = issue(body="current", edits=[("2017-01-01T00:00:00Z", None), ("2017-01-02T00:00:00Z", None)])
    assert body_at(old, OPENED) == ("current", False, False)


def test_body_edited_after_the_pr_uses_the_version_before():
    i = issue(body="v3 explains the fix", edits=[
        ("2026-07-01T00:00:00Z", "v1"), ("2026-07-05T00:00:00Z", "v2"), ("2026-07-20T00:00:00Z", "v3 explains the fix")])
    assert body_at(i, OPENED) == ("v2", True, False)


def test_body_created_after_the_pr_uses_the_oldest_version():
    i = issue(body="v2", edits=[("2026-07-11T00:00:00Z", "v1"), ("2026-07-12T00:00:00Z", "v2")])
    assert body_at(i, OPENED) == ("v1", True, False)


def test_body_version_text_missing():
    i = issue(body="v2", edits=[("2026-07-01T00:00:00Z", None), ("2026-07-20T00:00:00Z", "v2")])
    assert body_at(i, OPENED) == ("", True, True)


def test_title_before_a_rename():
    i = issue(title="Fix the parser for X", renames=[
        ("2026-07-01T00:00:00Z", "first", "second"), ("2026-07-15T00:00:00Z", "second", "Fix the parser for X")])
    assert title_at(i, OPENED) == ("second", True)
    assert title_at(issue(title="same"), OPENED) == ("same", False)


def test_hints_keep_people_before_the_pr():
    i = issue(comments=[
        ("2026-07-02T00:00:00Z", {"__typename": "User", "login": "ann"}, "I see it too <!-- hidden -->"),
        ("2026-07-03T00:00:00Z", {"__typename": "Bot", "login": "stale"}, "This issue is stale"),
        ("2026-07-11T00:00:00Z", {"__typename": "User", "login": "bob"}, "Fixed in #99"),
    ])
    assert hints_before(i, OPENED) == "I see it too"
    assert hints_before(issue(), OPENED) is None


def test_build_query_format():
    assert build_query(" Crash on empty input ", "Steps:\n<!-- template -->\n1. run it\n") == \
        "Crash on empty input\n\nSteps:\n\n1. run it"


# ---- leak check

FIX = {"number": 123, "mergeCommit": {"oid": "a1b2c3d4e5f6" + "0" * 28},
       "commits": {"nodes": [{"commit": {"oid": "fedcba9876" + "1" * 30}}]}}


def test_leak_finds_the_pr_and_its_commits():
    assert "PR #123" in leak("Fixed by #123", FIX)
    assert "PR #123" in leak("see https://github.com/acme/demo/pull/123", FIX)
    assert "a1b2c3d" in leak("Bisected to A1B2C3D, then fixed", FIX)
    assert "fedcba9876" in leak("in commit fedcba9876", FIX)


def test_leak_has_no_false_hits():
    assert leak("Also seen in #1234 and #12, and in issue 123", FIX) is None
    assert leak("commit a1b2c3 is too short; 0123456789abc is another commit", FIX) is None
    assert leak("HTML entity &#123; is not a PR", FIX) is None


# ---- batched fetch


def test_fetch_issues_in_batches(tmp_path):
    calls = []

    def runner(args, stdin):
        query = json.loads(stdin)["query"]
        numbers = [int(n) for n in re.findall(r"i(\d+): issueOrPullRequest", query)]
        calls.append(numbers)
        repository = {f"i{n}": None if n == 7 else {"__typename": "PullRequest"} if n == 8 else {"__typename": "Issue", "number": n}
                      for n in numbers}
        errors = [{"type": "NOT_FOUND", "message": "missing"}] if 7 in numbers else []
        return json.dumps({"data": {"repository": repository, "rateLimit": {"remaining": 4000}}, "errors": errors})

    gh = GitHub(runner=runner, cache_dir=tmp_path, min_interval=0)
    found = fetch_issues(gh, "acme/demo", [9, 7, 8, *range(10, 60)], batch=50)
    assert [len(c) for c in calls] == [50, 3]
    assert calls[0][:3] == [7, 8, 9]  # sorted, so the same set gives the same batches
    assert found[7] is None and found[8]["__typename"] == "PullRequest" and found[59]["number"] == 59
    fetch_issues(gh, "acme/demo", [9, 7, 8, *range(10, 60)], batch=50)
    assert len(calls) == 2  # the second run is answered from the cache, NOT_FOUND included


def test_issues_query_names_the_repo_and_aliases():
    q = issues_query("acme/demo", [3, 4])
    assert 'repository(owner: "acme", name: "demo")' in q
    assert "i3: issueOrPullRequest(number: 3)" in q and "i4: issueOrPullRequest(number: 4)" in q
