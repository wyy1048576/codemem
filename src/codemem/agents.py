"""Agent registration (`codemem init`): plan the config changes, then apply after confirmation."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import prompts

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


def _merge_mcp_json(path: Path, entry: dict) -> str:
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text("utf-8") or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(f"{path} is not valid JSON ({e}); fix or remove it first") from e
    data.setdefault("mcpServers", {})[prompts.SERVER_NAME] = entry
    return json.dumps(data, indent=2) + "\n"


def plan(repo_root: Path, agents: list[str], *, write_agent_notes: bool = False, steering: str = "light") -> list[Action]:
    repo_root = Path(repo_root).resolve()
    actions: list[Action] = []
    unknown = [a for a in agents if a not in AGENTS]
    if unknown:
        raise ValueError(f"unknown agents {unknown}; choose from {list(AGENTS)}")

    if "claude" in agents:
        # Claude Code starts project servers in the project root, so no path argument is needed.
        path = repo_root / ".mcp.json"
        actions.append(Action(
            "claude", f"add 'codemem' to {path.name} (or run: claude mcp add codemem -- codemem mcp)",
            path, _merge_mcp_json(path, {"command": COMMAND, "args": ["mcp"]}),
        ))
    if "cursor" in agents:
        path = repo_root / ".cursor" / "mcp.json"
        actions.append(Action(
            "cursor", "add 'codemem' to .cursor/mcp.json", path,
            _merge_mcp_json(path, {"command": COMMAND, "args": ["mcp", "${workspaceFolder}"]}),
        ))
    if "codex" in agents:
        snippet = (
            "# Add to ~/.codex/config.toml (codemem does not edit global files):\n"
            f"[mcp_servers.{prompts.SERVER_NAME}]\n"
            f'command = "{COMMAND}"\n'
            f'args = ["mcp", {json.dumps(repo_root.as_posix())}]\n'
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
