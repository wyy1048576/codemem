from dataclasses import replace

import pytest

from cmeval.cli import main
from cmeval.tasks import dumps, save_tasks


def test_help_lists_commands(capsys):
    with pytest.raises(SystemExit) as info:
        main(["--help"])
    assert info.value.code == 0
    out = capsys.readouterr().out
    for name in ("validate", "import", "collect", "review", "run", "score", "report"):
        assert name in out


def test_planned_command_exits_2(capsys):
    assert main(["review", "runs/x"]) == 2
    assert "cmeval review: not built yet" in capsys.readouterr().err


def test_validate_good_file(make_task, tmp_path, capsys):
    path = tmp_path / "tasks.jsonl"
    other = make_task(id="acme__auth-43", split="dev", fix=replace(make_task().fix, pr_number=43))
    save_tasks(path, [make_task(), other])
    assert main(["validate", str(path)]) == 0
    out = capsys.readouterr().out
    assert "2 tasks, valid" in out
    assert "split: dev 1, test 1" in out
    assert "source: fresh 2" in out


def test_validate_bad_file(make_task, tmp_path, capsys):
    path = tmp_path / "tasks.jsonl"
    path.write_text(dumps(make_task(split="train")) + "\n", encoding="utf-8")
    assert main(["validate", str(path)]) == 1
    err = capsys.readouterr().err
    assert "tasks.jsonl:1 (acme__auth-42): split 'train'" in err
    assert "not valid (1 problems)" in err


def test_validate_missing_file(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "nope.jsonl")]) == 1
    assert "no such file" in capsys.readouterr().err
