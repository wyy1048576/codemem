"""`codemem hook` on the user's prompt (UserPromptSubmit): the starting search. The first two hooks
(PreToolUse, PostToolUse) are tested in test_frontends.py."""

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from gitrepo import commit, git, needs_git

import codemem
from codemem import hook, prompts
from codemem.cli import main
from codemem.config import default_index_dir
from codemem.embedder import LocalModelUnavailable
from codemem.service import CodememService
from codemem.store import Store

GOLDEN = Path(__file__).parent / "fixtures" / "start_search_block.json"
QUERY = "revoke every session of a user"


@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")


@pytest.fixture
def indexed(sample_repo, fake_env, capsys):
    """The sample repo with its default index, as `codemem index` builds it."""
    assert main(["index", str(sample_repo)]) == 0
    capsys.readouterr()
    return sample_repo


def _prompt(cwd, prompt: str = QUERY, session: str = "s1") -> str:
    event = {"session_id": session, "transcript_path": "/x/s.jsonl", "cwd": str(cwd), "permission_mode": "default",
             "hook_event_name": "UserPromptSubmit", "prompt": prompt}
    out = io.StringIO()
    assert hook.run(io.StringIO(json.dumps(event)), out) == 0
    return out.getvalue()


def _cli_results(repo, capsys) -> list[dict]:
    """The results of `codemem search -k 20 --json` for QUERY."""
    assert main(["search", QUERY, "--repo", str(repo), "-k", "20", "--json"]) == 0
    return json.loads(capsys.readouterr().out)["results"]


def test_the_block_is_the_text_of_the_golden_file():
    golden = json.loads(GOLDEN.read_text("utf-8"))
    assert prompts.start_search_block(golden["results"]) == golden["text"]
    assert hook.START_K == golden["k"] == 20
    assert golden["text"].splitlines()[0] == prompts.START_SEARCH_HEADER


def test_the_first_prompt_gets_the_search_of_codemem_search_and_later_ones_nothing(indexed, capsys):
    out = json.loads(_prompt(indexed))["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    results = _cli_results(indexed, capsys)
    assert out["additionalContext"] == prompts.start_search_block(results)
    lines = out["additionalContext"].splitlines()
    assert lines[0] == prompts.START_SEARCH_HEADER and len(lines) == 1 + len(results) > 1
    assert lines[1] == f"{results[0]['path']}:{results[0]['start_line']}  {results[0]['qualname']}"
    # Later prompts of the session get nothing; a new session gets its own search.
    assert _prompt(indexed) == "" and _prompt(indexed, "and the users?") == ""
    assert "additionalContext" in _prompt(indexed, session="s2")


@needs_git
def test_the_search_is_made_in_the_repository_that_holds_cwd(sample_repo, fake_env, capsys):
    git(sample_repo, "init", "-q", "-b", "main")
    commit(sample_repo, "A")
    assert main(["index", str(sample_repo)]) == 0
    capsys.readouterr()
    out = json.loads(_prompt(sample_repo / "auth"))["hookSpecificOutput"]
    assert out["additionalContext"] == prompts.start_search_block(_cli_results(sample_repo, capsys))


def test_no_index_gives_nothing_and_the_session_is_done(sample_repo, fake_env, capsys):
    assert _prompt(sample_repo) == ""
    # The first prompt had its turn: an index built later does not reach the next prompt.
    assert main(["index", str(sample_repo)]) == 0
    capsys.readouterr()
    assert _prompt(sample_repo, "the second prompt") == ""


def test_an_index_whose_build_has_not_finished_gives_nothing(sample_repo, fake_env):
    Store(default_index_dir(sample_repo)).close()  # the folder and the store, and no finished build
    assert _prompt(sample_repo) == ""


def test_a_search_by_keywords_only_gives_nothing(indexed, monkeypatch, capsys):
    real = CodememService.search
    monkeypatch.setattr(CodememService, "search", lambda self, q, **kw: real(self, q, **{**kw, "signals": ["bm25"]}))
    assert _cli_results(indexed, capsys)  # the keywords find something
    assert _prompt(indexed) == ""


@pytest.mark.parametrize("error", [LocalModelUnavailable("no PyTorch here"), RuntimeError("boom"), OSError("disk")])
def test_a_search_that_fails_gives_nothing(indexed, monkeypatch, error):
    def fail(self, q, **kw):
        raise error

    monkeypatch.setattr(CodememService, "search", fail)
    assert _prompt(indexed) == ""


def test_a_search_that_finds_nothing_gives_nothing(tmp_path, fake_env, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "notes.txt").write_text("no code here\n")
    assert main(["index", str(empty)]) == 0
    capsys.readouterr()
    assert CodememService(empty).has_index() and _cli_results(empty, capsys) == []
    assert _prompt(empty) == ""


def test_what_is_not_a_prompt_of_a_session_gives_nothing(indexed):
    for event in ({"prompt": QUERY, "cwd": str(indexed)},  # no session
                  {"session_id": "s1", "cwd": str(indexed)},  # no prompt
                  {"session_id": "s1", "prompt": "  ", "cwd": str(indexed)},
                  {"session_id": "s1", "prompt": QUERY},  # no cwd
                  {"session_id": "s1", "prompt": QUERY, "cwd": 3}):
        out = io.StringIO()
        assert hook.run(io.StringIO(json.dumps({"hook_event_name": "UserPromptSubmit", **event})), out) == 0
        assert out.getvalue() == ""
    assert "additionalContext" in _prompt(indexed)  # none of them took the session's first search


def test_a_search_past_its_limit_gives_nothing(indexed, monkeypatch):
    monkeypatch.setattr(hook, "_worker", None)  # put back after the test, so no later test sees this search
    monkeypatch.setattr(hook, "START_SECONDS", 0.2)
    monkeypatch.setattr(hook, "_search", lambda prompt, cwd: time.sleep(1.5) or [{"path": "a.py", "start_line": 1}])
    t0 = time.monotonic()
    assert _prompt(indexed) == ""
    assert time.monotonic() - t0 < 1.0 and hook.search_left_running()
    hook._worker.join()


def _python(code: str, tmp_path, timeout: float = 60) -> subprocess.CompletedProcess:
    """Run `code` in a Python of its own, on this codemem, with a codemem home in tmp_path."""
    env = {**os.environ, "PYTHONPATH": str(Path(codemem.__file__).parents[1]), "CODEMEM_HOME": str(tmp_path / "home")}
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=timeout)


