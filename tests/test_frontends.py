"""Service, watcher, CLI, agent config and MCP server (all with the fake embedder)."""

import json
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


def _settings(repo) -> dict:
    return json.loads((repo / ".claude" / "settings.json").read_text())


def _our_hooks(repo) -> dict:
    """event -> the (matcher, condition, command, timeout) of every codemem hook registered for it."""
    return {
        event: [
            (group["matcher"], h.get("if"), h["command"], h.get("timeout"))
            for group in groups for h in group["hooks"] if h["command"].endswith("codemem hook")
        ]
        for event, groups in _settings(repo)["hooks"].items()
    }


def _expected_hooks() -> dict:
    from codemem import hook

    t = agents.HOOK_TIMEOUT
    return {
        "PreToolUse": [
            (hook.PRE_MATCHER, None, "codemem hook", t),
            # Shell commands: one command for each word, started only when its condition matches.
            ("Bash", "Bash(rg *)", "codemem hook", t),
            ("Bash", "Bash(grep *)", "codemem hook", t),
            ("Bash", "Bash(find *)", "codemem hook", t),
        ],
        "PostToolUse": [(hook.POST_MATCHER, None, "codemem hook", t)],
    }


@pytest.fixture
def on_path(monkeypatch):
    monkeypatch.setattr(agents, "launch_command", lambda: ("codemem", []))


def test_cli_init_write_hooks_dry_run_writes_nothing(sample_repo, fake_env, on_path, capsys):
    assert main(["init", str(sample_repo), "--dry-run", "--write-hooks"]) == 0
    out = capsys.readouterr().out
    assert "would write" in out and "settings.json" in out and "codemem hook" in out
    assert not (sample_repo / ".claude").exists()


def test_cli_init_write_hooks(sample_repo, tmp_path, fake_env, on_path, capsys):
    from codemem import hook

    rc = main(["init", str(sample_repo), "--yes", "--write-hooks", "--index-dir", str(tmp_path / "idx")])
    assert rc == 0
    assert _our_hooks(sample_repo) == _expected_hooks()
    assert (sample_repo / ".mcp.json").exists()
    # Running again changes nothing, so there is nothing to write for the hooks.
    again = agents.plan(sample_repo, ["claude"], write_hooks=True)
    assert [a.agent for a in again] == ["claude"]


def test_init_hooks_only_when_asked_and_only_for_claude(sample_repo, on_path):
    assert "hooks" not in [a.agent for a in agents.plan(sample_repo, ["claude"])]
    assert "hooks" not in [a.agent for a in agents.plan(sample_repo, ["cursor", "codex"], write_hooks=True)]
    assert "hooks" in [a.agent for a in agents.plan(sample_repo, ["claude", "cursor"], write_hooks=True)]


def test_init_hooks_keep_other_settings_and_hooks(sample_repo, on_path):
    theirs = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo checked"}]}
    stop = [{"hooks": [{"type": "command", "command": "say done"}]}]
    path = sample_repo / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {"PreToolUse": [theirs], "Stop": stop},
    }))
    agents.apply(agents.plan(sample_repo, ["claude"], write_hooks=True))
    data = _settings(sample_repo)
    assert data["permissions"] == {"allow": ["Bash(ls:*)"]} and data["hooks"]["Stop"] == stop
    assert data["hooks"]["PreToolUse"][0] == theirs and len(data["hooks"]["PreToolUse"]) == 3
    assert [len(v) for v in _our_hooks(sample_repo).values()] == [4, 0, 1]  # PreToolUse, Stop, PostToolUse


def test_init_hooks_replace_an_earlier_entry_where_it_stands(sample_repo, on_path):
    from codemem import hook

    old = {"type": "command", "command": "/old/env/bin/python -m codemem hook"}
    theirs = {"type": "command", "command": "echo checked"}
    path = sample_repo / ".claude" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": "Grep", "hooks": [old]}, {"matcher": "Bash", "hooks": [theirs]}],
        # The user put a hook of their own into the same group as codemem's: theirs stays there.
        "PostToolUse": [{"matcher": "Write", "hooks": [theirs]}, {"matcher": "Grep|Glob", "hooks": [old, theirs]}],
    }}))
    agents.apply(agents.plan(sample_repo, ["claude"], write_hooks=True))
    hooks = _settings(sample_repo)["hooks"]
    assert [g["matcher"] for g in hooks["PreToolUse"]] == [hook.PRE_MATCHER, "Bash", "Bash"]
    assert hooks["PreToolUse"][2]["hooks"] == [theirs]  # their own Bash hook, after codemem's
    assert [g["matcher"] for g in hooks["PostToolUse"]] == ["Write", hook.POST_MATCHER, "Grep|Glob"]
    assert hooks["PostToolUse"][2]["hooks"] == [theirs]
    assert _our_hooks(sample_repo) == _expected_hooks()
    assert "hooks" not in [a.agent for a in agents.plan(sample_repo, ["claude"], write_hooks=True)]


