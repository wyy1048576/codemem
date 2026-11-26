"""Hops from each far-missed gold file to the nearest top-50 file, over the import graph and the call graph.

Import graph: file A - file B if either includes/imports the other, or they are a C/C++ header/source pair.
Call graph: file A - file B if a function in A calls a name defined in B (name match, names with at most
max_defs_per_name definitions in the language family, as codemem links calls). Both undirected.
Usage: python gold_distance.py
"""
import collections as C, json, os, posixpath as pp, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import build_links as B

ROOT = Path(__file__).parent
TASKS = {"duckdb": "fresh-cpp-v1-68.jsonl", "pandas": "fresh-v1-py100.jsonl"}
WANT = [("duckdb", "25101"), ("duckdb", "24752"), ("duckdb", "25042"), ("pandas", "71334"), ("pandas", "70107")]
ARMS = {"whole": "arc-diag", "oneshot": "arc-diag", "diagnose": "arc-diag"}
tasks = {}
for f in TASKS.values():
    for l in open(ROOT.parent.parent / "codemem-7c24558/eval/tasks" / f, encoding="utf8"):
        t = json.loads(l); tasks[t["id"]] = t

def graphs(repo_name, sha):
    repo = Path.home() / ".cmeval/repos" / (repo_name.replace("/", "__") + ".git")
    entries = [e for e in B.git_tree(repo, sha) if e[1] == "blob" and e[0] != "120000"]
    cfg = [(e[2], e[4]) for e in entries if pp.basename(e[4]) == ".gitignore" or re.fullmatch(r"[tj]sconfig[^/]*\.json", pp.basename(e[4])) or (pp.basename(e[4]) == "package.json" and "node_modules/" not in e[4])]
    texts = {o: d.decode("utf-8", "replace") for o, d in B.read_blobs(repo, list(dict.fromkeys(o for o, _ in cfg)))}
    rules = B.BlobIgnore({pp.dirname(p): texts.get(o, "") for o, p in cfg if pp.basename(p) == ".gitignore"})
    sel = {p: o for _, _, o, s, p in entries if os.path.splitext(p)[1].lower() in B.EXTS and rules.allows(p) and s <= B.CFG.max_file_size}
    cache = B.ParseCache(ROOT.parent / "out-arms/parse" / (repo_name.replace("/", "__") + ".sqlite"))
    keys = {p: f"{B.PARSE_VERSION}|{o}|{p}" for p, o in sel.items()}
    missing = cache.get_many(list(keys.values()))
    assert not missing, len(missing)
    rec = {p: cache.memo[k] for p, k in keys.items() if "chunks" in cache.memo[k]}
    res = B.Resolver(set(rec), {p: texts.get(o, "") for o, p in cfg if p.endswith(".json") and pp.basename(p) != "package.json"}, {p: texts.get(o, "") for o, p in cfg if pp.basename(p) == "package.json"})
    imp = C.defaultdict(set)
    for p, r in rec.items():
        for it in r["imports"]:
            ts = res.python(p, *it) if r["language"] == "python" else res.typescript(p, it) if r["language"] in B.JS_LANGS else res.include(p, *it)
            for t in ts:
                if t != p: imp[p].add(t); imp[t].add(p)
    for p in list(rec):
        if p.endswith(B.C_SOURCE):
            stem = pp.splitext(pp.basename(p))[0]
            for t in list(imp[p]):
                if t.endswith(B.C_HEADER) and pp.splitext(pp.basename(t))[0] == stem: imp[p].add(t); imp[t].add(p)
    defs = C.defaultdict(set)
    for p, r in rec.items():
        for c in r["chunks"]:
            if c[1] in B.CALLABLE_KINDS: defs[(r["family"], c[2])].add(p)
    call = C.defaultdict(set)
    for p, r in rec.items():
        for c in r["chunks"]:
            for name in c[6]:
                ds = defs.get((r["family"], name), ())
                if 0 < len(ds) <= B.CFG.max_defs_per_name:
                    for d in ds:
                        if d != p: call[p].add(d); call[d].add(p)
    return imp, call

def bfs(g, start, targets):
    seen, frontier, prev = {start: 0}, [start], {}
    while frontier:
        nxt = []
        for u in frontier:
            if u in targets:
                path = [u]
                while path[-1] != start: path.append(prev[path[-1]])
                return seen[u], path[::-1]
            for v in g.get(u, ()):
                if v not in seen: seen[v] = seen[u] + 1; prev[v] = u; nxt.append(v)
        frontier = nxt
    return None, []

hits = {}
for arm, suf in ARMS.items():
    for repo in TASKS:
        for l in open(Path.home() / f".cmeval/runs/{repo}-{suf}/{arm}.jsonl", encoding="utf8"):
            r = json.loads(l); hits[(arm, r["task_id"])] = {h["path"] for h in r["hits"][:50]}
done = {}
for repo, num in WANT:
    tid = next(t for t in tasks if t.endswith(f"-{num}") and repo in t)
    t = tasks[tid]
    key = (t["repo"], t["base_commit"])
    if key not in done: done[key] = graphs(*key)
    imp, call = done[key]
    print(f"\n### {tid}  (import degree / call degree of gold file shown per file)")
    for gold in t["gold"]["files"]:
        print(f"  gold {gold}: imports {len(imp.get(gold, ()))}, call links {len(call.get(gold, ()))}")
        for arm in ARMS:
            top = hits[(arm, tid)]
            if gold in top: print(f"    {arm:9} in top 50"); continue
            di, pi = bfs(imp, gold, top); dc, pc = bfs(call, gold, top)
            print(f"    {arm:9} import hops {di} via {' -> '.join(pi)}")
            print(f"    {'':9} call hops   {dc} via {' -> '.join(pc)}")
