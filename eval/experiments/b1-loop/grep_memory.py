"""Does the grep agent reach gold code using names it could only know from memory?

Per finished grep run (out/e2e-all/<task>/grep.jsonl):
  names in its search patterns (identifier-like tokens, >= 4 chars) are "new" if they appear neither in the
  issue text nor in any earlier tool result (case-insensitive);
  first gold contact = first tool call whose input path is a gold file, or whose result lists a gold file;
  that contact is "blind" when the call names the gold file (path) before any result showed it,
  or its search pattern has a new name and the result is the first to show a gold file.
"""
import json, re, sys
from pathlib import Path

ROOT = Path(sys.argv[1])
tasks = {}
for f in ("codemem-7c24558/eval/tasks/fresh-cpp-v1-68.jsonl", "codemem-7c24558/eval/tasks/fresh-v1-py100.jsonl"):
    for l in open(ROOT / f, encoding="utf8"):
        t = json.loads(l); tasks[t["id"]] = t
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
STOP = {"path", "self", "true", "false", "none", "return", "const", "auto", "void", "class", "struct", "def",
        "import", "from", "with", "this", "pandas", "duckdb", "test", "tests"}


def norm(p):
    p = p.replace("\\", "/")
    m = re.search(r"e2e-copies/[^/]+/(.*)", p)
    return m.group(1) if m else p


rows = []
for d in sorted((ROOT / "b1-links/llm_query/out/e2e-all").iterdir()):
    g = d / "grep.jsonl"
    if not (d / "grep.summary.json").exists() or not g.exists():
        continue
    t = tasks[d.name]
    gold = set(t["gold"]["files"])
    seen = t["query"].lower()
    calls, new_names, all_names = 0, set(), set()
    first = None
    pending = {}
    for line in open(g, encoding="utf8"):
        e = json.loads(line)
        if e.get("type") == "assistant":
            for c in e["message"]["content"]:
                if c.get("type") == "tool_use":
                    calls += 1
                    inp = c["input"]
                    pat = inp.get("pattern", "") if c["name"] in ("Grep", "Glob") else ""
                    names = {n for n in IDENT.findall(pat) if n.lower() not in STOP}
                    new = {n for n in names if n.lower() not in seen}
                    all_names |= names; new_names |= new
                    path = norm(inp.get("file_path") or inp.get("path") or "")
                    pending[c["id"]] = (calls, c["name"], path, pat, new)
                    if first is None and path in gold:
                        first = {"call": calls, "tool": c["name"], "how": "named path",
                                 "blind": path.lower() not in seen and Path(path).name.lower() not in seen, "pattern": pat}
        if e.get("type") == "user":
            for c in e["message"]["content"]:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    txt = c["content"] if isinstance(c["content"], str) else json.dumps(c["content"])
                    txt_n = txt.replace("\\", "/")
                    n, tool, path, pat, new = pending.get(c["tool_use_id"], (None,) * 5)
                    if first is None and tool in ("Grep", "Glob") and any(gf in txt_n for gf in gold):
                        first = {"call": n, "tool": tool, "how": "search result", "blind": bool(new),
                                 "pattern": pat, "new_names": sorted(new)}
                    seen += "\n" + txt.lower()
    s = json.loads((d / "grep.summary.json").read_text(encoding="utf8"))
    rows.append({"task": d.name, "calls": calls, "cost": round(s["cost_usd"], 3), "names": len(all_names),
                 "new_names": len(new_names), "first_gold": first})

for r in rows:
    f = r["first_gold"] or {}
    print(f"{r['task']:30} calls {r['calls']:3} ${r['cost']:.2f} names {r['names']:3} new {r['new_names']:3}  "
          f"first gold @ {f.get('call', '-')} {f.get('how', '')} blind={f.get('blind', '-')} {str(f.get('new_names', ''))[:60]} {f.get('pattern', '')[:70]!r}")
n = len(rows)
print(f"\n{n} runs; first gold contact at call 1: {sum(1 for r in rows if (r['first_gold'] or {}).get('call') == 1)}; "
      f"blind first contact: {sum(1 for r in rows if (r['first_gold'] or {}).get('blind'))}; never: {sum(1 for r in rows if not r['first_gold'])}")
print(f"new names / all pattern names: {sum(r['new_names'] for r in rows)} / {sum(r['names'] for r in rows)}")
json.dump(rows, open(Path(sys.argv[2]), "w"), indent=1)
