import os
import time

import pytest

from codemem.embedder import make_embedder
from codemem.indexer import Indexer, walk_source_files
from codemem.store import Store


def _edit(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")
    st = path.stat()
    # Guarantee the mtime pre-check sees a change even on coarse-resolution filesystems.
    os.utime(path, (st.st_atime, st.st_mtime + 2))


def test_file_order_of_the_os_does_not_matter(sample_repo, fake_config, monkeypatch):
    normal = list(walk_source_files(sample_repo, fake_config))
    real_walk = os.walk

    def reversed_walk(top, *args, **kwargs):
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
            yield dirpath, dirnames, filenames[::-1]

    monkeypatch.setattr(os, "walk", reversed_walk)
    assert list(walk_source_files(sample_repo, fake_config)) == normal  # same order, so same chunk ids

@pytest.fixture
def indexed(sample_repo, tmp_path, fake_config, recorder):
    store = Store(tmp_path / "index")
    indexer = Indexer(sample_repo, store, fake_config, embedder_factory=lambda m, c: recorder)
    stats = indexer.update()
    yield sample_repo, store, indexer, stats
    store.close()


def _vector_chunks(store, vec_type):
    return {chunk_id for chunk_id, _ in store.vector_rows(vec_type)}


def _usage_text(store, key):
    from codemem.texts import BuildContext, build_texts

    chunk = store.get_chunk_by_key(key)
    return build_texts(chunk, BuildContext(callers=store.caller_refs()), ["usage"]).get("usage")


def test_walk_respects_gitignore_and_skip_dirs(sample_repo, fake_config):
    files = sorted(walk_source_files(sample_repo, fake_config))
    assert files == [
        "api/routes.py", "auth/__init__.py", "auth/db.py", "auth/sessions.py", "auth/users.py",
        "tests/test_users.py",
    ]
    fake_config.ignore = ["api/"]
    assert "api/routes.py" not in walk_source_files(sample_repo, fake_config)


def test_nested_gitignore(sample_repo, fake_config):
    (sample_repo / "auth" / ".gitignore").write_text("db.py\n")
    assert "auth/db.py" not in walk_source_files(sample_repo, fake_config)
    assert "auth/users.py" in walk_source_files(sample_repo, fake_config)


def test_full_index_builds_chunks_edges_and_vectors(indexed):
    _, store, _, stats = indexed
    counts = store.counts()
    assert stats.files_changed == 6 and counts["files"] == 6
    assert store.get_chunk_by_key("auth/sessions.py::revoke_session").kind == "function"
    assert store.get_chunk_by_key("auth/db.py::Table.delete").kind == "method"
    # every chunk has a code vector; only chunks with callers have a usage vector
    assert counts["vectors"]["code"] == counts["chunks"]
    assert 0 < counts["vectors"]["usage"] < counts["chunks"]
    assert _usage_text(store, "auth/sessions.py::revoke_session") == (
        "revoke_session in auth/sessions.py\n"
        "called by logout in api/routes.py\n"
        "called by disable_user in auth/users.py\n"
        "tested by test_disabled_user_loses_sessions in tests/test_users.py"
    )
    assert store.get_meta("repo_path")
    assert set(stats.timings) >= {"scan", "chunk", "embed", "total"}


def test_noop_update_embeds_nothing(indexed, recorder):
    _, store, indexer, _ = indexed
    before = len(recorder.documents)
    stats = indexer.update()
    assert stats.files_changed == 0 and stats.embedded == {"code": 0, "usage": 0}
    assert len(recorder.documents) == before


def test_touch_without_change_does_not_reembed(indexed, recorder):
    repo, _, indexer, _ = indexed
    p = repo / "auth" / "users.py"
    _edit(p, p.read_text(encoding="utf-8"))
    before = len(recorder.documents)
    stats = indexer.update()
    assert stats.files_changed == 0 and len(recorder.documents) == before


def test_crlf_conversion_changes_file_but_not_chunks(indexed, recorder):
    repo, _, indexer, _ = indexed
    p = repo / "auth" / "users.py"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))  # e.g. git autocrlf on Windows
    before = len(recorder.documents)
    stats = indexer.update()
    assert stats.files_changed == 1
    assert stats.chunks_updated == 0 and len(recorder.documents) == before


def test_body_edit_reembeds_only_that_code_text(indexed, recorder):
    repo, store, indexer, _ = indexed
    p = repo / "auth" / "sessions.py"
    _edit(p, p.read_text(encoding="utf-8").replace("db.sessions.delete(session_id)", "db.sessions.delete(session_id)  # gone"))
    rid = store.get_chunk_by_key("auth/sessions.py::revoke_session").chunk_id
    recorder.documents.clear()
    stats = indexer.update()
    assert stats.chunks_updated == 1 and stats.chunks_added == 0
    assert stats.embedded == {"code": 1, "usage": 0}
    assert "# gone" in recorder.documents[0]
    assert store.get_chunk_by_key("auth/sessions.py::revoke_session").chunk_id == rid  # stable id


