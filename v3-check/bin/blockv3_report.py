"""Tables of the v3-against-v2 check (blockv3.py) into .personal/benchmarks/2026-11-28-v3-against-v2.md, between
markers, one part per stage, so that the hand-written parts of the file stay. Records: runs/v3s*/record.json
(finished, not discarded). Seconds: the proxy's answer_s, set aside for a session that overlapped a foreign model
process or started on a busy machine (summary.busy).

usage: blockv3_report.py [note]          write the tables
       blockv3_report.py --print [note]  print them only
"""
from __future__ import annotations

import json
import math
import random
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import summary as S  # noqa: E402

C = Path(__file__).resolve().parents[1]  # the folder that holds bin/, runs/ and v3/
CM = Path(__import__("os").environ.get("CODEMEM_REPO", "/path/to/codemem"))  # a codemem checkout
RUNS = C / "runs"
REPORT = CM / ".personal/benchmarks/2026-11-28-v3-against-v2.md"
ARMS = ["grep", "v2-tool", "v3-tool", "v2", "v3"]
NEW_INPUTS = ("intent", "symptom", "anchors", "locations")
MEASURES = ("turns", "tokens", "cost", "seconds")


# ---------------------------------------------------------------- reading

AGENT_ERROR = "validation error for search_codeArguments"


def discarded_first_attempts() -> dict[str, dict]:
    """The first attempt of each session of this block that the harness discarded, with its cause: "agent" when its
    first search_code call failed on the agent's own arguments (a validation error: the server answered), "server"
    otherwise. compare.discard_reason reads both as a server that died at the first search, and runs the session
    again."""
    out = {}
    path = RUNS / "discards.jsonl"
    for line in (path.read_text().split("\n") if path.exists() else []):
        if not line.strip():
            continue
        d = json.loads(line)
        p = RUNS / d["moved_to"] / "record.json"
        if not d["run"].startswith("v3s") or d["run"] in out or not p.exists():
            continue
        r = json.loads(p.read_text())
        r["_dir"] = p.parent
        first = next((c for c in r.get("calls") or [] if c.get("kind") == "search_code"), None)
        r["_discard_cause"] = "agent" if first and AGENT_ERROR in (first.get("result_head") or "") else "server"
        out[d["run"]] = r
    return out


def records(view: str = "harness") -> list[dict]:
    """The finished sessions of this block. view "harness": as compare.py counts them (a discarded session is
    replaced by its run again); view "first": a session discarded for the agent's own argument error counts with
    its first attempt instead (what the arm did the first time, whatever happened)."""
    first = discarded_first_attempts() if view == "first" else {}
    out = []
    for p in sorted(RUNS.glob("v3s*/record.json")):
        if "." in p.parent.name:
            continue
        r = json.loads(p.read_text())
        if r.get("fake") or r.get("status") != "finished":
            continue
        r["_dir"] = p.parent
        d = first.get(r["run"])
        out.append(d if d is not None and d["_discard_cause"] == "agent" else r)
    return out


def group(recs, taskset, model):
    """arm -> task -> rep -> record, for one task set ("pandas" or "vllm") and model ("haiku" or "sonnet")."""
    g = {a: {} for a in ARMS}
    for r in recs:
        if ("vllm" in r["task"]) != (taskset == "vllm") or not r["model"].startswith(f"claude-{model}"):
            continue
        g[r["arm"]].setdefault(r["task"], {})[r.get("rep", 1)] = r
    return g


def val(r, m):
    t = r.get("tokens") or {}
    if m == "turns":
        return r.get("n_turns")
    if m == "tokens":
        return t.get("total")
    if m == "cost":
        return (r.get("result") or {}).get("total_cost_usd") or 0.0
    if m == "seconds":
        return None if S.busy(r) else S.secs(r)
    if m in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
        return t.get(m)
    if m == "file":
        return int(bool(r.get("gold_file_first")))
    if m == "function":
        return None if r.get("gold_fn_full") is None else int(bool(r.get("gold_fn_full")))
    raise KeyError(m)


def search_calls(r) -> list[dict]:
    """The search_code inputs of a session, in order, from its stream."""
    out = []
    for line in (r["_dir"] / "stream.jsonl").read_text().split("\n"):
        if not line.startswith("{"):
            continue
        e = json.loads(line)
        if e.get("type") == "assistant":
            for b in (e.get("message") or {}).get("content") or []:
                if b.get("type") == "tool_use" and b.get("name") == "mcp__codemem__search_code":
                    out.append(b.get("input") or {})
    return out


