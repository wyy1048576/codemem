import csv
import hashlib
import json

import pytest

from cmeval.cli import main
from cmeval.metrics.tokens import EstimateCounter
from cmeval.paths import runs_dir
from cmeval.retriever import Hit
from cmeval.score import ScoreError, score
from cmeval.tasks import Fix, Gold, Span, save_tasks


class WordCounter:
    """Tokens = characters, so the hand-computed numbers are easy to follow."""
    name = "chars"
    estimate = False

    def count(self, texts):
        return [len(t) for t in texts]


@pytest.fixture
def run_dir(tmp_path, make_task):
    gold = Gold(files=["auth/sessions.py"],
                classes=[Span("auth/sessions.py", 10, 80, "SessionManager")],
                functions=[Span("auth/sessions.py", 33, 34, "SessionManager.revoke_session")])
    main_task = make_task(gold=gold)
    partial = make_task(id="acme__auth-43", fix=Fix(pr_number=43), gold=gold, tags={"partial_labels": True})
    no_fn = make_task(id="acme__auth-44", fix=Fix(pr_number=44), gold=Gold(files=["auth/sessions.py"]))
    tasks_file = tmp_path / "tasks.jsonl"
    save_tasks(tasks_file, [main_task, partial, no_fn])

    run = runs_dir() / "r1"
    run.mkdir(parents=True)
    meta = {"status": "done", "k": 50, "tasks_file": str(tasks_file), "tasks_sha256": hashlib.sha256(tasks_file.read_bytes()).hexdigest(),
            "systems": [{"name": "line-sys", "granularity": "line", "index_key": "k1"},
                        {"name": "file-sys", "granularity": "file", "index_key": "k2"}]}
    (run / "meta.json").write_text(json.dumps(meta))
    line_hits = [Hit("auth/users.py", 1, 5, text="aaaa"),  # 4 tokens, wrong file
                 Hit("auth/sessions.py", 1, 200, text="bb"),  # 2 tokens; class IoU 71/200 = 0.355
                 Hit("auth/sessions.py", 33, 34, text="ccc")]  # 3 tokens; the gold function
    with (run / "line-sys.jsonl").open("w") as f:
        for task_id, ms in (("acme__auth-42", 10.0), ("acme__auth-43", 30.0), ("acme__auth-44", 20.0)):
            f.write(json.dumps({"task_id": task_id, "commit": "x", "search_ms": ms, "hits": [h.to_dict() for h in line_hits]}) + "\n")
    with (run / "file-sys.jsonl").open("w") as f:
        for task_id in ("acme__auth-42", "acme__auth-43", "acme__auth-44"):
            f.write(json.dumps({"task_id": task_id, "commit": "x", "search_ms": 5.0,
                                "hits": [Hit("auth/sessions.py", text="dddd").to_dict()]}) + "\n")
    index = [{"system": "line-sys", "index_key": "k1", "mode": "build", "report": {"seconds": 4.0, "bytes_on_disk": 9, "items_reembedded": 5, "extra": {}}},
             {"system": "file-sys", "index_key": "k2", "mode": "build", "report": {"seconds": 0.0, "bytes_on_disk": 0, "items_reembedded": None, "extra": {}}}]
    (run / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in index))
    return run, tasks_file


def rows_for(run, **match):
    rows = [json.loads(l) for l in (run / "scores.jsonl").read_text().splitlines()]
    return {r["metric"]: r["value"] for r in rows if all(r[k] == v for k, v in match.items())}


def test_scores_match_hand_computed_numbers(run_dir):
    run, _ = run_dir
    summary = score("r1", counter=WordCounter())
    main = dict(task_id="acme__auth-42", system="line-sys")
    file_level = rows_for(run, **main, level="file")
    assert file_level["mrr"] == 0.5  # users.py, then sessions.py: rank 2 in the file list
    assert (file_level["recall@1"], file_level["recall@5"]) == (0.0, 1.0)
    fn = rows_for(run, **main, level="function", iou=0.5)
    assert fn["mrr"] == pytest.approx(1 / 3) and fn["tokens_to_first"] == 9.0  # 4 + 2 + 3
    assert fn["recall@budget500"] == 1.0
    assert rows_for(run, **main, level="class", iou=0.5)["mrr"] == pytest.approx(1 / 3)
    assert rows_for(run, **main, level="class", iou=0.3)["mrr"] == 0.5  # the 1-200 hit matches at IoU 0.3
    assert summary.rows > 0 and summary.counter == "chars"


