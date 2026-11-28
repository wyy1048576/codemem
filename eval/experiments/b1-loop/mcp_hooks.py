"""Claude Code hooks of the `mcp` arm: hybrid_v2's rules A (repeated greps) and D (review after the first edit), as
hooks on the real agent instead of steps of our own loop. State per session in STATE_DIR/<session_id>.json; every
decision is appended to STATE_DIR/<session_id>.log.jsonl.

  PreToolUse Grep   A grep is a repeat when half or more of its normalised alternatives (a|b|c, lowercased, escapes
                    removed) were in an earlier grep's that ran (as hybrid_v2). The first repeat runs; later repeats are refused,
                    with a pointer to codemem's search_code.
  PostToolUse       After STUCK greps in a row with no edit and no codemem search: one note to change direction with
                    search_code. Edit / Write / search_code reset the count.
  Stop              The first time the agent stops after an edit: blocked once, with the diff and the review checklist
                    of hybrid_v2 (callers, sibling code paths, other files). A stop with no edit is not blocked.

Usage (settings.json hook command): python mcp_hooks.py STATE_DIR
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

STUCK = 4
REPEAT_JACCARD = 0.5
DIFF_CHARS = 6000
SEARCH = "mcp__codemem__search_code"


def alternatives(pattern):
    parts = re.split(r"(?<!\\)\|", pattern or "")
    return sorted({re.sub(r"[\\()^$]", "", p).strip().lower() for p in parts if p.strip()})


def main():
    ev = json.load(sys.stdin)
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".codemem-e2e" / "hooks"
    folder.mkdir(parents=True, exist_ok=True)
    sid = ev.get("session_id") or "nosession"
    sf = folder / f"{sid}.json"
    st = json.loads(sf.read_text(encoding="utf8")) if sf.exists() else {"greps": [], "repeats": 0, "row": 0, "noted": False, "reviewed": False}
    name, tool, inp = ev.get("hook_event_name"), ev.get("tool_name"), ev.get("tool_input") or {}
    out, logged = None, None

    if name == "PreToolUse" and tool == "Grep":
        alts = set(alternatives(inp.get("pattern")))
        overlap = max((len(alts & set(g)) / len(alts | set(g)) for g in st["greps"] if alts | set(g)), default=0)
        if overlap >= REPEAT_JACCARD:
            st["repeats"] += 1
            logged = {"event": "repeat", "pattern": inp.get("pattern"), "overlap": round(overlap, 2), "n": st["repeats"]}
            if st["repeats"] >= 2:
                logged["refused"] = True
                out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                       "permissionDecisionReason": (
                           f"This grep repeats an earlier one (its alternatives overlap an earlier grep's by {overlap:.0%}). "
                           "Do not grep again with small changes to the pattern. If you know the file or function, Read it; "
                           f"otherwise change direction with codemem's search_code: describe the code you are looking for.")}}

    elif name == "PostToolUse":
        if tool in ("Edit", "Write", "MultiEdit", SEARCH):
            st["row"], st["noted"] = 0, False
        elif tool == "Grep":  # a grep counts for repeats once it has run (a refused one, e.g. by PR #26's first-search hook, does not)
            st["greps"].append(alternatives(inp.get("pattern")))
            st["row"] += 1
            if st["row"] >= STUCK and not st["noted"]:
                st["noted"] = True
                logged = {"event": "stuck_note", "row": st["row"]}
                out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": (
                    f"{st['row']} greps in a row without an edit. If you still do not know where the code is, change "
                    "direction with codemem's search_code: describe what the code does, in the words source code would use.")}}

    elif name == "Stop" and not st["reviewed"]:
        cwd = ev.get("cwd") or os.getcwd()
        diff = subprocess.run(["git", "diff"], cwd=cwd, capture_output=True, text=True, encoding="utf8", errors="replace").stdout
        if diff.strip():
            st["reviewed"] = True
            logged = {"event": "review", "diff_chars": len(diff)}
            cut = diff if len(diff) <= DIFF_CHARS else diff[:DIFF_CHARS] + "\n[... diff cut]"
            out = {"decision": "block", "reason": (
                "Before you finish, review your change. Your edits so far:\n\n" + cut + "\n\n"
                "Check whether other code needs the same change or a matching one: callers of the code you changed, "
                "sibling code paths that handle the same case (another branch, another format, another method of the "
                "same class), and other files. Look at them if you have not, then edit them or, if the fix is complete, "
                "reply with your short summary.")}

    sf.write_text(json.dumps(st), encoding="utf8")
    if logged:
        with open(folder / f"{sid}.log.jsonl", "a", encoding="utf8") as f:
            f.write(json.dumps({"hook": name, "tool": tool, **logged}) + "\n")
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
