import difflib

import pytest
from conftest import FIXTURES, REMOTE_REPO

from cmeval.labels import LabelError, find_definitions, identifier_in_query, label_at_commit, label_patch
from cmeval.patches import PatchMismatch, apply_file_diff, parse_patch, split_lines
from cmeval.tasks import Gold, Span

SAMPLE = (FIXTURES / "defs_sample.py").read_text()
PATH = "auth/sessions.py"


def make_diff(old: str | None, new: str | None, path: str = PATH) -> str:
    """A git-style diff for one file. None means the file does not exist on that side."""
    head = f"diff --git a/{path} b/{path}\n"
    if old is None:
        head += "new file mode 100644\n"
    if new is None:
        head += "deleted file mode 100644\n"
    lines = difflib.unified_diff(
        split_lines(old or ""),  # like git: lines end at "\n" only
        split_lines(new or ""),
        fromfile=f"a/{path}" if old is not None else "/dev/null",
        tofile=f"b/{path}" if new is not None else "/dev/null",
    )
    return head + "".join(lines)


def edit(text: str, line: int, new_line: str) -> str:
    lines = split_lines(text)
    lines[line - 1] = new_line + "\n"
    return "".join(lines)


def insert(text: str, after: int, new_lines: str) -> str:
    lines = split_lines(text)
    return "".join(lines[:after] + [new_lines] + lines[after:])


def label(new: str, old: str = SAMPLE, path: str = PATH):
    return label_patch(make_diff(old, new, path), lambda p: old if p == path else None)


def symbols(spans):
    return [s.symbol for s in spans]


def test_find_definitions():
    defs, has_error = find_definitions(SAMPLE, "python")
    assert not has_error
    assert [(d.kind, d.symbol, d.start, d.end) for d in defs] == [
        ("function", "top", 6, 7),
        ("function", "fetch", 10, 11),
        ("function", "decorated", 14, 19),  # decorator lines included; the lambda is not a definition
        ("class", "SessionManager", 22, 42),
        ("function", "SessionManager.revoke_session", 25, 30),
        ("function", "SessionManager.revoke_session.helper", 26, 27),
        ("class", "SessionManager.Config", 32, 34),
        ("function", "SessionManager.Config.load", 33, 34),
        ("function", "SessionManager.value", 36, 38),  # property getter and setter: two definitions
        ("function", "SessionManager.value", 40, 42),
    ]


def test_change_in_method():
    r = label(edit(SAMPLE, 30, "            helper(s, force=True)"))
    assert symbols(r.gold.functions) == ["SessionManager.revoke_session"]
    assert symbols(r.gold.classes) == ["SessionManager"]
    assert r.gold.files == [PATH] and r.language == "python"
    assert r.gold.lines == [Span(PATH, 30, 30)]
    assert r.tags == {"n_gold_files": 1, "n_gold_classes": 1, "n_gold_functions": 1,
                      "module_level_change": False, "partial_labels": False, "hunks_moved": 0}


def test_change_in_nested_function_is_innermost_only():
    r = label(edit(SAMPLE, 27, "            return s.close(force=True)"))
    assert symbols(r.gold.functions) == ["SessionManager.revoke_session.helper"]
    assert symbols(r.gold.classes) == ["SessionManager"]


def test_change_in_lambda_belongs_to_enclosing_function():
    r = label(edit(SAMPLE, 18, "    square = lambda x: x ** 2"))
    assert symbols(r.gold.functions) == ["decorated"] and r.gold.classes == []


def test_change_in_decorator_belongs_to_the_function():
    r = label(edit(SAMPLE, 15, '    "changed",'))
    assert symbols(r.gold.functions) == ["decorated"]


def test_change_in_class_body_outside_methods():
    r = label(edit(SAMPLE, 23, "    timeout = 5"))
    assert r.gold.functions == [] and symbols(r.gold.classes) == ["SessionManager"]
    assert r.tags["module_level_change"] is True


