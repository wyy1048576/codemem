"""Agent registration (`codemem init`): plan the config changes, then apply after confirmation."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import hook, prompts

AGENTS = ("claude", "cursor", "codex")
COMMAND = "codemem"


@dataclass
class Action:
    agent: str
    description: str
    path: Path | None = None  # None = print only, never write
    content: str = ""

    @property
    def writes(self) -> bool:
        return self.path is not None


def launch_command() -> tuple[str, list[str]]:
    """How an agent starts codemem: the `codemem` command when it is on PATH (uv tool, pipx),
    else this Python with `-m codemem`, which works from whichever environment codemem is in."""
    if shutil.which(COMMAND):
        return COMMAND, []
    return sys.executable, ["-m", "codemem"]


def _merge_mcp_json(path: Path, entry: dict) -> str:
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text("utf-8") or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}); fix or remove it first") from e
    data.setdefault("mcpServers", {})[prompts.SERVER_NAME] = entry
    return json.dumps(data, indent=2) + "\n"


HOOK_TIMEOUT = 10  # seconds; the command takes about 0.2
# Seconds for the starting search: the first search of a process loads the embedding model, about
# 9 s on a laptop. The hook gives up by itself before this (hook.START_SECONDS).
START_SEARCH_TIMEOUT = 60
_OUR_HOOK = re.compile(r"""codemem(\.exe)?["']?\s+hook\s*$""")  # `codemem hook`, `<python> -m codemem hook`


def _hook_groups(command: str, *, write_hooks: bool = True, start_search: bool = False) -> dict[str, list[dict]]:
    """What codemem registers with Claude Code: for each event, the groups (a matcher and its
    commands) in the form of `.claude/settings.json`. `write_hooks`: the first search and the lost
    trail (PreToolUse, PostToolUse); `start_search`: the starting search (UserPromptSubmit)."""
    groups: dict[str, list[dict]] = {}
    if write_hooks:
        direct = {"type": "command", "command": command, "timeout": HOOK_TIMEOUT}
        # One command for each word, because a condition holds exactly one rule. Claude Code starts
        # a command only when its condition matches, so other shell commands cost nothing. A
        # version of Claude Code without `if` would start it for every shell command; the hook
        # checks the words again itself, so that is slower but not wrong.
        shell = [
            {"type": "command", "if": rule, "command": command, "timeout": HOOK_TIMEOUT} for rule in hook.SHELL_RULES
        ]
        groups["PreToolUse"] = [
            {"matcher": hook.PRE_MATCHER, "hooks": [direct]},
            {"matcher": hook.SHELL_TOOL, "hooks": shell},
        ]
        groups["PostToolUse"] = [{"matcher": hook.POST_MATCHER, "hooks": [direct]}]
    if start_search:
        # No matcher: Claude Code runs it on every prompt, and the hook searches on the first only.
        start = {"type": "command", "command": command, "timeout": START_SEARCH_TIMEOUT}
        groups["UserPromptSubmit"] = [{"hooks": [start]}]
    return groups


def hook_command() -> str:
    """The `codemem hook` command line, as Claude Code's hook shell runs it (a POSIX shell: sh or
    bash, and Git Bash on Windows). A Windows path is written with forward slashes, which that
    shell and PowerShell both take, and is quoted only when it has to be. Claude Code falls back
    to PowerShell where Git Bash is missing; a quoted path does not run there."""
    command, prefix = launch_command()
    if os.sep == "\\" and command != COMMAND:
        command = Path(command).as_posix()
    return " ".join([shlex.quote(command), *prefix, "hook"])


def _is_our_hook(entry: object) -> bool:
    return isinstance(entry, dict) and isinstance(entry.get("command"), str) and bool(_OUR_HOOK.search(entry["command"]))


