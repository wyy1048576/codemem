"""Ranks of the first gold file and the first gold function in a result list, and the tables made of them."""
from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L


def first_ranks(index: L.Index, task: dict, rows: list[int] | np.ndarray) -> tuple[int | None, int | None]:
    """1-based place of the first result in a gold file, and of the first result that is a gold function."""
    files, fns = index.gold_rows(task)
    rf = rn = None
    for place, row in enumerate(rows, start=1):
        row = int(row)
        if rf is None and int(index.file_of[row]) in files:
            rf = place
        if rn is None and row in fns:
            rn = place
        if rf is not None and rn is not None:
            break
    return rf, rn


def label_counts(index: L.Index, tasks: list[dict]) -> dict:
    n_files = sum(len(t["gold_files"]) for t in tasks)
    n_fns = sum(len(t["gold_fns"]) for t in tasks)
    files_in = sum(len([p for p in t["gold_files"] if p in index.file_no]) for t in tasks)
    fns_in = sum(len([s for s in t["gold_fns"] if s in index.symbol_rows]) for t in tasks)
    return {
        "tasks": len(tasks),
        "gold_files": n_files, "gold_files_in_snapshot": files_in,
        "gold_functions": n_fns, "gold_functions_in_snapshot": fns_in,
        "tasks_with_no_gold_function_label": sum(not t["gold_fns"] for t in tasks),
        "tasks_with_a_gold_file_in_snapshot": sum(bool(index.gold_rows(t)[0]) for t in tasks),
        "tasks_with_a_gold_function_in_snapshot": sum(bool(index.gold_rows(t)[1]) for t in tasks),
    }


def table(index: L.Index, tasks: list[dict], results: dict[str, list[int]], ks=(5, 10, 20, 50)) -> dict:
    """results: task id -> rows in rank order (at least max(ks) of them where the search has that many)."""
    file_ranks, fn_ranks = [], []
    for t in tasks:
        files, fns = index.gold_rows(t)
        rf, rn = first_ranks(index, t, results[t["id"]])
        if files:
            file_ranks.append(rf)
        if fns:
            fn_ranks.append(rn)
    out = {"file_tasks": len(file_ranks), "fn_tasks": len(fn_ranks)}
    for label, ranks in (("file", file_ranks), ("fn", fn_ranks)):
        for k in ks:
            out[f"{label}@{k}"] = sum(r is not None and r <= k for r in ranks)
        out[f"{label}_mrr"] = float(np.mean([1.0 / r if r else 0.0 for r in ranks])) if ranks else 0.0
    return out


def fmt_row(name: str, m: dict, ks=(5, 10, 20, 50)) -> str:
    cells = [name, str(m["file_tasks"])]
    cells += [f"{m[f'file@{k}']} ({100 * m[f'file@{k}'] / max(1, m['file_tasks']):.0f}%)" for k in ks]
    cells += [f"{m['file_mrr']:.3f}", str(m["fn_tasks"])]
    cells += [f"{m[f'fn@{k}']} ({100 * m[f'fn@{k}'] / max(1, m['fn_tasks']):.0f}%)" for k in ks]
    cells += [f"{m['fn_mrr']:.3f}"]
    return "| " + " | ".join(cells) + " |"


def header(ks=(5, 10, 20, 50)) -> str:
    cols = ["set", "tasks with a gold file"] + [f"file in top {k}" for k in ks] + ["file MRR", "tasks with a gold function"]
    cols += [f"function in top {k}" for k in ks] + ["function MRR"]
    return "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols)
