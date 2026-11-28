"""One-hop call-graph expansion of an earlier arm's top 50 (no Sonnet calls).

For each task, take the saved top 50 of BASE_ARM from BASE_RUN, find each result's one-hop call-graph
neighbours in the codemem index at the task's commit (callers and callees, from the `edges` table), score each
neighbour by cosine between its code vector and the whole issue's query vector, and add the best few per result:

    ranks 1-5:   15 neighbours each      ranks 6-20: 10 each      ranks 21-50: 5 each

Neighbours already in the top 50 are skipped; a neighbour picked from several results counts once.
Returned hits: the base top 50 in order, then the added neighbours (by seed rank, then cosine).
hits[0].extra["hop"] keeps every neighbour of every seed (chunk id, location, cosine) for later analysis.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from cmeval.adapters.codemem import _SHARED, CodememRetriever
from cmeval.retriever import Hit

from aug_retriever import _MemoEmbedder, _sha
from cmeval.tasks import load_tasks

BUDGET = ((5, 15), (20, 10), (50, 5))  # (last rank of the band, neighbours per result)


class HopRetriever(CodememRetriever):
    def __init__(self, name="hop", signals=None, config=None, base_suffix="arc-loopfull", base_arm="oneshot"):
        super().__init__(name, signals, config)
        self.base_arm, self.base = base_arm, {}
        for repo in ("duckdb", "pandas"):
            path = Path.home() / ".cmeval" / "runs" / f"{repo}-{base_suffix}" / f"{base_arm}.jsonl"
            if path.exists():
                self.base.update({r["task_id"]: r["hits"][:50] for r in map(json.loads, path.read_text(encoding="utf8").splitlines())})
        self.tasks = {_sha(t.query): t for t in load_tasks(os.environ["AUG_TASKS"])}

    def describe(self):
        return {**super().describe(), "adapter": "hop", "base_arm": self.base_arm, "budget": BUDGET}

    def search(self, query: str, k: int) -> list[Hit]:
        task = self.tasks.get(_sha(query))
        if task is None:
            return super().search(query, k)
        store = _SHARED[self._index_dir]["service"].store
        conn = store.conn
        seeds, unmatched = [], 0
        for h in self.base[task.id]:
            row = conn.execute("SELECT chunk_id FROM chunks WHERE path = ? AND start_line = ? AND end_line = ?",
                               (h["path"], h["start_line"], h["end_line"])).fetchone()
            unmatched += row is None
            seeds.append(row[0] if row else None)
        top = {s for s in seeds if s is not None}
        qvec = _MemoEmbedder(self.config.vectors["code"], self.config).embed_queries([task.query])[0]
        per_seed, all_ids = [], set()
        for s in seeds:
            if s is None:
                per_seed.append([])
                continue
            n = {r[0] for r in conn.execute("SELECT callee_id FROM edges WHERE caller_id = ?", (s,))}
            n |= {r[0] for r in conn.execute("SELECT caller_id FROM edges WHERE callee_id = ?", (s,))}
            n.discard(s)
            per_seed.append(sorted(n))
            all_ids |= n
        scored = {h.chunk_id: h.score for h in store.vector_search("code", qvec, len(all_ids), sorted(all_ids))} if all_ids else {}
        chunks = store.get_chunks(all_ids)
        added, order = set(), []
        for rank, nbrs in enumerate(per_seed, start=1):
            quota = next(q for last, q in BUDGET if rank <= last)
            ranked = sorted((c for c in nbrs if c not in top), key=lambda c: -scored.get(c, -9))
            for c in ranked[:quota]:
                if c not in added:
                    added.add(c)
                    order.append((c, rank))
        hits = [Hit.from_dict(h) for h in self.base[task.id]]
        for c, rank in order:
            ch = chunks[c]
            hits.append(Hit(path=ch.path, start_line=ch.start_line, end_line=ch.end_line, symbol=ch.qualname,
                            score=scored.get(c, 0.0), text=f"hop from rank {rank}: {ch.path}:{ch.start_line}-{ch.end_line} {ch.qualname}",
                            extra={"kind": ch.kind, "chunk_id": c, "seed_rank": rank}))
        hits[0].extra = {**hits[0].extra, "hop": {
            "unmatched_seeds": unmatched, "selected": len(order), "picked_with_repeats": sum(
                min(len([c for c in n if c not in top]), next(q for last, q in BUDGET if r <= last)) for r, n in enumerate(per_seed, 1)),
            "neighbours": [[[c, round(scored[c], 4) if c in scored else None] for c in n] for n in per_seed],
            "where": {c: [chunks[c].path, chunks[c].start_line, chunks[c].end_line] for c in all_ids}}}
        return hits[:k]
