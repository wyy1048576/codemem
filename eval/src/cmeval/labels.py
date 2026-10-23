"""Gold labels: which files, classes, and functions a fix changed.

The eval suite has its own definition finder (tree-sitter). It does not use codemem's chunker:
it must work for languages codemem does not support, and a tool must not be graded with its
own ruler.

Rules, for each code file the fix changes (line numbers on the base side):
- A changed line belongs to the innermost named function that contains it (function gold)
  and to the innermost class that contains it (class gold).
- An insertion between base lines L and L+1 belongs to the innermost function (and class)
  that contains both L and L+1. A new method right after method A is not inside A.
- A change outside every function adds no function gold and sets module_level_change.
- Anonymous functions (lambdas) are not definitions; their lines belong to the enclosing one.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from tree_sitter import Language, Node, Parser

from . import repos
from .patches import FileChange, PatchMismatch, apply_file_diff, parse_patch
from .tasks import Gold, Span, Unretrievable

LABELER_VERSION = "cmeval-labels/1"


class LabelError(ValueError):
    """The patch does not fit the base code, so the task cannot be labeled."""


@dataclass(frozen=True)
class LangSpec:
    functions: frozenset[str]  # node types of named functions
    classes: frozenset[str]  # node types of classes
    wrappers: frozenset[str]  # node types whose span includes the definition (decorators)
    load: Callable[[], object]  # returns the tree-sitter language object


def _python():
    import tree_sitter_python

    return tree_sitter_python.language()


LANGUAGES: dict[str, LangSpec] = {
    "python": LangSpec(
        functions=frozenset({"function_definition"}),
        classes=frozenset({"class_definition"}),
        wrappers=frozenset({"decorated_definition"}),
        load=_python,
    ),
}


@lru_cache(maxsize=None)
def _language(name: str) -> Language:
    return Language(LANGUAGES[name].load())


@dataclass(frozen=True)
class Definition:
    kind: str  # function | class
    name: str
    symbol: str  # dotted path of enclosing classes and functions, for example Cls.method
    start: int  # 1-based, inclusive, decorators included
    end: int

    def contains(self, line: int) -> bool:
        return self.start <= line <= self.end


def find_definitions(source: str, language: str) -> tuple[list[Definition], bool]:
    """All named functions and classes in a source file, and whether the parse had errors."""
    spec = LANGUAGES[language]
    tree = Parser(_language(language)).parse(source.encode("utf-8"))
    found: list[Definition] = []

    def end_line(node: Node) -> int:
        row, col = node.end_point
        return row if col == 0 and row > node.start_point[0] else row + 1

    def walk(node: Node, scope: tuple[str, ...]) -> None:
        for child in node.children:
            kind = "function" if child.type in spec.functions else "class" if child.type in spec.classes else None
            name_node = child.child_by_field_name("name") if kind else None
            if kind and name_node is not None:
                name = name_node.text.decode("utf-8", "replace")
                outer = child.parent if child.parent is not None and child.parent.type in spec.wrappers else child
                symbol = ".".join((*scope, name))
                found.append(Definition(kind, name, symbol, outer.start_point[0] + 1, end_line(outer)))
                walk(child, (*scope, name))
            else:
                walk(child, scope)

    walk(tree.root_node, ())
    found.sort(key=lambda d: (d.start, -d.end))
    return found, tree.root_node.has_error


def _innermost(defs: list[Definition], *lines: int) -> Definition | None:
    """The containing definition with the latest start. Definitions nest, so that is the innermost."""
    best = None
    for d in defs:
        if all(d.contains(line) for line in lines) and (best is None or d.start >= best.start):
            best = d
    return best


def _ranges(lines: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for line in sorted(set(lines)):
        if out and line == out[-1][1] + 1:
            out[-1] = (out[-1][0], line)
        else:
            out.append((line, line))
    return out


def _span(path: str, d: Definition) -> Span:
    return Span(path, d.start, d.end, d.symbol)


@dataclass
class LabelResult:
    gold: Gold
    unretrievable: Unretrievable
    language: str | None
    tags: dict = field(default_factory=dict)


def label_patch(patch: str, read_base: Callable[[str], str | None]) -> LabelResult:
    """Label a code patch. read_base(path) returns a file's text at the base commit, or None."""
    gold = Gold()
    unretrievable = Unretrievable()
    module_level = False
    partial = False
    changed_by_language: Counter[str] = Counter()

    for change in parse_patch(patch):
        if change.file_class != "code":
            continue
        if change.status == "added":
            unretrievable.files.append(change.new_path)
            defs = _definitions_or_none(apply_file_diff(None, change.diff), change.language)
            for d in defs or []:
                _add_unretrievable(unretrievable, change.new_path, d)
            continue

        base_text = read_base(change.old_path)
        if base_text is None:
            raise LabelError(f"{change.old_path}: the patch changes it, but it does not exist at the base commit")
        try:
            new_text = apply_file_diff(base_text, change.diff) if change.status != "deleted" else None
        except PatchMismatch as exc:
            raise LabelError(str(exc)) from None

        gold.files.append(change.old_path)
        changed_by_language[change.language] += len(change.changed) + len(change.insert_after)
        for start, end in _ranges(change.changed + [max(L, 1) for L in change.insert_after]):
            gold.lines.append(Span(change.old_path, start, end))

        defs = _definitions_or_none(base_text, change.language)
        if defs is None:
            partial = True
            continue
        file_module_level = _label_file(change, defs, gold)
        module_level = module_level or file_module_level

        if new_text is not None:
            new_defs = _definitions_or_none(new_text, change.language) or []
            known = {(d.kind, d.symbol) for d in defs}
            for d in new_defs:
                if (d.kind, d.symbol) not in known:
                    _add_unretrievable(unretrievable, change.new_path, d)

    language = changed_by_language.most_common(1)[0][0] if changed_by_language else None
    tags = {
        "n_gold_files": len(gold.files),
        "n_gold_classes": len(gold.classes),
        "n_gold_functions": len(gold.functions),
        "module_level_change": module_level,
        "partial_labels": partial,
    }
    return LabelResult(gold, unretrievable, language, tags)


