import subprocess
from pathlib import Path

import pytest

from cmeval.repos import ensure_clone
from cmeval.tasks import Fix, Gold, Issue, Span, Task

FIXTURES = Path(__file__).parent / "fixtures"
REMOTE_REPO = "acme/demo"

PATCH = """\
diff --git a/auth/sessions.py b/auth/sessions.py
--- a/auth/sessions.py
+++ b/auth/sessions.py
@@ -33,2 +33,3 @@ class SessionManager:
     def revoke_session(self, user):
-        pass
+        for s in self.db.sessions_for(user):
+            self.db.delete(s)
"""


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the real ~/.cmeval from tests."""
    monkeypatch.setenv("CMEVAL_HOME", str(tmp_path / "cmeval_home"))


@pytest.fixture
def make_task():
    """Factory for a valid task. Keyword arguments replace top-level fields."""

    def make(**overrides) -> Task:
        fields = dict(
            id="acme__auth-42",
            source="fresh",
            split="test",
            repo="acme/auth",
            base_commit="0123456789abcdef0123456789abcdef01234567",
            language="python",
            query="Disabled users stay logged in\n\nAfter an admin disables a user, the user can still use the app.",
            issue=Issue(number=41, url="https://github.com/acme/auth/issues/41", created_at="2026-08-14T09:00:00Z"),
            fix=Fix(pr_number=42, url="https://github.com/acme/auth/pull/42", merged_at="2026-08-20T15:00:00Z", merge_type="squash"),
            patch=PATCH,
            gold=Gold(
                files=["auth/sessions.py"],
                classes=[Span("auth/sessions.py", 10, 80, "SessionManager")],
                functions=[Span("auth/sessions.py", 33, 34, "SessionManager.revoke_session")],
                lines=[Span("auth/sessions.py", 34, 34)],
            ),
            tags={"identifier_in_query": False, "n_gold_files": 1, "query_tokens": None},
            labeler="cmeval-labels/1",
        )
        fields.update(overrides)
        return Task(**fields)

    return make


class RemoteRepo:
    """A local git repo that stands in for GitHub."""

    def __init__(self, root: Path):
        self.root = root
        self.shas: list[str] = []

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, files: dict[str, str], message: str = "change") -> str:
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        sha = self.git("rev-parse", "HEAD")
        self.shas.append(sha)
        return sha

    def diff(self, old: str, new: str) -> str:
        return subprocess.run(
            ["git", "diff", old, new], cwd=self.root, check=True, capture_output=True, text=True
        ).stdout


@pytest.fixture
def remote(tmp_path, monkeypatch):
    """REMOTE_REPO with 3 commits of app.py, already cloned into CMEVAL_HOME. User git config is ignored."""
    config = tmp_path / "gitconfig"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "Test")
        monkeypatch.setenv(f"{key}_EMAIL", "test@example.com")
    root = tmp_path / "remote"
    root.mkdir()
    repo = RemoteRepo(root)
    repo.git("init", "-q", "-b", "main")
    for i in (1, 2, 3):
        repo.commit({"app.py": f"VERSION = {i}\n"}, f"v{i}")
    ensure_clone(REMOTE_REPO, url=str(root))
    return repo
