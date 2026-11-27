"""Hybrid v2 (arm hybrid_v2): grep, codemem search and open, chosen by Sonnet at each step, in ONE growing conversation.

Changes from e2e_hybrid.py (letters as in Track B's plan of 2026-11-27):
  F  One conversation, append-only: each step resumes the same Claude CLI session (`--resume`) and adds only that
     step's results, so earlier steps are prompt-cache reads, as in the grep agent. Prompt caching on. Because the
     code shown earlier stays in the conversation, picks are not resent (this replaces E: no resending at all) and
     there is no rebuilt earlier-steps JSON (Sonnet's own earlier answers are its notes).
  B  `open` replaces `read`: up to 3 targets per step, each a path with a line range, a path with a symbol (the
     smallest chunk with that name in that file), or an earlier result ("3.2"). Opened code joins the picks.
     `open` with no targets shows the picks again, from the current files.
  C  grep shows code: 5 lines on each side of each match, matches in the same function merged into one block (a
     numbered result). Over GREP_LINES matching lines: only the lines and a count per file, and a hint to narrow.
  A  Repeated greps: a grep is a repeat when half or more of its normalised alternatives (a|b|c, lowercased, escapes
     removed) match an earlier grep's (Jaccard >= 0.5), or when it finds no matching line not shown before. First
     repeat: it runs, shows only new lines, with a note to use open or codemem. Later repeats: grep is refused and
     the next answer's schema leaves grep out. After STUCK_GREPS greps in a row with no edit, the note says to switch
     to codemem. Every repeat is logged.
  D  The grep agent's stopping rule (as hybrid_done): an applied edit is followed by a review message (the git diff
     and the edited functions in full); the run ends when Sonnet says done (or edits with done = true), or at the cap.
  G  Tool guidance in system_hybrid_v2.txt: exact string -> grep; file or function known -> open; no clue or stuck ->
     codemem; after an edit, check callers and sibling code paths; edit as soon as the code in view confirms it.
Step 1 is the same call as in e2e_hybrid.py (system_hybrid_first.txt, answer cache shared), so the first tool and
query match the hybrid arms; the conversation starts with the issue and that step's results.

Usage: python e2e_hybrid2.py TASKS.jsonl TASK_ID REPO_COPY OUT_DIR   (LOOP_TAG default hybrid_v2)
"""
from __future__ import annotations

import collections as C
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from codemem.config import load_config
from codemem.render import format_results
from codemem.search import SearchResponse, _pick_top, make_card, rrf
from codemem.service import CodememService

os.environ.setdefault("LLM_NO_PROMPT_CACHE", "1")  # the step-1 call, as in e2e_hybrid.py (shares its answer cache)
import llm  # noqa: E402
from aug_retriever import LOOP_POOL, AugRetriever

llm._kind("hybrid_first", "system_hybrid_first.txt", "schema_hybrid_first.json")

MAX_STEPS = int(os.environ.get("HYBRID_MAX_STEPS", "15"))
MAX_COST = 3.0
KS = (3, 5, 10)
CODE_CAP = 20000  # one result or one opened target
STEP_CAP = 60000  # all of one step's results
MAX_PICKED = 8
GREP_LINES = 40
GREP_CONTEXT = 5
GREP_MERGE_GAP = 20  # matches in the same function closer than this many lines share one block
GREP_WINDOW = 25  # a grep match outside any function stands for this many lines on each side
STUCK_GREPS = 3
REPEAT_JACCARD = 0.5
DIFF_CAP = 20000
TAG = os.environ.get("LOOP_TAG", "hybrid_v2")
HERE = Path(__file__).resolve().parent
SYSTEM = (HERE / "system_hybrid_v2.txt").read_text(encoding="utf8")
SESSIONS = HERE / "out" / "hybrid_v2_sessions"  # the CLI keeps each run's conversation under this working folder

tasks_file, task_id, repo_arg, out_dir = sys.argv[1:5]
task = next(t for t in (json.loads(x) for x in Path(tasks_file).read_text(encoding="utf8").split("\n") if x.strip())
            if t["id"] == task_id)
