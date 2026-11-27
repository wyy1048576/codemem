"""The kubernetes recipe: which test files it takes, and how its test command finds the packages."""

import os
import shutil
import subprocess

import pytest

from cmeval import generate as gen


def _patch(*files):
    return "".join(f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1 +1 @@\n+x\n" for f in files)


def test_load_recipe_kubernetes():
    recipe = gen.load_recipe("kubernetes")
    assert recipe.repo == "kubernetes/kubernetes"
    env = dict(recipe.env)
    # The build cache must be in the image, not in the build-time cache mount.
    assert not env["GOCACHE"].startswith("/root/.cache")
    assert env["GOTOOLCHAIN"] == "local"
    # The Go version comes from the task's commit.
    assert recipe.deps_files == (".go-version",)
    assert "-count=1" in recipe.test and "-p 8" in recipe.test and "-race" not in recipe.test


def test_kubernetes_test_files_are_unit_tests_only():
    recipe = gen.load_recipe("kubernetes")

    class T:
        test_patch = _patch(
            "pkg/kubelet/kubelet_test.go",
            "staging/src/k8s.io/apimachinery/pkg/util/yaml/yaml_test.go",
            "test/utils/ktesting/tcontext_test.go",
            "pkg/kubelet/testdata/pod.yaml",
            "test/integration/scheduler/queue_test.go",
            "test/e2e_node/eviction_test.go",
            "test/e2e/common/node/file_key.go",
        )

    assert gen.task_test_files(recipe, T) == [
        "pkg/kubelet/kubelet_test.go",
        "staging/src/k8s.io/apimachinery/pkg/util/yaml/yaml_test.go",
        "test/utils/ktesting/tcontext_test.go",
    ]


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_kubernetes_test_command_runs_each_package_once(tmp_path):
    recipe = gen.load_recipe("kubernetes")
    # A stand-in for gotestsum that prints its arguments.
    fake = tmp_path / "gotestsum"
    fake.write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done\n')
    fake.chmod(0o755)
    files = [
        "pkg/kubelet/prober/prober_test.go",
        "pkg/kubelet/prober/worker_test.go",
        "staging/src/k8s.io/apimachinery/pkg/util/yaml/yaml_test.go",
        "staging/src/k8s.io/apiextensions-apiserver/test/integration/basic_test.go",
        "cmd/kubeadm/test/cmd/init_test.go",
    ]
    # The same replacement as in test_run_line.
    command = recipe.test.replace("{files}", " ".join(f"'{f}'" for f in files)).replace("{junit}", "/work/x.xml")
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    out = subprocess.run(["bash", "-c", command], capture_output=True, text=True, env=env, check=True).stdout.split()
    assert out[:2] == ["--junitfile", "/work/x.xml"]
    packages = [a for a in out[out.index("--") + 1:] if a.startswith("./")]
    assert packages == ["./pkg/kubelet/prober", "./staging/src/k8s.io/apimachinery/pkg/util/yaml"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_kubernetes_test_command_fails_with_no_package(tmp_path):
    recipe = gen.load_recipe("kubernetes")
    files = "'staging/src/k8s.io/kube-aggregator/test/integration/a_test.go'"
    command = recipe.test.replace("{files}", files).replace("{junit}", "/work/x.xml")
    proc = subprocess.run(["bash", "-c", command], capture_output=True, text=True, check=False)
    assert proc.returncode == 1 and "no package to test" in proc.stdout


def _reference_step(recipe) -> str:
    # Docker joins a line that ends with a backslash with the next line.
    return next(step for step in recipe.deps if "cmeval-k8s-warm" in step).replace("\\\n", "")


def test_kubernetes_warm_up_is_the_same_in_deps_and_build():
    recipe = gen.load_recipe("kubernetes")
    # The layer is keyed on the Go version only. It must not read a per-task value.
    assert recipe.deps_files == (".go-version",)
    assert not any("{exclude_newer}" in step for step in recipe.deps)
    # One script fills the cache at the reference and at the task, so their cache keys can match.
    assert "cmeval-k8s-warm && " in _reference_step(recipe)
    assert recipe.build[0].startswith("cmeval-k8s-warm && ")
    # The reference is checked out in /testbed, the folder of the task: the folder is part of Go's cache key.
    assert "git init -q /testbed && cd /testbed" in _reference_step(recipe)
    # Entries get a time in the future, so Go never sets their time on use (which copies a file of a
    # lower layer) and never trims them. The task build changes only its own new files.
    assert "touch -d 2100-01-01T00:00:00Z" in _reference_step(recipe)
    assert recipe.build[0].count("! -newermt 2099-01-01") == 2


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("version, ref", [
    ("1.27.1", "0ba07e0866bb1e3d67464b2d3e01f6bde6fe9963"),
    ("1.26.4", "1ef08364a754caec0b6706ff61e08cfb39fd53e6"),
    ("1.30.0", ""),
])
def test_kubernetes_dependency_layer_takes_the_reference_of_the_go_version(tmp_path, version, ref):
    (tmp_path / ".go-version").write_text(version + "\n")
    # Only the part that chooses the reference: it stops before the network is used.
    command = _reference_step(gen.load_recipe("kubernetes")).split("if [ -z")[0] + 'echo "ref=$ref"'
    out = subprocess.run(["bash", "-c", command], cwd=tmp_path, capture_output=True, text=True, check=True).stdout
    assert out.strip() == f"ref={ref}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_kubernetes_warm_script_builds_the_packages_of_unit_tests(tmp_path):
    step = next(s for s in gen.load_recipe("kubernetes").base_setup if "cmeval-k8s-warm" in s)
    script = tmp_path / "cmeval-k8s-warm"
    command = step.replace("\\\n", "").replace("/usr/local/bin/cmeval-k8s-warm", str(script))
    subprocess.run(["bash", "-c", command], check=True)
    # A stand-in for go: module list, package list, dependency list, and a build that records its packages.
    fake = tmp_path / "go"
    fake.write_text(
        '#!/bin/bash\n'
        'case "$*" in\n'
        '  "list -m -f {{.Path}}/...") echo k8s.io/kubernetes/... ;;\n'
        '  "list -e -f {{.ImportPath}} k8s.io/kubernetes/...") printf "%s\\n" k8s.io/kubernetes/pkg/a'
        ' k8s.io/kubernetes/test/e2e/b k8s.io/kubernetes/test/integration/c ;;\n'
        '  "list -e -deps -test -f "*) shift 6; echo "roots: $*" > "$OUT/roots"; printf "%s\\n" k8s.io/z k8s.io/y k8s.io/z ;;\n'
        '  build*) shift; echo "$@" > "$OUT/built" ;;\n'
        '  *) echo "unexpected: $*" >&2; exit 2 ;;\n'
        'esac\n')
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "OUT": str(tmp_path)}
    proc = subprocess.run([str(script)], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "roots").read_text().split() == ["roots:", "k8s.io/kubernetes/pkg/a"]
    assert (tmp_path / "built").read_text().split() == ["k8s.io/y", "k8s.io/z"]
