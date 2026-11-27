"""The image archive: validated task images as one compressed file each, on a large slow drive.

The system drive of the run machine cannot hold all task images (1.5 to 16 GB each, about 250 in
the final set). A second drive can, but it is slow for many small files and fine for one large
file. So a validated image is saved to one file, removed from Docker, and loaded back for the batch
that needs it. The run then uses the validated image itself, with the same image id, not a rebuild.

  save  `docker save TAG | zstd -T0 -3` to <dir>/<recipe>/<task id lower>.tar.zst, through a
        temporary name. gzip when zstd is not there. A JSON file beside it (<task id lower>.json)
        holds the image id, the fingerprint, the sizes, the sha256 of the file, and the entry of
        image-builds.json that the image belongs to. Only the image of a valid task is saved
  load  check the sha256 of the file, `docker load` it, and check that the loaded image has the
        saved id and fingerprint label. An image that does not is removed again
  list  what the archive holds, and which of its images are in Docker now

The archive folder is --dir, else the variable CMEVAL_IMAGE_ARCHIVE. Each save, removal and load
is added to the task's image-builds.json (steps archive, remove and load).

Each file stands alone: it also holds the layers that the task shares with other tasks of the repo
(the base image, and for pandas the dependency layer of its week). This costs space on the archive
drive. One file for a group of tasks would hold those layers once, but a group file cannot take a
new task without all images of the group in Docker, and it loads every image of the group.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from . import generate as gen
from .generate import GenerateError, Recipe
from .tasks import Task

ARCHIVE_ENV = "CMEVAL_IMAGE_ARCHIVE"
# Compression tool: (file suffix, command that compresses stdin to stdout, command that tests a file).
TOOLS = {
    "zstd": (".tar.zst", ["zstd", "-T0", "-3", "-q", "-c"], ["zstd", "-t", "-q"]),
    "gzip": (".tar.gz", ["gzip", "-3", "-c"], ["gzip", "-t"]),
}
CHUNK = 1 << 20


def archive_root(folder: str | Path | None = None) -> Path:
    """The archive folder: `folder`, else CMEVAL_IMAGE_ARCHIVE. An error when neither is set."""
    value = folder or os.environ.get(ARCHIVE_ENV)
    if not value:
        raise GenerateError(f"no image archive: give --dir or set {ARCHIVE_ENV}")
    return Path(value)


def compression() -> str:
    """zstd when it is installed, else gzip."""
    if shutil.which("zstd"):
        return "zstd"
    if shutil.which("gzip"):
        return "gzip"
    raise GenerateError("neither zstd nor gzip is installed")


def _name(task: Task) -> str:
    return task.id.lower()


def meta_path(root: Path, recipe: Recipe, task: Task) -> Path:
    return root / recipe.name / f"{_name(task)}.json"


def read_meta(root: Path, recipe: Recipe, task: Task) -> dict | None:
    """The JSON file of the task's archive file. None when there is none or it does not parse."""
    try:
        meta = json.loads(meta_path(root, recipe, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def archive_file(root: Path, recipe: Recipe, meta: dict) -> Path:
    return root / recipe.name / meta["file"]


def archived(recipe: Recipe, task: Task, folder: str | Path | None = None) -> bool:
    """The archive holds an image of the task with the current fingerprint. False when no archive is set."""
    try:
        root = archive_root(folder)
    except GenerateError:
        return False
    meta = read_meta(root, recipe, task)
    return bool(meta and meta.get("fingerprint") == gen.image_fingerprint(recipe, task)
                and meta.get("file") and archive_file(root, recipe, meta).is_file())


def missing_image_hint(recipe: Recipe, task: Task) -> str:
    """What to do when the task's image is not in Docker: load it from the archive, or build it again."""
    load = f"cmeval images load {recipe.name} --tasks FILE --id {task.id}"
    rebuild = f"cmeval generate {recipe.name} --tasks FILE --id {task.id} --rebuild"
    if archived(recipe, task):
        return f"it is in the image archive; load it with {load}"
    if not os.environ.get(ARCHIVE_ENV):
        return f"load it with {load} if it is archived (set {ARCHIVE_ENV}), else build it again with {rebuild}"
    return f"build it again with {rebuild}"


# ---- docker and the compression tool

def image_layers(tag: str) -> list[str]:
    """The diff ids of the image's layers, bottom first. Empty when the image does not exist."""
    proc = gen._run(["docker", "image", "inspect", "-f", "{{json .RootFS.Layers}}", tag])
    if proc.returncode != 0:
        return []
    try:
        layers = json.loads(proc.stdout or "null")
    except ValueError:
        return []
    return layers if isinstance(layers, list) else []


def _stderr_text(handle) -> str:
    handle.seek(0)
    return handle.read().decode(errors="replace").strip()[-500:]


def _docker_save(tag: str, dest: Path, tool: str) -> tuple[str, int]:
    """Write `docker save TAG`, compressed, to dest. Returns the sha256 and the size of the file,
    counted while it is written, so the slow drive is not read again."""
    digest, size = hashlib.sha256(), 0
    with tempfile.TemporaryFile() as save_err, tempfile.TemporaryFile() as tool_err:
        save = subprocess.Popen(["docker", "save", tag], stdout=subprocess.PIPE, stderr=save_err)
        comp = subprocess.Popen(TOOLS[tool][1], stdin=save.stdout, stdout=subprocess.PIPE, stderr=tool_err)
        save.stdout.close()  # so that docker save stops when the tool stops
        try:
            with open(dest, "wb") as out:
                for chunk in iter(lambda: comp.stdout.read(CHUNK), b""):
                    digest.update(chunk)
                    out.write(chunk)
                    size += len(chunk)
                out.flush()
                os.fsync(out.fileno())
        finally:
            comp.stdout.close()
            tool_code, save_code = comp.wait(), save.wait()
        if save_code != 0:
            raise GenerateError(f"docker save {tag} failed: {_stderr_text(save_err)}")
        if tool_code != 0:
            raise GenerateError(f"{tool} failed: {_stderr_text(tool_err)}")
    return digest.hexdigest(), size


def _test_file(path: Path, tool: str) -> None:
    """Read the whole file back and check the compression tool's checksums."""
    proc = subprocess.run([*TOOLS[tool][2], str(path)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GenerateError(f"{path}: {tool} test failed: {proc.stderr.strip()[-500:]}")


def _docker_load(path: Path, tool: str) -> str:
    """Decompress the file into `docker load`. Returns the output of docker load."""
    with tempfile.TemporaryFile() as tool_err:
        comp = subprocess.Popen([tool, "-d", "-c", str(path)], stdout=subprocess.PIPE, stderr=tool_err)
        try:
            load = subprocess.run(["docker", "load"], stdin=comp.stdout, capture_output=True, text=True)
        finally:
            comp.stdout.close()
            tool_code = comp.wait()
        if tool_code != 0:
            raise GenerateError(f"{tool} -d {path} failed: {_stderr_text(tool_err)}")
    if load.returncode != 0:
        raise GenerateError(f"docker load of {path} failed: {load.stderr.strip()[-500:]}")
    return load.stdout.strip()


def _remove_image(tag: str) -> str | None:
    """Remove the image's tag (and the image when no other tag has it). None when that worked, else the error."""
    proc = gen._run(["docker", "image", "rm", tag])
    return None if proc.returncode == 0 else (proc.stderr or proc.stdout or "docker image rm failed").strip()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(f".{path.name}.partial")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---- save

def _validation(recipe: Recipe, task: Task) -> dict | None:
    """The task's saved validation record when it has the current fingerprint, else None."""
    try:
        record = json.loads((gen.task_dir(recipe, task) / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if record.get("fingerprint") != gen.validation_fingerprint(recipe, task, record.get("repeats")):
        return None
    return record


def _build_entry(recipe: Recipe, task: Task, tag: str, image: str) -> dict | None:
    """The entry of image-builds.json that the image came from: the newest one of a build, a
    validation or a reuse with its id. When the history has none, the image is added as found."""
    for entry in reversed(gen.read_builds(recipe, task)):
        if entry.get("image_id") == image and entry.get("step") not in ("archive", "remove", "load"):
            return entry
    return gen.record_image(recipe, task, tag, step="archive", event="found")


def _removal(recipe: Recipe, task: Task, tag: str, facts: dict, why: str, **fields) -> str | None:
    """Remove the image and add the removal to the history. None when it worked, else the error."""
    error = _remove_image(tag)
    if error is None:
        gen.add_history(recipe, task, {"step": "remove", "event": "removed", "recorded_at": gen.now_utc(),
                                       "image_id": facts["image_id"], "fingerprint": facts["fingerprint"],
                                       "why": why, **fields})
    return error


def save_task(recipe: Recipe, task: Task, root: Path, *, remove: bool = False) -> dict:
    """Save the image of one valid task to the archive. With remove, the image then leaves Docker,
    and so does the image of a task whose validation is not valid (it is never run, so it is not
    saved). Returns a short record with the status: saved, archived (the file holds this image
    already), removed (not valid), skipped, refused (the file holds another image), or failed."""
    tag = gen.task_tag(recipe, task)
    record: dict = {"id": task.id, "status": "skipped", "reason": "", "file": None, "file_bytes": None,
                    "save_s": None, "removed": False}
    facts = gen.image_facts(tag)
    if facts is None:
        return {**record, "reason": "no image in Docker"}
    if facts["fingerprint"] != gen.image_fingerprint(recipe, task):
        return {**record, "reason": "the image has another fingerprint than the recipe and the task give now"}
    validation = _validation(recipe, task)
    if validation is None:
        return {**record, "reason": "no validation record with the current fingerprint"}
    if not validation.get("valid"):
        if not remove:
            return {**record, "reason": "not valid"}
        error = _removal(recipe, task, tag, facts, "not valid; not archived")
        if error:
            return {**record, "status": "failed", "reason": f"not valid; removal failed: {error}"}
        return {**record, "status": "removed", "reason": "not valid; image removed, not archived", "removed": True}

    folder = root / recipe.name
    meta = read_meta(root, recipe, task)
    if meta and meta.get("image_id") == facts["image_id"] and meta.get("file") \
            and archive_file(root, recipe, meta).is_file() \
            and archive_file(root, recipe, meta).stat().st_size == meta.get("file_bytes"):
        record.update(status="archived", reason="the archive holds this image", file=meta["file"],
                      file_bytes=meta["file_bytes"])
        if remove:
            # The file was saved without --remove, so it was not read back then.
            try:
                _test_file(archive_file(root, recipe, meta), meta.get("compression") or "zstd")
            except GenerateError as exc:
                return {**record, "status": "failed", "reason": f"the archive holds this image; {exc}"}
    elif meta:
        return {**record, "status": "refused",
                "reason": f"the archive holds another image of this task ({str(meta.get('image_id'))[:19]}, "
                          f"{meta.get('file')}), or its file is missing or has another size; move it away first"}
    else:
        tool = compression()
        suffix = TOOLS[tool][0]
        name = f"{_name(task)}{suffix}"
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f".{name}.partial"
        entry = _build_entry(recipe, task, tag, facts["image_id"])
        start = time.monotonic()
        try:
            sha, size = _docker_save(tag, tmp, tool)
            if remove:
                _test_file(tmp, tool)
            tmp.replace(folder / name)
        except (GenerateError, OSError) as exc:
            tmp.unlink(missing_ok=True)
            return {**record, "status": "failed", "reason": f"error: {exc}"}
        seconds = round(time.monotonic() - start, 1)
        meta = {"task_id": task.id, "recipe": recipe.name, "repo": recipe.repo, "tag": tag,
                "image_id": facts["image_id"], "fingerprint": facts["fingerprint"], "image_size": facts["size"],
                "image_created": facts["created"], "layers": image_layers(tag), "file": name,
                "compression": tool, "file_bytes": size, "sha256": sha, "saved_at": gen.now_utc(),
                "save_s": seconds, "validation_image_id": validation.get("image_id"), "build": entry}
        _write_json(meta_path(root, recipe, task), meta)
        gen.add_history(recipe, task, {"step": "archive", "event": "saved", "recorded_at": meta["saved_at"],
                                       "image_id": facts["image_id"], "fingerprint": facts["fingerprint"],
                                       "archive_file": str(folder / name), "file_bytes": size, "sha256": sha,
                                       "save_s": seconds})
        record.update(status="saved", reason="saved", file=name, file_bytes=size, save_s=seconds)
    if remove:
        error = _removal(recipe, task, tag, facts, "archived", archive_file=str(folder / record["file"]))
        if error:
            return {**record, "status": "failed", "reason": f"{record['reason']}; removal failed: {error}"}
        record["removed"] = True
    return record


def save(recipe: Recipe, tasks: list[Task], root: Path, *, remove: bool = False,
         progress: Callable[[str], None] = lambda message: None) -> list[dict]:
    """save_task for each task, one at a time (the archive drive is fastest with one writer)."""
    records = []
    for task in tasks:
        record = save_task(recipe, task, root, remove=remove)
        if record["status"] != "skipped" or record["reason"] != "no image in Docker":
            progress(format_save(record))
        records.append(record)
    return records


def _gb(size: int | None) -> str:
    return f"{size / 1e9:.2f} GB" if size is not None else "-"


def format_save(record: dict) -> str:
    removed = ", removed from Docker" if record["removed"] else ""
    if record["status"] == "saved":
        return f"saved    {record['id']}: {_gb(record['file_bytes'])} in {record['save_s']} s{removed}"
    return f"{record['status']:<8} {record['id']}: {record['reason']}{removed}"


# ---- load

def load_task(recipe: Recipe, task: Task, root: Path) -> dict:
    """Load the task's image from the archive when it is not in Docker. Returns a short record with
    the status: loaded, exists, skipped (not in the archive), refused, or failed."""
    tag = gen.task_tag(recipe, task)
    record: dict = {"id": task.id, "status": "skipped", "reason": "", "hash_s": None, "load_s": None,
                    "image_id": None}
    meta = read_meta(root, recipe, task)
    if meta is None:
        return {**record, "reason": "not in the archive"}
    facts = gen.image_facts(tag)
    fingerprint = gen.image_fingerprint(recipe, task)
    if facts and facts["fingerprint"] == fingerprint:
        same = facts["image_id"] == meta.get("image_id")
        return {**record, "status": "exists", "image_id": facts["image_id"],
                "reason": "the image is in Docker" + ("" if same else
                                                      f"; it is another image than the archive's "
                                                      f"({str(meta.get('image_id'))[:19]})")}
    if meta.get("fingerprint") != fingerprint:
        return {**record, "status": "refused",
                "reason": "the archived image was built from another version of the recipe or the task"}
    path = archive_file(root, recipe, meta)
    if not path.is_file():
        return {**record, "status": "failed", "reason": f"{path} does not exist"}
    start = time.monotonic()
    try:
        sha = file_sha256(path)
        record["hash_s"] = round(time.monotonic() - start, 1)
        if sha != meta.get("sha256"):
            return {**record, "status": "failed", "reason": f"{path} has another sha256 than its JSON file"}
        start = time.monotonic()
        output = _docker_load(path, meta.get("compression") or "zstd")
    except (GenerateError, OSError) as exc:
        return {**record, "status": "failed", "reason": f"error: {exc}"}
    seconds = round(time.monotonic() - start, 1)
    loaded = gen.image_facts(tag)
    if loaded is None:
        return {**record, "status": "failed", "load_s": seconds,
                "reason": f"no image {tag} after docker load (it said: {output[-200:]})"}
    if loaded["image_id"] != meta.get("image_id") or loaded["fingerprint"] != meta.get("fingerprint"):
        same_layers = image_layers(tag) == meta.get("layers")
        error = _remove_image(tag)
        return {**record, "status": "failed", "load_s": seconds, "image_id": loaded["image_id"],
                "reason": f"the loaded image is {loaded['image_id'][:19]} with label {loaded['fingerprint']}, the "
                          f"archive's is {str(meta.get('image_id'))[:19]} with label {meta.get('fingerprint')} "
                          f"(layers {'equal' if same_layers else 'differ'}); "
                          + ("removed again" if error is None else f"removal failed: {error}")}
    entry = gen.record_image(recipe, task, tag, step="load", event="loaded",
                             extra={"archive_file": str(path), "sha256": meta.get("sha256"),
                                    "hash_s": record["hash_s"], "load_s": seconds})
    return {**record, "status": "loaded", "reason": "loaded; the image id is the archive's", "load_s": seconds,
            "image_id": loaded["image_id"], "build": gen.build_number(recipe, task, entry and entry["image_id"])}


def load(recipe: Recipe, tasks: list[Task], root: Path,
         progress: Callable[[str], None] = lambda message: None) -> list[dict]:
    """load_task for each task, one at a time."""
    records = []
    for task in tasks:
        record = load_task(recipe, task, root)
        if record["status"] != "skipped":
            progress(format_load(record))
        records.append(record)
    return records


def format_load(record: dict) -> str:
    if record["status"] == "loaded":
        return (f"loaded   {record['id']}: sha256 checked in {record['hash_s']} s, loaded in {record['load_s']} s, "
                f"image {record['image_id'][:19]}")
    return f"{record['status']:<8} {record['id']}: {record['reason']}"


# ---- list

def listing(root: Path, recipe: str | None = None) -> dict[str, list[dict]]:
    """What the archive holds: recipe -> one row per task (id, file size, image id, in Docker now:
    yes, no, or another image)."""
    out: dict[str, list[dict]] = {}
    folders = [root / recipe] if recipe else sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    for folder in folders:
        rows = []
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(meta, dict) or not meta.get("tag"):
                continue
            now = gen.image_id(meta["tag"])
            rows.append({"id": meta.get("task_id"), "file_bytes": meta.get("file_bytes"),
                         "image_id": meta.get("image_id"), "saved_at": meta.get("saved_at"),
                         "file_ok": (folder / meta.get("file", "")).is_file(),
                         "in_docker": "no" if now is None else "yes" if now == meta.get("image_id") else "another image"})
        if rows:
            out[folder.name] = rows
    return out


def format_listing(rows_by_recipe: dict[str, list[dict]], *, tasks: bool = True) -> list[str]:
    lines = []
    for name, rows in rows_by_recipe.items():
        total = sum(r["file_bytes"] or 0 for r in rows)
        in_docker = sum(1 for r in rows if r["in_docker"] == "yes")
        missing = sum(1 for r in rows if not r["file_ok"])
        lines.append(f"{name}: {len(rows)} tasks, {_gb(total)}, {in_docker} also in Docker now"
                     + (f", {missing} files missing" if missing else ""))
        if tasks:
            lines += [f"  {r['id']}  {_gb(r['file_bytes'])}  image {str(r['image_id'])[:19]}  in Docker: {r['in_docker']}"
                      + ("" if r["file_ok"] else "  (file missing)") for r in rows]
    return lines
