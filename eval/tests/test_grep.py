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