repo = Path(repo_arg).resolve()
out = Path(out_dir).resolve()
out.mkdir(parents=True, exist_ok=True)
service = CodememService(repo, config=load_config(repo))
service.repo_root = repo
stats = service.update(full=False)
if service.last_error or stats is None:
    raise SystemExit(f"codemem update failed: {service.last_error}")
store = service.store
searcher = AugRetriever.__new__(AugRetriever)
searcher.config, searcher.mode, searcher.guess, searcher.suspects, searcher.max_rounds = service.config, "loop", False, False, MAX_STEPS


# ---------- the answer schema (grep can be left out after a refused repeat)
def schema(allow_grep: bool) -> str:
    s, a = {"type": "string"}, {"type": "array", "items": {"type": "string"}}
    edit = {"type": "object", "additionalProperties": False, "required": ["path", "old", "new"],
            "properties": {"path": s, "old": s, "new": s}}
    target = {"type": "object", "additionalProperties": False, "required": ["path", "lines", "symbol", "result"],
              "properties": {"path": s, "lines": s, "symbol": s, "result": s}}
    actions = ["edit", "open", "codemem", "grep", "done"] if allow_grep else ["edit", "open", "codemem", "done"]
    props = {"action": {"type": "string", "enum": actions}, "picks": {"type": "array", "items": {"type": "integer"}},
             "analysis": s, "done": {"type": "boolean"}, "edits": {"type": "array", "items": edit},
             "open_targets": {"type": "array", "items": target}, "query": s, "look_in": a,
             "next_k": {"type": "integer", "enum": list(KS)}, "grep_pattern": s, "grep_path": s,
             "grep_ignore_case": {"type": "boolean"}}
    return json.dumps({"type": "object", "additionalProperties": False, "required": list(props), "properties": props})


# ---------- the conversation
SESSION_ID = str(uuid.uuid4())
_started, _total = False, 0.0


def converse(text: str, allow_grep: bool = True) -> dict:
    """One step: resume this run's CLI session with `text` appended. Returns output, this call's cost and usage."""
    global _started, _total, SESSION_ID
    SESSIONS.mkdir(parents=True, exist_ok=True)
    last = ""
    for attempt in range(2):
        command = [str(llm.CLAUDE), "-p", "--model", llm.MODEL, "--effort", llm.EFFORT, "--output-format", "json",
                   "--json-schema", schema(allow_grep), "--tools", "", "--setting-sources", "", "--strict-mcp-config",
                   "--disable-slash-commands", "--system-prompt", SYSTEM] \
            + (["--resume", SESSION_ID] if _started else ["--session-id", SESSION_ID])
        done = subprocess.run(command, input=text, capture_output=True, text=True, encoding="utf8", errors="replace",
                              cwd=SESSIONS, timeout=600, env=os.environ.copy())
        try:
            reply = json.loads(done.stdout)
        except json.JSONDecodeError:
            last = f"exit {done.returncode}, not JSON: {(done.stderr or done.stdout)[:300]}"
            continue
        if reply.get("session_id") == SESSION_ID:
            _started = True
        total = reply.get("total_cost_usd") or 0.0  # cumulative over the session
        call_cost, _total = max(total - _total, 0.0), max(total, _total)
        used = reply.get("modelUsage") or {}
        if done.returncode == 0 and not reply.get("is_error") and isinstance(reply.get("structured_output"), dict):
            if set(used) - {llm.MODEL}:
                raise llm.LLMError(f"answered by {sorted(used)}")
            return {"output": reply["structured_output"], "cost_usd": call_cost, "usage": reply.get("usage") or {}}
        last = f"exit {done.returncode}, error {reply.get('is_error')}, subtype {reply.get('subtype')}"
        if _started:
            text = "Your last answer did not come through. Answer the previous message again, in the required format."
        else:
            SESSION_ID = str(uuid.uuid4())
    raise llm.LLMError(f"hybrid_v2 step: no valid answer ({last})")


# ---------- helpers
def k_of(value) -> int:
    return value if value in KS else 10


