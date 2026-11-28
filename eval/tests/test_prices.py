import json

import pytest

from cmeval import prices


def _usage(inp=0, five=0, hour=0, read=0, out=0, split=True):
    usage = {"input_tokens": inp, "cache_creation_input_tokens": five + hour, "cache_read_input_tokens": read,
             "output_tokens": out}
    if split:
        usage["cache_creation"] = {"ephemeral_5m_input_tokens": five, "ephemeral_1h_input_tokens": hour}
    return usage


def test_request_cost_of_each_class():
    # Sonnet: 2.00, 2.50, 4.00, 0.10 and 10.00 USD for each million tokens.
    usage = _usage(inp=1_000_000, five=1_000_000, hour=1_000_000, read=1_000_000, out=1_000_000)
    assert prices.request_cost("claude-sonnet-5-5", usage) == pytest.approx(18.60)
    assert prices.request_cost("claude-opus-5-5", _usage(out=1_000_000)) == pytest.approx(20.0)
    # A date after the model id is the same model.
    assert prices.request_cost("claude-sonnet-5-5-20261101", _usage(read=1_000_000)) == pytest.approx(0.10)


def test_haiku_card_depends_on_the_prompt_of_the_request():
    # A prompt of exactly 100,000 tokens (input, cache reads and cache writes) gets the first card.
    small = _usage(inp=10_000, five=20_000, hour=30_000, read=40_000, out=1_000)
    assert prices.prompt_tokens(prices.token_classes(small)) == 100_000
    assert prices.request_cost("claude-haiku-5-5", small) == pytest.approx(
        (10_000 * 0.10 + 20_000 * 0.125 + 30_000 * 0.20 + 40_000 * 0.01 + 1_000 * 0.50) / 1e6)
    large = _usage(inp=10_001, five=20_000, hour=30_000, read=40_000, out=1_000)
    assert prices.request_cost("claude-haiku-5-5", large) == pytest.approx(
        (10_001 * 0.50 + 20_000 * 0.625 + 30_000 * 1.00 + 40_000 * 0.05 + 1_000 * 2.50) / 1e6)
    # Output tokens do not count in the prompt.
    assert prices.request_cost("claude-haiku-5-5", _usage(inp=1, out=200_000)) == pytest.approx(
        (0.10 + 200_000 * 0.50) / 1e6)


def test_no_price_without_the_model_or_the_cache_split():
    assert prices.request_cost("claude-other-1", _usage(inp=10)) is None
    assert prices.request_cost(None, _usage(inp=10)) is None
    assert prices.request_cost("claude-haiku-5-5", _usage(inp=10, five=5, split=False)) is None
    # Without a cache write, the split is not needed.
    assert prices.request_cost("claude-haiku-5-5", _usage(inp=10, split=False)) == pytest.approx(1e-6)
    wrong = {**_usage(inp=10, five=5), "cache_creation_input_tokens": 9}
    assert prices.request_cost("claude-haiku-5-5", wrong) is None


def _log(path, lines):
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def test_log_cost_counts_the_answered_message_requests(tmp_path):
    assert prices.log_cost(tmp_path / "none.jsonl") is None
    lines = [
        {"seq": 1, "path": "/v1/messages", "status": 200, "model": "claude-sonnet-5-5",
         "response_model": "claude-sonnet-5-5", "usage": _usage(inp=1_000_000)},
        {"seq": 2, "path": "/v1/messages", "status": 200, "model": "claude-sonnet-5-5", "usage": _usage(out=100_000)},
        {"seq": 3, "path": "/v1/messages", "status": 429, "model": "claude-sonnet-5-5", "error": {"type": "x"}},
        {"seq": 4, "path": "/v1/messages/count_tokens", "status": 200, "counted_input_tokens": 50},
        {"seq": 5, "path": "/v1/messages", "status": 200, "model": "claude-haiku-5-5",
         "usage": _usage(inp=1, read=100_000)},
    ]
    cost = prices.log_cost(_log(tmp_path / "proxy.jsonl", lines))
    assert cost["usd"] == pytest.approx(2.0 + 1.0 + (0.50 + 100_000 * 0.05) / 1e6)
    assert (cost["requests"], cost["unpriced"], cost["large_prompts"]) == (3, 0, 2)
    lines.append({"seq": 6, "path": "/v1/messages", "status": 200, "model": "claude-other-1", "usage": _usage(inp=1)})
    cost = prices.log_cost(_log(tmp_path / "proxy.jsonl", lines))
    assert cost["usd"] is None and cost["unpriced"] == 1
