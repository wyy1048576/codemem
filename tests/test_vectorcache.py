"""The machine-wide vector cache: keyed reads, last use, the size cap, the import of a cache file
in the row format, and what the indexer sees of all that."""

import os
import sqlite3
import subprocess
import sys
import threading
import time

import numpy as np
import pytest

from codemem import vectorcache
from codemem.config import Config, config_from_dict
from codemem.indexer import Indexer
from codemem.render import format_status
from codemem.schema import text_hash
from codemem.service import CodememService
from codemem.store import Store
from codemem.vectorcache import CACHE_FILE, ROW_FORMAT_FILE, VectorCache, machine_cache

DAY = 86400
KEY = "model-a|doc"


@pytest.fixture
def clock(monkeypatch):
    """The cache's clock, as a one-item list the test moves forward."""
    now = [1_800_000_000 // DAY * DAY + 3600]  # an hour into a day
    monkeypatch.setattr(vectorcache, "_now", lambda: now[0])
    return now


def _hashes(tag, n):
    return [text_hash(f"{tag} {i}") for i in range(n)]


def _vecs(n, dim, seed=0):
    return np.random.default_rng(seed).standard_normal((n, dim), dtype=np.float32)


def _put(cache, embedder, hashes, vecs, batch=200):
    for i in range(0, len(hashes), batch):
        cache.put_many(embedder, hashes[i : i + batch], vecs[i : i + batch])


def _raw(path):
    return sqlite3.connect(path, isolation_level=None)


def _gone(cache, embedder, hashes):
    """Positions in `hashes` of what the cache does not hold (a read: it marks nothing as used)."""
    return [i for i, found in enumerate(cache.fetch(embedder, hashes)[1]) if not found]


def _stamps(path):
    conn = _raw(path)
    try:
        return {vectorcache._unpack(h): used for h, used in conn.execute("SELECT hash, used FROM entry")}
    finally:
        conn.close()


def _check_layout(path):
    """Every vector table uses slots 1..n, and each entry points at the row that carries its hash."""
    conn = _raw(path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        for (eid,) in conn.execute("SELECT id FROM embedder").fetchall():
            rows, last = conn.execute(f"SELECT COUNT(*), COALESCE(MAX(slot), 0) FROM vec_{eid}").fetchone()
            entries = conn.execute("SELECT COUNT(*) FROM entry WHERE embedder = ?", (eid,)).fetchone()[0]
            wrong = conn.execute(
                f"SELECT COUNT(*) FROM entry e LEFT JOIN vec_{eid} v ON v.slot = e.slot WHERE e.embedder = ? AND v.hash IS NOT e.hash",
                (eid,),
            ).fetchone()[0]
            assert rows == last == entries and wrong == 0, (eid, rows, last, entries, wrong)
    finally:
        conn.close()


# ---------------------------------------------------------------- keyed reads


def test_get_many_returns_what_it_holds_and_fetch_keeps_the_callers_order(tmp_path):
    cache = VectorCache(tmp_path / "cache.db")
    hashes, vecs = _hashes("a", 50), _vecs(50, 96)
    cache.put_many(KEY, hashes, vecs)
    stored = vecs.astype(np.float16)

    got = cache.get_many(KEY, [hashes[3], "0" * 20, hashes[1], hashes[3]])
    assert set(got) == {hashes[1], hashes[3]} and np.array_equal(got[hashes[3]], stored[3])

    order = [hashes[7], "0" * 20, hashes[2], hashes[7], "not a hex hash", hashes[49]]
    rows, found = cache.fetch(KEY, order)
    assert rows.dtype == np.float16 and rows.shape == (6, 96)
    assert found.tolist() == [True, False, True, True, False, True]
    assert np.array_equal(rows[[0, 2, 3, 5]], stored[[7, 2, 7, 49]]) and not rows[[1, 4]].any()

    rows, found = cache.fetch("a model it has never seen", order)
    assert rows.shape == (6, 0) and not found.any()
    assert cache.get_many("a model it has never seen", order) == {}
    assert cache.fetch(KEY, [])[0].shape == (0, 96)


def test_more_keys_than_one_statement_takes(tmp_path):
    cache = VectorCache(tmp_path / "cache.db")
    hashes, vecs = _hashes("a", 1300), _vecs(1300, 16)
    cache.put_many(KEY, hashes, vecs)
    order = hashes[::-1] + ["0" * 20]
    rows, found = cache.fetch(KEY, order)
    assert found.tolist() == [True] * 1300 + [False] and np.array_equal(rows[:1300], vecs.astype(np.float16)[::-1])
    assert len(cache.get_many(KEY, order)) == 1300 and cache.touch(KEY, order) == ["0" * 20]


@pytest.mark.parametrize("dim", [8, 64, 896, 1024, 4096])
def test_vectors_of_any_length_come_back_bit_for_bit(tmp_path, dim):
    cache = VectorCache(tmp_path / "cache.db")
    hashes, vecs = _hashes("a", 40), _vecs(40, dim, seed=dim)
    cache.put_many(KEY, hashes, vecs)
    rows, found = cache.fetch(KEY, hashes)
    assert found.all() and rows.tobytes() == vecs.astype(np.float16).tobytes()
    assert cache.stats()["embedders"] == {KEY: {"entries": 40, "dim": dim}}
    _check_layout(cache.path)


def test_a_hash_is_stored_once_and_keeps_its_first_vector(tmp_path):
    cache = VectorCache(tmp_path / "cache.db")
    hashes = _hashes("a", 10)
    cache.put_many(KEY, hashes, _vecs(10, 32, seed=1))
    cache.put_many(KEY, hashes[5:] + _hashes("b", 5) + hashes[:1], _vecs(11, 32, seed=2))
    assert cache.count(KEY) == 15 and cache.count() == 15 and cache.count("another model") == 0
    assert np.array_equal(cache.fetch(KEY, hashes)[0], _vecs(10, 32, seed=1).astype(np.float16))
    other = "model-b|doc"  # the same text under another embedder is another entry
    cache.put_many(other, hashes[:3], _vecs(3, 8))
    assert cache.count(other) == 3 and cache.count() == 18 and cache.fetch(other, hashes[:1])[0].shape == (1, 8)
    _check_layout(cache.path)


def test_an_embedder_has_one_vector_length(tmp_path, caplog):
    cache = VectorCache(tmp_path / "cache.db")
    cache.put_many(KEY, _hashes("a", 3), _vecs(3, 32))
    cache.put_many(KEY, _hashes("b", 3), _vecs(3, 64))  # not stored, and no error
    assert cache.count(KEY) == 3 and cache.get_many(KEY, _hashes("b", 3)) == {}
    assert "not cached" in caplog.text


def test_hashes_that_are_not_hex_work_too(tmp_path):
    cache = VectorCache(tmp_path / "cache.db")
    odd = ["h", "ABCDEF", "abc", "ab cd", "", "café"]  # not lowercase hex pairs: kept as text
    cache.put_many(KEY, odd + ["abcdef"], _vecs(7, 4))
    rows, found = cache.fetch(KEY, ["abcdef", *odd])
    assert found.all() and np.array_equal(rows, _vecs(7, 4).astype(np.float16)[[6, 0, 1, 2, 3, 4, 5]])
    assert set(cache.get_many(KEY, odd)) == set(odd)


# ---------------------------------------------------------------- last use


def test_a_read_writes_nothing_unless_asked_and_a_stamp_is_written_once_a_day(tmp_path, clock):
    cache = VectorCache(tmp_path / "cache.db")
    hashes = _hashes("a", 30)
    cache.put_many(KEY, hashes, _vecs(30, 16))
    put_at = clock[0]
    watcher = _raw(cache.path)

    def version():  # changes when any other connection commits
        return watcher.execute("PRAGMA data_version").fetchone()[0]

    clock[0] += 2 * DAY
    before = version()
    assert len(cache.get_many(KEY, hashes)) == 30 and cache.fetch(KEY, hashes)[1].all()
    assert version() == before and set(_stamps(cache.path).values()) == {put_at}

    cache.get_many(KEY, hashes[:10], touch=True)
    cache.fetch(KEY, hashes[10:15], touch=True)
    assert cache.touch(KEY, hashes[15:20] + ["0" * 20]) == ["0" * 20]  # it also says what the cache does not hold
    stamps = _stamps(cache.path)
    assert {stamps[h] for h in hashes[:20]} == {clock[0]} and {stamps[h] for h in hashes[20:]} == {put_at}

    clock[0] += 3600  # later the same day: every stamp is from today, so nothing is written
    before = version()
    cache.get_many(KEY, hashes[:20], touch=True)
    assert cache.touch(KEY, hashes[:20]) == [] and version() == before
    cache.put_many(KEY, hashes[25:], _vecs(5, 16))  # a put of something held counts as use
    stamps = _stamps(cache.path)
    assert {stamps[h] for h in hashes[25:]} == {clock[0]} and {stamps[h] for h in hashes[20:25]} == {put_at}
    assert cache.touch("a model it has never seen", hashes[:2]) == hashes[:2]
    watcher.close()


# ---------------------------------------------------------------- the cap


def test_past_the_cap_the_least_recently_used_go_and_the_file_shrinks(tmp_path, clock):
    cache = VectorCache(tmp_path / "cache.db")
    old, mid, new = _hashes("old", 5000), _hashes("mid", 1000), _hashes("new", 1200)
    _put(cache, KEY, old, _vecs(5000, 128, seed=1))
    clock[0] += DAY
    _put(cache, KEY, mid, _vecs(1000, 128, seed=2))
    clock[0] += DAY
    kept = old[::2]
    assert cache.touch(KEY, kept) == []
    cap = cache.max_bytes = cache.stats()["bytes"] + 100_000  # the next puts pass it

    _put(cache, KEY, new, _vecs(1200, 128, seed=3))
    assert cache.count() < 7200  # a put looked at the size and started deleting
    cache.evict()  # finishes it, in case the last put's share of the work was cut short
    stats = cache.stats()
    assert stats["bytes"] <= cap and stats["max_bytes"] == cap

    everything = old + mid + new
    left = {everything[i] for i in _gone(cache, KEY, everything)}
    assert left <= set(old) - set(kept) and 0 < len(left) < 2500  # only entries nobody used since day one
    for hashes, seed in ((kept, 1), (mid, 2), (new, 3)):
        rows, found = cache.fetch(KEY, hashes)
        expect = _vecs(len(old) if seed == 1 else len(hashes), 128, seed=seed).astype(np.float16)
        assert found.all() and np.array_equal(rows, expect[::2] if seed == 1 else expect)
    _check_layout(cache.path)

    clock[0] += DAY
    late = _hashes("late", 300)  # a put after eviction
    _put(cache, KEY, late, _vecs(300, 128, seed=4))
    assert np.array_equal(cache.fetch(KEY, late)[0], _vecs(300, 128, seed=4).astype(np.float16))
    _check_layout(cache.path)

    # The file itself gets smaller, whichever entries go: here every third one, spread over all its pages.
    cache.max_bytes = 0
    conn = _raw(cache.path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    before = os.path.getsize(cache.path)
    clock[0] += DAY
    cache.touch(KEY, [h for i, h in enumerate(everything + late) if i % 3])
    cache.max_bytes = int(before * 0.8)
    deleted = cache.evict()
    after = os.path.getsize(cache.path)
    assert deleted > 0 and after <= 0.9 * cache.max_bytes < before
    assert cache.evict() == 0  # under the cap: nothing to do
    _check_layout(cache.path)
    conn.close()


def test_eviction_in_slices_goes_on_where_it_stopped(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(vectorcache, "_EVICT_ROWS", 100)
    cache = VectorCache(tmp_path / "cache.db")
    hashes = _hashes("a", 3000)
    for day in range(3):  # three days of puts, so the order of eviction is known
        _put(cache, KEY, hashes[day * 1000 : (day + 1) * 1000], _vecs(1000, 64, seed=day))
        clock[0] += DAY
    cache.max_bytes = int(cache.stats()["bytes"] * 0.7)
    assert cache.evict(max_seconds=0) == 100 and cache.count() == 2900  # one batch, then the time is up
    assert max(_gone(cache, KEY, hashes)) < 1000  # of the first day
    assert cache.evict(max_seconds=0) == 100
    total = 200 + cache.evict()
    assert cache.stats()["bytes"] <= 0.9 * cache.max_bytes and cache.count() == 3000 - total
    gone = _gone(cache, KEY, hashes)
    assert len(gone) == total and max(i // 1000 for i in gone) <= min(i // 1000 for i in set(range(3000)) - set(gone))
    _check_layout(cache.path)


def test_eviction_with_two_vector_lengths_and_other_writers(tmp_path, clock):
    """Entries of two embedders are evicted in one order of last use, while another thread keeps putting."""
    cache = VectorCache(tmp_path / "cache.db")
    big, small = _hashes("big", 3000), _hashes("small", 6000)
    big_vecs, small_vecs, extra_vecs = _vecs(3000, 512, seed=5), _vecs(6000, 16, seed=6), _vecs(2000, 32, seed=7)
    for i in range(6):  # interleaved, 500 big and 1,000 small a day
        cache.put_many(KEY, big[i * 500 : (i + 1) * 500], big_vecs[i * 500 : (i + 1) * 500])
        cache.put_many("small|doc", small[i * 1000 : (i + 1) * 1000], small_vecs[i * 1000 : (i + 1) * 1000])
        clock[0] += DAY
    extra, errors = _hashes("extra", 2000), []

    def writer():
        try:
            for i in range(0, 2000, 50):
                cache.put_many("other|doc", extra[i : i + 50], extra_vecs[i : i + 50])
        except BaseException as e:  # noqa: BLE001 - any error fails the test
            errors.append(e)
        finally:
            cache.close()

    cache.max_bytes = int(cache.stats()["bytes"] * 0.6)
    thread = threading.Thread(target=writer)
    thread.start()
    while thread.is_alive():
        cache.evict()
        time.sleep(0.001)
    thread.join()
    cache.evict()
    assert errors == [] and cache.stats()["bytes"] <= cache.max_bytes
    # The oldest days went first, whichever embedder an entry belongs to.
    gone = {i // 500 for i in _gone(cache, KEY, big)} | {i // 1000 for i in _gone(cache, "small|doc", small)}
    here = {i // 500 for i in set(range(3000)) - set(_gone(cache, KEY, big))}
    here |= {i // 1000 for i in set(range(6000)) - set(_gone(cache, "small|doc", small))}
    assert gone and here and max(gone) <= min(here) and _gone(cache, "other|doc", extra) == []
    for key, hashes, vecs in ((KEY, big, big_vecs), ("small|doc", small, small_vecs), ("other|doc", extra, extra_vecs)):
        rows, found = cache.fetch(key, hashes)
        assert np.array_equal(rows[found], vecs.astype(np.float16)[found])  # whatever is left is still its own vector
    _check_layout(cache.path)


def test_no_cap_means_no_eviction(tmp_path):
    cache = VectorCache(tmp_path / "cache.db")
    _put(cache, KEY, _hashes("a", 2000), _vecs(2000, 64))
    assert cache.evict() == 0 and cache.count() == 2000 and cache.stats()["max_bytes"] == 0


def test_the_cap_setting_is_checked_and_changes_no_index():
    assert Config().vector_cache_max_gb == 8.0
    assert config_from_dict({"vector_cache_max_gb": 0}).vector_cache_max_gb == 0
    assert config_from_dict({"vector_cache_max_gb": 2.5}).vector_cache_max_gb == 2.5
    for bad in (-1, "8", True, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="vector_cache_max_gb"):
            config_from_dict({"vector_cache_max_gb": bad})
    assert config_from_dict({"vector_cache_max_gb": 1}).index_settings() == Config().index_settings()


# ---------------------------------------------------------------- a cache file in the row format

_ROW_FORMAT = """
CREATE TABLE IF NOT EXISTS cache (
    embedder TEXT NOT NULL, text_hash TEXT NOT NULL, dim INTEGER NOT NULL, data BLOB NOT NULL,
    PRIMARY KEY (embedder, text_hash)
) WITHOUT ROWID;
"""


def _row_format_file(path, n=900):
    """A cache file as codemem wrote it before: one table, one row per vector. Returns what it holds."""
    content = {
        "jina|doc|L1024|float16|mps": (_hashes("j", n), _vecs(n, 896, seed=1).astype(np.float16)),
        "fake:64|doc": (_hashes("f", n // 3) + ["h", "ABCDEF"], _vecs(n // 3 + 2, 64, seed=2).astype(np.float16)),
        "api:host|m|dims=full|doc=0": (_hashes("j", 20), _vecs(20, 8, seed=3).astype(np.float16)),
    }
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_ROW_FORMAT)
    conn.execute("BEGIN")
    for embedder, (hashes, vecs) in content.items():
        conn.executemany(
            "INSERT INTO cache(embedder, text_hash, dim, data) VALUES(?, ?, ?, ?)",
            [(embedder, h, vecs.shape[1], v.tobytes()) for h, v in zip(hashes, vecs)],
        )
    conn.execute("COMMIT")
    conn.close()
    return content


def _assert_holds(cache, content):
    for embedder, (hashes, vecs) in content.items():
        rows, found = cache.fetch(embedder, hashes)
        assert found.all() and rows.tobytes() == vecs.tobytes(), embedder
        assert cache.count(embedder) == len(hashes)
    assert cache.count() == sum(len(hashes) for hashes, _ in content.values())
    _check_layout(cache.path)


def _files(folder):
    return sorted(p.name for p in folder.iterdir())


def test_a_cache_in_the_row_format_is_imported_byte_for_byte(tmp_path, clock, caplog):
    content = _row_format_file(tmp_path / ROW_FORMAT_FILE)
    written = int((tmp_path / ROW_FORMAT_FILE).stat().st_mtime)
    with caplog.at_level("INFO"):
        cache = VectorCache(tmp_path / CACHE_FILE, import_from=tmp_path / ROW_FORMAT_FILE)
        _assert_holds(cache, content)
    assert "importing 1222 vectors" in caplog.text and "imported 1222 vectors" in caplog.text
    cache.close()
    assert _files(tmp_path) == [CACHE_FILE]  # the row-format file and its WAL files are gone
    assert set(_stamps(tmp_path / CACHE_FILE).values()) == {written}  # last used when that file was last written

    again = VectorCache(tmp_path / CACHE_FILE, import_from=tmp_path / ROW_FORMAT_FILE)  # nothing to import now
    _assert_holds(again, content)
    again.close()


def test_an_interrupted_import_finishes_at_the_next_start(tmp_path, monkeypatch):
    content = _row_format_file(tmp_path / ROW_FORMAT_FILE)
    monkeypatch.setattr(vectorcache, "_IMPORT_ROWS", 100)
    real, calls = VectorCache._store, []

    def dies_midway(self, *args):
        calls.append(1)
        if len(calls) == 6:
            raise KeyboardInterrupt  # the process is stopped between two batches
        return real(self, *args)

    monkeypatch.setattr(VectorCache, "_store", dies_midway)
    first = VectorCache(tmp_path / CACHE_FILE, import_from=tmp_path / ROW_FORMAT_FILE)
    with pytest.raises(KeyboardInterrupt):
        first.count()
    assert (tmp_path / ROW_FORMAT_FILE).exists()  # not deleted before everything is in

    monkeypatch.setattr(VectorCache, "_store", real)
    assert 0 < VectorCache(tmp_path / CACHE_FILE).count() < 1222  # part of it had been committed
    second = VectorCache(tmp_path / CACHE_FILE, import_from=tmp_path / ROW_FORMAT_FILE)
    _assert_holds(second, content)
    second.close()
    assert not (tmp_path / ROW_FORMAT_FILE).exists()


def test_a_failed_import_keeps_the_row_format_file_and_the_cache_usable(tmp_path, monkeypatch, caplog):
    content = _row_format_file(tmp_path / ROW_FORMAT_FILE)
    monkeypatch.setattr(vectorcache, "_IMPORT_ROWS", 100)
    real, calls = VectorCache._store, []

    def fails_once(self, *args):
        calls.append(1)
        if len(calls) == 4:
            raise sqlite3.OperationalError("disk I/O error")
        return real(self, *args)

    monkeypatch.setattr(VectorCache, "_store", fails_once)
    cache = VectorCache(tmp_path / CACHE_FILE, import_from=tmp_path / ROW_FORMAT_FILE)
    cache.put_many(KEY, _hashes("x", 5), _vecs(5, 16))  # no error reaches the caller, and the cache works
    assert cache.count(KEY) == 5 and (tmp_path / ROW_FORMAT_FILE).exists() and "could not import" in caplog.text
    cache.close()
    second = VectorCache(tmp_path / CACHE_FILE, import_from=tmp_path / ROW_FORMAT_FILE)  # the next process finishes it
    assert second.count(KEY) == 5
    _assert_holds(second, {**content, KEY: (_hashes("x", 5), _vecs(5, 16).astype(np.float16))})
    assert not (tmp_path / ROW_FORMAT_FILE).exists()
    second.close()


_IMPORTER = """
import pathlib, sys, time
from codemem import vectorcache

vectorcache._IMPORT_ROWS = 25  # many small batches, so the two processes take turns
new, old, ready, go = sys.argv[1:]
real, copied = vectorcache.VectorCache._store, []


def counting(self, *args):
    n = real(self, *args)
    copied.append(n)
    return n


vectorcache.VectorCache._store = counting
pathlib.Path(ready).touch()
while not pathlib.Path(go).exists():
    time.sleep(0.002)
cache = vectorcache.VectorCache(new, import_from=old)
print(cache.count(), sum(copied))
cache.close()
"""


def test_two_processes_importing_at_once_end_with_one_complete_cache(tmp_path):
    content = _row_format_file(tmp_path / ROW_FORMAT_FILE, n=1500)
    total = sum(len(hashes) for hashes, _ in content.values())
    stored_bytes = sum(vecs.nbytes for _, vecs in content.values())
    go = tmp_path / "go"
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _IMPORTER, str(tmp_path / CACHE_FILE), str(tmp_path / ROW_FORMAT_FILE),
             str(tmp_path / f"ready{i}"), str(go)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for i in range(2)
    ]
    try:
        deadline = time.monotonic() + 60
        while not all((tmp_path / f"ready{i}").exists() for i in range(2)):
            assert all(p.poll() is None for p in procs) and time.monotonic() < deadline
            time.sleep(0.01)
        go.touch()  # both are loaded and waiting: they start the import at the same moment
        outs = [p.communicate(timeout=120) for p in procs]
    finally:
        for p in procs:
            p.kill()
    assert [p.returncode for p in procs] == [0, 0], outs
    counts, copied = zip(*(map(int, out.split()) for out, _ in outs))
    assert counts == (total, total)  # neither went on with half a cache
    assert sum(copied) == stored_bytes  # and no vector was stored twice
    cache = VectorCache(tmp_path / CACHE_FILE)
    _assert_holds(cache, content)
    cache.close()
    assert not (tmp_path / ROW_FORMAT_FILE).exists()
    conn = _raw(tmp_path / CACHE_FILE)  # created by two processes at once, and still laid out as one would
    assert conn.execute("PRAGMA page_size").fetchone()[0] == 32768 and conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
    conn.close()


def test_a_file_that_is_not_a_row_format_cache_is_left_alone(tmp_path):
    other = tmp_path / ROW_FORMAT_FILE
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE notes(text)")
    conn.commit()
    conn.close()
    cache = VectorCache(tmp_path / CACHE_FILE, import_from=other)
    assert cache.count() == 0 and other.exists()
    cache.close()


# ---------------------------------------------------------------- failures stay inside


def _everything(cache, monkeypatch):
    """Every call of the cache, each trying a file it cannot use: what a caller sees is an empty cache."""
    hashes = _hashes("a", 3)
    with monkeypatch.context() as patch:
        patch.setattr(vectorcache, "_RETRY_SECONDS", 0.0)  # no call is spared the file because another one failed
        cache.put_many(KEY, hashes, _vecs(3, 16))
        rows, found = cache.fetch(KEY, hashes)
        assert cache.get_many(KEY, hashes) == {} and rows.shape == (3, 0) and not found.any()
        assert cache.touch(KEY, hashes) == [] and cache.count() == 0 and cache.stats() is None and cache.evict() == 0
    cache.close()


def _index(repo, index_dir, config, embedder):
    store = Store(index_dir)
    try:
        return Indexer(repo, store, config, embedder_factory=lambda m, c: embedder).update()
    finally:
        store.close()


def test_a_locked_cache_file_never_stops_an_index_update(sample_repo, tmp_path, fake_config, recorder, monkeypatch, caplog):
    monkeypatch.setattr(vectorcache, "_BUSY_SECONDS", 0.2)
    path = machine_cache(fake_config).path
    first = _index(sample_repo, tmp_path / "one", fake_config, recorder)  # fills the cache
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("PRAGMA locking_mode = EXCLUSIVE")
    holder.execute("BEGIN EXCLUSIVE")  # no other connection can read or write the file now
    try:
        _everything(machine_cache(fake_config), monkeypatch)
        caplog.clear()
        stats = _index(sample_repo, tmp_path / "two", fake_config, recorder)
        assert stats.errors == [] and stats.embedded == first.embedded
        assert stats.model_embedded == first.model_embedded and sum(stats.cache_hits.values()) == 0  # the model did the work
        assert caplog.text.count("going on without it") == 1  # it waited for the lock once, then left the file alone
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    stats = _index(sample_repo, tmp_path / "three", fake_config, recorder)  # unlocked: the cache serves again
    assert sum(stats.model_embedded.values()) == 0 and stats.cache_hits == first.embedded


@pytest.mark.skipif(os.name == "nt" or getattr(os, "geteuid", lambda: 1)() == 0, reason="needs POSIX permissions, not root")
def test_a_read_only_cache_never_stops_an_index_update(sample_repo, tmp_path, fake_config, recorder, monkeypatch):
    path = machine_cache(fake_config).path
    first = _index(sample_repo, tmp_path / "one", fake_config, recorder)
    os.chmod(path, 0o444)
    os.chmod(path.parent, 0o555)
    try:
        _everything(machine_cache(fake_config), monkeypatch)
        stats = _index(sample_repo, tmp_path / "two", fake_config, recorder)
        assert stats.errors == [] and stats.embedded == first.embedded and stats.model_embedded == first.model_embedded
    finally:
        os.chmod(path.parent, 0o755)
        os.chmod(path, 0o644)


def test_a_file_that_is_not_a_cache_never_stops_an_index_update(sample_repo, tmp_path, fake_config, recorder, monkeypatch):
    path = machine_cache(fake_config).path
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not a database" * 500)
    _everything(machine_cache(fake_config), monkeypatch)
    stats = _index(sample_repo, tmp_path / "one", fake_config, recorder)
    assert stats.errors == [] and sum(stats.model_embedded.values()) == sum(stats.embedded.values()) > 0
    assert path.read_bytes().startswith(b"this is not a database")  # and it is not overwritten

    conn = sqlite3.connect(tmp_path / "other.db")  # a database, but somebody else's
    conn.execute("CREATE TABLE notes(text)")
    conn.commit()
    conn.close()
    _everything(VectorCache(tmp_path / "other.db"), monkeypatch)


# ---------------------------------------------------------------- the indexer and the cache


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True,
    )


@pytest.fixture
def two_branches(sample_repo):
    """The sample repo as a git repo with two branches: `main` (state A) and `feature` (state B)."""
    _git(sample_repo, "init", "-q", "-b", "main")
    _git(sample_repo, "add", "-A")
    _git(sample_repo, "commit", "-qm", "state A")
    _git(sample_repo, "checkout", "-qb", "feature")
    sessions = sample_repo / "auth" / "sessions.py"
    sessions.write_text(sessions.read_text().replace("db.sessions.delete(session_id)", "db.sessions.delete(session_id)\n    db.audit(session_id)"))
    (sample_repo / "auth" / "tokens.py").write_text("from auth.sessions import revoke_session\n\n\ndef rotate_token(session_id):\n    revoke_session(session_id)\n    return session_id[::-1]\n")
    (sample_repo / "api" / "routes.py").unlink()
    _git(sample_repo, "add", "-A")
    _git(sample_repo, "commit", "-qm", "state B")
    _git(sample_repo, "checkout", "-q", "main")
    return sample_repo


def test_a_second_visit_to_a_branch_makes_no_model_call(two_branches, tmp_path, fake_config, recorder):
    repo = two_branches
    store = Store(tmp_path / "index")
    indexer = Indexer(repo, store, fake_config, embedder_factory=lambda m, c: recorder)

    def visit(branch):
        _git(repo, "checkout", "-q", branch)
        before = len(recorder.calls)
        stats = indexer.update()
        assert stats.errors == []
        return stats, len(recorder.calls) - before

    stats, calls = visit("main")  # state A, first visit: everything goes to the model
    assert calls > 0 and stats.model_embedded == stats.embedded
    stats, calls = visit("feature")  # state B, first visit: only what is new in B
    assert calls > 0 and 0 < sum(stats.model_embedded.values()) < sum(stats.embedded.values()) + 1
    in_b = store.get_chunk_by_key("auth/tokens.py::rotate_token")
    assert in_b is not None and store.get_chunk_by_key("api/routes.py::logout") is None

    stats, calls = visit("main")  # state A again
    assert calls == 0 and sum(stats.model_embedded.values()) == 0
    assert sum(stats.embedded.values()) > 0 and sum(stats.cache_hits.values()) > 0  # its vectors came from the cache
    assert store.get_chunk_by_key("api/routes.py::logout") is not None
    assert store.get_chunk_by_key("auth/tokens.py::rotate_token") is None

    stats, calls = visit("feature")  # and state B again
    assert calls == 0 and sum(stats.model_embedded.values()) == 0 and sum(stats.embedded.values()) > 0

    before = len(recorder.calls)
    assert indexer.verify() == []  # the index equals a fresh build of B, and that build embedded nothing either
    assert len(recorder.calls) == before
    store.close()


def test_what_stage_b_looks_up_and_puts_counts_as_use(sample_repo, tmp_path, fake_config, recorder, clock):
    first = _index(sample_repo, tmp_path / "one", fake_config, recorder)
    path = machine_cache(fake_config).path
    put_at = clock[0]
    assert set(_stamps(path).values()) == {put_at}

    clock[0] += 3 * DAY
    (sample_repo / "auth" / "extra.py").write_text("def extra_helper(x):\n    return x + 1\n")
    stats = _index(sample_repo, tmp_path / "two", fake_config, recorder)  # another index: hits, and one new text
    assert sum(stats.cache_hits.values()) == sum(first.embedded.values()) and sum(stats.model_embedded.values()) > 0
    assert set(_stamps(path).values()) == {clock[0]}  # every hit and every put is stamped today


def test_evicted_vectors_are_embedded_again(sample_repo, tmp_path, fake_config, recorder, clock):
    first = _index(sample_repo, tmp_path / "one", fake_config, recorder)
    texts = [text_hash(t) for t in dict.fromkeys(recorder.documents)]
    cache = machine_cache(fake_config)
    assert cache.count() == len(texts) and _gone(cache, recorder.key, texts) == []
    clock[0] += DAY
    _put(cache, recorder.key, _hashes("other repos", 4000), _vecs(4000, 64))  # newer than this repo's vectors
    cache.max_bytes = int(cache.stats()["bytes"] * 0.9)
    assert cache.evict() >= len(texts) and len(_gone(cache, recorder.key, texts)) == len(texts)
    cache.close()

    stats = _index(sample_repo, tmp_path / "two", fake_config, recorder)  # the model embeds them again
    assert stats.errors == [] and stats.embedded == first.embedded and stats.model_embedded == first.model_embedded
    stats = _index(sample_repo, tmp_path / "three", fake_config, recorder)  # which puts them back
    assert sum(stats.model_embedded.values()) == 0 and stats.cache_hits == first.embedded


def test_the_configured_cap_reaches_the_cache_and_an_update_enforces_it(sample_repo, tmp_path, fake_config, recorder, clock):
    store = Store(tmp_path / "index")
    indexer = Indexer(sample_repo, store, fake_config, embedder_factory=lambda m, c: recorder)
    cache = indexer.vector_cache()
    assert cache.max_bytes == 8_000_000_000 and cache.path.name == CACHE_FILE
    _put(cache, recorder.key, _hashes("other repos", 4000), _vecs(4000, 64))
    clock[0] += DAY
    indexer.update()
    texts = [text_hash(t) for t in dict.fromkeys(recorder.documents)]
    size = cache.stats()["bytes"]

    fake_config.vector_cache_max_gb = size * 0.9 / 1e9  # the setting changes: the cache is now over its cap
    assert indexer.vector_cache() is cache and cache.max_bytes == vectorcache.cap_bytes(fake_config) < size
    indexer.update()  # nothing to index, and still the cache is brought under 90% of its cap
    assert cache.stats()["bytes"] <= 0.9 * cache.max_bytes and _gone(cache, recorder.key, texts) == []
    fake_config.vector_cache = "off"
    assert indexer.vector_cache() is None
    store.close()


def test_status_shows_the_cache(sample_repo, tmp_path, fake_config):
    svc = CodememService(sample_repo, index_dir=tmp_path / "idx", config=fake_config)
    try:
        svc.update()
        info = svc.status()
        cache = info["vector_cache"]
        assert cache["entries"] == sum(info["vectors"].values()) > 0 and cache["max_bytes"] == 8_000_000_000
        assert cache["bytes"] == os.path.getsize(cache["path"]) and cache["embedders"]["fake:64|doc"]["dim"] == 64
        line = next(line for line in format_status(info).splitlines() if line.startswith("vector cache"))
        assert line == f"vector cache: {cache['entries']} vectors, {cache['bytes'] / 1e3:.1f} KB of 8.0 GB, in {cache['path']}"
        fake_config.vector_cache_max_gb = 0
        assert "KB (no cap), in " in format_status(svc.status())
        fake_config.vector_cache = "off"
        assert svc.status()["vector_cache"] is None and "vector cache: off" in format_status(svc.status())
        fake_config.vector_cache = "global"
        with open(cache["path"], "wb") as f:
            f.write(b"not a database" * 100)
        assert f"vector cache: cannot be read ({cache['path']})" in format_status(svc.status())
    finally:
        svc.close()
