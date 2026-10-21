"""Text builders: one text per (chunk, vector type), each embedded separately.

A builder is `fn(chunk, ctx) -> str | None`; None means "no vector of this type
for this chunk". New types (summary, file summary, ...) register here without
changes to the store or search.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .callgraph import is_test_caller
from .schema import Chunk


@dataclass(frozen=True)
class Ref:
    chunk_id: int
    qualname: str
    name: str
    path: str
    start_line: int


@dataclass
class BuildContext:
    callers: dict[int, list[Ref]] = field(default_factory=dict)  # callee chunk_id -> callers
    commits: dict[str, list[str]] = field(default_factory=dict)  # path -> commit subjects
    max_items: int = 20


TextBuilder = Callable[[Chunk, BuildContext], "str | None"]
TEXT_BUILDERS: dict[str, TextBuilder] = {}


def register(name: str) -> Callable[[TextBuilder], TextBuilder]:
    def deco(fn: TextBuilder) -> TextBuilder:
        TEXT_BUILDERS[name] = fn
        return fn

    return deco


def build_texts(chunk: Chunk, ctx: BuildContext, vec_types: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for vec_type in vec_types:
        builder = TEXT_BUILDERS.get(vec_type)
        if builder is None:
            raise KeyError(f"no text builder registered for vector type {vec_type!r}")
        text = builder(chunk, ctx)
        if text:
            out[vec_type] = text
    return out


@register("code")
def build_code(chunk: Chunk, ctx: BuildContext) -> str | None:
    return chunk.code or None


@register("usage")
def build_usage(chunk: Chunk, ctx: BuildContext) -> str | None:
    if chunk.kind == "file_header" or chunk.chunk_id is None:
        return None
    callers = sorted(ctx.callers.get(chunk.chunk_id, []), key=lambda r: (r.path, r.start_line))
    tests = [r for r in callers if is_test_caller(r.path, r.name)]
    users = [r for r in callers if not is_test_caller(r.path, r.name)]
    commits = ctx.commits.get(chunk.path, [])
    if not (tests or users or commits):
        return None

    # Tests are reserved up to half the budget so many callers can't crowd them out.
    tests = tests[: max(ctx.max_items // 2, ctx.max_items - len(users))]
    users = users[: ctx.max_items - len(tests)]
    lines = [f"{chunk.qualname} in {chunk.path}"]
    lines += [f"called by {ref.qualname} in {ref.path}" for ref in users]
    lines += [f"tested by {ref.qualname} in {ref.path}" for ref in tests]
    for subject in commits[:5]:
        lines.append(f"changed in commit: {subject}")
    return "\n".join(lines)


@register("summary")
def build_summary(chunk: Chunk, ctx: BuildContext) -> str | None:
    # Slot for LLM summaries (not in Week 1). Enabling `vectors.summary` is a no-op
    # until a summarizer fills this in.
    return None
