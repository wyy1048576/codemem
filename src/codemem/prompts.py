"""ALL agent-facing text lives here so it can be edited and varied for the agent study.

`steering` (config: none | light | strong) controls how hard we push agents
toward codemem over grep.
"""

from __future__ import annotations

SERVER_NAME = "codemem"

_FILTERS = (
    " Optional filters: path_prefix (a folder), kinds (function, method, class, block), tests "
    "(include, exclude, only)."
)

_SEARCH_CODE = {
    "none": (
        "Search this repository's code (functions, classes, top-level code) by natural-language or "
        "identifier query. Returns ranked results with file:line, signature and a short preview." + _FILTERS
    ),
    "light": (
        "Find the code for a task described in plain words, even when you know no identifier: "
        "\"where do users log in?\", \"add OCR to the upload pipeline\", \"why are disabled users still "
        "logged in?\". Returns ranked functions, classes and code blocks with file:line, signature and "
        "a short preview. Prefer this over grep for exploring; use grep for exact strings." + _FILTERS
    ),
    "strong": (
        "Use search_code FIRST to find the code for a task, bug or feature described in plain words, "
        "even when you know no identifier: \"where do users log in?\", \"add OCR to the upload "
        "pipeline\". It combines keyword and semantic search over every function and class, including "
        "who calls it and which tests cover it, and returns ranked results with file:line. Always try "
        "this before grep/find for exploring; use grep only for exact strings. Then call get_chunk on "
        "promising results instead of reading whole files." + _FILTERS
    ),
}

_GET_CHUNK = {
    "none": "Return the full source of one indexed function or class plus its callers and callees.",
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
    "models in use, the indexed git commit, anything still being indexed, and which files are not "
    "indexed and why (too large, generated, not code, ignored)."
    for level in ("none", "light", "strong")
}

_REFRESH_INDEX = {
    level: "Check every file now and index what changed. The index follows your edits on its own; "
    "call this after git checkout, pull or rebase, or when results look out of date. Waits up to "
    "a minute and says what changed."
    for level in ("none", "light", "strong")
}

_INSTRUCTIONS = {
    "none": "codemem: code search over this repository's functions and classes.",
    "light": (
        "codemem indexes every function and class in this repository (code, callers, tests) for "
        "hybrid keyword + semantic search.\n"
        "- search_code(query): describe what you want to build, change or understand in plain "
        "words (\"add OCR to the upload pipeline\"); identifiers work too.\n"
        "- get_chunk(ref): read one result in full with its callers/callees.\n"
        "- index_status(): readiness, and what is not indexed.\n"
        "- refresh_index(): after git checkout, pull or rebase (the index follows your own edits).\n"
        "Use grep for exact string matches."
    ),
    "strong": (
        "codemem indexes every function and class in this repository (code, callers, tests) for "
        "hybrid keyword + semantic search. Start every code-location task with search_code: describe the "
        "behaviour from the issue in plain words (you don't need exact identifiers). Inspect hits "
        "with get_chunk and follow callers/callees from there. Fall back to grep only for exact "
        "strings, and re-run search_code with different wording before giving up. The index follows "
        "your edits; call refresh_index after git checkout, pull or rebase."
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
    table = {
        "search_code": _SEARCH_CODE, "get_chunk": _GET_CHUNK, "index_status": _INDEX_STATUS,
        "refresh_index": _REFRESH_INDEX,
    }[tool]
    return table[steering]


def server_instructions(steering: str = "light") -> str:
    return _INSTRUCTIONS[steering]


def agent_notes(steering: str = "light") -> str | None:
    """Snippet for AGENTS.md / CLAUDE.md, or None when steering is off."""
    text = _AGENT_NOTES.get(steering)
    if text is None:
        return None
    return f"{AGENT_NOTES_MARKER}\n## Code search\n\n{text}\n{AGENT_NOTES_MARKER}\n"


def models_loading_notice() -> str:
    return (
        "Note: the embedding model is still loading (the first search after codemem starts); these "
        "results come from keyword matching only. Search again in a few seconds for results by meaning."
    )


def indexing_notice(percent: float) -> str:
    return (
        f"Note: the codemem index is still being built ({percent:.0f}% done); results may be "
        "incomplete. Keyword matches are available first, semantic matches fill in as embedding "
        "proceeds."
    )
