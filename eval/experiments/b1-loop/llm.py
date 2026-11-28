"""Sonnet 5.5 query extraction through the signed-in Claude CLI, with every answer cached on disk.

The CLI runs with no tools, no settings, no MCP servers, and an empty working folder. A cached
answer is keyed by the frozen prompts, model, effort, and exact input, so reruns make no calls.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
CLAUDE = Path.home() / ".local" / "bin" / "claude.exe"
MODEL = "claude-sonnet-5-5"
EFFORT = "medium"
SYSTEM = {"oneshot": (HERE / "system_oneshot.txt").read_text(encoding="utf8"),
          "revise": (HERE / "system_revise.txt").read_text(encoding="utf8")}
SCHEMA = (HERE / "schema.json").read_text(encoding="utf8")
PROMPT_SHA = hashlib.sha256(json.dumps([SYSTEM, SCHEMA, MODEL, EFFORT], sort_keys=True).encode("utf8")).hexdigest()
CACHE = HERE / "out" / "cache" / PROMPT_SHA[:12]
# v2 one-shot (diagnosis + suspects): its own prompt, schema, hash and cache, so the v1 cache stays valid.
SYSTEM_V2 = (HERE / "system_oneshot_v2.txt").read_text(encoding="utf8")
SCHEMA_V2 = (HERE / "schema_v2.json").read_text(encoding="utf8")
PROMPT_SHA_V2 = hashlib.sha256(json.dumps([SYSTEM_V2, SCHEMA_V2, MODEL, EFFORT], sort_keys=True).encode("utf8")).hexdigest()
CACHE_V2 = HERE / "out" / "cache" / ("v2-" + PROMPT_SHA_V2[:12])
# Search loop (codemem in place of grep): its own prompt, schema, hash and cache.
SYSTEM_LOOP = (HERE / "system_loop.txt").read_text(encoding="utf8")
SCHEMA_LOOP = (HERE / "schema_loop.json").read_text(encoding="utf8")
PROMPT_SHA_LOOP = hashlib.sha256(json.dumps([SYSTEM_LOOP, SCHEMA_LOOP, MODEL, EFFORT], sort_keys=True).encode("utf8")).hexdigest()
CACHE_LOOP = HERE / "out" / "cache" / ("loop-" + PROMPT_SHA_LOOP[:12])
# Fix step of the end-to-end loop.
SYSTEM_FIX = (HERE / "system_fix.txt").read_text(encoding="utf8")
SCHEMA_FIX = (HERE / "schema_fix.json").read_text(encoding="utf8")
PROMPT_SHA_FIX = hashlib.sha256(json.dumps([SYSTEM_FIX, SCHEMA_FIX, MODEL, EFFORT], sort_keys=True).encode("utf8")).hexdigest()
CACHE_FIX = HERE / "out" / "cache" / ("fix-" + PROMPT_SHA_FIX[:12])
PROMPTS = {"oneshot": (SYSTEM["oneshot"], SCHEMA, PROMPT_SHA, CACHE), "revise": (SYSTEM["revise"], SCHEMA, PROMPT_SHA, CACHE),
           "oneshot_v2": (SYSTEM_V2, SCHEMA_V2, PROMPT_SHA_V2, CACHE_V2),
           "loop": (SYSTEM_LOOP, SCHEMA_LOOP, PROMPT_SHA_LOOP, CACHE_LOOP),
           "fix": (SYSTEM_FIX, SCHEMA_FIX, PROMPT_SHA_FIX, CACHE_FIX),
           # same prompt as "loop", but the judge sees each result's full code: its own cache folder
           "loop_full": (SYSTEM_LOOP, SCHEMA_LOOP, PROMPT_SHA_LOOP, HERE / "out" / "cache" / ("loopfull-" + PROMPT_SHA_LOOP[:12]))}


def _kind(name: str, system_file: str, schema_file: str) -> None:
    """Register a prompt kind with its own hash and cache folder."""
    system, schema = (HERE / system_file).read_text(encoding="utf8"), (HERE / schema_file).read_text(encoding="utf8")
    sha = hashlib.sha256(json.dumps([system, schema, MODEL, EFFORT], sort_keys=True).encode("utf8")).hexdigest()
    PROMPTS[name] = (system, schema, sha, HERE / "out" / "cache" / f"{name}-{sha[:12]}")


# loop-k: the first query also picks k (results shown), and each round is one call that edits or searches again
_kind("oneshot_k", "system_oneshot_k.txt", "schema_oneshot_k.json")
_kind("loopk", "system_loopk.txt", "schema_loopk.json")
# loop-k with a separate judge and fix call: the judge prompt of the full-code loop plus next_k
_kind("loop_full_k", "system_loop_k.txt", "schema_loop_k.json")
MAX_SUSPECTS = 5
MAX_LOOK_IN = 3
MAX_ANCHORS = 20
MAX_GUESSES = 5
_empty = Path(tempfile.gettempdir()) / "codemem-llm-empty"
# LLM_NO_PROMPT_CACHE=1: the CLI sends no cache markers (DISABLE_PROMPT_CACHING), so the input is billed at the plain
# input rate instead of the cache-write rate. Each call is a new conversation, so nothing it caches is read again.
NO_PROMPT_CACHE = os.environ.get("LLM_NO_PROMPT_CACHE") == "1"


def _cli_env() -> dict:
    env = os.environ.copy()
    if NO_PROMPT_CACHE:
        env["DISABLE_PROMPT_CACHING"] = "1"
    return env
_lock = threading.Lock()


class LLMError(RuntimeError):
    pass


def oneshot_input(repo: str, issue: str) -> str:
    return f"Repository: {repo}\n\n<issue>\n{issue}\n</issue>"


def revise_input(repo: str, issue: str, first: dict, cards: str) -> str:
    fields = {k: first[k] for k in ("intent", "symptom", "anchors", "stated_location", "guessed_location")}
    return (f"Repository: {repo}\n\n<issue>\n{issue}\n</issue>\n\n"
            f"<first_extraction>\n{json.dumps(fields, ensure_ascii=False, indent=1)}\n</first_extraction>\n\n"
            f"<search_results>\n{cards}\n</search_results>")


def loop_input(repo: str, issue: str, history: list[dict], round_no: int, cards: str) -> str:
    """One round of the search loop: the issue, earlier queries with their notes and picks, and the new results."""
    past = []
    for h in history:
        query = {k: h["query"][k] for k in ("intent", "symptom", "anchors", "look_in") if k in h["query"]}
        entry = {"round": h["round"], "query": query}
        if "analysis" in h:
            entry["your_notes"] = h["analysis"]
            entry["your_picks"] = h["picked"]
        if "fix_attempt" in h:  # end-to-end loop only: why the picked code could not be fixed
            entry["fix_attempt"] = h["fix_attempt"]
        past.append(entry)
    return (f"Repository: {repo}\n\n<issue>\n{issue}\n</issue>\n\n"
            f"<earlier_rounds>\n{json.dumps(past, ensure_ascii=False, indent=1)}\n</earlier_rounds>\n\n"
            f"<search_results round=\"{round_no}\">\n{cards}\n</search_results>")


def clean_loop(output: dict, issue: str, seen_text: str, shown: int) -> dict:
    """Anchors must appear verbatim in the issue or a result already shown; picks must be shown result numbers."""
    def unique(values):
        return list(dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip()))

    source = issue + "\n" + seen_text
    anchors = unique(output["anchors"])
    kept = [a for a in anchors if a in source][:MAX_ANCHORS]
    picks = list(dict.fromkeys(p for p in output["picks"] if isinstance(p, int) and 1 <= p <= shown))
    return {"found": bool(output["found"]), "picks": picks, "analysis": output["analysis"].strip(),
            "intent": output["intent"].strip(), "symptom": output["symptom"].strip(), "anchors": kept,
            "look_in": unique(output["look_in"])[:MAX_LOOK_IN], "guessed_location": unique(output["guessed_location"])[:MAX_GUESSES],
            "dropped_anchors": len(anchors) - len(kept), "dropped_picks": len(output["picks"]) - len(picks)}


def loopk_input(repo: str, issue: str, history: list[dict], round_no: int, picked_code: str, cards: str) -> str:
    """One loop-k round: the issue, earlier queries with notes and edit attempts, earlier picks' code, new results."""
    past = []
    for h in history:
        entry = {"round": h["round"], "query": {k: h["query"][k] for k in ("intent", "symptom", "anchors", "look_in") if k in h["query"]},
                 "k": h["k"]}
        for key, name in (("analysis", "your_notes"), ("picked", "your_picks"), ("edit_attempt", "edit_attempt")):
            if key in h:
                entry[name] = h[key]
        past.append(entry)
    return (f"Repository: {repo}\n\n<issue>\n{issue}\n</issue>\n\n"
            f"<earlier_rounds>\n{json.dumps(past, ensure_ascii=False, indent=1)}\n</earlier_rounds>\n\n"
            f"<picked_earlier>\n{picked_code}\n</picked_earlier>\n\n"
            f"<search_results round=\"{round_no}\">\n{cards}\n</search_results>")


