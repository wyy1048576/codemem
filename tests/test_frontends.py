"""Service, watcher, CLI, agent config and MCP server (all with the fake embedder)."""

import json
import re
import threading
import time

import anyio
import pytest

from codemem import agents, prompts
from codemem.cli import main
from codemem.config import Config
from codemem.embedder import make_embedder
from codemem.render import format_status
from codemem.service import CodememService


@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")


@pytest.fixture
def service(sample_repo, tmp_path, fake_env):
    svc = CodememService(sample_repo, index_dir=tmp_path / "idx")
    yield svc
    svc.close()


def _wait_for(pred, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------- service


def test_service_background_index_and_refs(service):
    assert service.state == "empty"
    service.start_background_update(prewarm=False).join(timeout=30)
    assert service.state == "ready" and service.progress == 100
    by_id = service.get_chunk(service.store.get_chunk_by_key("auth/sessions.py::revoke_session").chunk_id)
    by_line = service.get_chunk("auth/sessions.py:20")
    by_key = service.get_chunk("auth/sessions.py::revoke_session")
    assert by_id["chunk_id"] == by_line["chunk_id"] == by_key["chunk_id"]
    assert {c["qualname"] for c in by_key["callers"]} == {"logout", "disable_user", "test_disabled_user_loses_sessions"}
    assert [c["qualname"] for c in by_key["callees"]] == ["Table.delete"]
    assert service.get_chunk("nope.py:1") is None and service.get_chunk("garbage") is None


def test_status_reports_staleness(service, sample_repo):
    service.update()
    assert service.status()["stale"]["changed_files"] == 0
    (sample_repo / "auth" / "extra.py").write_text("def extra():\n    pass\n")
    info = service.status()
    assert info["stale"]["changed_files"] == 1 and info["models"]["code"]["model"] == "fake:64"


def test_concurrent_updates_both_run_and_return_stats(service):
    """An update that finds another one running waits and runs: it never returns None, which the
    eval adapter treats as a failed update."""
    results = []

    def run():
        results.append(service.update())
        service.store.close_thread_conn()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(results) == 2 and all(r is not None for r in results)


def test_watcher_reindexes_after_save(service, sample_repo):
    service.update()
    service.start_watcher()
    time.sleep(0.3)
    (sample_repo / "auth" / "audit.py").write_text("def record_audit_event(evt):\n    return evt\n")
    t0 = time.monotonic()
    assert _wait_for(lambda: service.store.get_chunk_by_key("auth/audit.py::record_audit_event") is not None)
    assert time.monotonic() - t0 < 5
    hits = service.search("record_audit_event").results
    assert hits[0].qualname == "record_audit_event"


def test_a_watcher_that_is_still_starting_is_not_taken_for_one_that_stopped(service, monkeypatch):
    """Fixed bug: the service handed the watcher to the writer before it started it. A start takes
    a while (on Linux it adds a watch to every folder before its thread runs). A writer that had
    a quiet moment in between saw a watcher that was not alive, took it for one that had stopped,
    and scanned the whole repo every few seconds for the rest of the session."""
    from codemem.watcher import RepoWatcher

    service.update()
    real_start = RepoWatcher.start
    during_start = []

    def slow_start(watcher):
        for _ in range(5):  # the writer's quiet moments while the watcher starts
            service._step()
        during_start.append(service._polling)
        real_start(watcher)

    monkeypatch.setattr(RepoWatcher, "start", slow_start)
    service.start_watcher()
    for _ in range(5):
        service._step()
    assert during_start == [False] and not service._polling
    assert service.status(check_staleness=False)["watching"] is True


def test_watcher_ignores_non_code_and_skip_dirs(service, sample_repo):
    service.update()
    calls = []
    service.notify = lambda paths, reconcile=False: calls.append((paths, reconcile))
    service.start_watcher()
    time.sleep(0.3)
    (sample_repo / "notes.txt").write_text("hello")
    (sample_repo / "build" / "x.py").write_text("x = 1")
    time.sleep(1.5)
    assert calls == []
    (sample_repo / "auth" / "audit.py").write_text("def audit():\n    pass\n")
    assert _wait_for(lambda: calls)
    assert calls[0] == ({"auth/audit.py"}, False)  # the path itself, not a scan of the repo


def test_search_right_after_a_save_sees_the_edit(service, sample_repo):
    """The freshness contract: a search applies every save made before it, with no waiting."""
    service.update()
    service.start(prewarm=False)
    time.sleep(0.3)
    (sample_repo / "auth" / "quota.py").write_text("def enforce_login_quota(user):\n    return user\n")
    resp = service.search("enforce_login_quota", k=3)  # immediately: no sleep before searching
    assert resp.results and resp.results[0].qualname == "enforce_login_quota"
    assert resp.freshness.complete


class _SlowModel:
    """The fake model, slowed per text (10 ms by default) and per character, so an embedding
    backlog takes real time."""

    def __init__(self, inner, per_text=0.01, per_char=0.0):
        self.inner, self.per_text, self.per_char = inner, per_text, per_char

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def embed_documents(self, texts):
        time.sleep(self.per_text * len(texts) + self.per_char * sum(map(len, texts)))
        return self.inner.embed_documents(texts)


@pytest.fixture
def slow_service(sample_repo, tmp_path, fake_env):
    (sample_repo / ".codemem.toml").write_text("catchup_budget_ms = 300\n")
    svc = CodememService(
        sample_repo, index_dir=tmp_path / "idx", embedder_factory=lambda m, c: _SlowModel(make_embedder(m, c))
    )
    yield svc
    svc.close()


_MANY = "\n\n".join(f"def helper_{i}(x):\n    return x * {i} + {i * 7}\n" for i in range(150))  # 1.5 s to embed


def test_a_search_waits_for_edits_the_writer_is_applying(service, sample_repo, monkeypatch):
    """Fixed bug: a save the writer thread had taken, but not committed yet, was invisible to a
    search, which still called itself complete."""
    service.update()
    service.start(prewarm=False)
    time.sleep(0.3)
    taken = threading.Event()
    structure = service.indexer.structure

    def slow_structure(stats, **kw):
        if threading.current_thread().name == "codemem-writer" and kw.get("paths"):
            taken.set()
            time.sleep(0.6)  # a big repo, or a git checkout still writing files
        return structure(stats, **kw)

    monkeypatch.setattr(service.indexer, "structure", slow_structure)
    (sample_repo / "auth" / "quota.py").write_text("def enforce_login_quota(user):\n    return user\n")
    assert taken.wait(5)  # the writer has the save and is in stage A
    resp = service.search("enforce_login_quota", k=3)
    assert resp.results and resp.results[0].qualname == "enforce_login_quota"
    assert resp.freshness.complete


def test_a_search_stops_waiting_at_its_limit(slow_service, sample_repo):
    """Fixed bug: the limit was checked only between batches, and a search took the whole queue
    as one batch, so a big edit kept it waiting until everything was embedded."""
    svc = slow_service
    svc.update()
    svc.start(prewarm=False)
    time.sleep(0.3)
    (sample_repo / "auth" / "many.py").write_text(_MANY)
    t = time.monotonic()
    resp = svc.search("helper_7", k=10)
    assert time.monotonic() - t < 1.0  # the 0.3 s limit, one model call (0.16 s) and the search
    assert not resp.freshness.complete and resp.freshness.pending_chunks > 0
    keywords = svc.search("helper_7", k=1, signals=["bm25"]).results
    assert keywords[0].qualname == "helper_7"  # keywords are current already, vectors or not
    assert _wait_for(lambda: svc.store.dirty_count() == 0)  # the writer embeds the rest
    assert svc.indexer.verify() == []


def test_a_search_embeds_its_own_edit_first(slow_service, sample_repo):
    """While the writer works through a big change, an agent edits one function and searches:
    the writer hands over the model at its next call, and the newest edit is embedded first."""
    svc = slow_service
    svc.update()
    svc.start(prewarm=False)
    time.sleep(0.3)
    (sample_repo / "auth" / "many.py").write_text(_MANY)
    assert _wait_for(lambda: svc.store.dirty_count() > 0)  # applied; the writer is embedding it
    time.sleep(0.2)
    (sample_repo / "auth" / "quota.py").write_text("def enforce_login_quota(user):\n    return user\n")
    t = time.monotonic()
    svc.search("enforce_login_quota", k=3)
    assert time.monotonic() - t < 1.0
    quota = svc.store.get_chunk_by_key("auth/quota.py::enforce_login_quota")
    assert quota is not None and not svc.store.dirty_seqs([quota.chunk_id])  # its vectors are in
    assert svc.store.dirty_count() > 0  # while the older work is still queued


def test_a_search_does_not_wait_past_its_limit_for_a_slow_stage_a(slow_service, sample_repo, monkeypatch):
    """Stage A of a huge file (or during a checkout) can take seconds. The search hands the save to
    the writer instead of applying it itself, waits at most its limit, and says what is pending."""
    svc = slow_service
    svc.update()
    svc.start(prewarm=False)
    time.sleep(0.3)
    structure = svc.indexer.structure

    def slow_structure(stats, **kw):
        if kw.get("paths"):
            time.sleep(1.5)
        return structure(stats, **kw)

    monkeypatch.setattr(svc.indexer, "structure", slow_structure)
    (sample_repo / "auth" / "quota.py").write_text("def enforce_login_quota(user):\n    return user\n")
    t = time.monotonic()
    resp = svc.search("enforce_login_quota", k=3)
    assert time.monotonic() - t < 1.0  # the 0.3 s limit, not the 1.5 s stage A
    assert not resp.freshness.complete and resp.freshness.pending_files > 0
    assert _wait_for(lambda: svc.store.get_chunk_by_key("auth/quota.py::enforce_login_quota") is not None)


def test_without_file_events_a_search_finds_saves_through_a_full_check(service, sample_repo):
    """When the OS file watcher can't run (network drives, WSL, watch limits), a search asks for a
    full check first, so it still includes every earlier save."""
    service.update()
    service.start(watch=False, prewarm=False)
    time.sleep(0.3)
    (sample_repo / "auth" / "quota.py").write_text("def enforce_login_quota(user):\n    return user\n")
    resp = service.search("enforce_login_quota", k=3)
    assert resp.results and resp.results[0].qualname == "enforce_login_quota"
    assert resp.freshness.complete


def test_a_search_says_so_when_it_cannot_confirm_every_save_was_seen(service, sample_repo, monkeypatch):
    service.update()
    service.start(prewarm=False)
    time.sleep(0.3)
    monkeypatch.setattr(service._watcher, "barrier", lambda timeout=0.25: False)  # the marker never came back
    resp = service.search("revoke_session", k=3)
    assert resp.freshness.unconfirmed and not resp.freshness.complete


def test_status_lists_every_file_the_index_leaves_out(sample_repo, tmp_path, fake_env):
    from codemem.render import format_status

    (sample_repo / ".codemem.toml").write_text("max_file_size = 5000\n")  # a small file can play a big one
    (sample_repo / "big_table.py").write_text("ROWS = [\n" + "\n".join(f"    ({i}, 'row {i}')," for i in range(300)) + "\n]\n")
    (sample_repo / "auth" / "models_gen.py").write_text("# Code generated by sqlc. DO NOT EDIT.\nclass User:\n    pass\n")
    (sample_repo / "auth" / "broken.py").write_text("def ok():\n    return 1\n\ndef broken(:\n    pass\n")
    for name in ("deploy.yaml", "schema.sql", "Makefile"):
        (sample_repo / name).write_text("x\n")
    (sample_repo / "node_modules" / "pad").mkdir(parents=True)
    (sample_repo / "node_modules" / "pad" / "index.js").write_text("module.exports = 1\n")
    svc = CodememService(sample_repo, index_dir=tmp_path / "idx")
    try:
        svc.update()
        info = svc.status()
        assert info["skipped_files"]["by_reason"] == {"too_large": 1, "generated": 1, "parse_errors": 1}
        cov = info["coverage"]
        # .codemem.toml, auth/README.txt, the three above, and .gitignore (no extension, like Makefile)
        assert cov["not_code_by_extension"] == {"(none)": 2, ".toml": 1, ".txt": 1, ".yaml": 1, ".sql": 1}
        assert cov["skipped_dirs"] == {"(ignored)": 1, "build": 1, "node_modules": 1}  # scratch/ is gitignored
        assert cov["ignored_files"] == 1  # auth/schema_generated.py, by *_generated.py
        assert svc.store.get_chunk_by_key("auth/broken.py::ok") is not None  # partly parsed: still indexed
        text = format_status(info)
        assert "not indexed or partly parsed: 1 generated, 1 with parse errors, 1 too large" in text
        assert "big_table.py (too large, 6." in text and " KB)" in text
        assert "not code (no supported language): 6 files (no extension 2, " in text
        assert "ignored: 1 file; skipped folders: build 1, node_modules 1, 1 by ignore rules" in text
    finally:
        svc.close()


def test_get_chunk_right_after_a_save_shows_the_new_code(service, sample_repo):
    service.update()
    service.start(prewarm=False)
    time.sleep(0.3)
    p = sample_repo / "auth" / "sessions.py"
    p.write_text(p.read_text().replace("db.sessions.delete(session_id)", "db.sessions.delete(session_id)  # revoked"))
    d = service.get_chunk("auth/sessions.py::revoke_session")  # immediately: no sleep
    assert d is not None and "# revoked" in d["code"]


def test_the_writer_applies_new_saves_during_a_long_embedding(slow_service, sample_repo):
    """During a backlog (600 texts, 6 s of model time), a new save's structure is in after the
    quiet period and one model call, not after the writer's 5 s embedding step."""
    svc = slow_service
    svc.update()
    svc.start(prewarm=False)
    time.sleep(0.3)
    many = "\n\n".join(f"def helper_{i}(x):\n    return x * {i} + {i * 7}\n" for i in range(600))
    (sample_repo / "auth" / "many.py").write_text(many)
    assert _wait_for(lambda: svc.store.dirty_count() > 0)  # applied; the writer is embedding it
    time.sleep(0.3)
    (sample_repo / "auth" / "quota.py").write_text("def enforce_login_quota(user):\n    return user\n")
    t = time.monotonic()
    assert _wait_for(lambda: svc.store.get_chunk_by_key("auth/quota.py::enforce_login_quota") is not None)
    assert time.monotonic() - t < 2.0


def test_long_texts_do_not_push_a_search_past_its_limit(sample_repo, tmp_path, fake_env):
    """One model call of 16 long texts took 7 s on the M1. Calls are sized by length, and a call the
    model's measured speed says would end past the limit isn't started."""
    (sample_repo / ".codemem.toml").write_text("catchup_budget_ms = 1000\n")
    svc = CodememService(
        sample_repo, index_dir=tmp_path / "idx",
        embedder_factory=lambda m, c: _SlowModel(make_embedder(m, c), per_text=0.0, per_char=0.0002),
    )
    try:
        svc.update()
        svc.start(prewarm=False)
        time.sleep(0.3)
        body = "\n".join(f"    step_{j} = handle(request, {j})" for j in range(90))  # about 3,000 characters
        (sample_repo / "auth" / "long.py").write_text(
            "\n\n".join(f"def long_{i}(request):\n{body}\n    return step_0\n" for i in range(12))
        )
        t = time.monotonic()
        resp = svc.search("long_3", k=3)
        assert time.monotonic() - t < 2.0  # the 1 s limit plus at most one 0.6 s call (12 texts: 7 s)
        assert not resp.freshness.complete
    finally:
        svc.close()


def test_an_ignore_rule_change_reconciles(service, sample_repo):
    service.update()
    service.start(prewarm=False)
    assert service.store.get_chunk_by_key("auth/db.py::Table") is not None
    gi = sample_repo / ".gitignore"
    gi.write_text(gi.read_text() + "auth/db.py\n")
    assert _wait_for(lambda: service.store.get_chunk_by_key("auth/db.py::Table") is None)


def test_a_config_change_reaches_the_index(service, sample_repo):
    service.update()
    service.start(prewarm=False)
    (sample_repo / ".codemem.toml").write_text("code_header = false\n")
    assert _wait_for(lambda: (service.store.get_meta("index_settings") or {}).get("code_header") is False)
    assert _wait_for(lambda: service.store.dirty_count() == 0)
    assert service.indexer.verify() == []


def test_a_git_branch_switch_reconciles(service, sample_repo):
    import subprocess

    def git(*args):
        subprocess.run(["git", "-C", str(sample_repo), *args], check=True, capture_output=True)

    git("init", "-q")
    git("add", "-A")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    git("checkout", "-qb", "feature")
    (sample_repo / "auth" / "feature.py").write_text("def new_feature():\n    pass\n")
    git("add", "-A")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "feature")
    service.update()
    service.start(prewarm=False)
    time.sleep(0.3)
    git("checkout", "-q", "-")  # back to the first branch: feature.py disappears
    assert _wait_for(lambda: service.store.get_chunk_by_key("auth/feature.py::new_feature") is None)


