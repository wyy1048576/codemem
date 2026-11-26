"""The screen for unfair hidden tests: packets, reads, the merge, the table, and its use in the score."""

import json
from dataclasses import replace

import pytest

from cmeval import e2e_screen
from cmeval import generate as gen
from cmeval.cli import main
from cmeval.e2e_screen import ScreenError
from cmeval.tasks import save_tasks

TEST_PATCH = """\
diff --git a/pandas/tests/io/test_core.py b/pandas/tests/io/test_core.py
--- a/pandas/tests/io/test_core.py
+++ b/pandas/tests/io/test_core.py
@@ -1 +1,2 @@
 import pandas
+def test_f(): assert pandas.f() == 2
"""

ONLY_TESTS_FIX = """\
diff --git a/pandas/tests/conftest.py b/pandas/tests/conftest.py
--- a/pandas/tests/conftest.py
+++ b/pandas/tests/conftest.py
@@ -1 +1 @@
-a = 1
+a = 2
"""


def _row(task_id="t1", read=1, fair=True, **fields):
    row = {"id": task_id, "repo": "acme/auth", "difficulty": "easy", "read": read, "reader": f"reader {read}",
           "fair": fair, "kinds": [] if fair else ["extra-cases"], "deciding_assertions": "test_x asserts y",
           "reason": "because", "confidence": "high", "rules": "screen-rules-v1", "content_hash": "0123456789abcdef",
           "date": "2026-11-26"}
    row.update(fields)
    return row


def _write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


# ---- hash and rows

def test_content_hash_follows_issue_fix_and_test_change(make_task):
    task = make_task(test_patch=TEST_PATCH)
    base = e2e_screen.content_hash(task)
    assert len(base) == 16 and base == e2e_screen.content_hash(make_task(test_patch=TEST_PATCH))
    assert e2e_screen.content_hash(replace(task, query=task.query + " more")) != base
    assert e2e_screen.content_hash(replace(task, patch=task.patch + "\n")) != base
    assert e2e_screen.content_hash(replace(task, test_patch=None)) != base
    # Fields a reader does not read do not change it.
    assert e2e_screen.content_hash(replace(task, split="dev")) == base


def test_row_problems():
    assert e2e_screen.row_problems(_row()) == []
    assert e2e_screen.row_problems(_row(fair=False)) == []
    assert e2e_screen.row_problems(_row(note="imported")) == []
    assert e2e_screen.row_problems("x") == ["a row must be a JSON object"]
    cases = [
        (_row(kinds=["extra-cases"]), "a fair verdict has no kinds"),
        (_row(fair=False, kinds=[]), "needs at least one kind"),
        (_row(fair=False, kinds=["typo"]), "unknown kinds"),
        (_row(fair=False, kinds=["other", "other"]), "given twice"),
        (_row(confidence="sure"), "'confidence' must be one of"),
        (_row(read=0), "'read' must be 1 or more"),
        (_row(read=True), "'read' must be an integer"),
        (_row(fair="yes"), "'fair' must be bool"),
        (_row(difficulty="tiny"), "'difficulty' must be one of"),
        (_row(content_hash="xyz"), "16 hex digits"),
        (_row(date="26.11.2026"), "YYYY-MM-DD"),
        (_row(reason=" "), "'reason' is empty"),
        (_row(reader=""), "'reader' is empty"),
        (_row(extra=1), "unknown field 'extra'"),
        ({k: v for k, v in _row().items() if k != "rules"}, "'rules' is missing"),
    ]
    for row, message in cases:
        problems = e2e_screen.row_problems(row)
        assert any(message in p for p in problems), (row, problems)


