"""Experiment 14: a keyword ranking over whole files, and experiment 15's outline capped per file.

A scratch SQLite FTS5 table per repo (out/files-fts-<repo>.db), one row per file of the snapshot, with
codemem's own keyword text (codemem.tokenize.to_fts_text, the index's token options) and FTS5
tokenizer ("unicode61 tokenchars '_'"). Two kinds of row: "text": the path and the file as read from
the checkout (at the index's commit), one column; "fields": codemem's five fields gathered per file
(names, path, signatures, docs, the file text), ranked with codemem's field weights. The query's
words are the product's (search.bm25_match).

(a) the plain measure: a gold file in the top 5 / 10 of each whole-file ranking, against files in the
order of their best chunk in codemem's chunk-level keyword list;
(b) the experiment: the best c chunks (by their own code-vector similarity) of the top F files of a
whole-file ranking as one more fused list (as experiment 5), merged into out/s3-<set>.json as e14|...;
(c) experiment 15 capped: each top-10 file shown with its m functions closest to the query.

    ./run.sh e14_files.py <repo>
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import core as C
import lab_common as L
import prod
from codemem.tokenize import to_fts_text

CHECKOUT = {"vllm": L.ROOT / ".cache/repos/vllm", "pandas": L.ROOT / ".cache/repos/pandas"}
SETS = {"vllm": ["vllm-L0", "vllm-title"], "pandas": ["pandas-L0", "pandas-title", "vague-L1", "vague-L2"]}
WEIGHTS = (10.0, 3.0, 5.0, 2.0, 1.0)


def build(repo: str, ix: L.Index, opts: dict) -> Path:
    path = L.OUT / f"files-fts-{repo}.db"
    if path.is_file():
        return path
    t0 = time.perf_counter()
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.execute("CREATE VIRTUAL TABLE ftext USING fts5(body, content='', tokenize = \"unicode61 tokenchars '_'\")")
    con.execute("CREATE VIRTUAL TABLE ffields USING fts5(name_tokens, path_tokens, signature_tokens, doc_tokens, body_tokens, "
                "content='', tokenize = \"unicode61 tokenchars '_'\")")
    src = sqlite3.connect(f"file:{L.REPOS[repo]['index']}/index.db?mode=ro", uri=True)
    per_file = defaultdict(lambda: {"names": [], "sigs": [], "docs": []})
    for p, q, nm, sig, doc, lead in src.execute("SELECT path, qualname, name, signature, docstring, lead_comment FROM chunks"):
        d = per_file[p]
        d["names"].append(f"{q} {nm}")
        d["sigs"].append(sig)
        d["docs"].append(f"{doc}\n{lead}")
    missing = 0
    for f, p in enumerate(ix.paths):
        try:
            text = (CHECKOUT[repo] / p).read_text("utf-8", errors="replace")
        except OSError:
            text, missing = "", missing + 1
        con.execute("INSERT INTO ftext(rowid, body) VALUES(?, ?)", (f + 1, to_fts_text(f"{p}\n{text}", **opts)))
        d = per_file[p]
        con.execute("INSERT INTO ffields(rowid, name_tokens, path_tokens, signature_tokens, doc_tokens, body_tokens) VALUES(?, ?, ?, ?, ?, ?)",
                    (f + 1, to_fts_text(" ".join(d["names"]), **opts), to_fts_text(p, **opts), to_fts_text(" ".join(d["sigs"]), **opts),
                     to_fts_text(" ".join(d["docs"]), **opts), to_fts_text(text, **opts)))
    con.commit()
    con.close()
    tmp.rename(path)
    print(f"{repo}: whole-file keyword tables of {len(ix.paths)} files built in {time.perf_counter() - t0:.0f} s ({missing} not readable)", flush=True)
    return path


def main() -> None:
    repo = sys.argv[1]
    ix = L.Index(repo, vectors=True)
    fu = C.Fuser(ix)
    store, config = prod.open_store(repo)
    opts = {"stem": config.bm25_stem, "stopwords": config.bm25_stopwords}
    con = sqlite3.connect(build(repo, ix, opts))
    sets = L.query_sets(SETS[repo])
    measure = {}
    for name in SETS[repo]:
        run = C.load_run(name, ix)
        s3_path = L.OUT / f"s3-{name}.json"
        s3 = json.loads(s3_path.read_text("utf-8"))
        rec = s3[name]
        rows = []
        t_q = []
        for t in sets[name]["tasks"]:
            tid = t["id"]
            files, fns = ix.gold_rows(t)
            match = prod.bm25_match(store, t["query"], config)
            t0 = time.perf_counter()
            ftext = [r[0] - 1 for r in con.execute("SELECT rowid FROM ftext WHERE ftext MATCH ? ORDER BY bm25(ftext) LIMIT 50", (match,))] if match else []
            ffields = [r[0] - 1 for r in con.execute(
                "SELECT rowid FROM ffields WHERE ffields MATCH ? ORDER BY bm25(ffields, ?, ?, ?, ?, ?) LIMIT 50", (match, *WEIGHTS))] if match else []
            t_q.append(time.perf_counter() - t0)
            chunk_files = list(dict.fromkeys(int(ix.file_of[r]) for r in run[tid]["lists"]["bm25"]))
            fused_files = list(dict.fromkeys(int(ix.file_of[r]) for r in run[tid]["product"]))

            def at(order, k):
                return bool(files) and bool(set(order[:k]) & files)

            rows.append({"half": t["half"], "has_file": bool(files),
                         **{f"{lab}@{k}": at(order, k) for lab, order in (("whole_file_text", ftext), ("whole_file_fields", ffields),
                                                                          ("chunk_keywords_by_best_chunk", chunk_files),
                                                                          ("product_results_files", fused_files)) for k in (5, 10)}})
            # (b) the experiment: best c chunks of the top F files of a whole-file ranking, as one more list
            task = None
            s_code = ix.scores("code", t["vec"])
            order0, sc0 = fu.baseline(run[tid])
            cands = set(sc0)
            for lab, forder in (("text", ftext), ("fields", ffields)):
                for F in (3, 5, 10):
                    for c in (1, 2):
                        lst = []
                        for f in forder[:F]:
                            frows = ix.file_rows(f)
                            sc = s_code[frows]
                            ok = np.isfinite(sc)
                            frows, sc = frows[ok], sc[ok]
                            lst += frows[np.lexsort((frows, -sc))][:c].tolist()
                        added = sum(r not in cands for r in lst)
                        for w in (0.5, 1.0):
                            t2 = time.perf_counter()
                            scores = dict(sc0)
                            for rank, r in enumerate(lst, start=1):
                                scores[r] = scores.get(r, 0.0) + w / (60.0 + rank)
                            order = sorted(scores, key=lambda r: (-scores[r], fu.loc[r]))
                            fn = C.first_rank(order, fns) if fns else None
                            fl = C.first_rank(order, files, ix.file_of) if files else None
                            rec.setdefault(f"e14|{lab}|F{F}|c{c}|w{w}", {})[tid] = (fn, fl, added, int((t_q[-1] + time.perf_counter() - t2) * 1e6))
            # (c) experiment 15 capped: each top-10 file with its m functions closest to the query
            top = [int(x) for x in run[tid]["product"][:10]]
            tfiles = list(dict.fromkeys(int(ix.file_of[r]) for r in top))
            hit10 = any(r in fns for r in top)
            for m in (3, 5, 10):
                named = set()
                for f in tfiles:
                    frows = np.array([r for r in ix.file_rows(f).tolist() if ix.kind[r] in ("function", "method", "class")], dtype=np.int64)
                    if not len(frows):
                        continue
                    sc = s_code[frows]
                    named.update(frows[np.lexsort((frows, -sc))][:m].tolist())
                named -= set(top)
                rec.setdefault(f"e15cap|m{m}", {})[tid] = (1 if (hit10 or (named & fns)) else None, len(named), 0, 0)
        s3_path.write_text(json.dumps(s3), "utf-8")
        for scope in ("all", "held"):
            sel = [r for r in rows if r["has_file"] and (scope == "all" or r["half"] == 1 or name.startswith("vague"))]
            cells = [f"{lab} {sum(r[f'{lab}@5'] for r in sel)} / {sum(r[f'{lab}@10'] for r in sel)}"
                     for lab in ("whole_file_text", "whole_file_fields", "chunk_keywords_by_best_chunk", "product_results_files")]
            print(f"{name:13s} {scope:4s} tasks with a gold file {len(sel)} | gold file in the top 5 / 10 of: " + " | ".join(cells)
                  + f" | whole-file query ms median {1000 * np.median(t_q):.0f}", flush=True)
            measure[f"{name}|{scope}"] = {"tasks": len(sel), **{k: sum(r[k] for r in sel) for k in sel[0] if "@" in k}} if sel else {}
            if name.startswith("vague"):
                break
    prev = json.loads((L.OUT / "e14-measure.json").read_text("utf-8")) if (L.OUT / "e14-measure.json").is_file() else {}
    prev.update(measure)
    (L.OUT / "e14-measure.json").write_text(json.dumps(prev, indent=1), "utf-8")
    store.close()


if __name__ == "__main__":
    main()