def fix_input(repo: str, issue: str, history: list[dict], code: str) -> str:
    notes = [{"round": h["round"], "notes": h.get("analysis", ""), **({"fix_attempt": h["fix_attempt"]} if "fix_attempt" in h else {})}
             for h in history]
    return (f"Repository: {repo}\n\n<issue>\n{issue}\n</issue>\n\n"
            f"<search_notes>\n{json.dumps(notes, ensure_ascii=False, indent=1)}\n</search_notes>\n\n"
            f"<code>\n{code}\n</code>")


def _call(kind: str, text: str) -> dict:
    _empty.mkdir(exist_ok=True)
    system, schema = PROMPTS[kind][:2]
    command = [str(CLAUDE), "-p", "--model", MODEL, "--effort", EFFORT, "--output-format", "json",
               "--json-schema", schema, "--tools", "", "--no-session-persistence", "--setting-sources", "",
               "--strict-mcp-config", "--disable-slash-commands", "--system-prompt", system]
    last = ""
    for attempt in range(3):
        done = subprocess.run(command, input=text, capture_output=True, text=True, encoding="utf8",
                              errors="replace", cwd=_empty, timeout=420, env=_cli_env())
        try:
            reply = json.loads(done.stdout)
            if done.returncode == 0 and not reply.get("is_error") and isinstance(reply.get("structured_output"), dict):
                used = reply.get("modelUsage") or {}
                if set(used) != {MODEL}:
                    raise LLMError(f"answered by {sorted(used)}, not {MODEL}")
                return {"output": reply["structured_output"], "models": sorted(used),
                        "cost_usd": reply.get("total_cost_usd"), "stop_reason": reply.get("stop_reason"),
                        "usage": reply.get("usage"), "duration_ms": reply.get("duration_ms")}
            last = f"exit {done.returncode}, stop {reply.get('stop_reason')}, error {reply.get('is_error')}, subtype {reply.get('subtype')}"
            (HERE / "out" / "last_error.json").write_text(json.dumps({"kind": kind, "reply": reply, "stderr": done.stderr[-2000:],
                                                                       "input": text}, ensure_ascii=False, indent=1), encoding="utf8")
        except json.JSONDecodeError:
            last = f"exit {done.returncode}, not JSON: {(done.stderr or done.stdout)[:300]}"
        time.sleep(5 * (attempt + 1))
    raise LLMError(f"{kind}: no valid answer after 3 tries ({last})")


