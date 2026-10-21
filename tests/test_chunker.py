from pathlib import Path

import pytest

from codemem.chunker import chunk_source

FIXTURE = Path(__file__).parent / "fixtures" / "chunk_sample.py"


@pytest.fixture(scope="module")
def chunks():
    return {c.key: c for c in chunk_source(FIXTURE.read_bytes(), "pkg/chunk_sample.py")}


def test_keys_and_kinds(chunks):
    assert {k: c.kind for k, c in chunks.items()} == {
        "pkg/chunk_sample.py::<module>": "file_header",
        "pkg/chunk_sample.py::plain": "function",
        "pkg/chunk_sample.py::decorated": "function",
        "pkg/chunk_sample.py::fetch": "function",
        "pkg/chunk_sample.py::SessionManager.expire_old": "method",
        "pkg/chunk_sample.py::SessionManager.expire_old.is_old": "function",
        "pkg/chunk_sample.py::SessionManager.count": "method",
        "pkg/chunk_sample.py::SessionManager.count#2": "method",
    }


def test_function_fields(chunks):
    c = chunks["pkg/chunk_sample.py::plain"]
    assert (c.name, c.qualname, c.start_line, c.end_line) == ("plain", "plain", 10, 15)
    assert c.signature == "def plain(a, b=1):"
    assert c.docstring == "Add things.\n\nMore detail here."
    assert c.code.startswith("def plain(a, b=1):") and c.code.endswith("db.sessions.delete(b)")
    assert c.calls == ["helper", "delete"]
    assert c.class_name is None
    assert len(c.content_hash) == 20


def test_decorators_included(chunks):
    c = chunks["pkg/chunk_sample.py::decorated"]
    assert c.start_line == 18
    assert c.code.splitlines()[0] == "@functools.lru_cache(maxsize=None)"
    assert c.signature == "def decorated(x):"


def test_async(chunks):
    c = chunks["pkg/chunk_sample.py::fetch"]
    assert c.signature == "async def fetch(url: str) -> bytes:"
    assert c.calls == ["get"]


def test_methods_and_nested(chunks):
    m = chunks["pkg/chunk_sample.py::SessionManager.expire_old"]
    assert m.class_name == "SessionManager"
    # is_old() is called by expire_old; age() is called only inside the nested def.
    assert m.calls == ["all", "is_old"]
    nested = chunks["pkg/chunk_sample.py::SessionManager.expire_old.is_old"]
    assert nested.calls == ["age"]
    assert nested.class_name == "SessionManager"
    assert nested.start_line == 33


def test_duplicate_names_get_suffix(chunks):
    assert chunks["pkg/chunk_sample.py::SessionManager.count"].start_line == 38
    assert chunks["pkg/chunk_sample.py::SessionManager.count#2"].start_line == 42


def test_file_header(chunks):
    h = chunks["pkg/chunk_sample.py::<module>"]
    assert h.name == "chunk_sample"
    assert h.docstring == "Sample module for chunker tests."
    assert "MAX_AGE = 3600" in h.code
    assert "class SessionManager(Base):" in h.code and "timeout = 30" in h.code
    assert "def " not in h.code and "return" not in h.code
    assert "\n\n\n" not in h.code
    assert h.calls == ["configure_logging", "main"]


def test_empty_header_skipped():
    assert [c.kind for c in chunk_source("def f():\n    pass\n", "a.py")] == ["function"]
    assert chunk_source("", "a.py") == []


def test_crlf_and_broken_code_do_not_crash():
    src = b"def ok():\r\n    return 1\r\n\r\ndef broken(:\r\n    pass\r\n"
    chunks = chunk_source(src, "b.py")
    assert any(c.name == "ok" for c in chunks)
    assert all("\r" not in c.code for c in chunks)


def test_decorator_calls_belong_to_decorated_function(chunks):
    assert chunks["pkg/chunk_sample.py::decorated"].calls == ["lru_cache"]
