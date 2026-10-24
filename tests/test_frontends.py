"""Service, watcher, CLI, agent config and MCP server (all with the fake embedder)."""

import json
import threading
import time

import anyio
import pytest

from codemem import agents, prompts
from codemem.cli import main
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


def test_pending_changes_rank_files_by_how_much_depends_on_them(service, sample_repo):
    service.update()
    assert service.pending_changes()["files"] == []
    for rel in ("auth/sessions.py", "api/routes.py"):
        (sample_repo / rel).write_text((sample_repo / rel).read_text() + "\n# edited\n")
    (sample_repo / "auth" / "audit.py").write_text("def record_audit_event(evt):\n    return evt\n")
    (sample_repo / "auth" / "db.py").unlink()
    pending = service.pending_changes()
    assert (pending["changed_files"], pending["deleted_files"], pending["total_files"]) == (3, 1, 6)
    files = {f["path"]: f for f in pending["files"]}
    assert [f["path"] for f in pending["files"]][:2] == ["auth/sessions.py", "auth/db.py"]
    # revoke_session and friends are called from routes, users and the tests.
    assert files["auth/sessions.py"] == {
        "path": "auth/sessions.py", "change": "modified", "inbound_files": 3, "inbound_calls": 4, "percentile": 83,
    }
    assert files["auth/db.py"]["change"] == "deleted" and files["auth/db.py"]["inbound_files"] == 2
    assert files["api/routes.py"]["inbound_files"] == 0 and files["api/routes.py"]["percentile"] == 0
    assert files["auth/audit.py"]["change"] == "added"
    assert service.pending_changes(limit=1)["more_files"] == 3

    stats = service.reindex()
    assert stats.files_changed == 3 and stats.files_deleted == 1
    assert service.pending_changes()["files"] == []


def test_concurrent_update_requests_coalesce(service):
    service._update_lock.acquire()
    try:
        assert service.update() is None  # busy -> queued, not run in parallel
        assert service._pending.is_set()
    finally:
        service._update_lock.release()


def test_reindex_waits_for_a_running_update(service, sample_repo):
    service.update()
    service._update_lock.acquire()
    done = []
    worker = threading.Thread(target=lambda: done.append(service.reindex()))
    worker.start()
    time.sleep(0.2)
    assert not done  # waiting, not skipped
    (sample_repo / "auth" / "audit.py").write_text("def record_audit_event(evt):\n    return evt\n")
    service._update_lock.release()
    worker.join(timeout=30)
    assert done[0] is not None and done[0].files_changed == 1


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


def test_watcher_ignores_non_python_and_skip_dirs(service, sample_repo):
    service.update()
    calls = []
    service.request_update = lambda: calls.append(1)
    service.start_watcher()
    time.sleep(0.3)
    (sample_repo / "notes.txt").write_text("hello")
    (sample_repo / "build" / "x.py").write_text("x = 1")
    time.sleep(1.0)
    assert calls == []


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
    assert "codemem-reindex/SKILL.md" in out and not (sample_repo / ".claude").exists()


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
    skill = sample_repo / ".claude" / "skills" / "codemem-reindex" / "SKILL.md"
    assert skill.read_text("utf-8") == prompts.reindex_skill()
    assert "indexed 6 files" in capsys.readouterr().out
    # Running again does not duplicate the notes or rewrite the skill.
    again = agents.plan(sample_repo, ["claude"], write_agent_notes=True)
    assert [a.path.name for a in again] == [".mcp.json"]
    skill.write_text("my own version", encoding="utf-8")
    again = agents.plan(sample_repo, ["claude"])
    assert again[-1].path == skill and "yours differs" in again[-1].description


def test_reindex_skill_has_frontmatter_and_names_the_tools():
    text = prompts.reindex_skill()
    head, _, body = text.removeprefix("---\n").partition("\n---\n")
    assert head.startswith(f"name: {prompts.REINDEX_SKILL_NAME}\n") and "\ndescription: " in head
    for word in ("index_status", "reindex", "inbound_files", "percentile", "total_files", "head_moved"):
        assert word in body


def test_steering_levels_change_text():
    texts = {lvl: prompts.tool_description("search_code", lvl) for lvl in ("none", "light", "strong")}
    assert len(set(texts.values())) == 3 and "FIRST" in texts["strong"] and "grep" not in texts["none"]
    assert prompts.agent_notes("none") is None


def test_instructions_mention_reindex_only_without_watcher():
    for lvl in ("none", "light", "strong"):
        assert "not after every edit" in prompts.tool_description("reindex", lvl)
        assert "reindex()" in prompts.server_instructions(lvl)
        assert prompts.server_instructions(lvl, watch=True) == prompts._INSTRUCTIONS[lvl]


# ---------------------------------------------------------------- MCP


def test_mcp_tools_end_to_end(service):
    from mcp import Client

    from codemem.server import build_server

    service.update()
    server = build_server(service)

    async def run():
        async with Client(server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert set(tools) == {"search_code", "get_chunk", "index_status", "reindex"}
            assert tools["search_code"].description == prompts.tool_description("search_code", "light")
            assert client.instructions == prompts.server_instructions("light", watch=False)
            res = await client.call_tool("search_code", {"query": "revoke session", "k": 3})
            text = res.content[0].text
            assert "auth/sessions.py:19-20  revoke_session" in text
            res = await client.call_tool("get_chunk", {"ref": "auth/sessions.py:20"})
            assert "db.sessions.delete(session_id)" in res.content[0].text
            assert "callers: " in res.content[0].text
            res = await client.call_tool("index_status", {})
            assert "state: ready" in res.content[0].text

            (service.repo_root / "auth" / "audit.py").write_text("def record_audit_event(evt):\n    return evt\n")
            status = (await client.call_tool("index_status", {})).content[0].text
            assert "added    auth/audit.py  called from 0 other files" in status
            res = await client.call_tool("reindex", {})
            assert "1 files changed" in res.content[0].text and "re-embedded: 1 code" in res.content[0].text
            status = (await client.call_tool("index_status", {})).content[0].text
            assert "stale: 0 changed, 0 deleted" in status

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
                assert tools == {"search_code", "get_chunk", "index_status", "reindex"}
                for _ in range(100):
                    status = (await client.call_tool("index_status", {})).content[0].text
                    if "state: ready" in status:
                        break
                    await anyio.sleep(0.1)
                assert "state: ready" in status
                res = await client.call_tool("search_code", {"query": "disable user"})
                assert "disable_user" in res.content[0].text

                # No watcher by default: a save is not indexed until the agent calls reindex.
                (sample_repo / "auth" / "audit.py").write_text("def record_audit_event(evt):\n    return evt\n")
                await anyio.sleep(1.5)  # well past the 400 ms debounce a watcher would use
                res = await client.call_tool("search_code", {"query": "record_audit_event", "k": 1})
                assert "record_audit_event" not in res.content[0].text
                await client.call_tool("reindex", {})
                res = await client.call_tool("search_code", {"query": "record_audit_event", "k": 1})
                assert "auth/audit.py:1-2  record_audit_event" in res.content[0].text

    anyio.run(run)
