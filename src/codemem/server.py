"""MCP server (stdio). Thin layer over CodememService.

stdout carries protocol messages only; all logging goes to stderr.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

from mcp.server.mcpserver import Context, MCPServer

from . import __version__, prompts
from .dedup import SessionMemory
from .render import format_chunk, format_refresh, format_results, format_status, freshness_note
from .schema import KINDS
from .search import TEST_FILTERS
from .service import CodememService

log = logging.getLogger(__name__)


def build_server(service: CodememService) -> MCPServer:
    # Every tool answers in plain text, registered with `structured_output=False`. A tool that
    # returns `str` would otherwise also send `{"result": "<the text>"}` as structured content, and a
    # client that shows that to the model shows the line ends as the two characters `\n`: code
    # previews then read as one escaped line.
    steering = service.config.steering
    # One server process per agent session: what this session was sent (search_dedup, off by default).
    memory = SessionMemory(service.config.search_dedup, service.config.search_dedup_forget_calls)
    server = MCPServer(
        name=prompts.SERVER_NAME,
        version=__version__,
        instructions=prompts.server_instructions(steering),
    )

    @server.tool(
        name="search_code", description=prompts.tool_description("search_code", steering), structured_output=False
    )
    def search_code(
        query: str, k: int = 10, path_prefix: str | None = None, kinds: list[str] | None = None,
        tests: str = "include", ctx: Context | None = None,
    ) -> str:
        k = max(1, min(int(k), 50))
        if unknown := [kind for kind in kinds or [] if kind not in KINDS]:
            return f"Unknown kinds {unknown}; choose from {list(KINDS)}."
        if tests not in TEST_FILTERS:
            return f"tests must be one of {', '.join(TEST_FILTERS)}."
        notice = ""
        if service.state == "indexing":
            # A copy of another checkout's index is not a build in progress: the search waits for
            # its first full check, and has a notice of its own if that takes longer.
            if not service.copy_unchecked():
                notice = prompts.indexing_notice(service.progress) + "\n\n"
        elif service.state in ("empty", "error") and not service.has_index():
            return "The codemem index is not available yet." + (
                f" Last error: {service.last_error}" if service.last_error else ""
            )
        if not memory.on:
            return _search_page(notice, query, k, path_prefix, kinds, tests, k, None)
        # search_dedup (dedup.py). Calls in flight at once make their pages in the order they came in (a
        # ticket); a failure in the memory never fails the search: it answers the plain page (D2, D3).
        ticket = memory.ticket()
        try:
            depth = k
            try:
                memory.for_client(_client_of(ctx))
                depth = memory.depth(k, query, path_prefix, kinds, tests)
            except Exception:
                log.exception("search_dedup: no depth; this search goes on without it")
            return _search_page(notice, query, k, path_prefix, kinds, tests, depth, ticket)
        finally:
            memory.release(ticket)

    def _search_page(notice, query, k, path_prefix, kinds, tests, depth, ticket) -> str:
        resp = service.search(
            query, k=depth, path_prefix=path_prefix, kinds=kinds or None, tests=tests, wait_for_models=False
        )
        fresh = resp.freshness
        if fresh is not None and fresh.unchecked_copy:
            notice = prompts.copy_notice() + "\n\n"
        notes = [freshness_note(fresh, service.store.pending_paths() if fresh is not None and fresh.pending_chunks else (0, []))]
        if resp.models_loading:
            notes.append(prompts.vectors_unavailable_notice(resp.models_error) if resp.models_error else prompts.models_loading_notice())
        # Appended here, not in format_results: the eval builds its hit text from format_results.
        notes.append(prompts.search_footer(steering))
        body = None
        if ticket is not None:  # one line for what this session was sent and is unchanged: dedup.py
            current = (fresh is None or fresh.complete) and not resp.models_loading
            try:
                with memory.in_order(ticket):
                    body = memory.page(resp, k, service.store, current=current, path_prefix=path_prefix,
                                       kinds=kinds, tests=tests)
            except Exception:
                log.exception("search_dedup: the page failed; the plain page is sent and nothing is recorded")
                resp = replace(resp, results=resp.results[:k])
        if body is None:
            body = format_results(resp)
        return notice + body + "".join(f"\n\n{n}" for n in notes if n)

    @server.tool(
        name="get_chunk", description=prompts.tool_description("get_chunk", steering), structured_output=False
    )
    def get_chunk(ref: str, ctx: Context | None = None) -> str:
        d = service.get_chunk(ref)
        if d is None:
            missing = f"No indexed function matches {ref!r}. Use a chunk id, path:line, or path::qualname."
            # In a copy of another checkout's index, a function of this checkout may only be missing still.
            return f"{missing}\n\n{prompts.copy_notice()}" if service.copy_unchecked() else missing
        if memory.on:  # never shortened; only recorded, so a later search can name it in one line
            try:
                memory.for_client(_client_of(ctx))
                chunk = service.store.get_chunk(d["chunk_id"])
                if chunk is not None:
                    memory.got_chunk(chunk.key, chunk.content_hash, whole=d["code"] == chunk.code)
            except Exception:  # the answer does not depend on it (D2)
                log.exception("search_dedup: get_chunk was not recorded")
        return (prompts.copy_notice() + "\n\n" if d.get("unchecked_copy") else "") + format_chunk(d)

    @server.tool(
        name="refresh_index", description=prompts.tool_description("refresh_index", steering), structured_output=False
    )
    def refresh_index() -> str:
        return format_refresh(service.refresh(timeout=60))

    @server.tool(
        name="index_status", description=prompts.tool_description("index_status", steering), structured_output=False
    )
    def index_status() -> str:
        info = service.status(check_staleness=True)
        return format_status(info) + "\n\n" + json.dumps(
            {k: info.get(k) for k in ("state", "progress", "chunks", "vectors", "models_loaded", "search_index", "stale")}, default=str
        )

    return server


def _client_of(ctx: Context | None) -> object:
    """Which client this is: the name and version it gave in its `initialize` (the eval's gate is
    "cmeval-gate", Claude Code another). The params object itself can be new on every request."""
    try:
        info = ctx.session.client_params.client_info
        return (info.name, info.version)
    except Exception:  # outside a request, or a client that gave no info: one client
        return None


def run_stdio(repo: Path | str | None = None, index_dir: Path | str | None = None) -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="codemem %(levelname)s %(message)s")
    service = CodememService(repo, index_dir=index_dir)
    log.info("codemem MCP server for %s (index %s)", service.repo_root, service.index_dir)
    # The catch-up (or the first index) runs in the background, so the handshake isn't blocked.
    service.start()
    try:
        build_server(service).run("stdio")
    finally:
        service.close()
