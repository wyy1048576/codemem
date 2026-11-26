import subprocess

from cmeval.collect.test_split import path_matches, rust_test_lines, split_for_repo

LIB = """\
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adds() {
        assert_eq!(add(1, 2), 3);
    }
}
"""


def diff(old: dict[str, str], new: dict[str, str], tmp_path) -> str:
    """A git diff between two trees of files."""
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root,
                              check=True, capture_output=True, text=True).stdout

    git("init", "-q")
    for path, text in old.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    git("add", "-A")
    git("commit", "-q", "--allow-empty", "-m", "base")
    for path, text in new.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    git("add", "-A")
    return git("diff", "--cached", "-M")


def test_path_matches_uses_the_recipe_glob_rule():
    assert path_matches("crates/a/resources/test/fixtures/x.py", "crates/*/resources/test/**")
    assert path_matches("crates/a/src/rules/snapshots/x.snap", "**/snapshots/**")
    assert path_matches("pkg/testdata/a.golden", "**/testdata/**")
    assert path_matches("test/e2e/a.go", "test/**")
    assert not path_matches("crates/a/src/lib.rs", "**/tests/**")


def test_rust_test_lines_cover_cfg_test_items():
    lines = rust_test_lines(LIB)
    assert lines == set(range(5, 14))  # from #[cfg(test)] to the closing brace of mod tests


def test_rust_test_lines_other_attributes():
    source = ("#[cfg(any(test, feature = \"x\"))]\nfn helper() {}\n"
              "#[cfg(all(test, unix))]\nfn unix_only() {}\n"
              "#[cfg(not(test))]\nfn real() {}\n"
              "#[test]\n// note\nfn loose() {}\n")
    assert rust_test_lines(source) == {3, 4, 7, 8, 9}
    assert rust_test_lines("#![cfg(test)]\nfn a() {}\n") == {1, 2}


def test_rust_file_with_only_test_changes_is_a_test_file(tmp_path):
    new = LIB.replace("        assert_eq!(add(1, 2), 3);\n", "        assert_eq!(add(1, 2), 3);\n        assert_eq!(add(0, 0), 0);\n")
    patch = diff({"src/lib.rs": LIB}, {"src/lib.rs": new}, tmp_path)
    split = split_for_repo(patch, [], lambda path: LIB)
    assert "src/lib.rs" in split.parts["test"] and not split.parts["code"]
    assert split.moved == ["src/lib.rs"] and split.mixed == []


def test_a_new_test_module_is_test_code(tmp_path):
    base = LIB.split("#[cfg(test)]")[0]
    patch = diff({"src/lib.rs": base}, {"src/lib.rs": LIB}, tmp_path)
    split = split_for_repo(patch, [], lambda path: base)
    assert split.moved == ["src/lib.rs"]


def test_rust_file_with_code_and_test_changes_is_mixed(tmp_path):
    new = LIB.replace("    a + b\n", "    a.wrapping_add(b)\n").replace(
        "assert_eq!(add(1, 2), 3);", "assert_eq!(add(i32::MAX, 1), i32::MIN);")
    patch = diff({"src/lib.rs": LIB}, {"src/lib.rs": new}, tmp_path)
    split = split_for_repo(patch, [], lambda path: LIB)
    assert split.mixed == ["src/lib.rs"] and split.moved == []


def test_rust_code_change_stays_code_and_blank_lines_do_not_count(tmp_path):
    new = LIB.replace("    a + b\n", "    a.wrapping_add(b)\n").replace("#[cfg(test)]", "\n#[cfg(test)]")
    patch = diff({"src/lib.rs": LIB}, {"src/lib.rs": new}, tmp_path)
    split = split_for_repo(patch, [], lambda path: LIB)
    assert "src/lib.rs" in split.parts["code"] and split.mixed == [] and split.moved == []


def test_test_paths_move_any_extension_to_the_test_side(tmp_path):
    old = {"crates/a/src/rules/x.rs": "pub fn f() {}\n", "crates/a/resources/test/fixtures/X.py": "x = 1\n",
           "crates/a/src/rules/snapshots/x.snap": "old\n", "docs/x.md": "a\n"}
    new = {"crates/a/src/rules/x.rs": "pub fn f() { g() }\n", "crates/a/resources/test/fixtures/X.py": "x = 2\n",
           "crates/a/src/rules/snapshots/x.snap": "new\n", "docs/x.md": "b\n"}
    patch = diff(old, new, tmp_path)
    globs = ["crates/*/resources/test/**", "**/snapshots/**"]
    split = split_for_repo(patch, globs, lambda path: old.get(path))
    assert "x.rs" in split.parts["code"] and "X.py" not in split.parts["code"]
    assert "X.py" in split.parts["test"] and "x.snap" in split.parts["test"]
    assert "docs/x.md" in split.parts["other"]
    # Without the globs the fixture is Python code and the snapshot is "other", as before.
    plain = split_for_repo(patch, [], lambda path: old.get(path))
    assert "X.py" in plain.parts["code"] and "x.snap" in plain.parts["other"]


def test_python_files_are_never_read(tmp_path):
    patch = diff({"pkg/a.py": "x = 1\n"}, {"pkg/a.py": "x = 2\n"}, tmp_path)

    def read(path):
        raise AssertionError("only Rust files are read")

    assert "pkg/a.py" in split_for_repo(patch, [], read).parts["code"]
