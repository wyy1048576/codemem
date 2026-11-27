"""codemem's MCP server (the loops' codemem, 7c24558) as Claude Code launches it in the `mcp` arm, with three changes
that are fixes on `main` since or are needed for a fair run, and no change to what a search finds or shows:

  1. A search waits for the embedding model and for the warm-up thread (main: the eval's gate waits for it; #60:
     one model call at a time; without it the first search crashes on a dtype race). Without this, the first search of a
     session can come back from keywords only, as in PR #45's early agent runs.
  2. Every tool answers in plain text (main, f821dc7), not also as {"result": "..."}.
  3. Each search_code call is logged (query, k, path_prefix, the results' spans) to CODEMEM_CALL_LOG, one JSON line.
  4. With MCP_PR26=1: PR #26's light server instructions, search_code and get_chunk descriptions, and the footer
     "Lost the trail later? ..." (from main, pr26/prompts.py). The older snapshot has the earlier light wording.

Usage (Claude Code's MCP config): python mcp_codemem.py REPO
"""
import json
import os
import sys
import time

import mcp.server.mcpserver as M
from codemem import server as SV
from codemem import service as S

_search = S.CodememService.search


def search(self, query, *, wait_for_models=True, **kw):
    # One model call at a time (main, #60): the server's warm-up thread converts the query model to float32 while a
    # first search would already use it ("expected scalar type BFloat16 but found Float"), so wait for the warm-up.
    warm = getattr(self, "_prewarm", None)
    if warm is not None and warm.is_alive():
        warm.join()
    resp = _search(self, query, wait_for_models=True, **kw)
    log = os.environ.get("CODEMEM_CALL_LOG")
    if log:
        with open(log, "a", encoding="utf8") as f:
            f.write(json.dumps({"t": time.time(), "query": query, "k": kw.get("k"), "path_prefix": kw.get("path_prefix"),
                                "models_loading": resp.models_loading,
                                "results": [[r.path, r.start_line, r.end_line, r.qualname] for r in resp.results]}) + "\n")
    return resp


S.CodememService.search = search
_tool = M.MCPServer.tool


def tool(self, *a, **kw):
    kw.setdefault("structured_output", False)
    return _tool(self, *a, **kw)


M.MCPServer.tool = tool

if os.environ.get("MCP_PR26") == "1":  # 4. PR #26's light wording and the footer, from main (pr26/prompts.py)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from codemem import prompts as P
    from pr26 import prompts as P26
    for table in ("_INSTRUCTIONS", "_SEARCH_CODE", "_GET_CHUNK"):
        getattr(P, table)["light"] = getattr(P26, table)["light"]
    _format = SV.format_results
    SV.format_results = lambda resp: _format(resp) + "\n\n" + P26.search_footer("light")

if __name__ == "__main__":
    SV.run_stdio(sys.argv[1])
