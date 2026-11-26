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
