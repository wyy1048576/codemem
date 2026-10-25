"""Java: classes, interfaces, enums, records, methods and constructors. Annotations are part of
the definition's lines (they sit in its `modifiers`)."""

from __future__ import annotations

import re

from tree_sitter import Node

from .spec import Definition, LanguageSpec, text_of

_TEST_ANNOTATION = re.compile(r"@(Test|ParameterizedTest|RepeatedTest|TestFactory|TestTemplate)\b")


class Java(LanguageSpec):
    name = "java"
    family = "java"
    extensions = (".java",)
    grammar_module = "tree_sitter_java"
    function_types = frozenset({"method_declaration", "constructor_declaration", "compact_constructor_declaration"})
    class_types = frozenset({
        "class_declaration", "interface_declaration", "enum_declaration", "record_declaration",
        "annotation_type_declaration",
    })
    block_types = frozenset({"enum_body_declarations"})
    comment_types = frozenset({"line_comment", "block_comment"})
    import_types = frozenset({"import_declaration", "package_declaration"})
    call_types = frozenset({"method_invocation", "object_creation_expression"})
    definition_candidates = function_types | class_types
    test_file_patterns = ("*Test.java", "*Tests.java", "*IT.java", "Test*.java")

    def definition(self, node: Node) -> Definition | None:
        defn = super().definition(node)
        if defn is not None and node.type in ("constructor_declaration", "compact_constructor_declaration"):
            defn.subkind = "constructor"
        if defn is not None and node.type == "annotation_type_declaration":
            defn.subkind = "annotation"
        return defn

    def callee(self, node: Node) -> str | None:
        if node.type == "method_invocation":
            return text_of(node.child_by_field_name("name")) or None
        type_node = node.child_by_field_name("type")
        if type_node is None:
            return None
        if type_node.type == "generic_type":
            type_node = type_node.named_children[0] if type_node.named_child_count else None
        text = text_of(type_node)
        return text.rsplit(".", 1)[-1] or None

    def is_test_definition(self, defn: Definition, attached: list[Node]) -> bool:
        if defn.kind != "function":
            return False
        modifiers = next((c for c in defn.node.named_children if c.type == "modifiers"), None)
        return bool(_TEST_ANNOTATION.search(text_of(modifiers)))
