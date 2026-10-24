"""Compare one system of one scored cmeval run against one system of another, task by task.

    cd eval && uv run python ../scripts/compare_scores.py \
        results/2026-10-23-dev50-final/scores.jsonl.gz cm-bm25-code-usage \
        $CMEVAL_HOME/runs/<run>/scores.jsonl cm2-bm25-code-usage

Only tasks scored in both runs count. Differences are B - A, with cmeval's paired bootstrap 95%
interval and two-sided Wilcoxon test (the same statistics as `cmeval report`). Token metrics
are skipped unless both runs counted tokens the same way (pass --tokens to include them).
Needs the eval environment (cmeval installed).
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict

from cmeval.metrics.stats import paired_bootstrap_ci, wilcoxon

ACCURACY = ("mrr", "recall@1", "recall@5", "recall@10", "recall@20", "success@10")
TOKENS = ("tokens_to_first", "recall@budget1000", "recall@budget4000")


def load(path: str, system: str, iou: float | None) -> dict[tuple[str, str], dict[str, float]]:
    """(level, metric) -> task id -> value, for one system."""
    out: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    opener = gzip.open if path.endswith(".gz") else open  # run folders hold plain scores.jsonl
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            # Excluded rows carry the reason ("no gold at this level") instead of a number.
            if row["system"] != system or not isinstance(row["value"], (int, float)):
                continue
            if row["level"] != "file" and row["iou"] != iou:
                continue
            out[(row["level"], row["metric"])][row["task_id"]] = float(row["value"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("scores_a")
    ap.add_argument("system_a")
    ap.add_argument("scores_b")
    ap.add_argument("system_b")
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--tokens", action="store_true", help="also compare token metrics")
    args = ap.parse_args()
    a = load(args.scores_a, args.system_a, args.iou)
    b = load(args.scores_b, args.system_b, args.iou)
    metrics = ACCURACY + (TOKENS if args.tokens else ())
    print(f"A = {args.system_a} ({args.scores_a})\nB = {args.system_b} ({args.scores_b})\n")
    print(f"{'level':9s} {'metric':18s} {'n':>3s} {'A':>7s} {'B':>7s} {'B-A':>7s}  {'95% CI':>17s}  {'p':>6s}")
    for level in ("file", "class", "function"):
        for metric in metrics:
            xa, xb = a.get((level, metric), {}), b.get((level, metric), {})
            tasks = sorted(set(xa) & set(xb))
            if not tasks:
                continue
            va, vb = [xa[t] for t in tasks], [xb[t] for t in tasks]
            mean_a, mean_b = sum(va) / len(va), sum(vb) / len(vb)
            ci = paired_bootstrap_ci(vb, va)  # interval of B - A
            p = wilcoxon([round(y - x, 9) for x, y in zip(va, vb)]).p
            p = 1.0 if p is None else p
            ci_text = f"[{ci[0]:+.3f}, {ci[1]:+.3f}]" if ci else "-"
            print(f"{level:9s} {metric:18s} {len(tasks):3d} {mean_a:7.3f} {mean_b:7.3f} {mean_b - mean_a:+7.3f}  {ci_text:>17s}  {p:6.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
