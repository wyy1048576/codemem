"""Stage 1 tables from the kept runs (s1_run.py), and the check that the lab's fusion of the kept
lists gives the product's own top 50 for every task (core.Fuser).

    ./run.sh s1_report.py
"""
from __future__ import annotations

import json
import sys

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import core as C
import lab_common as L

SETS = ["vllm-L0", "pandas-L0", "vague-L0", "vague-L1", "vague-L2"]


def run_name(name: str) -> str:
    return "pandas-L0" if name == "vague-L0" else name


def main() -> None:
    names = [n for n in (sys.argv[1:] or SETS)
             if list(L.OUT.glob(f"s1-{run_name(n)}.json")) or list(L.OUT.glob(f"s1-{run_name(n)}.[0-9]*.json"))]
    sets = L.query_sets(names)
    indexes: dict[str, L.Index] = {}
    fusers: dict[str, C.Fuser] = {}
    report: dict = {}
    for name in names:
        repo = sets[name]["repo"]
        if repo not in indexes:
            indexes[repo] = L.Index(repo, vectors=False)
            fusers[repo] = C.Fuser(indexes[repo])
        ix, fu = indexes[repo], fusers[repo]
        run = C.load_run(run_name(name), ix)
        tasks = sets[name]["tasks"]
        same50 = same10 = 0
        per_task = {}
        for t in tasks:
            r = run[t["id"]]
            lab, _ = fu.baseline(r)
            same50 += list(lab[:50]) == r["product"].tolist()
            same10 += list(lab[:10]) == r["product"][:10].tolist()
            files, fns = ix.gold_rows(t)
            per_task[t["id"]] = {
                "file_rank": C.first_rank(r["product"], files, ix.file_of) if files else None,
                "fn_rank": C.first_rank(r["product"], fns) if fns else None,
                "has_file": bool(files), "has_fn": bool(fns),
            }
        n_files = sum(len(t["gold_files"]) for t in tasks)
        n_fns = sum(len(t["gold_fns"]) for t in tasks)
        lab = {
            "tasks": len(tasks),
            "gold_files": n_files, "gold_files_in_snapshot": sum(sum(p in ix.file_no for p in t["gold_files"]) for t in tasks),
            "gold_functions": n_fns, "gold_functions_in_snapshot": sum(sum(s in ix.symbol_rows for s in t["gold_fns"]) for t in tasks),
            "tasks_no_function_label": sum(not t["gold_fns"] for t in tasks),
            "tasks_with_file": sum(v["has_file"] for v in per_task.values()),
            "tasks_with_fn": sum(v["has_fn"] for v in per_task.values()),
            "lab_equals_product_top50": same50, "lab_equals_product_top10": same10,
            "search_ms_median": float(np.median([run[t["id"]]["ms"]["total"] for t in tasks])),
        }
        m = {}
        for kind, has, key in (("file", "has_file", "file_rank"), ("fn", "has_fn", "fn_rank")):
            ranks = [v[key] for v in per_task.values() if v[has]]
            for k in (5, 10, 15, 20, 30, 50):
                m[f"{kind}@{k}"] = sum(C.hit(x, k) for x in ranks)
            m[f"{kind}_mrr"] = float(np.mean([1.0 / x if x else 0.0 for x in ranks])) if ranks else 0.0
        report[name] = {"labels": lab, "metrics": m, "per_task": per_task}
    (L.OUT / "s1-report.json").write_text(json.dumps(report, indent=1), "utf-8")

    print("| set | tasks | gold files in the snapshot | gold functions in the snapshot | tasks with no function label | "
          "tasks with a gold file / function in the snapshot | lab fusion = product's top 50 | search ms (median) |")
    print("|---|---|---|---|---|---|---|---|")
    for name, v in report.items():
        b = v["labels"]
        print(f"| {name} | {b['tasks']} | {b['gold_files_in_snapshot']} of {b['gold_files']} | {b['gold_functions_in_snapshot']} of "
              f"{b['gold_functions']} | {b['tasks_no_function_label']} | {b['tasks_with_file']} / {b['tasks_with_fn']} | "
              f"{b['lab_equals_product_top50']} of {b['tasks']} | {b['search_ms_median']:.0f} |")
    print()
    for kind, label, ks in (("file", "a gold file", (5, 10, 20, 50)), ("fn", "a gold function", (5, 10, 20, 50))):
        print(f"| set ({label}) | tasks | " + " | ".join(f"top {k}" for k in ks) + " | MRR |")
        print("|---|---|" + "---|" * len(ks) + "---|")
        for name, v in report.items():
            n = v["labels"]["tasks_with_file" if kind == "file" else "tasks_with_fn"]
            cells = [f"{v['metrics'][f'{kind}@{k}']} ({100 * v['metrics'][f'{kind}@{k}'] / max(1, n):.0f}%)" for k in ks]
            print(f"| {name} | {n} | " + " | ".join(cells) + f" | {v['metrics'][f'{kind}_mrr']:.3f} |")
        print()
    ks = (10, 15, 20, 30)
    print("| set | tasks (file / function) | file in top " + " / ".join(map(str, ks)) + " | function in top " + " / ".join(map(str, ks)) + " |")
    print("|---|---|---|---|")
    for name, v in report.items():
        b, m = v["labels"], v["metrics"]
        print(f"| {name} | {b['tasks_with_file']} / {b['tasks_with_fn']} | " + " / ".join(str(m[f'file@{k}']) for k in ks)
              + " | " + " / ".join(str(m[f'fn@{k}']) for k in ks) + " |")


if __name__ == "__main__":
    main()
