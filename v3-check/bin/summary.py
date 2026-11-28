"""Tables from the session records (runs/<run>/record.json; discarded runs are left out).

usage:
  summary.py pairs <model short> <arm A> <arm B> [levels]   e.g. summary.py pairs haiku grep tool L0,L1,L2
  summary.py inside <model short> <arm> [levels]           what happened in the codemem sessions
  summary.py rows <model short> <arm> [levels]             one line per session
"""
import json
import re
import statistics
import sys
from math import comb
from pathlib import Path

C = Path(__file__).resolve().parents[1]
ARM_ID = {"grep": "grep", "tool": "tool", "upfront": "upfront", "tool+": "toolplus", "tool-h": "toolh", "tool+h": "toolplush"}


def records():
    out = {}
    for p in sorted((C / "runs").glob("*/record.json")):
        if "." in p.parent.name:
            continue
        r = json.loads(p.read_text())
        if r.get("fake"):
            continue
        out[r["run"]] = r
    return out


def rec(recs, arm, tid, level, model):
    return recs.get(f"{ARM_ID[arm]}-{tid[-5:]}-{level}-{model}")


def sign_p(lower, higher):
    n, k = lower + higher, min(lower, higher)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def secs(r):
    return r.get("answer_s") if r.get("answer_s") is not None else (r.get("result") or {}).get("duration_ms", 0) / 1000


def fmt(x, nd=0):
    if x is None:
        return "-"
    return f"{x:,.{nd}f}" if isinstance(x, float) else f"{x:,}"


