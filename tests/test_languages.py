"""Chunking in every supported language (fixtures in tests/fixtures/lang/)."""

from pathlib import Path

import pytest

from codemem.chunker import chunk_source
from codemem.languages import get_language, language_for_path, supported_languages
from codemem.languages.spec import clean_comment

LANG = Path(__file__).parent / "fixtures" / "lang"


def _chunks(name, rel):
    return {c.qualname if c.kind != "block" else f"<block {c.start_line}>": c for c in chunk_source((LANG / name).read_bytes(), rel)}


def _summary(chunks):
    return {q: (c.kind, c.subkind, c.start_line, c.end_line) for q, c in chunks.items()}


def test_registry():
    assert supported_languages() == ["python", "javascript", "typescript", "tsx", "go", "java", "c", "cpp", "rust"]
    assert language_for_path("a/b.py") == "python" and language_for_path("x.pyi") == "python"
    assert language_for_path("k.cu") == "cpp" and language_for_path("App.TSX") == "tsx"
    assert language_for_path("README.md") is None
    assert language_for_path("x.h", b"int f(void);\n") == "c"
    assert language_for_path("x.h", b"namespace a {\nclass B {};\n}\n") == "cpp"
    with pytest.raises(ValueError):
        get_language("cobol")


def test_typescript():
    chunks = _chunks("sessions.ts", "src/auth/sessions.ts")
    s = _summary(chunks)
    assert s["revokeSession"] == ("function", "", 4, 6)  # `export` line included
    assert s["disableUser"] == ("function", "arrow", 8, 11)  # const f = async () => {}
    assert s["SessionManager"] == ("class", "class", 13, 23)
    assert s["SessionManager.expireOld"] == ("method", "", 17, 21)  # decorator line 17 included
    assert s["SessionManager.expireOld.isOld"] == ("function", "arrow", 19, 19)
    assert s["SessionManager.handler"][:2] == ("method", "arrow")
    assert s["SessionManager.constructor"][:2] == ("method", "constructor")
    assert s["Mgr"][:2] == ("class", "interface") and s["Kind"][:2] == ("class", "enum")
    assert s["Auth.inner"][:2] == ("function", "")  # namespace adds a qualifier
    assert s["legacy"][:2] == ("function", "assigned")  # module.exports.legacy = function () {}
    assert chunks["revokeSession"].docstring == "Revoke one session."
    assert chunks["revokeSession"].calls == ["delete"]
    assert chunks["disableUser"].calls == ["forEach", "revokeSession"]  # calls inside the callback count
    describe = chunks["<block 31>"]
    assert describe.kind == "block" and describe.calls == ["describe", "it", "disableUser"]


def test_javascript():
    s = _summary(_chunks("sessions.js", "lib/sessions.js"))
    assert s["revokeSession"] == ("function", "", 6, 8)
    assert s["SessionManager.create"][:1] == ("method",)
    assert s["disableUser"][:2] == ("function", "arrow")


def test_go():
    chunks = _chunks("sessions.go", "auth/sessions.go")
    s = _summary(chunks)
    assert s["RevokeSession"] == ("function", "", 7, 9)
    assert chunks["RevokeSession"].docstring == "RevokeSession deletes one session.\nIt is idempotent."
    assert s["Manager"] == ("class", "struct", 11, 13) and s["Store"][:2] == ("class", "interface")
    method = chunks["Manager.ExpireOld"]
    assert (method.kind, method.class_name) == ("method", "Manager")  # receiver type qualifies it
    assert method.signature == "func (m *Manager) ExpireOld(now int)"
    assert chunks["TestDisable"].is_test and not chunks["RevokeSession"].is_test


def test_java():
    chunks = _chunks("SessionManager.java", "src/main/java/auth/SessionManager.java")
    s = _summary(chunks)
    assert s["SessionManager"] == ("class", "class", 6, 21)
    assert s["SessionManager.revokeSession"] == ("method", "", 12, 16)  # @Override line included
    assert s["SessionManager.SessionManager"][:2] == ("method", "constructor")
    assert s["SessionManager.Inner.helper"][:1] == ("method",)
    assert s["Kind.next"][:1] == ("method",) and s["Point"][:2] == ("class", "record")
    assert chunks["SessionManager.revokeSession"].docstring == "Revoke one session."
    assert chunks["SessionManager.revokeSession"].calls == ["delete", "sessions", "record", "Audit"]


