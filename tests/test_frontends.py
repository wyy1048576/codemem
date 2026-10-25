"""Service, watcher, CLI, agent config and MCP server (all with the fake embedder)."""

import json
import threading
import time

import anyio
import pytest

from codemem import agents, prompts
from codemem.cli import main
from codemem.embedder import make_embedder
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
    faiss = service.index_dir / "vec_code.faiss"
    before = faiss.stat().st_mtime_ns
    service.start(prewarm=False)
    time.sleep(0.3)
    (sample_repo / "auth" / "late.py").write_text("def late_save():\n    pass\n")
    assert _wait_for(lambda: service.store.get_chunk_by_key("auth/late.py::late_save") is not None)
    assert _wait_for(lambda: faiss.stat().st_mtime_ns != before and not service.store.vectors_unsaved())


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


def test_cli_search_without_index(sample_repo, tmp_path, fake_env, capsys):
    assert main(["search", "x", "--repo", str(sample_repo), "--index-dir", str(tmp_path / "none")]) == 2
    assert "run `codemem index`" in capsys.readouterr().err


def test_cli_default_index_dir_under_codemem_home(sample_repo, fake_env, isolated_home, capsys):
    assert main(["index", str(sample_repo)]) == 0
    dirs = list((isolated_home / "indexes").iterdir())
    assert len(dirs) == 1 and dirs[0].name.startswith("sample_repo-")
    assert (dirs[0] / "index.db").is_file() and (dirs[0] / "vec_code.faiss").is_file()


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
    assert mcp["mcpServers"]["codemem"] == {"command": "codemem", "args": ["mcp"]}
    assert "other" in mcp["mcpServers"]  # existing entries kept
    cursor = json.loads((sample_repo / ".cursor" / "mcp.json").read_text())
    assert cursor["mcpServers"]["codemem"]["args"] == ["mcp", "${workspaceFolder}"]
    assert prompts.AGENT_NOTES_MARKER in (sample_repo / "CLAUDE.md").read_text()
    assert "indexed 6 files" in capsys.readouterr().out
    # Running again does not duplicate the notes.
    again = agents.plan(sample_repo, ["claude"], write_agent_notes=True)
    assert [a.agent for a in again] == ["claude"]


def test_steering_levels_change_text():
    texts = {lvl: prompts.tool_description("search_code", lvl) for lvl in ("none", "light", "strong")}
    assert len(set(texts.values())) == 3 and "FIRST" in texts["strong"] and "grep" not in texts["none"]
    assert prompts.agent_notes("none") is None


# ---------------------------------------------------------------- MCP


def test_mcp_tools_end_to_end(service):
    from mcp import Client

    from codemem.server import build_server

    service.update()
    server = build_server(service)

    async def run():
        async with Client(server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert set(tools) == {"search_code", "get_chunk", "index_status"}
            assert tools["search_code"].description == prompts.tool_description("search_code", "light")
            assert client.instructions == prompts.server_instructions("light")
            res = await client.call_tool("search_code", {"query": "revoke session", "k": 3})
            text = res.content[0].text
            assert "auth/sessions.py:19-20  revoke_session" in text
            res = await client.call_tool("get_chunk", {"ref": "auth/sessions.py:20"})
            assert "db.sessions.delete(session_id)" in res.content[0].text
            assert "callers: " in res.content[0].text
            res = await client.call_tool("index_status", {})
            assert "state: ready" in res.content[0].text

    anyio.run(run)


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
                assert tools == {"search_code", "get_chunk", "index_status"}
                for _ in range(100):
                    status = (await client.call_tool("index_status", {})).content[0].text
                    if "state: ready" in status:
                        break
                    await anyio.sleep(0.1)
                assert "state: ready" in status
                res = await client.call_tool("search_code", {"query": "disable user"})
                assert "disable_user" in res.content[0].text

    anyio.run(run)
