import pytest

from cmeval.patches import classify_path, parse_patch, split_patch


def one(diff):
    [change] = parse_patch(diff)
    return change


def header(path="auth/sessions.py"):
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"


def test_modification():
    c = one(header() + """\
@@ -10,4 +10,4 @@ class SessionManager:
     def revoke(self):
-        pass
+        self.db.delete()
     def other(self):
         return 1
""")
    assert (c.status, c.old_path, c.new_path) == ("modified", "auth/sessions.py", "auth/sessions.py")
    assert c.changed == [11] and c.insert_after == []
    assert (c.added, c.removed) == (1, 1)


def test_pure_insertion_records_the_gap():
    c = one(header() + """\
@@ -20,3 +20,5 @@
     a = 1
+    b = 2
+    c = 3
     d = 4
     e = 5
""")
    assert c.changed == [] and c.insert_after == [20]  # new lines go between base lines 20 and 21


def test_insertion_at_file_start():
    c = one(header() + """\
@@ -1,2 +1,3 @@
+import os
 import sys
 x = 1
""")
    assert c.insert_after == [0]


def test_zero_context_insertion():
    c = one(header() + """\
@@ -10,0 +11,2 @@
+a
+b
""")
    assert c.changed == [] and c.insert_after == [10]


def test_replacement_then_insertion_in_one_hunk():
    c = one(header() + """\
@@ -5,5 +5,6 @@
 one
-two
+TWO
 three
+three_and_half
 four
 five
""")
    assert c.changed == [6]  # "two" was replaced; the added "TWO" is part of that change
    assert c.insert_after == [7]  # "three_and_half" goes after base line 7


def test_deletion_only():
    c = one(header() + """\
@@ -3,4 +3,2 @@
 keep
-gone1
-gone2
 keep2
""")
    assert c.changed == [4, 5] and c.insert_after == []


def test_several_hunks_and_no_newline_marker():
    c = one(header() + """\
@@ -1,2 +1,2 @@
-a
+A
 b
@@ -40,2 +40,3 @@
 y
 z
+end
\\ No newline at end of file
""")
    assert c.changed == [1] and c.insert_after == [41]


def test_new_file():
    c = one("""\
diff --git a/auth/new.py b/auth/new.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/auth/new.py
@@ -0,0 +1,2 @@
+def f():
+    pass
""")
    assert (c.status, c.old_path, c.new_path, c.path) == ("added", None, "auth/new.py", "auth/new.py")
    assert c.changed == [] and c.insert_after == [] and c.added == 2


def test_deleted_file():
    c = one("""\
diff --git a/auth/old.py b/auth/old.py
deleted file mode 100644
index 1111111..0000000
--- a/auth/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def f():
-    pass
""")
    assert (c.status, c.old_path, c.new_path) == ("deleted", "auth/old.py", None)
    assert c.changed == [1, 2]


def test_renames():
    changes = parse_patch("""\
diff --git a/auth/old.py b/auth/new.py
similarity index 90%
rename from auth/old.py
rename to auth/new.py
--- a/auth/old.py
+++ b/auth/new.py
@@ -1,2 +1,2 @@
-x = 1
+x = 2
 y = 3
diff --git a/auth/same.py b/auth/moved.py
similarity index 100%
rename from auth/same.py
rename to auth/moved.py
""")
    edited, moved = changes
    assert (edited.status, edited.old_path, edited.new_path, edited.changed) == ("renamed", "auth/old.py", "auth/new.py", [1])
    assert (moved.status, moved.old_path, moved.new_path, moved.changed) == ("renamed", "auth/same.py", "auth/moved.py", [])


def test_binary_file_is_other():
    c = one("""\
diff --git a/assets/logo.py b/assets/logo.py
new file mode 100644
index 0000000..e69de29
Binary files /dev/null and b/assets/logo.py differ
""")
    assert c.file_class == "other"


