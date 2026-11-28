"""The cost of a run in USD, from a price table and the token counts of its proxy log.

The table is in USD for each million tokens. It comes from Anthropic's pricing page as read on 2026-11-28 by the
project lead. Each model request has its own price: the sum over its token classes of tokens times the class's
price. A cache write has two prices: one for a 5 minute cache and one for a 1 hour cache. The usage block of the
answer gives the split (cache_creation.ephemeral_5m_input_tokens and ephemeral_1h_input_tokens).

Haiku 5.5 has two cards. The card of a request depends on the size of that request's prompt: its input tokens,
cache reads and cache writes. A prompt up to LARGE_PROMPT tokens gets the first card, a larger one the second.

A model that is not in the table has no price. A request that writes to the cache without the split has no price
either. In both cases the run gets no cost, not a guess.
"""

from __future__ import annotations

from pathlib import Path

from .proxy import MESSAGES_PATH, read_log

LARGE_PROMPT = 100_000
CLASSES = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")

# Model id -> list of (largest prompt for this card or None for no limit, prices of CLASSES in USD per million).
TABLE: dict[str, list[tuple[int | None, tuple[float, ...]]]] = {
    "claude-haiku-5-5": [(LARGE_PROMPT, (0.10, 0.125, 0.20, 0.01, 0.50)),
                         (None, (0.50, 0.625, 1.00, 0.05, 2.50))],
    "claude-sonnet-5-5": [(None, (2.00, 2.50, 4.00, 0.10, 10.00))],
    "claude-opus-5-5": [(None, (4.00, 5.00, 8.00, 0.20, 20.00))],
}


def model_key(model: str | None) -> str | None:
    """The table's id for a model name. A name can carry a suffix such as a date. None for an unknown model."""
    if not model:
        return None
    return next((key for key in TABLE if model.startswith(key)), None)


def token_classes(usage: dict) -> dict[str, int] | None:
    """The tokens of a usage block in the classes of the table. None when the block writes to the cache and does
    not say how much went to each cache, because the two writes have different prices."""
    written = usage.get("cache_creation_input_tokens") or 0
    split = usage.get("cache_creation")
    if isinstance(split, dict):
        five = split.get("ephemeral_5m_input_tokens") or 0
        hour = split.get("ephemeral_1h_input_tokens") or 0
        if five + hour != written:
            return None
    elif written:
        return None
    else:
        five = hour = 0
    return {"input": usage.get("input_tokens") or 0, "cache_write_5m": five, "cache_write_1h": hour,
            "cache_read": usage.get("cache_read_input_tokens") or 0, "output": usage.get("output_tokens") or 0}


def prompt_tokens(tokens: dict[str, int]) -> int:
    """The size of a request's prompt: input, cache reads and cache writes."""
    return tokens["input"] + tokens["cache_read"] + tokens["cache_write_5m"] + tokens["cache_write_1h"]


def request_cost(model: str | None, usage: dict) -> float | None:
    """The cost of one model request in USD, or None when the table cannot price it."""
    key = model_key(model)
    tokens = token_classes(usage) if isinstance(usage, dict) else None
    if key is None or tokens is None:
        return None
    size = prompt_tokens(tokens)
    prices = next(p for limit, p in TABLE[key] if limit is None or size <= limit)
    return sum(tokens[c] * price for c, price in zip(CLASSES, prices)) / 1e6


def log_cost(log_path: str | Path) -> dict | None:
    """The cost of the requests in one proxy log, or None when the file does not exist.

    The requests are those that summarize() adds up: /v1/messages with status 200 and a usage block.

      usd                  the sum of the request costs; None when a request has no price
      requests             the requests that count
      unpriced             of these, the requests without a price
      large_prompts        of these, the requests whose prompt is larger than LARGE_PROMPT tokens
    """
    path = Path(log_path)
    if not path.exists():
        return None
    total, requests, unpriced, large = 0.0, 0, 0, 0
    for r in read_log(path)[0]:
        usage = r.get("usage")
        if r.get("path") != MESSAGES_PATH or r.get("status") != 200 or not usage:
            continue
        requests += 1
        cost = request_cost(r.get("response_model") or r.get("model"), usage)
        tokens = token_classes(usage)
        if tokens is not None and prompt_tokens(tokens) > LARGE_PROMPT:
            large += 1
        if cost is None:
            unpriced += 1
        else:
            total += cost
    return {"usd": None if unpriced else total, "requests": requests, "unpriced": unpriced, "large_prompts": large}
