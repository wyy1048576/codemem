import shutil
import subprocess

import pytest

from cmeval.adapters.grep import GrepRetriever
from cmeval.adapters.grep_fn import GrepFnRetriever
from cmeval.retriever import RetrieverError, check_hits

pytestmark = pytest.mark.skipif(shutil.which("rg") is None, reason="needs ripgrep (rg)")

QUERY = "`revoke_session` leaks"

SESSIONS = """\
import os
# revoke_session is called on logout


class SessionManager:
    def revoke_session(self, user):
        for s in user.sessions:
            s.close()

    def other(self):
        return self.revoke_session(None)


def disable_user(user):
    def inner():
        SessionManager().revoke_session(user)
    inner()
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repo (so .gitignore applies) with known keyword counts."""
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    root = tmp_path / "repo"
    (root / "auth").mkdir(parents=True)
    (root / "docs").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "auth" / "sessions.py").write_text(SESSIONS)  # 4 matches: lines 2, 6, 11, 16
    (root / "auth" / "users.py").write_text("def logout(u):\n    revoke_session(u)\n    revoke_session(u)\n")  # 2
    (root / "docs" / "notes.md").write_text("revoke_session " * 5 + "\n")  # 5 on one line
    (root / "ignored.py").write_text("revoke_session\n" * 9)  # in .gitignore
    (root / ".gitignore").write_text("ignored.py\n")
    (root / ".hidden.py").write_text("revoke_session\n" * 9)  # hidden file
    return root


def test_grep_ranks_files_by_match_count(repo):
    grep = GrepRetriever()
    assert grep.build(repo, repo / "idx").seconds == 0.0
    hits = grep.search(QUERY, k=50)
    assert [(h.path, h.score) for h in hits] == [("docs/notes.md", 5.0), ("auth/sessions.py", 4.0), ("auth/users.py", 2.0)]
    assert check_hits(hits, "file", 50) == hits  # no line numbers, as a file-level system must
    assert hits[0].extra["keywords"] == ["revoke_session", "leaks"]


def test_grep_text_is_rg_style_and_capped(repo):
    grep = GrepRetriever(max_lines=2)
    grep.build(repo, repo)
    sessions = next(h for h in grep.search(QUERY, 50) if h.path == "auth/sessions.py")
    assert sessions.text == "auth/sessions.py:2:# revoke_session is called on logout\nauth/sessions.py:6:    def revoke_session(self, user):"


def test_grep_ties_are_broken_by_path(tmp_path):
    (tmp_path / "b.py").write_text("token_x\n")
    (tmp_path / "a.py").write_text("token_x\n")
    grep = GrepRetriever()
    grep.build(tmp_path, tmp_path)
    assert [h.path for h in grep.search("token_x", 50)] == ["a.py", "b.py"]


def test_grep_k_and_empty_cases(repo):
    grep = GrepRetriever()
    grep.build(repo, repo)
    assert len(grep.search(QUERY, k=1)) == 1
    assert grep.search("it is not ok", k=10) == []  # no keywords
    assert grep.search("`zzz_not_in_repo`", k=10) == []  # no matches (rg exit code 1)


def test_grep_cuts_very_long_lines(tmp_path):
    (tmp_path / "min.js").write_text("x" * 2000 + " revoke_session " + "y" * 2000 + "\n")
    grep = GrepRetriever()
    grep.build(tmp_path, tmp_path)
    [hit] = grep.search(QUERY, 5)
    assert len(hit.text) < 600


def test_grep_needs_build_and_rg(tmp_path):
    with pytest.raises(RetrieverError, match="search before build"):
        GrepRetriever().search(QUERY, 5)
    with pytest.raises(RetrieverError, match="ripgrep"):
        GrepRetriever(rg=str(tmp_path / "no-rg-here"))


