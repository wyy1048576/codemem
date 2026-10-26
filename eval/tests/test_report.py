import hashlib
import json
import random

import pytest

from cmeval.cli import main
from cmeval.paths import runs_dir
from cmeval.report import ReportError, report
from cmeval.retriever import Hit
from cmeval.score import score
from cmeval.tasks import Fix, Issue, save_tasks

GOLD = Hit("auth/sessions.py", 33, 34, text="g" * 10)  # the default task's gold function
MISS = Hit("other.py", 1, 5, text="t" * 10)


class CharCounter:
    """Tokens = characters, so token numbers are easy to follow."""
    name = "chars"
    estimate = False

    def count(self, texts):
        return [len(t) for t in texts]


# 6 tasks over 2 repos: identifier_in_query True for 4, False for 2; 3 issues before the cutoff.
TASKS = [("acme__auth-1", "acme/auth", True, "2025-05-01T00:00:00Z"),
         ("acme__auth-2", "acme/auth", True, "2025-06-01T00:00:00Z"),
         ("acme__auth-3", "acme/auth", False, "2026-08-01T00:00:00Z"),
         ("acme__web-4", "acme/web", True, "2026-09-01T00:00:00Z"),
         ("acme__web-5", "acme/web", True, "2024-01-01T00:00:00Z"),
         ("acme__web-6", "acme/web", False, "2026-10-01T00:00:00Z")]
PRIMARY = ["cm-a", "cm-b"]  # the systems under test in these hand-made runs
FOUND_BY_CM_B = {"acme__auth-1", "acme__auth-2", "acme__web-4"}


def hits(system, task_id):
    if system == "grep":
        return [Hit("auth/sessions.py", text="x" * 10)]
    if system == "grep-fn":
        return [MISS, GOLD]  # rank 2: MRR 0.5, 20 tokens to the first right function
    if system == "cm-a":
        return [GOLD, MISS]  # rank 1: MRR 1.0, 10 tokens
    return [GOLD, MISS] if task_id in FOUND_BY_CM_B else [MISS]  # cm-b: half found


@pytest.fixture
def run_dir(tmp_path, make_task):
    tasks = [make_task(id=task_id, repo=repo, fix=Fix(pr_number=int(task_id.rsplit("-", 1)[1])),
                       issue=Issue(number=1, url="https://github.com/x/y/issues/1", created_at=created),
                       tags={"identifier_in_query": ident}) for task_id, repo, ident, created in TASKS]
    tasks_file = tmp_path / "tasks.jsonl"
    save_tasks(tasks_file, tasks)
    run = runs_dir() / "r1"
    run.mkdir(parents=True)
    systems = [("grep", "file", "g"), ("grep-fn", "line", "g"), ("cm-a", "line", "c"), ("cm-b", "line", "c")]
    meta = {"run_id": "r1", "status": "done", "k": 50, "split": "dev", "index_mode": "update",
            "tasks_file": str(tasks_file), "tasks_sha256": hashlib.sha256(tasks_file.read_bytes()).hexdigest(),
            "cmeval_git": {"sha": "a" * 40, "dirty": False}, "machine": {"platform": "test-os"},
            "systems": [{"name": n, "adapter": "codemem" if n.startswith("cm") else "grep", "granularity": g,
                         "index_key": k, "describe": {"codemem_git": {"sha": "b" * 40, "dirty": False}}}
                        for n, g, k in systems]}
    (run / "meta.json").write_text(json.dumps(meta))
    for name, _, _ in systems:
        with (run / f"{name}.jsonl").open("w") as f:
            for task_id, *_ in TASKS:
                f.write(json.dumps({"task_id": task_id, "commit": "c" * 40, "search_ms": 5.0,
                                    "hits": [h.to_dict() for h in hits(name, task_id)]}) + "\n")
    index = [{"system": "cm-a", "task_id": "acme__auth-1", "index_key": "c", "mode": "build",
              "report": {"seconds": 3.0, "bytes_on_disk": 2_000_000, "items_reembedded": 7, "extra": {"files_failed": 0}}},
             {"system": "grep", "task_id": "acme__auth-1", "index_key": "g", "mode": "build",
              "report": {"seconds": 0.0, "bytes_on_disk": 0, "items_reembedded": None, "extra": {}}}]
    (run / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in index))
    score("r1", counter=CharCounter())
    return run


def edit_json(path, **changes):
    data = json.loads(path.read_text())
    data.update(changes)
    path.write_text(json.dumps(data))


