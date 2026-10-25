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
    "models in use and the indexed git commit. Lists the files that changed since the last index, "
    "most depended-on first: how many other files call into each one, and its percentile in the "
    "repo. Use it to decide whether to call reindex."
    for level in ("none", "light", "strong")
}

_REINDEX = {
    level: "Bring the code index up to date with the files on disk, then return what changed. "
    "Only changed functions are re-embedded, so the cost grows with the size of the change. "
    "Call it when edits since the last index matter for your next searches, not after every edit."
    for level in ("none", "light", "strong")
}

# Added to the instructions when the server does not re-index on save (config `watch = false`).
_MANUAL_UPDATES = (
    "The index does not update on save. After you edit files, index_status lists what changed; "
    "call reindex() when those changes matter for your next searches."
)

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
    table = {
        "search_code": _SEARCH_CODE, "get_chunk": _GET_CHUNK, "index_status": _INDEX_STATUS, "reindex": _REINDEX,
    }[tool]
    return table[steering]


def server_instructions(steering: str = "light", *, watch: bool = False) -> str:
    return _INSTRUCTIONS[steering] if watch else f"{_INSTRUCTIONS[steering]}\n{_MANUAL_UPDATES}"


def agent_notes(steering: str = "light") -> str | None:
    """Snippet for AGENTS.md / CLAUDE.md, or None when steering is off."""
    text = _AGENT_NOTES.get(steering)
    if text is None:
        return None
    return f"{AGENT_NOTES_MARKER}\n## Code search\n\n{text}\n{AGENT_NOTES_MARKER}\n"


REINDEX_SKILL_NAME = "codemem-reindex"

# Installed by `codemem init --agents claude` as .claude/skills/codemem-reindex/SKILL.md.
_REINDEX_SKILL = """\
---
name: codemem-reindex
description: Decide when to refresh the codemem code search index. Use after you create, edit, delete or rename source files in this repo, after git checkout/pull/rebase, and before relying on search_code for code that changed.
---

# Keeping the codemem index fresh

The codemem index does not update on save in this repo. `search_code` sees the files as they
were at the last index: when the session started, or your last `reindex`. You decide when to
reindex. Weigh what is stale against what a reindex costs.

## You don't need to track your edits

`index_status` lists every file that differs from the index, whether you, the user, git or a
tool changed it. Check it instead of keeping your own list. For each file it gives:

- `change`: modified, added or deleted;
- `inbound_files`: how many other files call into it, and `inbound_calls`: how many calls;
- `percentile`: the share of indexed files that fewer other files call into. 95 means only
  about 5% of files are more depended-on.

It also gives `total_files` and `head_moved` (git HEAD moved since the last index). The call
counts come from function-name matching, so treat them as approximate.

## When to check

- before relying on `search_code` for code that changed;
- after a batch of edits, a refactor, or adding, renaming or deleting functions;
- after `git checkout`, `pull`, `rebase` or `stash pop`, a code generator, or a formatter run
  across the repo.

You don't need to check between small edits.

## Decide on two things

1. **How much changed:** the changed and deleted files against `total_files`.
2. **How central the changed files are:** `inbound_files` and `percentile`, plus what you
   know about the code.
   - Central: entry points, base classes, shared utilities, public APIs, widely used models,
     schemas and config.
   - Leaves: tests, scripts, examples, and modules used in one place.

   Added, renamed or deleted functions make stale results more misleading than edits inside a
   function body: a search for the new name finds nothing.

Rough guide. Use judgment; these are not fixed rules.

| Situation | Action |
|---|---|
| A few leaf files changed, and you already know where your changes are | don't reindex yet |
| Any changed file is central (percentile around 90 or more, or called from many files) and you will search again | reindex |
| A large share of the repo changed (around 5% of files, or more than about 50 files) | reindex |
| `head_moved` is true (branch switch, pull, rebase) | reindex |
| You are about to search for code you added or renamed | reindex first |
| You are done and won't search again | skip: the server catches up when it next starts |

## Cost

`reindex` re-embeds only what changed: the changed functions, plus the caller lists ("usage")
of the functions they call. Unchanged files are only checked by size and timestamp. So the cost
grows with the size of the change: about a second for a few files, minutes for hundreds of
files on a CPU. Batch your edits and reindex once after a group of changes, not after every
file.

## How

Call the `reindex` tool of the `codemem` MCP server. It returns when the index is up to date,
with what changed. Don't run `codemem index` in a shell while the server is running: the server
would keep searching its old vectors.
"""


def reindex_skill() -> str:
    return _REINDEX_SKILL


def indexing_notice(percent: float) -> str:
    return (
        f"Note: the codemem index is still being built ({percent:.0f}% done); results may be "
        "incomplete. Keyword matches are available first, semantic matches fill in as embedding "
        "proceeds."
    )
