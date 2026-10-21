"""tree-sitter Python chunking + call extraction.

One chunk per function/method (nested and async included, decorators included),
plus one `file_header` chunk with the module-level code outside functions.
"""

from __future__ import annotations

import ast
import inspect
import logging
from functools import lru_cache
from pathlib import PurePosixPath

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from .schema import FILE_HEADER_QUALNAME, Chunk, make_key, text_hash

log = logging.getLogger(__name__)

_SCOPE_TYPES = ("function_definition", "class_definition")


@lru_cache(maxsize=1)
def _language() -> Language:
    return Language(tree_sitter_python.language())


def _parser() -> Parser:
    # Parsers are cheap; a fresh one per call keeps this thread-safe for the watcher.
    return Parser(_language())


def _text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def _docstring(body: Node | None) -> str:
    if body is None or body.named_child_count == 0:
        return ""
    first = body.named_children[0]
    if first.type != "expression_statement" or first.named_child_count != 1:
        return ""
    string = first.named_children[0]
    if string.type != "string":
        return ""
    raw = _text(string)
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        value = raw.strip("\"'rRbBuUfF")
    return inspect.cleandoc(value) if isinstance(value, str) else ""


def _signature(fn: Node) -> str:
    body = fn.child_by_field_name("body")
    end = body.start_byte if body is not None else fn.end_byte
    raw = fn.text[: end - fn.start_byte] if fn.text is not None else b""
    sig = raw.decode("utf-8", errors="replace").strip()
    return " ".join(sig.split())  # collapse multi-line parameter lists


def callee_name(call: Node) -> str | None:
    """`foo()` -> foo; `db.sessions.delete()` -> delete; anything else -> None."""
    func = call.child_by_field_name("function")
    if func is None:
        return None
    if func.type == "identifier":
        return _text(func)
    if func.type == "attribute":
        attr = func.child_by_field_name("attribute")
        return _text(attr) or None
    return None


def _collect_calls(node: Node, out: list[str]) -> None:
    """Calls in `node`'s subtree, not descending into nested functions/classes."""
    for child in node.children:
        # Decorator calls belong to the decorated def (its chunk contains those lines).
        if child.type in _SCOPE_TYPES or child.type == "decorated_definition":
            continue
        if child.type == "call":
            name = callee_name(child)
            if name:
                out.append(name)
        _collect_calls(child, out)


def _dedupe(names: list[str]) -> list[str]:
    return list(dict.fromkeys(names))


class _Builder:
    def __init__(self, path: str, lines: list[str]):
        self.path = path
        self.lines = lines
        self.chunks: list[Chunk] = []
        self.covered: list[tuple[int, int]] = []  # 0-based inclusive line ranges of top-level defs
        self.keys: dict[str, int] = {}

    def unique_key(self, qualname: str) -> str:
        base = make_key(self.path, qualname)
        n = self.keys.get(base, 0) + 1
        self.keys[base] = n
        return base if n == 1 else f"{base}#{n}"

    def visit(self, node: Node, scope: list[tuple[str, str]], depth: int) -> None:
        for child in node.children:
            outer = child
            definition = child
            if child.type == "decorated_definition":
                definition = child.child_by_field_name("definition") or child
            if definition.type == "function_definition":
                self.add_function(definition, outer, scope, depth)
            elif definition.type == "class_definition":
                name = _text(definition.child_by_field_name("name"))
                body = definition.child_by_field_name("body")
                if body is not None:
                    self.visit(body, [*scope, ("class", name)], depth + 1)
            elif child.type not in ("string", "comment"):
                # Compound statements (if/try/with/for) can hold defs too.
                if child.child_count:
                    self.visit(child, scope, depth)

    def add_function(self, fn: Node, outer: Node, scope: list[tuple[str, str]], depth: int) -> None:
        name = _text(fn.child_by_field_name("name"))
        qualname = ".".join([s[1] for s in scope] + [name])
        in_class = bool(scope) and scope[-1][0] == "class"
        class_name = next((s[1] for s in reversed(scope) if s[0] == "class"), None)
        start, end = outer.start_point[0], outer.end_point[0]
        code = "\n".join(self.lines[start : end + 1])
        body = fn.child_by_field_name("body")
        calls: list[str] = []
        for dec in outer.children if outer is not fn else ():
            if dec.type == "decorator":
                _collect_calls(dec, calls)
        if body is not None:
            _collect_calls(body, calls)
        self.chunks.append(
            Chunk(
                key=self.unique_key(qualname),
                path=self.path,
                qualname=qualname,
                name=name,
                kind="method" if in_class else "function",
                start_line=start + 1,
                end_line=end + 1,
                signature=_signature(fn),
                docstring=_docstring(body),
                code=code,
                content_hash=text_hash(code),
                class_name=class_name,
                calls=_dedupe(calls),
            )
        )
        if not any(s[0] == "function" for s in scope):
            self.covered.append((start, end))
        if body is not None:
            self.visit(body, [*scope, ("function", name)], depth + 1)

    def file_header(self, root: Node) -> Chunk | None:
        covered = set()
        for start, end in self.covered:
            covered.update(range(start, end + 1))
        kept = [(i, line) for i, line in enumerate(self.lines) if i not in covered]
        if not any(line.strip() for _, line in kept):
            return None
        # Drop runs of blank lines left behind by removed functions.
        out: list[str] = []
        for _, line in kept:
            if line.strip() or (out and out[-1].strip()):
                out.append(line)
        code = "\n".join(out).strip("\n")
        last_line = max(i for i, line in kept if line.strip()) + 1
        calls: list[str] = []
        _collect_calls(root, calls)
        module = PurePosixPath(self.path).stem
        body_doc = _docstring(root)
        return Chunk(
            key=self.unique_key(FILE_HEADER_QUALNAME),
            path=self.path,
            qualname=FILE_HEADER_QUALNAME,
            name=module,
            kind="file_header",
            start_line=1,
            end_line=last_line,
            signature=f"module {self.path}",
            docstring=body_doc,
            code=code,
            content_hash=text_hash(code),
            calls=_dedupe(calls),
        )


def chunk_source(source: bytes | str, path: str) -> list[Chunk]:
    """Chunk one Python file. `path` is repo-relative with forward slashes."""
    data = source.encode("utf-8") if isinstance(source, str) else source
    tree = _parser().parse(data)
    root = tree.root_node
    if root.has_error:
        log.warning("parse errors in %s; chunking what tree-sitter recovered", path)
    lines = data.decode("utf-8", errors="replace").splitlines()
    builder = _Builder(path, lines)
    builder.visit(root, [], 0)
    header = builder.file_header(root)
    chunks = builder.chunks
    if header is not None:
        chunks.insert(0, header)
    return chunks
