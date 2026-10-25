import pytest

from cmeval.collect.links import PR_KEYWORDS, find_links, list_links, regex_links

REPO = "acme/demo"


def pr(title="", body="", messages=(), listed=()):
    return {
        "title": title,
        "body": body,
        "commits": {"nodes": [{"commit": {"message": m}} for m in messages]},
        "closingIssuesReferences": {"nodes": [{"number": n, "repository": {"nameWithOwner": r}} for n, r in listed]},
    }


@pytest.mark.parametrize("word", sorted(PR_KEYWORDS))
def test_every_keyword_links_in_any_case(word):
    assert regex_links(pr(body=f"{word} #12"), REPO) == {12}
    assert regex_links(pr(body=f"{word.upper()} #13"), REPO) == {13}


def test_full_issue_url_of_the_same_repo():
    assert regex_links(pr(body="Fixes https://github.com/acme/demo/issues/7"), REPO) == {7}
    assert regex_links(pr(body="Fixes https://github.com/other/demo/issues/7"), REPO) == set()


def test_only_closing_keywords_count():
    assert regex_links(pr(body="see #12, related to #13, part of #14"), REPO) == set()
    assert regex_links(pr(body="Fixes: #12"), REPO) == set()  # SWE-bench's pattern needs white space, not ":"


def test_html_comments_are_removed_first():
    body = "<!-- If this fixes an issue, write: fixes #1 -->\nThis PR fixes #2."
    assert regex_links(pr(body=body), REPO) == {2}


def test_title_and_commit_messages_are_read():
    assert regex_links(pr(title="Fix #3: crash on empty input"), REPO) == {3}
    assert regex_links(pr(messages=["Handle empty input\n\ncloses #4"]), REPO) == {4}


def test_list_links_keep_the_same_repo_only():
    p = pr(listed=[(5, "acme/demo"), (6, "Acme/Demo"), (7, "acme/frontend")])
    assert list_links(p, REPO) == {5, 6}


def test_union_records_the_method():
    p = pr(body="fixes #1 and resolves #2", listed=[(2, REPO), (3, REPO)])
    assert find_links(p, REPO) == {1: "regex", 2: "both", 3: "list"}
    assert find_links(pr(), REPO) == {}