def test_exclusions_are_rows_not_zeros(run_dir):
    run, _ = run_dir
    score("r1", counter=WordCounter())
    assert rows_for(run, task_id="acme__auth-42", system="file-sys", level="function", iou=0.5) == {"excluded": "file-granularity system"}
    assert rows_for(run, task_id="acme__auth-43", system="line-sys", level="class", iou=0.5) == {"excluded": "partial labels"}
    assert rows_for(run, task_id="acme__auth-44", system="line-sys", level="function", iou=0.5) == {"excluded": "no gold at this level"}
    assert rows_for(run, task_id="acme__auth-42", system="file-sys", level="file")["mrr"] == 1.0


def test_summary_and_latency(run_dir):
    run, _ = run_dir
    score("r1", counter=WordCounter())
    rows = list(csv.DictReader((run / "summary.csv").open()))
    get = {(r["system"], r["level"], r["iou"], r["metric"]): r for r in rows}
    fn_mrr = get[("line-sys", "function", "0.5", "mrr")]
    assert float(fn_mrr["mean"]) == pytest.approx(1 / 3) and (fn_mrr["n"], fn_mrr["n_excluded"]) == ("1", "2")
    assert float(get[("line-sys", "-", "", "search_ms_median")]["mean"]) == 20.0
    assert float(get[("line-sys", "-", "", "build_seconds_mean")]["mean"]) == 4.0
    assert float(get[("line-sys", "function", "0.5", "not_found_share")]["mean"]) == 0.0
    meta = json.loads((run / "score-meta.json").read_text())
    assert meta["ious"] == [0.5, 0.3, 0.7] and meta["token_estimate"] is False


def test_changed_tasks_file_is_refused(run_dir):
    run, tasks_file = run_dir
    tasks_file.write_text(tasks_file.read_text() + "\n")
    with pytest.raises(ScoreError, match="changed since the run"):
        score("r1", counter=WordCounter())
    with pytest.raises(ScoreError, match="no run folder"):
        score("nope", counter=WordCounter())


def test_cli_score(run_dir, capsys):
    assert main(["score", "r1", "--tokens", "estimate"]) == 0
    out = capsys.readouterr().out
    assert "ESTIMATES" in out and "line-sys" in out and "file-sys" in out
    assert main(["score", "missing-run", "--tokens", "estimate"]) == 1


def test_estimate_counter_marks_meta(run_dir):
    run, _ = run_dir
    summary = score("r1", counter=EstimateCounter())
    assert summary.estimate is True and json.loads((run / "score-meta.json").read_text())["token_estimate"] is True


# ---- review fixes


def test_only_tasks_every_system_finished_are_scored(run_dir):
    run, _ = run_dir
    lines = (run / "file-sys.jsonl").read_text().splitlines()
    (run / "file-sys.jsonl").write_text(lines[0] + "\n")  # file-sys stopped after one task
    meta = json.loads((run / "meta.json").read_text())
    meta["status"] = "failed"
    (run / "meta.json").write_text(json.dumps(meta))
    warnings = []
    summary = score("r1", counter=WordCounter(), warn=warnings.append)
    assert summary.tasks_scored == 1
    assert any("not 'done'" in w for w in warnings) and any("line-sys: 2 tasks left out" in w for w in warnings)
    assert {json.loads(l)["task_id"] for l in (run / "scores.jsonl").read_text().splitlines()} == {"acme__auth-42"}


def test_k_values_follow_the_run(run_dir):
    run, _ = run_dir
    meta = json.loads((run / "meta.json").read_text())
    meta["k"] = 10
    (run / "meta.json").write_text(json.dumps(meta))
    score("r1", counter=WordCounter())
    metrics = rows_for(run, task_id="acme__auth-42", system="line-sys", level="file")
    assert "recall@10" in metrics and "recall@20" not in metrics and "precision@50" not in metrics


def test_iou_thresholds_are_checked(run_dir):
    run, _ = run_dir
    score("r1", counter=WordCounter(), ious=(0.3, 0.3))
    meta = json.loads((run / "score-meta.json").read_text())
    assert meta["ious"] == [0.5, 0.3]  # main threshold added, duplicate removed
    with pytest.raises(ScoreError, match=r"\(0, 1\]"):
        score("r1", counter=WordCounter(), ious=(0.0,))


def test_bad_run_files_are_a_score_error(run_dir):
    run, _ = run_dir
    (run / "line-sys.jsonl").write_text((run / "line-sys.jsonl").read_text() + '{"task_id": "cut-of\n')
    with pytest.raises(ScoreError, match="line-sys.jsonl:4: not valid JSON"):
        score("r1", counter=WordCounter())
