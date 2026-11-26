"""Stage 2: where the gold functions are when the product's top 10 has none of them, and what they are.

Per task with a gold function in the snapshot: in the top 10 or not; if not, for its closest gold
function (the best fused rank, else the best rank in any list): its rank in each list out to 1,000
(keywords, code vectors, usage vectors) and in the fused list; whether it is one call away from a
top-10 result (each edge version), in the same file or folder as one; its kind, lines, characters,
code windows, whether the model cut a window (tokens > max_seq_length, counted as the product
counts: document prompt + text), its file's chunk count, whether the query names it.

    ./run.sh s2_errors.py [<set> ...]
"""
from __future__ import annotations

import glob
import json
import re
import sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import core as C
import lab_common as L
import prod
from codemem.texts import BuildContext, build_parts
from codemem.schema import text_hash

SETS = ["vllm-L0", "pandas-L0", "vague-L0", "vague-L1", "vague-L2"]
VERSIONS = ("a", "b99", "b90", "c")
DOC_PROMPT = "Candidate code snippet:\n"
QUERY_PROMPT = "Find the most relevant code snippet given the following query:\n"


def tokenizer():
    from transformers import AutoTokenizer
    snap = glob.glob(str(L.ROOT / ".cache/huggingface/hub/models--jinaai--jina-code-embeddings-0.5b/snapshots/*"))[0]
    return AutoTokenizer.from_pretrained(snap)


class Attrs:
    """Attributes of chunks, computed once per chunk: code windows and whether the model cut one."""

    def __init__(self, repo: str, ix: L.Index, tok):
        self.ix, self.tok = ix, tok
        self.store, self.config = prod.open_store(repo)
        self.ctx = BuildContext(code_header=self.config.code_header, window_chars=self.config.effective_window_chars(),
                                window_overlap_lines=self.config.window_overlap_lines)
        self.cache: dict[int, dict] = {}
        self.limit = self.config.max_seq_length

    def of(self, row: int) -> dict:
        if row in self.cache:
            return self.cache[row]
        ix = self.ix
        cid = int(ix.ids[row])
        chunk = self.store.get_chunks([cid])[cid]
        parts = build_parts(chunk, self.ctx, "code")
        stored = dict(self.store.conn.execute(
            "SELECT part, text_hash FROM vectors WHERE chunk_id = ? AND vec_type = 'code'", (cid,)).fetchall())
        same = all(stored.get(p.part) == text_hash(p.text) for p in parts) and len(stored) == len(parts)
        tokens = [len(self.tok(DOC_PROMPT + p.text)["input_ids"]) for p in parts]
        has_usage = bool(self.store.conn.execute(
            "SELECT 1 FROM vectors WHERE chunk_id = ? AND vec_type = 'usage' LIMIT 1", (cid,)).fetchone())
        body = chunk.skeleton if chunk.kind == "class" and chunk.skeleton else chunk.code
        out = {
            "kind": ix.kind[row] + (f"/{ix.subkind[row]}" if ix.subkind[row] and ix.subkind[row] != ix.kind[row] else ""),
            "lines": int(ix.end[row] - ix.start[row] + 1), "chars": len(chunk.code), "embedded_chars": len(body),
            "windows": len(parts), "max_tokens": max(tokens) if tokens else 0,
            "cut": any(t > self.limit for t in tokens), "text_check": same, "has_usage_vector": has_usage,
            "file_chunks": int(len(ix.file_rows(int(ix.file_of[row])))), "is_test": bool(ix.is_test[row]),
            "callers": int(ix.in_deg[row]), "callees": int(ix.out_deg[row]),
        }
        self.cache[row] = out
        return out


def names_in(query: str, name: str) -> bool:
    return bool(name) and re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", query) is not None


def place(rank: int | None) -> str:
    if rank is None:
        return "-"
    return str(rank)