def extract(kind: str, text: str) -> dict:
    """The cached answer for this exact input, or a new call. Returns the raw record."""
    key = hashlib.sha256(f"{kind}\0{text}".encode("utf8")).hexdigest()
    _, _, prompt_sha, cache = PROMPTS[kind]
    if NO_PROMPT_CACHE:  # answers made without prompt caching are kept apart, so a rerun really calls the model
        cache = cache.with_name(cache.name + "-nocache")
    path = cache / f"{kind}-{key[:24]}.json"
    if path.exists():
        record = json.loads(path.read_text(encoding="utf8"))
        _log(kind, text, record, cached=True)
        return record
    if os.environ.get("LLM_CACHE_ONLY") == "1":
        raise LLMError(f"{kind}: not in the cache and LLM_CACHE_ONLY=1")
    record = {"kind": kind, "prompt_sha": prompt_sha, "model": MODEL, "effort": EFFORT, "input_sha": key, **_call(kind, text)}
    with _lock:
        cache.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf8")
        os.replace(temp, path)
    _log(kind, text, record, cached=False)
    return record


def _log(kind: str, text: str, record: dict, cached: bool) -> None:
    """LLM_LOG=path: one JSON line per call with the sizes of what was sent and returned."""
    if not os.environ.get("LLM_LOG"):
        return
    system, schema = PROMPTS[kind][:2]
    line = {"kind": kind, "cached": cached, "input_chars": len(text), "system_chars": len(system),
            "schema_chars": len(schema), "output_chars": len(json.dumps(record["output"], ensure_ascii=False)),
            "cost_usd": record.get("cost_usd"), "usage": record.get("usage")}
    if os.environ.get("LLM_LOG_TEXT") == "1":
        line["text"] = text
    with _lock, open(os.environ["LLM_LOG"], "a", encoding="utf8") as f:
        f.write(json.dumps(line) + "\n")


def clean(output: dict, issue: str, cards: str = "") -> dict:
    """Keep anchors found verbatim in the issue (or shown cards) and locations found in the issue."""
    def unique(values):
        return list(dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip()))

    source = issue + "\n" + cards
    anchors = unique(output["anchors"])
    kept = [a for a in anchors if a in source][:MAX_ANCHORS]
    stated = unique(output["stated_location"])
    stated_kept = [s for s in stated if s in issue]
    out = {"intent": output["intent"].strip(), "symptom": output["symptom"].strip(), "anchors": kept,
           "stated_location": stated_kept, "guessed_location": unique(output["guessed_location"])[:MAX_GUESSES],
           "dropped_anchors": len(anchors) - len(kept), "dropped_stated": len(stated) - len(stated_kept)}
    if "diagnosis" in output:  # v2 only; suspects are Sonnet's own words, so no verbatim check
        out["diagnosis"] = output["diagnosis"].strip()
        out["suspects"] = unique(output["suspects"])[:MAX_SUSPECTS]
    return out
