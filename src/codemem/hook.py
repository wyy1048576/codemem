"""`codemem hook`: three Claude Code hooks. One gives the agent a codemem search with its first
prompt; two point it at codemem when it has no lead.

Claude Code runs the command when the user sends a prompt and around tool calls, with the event as
JSON on stdin (README, "Using it from an agent"). One command serves the three hooks and tells them
apart by `hook_event_name`.

1. Before a tool call (PreToolUse, on Grep, Glob, Bash and codemem's search_code): the first search.
   The first Grep or Glob of a session, when search_code has not been used yet, is refused once
   with `prompts.first_search_refusal()` as the reason. The agent then either calls search_code
   or repeats its call, which goes through. If search_code came first, nothing happens.
   A shell command (the Bash tool) counts as a search here when it runs one of SHELL_WORDS. That
   is a word check, not a parse of the command: `pytest | grep FAILED` counts too, and costs one
   refusal in a session; a search written some other way does not count. So that the other shell
   commands (tests, git, builds) do not pay for starting Python, the hook for Bash is registered
   with a condition for each word (SHELL_RULES, Claude Code's `if`): Claude Code then starts the
   command only for a shell command that runs one of them.

2. After a tool call (PostToolUse, on Grep, Glob, Read and codemem's search_code and get_chunk):
   the lost trail. Never refuses anything. It adds `prompts.lost_trail_nudge()` to what the agent
   reads after a Grep or Glob that
   - found nothing, or
   - matched more than MANY_FILES files, or
   - was search number STREAK in a row, counting Grep and Glob, with no Read, search_code or
     get_chunk in between.
   Shell commands take no part in this one: they neither count as a search nor end a run.
   After a nudge the next QUIET searches get none, so the agent is not told the same thing on
   every search. A search_code call ends that quiet stretch: what follows it is a new trail.

3. When the user sends a prompt (UserPromptSubmit): the starting search. On the first prompt of a
   session, one codemem search with the prompt as the query, in the repository that holds the
   session's `cwd`: the search `codemem search -k START_K` makes, with its defaults (it brings the
   index to the checkout first, as that command does). The agent gets its results with the prompt,
   as context: `prompts.start_search_block()`, the header line, then one line per result,
   `path:start_line  qualified name`. Later prompts of the session get nothing. So does the first
   one when there is no index or its first build has not finished, when the search could not use
   the embedding model (keywords only), when it finds nothing or fails, and when it takes longer
   than START_SECONDS: the prompt then goes to the agent as it would without the hook. The first
   search of a process loads the embedding model (about 9 s on a laptop), which is why this hook is
   registered with a timeout of its own (agents.START_SEARCH_TIMEOUT), longer than START_SECONDS.

State is three small files per session in `<CODEMEM_HOME>/hook-sessions/`: `<session>` (the first
search has been handled), `<session>.trail` (the two counters of the second hook) and
`<session>.start` (the starting search has been made).

This module imports the standard library and `prompts` only, because the first two hooks run on
every Grep, Glob and Read. The starting search imports the search stack (numpy, the index, the
model) inside its own function, and only on the first prompt of a session. A hook must never break
the agent: whatever goes wrong here, nothing is refused and nothing is added.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, TextIO

from . import prompts

SEARCH_TOOLS = ("Grep", "Glob")
_TRAIL_TOOLS = ("search_code", "get_chunk")  # codemem tools that count as following a lead
PRE_MATCHER = "|".join((*SEARCH_TOOLS, prompts.MCP_SEARCH_TOOL))
POST_MATCHER = "|".join((*SEARCH_TOOLS, "Read", f"mcp__{prompts.SERVER_NAME}__({'|'.join(_TRAIL_TOOLS)})"))

SHELL_TOOL = "Bash"
SHELL_WORDS = ("rg", "grep", "find")  # a shell command that runs one of these is a code search
# The word on its own: not part of a path (docs/grep.md), an option (--find-links) or a longer
# word (findstr).
# The same words as conditions of a hook, in Claude Code's permission-rule form: `Bash(rg *)`.
SHELL_RULES = tuple(f"{SHELL_TOOL}({word} *)" for word in SHELL_WORDS)
_SHELL_SEARCH = re.compile(rf"(?<![\w./-])({'|'.join(SHELL_WORDS)})(?![\w-])")

MANY_FILES = 50  # more files than this is "too many to give a clear lead"
STREAK = 3  # this many searches in a row with nothing opened in between
QUIET = 2  # searches after a nudge that get none
_KEEP_SECONDS = 7 * 24 * 3600  # state of older sessions is deleted

START_K = 20  # results in the starting search's block
START_SECONDS = 50.0  # the starting search's own limit, inside the hook's timeout in settings.json
_EMBEDDED = "embed_query:"  # the start of codemem's timing of the query's embedding (search.py)


def _sessions_dir() -> Path:
    # The same folder as config.codemem_home(), without importing config.
    return Path(os.environ.get("CODEMEM_HOME") or Path.home() / ".codemem") / "hook-sessions"


def _session_file(event: dict, suffix: str = "") -> Path | None:
    session = event.get("session_id")
    if not isinstance(session, str) or not session:
        return None
    return _sessions_dir() / (re.sub(r"[^A-Za-z0-9_-]", "_", session)[:120] + suffix)


def _codemem_tool(tool: str, names: tuple[str, ...]) -> bool:
    # A server registered by a plugin gets a longer prefix, so match the ends.
    return tool.startswith("mcp__") and prompts.SERVER_NAME in tool and tool.endswith(tuple(f"__{n}" for n in names))


def _forget_old_sessions(folder: Path) -> None:
    cutoff = time.time() - _KEEP_SECONDS
    for entry in os.scandir(folder):
        try:
            if entry.stat().st_mtime < cutoff:
                os.unlink(entry.path)
        except OSError:
            pass


# ---------------------------------------------------------------- 1. the first search


def _claim(marker: Path) -> bool:
    """Create the session's marker. True if this call created it, False if it was there already.
    Creating it is one atomic step, so of two searches sent at once only one is refused."""
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(marker, "x"):
            pass
    except FileExistsError:
        return False
    _forget_old_sessions(marker.parent)
    return True


def _is_shell_search(event: dict) -> bool:
    tool_input = event.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    return isinstance(command, str) and bool(_SHELL_SEARCH.search(command))


def before_tool(event: dict) -> str | None:
    """The reason to refuse this tool call, or None to let it through."""
    tool = event.get("tool_name")
    if not isinstance(tool, str):
        return None
    search = tool in SEARCH_TOOLS or (tool == SHELL_TOOL and _is_shell_search(event))
    if not search and not _codemem_tool(tool, ("search_code",)):
        return None
    marker = _session_file(event)
    if marker is None:
        return None
    first = _claim(marker)
    return prompts.first_search_refusal() if first and search else None


# ---------------------------------------------------------------- 2. the lost trail


def _file_count(response: Any) -> tuple[int | None, bool]:
    """(files a Grep or Glob matched, whether it matched nothing), read from the tool's result.
    The count is None when the result does not give one: Grep's `content` mode lists lines, not
    files, and a result in a form this code does not know says nothing either way."""
    if isinstance(response, str):
        return None, response.lstrip().startswith(("No matches found", "No files found"))
    if not isinstance(response, dict):
        return None, False
    if response.get("mode") == "content":
        lines = response.get("numLines")
        return None, lines == 0 and not response.get("content")
    for key in ("totalMatches", "totalFiles", "numFiles"):  # Glob; Grep's file list; Grep's counts
        n = response.get(key)
        if isinstance(n, int) and not isinstance(n, bool):
            return n, n == 0
    return None, False


def _load(path: Path) -> dict[str, int]:
    try:
        data = json.loads(path.read_text("utf-8"))
        return {"streak": max(0, int(data["streak"])), "quiet": max(0, int(data["quiet"]))}
    except (OSError, ValueError, TypeError, KeyError):
        return {"streak": 0, "quiet": 0}


def _save(path: Path, state: dict[str, int]) -> None:
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), "utf-8")
    if new:
        _forget_old_sessions(path.parent)


def after_tool(event: dict) -> str | None:
    """The reminder to add after this tool call, or None."""
    tool = event.get("tool_name")
    path = _session_file(event, ".trail")
    if path is None or not isinstance(tool, str):
        return None
    if tool == "Read" or _codemem_tool(tool, _TRAIL_TOOLS):
        if path.exists():  # nothing to reset in a session that has not searched yet
            state = _load(path)
            reset = {"streak": 0, "quiet": 0 if tool.endswith("__search_code") else state["quiet"]}
            if reset != state:
                _save(path, reset)
        return None
    if tool not in SEARCH_TOOLS:
        return None

    state = _load(path)
    streak = state["streak"] + 1
    files, nothing = _file_count(event.get("tool_response"))
    if nothing:
        nudge = prompts.lost_trail_nudge("empty")
    elif files is not None and files > MANY_FILES:
        nudge = prompts.lost_trail_nudge("many", files)
    elif streak >= STREAK:
        nudge = prompts.lost_trail_nudge("streak", streak)
    else:
        nudge = None
    if nudge and state["quiet"] == 0:
        _save(path, {"streak": 0, "quiet": QUIET})
        return nudge
    _save(path, {"streak": streak, "quiet": max(0, state["quiet"] - 1)})
    return None


# ---------------------------------------------------------------- 3. the starting search

_worker: threading.Thread | None = None  # the starting search of this process, once one has started


def _search(prompt: str, cwd: str) -> list[dict] | None:
    """The results of `codemem search -k START_K <prompt>` in the repository that holds `cwd`, as
    `--json` gives them; None without a finished index or without the embedding model."""
    import contextlib
    import sys

    from .cli import _follow_checkout
    from .service import CodememService

    # Claude Code reads this process's stdout as the hook's answer: whatever the search stack might
    # print goes to stderr instead.
    with contextlib.redirect_stdout(sys.stderr):
        svc = CodememService(cwd)
        try:
            if not svc.has_index():
                return None
            options = dict(k=START_K, signals=None, path_prefix=None, kinds=None, languages=None, tests="include")
            _follow_checkout(svc, prompt, options)
            resp = svc.search(prompt, **options)
        finally:
            svc.close()
    if not any(str(key).startswith(_EMBEDDED) for key in resp.timings):
        return None
    return resp.to_dict()["results"]


def start_search(event: dict) -> str | None:
    """The block to give the agent with this prompt, or None."""
    global _worker
    prompt, cwd = event.get("prompt"), event.get("cwd")
    if not isinstance(prompt, str) or not prompt.strip() or not isinstance(cwd, str) or not cwd:
        return None
    marker = _session_file(event, ".start")
    if marker is None or not _claim(marker):
        return None
    found: list = []

    def work() -> None:
        try:
            found.append(_search(prompt, cwd))
        except Exception:  # no model, an embedding endpoint that does not answer, a store it cannot read
            pass

    # In a thread of its own, so that a search past START_SECONDS can be left behind (cli.cmd_hook
    # then ends the process without waiting for it).
    _worker = threading.Thread(target=work, name="codemem-start-search", daemon=True)
    _worker.start()
    _worker.join(START_SECONDS)
    results = found[0] if found and not _worker.is_alive() else None
    return prompts.start_search_block(results) if results else None


def search_left_running() -> bool:
    """Whether the starting search of this process ran past START_SECONDS and is still running."""
    return _worker is not None and _worker.is_alive()


# ---------------------------------------------------------------- the command


def run(stdin: TextIO, stdout: TextIO) -> int:
    try:
        event = json.loads(stdin.read())
        if not isinstance(event, dict):
            return 0
        if event.get("hook_event_name") == "UserPromptSubmit":
            text = start_search(event)
            out = {"hookEventName": "UserPromptSubmit", "additionalContext": text}
        elif event.get("hook_event_name") == "PostToolUse":
            text = after_tool(event)
            out = {"hookEventName": "PostToolUse", "additionalContext": text}
        else:
            text = before_tool(event)
            out = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": text}
    except (OSError, ValueError, TypeError):
        return 0
    if text:
        json.dump({"hookSpecificOutput": out}, stdout)
        stdout.write("\n")
    return 0