def norm_path(text: str) -> str:
    return (text or "").strip().strip("`'\"").replace("\\", "/").removeprefix("./").strip("/")


def file_lines(path: str) -> list[str]:
    p = repo / path
    return p.read_text(encoding="utf8", errors="replace").splitlines() if p.is_file() else []


def span_of(item) -> tuple[str, int, int, str]:
    if item[0] == "chunk":
        c = store.get_chunks([item[1]]).get(item[1])
        return (c.path, c.start_line, c.end_line, c.qualname) if c else ("", 0, 0, "")
    return item[1], item[2], item[3], item[4] if len(item) > 4 else "lines"


def show_item(item) -> tuple[str, str]:
    """An item's current code from disk, with a header; and its 'path lines a-b' for scoring."""
    path, a, b, label = span_of(item)
    lines = file_lines(path)
    if not path or not lines:
        return "", ""
    b = min(b, len(lines))
    code = "\n".join(lines[a - 1:b])
    if len(code) > CODE_CAP:
        code = code[:CODE_CAP] + f"\n[... cut at {CODE_CAP} characters]"
    return f"=== {path} lines {a}-{b} ({label})\n{code}", f"{path} lines {a}-{b}"


def enclosing(path: str, a: int, b: int | None = None):
    b = a if b is None else b
    return store.conn.execute("SELECT chunk_id, qualname, start_line, end_line FROM chunks WHERE path=? AND start_line<=? "
                              "AND end_line>=? ORDER BY end_line - start_line LIMIT 1", (path, a, b)).fetchone()


def show_cards(cards, step_no: int) -> tuple[str, list[bool]]:
    chunks = store.get_chunks([c.chunk_id for c in cards])
    parts, whole = [], []
    for i, card in enumerate(cards, start=1):
        text = format_results(SearchResponse("", ["llm"], [card]))
        head = (f"{step_no}.{i}." + text[2:] if text.startswith("1.") else text).split("\n", 1)[0]
        chunk = chunks.get(card.chunk_id)
        code = chunk.code if chunk else ""
        ok = len(code) <= CODE_CAP
        if not ok:
            code = ("[class too long to show whole: its skeleton]\n" + chunk.skeleton[:CODE_CAP]) if chunk.kind == "class" \
                and chunk.skeleton else code[:CODE_CAP] + f"\n[... cut at {CODE_CAP} characters]"
        parts.append(head + "\n" + code)
        whole.append(ok)
    return "\n\n".join(parts), whole


def free_fused(query: dict) -> list[tuple[int, float]]:
    text = query["query"]
    ranked = {f"q_{s}": searcher._ranked(store, text, s, LOOP_POOL) for s in ("code", "usage", "bm25")}
    for i, prefix in enumerate(query["look_in"]):
        ranked[f"in{i}_bm25"] = searcher._ranked(store, text, "bm25", path_prefix=prefix)
        ranked[f"in{i}_code"] = searcher._ranked(store, text, "code", path_prefix=prefix)
    return rrf(ranked, k=service.config.rrf_k)


# ---------- grep (C) and repeat detection (A)
def alternatives(pattern: str) -> set[str]:
    parts = re.split(r"(?<!\\)\|", pattern)
    return {re.sub(r"[\\()^$]", "", p).strip().lower() for p in parts if p.strip()}


