"""JavaScript, TypeScript and TSX: functions, methods, classes, interfaces, enums and named
function values (`const f = () => {}`, `exports.f = function () {}`)."""

from __future__ import annotations

from tree_sitter import Node

from .spec import Container, Definition, LanguageSpec, text_of

_FUNCTION_VALUES = frozenset({"arrow_function", "function_expression", "function", "generator_function"})
_DECLARATIONS = frozenset({"lexical_declaration", "variable_declaration"})


class JavaScript(LanguageSpec):
    name = "javascript"
    family = "js"
    extensions = (".js", ".jsx", ".mjs", ".cjs")
    grammar_module = "tree_sitter_javascript"
    function_types = frozenset({"function_declaration", "generator_function_declaration", "method_definition"})
    class_types = frozenset({"class_declaration"})
    decorator_types = frozenset({"decorator"})
    import_types = frozenset({"import_statement"})
    call_types = frozenset({"call_expression", "new_expression"})
    definition_candidates = frozenset({
        "function_declaration", "generator_function_declaration", "method_definition", "class_declaration",
        "abstract_class_declaration", "interface_declaration", "enum_declaration", "export_statement",
        "lexical_declaration", "variable_declaration", "public_field_definition", "field_definition",
        "expression_statement",
    })
    test_dirs = LanguageSpec.test_dirs | {"__mocks__"}
    test_file_patterns = ("*.test.*", "*.spec.*")

    def definition(self, node: Node) -> Definition | None:
        t = node.type
        if t == "export_statement":
            inner = node.child_by_field_name("declaration") or node.child_by_field_name("value")
            if inner is None:
                return None
            defn = self.definition(inner)
            if defn is None and inner.type in _FUNCTION_VALUES:
                defn = Definition("function", "default", inner, inner, inner.child_by_field_name("body"))
            if defn is not None and defn.outer is inner:
                defn.outer = node
            return defn
        if t in _DECLARATIONS:
            declarators = [c for c in node.named_children if c.type == "variable_declarator"]
            if len(declarators) != 1:
                return None
            value = declarators[0].child_by_field_name("value")
            name = text_of(declarators[0].child_by_field_name("name"))
            if value is None or value.type not in _FUNCTION_VALUES or not name:
                return None
            return Definition("function", name, declarators[0], node, value.child_by_field_name("body"), "arrow")
        if t in ("public_field_definition", "field_definition"):
            value = node.child_by_field_name("value")
            name = text_of(node.child_by_field_name("name") or node.child_by_field_name("property"))
            if value is None or value.type not in _FUNCTION_VALUES or not name:
                return None
            return Definition("function", name, node, node, value.child_by_field_name("body"), "arrow")
        if t == "expression_statement":
            expr = node.named_children[0] if node.named_child_count else None
            if expr is None or expr.type != "assignment_expression":
                return None
            right, left = expr.child_by_field_name("right"), expr.child_by_field_name("left")
            if right is None or right.type not in _FUNCTION_VALUES or left is None:
                return None
            target = left.child_by_field_name("property") if left.type == "member_expression" else left
            name = text_of(target)
            if not name or left.type not in ("member_expression", "identifier"):
                return None
            return Definition("function", name, expr, node, right.child_by_field_name("body"), "assigned")
        defn = super().definition(node)
        if defn is not None and t == "method_definition":
            defn.subkind = "constructor" if defn.name == "constructor" else ""
        return defn

    def callee(self, node: Node) -> str | None:
        func = node.child_by_field_name("constructor" if node.type == "new_expression" else "function")
        if func is None:
            return None
        if func.type == "identifier":
            return text_of(func)
        if func.type == "member_expression":
            return text_of(func.child_by_field_name("property")) or None
        return None


class TypeScript(JavaScript):
    name = "typescript"
    extensions = (".ts", ".mts", ".cts")
    grammar_module = "tree_sitter_typescript"
    grammar_function = "language_typescript"
    class_types = frozenset({"class_declaration", "abstract_class_declaration", "interface_declaration", "enum_declaration"})
    container_candidates = frozenset({"expression_statement", "internal_module"})

    def class_subkind(self, node: Node) -> str:
        return {"abstract_class_declaration": "class", "class_declaration": "class"}.get(
            node.type, super().class_subkind(node)
        )

    def container(self, node: Node) -> Container | None:
        # `namespace Auth { ... }` parses as expression_statement > internal_module.
        target = node
        if node.type == "expression_statement" and node.named_child_count == 1:
            target = node.named_children[0]
        if target.type == "internal_module":
            return Container(text_of(target.child_by_field_name("name")), target.child_by_field_name("body"))
        return None


class TSX(TypeScript):
    name = "tsx"
    extensions = (".tsx",)
    grammar_function = "language_tsx"