def test_grep_fn_ranks_functions_around_matches(repo):
    grep_fn = GrepFnRetriever()
    grep_fn.build(repo, repo)
    hits = grep_fn.search(QUERY, k=50)
    assert check_hits(hits, "line", 50) == hits
    assert [(h.path, h.symbol, h.start_line, h.end_line, h.score) for h in hits] == [
        ("auth/users.py", "logout", 1, 3, 2.0),  # most matches first
        ("auth/sessions.py", "SessionManager.revoke_session", 6, 8, 1.0),  # ties: by file rank, then line
        ("auth/sessions.py", "SessionManager.other", 10, 11, 1.0),
        ("auth/sessions.py", "disable_user.inner", 15, 16, 1.0),  # innermost function, not disable_user
    ]
    # docs/notes.md has the most matches but no grammar: dropped. Line 2 of sessions.py is outside every function.
    assert hits[3].text == "auth/sessions.py:16:        SessionManager().revoke_session(user)"


def test_grep_fn_top_files_cap(repo):
    grep_fn = GrepFnRetriever(top_files=2)  # docs/notes.md and auth/sessions.py only
    grep_fn.build(repo, repo)
    assert {h.path for h in grep_fn.search(QUERY, 50)} == {"auth/sessions.py"}


def test_grep_fn_sees_file_changes_after_update(repo):
    grep_fn = GrepFnRetriever()
    grep_fn.build(repo, repo)
    grep_fn.search(QUERY, 50)
    (repo / "auth" / "users.py").write_text("\n\ndef logout(u):\n    revoke_session(u)\n")  # moved down 2 lines
    grep_fn.update(repo, repo)
    hit = next(h for h in grep_fn.search(QUERY, 50) if h.path == "auth/users.py")
    assert (hit.start_line, hit.end_line) == (3, 4)  # the definitions cache is keyed by content


# ---- review fixes


def test_grep_fn_line_numbers_match_rg_with_a_lone_carriage_return(tmp_path):
    # rg counts "\n" only. Line 1 is "# a\r# b"; def f is on line 3, not line 4.
    (tmp_path / "m.py").write_bytes(b"# a\r# b\n\ndef f():\n    revoke_session()\n")
    grep_fn = GrepFnRetriever()
    grep_fn.build(tmp_path, tmp_path)
    [hit] = grep_fn.search(QUERY, 5)
    assert (hit.symbol, hit.start_line, hit.end_line) == ("f", 3, 4)


def test_rg_can_be_given_by_command_name():
    assert GrepRetriever(rg="rg").rg == shutil.which("rg")


@pytest.fixture
def ranked_repo(tmp_path):
    """One function with a rare keyword once; long functions and tests that repeat a common word."""
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "core.py").write_text("def fix_here():\n    return special_widget\n")
    for name in ("a", "b", "c"):
        (tmp_path / "src" / f"{name}.py").write_text("def busy():\n" + "    common = common + 1\n" * 6)
    (tmp_path / "tests" / "test_core.py").write_text("def test_it():\n" + "    special_widget(common)\n" * 9)
    (tmp_path / "notes.md").write_text("common special_widget " * 40 + "\n")
    return tmp_path


def _symbols(grep_fn, root, query="`special_widget` common"):
    grep_fn.build(root, root)
    return [(h.path, h.symbol) for h in grep_fn.search(query, 50)]


def test_grep_fn_idf_weights_rare_keywords_and_ignores_length(ranked_repo):
    naive = _symbols(GrepFnRetriever(), ranked_repo)
    assert naive[0] == ("tests/test_core.py", "test_it")  # 18 raw matches
    assert naive.index(("src/core.py", "fix_here")) > naive.index(("src/a.py", "busy"))  # 1 match < 12
    idf = _symbols(GrepFnRetriever(weighting="idf"), ranked_repo)
    # special_widget is in 3 of 6 files, common in 5: the function with both rare and common words wins,
    # then the one with the rare word once beats the long functions that repeat the common word.
    assert idf[:2] == [("tests/test_core.py", "test_it"), ("src/core.py", "fix_here")]


def test_grep_fn_tests_last(ranked_repo):
    hits = _symbols(GrepFnRetriever(weighting="idf", tests_last=True), ranked_repo)
    assert hits[0] == ("src/core.py", "fix_here") and hits[-1] == ("tests/test_core.py", "test_it")


