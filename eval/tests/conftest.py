import pytest

from cmeval.tasks import Fix, Gold, Issue, Span, Task

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
