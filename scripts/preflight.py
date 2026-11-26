"""Start codemem's MCP server on a repo and an index, as a run does, and print what a run's records
do not show by themselves: how long the first searches answer from keywords only, the search index
in use, whether the watcher runs, and whether the model is in memory.

usage: <codemem checkout>/.venv/bin/python preflight.py <repo> <index folder> ["a question"]
The server gets this process's environment: set what the runner sets (CODEMEM_VECTOR_BACKEND, ...).
"""
import os
import sys
import time

import anyio
from mcp import Client, StdioServerParameters

REPO, INDEX = sys.argv[1], sys.argv[2]
QUERY = sys.argv[3] if len(sys.argv) > 3 else "where is the configuration read"
KEYWORDS_ONLY = "keyword matching only"  # in both notes: "still loading" and "cannot embed right now"


async def main() -> None:
    server = StdioServerParameters(command=sys.executable, args=["-m", "codemem", "mcp", REPO, "--index-dir", INDEX],
                                   env=dict(os.environ))
    start = time.monotonic()
    async with Client(server) as client:
        asked = 0
        while True:
            text = (await client.call_tool("search_code", {"query": QUERY, "k": 3})).content[0].text
            asked += 1
            now = time.monotonic() - start
            if KEYWORDS_ONLY not in text:
                print(f"preflight: search {asked}, answered {now:.1f} s after the start, has results by meaning")
                break
            print(f"preflight: search {asked}, answered {now:.1f} s after the start, is from KEYWORDS ONLY")
            if now > 300:
                print("preflight: FAILED, no results by meaning after 300 s")
                break
            await anyio.sleep(1)
        status = (await client.call_tool("index_status", {})).content[0].text
        print(status[: status.rindex("\n\n")])
        for want in ("watching for changes", "embedding model: in memory", "search index: exact (faiss)"):
            print(f"preflight: {'ok     ' if want in status else 'MISSING'} {want!r}")


anyio.run(main)