def test_change_in_nested_class_method():
    r = label(edit(SAMPLE, 34, "            return {'a': 1}"))
    assert symbols(r.gold.functions) == ["SessionManager.Config.load"]
    assert symbols(r.gold.classes) == ["SessionManager.Config"]  # innermost class only


def test_change_in_import():
    r = label(edit(SAMPLE, 1, "import sys"))
    assert r.gold.functions == [] and r.gold.classes == [] and r.gold.files == [PATH]
    assert r.tags["module_level_change"] is True


def test_insertion_inside_body():
    r = label(insert(SAMPLE, 29, "            log(s)\n"))
    assert symbols(r.gold.functions) == ["SessionManager.revoke_session"]
    assert r.tags["module_level_change"] is False


def test_new_method_after_last_line_of_another():
    new = insert(SAMPLE, 30, "\n    def revoke_all(self):\n        pass\n")
    r = label(new)
    assert r.gold.functions == []  # revoke_session itself did not change
    assert symbols(r.gold.classes) == ["SessionManager"]
    assert symbols(r.unretrievable.functions) == ["SessionManager.revoke_all"]
    assert r.tags["module_level_change"] is True


def test_insertion_between_top_level_functions():
    r = label(insert(SAMPLE, 8, "def middle():\n    return 0\n\n\n"))
    assert r.gold.functions == [] and r.gold.classes == []
    assert symbols(r.unretrievable.functions) == ["middle"]


def test_insertion_at_file_start():
    r = label("import sys\n" + SAMPLE)
    assert r.gold.functions == [] and r.gold.classes == [] and r.tags["module_level_change"] is True


def test_new_file_is_unretrievable():
    r = label_patch(make_diff(None, "class New:\n    def go(self):\n        pass\n", "auth/new.py"), lambda p: None)
    assert r.gold.files == [] and r.unretrievable.files == ["auth/new.py"]
    assert symbols(r.unretrievable.classes) == ["New"]
    assert symbols(r.unretrievable.functions) == ["New.go"]


def test_deleted_file_makes_its_definitions_gold():
    r = label(None)
    assert r.gold.files == [PATH]
    assert len(r.gold.functions) == 8  # every function; the lambda is not one
    assert symbols(r.gold.classes) == ["SessionManager", "SessionManager.Config"]


def test_test_file_is_not_gold():
    r = label(edit(SAMPLE, 7, "    return a - b"), path="tests/test_sessions.py")
    assert r.gold.files == [] and r.language is None


def test_unsupported_language_is_file_level_only():
    old = "package main\n\nfunc main() {\n}\n"
    r = label(edit(old, 3, "func main() { run() }"), old=old, path="cmd/main.go")
    assert r.gold.files == ["cmd/main.go"] and r.gold.functions == []
    assert r.tags["partial_labels"] is True and r.language == "go"


def test_patch_that_does_not_fit_the_base_is_rejected():
    diff = make_diff(SAMPLE, edit(SAMPLE, 30, "            helper(s, force=True)"))
    other_base = edit(SAMPLE, 29, "        for s in self.all_sessions(user):")
    with pytest.raises(LabelError, match="auth/sessions.py: hunk at base line 2[0-9] matches nowhere"):
        label_patch(diff, lambda p: other_base)
    with pytest.raises(LabelError, match="does not exist at the base commit"):
        label_patch(diff, lambda p: None)


def test_apply_file_diff_rebuilds_the_new_file():
    new = insert(edit(SAMPLE, 23, "    timeout = 5"), 29, "            log(s)\n")
    assert apply_file_diff(SAMPLE, make_diff(SAMPLE, new)) == new
    assert apply_file_diff(None, make_diff(None, "x = 1\n", "n.py")) == "x = 1\n"
    with pytest.raises(PatchMismatch):
        apply_file_diff("totally different\n", make_diff(SAMPLE, new))


