"""C and C++ (including CUDA): functions, methods (in-class and out-of-line `A::b`), function-like
macros, structs/unions/enums/classes, namespaces, templates, and gtest-style `TEST(Suite, Name)`.

Code inside `#if/#ifdef` and `extern "C" {}` is read as if the wrapper were not there.
"""

from __future__ import annotations

import re

from tree_sitter import Node

from .spec import Container, Definition, LanguageSpec, strip_template_args, text_of

_WRAPPING_DECLARATORS = frozenset({
    "pointer_declarator", "reference_declarator", "attributed_declarator", "parenthesized_declarator",
})
_TEST_MACROS = frozenset({"TEST", "TEST_F", "TEST_P", "TYPED_TEST", "TYPED_TEST_P", "BENCHMARK"})
_RECORD_TYPES = frozenset({"struct_specifier", "union_specifier", "enum_specifier", "class_specifier"})


class C(LanguageSpec):
    name = "c"
    family = "c"
    extensions: tuple[str, ...] = (".c", ".h")
    grammar_module = "tree_sitter_c"
    function_types = frozenset({"function_definition"})
    class_types = frozenset({"struct_specifier", "union_specifier", "enum_specifier"})
    transparent_types = frozenset({"preproc_if", "preproc_ifdef", "preproc_else", "preproc_elif", "preproc_elifdef"})
    transparent_holds_items = True
    import_types = frozenset({"preproc_include"})
    call_types = frozenset({"call_expression"})
    definition_candidates = frozenset({
        "function_definition", "preproc_function_def", "struct_specifier", "union_specifier", "enum_specifier",
        "class_specifier", "type_definition", "declaration", "template_declaration",
    })
    test_file_patterns = (
        "*_test.c", "*_test.cc", "*_test.cpp", "*_unittest.cc", "*_unittest.cpp", "test_*.c", "test_*.cc",
        "test_*.cpp", "*Test.cpp", "*Tests.cpp", "*_test.cu",
    )

    def definition(self, node: Node) -> Definition | None:
        t = node.type
        if t == "function_definition":
            named = self._declarator_name(node)
            body = node.child_by_field_name("body")
            if named is None or body is None:
                return None
            name, scope = named
            if name in _TEST_MACROS:
                return self._test_macro(node, name, body)
            subkind = "destructor" if name.startswith("~") else ""
            return Definition("function", name, node, node, body, subkind, scope)
        if t == "preproc_function_def":
            name = text_of(node.child_by_field_name("name"))
            return Definition("function", name, node, node, node.child_by_field_name("value"), "macro") if name else None
        if t in _RECORD_TYPES:
            return self._record(node, node, text_of(node.child_by_field_name("name")))
        if t == "type_definition":  # typedef struct { ... } name_t;
            inner = node.child_by_field_name("type")
            if inner is None or inner.type not in _RECORD_TYPES:
                return None
            name = text_of(inner.child_by_field_name("name")) or text_of(node.child_by_field_name("declarator"))
            return self._record(inner, node, name)
        if t == "declaration":  # struct x { ... } instance;
            inner = node.child_by_field_name("type")
            if inner is None or inner.type not in _RECORD_TYPES:
                return None
            return self._record(inner, node, text_of(inner.child_by_field_name("name")))
        return None

    def _record(self, node: Node, outer: Node, name: str) -> Definition | None:
        body = node.child_by_field_name("body")
        if body is None or node.type not in self.class_types or not name:
            return None
        name = strip_template_args(name)
        parts = [p for p in name.split("::") if p]
        return Definition("class", parts[-1], node, outer, body, node.type.removesuffix("_specifier"), tuple(parts[:-1]))

    @staticmethod
    def _declarator_name(node: Node) -> tuple[str, tuple[str, ...]] | None:
        """(name, qualifiers) of a function definition: walks pointer/reference declarators down to
        the function declarator. `SessionManager<T>::ExpireOld` -> ("ExpireOld", ("SessionManager",))."""
        d = node.child_by_field_name("declarator")
        while d is not None and d.type != "function_declarator":
            if d.type not in _WRAPPING_DECLARATORS:
                return None
            d = d.child_by_field_name("declarator") or (d.named_children[-1] if d.named_child_count else None)
        target = d.child_by_field_name("declarator") if d is not None else None
        if target is None:
            return None
        text = strip_template_args(" ".join(text_of(target).split()))
        parts = [p.strip() for p in text.split("::") if p.strip()]
        return (parts[-1], tuple(parts[:-1])) if parts else None

    def _test_macro(self, node: Node, macro: str, body: Node) -> Definition:
        """gtest `TEST(UsersTest, DisableUser) {}` parses as a function named TEST."""
        d = node.child_by_field_name("declarator")
        while d is not None and d.type != "function_declarator":
            d = d.child_by_field_name("declarator")
        params = d.child_by_field_name("parameters") if d is not None else None
        args = [" ".join(text_of(p).split()) for p in params.named_children] if params is not None else []
        name = ".".join(a for a in args if a) or macro
        return Definition("function", name, node, node, body, "test_macro")

    def signature(self, defn: Definition) -> str:
        sig = super().signature(defn)
        if defn.outer.type == "type_definition" and defn.kind == "class":  # typedef struct { ... } x_t;
            return f"typedef {sig} {defn.name}" if not sig.endswith(defn.name) else f"typedef {sig}"
        return sig

    def callee(self, node: Node) -> str | None:
        func = node.child_by_field_name("function")
        if func is None:
            return None
        if func.type == "identifier":
            return text_of(func)
        if func.type == "field_expression":
            return text_of(func.child_by_field_name("field")) or None
        if func.type in ("qualified_identifier", "template_function", "scoped_identifier"):
            name = strip_template_args(text_of(func)).rsplit("::", 1)[-1].strip()
            return name or None
        return None

    def is_test_definition(self, defn: Definition, attached: list[Node]) -> bool:
        return defn.subkind == "test_macro"


class Cpp(C):
    name = "cpp"
    extensions = (
        ".cc", ".cpp", ".cxx", ".c++", ".hpp", ".hh", ".hxx", ".h++", ".ipp", ".tpp", ".inl", ".cu", ".cuh",
    )
    grammar_module = "tree_sitter_cpp"
    class_types = C.class_types | {"class_specifier"}
    transparent_types = C.transparent_types | {"linkage_specification"}
    block_types = frozenset({"declaration_list"})
    container_candidates = frozenset({"namespace_definition"})

    def definition(self, node: Node) -> Definition | None:
        if node.type == "template_declaration":
            for child in node.named_children:
                defn = self.definition(child)
                if defn is not None:
                    if defn.outer is child:
                        defn.outer = node
                    return defn
            return None
        defn = super().definition(node)
        if defn is not None and node.type == "function_definition" and defn.subkind == "":
            if defn.scope and defn.scope[-1] == defn.name:
                defn.subkind = "constructor"
        return defn

    def container(self, node: Node) -> Container | None:
        if node.type == "namespace_definition":
            name = strip_template_args(text_of(node.child_by_field_name("name"))).replace("::", ".")
            return Container(name or "<anonymous>", node.child_by_field_name("body"))
        return None


# `.h` is C unless the file uses C++-only syntax.
_CPP_HINTS = re.compile(
    rb"^\s*(template\s*<|namespace\s+\w|class\s+\w+[^;]*\{|using\s+namespace\b|public:|private:|protected:)"
    rb"|\bstd::|::\w+\s*\(",
    re.MULTILINE,
)


def header_language(data: bytes | None) -> str:
    if data and _CPP_HINTS.search(data[:65536]):
        return "cpp"
    return "c"