def test_load_screen_refuses_a_bad_file(tmp_path):
    good = _write_rows(tmp_path / "good.jsonl", [_row(), _row(read=2, fair=False)])
    assert [r["read"] for r in e2e_screen.load_screen(good)] == [1, 2]
    with pytest.raises(ScreenError, match="no such screen file"):
        e2e_screen.load_screen(tmp_path / "none.jsonl")
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(_row()) + "\n{not json\n" + json.dumps(_row(read=2, confidence="x")) + "\n")
    with pytest.raises(ScreenError, match="2 problems") as info:
        e2e_screen.load_screen(bad)
    assert "line 2: not JSON" in str(info.value) and "line 3:" in str(info.value)
    twice = _write_rows(tmp_path / "twice.jsonl", [_row(), _row(reader="other")])
    with pytest.raises(ScreenError, match="read 1 of t1 is already"):
        e2e_screen.load_screen(twice)
    # One reader cannot give both reads of a task.
    same = _write_rows(tmp_path / "same.jsonl", [_row(), _row(read=2, reader="reader 1")])
    with pytest.raises(ScreenError, match="must be independent"):
        e2e_screen.load_screen(same)
    # Two files that are good alone can clash.
    other = _write_rows(tmp_path / "other.jsonl", [_row(reader="someone")])
    with pytest.raises(ScreenError, match="do not fit together"):
        e2e_screen.load_screens([good, other])


# ---- merge

def test_task_status():
    status = e2e_screen.task_status
    assert status([]) == "not screened"
    assert status([_row()]) == "one read"
    assert status([_row(), _row(read=2)]) == "fair"
    assert status([_row(fair=False), _row(read=2, fair=False)]) == "unfair"
    assert status([_row(), _row(read=2, fair=False)]) == "disagree"
    # A third read decides by majority.
    assert status([_row(), _row(read=2, fair=False), _row(read=3, fair=False)]) == "unfair"
    assert status([_row(), _row(read=2, fair=False), _row(read=3)]) == "fair"
    assert status([_row(), _row(read=2, fair=False), _row(read=3), _row(read=4, fair=False)]) == "disagree"


def test_merge_leaves_out_stale_reads():
    rows = [_row("t1"), _row("t1", read=2), _row("t2"), _row("t2", read=2, content_hash="ffffffffffffffff"),
            _row("t3")]
    merged = e2e_screen.merge(rows)
    assert merged["t1"].status == "fair" and merged["t1"].stale == 0
    # Without today's hashes, a task with two hashes cannot be judged.
    assert merged["t2"].status == "not screened" and merged["t2"].stale == 2
    assert merged["t3"].status == "one read"
    hashes = {"t1": "0123456789abcdef", "t2": "ffffffffffffffff", "t4": "aaaaaaaaaaaaaaaa"}
    tasks = {"t1": ("acme/auth", "easy"), "t2": ("acme/auth", "hard"), "t4": ("acme/auth", "medium")}
    merged = e2e_screen.merge(rows, hashes, tasks)
    assert merged["t2"].status == "one read" and merged["t2"].stale == 1 and merged["t2"].difficulty == "hard"
    # A task with no row is not screened; a row of a task outside today's set is left out.
    assert merged["t4"].status == "not screened" and "t3" not in merged


# ---- packets

def _pack_setup(make_task, tmp_path):
    """The pandas recipe and five tasks: valid, valid with an only-test fix and a long list, invalid, stale,
    not validated. Returns the recipe, the tasks and the task file."""
    recipe = gen.load_recipe("pandas")
    fix = make_task().fix
    tasks = [make_task(id=f"pandas-dev__pandas-{i}", repo=recipe.repo, test_patch=TEST_PATCH,
                       fix=replace(fix, pr_number=i)) for i in range(1, 6)]
    tasks[1] = replace(tasks[1], patch=ONLY_TESTS_FIX)
    path = tmp_path / "tasks.jsonl"
    save_tasks(path, tasks)
    long = [f"pandas.tests.io.test_core::test_{i:05d}" for i in range(250)] + ["pandas.tests.other::test_a"]
    for task, f2p, valid in ((tasks[0], ["pandas.tests.io.test_core::test_f"], True), (tasks[1], long, True),
                             (tasks[2], [], False), (tasks[3], ["x"], True)):
        folder = gen.task_dir(recipe, task)
        folder.mkdir(parents=True)
        record = {"id": task.id, "valid": valid, "reason": "ok" if valid else "no test went from failing to passing",
                  "fingerprint": gen.validation_fingerprint(recipe, task, 3), "repeats": 3,
                  "fail_to_pass_failed_before": len(f2p), "fail_to_pass_skipped_before": 0,
                  "fail_to_pass_missing_before": 0}
        (folder / "result.json").write_text(json.dumps(record))
        if valid:
            (folder / "tests.json").write_text(json.dumps({
                "fingerprint": gen.validation_fingerprint(recipe, task, 3), "repeats": 3,
                "fail_to_pass": f2p, "pass_to_pass": ["pandas.tests.io.test_core::test_old"]}))
    # Task 4 was validated with another version of the task.
    stale = gen.task_dir(recipe, tasks[3]) / "result.json"
    stale.write_text(json.dumps({**json.loads(stale.read_text()), "fingerprint": "0000000000000000"}))
    return recipe, tasks, path