def test_primary_comparisons_with_hand_computed_numbers(run_dir):
    result = report("r1", baseline="grep-fn", primary=PRIMARY, resamples=500)
    primary = {(c.system, c.metric): c for c in result.primary}
    assert sorted(primary) == [("cm-a", "mrr"), ("cm-a", "tokens_to_first"), ("cm-b", "mrr"), ("cm-b", "tokens_to_first")]
    a_mrr, a_tok = primary[("cm-a", "mrr")], primary[("cm-a", "tokens_to_first")]
    assert (a_mrr.n, a_mrr.baseline_mean, a_mrr.system_mean, a_mrr.diff) == (6, 0.5, 1.0, 0.5)
    assert a_mrr.test.p == pytest.approx(2 / 64)  # 6 positive differences, exact test
    assert (a_tok.n, a_tok.diff, a_tok.test.p) == (6, -10.0, pytest.approx(2 / 64))
    b_tok = primary[("cm-b", "tokens_to_first")]
    assert b_tok.n == 3 and b_tok.test.p == pytest.approx(2 / 8)  # paired only on the 3 tasks both found
    assert b_tok.found == {"both": 3, "system only": 0, "baseline only": 3, "neither": 0}
    assert primary[("cm-b", "mrr")].diff == 0.0
    # Holm over the 4 primary tests: p = 1/32, 1/32, 1/4, 1 -> 4/32, 4/32, 2/4, 1.
    assert [primary[k].p_holm for k in sorted(primary)] == pytest.approx([0.125, 0.125, 1.0, 0.5])
    text = result.report_path.read_text()
    assert "Holm correction over all 4 tests" in text and "| cm-a | function mrr | 6 | 0.500 | 1.000 |" in text
    assert "Primary systems: cm-a, cm-b (chosen with --primary)." in text
    assert "| cm-b | 3 | 0 | 3 | 0 |" in text  # found by both, system only, baseline only, neither


def test_main_tables_and_counts(run_dir):
    text = report("r1", baseline="grep-fn", primary=PRIMARY, resamples=500).report_path.read_text()
    assert "| grep | - | n/a | n/a | n/a | n/a | n/a |" in text  # file-granularity: n/a below file level, never 0
    assert "| cm-a | 6 | 1.000 [1.000, 1.000] |" in text
    assert "| grep | function | 6 | file-granularity system: 6 |" in text
    assert "Only 6 tasks: percentile bootstrap intervals are too narrow" in text
    assert "### Exploratory (raw p, no correction)" in text and "| grep | mrr | 6 |" in text
    assert "mrr @ IoU 0.3 | mrr @ IoU 0.5 | mrr @ IoU 0.7" in text
    assert "| cm-b | 5.0 | 5.0 | same as cm-a |" in text  # shared index costs are not repeated
    assert "| cm-a | 5.0 | 5.0 | 3.0 |" in text and "| 2.0 | 0.0 |" in text  # 2,000,000 bytes = 2.0 MB


def test_group_tables(run_dir):
    text = report("r1", baseline="grep-fn", primary=PRIMARY, resamples=500).report_path.read_text()
    assert "- language: all 6 tasks are 'python', so there is no table." in text
    assert "### By identifier in query" in text and "### By repo" in text and "### By issue date" in text
    assert "| before 2026-07-01 | 3 |" in text and "| on or after 2026-07-01 | 3 |" in text
    # cm-b finds acme__auth-1 and -2 but not -3: function MRR 0.667 over the 3 acme/auth tasks.
    assert "| acme/auth | 3 | 0.500 (3) | 1.000 (3) | 0.667 (3) |" in text


def test_warnings(run_dir):
    assert report("r1", baseline="grep-fn", primary=PRIMARY, resamples=500).warnings == []
    edit_json(run_dir / "score-meta.json", token_estimate=True)
    edit_json(run_dir / "meta.json", status="failed", sessions=[
        {"cmeval_git": {"sha": "a" * 40}, "machine": {"platform": "mac"}},
        {"cmeval_git": {"sha": "a" * 40}, "machine": {"platform": "windows"}}])
    warnings = report("r1", baseline="grep-fn", primary=PRIMARY, resamples=500).warnings
    assert any("ESTIMATES" in w for w in warnings) and any("not 'done'" in w for w in warnings)
    assert any("2 sessions" in w and "windows" in w for w in warnings)
    assert "## Warnings" in (run_dir / "report.md").read_text()


