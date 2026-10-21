"""Compact plain-text rendering shared by the MCP tools and the CLI."""

from __future__ import annotations

import json
from typing import Any

from .search import SearchResponse


def format_results(resp: SearchResponse, *, debug: bool = False, preview: bool = True) -> str:
    if not resp.results:
        return f"No results for {resp.query!r}."
    out: list[str] = []
    for i, r in enumerate(resp.results, start=1):
        head = f"{i}. {r.location}  {r.qualname}  [id {r.chunk_id}]"
        if debug and r.ranks is not None:
            head += "  " + " ".join(f"{s}={rank}" for s, rank in sorted(r.ranks.items())) + f" rrf={r.score:.4f}"
        out.append(head)
        out.append(f"   {r.signature}")
        if r.doc:
            out.append(f"   {r.doc}")
        if preview and r.preview and r.kind != "file_header":
            body = r.preview.splitlines()[1:]  # first line repeats the signature/decorator
            out.extend(f"   | {line}" for line in body[:6])
    return "\n".join(out)


def format_chunk(d: dict[str, Any]) -> str:
    lines = [f"{d['location']}  {d['qualname']}  [id {d['chunk_id']}]", "", d["code"], ""]
    for label in ("callers", "callees"):
        items = d[label]
        lines.append(f"{label}: " + (", ".join(f"{c['qualname']} ({c['location']})" for c in items) or "none"))
    return "\n".join(lines)


def format_status(info: dict[str, Any]) -> str:
    lines = [f"state: {info['state']}" + (f" ({info['progress']}%)" if info.get("progress") is not None else "")]
    lines.append(f"repo: {info['repo']}")
    lines.append(f"index: {info['index_dir']}")
    lines.append(
        f"files: {info['files']}  chunks: {info['chunks']} {json.dumps(info['chunks_by_kind'])}  edges: {info['edges']}"
    )
    lines.append(f"vectors: {json.dumps(info['vectors'])}")
    for vec_type, m in info["models"].items():
        lines.append(f"  {vec_type}: {m['model']} (dim {m['dim']})")
    lines.append(f"indexed commit: {info['indexed_commit'] or '-'}")
    if "age_seconds" in info:
        lines.append(f"last indexed: {info['age_seconds']:.0f}s ago")
    if stale := info.get("stale"):
        lines.append(
            f"stale: {stale['changed_files']} changed, {stale['deleted_files']} deleted"
            + (", git HEAD moved" if stale["head_moved"] else "")
        )
    if info.get("error"):
        lines.append(f"error: {info['error']}")
    return "\n".join(lines)