def test_label_at_commit_with_real_git_diff(remote):
    base = remote.commit({"auth/sessions.py": SAMPLE}, "add sessions")
    fixed = remote.commit({"auth/sessions.py": edit(SAMPLE, 30, "            helper(s, force=True)"), "README.md": "docs\n"})
    diff = remote.diff(base, fixed)
    sessions_diff = next(c.diff for c in parse_patch(diff) if c.path == "auth/sessions.py")
    assert apply_file_diff(SAMPLE, sessions_diff) == edit(SAMPLE, 30, "            helper(s, force=True)")
    r = label_at_commit(REMOTE_REPO, base, diff)
    assert r.gold.files == ["auth/sessions.py"]  # README.md is "other", never gold
    assert symbols(r.gold.functions) == ["SessionManager.revoke_session"]


@pytest.mark.parametrize(
    "query, expected",
    [
        ("Calling revoke_session does not log the user out", True),
        ("The `Config` object ignores env vars", True),
        ("SessionManager keeps old sessions", True),
        ("Disabled users stay logged in", False),
        ("Make the query faster", False),
        ("I want to save the file", False),
        ("calling `save()` loses data", True),
        ("x.save fails", True),
        ("crash in auth/sessions.py line 3", True),
        ("crash in sessions.py", True),
        ("old sessions are kept", False),
    ],
)
def test_identifier_in_query(query, expected):
    gold = Gold(
        files=["auth/sessions.py"],
        classes=[Span("auth/sessions.py", 1, 50, "SessionManager"), Span("auth/sessions.py", 10, 20, "SessionManager.Config")],
        functions=[Span("auth/sessions.py", 30, 40, "SessionManager.revoke_session"), Span("auth/sessions.py", 41, 45, "Store.save"),
                   Span("auth/sessions.py", 46, 49, "Query.query")],
    )
    assert identifier_in_query(query, gold) is expected


def test_diff_with_shifted_line_numbers_is_labeled_where_it_really_applies():
    """Some SWE-bench patches state line numbers that are off from the base file (git apply finds them)."""
    diff = make_diff(SAMPLE, edit(SAMPLE, 30, "            helper(s, force=True)"))
    shifted_base = "# one\n# two\n# three\n# four\n# five\n" + SAMPLE  # every line is 5 lower
    r = label_patch(diff, lambda p: shifted_base)
    assert symbols(r.gold.functions) == ["SessionManager.revoke_session"]
    assert r.gold.lines == [Span(PATH, 35, 35)]  # line 30 of the diff is line 35 of this base
    assert [(s.start, s.end) for s in r.gold.functions] == [(30, 35)]
    assert r.tags["hunks_moved"] == 1


def test_shifted_insertion_gap_moves_too():
    diff = make_diff(SAMPLE, insert(SAMPLE, 29, "            log(s)\n"))
    shifted_base = "# a\n# b\n" + SAMPLE
    r = label_patch(diff, lambda p: shifted_base)
    assert symbols(r.gold.functions) == ["SessionManager.revoke_session"] and r.tags["hunks_moved"] == 1


# ---- review fixes


def test_lines_appended_at_the_end_of_a_function_belong_to_it():
    # revoke_session ends at line 30, line 31 is blank: the new lines extend its body.
    r = label(insert(SAMPLE, 30, "        else:\n            log('none')\n"))
    assert symbols(r.gold.functions) == ["SessionManager.revoke_session"]
    assert symbols(r.gold.classes) == ["SessionManager"]
    assert r.tags["module_level_change"] is False


def test_lines_appended_at_the_end_of_the_file_belong_to_the_last_function():
    r = label(SAMPLE + "        log(v)\n")
    assert symbols(r.gold.functions) == ["SessionManager.value"]
    assert [s.start for s in r.gold.functions] == [40]  # the setter, not the getter


def test_new_decorator_belongs_to_the_function():
    r = label(insert(SAMPLE, 5, "@cache\n"))  # line 6 is "def top"
    assert symbols(r.gold.functions) == ["top"] and r.tags["module_level_change"] is False


def test_blank_line_changes_do_not_set_module_level():
    r = label(insert(SAMPLE, 31, "\n"))
    assert r.gold.functions == [] and r.tags["module_level_change"] is False


