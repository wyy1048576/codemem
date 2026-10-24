"""Which hits find which gold items (Decisions 2, 3, 4).

- File level: a hit finds a gold file if the paths are equal. Ranks are over the ranked file
  list (unique paths in order of first appearance).
- Class and function level: a hit finds a gold item if it is in the same file, has line numbers,
  and either lies inside the gold range or overlaps it with line IoU >= the threshold. Ranks are
  over the raw hits.
- Each gold item counts once, at its first matching hit.
"""

from __future__ import annotations

from ..retriever import Hit
from ..tasks import Span, Task

LEVELS = ("file", "class", "function")


def level_gold(task: Task, level: str) -> list:
    """Gold items at a level: paths for "file", spans for "class" and "function"."""
    return {"file": task.gold.files, "class": task.gold.classes, "function": task.gold.functions}[level]


def excluded(task: Task, granularity: str, level: str) -> str | None:
    """Why a (task, system, level) is left out of the scores, or None if it is scored."""
    if level != "file" and granularity == "file":
        return "file-granularity system"  # shown as n/a, never 0
    if level != "file" and task.tags.get("partial_labels"):
        return "partial labels"
    if not level_gold(task, level):
        return "no gold at this level"
    return None


def line_iou(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    """Lines shared by both ranges / lines covered by either range."""
    inter = max(0, min(a_end, b_end) - max(a_start, b_start) + 1)
    union = max(a_end, b_end) - min(a_start, b_start) + 1
    return inter / union


def hit_matches(hit: Hit, span: Span, iou: float) -> bool:
    if hit.path != span.path or hit.start_line is None or hit.end_line is None:
        return False
    if span.start <= hit.start_line and hit.end_line <= span.end:
        return True  # the hit points into the gold item
    return line_iou(hit.start_line, hit.end_line, span.start, span.end) >= iou


def raw_relevance(hits: list[Hit], gold: list, level: str, iou: float) -> list[set[int]]:
    """For each hit, in rank order, the indexes of the gold items it matches."""
    if level == "file":
        return [{j for j, path in enumerate(gold) if hit.path == path} for hit in hits]
    return [{j for j, span in enumerate(gold) if hit_matches(hit, span, iou)} for hit in hits]


def file_units(hits: list[Hit], relevance: list[set[int]]) -> list[set[int]]:
    """The ranked file list: one entry for each unique path, at its first appearance."""
    seen: set[str] = set()
    units = []
    for hit, rel in zip(hits, relevance):
        if hit.path not in seen:
            seen.add(hit.path)
            units.append(rel)
    return units
