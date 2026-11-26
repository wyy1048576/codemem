"""Part 4, measured as experiment 11 was: test chunks take no place among the 10 cards (the cards are
the ranking with tests left out of every list, as `tests="exclude"`), and the best 5 test chunks
(the same three lists with only tests, fused) are named after the cards. Per set: a gold function in
the 10 cards, against today's 10; and the tasks where a named test is one call away from a gold
function (it calls one), with every edge and with callees over 100 callers left out.

    ./run.sh e16_tests_apart.py
"""
from __future__ import annotations

import json
import sys

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import core as C
import lab_common as L
import s3_report as R

N_TESTS = 5


def main() -> None:
    out = {}
    for repo, names in (("vllm", ["vllm-L0", "vllm-title"]), ("pandas", ["pandas-L0", "vague-L0", "vague-L1", "vague-L2", "pandas-title"])):
        ix = L.Index(repo, vectors=False)
        fu = C.Fuser(ix)
        m = ix.in_deg[ix.e_callee] <= 100
        op, o = ix._csr(ix.e_caller[m], ix.e_callee[m])
        ip, i_ = ix._csr(ix.e_callee[m], ix.e_caller[m])
        ix._graphs["k100"] = (op, o, ip, i_)
        sets = L.query_sets(names)
        for name in names:
            run = C.load_run("pandas-L0" if name == "vague-L0" else name, ix)
            rows = []
            for t in sets[name]["tasks"]:
                files, fns = ix.gold_rows(t)
                if not fns:
                    continue
                lists = run[t["id"]]["lists"]
                base = run[t["id"]]["product"][:10].tolist()
                src = {s: [r for r in lists[s].tolist() if not ix.is_test[r]][:50] for s in C.SIGNALS}
                tst = {s: [r for r in lists[s].tolist() if ix.is_test[r]][:50] for s in C.SIGNALS}
                cards, _ = fu.fuse([(s, src[s], 1.0) for s in C.SIGNALS])
                tests, _ = fu.fuse([(s, tst[s], 1.0) for s in C.SIGNALS])
                cards, tests = cards[:10], tests[:N_TESTS]
                calls = {v: {int(x) for r in tests for x in ix.neighbours(int(r), v, "callees")} for v in ("a", "k100")}
                rows.append({
                    "half": t["half"], "today": any(r in fns for r in base), "cards": any(r in fns for r in cards),
                    "tests_in_today": sum(bool(ix.is_test[r]) for r in base),
                    "test_calls_gold_a": bool(calls["a"] & fns), "test_calls_gold_k100": bool(calls["k100"] & fns),
                    "listed": len(tests),
                })
            for scope in ("all", "held"):
                sel = [r for r in rows if scope == "all" or r["half"] == 1 or name.startswith("vague")]
                b = np.array([r["today"] for r in sel], dtype=int)
                e = np.array([r["cards"] for r in sel], dtype=int)
                s, lo, hi = R.boot(e - b)
                reach = sum(r["cards"] or r["test_calls_gold_k100"] for r in sel)
                res = {"tasks": len(sel), "today": int(b.sum()), "cards": int(e.sum()), "diff": s, "ci": (lo, hi),
                       "won": int(((e - b) > 0).sum()), "lost": int(((e - b) < 0).sum()),
                       "tests_among_todays_10": float(np.mean([r["tests_in_today"] for r in sel])),
                       "named_test_calls_a_gold_function": int(sum(r["test_calls_gold_a"] for r in sel)),
                       "named_test_calls_a_gold_function_cap100": int(sum(r["test_calls_gold_k100"] for r in sel)),
                       "of_them_gold_not_in_cards": int(sum(r["test_calls_gold_k100"] and not r["cards"] for r in sel)),
                       "cards_or_a_named_test_calls_it": int(reach)}
                out[f"{name}|{scope}"] = res
                print(f"{name:13s} {scope:4s} tasks {res['tasks']:3d} | gold function in the 10 cards: today {res['today']}, tests apart "
                      f"{res['cards']} ({s:+.0f}, {lo:+.0f}..{hi:+.0f}; +{res['won']}/-{res['lost']}) | tests among today's 10: "
                      f"{res['tests_among_todays_10']:.1f} | a named test calls a gold function: {res['named_test_calls_a_gold_function']} "
                      f"(cap 100: {res['named_test_calls_a_gold_function_cap100']}; gold not in the cards: {res['of_them_gold_not_in_cards']}) | "
                      f"cards or a named test's callee: {res['cards_or_a_named_test_calls_it']}", flush=True)
                if name.startswith("vague"):
                    break
    (L.OUT / "e16-tests-apart.json").write_text(json.dumps(out, indent=1), "utf-8")


if __name__ == "__main__":
    main()