def test_refresh_reports_what_changed(service, sample_repo):
    service.update()
    (sample_repo / "auth" / "extra.py").write_text("def extra():\n    pass\n")
    out = service.refresh(timeout=30)
    assert out["files_changed"] == 1 and out["pending"] == 0 and out["texts_embedded"] >= 1


def test_the_search_indexes_are_written_once_the_index_is_quiet(service, sample_repo, monkeypatch):
    import codemem.service as svc_mod

    monkeypatch.setattr(svc_mod, "SAVE_AFTER_IDLE", 0.3)
    service.update()
    saved = service.store._data_path("code")
    before = saved.stat().st_mtime_ns
    service.start(prewarm=False)
    time.sleep(0.3)
    (sample_repo / "auth" / "late.py").write_text("def late_save():\n    pass\n")
    assert _wait_for(lambda: service.store.get_chunk_by_key("auth/late.py::late_save") is not None)
    assert _wait_for(lambda: saved.stat().st_mtime_ns != before and not service.store.vectors_unsaved())


def test_a_save_that_fails_does_not_stop_the_writer(service, monkeypatch, caplog):
    """The writer thread writes the search indexes' files in a quiet moment. A save can fail: the
    disk is full, or another process holds the database's write lock for longer than a save waits
    (Store.save_vectors ends in a short transaction). An error that left the step would end the
    thread, and with it the watcher's updates until a search started a new one."""
    import sqlite3

    import codemem.service as svc_mod

    service.update()
    tries = []

    def locked(**_):
        tries.append(1)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(svc_mod, "SAVE_AFTER_IDLE", -1.0)
    monkeypatch.setattr(service.store, "vectors_unsaved", lambda: True)
    monkeypatch.setattr(service.store, "save_vectors", locked)
    with caplog.at_level("ERROR", logger="codemem"):
        assert service._step() is True  # logged, not raised
    assert tries == [1]
    assert any("could not write the search indexes" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- CLI


def test_cli_index_search_status(sample_repo, tmp_path, fake_env, capsys):
    idx = str(tmp_path / "idx")
    assert main(["index", str(sample_repo), "--index-dir", idx]) == 0
    assert "indexed 6 files" in capsys.readouterr().out

    assert main(["search", "revoke session", "--repo", str(sample_repo), "--index-dir", idx, "-k", "3"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("1. auth/sessions.py:19-20  revoke_session")

    assert main(["search", "logout", "--repo", str(sample_repo), "--index-dir", idx, "--json", "--debug"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["results"][0]["qualname"] == "logout" and "ranks" in data["results"][0]

    assert main(["search", "x", "--repo", str(sample_repo), "--index-dir", idx, "--signals", "bogus"]) == 2
    capsys.readouterr()

    assert main(["status", str(sample_repo), "--index-dir", idx, "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["state"] == "ready" and status["files"] == 6 and status["stale"]["changed_files"] == 0


def test_cli_without_pytorch_names_the_remedy_and_status_still_works(sample_repo, tmp_path, monkeypatch, capsys):
    """The local model in an environment built without its packages: one line on stderr, no traceback."""
    monkeypatch.setattr("codemem.embedder.find_spec", lambda name: None)
    monkeypatch.setattr("codemem.embedder._CACHE", {})
    idx = str(tmp_path / "idx")
    assert main(["index", str(sample_repo), "--index-dir", idx]) == 1
    err = capsys.readouterr().err
    assert "error: The local embedding model cannot run because PyTorch and sentence-transformers are not" in err
    assert "pip install torch sentence-transformers" in err and "Traceback" not in err
    assert main(["status", str(sample_repo), "--index-dir", idx]) == 0  # needs no model
    assert "state: empty" in capsys.readouterr().out

    svc = CodememService(sample_repo, index_dir=idx)
    try:
        assert svc.update() is None  # what the MCP server's writer does: the error is kept for index_status
        assert "pip install torch sentence-transformers" in format_status(svc.status())
    finally:
        svc.close()


def test_without_pytorch_an_index_keeps_its_vectors_and_answers_from_keywords(sample_repo, tmp_path, monkeypatch):
    """The MCP server's service in an environment built without PyTorch, with a config that asks
    for the local model: no update is applied, nothing is dropped, and a search answers from
    keywords once its wait for the model is over. Its note says why, not that the model is
    still loading."""
    from mcp import Client

    from codemem.server import build_server

    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    built = CodememService(sample_repo, index_dir=tmp_path / "idx")
    built.update()
    vectors = built.store.counts()["vectors"]
    built.close()

    monkeypatch.delenv("CODEMEM_MODEL")
    monkeypatch.setattr("codemem.embedder.find_spec", lambda name: None)
    monkeypatch.setattr("codemem.embedder._CACHE", {})
    svc = CodememService(sample_repo, index_dir=tmp_path / "idx", config=Config(catchup_budget_ms=300))
    try:
        svc.start(watch=False, prewarm=False)
        assert _wait_for(lambda: "pip install torch" in (svc.last_error or ""))
        resp = svc.search("revoke session", k=3, wait_for_models=False)
        assert resp.signals == ["bm25"] and resp.models_loading
        assert resp.models_error.startswith("LocalModelUnavailable: The local embedding model cannot run")
        assert resp.results[0].qualname == "revoke_session"
        assert svc.store.counts()["vectors"] == vectors and sum(vectors.values()) > 0
        server = build_server(svc)

        async def run():
            async with Client(server) as client:
                text = (await client.call_tool("search_code", {"query": "revoke session", "k": 3})).content[0].text
                assert "revoke_session" in text and "still loading" not in text
                assert "Note: codemem cannot embed right now (LocalModelUnavailable: The local embedding model" in text
                assert "pip install torch sentence-transformers" in text and "keyword matching only" in text

        anyio.run(run)
    finally:
        svc.close()


def test_cli_search_without_index(sample_repo, tmp_path, fake_env, capsys):
    assert main(["search", "x", "--repo", str(sample_repo), "--index-dir", str(tmp_path / "none")]) == 2
    assert "run `codemem index`" in capsys.readouterr().err


def test_cli_default_index_dir_under_codemem_home(sample_repo, fake_env, isolated_home, capsys):
    assert main(["index", str(sample_repo)]) == 0
    dirs = list((isolated_home / "indexes").iterdir())
    assert len(dirs) == 1 and dirs[0].name.startswith("sample_repo-")
    saved = {p.name for p in dirs[0].glob("vec_code.*")}  # the search index and its note
    assert (dirs[0] / "index.db").is_file() and "vec_code.json" in saved and len(saved) == 2


def test_cli_init_dry_run_writes_nothing(sample_repo, fake_env, capsys):
    assert main(["init", str(sample_repo), "--agents", "claude,cursor,codex", "--dry-run", "--write-agent-notes"]) == 0
    out = capsys.readouterr().out
    assert "would write" in out and "[mcp_servers.codemem]" in out
    assert not (sample_repo / ".mcp.json").exists() and not (sample_repo / "CLAUDE.md").exists()


def test_cli_init_writes_configs(sample_repo, tmp_path, fake_env, capsys):
    (sample_repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    idx = str(tmp_path / "idx")
    rc = main(["init", str(sample_repo), "--agents", "claude,cursor", "--yes", "--write-agent-notes", "--index-dir", idx])
    assert rc == 0
    mcp = json.loads((sample_repo / ".mcp.json").read_text())
    # alwaysLoad: Claude Code shows the tools from the first turn. Cursor's file does not get it.
    assert mcp["mcpServers"]["codemem"] == {"command": "codemem", "args": ["mcp"], "alwaysLoad": True}
    assert "other" in mcp["mcpServers"]  # existing entries kept
    cursor = json.loads((sample_repo / ".cursor" / "mcp.json").read_text())
    assert cursor["mcpServers"]["codemem"] == {"command": "codemem", "args": ["mcp", "${workspaceFolder}"]}
    assert prompts.AGENT_NOTES_MARKER in (sample_repo / "CLAUDE.md").read_text()
    assert "indexed 6 files" in capsys.readouterr().out
    # Running again does not duplicate the notes.
    again = agents.plan(sample_repo, ["claude"], write_agent_notes=True)
    assert [a.agent for a in again] == ["claude"]


def test_cli_init_writes_the_agent_note_by_default(sample_repo, tmp_path, fake_env, capsys):
    idx = str(tmp_path / "idx")
    assert main(["init", str(sample_repo), "--agents", "claude,codex", "--dry-run"]) == 0
    assert "append codemem note to CLAUDE.md" in capsys.readouterr().out
    assert not (sample_repo / "CLAUDE.md").exists()  # a dry run still writes nothing

    (sample_repo / "CLAUDE.md").write_text("# Project rules\n\nKeep me.\n", encoding="utf-8")
    assert main(["init", str(sample_repo), "--agents", "claude,codex", "--yes", "--index-dir", idx]) == 0
    claude = (sample_repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.startswith("# Project rules\n\nKeep me.\n") and claude.count(prompts.AGENT_NOTES_MARKER) == 2
    assert prompts.agent_notes("light") in claude
    assert prompts.AGENT_NOTES_MARKER in (sample_repo / "AGENTS.md").read_text(encoding="utf-8")  # for codex
    # A second init adds nothing.
    assert main(["init", str(sample_repo), "--agents", "claude,codex", "--yes", "--index-dir", idx]) == 0
    assert (sample_repo / "CLAUDE.md").read_text(encoding="utf-8") == claude


def test_cli_init_no_agent_notes(sample_repo, tmp_path, fake_env, capsys):
    idx = str(tmp_path / "idx")
    assert main(["init", str(sample_repo), "--yes", "--no-agent-notes", "--index-dir", idx]) == 0
    assert (sample_repo / ".mcp.json").exists() and not (sample_repo / "CLAUDE.md").exists()
    # It wins over the old flag, which is otherwise still accepted and changes nothing.
    assert main(["init", str(sample_repo), "--yes", "--no-agent-notes", "--write-agent-notes", "--index-dir", idx]) == 0
    assert not (sample_repo / "CLAUDE.md").exists()
    assert main(["init", str(sample_repo), "--yes", "--write-agent-notes", "--index-dir", idx]) == 0
    assert (sample_repo / "CLAUDE.md").read_text(encoding="utf-8").count(prompts.AGENT_NOTES_MARKER) == 2
    capsys.readouterr()
    with pytest.raises(SystemExit):
        main(["init", "--help"])
    shown = capsys.readouterr().out
    assert "--no-agent-notes" in shown and "--write-agent-notes" not in shown


def test_cli_init_writes_no_note_without_steering(sample_repo, tmp_path, fake_env, monkeypatch):
    monkeypatch.setenv("CODEMEM_STEERING", "none")
    assert main(["init", str(sample_repo), "--yes", "--index-dir", str(tmp_path / "idx")]) == 0
    assert (sample_repo / ".mcp.json").exists() and not (sample_repo / "CLAUDE.md").exists()


def test_steering_levels_change_text():
    texts = {lvl: prompts.tool_description("search_code", lvl) for lvl in ("none", "light", "strong")}
    assert len(set(texts.values())) == 3 and "FIRST" in texts["strong"] and "grep" not in texts["none"]
    assert prompts.agent_notes("none") is None
    # `light` states when to search (no concrete lead), in all three places an agent reads.
    for text in (texts["light"], prompts.server_instructions("light"), prompts.agent_notes("light")):
        assert "exact" in text and "grep" in text
    assert prompts.search_footer("none") == ""
    assert prompts.search_footer("light") == prompts.search_footer("strong") != ""


def test_light_says_the_two_times_to_search():
    """What the hooks used to say, now in the texts the agent reads: the first search unless there is
    a clear anchor, and whenever the trail is lost (no direction to grep)."""
    for text in (prompts.tool_description("search_code", "light"), prompts.server_instructions("light"),
                 prompts.agent_notes("light")):
        flat = " ".join(text.split())
        assert "first search" in flat.lower() and "clear anchor" in flat
        assert "lose the trail" in flat.lower() or "lost the trail" in flat.lower()
        assert "which direction to grep" in flat and "found nothing or too many files" in flat


def test_search_code_k_is_1_to_10(service):
    from mcp import Client

    from codemem.server import build_server

    for level in ("none", "light", "strong"):
        assert "k: how many results, 1 to 10 (default 10)." in prompts.tool_description("search_code", level)
    service.update()
    counts = {}

    async def run():
        async with Client(build_server(service)) as client:
            for k in (0, 1, 3, 10, 11, 50):
                text = (await client.call_tool("search_code", {"query": "session", "k": k})).content[0].text
                counts[k] = len(re.findall(r"^\d+\. ", text, re.MULTILINE))

    anyio.run(run)
    assert counts[0] == counts[1] == 1 and counts[3] == 3
    assert counts[10] == counts[11] == counts[50] == min(10, counts[10]) and counts[10] > 3


def test_the_old_hook_command_does_nothing(monkeypatch, capsys):
    """A .claude/settings.json from an older `init --write-hooks` still runs `codemem hook`: it must end
    with 0 (go on) and print nothing, never 2 (Claude Code would refuse the tool call)."""
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO('{"hook_event_name": "PreToolUse", "tool_name": "Grep"}'))
    assert main(["hook"]) == 0
    assert capsys.readouterr().out == ""


def test_init_writes_no_hooks(sample_repo, tmp_path, fake_env):
    assert main(["init", str(sample_repo), "--yes", "--no-index", "--write-hooks"]) == 0
    assert (sample_repo / ".mcp.json").exists() and not (sample_repo / ".claude" / "settings.json").exists()


# ---------------------------------------------------------------- MCP


def test_mcp_tools_end_to_end(service):
    from mcp import Client

    from codemem.server import build_server

    service.update()
    server = build_server(service)

    async def run():
        async with Client(server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert set(tools) == {"search_code", "get_chunk", "index_status", "refresh_index"}
            assert tools["search_code"].description == prompts.tool_description("search_code", "light")
            assert client.instructions == prompts.server_instructions("light")
            res = await client.call_tool("search_code", {"query": "revoke session", "k": 3})
            text = res.content[0].text
            assert "auth/sessions.py:19-20  revoke_session" in text
            assert text.endswith("\n\n" + prompts.search_footer("light"))
            res = await client.call_tool("get_chunk", {"ref": "auth/sessions.py:20"})
            assert "db.sessions.delete(session_id)" in res.content[0].text
            assert "callers: " in res.content[0].text
            res = await client.call_tool("index_status", {})
            assert "state: ready" in res.content[0].text

    anyio.run(run)


def test_mcp_tools_answer_in_plain_text(service):
    """Every tool's answer reaches the client as its text alone. With structured output (the MCP
    library's default for a tool that returns `str`) it also came as `{"result": "..."}`, and a
    client that shows that to the model shows each line end as the two characters `\\n`."""
    from mcp import Client

    from codemem.render import format_chunk
    from codemem.server import build_server

    service.update()
    server = build_server(service)

    async def run():
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
            assert len(tools) == 4 and all(t.output_schema is None for t in tools)  # none announces structured output
            calls = {
                "search_code": {"query": "revoke session", "k": 3}, "get_chunk": {"ref": "auth/sessions.py:20"},
                "index_status": {}, "refresh_index": {},
            }
            texts = {}
            for name, args in calls.items():
                res = await client.call_tool(name, args)
                assert res.structured_content is None, name
                assert [c.type for c in res.content] == ["text"], name
                texts[name] = res.content[0].text
                assert not texts[name].startswith("{"), name
            assert texts["search_code"].startswith("1. auth/sessions.py:19-20  revoke_session  [id ")
            assert "\n   def revoke_session(session_id):\n" in texts["search_code"]  # real line ends
            assert texts["get_chunk"] == format_chunk(service.get_chunk("auth/sessions.py:20"))
            assert texts["index_status"].startswith("state: ready")

    anyio.run(run)


def test_mcp_search_has_no_footer_without_steering(service):
    from mcp import Client

    from codemem.render import format_results
    from codemem.server import build_server

    service.update()
    service.config.steering = "none"
    server = build_server(service)

    async def run():
        async with Client(server) as client:
            res = await client.call_tool("search_code", {"query": "revoke session", "k": 3})
            assert prompts.search_footer("light") not in res.content[0].text

    anyio.run(run)
    # The footer is the MCP tool's, not the renderer's: the eval's hit text stays as it was.
    resp = service.search("revoke session", k=3)
    assert prompts.search_footer("light") not in format_results(resp)


def test_mcp_search_while_indexing_reports_progress(service):
    from mcp import Client

    from codemem.server import build_server

    service.update()
    service.state, service.progress = "indexing", 42.0
    server = build_server(service)

    async def run():
        async with Client(server) as client:
            res = await client.call_tool("search_code", {"query": "logout"})
            assert "42% done" in res.content[0].text and "logout" in res.content[0].text

    anyio.run(run)


def test_mcp_stdio_subprocess(sample_repo, tmp_path, isolated_home):
    """Real `codemem mcp` over stdio: handshake not blocked by indexing, stdout stays clean."""
    import os
    import sys

    from mcp import Client, StdioServerParameters

    env = {**os.environ, "CODEMEM_MODEL": "fake:64", "CODEMEM_HOME": str(isolated_home)}
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "codemem.cli", "mcp", str(sample_repo)], env=env, cwd=str(tmp_path)
    )

    async def run():
        with anyio.fail_after(60):
            async with Client(params) as client:
                tools = {t.name for t in (await client.list_tools()).tools}
                assert tools == {"search_code", "get_chunk", "index_status", "refresh_index"}
                for _ in range(100):
                    status = (await client.call_tool("index_status", {})).content[0].text
                    if "state: ready" in status:
                        break
                    await anyio.sleep(0.1)
                assert "state: ready" in status
                res = await client.call_tool("search_code", {"query": "disable user"})
                assert "disable_user" in res.content[0].text

    anyio.run(run)


def test_mcp_search_filters_and_refresh(service, sample_repo):
    from mcp import Client

    from codemem.server import build_server

    service.update()
    server = build_server(service)

    async def run():
        async with Client(server) as client:
            text = (await client.call_tool("search_code", {"query": "session", "kinds": ["class"]})).content[0].text
            assert "Session" in text and "revoke_session" not in text
            text = (await client.call_tool("search_code", {"query": "disabled user", "tests": "only"})).content[0].text
            assert "test_disabled_user_loses_sessions" in text and "auth/users.py" not in text
            text = (await client.call_tool("search_code", {"query": "disabled user", "tests": "exclude"})).content[0].text
            assert "tests/" not in text
            assert "choose from" in (await client.call_tool("search_code", {"query": "x", "kinds": ["klass"]})).content[0].text
            assert "tests must be" in (await client.call_tool("search_code", {"query": "x", "tests": "some"})).content[0].text
            (sample_repo / "auth" / "quota.py").write_text("def enforce_login_quota(user):\n    return user\n")
            text = (await client.call_tool("refresh_index", {})).content[0].text
            assert "Checked every file" in text and "1 file changed" in text
            text = (await client.call_tool("search_code", {"query": "enforce_login_quota"})).content[0].text
            assert "enforce_login_quota" in text

    anyio.run(run)


def test_a_search_that_could_not_include_everything_says_what_is_pending():
    from codemem.render import freshness_note
    from codemem.service import Freshness

    assert freshness_note(Freshness()) == ""
    note = freshness_note(Freshness(pending_chunks=12), (4, ["auth/a.py", "auth/b.py", "api/c.py"]))
    assert "12 code chunks in 4 files (auth/a.py, auth/b.py, api/c.py, ...)" in note and "grep" in note
    assert "1 file saved moments ago" in freshness_note(Freshness(pending_files=1))
    assert "could not confirm" in freshness_note(Freshness(unconfirmed=True))


def test_init_falls_back_to_python_m_codemem_when_the_command_is_not_on_path(sample_repo, monkeypatch):
    import sys

    monkeypatch.setattr(agents.shutil, "which", lambda name: None)
    (action,) = agents.plan(sample_repo, ["claude"])
    entry = json.loads(action.content)["mcpServers"]["codemem"]
    assert entry == {"command": sys.executable, "args": ["-m", "codemem", "mcp"], "alwaysLoad": True}


def test_python_m_codemem_is_the_command_line():
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "-m", "codemem", "--version"], capture_output=True, text=True, check=True)
    assert out.stdout.startswith("codemem ")


def test_index_verify_compares_with_a_fresh_build(sample_repo, tmp_path, fake_env, capsys):
    assert main(["index", str(sample_repo), "--index-dir", str(tmp_path / "idx"), "--verify"]) == 0
    assert "the index equals a fresh build" in capsys.readouterr().out


class _LoadingModel:
    """The fake model, taking `delay` seconds to load, as the real one does when codemem starts."""

    def __init__(self, inner, delay):
        self.inner, self.loaded_at = inner, time.monotonic() + delay

    def __getattr__(self, name):
        return getattr(self.inner, name)

    @property
    def ready(self):
        return time.monotonic() >= self.loaded_at

    def embed_queries(self, texts):
        while not self.ready:
            time.sleep(0.01)
        return self.inner.embed_queries(texts)

    def embed_documents(self, texts):
        while not self.ready:
            time.sleep(0.01)
        return self.inner.embed_documents(texts)


def test_the_first_mcp_search_does_not_wait_for_the_model_to_load(sample_repo, tmp_path, fake_env):
    from mcp import Client

    from codemem.server import build_server

    (sample_repo / ".codemem.toml").write_text("catchup_budget_ms = 300\n")
    built = CodememService(sample_repo, index_dir=tmp_path / "idx")
    built.update()
    built.close()
    models = {}

    def factory(spec, cfg):
        return models.setdefault(spec.model, _LoadingModel(make_embedder(spec, cfg), delay=2.0))

    svc = CodememService(sample_repo, index_dir=tmp_path / "idx", embedder_factory=factory)
    try:
        svc.start()  # with prewarm: the model loads in the background
        server = build_server(svc)

        async def run():
            async with Client(server) as client:
                t = time.monotonic()
                text = (await client.call_tool("search_code", {"query": "revoke session", "k": 3})).content[0].text
                assert time.monotonic() - t < 1.5  # within the 0.3 s limit, not the 2 s load
                assert "revoke_session" in text and "still loading" in text  # keyword results, and the note
                await anyio.sleep(2.0)
                text = (await client.call_tool("search_code", {"query": "revoke session", "k": 3})).content[0].text
                assert "revoke_session" in text and "still loading" not in text

        anyio.run(run)
    finally:
        svc.close()


def test_the_command_line_starts_without_the_search_stack():
    """Starting `codemem` must not import numpy, faiss or the embedder: the commands that need them
    import them themselves."""
    import subprocess
    import sys

    code = (
        "import sys, codemem.cli; codemem.cli.build_parser(); "
        "print(sorted(m for m in ('numpy', 'faiss', 'torch', 'codemem.embedder', 'codemem.embedserver', "
        "'codemem.store') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
