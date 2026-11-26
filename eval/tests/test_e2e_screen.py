"""The screen for unfair hidden tests: packets, reads, the merge, the table, and its use in the score."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from cmeval import e2e_run, e2e_screen
from cmeval import generate as gen
from cmeval.cli import main
from cmeval.e2e_score import format_score, score
from cmeval.e2e_screen import ScreenError
from cmeval.tasks import load_tasks, save_tasks

TASKS = Path(__file__).resolve().parents[1] / "tasks"
PILOT18 = TASKS / "screen" / "pilot18.jsonl"

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


def test_facts_change_the_hash_and_load(tmp_path, make_task):
    task = make_task(test_patch=TEST_PATCH)
    assert e2e_screen.content_hash(task, []) == e2e_screen.content_hash(task)
    with_fact = e2e_screen.content_hash(task, ["checked on 1.0: the case passes"])
    assert with_fact != e2e_screen.content_hash(task)
    assert e2e_screen.task_hashes([task], {task.id: ["checked on 1.0: the case passes"]}) == {task.id: with_fact}

    lines = tmp_path / "facts.jsonl"
    lines.write_text(json.dumps({"id": "a", "fact": "f1", "date": "2026-11-26", "source": "check"}) + "\n\n"
                     + json.dumps({"id": "a", "fact": "f2", "date": "2026-11-27", "source": "check"}) + "\n")
    assert e2e_screen.load_facts(lines) == {"a": ["f1", "f2"]}
    mapping = tmp_path / "facts.json"
    mapping.write_text(json.dumps({"a": ["f1"], "b": ["f2", "f3"]}))
    assert e2e_screen.load_facts(mapping) == {"a": ["f1"], "b": ["f2", "f3"]}
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"id": "a", "fact": " ", "date": "26.11.2026", "source": "x"}) + "\nnope\n"
                   + json.dumps({"id": "a", "fact": "f"}) + "\n")
    with pytest.raises(ScreenError, match="3 problems") as info:
        e2e_screen.load_facts(bad)
    assert "'fact' is empty" in str(info.value) and "YYYY-MM-DD" in str(info.value) and "'date' is missing" in str(info.value)
    mapping.write_text(json.dumps({"a": "f1"}))
    with pytest.raises(ScreenError, match="list of fact texts"):
        e2e_screen.load_facts(mapping)
    with pytest.raises(ScreenError, match="no such facts file"):
        e2e_screen.load_facts(tmp_path / "none.jsonl")
    # The facts file of the repo is good.
    assert all(e2e_screen.load_facts().values())


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

    # A fact goes into the packet and its hash.
    fact = {"pandas-dev__pandas-1": ["checked: the case fails on 2.0"]}
    e2e_screen.pack(recipe, tasks, out, facts=fact)
    facts = json.loads((first / "packet.json").read_text())
    assert facts["facts"] == ["checked: the case fails on 2.0"]
    assert facts["content_hash"] == e2e_screen.content_hash(tasks[0], fact["pandas-dev__pandas-1"])
    assert [p["facts"] for p in e2e_screen.load_index(out)["packets"]] == [1, 0]
    assert "facts" not in json.loads((out / "pandas-dev__pandas-2" / "packet.json").read_text())

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

def _table_rows():
    rows = []
    cases = [("easy", (True, True)), ("easy", (False, False)), ("medium", (True, False)), ("hard", (True,)),
             ("hard", (True, True)), ("hard", (True, False, True))]
    for i, (level, verdicts) in enumerate(cases):
        rows += [_row(f"t{i}", read=n, fair=v, difficulty=level, kinds=[] if v else ["other"])
                 for n, v in enumerate(verdicts, start=1)]
    rows.append(_row("u1", repo="other/repo"))
    rows.append(_row("u1", read=2, repo="other/repo"))
    return rows


def test_table_counts_and_warnings():
    status = e2e_screen.merge(_table_rows())
    assert status["t5"].by_majority and status["t5"].any_unfair and not status["t4"].by_majority
    pools = {"acme/auth": {lv: {"candidates": 10, "validated": 4, "valid": 2} for lv in e2e_screen.LEVELS}}
    result = e2e_screen.table(status, pools=pools, need_repo=3, need_level={"easy": 1, "medium": 1, "hard": 1},
                              early_factor=2, floor_repo=2)
    by = {(r["repo"], r["level"]): r for r in result["rows"]}
    assert by[("acme/auth", "all")] == {"repo": "acme/auth", "level": "all", "valid": 6, "kept": 3, "removed": 1,
                                         "disagree": 1, "open": 1}
    # Every level has a row, also one with no task.
    assert by[("other/repo", "medium")] == {"repo": "other/repo", "level": "medium", "valid": 0, "kept": 0,
                                            "removed": 0, "disagree": 0, "open": 0}
    assert len(result["rows"]) == 8
    assert result["disagree"] == ["t2"] and result["one_read"] == ["t3"] and result["majority"] == ["t5"]
    assert result["total"]["valid"] == 7 and result["levels"]["easy"] == {"valid": 3, "kept": 2, "removed": 1,
                                                                         "disagree": 0, "open": 0}
    agreement = result["agreement"]
    assert (agreement["tasks"], agreement["agree"]) == (6, 4)
    assert agreement["kappa"] == pytest.approx(1 / 3)

    warnings = {(w["repo"], w["level"]): (w["tier"], w["text"]) for w in result["warnings"]}
    assert sorted(warnings) == [("acme/auth", "all"), ("acme/auth", "easy"), ("acme/auth", "medium"),
                                ("other/repo", "all"), ("other/repo", "easy"), ("other/repo", "hard"),
                                ("other/repo", "medium")]
    assert warnings[("acme/auth", "easy")] == ("early warning", (
        "acme/auth easy: 1 kept; need 1, early warning below 2; keep rate 1 of 2; to reach 2: about 4 more "
        "candidates to validate (validity rate 2 of 4); 6 candidates with tests are not validated yet"))
    assert warnings[("acme/auth", "medium")] == ("below the need", (
        "acme/auth medium: 0 kept; need 1, early warning below 2; 1 valid tasks not decided yet; no keep rate yet"))
    assert warnings[("acme/auth", "all")] == ("early warning", (
        "acme/auth: 3 kept; need 3, early warning below 6, floor 2; 2 valid tasks not decided yet; keep rate 3 of 4; "
        "to reach 6: about 4 more candidates to validate (validity rate 6 of 12); 18 candidates with tests are not "
        "validated yet"))
    assert warnings[("other/repo", "all")] == ("below the floor", (
        "other/repo: 1 kept; need 3, early warning below 6, floor 2; keep rate 1 of 1; to reach 3: about 2 more "
        "valid tasks (give --packets for candidates)"))

    text = e2e_screen.format_table(result, ["s.jsonl"])
    assert "| **acme/auth** | **all** | 6 | 3 | 1 | 1 | 1 |" in text
    assert "| other/repo | medium | 0 | 0 | 0 | 0 | 0 |" in text
    assert "| **all** | **all** | 7 | 4 | 1 | 1 | 1 |" in text
    assert "easy 2 of 3 (67%)" in text and "Disagree, needs a third read (1): t2" in text
    assert "Read 1 and read 2 agree on 4 of 6 (67%) tasks; Cohen's kappa 0.33." in text
    assert "(for example 2 to 1): 1 (t5)." in text
    assert "- **Below the floor:** other/repo: 1 kept" in text and "- **Early warning:** acme/auth easy" in text
    assert "early warning below 6 per repo (per level easy 2, medium 2, hard 2); floor 2 per repo." in text


def test_agreement_edge_cases():
    assert e2e_screen.agreement({}) == {"tasks": 0, "agree": 0, "share": None, "kappa": None}
    same = e2e_screen.merge([_row("a"), _row("a", read=2), _row("b"), _row("b", read=2)])
    result = e2e_screen.agreement(same)
    assert (result["share"], result["kappa"]) == (1.0, None)
    assert "Cohen's kappa not defined" in e2e_screen.format_table(e2e_screen.table(same), ["s"])


def test_default_needs():
    status = e2e_screen.merge([_row("a"), _row("a", read=2)])
    result = e2e_screen.table(status)
    assert [w["tier"] for w in result["warnings"]] == ["below the need"] * 3 + ["below the floor"]
    text = e2e_screen.format_table(result, ["s"])
    assert ("Need: 20 kept tasks per repo (per level easy 6, medium 8, hard 6); early warning below 25 per repo "
            "(per level easy 8, medium 10, hard 8); floor 12 per repo.") in text


def test_parse_need_level():
    assert e2e_screen.parse_need_level("") == e2e_screen.NEED_LEVEL
    assert e2e_screen.parse_need_level("easy=2, hard=3") == {"easy": 2, "medium": 8, "hard": 3}
    with pytest.raises(ScreenError, match="LEVEL=N"):
        e2e_screen.parse_need_level("tiny=2")
    with pytest.raises(ScreenError, match="LEVEL=N"):
        e2e_screen.parse_need_level("easy=x")


def test_pilot18_screen_in_the_repo():
    """The two reads of 2026-11-25 agree on all 18 tasks, 9 fair and 9 not. A fact of 2026-11-26 reopened
    pandas 70742: with the task files and the facts, its two reads are stale, and 17 tasks are decided."""
    rows = e2e_screen.load_screen(PILOT18)
    assert len(rows) == 36 and {r["read"] for r in rows} == {1, 2}
    result = e2e_screen.table(e2e_screen.merge(rows))
    by = {(r["repo"], r["level"]): r for r in result["rows"]}
    assert (result["total"]["kept"], result["total"]["removed"], result["total"]["disagree"]) == (9, 9, 0)
    assert (by[("pandas-dev/pandas", "all")]["valid"], by[("pandas-dev/pandas", "all")]["kept"]) == (10, 4)
    assert (by[("microsoft/playwright", "all")]["valid"], by[("microsoft/playwright", "all")]["kept"]) == (8, 5)

    tasks = load_tasks(TASKS / "fresh-v1.jsonl") + load_tasks(TASKS / "fresh-ts-v1.jsonl")
    facts = e2e_screen.load_facts()
    assert list(facts) == ["pandas-dev__pandas-70742"]
    result = e2e_screen.screen_table([PILOT18], tasks=tasks, facts=facts)
    by = {(r["repo"], r["level"]): r for r in result["rows"]}
    assert result["stale"] == ["pandas-dev__pandas-70742"]
    assert result["total"] == {"valid": 18, "kept": 8, "removed": 9, "disagree": 0, "open": 1}
    assert by[("pandas-dev/pandas", "all")] == {"repo": "pandas-dev/pandas", "level": "all", "valid": 10, "kept": 3,
                                                 "removed": 6, "disagree": 0, "open": 1}
    assert by[("pandas-dev/pandas", "medium")]["kept"] == 0 and by[("microsoft/playwright", "all")]["kept"] == 5
    assert (result["agreement"]["tasks"], result["agreement"]["agree"]) == (17, 17)


# ---- the score

def _write_run(run_id, task_id, setup, completed, tokens):
    record = {"task_id": task_id, "setup": setup, "rep": 1, "end": "finished", "completed": completed,
              "discard": False, "flags": [], "tokens": {"processed_tokens": tokens}, "time": {"agent_s": 10.0},
              "steps": {"turns": 5}}
    out = e2e_run.run_dir(run_id, task_id, setup, 1)
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps(record))


def test_score_with_a_screen(make_task, tmp_path, capsys):
    # t1 fair: grep fails, tool completes. t2 unfair: both complete. t3 not screened: grep completes.
    # t4 fair by 2 to 1: grep completes, tool fails.
    for task_id, grep_done, tool_done in (("t1", False, True), ("t2", True, True), ("t3", True, False),
                                          ("t4", True, False)):
        _write_run("sc", task_id, "grep", grep_done, 1000)
        _write_run("sc", task_id, "tool", tool_done, 500)
    screen = _write_rows(tmp_path / "s.jsonl", [_row("t1"), _row("t1", read=2), _row("t2", fair=False),
                                                _row("t2", read=2, fair=False), _row("t4"),
                                                _row("t4", read=2, fair=False), _row("t4", read=3)])
    plain = score("sc")
    assert "screen" not in plain and "completion_runs" not in plain["setups"]["grep"]
    assert "completed_share_strict" not in plain["setups"]["grep"]
    assert plain["setups"]["grep"]["completed_share"] == pytest.approx(3 / 4)
    assert "conservative" not in format_score(plain)

    summary = score("sc", e2e_screen.completion_set([screen]))
    grep, tool = summary["setups"]["grep"], summary["setups"]["tool"]
    assert (grep["completed_share"], tool["completed_share"]) == (0.5, 0.5)
    # The conservative variant also leaves out t4, which had an unfair read.
    assert (grep["completed_share_strict"], tool["completed_share_strict"]) == (0.0, 1.0)
    assert grep["completion_runs"] == 2 and grep["tokens_mean"] == 1000 and grep["runs"] == 4
    assert summary["screen"] == {"files": ["s.jsonl"], "tasks": 4, "fair": 2, "fair_strict": 1,
                                 "left_out": {"t2": "unfair", "t3": "not screened"}}
    paired = summary["paired"][0]
    assert (paired["tasks"], paired["completed_tasks"], paired["completed"], paired["tokens"]) == (4, 2, 0.0, -500.0)
    text = format_score(summary)
    assert "screen s.jsonl: completion counts 2 of 4 tasks; 2 left out (not screened 1, unfair 1)" in text
    assert "conservative (no unfair read at all): completion over 1 tasks: grep 0.00, tool 1.00" in text
    assert "completed 0.00 (over 2 fair tasks), tokens -500" in text

    # Without the task files a stale read could count, so the command line refuses it.
    assert main(["e2e", "score", "sc", "--screen", str(screen)]) == 1
    assert "--screen needs --tasks FILE" in capsys.readouterr().err
    assert main(["e2e", "score", "sc", "--tasks", str(screen)]) == 1
    assert "only with --screen" in capsys.readouterr().err
    assert main(["e2e", "score", "sc", "--screen", str(tmp_path / "none.jsonl")]) == 1


def test_score_screen_checks_hashes_with_the_task_file(make_task, tmp_path, capsys):
    task = make_task(id="acme__auth-42", test_patch=TEST_PATCH)
    path = tmp_path / "tasks.jsonl"
    save_tasks(path, [task])
    _write_run("sh", "acme__auth-42", "grep", True, 1000)
    good = e2e_screen.content_hash(task)
    screen = _write_rows(tmp_path / "s.jsonl", [_row("acme__auth-42", content_hash=good),
                                                _row("acme__auth-42", read=2, content_hash=good)])
    assert score("sh", e2e_screen.completion_set([screen], load_tasks(path)))["screen"]["fair"] == 1
    # The task changed after the reads: they are stale, and the task leaves the completion score.
    changed = tmp_path / "changed.jsonl"
    save_tasks(changed, [replace(task, query="another issue")])
    assert main(["e2e", "score", "sh", "--screen", str(screen), "--tasks", str(changed)]) == 0
    assert "1 left out (not screened 1)" in capsys.readouterr().out
    # A new fact reopens the task: the reads made without it are stale.
    facts = tmp_path / "facts.jsonl"
    facts.write_text(json.dumps({"id": task.id, "fact": "f", "date": "2026-11-26", "source": "check"}) + "\n")
    assert main(["e2e", "score", "sh", "--screen", str(screen), "--tasks", str(path), "--facts", str(facts)]) == 0
    assert "1 left out (not screened 1)" in capsys.readouterr().out
    assert main(["e2e", "screen-table", "--screen", str(screen), "--tasks", str(path), "--facts", str(facts)]) == 0
    out = capsys.readouterr().out
    assert "Reads left out because the task or its facts changed after the read: acme__auth-42" in out
    assert not out.startswith("Note:")
    # Without --tasks and --packets the table still works, with a note first.
    assert main(["e2e", "screen-table", "--screen", str(screen)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Note: no --tasks and no --packets, so stale reads") and "| acme/auth | easy | 1 | 1 |" in out


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
