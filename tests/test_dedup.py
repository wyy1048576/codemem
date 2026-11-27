"""search_dedup (dedup.py): a result this MCP session was sent, unchanged, comes back as one line."""

from __future__ import annotations

import re
from types import SimpleNamespace

import anyio
import pytest

from codemem.config import Config, VectorConfig, config_from_dict
from codemem.dedup import SessionMemory
from codemem.prompts import search_footer
from codemem.render import card_label, format_results
from codemem.search import ResultCard, SearchResponse
from codemem.service import CodememService


def _main_format_results(resp: SearchResponse) -> str:
    """format_results exactly as on main at 463171c, before format_card was split out."""
    if not resp.results:
        return f"No results for {resp.query!r}."
    out: list[str] = []
    for i, r in enumerate(resp.results, start=1):
        head = f"{i}. {r.location}  {card_label(r)}  [id {r.chunk_id}]"
        if r.best_lines:
            head += f"  best {r.best_lines[0]}-{r.best_lines[1]}"
        out.append(head)
        if r.kind != "block":
            out.append(f"   {r.signature}")
        if r.doc:
            out.append(f"   {r.doc}")
        if r.preview:
            body = r.preview.splitlines()
            if r.kind != "block" and not r.best_lines:
                body = body[1:]
            out.extend(f"   | {line}" for line in body[:6])
    return "\n".join(out)


# ---------------------------------------------------------------- unit: SessionMemory on made-up cards


def _card(n: int, preview: str = "def f():\n    a\n    b", best=None) -> ResultCard:
    return ResultCard(chunk_id=n, key=f"m.py::f{n}", path="m.py", start_line=10 * n, end_line=10 * n + 5,
                      qualname=f"f{n}", kind="function", signature=f"def f{n}():", doc="", preview=preview,
                      score=1.0 / n, best_lines=best)


class _Store:
    def __init__(self, n: int):
        self.hash = {i: f"h{i}" for i in range(1, n + 1)}

    def get_chunks(self, ids):
        return {i: SimpleNamespace(content_hash=self.hash[i]) for i in ids if i in self.hash}


def _resp(ids, query="q", **kw) -> SearchResponse:
    return SearchResponse(query, ["bm25"], [_card(i, **kw) for i in ids])


SHORT = r"\n   \(shown earlier (?:as a card|in full by get_chunk), unchanged\)"


def _full_cards(text: str) -> list[int]:
    return [int(m) for m in re.findall(r"\[id (\d+)\](?:  best \d+-\d+)?(?!" + SHORT + ")$", text, re.MULTILINE)]


def _one_lines(text: str) -> list[int]:
    return [int(m) for m in re.findall(r"\[id (\d+)\]" + SHORT, text)]


