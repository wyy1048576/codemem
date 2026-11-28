"""The block of codemem results at the top of the first message, for the setups `codemem` and `upfront`.

The block is one codemem search made for the agent before it starts. Its query is the prompt text of the run's
level (e2e_run.prompt_text: the issue as written at L0, the rewrite at L1 and L2), on the task's own index, with
20 results and the tool's default filters (none). The text is the line HEADER, then one line per result in rank
order: path:start_line, two spaces, the qualified name.

  Possibly relevant code, from a search by meaning (it may be wrong):
  pandas/tests/arithmetic/test_numeric.py:48  adjust_negative_zero
  pandas/core/reshape/merge.py:2599  _AsOfMerge._validate_tolerance

The first message of a run with a block is the block, one empty line, and the prompt exactly as the other setups
get it (e2e_run.make_prompt). The proxy counts its tokens as it counts any prompt text. The search is made before
the run, so it is outside the run's clock, and the run counts it as one codemem search before its first turn
(e2e_steps.count_steps).

`cmeval e2e block` makes the blocks on the host before the runs, once for each task and level, so that every
repetition and every model gets the same block. It skips a block that a run can use. The search is the eval's
search of a task's index outside a container (e2e_replay.cli_search_json: `codemem search --json`), on the src/
worktree of `cmeval e2e index`, with a private copy of the task's index and the environment of the replay
(e2e_replay.server_env), which names the batch's search index (e2e_index.vector_backend). It must be a search by
meaning: codemem's timings must hold a key that starts with embed_query:.

Before anything of a run starts, the run refuses a block that is missing, empty, made without the embedding
model, made from another prompt text, or whose text does not match its sha256 (read_block, check_block). It also
refuses a stale block: one made by another codemem commit than the program of the runs, on the other search
index than the batch's, or on another build of the task's index. A rebuild of the index (`cmeval e2e index`)
deletes the blocks beside it. A new block replaces the old file only when a run can use it.

The file of a block, beside the task's index: CMEVAL_HOME/e2e/indexes/<recipe>/<task id>/block-<level>.json, and
<task id>/compact/block-<level>.json for the compact search index.

  task_id, level, query       the task, the level, and the text that was searched
  k, text, sha256             the number of results asked for, the block's text, and the sha256 of the text
  results                     rank, path, start, end, name and score of each result, in rank order
  embedded, timings           whether codemem embedded the query (a timing embed_query:), and its own timings
  search_s                    seconds of the codemem command, with its start and the load of the model
  codemem_bin, codemem_commit, index
                              the codemem program, its commit, and index.json of the index that was searched
  made_utc                    when the block was made
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from . import e2e_replay
from .codemem_gate import McpError
from .e2e_index import VECTOR_BACKEND_ENV, codemem_bin, codemem_checkout, codemem_commit, index_form, index_root, \
    index_state, read_index_meta, src_root, vector_backend
from .files import write_json
from .generate import GenerateError, Recipe
from .metrics.matching import hit_matches
from .retriever import Hit
from .tasks import Task

SCHEMA = 1
HEADER = "Possibly relevant code, from a search by meaning (it may be wrong):"
K = 20
EMBEDDED = "embed_query:"  # the start of codemem's timing of the query's embedding
SEARCH_TIMEOUT_S = 900  # one codemem command: its start, the load of the model, and the search


def block_text(results: list[dict]) -> str:
    """The text of a block: HEADER, then one line per result in rank order. Every line ends in a newline."""
    lines = [HEADER] + [f"{r['path']}:{r['start']}  {r['name']}" for r in results]
    return "".join(line + "\n" for line in lines)


def block_path(recipe: Recipe, task: Task, level: str, backend: str | None = None) -> Path:
    """The file of the block, in the folder of the index of its form (default: the batch's)."""
    return index_root(recipe, task, backend) / f"block-{level}.json"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_block(task: Task, level: str, query: str, answer: dict, *, search_s: float, program: Path | None,
               commit: str | None, index: dict | None) -> dict:
    """The block of one task and level, from the answer of `codemem search --json` (its results and timings)."""
    results = [{"rank": i, "path": r["path"], "start": r["start_line"], "end": r["end_line"],
                "name": r.get("qualname") or "", "score": r.get("score")}
               for i, r in enumerate(answer.get("results") or [], start=1)]
    timings = answer.get("timings") or {}
    text = block_text(results)
    return {"schema": SCHEMA, "task_id": task.id, "level": level, "query": query, "k": K, "text": text,
            "sha256": _sha256(text), "results": results,
            "embedded": any(str(key).startswith(EMBEDDED) for key in timings), "timings": timings,
            "search_s": search_s, "codemem_bin": str(program) if program else None, "codemem_commit": commit,
            "index": index, "made_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def codemem_program_commit() -> str | None:
    """The commit of the codemem program that makes the blocks and serves the runs (e2e_index.codemem_bin)."""
    return codemem_commit(codemem_checkout(codemem_bin()))


def read_block(recipe: Recipe, task: Task, level: str, query: str, commit: str | None,
               backend: str | None = None) -> tuple[dict, Path]:
    """The block of a task and level and its file, for a run that sends `query` at that level with the codemem
    program at `commit`, on the search index `backend` (default: the batch's). Raises GenerateError when a run
    cannot use it (check_block), so that no run starts without its block."""
    backend = backend or vector_backend()
    path = block_path(recipe, task, level, backend)
    if not path.exists():
        raise GenerateError(f"{task.id}: the block at {level} ({path}) does not exist; make it with cmeval e2e "
                            f"block {recipe.name}")
    try:
        block = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        block = None
    check_block(block, path, recipe, task, level, query, commit, backend)
    return block, path


def check_block(block: object, path: Path, recipe: Recipe, task: Task, level: str, query: str,
                commit: str | None, backend: str | None = None) -> None:
    """Raise GenerateError when a run cannot use the block: it is empty or of another task or level, it was made
    without the embedding model or from another prompt text, its text does not match its sha256, or it is stale.
    A stale block was made by another codemem commit than `commit`, on another search index than `backend`
    (default: the batch's; the form of the index.json that the block holds), or on another build of the task's
    index (its index.json is not the one of the index now)."""
    backend = backend or vector_backend()
    where = f"{task.id}: the block at {level} ({path})"
    hint = f"make it with cmeval e2e block {recipe.name}"
    again = f"make it again with cmeval e2e block {recipe.name} --force"
    if (not isinstance(block, dict) or block.get("task_id") != task.id or block.get("level") != level
            or not isinstance(block.get("text"), str) or not isinstance(block.get("results"), list)
            or not block["results"]):
        raise GenerateError(f"{where} is empty or not a block of this task and level; {hint}")
    if not block.get("embedded"):
        raise GenerateError(f"{where} was made without the embedding model (codemem's timings have no "
                            f"{EMBEDDED} key), from keywords only; {hint}")
    if block.get("query") != query:
        raise GenerateError(f"{where} was made from another prompt text than this run's; {hint}")
    if _sha256(block["text"]) != block.get("sha256"):
        raise GenerateError(f"{where} has a text that does not match its sha256; {hint}")
    if block.get("codemem_commit") != commit:
        raise GenerateError(f"{where} was made by codemem {block.get('codemem_commit')}, and the codemem program "
                            f"of the runs is at {commit}; {again}")
    if (made_on := index_form(block.get("index"))) != backend:
        raise GenerateError(f"{where} was made on the {made_on} search index, and this batch searches with the "
                            f"{backend} one ({VECTOR_BACKEND_ENV}); {again}")
    if block.get("index") != read_index_meta(recipe, task, backend):
        raise GenerateError(f"{where} was made on another build of the task's index (its index.json is not the "
                            f"one in {index_root(recipe, task, backend)}); {again}")


def block_problem(recipe: Recipe, task: Task, level: str, query: str, commit: str | None,
                  backend: str | None = None) -> str | None:
    """Why a run could not use the block of this task and level, or None when it can."""
    try:
        read_block(recipe, task, level, query, commit, backend)
    except GenerateError as exc:
        return str(exc)
    return None


def gold_ranks(results: list[dict], task: Task, iou: float = e2e_replay.DEFAULT_IOU) -> dict:
    """Where the gold is among the results of a block: the rank of the first result in a gold file, and of the
    first result on a gold function (inside it, or line IoU >= iou, as in e2e_replay). None when no result is;
    the function rank is also None for a task whose function gold is not scored, and gold_function_excluded
    says why."""
    gold = e2e_replay.gold_of(task)
    files = set(gold["files"])
    first_file = next((r["rank"] for r in results if r["path"] in files), None)
    first_function = None
    if gold["function_excluded"] is None:
        first_function = next((r["rank"] for r in results
                               if any(hit_matches(Hit(path=r["path"], start_line=r["start"], end_line=r["end"]),
                                                  span, iou) for span in gold["functions"])), None)
    return {"first_gold_file_rank": first_file, "first_gold_function_rank": first_function,
            "gold_function_excluded": gold["function_excluded"]}


def record_entry(block: dict, path: Path, task: Task, vector_backend: str | None = None) -> dict:
    """What run.json keeps of the block (identity.block): its file and sha256, the number of result lines, the
    search's seconds and codemem commit, the search index (only for a batch that names one: vector_backend), the
    one codemem search that was made for the agent, where the gold is among the results, and the results (rank,
    path, line, name), which the agent saw before its first turn."""
    results = block["results"]
    return {"file": str(path), "sha256": block["sha256"], "lines": len(results), "search_s": block.get("search_s"),
            "codemem_commit": block.get("codemem_commit"),
            **({"vector_backend": vector_backend} if vector_backend else {}), "searches_made_for_agent": 1,
            **gold_ranks(results, task),
            "results": [{"rank": r["rank"], "path": r["path"], "line": r["start"], "name": r["name"]}
                        for r in results]}


def build_blocks(recipe: Recipe, task: Task, queries: dict[str, str], *, program: Path, commit: str | None,
                 search: Callable[..., dict] | None = None, timeout: float = SEARCH_TIMEOUT_S,
                 backend: str | None = None) -> dict[str, tuple[dict, str | None]]:
    """Search the text of each level of `queries` (level: text) on one private copy of the task's index of the
    search index `backend` (default: the batch's), with codemem told to search with it. Returns each level's
    block and why a run could not use it (check_block; None when it can). Only a block that a run can use
    replaces the file of its level, through a temporary file; else the old file stays as it was. The task's
    index and src/ are never written."""
    search = search or e2e_replay.cli_search_json
    backend = backend or vector_backend()
    root, src = index_root(recipe, task, backend), src_root(recipe, task)
    state = index_state(recipe, task, backend)
    if state != "ok" or not src.is_dir():
        found = state if state != "ok" else "no src/"
        raise GenerateError(f"{task.id}: no index for base commit {task.base_commit[:12]} in {root} ({found}); "
                            f"run cmeval e2e index {recipe.name} first")
    meta = read_index_meta(recipe, task, backend)
    made = {}
    # On the disk of the index, so that the copy is quick. It is deleted after the searches.
    work = Path(tempfile.mkdtemp(prefix=".block-", dir=root))
    try:
        copy, home = work / "index", work / "home"
        shutil.copytree(root / "index", copy)
        home.mkdir()
        env = e2e_replay.server_env(None, home, backend)
        for level, query in queries.items():
            t0 = time.monotonic()
            answer = search(program, src, copy, env, {"query": query}, K, timeout)
            block = make_block(task, level, query, answer, search_s=round(time.monotonic() - t0, 3),
                               program=program, commit=commit, index=meta)
            path = block_path(recipe, task, level, backend)
            temporary = path.with_name(f".{path.name}.new")
            write_json(temporary, block)
            try:
                check_block(json.loads(temporary.read_text(encoding="utf-8")), path, recipe, task, level, query,
                            commit, backend)
            except GenerateError as exc:
                temporary.unlink()
                made[level] = (block, str(exc))
                continue
            os.replace(temporary, path)
            made[level] = (block, None)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return made


def block_tasks(recipe: Recipe, jobs: list[tuple[Task, dict[str, str]]], *, force: bool = False,
                search: Callable[..., dict] | None = None,
                progress: Callable[[str], None] = lambda message: None) -> int:
    """Make the blocks of each task on the batch's search index, one task at a time (codemem uses the GPU).
    `jobs` holds each task with the text of each of its levels. A block that a run can use is skipped, unless
    force. Returns the number of blocks that failed, or that a run could not use."""
    backend = vector_backend()
    program = codemem_bin()
    commit = codemem_commit(codemem_checkout(program))
    failed = 0
    for task, queries in jobs:
        todo = {level: query for level, query in queries.items()
                if force or block_problem(recipe, task, level, query, commit, backend)}
        for level in queries:
            if level not in todo:
                progress(f"{task.id} {level}: skipped, the block exists")
        if not todo:
            continue
        try:
            made = build_blocks(recipe, task, todo, program=program, commit=commit, search=search, backend=backend)
        except (GenerateError, McpError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            failed += len(todo)
            progress(f"{task.id}: failed: {exc}")
            continue
        for level, (block, problem) in made.items():
            if problem:
                failed += 1
                progress(f"{task.id} {level}: made, but a run cannot use it, and the file was not changed: "
                         f"{problem}")
            else:
                progress(f"{task.id} {level}: {len(block['results'])} results in {block['search_s']} s")
    return failed


def sample_ids(path: Path, repo: str) -> set[str]:
    """The ids of the tasks of one repo that a run sample (`cmeval e2e sample`) runs: its rows with run true."""
    ids = set()
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if row["repo"] == repo and row["run"] is True:
                ids.add(row["id"])
        except (ValueError, KeyError, TypeError) as exc:
            raise GenerateError(f"{path}, line {number}: not a row of a run sample (repo, id, run): {exc}") from None
    return ids