def test_grep_fn_types_keep_docs_out_of_the_file_budget(ranked_repo):
    assert _symbols(GrepFnRetriever(top_files=1), ranked_repo) == []  # the top file is notes.md: no functions
    assert _symbols(GrepFnRetriever(top_files=1, types=["py"]), ranked_repo) == [("tests/test_core.py", "test_it")]


def test_grep_fn_clean_keywords(ranked_repo):
    grep_fn = GrepFnRetriever(clean_keywords=True)
    grep_fn.build(ranked_repo, ranked_repo)
    query = "See https://github.com/acme/demo and commit `3f31fc9a` in setup.py: `special_widget` breaks"
    naive = GrepFnRetriever()
    naive.build(ranked_repo, ranked_repo)
    removed = set(naive._keywords(query)) - set(grep_fn._keywords(query))
    assert removed == {"github.com", "3f31fc9a", "setup.py"}  # a web address, a commit hash, a file name
    assert grep_fn._keywords(query)[:2] == ["special_widget", "https"]  # plain words stay


def test_grep_fn_options_are_checked_and_described():
    with pytest.raises(RetrieverError, match="weighting 'tfidf'"):
        GrepFnRetriever(weighting="tfidf")
    described = GrepFnRetriever(types=["py"], weighting="idf", clean_keywords=True, tests_last=True).describe()
    assert (described["types"], described["weighting"], described["clean_keywords"], described["tests_last"]) == (["py"], "idf", True, True)
    assert GrepFnRetriever().describe()["weighting"] == "count"


def test_tests_last_uses_the_labelers_test_rule(tmp_path):
    (tmp_path / "pkg" / "testing").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg" / "testing" / "helpers.py").write_text("def helper():\n    special_widget(1)\n")  # library code
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    special_widget(1)\n    special_widget(2)\n")
    hits = _symbols(GrepFnRetriever(tests_last=True), tmp_path, "`special_widget`")
    assert hits == [("pkg/testing/helpers.py", "helper"), ("tests/test_a.py", "test_a")]


def test_clean_keywords_keeps_code_names_that_look_like_addresses(ranked_repo):
    grep_fn = GrepFnRetriever(clean_keywords=True)
    grep_fn.build(ranked_repo, ranked_repo)
    keywords = grep_fn._keywords("`astropy.io.fits.open` and `Response.json` fail, see https://github.com/x/y")
    assert "astropy.io.fits.open" in keywords and "response.json" in keywords and "github.com" not in keywords


def test_grep_fn_counts_keywords_on_whole_lines_and_cuts_only_the_text(tmp_path):
    (tmp_path / "long.py").write_text("def wide():\n    x = '" + "a" * 320 + "' + special_widget\n")
    (tmp_path / "short.py").write_text("def narrow():\n    return 1  # special_widget\n")
    grep_fn = GrepFnRetriever()
    grep_fn.build(tmp_path, tmp_path)
    hits = {h.path: h for h in grep_fn.search("`special_widget`", 10)}
    assert hits["long.py"].score == 1.0  # the match after column 300 counts
    rg_text = subprocess.run(["rg", "--no-config", "-n", "--with-filename", "--max-columns", "300", "--max-columns-preview",
                              "-e", "special_widget", "long.py"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    assert hits["long.py"].text == rg_text  # the hit text is cut exactly as rg shows it


def test_grep_fn_maps_cpp_and_typescript_matches_to_functions(tmp_path):
    (tmp_path / "store.cpp").write_text(
        "namespace s {\nvoid Store::revoke_session(int id) {\n    drop(id);\n}\n}\n")
    (tmp_path / "session.ts").write_text(
        "export class Manager {\n  revoke() {\n    const run = () => revoke_session(1);\n    run();\n  }\n}\n")
    grep_fn = GrepFnRetriever()
    grep_fn.build(tmp_path, tmp_path)
    hits = {(h.path, h.symbol, h.start_line, h.end_line) for h in grep_fn.search(QUERY, 5)}
    assert hits == {("store.cpp", "Store.revoke_session", 2, 4), ("session.ts", "Manager.revoke.run", 3, 3)}
