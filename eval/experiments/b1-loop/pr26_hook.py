"""PR #26's `codemem hook` (first-search refusal, lost-trail reminder; pr26/hook.py from main, unchanged), run for the
mcp arm. Its answers are passed through as they are and also appended to LOG_FILE, one JSON line each.

Usage (settings.json hook command): python pr26_hook.py LOG_FILE
"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr26.hook import run  # noqa: E402

event_text = sys.stdin.read()
out = io.StringIO()
rc = run(io.StringIO(event_text), out)
if out.getvalue().strip():
    try:
        ev = json.loads(event_text)
    except ValueError:
        ev = {}
    with open(sys.argv[1], "a", encoding="utf8") as f:
        f.write(json.dumps({"hook": ev.get("hook_event_name"), "tool": ev.get("tool_name"),
                            "answer": json.loads(out.getvalue())["hookSpecificOutput"]}) + "\n")
sys.stdout.write(out.getvalue())
sys.exit(rc)