def test_rust():
    chunks = _chunks("sessions.rs", "src/sessions.rs")
    s = _summary(chunks)
    assert s["revoke_session"] == ("function", "", 4, 6)
    assert chunks["revoke_session"].docstring == "Revoke one session."
    assert s["Manager"][:2] == ("class", "struct") and s["Store"][:2] == ("class", "trait")
    assert s["Manager.expire_old"][:1] == ("method",)  # from `impl Manager`
    assert s["Manager.delete"][:1] == ("method",)  # from `impl Store for Manager`
    test = chunks["tests.disabled_user_loses_sessions"]
    assert test.is_test and (test.start_line, test.end_line) == (25, 26)  # #[test] line included


def test_c():
    chunks = _chunks("session.c", "kernel/session.c")
    s = _summary(chunks)
    assert s["revoke_session"] == ("function", "", 6, 10)  # pointer declarator: static int *revoke_session(...)
    assert chunks["revoke_session"].docstring == "Revoke one session."
    assert chunks["revoke_session"].signature == "static int *revoke_session(struct session *s)"
    assert s["REVOKE"] == ("function", "macro", 3, 3)  # ends at column 0 of the next line: still line 3
    assert s["session"] == ("class", "struct", 12, 14)
    assert s["manager_t"][:2] == ("class", "struct")  # typedef struct { ... } manager_t;
    assert chunks["manager_t"].signature == "typedef struct manager_t"
    assert s["audit"] == ("function", "", 21, 21)  # inside #ifdef
    assert chunks["<block 1>"].code.splitlines() == ["#include <stdio.h>", "#define MAX_AGE 3600"]


def test_cpp():
    chunks = _chunks("session_manager.cc", "src/auth/session_manager.cc")
    s = _summary(chunks)
    assert s["auth.SessionManager"] == ("class", "class", 6, 14)  # template line included
    assert chunks["auth.SessionManager"].docstring == "Manages sessions."
    out_of_line = chunks["auth.SessionManager.ExpireOld"]  # SessionManager<T>::ExpireOld
    assert (out_of_line.kind, out_of_line.class_name, out_of_line.start_line) == ("method", "SessionManager", 16)
    assert s["auth.RevokeSession"][:1] == ("function",)
    assert s["c_api"][:1] == ("function",)  # inside extern "C" { }
    assert s["kernel"][:1] == ("function",)  # CUDA __global__ still found
    gtest = chunks["UsersTest.DisableUser"]
    assert gtest.is_test and gtest.subkind == "test_macro" and gtest.calls == ["DisableUser"]


def test_test_paths():
    py, go, ts, java = (get_language(n) for n in ("python", "go", "typescript", "java"))
    assert py.is_test_path("tests/test_users.py") and py.is_test_path("pkg/tests/helpers.py")
    assert py.is_test_path("test/conftest.py") and not py.is_test_path("django/test/client.py")
    assert go.is_test_path("auth/users_test.go") and not go.is_test_path("auth/users.go")
    assert ts.is_test_path("web/src/users.test.ts") and ts.is_test_path("web/__tests__/a.ts")
    assert java.is_test_path("src/test/java/a/UsersTest.java")


def test_clean_comment():
    assert clean_comment("/**\n * Revoke one session.\n * Idempotent.\n */") == "Revoke one session.\nIdempotent."
    assert clean_comment("/// Doc line") == "Doc line" and clean_comment("# note") == "note"
    assert clean_comment("// a") == "a"


def test_broken_code_in_any_language_does_not_crash():
    for rel, src in [("a.ts", "function ok() { return 1 }\nfunction broken( {"), ("a.go", "func ok() {}\nfunc ("),
                     ("a.c", "int ok(void) { return 0; }\nint broken(")]:
        chunks = chunk_source(src, rel)
        assert any(c.name == "ok" for c in chunks), rel
