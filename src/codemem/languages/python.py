"""Python: functions, methods, classes; decorators are part of the definition's lines."""

from __future__ import annotations

import ast
import inspect

from tree_sitter import Node

from .spec import Definition, LanguageSpec, clean_comment, end_row, text_of


def _docstring(body: Node | None) -> str:
    if body is None or body.named_child_count == 0:
        return ""
    first = body.named_children[0]
    if first.type != "expression_statement" or first.named_child_count != 1:
        return ""
    string = first.named_children[0]
    if string.type != "string":
        return ""
    raw = text_of(string)
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        value = raw.strip("\"'rRbBuUfF")
    return inspect.cleandoc(value) if isinstance(value, str) else ""


class Python(LanguageSpec):
    name = "python"
    family = "python"
    extensions = (".py", ".pyi")
    grammar_module = "tree_sitter_python"
    line_comment = "#"
    docstring_in_code = True
    function_types = frozenset({"function_definition"})
    class_types = frozenset({"class_definition"})
    transparent_types = frozenset({
        "if_statement", "elif_clause", "else_clause", "try_statement", "except_clause",
        "except_group_clause", "finally_clause", "with_statement", "for_statement", "while_statement",
    })
    block_types = frozenset({"block"})
    import_types = frozenset({"import_statement", "import_from_statement", "future_import_statement"})
    call_types = frozenset({"call"})
    definition_candidates = frozenset({"function_definition", "class_definition", "decorated_definition"})
    test_file_patterns = ("test_*.py", "*_test.py", "conftest.py", "test_*.pyi")

    def definition(self, node: Node) -> Definition | None:
        outer = node
        if node.type == "decorated_definition":
            node = node.child_by_field_name("definition") or node
        defn = super().definition(node)
        if defn is not None:
            defn.outer = outer
            if defn.kind == "class":
                defn.subkind = "class"
        return defn

    def callee(self, node: Node) -> str | None:
        func = node.child_by_field_name("function")
        if func is None:
            return None
        if func.type == "identifier":
            return text_of(func)
        if func.type == "attribute":
            return text_of(func.child_by_field_name("attribute")) or None
        return None

    def docstring(self, defn: Definition, comments: list[Node]) -> str:
        return _docstring(defn.body)

    def lead_comment(self, defn: Definition, comments: list[Node]) -> str:
        # A comment that trails code on its line (`x = 1  # note`) belongs to that code.
        own = [
            c for c in comments
            if c.prev_named_sibling is None or end_row(c.prev_named_sibling) < c.start_point[0]
        ]
        return "\n".join(clean_comment(text_of(c)) for c in own).strip()

    def module_docstring(self, root: Node) -> str:
        """The module docstring (the first statement is a string)."""
        return _docstring(root)

    def is_test_definition(self, defn: Definition, attached: list[Node]) -> bool:
        return defn.name.startswith("test_") or defn.name == "test"
