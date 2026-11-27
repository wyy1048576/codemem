"""The run sample: the seeded order, the easy-tier label pattern, the tasks that are run, and the files."""

import json

import pytest

from cmeval import e2e_screen
from cmeval.cli import main
from cmeval.generate import difficulty, tier
from cmeval.run_sample import EASY_PATTERN, SampleError, run_counts, run_sample
from cmeval.tasks import Fix, save_tasks


def _patch(files: int, lines: int) -> str:
    """A fix of `files` code files with `lines` added lines each."""
    parts = []
    for i in range(files):
        body = "".join(f"+x{n} = {n}\n" for n in range(lines))
        parts.append(f"diff --git a/pkg/m{i}.py b/pkg/m{i}.py\n--- a/pkg/m{i}.py\n+++ b/pkg/m{i}.py\n"
                     f"@@ -1 +1,{lines + 1} @@\n x = 0\n{body}")
    return "".join(parts)


SIZES = {"easy": _patch(1, 5), "medium": _patch(1, 30), "hard": _patch(3, 10), "large": _patch(6, 10)}


@pytest.fixture
def make(make_task):
    """A task of a repo, with a fix of one size: easy and medium (easy tier), hard (medium tier), large (hard
    tier)."""
    def build(repo: str, n: int, size: str, split: str = "test"):
        return make_task(id=f"{repo.replace('/', '__')}-{n}", repo=repo, split=split, patch=SIZES[size],
                         fix=Fix(pr_number=n), query=f"issue {n}")
    return build


def _screen(path, tasks, unfair=(), stale=()):
    """Two reads of each task: fair, except the ids in `unfair`. The ids in `stale` get another hash."""
    rows = []
    for task in tasks:
        fair = task.id not in unfair
        digest = "0" * 16 if task.id in stale else e2e_screen.content_hash(task)
        for read in (1, 2):
            rows.append({"id": task.id, "repo": task.repo, "difficulty": difficulty(task.patch), "read": read,
                         "reader": f"reader {read}", "fair": fair, "kinds": [] if fair else ["extra-cases"],
                         "deciding_assertions": "test_x", "reason": "because", "confidence": "high",
                         "rules": "screen-rules-v1", "content_hash": digest, "date": "2026-11-27"})
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def _prompts(path, ids):
    path.write_text("".join(json.dumps({"id": i, "level": level, "prompt": f"{level} text"}) + "\n"
                            for i in ids for level in ("L1", "L2")))
    return path


def _inputs(tmp_path, tasks, large=(), unfair=(), stale=(), prompted=None):
    first, second = tmp_path / "acme.jsonl", tmp_path / "acme-large.jsonl"
    save_tasks(first, tasks)
    save_tasks(second, list(large))
    screen = _screen(tmp_path / "screen.jsonl", [*tasks, *large], unfair, stale)
    prompts = _prompts(tmp_path / "vague.jsonl", [t.id for t in [*tasks, *large]] if prompted is None else prompted)
    facts = tmp_path / "facts.jsonl"
    facts.write_text("")
    return {"task_files": [first, second], "screens": [screen], "facts": facts, "prompts": [prompts]}


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _full_repo(make, repo="acme/a"):
    """10 easy-tier tasks (5 medium, 5 easy labels, 3 of them dev), 5 medium-tier tasks (1 dev), 5 hard."""
    tasks = [make(repo, i, "medium", "dev" if i == 0 else "test") for i in range(5)]
    tasks += [make(repo, 10 + i, "easy", "dev" if i < 2 else "test") for i in range(5)]
    tasks += [make(repo, 20 + i, "hard", "dev" if i == 0 else "test") for i in range(5)]
    large = [make(repo, 30 + i, "large") for i in range(5)]
    return tasks, large


def test_the_fixture_sizes_fall_in_their_tiers():
    assert [difficulty(SIZES[s]) for s in ("easy", "medium", "hard", "large")] == ["easy", "medium", "hard", "hard"]
    assert [tier(SIZES[s]) for s in ("easy", "medium", "hard", "large")] == ["easy", "easy", "medium", "hard"]


def test_same_inputs_and_seed_give_the_same_bytes(tmp_path, make):
    tasks, large = _full_repo(make)
    inputs = _inputs(tmp_path, tasks, large)
    a = run_sample(tmp_path / "a.jsonl", seed="s1", **inputs)
    b = run_sample(tmp_path / "b.jsonl", seed="s1", **inputs)
    assert a.written and b.written
    assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()
    # The order of the input tasks does not change the draw.
    save_tasks(inputs["task_files"][0], list(reversed(tasks)))
    run_sample(tmp_path / "c.jsonl", seed="s1", **inputs)
    assert (tmp_path / "c.jsonl").read_bytes() == (tmp_path / "a.jsonl").read_bytes()
    run_sample(tmp_path / "d.jsonl", seed="s2", **inputs)
    assert (tmp_path / "d.jsonl").read_bytes() != (tmp_path / "a.jsonl").read_bytes()


