"""The image archive: the parts that need no Docker. Docker and the compression tool are replaced."""

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import replace

import pytest

from cmeval import e2e, e2e_run, images
from cmeval import generate as gen
from cmeval.cli import main
from cmeval.tasks import save_tasks


def _patch(*files):
    return "".join(f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1 +1 @@\n+x\n" for f in files)


def _recipe(**fields):
    values = dict(name="r", repo="acme/auth", base_image="i", test="pytest {files} --junitxml={junit}",
                  test_files=("pkg/tests/**/test_*.py",))
    values.update(fields)
    return gen.Recipe(**values)


class FakeDocker:
    """Images by tag, as image_facts gives them. A saved file holds the image as JSON; loading it
    makes the image again, with the id in the file."""

    def __init__(self, monkeypatch, tool="zstd"):
        self.images: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.load_id: str | None = None  # when set, a load gives this id instead of the saved one
        self.save_error: str | None = None
        self.test_error: str | None = None
        monkeypatch.setattr(gen, "image_facts", lambda tag: dict(self.images[tag]) if tag in self.images else None)
        # repo_digest and other inspect calls: no such image.
        monkeypatch.setattr(gen, "_run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", ""))
        monkeypatch.setattr(images, "image_layers", lambda tag: ["sha256:base", f"sha256:top-{tag}"]
                            if tag in self.images else [])
        monkeypatch.setattr(images, "_docker_save", self.save)
        monkeypatch.setattr(images, "_test_file", self.test_file)
        monkeypatch.setattr(images, "_docker_load", self.load)
        monkeypatch.setattr(images, "_remove_image", self.remove)
        monkeypatch.setattr(images.shutil, "which", lambda name: f"/usr/bin/{name}" if name in (tool, "gzip") else None)

    def add(self, tag, fingerprint, n=1):
        self.images[tag] = {"image_id": f"sha256:{n}{tag}", "created": "2026-11-26T01:00:00Z", "size": 3_000_000_000,
                            "fingerprint": fingerprint}

    def save(self, tag, dest, tool):
        self.calls.append(("save", tag, dest.name, tool))
        if self.save_error:
            dest.write_bytes(b"half")
            raise gen.GenerateError(self.save_error)
        data = json.dumps({"tag": tag, **self.images[tag]}).encode()
        dest.write_bytes(data)
        return hashlib.sha256(data).hexdigest(), len(data)

    def test_file(self, path, tool):
        self.calls.append(("test", path.name, tool))
        if self.test_error:
            raise gen.GenerateError(self.test_error)

    def load(self, path, tool):
        self.calls.append(("load", path.name, tool))
        data = json.loads(path.read_bytes())
        tag = data.pop("tag")
        if self.load_id:
            data["image_id"] = self.load_id
        self.images[tag] = data
        return f"Loaded image: {tag}"

    def remove(self, tag):
        self.calls.append(("remove", tag))
        self.images.pop(tag, None)
        return None


def _validated(recipe, task, *, valid=True, image_id=None):
    """A saved validation record with the current fingerprint, and the image's history."""
    folder = gen.task_dir(recipe, task)
    folder.mkdir(parents=True, exist_ok=True)
    fingerprint = gen.validation_fingerprint(recipe, task, 3)
    (folder / "result.json").write_text(json.dumps({"id": task.id, "valid": valid, "fingerprint": fingerprint,
                                                    "repeats": 3, "image_id": image_id}))
    if valid:
        gen.tests_path(recipe, task).write_text(json.dumps({"fingerprint": fingerprint, "repeats": 3,
                                                            "fail_to_pass": ["t::new"], "pass_to_pass": []}))


def _setup(monkeypatch, make_task, tmp_path, *, tool="zstd", valid=True):
    recipe, task = _recipe(), make_task(test_patch=_patch("pkg/tests/test_a.py"))
    docker = FakeDocker(monkeypatch, tool)
    tag = gen.task_tag(recipe, task)
    docker.add(tag, gen.image_fingerprint(recipe, task))
    gen.record_image(recipe, task, tag, step="validate", event="built", build_s=100.0)
    _validated(recipe, task, valid=valid, image_id=docker.images[tag]["image_id"])
    return recipe, task, docker, tag, tmp_path / "archive"


# ---- the archive folder and the tool