def first_request(r) -> dict:
    """The first main request's input tokens (all classes) and its codemem tool definitions."""
    recs = [json.loads(l) for l in (r["_dir"] / "proxy.jsonl").read_text().split("\n") if l.strip()]
    main = [x for x in recs if x.get("path") == "/v1/messages" and (x.get("tools") or 0) > 0]
    u = (main[0].get("usage") or {}) if main else {}
    total_in = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    out = {"input_total": total_in, "requests": len(main)}
    for path in sorted((r["_dir"] / "bodies").glob("*.request")):
        try:
            b = json.loads(path.read_bytes())
        except ValueError:
            continue
        if not b.get("tools"):
            continue
        cm = [t for t in b["tools"] if str(t.get("name", "")).startswith("mcp__codemem__")]
        out["tool_chars"] = sum(len(json.dumps(t)) for t in cm)
        out["search_code_description_chars"] = sum(len(t.get("description") or "") for t in cm
                                                   if t["name"] == "mcp__codemem__search_code")
        texts = "\n".join(strings(b.get("system"))) + "\n" + "\n".join(strings(b.get("messages")))
        out["instruction_chars"] = next((len(t) for which in ("v3", "v2") if (t := instructions(which)) and t in texts), None)
        break
    return out


INSTR: dict[str, str] = {}


