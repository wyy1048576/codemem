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
        "Find code from a plain-words description when you have no exact name to grep for: "
        "\"where do users log in?\", \"why are disabled users still logged in?\". Use it first on a "
        "new task, and again whenever you lose the trail. Returns ranked functions, classes and code "
        "blocks with file:line, signature and a short preview. Once you have an exact identifier or "
        "string, use grep." + _FILTERS
    ),
    "detailed": (
        "Search every function, class and code block of this repository by meaning and by keywords at "
        "once (the index follows your edits). One call returns the 10 best matches, ranked, each as "
        "`path:start-end  name  [id N]` with its signature and up to 6 lines of its code: about 2,000 "
        "tokens for 10 results, the cost of one or two file reads.\n\n"
        "Call search_code INSTEAD OF Grep or Glob when:\n"
        "- the task describes a behaviour, bug or feature in words and you do not know yet which file or "
        "function implements it. Make it your first call, before any Grep or Glob;\n"
        "- the names you would grep for are guesses: a function you think exists, or a word from the task "
        "that may not appear in the code;\n"
        "- you are about to try a second variant of a grep for the same idea, or a grep returned nothing, "
        "or more files than you would read;\n"
        "- the code you need is spread over several files (\"where are options checked before a request "
        "is sent\").\n"
        "One search usually replaces several exploratory greps and reads: that is where it saves turns.\n\n"
        "Use Grep or Read INSTEAD when you already hold something exact: an identifier, path, error "
        "message or string that appears verbatim in the task or in code you have read; to list every use "
        "of a known name; to open a file you already know.\n\n"
        "How to call it: describe the behaviour in plain words with the nouns of the task, not one "
        "keyword; leave k at 10. Read the previews before anything else: the function to change is often "
        "among them. Then open only what you need: Read with the path and lines given, or get_chunk(id). "
        "Search again only in different words, when you lose the trail; the same query returns the same "
        "results." + _FILTERS
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
    "detailed": (
        "Return the full source of one function or class plus the names of its callers and callees. "
        "`ref` is a chunk id from search_code (`[id N]`), a `path:line` location, or a `path::qualname` "
        "key. Use it for a search result whose preview is not enough: it costs less than reading the "
        "whole file. A class of 80 lines or more comes back as its outline."
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
    for level in ("none", "light", "detailed", "strong")
}

_REFRESH_INDEX = {
    level: "Check every file now and index what changed. The index follows your edits on its own; "
    "call this after git checkout, pull or rebase, or when results look out of date. Waits up to "
    "a minute and says what changed."
    for level in ("none", "light", "detailed", "strong")
}

_INSTRUCTIONS = {
    "none": "codemem: code search over this repository's functions and classes.",
    "light": (
        "codemem searches this repository by meaning: every function and class, with callers and "
        "tests.\n"
        "Call search_code whenever you have no concrete lead:\n"
        "- at the start of a task, before any grep or file listing: describe the behaviour in plain "
        "words;\n"
        "- whenever you lose the trail: a grep returned nothing or too much, or you don't know which "
        "file or symbol to open next.\n"
        "Once you have an exact name, path or error string, grep or read the file directly.\n"
        "- get_chunk(ref): read one result in full with its callers and callees.\n"
        "- refresh_index(): after git checkout, pull or rebase (the index follows your own edits)."
    ),
    "detailed": (
        "codemem searches this repository's functions, classes and code blocks by meaning and keywords.\n"
        "Choose between search_code and Grep before your first search, not after:\n"
        "- no exact name yet (the task describes behaviour, or your names are guesses): start with ONE "
        "search_code call in plain words, read its previews, then Read or Grep precisely;\n"
        "- an exact identifier, path or string from the task or from code you have read: Grep or Read "
        "it directly, with no search_code first;\n"
        "- lost the trail later (a grep found nothing or too much, or you are guessing a second variant): "
        "search_code again in different words rather than another guess.\n"
        "get_chunk(ref) reads one result in full with its callers and callees. refresh_index() is only "
        "for after git checkout, pull or rebase."
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
        "This repo is indexed by codemem. With no exact name, path or error string to go on (at the "
        "start of a task, or when a grep leads nowhere), call `search_code` with a plain-words "
        "description. Once you have an exact name, use grep."
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


# Claude Code names an MCP tool mcp__<server>__<tool>.
MCP_SEARCH_TOOL = f"mcp__{SERVER_NAME}__search_code"


def first_search_refusal() -> str:
    """What `codemem hook` tells the agent when it refuses the first Grep or Glob of a session."""
    return (
        "This is the first code search of this session and search_code has not been used yet.\n"
        "Unless you already have an exact function name, file path or error string that takes you "
        f"straight to the right file, call {MCP_SEARCH_TOOL} with a plain-words description instead. "
        "If you do have one, repeat this call and it will go through."
    )


def lost_trail_nudge(reason: str, n: int = 0) -> str:
    """What `codemem hook` adds after a Grep or Glob that looks like a lost trail. `reason` is
    `empty` (nothing found), `many` (n files matched) or `streak` (n searches in a row with no
    file opened in between)."""
    what = {
        "empty": "This search found nothing.",
        "many": f"This search matched {n} files, too many to give a clear lead.",
        "streak": f"That is {n} searches in a row without opening a file.",
    }[reason]
    return (
        f"{what} If you have no exact name, path or error string to go on, call {MCP_SEARCH_TOOL} "
        "with a plain-words description of what you are looking for."
    )


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