def run_grep(pattern: str, path: str, ignore_case: bool, step_no: int, only_new: set | None = None):
    """Matches with code around them, merged per function. Returns text, items (one per block), all hit keys, meta."""
    meta = {"pattern": pattern, "path": path, "ignore_case": ignore_case}
    if not pattern:
        return "[grep: empty pattern]", [], set(), meta | {"matches": 0}
    if path and not (repo / path).exists():
        return f"[grep: no file or folder {path}]", [], set(), meta | {"matches": 0}
    cmd = ["git", "-c", "core.quotepath=off", "grep", "-n", "-I", "--no-color", "-E"] + (["-i"] if ignore_case else []) \
        + ["-e", pattern, "--"] + ([path] if path else [])
    r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, encoding="utf8", errors="replace", timeout=180)
    if r.returncode > 1:
        return f"[grep error: {r.stderr.strip()[:300]}]", [], set(), meta | {"matches": 0, "error": True}
    hits = [(m[1], int(m[2])) for m in (re.match(r"^(.+?):(\d+):", x) for x in r.stdout.splitlines()) if m]
    keys = {f"{p}:{n}" for p, n in hits}
    if only_new is not None:
        hits = [(p, n) for p, n in hits if f"{p}:{n}" not in only_new]
    per_file = C.Counter(p for p, _ in hits)
    meta |= {"matches": len(hits), "files": len(per_file)}
    if not hits:
        return (f"[grep: no {'new ' if only_new is not None else ''}matches for {pattern!r}" + (f" in {path}" if path else "")
                + "]"), [], keys, meta
    if len(hits) > GREP_LINES:  # too many: lines only, and a count per file
        texts = {(m[1], int(m[2])): m[3].strip()[:200] for m in (re.match(r"^(.+?):(\d+):(.*)$", x) for x in r.stdout.splitlines()) if m}
        shown = [f"{p}:{n}  {texts.get((p, n), '')}" for p, n in hits[:GREP_LINES]]
        counts = ", ".join(f"{p} ({n})" for p, n in per_file.most_common(30))
        meta["cut"] = True
        return (f"{len(hits)} matching lines in {len(per_file)} files: too many to show with code. Narrow the path or "
                f"the pattern. The first {GREP_LINES} lines:\n" + "\n".join(shown) + f"\nmatches per file: {counts}"), [], keys, meta
    blocks = []  # (path, a, b, chunk row, hit lines)
    for p, n in hits:
        row = enclosing(p, n)
        a, b = max(1, n - GREP_CONTEXT), n + GREP_CONTEXT
        last = blocks[-1] if blocks else None
        if last and last[0] == p and ((row and last[3] and row[0] == last[3][0] and n - last[2] <= GREP_MERGE_GAP) or a <= last[2] + 1):
            blocks[-1] = (p, last[1], max(last[2], b), last[3], last[4] + [n])
        else:
            blocks.append((p, a, b, row, [n]))
    parts, items, where, size = [], [], [], 0
    for i, (p, a, b, row, ns) in enumerate(blocks, start=1):
        lines = file_lines(p)
        b = min(b, len(lines))
        body = "\n".join(f"{'>' if k in ns else ' '}{k:6d}  {lines[k - 1]}" for k in range(a, b + 1))
        part = f"{step_no}.{i}. {p} lines {a}-{b} ({'in ' + row[1] if row else 'not in a function'}; match on line{'s' if len(ns) > 1 else ''} {', '.join(map(str, ns))})\n{body}"
        if size + len(part) > STEP_CAP:
            parts.append(f"[... {len(blocks) - i + 1} more blocks cut]")
            break
        parts.append(part)
        size += len(part)
        items.append(("chunk", row[0]) if row else ("span", p, max(1, ns[0] - GREP_WINDOW), ns[-1] + GREP_WINDOW, "lines around a grep match"))
        where += [f"{p}:{k}" for k in ns]
        meta.setdefault("blocks_shown", []).append(f"{p} lines {a}-{b}")
    meta["shown_lines"] = where
    return f"{len(hits)} matching lines in {len(per_file)} files, in {len(blocks)} blocks\n\n" + "\n\n".join(parts), items, keys, meta


