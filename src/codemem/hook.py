"""`codemem hook`: two Claude Code hooks that point an agent at codemem when it has no lead.

Claude Code runs the command around tool calls, with the call as JSON on stdin (README, "Using it
from an agent"). One command serves both hooks and tells them apart by `hook_event_name`.

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

State is two small files per session in `<CODEMEM_HOME>/hook-sessions/`: `<session>` (the first
search has been handled) and `<session>.trail` (the two counters of the second hook).

This module imports the standard library and `prompts` only, because it runs on every Grep, Glob
and Read. A hook must never break the agent: whatever goes wrong here, nothing is refused and
nothing is added.
"""

from __future__ import annotations

import json
import os
import re
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


# ---------------------------------------------------------------- the command


def run(stdin: TextIO, stdout: TextIO) -> int:
    try:
        event = json.loads(stdin.read())
        if not isinstance(event, dict):
            return 0
        if event.get("hook_event_name") == "PostToolUse":
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
