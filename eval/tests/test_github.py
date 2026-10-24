import json

import pytest

from cmeval.github import GitHub, GitHubError, cache_key


class FakeRunner:
    """Stands in for `gh`: returns the next answer and records each call."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, args, stdin):
        self.calls.append((args, stdin))
        return json.dumps(self.answers.pop(0))


def make_gh(tmp_path, runner, **kwargs):
    return GitHub(runner=runner, cache_dir=tmp_path / "cache", min_interval=0, **kwargs)


def test_rest_answer_is_cached(tmp_path):
    runner = FakeRunner({"default_branch": "main"})
    gh = make_gh(tmp_path, runner)
    assert gh.rest("repos/acme/demo") == {"default_branch": "main"}
    assert make_gh(tmp_path, runner).rest("repos/acme/demo") == {"default_branch": "main"}
    assert len(runner.calls) == 1
    assert runner.calls[0][0] == ["api", "repos/acme/demo"]


def test_graphql_sends_query_and_variables_on_stdin(tmp_path):
    runner = FakeRunner({"data": {"viewer": {"login": "a"}}})
    gh = make_gh(tmp_path, runner)
    assert gh.graphql("query { viewer { login } }", {"x": 1}) == {"viewer": {"login": "a"}}
    args, stdin = runner.calls[0]
    assert args == ["api", "graphql", "--input", "-"]
    assert json.loads(stdin) == {"query": "query { viewer { login } }", "variables": {"x": 1}}
    assert gh.api_calls == 1 and gh.cache_hits == 0


def test_refresh_asks_again(tmp_path):
    runner = FakeRunner({"n": 1}, {"n": 2})
    make_gh(tmp_path, runner).rest("x")
    assert make_gh(tmp_path, runner, refresh=True).rest("x") == {"n": 2}
    assert make_gh(tmp_path, runner).rest("x") == {"n": 2}  # the new answer replaced the old one


def test_cache_key_does_not_depend_on_variable_order():
    assert cache_key("graphql", "q", {"a": 1, "b": 2}) == cache_key("graphql", "q", {"b": 2, "a": 1})
    assert cache_key("graphql", "q", {"a": 1}) != cache_key("graphql", "q", {"a": 2})
    assert cache_key("rest", "q") != cache_key("graphql", "q")


def test_graphql_errors_raise_and_are_not_cached(tmp_path):
    runner = FakeRunner({"errors": [{"message": "Bad query"}]}, {"data": {"ok": True}})
    gh = make_gh(tmp_path, runner)
    with pytest.raises(GitHubError, match="Bad query"):
        gh.graphql("query { bad }")
    assert gh.graphql("query { bad }") == {"ok": True}  # asked again: the error was not stored


def test_low_rate_limit_stops(tmp_path):
    runner = FakeRunner({"data": {"search": {}, "rateLimit": {"remaining": 10}}})
    with pytest.raises(GitHubError, match="rate limit"):
        make_gh(tmp_path, runner).graphql("query { search }")


def test_text_that_is_not_json_raises(tmp_path):
    gh = GitHub(runner=lambda args, stdin: "<html>", cache_dir=tmp_path, min_interval=0)
    with pytest.raises(GitHubError, match="not JSON"):
        gh.rest("x")
