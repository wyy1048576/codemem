"""Where do the one-hop picks (hop_retriever.py) sit relative to the top-50 result they came from?
same file / a file one import away from it (imports, imported-by, C++ .h/.cpp partner and its imports) / other.
A pick reached from several results is counted once, against the first (best-ranked) one.
Usage: python hop_where.py
"""
NL = chr(10)
import collections as C, json, os, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
sys.argv = [sys.argv[0], "x", "x"]
src = (HERE.parent / "hop_coverage.py").read_text(encoding="utf8").split("\nrows = []")[0]
exec(compile(src, "hop_coverage_defs", "exec"))
TASKS = HERE.parent.parent / "codemem-7c24558" / "eval" / "tasks"
ARMS = {"whole": "arc-hop", "oneshot": "arc-hop", "revise": "arc-hop2", "diagnose": "arc-hop2", "loop": "arc-hop", "loop-full": "arc-hop"}
if __name__ == "__main__":
    tasks = {json.loads(x)["id"]: json.loads(x) for f in TASKS.glob("fresh-*.jsonl") for x in f.read_text(encoding="utf8").split(NL) if x.strip()}
    total = {a: C.Counter() for a in ARMS}
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1)) as pool:
        for repo, slug in (("duckdb", "duckdb__duckdb"), ("pandas", "pandas-dev__pandas")):
            cache = bl.ParseCache(HERE.parent / "out-arms" / "parse" / f"{slug}.sqlite")
            graphs = {}
            for arm, suf in ARMS.items():
                for line in (Path.home() / ".cmeval" / "runs" / f"{repo}-{suf}" / f"hop-{arm}.jsonl").read_text(encoding="utf8").split(NL)[:-1]:
                    r = json.loads(line)
                    sha = tasks[r["task_id"]]["base_commit"]
                    if sha not in graphs:
                        graphs[sha] = graph(REPOS / f"{slug}.git", sha, cache, pool)
                    out_e, in_e, partners, _ = graphs[sha]
                    hits = r["hits"]
                    for h in hits[50:]:
                        seed = hits[h["extra"]["seed_rank"] - 1]["path"]
                        if h["path"] == seed:
                            total[arm]["same_file"] += 1
                        elif h["path"] in neighbours(seed, out_e, in_e, partners):
                            total[arm]["one_import_away"] += 1
                        else:
                            total[arm]["other"] += 1
            cache.db.close()
    print(json.dumps(total, indent=1))
