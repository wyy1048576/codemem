"""Text builders: the texts that get embedded, one or more per (chunk, vector type).

A builder is `fn(chunk, ctx) -> str | None` and returns the whole text of one vector type; None
means "no vector of this type for this chunk". New types (summary, file summary, ...) register
here without changes to the store or search.

`build_parts()` turns a text into the vectors actually stored. A `code` text longer than the
embedder can read is split into windows ("parts") of whole lines, each with the same short
context header; each part is its own vector of the same chunk, and search scores the chunk by
its best part. Line offsets are relative to the chunk's first line, so code moving down the file
does not change any text.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .callgraph import is_test_caller
from .schema import BLOCK_QUALNAME, Chunk


@dataclass(frozen=True)
class Ref:
    chunk_id: int
    qualname: str
    name: str
    path: str
    start_line: int
    is_test: bool | None = None  # None: guess from path and name (v1 behaviour, Python rules)
    kind: str = "function"


@dataclass
class BuildContext:
    callers: dict[int, list[Ref]] = field(default_factory=dict)  # callee chunk_id -> callers
    commits: dict[str, list[str]] = field(default_factory=dict)  # path -> commit subjects
    max_items: int = 20
    code_header: bool = True
    window_chars: int = 3000
    window_overlap_lines: int = 3


@dataclass(frozen=True)
class TextPart:
    text: str
    part: int = 0
    n_parts: int = 1
    start_off: int = 0  # first and last line of this part, relative to the chunk's start_line
    end_off: int = 0


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


# --------------------------------------------------------------------------- code


def _comment_prefix(chunk: Chunk) -> str:
    from .languages import LANGUAGES

    spec = LANGUAGES.get(chunk.language)
    return spec.line_comment if spec else "#"


def _scope_of(chunk: Chunk) -> str:
    """Enclosing scope from the qualname: `SessionManager.expire_old.is_old` -> `SessionManager.expire_old`."""
    qualname = chunk.qualname.removesuffix(BLOCK_QUALNAME).rstrip(".")
    if chunk.kind == "block":
        return qualname
    return qualname.rsplit(".", 1)[0] if "." in qualname else ""


def _header_lines(chunk: Chunk, part_label: str = "") -> list[str]:
    prefix = _comment_prefix(chunk)
    lines = [f"{prefix} {chunk.path}"]
    scope = _scope_of(chunk)
    if scope:
        lines.append(f"{prefix} in {scope}")
    if part_label:
        lines.append(f"{prefix} {part_label}")
    return lines


def _doc_lines(chunk: Chunk) -> list[str]:
    """Doc comments of non-Python code sit above the code span, so the code text lacks them."""
    if chunk.language == "python" or not chunk.docstring:
        return []
    prefix = _comment_prefix(chunk)
    return [f"{prefix} {line}".rstrip() for line in chunk.docstring.splitlines()]


def _code_body(chunk: Chunk) -> str:
    return chunk.skeleton if chunk.kind == "class" and chunk.skeleton else chunk.code


@register("code")
def build_code(chunk: Chunk, ctx: BuildContext) -> str | None:
    body = _code_body(chunk)
    if not body.strip():
        return None
    if not ctx.code_header:
        return body
    return "\n".join([*_header_lines(chunk), *_doc_lines(chunk), body])


def _windows(lines: list[str], budget: int, overlap: int) -> list[tuple[int, int]]:
    """Split lines into (first, last) windows of at most `budget` characters, overlapping by up
    to `overlap` lines. A single line longer than the budget is a window of its own."""
    windows: list[tuple[int, int]] = []
    start = 0
    n = len(lines)
    while start < n:
        size = 0
        end = start
        while end < n and (end == start or size + len(lines[end]) + 1 <= budget):
            size += len(lines[end]) + 1
            end += 1
        windows.append((start, end - 1))
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return windows


def _split_code(chunk: Chunk, ctx: BuildContext) -> list[TextPart]:
    body = _code_body(chunk)
    lines = body.split("\n")
    span = chunk.end_line - chunk.start_line
    head_len = sum(len(line) + 1 for line in _header_lines(chunk, "part 99/99")) if ctx.code_header else 0
    doc = _doc_lines(chunk) if ctx.code_header else []
    budget = max(ctx.window_chars - head_len - sum(len(line) + 1 for line in doc), 200)
    windows = _windows(lines, budget, ctx.window_overlap_lines)
    parts: list[TextPart] = []
    for i, (first, last) in enumerate(windows):
        label = f"part {i + 1}/{len(windows)}"
        head = [*_header_lines(chunk, label), *(doc if i == 0 else [])] if ctx.code_header else []
        text = "\n".join([*head, *lines[first : last + 1]])
        if chunk.kind == "class":  # a skeleton's lines are not source lines
            first, last = 0, span
        parts.append(TextPart(text[: ctx.window_chars * 2], i, len(windows), first, min(last, span)))
    return parts


def build_parts(chunk: Chunk, ctx: BuildContext, vec_type: str) -> list[TextPart]:
    """The vectors to store for one (chunk, vector type): usually one part, several windows for
    long code. Empty when the builder has nothing for this chunk."""
    builder = TEXT_BUILDERS.get(vec_type)
    if builder is None:
        raise KeyError(f"no text builder registered for vector type {vec_type!r}")
    text = builder(chunk, ctx)
    if not text:
        return []
    span = chunk.end_line - chunk.start_line
    if vec_type == "code" and len(text) > ctx.window_chars:
        return _split_code(chunk, ctx)
    return [TextPart(text[: ctx.window_chars * 2], 0, 1, 0, span)]


# --------------------------------------------------------------------------- usage


def _is_test(ref: Ref) -> bool:
    return ref.is_test if ref.is_test is not None else is_test_caller(ref.path, ref.name)


@register("usage")
def build_usage(chunk: Chunk, ctx: BuildContext) -> str | None:
    if chunk.kind == "block" or chunk.chunk_id is None:
        return None
    callers = sorted(ctx.callers.get(chunk.chunk_id, []), key=lambda r: (r.path, r.start_line))
    tests = [r for r in callers if _is_test(r)]
    users = [r for r in callers if not _is_test(r)]
    commits = ctx.commits.get(chunk.path, [])
    if not (tests or users or commits):
        return None

    # Tests are reserved up to half the budget so many callers can't crowd them out.
    tests = tests[: max(ctx.max_items // 2, ctx.max_items - len(users))]
    users = users[: ctx.max_items - len(tests)]
    lines = [f"{chunk.qualname} in {chunk.path}"]
    lines += [_caller_line("called by", "called at top level in", ref) for ref in users]
    lines += [_caller_line("tested by", "tested in", ref) for ref in tests]
    for subject in commits[:5]:
        lines.append(f"changed in commit: {subject}")
    return "\n".join(lines)


def _caller_line(verb: str, block_verb: str, ref: Ref) -> str:
    if ref.kind == "block":
        return f"{block_verb} {ref.path}"
    return f"{verb} {ref.qualname} in {ref.path}"


@register("summary")
def build_summary(chunk: Chunk, ctx: BuildContext) -> str | None:
    # Slot for LLM summaries. Enabling `vectors.summary` is a no-op until a summarizer fills this in.
    return None
