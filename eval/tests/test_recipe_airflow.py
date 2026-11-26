"""The recipe for apache/airflow: which suite gets which test file, and the helper that it writes."""

import hashlib
import subprocess

from cmeval import generate as gen


def _patch(*files):
    return "".join(f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1 +1 @@\n+x\n" for f in files)


class _Task:
    def __init__(self, *files):
        self.test_patch = _patch(*files)


def _suites_of(recipe, path):
    return [k for k, suite in enumerate(recipe.suites) if gen.suite_files(suite, _Task(path))]


def test_each_test_file_goes_to_the_suites_of_its_distribution():
    recipe = gen.load_recipe("airflow")
    core = "airflow-core/tests/unit/jobs/test_scheduler_job.py"
    provider = "providers/microsoft/azure/tests/unit/microsoft/azure/hooks/test_batch.py"
    # airflow-core and the providers: one suite without the database, one with it.
    assert _suites_of(recipe, core) == [0, 1]
    assert _suites_of(recipe, provider) == [0, 1]
    for path in ("task-sdk/tests/task_sdk/api/test_client.py", "airflow-ctl/tests/airflow_ctl/api/test_operations.py",
                 "shared/logging/tests/logging/test_structlog.py", "dev/breeze/tests/test_selective_checks.py",
                 "scripts/tests/test_react_plugin_bootstrap.py", "dev/registry/tests/test_extract_parameters.py",
                 "airflow-core/src/airflow/ui/src/components/TaskTrySelect.test.tsx",
                 "airflow-core/src/airflow/ui/src/utils/tab.test.ts"):
        assert len(_suites_of(recipe, path)) == 1, path
    # No suite for tests that need services, for system tests, for helpers, or for the TypeScript SDK.
    for path in ("providers/redis/tests/integration/redis/hooks/test_redis.py",
                 "providers/google/tests/system/google/cloud/gcs/example_sftp_to_gcs.py",
                 "providers/fab/tests/unit/fab/auth_manager/api_fastapi/conftest.py",
                 "kubernetes-tests/tests/kubernetes_tests/test_kubernetes_pod_operator.py",
                 "airflow-ctl-tests/tests/airflowctl_tests/test_airflowctl_commands.py",
                 "airflow-core/src/airflow/ui/tests/e2e/pages/XComsPage.ts",
                 "ts-sdk/tests/coordinator/log-channel.test.ts"):
        assert _suites_of(recipe, path) == [], path


def test_fixed_workers_and_no_reruns():
    recipe = gen.load_recipe("airflow")
    pytest_suites = [suite.test for suite in recipe.suites if suite.test.startswith(("pytest", "export"))]
    assert len(pytest_suites) == 8
    for test in pytest_suites:
        assert "-p no:rerunfailures" in test and "--continue-on-collection-errors" in test
        assert "-n auto" not in test
    # The database tests run in one process, each run with a new AIRFLOW_HOME.
    db = recipe.suites[1].test
    assert "--run-db-tests-only" in db and " -n " not in db and "mktemp -d" in db
    assert "--maxWorkers=4" in recipe.suites[-1].test
    assert "CI" not in dict(recipe.env)


def test_ui_suite_gives_vitest_paths_relative_to_the_ui_folder(tmp_path):
    recipe = gen.load_recipe("airflow")
    task = _Task("airflow-core/src/airflow/ui/src/a/B.test.tsx", "airflow-core/src/airflow/ui/src/c.test.ts")
    files = gen.suite_files(recipe.suites[-1], task)
    ui = tmp_path / "airflow-core/src/airflow/ui"
    (ui / "node_modules/.bin").mkdir(parents=True)
    vitest = ui / "node_modules/.bin/vitest"
    vitest.write_text('#!/bin/sh\necho "$@"\n')
    vitest.chmod(0o755)
    command = recipe.suites[-1].test.replace("{files}", " ".join(f"'{f}'" for f in files)).replace("{junit}", "/w/j.xml")
    out = subprocess.run(["bash", "-c", command], cwd=tmp_path, capture_output=True, text=True, check=True).stdout
    assert out.split()[:3] == ["run", "src/a/B.test.tsx", "src/c.test.ts"]
    assert "--outputFile.junit=/w/j.xml" in out


def _helper_source(recipe, tmp_path):
    # base_setup writes the helper with printf. Run that line with another target path.
    line = next(c for c in recipe.base_setup if "cmeval-provider-deps" in c)
    target = tmp_path / "helper.py"
    subprocess.run(["bash", "-c", line.replace("/usr/local/bin/cmeval-provider-deps", str(target))], check=True)
    return target


def test_provider_deps_helper_writes_the_hash_of_the_test_plugin(tmp_path):
    recipe = gen.load_recipe("airflow")
    helper = _helper_source(recipe, tmp_path)
    repo = tmp_path / "repo"
    for name in ("amazon", "microsoft/azure"):
        (repo / "providers" / name).mkdir(parents=True)
        (repo / "providers" / name / "pyproject.toml").write_text(f"name = {name!r}\n")
        (repo / "providers" / name / "provider.yaml").write_text(f"package-name: {name}\n")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "x"\n[tool.uv.workspace]\nmembers = [\n    ".",\n    "airflow-core",\n'
        '    # a comment\n    "providers/microsoft/azure",\n    "providers/amazon",\n]\n"providers/not-a-member"\n')
    (repo / "generated").mkdir()
    # A stand-in for the repo's script: it writes the dependency file.
    script = repo / "scripts/ci/prek/update_providers_dependencies.py"
    script.parent.mkdir(parents=True)
    script.write_text("import pathlib\npathlib.Path('generated/provider_dependencies.json').write_text('{}')\n")

    subprocess.run(["python3", str(helper)], cwd=repo, check=True)
    # The plugin's hash: sha256 of the member providers' pyproject.toml and provider.yaml, in sorted path order.
    expected = hashlib.sha256()
    for path in sorted(repo / "providers" / name / f for name in ("amazon", "microsoft/azure")
                       for f in ("pyproject.toml", "provider.yaml")):
        expected.update(path.read_bytes())
    mark = repo / "generated/provider_dependencies.json.sha256sum"
    assert mark.read_text() == expected.hexdigest()
    assert (repo / "generated/provider_dependencies.json").exists()

    # With a current hash, the script does not run again.
    (repo / "generated/provider_dependencies.json").write_text("kept")
    subprocess.run(["python3", str(helper)], cwd=repo, check=True)
    assert (repo / "generated/provider_dependencies.json").read_text() == "kept"
    # A changed provider.yaml runs it again.
    (repo / "providers/amazon/provider.yaml").write_text("changed\n")
    subprocess.run(["python3", str(helper)], cwd=repo, check=True)
    assert (repo / "generated/provider_dependencies.json").read_text() == "{}"
