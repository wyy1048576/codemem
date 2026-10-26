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
- Parse errors (the narrow rule): a file with errors keeps its function and class gold if no
  changed line is on an error line and no changed line's function contains an error. Otherwise
  the file gets no function or class gold (partial_labels).
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

# 2: added lines are placed in the fixed file (4ec55f4). 3: Cython files (.pyx, .pxd) count as code.
# 4: C, C++, TypeScript and TSX definitions; the narrow parse-error rule; with the F7 path rules
# in patches.py (.tsx, CUDA and GPU kernel files, TypeScript test folders at any depth).
LABELER_VERSION = "cmeval-labels/4"


class LabelError(ValueError):
    """The patch does not fit the base code, so the task cannot be labeled."""


@dataclass(frozen=True)
class LangSpec:
    functions: frozenset[str]  # node types of named functions
    classes: frozenset[str]  # node types of classes
    wrappers: frozenset[str]  # node types whose span includes the definition (decorators, export)
    grammars: tuple[Callable[[], object], ...]  # tree-sitter language objects, tried in this order
    # Names for definition nodes: (qualifier parts..., name), or None if the node is not a definition.
    # Without it, a node is named by its "name" field.
    name_of: Callable[[Node], list[str] | None] | None = None
    needs_body: bool = False  # a class counts only with a body (C++ "struct S;" is not a class)
    leading_decorators: bool = False  # decorators just before a definition belong to it (TS methods)
    signature_of: Callable[[Node], str | None] | None = None  # tells overloads apart (C++)
    misread: Callable[[Node], bool] | None = None  # a definition that is a misparse: its lines count as errors


def _python():
    import tree_sitter_python

    return tree_sitter_python.language()


def _c():
    import tree_sitter_c

    return tree_sitter_c.language()


def _cpp():
    import tree_sitter_cpp

    return tree_sitter_cpp.language()


def _typescript():
    import tree_sitter_typescript

    return tree_sitter_typescript.language_typescript()


def _tsx():
    import tree_sitter_typescript

    return tree_sitter_typescript.language_tsx()


def _text(node: Node) -> str:
    return node.text.decode("utf-8", "replace")


def _field_name(node: Node) -> list[str] | None:
    name = node.child_by_field_name("name")
    return [_text(name)] if name is not None else None


# ---- C and C++: a function's name is inside its declarator (`int *Foo<T>::get(int x) const`)

# Declarators around the name: pointers, references, attributes, parentheses, parameters.
_C_WRAPPING_DECLARATORS = frozenset({
    "pointer_declarator", "reference_declarator", "attributed_declarator", "parenthesized_declarator",
    "function_declarator",
})


def _qualified(node: Node) -> list[str]:
    """Name parts of a C++ name: A::B::f gives [A, B, f]. Template arguments are dropped."""
    if node.type == "qualified_identifier":
        scope, name = node.child_by_field_name("scope"), node.child_by_field_name("name")
        parts = _qualified(scope) if scope is not None else []  # no scope: ::f
        return parts + (_qualified(name) if name is not None else [])
    if node.type in ("template_type", "template_function", "template_method"):
        name = node.child_by_field_name("name")
        return _qualified(name) if name is not None else []
    if node.type == "operator_cast":  # operator bool
        kind = node.child_by_field_name("type")
        return ["operator " + _text(kind)] if kind is not None else []
    return [" ".join(_text(node).split())]


def _c_declarators(node: Node) -> tuple[Node | None, Node | None]:
    """A function definition's function_declarator (or None) and the name node at the end of the chain."""
    found = None
    declarator = node.child_by_field_name("declarator")
    while declarator is not None and declarator.type in _C_WRAPPING_DECLARATORS:
        if declarator.type == "function_declarator" and found is None:
            found = declarator
        inner = declarator.child_by_field_name("declarator")
        if inner is None and declarator.named_children:  # reference_declarator has no field names
            inner = declarator.named_children[-1]
        declarator = inner
    return found, declarator