def test_the_command_leaves_a_search_past_its_limit_and_exits_0(tmp_path):
    code = """
import io, json, sys, time
from codemem import hook
hook.START_SECONDS = 0.5
hook._search = lambda prompt, cwd: time.sleep(30) or [{"path": "a.py", "start_line": 1}]
sys.stdin = io.StringIO(json.dumps({"session_id": "s1", "hook_event_name": "UserPromptSubmit", "prompt": "q",
                                    "cwd": "."}))
from codemem.cli import main
main(["hook"])
print("not reached")
"""
    t0 = time.monotonic()
    done = _python(code, tmp_path)
    assert (done.returncode, done.stdout) == (0, "") and time.monotonic() - t0 < 20


def test_the_two_fast_hooks_import_no_search_stack(tmp_path):
    """Importing codemem.hook and answering a PreToolUse or PostToolUse event, or a later prompt of a
    session, loads neither torch nor faiss nor codemem's search stack."""
    code = """
import io, json, sys
from codemem import hook
from codemem.cli import main
events = [
    {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Grep", "tool_input": {}},
    {"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Grep", "tool_input": {},
     "tool_response": {"mode": "files_with_matches", "filenames": [], "numFiles": 0}},
    {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "rg x"}},
]
for event in events:
    sys.stdin = io.StringIO(json.dumps(event))
    assert main(["hook"]) == 0
hook._claim(hook._session_file({"session_id": "s1"}, ".start"))  # the session's first prompt has been searched
out = io.StringIO()
hook.run(io.StringIO(json.dumps({"session_id": "s1", "hook_event_name": "UserPromptSubmit", "prompt": "q",
                                 "cwd": "."})), out)
assert out.getvalue() == ""
loaded = [m for m in ("torch", "faiss", "numpy", "codemem.service", "codemem.search") if m in sys.modules]
print(json.dumps(loaded), file=sys.stderr)
"""
    done = _python(code, tmp_path)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stderr.strip().splitlines()[-1]) == []
    assert done.stdout.count('"permissionDecision": "deny"') == 1 and done.stdout.count("additionalContext") == 1
