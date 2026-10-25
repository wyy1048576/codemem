"""How one programming language maps onto codemem's chunks.

The generic walker in `chunker.py` does all the traversal. A `LanguageSpec` only says which
tree-sitter node types define functions, classes and namespaces, how to read their names, which
nodes are calls, and which files and definitions are tests. A language overrides a hook where its
syntax is unusual (C declarators, Go receivers, JavaScript arrow functions).
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cached_property
from pathlib import PurePosixPath

from tree_sitter import Language, Node, Parser


def text_of(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def end_row(node: Node) -> int:
    """0-based last row of a node. A node that ends at column 0 ends on the row before: tree-sitter
    puts the end of `#define X 1\\n` or of a `///` comment at the start of the next line."""
    row, col = node.end_point
    return row - 1 if col == 0 and row > node.start_point[0] else row


_TEMPLATE_ARGS = re.compile(r"<[^<>]*>")


def strip_template_args(name: str) -> str:
    """`SessionManager<T>::ExpireOld` -> `SessionManager::ExpireOld` (nested brackets too)."""
    prev = None
    while prev != name:
        prev, name = name, _TEMPLATE_ARGS.sub("", name)
    return name


_BLOCK_COMMENT_LINE = re.compile(r"^\s*\*(?!/) ?")
_LINE_COMMENT_PREFIX = re.compile(r"^\s*(//[/!]?|#+!?) ?")


def clean_comment(text: str) -> str:
    """Comment text without its markers: `/** a\\n * b */` -> `a\\nb`, `/// a` -> `a`."""
    t = text.strip()
    if t.startswith("/*"):
        t = t[2:].lstrip("*!")
        t = t[:-2] if t.endswith("*/") else t
        lines = [_BLOCK_COMMENT_LINE.sub("", line) for line in t.split("\n")]
    else:
        lines = [_LINE_COMMENT_PREFIX.sub("", line) for line in t.split("\n")]
    return "\n".join(line.rstrip() for line in lines).strip()


@dataclass
class Definition:
    """A named function or class found by a LanguageSpec."""

    kind: str  # "function" | "class"
    name: str
    node: Node  # the definition proper: its signature and body come from here
    outer: Node  # the node whose lines are the chunk's range (decorators, export, template ...)
    body: Node | None
    subkind: str = ""
    scope: tuple[str, ...] = ()  # qualifiers the definition names itself: C++ `A::b`, Go receivers


@dataclass
class Container:
    """A namespace-like node: adds a qualifier and holds definitions, but is not a chunk itself."""

    name: str
    body: Node | None
    members: bool = False  # True for an impl block: its functions are methods and it has no code blocks


class LanguageSpec:
    name: str = ""
    family: str = ""  # languages that can call each other by name (c and cpp; javascript and typescript)
    extensions: tuple[str, ...] = ()
    grammar_module: str = ""
    grammar_function: str = "language"
    line_comment: str = "//"  # prefix for the context header written above embedded code

    function_types: frozenset[str] = frozenset()
    class_types: frozenset[str] = frozenset()
    # Wrappers that can hold definitions (`if TYPE_CHECKING:`, `#ifdef`, `extern "C" {}`). They are
    # opened only when they contain a definition; otherwise they are ordinary statements.
    transparent_types: frozenset[str] = frozenset()
    # Inside an opened wrapper: True when its items are direct children (C preprocessor), False
    # when they sit in `block_types` children (Python's `if ...: <block>`).
    transparent_holds_items: bool = False
    block_types: frozenset[str] = frozenset()  # nodes whose named children are all items
    comment_types: frozenset[str] = frozenset({"comment"})
    decorator_types: frozenset[str] = frozenset()  # sibling decorators/attributes of the next definition
    import_types: frozenset[str] = frozenset()
    call_types: frozenset[str] = frozenset()
    # Node types for which `definition()` / `container()` can return something; others are skipped
    # cheaply when searching a subtree.
    definition_candidates: frozenset[str] = frozenset()
    container_candidates: frozenset[str] = frozenset()

    test_dirs: frozenset[str] = frozenset({"tests", "__tests__", "testdata", "spec", "specs"})
    top_test_dirs: frozenset[str] = frozenset({"test", "testing"})  # only at the top or under src/
    test_file_patterns: tuple[str, ...] = ()

    # ---- grammar
    @cached_property
    def language(self) -> Language:
        module = importlib.import_module(self.grammar_module)
        return Language(getattr(module, self.grammar_function)())

    def parser(self) -> Parser:
        return Parser(self.language)

    # ---- definitions
    def definition(self, node: Node) -> Definition | None:
        """The function or class that `node` defines, or None."""
        if node.type in self.function_types:
            body = node.child_by_field_name("body")
            name = self.name_of(node)
            if body is None or not name:
                return None
            return Definition("function", name, node, node, body)
        if node.type in self.class_types:
            body = node.child_by_field_name("body")
            name = self.name_of(node)
            if body is None or not name:
                return None
            return Definition("class", name, node, node, body, subkind=self.class_subkind(node))
        return None

    def name_of(self, node: Node) -> str:
        return text_of(node.child_by_field_name("name"))

    def class_subkind(self, node: Node) -> str:
        return node.type.removesuffix("_declaration").removesuffix("_definition").removesuffix("_specifier").removesuffix("_item")

    def container(self, node: Node) -> Container | None:
        return None

    def callee(self, node: Node) -> str | None:
        """Name of the function a call node calls (`a.b.c()` -> `c`), or None."""
        return None

    def signature(self, defn: Definition) -> str:
        """The definition's text up to its body, on one line."""
        node, body = defn.node, defn.body
        raw = node.text or b""
        if body is not None and node.start_byte <= body.start_byte <= node.end_byte:
            raw = raw[: body.start_byte - node.start_byte]
        sig = " ".join(raw.decode("utf-8", errors="replace").split())
        return sig.removesuffix("{").rstrip() if sig.endswith("{") else sig

    # One rule for every language: the comment block directly above a definition is its doc text.
    # Most languages write their docs there, so it is the `docstring`. A language whose docstring
    # sits inside the definition (Python) sets `docstring_in_code`: the code text already holds
    # that docstring, and the comments above go to `lead_comment`. Texts and keyword rows read
    # whichever field holds the comments above, so a new language only declares its syntax.
    docstring_in_code: bool = False

    def docstring(self, defn: Definition, comments: list[Node]) -> str:
        """The doc comments above the definition (an in-code docstring where `docstring_in_code`)."""
        return "\n".join(clean_comment(text_of(c)) for c in comments).strip()

    def lead_comment(self, defn: Definition, comments: list[Node]) -> str:
        """The comments above the definition, where `docstring` holds an in-code docstring instead."""
        return ""

    def module_docstring(self, root: Node) -> str:
        """The file's own docstring, kept with its first block of code (Python's module docstring)."""
        return ""

    # ---- tests
    def is_test_path(self, path: str) -> bool:
        p = PurePosixPath(path)
        dirs = p.parts[:-1]
        if any(d in self.test_dirs for d in dirs):
            return True
        if dirs and dirs[0] in self.top_test_dirs:
            return True
        if len(dirs) >= 2 and dirs[0] == "src" and dirs[1] in self.top_test_dirs:
            return True
        return any(fnmatchcase(p.name, pat) for pat in self.test_file_patterns)

    def is_test_definition(self, defn: Definition, attached: list[Node]) -> bool:
        """Whether a definition is a test by its own name or attributes (`test_x`, `#[test]`)."""
        return False

    def __repr__(self) -> str:
        return f"<LanguageSpec {self.name}>"