def main() -> None:
    names = sys.argv[1:] or SETS
    sets = L.query_sets(names)
    tok = tokenizer()
    indexes: dict[str, L.Index] = {}
    fusers: dict[str, C.Fuser] = {}
    attrs: dict[str, Attrs] = {}
    report: dict = {}
    for name in names:
        repo = sets[name]["repo"]
        if repo not in indexes:
            indexes[repo] = L.Index(repo, vectors=False)
            fusers[repo] = C.Fuser(indexes[repo])
            attrs[repo] = Attrs(repo, indexes[repo], tok)
        ix, fu, at = indexes[repo], fusers[repo], attrs[repo]
        run = C.load_run("pandas-L0" if name == "vague-L0" else name, ix)
        rows_out = []
        n_query_cut = 0
        for t in sets[name]["tasks"]:
            files, fns = ix.gold_rows(t)
            qtok = len(tok(QUERY_PROMPT + t["query"])["input_ids"])
            n_query_cut += qtok > 1024
            if not fns:
                rows_out.append({"id": t["id"], "status": "no gold function in the snapshot" if t["gold_fns"] else "no function label",
                                 "query_tokens": qtok})
                continue
            r = run[t["id"]]
            fused, _ = fu.baseline(r)
            fused_rank = {int(x): i for i, x in enumerate(fused, start=1)}
            list_rank = {s: {int(x): i for i, x in enumerate(r["lists"][s], start=1)} for s in C.SIGNALS}
            top10 = [int(x) for x in r["product"][:10]]
            per_fn = []
            for g in sorted(fns):
                lr = {s: list_rank[s].get(g) for s in C.SIGNALS}
                per_fn.append({"row": g, "qualname": ix.qualname[g], "path": ix.path[g], "fused": fused_rank.get(g),
                               "lists": lr, "best_list": min((v for v in lr.values() if v), default=None),
                               "named": names_in(t["query"], ix.cname[g]), **at.of(g)})
            hit10 = any(p["fused"] and p["fused"] <= 10 for p in per_fn)
            # the closest gold function: best fused rank, else best rank in any list, else the first
            closest = min(per_fn, key=lambda p: (p["fused"] or 10**6, p["best_list"] or 10**6, p["row"]))
            reach = {}
            for v in VERSIONS:
                nb = set()
                for x in top10:
                    nb.update(int(y) for y in ix.neighbours(x, v, "both"))
                reach[f"hop_{v}"] = any(g in nb for g in fns)
                nb_callees = set()
                for x in top10:
                    nb_callees.update(int(y) for y in ix.neighbours(x, v, "callees"))
                reach[f"callee_{v}"] = any(g in nb_callees for g in fns)
            top_files = {int(ix.file_of[x]) for x in top10}
            top_folders = {int(ix.folder_of[x]) for x in top10}
            reach["same_file"] = any(int(ix.file_of[g]) in top_files for g in fns)
            reach["same_folder"] = any(int(ix.folder_of[g]) in top_folders for g in fns)
            reach["gold_file_in_top10"] = any(int(ix.file_of[x]) in files for x in top10)
            rows_out.append({"id": t["id"], "status": "hit" if hit10 else "miss", "query_tokens": qtok, "closest": closest,
                             "reach": reach, "fns": per_fn, "n_gold_fns": len(fns)})
        report[name] = {"rows": rows_out, "queries_cut": n_query_cut}
        summarise(name, rows_out, n_query_cut)
    (L.OUT / "s2-errors.json").write_text(json.dumps(report, indent=1, default=int), "utf-8")


def bucket(p: dict) -> str:
    f, b = p["fused"], p["best_list"]
    if f is not None and f <= 20:
        return "ranking: fused 11-20"
    if f is not None and f <= 50:
        return "ranking: fused 21-50"
    if f is not None:
        return "ranking: a candidate, fused past 50"
    if b is not None and b <= 200:
        return "depth: a list's 51-200"
    if b is not None:
        return "depth: a list's 201-1000"
    return "no list's top 1000"


