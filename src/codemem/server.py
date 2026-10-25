"""MCP server (stdio). Thin layer over CodememService.

stdout carries protocol messages only; all logging goes to stderr.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import __version__, prompts
from .render import format_chunk, format_refresh, format_results, format_status, freshness_note
from .schema import KINDS
from .search import TEST_FILTERS
from .service import CodememService

log = logging.getLogger(__name__)


def build_server(service: CodememService) -> MCPServer:
    steering = service.config.steering
    server = MCPServer(
        name=prompts.SERVER_NAME,
        version=__version__,
        instructions=prompts.server_instructions(steering),
    )

    @server.tool(name="search_code", description=prompts.tool_description("search_code", steering))
    def search_code(
        query: str, k: int = 10, path_prefix: str | None = None, kinds: list[str] | None = None,
        tests: str = "include",
    ) -> str:
        k = max(1, min(int(k), 50))
        if unknown := [kind for kind in kinds or [] if kind not in KINDS]:
            return f"Unknown kinds {unknown}; choose from {list(KINDS)}."
        if tests not in TEST_FILTERS:
            return f"tests must be one of {', '.join(TEST_FILTERS)}."
        notice = ""
        if service.state == "indexing":
            notice = prompts.indexing_notice(service.progress) + "\n\n"
        elif service.state in ("empty", "error") and not service.has_index():
            return "The codemem index is not available yet." + (
                f" Last error: {service.last_error}" if service.last_error else ""
            )
        resp = service.search(query, k=k, path_prefix=path_prefix, kinds=kinds or None, tests=tests)
        fresh = resp.freshness
        note = freshness_note(fresh, service.store.pending_paths() if fresh is not None and fresh.pending_chunks else (0, []))
        return notice + format_results(resp) + (f"\n\n{note}" if note else "")

    @server.tool(name="get_chunk", description=prompts.tool_description("get_chunk", steering))
    def get_chunk(ref: str) -> str:
        d = service.get_chunk(ref)
        if d is None:
            return f"No indexed function matches {ref!r}. Use a chunk id, path:line, or path::qualname."
        return format_chunk(d)

    @server.tool(name="refresh_index", description=prompts.tool_description("refresh_index", steering))
    def refresh_index() -> str:
        return format_refresh(service.refresh(timeout=60))

    @server.tool(name="index_status", description=prompts.tool_description("index_status", steering))
    def index_status() -> str:
        info = service.status(check_staleness=True)
        return format_status(info) + "\n\n" + json.dumps(
            {k: info.get(k) for k in ("state", "progress", "chunks", "vectors", "stale")}, default=str
        )

    return server


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