def test_refusals(run_dir, tmp_path):
    with pytest.raises(ReportError, match="pass --split dev"):
        report("r1", baseline="grep-fn", primary=PRIMARY, split="test")
    with pytest.raises(ReportError, match="baseline 'grep-fn-plus' is not a system"):
        report("r1")  # the default baseline; this run has only the naive grep-fn
    with pytest.raises(ReportError, match="baseline 'nope'"):
        report("r1", baseline="nope", primary=PRIMARY)
    with pytest.raises(ReportError, match="not a date"):
        report("r1", baseline="grep-fn", primary=PRIMARY, cutoff="July")
    (run_dir / "scores.jsonl").unlink()
    with pytest.raises(ReportError, match="not scored yet"):
        report("r1", baseline="grep-fn", primary=PRIMARY)


def test_the_primary_systems_are_an_explicit_list(run_dir):
    with pytest.raises(ReportError, match="no primary family fits"):
        report("r1", baseline="grep-fn")  # codemem systems with other names: never a silent empty family
    with pytest.raises(ReportError, match=r"primary systems \['grep'\]"):
        report("r1", baseline="grep-fn", primary=["cm-a", "grep"])  # grep has no function level
    result = report("r1", baseline="grep-fn", primary=["cm-b"], resamples=500)
    assert {c.system for c in result.primary} == {"cm-b"} and len(result.primary) == 2
    assert "Holm correction over all 2 tests" in result.report_path.read_text()


def test_a_file_level_baseline_has_no_primary_tests(run_dir):
    result = report("r1", baseline="grep", primary=PRIMARY, resamples=500)
    assert result.primary == [] and "n/a: the baseline grep has no function-level results" in result.report_path.read_text()


def test_same_inputs_give_the_same_report(run_dir):
    first = report("r1", baseline="grep-fn", primary=PRIMARY).report_path.read_text()
    rows = (run_dir / "scores.jsonl").read_text().splitlines()
    random.Random(0).shuffle(rows)
    (run_dir / "scores.jsonl").write_text("\n".join(rows) + "\n")
    assert report("r1", baseline="grep-fn", primary=PRIMARY).report_path.read_text() == first


def test_cli_report(run_dir, capsys):
    assert main(["report", "r1", "--baseline", "grep-fn", "--primary", "cm-a", "--primary", "cm-b"]) == 0
    out = capsys.readouterr().out
    assert "report.md: 6 tasks" in out and "Holm over 4 tests" in out and "cm-a" in out
    assert main(["report", "missing"]) == 1


# ---- F5 B1: the filter, the new groups, grep-only runs

# task -> gold_all_python, repo_py_files, code_lines_changed, n_gold_files (None: the tag is missing)
TAGS = {"acme__auth-1": (True, 999, 10, 1), "acme__auth-2": (True, 1000, 11, 2), "acme__auth-3": (True, 5000, 50, 1),
        "acme__web-4": (True, 5001, 51, 1), "acme__web-5": (False, None, 3, 3), "acme__web-6": (False, 20000, None, 1)}


@pytest.fixture
def tagged(run_dir):
    """The run of run_dir, with fresh-task tags on its tasks (the tasks file hash is updated)."""
    from dataclasses import replace

    from cmeval.tasks import load_tasks

    meta_path = run_dir / "meta.json"
    tasks_file = json.loads(meta_path.read_text())["tasks_file"]
    tagged_tasks = []
    for task in load_tasks(tasks_file):
        names = ("gold_all_python", "repo_py_files", "code_lines_changed", "n_gold_files")
        extra = {k: v for k, v in zip(names, TAGS[task.id]) if v is not None}
        tagged_tasks.append(replace(task, tags={**task.tags, **extra}))
    save_tasks(tasks_file, tagged_tasks)
    edit_json(meta_path, tasks_sha256=hashlib.sha256(open(tasks_file, "rb").read()).hexdigest())
    return run_dir


def test_parse_where():
    from cmeval.report import parse_where

    assert parse_where(["gold_all_python=true", "n_gold_files=2", "repo=Acme/Web", "x=False"]) == \
        [("gold_all_python", True), ("n_gold_files", 2), ("repo", "Acme/Web"), ("x", False)]
    assert parse_where(None) == []
    for bad in ("gold_all_python", "=true", "gold_all_python="):
        with pytest.raises(ReportError, match="KEY=VALUE"):
            parse_where([bad])


def test_the_filter_limits_every_table(tagged):
    result = report("r1", baseline="grep-fn", primary=PRIMARY, where=["gold_all_python=true"], resamples=500)
    assert (result.tasks_scored, result.left_out, result.filter) == (4, 2, "gold_all_python=true")
    assert result.warnings == []  # score-meta.json still has all 6 tasks: no false "score it again"
    assert {c.n for c in result.primary if c.metric == "mrr"} == {4}
    text = result.report_path.read_text()
    assert "- Filter: gold_all_python=true: 4 of 6 scored tasks (2 left out" in text
    assert "| cm-a | 4 | 1.000 [1.000, 1.000] |" in text and "4 tasks scored" in text
    assert "## Tasks left out by the filter" in text and "| left out | 2 | 0.500 (2) | 1.000 (2) |" in text
    assert "over all 6 scored tasks: the filter does not apply to them" in text


