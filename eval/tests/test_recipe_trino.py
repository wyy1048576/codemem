"""The trino recipe: which test files it takes, and how its script chooses and runs tests."""

import os
import shutil
import subprocess
import sys

import pytest

from cmeval import generate as gen

FAIL, PASS = gen.FAIL, gen.PASS


def _patch(*files):
    return "".join(f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1 +1 @@\n+x\n" for f in files)


def test_load_recipe_trino():
    recipe = gen.load_recipe("trino")
    assert recipe.repo == "trinodb/trino"
    assert recipe.base_image.startswith("eclipse-temurin:25.")
    env = dict(recipe.env)
    # The local repository and the Maven distribution must be in the image, not in the build cache mount.
    assert env["MAVEN_OPTS"] == "-Dmaven.repo.local=/opt/m2/repository"
    assert env["MAVEN_USER_HOME"] == "/opt/m2"
    assert "CI" not in env and "CONTINUOUS_INTEGRATION" not in env
    # The dependency layer builds the same module list as the task build.
    modules = recipe.build[0].split(" -pl ")[1].split()[0]
    assert f"-pl {modules} -am" in recipe.deps[0]
    assert recipe.refresh == ("cmeval-trino-test --refresh",)
    assert recipe.test == "cmeval-trino-test {junit} {files}"


def test_trino_test_files_are_built_modules_only():
    recipe = gen.load_recipe("trino")

    class T:
        test_patch = _patch(
            "core/trino-main/src/test/java/io/trino/sql/query/TestX.java",
            "plugin/trino-iceberg/src/test/resources/data.json",
            "testing/trino-testing/src/main/java/io/trino/testing/BaseConnectorTest.java",
            "plugin/trino-mongodb/src/test/java/io/trino/plugin/mongodb/TestMongoConnectorTest.java",
            "plugin/trino-redshift/src/test/java/io/trino/plugin/redshift/TestRedshiftUnload.java",
            "core/trino-main/src/main/java/io/trino/Foo.java",
        )

    assert gen.task_test_files(recipe, T) == [
        "core/trino-main/src/test/java/io/trino/sql/query/TestX.java",
        "plugin/trino-iceberg/src/test/resources/data.json",
        "testing/trino-testing/src/main/java/io/trino/testing/BaseConnectorTest.java",
    ]


BASE = """package io.trino.plugin.iceberg;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

public abstract class BaseIcebergConnectorTest
        extends io.trino.testing.BaseConnectorTest
{
    private static final String TEXT = "a { b"; // a brace in a string

    @Test
    public void testA()
    {
        check(1);
    }

    @ParameterizedTest
    @ValueSource(strings = {"x", "y"})
    public void testB(String value)
    {
        Runnable r = () -> { value.length(); };
    }

    @Test
    public void testC()
    {
    }

    protected void check(int value)
    {
    }

    @Override
    protected boolean hasBehavior(String behavior)
    {
        return switch (behavior) {
            case "SUPPORTS_A" -> true;
            default -> false;
        };
    }
}
"""

CONNECTOR_BASE = """package io.trino.testing;

import org.junit.jupiter.api.Test;

public abstract class BaseConnectorTest
{
    @Test
    public void testRefreshView()
    {
        if (!hasBehavior(SUPPORTS_REFRESH_VIEW)) {
            return;
        }
    }

    @Test
    public void testOther()
    {
    }

    protected abstract boolean hasBehavior(String behavior);
}
"""


def _write(root, path, text):
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text)