def test_pack_writes_packets_index_and_batches(make_task, tmp_path):
    recipe, tasks, _ = _pack_setup(make_task, tmp_path)
    out = tmp_path / "packets"
    entry = e2e_screen.pack(recipe, tasks, out, task_file="tasks.jsonl", n_batches=2)
    assert entry["packets"] == 2 and entry["not_validated"] == 1
    assert {s["id"]: s["reason"].split(":")[0] for s in entry["skipped"]} == {
        "pandas-dev__pandas-3": "not valid", "pandas-dev__pandas-4": e2e_screen.STALE_RECORD}
    assert entry["pool"]["easy"] == {"candidates": 5, "validated": 3, "valid": 2}

    first = out / "pandas-dev__pandas-1"
    assert (first / "issue.txt").read_text() == tasks[0].query
    assert (first / "real-fix.patch").read_text() == tasks[0].patch
    assert (first / "test.patch").read_text() == TEST_PATCH
    facts = json.loads((first / "packet.json").read_text())
    assert facts["content_hash"] == e2e_screen.content_hash(tasks[0]) and facts["difficulty"] == "easy"
    assert facts["fix_files"] == ["auth/sessions.py"] and facts["test_files"] == ["pandas/tests/io/test_core.py"]
    assert facts["fix_changes_only_tests"] is False and facts["fix_files_named_test"] == []
    assert facts["fail_to_pass"] == {"total": 1, "shown": ["pandas.tests.io.test_core::test_f"]}
    assert facts["fail_to_pass_before"] == {"failed": 1, "skipped": 0, "missing": 0}

    second = json.loads((out / "pandas-dev__pandas-2" / "packet.json").read_text())
    assert second["fix_changes_only_tests"] is True
    assert second["fail_to_pass"]["total"] == 251 and len(second["fail_to_pass"]["shown"]) == e2e_screen.LIST_SHOWN
    assert second["fail_to_pass"]["groups"] == {"pandas.tests.io.test_core": 250, "pandas.tests.other": 1}

    index = e2e_screen.load_index(out)
    assert index["rules"] == e2e_screen.RULES_VERSION and index["rules_sha256"]
    assert [p["id"] for p in index["packets"]] == ["pandas-dev__pandas-1", "pandas-dev__pandas-2"]
    batches = [(out / name).read_text().split() for name in entry["batches"]]
    assert sorted(i for b in batches for i in b) == ["pandas-dev__pandas-1", "pandas-dev__pandas-2"]
    assert len(batches) == 2

    # Packing one task again keeps the index of the other recipe and replaces this recipe's packets.
    entry = e2e_screen.pack(recipe, tasks, out, ids=["pandas-dev__pandas-1"])
    assert entry["packets"] == 1 and [p["id"] for p in e2e_screen.load_index(out)["packets"]] == ["pandas-dev__pandas-1"]
    assert sorted(f.name for f in (out / "batches").iterdir()) == ["pandas-1.txt"]
    # An index of other rules is refused.
    (out / "index.json").write_text(json.dumps({"rules": "screen-rules-v0", "recipes": {}, "packets": []}))
    with pytest.raises(ScreenError, match="use a new folder"):
        e2e_screen.pack(recipe, tasks, out)


def test_short_list():
    assert e2e_screen.short_list(["b", "a"]) == {"total": 2, "shown": ["a", "b"]}
    long = e2e_screen.short_list([f"f{i % 3}::t{i}" for i in range(10)], limit=4, groups=2)
    assert long["total"] == 10 and len(long["shown"]) == 4
    assert long["groups"] == {"f0": 4, "f1": 3} and long["groups_total"] == 3


def test_batches_mix_levels():
    packets = [{"id": f"t{i}", "repo": "r", "difficulty": level} for i, level in
               enumerate(["easy", "easy", "medium", "medium", "hard", "hard"])]
    split = e2e_screen.batches(packets, 2)
    assert split == [["t0", "t2", "t4"], ["t1", "t3", "t5"]]
    assert e2e_screen.batches(packets[:1], 3) == [["t0"]]


