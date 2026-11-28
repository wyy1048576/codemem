"""Per task: the mean of each arm's runs (turns, tokens, cost, seconds), and how often each arm searched, for reading
where a difference between two arms comes from. usage: blockv3_tasks.py <pandas|vllm> <haiku|sonnet> <arm B> <arm A>"""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import blockv3_report as R  # noqa: E402


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def main():
    taskset, model, b, a = sys.argv[1:5]
    g = R.group(R.records(), taskset, model)
    print(f"{'task':6} | {a:>8} turns tok cost searches | {b:>8} turns tok cost searches | tokens B/A | runs of A differ by | of B")
    for t in sorted(set(g[a]) & set(g[b])):
        ra, rb = list(g[a][t].values()), list(g[b][t].values())

        def cells(rs):
            return (mean([R.val(r, "turns") for r in rs]), mean([R.val(r, "tokens") for r in rs]),
                    mean([R.val(r, "cost") for r in rs]), mean([len(R.search_calls(r)) for r in rs]))

        ca, cb = cells(ra), cells(rb)

        def spread(rs):
            v = [R.val(r, "tokens") for r in rs]
            return f"{max(v) / min(v):.2f}x" if len(v) > 1 and min(v) else "-"

        print(f"{t[-5:]:6} | {ca[0]:5.1f} {ca[1]:7,.0f} {ca[2]:.4f} {ca[3]:.1f} | {cb[0]:5.1f} {cb[1]:7,.0f} {cb[2]:.4f} "
              f"{cb[3]:.1f} | {cb[1] / ca[1]:.2f} | {spread(ra)} | {spread(rb)}")


if __name__ == "__main__":
    main()
