"""hybrid_v2 counts on e2e-b45 (tools per step, repeat greps, edits by gold-function count). Run from b1-loop/."""
import json, glob, collections as C
rep = runs = refused = cut = rev = 0; secs = []; firsts = C.Counter(); after = C.Counter(); long_runs = 0
for f in glob.glob("out/e2e-b45/L*/*/hybrid_v2.summary.json"):
    s = json.load(open(f, encoding="utf8")); runs += 1; rep += len(s["repeats"]); secs.append(s["seconds"])
    refused += sum(1 for h in s["history"] if h.get("refused")); cut += sum(1 for h in s["history"] if h.get("cut"))
    rev += s["tools"].get("review", 0); long_runs += s["rounds"] >= 10
    firsts[s["history"][0]["tool"]] += 1; after.update(h["tool"] for h in s["history"][1:])
print("runs", runs, "repeat greps", rep, "refused", refused, "greps over 40 lines", cut, "review steps", rev,
      "runs with 10+ steps", long_runs, "mean sec", round(sum(secs) / len(secs)), "first", dict(firsts), "later", dict(after))
sc = {(r["level"], r["task"], r["arm"]): r for r in json.load(open("out/e2e-b45/score.json", encoding="utf8")) if not r.get("missing")}
A = ("grep", "loopk_nc", "hybrid", "hybrid_v2")
for name, sel in (("1 gold", lambda g: g == 1), ("2+ gold", lambda g: g >= 2)):
    acc = C.Counter()
    for (lv, t, a), r in sc.items():
        if a in A and all((lv, t, x) in sc for x in A) and sel(r["gold"]):
            acc[a] += r["edited"]; acc[a + "_g"] += r["gold"]
    print(name, {a: (acc[a], acc[a + "_g"]) for a in A})
for old in ("hybrid", "grep"):
    w = l = 0
    for (lv, t, a), r in sc.items():
        if a == "hybrid_v2" and (lv, t, old) in sc:
            w += r["edited"] > sc[(lv, t, old)]["edited"]; l += r["edited"] < sc[(lv, t, old)]["edited"]
    print(f"hybrid_v2 vs {old}: more edited in {w} runs, fewer in {l}")