# ---- add a read

def _verdicts(index, fair=True, **fields):
    return [{"id": p["id"], "content_hash": p["content_hash"], "fair": fair, "kinds": [] if fair else ["new-name"],
             "deciding_assertions": "a", "reason": "b", "confidence": "medium", **fields} for p in index["packets"]]


def test_add_read_checks_against_the_packets(make_task, tmp_path):
    recipe, tasks, _ = _pack_setup(make_task, tmp_path)
    out = tmp_path / "packets"
    e2e_screen.pack(recipe, tasks, out)
    index = e2e_screen.load_index(out)
    screen = tmp_path / "screen" / "s.jsonl"
    output = tmp_path / "read.json"

    def add(verdicts, **kwargs):
        output.write_text(json.dumps(verdicts))
        args = {"read": 1, "reader": "r1"} | kwargs
        return e2e_screen.add_read(output, out, screen, **args)

    bad_hash = _verdicts(index)
    bad_hash[0]["content_hash"] = "ffffffffffffffff"
    with pytest.raises(ScreenError, match="is not the packet's"):
        add(bad_hash)
    with pytest.raises(ScreenError, match="have no verdict"):
        add(_verdicts(index)[:1])
    with pytest.raises(ScreenError, match="no packet of this id"):
        add(_verdicts(index) + [{**_verdicts(index)[0], "id": "pandas-dev__pandas-9"}])
    with pytest.raises(ScreenError, match="given twice"):
        add(_verdicts(index) + _verdicts(index)[:1])
    with pytest.raises(ScreenError, match="unknown field 'read'"):
        add(_verdicts(index, read=1))
    with pytest.raises(ScreenError, match="needs at least one kind"):
        add(_verdicts(index, fair=False, kinds=[]))
    assert not screen.exists()

    rows = add(_verdicts(index), date="2026-11-26")
    assert len(rows) == 2 and rows[0]["rules"] == e2e_screen.RULES_VERSION and rows[0]["difficulty"] == "easy"
    assert e2e_screen.load_screen(screen) == rows
    # The same read again, or the same reader for read 2, is refused and writes nothing.
    with pytest.raises(ScreenError, match="already"):
        add(_verdicts(index), reader="r2")
    with pytest.raises(ScreenError, match="must be independent"):
        add(_verdicts(index), read=2)
    assert len(e2e_screen.load_screen(screen)) == 2

    # A batch file limits the expected packets. JSON lines work too.
    batch = tmp_path / "batch.txt"
    batch.write_text("pandas-dev__pandas-2\n")
    output.write_text(json.dumps(_verdicts(index, fair=False)[1]) + "\n")
    rows = e2e_screen.add_read(output, out, screen, read=2, reader="r2", batch=batch, note="n", rules="old-rules")
    assert [(r["id"], r["fair"], r["note"], r["rules"]) for r in rows] == [("pandas-dev__pandas-2", False, "n",
                                                                           "old-rules")]
    output.write_text(json.dumps(_verdicts(index)))
    with pytest.raises(ScreenError, match="outside the batch"):
        e2e_screen.add_read(output, out, screen, read=3, reader="r3", batch=batch)


def test_add_read_needs_an_index(tmp_path):
    (tmp_path / "out.json").write_text("[]")
    with pytest.raises(ScreenError, match="no packet index"):
        e2e_screen.add_read(tmp_path / "out.json", tmp_path, tmp_path / "s.jsonl", read=1, reader="r")


# ---- table

