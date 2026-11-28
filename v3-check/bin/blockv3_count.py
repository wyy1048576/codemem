"""How far the v3-against-v2 check is: finished sessions per stage, the last one, the block's ledger count."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import blockv3_report as R  # noqa: E402

recs = R.records()
by = {}
for r in recs:
    by[r["block"]] = by.get(r["block"], 0) + 1
led = sum(1 for l in (R.RUNS / "ledger.jsonl").read_text().split("\n") if l.strip()
          and (e := json.loads(l)).get("block", "").startswith("v3s") and not e.get("fake"))
last = max(recs, key=lambda r: (r["_dir"] / "record.json").stat().st_mtime) if recs else None
print(f"finished {len(recs)} {by} | ledger {led} | last {last['run'] if last else None}")
