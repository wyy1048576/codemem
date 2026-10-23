"""Gold labels: which files, classes, and functions a fix changed.

The eval suite has its own definition finder (tree-sitter). It does not use codemem's chunker:
it must work for languages codemem does not support, and a tool must not be graded with its
own ruler.

Rules, for each code file the fix changes:
- A removed or changed base line belongs to the innermost named function that contains it
  (function gold) and to the innermost class that contains it (class gold).
- An added line is placed in the fixed file: the innermost function (and class) around it there
  that also exists in the base file is gold. Lines appended at the end of a function belong to
  it; a new method added after method A belongs to the class, not to A.
- Blank lines are ignored for function and class gold.
- A change outside every function adds no function gold and sets module_level_change.
- Anonymous functions (lambdas) are not definitions; their lines belong to the enclosing one.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from tree_sitter import Language, Node, Parser
from unidiff.errors import UnidiffParseError

from . import repos
from .patches import PatchMismatch, align_file_diff, apply_file_diff, parse_patch, split_lines
from .tasks import Gold, Span, Unretrievable

LABELER_VERSION = "cmeval-labels/2"


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


def innermost(defs: list[Definition], *lines: int) -> Definition | None:
    """The containing definition with the latest start. Definitions nest, so that is the innermost."""
    best = None
    for d in defs:
        if all(d.contains(line) for line in lines) and (best is None or d.start >= best.start):
            best = d
    return best


_innermost = innermost  # old private name


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
    hunks_moved = 0
    changed_by_language: Counter[str] = Counter()

    try:
        changes = parse_patch(patch)
    except UnidiffParseError as exc:
        raise LabelError(f"the patch cannot be parsed: {exc}") from None
    for change in changes:
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
            applied = align_file_diff(base_text, change.diff)
        except PatchMismatch as exc:
            raise LabelError(str(exc)) from None
        hunks_moved += sum(1 for offset in applied.offsets if offset)
        new_text = applied.new_text if change.status != "deleted" else None

        path = change.old_path
        gold.files.append(path)
        changed_by_language[change.language] += len(applied.changed) + len(applied.insert_after)
        for start, end in _ranges(applied.changed + [max(L, 1) for L in applied.insert_after]):
            gold.lines.append(Span(path, start, end))

        defs = _definitions_or_none(base_text, change.language)
        if defs is None:
            partial = True
            continue
        new_defs = _definitions_or_none(new_text, change.language) if new_text is not None else None
        file_module_level = _label_file(path, base_text, new_text, applied, defs, new_defs, gold)
        module_level = module_level or file_module_level

        if new_defs is not None:
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
        "hunks_moved": hunks_moved,
    }
    return LabelResult(gold, unretrievable, language, tags)


def _definitions_or_none(source: str, language: str | None) -> list[Definition] | None:
    """Definitions, or None if this file cannot be labeled (no language table or a parse error)."""
    if language not in LANGUAGES:
        return None
    defs, has_error = find_definitions(source, language)
    return None if has_error else defs


def _map_to_base(new_defs: list[Definition], base_defs: list[Definition]) -> dict[Definition, Definition]:
    """Match each definition in the fixed file to the base definition with the same kind and symbol.

    A symbol can appear more than once (a property getter and setter); the k-th one in the fixed
    file matches the k-th one in the base file.
    """
    by_key: dict[tuple[str, str], list[Definition]] = defaultdict(list)
    for d in base_defs:
        by_key[(d.kind, d.symbol)].append(d)
    seen: Counter[tuple[str, str]] = Counter()
    mapping: dict[Definition, Definition] = {}
    for d in new_defs:
        key = (d.kind, d.symbol)
        if seen[key] < len(by_key[key]):
            mapping[d] = by_key[key][seen[key]]
        seen[key] += 1
    return mapping


def _innermost_existing(new_defs: list[Definition], line: int, mapping: dict) -> Definition | None:
    """The innermost definition around a line of the fixed file that also exists in the base file."""
    for d in sorted((d for d in new_defs if d.contains(line)), key=lambda d: d.start, reverse=True):
        if d in mapping:
            return mapping[d]
    return None


def _is_blank(lines: list[str], line: int) -> bool:
    return not (1 <= line <= len(lines)) or not lines[line - 1].strip()


def _label_file(path, base_text, new_text, applied, defs, new_defs, gold: Gold) -> bool:
    """Add the file's gold classes and functions. Returns True if a change is outside every function."""
    functions = [d for d in defs if d.kind == "function"]
    classes = [d for d in defs if d.kind == "class"]
    gold_functions: dict[Definition, None] = {}  # dicts keep insertion order
    gold_classes: dict[Definition, None] = {}
    module_level = False

    def add(fn: Definition | None, cls: Definition | None) -> None:
        nonlocal module_level
        if fn is not None:
            gold_functions[fn] = None
        else:
            module_level = True
        if cls is not None:
            gold_classes[cls] = None

    base_lines = split_lines(base_text)
    for line in applied.changed:
        if not _is_blank(base_lines, line):
            add(_innermost(functions, line), _innermost(classes, line))

    if new_defs is not None:
        mapping = _map_to_base(new_defs, defs)
        new_functions = [d for d in new_defs if d.kind == "function"]
        new_classes = [d for d in new_defs if d.kind == "class"]
        new_lines = split_lines(new_text)
        for line in applied.added_lines:
            if not _is_blank(new_lines, line):
                add(_innermost_existing(new_functions, line, mapping), _innermost_existing(new_classes, line, mapping))
    else:
        # The fixed file cannot be parsed: fall back to the base side. An insertion between base
        # lines L and L+1 belongs to the innermost definition that contains both.
        for L in applied.insert_after:
            if L < 1:
                module_level = True
            else:
                add(_innermost(functions, L, L + 1), _innermost(classes, L, L + 1))

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


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def identifier_in_query(query: str, gold: Gold) -> bool:
    """True if the query names a gold function, class, or file. Used to report "easy for grep" tasks.

    A name counts as a whole word (case-sensitive) if it looks like an identifier, or if it is in
    code form (`name`, name(, .name). Plain words such as "query" or "save" do not count alone.
    Dunder methods (__init__, __repr__) belong to every class, so they count only together with
    their class: Foo.__init__. A file counts by its file name with extension (sessions.py) or by
    its path.
    """
    for span in [*gold.functions, *gold.classes]:
        if not span.symbol:
            continue
        parts = span.symbol.split(".")
        name = parts[-1]
        if _is_dunder(name):
            if len(parts) > 1 and re.search(rf"(?<![\w]){re.escape(parts[-2])}\.{re.escape(name)}(?![\w])", query):
                return True
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