def pairs(model, a, b, levels):
    recs = records()
    tasks = sorted({r["task"] for r in recs.values()})
    print(f"| Level | Arm | Tasks | Gold file first | Gold file in answer | Gold function (full name / last part) | "
          f"No answer | Median turns | Median tokens | Median seconds |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    cmp_rows = []
    for level in levels:
        both = [t for t in tasks if (ra := rec(recs, a, t, level, model)) and (rb := rec(recs, b, t, level, model))
                and ra.get("status") == "finished" and rb.get("status") == "finished"]
        for arm in (a, b):
            rs = [rec(recs, arm, t, level, model) for t in both]
            fn = [r for r in rs if r.get("gold_fn_full") is not None]
            print(f"| {level} | {arm} | {len(rs)} | {sum(bool(r.get('gold_file_first')) for r in rs)} | "
                  f"{sum(bool(r.get('gold_file_any')) for r in rs)} | "
                  f"{sum(bool(r.get('gold_fn_full')) for r in fn)} / {sum(bool(r.get('gold_fn_last')) for r in fn)} of {len(fn)} | "
                  f"{sum(not r.get('answered') for r in rs)} | {fmt(med([r.get('n_turns') for r in rs]))} | "
                  f"{fmt(med([r['tokens']['total'] for r in rs]))} | {fmt(med([secs(r) for r in rs]), 1)} |")
        row = [level, len(both)]
        for key in ("turns", "tokens", "seconds"):
            lo = eq = hi = 0
            for t in both:
                ra, rb = rec(recs, a, t, level, model), rec(recs, b, t, level, model)
                va, vb = {"turns": (ra.get("n_turns"), rb.get("n_turns")),
                          "tokens": (ra["tokens"]["total"], rb["tokens"]["total"]),
                          "seconds": (secs(ra), secs(rb))}[key]
                if key == "seconds":  # within 5% counts as equal
                    if abs(vb - va) <= 0.05 * max(va, vb):
                        eq += 1
                        continue
                if vb < va:
                    lo += 1
                elif vb == va:
                    eq += 1
                else:
                    hi += 1
            row.append(f"{lo} / {eq} / {hi} (p {sign_p(lo, hi):.2f})")
        cmp_rows.append(row)
    print()
    print(f"| Level | Pairs | Turns: {b} lower / equal / higher | Tokens | Seconds (within 5% = equal) |")
    print("|---|---|---|---|---|")
    for r in cmp_rows:
        print("| " + " | ".join(str(x) for x in r) + " |")
    print()
    print("Gold file and gold function, pair by pair (a = " + a + ", b = " + b + "):")
    for level in levels:
        both = [t for t in tasks if rec(recs, a, t, level, model) and rec(recs, b, t, level, model)]
        wins = {"b right, a wrong": [], "a right, b wrong": []}
        for t in both:
            ra, rb = rec(recs, a, t, level, model), rec(recs, b, t, level, model)
            if rb.get("gold_file_first") and not ra.get("gold_file_first"):
                wins["b right, a wrong"].append(t[-5:])
            if ra.get("gold_file_first") and not rb.get("gold_file_first"):
                wins["a right, b wrong"].append(t[-5:])
        print(f"  {level} gold file first: {wins}")


def inside(model, arm, levels):
    recs = records()
    for level in levels:
        rs = [r for r in recs.values() if r.get("arm") == arm and r.get("level") == level
              and r.get("model", "").endswith(model + "-5-5") and r.get("status") == "finished"]
        called = [r for r in rs if r.get("called_search")]
        turns = {}
        for r in called:
            turns[r["first_search_turn"]] = turns.get(r["first_search_turn"], 0) + 1
        again = sum(r.get("n_searches", 0) >= 2 for r in called)
        gfile = sum(r.get("first_search_gold_file_rank") is not None for r in called)
        gfirst = sum(r.get("first_search_gold_file_rank") == 1 for r in called)
        gfn = sum(bool((r.get("first_search_gold_fn") or {}).get("full")) for r in called)
        nxt = {}
        for r in called:
            k = after_search(r)
            nxt[k] = nxt.get(k, 0) + 1
        print(f"{level}: {len(rs)} sessions; called search_code {len(called)}; first call at turn {dict(sorted(turns.items()))}; "
              f"searched again {again}; first result held a gold file {gfile} (first card {gfirst}), a gold function {gfn}; "
              f"next step {nxt}; get_chunk used in {sum(r.get('n_get_chunk', 0) > 0 for r in called)}")


def after_search(r):
    calls = r.get("calls") or []
    i = next((j for j, c in enumerate(calls) if c["kind"] == "search_code"), None)
    if i is None:
        return "no search"
    first = calls[i]
    paths = {re.sub(r":\d+.*", "", x.split(" ")[0]) for x in first.get("card_list") or []}
    names = {x.split(" ")[-1].split(".")[-1] for x in first.get("card_list") or []}
    later = [c for c in calls[i + 1:] if c["turn"] > first["turn"]] or calls[i + 1:]
    if not later:
        return "answered"
    c = later[0]
    if c["kind"] == "search_code":
        return "searched again"
    if c["kind"] == "get_chunk":
        return "get_chunk"
    arg = c["arg"]
    if c["kind"] == "file read" and any(p and p in arg for p in paths):
        return "read a file from it"
    if c["kind"] == "shell search" and (any(p and p in arg for p in paths) or any(n and len(n) > 3 and n in arg for n in names)):
        return "grep with a name or path from it"
    return "did something else"


def rows(model, arm, levels):
    recs = records()
    for r in sorted(recs.values(), key=lambda r: (r["level"], r["task"])):
        if r.get("arm") != arm or r.get("level") not in levels or not r.get("model", "").endswith(model + "-5-5"):
            continue
        print(f"{r['run']:28} {r.get('status'):9} first={str(r.get('gold_file_first')):5} fn={str(r.get('gold_fn_full')):5} "
              f"turns={r.get('n_turns')} tok={r.get('tokens', {}).get('total')} s={secs(r) if r.get('status') == 'finished' else '-'} "
              f"seen@{r.get('gold_seen_turn')} read@{r.get('gold_read_turn')} q={str(r.get('first_query'))[:60]!r} "
              f"files={r.get('files')} fns={r.get('functions')}")


def cost(r):
    return (r.get("result") or {}).get("total_cost_usd") or 0.0


def adj_turns(r):
    return (r.get("n_turns") or 0) - (r.get("refused_turns") or 0)


def busy(r) -> bool:
    """The session overlapped a foreign model process, or started on a busy machine (quiet.sh gave up after
    10 minutes: another agent's heavy job was running). Its seconds are set aside; turns and tokens count."""
    return bool(r.get("foreign_overlap")) or (r.get("machine") or {}).get("quiet") is False


def secs_clean(rs):
    """Seconds only from sessions on a quiet machine."""
    return [secs(r) for r in rs if not busy(r)]


def running_table(model="haiku", levels=("L2", "L1"), arms=("grep", "tool", "tool+")) -> str:
    """Per level and arm, over the sessions done so far."""
    recs = [r for r in records().values() if r.get("status") == "finished" and r.get("model", "").endswith(model + "-5-5")]
    lines = ["| Level | Arm | Tasks | Gold file first | Gold file in `files` | Gold function named | No answer | "
             "Median turns (raw / less refused turns) | Refused calls (sessions with one) | Median tokens | "
             "Median cost $ | Median seconds | Called search_code / at turn 1 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for level in levels:
        for arm in arms:
            rs = [r for r in recs if r.get("arm") == arm and r.get("level") == level]
            if not rs:
                continue
            fn = [r for r in rs if r.get("gold_fn_full") is not None]
            called = (f"{sum(bool(r.get('called_search')) for r in rs)} / {sum(r.get('first_search_turn') == 1 for r in rs)}"
                      if arm not in ("grep", "upfront") else "")
            lines.append(
                f"| {level} | {arm} | {len(rs)} | {sum(bool(r.get('gold_file_first')) for r in rs)} | "
                f"{sum(bool(r.get('gold_file_any')) for r in rs)} | {sum(bool(r.get('gold_fn_full')) for r in fn)} of {len(fn)} | "
                f"{sum(not r.get('answered') for r in rs)} | {fmt(med([r.get('n_turns') for r in rs]))} / "
                f"{fmt(med([adj_turns(r) for r in rs]))} | {sum(r.get('n_refused') or 0 for r in rs)} "
                f"({sum(bool(r.get('n_refused')) for r in rs)}) | {fmt(med([r['tokens']['total'] for r in rs]))} | "
                f"{med([cost(r) for r in rs]) or 0:.4f} | {fmt(med(secs_clean(rs)), 1)} | {called} |")
    return "\n".join(lines)


def pair_counts(model, a, b, level, key):
    """Tasks where arm b was lower / equal / higher than arm a (for seconds, pairs on a quiet machine only)."""
    recs = records()
    lo = eq = hi = 0
    for t in sorted({r["task"] for r in recs.values()}):
        ra, rb = rec(recs, a, t, level, model), rec(recs, b, t, level, model)
        if not ra or not rb or ra.get("status") != "finished" or rb.get("status") != "finished":
            continue
        if key is secs and (busy(ra) or busy(rb)):
            continue
        va, vb = key(ra), key(rb)
        if vb < va:
            lo += 1
        elif vb == va:
            eq += 1
        else:
            hi += 1
    return f"{lo} / {eq} / {hi} (sign test p {sign_p(lo, hi):.2f})"


def upfront_use(r: dict) -> dict:
    """Did the agent of an upfront session use the list: do its first calls go to a file or a name from it?"""
    path = C / "upfront" / f"{r['task']}-{r['level']}.json"
    if not path.exists():
        return {"used": None}
    hits = json.loads(path.read_text())["results"][:20]
    paths = {h["path"] for h in hits}
    names = {re.split(r"[.:]", (h.get("qualname") or ""))[-1] for h in hits} - {""}
    def uses(c):
        arg = c["arg"]
        if any(p in arg for p in paths):
            return "a listed file"
        words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", arg))
        if words & names:
            return "a listed name"
        return None
    calls = [c for c in r.get("calls") or [] if c["kind"] in ("shell search", "file read")]
    first = calls[:2]
    marks = [uses(c) for c in first]
    gold_fns = r.get("gold_functions") or []
    fn_in = any(h["path"] in (r.get("gold_files") or []) and h.get("qualname") in gold_fns for h in hits)
    return {"used": any(marks), "first_calls": [f"t{c['turn']} {c['kind']}: {c['arg'][:90]}" for c in first],
            "marks": marks, "gold_in_list": bool(set(r.get("gold_files") or []) & paths),
            "gold_fn_in_list": fn_in if gold_fns else None}


def pairs_table(model, levels, arms) -> list[str]:
    lines = [f"| Level | Arm | Pairs | Turns | Tokens | Cost | Seconds |", "|---|---|---|---|---|---|---|"]
    recs = records()
    for level in levels:
        for arm in arms:
            n = sum(1 for t in {r["task"] for r in recs.values()}
                    if (a := rec(recs, "grep", t, level, model)) and (b := rec(recs, arm, t, level, model))
                    and a.get("status") == b.get("status") == "finished")
            if not n:
                continue
            lines.append(f"| {level} | {arm} | {n} | " + " | ".join(
                pair_counts(model, "grep", arm, level, key).replace("(sign test p ", "(p ")
                for key in (lambda r: r.get("n_turns") or 0, lambda r: r["tokens"]["total"], cost, secs)) + " |")
    return lines


def branch_test(levels=("L2", "L1")) -> list[str]:
    """Over the Haiku tasks: the cells where `tool`'s first result had no gold function among its cards, and what
    `tool+` showed there (cards / related / more / absent) and whether `tool+` named the gold function."""
    recs = records()
    out = ["| Level | Cells: `tool`'s first result has no gold function card | `tool+` there: card / related / more / "
           "absent | `tool+` named the gold function | `tool` named it | Cells |", "|---|---|---|---|---|---|---|"]
    for level in levels:
        cells = []
        for t in sorted({r["task"] for r in recs.values()}):
            a, b = rec(recs, "tool", t, level, "haiku"), rec(recs, "tool+", t, level, "haiku")
            if not a or not b or a.get("status") != "finished" or b.get("status") != "finished":
                continue
            if not a.get("gold_functions"):
                continue  # a task with no gold function cannot be scored here
            where_a = (a.get("first_gold_where") or {}).get("function") if a.get("called_search") else "no search"
            if where_a != "card":
                cells.append((t, where_a, (b.get("first_gold_where") or {}).get("function") if b.get("called_search")
                              else "no search", bool(b.get("gold_fn_full")), bool(a.get("gold_fn_full"))))
        tally = {k: sum(1 for c in cells if c[2] == k) for k in ("card", "related", "more", "absent")}
        out.append(f"| {level} | {len(cells)} | {tally['card']} / {tally['related']} / {tally['more']} / {tally['absent']} | "
                   f"{sum(c[3] for c in cells)} of {len(cells)} | {sum(c[4] for c in cells)} of {len(cells)} | "
                   + (", ".join(f"{c[0][-5:]} ({c[1]}: {c[2]})" for c in cells) or "-") + " |")
    return out


def upfront_detail(model) -> str:
    recs = [r for r in records().values() if r.get("arm") == "upfront" and r.get("status") == "finished"
            and r.get("model", "").endswith(model + "-5-5")]
    if not recs:
        return ""
    us = [upfront_use(r) for r in recs]
    return (f"- {model} `upfront` ({len(recs)} sessions): gold file among the 20 lines {sum(bool(u.get('gold_in_list')) for u in us)}; "
            f"a gold function among them {sum(bool(u.get('gold_fn_in_list')) for u in us)}; the first call went to a "
            f"file or name from the list in {sum(bool(u.get('used')) for u in us)}.")


def write_progress_table(note: str, sessions: int, path=None) -> None:
    import time
    TOP_START, TOP_END = "<!-- running table: start -->", "<!-- running table: end -->"
    recs = records()
    body = [TOP_START, "## Running table (rewritten as the runs go)", "",
            f"Updated {time.strftime('%H:%M')}: {note}. Sessions so far: {sessions} of 280. Gold function: the "
            "full-name rule (the answer's name, less any module or path prefix, equals the gold Class.method). Tokens: "
            "input + output + cache read + cache written, from the result event. Seconds: from the first model request "
            "to the answer (the hold is outside it in every arm), sessions that overlapped a foreign model process left "
            "out. Allow lists: block (i-a) without `cd`; blocks (iii), (i-b), (ii), (iv), (v) with `Bash(cd:*)`.", "",
            "**Haiku**", "", running_table("haiku", ("L2", "L1", "L0"), ("grep", "tool", "tool+", "upfront")), "",
            "Haiku, pair by pair against `grep` on the same task and level (arm lower / equal / higher; sign test):", "",
            *pairs_table("haiku", ("L2", "L1"), ("tool", "tool+", "upfront")), "",
            "**The test of the branch** (Haiku, all tasks so far; a cell is a task at a level; tasks without a gold "
            "function left out):", "", *branch_test()]
    if any(r.get("model") == "claude-sonnet-5-5" for r in recs.values()):
        body += ["", "**Sonnet** (L2)", "",
                 running_table("sonnet", ("L2",), ("grep", "tool", "tool-h", "tool+h", "upfront")), "",
                 "`tool-h` against `grep`, task by task (tool-h lower / equal / higher): turns "
                 + pair_counts("sonnet", "grep", "tool-h", "L2", lambda r: r.get("n_turns") or 0)
                 + "; turns less refused turns " + pair_counts("sonnet", "grep", "tool-h", "L2", adj_turns)
                 + "; tokens " + pair_counts("sonnet", "grep", "tool-h", "L2", lambda r: r["tokens"]["total"]) + ".",
                 "", "Sonnet, pair by pair against `grep`:", "", *pairs_table("sonnet", ("L2",), ("tool", "tool-h", "tool+h", "upfront"))]
    if any(r.get("model") == "claude-opus-5-5" for r in recs.values()):
        body += ["", "**Opus** (L2, block D, six tasks)", "", running_table("opus", ("L2",), ("grep", "tool", "upfront")), "",
                 "Opus, pair by pair against `grep`:", "", *pairs_table("opus", ("L2",), ("tool", "upfront"))]
    if (C / "closed/runs").exists():
        import closed_report as CR
        body += ["", "**Closed book** (block E: no tools, no repository, one turn; vague-v3 prompts; duckdb's gold names "
                 "lose their `duckdb.` namespace for the full-name rule; kubernetes labels no functions)", "",
                 *CR.table_by_repo(CR.closed())]
    body += ["", "**Inside the codemem sessions** (first `search_code` of each session; counts of sessions)", ""]
    for model in ("haiku", "sonnet", "opus"):
        for arm in ("tool", "tool+", "tool-h", "tool+h"):
            rs = [r for r in recs.values() if r.get("status") == "finished" and r.get("arm") == arm
                  and r.get("model", "").endswith(model + "-5-5")]
            if not rs:
                continue
            called = [r for r in rs if r.get("called_search")]
            def tally(key):
                out = {}
                for r in called:
                    v = key(r)
                    out[v] = out.get(v, 0) + 1
                return ", ".join(f"{k} {n}" for k, n in sorted(out.items(), key=lambda kv: -kv[1])) or "-"
            line = (f"- {model} `{arm}`: {len(called)} of {len(rs)} called it. Gold file in the first result: "
                    f"{tally(lambda r: (r.get('first_gold_where') or {}).get('file'))}. Gold function: "
                    f"{tally(lambda r: (r.get('first_gold_where') or {}).get('function'))}. Next step: "
                    f"{tally(lambda r: (r.get('first_next_step') or {}).get('step'))}.")
            if arm.startswith("tool+"):
                line += f" Passed `names`: {sum(bool(r.get('any_names')) for r in called)}."
            if arm in ("tool-h", "tool+h"):
                after = {}
                for r in rs:
                    if r.get("hook_first_refused"):
                        after[r.get("hook_after_refusal")] = after.get(r.get("hook_after_refusal"), 0) + 1
                line += (f" First grep refused by the hook: {sum(bool(r.get('hook_first_refused')) for r in rs)}; "
                         f"next call after it: {', '.join(f'{k} {n}' for k, n in after.items()) or '-'}; "
                         f"later refusals: {sum(r.get('hook_later_refusals') or 0 for r in rs)}.")
            body.append(line)
    body += ["", "**The upfront list**", ""] + [x for x in (upfront_detail("haiku"), upfront_detail("sonnet"),
                                                         upfront_detail("opus")) if x]
    path1 = C / "logs/phase1.jsonl"
    rows = [json.loads(l) for l in path1.read_text().split("\n") if l.strip()] if path1.exists() else []
    if rows:
        body += ["", "**Indexes** (built newest first; each build reuses the vectors of the ones before)", "",
                 "| Task | Files | Chunks | Vectors embedded new | Seconds | Current | Gold functions not in the index |",
                 "|---|---|---|---|---|---|---|"]
        for r in rows:
            body.append(f"| {r['task'][-5:]} | {r['files']:,} | {r['chunks']:,} | {r['new_vectors'] or '-'} | "
                        f"{r['seconds'] or '-'} | {'yes' if r['current'] else 'NO'} | {', '.join(r['gold_functions_missing']) or 'none'} |")
    over = [r["run"] for r in recs.values() if busy(r)]
    crashed = [r["run"] for r in recs.values() if r.get("server_crashed")]
    utils = [r.get("util_7d") for r in sorted(recs.values(), key=lambda r: r.get("run")) if r.get("util_7d")]
    body += ["", discards_line(),
             f"Sessions that overlapped a foreign model process or started on a busy machine (seconds set aside, "
             f"turns and tokens kept): {', '.join(over) or 'none'}.",
             f"Sessions whose codemem server crashed later in the session (kept, flagged): {', '.join(crashed) or 'none'}.",
             f"Subscription 7-day use at the last session: {utils[-1] if utils else '-'}.", TOP_END, ""]
    path = path or (C / "progress.md")
    text = path.read_text()
    if TOP_START in text:
        a, b = text.index(TOP_START), text.index(TOP_END) + len(TOP_END)
        text = text[:a] + "\n".join(body).rstrip("\n") + text[b:]
    else:
        title, rest = text.split("\n", 1)
        text = title + "\n\n" + "\n".join(body) + "\n" + rest
    path.write_text(text)


def discards_line() -> str:
    path = C / "runs" / "discards.jsonl"
    rows = [json.loads(l) for l in path.read_text().split("\n") if l.strip()] if path.exists() else []
    if not rows:
        return "Discarded sessions: none."
    why = {}
    for r in rows:
        why[r["why"]] = why.get(r["why"], 0) + 1
    return f"Discarded sessions: {len(rows)} (" + "; ".join(f"{n} x {w}" for w, n in why.items()) + ")."


if __name__ == "__main__":
    cmd = sys.argv[1]
    levels = sys.argv[-1].split(",") if sys.argv[-1].startswith("L") else ["L0", "L1", "L2"]
    if cmd == "pairs":
        pairs(sys.argv[2], sys.argv[3], sys.argv[4], levels)
    elif cmd == "inside":
        inside(sys.argv[2], sys.argv[3], levels)
    elif cmd == "rows":
        rows(sys.argv[2], sys.argv[3], levels)
    elif cmd == "table":
        print(running_table())
        print()
        print(discards_line())