def _eval_parse(text: str) -> list[int]:
    """The chunk ids that the eval's parser (eval/src/cmeval/e2e_replay.py, parse_results) reads from a page."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "eval" / "src" / "cmeval" / "e2e_replay.py"
    head = next(line for line in path.read_text(encoding="utf8").splitlines() if line.startswith("_HEAD = "))
    pattern = re.compile(eval(head.split("=", 1)[1].strip().removeprefix("re.compile(").rsplit(",", 1)[0]), re.MULTILINE)
    return [int(m[6]) for m in pattern.finditer(text)]


def test_first_search_is_what_off_returns():
    store = _Store(20)
    for mode in ("shorten", "refill"):
        assert SessionMemory(mode).page(_resp(range(1, 6)), 5, store, current=True) == format_results(_resp(range(1, 6)))


def test_shorten_turns_repeats_into_one_line_and_keeps_the_order():
    m, store = SessionMemory("shorten"), _Store(20)
    m.page(_resp([1, 2, 3]), 3, store, current=True, )
    text = m.page(_resp([2, 4, 1], query="other words"), 3, store, current=True)
    assert _one_lines(text) == [2, 1] and _full_cards(text) == [4]
    assert text.splitlines()[:2] == ["1. m.py:20-25  f2  [id 2]", "   (shown earlier as a card, unchanged)"]
    assert _eval_parse(text) == [2, 4, 1]  # the eval reads every result of the page, short or not
    assert "get_chunk(id) returns the current code" in text


def test_refill_goes_deeper_until_k_new_cards():
    m, store = SessionMemory("refill"), _Store(20)
    m.page(_resp([1, 2, 3]), 3, store, current=True)
    assert m.depth(3, "other words", None, None, "include") == 6
    text = m.page(_resp([2, 1, 4, 3, 5, 6], query="other words"), 3, store, current=True)
    assert _one_lines(text) == [2, 1, 3] and _full_cards(text) == [4, 5, 6]
    text = m.page(_resp([1, 2, 3, 4], query="third"), 3, store, current=True)  # the ranking ends first
    assert _full_cards(text) == [] and "Only 0 of these results are new to this session." in text


def test_changed_code_comes_back_in_full_and_says_so():
    m, store = SessionMemory("shorten"), _Store(5)
    m.page(_resp([1, 2]), 2, store, current=True)
    store.hash[1] = "edited"
    text = m.page(_resp([1, 2], query="again, other words"), 2, store, current=True)
    assert _full_cards(text) == [1] and _one_lines(text) == [2]
    assert "[id 1]\n   (changed since shown earlier)" in text and _eval_parse(text) == [1, 2]
    text = m.page(_resp([1], query="a third time"), 1, store, current=True)
    assert _one_lines(text) == [1]  # the changed card was sent: from now on that is what was seen


def test_never_one_line_when_the_index_is_not_current():
    m, store = SessionMemory("refill"), _Store(5)
    m.page(_resp([1, 2]), 2, store, current=True)
    text = m.page(_resp([1, 2], query="other words"), 2, store, current=False)
    assert _one_lines(text) == [] and _full_cards(text) == [1, 2]


def test_same_code_other_lines_is_a_full_card():
    m, store = SessionMemory("shorten"), _Store(5)
    m.page(_resp([1], best=(12, 14)), 1, store, current=True)
    text = m.page(_resp([1], query="other words", best=(30, 32)), 1, store, current=True)
    assert _full_cards(text) == [1] and "best 30-32\n   (shown earlier, other lines this time)" in text
    assert _eval_parse(text) == [1]


def test_the_same_query_again_shows_every_card():
    m, store = SessionMemory("refill"), _Store(5)
    m.page(_resp([1, 2]), 2, store, current=True)
    assert m.depth(2, "  Q ", None, None, "include") == 2  # same words: no deeper ranking
    assert m.page(_resp([1, 2], query="  Q "), 2, store, current=True) == format_results(_resp([1, 2], query="  Q "))
    # the same words with another filter are another query: repeats are one line
    assert _one_lines(m.page(_resp([1, 2], query="q"), 2, store, current=True, path_prefix="m.py")) == [1, 2]


def test_get_chunk_in_full_counts_a_card_does_not_need_to_match():
    m, store = SessionMemory("shorten"), _Store(5)
    m.got_chunk("m.py::f3", "h3", whole=True)
    m.got_chunk("m.py::f4", "h4", whole=False)  # a long class's outline is not its code
    text = m.page(_resp([3, 4]), 2, store, current=True)
    assert _one_lines(text) == [3] and _full_cards(text) == [4]
    assert "(shown earlier in full by get_chunk, unchanged)" in text


def test_forgetting_after_n_calls():
    m, store = SessionMemory("shorten", forget_calls=2), _Store(5)
    m.page(_resp([1]), 1, store, current=True)  # call 1
    assert _one_lines(m.page(_resp([1], query="b"), 1, store, current=True)) == [1]  # call 2: 1 call ago
    assert _full_cards(m.page(_resp([1], query="c"), 1, store, current=True)) == [1]  # call 3: 2 calls ago, forgotten
    never = SessionMemory("shorten", forget_calls=0)
    never.page(_resp([1]), 1, store, current=True)
    for q in "bcdefghijklm":
        assert _one_lines(never.page(_resp([1], query=q), 1, store, current=True)) == [1]


def test_config_switch():
    assert Config().search_dedup == "off"
    assert config_from_dict({"search_dedup": "refill", "search_dedup_forget_calls": 0}).search_dedup == "refill"
    with pytest.raises(ValueError):
        config_from_dict({"search_dedup": "on"})
    with pytest.raises(ValueError):
        SessionMemory("on")


# ---------------------------------------------------------------- through the MCP server, on the sample repo


def _service(sample_repo, tmp_path, mode: str) -> CodememService:
    cfg = Config(search_dedup=mode)
    cfg.vectors = {"code": VectorConfig(model="fake:64"), "usage": VectorConfig(model="fake:64")}
    svc = CodememService(sample_repo, index_dir=tmp_path / f"idx-{mode}", config=cfg)
    svc.update()
    return svc


def _calls(svc, calls):
    from mcp import Client

    from codemem.server import build_server

    out = []

    async def run():
        async with Client(build_server(svc)) as client:
            for tool, args in calls:
                out.append((await client.call_tool(tool, args)).content[0].text)

    anyio.run(run)
    return out


QUERIES = [("search_code", {"query": "revoke session", "k": 5}), ("search_code", {"query": "log out a user session", "k": 5}),
           ("get_chunk", {"ref": "auth/sessions.py::revoke_session"}), ("search_code", {"query": "session token", "k": 5})]


def test_off_is_byte_for_byte_main(sample_repo, tmp_path):
    svc = _service(sample_repo, tmp_path, "off")
    try:
        got = _calls(svc, QUERIES)
        for (tool, args), text in zip(QUERIES, got):
            if tool == "search_code":
                resp = svc.search(args["query"], k=args["k"], wait_for_models=False)
                assert text == _main_format_results(resp) + "\n\n" + search_footer("light")
        assert got[0] == _calls(svc, QUERIES[:1])[0]
    finally:
        svc.close()


def test_on_first_search_and_get_chunk_unchanged(sample_repo, tmp_path):
    off, on = _service(sample_repo, tmp_path, "off"), _service(sample_repo, tmp_path, "refill")
    try:
        a, b = _calls(off, QUERIES), _calls(on, QUERIES)
        assert a[0] == b[0]  # the first search of a session
        assert a[2] == b[2]  # get_chunk
        assert "shown earlier" in b[1] or "shown earlier" in b[3]
        assert len(_full_cards(b[1])) == len(_full_cards(a[1]))  # refill: as many full cards as off
    finally:
        off.close()
        on.close()


def test_an_edit_between_searches_is_shown_in_full(sample_repo, tmp_path):
    svc = _service(sample_repo, tmp_path, "shorten")
    try:
        from mcp import Client

        from codemem.server import build_server

        texts = []

        async def run():
            async with Client(build_server(svc)) as client:
                async def search(q):
                    texts.append((await client.call_tool("search_code", {"query": q, "k": 3})).content[0].text)

                await search("revoke session")
                f = sample_repo / "auth" / "sessions.py"
                f.write_text(f.read_text().replace("def revoke_session(session_id):", "def revoke_session(session_id):\n    pass  # edited"))
                svc.update()
                await search("revoke a session")

        anyio.run(run)
        lines = texts[1].splitlines()
        i = next(n for n, x in enumerate(lines) if "revoke_session  [id" in x)
        assert lines[i + 1] == "   (changed since shown earlier)"
    finally:
        svc.close()


def test_a_new_client_starts_with_nothing_sent(sample_repo, tmp_path):
    """The eval's gate (codemem_gate.py) does its own handshake and a warm-up search, then hands the same
    server process to Claude Code, whose handshake comes second: the agent's first search is a full page."""
    from mcp import Client

    from codemem.server import build_server

    svc = _service(sample_repo, tmp_path, "refill")
    try:
        server = build_server(svc)
        texts = []

        from mcp.types import Implementation

        async def session(name, queries):
            async with Client(server, client_info=Implementation(name=name, version="1")) as client:
                for q in queries:
                    texts.append((await client.call_tool("search_code", {"query": q, "k": 3})).content[0].text)

        anyio.run(session, "cmeval-gate", ["revoke session"])  # the gate's warm-up
        anyio.run(session, "claude-code", ["revoke a session", "revoke the session"])  # the agent
        assert "shown earlier" not in texts[1]  # the agent's first search
        assert "shown earlier" in texts[2]  # within the agent's session it works
    finally:
        svc.close()


