"""Merge systems from one run into a copy of another run, so the report can compare them.

The report compares systems inside one run folder. A new system (for example a stronger grep
baseline) can run on its own and be merged into an earlier run, so the systems of the earlier
run need no new search or index:

    cmeval merge BASE EXTRA --run-id NEW [--system NAME ...]

NEW is a new run folder: the run files of BASE, plus the <system>.jsonl files and index rows of
the chosen EXTRA systems. BASE and EXTRA are not changed. The two runs must use the same tasks
file, split, hits per search, and index mode, and EXTRA must have every task that BASE has. meta.json of NEW
records both parts (code, machine, sessions). NEW has no scores: score it next.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .files import now, read_jsonl, write_json
from .paths import runs_dir
from .run import _RUN_ID_RE
from .score import resolve_run

MUST_MATCH = ("tasks_sha256", "split", "k", "index_mode")


class MergeError(RuntimeError):
    """The runs cannot be merged (different inputs, missing tasks, a name used twice)."""


def _load(run_dir: Path) -> tuple[dict, dict[str, list[dict]], list[dict]]:
    try:
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        lines = {s["name"]: read_jsonl(run_dir / f"{s['name']}.jsonl") for s in meta["systems"]}
        index_rows = read_jsonl(run_dir / "index.jsonl")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise MergeError(f"run files in {run_dir} are not valid: {type(exc).__name__}: {exc}") from None
    return meta, lines, index_rows


def _part(run_dir: Path, meta: dict, systems: list[str]) -> dict:
    return {"run_id": run_dir.name, "systems": systems, "cmeval_git": meta.get("cmeval_git"),
            "machine": meta.get("machine"), "started": meta.get("started"), "ended": meta.get("ended"),
            "index_mode": meta.get("index_mode"), "config_sha256": meta.get("config_sha256"),
            "sessions": meta.get("sessions") or []}


def merge(base: str | Path, extra: str | Path, run_id: str, *, systems: list[str] | None = None) -> Path:
    if not _RUN_ID_RE.match(run_id):
        raise MergeError(f"run id {run_id!r} may only use letters, digits, '_', '.', '-'")
    base_dir, extra_dir = resolve_run(base), resolve_run(extra)
    new_dir = runs_dir() / run_id
    if new_dir.exists():
        raise MergeError(f"run id {run_id!r} exists already; choose a new run id")
    base_meta, base_lines, base_index = _load(base_dir)
    extra_meta, extra_lines, extra_index = _load(extra_dir)

    for run_dir, meta in ((base_dir, base_meta), (extra_dir, extra_meta)):
        if meta.get("status") != "done":
            raise MergeError(f"run {run_dir.name} has status {meta.get('status')!r}; only finished runs can be merged")
    changed = [key for key in MUST_MATCH if base_meta.get(key) != extra_meta.get(key)]
    if changed:
        raise MergeError(f"the runs have different {', '.join(changed)}; they cannot be compared")

    base_names = [s["name"] for s in base_meta["systems"]]
    extra_names = [s["name"] for s in extra_meta["systems"]]
    chosen = systems if systems else [name for name in extra_names if name not in base_names]
    if not chosen:
        raise MergeError(f"run {extra_dir.name} has no system that is not in {base_dir.name}")
    for name in chosen:
        if name not in extra_names:
            raise MergeError(f"system {name!r} is not in run {extra_dir.name} (it has {extra_names})")
        if name in base_names:
            raise MergeError(f"system {name!r} is in both runs; a merged run needs unique names")

    # Every task of the base run, at the same commit, so the systems are compared on the same tasks.
    base_tasks = {line["task_id"]: line["commit"] for name in base_names for line in base_lines[name]}
    for name in chosen:
        extra_tasks = {line["task_id"]: line["commit"] for line in extra_lines[name]}
        missing = sorted(set(base_tasks) - set(extra_tasks))
        if missing:
            raise MergeError(f"{name}: {len(missing)} tasks of {base_dir.name} are missing, for example {missing[0]}")
        moved = [t for t in base_tasks if extra_tasks[t] != base_tasks[t]]
        if moved:
            raise MergeError(f"{name}: task {moved[0]} ran at another commit than in {base_dir.name}")

    new_dir.mkdir(parents=True)
    try:
        for name in base_names:
            shutil.copyfile(base_dir / f"{name}.jsonl", new_dir / f"{name}.jsonl")
        for name in chosen:
            with (new_dir / f"{name}.jsonl").open("w", encoding="utf-8", newline="\n") as f:
                for line in extra_lines[name]:
                    if line["task_id"] in base_tasks:  # only the tasks of the base run
                        f.write(json.dumps(line, ensure_ascii=False) + "\n")
        rows = base_index + [r for r in extra_index if r.get("system") in chosen]
        (new_dir / "index.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                             encoding="utf-8", newline="\n")
        meta = {key: value for key, value in base_meta.items()
                if key not in ("searched", "skipped", "resumed", "error")}
        meta.update(
            run_id=run_id,
            systems=base_meta["systems"] + [s for s in extra_meta["systems"] if s["name"] in chosen],
            sessions=(base_meta.get("sessions") or []) + (extra_meta.get("sessions") or []),
            merged=now(),
            merged_from=[_part(base_dir, base_meta, base_names), _part(extra_dir, extra_meta, chosen)],
            config_text=base_meta.get("config_text", "") + f"\n# merged from {extra_dir.name}:\n"
                        + extra_meta.get("config_text", ""),
        )
        write_json(new_dir / "meta.json", meta)
    except BaseException:
        shutil.rmtree(new_dir, ignore_errors=True)  # never leave half a merged run
        raise
    return new_dir