def test_the_rows_and_the_meta_file(tmp_path, make):
    tasks, large = _full_repo(make)
    inputs = _inputs(tmp_path, tasks, large)
    run_sample(tmp_path / "s.jsonl", seed="s1", command="cmeval e2e sample", **inputs)
    rows = _rows(tmp_path / "s.jsonl")
    assert list(rows[0]) == ["repo", "id", "tier", "label", "split", "number", "run", "has_prompts"]
    assert len(rows) == 20 and len({r["id"] for r in rows}) == 20
    for name, n in (("easy", 10), ("medium", 5), ("hard", 5)):
        assert [r["number"] for r in rows if r["tier"] == name] == list(range(1, n + 1))
    assert {name: sum(r["run"] for r in rows if r["tier"] == name) for name in ("easy", "medium", "hard")} == \
        {"easy": 6, "medium": 4, "hard": 4}
    meta = json.loads((tmp_path / "s.meta.json").read_text())
    assert meta["seed"] == "s1" and meta["command"] == "cmeval e2e sample" and meta["rows"] == 20
    assert meta["inputs"]["screens"][0]["sha256"] == e2e_screen.sha256_file(inputs["screens"][0])
    tiers = meta["repos"]["acme/a"]["tiers"]
    assert tiers["easy"] == {"fair": 10, "target": 6, "run": 6, "spare": 4, "test": 7, "dev": 3,
                             "labels": {"easy": 5, "medium": 5}}


def test_test_split_comes_before_dev_in_each_tier(tmp_path, make):
    tasks, large = _full_repo(make)
    run_sample(tmp_path / "s.jsonl", seed="s1", **_inputs(tmp_path, tasks, large))
    rows = _rows(tmp_path / "s.jsonl")
    medium = [r["split"] for r in rows if r["tier"] == "medium"]
    assert medium == ["test"] * 4 + ["dev"]
    for label in ("easy", "medium"):
        splits = [r["split"] for r in rows if r["tier"] == "easy" and r["label"] == label]
        assert splits == sorted(splits, key=lambda s: s != "test")


def test_the_easy_tier_follows_the_label_pattern(tmp_path, make):
    tasks, large = _full_repo(make)
    run_sample(tmp_path / "s.jsonl", seed="s1", **_inputs(tmp_path, tasks, large))
    labels = [r["label"] for r in _rows(tmp_path / "s.jsonl") if r["tier"] == "easy"]
    assert labels[:6] == list(EASY_PATTERN) == ["medium", "easy", "medium", "medium", "easy", "medium"]
    # The pattern starts again after 6: 7 is medium (the last one), 8 to 10 are easy.
    assert labels[6:] == ["medium", "easy", "easy", "easy"]


def test_a_label_that_runs_out_is_filled_from_the_other(tmp_path, make):
    tasks = [make("acme/a", i, "medium") for i in range(2)] + [make("acme/a", 10 + i, "easy") for i in range(5)]
    result = run_sample(tmp_path / "s.jsonl", seed="s1", **_inputs(tmp_path, tasks))
    labels = [r["label"] for r in _rows(tmp_path / "s.jsonl") if r["tier"] == "easy"]
    assert labels == ["medium", "easy", "medium", "easy", "easy", "easy", "easy"]
    assert any("numbers 4, 6 have the label easy" in n for n in result.samples[0].notes)


def test_medium_fills_up_when_hard_is_short():
    assert run_counts({"easy": 10, "medium": 10, "hard": 2}) == {"easy": 6, "medium": 6, "hard": 2}
    assert run_counts({"easy": 10, "medium": 10, "hard": 0}) == {"easy": 6, "medium": 8, "hard": 0}
    assert run_counts({"easy": 10, "medium": 10, "hard": 9}) == {"easy": 6, "medium": 4, "hard": 4}


def test_medium_fill_in_the_file(tmp_path, make):
    tasks = [make("acme/a", 20 + i, "hard") for i in range(9)]
    large = [make("acme/a", 40, "large")]
    result = run_sample(tmp_path / "s.jsonl", seed="s1", **_inputs(tmp_path, tasks, large))
    rows = _rows(tmp_path / "s.jsonl")
    assert sum(r["run"] for r in rows if r["tier"] == "medium") == 7
    assert sum(r["run"] for r in rows if r["tier"] == "hard") == 1
    assert any("the target is 7" in n for n in result.samples[0].notes)