def test_renaming_caller_refreshes_callee_usage_text(indexed, recorder):
    repo, store, indexer, _ = indexed
    p = repo / "auth" / "users.py"
    _edit(p, p.read_text(encoding="utf-8").replace("def disable_user", "def deactivate_user"))
    t = repo / "tests" / "test_users.py"
    _edit(t, t.read_text(encoding="utf-8").replace("disable_user", "deactivate_user"))
    old_id = store.get_chunk_by_key("auth/users.py::disable_user").chunk_id
    recorder.documents.clear()
    stats = indexer.update()

    # revoke_session's own code is unchanged, but its usage text names the new caller.
    assert "called by deactivate_user in auth/users.py" in _usage_text(store, "auth/sessions.py::revoke_session")
    usage_docs = [d for d in recorder.documents if d.startswith("revoke_session in")]
    assert len(usage_docs) == 1
    assert not any("def revoke_session(" in d for d in recorder.documents)
    # old chunk is gone along with its vectors and edges
    assert store.get_chunk(old_id) is None
    assert old_id not in _vector_chunks(store, "code") and old_id not in _vector_chunks(store, "usage")
    # The function, and the test file's import block (blocks are keyed by their content).
    assert stats.chunks_deleted == 2 and stats.chunks_added == 2


def test_renaming_callee_moves_usage_to_new_name(indexed, recorder):
    repo, store, indexer, _ = indexed
    for rel in ("auth/sessions.py", "auth/users.py", "api/routes.py", "tests/test_users.py"):
        p = repo / rel
        _edit(p, p.read_text(encoding="utf-8").replace("revoke_session", "end_session"))
    old = store.get_chunk_by_key("auth/sessions.py::revoke_session")
    recorder.documents.clear()
    indexer.update()
    assert store.get_chunk_by_key("auth/sessions.py::revoke_session") is None
    assert old.chunk_id not in _vector_chunks(store, "usage")
    assert _usage_text(store, "auth/sessions.py::end_session").startswith("end_session in auth/sessions.py\ncalled by")
    # callers whose code changed get a new code vector
    assert any("def disable_user" in d and "end_session" in d for d in recorder.documents)


def test_losing_last_caller_removes_usage_vector(indexed):
    repo, store, indexer, _ = indexed
    gid = store.get_chunk_by_key("auth/users.py::get_user_by_id").chunk_id
    assert gid in _vector_chunks(store, "usage")
    p = repo / "api" / "routes.py"
    _edit(p, p.read_text(encoding="utf-8").replace("get_user_by_id(request.user_id)", "request.user"))
    stats = indexer.update()
    assert gid not in _vector_chunks(store, "usage")
    assert stats.vectors_removed == {"usage": 1}


def test_deleted_and_added_files(indexed):
    repo, store, indexer, _ = indexed
    (repo / "api" / "routes.py").unlink()
    (repo / "api" / "health.py").write_text("def healthcheck():\n    return 'ok'\n")
    stats = indexer.update()
    assert stats.files_deleted == 1
    assert store.get_chunk_by_key("api/routes.py::logout") is None
    assert store.get_chunk_by_key("api/health.py::healthcheck") is not None
    assert "called by logout" not in _usage_text(store, "auth/sessions.py::revoke_session")
    assert _vector_chunks(store, "code") == {c.chunk_id for c in store.iter_chunks()}


def test_oversized_and_unparseable_files(indexed, fake_config):
    repo, store, indexer, _ = indexed
    (repo / "auth" / "broken.py").write_text("def ok():\n    return 1\n\ndef broken(:\n")
    fake_config.max_file_size = 300
    stats = indexer.update()
    assert store.get_chunk_by_key("auth/broken.py::ok") is not None
    assert store.get_chunk_by_key("auth/sessions.py::revoke_session") is None  # now too big -> dropped
    assert stats.errors == []


def test_model_change_rebuilds_one_vec_type(sample_repo, tmp_path, fake_config):
    store = Store(tmp_path / "index")
    indexer = Indexer(sample_repo, store, fake_config, embedder_factory=make_embedder)
    indexer.update()
    n_code = len(store.vector_rows("code"))
    fake_config.vectors["code"].model = "fake:32"
    stats = indexer.update()
    assert stats.embedded["code"] == n_code and stats.embedded["usage"] == 0
    assert store.vector_dim("code") == 32 and store.get_meta("vec.code.embedder") == "fake:32|doc"
    store.close()


def test_matryoshka_dim_change_does_not_reembed(indexed, fake_config, recorder):
    _, store, indexer, _ = indexed
    before = len(recorder.documents)
    fake_config.embedding_dim = 16
    stats = indexer.update()
    assert stats.embedded == {"code": 0, "usage": 0} and len(recorder.documents) == before
    assert store.vector_dim("code") == 16