def test_init_hooks_refuse_settings_they_cannot_read(sample_repo, on_path):
    path = sample_repo / ".claude" / "settings.json"
    path.parent.mkdir()
    for text in ("{not json", "[]", '{"hooks": []}', '{"hooks": {"PreToolUse": {}}}'):
        path.write_text(text)
        with pytest.raises(ValueError, match="fix or remove it first"):
            agents.plan(sample_repo, ["claude"], write_hooks=True)
        assert path.read_text() == text


def test_hook_command_when_codemem_is_not_on_path(monkeypatch):
    import os

    monkeypatch.setattr(agents, "launch_command", lambda: ("/opt/my env/bin/python", ["-m", "codemem"]))
    assert agents.hook_command() == "'/opt/my env/bin/python' -m codemem hook"
    assert agents._is_our_hook({"type": "command", "command": agents.hook_command()})
    monkeypatch.setattr(agents, "launch_command", lambda: ("/opt/env/bin/python", ["-m", "codemem"]))
    assert agents.hook_command() == "/opt/env/bin/python -m codemem hook"
    if os.sep == "\\":  # a Windows path goes in with forward slashes, which Git Bash takes
        monkeypatch.setattr(agents, "launch_command", lambda: ("C:\\envs\\cm\\python.exe", ["-m", "codemem"]))
        assert agents.hook_command() == "C:/envs/cm/python.exe -m codemem hook"
    assert not agents._is_our_hook({"type": "command", "command": "codemem hook --and-more"})
    assert not agents._is_our_hook({"type": "command", "command": "echo codemem"})


def test_steering_levels_change_text():
    texts = {lvl: prompts.tool_description("search_code", lvl) for lvl in ("none", "light", "strong")}
    assert len(set(texts.values())) == 3 and "FIRST" in texts["strong"] and "grep" not in texts["none"]
    assert prompts.agent_notes("none") is None
    # `light` states when to search (no concrete lead), in all three places an agent reads.
    for text in (texts["light"], prompts.server_instructions("light"), prompts.agent_notes("light")):
        assert "exact" in text and "grep" in text
    assert "lose the trail" in texts["light"] and "lose the trail" in prompts.server_instructions("light")
    assert prompts.search_footer("none") == ""
    assert prompts.search_footer("light") == prompts.search_footer("strong") != ""


# ---------------------------------------------------------------- hook


def _hook(event) -> str:
    import io

    from codemem import hook

    out = io.StringIO()
    assert hook.run(io.StringIO(event if isinstance(event, str) else json.dumps(event)), out) == 0
    return out.getvalue()