def test_archive_root_needs_a_folder(tmp_path, monkeypatch):
    monkeypatch.delenv(images.ARCHIVE_ENV, raising=False)
    with pytest.raises(gen.GenerateError, match="give --dir or set CMEVAL_IMAGE_ARCHIVE"):
        images.archive_root(None)
    monkeypatch.setenv(images.ARCHIVE_ENV, str(tmp_path / "env"))
    assert images.archive_root(None) == tmp_path / "env"
    assert images.archive_root(tmp_path / "dir") == tmp_path / "dir"


def test_compression_prefers_zstd(monkeypatch):
    monkeypatch.setattr(images.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert images.compression() == "zstd"
    monkeypatch.setattr(images.shutil, "which", lambda name: "/bin/gzip" if name == "gzip" else None)
    assert images.compression() == "gzip"
    monkeypatch.setattr(images.shutil, "which", lambda name: None)
    with pytest.raises(gen.GenerateError, match="neither zstd nor gzip"):
        images.compression()


# ---- save

def test_save_writes_the_file_and_its_json(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    record = images.save_task(recipe, task, root)
    name = f"{task.id.lower()}.tar.zst"
    assert record["status"] == "saved" and record["file"] == name and not record["removed"]
    path = root / "r" / name
    assert path.is_file() and not list((root / "r").glob(".*"))  # no temporary file stays
    meta = json.loads((root / "r" / f"{task.id.lower()}.json").read_text())
    assert meta["image_id"] == docker.images[tag]["image_id"] and meta["tag"] == tag
    assert meta["fingerprint"] == gen.image_fingerprint(recipe, task) and meta["image_size"] == 3_000_000_000
    assert meta["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest() and meta["file_bytes"] == path.stat().st_size
    assert meta["compression"] == "zstd" and meta["layers"] == ["sha256:base", f"sha256:top-{tag}"]
    assert meta["validation_image_id"] == meta["image_id"] and meta["saved_at"]
    # The entry of image-builds.json that the image came from.
    assert (meta["build"]["step"], meta["build"]["event"], meta["build"]["build_s"]) == ("validate", "built", 100.0)
    history = gen.read_builds(recipe, task)
    assert [(e["step"], e["event"]) for e in history] == [("validate", "built"), ("archive", "saved")]
    assert history[-1]["sha256"] == meta["sha256"] and history[-1]["image_id"] == meta["image_id"]
    # Without --remove the file is not read back, and the image stays.
    assert ("test", f".{name}.partial", "zstd") not in docker.calls and tag in docker.images
    # The same image again: not saved again.
    record = images.save_task(recipe, task, root)
    assert record["status"] == "archived" and [c[0] for c in docker.calls].count("save") == 1
    assert images.format_save(record) == f"archived {task.id}: the archive holds this image"


def test_save_uses_gzip_when_zstd_is_missing(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path, tool="gzip")
    record = images.save_task(recipe, task, root)
    assert record["file"] == f"{task.id.lower()}.tar.gz" and docker.calls[0][3] == "gzip"
    assert images.read_meta(root, recipe, task)["compression"] == "gzip"


def test_save_with_remove(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    record = images.save_task(recipe, task, root, remove=True)
    assert record["status"] == "saved" and record["removed"] and tag not in docker.images
    # The file is tested before it gets its name, and the image is removed after the JSON is written.
    kinds = [c[0] for c in docker.calls]
    assert kinds == ["save", "test", "remove"]
    history = gen.read_builds(recipe, task)
    assert [(e["step"], e["event"]) for e in history] == [("validate", "built"), ("archive", "saved"),
                                                          ("remove", "removed")]
    assert history[-1]["why"] == "archived" and history[-1]["archive_file"].endswith(".tar.zst")
    assert images.format_save(record).endswith(", removed from Docker")


def test_save_removes_an_archived_image(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    images.save_task(recipe, task, root)
    # The file is read back before the image is removed. A file that fails the test keeps the image.
    docker.test_error = "zstd test failed"
    record = images.save_task(recipe, task, root, remove=True)
    assert record["status"] == "failed" and not record["removed"] and tag in docker.images
    docker.test_error = None
    record = images.save_task(recipe, task, root, remove=True)
    assert record["status"] == "archived" and record["removed"] and tag not in docker.images
    assert [c[0] for c in docker.calls] == ["save", "test", "test", "remove"]


def test_save_skips(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    fingerprint = docker.images[tag]["fingerprint"]
    docker.images[tag]["fingerprint"] = "0" * 16
    assert "another fingerprint" in images.save_task(recipe, task, root)["reason"]
    docker.images[tag]["fingerprint"] = fingerprint
    # A validation of another recipe version, or none.
    record = images.save_task(replace(recipe, refresh=("make",)), task, root, remove=True)
    assert record["reason"] == "no validation record with the current fingerprint" and tag in docker.images
    (gen.task_dir(recipe, task) / "result.json").unlink()
    assert images.save_task(recipe, task, root, remove=True)["status"] == "skipped" and tag in docker.images
    docker.images.clear()
    assert images.save_task(recipe, task, root)["reason"] == "no image in Docker"
    assert not (root / "r").exists()


def test_save_removes_the_image_of_a_task_that_is_not_valid(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path, valid=False)
    assert images.save_task(recipe, task, root) == {"id": task.id, "status": "skipped", "reason": "not valid",
                                                    "file": None, "file_bytes": None, "save_s": None,
                                                    "removed": False}
    record = images.save_task(recipe, task, root, remove=True)
    assert record["status"] == "removed" and record["removed"] and tag not in docker.images
    assert not (root / "r").exists()  # not archived
    assert gen.read_builds(recipe, task)[-1]["why"] == "not valid; not archived"


def test_save_refuses_when_the_archive_holds_another_image(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    images.save_task(recipe, task, root)
    before = images.read_meta(root, recipe, task)
    docker.add(tag, gen.image_fingerprint(recipe, task), n=2)  # a rebuild
    record = images.save_task(recipe, task, root, remove=True)
    assert record["status"] == "refused" and "another image" in record["reason"] and tag in docker.images
    assert images.read_meta(root, recipe, task) == before
    # A file with another size than its JSON says is not taken as archived either.
    docker.add(tag, gen.image_fingerprint(recipe, task), n=1)
    (root / "r" / before["file"]).write_bytes(b"cut")
    assert images.save_task(recipe, task, root)["status"] == "refused"


def test_a_failed_save_leaves_no_file_and_keeps_the_image(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    docker.save_error = "docker save failed: no space left"
    record = images.save_task(recipe, task, root, remove=True)
    assert record["status"] == "failed" and "no space left" in record["reason"]
    assert tag in docker.images and not list((root / "r").iterdir())
    docker.save_error, docker.test_error = None, "zstd test failed"
    record = images.save_task(recipe, task, root, remove=True)
    assert record["status"] == "failed" and tag in docker.images and not list((root / "r").iterdir())
    assert [e["step"] for e in gen.read_builds(recipe, task)] == ["validate"]


def test_save_adds_an_image_that_the_history_does_not_have(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    gen.builds_path(recipe, task).unlink()
    images.save_task(recipe, task, root)
    meta = images.read_meta(root, recipe, task)
    assert (meta["build"]["step"], meta["build"]["event"]) == ("archive", "found")
    assert [(e["step"], e["event"]) for e in gen.read_builds(recipe, task)] == [("archive", "found"),
                                                                               ("archive", "saved")]


# ---- load

def test_load_brings_back_the_saved_image(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    saved_id = docker.images[tag]["image_id"]
    images.save_task(recipe, task, root, remove=True)
    record = images.load_task(recipe, task, root)
    assert record["status"] == "loaded" and record["image_id"] == saved_id and docker.images[tag]["image_id"] == saved_id
    assert record["hash_s"] is not None and record["load_s"] is not None
    entry = gen.read_builds(recipe, task)[-1]
    assert (entry["step"], entry["event"], entry["image_id"]) == ("load", "loaded", saved_id)
    assert entry["sha256"] == images.read_meta(root, recipe, task)["sha256"] and entry["archive_file"].endswith(".tar.zst")
    assert images.format_load(record).startswith(f"loaded   {task.id}: sha256 checked in ")
    # In Docker now: nothing to load.
    calls = len(docker.calls)
    assert images.load_task(recipe, task, root)["status"] == "exists" and len(docker.calls) == calls


def test_load_checks_the_file_and_the_loaded_image(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    images.save_task(recipe, task, root, remove=True)
    meta = images.read_meta(root, recipe, task)
    path = root / "r" / meta["file"]
    good = path.read_bytes()
    # A changed file is not loaded.
    path.write_bytes(good + b" ")
    record = images.load_task(recipe, task, root)
    assert record["status"] == "failed" and "another sha256" in record["reason"]
    assert not [c for c in docker.calls if c[0] == "load"]
    # A loaded image with another id is removed again.
    path.write_bytes(good)
    docker.load_id = "sha256:other"
    record = images.load_task(recipe, task, root)
    assert record["status"] == "failed" and "removed again" in record["reason"] and tag not in docker.images
    assert "layers equal" in record["reason"]
    assert gen.read_builds(recipe, task)[-1]["step"] == "remove"  # no load entry
    # A missing file.
    path.unlink()
    assert "does not exist" in images.load_task(recipe, task, root)["reason"]


def test_load_refuses_and_skips(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    images.save_task(recipe, task, root, remove=True)
    # The recipe changed in the image: the archived image is of another version.
    record = images.load_task(replace(recipe, build=("make",)), task, root)
    assert record["status"] == "refused"
    other = replace(task, id="acme__auth-7")
    assert images.load_task(recipe, other, root)["reason"] == "not in the archive"


def test_an_image_in_docker_that_is_not_the_archived_one(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    images.save_task(recipe, task, root)
    docker.add(tag, gen.image_fingerprint(recipe, task), n=2)
    record = images.load_task(recipe, task, root)
    assert record["status"] == "exists" and "another image than the archive's" in record["reason"]


# ---- list

def test_listing(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    second = make_task(id="acme__auth-7", test_patch=_patch("pkg/tests/test_a.py"))
    docker.add(gen.task_tag(recipe, second), gen.image_fingerprint(recipe, second))
    _validated(recipe, second)
    images.save_task(recipe, task, root, remove=True)
    images.save_task(recipe, second, root)
    rows = images.listing(root)
    assert list(rows) == ["r"] and [(r["id"], r["in_docker"]) for r in rows["r"]] == [
        (task.id, "no"), (second.id, "yes")]
    docker.add(gen.task_tag(recipe, second), "x", n=3)
    assert images.listing(root, "r")["r"][1]["in_docker"] == "another image"
    lines = images.format_listing(rows)
    assert lines[0].startswith("r: 2 tasks, ") and lines[0].endswith("1 also in Docker now") and len(lines) == 3
    assert images.format_listing(rows, tasks=False) == lines[:1]
    assert images.listing(tmp_path / "none") == {}


# ---- the rest of the package knows the archive

def test_hint_names_the_load_command(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    monkeypatch.delenv(images.ARCHIVE_ENV, raising=False)
    hint = images.missing_image_hint(recipe, task)
    assert "cmeval images load r --tasks FILE" in hint and f"--id {task.id} --rebuild" in hint
    monkeypatch.setenv(images.ARCHIVE_ENV, str(root))
    assert images.missing_image_hint(recipe, task) == (
        f"build it again with cmeval generate r --tasks FILE --id {task.id} --rebuild")
    images.save_task(recipe, task, root, remove=True)
    assert images.missing_image_hint(recipe, task) == (
        f"it is in the image archive; load it with cmeval images load r --tasks FILE --id {task.id}")
    # The grader and the runner say it.
    monkeypatch.setattr(e2e, "image_exists", lambda tag: False)
    with pytest.raises(gen.GenerateError, match="cmeval images load r"):
        e2e.grade(recipe, task, "", tmp_path / "grade")
    monkeypatch.setattr(e2e_run, "image_exists", lambda tag: False)
    with pytest.raises(gen.GenerateError, match="in the image archive; load it"):
        e2e_run.preconditions(recipe, task, e2e_run.RunSettings())


def test_generate_and_rebuild_do_not_build_an_archived_image(make_task, tmp_path, monkeypatch):
    recipe, task, docker, tag, root = _setup(monkeypatch, make_task, tmp_path)
    record = json.loads((gen.task_dir(recipe, task) / "result.json").read_text())
    monkeypatch.setenv(images.ARCHIVE_ENV, str(root))
    images.save_task(recipe, task, root, remove=True)
    monkeypatch.setattr(gen, "image_label", lambda tag: docker.images.get(tag, {}).get("fingerprint"))
    monkeypatch.setattr(gen, "build_task_image", lambda *a, **k: pytest.fail("no build"))
    assert gen.generate_task(recipe, task) == record
    rebuilt = gen.rebuild_task(recipe, task)
    assert rebuilt["status"] == "archived" and "cmeval images load r" in rebuilt["reason"]
    # Without the archive, the image is built again, as before.
    monkeypatch.delenv(images.ARCHIVE_ENV)
    with pytest.raises(pytest.fail.Exception, match="no build"):
        gen.rebuild_task(recipe, task)


# ---- the command line

def test_cli_images(make_task, tmp_path, monkeypatch, capsys):
    recipe = gen.load_recipe("pandas")
    docker = FakeDocker(monkeypatch)
    fix = make_task().fix
    tasks = [make_task(id=f"pandas-dev__pandas-{n}", repo=recipe.repo, test_patch=_patch("pandas/tests/test_a.py"),
                       fix=replace(fix, pr_number=n)) for n in (1, 2, 3)]
    for task in tasks[:2]:
        docker.add(gen.task_tag(recipe, task), gen.image_fingerprint(recipe, task))
        _validated(recipe, task)
    path = tmp_path / "tasks.jsonl"
    save_tasks(path, tasks)
    root = tmp_path / "archive"
    monkeypatch.delenv(images.ARCHIVE_ENV, raising=False)
    assert main(["images", "save", "pandas", "--tasks", str(path)]) == 1
    assert "give --dir or set CMEVAL_IMAGE_ARCHIVE" in capsys.readouterr().err
    assert main(["images", "save", "pandas", "--tasks", str(path), "--dir", str(root), "--id", "nope"]) == 1
    assert main(["images", "save", "pandas", "--tasks", str(path), "--dir", str(root), "--remove"]) == 0
    out = capsys.readouterr().out
    assert "2 saved" in out and "2 removed from Docker (0 of them not valid), 1 skipped, 0 refused, 0 failed" in out
    monkeypatch.setenv(images.ARCHIVE_ENV, str(root))
    assert main(["images", "list"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("pandas: 2 tasks, ") and "in Docker: no" in out
    assert main(["images", "load", "pandas", "--tasks", str(path), "--id", tasks[0].id]) == 0
    assert "1 loaded" in capsys.readouterr().out and gen.task_tag(recipe, tasks[0]) in docker.images
    assert main(["images", "load", "pandas", "--tasks", str(path)]) == 0
    out = capsys.readouterr().out
    assert "1 loaded" in out and "1 in Docker already, 1 not in the archive, 0 refused, 0 failed" in out
    # A task named with --id that the archive does not hold: the run would miss its image.
    assert main(["images", "load", "pandas", "--tasks", str(path), "--id", tasks[2].id]) == 3
    assert main(["images", "list", "--summary", "--dir", str(tmp_path / "empty")]) == 0
    assert "no archived image" in capsys.readouterr().out


# ---- the streaming helpers, with a stand-in docker program and the real tool

@pytest.fixture
def docker_program(tmp_path, monkeypatch):
    """A `docker` program on PATH: `save TAG` writes 3 MB that hold the tag, `load` copies stdin to a file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    loaded = tmp_path / "loaded.tar"
    script = bin_dir / "docker"
    script.write_text("#!/bin/sh\n"
                      "case $1 in\n"
                      "  save) [ \"$2\" = bad ] && { echo 'no such image' >&2; exit 1; }\n"
                      "        i=0; while [ $i -lt 3000 ]; do printf '%1024s' \"$2\"; i=$((i+1)); done ;;\n"
                      f"  load) cat > '{loaded}'; echo \"Loaded image: x\" ;;\n"
                      "esac\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return loaded


@pytest.mark.parametrize("tool", ["zstd", "gzip"])
def test_save_and_load_streams(tool, tmp_path, docker_program):
    if not shutil.which(tool):
        pytest.skip(f"{tool} is not installed")
    dest = tmp_path / f"x{images.TOOLS[tool][0]}"
    sha, size = images._docker_save("cmeval-env/r:t", dest, tool)
    assert size == dest.stat().st_size and sha == images.file_sha256(dest) and size < 3000 * 1024
    images._test_file(dest, tool)
    assert images._docker_load(dest, tool) == "Loaded image: x"
    data = docker_program.read_bytes()
    assert len(data) == 3000 * 1024 and data.strip().startswith(b"cmeval-env/r:t")
    with pytest.raises(gen.GenerateError, match="docker save bad failed: no such image"):
        images._docker_save("bad", tmp_path / "bad.tar", tool)
    (tmp_path / "broken").write_bytes(b"not compressed")
    with pytest.raises(gen.GenerateError, match="test failed"):
        images._test_file(tmp_path / "broken", tool)
    with pytest.raises(gen.GenerateError, match="failed"):
        images._docker_load(tmp_path / "broken", tool)
