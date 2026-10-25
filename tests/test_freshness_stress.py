"""The freshness promise under load: an agent saves and searches at random moments.

A slow fake model (4 ms per text) and occasional big files make embedding backlogs, so saves, the
background writer and searches overlap in many ways. Every search must:
- return within its limit (plus at most one small model call);
- include the newest save, unless it says that files are pending or that it couldn't confirm it
  had seen every save;
- say "complete" only when the newest save's chunk is no longer queued.

`get_chunk` must show the newest code, and at the end the index must equal a fresh build.
`CODEMEM_STRESS_SEEDS=20 uv run pytest tests/test_freshness_stress.py` runs more scripts.
"""

import os
import random
import time

import pytest

from codemem.embedder import make_embedder
from codemem.search import search
from codemem.service import CodememService

SEEDS = range(int(os.environ.get("CODEMEM_STRESS_SEEDS", "2")))
LIMIT_S = 0.8


class _SlowModel:
    """The fake model, slowed per text."""

    def __init__(self, inner, per_text):
        self.inner, self.per_text = inner, per_text

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def embed_documents(self, texts):
        time.sleep(self.per_text * len(texts))
        return self.inner.embed_documents(texts)


def _wait_for(pred, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("seed", SEEDS)
def test_random_saves_and_searches_keep_the_freshness_promise(sample_repo, tmp_path, monkeypatch, seed):
    monkeypatch.setenv("CODEMEM_MODEL", "fake:64")
    rng = random.Random(seed)
    (sample_repo / ".codemem.toml").write_text(f"catchup_budget_ms = {int(LIMIT_S * 1000)}\n")
    svc = CodememService(
        sample_repo, index_dir=tmp_path / "idx", embedder_factory=lambda m, c: _SlowModel(make_embedder(m, c), 0.004)
    )
    checked = 0
    try:
        svc.update()
        svc.start(prewarm=False)
        time.sleep(0.3)
        newest = None  # (a word no other code has, the chunk that holds it)
        for step in range(30):
            if rng.random() < 0.15:  # a big file: an embedding backlog
                n = rng.randint(50, 250)
                bulk = "\n\n".join(f"def bulk_{step}_{i}(x):\n    return x + {i}\n" for i in range(n))
                (sample_repo / "auth" / f"bulk_{step % 3}.py").write_text(bulk)
            else:  # an edit: a file gets one function with a new word in it
                word, name = f"word_{seed}_{step}", f"edit_{rng.randint(0, 3)}.py"
                (sample_repo / "auth" / name).write_text(f"def fn_{step}(x):\n    {word} = x\n    return {word}\n")
                newest = (word, f"auth/{name}::fn_{step}")
            time.sleep(rng.choice([0, 0, 0, 0.05, 0.2, 0.6]))
            if newest is None or rng.random() < 0.3:
                continue
            word, key = newest
            t = time.monotonic()
            fresh = svc.search(word, k=5).freshness
            took = time.monotonic() - t
            assert took < LIMIT_S + 0.7, f"step {step}: the search took {took:.2f} s"
            if fresh.pending_files or fresh.unconfirmed:
                continue  # it said the newest save may not be in: allowed
            hits = search(svc.store, word, svc.config, k=1, signals=["bm25"], embedder_factory=svc.embedder_factory)
            assert hits.results and hits.results[0].key == key, f"step {step}: {word} is not in the index"
            if fresh.complete:
                chunk = svc.store.get_chunk_by_key(key)
                assert not svc.store.dirty_seqs([chunk.chunk_id]), f"step {step}: complete, but {key} is queued"
            d = svc.get_chunk(key)
            assert d is not None and word in d["code"], f"step {step}: get_chunk shows old code for {key}"
            checked += 1
        assert checked >= 5, "too few searches were checked to mean anything"
        # The last saves may still be in the watcher's quiet period: catch up as a search does,
        # with time to embed everything, then compare with a fresh build.
        assert svc.catch_up(budget=60).complete
        assert _wait_for(lambda: svc.store.dirty_count() == 0, timeout=60)
        assert svc.indexer.verify() == []
    finally:
        svc.close()
