"""Experiment 15: results grouped by file, each file with an outline of its functions (names, no
code). For the baseline's top 10: how many distinct files; whether a gold function's name would be
on the page without being one of the 10 results; and what the page costs (names, characters).
Beside it, the same reach for experiment 8 (3 relations per card) and for the names of results 11
to 30, on the same tasks.

    ./run.sh e15_outline.py
"""
from __future__ import annotations

import json
import sys

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import core as C
import lab_common as L
import s3_report as R

OUTLINE_KINDS = ("function", "method", "class")


def main() -> None:
    data = R.load()
    out = {}
    for repo, names in (("vllm", ["vllm-L0", "vllm-title"]), ("pandas", ["pandas-L0", "vague-L0", "vague-L1", "vague-L2", "pandas-title"])):
        ix = L.Index(repo, vectors=False)
        sets = L.query_sets(names)
        for name in names:
            run = C.load_run("pandas-L0" if name == "vague-L0" else name, ix)
            rows = []
            for t in sets[name]["tasks"]:
                files, fns = ix.gold_rows(t)
                if not fns:
                    continue
                top = [int(x) for x in run[t["id"]]["product"][:10]]
                top30 = [int(x) for x in run[t["id"]]["product"][:30]]
                tfiles = list(dict.fromkeys(int(ix.file_of[r]) for r in top))
                outline = [r for f in tfiles for r in ix.file_rows(f).tolist() if ix.kind[r] in OUTLINE_KINDS]
                hit10 = any(r in fns for r in top)
                on_page = hit10 or any(r in fns for r in outline)
                e8 = data.get(name, {}).get("e8|b99|both|r3", {}).get(t["id"])
                rows.append({
                    "half": t["half"], "hit10": hit10, "outline": on_page,
                    "outline_only": on_page and not hit10,
                    "files": len(tfiles), "names": len(outline),
                    "chars": sum(len(ix.qualname[r]) + 2 + len(str(int(ix.start[r]))) for r in outline) + sum(len(ix.paths[f]) for f in tfiles),
                    "top30": any(r in fns for r in top30),
                    "relations": bool(e8 and e8[0]),
                })
            for scope in ("all", "held"):
                sel = [r for r in rows if scope == "all" or r["half"] == 1 or name.startswith("vague")]
                b = np.array([r["hit10"] for r in sel], dtype=int)
                o = np.array([r["outline"] for r in sel], dtype=int)
                s, lo, hi = R.boot(o - b)
                res = {
                    "tasks": len(sel), "top10": int(b.sum()), "outline_reach": int(o.sum()), "gain": s, "ci": (lo, hi),
                    "files_mean": float(np.mean([r["files"] for r in sel])), "names_mean": float(np.mean([r["names"] for r in sel])),
                    "names_median": float(np.median([r["names"] for r in sel])), "chars_mean": float(np.mean([r["chars"] for r in sel])),
                    "top30_reach": int(sum(r["top30"] for r in sel)), "relations_reach": int(sum(r["relations"] for r in sel)),
                    "outline_or_relations": int(sum(r["outline"] or r["relations"] for r in sel)),
                }
                out[f"{name}|{scope}"] = res
                print(f"{name:13s} {scope:4s} tasks {res['tasks']:3d} | top10 {res['top10']} | outline page {res['outline_reach']} "
                      f"({s:+.0f}, {lo:+.0f}..{hi:+.0f}) | files {res['files_mean']:.1f}, names {res['names_mean']:.0f} (median "
                      f"{res['names_median']:.0f}), chars {res['chars_mean']:.0f} | relations {res['relations_reach']} | "
                      f"names of results 11-30 {res['top30_reach']} | outline or relations {res['outline_or_relations']}", flush=True)
                if name.startswith("vague"):
                    break
    (L.OUT / "e15-outline.json").write_text(json.dumps(out, indent=1), "utf-8")


if __name__ == "__main__":
    main()
