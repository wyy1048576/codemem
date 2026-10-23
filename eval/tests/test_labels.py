import difflib

import pytest
from conftest import FIXTURES, REMOTE_REPO

from cmeval.labels import LabelError, find_definitions, identifier_in_query, label_at_commit, label_patch
from cmeval.patches import PatchMismatch, apply_file_diff, parse_patch
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
        (old or "").splitlines(keepends=True),
        (new or "").splitlines(keepends=True),
        fromfile=f"a/{path}" if old is not None else "/dev/null",
        tofile=f"b/{path}" if new is not None else "/dev/null",
    )
    return head + "".join(lines)


def edit(text: str, line: int, new_line: str) -> str:
    lines = text.splitlines(keepends=True)
    lines[line - 1] = new_line + "\n"
    return "".join(lines)


def insert(text: str, after: int, new_lines: str) -> str:
    lines = text.splitlines(keepends=True)
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
                      "module_level_change": False, "partial_labels": False}


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
    with pytest.raises(LabelError, match="auth/sessions.py:29: diff expects"):
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