def _c_names(node: Node) -> list[str] | None:
    if node.type != "function_definition":
        name = node.child_by_field_name("name")
        return (_qualified(name) or None) if name is not None else None
    name = _c_declarators(node)[1]
    return (_qualified(name) or None) if name is not None else None


def _c_signature(node: Node) -> str | None:
    function = _c_declarators(node)[0] if node.type == "function_definition" else None
    return " ".join(_text(function).split()) if function is not None else None


def _c_misread(node: Node) -> bool:
    """A function with no parameter list. Example: the C grammar reads C++ `namespace ui {` as a
    function, and a macro can make a C++ class look like one. Not `Foo::operator bool() const`."""
    if node.type != "function_definition":
        return False
    function, name = _c_declarators(node)
    if function is not None or name is None:
        return function is None
    return not (name.type == "operator_cast" or name.type == "qualified_identifier" and "operator_cast" in {
        c.type for c in name.named_children})


# ---- TypeScript: functions can be values (`const f = () => {}`)

_TS_FUNCTION_VALUES = frozenset({"arrow_function", "function_expression", "generator_function"})


def _ts_names(node: Node) -> list[str] | None:
    if node.type in _TS_FUNCTION_VALUES:  # a definition only as `export default function () {}`
        parent = node.parent
        return ["default"] if parent is not None and parent.type == "export_statement" else None
    if node.type in ("variable_declarator", "public_field_definition"):
        value = node.child_by_field_name("value")
        if value is None or value.type not in _TS_FUNCTION_VALUES:
            return None
        name = node.child_by_field_name("name")
        if name is None or (node.type == "variable_declarator" and name.type != "identifier"):
            return None  # const { a, b } = ...
        return [_text(name)]
    return _field_name(node)


_C_FAMILY = dict(
    functions=frozenset({"function_definition"}),
    classes=frozenset({"class_specifier", "struct_specifier"}),
    wrappers=frozenset({"template_declaration"}),
    name_of=_c_names,
    needs_body=True,
    signature_of=_c_signature,
    misread=_c_misread,
)
_TS_FAMILY = dict(
    functions=frozenset({
        "function_declaration", "generator_function_declaration", "method_definition", "variable_declarator",
        "public_field_definition", *_TS_FUNCTION_VALUES,
    }),
    classes=frozenset({"class_declaration", "abstract_class_declaration", "interface_declaration", "enum_declaration"}),
    wrappers=frozenset({"export_statement", "lexical_declaration", "variable_declaration"}),
    name_of=_ts_names,
    leading_decorators=True,
)

LANGUAGES: dict[str, LangSpec] = {
    "python": LangSpec(
        functions=frozenset({"function_definition"}),
        classes=frozenset({"class_definition"}),
        wrappers=frozenset({"decorated_definition"}),
        grammars=(_python,),
    ),
    "c": LangSpec(**_C_FAMILY, grammars=(_c, _cpp)),  # .h files are often C++
    "cpp": LangSpec(**_C_FAMILY, grammars=(_cpp,)),
    "typescript": LangSpec(**_TS_FAMILY, grammars=(_typescript,)),
    "tsx": LangSpec(**_TS_FAMILY, grammars=(_tsx,)),
}


@lru_cache(maxsize=None)
def _languages(name: str) -> tuple[Language, ...]:
    return tuple(Language(load()) for load in LANGUAGES[name].grammars)


@dataclass(frozen=True)
class Definition:
    kind: str  # function | class
    name: str
    symbol: str  # dotted path of enclosing classes and functions, for example Cls.method
    start: int  # 1-based, inclusive, decorators included
    end: int
    has_error: bool = field(default=False, compare=False)  # its span contains a parse error
    signature: str | None = field(default=None, compare=False)  # C and C++: the declarator, for overloads

    def contains(self, line: int) -> bool:
        return self.start <= line <= self.end


@dataclass(frozen=True)
class Parsed:
    definitions: list[Definition]
    error_lines: frozenset[int]  # lines of parse errors (ERROR and MISSING nodes); empty if clean


def _end_line(node: Node) -> int:
    row, col = node.end_point
    return row if col == 0 and row > node.start_point[0] else row + 1


