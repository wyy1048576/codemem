"""Compact plain-text rendering shared by the MCP tools and the CLI.

A card is what an agent reads for one result; the eval harness counts its tokens.
"""

from __future__ import annotations

import json
from typing import Any

from .search import ResultCard, SearchResponse


def card_label(r: ResultCard) -> str:
    if r.kind == "block":
        return f"<{r.subkind or 'block'}> {r.name}" if r.subkind != "imports" else "<imports>"
    if r.kind == "class" and r.subkind and r.subkind != "class":
        return f"{r.qualname} ({r.subkind})"
    return r.qualname


def format_results(resp: SearchResponse, *, debug: bool = False, preview: bool = True) -> str:
    if not resp.results:
        return f"No results for {resp.query!r}."
    out: list[str] = []
    for i, r in enumerate(resp.results, start=1):
        head = f"{i}. {r.location}  {card_label(r)}  [id {r.chunk_id}]"
        if r.best_lines:
            head += f"  best {r.best_lines[0]}-{r.best_lines[1]}"
        if debug and r.ranks is not None:
            head += "  " + " ".join(f"{s}={rank}" for s, rank in sorted(r.ranks.items())) + f" rrf={r.score:.4f}"
        out.append(head)
        if r.kind != "block":
            out.append(f"   {r.signature}")
        if r.doc:
            out.append(f"   {r.doc}")
        if preview and r.preview:
            body = r.preview.splitlines()
            if r.kind != "block" and not r.best_lines:
                body = body[1:]  # first line repeats the signature/decorator
            out.extend(f"   | {line}" for line in body[:6])
    return "\n".join(out)


def format_chunk(d: dict[str, Any]) -> str:
    lines = [f"{d['location']}  {d['qualname']}  [id {d['chunk_id']}]", "", d["code"], ""]
    if d.get("members"):
        lines.append("members: " + ", ".join(f"{c['qualname']} ({c['location']})" for c in d["members"]))
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
    if info.get("chunks_by_language"):
        lines.append(f"languages: {json.dumps(info['chunks_by_language'])}")
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
    if info.get("pending_chunks") or info.get("pending_files"):
        lines.append(f"pending: {info.get('pending_files', 0)} files, {info.get('pending_chunks', 0)} chunks to embed")
    if "watching" in info:
        lines.append("watching for changes" if info["watching"] else "not watching (scanning on a timer or on request)")
    lines.extend(format_coverage(info))
    if info.get("error"):
        lines.append(f"error: {info['error']}")
    return "\n".join(lines)


def format_coverage(info: dict[str, Any]) -> list[str]:
    """What the index leaves out, and why, so nothing is missed silently."""
    out: list[str] = []
    skipped = info.get("skipped_files") or {}
    if by_reason := skipped.get("by_reason"):
        parts = ", ".join(f"{n} {reason.replace('_', ' ')}" for reason, n in sorted(by_reason.items()))
        out.append(f"not indexed or partly parsed: {parts}")
        for ex in skipped.get("examples", [])[:5]:
            out.append(f"  {ex['path']} ({ex['reason'].replace('_', ' ')}, {ex['size'] / 1e6:.1f} MB)")
    cov = info.get("coverage") or {}
    if cov.get("not_code_files"):
        exts = ", ".join(f"{ext} {n}" for ext, n in (cov.get("not_code_by_extension") or {}).items())
        out.append(f"not code (no supported language): {cov['not_code_files']} files ({exts})")
    if cov.get("ignored_files") or cov.get("skipped_dirs"):
        dirs = ", ".join(f"{d} {n}" for d, n in (cov.get("skipped_dirs") or {}).items())
        out.append(f"ignored: {cov.get('ignored_files', 0)} files; skipped folders: {dirs or 'none'}")
    return out