def test_many_conditions_and_text_values(tagged):
    result = report("r1", baseline="grep-fn", primary=PRIMARY, where=["repo=ACME/WEB", "gold_all_python=false"], resamples=500)
    assert (result.tasks_scored, result.left_out) == (2, 4)


def test_filter_refusals(tagged):
    with pytest.raises(ReportError, match="no scored task has \\['gold_python'\\]; known keys: .*gold_all_python"):
        report("r1", baseline="grep-fn", primary=PRIMARY, where=["gold_python=true"])
    with pytest.raises(ReportError, match="no scored task matches"):
        report("r1", baseline="grep-fn", primary=PRIMARY, where=["repo=acme/nope"])


def test_size_groups_in_natural_order(tagged):
    text = report("r1", baseline="grep-fn", primary=PRIMARY, resamples=500).report_path.read_text()
    section = text.split("### By repo size (Python files)")[1].split("###")[0]
    rows = ["| small (< 1,000) | 1 |", "| medium (1,000 to 5,000) | 2 |", "| large (> 5,000) | 2 |", "| unknown | 1 |"]
    assert [section.index(r) for r in rows] == sorted(section.index(r) for r in rows)  # natural order, unknown last
    section = text.split("### By fix size (changed code lines)")[1].split("###")[0]
    rows = ["| up to 10 | 2 |", "| 11 to 50 | 2 |", "| over 50 | 1 |", "| unknown | 1 |"]
    assert [section.index(r) for r in rows] == sorted(section.index(r) for r in rows)
    section = text.split("### By gold files")[1].split("###")[0]
    assert "| 1 | 4 |" in section and "| 2 or more | 2 |" in section
    assert "### By gold all Python" in text and "| false | 2 |" in text


def test_a_run_without_codemem_has_no_primary_tests(run_dir):
    meta = json.loads((run_dir / "meta.json").read_text())
    for system in meta["systems"]:
        system["adapter"] = "grep"  # a grep-only run, like the fresh grep baselines
    (run_dir / "meta.json").write_text(json.dumps(meta))
    result = report("r1", baseline="grep-fn", resamples=500)
    text = result.report_path.read_text()
    assert result.primary == [] and "No primary systems in this run (it has no codemem system)" in text
    assert "Holm correction over all 0 tests" not in text
    with pytest.raises(ReportError, match=r"primary systems \['cm-x'\]"):
        report("r1", baseline="grep-fn", primary=["cm-x"])  # an explicit list is still checked


def test_cli_report_with_a_filter(tagged, capsys):
    args = ["report", "r1", "--baseline", "grep-fn", "--primary", "cm-a", "--where", "gold_all_python=true"]
    assert main(args) == 0
    assert "4 tasks (filter gold_all_python=true; 2 tasks left out)" in capsys.readouterr().out
    assert main(["report", "r1", "--baseline", "grep-fn", "--where", "nope"]) == 1


def test_default_primary_picks_the_family_of_the_run():
    from cmeval.report import PRIMARY_FAMILIES, default_primary

    v3, mvp = PRIMARY_FAMILIES[0][1], PRIMARY_FAMILIES[1][1]
    assert default_primary(["grep-fn-plus", *v3, "cm3-full-v2-weights"], True)[1] == v3
    assert default_primary(["grep-fn-plus", *mvp], True)[1] == mvp  # an old MVP run reports as before
    assert default_primary([*mvp, *v3], True)[1] == v3  # the newest family first
    assert default_primary(["grep", "grep-fn-plus"], False) == ("none (no codemem system in this run)", ())
    with pytest.raises(ReportError, match="no primary family fits"):
        default_primary(["grep-fn-plus", "cm3-bm25", "cm-bm25", "cm-bm25-code"], True)  # no family complete


def test_primary_families_name_real_codemem_systems():
    from pathlib import Path

    from cmeval.report import PRIMARY_FAMILIES
    from cmeval.systems import load_systems

    configs = Path(__file__).parents[1] / "configs"
    for (label, family), config in zip(PRIMARY_FAMILIES, ("codemem-v3-full.toml", "baseline.toml")):
        specs = {spec.name: spec for spec in load_systems(configs / config)}
        for name in family:
            assert name in specs and specs[name].adapter == "codemem", (label, name)