def _merge_hooks_json(path: Path, command: str, *, write_hooks: bool = True, start_search: bool = False) -> str | None:
    """`.claude/settings.json` with codemem's hooks in it (those `_hook_groups` gives for the two
    flags), or None when they are there already. Every other setting and every other hook is kept,
    codemem's entries of the other events too. Earlier codemem entries of an event are replaced
    where the first of them stands, so running `init` again never adds them twice."""
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text("utf-8") or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}); fix or remove it first") from e
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise ValueError(f"{path} does not hold a settings object with a `hooks` object; fix or remove it first")
    before = json.dumps(data, sort_keys=True)
    hooks = data.setdefault("hooks", {})
    for event, ours in _hook_groups(command, write_hooks=write_hooks, start_search=start_search).items():
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"{path}: hooks.{event} is not a list; fix or remove it first")
        kept: list = []
        at: int | None = None  # where the earlier codemem entry stood
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(inner, list) or not any(_is_our_hook(h) for h in inner):
                kept.append(group)
                continue
            if at is None:
                at = len(kept)
            if others := [h for h in inner if not _is_our_hook(h)]:  # the user's own hooks in the same group
                kept.append({**group, "hooks": others})
        at = len(kept) if at is None else at
        hooks[event] = [*kept[:at], *ours, *kept[at:]]
    if json.dumps(data, sort_keys=True) == before:
        return None
    return json.dumps(data, indent=2) + "\n"


def plan(
    repo_root: Path, agents: list[str], *, write_agent_notes: bool = False, write_hooks: bool = False,
    start_search: bool = False, steering: str = "light",
) -> list[Action]:
    repo_root = Path(repo_root).resolve()
    actions: list[Action] = []
    unknown = [a for a in agents if a not in AGENTS]
    if unknown:
        raise ValueError(f"unknown agents {unknown}; choose from {list(AGENTS)}")

    command, prefix = launch_command()
    if "claude" in agents:
        # Claude Code starts project servers in the project root, so no path argument is needed.
        # alwaysLoad: by default Claude Code keeps an MCP server's tools behind a tool-search
        # step, where the agent sees their names only. With it, codemem's tools and their
        # descriptions are in front of the agent from the first turn.
        path = repo_root / ".mcp.json"
        shown = " ".join([command, *prefix, "mcp"])
        actions.append(Action(
            "claude", f"add 'codemem' to {path.name} (or run: claude mcp add codemem -- {shown})",
            path, _merge_mcp_json(path, {"command": command, "args": [*prefix, "mcp"], "alwaysLoad": True}),
        ))
        if write_hooks or start_search:  # hooks are a Claude Code feature: the flags do nothing for other agents
            path = repo_root / ".claude" / "settings.json"
            content = _merge_hooks_json(path, hook_command(), write_hooks=write_hooks, start_search=start_search)
            if content is not None:
                what = ["first search", "lost trail"] if write_hooks else []
                what += ["starting search"] if start_search else []
                actions.append(Action(
                    "hooks", f"add codemem's hooks ({', '.join(what)}) to .claude/settings.json", path, content,
                ))
    if "cursor" in agents:
        path = repo_root / ".cursor" / "mcp.json"
        actions.append(Action(
            "cursor", "add 'codemem' to .cursor/mcp.json", path,
            _merge_mcp_json(path, {"command": command, "args": [*prefix, "mcp", "${workspaceFolder}"]}),
        ))
    if "codex" in agents:
        args = json.dumps([*prefix, "mcp", repo_root.as_posix()])
        snippet = (
            "# Add to ~/.codex/config.toml (codemem does not edit global files):\n"
            f"[mcp_servers.{prompts.SERVER_NAME}]\n"
            f"command = {json.dumps(command)}\n"
            f"args = {args}\n"
        )
        actions.append(Action("codex", "print snippet for ~/.codex/config.toml", None, snippet))

    if write_agent_notes and (notes := prompts.agent_notes(steering)):
        targets = []
        if "claude" in agents:
            targets.append("CLAUDE.md")
        if "codex" in agents or "cursor" in agents:
            targets.append("AGENTS.md")
        for name in targets:
            path = repo_root / name
            existing = path.read_text("utf-8") if path.is_file() else ""
            if prompts.AGENT_NOTES_MARKER in existing:
                continue  # already present: idempotent
            content = existing + ("\n" if existing and not existing.endswith("\n") else "") + (
                "\n" if existing else ""
            ) + notes
            actions.append(Action("notes", f"append codemem note to {name}", path, content))
    return actions


def apply(actions: list[Action]) -> list[str]:
    done = []
    for action in actions:
        if action.path is None:
            continue
        action.path.parent.mkdir(parents=True, exist_ok=True)
        action.path.write_text(action.content, encoding="utf-8", newline="\n")
        done.append(str(action.path))
    return done


def command_on_path() -> bool:
    return shutil.which(COMMAND) is not None
