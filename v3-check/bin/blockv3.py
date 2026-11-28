"""The v3-against-v2 check (brief .cache/review/briefs/v3-against-v2.md): Claude Code sessions in compare.py's harness
as it is (its gates, recording proxy, watchdog, discards and scoring), with five arms:
  grep      the agent's own tools only
  v2-tool   codemem 463171c as the MCP tool (.cache/wt/compare-main)
  v3-tool   PR #85 at 4902671 as the MCP tool (.cache/wt/compare-pr85)
  v2        v2-tool plus the 20 lines at the top of the first message (v3/upfront-463171c, made at 463171c)
  v3        v3-tool plus the same 20 lines
What this script adds, none of it a gate made weaker: the four arms in compare.ARMS; the vLLM tasks in the task and
prompt tables (v3lib.all_tasks; each has its own clone of the checkout with an empty .git marker, and of the real
index); "Agent Instructions for vLLM" in compare.FOREIGN; this block's own cap (340 sessions, discards included) in
place of compare's old global one; no new session at or after 07:00 UTC on Nov 28, with less than 6 GB free, or after
a session whose subscription status was not "allowed" (stricter than the watchdog, which lets "allowed_warning" pass);
a stop when any request body of a session carries an agent file that Claude Code loaded by itself.

usage: blockv3.py run <stage> [<stage> ...]    s1 Haiku pandas; s2 vLLM, Haiku then Sonnet; s3 Sonnet pandas;
                                               s4 Sonnet pandas, a second run
       blockv3.py fake <arm> <task id>        a dry start of one arm (the fake API: no model call)
       blockv3.py plan <stage>                the stage's sessions, in order
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import compare as K  # noqa: E402
import pipeline as P  # noqa: E402
import v3lib as L  # noqa: E402

C, V = K.C, L.V
HAIKU, SONNET = P.HAIKU, P.SONNET
ARMS5 = ["grep", "v2-tool", "v3-tool", "v2", "v3"]
CODEMEM4 = ["v2-tool", "v3-tool", "v2", "v3"]
ID = {"grep": "grep", "v2-tool": "v2t", "v3-tool": "v3t", "v2": "v2u", "v3": "v3u"}
K.ARMS.update({"v2-tool": (L.SRC["v2"], False), "v3-tool": (L.SRC["v3"], False),
               "v2": (L.SRC["v2"], True), "v3": (L.SRC["v3"], True)})
K.FOREIGN = K.FOREIGN + ("Agent Instructions for vLLM",)
K.CAP = 10 ** 6  # this block's own cap is checked in guard()
CAP = 340
DEADLINE = datetime(2026, 11, 28, 7, 0, tzinfo=timezone.utc).timestamp()
MIN_FREE_GB = 6.0
VLLM = [json.loads(l)["id"] for l in L.VLLM_TASKS.read_text().split("\n") if l.strip()]
LOADED = re.compile(r"Contents of [^\n\"]{0,300}?(AGENTS|CLAUDE)\.md")
LOG = V / "logs/blockv3.log"


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def upfront_lines(task_id: str, level: str) -> list[str]:
    """compare.upfront_lines, word for word, on the blocks made at 463171c (v3check.py blocks)."""
    hits = json.loads((L.BLOCKS / f"{task_id}-{level}.json").read_text())
    hits = hits.get("results", hits) if isinstance(hits, dict) else hits
    return [f"{h['path']}:{h['start_line']}  {h.get('qualname') or h.get('name') or ''}".rstrip() for h in hits[:20]]


K.upfront_lines = upfront_lines


def rotated(xs: list, k: int) -> list:
    return xs[k % len(xs):] + xs[:k % len(xs)]


def spec(stage: str, arm: str, tid: str, model: str, rep: int) -> dict:
    short = P.SHORT[model]
    return {"run": f"v3{stage}-{ID[arm]}-{tid[-5:]}-L2-{short}-r{rep}", "arm": arm, "task": tid, "level": "L2",
            "model": model, "cell": f"v3{stage}-{tid[-5:]}-L2-{short}", "cd": True, "block": f"v3{stage}", "rep": rep}


def haiku_round(stage: str, tids: list[str]) -> list[dict]:
    """Per task: grep once and the four codemem arms twice; the first round in ARMS5 order rotated by the task's
    place, the second the codemem arms in the reverse order, rotated too."""
    out = []
    for k, tid in enumerate(tids):
        out += [spec(stage, a, tid, HAIKU, 1) for a in rotated(ARMS5, k)]
        out += [spec(stage, a, tid, HAIKU, 2) for a in rotated(list(reversed(CODEMEM4)), k)]
    return out


def plan(stage: str) -> list[dict]:
    if stage == "s1":
        return haiku_round("s1", P.ORDER)
    if stage == "s2":
        return haiku_round("s2", VLLM) + [spec("s2", a, tid, SONNET, 1) for k, tid in enumerate(VLLM)
                                          for a in rotated(ARMS5, k)]
    if stage == "s3":
        return [spec("s3", a, tid, SONNET, 1) for k, tid in enumerate(P.ORDER) for a in rotated(ARMS5, k)]
    if stage == "s4":
        # The cap leaves about 18 sessions after stages 1 to 3: too few for a second run of every cell, so the second
        # Sonnet run goes to the two arms of the comparison that runs in the evaluation, v2 and v3, task by task.
        return [spec("s4", a, tid, SONNET, 2) for k, tid in enumerate(P.ORDER) for a in (["v2", "v3"] if k % 2 == 0
                                                                                          else ["v3", "v2"])]
    raise SystemExit(f"no stage {stage}")


def block_count() -> int:
    n = 0
    for line in K.LEDGER.read_text().split("\n"):
        if line.strip():
            e = json.loads(line)
            n += (not e.get("fake")) and str(e.get("block", "")).startswith("v3s")
    return n


def guard(s: dict) -> None:
    if (K.RUNS / s["run"] / "record.json").exists():
        return
    if time.time() >= DEADLINE:
        raise K.StopRun("07:00 UTC on Nov 28: no new session (the brief's deadline)", 5)
    if block_count() >= CAP:
        raise K.StopRun(f"the block's cap of {CAP} sessions is reached", 3)
    gb = L.free_gb()
    if gb < MIN_FREE_GB:
        raise K.StopRun(f"{gb:.1f} GB free on disk, under {MIN_FREE_GB} GB", 6)


def loaded_agent_files(out: Path) -> list[str]:
    """Agent files that Claude Code put into any request of the session by itself (not a file the agent read)."""
    hits = set()
    for path in sorted((out / "bodies").glob("*.request")):
        for m in LOADED.finditer(path.read_text(errors="replace")):
            hits.add(m.group(0)[-160:])
    return sorted(hits)


def run(s: dict, tasks: dict, vague: dict) -> dict:
    guard(s)
    rec = K.run_spec(s, tasks, vague)
    out = K.RUNS / s["run"]
    status = rec.get("unified_status")
    log(f"{s['run']}: {rec.get('status')}, {rec.get('n_turns')} turns, {rec.get('answer_s')} s, "
        f"{(rec.get('tokens') or {}).get('total')} tokens, ${(rec.get('result') or {}).get('total_cost_usd')}, file first "
        f"{rec.get('gold_file_first')}, function {rec.get('gold_fn_full')}; subscription {status} (7d {rec.get('util_7d')}, "
        f"5h {rec.get('util_5h')}); {block_count()} sessions in the block; {L.free_gb():.1f} GB free")
    agent_files = loaded_agent_files(out)
    if agent_files:
        raise K.StopRun(f"{s['run']}: agent files loaded by Claude Code into a request: {agent_files}", 7)
    if status not in (None, "allowed"):
        raise K.StopRun(f"{s['run']}: subscription status {status} (7d {rec.get('util_7d')}, 5h {rec.get('util_5h')}): "
                        f"a sign of a usage limit; no further session", 3)
    return rec


def machine_note(stage: str) -> None:
    up = subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip()
    mp = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout.strip().split("\n")[-1]
    sw = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout.strip()
    log(f"stage {stage} starts: {up} | {mp} | swap {sw} | {L.free_gb():.1f} GB free")


def report(note: str) -> None:
    p = subprocess.run([str(K.PY), str(C / "bin/blockv3_report.py"), note], capture_output=True, text=True)
    log(f"report written ({note}): rc {p.returncode} {p.stderr[-300:]}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    tasks, vague = L.all_tasks()
    if args[0] == "plan":
        for s in plan(args[1]):
            print(s["run"])
        return
    if args[0] == "fake":
        fake(args[1], args[2], tasks, vague)
        return
    if args[0] == "drycheck":  # the checks of a dry start already made
        s = {"run": f"v3fake-{ID[args[1]]}-{args[2][-5:]}"}
        out = K.RUNS / s["run"]
        dry_checks(args[1], args[2], s, json.loads((out / "record.json").read_text()), out)
        return
    if args[0] != "run":
        raise SystemExit(__doc__)
    for stage in args[1:]:
        machine_note(stage)
        try:
            for s in plan(stage):
                run(s, tasks, vague)
        except K.StopRun as e:
            log(f"STOP in stage {stage}: {e}")
            report(f"stage {stage} stopped: {e}")
            sys.exit(e.code)
        log(f"stage {stage} done")
        report(f"stage {stage} done")
    log("all stages asked for are done")


# ---------------------------------------------------------------- dry starts

def fake_script(arm: str, tid: str, tasks: dict) -> list:
    repo = C / "tasks" / tid / "repo"
    gold = tasks[tid]["gold"]["files"][0]
    answer = [{"type": "text", "text": json.dumps({"files": [gold], "functions": []})}]
    read = [{"type": "tool_use", "id": "toolu_v3f_read", "name": "Read",
             "input": {"file_path": str(repo / gold), "offset": 1, "limit": 5}}]
    if arm == "grep":
        return [[{"type": "tool_use", "id": "toolu_v3f_grep", "name": "Bash",
                  "input": {"command": f"grep -n \"def \" {gold} | head -3", "description": "dry start"}}], read, answer]
    query = {"query": "where the request's behaviour is decided"}
    if arm in ("v3-tool", "v3"):
        query.update({"intent": "the function that decides the behaviour the request describes",
                      "symptom": "the wrong behaviour of the request", "anchors": [Path(gold).stem],
                      "locations": [gold]})
    return [[{"type": "tool_use", "id": "toolu_v3f_search", "name": "mcp__codemem__search_code", "input": query}],
            read, answer]


def fake(arm: str, tid: str, tasks: dict, vague: dict) -> None:
    s = {"run": f"v3fake-{ID[arm]}-{tid[-5:]}", "arm": arm, "task": tid, "level": "L2", "model": HAIKU,
         "cell": f"v3fake-{tid[-5:]}", "cd": True, "block": "v3fake"}
    out = K.RUNS / s["run"]
    shutil.rmtree(out, ignore_errors=True)
    rec = K.run_one(s, tasks=tasks, vague=vague, fake_script=fake_script(arm, tid, tasks))
    dry_checks(arm, tid, s, rec, out)


def dry_checks(arm: str, tid: str, s: dict, rec: dict, out: Path) -> None:
    """What the first request of a dry start carried: the arm's tool texts, no hook, the 20 lines where they belong."""
    checks = {"status": rec.get("status"), "why": rec.get("why"), "init_s": rec.get("init_s")}
    events = [json.loads(l) for l in (out / "stream.jsonl").read_text().split("\n") if l.strip().startswith("{")]
    checks["hook_events"] = sum(1 for e in events if "hook" in str(e.get("subtype") or "") or e.get("type") == "hook")
    checks["settings_flag"] = "--settings" in (out / "cmd.json").read_text()
    body = None
    for path in sorted((out / "bodies").glob("*.request")):
        try:
            b = json.loads(path.read_bytes())
        except ValueError:  # a request without a JSON body (compare.body_check skips it too)
            continue
        if b.get("tools"):
            body = b
            break
    raw = json.dumps(body)
    tools = {t["name"]: t for t in body.get("tools") or []}
    checks["tools"] = sorted(tools)
    descr = json.loads((V / "check-plain.json").read_text())["pandas-dev__pandas-70205"]["descriptions"]
    schemas = json.loads((V / "check-plain.json").read_text())["pandas-dev__pandas-70205"]["schemas"]
    if K.ARMS[arm][0] is not None:
        which = "v3" if arm in ("v3-tool", "v3") else "v2"
        other = "v2" if which == "v3" else "v3"
        sc = tools["mcp__codemem__search_code"]
        checks["search_code_description_is"] = ("v3" if sc.get("description") == descr["v3"]["search_code"] else
                                                "v2" if sc.get("description") == descr["v2"]["search_code"] else "neither")
        checks["all_codemem_descriptions_match_" + which] = all(
            tools[f"mcp__codemem__{n}"].get("description") == d for n, d in descr[which].items())
        checks["search_code_inputs"] = sorted((sc.get("input_schema") or {}).get("properties") or {})
        checks["schema_matches_" + which] = (sc.get("input_schema") or {}).get("properties") == \
            (schemas[which]["search_code"] or {}).get("properties")
        checks["other_text_absent"] = descr[other]["search_code"] not in raw
        checks["codemem_tool_chars"] = sum(len(json.dumps(t)) for n, t in tools.items() if n.startswith("mcp__codemem__"))
    prompt = (out / "prompt.txt").read_text()
    if K.ARMS[arm][1]:
        lines = prompt.split("\n\n", 1)[0].split("\n")
        checks["prompt_head"] = lines[0] == K.UPFRONT_HEAD
        checks["prompt_lines"] = len(lines) - 1
        checks["lines_in_first_request"] = all(l in raw for l in [json.dumps(x)[1:-1] for x in lines])
        checks["lines_are_463171c_blocks"] = lines[1:] == upfront_lines(tid, "L2")
    else:
        checks["no_upfront"] = K.UPFRONT_HEAD not in prompt and K.UPFRONT_HEAD not in raw
    search = [c for c in rec.get("calls") or [] if c["kind"] == "search_code"]
    if search:
        checks["search_result"] = {"cards": search[0].get("cards"), "error": search[0].get("error"),
                                   "keyword_only": search[0].get("keyword_only"), "head": search[0].get("result_head", "")[:160]}
    checks["foreign"] = (rec.get("body") or {}).get("foreign")
    checks["git_section_empty"] = (rec.get("body") or {}).get("git_section_empty")
    checks["agent_files_loaded"] = loaded_agent_files(out)
    print(json.dumps(checks, indent=1))
    res = V / "check-dry.json"
    old = json.loads(res.read_text()) if res.exists() else {}
    old[s["run"]] = checks
    res.write_text(json.dumps(old, indent=1))


if __name__ == "__main__":
    main()
