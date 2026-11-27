"""No crash dumps from the containers of the package: every docker run has the core limit."""

import ast
import subprocess
from pathlib import Path

from cmeval import e2e_run
from cmeval import generate as gen

SOURCE = Path(gen.__file__).parent


def _docker_run_lists():
    """(file, line, node) of each list literal in the package that starts with "docker", "run"."""
    for path in sorted(SOURCE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.List) and len(node.elts) >= 2
                    and all(isinstance(e, ast.Constant) for e in node.elts[:2])
                    and [e.value for e in node.elts[:2]] == ["docker", "run"]):
                yield path.name, node.lineno, node


def _has_limit(node) -> bool:
    return any(isinstance(e, ast.Starred) and isinstance(e.value, ast.Name) and e.value.id == "NO_CORE_DUMPS"
               for e in node.elts)


def test_the_limit_is_one_and_not_zero():
    assert gen.NO_CORE_DUMPS == ("--ulimit", "core=1:1")


def test_every_docker_run_of_the_package_has_the_limit():
    found = list(_docker_run_lists())
    # The validation and grading container, the agent's container, and the helper that removes an index copy.
    assert {name for name, _, _ in found} >= {"generate.py", "e2e_run.py"} and len(found) >= 3
    missing = [f"{name}:{line}" for name, line, node in found if not _has_limit(node)]
    assert not missing, f"docker run without NO_CORE_DUMPS: {missing}"


def _pair(cmd):
    i = cmd.index("--ulimit")
    return tuple(cmd[i:i + 2])


def test_run_in_container_has_the_limit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(gen, "_run", lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    assert gen.run_in_container("tag", tmp_path, prefix="cmeval-grade", limit=1, cpus=2)
    [run] = [c for c in calls if c[:2] == ["docker", "run"]]
    assert _pair(run) == gen.NO_CORE_DUMPS and run.index("--ulimit") < run.index("tag")


def test_the_helper_that_removes_an_index_copy_has_the_limit(tmp_path, monkeypatch):
    calls = []
    copy = tmp_path / "cmindex"
    copy.mkdir()
    # rmtree does not remove the folder, so the helper container runs.
    monkeypatch.setattr(e2e_run.shutil, "rmtree", lambda path, ignore_errors=False: None)
    monkeypatch.setattr(e2e_run, "_run", lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    e2e_run.remove_index_copy(copy, "tag")
    [run] = [c for c in calls if c[:2] == ["docker", "run"]]
    assert _pair(run) == gen.NO_CORE_DUMPS and run.index("--ulimit") < run.index("tag")


def test_the_limit_changes_no_fingerprint(make_task):
    recipe = gen.Recipe(name="r", repo="acme/auth", base_image="i", test="pytest {files}")
    task = make_task()
    # The values that the code before the limit gives for this recipe and task.
    assert gen.image_fingerprint(recipe, task) == "9a04a6604165abdd"
    assert gen.validation_fingerprint(recipe, task, 3) == "7a5763556a8e7657"
