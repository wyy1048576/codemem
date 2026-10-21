"""ALL agent-facing text lives here so it can be edited and varied for the agent study.

`steering` (config: none | light | strong) controls how hard we push agents
toward codemem over grep.
"""

from __future__ import annotations

SERVER_NAME = "codemem"

_SEARCH_CODE = {
    "none": (
        "Search this repository's functions by natural-language or identifier query. "
        "Returns ranked functions with file:line, signature and a short preview."
    ),
    "light": (
        "Use search_code to locate code relevant to an issue, bug or feature, especially when you "
        "don't know exact identifiers. Returns ranked functions with file:line, signature and a "
        "short preview. Prefer this over grep for exploratory search; use grep for exact strings."
    ),
    "strong": (
        "Use search_code FIRST to locate code relevant to an issue, bug or feature, especially when "
        "you don't know exact identifiers. It combines keyword and semantic search over every "
        "function, including who calls it and which tests cover it, and returns ranked functions "
        "with file:line. Always try this before grep/find for exploratory search; use grep only for "
        "exact strings. Then call get_chunk on promising results instead of reading whole files."
    ),
}

_GET_CHUNK = {
    "none": "Return the full source of one indexed function plus its callers and callees.",
    "light": (
        "Return the full source of one function plus its callers and callees. `ref` is a chunk id "
        "from search_code, a `path:line` location, or a `path::qualname` key."
    ),
    "strong": (
        "Return the full source of one function plus its callers and callees. `ref` is a chunk id "
        "from search_code, a `path:line` location, or a `path::qualname` key. Use this to inspect "
        "search results and follow the call graph instead of opening whole files."
    ),
}

_INDEX_STATUS = {
    level: "Report whether the code index is ready or still indexing (with progress), counts, "
    "models in use, the indexed git commit and how many files changed since."
    for level in ("none", "light", "strong")
}

_INSTRUCTIONS = {
    "none": "codemem: code search over this repository's functions.",
    "light": (
        "codemem indexes every function in this repository (code, callers, tests) for hybrid "
        "keyword + semantic search.\n"
        "- search_code(query): find functions relevant to a task; describe behaviour in plain "
        "words or use identifiers.\n"
        "- get_chunk(ref): read one result in full with its callers/callees.\n"
        "- index_status(): check readiness.\n"
        "Use grep for exact string matches."
    ),
    "strong": (
        "codemem indexes every function in this repository (code, callers, tests) for hybrid "
        "keyword + semantic search. Start every code-location task with search_code: describe the "
        "behaviour from the issue in plain words (you don't need exact identifiers). Inspect hits "
        "with get_chunk and follow callers/callees from there. Fall back to grep only for exact "
        "strings, and re-run search_code with different wording before giving up."
    ),
}

AGENT_NOTES_MARKER = "<!-- codemem -->"

_AGENT_NOTES = {
    "light": "This repo is indexed by codemem. Prefer `search_code` before grep when locating code.",
    "strong": (
        "This repo is indexed by codemem (MCP server `codemem`). When locating code for an issue, "
        "call `search_code` first with a plain-language description, then `get_chunk` on the hits. "
        "Use grep only for exact strings."
    ),
}


def tool_description(tool: str, steering: str = "light") -> str:
    table = {"search_code": _SEARCH_CODE, "get_chunk": _GET_CHUNK, "index_status": _INDEX_STATUS}[tool]
    return table[steering]


def server_instructions(steering: str = "light") -> str:
    return _INSTRUCTIONS[steering]


def agent_notes(steering: str = "light") -> str | None:
    """Snippet for AGENTS.md / CLAUDE.md, or None when steering is off."""
    text = _AGENT_NOTES.get(steering)
    if text is None:
        return None
    return f"{AGENT_NOTES_MARKER}\n## Code search\n\n{text}\n{AGENT_NOTES_MARKER}\n"


def indexing_notice(percent: float) -> str:
    return (
        f"Note: the codemem index is still being built ({percent:.0f}% done); results may be "
        "incomplete. Keyword matches are available first, semantic matches fill in as embedding "
        "proceeds."
    )
