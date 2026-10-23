"""Search and index latency from the run files."""

from __future__ import annotations

import math
import statistics


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..1). None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def search_latency(search_ms: list[float]) -> dict[str, float | None]:
    return {
        "search_ms_median": statistics.median(search_ms) if search_ms else None,
        "search_ms_p95": percentile(search_ms, 0.95),
    }


def index_costs(index_rows: list[dict], system: str) -> dict[str, float | None]:
    """Index cost of the system that does the real work for a shared group (its own rows only).

    A resumed run can write more than one row for the same task (for example a build, then an
    update that finds nothing left to do). Only the first one counts: it did the real work.
    Rows marked "resumed" finished an update that a stopped run had started, so they show only
    part of the work and are left out.
    files_failed_max is the largest count in any one report: a file that keeps failing would be
    counted again at every update if the counts were added up.
    """
    first: dict[tuple, dict] = {}
    for position, r in enumerate(index_rows):
        if r["system"] == system and not r.get("resumed"):
            # Rows without a task id cannot be matched, so they are never merged.
            key = (r["task_id"],) if r.get("task_id") else ("row", position)
            first.setdefault(key, r)
    rows = list(first.values())
    builds = [r["report"]["seconds"] for r in rows if r["mode"] == "build"]
    updates = [r["report"]["seconds"] for r in rows if r["mode"] == "update"]
    reembedded = [r["report"]["items_reembedded"] for r in rows if r["report"].get("items_reembedded") is not None]
    return {
        "build_seconds_mean": statistics.mean(builds) if builds else None,
        "update_seconds_median": statistics.median(updates) if updates else None,
        "items_reembedded_mean": statistics.mean(reembedded) if reembedded else None,
        "index_bytes_max": max((r["report"]["bytes_on_disk"] for r in rows), default=None),
        "files_failed_max": float(max((r["report"].get("extra", {}).get("files_failed", 0) for r in rows), default=0)),
    }
