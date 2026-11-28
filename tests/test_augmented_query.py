"""search_code's augmented query: intent, symptom, anchors and locations, written by the calling agent's model."""

from __future__ import annotations

import anyio
import pytest

from codemem.config import Config, VectorConfig
from codemem.search import BM25
from codemem.service import CodememService


@pytest.fixture
def svc(sample_repo, tmp_path):
    cfg = Config()
    cfg.vectors = {"code": VectorConfig(model="fake:64"), "usage": VectorConfig(model="fake:64")}
    service = CodememService(sample_repo, index_dir=tmp_path / "idx", config=cfg)
    service.update()
    yield service
    service.close()


def _search(svc, query, **kw):
    return svc.search(query, wait_for_models=False, **kw)


def test_no_fields_is_the_plain_search(svc):
    for query in ("revoke session", "users stay logged in"):
        plain = _search(svc, query, k=5)
        empty = _search(svc, query, k=5, intent=" ", symptom="", anchors=["", " "], locations=[" "])
        assert [(r.chunk_id, r.score) for r in empty.results] == [(r.chunk_id, r.score) for r in plain.results]


def test_intent_and_anchors_add_their_rankings(svc):
    resp = _search(svc, "users stay logged in", k=10, debug=True, intent="ends a user's session",
                   symptom="disabled users stay logged in", anchors=["revoke_session"])
    lists = set().union(*(r.ranks for r in resp.results))
    assert {"intent_code", "intent_usage", "anchors_bm25", "bm25", "code", "usage"} <= lists


def test_anchors_find_the_exact_name(svc):
    plain = _search(svc, "tenant billing report", k=3)
    assert "revoke_session" not in [r.qualname for r in plain.results]
    resp = _search(svc, "tenant billing report", k=3, anchors=["revoke_session"])
    assert "revoke_session" in [r.qualname for r in resp.results]


@pytest.mark.parametrize("location", [
    "auth/sessions.py::revoke_session", "revoke_session", "revoke_session()", "`sessions.revoke_session`",
    "auth/sessions.py:20", ".\\auth\\sessions.py::revoke_session",
])
def test_a_named_location_comes_first(svc, location):
    resp = _search(svc, "tenant billing report", k=3, locations=[location])
    assert resp.results[0].qualname == "revoke_session"


def test_a_named_file_puts_its_code_first(svc):
    resp = _search(svc, "tenant billing report", k=5, locations=["sessions.py"])
    assert {r.path for r in resp.results[:3]} == {"auth/sessions.py"}


def test_unknown_or_filtered_out_locations_pin_nothing(svc):
    plain = [r.chunk_id for r in _search(svc, "revoke session", k=5).results]
    unknown = _search(svc, "revoke session", k=5, locations=["nowhere.py", "no_such_function", "a.b.c"])
    assert [r.chunk_id for r in unknown.results] == plain
    inside = _search(svc, "revoke session", k=5, path_prefix="api/", locations=["auth/sessions.py::revoke_session"])
    assert inside.results and all(r.path.startswith("api/") for r in inside.results)


def test_k_caps_the_pinned_results(svc):
    resp = _search(svc, "anything", k=1, locations=["auth/sessions.py", "auth/users.py"])
    assert len(resp.results) == 1 and resp.results[0].path == "auth/sessions.py"


def test_keywords_only_with_the_fields(svc):
    """While the model loads, a search answers from keywords: intent and symptom are left out, anchors stay."""
    resp = svc.search("revoke session", k=10, signals=[BM25], debug=True, intent="x", symptom="y",
                      anchors=["revoke_session"])
    lists = set().union(*(r.ranks for r in resp.results))
    assert "anchors_bm25" in lists and not any(name.startswith("intent_") for name in lists)


def test_search_code_takes_the_fields(svc):
    from mcp import Client

    from codemem.server import build_server

    async def run():
        async with Client(build_server(svc)) as client:
            tool = {t.name: t for t in (await client.list_tools()).tools}["search_code"]
            assert {"intent", "symptom", "anchors", "locations"} <= set(tool.input_schema["properties"])
            assert set(tool.input_schema.get("required", [])) == {"query"}
            res = await client.call_tool("search_code", {
                "query": "tenant billing report", "k": 2, "intent": "ends a session",
                "anchors": ["revoke_session"], "locations": ["revoke_session"],
            })
            return res.content[0].text

    text = anyio.run(run)
    assert text.startswith("1. auth/sessions.py:") and "revoke_session" in text.splitlines()[0]
