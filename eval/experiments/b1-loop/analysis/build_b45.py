"""Task set e2e-b45: every task of vague-b7-v3 (45 pandas / playwright tasks, valid and fair by the b7 screen),
with its L1 / L2 prompt as the query. Prints dates and gold-function counts.
Inputs (not in git): pandas.jsonl, playwright.jsonl and vague-b7-v3.jsonl, the vague-b7 task and prompt files, next to this script."""
import json, collections as C
from pathlib import Path
SCR = Path(__file__).parent
OUT = Path(__file__).resolve().parents[1] / "out" / "e2e-b45"
base = {}
for f in ("pandas.jsonl", "playwright.jsonl"):
    for l in (SCR / f).read_text(encoding="utf8").split(chr(10)):
        if l.strip():
            t = json.loads(l); base[t["id"]] = t
prompts = [json.loads(l) for l in (SCR / "vague-b7-v3.jsonl").read_text(encoding="utf8").split(chr(10)) if l.strip()]
dates, nf = [], C.Counter()
for level in ("L1", "L2"):
    rows = []
    for p in prompts:
        if p["level"] != level:
            continue
        t = dict(base[p["id"]])
        t["query_L0"], t["query"], t["level"] = t["query"], p["prompt"], level
        rows.append(t)
        if level == "L1":
            iss = t["issue"]; dates.append((iss.get("created_at") or "")[:10]); nf[len(t["gold"].get("functions", []))] += 1
    (OUT / f"tasks-{level}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf8")
    print(level, len(rows))
print("issue opened:", min(dates), "to", max(dates), "| keys", list(base[prompts[0]["id"]]["issue"].keys()))
print("gold functions per task:", dict(sorted(nf.items())))