# ---------- open (B)
def resolve(target: dict, results_by_step: dict) -> tuple | str:
    ref = (target.get("result") or "").strip()
    if ref:
        m = re.match(r"^(\d+)\.(\d+)$", ref)
        if not m or int(m[1]) not in results_by_step or not 1 <= int(m[2]) <= len(results_by_step[int(m[1])]):
            return f"no result {ref}"
        return results_by_step[int(m[1])][int(m[2]) - 1]
    path = norm_path(target.get("path"))
    if not path or not (repo / path).is_file():
        return f"no file {target.get('path')!r}"
    symbol = (target.get("symbol") or "").strip()
    if symbol:
        name = symbol.split(".")[-1].split("::")[-1]
        rows = store.conn.execute("SELECT chunk_id, qualname, start_line, end_line FROM chunks WHERE path=?", (path,)).fetchall()
        hit = [r for r in rows if r[1] == symbol or r[1].split(".")[-1].split("::")[-1] == name]
        if not hit:
            return f"no symbol {symbol!r} in {path}"
        return ("chunk", min(hit, key=lambda r: r[3] - r[2])[0])
    m = re.match(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$", target.get("lines") or "")
    if not m:
        return f"give lines (for example 120-180) or a symbol for {path}"
    a = int(m[1])
    b = int(m[2]) if m[2] else a + 40
    return ("span", path, max(1, a), max(a, b), "opened lines")


# ---------- edits (D)
def apply(edits: list[dict]) -> tuple[bool, str]:
    planned: dict[Path, str] = {}
    for e in edits:
        path = repo / norm_path(e["path"])
        if not path.is_file():
            return False, f"no file {e['path']}"
        text = planned.get(path) or path.open(encoding="utf8", newline="").read()
        crlf = "\r\n" in text
        old, new = (e["old"].replace("\r\n", "\n").replace("\n", "\r\n"), e["new"].replace("\r\n", "\n").replace("\n", "\r\n")) \
            if crlf else (e["old"], e["new"])
        if text.count(old) != 1:
            return False, f"the old text occurs {text.count(old)} times in {e['path']}"
        planned[path] = text.replace(old, new)
    for path, text in planned.items():
        with path.open("w", encoding="utf8", newline="") as f:
            f.write(text)
    return True, ""


def edited_items() -> list[tuple]:
    service.update(full=False)
    diff = subprocess.run(["git", "diff", "-U0"], cwd=repo, capture_output=True, text=True, encoding="utf8").stdout
    items, path = [], None
    for line in diff.split("\n"):
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
        if m and path:
            a = int(m[1])
            b = a + max(int(m[2] if m[2] is not None else 1), 1) - 1
            row = enclosing(path, a, b)
            item = ("chunk", row[0]) if row else ("span", path, max(1, a - GREP_WINDOW), b + GREP_WINDOW, "edited lines")
            if item not in items:
                items.append(item)
    return items


def show_items(items) -> tuple[str, list[str]]:
    parts, spans = [], []
    for it in items[:MAX_PICKED]:
        text, span = show_item(it)
        if text and span not in spans:
            parts.append(text)
            spans.append(span)
    return "\n\n".join(parts), spans


# ---------- the run
start = time.time()
first_record = llm.extract("hybrid_first", llm.oneshot_input(task["repo"], task["query"]))
cost = first_record.get("cost_usd") or 0.0
fo = first_record["output"]
first = llm.clean(fo, task["query"])
if fo["tool"] == "grep":
    step = {"tool": "grep", "input": {"pattern": fo.get("grep_pattern") or "", "path": norm_path(fo.get("grep_path")),
                                     "ignore_case": bool(fo.get("grep_ignore_case"))}}
    first_line = f"Step 1 (chosen from the issue): grep for {step['input']['pattern']!r}" + (f" in {step['input']['path']}" if step['input']['path'] else "")
else:
    step = {"tool": "codemem", "k": k_of(fo.get("k")), "input": {k: first[k] for k in ("intent", "symptom", "anchors")}}
    first_line = f"Step 1 (chosen from the issue): codemem search for: {first['intent']}"

history, seen, picks, results_by_step = [], set(), [], {}
grep_alts, grep_keys_seen, repeats, greps_in_row = [], set(), [], 0
tools, fixed, allow_grep, retry = C.Counter(), None, True, False
for step_no in range(1, MAX_STEPS + 1):
    h = {"step": step_no, **step}
    tools[h["tool"]] += 1
    allow_grep = True
    items, note = [], ""
    if h["tool"] == "codemem":
        if step_no == 1:
            cards, _ = searcher._retrieve(store, task["query"], first, False, h["k"])
        else:
            fresh = _pick_top([x for x in free_fused(h["input"]) if x[0] not in seen], h["k"], store.get_chunks)
            cards = [make_card(chunk, score, service.config) for chunk, score in fresh]
        body, whole = show_cards(cards, step_no) if cards else ("[codemem found no results not shown before]", [])
        seen.update(c.chunk_id for c in cards)
        items = [("chunk", c.chunk_id) for c in cards]
        h.update(shown=[[c.path, c.start_line, c.end_line] for c in cards], shown_whole=whole)
        greps_in_row = 0
    elif h["tool"] == "grep":
        alts = alternatives(h["input"]["pattern"])
        earlier = max((len(alts & x) / len(alts | x) for x in grep_alts if alts | x), default=0.0)
        _, _, keys, _ = run_grep(**h["input"], step_no=step_no, only_new=set()) if grep_alts else ("", [], set(), {})
        no_new = bool(grep_alts) and not (keys - grep_keys_seen)
        is_repeat = bool(grep_alts) and (earlier >= REPEAT_JACCARD or no_new)
        if is_repeat:
            repeats.append({"step": step_no, "pattern": h["input"]["pattern"], "jaccard": round(earlier, 2), "no_new_lines": no_new})
        if is_repeat and len(repeats) >= 2:
            body = ("[grep refused: this grep repeats earlier ones (" + ("no new matching lines" if no_new else f"its alternatives overlap an earlier grep's by {earlier:.0%}")
                    + "). Use open if you know the file or function, codemem if you do not know where to look, or edit.]")
            h.update(matches=0, refused=True)
            allow_grep = False
        else:
            body, items, keys, meta = run_grep(**h["input"], step_no=step_no, only_new=grep_keys_seen if is_repeat else None)
            grep_keys_seen |= keys
            h.update(matches=meta["matches"], grep_shown=meta.get("shown_lines", []), picked_shown=meta.get("blocks_shown", []),
                     cut=meta.get("cut", False))
            if is_repeat:
                note = (f"\n\n[note: this grep repeats an earlier one; only its new lines are shown. If you know the file or "
                        f"function, use open; if you do not know where to look, use codemem.]")
        grep_alts.append(alts)
        greps_in_row += 1
        if greps_in_row >= STUCK_GREPS and not note:
            note = (f"\n\n[note: {greps_in_row} greps in a row without an edit. If they have not found the code to "
                    f"change, switch to codemem with a new query.]")
    elif h["tool"] == "open":
        targets = h["input"]["targets"]
        if not targets:
            body, spans = show_items(picks)
            body = body or "[no picks yet]"
            h["picked_shown"] = spans
        else:
            parts, spans = [], []
            for t in targets[:3]:
                it = resolve(t, results_by_step)
                if isinstance(it, str):
                    parts.append(f"[open: {it}]")
                    continue
                text, span = show_item(it)
                parts.append(text or f"[open: nothing to show for {t}]")
                if span:
                    spans.append(span)
                    picks = [it] + [x for x in picks if x != it]
                    items.append(it)
            body = "\n\n".join(parts)
            h["picked_shown"] = spans
        greps_in_row = 0
    else:  # review after an applied edit, or a retry after an edit that did not apply
        edited = edited_items() if h["tool"] == "review" else [x for x in picks if span_of(x)[0] in h["input"].get("paths", [])]
        if h["tool"] == "review":
            picks = edited + [x for x in picks if x not in edited]
        code, spans = show_items(edited)
        diff = subprocess.run(["git", "diff"], cwd=repo, capture_output=True, text=True, encoding="utf8").stdout
        diff = diff[:DIFF_CAP] + (f"\n[... diff cut at {DIFF_CAP} characters]" if len(diff) > DIFF_CAP else "")
        body = ((f"Your edits so far, as a diff against the original code:\n{diff}\n\nThe edited functions now:\n{code}")
                if h["tool"] == "review" else
                (f"Your last edit did not apply: {h['input']['why']}. The current code of the files you tried to edit:\n{code}"
                 + (f"\n\nYour edits that did apply so far:\n{diff}" if diff else "")))
        h["picked_shown"] = spans
        greps_in_row = 0
    results_by_step[step_no] = items
    if len(body) > STEP_CAP:
        body = body[:STEP_CAP] + f"\n[... results cut at {STEP_CAP} characters]"
    message = ((f"Repository: {task['repo']}\n\n<issue>\n{task['query']}\n</issue>\n\n{first_line}\n\n") if step_no == 1 else "") \
        + f"<results step=\"{step_no}\" tool=\"{h['tool']}\">\n{body}\n</results>{note}"
    record = converse(message, allow_grep)
    cost += record["cost_usd"]
    u = record["usage"]
    h.update(call_cost=round(record["cost_usd"], 5), tokens={k: u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                                                      "cache_read_input_tokens", "output_tokens")})
    o = record["output"]
    analysis = (o.get("analysis") or "").strip()
    new_picks = [items[p - 1] for p in dict.fromkeys(o.get("picks") or []) if isinstance(p, int) and 1 <= p <= len(items)]
    picks = new_picks + [x for x in picks if x not in new_picks]
    h.update(action=o["action"], analysis=analysis, picked=[f"{span_of(x)[0]}:{span_of(x)[3]}" for x in new_picks])
    history.append(h)
    if o["action"] == "done" or cost > MAX_COST:
        break
    if o["action"] == "edit":
        ok, why = apply(o["edits"]) if o["edits"] else (False, "no edits given")
        if ok:
            h["edit_attempt"] = "applied"
            fixed = fixed or {"edits": 0, "edit_steps": []}
            fixed["edits"] += len(o["edits"])
            fixed["edit_steps"].append(step_no)
            if o.get("done"):
                h["done"] = True
                break
            step = {"tool": "review", "input": {}}
        else:
            h["edit_attempt"] = f"did not apply: {why}"
            step = {"tool": "retry", "input": {"why": why, "paths": sorted({norm_path(e["path"]) for e in o["edits"]})}}
        continue
    if o["action"] == "grep":
        step = {"tool": "grep", "input": {"pattern": o.get("grep_pattern") or "", "path": norm_path(o.get("grep_path")),
                                         "ignore_case": bool(o.get("grep_ignore_case"))}}
    elif o["action"] == "open":
        step = {"tool": "open", "input": {"targets": (o.get("open_targets") or [])[:3]}}
    else:
        look_in = list(dict.fromkeys(x.strip() for x in o.get("look_in") or [] if isinstance(x, str) and x.strip()))[:3]
        step = {"tool": "codemem", "k": k_of(o.get("next_k")),
                "input": {"query": (o.get("query") or "").strip() or analysis,
                          "look_in": [p for p in (searcher._prefix(store, x) for x in look_in) if p]}}