def test_form_feed_does_not_shift_line_numbers():
    base = "import os\n\x0c\n" + SAMPLE  # a page break, as in some older code
    new = base.replace("            helper(s)\n", "            helper(s, force=True)\n")
    r = label(new, old=base)
    assert symbols(r.gold.functions) == ["SessionManager.revoke_session"]
    assert r.tags["hunks_moved"] == 0 and r.gold.lines == [Span(PATH, 32, 32)]


def test_unparsable_patch_is_a_label_error():
    with pytest.raises(LabelError, match="cannot be parsed"):
        label_patch("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n-a\n", lambda p: "a\n")


@pytest.mark.parametrize(
    "query, expected",
    [
        ("the __init__ method crashes", False),  # every class has one
        ("Widget.__init__ crashes", False),  # another class
        ("SessionManager.__init__ crashes", True),
    ],
)
def test_dunder_names_count_only_with_their_class(query, expected):
    gold = Gold(files=["auth/sessions.py"], functions=[Span("auth/sessions.py", 2, 5, "SessionManager.__init__")])
    assert identifier_in_query(query, gold) is expected


# ---- C, C++, TypeScript and TSX (cmeval-labels/4)

CPP = (FIXTURES / "defs_sample.cpp").read_text()
CPP_PATH = "src/store.cpp"
TS = (FIXTURES / "defs_sample.ts").read_text()
TS_PATH = "src/session.ts"

# The macro makes tree-sitter fail: in Bar it is an error inside the function, and in Widget it
# makes the class look like a function named Widget.
MACRO = """\
DUCKDB_API void Bar(int x) {
    run(x);
}

int clean(int a) {
    return a;
}

class DUCKDB_API Widget : public Base {
public:
    void draw() { }
    int size() { return 1; }
};
"""
MACRO_PATH = "src/widget.cpp"


def test_find_definitions_cpp():
    defs, has_error = find_definitions(CPP, "cpp")
    assert not has_error
    assert [(d.kind, d.symbol, d.start, d.end) for d in defs] == [
        ("function", "store.add", 8, 10),  # namespaces are part of the symbol; struct Entry; is not a class
        ("class", "store.Store", 12, 21),
        ("function", "store.Store.count", 14, 14),  # ~Store(); is a declaration, not a definition
        ("class", "store.Store.Options", 16, 18),
        ("function", "store.Store.Options.load", 17, 17),
        ("function", "store.Store.~Store", 23, 25),  # out of the class: Store:: gives the scope
        ("function", "store.Cache.get", 27, 31),  # template line included, <T> dropped, the lambda is not one
        ("function", "store.Store.operator==", 33, 35),
        ("function", "store.Store.operator bool", 37, 39),
        ("function", "store.detail.flush.run", 42, 44),
    ]


def test_find_definitions_typescript():
    defs, has_error = find_definitions(TS, "typescript")
    assert not has_error
    assert [(d.kind, d.symbol, d.start, d.end) for d in defs] == [
        ("function", "openSession", 3, 5),  # export included
        ("function", "closeSession", 7, 9),  # an arrow function named by its const
        ("function", "ids", 11, 13),
        ("class", "Session", 15, 30),  # the class decorator before export included
        ("function", "Session.onClose", 17, 17),  # an arrow function in a class field
        ("function", "Session.constructor", 19, 21),
        ("function", "Session.title", 23, 27),  # the method decorator included
        ("function", "Session.title.format", 25, 25),  # a nested arrow const, like a nested def
        ("class", "Closable", 32, 34),  # abstract close() and interface signatures have no body
        ("class", "State", 36, 36),
        ("function", "default", 38, 40),
    ]


def test_tsx_has_its_own_grammar():
    source = "export const Card = (p: Props) => <div>{p.title}</div>;\n"
    assert find_definitions(source, "typescript")[1] is True
    defs, has_error = find_definitions(source, "tsx")
    assert not has_error and [d.symbol for d in defs] == ["Card"]


