"""Accuracy for one task at one level, from the ranked list of matched gold items."""

from __future__ import annotations

KS = (1, 5, 10, 20, 50)


def accuracy_metrics(units: list[set[int]], n_gold: int, ks: tuple[int, ...] = KS) -> dict[str, float]:
    """recall@k, precision@k, success@k, and mrr.

    units: for each rank position, the gold items found there (a gold item counts at its first
    position only). n_gold: number of gold items at this level (more than 0).
    """
    first: dict[int, int] = {}
    for rank, found in enumerate(units, start=1):
        for item in found:
            first.setdefault(item, rank)
    relevant_ranks = [rank for rank, found in enumerate(units, start=1) if found]
    out: dict[str, float] = {}
    for k in ks:
        found_k = sum(1 for rank in first.values() if rank <= k)
        out[f"recall@{k}"] = found_k / n_gold
        out[f"precision@{k}"] = sum(1 for rank in relevant_ranks if rank <= k) / k
        out[f"success@{k}"] = 1.0 if found_k == n_gold else 0.0
    out["mrr"] = 1.0 / relevant_ranks[0] if relevant_ranks else 0.0
    return out
