import subprocess

import pytest

from cmeval.metrics.accuracy import accuracy_metrics
from cmeval.metrics.latency import index_costs, percentile, search_latency
from cmeval.metrics.matching import excluded, file_units, hit_matches, line_iou, raw_relevance
from cmeval.metrics import tokens as tokens_module
from cmeval.metrics.tokens import AnthropicCounter, EstimateCounter, TokenCountError, find_api_key, make_counter, token_metrics
from cmeval.retriever import Hit
from cmeval.tasks import Gold, Span

FN = Span("a.py", 100, 150, "f")  # 51 lines


# ---- matching (Decision 2)


@pytest.mark.parametrize(
    "hit, expected",
    [
        (Hit("a.py", 98, 150), True),  # decorator included: IoU 51/53
        (Hit("a.py", 120, 130), True),  # inside the gold function
        (Hit("a.py", 1, 800), False),  # file-header-like hit: IoU 51/800
        (Hit("b.py", 100, 150), False),  # other file
        (Hit("a.py"), False),  # no line numbers
        (Hit("a.py", 126, 175), False),  # IoU 25/76 = 0.33
    ],
)
def test_hit_matches_examples(hit, expected):
    assert hit_matches(hit, FN, 0.5) is expected


def test_iou_threshold_edge():
    # gold 1-10 and hit 6-15: shared 5, covered 15 -> 0.333; gold 1-10 and hit 1-20: 10/20 = 0.5
    assert line_iou(1, 10, 6, 15) == pytest.approx(1 / 3)
    assert hit_matches(Hit("a.py", 1, 20), Span("a.py", 1, 10), 0.5) is True
    assert hit_matches(Hit("a.py", 1, 21), Span("a.py", 1, 10), 0.5) is False  # 10/21


def test_file_level_ranks_unique_paths():
    hits = [Hit("x.py"), Hit("x.py"), Hit("gold.py"), Hit("x.py")]
    rel = raw_relevance(hits, ["gold.py"], "file", 0.5)
    assert rel == [set(), set(), {0}, set()]
    assert file_units(hits, rel) == [set(), {0}]  # gold.py is rank 2 in the file list, not 3


def test_exclusions(make_task):
    task = make_task()
    assert excluded(task, "file", "function") == "file-granularity system"
    assert excluded(task, "file", "file") is None
    assert excluded(make_task(tags={"partial_labels": True}), "line", "class") == "partial labels"
    assert excluded(make_task(gold=Gold(files=["auth/sessions.py"])), "line", "function") == "no gold at this level"


# ---- accuracy


def test_gold_at_rank_three():
    m = accuracy_metrics([set(), set(), {0}], n_gold=1)
    assert m["mrr"] == pytest.approx(1 / 3)
    assert (m["recall@1"], m["recall@5"], m["success@5"]) == (0.0, 1.0, 1.0)
    assert m["precision@5"] == pytest.approx(1 / 5)  # divided by k, not by the hits returned


def test_two_gold_items_one_found_and_each_counted_once():
    m = accuracy_metrics([{0}, {0}, set()], n_gold=2)
    assert (m["recall@10"], m["success@10"], m["mrr"]) == (0.5, 0.0, 1.0)
    assert m["precision@5"] == pytest.approx(2 / 5)  # two relevant positions, one gold item
    assert accuracy_metrics([], n_gold=1)["mrr"] == 0.0


# ---- tokens (Decision 6)


def test_token_metrics():
    rel = [set(), set(), {0}, {1}]
    m = token_metrics([400, 300, 200, 600], rel, n_gold=2, budgets=(500, 1000, 1500))
    assert (m["tokens_to_first"], m["found"]) == (900.0, 1.0)  # 400 + 300 + 200
    assert m["recall@budget500"] == 0.0  # only the first hit fits
    assert m["recall@budget1000"] == 0.5  # first three hits (900)
    assert m["recall@budget1500"] == 1.0  # all four (1500)
    none = token_metrics([10, 10], [set(), set()], n_gold=1)
    assert (none["tokens_to_first"], none["found"]) == (None, 0.0)


class FakeClient:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail
        self.messages = self

    def count_tokens(self, model, messages):
        if self.fail:
            raise ConnectionError("offline")
        text = messages[0]["content"]
        self.calls.append(text)

        class R:
            input_tokens = 7 + len(text.split())  # 7 = fixed overhead + "a" is 1 word

        return R()


def test_anthropic_counter_subtracts_overhead_and_caches(tmp_path):
    client = FakeClient()
    counter = AnthropicCounter(client=client, cache_dir=tmp_path)
    assert counter.count(["one two three", "", "one two three", "x"]) == [3, 0, 3, 1]
    assert counter.overhead == 7
    assert sorted(client.calls) == ["a", "one two three", "x"]  # each unique text once; threads may reorder
    again = AnthropicCounter(client=FakeClient(), cache_dir=tmp_path)
    assert again.count(["one two three"]) == [3] and again.client.calls == []  # cache and overhead on disk


def test_anthropic_counter_error_is_clear_and_has_no_key(tmp_path):
    counter = AnthropicCounter(client=FakeClient(fail=True), cache_dir=tmp_path)
    with pytest.raises(TokenCountError, match="--tokens estimate"):
        counter.count(["text"])