def test_c_header_falls_back_to_cpp():
    header = "#pragma once\nnamespace ui {\nclass Panel {\n    int width() { return w; }\n};\n}\n"
    defs, has_error = find_definitions(header, "c")  # .h files are "c"; this one is C++
    assert not has_error and [d.symbol for d in defs] == ["ui.Panel", "ui.Panel.width"]
    defs, has_error = find_definitions("struct point { int x; };\nint norm(int a) { return a; }\n", "c")
    assert not has_error and [d.symbol for d in defs] == ["point", "norm"]


def test_change_in_cpp_methods():
    r = label(edit(CPP, 24, "    clear(true);"), old=CPP, path=CPP_PATH)
    assert symbols(r.gold.functions) == ["store.Store.~Store"] and r.language == "cpp"
    assert r.gold.classes == []  # an out-of-class method is not inside the class's lines
    r = label(edit(CPP, 28, "    auto check = [](int x) { return x >= 0; };"), old=CPP, path=CPP_PATH)
    assert symbols(r.gold.functions) == ["store.Cache.get"]
    r = label(edit(CPP, 17, "        bool load() const { return false; }"), old=CPP, path=CPP_PATH)
    assert symbols(r.gold.functions) == ["store.Store.Options.load"] and symbols(r.gold.classes) == ["store.Store.Options"]


def test_change_in_cpp_class_body_outside_methods():
    r = label(edit(CPP, 20, "    int count_ = 1;"), old=CPP, path=CPP_PATH)
    assert r.gold.functions == [] and symbols(r.gold.classes) == ["store.Store"]
    assert r.tags["module_level_change"] is True


def test_new_cpp_overload_before_the_old_one_is_unretrievable():
    r = label(insert(CPP, 7, "int add(int a, int b, int c) {\n    return a + b + c;\n}\n\n"), old=CPP, path=CPP_PATH)
    assert r.gold.functions == []  # the old add (now second) matches by its signature; it did not change
    assert symbols(r.unretrievable.functions) == ["store.add"] and r.unretrievable.functions[0].start == 8


def test_changed_cpp_parameters_keep_the_function():
    r = label(edit(CPP, 8, "int add(int a, int b, bool checked) {"), old=CPP, path=CPP_PATH)
    assert symbols(r.gold.functions) == ["store.add"] and r.unretrievable.functions == []


def test_typescript_changes():
    r = label(insert(TS, 8, "  log(s);\n"), old=TS, path=TS_PATH)
    assert symbols(r.gold.functions) == ["closeSession"] and r.language == "typescript"
    r = label(edit(TS, 25, "    const format = (t: string) => t.trim().toLowerCase();"), old=TS, path=TS_PATH)
    assert symbols(r.gold.functions) == ["Session.title.format"] and symbols(r.gold.classes) == ["Session"]
    r = label(edit(TS, 23, "  @memoize()"), old=TS, path=TS_PATH)
    assert symbols(r.gold.functions) == ["Session.title"]
    r = label(edit(TS, 29, "  abstract close(force?: boolean): void;"), old=TS, path=TS_PATH)
    assert r.gold.functions == [] and symbols(r.gold.classes) == ["Session"]


def test_parse_errors_only_matter_where_the_change_is():
    clean = label(edit(MACRO, 6, "    return a + 1;"), old=MACRO, path=MACRO_PATH)
    assert symbols(clean.gold.functions) == ["clean"] and clean.tags["partial_labels"] is False
    for line, new_line in [(2, "    run(x + 1);"),  # in Bar, which holds the macro error
                           (11, "    void draw() { paint(); }")]:  # in the class the macro breaks
        r = label(edit(MACRO, line, new_line), old=MACRO, path=MACRO_PATH)
        assert r.gold.files == [MACRO_PATH] and r.gold.functions == [] and r.gold.classes == []
        assert r.tags["partial_labels"] is True


def test_parse_error_elsewhere_in_a_python_file_keeps_its_gold():
    broken = SAMPLE + "\n\ndef broken(:\n    pass\n"
    r = label(edit(broken, 30, "            helper(s, force=True)"), old=broken)
    assert symbols(r.gold.functions) == ["SessionManager.revoke_session"]
    assert r.tags["partial_labels"] is False
    r = label(edit(broken, len(split_lines(broken)), "    return 1"), old=broken)
    assert r.gold.functions == [] and r.tags["partial_labels"] is True


