"""Go: functions, methods (qualified by their receiver type) and struct/interface types."""

from __future__ import annotations

import re

from tree_sitter import Node

from .spec import Definition, LanguageSpec, text_of

_TEST_NAME = re.compile(r"^(Test|Benchmark|Fuzz|Example)([A-Z0-9_]|$)")


class Go(LanguageSpec):
    name = "go"
    family = "go"
    extensions = (".go",)
    grammar_module = "tree_sitter_go"
    function_types = frozenset({"function_declaration", "method_declaration"})
    # A grouped `type ( A struct{}; B interface{} )` is opened like a wrapper; each spec is a type.
    transparent_types = frozenset({"type_declaration"})
    transparent_holds_items = True
    import_types = frozenset({"import_declaration", "package_clause"})
    call_types = frozenset({"call_expression"})
    definition_candidates = frozenset({"function_declaration", "method_declaration", "type_declaration", "type_spec"})
    test_file_patterns = ("*_test.go",)

    def definition(self, node: Node) -> Definition | None:
        if node.type == "type_declaration":
            specs = [c for c in node.named_children if c.type == "type_spec"]
            if len(specs) != 1:
                return None
            defn = self._type_spec(specs[0])
            if defn is not None:
                defn.outer = node
            return defn
        if node.type == "type_spec":
            return self._type_spec(node)
        defn = super().definition(node)
        if defn is not None and node.type == "method_declaration":
            receiver = self._receiver_type(node)
            defn.scope = (receiver,) if receiver else ()
        return defn

    def _type_spec(self, spec: Node) -> Definition | None:
        type_node = spec.child_by_field_name("type")
        name = text_of(spec.child_by_field_name("name"))
        if type_node is None or not name:
            return None
        if type_node.type == "struct_type":
            body = next((c for c in type_node.named_children if c.type == "field_declaration_list"), None)
            return Definition("class", name, spec, spec, body, "struct")
        if type_node.type == "interface_type":
            return Definition("class", name, spec, spec, type_node, "interface")
        return None

    @staticmethod
    def _receiver_type(method: Node) -> str:
        receiver = method.child_by_field_name("receiver")
        param = next((c for c in receiver.named_children if c.type == "parameter_declaration"), None) if receiver else None
        type_node = param.child_by_field_name("type") if param else None
        text = text_of(type_node).lstrip("*").strip()
        return text.split("[", 1)[0]  # generic receivers: `List[T]` -> `List`

    def signature(self, defn: Definition) -> str:
        if defn.kind == "class":
            return f"type {defn.name} {defn.subkind}"
        return super().signature(defn)

    def callee(self, node: Node) -> str | None:
        func = node.child_by_field_name("function")
        if func is None:
            return None
        if func.type == "identifier":
            return text_of(func)
        if func.type == "selector_expression":
            return text_of(func.child_by_field_name("field")) or None
        return None

    def is_test_definition(self, defn: Definition, attached: list[Node]) -> bool:
        return defn.kind == "function" and bool(_TEST_NAME.match(defn.name))