@pytest.fixture
def trino(tmp_path):
    """A small repo with the layout of trino, the script as the base image writes it, and a mvnw
    that records its arguments and writes a surefire report for each class of -Dtest that has tests."""
    if not (shutil.which("bash") and shutil.which("git")):
        pytest.skip("needs bash and git")
    recipe = gen.load_recipe("trino")
    step = next(step for step in recipe.base_setup if "cmeval-trino-test" in step)
    script = tmp_path / "cmeval-trino-test"
    # Docker joins a line that ends with a backslash with the next line.
    command = step.replace("\\\n", "").replace("/usr/local/bin/cmeval-trino-test", str(script))
    command = command.replace("&& cmeval-trino-test --select", "")
    subprocess.run(["bash", "-c", command], check=True)
    repo = tmp_path / "repo"
    for module in ("core/trino-web-ui", "core/trino-main", "plugin/trino-iceberg", "testing/trino-testing",
                   "plugin/trino-mongodb", "lib/trino-plugin-toolkit"):
        _write(repo, f"{module}/pom.xml", "<project/>\n")
        if module != "plugin/trino-mongodb":
            (repo / module / "target").mkdir()
    _write(repo, "pom.xml", "<project/>\n")
    iceberg = "plugin/trino-iceberg/src/test/java/io/trino/plugin/iceberg"
    _write(repo, f"{iceberg}/BaseIcebergConnectorTest.java", BASE)
    for name in ("TestIcebergParquetConnectorTest", "TestIcebergOrcConnectorTest"):
        _write(repo, f"{iceberg}/{name}.java",
               f"package io.trino.plugin.iceberg;\nfinal class {name}\n        extends BaseIcebergConnectorTest\n{{\n}}\n")
    _write(repo, f"{iceberg}/TestIcebergData.java",
           "package io.trino.plugin.iceberg;\nclass TestIcebergData\n{\n    String file = \"data.json\";\n"
           "    @org.junit.jupiter.api.Test\n    void data() {}\n}\n")
    _write(repo, "plugin/trino-iceberg/src/test/resources/data.json", "{}\n")
    _write(repo, "testing/trino-testing/src/main/java/io/trino/testing/BaseConnectorTest.java", CONNECTOR_BASE)
    main = "core/trino-main/src/test/java/io/trino"
    _write(repo, f"{main}/TestingHelper.java", "package io.trino;\npublic class TestingHelper\n{\n}\n")
    _write(repo, f"{main}/TestEngine.java",
           "package io.trino;\nclass TestEngine\n{\n    TestingHelper helper;\n    @org.junit.jupiter.api.Test\n"
           "    void run() {}\n}\n")
    _write(repo, "plugin/trino-mongodb/src/test/java/io/trino/plugin/mongodb/TestMongo.java",
           "package io.trino.plugin.mongodb;\nclass TestMongo\n{\n}\n")
    _write(repo, "lib/trino-plugin-toolkit/src/test/java/io/trino/plugin/base/TestToolkit.java",
           "package io.trino.plugin.base;\nclass TestToolkit\n{\n    @org.junit.jupiter.api.Test\n    void t() {}\n}\n")
    # mvnw: refuses to leave out the web UI module when only the toolkit is chosen, as Maven does
    # when the module is not in the build. Writes a passing report for each class of -Dtest.
    _write(repo, "mvnw", """#!/bin/bash
echo "$@" >> "$MVNW_LOG"
for a in "$@"; do
  case $a in
    -pl) ;;
    *trino-plugin-toolkit*'!core/trino-web-ui'*) echo "[ERROR] Could not find the selected project in the reactor: core/trino-web-ui @"; exit 1 ;;
  esac
done
for a in "$@"; do
  case $a in
    -Dtest=*)
      IFS=, read -ra specs <<< "${a#-Dtest=}"
      for s in "${specs[@]}"; do
        c=${s%%#*}
        for m in */*; do
          f="$m/src/test/java/$(echo "$c" | tr . /).java"
          if grep -q junit "$f" 2>/dev/null; then
            mkdir -p "$m/target/surefire-reports"
            printf '<?xml version="1.0" encoding="UTF-8"?>\\n<testsuite name="%s"><properties><property name="a" value="b"/></properties><testcase name="t" classname="%s"><system-out>log</system-out></testcase></testsuite>\\n' "$c" "$c" > "$m/target/surefire-reports/TEST-$c.xml"
          fi
        done
      done ;;
  esac
done
""")
    (repo / "mvnw").chmod(0o755)
    subprocess.run("git init -q && git add -A && git -c user.name=t -c user.email=t@t commit -qm base",
                   shell=True, cwd=repo, check=True)
    log = tmp_path / "mvnw.log"
    env = {**os.environ, "MVNW_LOG": str(log)}

    def run(*args):
        proc = subprocess.run([sys.executable, str(script), *args], cwd=repo, env=env, capture_output=True, text=True)
        calls = log.read_text().splitlines() if log.exists() else []
        log.unlink(missing_ok=True)
        return proc, calls

    return repo, run


def _choice(output):
    lines = [line.split(" ", 2) for line in output.splitlines() if not line.startswith("cmeval-trino-test:")]
    return {name: rest for _, name, rest in lines}


def test_trino_script_chooses_touched_methods_of_a_base_class(trino):
    repo, run = trino
    base = "plugin/trino-iceberg/src/test/java/io/trino/plugin/iceberg/BaseIcebergConnectorTest.java"
    text = (repo / base).read_text()
    text = text.replace('{"x", "y"}', '{"x", "y", "z"}')
    text = text.replace("    protected void check", "    @Test\n    public void testD()\n    {\n        check(2);\n    }\n\n"
                                                    "    protected void check")
    (repo / base).write_text(text)
    proc, _ = run("--select", base)
    assert proc.returncode == 0
    # Two concrete subclasses, each with the changed test and the new test. The base class does not run.
    assert _choice(proc.stdout) == {
        "io.trino.plugin.iceberg.TestIcebergOrcConnectorTest": "testB testD",
        "io.trino.plugin.iceberg.TestIcebergParquetConnectorTest": "testB testD",
    }


def test_trino_script_follows_a_changed_helper_and_a_changed_flag(trino):
    repo, run = trino
    base = "plugin/trino-iceberg/src/test/java/io/trino/plugin/iceberg/BaseIcebergConnectorTest.java"
    (repo / base).write_text((repo / base).read_text().replace("    {\n    }\n\n    @Override",
                                                                 "    {\n        int x = 1;\n    }\n\n    @Override"))
    proc, _ = run("--select", base)
    # The body of check() changed: testA calls it.
    assert set(_choice(proc.stdout).values()) == {"testA"}
    subprocess.run(["git", "checkout", "-q", "--", base], cwd=repo, check=True)
    text = (repo / base).read_text().replace('case "SUPPORTS_A" -> true;',
                                             'case "SUPPORTS_A" -> true;\n            case SUPPORTS_REFRESH_VIEW -> true;')
    (repo / base).write_text(text)
    proc, _ = run("--select", base)
    # No test method changed. The inherited test that names the changed flag runs.
    assert set(_choice(proc.stdout).values()) == {"testRefreshView"}