# ---- review fixes (F7 B3 step 0)


def test_cpp_defaulted_and_deleted_members_are_not_functions():
    source = "class A {\n  A() = default;\n  A(const A&) = delete;\n  A(int x) try : y(x) {} catch (...) {}\n};\n"
    defs, _ = find_definitions(source, "cpp")
    assert [(d.symbol, d.start) for d in defs] == [("A", 1), ("A.A", 4)]  # a function-try-block is one


def test_namespaces_are_part_of_the_symbol():
    source = "namespace duckdb {\nvoid A::h() {}\n}\nvoid duckdb::A::k() {}\nnamespace a::b { void f() {} }\nnamespace { void anon() {} }\n"
    assert [d.symbol for d in find_definitions(source, "cpp")[0]] == ["duckdb.A.h", "duckdb.A.k", "a.b.f", "anon"]
    ts = "export namespace Event { export function once() {} }\nnamespace A.B { function once() {} }\ndeclare module 'x' { function d(): void; function e() {} }\n"
    assert [d.symbol for d in find_definitions(ts, "typescript")[0]] == ["Event.once", "A.B.once", "e"]


def test_new_function_in_a_file_with_a_lasting_macro_error_is_unretrievable(remote):
    # A git diff: difflib would slide Bar's closing brace into the insertion (git does not).
    added = "int added(int a) {\n    return a * 2;\n}\n\n"
    base = remote.commit({MACRO_PATH: MACRO}, "add widget")
    fixed = remote.commit({MACRO_PATH: insert(MACRO, 4, added)}, "add a function between Bar and clean")
    r = label_at_commit(REMOTE_REPO, base, remote.diff(base, fixed))
    assert symbols(r.unretrievable.functions) == ["added"] and r.tags["partial_labels"] is False
    late = remote.commit({MACRO_PATH: insert(MACRO, 8, added)}, "add it right before the misread class")
    r = label_at_commit(REMOTE_REPO, fixed, remote.diff(fixed, late))
    assert r.tags["partial_labels"] is True  # an insertion next to an error region is not trusted


def test_deep_nesting_does_not_hit_the_recursion_limit():
    # Generated code (duckdb's constant tables) nests deeper than Python's recursion limit.
    deep = "int f() {\n    return " + "(" * 3000 + "1" + ")" * 3000 + ";\n}\n"
    defs, has_error = find_definitions(deep, "cpp")
    assert not has_error and [(d.symbol, d.start, d.end) for d in defs] == [("f", 1, 3)]
    deep_py = "def g():\n    return " + "[" * 3000 + "]" * 3000 + "\n"
    assert [d.symbol for d in find_definitions(deep_py, "python")[0]] == ["g"]


# ---- second review (cmeval-labels/5)


def test_definitions_inside_a_misparsed_region_are_not_new():
    base = "namespace n {\nclass S {\n  void a() {}\n  void b() {}\n  void c() {}\n};\n}\n"
    new = base.replace("  void a() {}\n", "  void a() {}\n  MACRO(x) {\n")  # the fix leaves a misparse
    r = label(new, old=base, path="src/s.cpp")
    assert r.unretrievable.functions == []  # b and c exist in the base; their new scope is not trusted


def test_inline_namespaces_drop_the_keyword():
    source = "namespace a::inline b { void f() {} }\n"
    assert [d.symbol for d in find_definitions(source, "cpp")[0]] == ["a.b.f"]


def test_added_file_with_a_parse_error_lists_its_clean_functions():
    added = "DUCKDB_API void Bar(int x) {\n    run(x);\n}\n\nint clean(int a) {\n    return a;\n}\n"
    r = label_patch(make_diff(None, added, "src/new.cpp"), lambda p: None)
    assert symbols(r.unretrievable.functions) == ["clean"]  # Bar holds the macro error
