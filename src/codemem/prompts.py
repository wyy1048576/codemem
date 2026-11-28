"""ALL agent-facing text lives here so it can be edited and varied for the agent study.

`steering` (config: none | light | strong) controls how hard we push agents
toward codemem over grep.
"""

from __future__ import annotations

SERVER_NAME = "codemem"

MAX_K = 10  # search_code returns at most this many results

_FILTERS = (
    f" k: how many results, 1 to {MAX_K} (default {MAX_K})."
    " Optional filters: path_prefix (a folder), kinds (function, method, class, block), tests "
    "(include, exclude, only)."
    "\nOptional, most useful on your first search of a task, written from the task: intent (one or two "
    "sentences: what the code that has to change does, in the words source code would use), symptom "
    "(one sentence: the wrong behaviour or the missing feature), anchors (up to 20 strings copied "
    "exactly from the task that may appear in the code: identifiers, option names, file names, "
    "fragments of error messages), locations (files or functions that the task itself says are where "
    "the change belongs; their code is shown first)."
)

_SEARCH_CODE = {
    "none": (
        "Search this repository's code (functions, classes, top-level code) by natural-language or "
        "identifier query. Returns ranked results with file:line, signature and a short preview." + _FILTERS
    ),
    "light": (
        "Find code from a plain-words description of what it does: \"where do users log in?\", "
        "\"why are disabled users still logged in?\". Use it:\n"
        "- for your first search on a task, unless you already have a clear anchor: an exact "
        "function, class or file name, or an error string, that leads straight to the code. Fill in "
        "intent, symptom and anchors too (below);\n"
        "- whenever you lose the trail and don't know which direction to grep: a grep found nothing "
        "or too many files, or several searches in a row found no file worth opening.\n"
        "Returns ranked functions, classes and code blocks with file:line, signature and a short "
        "preview. Once you have an exact name or string, grep or read the file." + _FILTERS
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
        "codemem searches this repository by meaning: every function and class, with callers and "
        "tests.\n"
        "Call search_code, describing the behaviour in plain words:\n"
        "- for your first search on a task, before any grep or file listing, unless you already have "
        "a clear anchor: an exact function, class or file name, or an error string, that leads "
        "straight to the code. Fill in its intent, symptom and anchors from the task too;\n"
        "- whenever you lose the trail and don't know which direction to grep: a grep found nothing "
        "or too many files, or several searches in a row found no file worth opening.\n"
        "Once you have an exact name, path or error string, grep or read the file directly.\n"
        "- get_chunk(ref): read one result in full with its callers and callees.\n"
        "- refresh_index(): after git checkout, pull or rebase (the index follows your own edits)."
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
    "light": (
        "This repo is indexed by codemem: `search_code` finds code from a plain-words description of "
        "what it does.\n\n"
        "- **First search on a task:** call `search_code` before any grep, unless you already have a "
        "clear anchor: an exact function, class or file name, or an error string, that leads straight "
        "to the code. Fill in its `intent`, `symptom` and `anchors` from the task too, and `locations` "
        "if the task names where the change belongs.\n"
        "- **Lost the trail:** when you don't know which direction to grep (a grep found nothing or "
        "too many files, or several searches in a row found no file worth opening), call "
        "`search_code` instead of another grep.\n\n"
        "Once you have an exact name, grep or read the file."
    ),
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


_SEARCH_FOOTER = "Lost the trail later? Search again in different words."


def search_footer(steering: str = "light") -> str:
    """Last line of every search_code result from the MCP tool; "" when steering is off."""
    return "" if steering == "none" else _SEARCH_FOOTER


def models_loading_notice() -> str:
    return (
        "Note: codemem is still loading its embedding model or its search index (the first searches after "
        "it starts); these results come from keyword matching only. Search again shortly for results by "
        "meaning."
    )


def vectors_unavailable_notice(why: str) -> str:
    """After results that are by keywords only because codemem could not embed, and not for a load
    in progress: `why` is the error of the model's load or of the embedding endpoint."""
    return (
        f"Note: codemem cannot embed right now ({why}), so these results come from keyword matching only. It tries "
        "again by itself; search again later for results by meaning."
    )


def copy_notice() -> str:
    """Before an answer read from a new checkout's index that is still a copy of another
    checkout's: its first full check did not end within the time the tool waits."""
    return (
        "Note: codemem's index for this checkout started as a copy of another checkout's index, and codemem is "
        "still comparing it with the files here. Until that is done, what it returns can be the other checkout's "
        "code: names, line numbers and code may differ from the files in this checkout. Ask again in a few "
        "seconds, or read the files themselves."
    )


def indexing_notice(percent: float) -> str:
    return (
        f"Note: the codemem index is still being built ({percent:.0f}% done); results may be "
        "incomplete. Keyword matches are available first, semantic matches fill in as embedding "
        "proceeds."
    )