def test_a_short_repo_runs_all_it_has(tmp_path, make):
    tasks = [make("acme/b", 1, "medium"), make("acme/b", 2, "easy"), make("acme/b", 3, "hard")]
    result = run_sample(tmp_path / "s.jsonl", seed="s1", **_inputs(tmp_path, tasks))
    rows = _rows(tmp_path / "s.jsonl")
    assert len(rows) == 3 and all(r["run"] for r in rows)
    counts = result.samples[0].counts()["tiers"]
    assert counts["medium"]["target"] == 8 and counts["hard"]["fair"] == 0
    assert any("hard tier: 0 fair tasks" in n for n in result.samples[0].notes)


def test_unfair_and_stale_tasks_are_left_out(tmp_path, make):
    tasks, large = _full_repo(make)
    unfair, stale = tasks[1].id, tasks[6].id
    result = run_sample(tmp_path / "s.jsonl", seed="s1", **_inputs(tmp_path, tasks, large, [unfair], [stale]))
    ids = {r["id"] for r in _rows(tmp_path / "s.jsonl")}
    assert len(ids) == 18 and unfair not in ids and stale not in ids
    assert result.stale_reads == 2


def test_a_new_fact_makes_the_reads_stale(tmp_path, make):
    tasks, large = _full_repo(make)
    inputs = _inputs(tmp_path, tasks, large)
    inputs["facts"].write_text(json.dumps({"id": tasks[0].id, "fact": "checked", "date": "2026-11-27",
                                           "source": "check"}) + "\n")
    run_sample(tmp_path / "s.jsonl", seed="s1", **inputs)
    assert tasks[0].id not in {r["id"] for r in _rows(tmp_path / "s.jsonl")}


def test_repos_without_prompts_and_the_repo_filter(tmp_path, make):
    tasks_a, large_a = _full_repo(make, "acme/a")
    tasks_b = [make("other/b", 100 + i, "easy") for i in range(3)]
    inputs = _inputs(tmp_path, [*tasks_a, *tasks_b], large_a, prompted=[t.id for t in [*tasks_a, *large_a]])
    result = run_sample(tmp_path / "s.jsonl", seed="s1", **inputs)
    assert [s.repo for s in result.samples] == ["acme/a", "other/b"]
    rows = _rows(tmp_path / "s.jsonl")
    assert all(r["has_prompts"] == (r["repo"] == "acme/a") for r in rows)
    assert len(result.samples[1].counts()["run_without_prompts"]) == 3
    only = run_sample(tmp_path / "b.jsonl", seed="s1", repos=["B"], **inputs)
    assert [s.repo for s in only.samples] == ["other/b"]
    # The draw of a repo does not depend on the other repos.
    assert _rows(tmp_path / "b.jsonl") == [r for r in rows if r["repo"] == "other/b"]
    with pytest.raises(SampleError, match="no fair task"):
        run_sample(tmp_path / "x.jsonl", seed="s1", repos=["nope"], **inputs)


def test_a_written_sample_is_not_replaced_without_force(tmp_path, make):
    tasks, large = _full_repo(make)
    inputs = _inputs(tmp_path, tasks, large)
    out = tmp_path / "s.jsonl"
    run_sample(out, seed="s1", **inputs)
    meta = (tmp_path / "s.meta.json").read_text()
    assert not run_sample(out, seed="s1", **inputs).written  # the same sample: nothing is written
    assert (tmp_path / "s.meta.json").read_text() == meta
    with pytest.raises(SampleError, match="holds another sample"):
        run_sample(out, seed="s2", **inputs)
    assert run_sample(out, seed="s2", force=True, **inputs).written


def test_the_command(tmp_path, make, capsys):
    tasks, large = _full_repo(make)
    inputs = _inputs(tmp_path, tasks, large)
    argv = ["e2e", "sample", "--seed", "s1", "--out", str(tmp_path / "s.jsonl"), "--facts", str(inputs["facts"]),
            "--screen", str(inputs["screens"][0]), "--prompts", str(inputs["prompts"][0])]
    for path in inputs["task_files"]:
        argv += ["--tasks", str(path)]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "acme/a" in out and "run tasks without L1 and L2: 0" in out and "20 tasks" in out
    assert main(argv[:3] + ["s2"] + argv[4:]) == 1
    assert "holds another sample" in capsys.readouterr().err