def test_find_api_key_order(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert find_api_key() == "from-env"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(tokens_module.sys, "platform", "darwin")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="from-keychain\n", stderr="")

    monkeypatch.setattr(tokens_module.subprocess, "run", fake_run)
    assert find_api_key() == "from-keychain"
    assert calls[0][:2] == ["security", "find-generic-password"] and "anthropic-api-key" in calls[0]


def test_no_key_is_an_error_and_estimates_need_to_be_asked_for(monkeypatch):
    monkeypatch.setattr(tokens_module, "find_api_key", lambda: None)
    with pytest.raises(TokenCountError, match="no Anthropic API key"):
        make_counter("anthropic")  # never a quiet fallback that could replace real numbers
    warnings = []
    counter = make_counter("estimate", warnings.append)
    assert isinstance(counter, EstimateCounter) and counter.estimate is True and "never report" in warnings[0]
    assert EstimateCounter().count(["1234567"]) == [2]


# ---- latency


def test_latency():
    assert search_latency([10.0, 30.0, 20.0]) == {"search_ms_median": 20.0, "search_ms_p95": 30.0}
    assert percentile(list(range(1, 101)), 0.95) == 95
    rows = [
        {"system": "a", "mode": "build", "report": {"seconds": 2.0, "bytes_on_disk": 10, "items_reembedded": 8, "extra": {"files_failed": 1}}},
        {"system": "a", "mode": "update", "report": {"seconds": 1.0, "bytes_on_disk": 12, "items_reembedded": 2, "extra": {}}},
        {"system": "a", "mode": "update", "report": {"seconds": 3.0, "bytes_on_disk": 11, "items_reembedded": 0, "extra": {}}},
        {"system": "b", "mode": "update", "report": {"seconds": 0.01, "bytes_on_disk": 12, "items_reembedded": 0, "extra": {}}},
    ]
    costs = index_costs(rows, "a")
    assert costs == {"build_seconds_mean": 2.0, "update_seconds_median": 2.0, "items_reembedded_mean": 10 / 3,
                     "index_bytes_max": 12, "files_failed_max": 1.0}


def test_rate_limiter_spaces_calls():
    import time

    from cmeval.metrics.tokens import _RateLimiter

    limiter = _RateLimiter(rpm=1200)  # one call every 0.05 s
    start = time.monotonic()
    for _ in range(5):
        limiter.wait()
    assert time.monotonic() - start >= 0.19  # 4 gaps of 0.05 s


def test_counts_are_saved_before_a_later_failure(tmp_path):
    class FailsOnSecond(FakeClient):
        def count_tokens(self, model, messages):
            if messages[0]["content"] == "second":
                raise ConnectionError("network gone")
            return super().count_tokens(model, messages)

    counter = AnthropicCounter(client=FailsOnSecond(), cache_dir=tmp_path, workers=1, rpm=0)
    with pytest.raises(TokenCountError):
        counter.count(["first", "second"])
    again = AnthropicCounter(client=FakeClient(), cache_dir=tmp_path, rpm=0)
    assert again.count(["first"]) == [1] and again.client.calls == []  # "first" was kept


# ---- review fixes


def test_whitespace_only_text_is_counted_after_an_a(tmp_path):
    class RefusesWhitespace(FakeClient):
        def count_tokens(self, model, messages):
            assert messages[0]["content"].strip(), "the API refuses whitespace-only text"
            return super().count_tokens(model, messages)

    counter = AnthropicCounter(client=RefusesWhitespace(), cache_dir=tmp_path, rpm=0)
    assert counter.count(["\n\n"]) == [0]  # "a\n\n" is one word: 8 - 1 - overhead 7 = 0


def test_counts_that_finish_after_a_failure_are_kept(tmp_path):
    import time

    class FailsFirst(FakeClient):
        def count_tokens(self, model, messages):
            text = messages[0]["content"]
            if text == "bad":
                raise ConnectionError("gone")  # fails at once ...
            time.sleep(0.2)  # ... while the others are still running
            return super().count_tokens(model, messages)

    counter = AnthropicCounter(client=FailsFirst(), cache_dir=tmp_path, workers=4, rpm=0)
    counter._overhead = 7  # skip the overhead call, so the failure really comes first
    with pytest.raises(TokenCountError):
        counter.count(["bad", "good one", "good two", "good three"])
    again = AnthropicCounter(client=FakeClient(), cache_dir=tmp_path, rpm=0)
    again._overhead = 7
    assert again.count(["good one", "good two", "good three"]) == [2, 2, 2] and again.client.calls == []


def test_bad_rpm_setting_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("CMEVAL_TOKEN_RPM", "fast")
    with pytest.raises(TokenCountError, match="CMEVAL_TOKEN_RPM"):
        AnthropicCounter(client=FakeClient(), cache_dir=tmp_path)


def test_repeated_index_rows_count_once_and_failures_are_not_summed():
    row = lambda task, seconds, failed: {"system": "a", "task_id": task, "mode": "update",
                                         "report": {"seconds": seconds, "bytes_on_disk": 1, "items_reembedded": 0, "extra": {"files_failed": failed}}}
    rows = [row("t1", 1.0, 1), row("t2", 9.0, 1), row("t2", 0.01, 1), row("t3", 5.0, 1)]  # t2 again after a resume: no work left
    costs = index_costs(rows, "a")
    assert costs["update_seconds_median"] == 5.0 and costs["files_failed_max"] == 1.0  # the first t2 row counts
