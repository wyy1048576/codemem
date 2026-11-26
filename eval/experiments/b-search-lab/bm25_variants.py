"""Keyword lists for shortened or reduced queries, through the product's own calls (bm25_match +
Store.bm25_search), 200 deep, for experiments 7 (keywords from a shortened issue) and 12 (keywords
on the issue's identifiers). Per task of the repo's L0 set:
  title       the issue's first line
  w32/w64/w128  its first 32, 64, 128 words
  idents      the code-like names in it (core.identifiers: dotted names, snake_case, CamelCase)
  idents_q    those and its quoted strings
Kept in out/bm25v-<repo>.json as {task id: {variant: [chunk ids]}}.

    ./run.sh bm25_variants.py <repo>
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import core as C
import lab_common as L
import prod

DEPTH = 200


def variants(query: str) -> dict[str, str]:
    words = query.split()
    ids = C.identifiers(query)
    return {
        "title": L.title_of(query), "w32": " ".join(words[:32]), "w64": " ".join(words[:64]),
        "w128": " ".join(words[:128]), "idents": " ".join(ids), "idents_q": " ".join(ids + C.quoted(query)),
    }


def main() -> None:
    repo = sys.argv[1]
    tasks = L.load_tasks(repo)
    store, config = prod.open_store(repo)
    out: dict[str, dict] = {}
    t0 = time.perf_counter()
    for i, t in enumerate(tasks):
        row = {}
        for name, text in variants(t["query"]).items():
            match = prod.bm25_match(store, text, config) if text.strip() else None
            row[name] = store.bm25_search(match, DEPTH, config.bm25_weights5()) if match else []
            row[f"{name}_text"] = text
        out[t["id"]] = row
        if (i + 1) % 50 == 0:
            print(f"{repo}: {i + 1}/{len(tasks)} in {time.perf_counter() - t0:.0f} s", flush=True)
    (L.OUT / f"bm25v-{repo}.json").write_text(json.dumps(out), "utf-8")
    print(f"{repo}: done in {time.perf_counter() - t0:.0f} s", flush=True)
    store.close()


if __name__ == "__main__":
    main()