@pytest.mark.parametrize(
    "path, expected",
    [
        ("auth/sessions.py", ("code", "python")),
        ("tests/test_users.py", ("test", "python")),
        ("auth/test_sessions.py", ("test", "python")),
        ("auth/sessions_test.py", ("test", "python")),
        ("auth/conftest.py", ("test", "python")),
        ("auth/attestation.py", ("code", "python")),
        ("auth/latest.py", ("code", "python")),
        ("pkg/server/server.go", ("code", "go")),
        ("pkg/server/server_test.go", ("test", "go")),
        ("pkg/server/testdata/input.go", ("test", "go")),
        ("src/app.ts", ("code", "typescript")),
        ("src/app.test.ts", ("test", "typescript")),
        ("src/components/Button.spec.tsx", ("test", "tsx")),
        ("src/components/Button.tsx", ("code", "tsx")),
        ("src/server/index.mts", ("code", "typescript")),
        ("src/server/index.test.mts", ("test", "typescript")),
        # TypeScript: test/ and testing/ hold tests at any depth (vscode), except playwright's MCP test tools
        ("src/vs/base/test/common/utils.ts", ("test", "typescript")),
        ("extensions/copilot/test/simulation/fixture.ts", ("test", "typescript")),
        ("packages/playwright/src/mcp/test/testTools.ts", ("code", "typescript")),
        ("src/__tests__/util.js", ("test", "javascript")),
        ("src/main/java/org/Foo.java", ("code", "java")),
        ("src/main/java/org/FooTest.java", ("test", "java")),
        ("src/test/java/org/Foo.java", ("test", "java")),
        ("src/util/strings.cc", ("code", "cpp")),
        ("src/util/strings_unittest.cc", ("test", "cpp")),
        ("include/util.hpp", ("code", "cpp")),
        ("kernel/sched.c", ("code", "c")),
        ("ggml/src/ggml-cuda/mmq.cu", ("code", "cpp")),
        ("ggml/src/ggml-cuda/common.cuh", ("code", "cpp")),
        ("src/include/duckdb/common/vector.inl", ("code", "cpp")),
        ("ggml/src/ggml-opencl/kernels/add.cl", ("code", "opencl")),  # code the labeler cannot read
        ("ggml/src/ggml-vulkan/vulkan-shaders/add.comp", ("code", "glsl")),
        ("ggml/src/ggml-metal/ggml-metal.metal", ("code", "metal")),
        ("tools/server/webui/src/App.svelte", ("code", "svelte")),
        ("tests/test-backend-ops.cpp", ("test", "cpp")),
        ("test/sql/storage/test_wal.cpp", ("test", "cpp")),
        ("django/test/runner.ts", ("test", "typescript")),
        ("pandas/_libs/tslibs/offsets.pyx", ("code", "cython")),
        ("pandas/_libs/lib.pxd", ("code", "cython")),
        ("Tests/AppTests.swift", ("test", "swift")),
        # test/ and testing/ hold tests only at the repo top or under src/; elsewhere they can be library code
        ("django/test/testcases.py", ("code", "python")),
        ("sympy/testing/pytest.py", ("code", "python")),
        ("numpy/testing/_private/utils.py", ("code", "python")),
        ("django/test/test_utils.py", ("test", "python")),  # the file name still marks a test
        ("test/helpers.py", ("test", "python")),
        ("testing/conftest_helpers.py", ("test", "python")),
        ("src/test/scala/FooSpec.scala", ("test", "scala")),
        ("lib/tests/util.py", ("test", "python")),
        ("README.md", ("other", None)),
        ("pyproject.toml", ("other", None)),
        ("docs/index.rst", ("other", None)),
    ],
)
def test_classify_path(path, expected):
    assert classify_path(path) == expected


def test_split_patch_keeps_every_file_once():
    code = header("auth/sessions.py") + "@@ -1,1 +1,1 @@\n-a\n+b\n"
    test = header("tests/test_sessions.py") + "@@ -1,1 +1,2 @@\n x\n+y\n"
    doc = header("README.md") + "@@ -1,1 +1,1 @@\n-old\n+new\n"
    parts = split_patch(code + test + doc)
    assert parts == {"code": code, "test": test, "other": doc}
    assert split_patch(code)["test"] == ""


def test_align_file_diff_finds_moved_hunks():
    from cmeval.patches import PatchMismatch, align_file_diff

    base = "".join(f"line {i}\n" for i in range(1, 21))
    diff = header("f.py") + "@@ -3,3 +3,3 @@\n line 5\n-line 6\n+LINE 6\n line 7\n"  # states line 3, really line 5
    applied = align_file_diff(base, diff)
    assert applied.offsets == [2] and applied.changed == [6]
    assert applied.new_text == base.replace("line 6\n", "LINE 6\n")
    exact = header("f.py") + "@@ -5,3 +5,3 @@\n line 5\n-line 6\n+LINE 6\n line 7\n"
    assert align_file_diff(base, exact).offsets == [0]
    with pytest.raises(PatchMismatch, match="matches nowhere"):
        align_file_diff(base, header("f.py") + "@@ -5,2 +5,2 @@\n line 5\n-line 99\n+x\n")


def test_align_prefers_the_nearest_exact_match():
    from cmeval.patches import align_file_diff

    base = "a\nx\nb\na\nx\nb\n"  # the same three lines twice: at index 0 and index 3
    diff = header("f.py") + "@@ -4,3 +4,3 @@\n a\n-x\n+y\n b\n"
    assert align_file_diff(base, diff).changed == [5]  # the stated position wins when it matches
    diff_off = header("f.py") + "@@ -3,3 +3,3 @@\n a\n-x\n+y\n b\n"  # stated index 2: index 3 is 1 away, index 0 is 2 away
    assert align_file_diff(base, diff_off).changed == [5]
