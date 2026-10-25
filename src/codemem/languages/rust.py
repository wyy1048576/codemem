"""Rust: functions, methods (qualified by their impl type), structs, enums, unions and traits.
`#[...]` attributes are part of the definition's lines; `#[test]` marks a test."""

from __future__ import annotations

import re

from tree_sitter import Node

from .spec import Container, Definition, LanguageSpec, strip_template_args, text_of

_TEST_ATTRIBUTE = re.compile(r"#\[\s*([\w:]*::)?(test|rstest|test_case|quickcheck)\b")


class Rust(LanguageSpec):
    name = "rust"
    family = "rust"
    extensions = (".rs",)
    grammar_module = "tree_sitter_rust"
    function_types = frozenset({"function_item"})
    class_types = frozenset({"struct_item", "enum_item", "union_item", "trait_item"})
    comment_types = frozenset({"line_comment", "block_comment"})
    decorator_types = frozenset({"attribute_item"})
    import_types = frozenset({"use_declaration", "extern_crate_declaration"})
    call_types = frozenset({"call_expression"})
    definition_candidates = function_types | class_types
    container_candidates = frozenset({"mod_item", "impl_item"})
    test_file_patterns = ("*_test.rs",)

    def container(self, node: Node) -> Container | None:
        if node.type == "mod_item":
            body = node.child_by_field_name("body")
            return Container(text_of(node.child_by_field_name("name")), body) if body is not None else None
        if node.type == "impl_item":
            type_name = strip_template_args(text_of(node.child_by_field_name("type")))
            return Container(type_name.rsplit("::", 1)[-1], node.child_by_field_name("body"), members=True)
        return None

    def callee(self, node: Node) -> str | None:
        func = node.child_by_field_name("function")
        if func is not None and func.type == "generic_function":
            func = func.child_by_field_name("function")
        if func is None:
            return None
        if func.type == "identifier":
            return text_of(func)
        if func.type == "field_expression":
            return text_of(func.child_by_field_name("field")) or None
        if func.type == "scoped_identifier":
            return text_of(func.child_by_field_name("name")) or None
        return None

    def is_test_definition(self, defn: Definition, attached: list[Node]) -> bool:
        return defn.kind == "function" and any(
            c.type == "attribute_item" and _TEST_ATTRIBUTE.search(text_of(c)) for c in attached
        )