def summarise(name: str, rows: list[dict], n_query_cut: int) -> None:
    withfn = [r for r in rows if r["status"] in ("hit", "miss")]
    miss = [r for r in withfn if r["status"] == "miss"]
    print(f"\n### {name}: {len(rows)} tasks; {len(withfn)} with a gold function in the snapshot; "
          f"{sum(r['status'] == 'no gold function in the snapshot' for r in rows)} whose gold functions are all missing from it; "
          f"{sum(r['status'] == 'no function label' for r in rows)} with no function label. Issue texts over 1,024 tokens: {n_query_cut}")
    hits = len(withfn) - len(miss)
    # the reach ladder (the earlier count): top 10, else one call away, else same file, else same folder, else none
    for v in VERSIONS:
        ladder = Counter()
        for r in withfn:
            if r["status"] == "hit":
                ladder["top 10"] += 1
            elif r["reach"][f"hop_{v}"]:
                ladder["one call away"] += 1
            elif r["reach"]["same_file"]:
                ladder["same file"] += 1
            elif r["reach"]["same_folder"]:
                ladder["same folder"] += 1
            else:
                ladder["none of these"] += 1
        n = len(withfn)
        print(f"ladder (edges {v}): " + "; ".join(f"{k} {ladder[k]} ({100 * ladder[k] / n:.0f}%)"
                                                   for k in ("top 10", "one call away", "same file", "same folder", "none of these")))
    causes = Counter(bucket(r["closest"]) for r in miss)
    print(f"misses: {len(miss)} of {len(withfn)}")
    order = ["ranking: fused 11-20", "ranking: fused 21-50", "ranking: a candidate, fused past 50",
             "depth: a list's 51-200", "depth: a list's 201-1000", "no list's top 1000"]
    for c in order:
        group = [r for r in miss if bucket(r["closest"]) == c]
        if not group:
            continue
        best_list = Counter(min(((v, s) for s, v in r["closest"]["lists"].items() if v), default=(None, "none"))[1] for r in group)
        hop = sum(r["reach"]["hop_a"] for r in group)
        same_file = sum(r["reach"]["same_file"] for r in group)
        gold_file = sum(r["reach"]["gold_file_in_top10"] for r in group)
        print(f"  {c}: {len(group)}; best list {dict(best_list)}; one call away (a) {hop}; same file {same_file}; "
              f"a gold file in the top 10 {gold_file}")
    def describe(group: list[dict], label: str) -> None:
        ps = [r["closest"] for r in group]
        if not ps:
            return
        kinds = Counter(p["kind"] for p in ps)
        print(f"  {label} ({len(ps)}): kinds {dict(kinds)}; lines median {np.median([p['lines'] for p in ps]):.0f}, "
              f"chars median {np.median([p['chars'] for p in ps]):.0f}; several windows {sum(p['windows'] > 1 for p in ps)}; "
              f"a window cut by the model {sum(p['cut'] for p in ps)}; text rebuilt = stored {sum(p['text_check'] for p in ps)}; "
              f"usage vector {sum(p['has_usage_vector'] for p in ps)}; file chunks median {np.median([p['file_chunks'] for p in ps]):.0f}; "
              f"test code {sum(p['is_test'] for p in ps)}; named in the query {sum(p['named'] for p in ps)}")
    for s_ in ("bm25", "code", "usage"):
        rk = [r["closest"]["lists"][s_] for r in miss]
        within = {d: sum(1 for x in rk if x and x <= d) for d in (50, 200, 1000)}
        med = np.median([x if x else 1001 for x in rk]) if rk else 0
        print(f"  misses, {s_} list: closest gold function within 50 / 200 / 1000: {within[50]} / {within[200]} / {within[1000]}; median rank {med:.0f} (1001 = beyond)")
    print(f"  misses with a gold file in the top 10: {sum(r['reach']['gold_file_in_top10'] for r in miss)} of {len(miss)}")
    describe([r for r in withfn if r["status"] == "hit"], "hits, closest gold function")
    describe(miss, "misses, closest gold function")
    describe([r for r in miss if bucket(r["closest"]) == "no list's top 1000"], "misses in no list's top 1000")


if __name__ == "__main__":
    main()
