"""The recipe for home-assistant/core: the fields that the validation depends on."""

from cmeval import generate as gen


def _patch(*files):
    return "".join(f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1 +1 @@\n+x\n" for f in files)


def test_load_recipe_homeassistant():
    recipe = gen.load_recipe("homeassistant")
    assert recipe.repo == "home-assistant/core"
    assert "{files}" in recipe.test and "{junit}" in recipe.test
    # A test file that does not import before the fix must not stop the other files.
    assert "--continue-on-collection-errors" in recipe.test
    # A fixed worker count, not one taken from the host.
    assert " -n 8 " in recipe.test and "auto" not in recipe.test and "logical" not in recipe.test
    # A missing or different snapshot must fail, and nothing may be written.
    assert "snapshot-update" not in recipe.test
    # Every integration's requirements, from the files of the task's commit.
    assert "requirements_all.txt" in recipe.deps_files
    assert all("{exclude_newer}" in command for command in recipe.deps)
    # Tests read the translation files, and a fix can change strings.json.
    assert any("script.translations develop --all" in command for command in recipe.build)
    assert any("script.translations develop --all" in command for command in recipe.refresh)
    assert "CI" not in dict(recipe.env)


def test_homeassistant_test_files_are_test_modules_only():
    recipe = gen.load_recipe("homeassistant")

    class T:
        test_patch = _patch(
            "tests/components/sun/test_condition.py",
            "tests/components/sun/conftest.py",
            "tests/components/sun/__init__.py",
            "tests/components/sun/snapshots/test_sensor.ambr",
            "tests/components/sun/fixtures/data.json",
            "tests/helpers/test_condition.py",
            "tests/test_core.py",
            "packages/pytest-home-assistant/tests/standalone/test_plugin.py",
        )

    assert gen.task_test_files(recipe, T) == [
        "tests/components/sun/test_condition.py",
        "tests/helpers/test_condition.py",
        "tests/test_core.py",
    ]