def _error_lines(root: Node) -> frozenset[int]:
    lines: set[int] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node.is_error or node.is_missing:
            lines.update(range(node.start_point[0] + 1, max(_end_line(node), node.start_point[0] + 1) + 1))
        elif node.has_error:
            stack.extend(node.children)
    return frozenset(lines)


def parse_definitions(source: str, language: str) -> Parsed:
    """All named functions and classes in a source file, and its parse-error lines.

    A language with several grammars (C, then C++) takes the first one that parses without
    errors, or else the one with the fewest error lines. Misread definitions count as errors.
    """
    data = source.encode("utf-8")
    best: Parsed | None = None
    for grammar in _languages(language):
        parsed = _parse_with(LANGUAGES[language], Parser(grammar).parse(data).root_node)
        if best is None or len(parsed.error_lines) < len(best.error_lines):
            best = parsed
        if not best.error_lines:
            break
    return best


def _parse_with(spec: LangSpec, root: Node) -> Parsed:
    found: list[Definition] = []
    errors = set(_error_lines(root)) if root.has_error else set()

    def names(node: Node, kind: str) -> list[str] | None:
        if kind == "class" and spec.needs_body and node.child_by_field_name("body") is None:
            return None
        return spec.name_of(node) if spec.name_of is not None else _field_name(node)

    def outer_of(node: Node) -> Node:
        # Wrappers can nest (export const f = () => {}). A wrapper that holds two definitions of
        # the same type (const a = () => 1, b = () => 2) belongs to neither.
        outer = node
        while outer.parent is not None and outer.parent.type in spec.wrappers:
            if sum(1 for c in outer.parent.named_children if c.type == outer.type) > 1:
                break
            outer = outer.parent
        return outer

    def start_of(outer: Node) -> Node:
        first = outer
        if spec.leading_decorators:
            while first.prev_named_sibling is not None and first.prev_named_sibling.type == "decorator":
                first = first.prev_named_sibling
        return first

    def walk(node: Node, scope: tuple[str, ...]) -> None:
        for child in node.children:
            kind = "function" if child.type in spec.functions else "class" if child.type in spec.classes else None
            parts = names(child, kind) if kind else None
            if parts:
                outer = outer_of(child)
                start, end = start_of(outer).start_point[0] + 1, _end_line(outer)
                misread = spec.misread is not None and spec.misread(child)
                if misread:
                    errors.update(range(start, end + 1))
                signature = spec.signature_of(child) if spec.signature_of is not None else None
                symbol = ".".join((*scope, *parts))
                found.append(Definition(kind, parts[-1], symbol, start, end, outer.has_error or misread, signature))
                walk(child, (*scope, *parts))
            else:
                walk(child, scope)

    walk(root, ())
    found.sort(key=lambda d: (d.start, -d.end))
    return Parsed(found, frozenset(errors))


def find_definitions(source: str, language: str) -> tuple[list[Definition], bool]:
    """All named functions and classes in a source file, and whether the parse had errors."""
    parsed = parse_definitions(source, language)
    return parsed.definitions, bool(parsed.error_lines)


def innermost(defs: list[Definition], *lines: int) -> Definition | None:
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

        base = _parsed_or_none(base_text, change.language)
        if base is None:
            partial = True
            continue
        defs = base.definitions
        new_defs = _definitions_or_none(new_text, change.language) if new_text is not None else None
        file_module_level = _label_file(path, base_text, new_text, applied, base, new_defs, gold)
        if file_module_level is None:
            partial = True  # a change touches a parse error
            continue
        module_level = module_level or file_module_level

        if new_defs is not None:
            # New in the fixed file: a symbol the base does not have, or (C and C++) a new overload.
            known = {(d.kind, d.symbol) for d in defs}
            mapping = _map_to_base(new_defs, defs)
            for d in new_defs:
                if (d.kind, d.symbol) not in known or (d.signature is not None and d not in mapping):
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


def _parsed_or_none(source: str, language: str | None) -> Parsed | None:
    """Definitions and parse-error lines, or None if the language has no table."""
    return parse_definitions(source, language) if language in LANGUAGES else None