service.close()
patch = subprocess.run(["git", "diff"], cwd=repo, capture_output=True, text=True, encoding="utf8").stdout
(out / f"{TAG}.diff").write_text(patch, encoding="utf8")
tok = C.Counter()
for h in history:
    tok.update(h.get("tokens", {}))
summary = {"arm": "hybrid-v2", "session_id": SESSION_ID, "task": task_id, "fixed": fixed, "rounds": len(history), "tools": dict(tools),
           "repeats": repeats, "ks": [h["k"] for h in history if h["tool"] == "codemem"], "sonnet_calls": len(history) + 1,
           "cost_usd": round(cost, 4), "first_call_cost_usd": first_record.get("cost_usd"), "tokens": dict(tok),
           "seconds": round(time.time() - start),
           "diff_stat": subprocess.run(["git", "diff", "--stat"], cwd=repo, capture_output=True, text=True).stdout.strip(),
           "history": history}
(out / f"{TAG}.summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf8")
print(json.dumps({k: v for k, v in summary.items() if k != "history"}, indent=1))
for h in history:
    print(f"step {h['step']}: {h['tool']} {json.dumps(h['input'], ensure_ascii=False)[:150]} -> {h.get('action')} "
          f"${h.get('call_cost')} cache read {h.get('tokens', {}).get('cache_read_input_tokens')} {h.get('edit_attempt', '')}")