def test_crash_before_vector_save_recovers(sample_repo, tmp_path, fake_config, recorder, monkeypatch):
    store = Store(tmp_path / "index")
    indexer = Indexer(sample_repo, store, fake_config, embedder_factory=lambda m, c: recorder)
    monkeypatch.setattr(store, "save_vectors", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        indexer.update()
    store.close()

    # The vectors were committed with their rows; only the derived search index was not saved.
    store2 = Store(tmp_path / "index")
    indexer2 = Indexer(sample_repo, store2, fake_config, embedder_factory=lambda m, c: recorder)
    before = len(recorder.documents)
    stats = indexer2.update()
    assert stats.embedded == {"code": 0, "usage": 0} and len(recorder.documents) == before
    ti = store2._type_index("code")
    assert ti.store.ids() == {vid for vid, _ in store2.vector_rows("code").values()}
    store2.close()


def test_rebuild_reuses_the_vector_cache(indexed, recorder, fake_config):
    _, store, indexer, first = indexed
    before = len(recorder.documents)
    stats = indexer.update(full=True)
    assert stats.embedded == first.embedded and sum(stats.model_embedded.values()) == 0
    assert stats.cache_hits == stats.embedded and len(recorder.documents) == before
    fake_config.vector_cache = "off"
    stats = indexer.update(full=True)
    assert stats.model_embedded["code"] == len(store.vector_rows("code")) and len(recorder.documents) > before


def test_a_copy_of_existing_code_reuses_its_vector(indexed, recorder, fake_config):
    repo, store, indexer, _ = indexed
    fake_config.vector_cache = "off"
    fake_config.code_header = False  # with the path header, a copy in another file is a different text
    indexer.update(full=True)
    before = len(recorder.documents)
    (repo / "auth" / "copy.py").write_text((repo / "auth" / "users.py").read_text())
    stats = indexer.update()
    assert stats.reused["code"] == stats.embedded["code"] > 0 and stats.model_embedded["code"] == 0


def test_full_flag_rebuilds_from_scratch(indexed, recorder):
    _, store, indexer, _ = indexed
    n = store.counts()["chunks"]
    stats = indexer.update(full=True)
    assert stats.files_changed == 6 and stats.embedded["code"] == n
    assert store.counts()["chunks"] == n


POLY = __import__("pathlib").Path(__file__).parent / "fixtures" / "poly_repo"


@pytest.fixture
def poly(tmp_path, fake_config, recorder):
    import shutil

    repo = tmp_path / "poly"
    shutil.copytree(POLY, repo)
    store = Store(tmp_path / "pindex")
    stats = Indexer(repo, store, fake_config, embedder_factory=lambda m, c: recorder).update()
    yield repo, store, stats
    store.close()


def test_every_language_is_indexed_and_generated_code_skipped(poly):
    repo, store, stats = poly
    files = sorted(store.get_files())
    assert files == [
        "gen/types_gen.go", "go/auth/sessions.go", "go/auth/users.go", "go/auth/users_test.go",
        "native/session.c", "native/session.h", "native/users.c",
        "web/src/sessions.ts", "web/src/users.test.ts", "web/src/users.ts",
    ]  # vendor/ and *.pb.go are ignored by default; the generated file is recorded as skipped
    assert store.get_files()["gen/types_gen.go"].status == "skipped" and stats.files_skipped == 1
    assert set(store.counts()["chunks_by_language"]) == {"go", "c", "typescript"}
    assert store.get_files()["native/session.h"].language == "c"
    assert store.get_chunk_by_key("go/auth/users_test.go::TestDisabledUserLosesSessions").is_test


def test_usage_text_in_every_language(poly):
    _, store, _ = poly
    assert _usage_text(store, "go/auth/sessions.go::RevokeSession").splitlines()[1:] == [
        "called by DisableUser in go/auth/users.go",
    ]
    assert _usage_text(store, "go/auth/users.go::DisableUser").splitlines()[1:] == [
        "tested by TestDisabledUserLosesSessions in go/auth/users_test.go",
    ]
    assert _usage_text(store, "web/src/users.ts::disableUser").splitlines()[1:] == ["tested in web/src/users.test.ts"]
    assert "called by disableUser in web/src/users.ts" in _usage_text(store, "web/src/sessions.ts::revokeSession")
    assert "called by disable_user in native/users.c" in _usage_text(store, "native/session.c::revoke_session")


def test_generated_marker_removed_gets_indexed(poly, fake_config, recorder):
    repo, store, _ = poly
    _edit(repo / "gen" / "types_gen.go", "package gen\n\nfunc HandWritten() {}\n")
    stats = Indexer(repo, store, fake_config, embedder_factory=lambda m, c: recorder).update()
    assert stats.files_changed == 1 and store.get_chunk_by_key("gen/types_gen.go::HandWritten") is not None


def test_language_filter(poly, fake_config, recorder, tmp_path):
    repo, _, _ = poly
    fake_config.languages = ["go"]
    store = Store(tmp_path / "go-only")
    Indexer(repo, store, fake_config, embedder_factory=lambda m, c: recorder).update()
    assert set(store.counts()["chunks_by_language"]) == {"go"}
    store.close()
