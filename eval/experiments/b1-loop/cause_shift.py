"""How each arm handles the gold files whole issue (or revised) missed, by cause A-E.

Reads the cause of each missed gold file from per_gold_file.md, and the per-file buckets of two
per_gold_file.py outputs (the first run's whole/oneshot/revise, and the diagnosis run's arms).
A gold file that an arm misses but per_gold_file.md has no cause for is listed as "new miss".

Usage: python cause_shift.py PER_GOLD_FILE.md LLM.json DIAG.json
"""
from __future__ import annotations

import collections as C
import json
import re
import sys

md, first, diag = sys.argv[1:4]
causes = {}
for line in open(md, encoding="utf8"):
    m = re.match(r"\| (duckdb|pandas)-(\d+) \| `([^`]+)` \|.*\| ([A-E]) \|", line)
    if m:
        causes[(m[1], m[2], m[3])] = m[4]
assert len(causes) == 27, len(causes)

status = C.defaultdict(dict)  # (repo, number, path) -> arm -> "rank N" | "near" | "far"
for path, prefix in ((first, ""), (diag, "")):
    for r in json.load(open(path, encoding="utf8"))["rows"]:
        key = (r["repo"], r["task"].rsplit("-", 1)[1], r["path"])
        value = f"rank {r['file_rank']}" if "file_rank" in r else ("near" if r["bucket"] == "near_one_import" else r["bucket"])
        if r["arm"] in status[key] and status[key][r["arm"]] != value:
            status[key][r["arm"] + "(rerun)"] = value
        else:
            status[key][r["arm"]] = value


def cause_of(key):
    repo, number, path = key
    hits = [c for (r, n, short), c in causes.items() if r == repo and n == number and path.endswith(short)]
    return hits[0] if len(hits) == 1 else None


ARMS = ("whole", "oneshot", "revise", "diagnose-base", "diagnose", "loop", "loop-full")
missed = {arm: [k for k, s in status.items() if arm in s and not s[arm].startswith("rank")] for arm in ARMS}
print("rerun differences (should be none):", {k: s for k, s in status.items() if any(a.endswith("(rerun)") for a in s)})
print("\nmissed gold files by cause")
print("cause".ljust(10), *(a.rjust(14) for a in ARMS))
for cause in "ABCDE":
    print(cause.ljust(10), *(str(sum(cause_of(k) == cause for k in missed[a])).rjust(14) for a in ARMS))
print("new miss".ljust(10), *(str(sum(cause_of(k) is None for k in missed[a])).rjust(14) for a in ARMS))
print("total".ljust(10), *(str(len(missed[a])).rjust(14) for a in ARMS))
for arm in ("loop-full", "loop"):
    for ref in ("whole", "oneshot", "diagnose", "loop"):
        rec = [k for k in missed[ref] if k not in missed[arm]]
        lost = [k for k in missed[arm] if k not in missed[ref]]
        print(f"\n{arm} vs {ref}: recovered {len(rec)} {dict(C.Counter(cause_of(k) or 'new' for k in rec))}, "
              f"lost {len(lost)} {dict(C.Counter(cause_of(k) or 'new' for k in lost))}")
        for k in lost:
            print("   lost:", k, status[k])
print("\nper file (27 with a cause, plus new misses)")
keys = sorted(set(k for k in status if cause_of(k)) | {k for a in ARMS for k in missed[a]})
for k in keys:
    print(f"{k[0]}-{k[1]} | {k[2]} | {cause_of(k) or 'new'} | " + " | ".join(status[k].get(a, "?") for a in ARMS))
