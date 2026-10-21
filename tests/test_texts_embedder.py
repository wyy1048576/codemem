import numpy as np

from codemem.callgraph import is_test_caller, is_test_path, resolve_edges
from codemem.config import Config, config_from_dict
from codemem.embedder import FakeEmbedder, make_embedder
from codemem.schema import Chunk
from codemem.texts import TEXT_BUILDERS, BuildContext, Ref, build_texts


def _chunk(chunk_id, name, path="auth/sessions.py", kind="function"):
    return Chunk(
        key=f"{path}::{name}", path=path, qualname=name, name=name, kind=kind,
        start_line=1, end_line=2, signature=f"def {name}():", docstring="",
        code=f"def {name}():\n    pass", content_hash="x", chunk_id=chunk_id,
    )


def test_resolve_edges_skips_ambiguous_and_self():
    defs = [(1, "revoke_session"), (2, "disable_user"), (3, "test_x")] + [(10 + i, "get") for i in range(6)]
    calls = [(2, "revoke_session"), (3, "disable_user"), (1, "revoke_session"), (2, "get"), (2, "print")]
    assert resolve_edges(defs, calls, max_defs_per_name=5) == {(2, 1), (3, 2)}
    # With a higher threshold the 6 `get`s link.
    assert len(resolve_edges(defs, calls, max_defs_per_name=6)) == 8


def test_test_detection():
    assert is_test_path("tests/test_users.py")
    assert is_test_path("pkg/tests/helpers.py")
    assert is_test_path("users_test.py")
    assert not is_test_path("auth/users.py")
    assert is_test_caller("auth/users.py", "test_something")
    assert not is_test_caller("auth/contest.py", "latest")


def test_usage_text_lists_callers_and_tests():
    revoke = _chunk(1, "revoke_session")
    ctx = BuildContext(callers={1: [
        Ref(3, "test_disabled_user_loses_sessions", "test_disabled_user_loses_sessions", "tests/test_users.py", 5),
        Ref(2, "disable_user", "disable_user", "auth/users.py", 10),
    ]})
    assert TEXT_BUILDERS["usage"](revoke, ctx) == (
        "revoke_session in auth/sessions.py\n"
        "called by disable_user in auth/users.py\n"
        "tested by test_disabled_user_loses_sessions in tests/test_users.py"
    )


def test_usage_text_none_without_callers_and_for_headers():
    assert TEXT_BUILDERS["usage"](_chunk(1, "lonely"), BuildContext()) is None
    header = _chunk(5, "mod", kind="file_header")
    assert TEXT_BUILDERS["usage"](header, BuildContext(callers={5: [Ref(1, "a", "a", "a.py", 1)]})) is None


def test_usage_text_caps_and_reserves_room_for_tests():
    callers = [Ref(100 + i, f"caller{i}", f"caller{i}", "app.py", i) for i in range(30)]
    callers += [Ref(200 + i, f"test_{i}", f"test_{i}", "tests/test_app.py", i) for i in range(30)]
    text = TEXT_BUILDERS["usage"](_chunk(1, "f"), BuildContext(callers={1: callers}, max_items=20))
    lines = text.splitlines()[1:]
    assert len(lines) == 20
    assert sum(line.startswith("tested by") for line in lines) == 10


def test_usage_text_includes_commits_when_given():
    ctx = BuildContext(callers={}, commits={"auth/sessions.py": ["Fix session leak"]})
    assert "changed in commit: Fix session leak" in TEXT_BUILDERS["usage"](_chunk(1, "f"), ctx)


def test_summary_slot_disabled_and_build_texts_skips_none():
    c = _chunk(1, "f")
    assert TEXT_BUILDERS["summary"](c, BuildContext()) is None
    assert build_texts(c, BuildContext(), ["code", "usage", "summary"]) == {"code": c.code}


def test_fake_embedder_deterministic_normalized_and_similarity():
    e = FakeEmbedder(dim=64)
    a = e.embed_documents(["revoke session token", "revoke session token", "parse html document"])
    assert a.shape == (3, 64) and a.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(a, axis=1), 1.0, rtol=1e-5)
    np.testing.assert_array_equal(a[0], a[1])
    q = e.embed_queries(["revoke session"])[0]
    assert q @ a[0] > q @ a[2]
    assert np.all(e.embed_documents([""]) == 0)  # empty text -> zero vector, no NaN


def test_make_embedder_fake_and_cache():
    cfg = Config()
    e1 = make_embedder("fake:16", cfg)
    assert isinstance(e1, FakeEmbedder) and e1.dim == 16
    assert make_embedder("fake:16", cfg) is e1


def test_config_parsing():
    cfg = config_from_dict({
        "device": "xpu",
        "vectors": {"usage": {"enabled": False}, "code": {"model": "jinaai/jina-code-embeddings-1.5b"}},
        "bm25": {"weights": [3, 2, 1]},
        "rrf": {"k": 10, "weights": {"bm25": 2.0}},
        "usage": {"max_defs_per_name": 3},
        "embedding_dim": 256,
    })
    assert cfg.device == "xpu"
    assert cfg.enabled_vec_types() == ["code"]
    assert cfg.model_id("code") == "jinaai/jina-code-embeddings-1.5b@256"
    assert cfg.bm25_weights == (3, 2, 1) and cfg.rrf_k == 10 and cfg.rrf_weights == {"bm25": 2.0}
    assert cfg.max_defs_per_name == 3


def test_load_config_layers(tmp_path, monkeypatch):
    from codemem.config import load_config

    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text('steering = "strong"\nbatch_size = 4\n')
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".codemem.toml").write_text("batch_size = 8\n")
    monkeypatch.setenv("CODEMEM_HOME", str(home))
    monkeypatch.setenv("CODEMEM_MODEL", "fake")
    cfg = load_config(repo)
    assert (cfg.steering, cfg.batch_size, cfg.vectors["code"].model) == ("strong", 8, "fake")
