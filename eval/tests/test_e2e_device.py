"""The switch CMEVAL_CODEMEM_DEVICE=cpu, for a machine whose containers cannot get a GPU: it builds its task indexes
on the CPU and runs codemem setups there, with the same device in every place where the eval starts codemem."""

import json
import os

import pytest

import test_e2e_run as run_tests
from cmeval import e2e_index, e2e_replay, e2e_run
from cmeval import generate as gen
from cmeval.e2e_run import RunSettings
from test_e2e_block import RECIPE, _write_block
from test_e2e_run import PROXY_LINES, TOOL_STREAM, _codemem_install, _events, _local_run, _shim

ENV = e2e_index.DEVICE_ENV
MODEL = "claude-haiku-5-5"


def test_unset_device_changes_nothing():
    assert ENV not in os.environ and e2e_index.codemem_device() is None
    assert e2e_index.codemem_env("faiss") == {"CODEMEM_VECTOR_BACKEND": "faiss"}


def test_the_device_is_cpu_or_not_set(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV, "cpu")
    assert e2e_index.codemem_device() == "cpu"
    assert e2e_index.codemem_env("compact") == {"CODEMEM_VECTOR_BACKEND": "compact", "CODEMEM_DEVICE": "cpu"}
    assert e2e_replay.server_env(None, tmp_path / "home")["CODEMEM_DEVICE"] == "cpu"
    monkeypatch.setenv(ENV, "cuda")
    with pytest.raises(gen.GenerateError, match="CMEVAL_CODEMEM_DEVICE must be one of cpu or not set, not 'cuda'"):
        e2e_index.codemem_device()


def test_an_index_of_another_device_is_not_ok(make_task, monkeypatch):
    task = make_task()
    root = e2e_index.index_root(RECIPE, task)
    (root / "index").mkdir(parents=True)
    meta = {"task_id": task.id, "repo": task.repo, "base_commit": task.base_commit, "codemem_commit": "abc",
            "seconds": 1.0, "summary": "indexed 3 files"}
    (root / "index.json").write_text(json.dumps(meta))
    assert e2e_index.index_state(RECIPE, task) == "ok"
    monkeypatch.setenv(ENV, "cpu")
    assert e2e_index.index_state(RECIPE, task) == "another device"  # built on the device codemem picked
    (root / "index.json").write_text(json.dumps({**meta, "codemem_device": "cpu"}))
    assert e2e_index.index_state(RECIPE, task) == "ok"
    monkeypatch.delenv(ENV)
    assert e2e_index.index_state(RECIPE, task) == "another device"


def test_cpu_build_names_the_device(make_task, tmp_path, monkeypatch):
    task = make_task()
    (tmp_path / "bin").mkdir()
    seen = tmp_path / "device.txt"
    _shim(tmp_path / "bin", "codemem", f'#!/bin/sh\necho "device=$CODEMEM_DEVICE" >> "{seen}"\nmkdir -p "$4"\n'
                                       'echo "indexed 1 files"\n')
    program = tmp_path / "bin" / "codemem"
    monkeypatch.setattr(e2e_index, "ensure_worktree", lambda task, src: src.mkdir(parents=True, exist_ok=True))
    monkeypatch.setenv(ENV, "cpu")
    meta = e2e_index.index_task(RECIPE, task, program=program, commit="abc")
    assert list(meta)[-1] == "codemem_device" and meta["codemem_device"] == "cpu"
    assert seen.read_text().splitlines() == ["device=cpu"]
    # The same commits and the same device: nothing to build. Without the switch it is built again, with no device.
    assert e2e_index.index_task(RECIPE, task, program=program, commit="abc") is None
    monkeypatch.delenv(ENV)
    meta = e2e_index.index_task(RECIPE, task, program=program, commit="abc")
    assert "codemem_device" not in meta and seen.read_text().splitlines() == ["device=cpu", "device="]


def test_cpu_run_without_the_gpu(make_task, tmp_path, monkeypatch):
    lines = [{**r, "opens_with_text": True} for r in PROXY_LINES]
    recipe, task, calls, _ = _local_run(monkeypatch, tmp_path, make_task, stream_lines=_events(TOOL_STREAM),
                                        proxy_lines=lines)
    _, _, _, meta = _codemem_install(tmp_path, monkeypatch, recipe, task)
    monkeypatch.setenv(e2e_run.GPUS_ENV, "0")
    out = e2e_run.run_dir("c1", task.id, "codemem", 1)
    # Without the switch, a codemem setup still needs the GPU.
    with pytest.raises(gen.GenerateError, match="needs the GPU in the container"):
        e2e_run.run_one(recipe, task, setup="codemem", model=MODEL, rep=1, out=out, settings=RunSettings(poll_s=0.05))
    # With it, the index and the block made on the CPU, the run has no GPU and its codemem is told the CPU.
    monkeypatch.setenv(ENV, "cpu")
    meta = {**meta, "codemem_device": "cpu"}
    (e2e_index.index_root(recipe, task) / "index.json").write_text(json.dumps(meta))
    _write_block(task)
    seen = {}
    run_tests._spy_docker_run(monkeypatch, seen)
    record = e2e_run.run_one(recipe, task, setup="codemem", model=MODEL, rep=1, out=out,
                             settings=RunSettings(poll_s=0.05))
    assert record["integrity"]["setup_ok"] and not record["discard"] and record["flags"] == []
    assert "--device" not in seen["cmd"] and record["integrity"]["gpus"] is False
    assert json.loads((out / "mcp.json").read_text())["mcpServers"]["codemem"]["env"]["CODEMEM_DEVICE"] == "cpu"
    codemem = record["identity"]["codemem"]
    assert codemem["device"] == "cpu" and codemem["index"] == meta