def test_table_counts_and_warnings():
    rows = []
    for i, (level, verdicts) in enumerate([("easy", (True, True)), ("easy", (False, False)), ("medium", (True, False)),
                                           ("hard", (True,)), ("hard", (True, True))]):
        rows += [_row(f"t{i}", read=n, fair=v, difficulty=level, kinds=[] if v else ["other"])
                 for n, v in enumerate(verdicts, start=1)]
    rows.append(_row("u1", repo="other/repo"))
    rows.append(_row("u1", read=2, repo="other/repo"))
    status = e2e_screen.merge(rows)
    pools = {"acme/auth": {lv: {"candidates": 10, "validated": 4, "valid": 2} for lv in e2e_screen.LEVELS}}
    result = e2e_screen.table(status, pools=pools, need_repo=3, need_level={"easy": 1, "medium": 1, "hard": 1})
    by = {(r["repo"], r["level"]): r for r in result["rows"]}
    assert by[("acme/auth", "all")] == {"repo": "acme/auth", "level": "all", "valid": 5, "kept": 2, "removed": 1,
                                         "disagree": 1, "open": 1}
    assert by[("acme/auth", "easy")]["kept"] == 1 and ("other/repo", "medium") not in by
    assert result["disagree"] == ["t2"] and result["one_read"] == ["t3"]
    assert result["total"]["valid"] == 6 and result["levels"]["easy"] == {"valid": 3, "kept": 2, "removed": 1,
                                                                         "disagree": 0, "open": 0}
    warnings = result["warnings"]
    assert len(warnings) == 3
    assert warnings[0] == ("acme/auth medium: 0 kept, 1 needed; 1 valid tasks not decided yet; 6 candidates with "
                           "tests are not validated yet")
    assert warnings[1].startswith("acme/auth: 2 kept, 3 needed; 2 valid tasks not decided yet; keep rate 2 of 3, "
                                  "so about 0 more valid tasks are needed; 18 candidates")
    assert warnings[2] == "other/repo: 1 kept, 3 needed; keep rate 1 of 1, so about 2 more valid tasks are needed"

    text = e2e_screen.format_table(result, ["s.jsonl"])
    assert "| **acme/auth** | **all** | 5 | 2 | 1 | 1 | 1 |" in text
    assert "| **all** | **all** | 6 | 3 | 1 | 1 | 1 |" in text
    assert "easy 2 of 3 (67%)" in text and "Disagree, needs a third read (1): t2" in text
    assert "- **Warning:** other/repo: 1 kept" in text


def test_parse_need_level():
    assert e2e_screen.parse_need_level("") == e2e_screen.NEED_LEVEL
    assert e2e_screen.parse_need_level("easy=2, hard=3") == {"easy": 2, "medium": 8, "hard": 3}
    with pytest.raises(ScreenError, match="LEVEL=N"):
        e2e_screen.parse_need_level("tiny=2")
    with pytest.raises(ScreenError, match="LEVEL=N"):
        e2e_screen.parse_need_level("easy=x")


# ---- command line

def test_cli_pack_add_table(make_task, tmp_path, capsys, monkeypatch):
    path = _pack_setup(make_task, tmp_path)[2]
    out = tmp_path / "packets"
    assert main(["e2e", "screen-pack", "pandas", "--tasks", str(path), "--out", str(out), "--batches", "2"]) == 0
    captured = capsys.readouterr()
    assert "pandas: 2 packets" in captured.out and "1 tasks skipped: not validated" in captured.err
    index = e2e_screen.load_index(out)
    screen = tmp_path / "s.jsonl"
    for read, fair in ((1, True), (2, False)):
        (tmp_path / f"r{read}.json").write_text(json.dumps(_verdicts(index, fair=fair)))
        assert main(["e2e", "screen-add", str(tmp_path / f"r{read}.json"), "--packets", str(out), "--screen",
                     str(screen), "--read", str(read), "--reader", f"r{read}", "--date", "2026-11-26"]) == 0
    assert "read 2 of 2 tasks added (0 fair, 2 unfair)" in capsys.readouterr().out
    assert main(["e2e", "screen-add", str(tmp_path / "r1.json"), "--packets", str(out), "--screen", str(screen),
                 "--read", "1", "--reader", "r9"]) == 1
    assert "nothing written" in capsys.readouterr().err

    assert main(["e2e", "screen-table", "--screen", str(screen), "--packets", str(out), "--need-repo", "1",
                 "--need-level", "easy=1"]) == 0
    text = capsys.readouterr().out
    assert "| **pandas-dev/pandas** | **all** | 2 | 0 | 0 | 2 | 0 |" in text
    assert "Disagree, needs a third read (2): pandas-dev__pandas-1, pandas-dev__pandas-2" in text
    assert main(["e2e", "screen-table", "--screen", str(screen), "--need-level", "x=1"]) == 1
    # No valid task: exit code 1.
    monkeypatch.setenv("CMEVAL_HOME", str(tmp_path / "empty_home"))
    assert main(["e2e", "screen-pack", "pandas", "--tasks", str(path), "--out", str(tmp_path / "p2")]) == 1