def _definitions_or_none(source: str, language: str | None) -> list[Definition] | None:
    """Definitions, or None if this file cannot be labeled (no language table or a parse error)."""
    if language not in LANGUAGES:
        return None
    defs, has_error = find_definitions(source, language)
    return None if has_error else defs


def _label_file(change: FileChange, defs: list[Definition], gold: Gold) -> bool:
    """Add the file's gold classes and functions. Returns True if a change is outside every function."""
    functions = [d for d in defs if d.kind == "function"]
    classes = [d for d in defs if d.kind == "class"]
    gold_functions: dict[Definition, None] = {}  # dicts keep insertion order
    gold_classes: dict[Definition, None] = {}
    module_level = False

    points = [(line,) for line in change.changed] + [(L, L + 1) for L in change.insert_after if L >= 1]
    if any(L < 1 for L in change.insert_after):
        module_level = True  # an insertion at the file start is outside every function
    for point in points:
        fn = _innermost(functions, *point)
        cls = _innermost(classes, *point)
        if fn is not None:
            gold_functions[fn] = None
        else:
            module_level = True
        if cls is not None:
            gold_classes[cls] = None

    path = change.old_path
    gold.functions.extend(_span(path, d) for d in sorted(gold_functions, key=lambda d: d.start))
    gold.classes.extend(_span(path, d) for d in sorted(gold_classes, key=lambda d: d.start))
    return module_level


def _add_unretrievable(unretrievable: Unretrievable, path: str, d: Definition) -> None:
    target = unretrievable.functions if d.kind == "function" else unretrievable.classes
    target.append(_span(path, d))


def label_at_commit(repo: str, commit: str, patch: str) -> LabelResult:
    return label_patch(patch, lambda path: repos.read_file(repo, commit, path))


# ---- identifier_in_query


def _looks_like_identifier(name: str) -> bool:
    """True for names that are unlikely to be plain English words: revoke_session, getUser, md5."""
    return "_" in name or any(c.isdigit() for c in name) or any(c.isupper() for c in name[1:])


def identifier_in_query(query: str, gold: Gold) -> bool:
    """True if the query names a gold function, class, or file. Used to report "easy for grep" tasks.

    A name counts as a whole word (case-sensitive) if it looks like an identifier, or if it is in
    code form (`name`, name(, .name). Plain words such as "query" or "save" do not count alone.
    A file counts by its file name with extension (sessions.py) or by its path.
    """
    for span in [*gold.functions, *gold.classes]:
        name = span.symbol.rsplit(".", 1)[-1] if span.symbol else None
        if not name:
            continue
        word = re.compile(rf"(?<![\w]){re.escape(name)}(?![\w])")
        code = re.compile(rf"`{re.escape(name)}`|(?<![\w]){re.escape(name)}\(|\.{re.escape(name)}(?![\w])")
        if (_looks_like_identifier(name) and word.search(query)) or code.search(query):
            return True
    for path in gold.files:
        file_name = path.rsplit("/", 1)[-1]
        if re.search(rf"(?<![\w.]){re.escape(file_name)}(?![\w])", query) or path in query:
            return True
    return False