def test_trino_script_runs_whole_classes_helpers_and_skips_unbuilt_modules(trino):
    repo, run = trino
    (repo / "core/trino-main/src/test/java/io/trino/TestingHelper.java").write_text(
        "package io.trino;\npublic class TestingHelper\n{\n    int x;\n}\n")
    (repo / "plugin/trino-iceberg/src/test/resources/data.json").write_text("{\"a\": 1}\n")
    proc, _ = run("--select", "core/trino-main/src/test/java/io/trino/TestingHelper.java",
                  "plugin/trino-iceberg/src/test/resources/data.json",
                  "plugin/trino-mongodb/src/test/java/io/trino/plugin/mongodb/TestMongo.java")
    assert _choice(proc.stdout) == {"io.trino.TestEngine": "all", "io.trino.plugin.iceberg.TestIcebergData": "all"}
    assert "no test for plugin/trino-mongodb" in proc.stdout


def test_trino_script_runs_maven_and_merges_reports(trino, tmp_path):
    repo, run = trino
    new = "core/trino-main/src/test/java/io/trino/TestNew.java"
    (repo / new).write_text("package io.trino;\nclass TestNew\n{\n    @org.junit.jupiter.api.Test\n    void n() {}\n}\n")
    (repo / "core/trino-main/src/test/java/io/trino/TestMissing.java").write_text(
        "package io.trino;\nclass TestMissing\n{\n}\n")
    # A stale report of an earlier run must not count.
    (repo / "core/trino-main/target/surefire-reports").mkdir(parents=True)
    (repo / "core/trino-main/target/surefire-reports/TEST-old.xml").write_text(
        '<testsuite><testcase name="old" classname="io.trino.Old"/></testsuite>')
    junit = tmp_path / "out.xml"
    proc, calls = run(str(junit), new, "core/trino-main/src/test/java/io/trino/TestMissing.java")
    assert len(calls) == 1
    call = calls[0]
    assert call.startswith("-o -B --no-transfer-progress -T 8 ")
    assert " test -pl core/trino-main,!core/trino-web-ui -am " in call
    assert "-Dtest=io.trino.TestMissing,io.trino.TestNew " in call
    for option in ("-fn", "-Dsurefire.failIfNoSpecifiedTests=false", "-Dsurefire.rerunFailingTestsCount=0",
                   "-Djunit.jupiter.execution.parallel.config.fixed.parallelism=8"):
        assert option in call.split()
    # The class without a report is one failed test, so the run is not empty.
    assert gen.parse_junit(junit) == {"io.trino.TestNew::t": PASS, "cmeval::no-results io.trino.TestMissing": FAIL}
    text = junit.read_text()
    assert "<properties" not in text and "system-out" not in text


def test_trino_script_leaves_the_web_ui_in_when_maven_refuses(trino, tmp_path):
    _, run = trino
    junit = tmp_path / "out.xml"
    proc, calls = run(str(junit), "lib/trino-plugin-toolkit/src/test/java/io/trino/plugin/base/TestToolkit.java")
    assert len(calls) == 2 and "!core/trino-web-ui" in calls[0] and "!core/trino-web-ui" not in calls[1]
    assert gen.parse_junit(junit) == {"io.trino.plugin.base.TestToolkit::t": PASS}


def test_trino_script_without_a_test_writes_a_failure(trino, tmp_path):
    _, run = trino
    junit = tmp_path / "out.xml"
    proc, calls = run(str(junit), "plugin/trino-mongodb/src/test/java/io/trino/plugin/mongodb/TestMongo.java")
    assert proc.returncode == 1 and calls == []
    assert gen.parse_junit(junit) == {"cmeval::no-results selection": FAIL}


def test_trino_refresh_compiles_changed_built_modules(trino):
    repo, run = trino
    proc, calls = run("--refresh")
    assert proc.returncode == 0 and calls == []
    (repo / "core/trino-main/src/test/java/io/trino/TestingHelper.java").write_text("package io.trino;\n")
    (repo / "plugin/trino-mongodb/src/test/java/io/trino/plugin/mongodb/TestMongo.java").write_text("x\n")
    (repo / "plugin/trino-iceberg/src/test/java/io/trino/plugin/iceberg/TestNew.java").write_text("x\n")
    proc, calls = run("--refresh")
    assert proc.returncode == 0
    assert calls == ["-o -B --no-transfer-progress -T 8 -Dair.check.skip-all=true -Dmaven.javadoc.skip=true "
                     "-Dmaven.source.skip=true test-compile -pl core/trino-main,plugin/trino-iceberg,!core/trino-web-ui -am"]