def _call(tool: str, session: str = "s1") -> dict:
    return {"session_id": session, "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {}}


def test_hook_refuses_the_first_search_once(isolated_home):
    out = json.loads(_hook(_call("Grep")))["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "deny"
    assert out["permissionDecisionReason"] == prompts.first_search_refusal()
    assert prompts.MCP_SEARCH_TOOL in out["permissionDecisionReason"]
    # The repeated call goes through, and so does every later search of that session.
    assert _hook(_call("Grep")) == "" and _hook(_call("Glob")) == ""
    # Another session gets its own first refusal.
    assert "deny" in _hook(_call("Glob", session="s2"))
    assert len(list((isolated_home / "hook-sessions").iterdir())) == 2


def _bash(command: str, session: str = "s1") -> dict:
    return {**_call("Bash", session), "tool_input": {"command": command, "description": "run it"}}


def test_hook_counts_a_shell_search_as_the_first_search(isolated_home):
    # Other shell commands pass and do not use up the refusal.
    for command in ("git status", "uv run pytest -q", "pip install --find-links wheels x", "cat docs/grep.md"):
        assert _hook(_bash(command)) == ""
    assert not (isolated_home / "hook-sessions").exists()
    out = json.loads(_hook(_bash("cd src && grep -rn revoke_session .")))["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and out["permissionDecisionReason"] == prompts.first_search_refusal()
    # Once in a session, whichever tool the search came through.
    assert _hook(_bash("cd src && grep -rn revoke_session .")) == "" and _hook(_call("Grep")) == ""
    assert "deny" in _hook(_call("Grep", session="s2")) and _hook(_bash("rg revoke", session="s2")) == ""
    assert _hook(_call(prompts.MCP_SEARCH_TOOL, session="s3")) == "" and _hook(_bash("rg revoke", session="s3")) == ""


def test_hook_shell_search_is_a_word_check():
    from codemem import hook

    assert hook.SHELL_RULES == ("Bash(rg *)", "Bash(grep *)", "Bash(find *)")
    searches = (
        "rg foo src", "grep -rn foo .", "find . -name '*.py'", "git grep -n foo", "xargs rg -l foo",
        "cd a && grep foo b", "pytest | grep FAILED",  # not a code search, but one refusal is harmless
    )
    others = (
        "git status", "cargo test", "git log --grep=fix", "pip install --find-links x pkg", "cat docs/grep.md",
        "findstr foo bar", "python find_dupes.py", "ls src/find",
    )
    for command in searches:
        assert hook._is_shell_search({"tool_input": {"command": command}}), command
    for command in others:
        assert not hook._is_shell_search({"tool_input": {"command": command}}), command
    for event in ({}, {"tool_input": None}, {"tool_input": {}}, {"tool_input": {"command": 7}}):
        assert not hook._is_shell_search(event)


def test_hook_is_silent_after_search_code(isolated_home):
    assert _hook(_call(prompts.MCP_SEARCH_TOOL)) == ""
    assert _hook(_call("Grep")) == "" and _hook(_call("Glob")) == ""
    # A server that a plugin registered has a longer name.
    assert _hook(_call("mcp__plugin_x_codemem__search_code", session="s2")) == ""
    assert _hook(_call("Grep", session="s2")) == ""


def test_hook_never_blocks_what_it_does_not_understand(isolated_home):
    for event in ("", "not json", "[1]", {}, {"session_id": "s1"}, {"tool_name": "Grep"}, _call("Read"), _call("Bash")):
        assert _hook(event) == ""
    assert not (isolated_home / "hook-sessions").exists()  # none of these counted as a search
    assert "deny" in _hook(_call("Grep"))


def test_hook_session_ids_cannot_leave_the_folder(isolated_home):
    assert "deny" in _hook(_call("Grep", session="../../outside"))
    assert [p.name for p in (isolated_home / "hook-sessions").iterdir()] == ["______outside"]


def test_hook_forgets_old_sessions(isolated_home):
    import os

    folder = isolated_home / "hook-sessions"
    folder.mkdir(parents=True)
    old = folder / "old"
    old.touch()
    os.utime(old, (0, 0))
    _hook(_call("Grep"))
    assert [p.name for p in folder.iterdir()] == ["s1"]


def test_cli_hook_reads_stdin(monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_call("Grep"))))
    assert main(["hook"]) == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_matchers_name_the_tools():
    import re

    from codemem import hook

    assert hook.PRE_MATCHER == "Grep|Glob|mcp__codemem__search_code"
    assert hook.POST_MATCHER == "Grep|Glob|Read|mcp__codemem__(search_code|get_chunk)"
    # Claude Code reads a matcher with these characters as an unanchored regular expression.
    for tool in ("Grep", "Glob", "Read", "mcp__codemem__search_code", "mcp__codemem__get_chunk"):
        assert re.search(hook.POST_MATCHER, tool)
    assert not re.search(hook.POST_MATCHER, "mcp__codemem__index_status")


# Results in the form Claude Code gives them (seen in a session transcript; not documented).
_NOTHING = {"mode": "files_with_matches", "filenames": [], "numFiles": 0, "totalFiles": 0}
_FEW = {"mode": "files_with_matches", "filenames": ["a.py", "b.py"], "numFiles": 2, "totalFiles": 2}
_LINES = {"mode": "content", "numFiles": 0, "filenames": [], "content": "a.py:1:x", "numLines": 1, "totalLines": 1}


def _after(tool: str, response=None, session: str = "s1") -> str:
    event = {**_call(tool, session), "hook_event_name": "PostToolUse", "tool_response": response}
    out = _hook(event)
    if not out:
        return ""
    out = json.loads(out)["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse" and set(out) == {"hookEventName", "additionalContext"}
    return out["additionalContext"]


def test_hook_nudges_after_an_empty_search():
    assert _after("Grep", _NOTHING) == prompts.lost_trail_nudge("empty")
    assert prompts.MCP_SEARCH_TOOL in prompts.lost_trail_nudge("empty")
    # Every form of "nothing": Glob, Grep's content and count modes, and plain text.
    for i, (tool, response) in enumerate([
        ("Glob", {"filenames": [], "numFiles": 0, "truncated": False, "totalMatches": 0}),
        ("Grep", {"mode": "content", "numFiles": 0, "filenames": [], "content": "", "numLines": 0, "totalLines": 0}),
        ("Grep", {"mode": "count", "numFiles": 0, "filenames": [], "content": "", "numMatches": 0}),
        ("Grep", "No matches found"),
    ]):
        assert _after(tool, response, session=f"e{i}") == prompts.lost_trail_nudge("empty")


def test_hook_nudges_after_too_many_files():
    from codemem import hook

    n = hook.MANY_FILES + 1
    assert _after("Grep", {"mode": "files_with_matches", "numFiles": n, "totalFiles": n}) == prompts.lost_trail_nudge("many", n)
    # Glob lists at most some of them; its total is what counts.
    glob = {"filenames": ["x"] * 10, "numFiles": 10, "truncated": True, "totalMatches": 400}
    assert _after("Glob", glob, session="s2") == prompts.lost_trail_nudge("many", 400)
    at_limit = {"mode": "count", "numFiles": hook.MANY_FILES, "numMatches": 900}
    assert _after("Grep", at_limit, session="s3") == ""
    assert _after("Grep", _LINES, session="s4") == ""  # lines, not files: no count to judge


def test_hook_nudges_on_the_third_search_in_a_row():
    assert _after("Grep", _FEW) == "" and _after("Glob", _FEW) == ""
    assert _after("Grep", _LINES) == prompts.lost_trail_nudge("streak", 3)


def test_hook_streak_ends_when_something_is_opened():
    for opened in ("Read", "mcp__codemem__get_chunk", "mcp__codemem__search_code"):
        session = opened[-6:]
        assert _after("Grep", _FEW, session) == "" and _after("Grep", _FEW, session) == ""
        assert _after(opened, {"anything": 1}, session) == ""
        assert _after("Grep", _FEW, session) == "" and _after("Grep", _FEW, session) == ""
        assert _after("Grep", _FEW, session) == prompts.lost_trail_nudge("streak", 3)
    # A tool the hook was not registered for changes nothing.
    assert _after("Grep", _FEW, "x") == "" and _after("Bash", "ok", "x") == "" and _after("Grep", _FEW, "x") == ""
    assert _after("Grep", _FEW, "x") != ""


def test_hook_shell_commands_take_no_part_in_the_lost_trail(isolated_home):
    def after_bash(command: str) -> str:
        return _hook({**_bash(command), "hook_event_name": "PostToolUse", "tool_response": {"stdout": "", "stderr": ""}})

    # A shell search that finds nothing is not nudged, however often, and keeps no state.
    for _ in range(4):
        assert after_bash("grep -rn nothing_here .") == ""
    assert not (isolated_home / "hook-sessions").exists()
    # Nor does it end a run of searches, as a Read would.
    assert _after("Grep", _FEW) == "" and _after("Grep", _FEW) == "" and after_bash("pytest | grep FAILED") == ""
    assert _after("Grep", _FEW) == prompts.lost_trail_nudge("streak", 3)


def test_hook_stays_quiet_after_a_nudge():
    from codemem import hook

    assert _after("Grep", _NOTHING) != ""
    for _ in range(hook.QUIET):
        assert _after("Grep", _NOTHING) == ""
    assert _after("Grep", _NOTHING) != ""
    # search_code starts a new trail, so the next dead end is said at once. A Read does not.
    assert _after("mcp__codemem__search_code", "1. auth/sessions.py") == ""
    assert _after("Grep", _NOTHING) != ""
    assert _after("Read", {"type": "text"}) == ""
    assert _after("Grep", _NOTHING) == ""


def test_hook_after_tool_ignores_what_it_does_not_understand(isolated_home):
    assert _after("Read", {"type": "text"}) == ""
    assert not (isolated_home / "hook-sessions").exists()  # a session that has not searched keeps no state
    for response in (None, 7, [], {"mode": "files_with_matches"}, {"numFiles": True}, "Error: rg failed"):
        assert _after("Grep", response, session="odd") == ""
        _after("Read", None, session="odd")
    (isolated_home / "hook-sessions" / "odd.trail").write_text("not json")
    assert _after("Grep", _NOTHING, session="odd") == prompts.lost_trail_nudge("empty")


def test_hook_two_hooks_keep_separate_state(isolated_home):
    assert "deny" in _hook(_call("Grep"))  # refused: the search did not run, so nothing follows it
    assert _hook(_call("Grep")) == "" and _after("Grep", _NOTHING) == prompts.lost_trail_nudge("empty")
    assert sorted(p.name for p in (isolated_home / "hook-sessions").iterdir()) == ["s1", "s1.trail"]


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
    """`codemem hook` runs on every search an agent makes, so starting `codemem` must not import
    numpy, faiss or the embedder: the commands that need them import them themselves."""
    import subprocess
    import sys

    code = (
        "import sys, codemem.cli; codemem.cli.build_parser(); "
        "print(sorted(m for m in ('numpy', 'faiss', 'torch', 'codemem.embedder', 'codemem.embedserver', "
        "'codemem.store') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