# ---------------------------------------------------------------- D2: a failure never fails the tool (review of 14:10 UTC)


def test_a_page_that_fails_halfway_records_nothing(monkeypatch):
    import codemem.dedup as dedup

    m = SessionMemory("shorten")
    m.page(_resp([1, 2, 3]), 3, _Store(6), current=True)
    before = (dict(m.sent), set(m.queries), m.calls, dict(m.stats))
    real, seen = dedup.format_card, []

    def fails_on_the_second(r, i, **kw):
        seen.append(i)
        if len(seen) == 2:
            raise RuntimeError("boom")
        return real(r, i, **kw)

    monkeypatch.setattr(dedup, "format_card", fails_on_the_second)
    with pytest.raises(RuntimeError):
        m.page(_resp([4, 5, 6], query="other"), 3, _Store(6), current=True)
    assert (dict(m.sent), set(m.queries), m.calls, dict(m.stats)) == before  # card 4 was built, not recorded
    monkeypatch.setattr(dedup, "format_card", real)
    assert _full_cards(m.page(_resp([4, 5, 6], query="other"), 3, _Store(6), current=True)) == [4, 5, 6]


@pytest.mark.parametrize("mode", ["shorten", "refill"])
def test_a_failing_memory_answers_the_plain_page(sample_repo, tmp_path, monkeypatch, mode):
    off = _service(sample_repo, tmp_path, "off")
    on = _service(sample_repo, tmp_path, mode)
    try:
        want = _calls(off, QUERIES)
        real_page, pages = SessionMemory.page, []

        def page(self, *a, **kw):  # the first page works, so refill asks for more than k after it
            pages.append(1)
            if len(pages) > 1:
                raise RuntimeError("boom")
            return real_page(self, *a, **kw)

        def got_chunk(self, *a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(SessionMemory, "page", page)
        monkeypatch.setattr(SessionMemory, "got_chunk", got_chunk)
        got = _calls(on, QUERIES)
        assert got == want  # the plain page, k results, the same notes; get_chunk unchanged
    finally:
        off.close()
        on.close()


# ---------------------------------------------------------------- D3: calls in flight at once


def test_threads_on_one_memory_raise_nothing():
    import sys
    import threading

    m, errors = SessionMemory("refill", forget_calls=3), []

    def work(seed):
        try:
            for n in range(400):
                ids = [(seed * 7 + n + j) % 30 + 1 for j in range(5)]
                m.depth(5, f"q{n % 4}", None, None, "include")
                m.page(_resp(ids, query=f"q{n % 4}"), 5, _Store(30), current=True)
                m.got_chunk(f"m.py::f{ids[0]}", f"h{ids[0]}", whole=True)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [threading.Thread(target=work, args=(s,)) for s in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old)
    assert errors == []
    assert m.stats["searches"] == 1600


def test_the_first_call_in_gets_the_cards():
    """Two searches in flight: the one that came in second finishes its search first, and waits."""
    import threading

    m, out = SessionMemory("shorten"), {}
    first, second = m.ticket(), m.ticket()

    def later():
        with m.in_order(second):
            out["second"] = m.page(_resp([1, 2, 3], query="b"), 3, _Store(3), current=True)
        m.release(second)

    t = threading.Thread(target=later)
    t.start()
    t.join(0.3)
    assert t.is_alive() and "second" not in out  # waits for the earlier call
    with m.in_order(first):
        out["first"] = m.page(_resp([1, 2, 3], query="a"), 3, _Store(3), current=True)
    m.release(first)
    t.join(5)
    assert _full_cards(out["first"]) == [1, 2, 3]
    assert _one_lines(out["second"]) == [1, 2, 3]


def test_a_call_that_fails_before_its_page_does_not_hold_up_the_next():
    import threading

    m, out = SessionMemory("shorten"), {}
    first, second = m.ticket(), m.ticket()

    def later():
        with m.in_order(second):
            out["second"] = m.page(_resp([1, 2]), 2, _Store(2), current=True)

    t = threading.Thread(target=later)
    t.start()
    m.release(first)  # its search failed: no page
    t.join(5)
    assert not t.is_alive() and _full_cards(out["second"]) == [1, 2]


def test_two_searches_sent_at_once_through_the_server(sample_repo, tmp_path):
    """One of the two pages has the cards and the other the short lines; neither is an error."""
    from mcp import Client

    from codemem.server import build_server

    svc = _service(sample_repo, tmp_path, "shorten")
    try:
        texts = {}

        async def run():
            async with Client(build_server(svc)) as client:
                async def search(name, q):
                    res = await client.call_tool("search_code", {"query": q, "k": 5})
                    assert not res.is_error
                    texts[name] = res.content[0].text

                async with anyio.create_task_group() as tg:
                    tg.start_soon(search, "a", "revoke session")
                    tg.start_soon(search, "b", "revoke a session")

        anyio.run(run)
        short = [name for name, text in texts.items() if "shown earlier" in text]
        assert len(short) == 1
        assert _one_lines(texts[short[0]])  # the other page sent those results as cards
    finally:
        svc.close()
