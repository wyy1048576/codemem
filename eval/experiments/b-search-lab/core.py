"""The lab's own search over the kept lists: the product's fusion re-done in Python, so that every
experiment is a change to one ranking function and the baseline is the product's search exactly.

Rows are chunk numbers 0..N-1 of lab_common.Index (chunk-id order). A run of s1_run.py gives, per
task, the product's top 50 and each list out to 1,000 (chunk ids, through the product's calls);
`load_run` turns them into rows. `Fuser.fuse` is codemem.search.rrf + _pick_top: scores summed in
the signals' order (bm25, code, usage), ties ordered by (path, start line, key)."""
from __future__ import annotations

import json
import re
import sys
import time

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import lab_common as L

SIGNALS = ("bm25", "code", "usage")


def load_run(name: str, index: L.Index) -> dict[str, dict]:
    """task id -> {"product": rows of the product's top 50, "lists": {signal: rows out to 1,000},
    "vscores": {type: scores of the vector lists}, "ms": product timings, "match": the BM25 match}."""
    files = sorted(L.OUT.glob(f"s1-{name}.json")) or sorted(L.OUT.glob(f"s1-{name}.[0-9]*.json"))
    if not files:
        raise FileNotFoundError(f"no run of {name} in {L.OUT}")
    out: dict[str, dict] = {}
    for f in files:
        for r in json.loads(f.read_text("utf-8"))["rows"]:
            rows = lambda ids: np.array([index.row_of[c] for c in ids], dtype=np.int64)
            out[r["id"]] = {
                "product": rows(r["results"]), "ranks": r["ranks"],
                "lists": {s: rows(r["lists"][s]) for s in SIGNALS},
                "vscores": {t: np.array(r["scores"][t], dtype=np.float32) for t in ("code", "usage")},
                "ms": r["ms"], "search_s": r["search_s"], "match": r["match"],
            }
    return out


class Fuser:
    def __init__(self, index: L.Index):
        self.ix = index
        order = sorted(range(index.N), key=lambda r: (index.path[r], int(index.start[r]), index.key[r]))
        self.loc = np.empty(index.N, dtype=np.int64)
        self.loc[np.array(order, dtype=np.int64)] = np.arange(index.N)

    def fuse(self, lists: list[tuple[str, np.ndarray | list, float]], k: float = 60.0,
             factor: dict[int, float] | None = None) -> tuple[list[int], dict[int, float]]:
        """lists: (name, rows best first, weight), in summation order. Returns every candidate in
        final order and the fused scores. `factor`: row -> multiplier (the product's _reweigh)."""
        scores: dict[int, float] = {}
        for _, rows, w in lists:
            if w == 0:
                continue
            for rank, r in enumerate(rows, start=1):
                r = int(r)
                scores[r] = scores.get(r, 0.0) + w / (k + rank)
        if factor:
            for r, f in factor.items():
                if r in scores:
                    scores[r] *= f
        loc = self.loc
        return sorted(scores, key=lambda r: (-scores[r], loc[r])), scores

    def baseline(self, run_row: dict, depth: int = 50, k: float = 60.0, weights: dict[str, float] | None = None):
        w = weights or {}
        return self.fuse([(s, run_row["lists"][s][:depth], w.get(s, 1.0)) for s in SIGNALS], k=k)


def first_rank(ranking, targets: set[int], by_file: np.ndarray | None = None) -> int | None:
    """1-based place of the first row in `targets` (rows), or, with by_file, of the first row whose
    file number is in `targets`."""
    for place, r in enumerate(ranking, start=1):
        if (by_file[int(r)] if by_file is not None else int(r)) in targets:
            return place
    return None


def hit(rank: int | None, k: int) -> int:
    return int(rank is not None and rank <= k)


# ---------------------------------------------------------------- identifiers in a query

_DOTTED = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b")
_IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_QUOTED = re.compile(r"`([^`\n]{2,80})`|'([^'\n]{2,60})'|\"([^\"\n]{2,60})\"")


def is_code_ident(tok: str) -> bool:
    """snake_case (an inner underscore, or a leading one), CamelCase / mixedCase, or a dunder."""
    t = tok.strip("_")
    if len(t) < 3:
        return False
    if "_" in t or tok.startswith("_"):
        return True
    if re.search(r"[a-z][A-Z]", t) or re.match(r"[A-Z][a-z0-9]+[A-Z]", t):
        return True
    return False


def identifiers(text: str) -> list[str]:
    """Code-like names in a text, in order of first appearance: dotted names (a.b.c, and each of
    their parts that looks like code), snake_case, CamelCase. Plain words are not names."""
    seen: dict[str, None] = {}
    for m in _DOTTED.finditer(text):
        whole = m.group(0)
        parts = whole.split(".")
        if any(is_code_ident(p) for p in parts) or len(parts) >= 2 and parts[0] in ("pd", "np", "df", "torch", "vllm", "self"):
            seen.setdefault(whole, None)
            for p in parts:
                if is_code_ident(p) or (len(p) >= 3 and p[0].isupper()):
                    seen.setdefault(p, None)
    for m in _IDENT.finditer(text):
        tok = m.group(0)
        if is_code_ident(tok):
            seen.setdefault(tok, None)
    return list(seen)


def quoted(text: str) -> list[str]:
    out = []
    for m in _QUOTED.finditer(text):
        s = next(g for g in m.groups() if g)
        out.append(s)
    return out


class Timer:
    def __init__(self):
        self.t = {}

    def add(self, name: str, s: float) -> None:
        self.t[name] = self.t.get(name, 0.0) + s
