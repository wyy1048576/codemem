from pathlib import Path

import pytest

from codemem.chunker import chunk_source

FIXTURE = Path(__file__).parent / "fixtures" / "chunk_sample.py"


@pytest.fixture(scope="module")
def chunks():
    return {c.key: c for c in chunk_source(FIXTURE.read_bytes(), "pkg/chunk_sample.py")}


def test_keys_and_kinds(chunks):
    funcs = {k: c.kind for k, c in chunks.items() if c.kind != "block"}
    assert funcs == {
        "pkg/chunk_sample.py::plain": "function",
        "pkg/chunk_sample.py::decorated": "function",
        "pkg/chunk_sample.py::fetch": "function",
        "pkg/chunk_sample.py::SessionManager": "class",
        "pkg/chunk_sample.py::SessionManager.expire_old": "method",
        "pkg/chunk_sample.py::SessionManager.expire_old.is_old": "function",
        "pkg/chunk_sample.py::SessionManager.count": "method",
        "pkg/chunk_sample.py::SessionManager.count#2": "method",
    }
    blocks = sorted((c.start_line, c.end_line) for c in chunks.values() if c.kind == "block")
    assert blocks == [(1, 7), (47, 48)]  # the code between definitions, with exact lines
    assert all(c.language == "python" and not c.is_test for c in chunks.values())


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


def test_blocks_hold_top_level_code(chunks):
    first, last = sorted((c for c in chunks.values() if c.kind == "block"), key=lambda c: c.start_line)
    assert first.docstring == "Sample module for chunker tests."
    assert "MAX_AGE = 3600" in first.code and "def " not in first.code
    assert first.calls == ["configure_logging"] and first.call_lines == [7]
    assert first.key.startswith("pkg/chunk_sample.py::<block>@") and first.qualname == "<block>"
    assert last.code == 'if __name__ == "__main__":\n    main()' and last.calls == ["main"]
    assert last.name == 'if __name__ == "__main__":'


def test_class_chunk_and_skeleton(chunks):
    c = chunks["pkg/chunk_sample.py::SessionManager"]
    assert (c.start_line, c.end_line, c.subkind) == (29, 44, "class")
    assert c.signature == "class SessionManager(Base):"
    assert c.skeleton.splitlines() == [
        "class SessionManager(Base):",
        "    timeout = 30",
        "    def expire_old(self, now):",
        "    def count(self):",
        "    def count(self, value):",
    ]
    assert chunks["pkg/chunk_sample.py::SessionManager.expire_old"].parent_key == c.key
    assert chunks["pkg/chunk_sample.py::SessionManager.expire_old.is_old"].parent_key.endswith("expire_old")


def test_imports_only_block_is_labelled():
    chunks = chunk_source("import os\nfrom a import b\n\n\ndef f():\n    pass\n", "m.py")
    block = next(c for c in chunks if c.kind == "block")
    assert (block.name, block.subkind, block.start_line, block.end_line) == ("imports", "imports", 1, 2)


def test_long_top_level_code_splits_into_blocks():
    src = "\n".join(f"X{i} = {i}" for i in range(450)) + "\n"
    blocks = chunk_source(src, "consts.py", max_block_lines=200)
    assert [(b.start_line, b.end_line) for b in blocks] == [(1, 200), (201, 400), (401, 450)]


def test_form_feed_does_not_shift_lines():
    # str.splitlines() also splits on \f, which would shift every later line against the parse tree.
    src = "x = 1\n\f\ndef after_page_break():\n    return 'ok'\n"
    c = next(c for c in chunk_source(src, "ff.py") if c.kind == "function")
    assert c.start_line == 3 and c.code.splitlines()[0] == "def after_page_break():"


def test_definitions_inside_if_and_try_are_found():
    src = (
        "try:\n    import ujson as json\nexcept ImportError:\n    def loads(s):\n        return s\n\n"
        "if TYPE_CHECKING:\n    from x import Y\n"
    )
    chunks = chunk_source(src, "compat.py")
    assert [(c.kind, c.name) for c in chunks if c.kind != "block"] == [("function", "loads")]
    assert any("import ujson" in c.code for c in chunks if c.kind == "block")


def test_no_blocks_without_top_level_code():
    assert [c.kind for c in chunk_source("def f():\n    pass\n", "a.py")] == ["function"]
    assert chunk_source("", "a.py") == []


def test_unknown_language_is_an_error():
    with pytest.raises(ValueError, match="not a supported language"):
        chunk_source("hello", "notes.txt")


def test_crlf_and_broken_code_do_not_crash():
    src = b"def ok():\r\n    return 1\r\n\r\ndef broken(:\r\n    pass\r\n"
    chunks = chunk_source(src, "b.py")
    assert any(c.name == "ok" for c in chunks)
    assert all("\r" not in c.code for c in chunks)


def test_decorator_calls_belong_to_decorated_function(chunks):
    assert chunks["pkg/chunk_sample.py::decorated"].calls == ["lru_cache"]