def instructions(which: str) -> str:
    """codemem's server instructions (light) at v2's or v3's commit, from that commit's own prompts module."""
    if which not in INSTR:
        saved = C / "v3" / f"instructions-{which}.txt"  # saved with the data: no codemem checkout needed
        if saved.exists():
            INSTR[which] = saved.read_text()
            return INSTR[which]
        import subprocess
        src = CM / {"v2": ".cache/wt/compare-main/src", "v3": ".cache/wt/compare-pr85/src"}[which]
        p = subprocess.run([str(CM / ".cache/wt/faiss-1-16/.venv/bin/python"), "-c", "import sys; from codemem import "
                            "prompts; sys.stdout.write(prompts.server_instructions('light'))"],
                           env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
        INSTR[which] = p.stdout
    return INSTR[which]


def strings(x) -> list[str]:
    if isinstance(x, str):
        return [x]
    if isinstance(x, list):
        return [s for y in x for s in strings(y)]
    if isinstance(x, dict):
        return [s for y in x.values() for s in strings(y)]
    return []


# ---------------------------------------------------------------- numbers

def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def tot(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) if xs else None


def f(x, nd=0):
    if x is None:
        return "-"
    if isinstance(x, float) and nd:
        return f"{x:,.{nd}f}"
    return f"{round(x):,}" if isinstance(x, (int, float)) else str(x)


def money(x):
    return "-" if x is None else f"{x:.4f}"


def sessions(g, arm):
    return [r for reps in g[arm].values() for r in reps.values()]


def lower_equal_higher(pairs, m):
    lo = eq = hi = 0
    for a, b in pairs:
        va, vb = val(a, m), val(b, m)
        if va is None or vb is None:
            continue
        if m == "seconds" and abs(vb - va) <= 0.05 * max(va, vb):
            eq += 1
        elif vb < va:
            lo += 1
        elif vb == va:
            eq += 1
        else:
            hi += 1
    return lo, eq, hi


def ratio(pairs, m):
    ps = [(val(a, m), val(b, m)) for a, b in pairs]
    ps = [(x, y) for x, y in ps if x is not None and y is not None]
    sa, sb = sum(x for x, _ in ps), sum(y for _, y in ps)
    return sb / sa if sa else None


def matched(A, B):
    """Pairs on the same task: run i of A with run i of B; an arm with one run (grep) is paired with each run of the
    other arm."""
    out = []
    for t in sorted(set(A) & set(B)):
        ra, rb = A[t], B[t]
        if len(ra) == 1 and len(rb) > 1:
            out += [(next(iter(ra.values())), rb[k]) for k in sorted(rb)]
        elif len(rb) == 1 and len(ra) > 1:
            out += [(ra[k], next(iter(rb.values()))) for k in sorted(ra)]
        else:
            out += [(ra[k], rb[k]) for k in sorted(set(ra) & set(rb))]
    return out


def same_arm(A):
    """The two runs of one arm on the same task: run 2 against run 1."""
    return [(reps[1], reps[2]) for t, reps in sorted(A.items()) if 1 in reps and 2 in reps]


def perm_p(A, B, m, n=5000, seed=7):
    """Is B against A more than chance, given how much runs of one arm differ? Within each task the arm labels of its
    sessions are shuffled (every session of the task is exchangeable if the arm makes no difference); the statistic
    is the log of the ratio of sums (quality: the difference of sums). Two-sided."""
    groups = []
    for t in sorted(set(A) & set(B)):
        va = [val(r, m) for r in A[t].values()]
        vb = [val(r, m) for r in B[t].values()]
        if any(v is None for v in va + vb):
            continue
        groups.append((va + vb, len(va)))
    if not groups:
        return None
    binary = m in ("file", "function")

    def stat(split):
        # per task the mean of each arm's sessions, summed over tasks: an arm with one run (grep) weighs as one with two
        sa = sum(sum(vals[:k]) / k for vals, k in split)
        sb = sum(sum(vals[k:]) / (len(vals) - k) for vals, k in split)
        if binary:
            return sb - sa
        return math.log(sb / sa) if sa > 0 and sb > 0 else 0.0

    obs = stat(groups)
    rng = random.Random(seed)
    hits = 0
    for _ in range(n):
        split = []
        for vals, k in groups:
            v = vals[:]
            rng.shuffle(v)
            split.append((v, k))
        if abs(stat(split)) >= abs(obs) - 1e-12:
            hits += 1
    return hits / n


# ---------------------------------------------------------------- tables

def arm_table(g) -> str:
    head = ("| Arm | Sessions | Right file first | Right function | Turns: median / sum | Seconds: median / sum | "
            "Tokens, all: median / sum | Cost $: median / sum | search_code calls per session |\n"
            "|---|---|---|---|---|---|---|---|---|")
    lines = [head]
    for arm in ARMS:
        rs = sessions(g, arm)
        if not rs:
            continue
        fn = [r for r in rs if r.get("gold_fn_full") is not None]
        sec = [val(r, "seconds") for r in rs]
        calls = [r.get("n_searches") or 0 for r in rs]
        lines.append(f"| `{arm}` | {len(rs)} | {sum(val(r, 'file') for r in rs)} | {sum(val(r, 'function') for r in fn)} of {len(fn)} | "
                     f"{f(med([val(r, 'turns') for r in rs]), 1)} / {f(tot([val(r, 'turns') for r in rs]))} | "
                     f"{f(med(sec), 1)} / {f(tot(sec))}" + (f" ({sum(x is None for x in sec)} set aside)" if any(x is None for x in sec) else "") +
                     f" | {f(med([val(r, 'tokens') for r in rs]))} / {f(tot([val(r, 'tokens') for r in rs]))} | "
                     f"{money(med([val(r, 'cost') for r in rs]))} / {money(tot([val(r, 'cost') for r in rs]))} | "
                     f"{statistics.mean(calls):.2f} |")
    return "\n".join(lines)


def class_table(g) -> str:
    lines = ["| Arm | New input: median / sum | Cache write: median / sum | Cache read: median / sum | Output: median / sum |",
             "|---|---|---|---|---|"]
    for arm in ARMS:
        rs = sessions(g, arm)
        if not rs:
            continue
        cells = []
        for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
            xs = [val(r, k) for r in rs]
            cells.append(f"{f(med(xs))} / {f(tot(xs))}")
        lines.append(f"| `{arm}` | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def pair_row(name, pairs, A=None, B=None) -> str:
    cells = []
    for m in MEASURES:
        lo, eq, hi = lower_equal_higher(pairs, m)
        rt = ratio(pairs, m)
        cells.append(f"{lo} / {eq} / {hi} ({'-' if rt is None else f'{rt:.2f}'})")
    q = []
    for m in ("file", "function"):
        ps = [(val(a, m), val(b, m)) for a, b in pairs]
        ps = [(x, y) for x, y in ps if x is not None and y is not None]
        q.append(f"{sum(y > x for x, y in ps)} / {sum(y == x for x, y in ps)} / {sum(y < x for x, y in ps)}")
    p = ""
    if A is not None:
        ps = [perm_p(A, B, m) for m in MEASURES + ("file", "function")]
        p = " | " + ", ".join("-" if x is None else f"{x:.2f}" for x in ps)
    return f"| {name} | {len(pairs)} | " + " | ".join(cells) + " | " + " | ".join(q) + p + " |"


def pair_table(g, two_runs: bool) -> str:
    head = ("| Pairs on the same task: B against A | Pairs | Turns: B lower / equal / higher (sum B / sum A) | Tokens | "
            "Cost | Seconds (within 5% = equal) | Right file first: B better / same / worse | Right function | "
            "p: turns, tokens, cost, seconds, file, function |\n|---|---|---|---|---|---|---|---|---|")
    lines = [head]
    comps = [("v3-tool", "v2-tool"), ("v3", "v2"), ("v2", "v2-tool"), ("v3", "v3-tool"),
             ("v2-tool", "grep"), ("v3-tool", "grep"), ("v2", "grep"), ("v3", "grep")]
    for b, a in comps:
        A, B = g[a], g[b]
        pairs = matched(A, B)
        if pairs:
            lines.append(pair_row(f"`{b}` against `{a}`", pairs, A, B))
    if two_runs:
        for arm in ARMS:
            pairs = same_arm(g[arm])
            if pairs:
                lines.append(pair_row(f"noise: `{arm}` run 2 against run 1", pairs) + " |")
    return "\n".join(lines)


def use_table(g) -> str:
    lines = ["| Arm | Sessions that searched (first call at turn 1) | search_code calls | Calls with intent / symptom / "
             "anchors / locations | Median characters of a call's arguments (of its query) | Calls asking k > 10 | "
             "Median characters of a result | First search: right file in its results (right function) | "
             "First search: median rank of the right file | Calls that failed in these sessions (of them: no `query`) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for arm in ("v2-tool", "v3-tool", "v2", "v3"):
        rs = sessions(g, arm)
        if not rs:
            continue
        calls = [c for r in rs for c in search_calls(r)]
        filled = [sum(1 for c in calls if c.get(k)) for k in NEW_INPUTS]
        res = [c.get("result_chars") for r in rs for c in r.get("calls") or [] if c.get("kind") == "search_code"]
        lines.append(f"| `{arm}` | {sum(bool(r.get('called_search')) for r in rs)} of {len(rs)} "
                     f"({sum(r.get('first_search_turn') == 1 for r in rs)}) | {len(calls)} | "
                     + " / ".join(str(x) for x in filled) +
                     f" | {f(med([len(json.dumps(c)) for c in calls]))} ({f(med([len(c.get('query') or '') for c in calls]))}) | "
                     f"{sum(1 for c in calls if int(c.get('k') or 10) > 10)} | {f(med(res))} | "
                     f"{sum((r.get('first_gold_where') or {}).get('file') == 'card' for r in rs)} "
                     f"({sum((r.get('first_gold_where') or {}).get('function') == 'card' for r in rs)}) of "
                     f"{sum(bool(r.get('called_search')) for r in rs)} | {f(med([r.get('first_search_gold_file_rank') for r in rs]), 1)} | "
                     f"{sum(1 for r in rs for c in r.get('calls') or [] if c.get('kind') == 'search_code' and c.get('error'))} "
                     f"({sum(1 for r in rs for c in r.get('calls') or [] if c.get('kind') == 'search_code' and AGENT_ERROR in (c.get('result_head') or ''))})"
                     + (f"; and {len(dk)} discarded first attempts whose first call had no `query`" if (dk := [
                         d for rid, d in discarded_first_attempts().items() if rid in {r['run'] for r in rs}
                         and d['_discard_cause'] == 'agent']) else "") + " |")
    return "\n".join(lines)


def definitions_table(g) -> str:
    """The cost of codemem's definitions in each request: characters from the first request's body, tokens from
    the first request's input (all classes), the same task and run, against grep and v2-tool."""
    lines = ["| Arm | codemem tool definitions, characters (search_code's description) | Server instructions, characters | "
             "First request, input tokens: median | More than `grep`, same task: median | More than `v2-tool`, same task: median | "
             "Model requests per session: median |", "|---|---|---|---|---|---|---|"]
    fr = {arm: {t: first_request(reps[min(reps)]) for t, reps in g[arm].items()} for arm in ARMS}
    for arm in ARMS:
        if not fr[arm]:
            continue
        one = next(iter(fr[arm].values()))
        d_grep = [fr[arm][t]["input_total"] - fr["grep"][t]["input_total"] for t in fr[arm] if t in fr["grep"]]
        base = "v2-tool" if arm in ("v3-tool",) else "v2" if arm == "v3" else None
        d_v2 = [fr[arm][t]["input_total"] - fr[base][t]["input_total"] for t in fr[arm] if base and t in fr[base]]
        reqs = [x["requests"] for r in sessions(g, arm) for x in [first_request(r)]]
        lines.append(f"| `{arm}` | {f(one.get('tool_chars'))} ({f(one.get('search_code_description_chars'))}) | "
                     f"{f(one.get('instruction_chars'))} | {f(med([x['input_total'] for x in fr[arm].values()]))} | "
                     f"{f(med(d_grep)) if arm != 'grep' else '-'} | {f(med(d_v2)) if base else '-'} | {f(med(reqs))} |")
    return "\n".join(lines)


PARTS = [("s1", "Stage 1: Haiku, pandas (17 tasks, L2): grep once, each codemem arm twice", "pandas", "haiku", True),
         ("s2h", "Stage 2a: Haiku, vLLM (6 tasks, L2): grep once, each codemem arm twice", "vllm", "haiku", True),
         ("s2s", "Stage 2b: Sonnet, vLLM (6 tasks, L2): each arm once", "vllm", "sonnet", False),
         ("s3", "Stages 3 and 4: Sonnet, pandas (17 tasks, L2): each arm once; `v2` and `v3` a second time on 8 tasks "
                "(stage 4, until the cap of 340 sessions)", "pandas", "sonnet", False)]


def part(recs, key, title, taskset, model, two) -> str | None:
    g = group(recs, taskset, model)
    if not any(g[a] for a in ARMS):
        return None
    two = two or any(len(reps) > 1 for a in ARMS[1:] for reps in g[a].values())
    n = sum(len(sessions(g, a)) for a in ARMS)
    disc = [r for r in discarded_first_attempts().values() if ("vllm" in r["task"]) == (taskset == "vllm")
            and r["model"].startswith(f"claude-{model}")]
    extra = ""
    if disc:
        by = {}
        for r in disc:
            by.setdefault((r["arm"], r["_discard_cause"]), []).append(r["run"])
        extra = ("\n\nDiscarded by the harness and run again: " + "; ".join(
            f"`{a}` {len(v)} ({'the first search_code call left out `query`: a validation error, the server alive' if c == 'agent' else 'the server'})"
            for (a, c), v in sorted(by.items())) + ".")
        if any(r["_discard_cause"] == "agent" for r in disc):
            g1 = group(records("first"), taskset, model)
            rows = [pair_row(f"`{b}` against `{a}`, first attempts", matched(g1[a], g1[b]), g1[a], g1[b])
                    for b, a in (("v3-tool", "v2-tool"), ("v3", "v2"), ("v3-tool", "grep"), ("v3", "grep"))
                    if matched(g1[a], g1[b])]
            extra += (" compare.py reads such a call as a server that died, so its rule replaces these sessions "
                      "by new runs. Counted with their first attempts instead:\n\n" + pair_table(g, False).split("\n")[0]
                      + "\n|---|---|---|---|---|---|---|---|---|\n" + "\n".join(rows))
    return (f"### {title}\n\n{n} sessions. Right file first: the answer's first file is a file of the fix. Right "
            f"function: a function of the fix named (the harness's full-name rule).\n\n{arm_table(g)}\n\nTokens by class "
            f"(new input, cache write, cache read, output):\n\n{class_table(g)}\n\nPairs on the same task. Each cell: B "
            f"lower / equal / higher than A, then in brackets the sum of B over the sum of A. p: a permutation test within "
            f"each task (the arm labels of the task's sessions shuffled, 5,000 times; two-sided), so it measures the gap "
            f"against the spread between runs. Noise rows: the second run of an arm against its first, on the same task.\n\n"
            f"{pair_table(g, two)}{extra}\n\nUse of search_code:\n\n{use_table(g)}\n\nWhat codemem's definitions add to each request:\n\n"
            f"{definitions_table(g)}\n")


def build(note: str) -> dict[str, str]:
    recs = records()
    out = {}
    for key, title, taskset, model, two in PARTS:
        text = part(recs, key, title, taskset, model, two)
        if text:
            out[key] = text
    out["_note"] = f"Tables written {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}: {note}. {len(recs)} finished sessions."
    return out


SKELETON = """# v3 (PR #85, `4902671`) against v2 (`main`, `463171c`): an independent check with Haiku and Sonnet

<!-- answer: start -->
(The answer comes here when the first stage is done.)
<!-- answer: end -->

<!-- note: start -->
<!-- note: end -->

<!-- s1: start -->
<!-- s1: end -->

<!-- s2h: start -->
<!-- s2h: end -->

<!-- s2s: start -->
<!-- s2s: end -->

<!-- s3: start -->
<!-- s3: end -->
"""


def write(parts: dict[str, str]) -> None:
    text = REPORT.read_text() if REPORT.exists() else SKELETON
    for key, body in [("note", parts.pop("_note"))] + list(parts.items()):
        a, b = f"<!-- {key}: start -->", f"<!-- {key}: end -->"
        if a not in text:
            text += f"\n{a}\n{b}\n"
        i, j = text.index(a) + len(a), text.index(b)
        text = text[:i] + "\n" + body.rstrip() + "\n" + text[j:]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text)


def main():
    args = sys.argv[1:]
    if args and args[0] == "--print":
        parts = build(" ".join(args[1:]) or "printed")
        print(parts.pop("_note"))
        for k, v in parts.items():
            print(v)
        return
    write(build(" ".join(args) or "update"))


if __name__ == "__main__":
    main()
