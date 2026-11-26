"""The candidate pool of a repo, the admission sample and the larger validation samples."""

import hashlib
import random
from pathlib import Path

from cmeval import generate as gen
from cmeval.tasks import load_tasks

TASKS = Path(__file__).resolve().parents[1] / "tasks"
RECIPE = gen.Recipe(name="r", repo="acme/r", base_image="i", test="t {files} {junit}", test_files=("tests/**/test_*.py",))


def _patch(n_files: int, n_lines: int) -> str:
    out = ""
    for i in range(n_files):
        lines = "".join(f"+x{j}\n" for j in range(n_lines // n_files))
        out += f"diff --git a/src/f{i}.py b/src/f{i}.py\n--- a/src/f{i}.py\n+++ b/src/f{i}.py\n@@ -1 +1,{n_lines} @@\n{lines}"
    return out


TEST_PATCH = "diff --git a/tests/test_a.py b/tests/test_a.py\n--- a/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -1 +1 @@\n+t\n"
SIZES = {"easy": (1, 5), "medium": (2, 40), "hard": (4, 150)}


def _tasks(make_task, per_level=12):
    tasks = []
    for level, (files, lines) in SIZES.items():
        for i in range(per_level):
            tasks.append(make_task(id=f"acme__r-{level}{i:02d}", repo="acme/r", patch=_patch(files, lines), test_patch=TEST_PATCH))
    return tasks


def _old_admission_sample(recipe, tasks, n=10, seed=None):
    """admission_sample as it was before the pool filter (2026-11-26)."""
    pool = {"easy": [], "medium": [], "hard": []}
    for task in sorted(tasks, key=lambda t: t.id):
        if task.repo == recipe.repo and task.test_patch and gen.task_test_files(recipe, task):
            pool[gen.difficulty(task.patch)].append(task)
    rng = random.Random(seed or f"admission-{recipe.name}-1")
    chosen = []
    for level, share in gen.ADMISSION_MIX:
        want = round(share * n / gen.ADMISSION_N)
        chosen += rng.sample(pool[level], min(want, len(pool[level])))
    return chosen


def test_the_admission_sample_is_unchanged_without_tagged_tasks(make_task):
    tasks = _tasks(make_task)
    assert [gen.difficulty(t.patch) for t in tasks[::12]] == ["easy", "medium", "hard"]
    for seed in (None, "s2"):
        assert gen.admission_sample(RECIPE, tasks, seed=seed) == _old_admission_sample(RECIPE, tasks, seed=seed)
    # An empty dependency_needed list (a task that resplit changed) stays in the pool.
    tagged = [make_task(**{**t.__dict__, "tags": {**t.tags, "dependency_needed": []}}) for t in tasks]
    assert gen.admission_sample(RECIPE, tagged) == _old_admission_sample(RECIPE, tagged)


def test_a_task_that_needs_a_dependency_leaves_the_pool(make_task):
    tasks = _tasks(make_task)
    first = gen.admission_sample(RECIPE, tasks)
    out = first[0]
    tags = {**out.tags, "dependency_needed": [{"file": "uv.lock", "package": "x", "old": "1", "new": "2", "kind": "raised"}]}
    tasks = [make_task(**{**t.__dict__, "tags": tags}) if t.id == out.id else t for t in tasks]
    pool, left = gen.candidates(RECIPE, tasks)
    assert [t.id for t in left] == [out.id] and out.id not in {t.id for level in pool.values() for t in level}
    second = gen.admission_sample(RECIPE, tasks)
    # Only the removed task is replaced, by another task of its level; the other nine stay.
    assert out.id not in {t.id for t in second} and len(second) == 10
    gone, came = {t.id for t in first} - {t.id for t in second}, [t for t in second if t.id not in {f.id for f in first}]
    assert gone == {out.id} and len(came) == 1 and gen.difficulty(came[0].patch) == gen.difficulty(out.patch)
    before = gen.sample(RECIPE, _tasks(make_task), 20)
    drawn = gen.sample(RECIPE, tasks, 20)
    assert out.id not in {t.id for t in drawn.tasks} and [t.id for t in drawn.left_out] == [out.id]
    assert len({t.id for t in before.tasks} - {t.id for t in drawn.tasks}) == 1


def test_a_sample_holds_the_admission_sample_and_fills_each_level(make_task):
    tasks = _tasks(make_task)
    drawn = gen.sample(RECIPE, tasks, 20)
    ids = [t.id for t in drawn.tasks]
    assert {t.id for t in gen.admission_sample(RECIPE, tasks)} <= set(ids)
    assert ids == [t.id for t in tasks if t.id in set(ids)]  # the order of the task file
    assert {level: v["chosen"] for level, v in drawn.levels.items()} == {"easy": 6, "medium": 8, "hard": 6}
    assert gen.sample(RECIPE, tasks, 20).tasks == drawn.tasks  # a fixed seed
    assert gen.sample(RECIPE, tasks, 20, seed="other").tasks != drawn.tasks
    # A level with a short pool gives what it has.
    assert gen.sample(RECIPE, tasks, 60).levels["medium"] == {"pool": 12, "want": 24, "chosen": 12}


def _ids_digest(tasks):
    return hashlib.sha256(" ".join(t.id for t in tasks).encode()).hexdigest()[:16]


def test_the_sample_gives_the_b7_draw_of_2026_11_26():
    # ~/.cmeval/tasks/b7-pandas-100.jsonl and b7-playwright-60.jsonl, drawn by a script on that day
    # from these task files. The digest is of their ids in file order.
    pandas = gen.sample(gen.load_recipe("pandas"), load_tasks(TASKS / "fresh-v1.jsonl"), 100)
    assert len(pandas.tasks) == 100 and _ids_digest(pandas.tasks) == "79cbacc306f1517b"
    playwright = gen.sample(gen.load_recipe("playwright"), load_tasks(TASKS / "fresh-ts-v1.jsonl"), 60)
    assert len(playwright.tasks) == 60 and _ids_digest(playwright.tasks) == "b971419ccb7fe571"
