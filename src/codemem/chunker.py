"""tree-sitter chunking for every supported language, plus call extraction.

Chunks (see docs/data-model.md):
- one per named function or method, nested ones included, from its first decorator, annotation or
  attribute line to the end of its body;
- one per class-like type (class, struct, interface, enum, trait) covering the whole type; its
  `skeleton` (header, fields, member signatures) is what gets embedded, not the full code;
- one per block of top-level code between definitions (imports, constants, module statements),
  with its exact line range.
Anonymous functions (lambdas, callbacks) are not chunks: their lines belong to the enclosing chunk.

The walker is generic; each language's syntax is described in `codemem.languages`.
"""

from __future__ import annotations

import logging
import zlib
from collections.abc import Iterable, Iterator

from tree_sitter import Node

from .languages import LanguageSpec, get_language, language_for_path
from .languages.python import module_docstring
from .languages.spec import Container, Definition, end_row, text_of
from .schema import BLOCK_QUALNAME, Chunk, make_key, text_hash

log = logging.getLogger(__name__)

MAX_BLOCK_LINES = 200
_SKIP_FIELDS = frozenset({"condition", "name", "value", "subject", "pattern"})
_SKELETON_LINE_CHARS = 200
_LABEL_CHARS = 60
_MEMBER_SCOPES = ("class", "impl")


def split_lines(text: str) -> list[str]:
    """Lines as tree-sitter counts them: split on "\\n" only. str.splitlines() also splits on form
    feeds, \\x1c-\\x1e and \\u2028, which would shift every later line against the parse tree."""
    return [line.removesuffix("\r") for line in text.split("\n")]


def _one_line(text: str, limit: int) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 3].rstrip() + "..."