def _definitions_or_none(source: str, language: str | None) -> list[Definition] | None:
    """Definitions, or None if this file cannot be labeled (no language table or a parse error)."""
    parsed = _parsed_or_none(source, language)
    return None if parsed is None or parsed.error_lines else parsed.definitions


def _map_to_base(new_defs: list[Definition], base_defs: list[Definition]) -> dict[Definition, Definition]:
    """Match each definition in the fixed file to the base definition with the same kind and symbol.

    A symbol can appear more than once (a property getter and setter, C++ overloads). Definitions
    with a signature (C and C++) first match the one with the same signature. The rest match in
    order: the k-th one left in the fixed file matches the k-th one left in the base file.
    """
    mapping: dict[Definition, Definition] = {}

    def match(key_of: Callable[[Definition], tuple]) -> None:
        taken = set(mapping.values())
        by_key: dict[tuple, list[Definition]] = defaultdict(list)
        for d in base_defs:
            if d not in taken:
                by_key[key_of(d)].append(d)
        seen: Counter[tuple] = Counter()
        for d in new_defs:
            if d in mapping:
                continue
            key = key_of(d)
            if seen[key] < len(by_key[key]):
                mapping[d] = by_key[key][seen[key]]
            seen[key] += 1

    if any(d.signature is not None for d in new_defs):
        match(lambda d: (d.kind, d.symbol, d.signature))
    match(lambda d: (d.kind, d.symbol))
    return mapping


def _innermost_existing(new_defs: list[Definition], line: int, mapping: dict) -> Definition | None:
    """The innermost definition around a line of the fixed file that also exists in the base file."""
    for d in sorted((d for d in new_defs if d.contains(line)), key=lambda d: d.start, reverse=True):
        if d in mapping:
            return mapping[d]
    return None


def _is_blank(lines: list[str], line: int) -> bool:
    return not (1 <= line <= len(lines)) or not lines[line - 1].strip()


class _TouchesError(Exception):
    """A changed line is on a parse error or in a function that contains one."""


def _label_file(path, base_text, new_text, applied, base: Parsed, new_defs, gold: Gold) -> bool | None:
    """Add the file's gold classes and functions. Returns True if a change is outside every function,
    or None (and adds nothing) if a change touches a parse error of the base file."""
    functions = [d for d in base.definitions if d.kind == "function"]
    classes = [d for d in base.definitions if d.kind == "class"]
    errors = base.error_lines
    gold_functions: dict[Definition, None] = {}  # dicts keep insertion order
    gold_classes: dict[Definition, None] = {}
    module_level = False

    def check(fn: Definition | None, *lines: int) -> Definition | None:
        if any(line in errors for line in lines) or (fn is not None and fn.has_error):
            raise _TouchesError
        return fn

    def add(fn: Definition | None, cls: Definition | None) -> None:
        nonlocal module_level
        if fn is not None:
            gold_functions[fn] = None
        else:
            module_level = True
        if cls is not None:
            gold_classes[cls] = None

    try:
        base_lines = split_lines(base_text)
        for line in applied.changed:
            if not _is_blank(base_lines, line):
                add(check(innermost(functions, line), line), innermost(classes, line))

        if new_defs is not None:
            for L in applied.insert_after:
                check(None, L, L + 1)  # the base side of an insertion must be clean too
            mapping = _map_to_base(new_defs, base.definitions)
            new_functions = [d for d in new_defs if d.kind == "function"]
            new_classes = [d for d in new_defs if d.kind == "class"]
            new_lines = split_lines(new_text)
            for line in applied.added_lines:
                if not _is_blank(new_lines, line):
                    add(check(_innermost_existing(new_functions, line, mapping)),
                        _innermost_existing(new_classes, line, mapping))
        else:
            # The fixed file cannot be parsed: fall back to the base side. An insertion between base
            # lines L and L+1 belongs to the innermost definition that contains both.
            for L in applied.insert_after:
                if L < 1:
                    module_level = True
                else:
                    add(check(innermost(functions, L, L + 1), L, L + 1), innermost(classes, L, L + 1))
    except _TouchesError:
        return None

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
