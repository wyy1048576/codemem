import hashlib
import json

import pytest
from conftest import REMOTE_REPO

from cmeval.cli import main
from cmeval.compare import CompareError, compare, in_code
from cmeval.paths import runs_dir
from cmeval.retriever import Hit
from cmeval.score import score
from cmeval.tasks import Fix, save_tasks

GOLD = Hit("auth/sessions.py", 33, 34, text="g" * 10)  # the default task's gold function


class CharCounter:
    """Tokens = characters, so token numbers are easy to set."""
    name = "chars"
    estimate = False

    def count(self, texts):
        return [len(t) for t in texts]


def ranked(paths_scores, text="t" * 10):
    return [Hit(path, 1, 5, score=s, text=text) for path, s in paths_scores]


def base_hits():
    """12 hits that never match gold: f0.py has score 1.00, f1.py 0.99, ... f11.py 0.89."""
    return [(f"f{i}.py", round(1 - i * 0.01, 4)) for i in range(12)]


@pytest.fixture
def make_run(tmp_path, make_task):
    tasks_file = tmp_path / "tasks.jsonl"
    save_tasks(tasks_file, [make_task(), make_task(id="acme__auth-43", fix=Fix(pr_number=43))])

    def make(name, mode, hits_by_task):
        run = runs_dir() / name
        run.mkdir(parents=True)
        meta = {"status": "done", "k": 50, "index_mode": mode, "tasks_file": str(tasks_file),
                "tasks_sha256": hashlib.sha256(tasks_file.read_bytes()).hexdigest(),
                "systems": [{"name": "cm", "granularity": "line", "index_key": "k1"}]}
        (run / "meta.json").write_text(json.dumps(meta))
        (run / "index.jsonl").write_text("")
        with (run / "cm.jsonl").open("w") as f:
            for task_id, hits in hits_by_task.items():
                f.write(json.dumps({"task_id": task_id, "commit": "c" * 40, "search_ms": 1.0,
                                    "hits": [h.to_dict() for h in hits]}) + "\n")
        score(name, counter=CharCounter())
        return run

    return make


def no_stale(repo, commit, hit):
    return not hit["path"].startswith("gone")


def both_tasks(hits_42, hits_43=None):
    return {"acme__auth-42": hits_42, "acme__auth-43": hits_43 if hits_43 is not None else ranked(base_hits())}


def test_same_locations_pass_even_with_other_texts(make_run):
    make_run("up", "update", both_tasks(ranked(base_hits())))
    make_run("re", "rebuild", both_tasks(ranked(base_hits(), text="u" * 10)))  # card ids differ, places do not
    result = compare("up", "re", exists=no_stale)
    assert result.passed and result.systems[0].same_top == 2
    report = result.report_path.read_text()
    assert result.report_path.name == "compare-re.md" and "## Result: PASS" in report
    assert "index mode update" in report and "index mode rebuild" in report


def test_a_swap_at_rank_10_fails_and_is_marked_as_a_near_tie(make_run):
    swapped = base_hits()
    swapped[9], swapped[10] = ("f10.py", 0.91), ("f9.py", 0.9099)  # GPU rounding swaps two almost equal hits
    make_run("up", "update", both_tasks(ranked(base_hits())))
    make_run("re", "rebuild", both_tasks(ranked(swapped)))
    result = compare("up", "re", exists=no_stale)
    cm = result.systems[0]
    assert not result.passed and cm.same_top == 1 and cm.share_same_top == 0.5  # 1 of 2 tasks
    hits = {h["path"]: h for h in cm.differences[0]["hits"]}
    assert hits["f9.py"]["only_in"] == "a" and (hits["f9.py"]["rank_a"], hits["f9.py"]["rank_b"]) == (10, 11)
    assert hits["f9.py"]["hint"] == "near tie"  # 0.9099 vs. 0.91 at rank 10 in B
    assert hits["f10.py"]["hint"] == "check"  # 0.90 vs. 0.91 in A: a gap of 1.1%
    assert "| A | `f9.py:1-5` |" in result.report_path.read_text()


