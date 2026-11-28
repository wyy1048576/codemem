"""One line per session of the v3-against-v2 check, for reading (the worked example, odd sessions).
usage: blockv3_rows.py <pandas|vllm> <haiku|sonnet> [task suffix] [--calls]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import blockv3_report as R  # noqa: E402


def main():
    taskset, model = sys.argv[1], sys.argv[2]
    only = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else None
    calls = "--calls" in sys.argv
    g = R.group(R.records(), taskset, model)
    tasks = sorted({t for a in R.ARMS for t in g[a]})
    for t in tasks:
        if only and not t.endswith(only):
            continue
        print(f"== {t}")
        for arm in R.ARMS:
            for rep, r in sorted((g[arm].get(t) or {}).items()):
                sc = R.search_calls(r)
                filled = ",".join(k for k in R.NEW_INPUTS if any(c.get(k) for c in sc))
                tok = r["tokens"]
                print(f"  {arm:8} r{rep} file1={int(bool(r.get('gold_file_first')))} fn={int(bool(r.get('gold_fn_full')))} "
                      f"turns={r['n_turns']:2} s={R.S.secs(r) or 0:5.1f} tok={tok['total']:7,} out={tok['output_tokens']:5,} "
                      f"${(r.get('result') or {}).get('total_cost_usd') or 0:.4f} searches={len(sc)} new={filled or '-'} "
                      f"files={r.get('files')} fns={(r.get('functions') or [])[:3]}")
                if calls:
                    for c in r.get("calls") or []:
                        extra = ""
                        if c["kind"] == "search_code":
                            extra = f"  -> {c.get('cards')} cards, gold file rank {c.get('gold_file_rank')}, fn rank {c.get('gold_fn_rank')}"
                        print(f"      t{c['turn']:2} {c['tool'][:28]:28} {c['arg'][:150]!r}{extra}")


if __name__ == "__main__":
    main()