class _Walker:
    def __init__(self, spec: LanguageSpec, path: str, lines: list[str], root: Node, max_block_lines: int):
        self.spec = spec
        self.path = path
        self.lines = lines
        self.max_block_lines = max_block_lines
        self.chunks: list[Chunk] = []
        self.keys: dict[str, int] = {}
        self.test_file = spec.is_test_path(path)
        self.module_doc_row: int | None = None
        if spec.name == "python" and module_docstring(root):
            self.module_doc_row = root.named_children[0].start_point[0]
        self.module_doc = module_docstring(root) if self.module_doc_row is not None else ""

    # ---- keys
    def unique_key(self, base: str) -> str:
        n = self.keys.get(base, 0) + 1
        self.keys[base] = n
        return base if n == 1 else f"{base}#{n}"

    # ---- recognising nodes
    def definition(self, node: Node) -> Definition | None:
        if node.type not in self.spec.definition_candidates:
            return None
        return self.spec.definition(node)

    def container(self, node: Node) -> Container | None:
        if node.type not in self.spec.container_candidates:
            return None
        return self.spec.container(node)

    def has_definition(self, node: Node) -> bool:
        stack = [node]
        while stack:
            n = stack.pop()
            if self.definition(n) is not None or self.container(n) is not None:
                return True
            stack.extend(n.named_children)
        return False

    def items(self, body: Node) -> Iterator[Node]:
        """The statements and definitions of a body, with wrappers that hold definitions opened."""
        spec = self.spec
        for child in body.named_children:
            if child.type in spec.block_types:
                yield from self.items(child)
            elif child.type in spec.transparent_types and self.has_definition(child):
                yield from self.open(child)
            else:
                yield child

    def open(self, node: Node) -> Iterator[Node]:
        """Items inside an opened wrapper (`if TYPE_CHECKING:`, `#ifdef`, `extern "C" {}`)."""
        spec = self.spec
        for i, child in enumerate(node.children):
            if not child.is_named or node.field_name_for_child(i) in _SKIP_FIELDS:
                continue
            if child.type in spec.block_types:
                yield from self.items(child)
            elif child.type in spec.transparent_types:
                yield from self.open(child)
            elif spec.transparent_holds_items:
                yield child

    def attached(self, outer: Node) -> list[Node]:
        """Comments and decorators directly above a definition (no blank line in between)."""
        spec = self.spec
        out: list[Node] = []
        row = outer.start_point[0]
        prev = outer.prev_named_sibling
        while prev is not None and (prev.type in spec.comment_types or prev.type in spec.decorator_types):
            if end_row(prev) < row - 1:
                break
            out.append(prev)
            row = prev.start_point[0]
            prev = prev.prev_named_sibling
        out.reverse()
        return out

    # ---- calls
    def calls_in(self, roots: Iterable[Node], skip_definitions: bool) -> tuple[list[str], list[int]]:
        """Callee names (first occurrence order) and the line of each first call.

        With `skip_definitions`, calls inside nested named definitions belong to those definitions.
        Calls inside anonymous functions belong to the enclosing chunk.
        """
        spec = self.spec
        names: list[str] = []
        lines: list[int] = []
        seen: set[str] = set()
        stack = list(reversed(list(roots)))
        while stack:
            n = stack.pop()
            if skip_definitions and self.definition(n) is not None:
                continue
            if n.type in spec.call_types:
                name = spec.callee(n)
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
                    lines.append(n.start_point[0] + 1)
            stack.extend(reversed(n.named_children))
        return names, lines

    def call_sites(self, roots: Iterable[Node]) -> list[tuple[str, int]]:
        """Every call under `roots` as (callee name, 1-based line), in source order."""
        spec = self.spec
        sites: list[tuple[str, int]] = []
        stack = list(reversed(list(roots)))
        while stack:
            n = stack.pop()
            if n.type in spec.call_types and (name := spec.callee(n)):
                sites.append((name, n.start_point[0] + 1))
            stack.extend(reversed(n.named_children))
        return sites

    # ---- walking
    def module(self, body: Node, scope: list[tuple[str, str]]) -> None:
        """Top level or a namespace body: definitions become chunks, the code between them blocks."""
        block: list[Node] = []
        for node in self.items(body):
            defn = self.definition(node)
            if defn is not None:
                attached = self.attached(defn.outer)
                attached_ids = {a.id for a in attached}
                while block and block[-1].id in attached_ids:
                    block.pop()
                self.flush(block, scope)
                block = []
                self.emit(defn, attached, scope, None)
                continue
            cont = self.container(node)
            if cont is not None:
                self.flush(block, scope)
                block = []
                if cont.body is not None:
                    if cont.members:
                        self.members(cont.body, [*scope, ("impl", cont.name)], None, None)
                    else:
                        self.module(cont.body, [*scope, ("namespace", cont.name)])
                continue
            block.append(node)
        self.flush(block, scope)

    def members(self, body: Node, scope: list[tuple[str, str]], parent: Chunk | None, skeleton: list[str] | None) -> None:
        """A class or impl body: definitions become member chunks; other statements are skeleton lines."""
        spec = self.spec
        for node in self.items(body):
            if node.type in spec.comment_types or node.type in spec.decorator_types:
                continue
            defn = self.definition(node)
            if defn is not None:
                chunk = self.emit(defn, self.attached(defn.outer), scope, parent.key if parent else None)
                if skeleton is not None:
                    skeleton.append(_one_line(chunk.signature, _SKELETON_LINE_CHARS))
                continue
            if skeleton is not None:
                line = _one_line(text_of(node), _SKELETON_LINE_CHARS)
                if line:
                    skeleton.append(line)
            if parent is not None:  # calls in field initializers belong to the class
                names, lines = self.calls_in([node], skip_definitions=True)
                for name, line in zip(names, lines):
                    if name not in parent.calls:
                        parent.calls.append(name)
                        parent.call_lines.append(line)

    def nested(self, body: Node, scope: list[tuple[str, str]], parent_key: str) -> None:
        """A function body: only nested named definitions become chunks."""
        stack = list(reversed(body.named_children))
        while stack:
            node = stack.pop()
            defn = self.definition(node)
            if defn is not None:
                self.emit(defn, self.attached(defn.outer), scope, parent_key)
                continue
            stack.extend(reversed(node.named_children))

    def emit(self, defn: Definition, attached: list[Node], scope: list[tuple[str, str]], parent_key: str | None) -> Chunk:
        spec = self.spec
        decorators = [n for n in attached if n.type in spec.decorator_types]
        comments = [n for n in attached if n.type in spec.comment_types]
        start = min([defn.outer.start_point[0], *(d.start_point[0] for d in decorators)])
        end = max(end_row(defn.outer), start)
        names = [s[1] for s in scope] + list(defn.scope) + [defn.name]
        qualname = ".".join(n for n in names if n)
        in_members = bool(scope) and scope[-1][0] in _MEMBER_SCOPES
        kind = defn.kind
        if kind == "function" and (in_members or defn.scope):
            kind = "method"
        if defn.scope:
            class_name: str | None = defn.scope[-1]
        else:
            class_name = next((s[1] for s in reversed(scope) if s[0] in _MEMBER_SCOPES), None)
        code = "\n".join(self.lines[start : end + 1])
        # Calls: decorators (siblings, or inside a Python decorated_definition) and the body.
        roots = [*decorators, *(c for c in defn.outer.children if c.type == "decorator")]
        if defn.body is not None:
            roots.append(defn.body)
        names_called, call_lines = self.calls_in(roots, skip_definitions=True) if kind != "class" else ([], [])
        chunk = Chunk(
            key=self.unique_key(make_key(self.path, qualname)),
            path=self.path,
            qualname=qualname,
            name=defn.name,
            kind=kind,
            start_line=start + 1,
            end_line=end + 1,
            signature=spec.signature(defn),
            docstring=spec.docstring(defn, comments),
            lead_comment=spec.lead_comment(defn, comments),
            code=code,
            content_hash=text_hash(code),
            class_name=class_name,
            calls=names_called,
            language=spec.name,
            subkind=defn.subkind,
            parent_key=parent_key,
            is_test=self.test_file or spec.is_test_definition(defn, attached),
            call_lines=call_lines,
        )
        self.chunks.append(chunk)
        if defn.body is None:
            return chunk
        if defn.kind == "class":
            skeleton: list[str] = []
            self.members(defn.body, [*scope, ("class", defn.name)], chunk, skeleton)
            header = _one_line(chunk.signature, _SKELETON_LINE_CHARS)
            chunk.skeleton = "\n".join([header, *(f"    {line}" for line in skeleton)])
        else:
            self.nested(defn.body, [*scope, ("function", defn.name)], chunk.key)
        return chunk

    # ---- blocks
    def flush(self, nodes: list[Node], scope: list[tuple[str, str]]) -> None:
        """Turn a run of top-level statements into block chunks of at most max_block_lines lines."""
        group: list[Node] = []
        for node in nodes:
            if group and end_row(node) - group[0].start_point[0] + 1 > self.max_block_lines:
                self.block(group, scope)
                group = []
            group.append(node)
        if group:
            self.block(group, scope)

    def piece_bounds(self, start: int, end: int) -> list[tuple[int, int]]:
        """Rows start..end as pieces of at most max_block_lines rows. A piece also ends after a line
        whose hash has its 5 low bits clear (once it has a quarter of the maximum), so the cuts
        follow the content: inserting a line moves only the cuts near it, not every later piece."""
        size = self.max_block_lines
        if end - start < size:
            return [(start, end)]
        min_rows = max(1, size // 4)
        pieces: list[tuple[int, int]] = []
        first = start
        for row in range(start, end + 1):
            rows = row - first + 1
            boundary = rows >= min_rows and zlib.crc32(self.lines[row].encode("utf-8")) & 31 == 0
            if row == end or rows >= size or boundary:
                pieces.append((first, row))
                first = row + 1
        return pieces

    def block(self, nodes: list[Node], scope: list[tuple[str, str]]) -> None:
        spec = self.spec
        real = [n for n in nodes if n.type not in spec.comment_types]
        if not real:
            return
        start = nodes[0].start_point[0]
        end = max(end_row(n) for n in nodes)
        imports = all(n.type in spec.import_types for n in real)
        prefix = ".".join(s[1] for s in scope)
        qualname = f"{prefix}.{BLOCK_QUALNAME}" if prefix else BLOCK_QUALNAME
        names_called, call_lines = self.calls_in(real, skip_definitions=False)
        docstring = self.module_doc if real[0].start_point[0] == self.module_doc_row else ""
        # One statement can be longer than max_block_lines (a 1,668-line dict in vllm/envs.py):
        # such a run is cut by lines, so every block points at a readable range.
        pieces = self.piece_bounds(start, end)
        sites = self.call_sites(real) if len(pieces) > 1 else []
        for i, (first, last) in enumerate(pieces):
            code = "\n".join(self.lines[first : last + 1])
            if not code.strip():
                continue
            if len(pieces) == 1:
                label_row, calls, lines = real[0].start_point[0], names_called, call_lines
            else:
                label_row = next(r for r in range(first, last + 1) if self.lines[r].strip())
                calls, lines = [], []
                for name, line in sites:
                    if first < line <= last + 1 and name not in calls:
                        calls.append(name)
                        lines.append(line)
            label = "imports" if imports else _one_line(self.lines[label_row], _LABEL_CHARS)
            content_hash = text_hash(code)
            self.chunks.append(
                Chunk(
                    key=self.unique_key(make_key(self.path, f"{qualname}@{content_hash[:8]}")),
                    path=self.path,
                    qualname=qualname,
                    name=label,
                    kind="block",
                    start_line=first + 1,
                    end_line=last + 1,
                    signature=label,
                    docstring=docstring if i == 0 else "",
                    code=code,
                    content_hash=content_hash,
                    calls=calls,
                    language=spec.name,
                    subkind="imports" if imports else "statements",
                    is_test=self.test_file,
                    call_lines=lines,
                )
            )


def chunk_source(
    source: bytes | str, path: str, language: str | None = None, *, max_block_lines: int = MAX_BLOCK_LINES
) -> list[Chunk]:
    """Chunk one file. `path` is repo-relative with forward slashes; the language comes from its
    extension unless given. Raises ValueError for a file in no supported language."""
    data = source.encode("utf-8") if isinstance(source, str) else source
    lang = language or language_for_path(path, data)
    if lang is None:
        raise ValueError(f"{path}: not a supported language")
    spec = get_language(lang)
    tree = spec.parser().parse(data)
    root = tree.root_node
    if root.has_error:
        log.warning("parse errors in %s; chunking what tree-sitter recovered", path)
    lines = split_lines(data.decode("utf-8", errors="replace"))
    walker = _Walker(spec, path, lines, root, max_block_lines)
    walker.module(root, [])
    return walker.chunks