def test_a_hit_at_code_that_is_gone_is_marked_stale(make_run):
    stale = base_hits()
    stale[3] = ("gone.py", 0.97)  # a deleted file that an update forgot to remove
    make_run("up", "update", both_tasks(ranked(stale)))
    make_run("re", "rebuild", both_tasks(ranked(base_hits())))
    hits = {h["path"]: h for h in compare("up", "re", exists=no_stale).systems[0].differences[0]["hits"]}
    assert hits["gone.py"]["hint"] == "stale" and hits["gone.py"]["rank_b"] is None
    assert hits["f3.py"]["hint"] == "check"  # in B's top 10 and nowhere in A


def test_metric_means_over_the_limit(make_run):
    gold_third = ranked(base_hits()[:2]) + [GOLD] + ranked(base_hits()[2:9])
    gold_first = [GOLD] + ranked(base_hits()[:9])
    make_run("up", "update", both_tasks(gold_third, gold_third))
    make_run("re", "rebuild", both_tasks(gold_first, gold_first))
    cm = compare("up", "re", exists=no_stale).systems[0]
    assert cm.same_top == 2  # same top-10 set, other order
    over = {(d["level"], d["iou"], d["metric"]): d for d in cm.metric_diffs}
    assert over[("function", 0.5, "mrr")]["diff"] == pytest.approx(1 - 1 / 3)
    assert over[("function", 0.5, "tokens_to_first")]["limit"] == "1% (relative)"  # 30 vs. 10 tokens
    assert not cm.passed


def test_token_counts_use_a_relative_limit(make_run):
    def gold_after(text):
        return ranked(base_hits()[:9], text=text) + [GOLD]  # tokens to first = 9 * len(text) + 10

    make_run("up", "update", both_tasks(gold_after("t" * 100), gold_after("t" * 100)))  # 910 tokens
    make_run("re", "rebuild", both_tasks(gold_after("t" * 100 + "1"), gold_after("t" * 100 + "1")))  # 919: 0.98%
    cm = compare("up", "re", exists=no_stale).systems[0]
    assert cm.passed and cm.largest_relative_diff == pytest.approx(9 / 919)


def test_runs_that_cannot_be_compared(make_run):
    make_run("up", "update", both_tasks(ranked(base_hits())))
    other = runs_dir() / "unscored"
    other.mkdir(parents=True)
    meta = json.loads((runs_dir() / "up" / "meta.json").read_text())
    (other / "meta.json").write_text(json.dumps(meta))
    (other / "cm.jsonl").write_text("")
    with pytest.raises(CompareError, match="not scored yet"):
        compare("up", "unscored")
    make_run("re", "rebuild", both_tasks(ranked(base_hits())))
    meta_re = json.loads((runs_dir() / "re" / "meta.json").read_text())
    meta_re["systems"][0]["name"] = "renamed"
    (runs_dir() / "re" / "meta.json").write_text(json.dumps(meta_re))
    with pytest.raises(CompareError, match="different systems"):
        compare("up", "re")


def test_in_code_reads_the_commit(remote):
    sha = remote.shas[-1]  # app.py is one line: "VERSION = 3"
    assert in_code(REMOTE_REPO, sha, {"path": "app.py", "start_line": 1, "end_line": 1})
    assert not in_code(REMOTE_REPO, sha, {"path": "app.py", "start_line": 1, "end_line": 2})  # past the end
    assert not in_code(REMOTE_REPO, sha, {"path": "gone.py", "start_line": 1, "end_line": 1})
    assert in_code(REMOTE_REPO, sha, {"path": "app.py"})  # a file-level hit


def test_cli_compare(make_run, capsys):
    make_run("up", "update", both_tasks(ranked(base_hits())))
    make_run("re", "rebuild", both_tasks(ranked(base_hits())))
    assert main(["compare", "up", "re"]) == 0
    out = capsys.readouterr().out
    assert "update vs. rebuild check: PASS" in out and "compare-re.md" in out
    assert main(["compare", "up", "missing"]) == 1
