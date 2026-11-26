"""What every search index shares (docs/architecture.md §5): where each vector came from, how many
vectors a search asks its index for, the hook that lets an index read stored vectors back, and
what a saved index belongs to: one database, a state of it, and the bytes that were saved."""

import json
import shutil
import sqlite3
import zlib
from contextlib import closing

import numpy as np
import pytest

from codemem.embedder import l2_normalize
from codemem.schema import Chunk, text_hash
from codemem.store import FaissVectorStore, Store, VectorRow, VectorStore, _TypeIndex, for_index

EMBEDDER = "fake|doc"


def _chunk(name, path="pkg/mod.py"):
    code = f"def {name}():\n    return 1"
    return Chunk(
        key=f"{path}::{name}", path=path, qualname=name, name=name, kind="function",
        start_line=1, end_line=2, signature=f"def {name}():", docstring="", code=code,
        content_hash=text_hash(code),
    )


def _vecs(n, dim=16, seed=0):
    return l2_normalize(np.random.default_rng(seed).normal(size=(n, dim)))


def _add_chunks(store, n):
    with store.transaction():
        ids = [store.upsert_chunk(_chunk(f"f{i:03d}")) for i in range(n)]
        store.ensure_vec_type("code", EMBEDDER)
    return ids


def _seed(store, n):
    """n chunks with one vector each; returns the chunk ids."""
    ids = _add_chunks(store, n)
    store.put_vectors("code", EMBEDDER, [VectorRow(c, 0, 1, 0, 1, f"h{c}") for c in ids], _vecs(n))
    return ids


def _rows(first, n, chunk0=100):
    """n vector ids from `first`, two to a chunk, and their (chunk, part, n_parts, start_off, end_off)."""
    info = [(chunk0 + i // 2, i % 2, 2, 10 * (i % 2), 10 * (i % 2) + 9) for i in range(n)]
    return list(range(first, first + n)), info


# ---------------------------------------------------------------- where each vector came from


def test_type_index_finds_vectors_and_chunks_in_32_bytes_a_vector():
    ti = _TypeIndex(8, 0, FaissVectorStore(8))
    ids, info = _rows(1, 10)
    ti.add(ids, info, _vecs(10, dim=8))
    assert ti.table.dtype.itemsize == 32 and ti.table.nbytes == 320 and ti.store.ids() == set(ids)
    assert ti.find([7, 2, 2]).tolist() == [(7, 103, 0, 2, 0, 9), (2, 100, 1, 2, 10, 19), (2, 100, 1, 2, 10, 19)]
    assert ti.find([]).tolist() == [] and ti.vectors_of([]).tolist() == []
    assert ti.vectors_of([104, 100, 999]).tolist() == [1, 2, 9, 10]
    for missing in ([11], [0], [5, 99]):
        with pytest.raises(KeyError):
            ti.find(missing)
    ti.remove([2, 3, 999])  # an id it does not hold is ignored
    assert ti.table["vector"].tolist() == [1, 4, 5, 6, 7, 8, 9, 10] and ti.store.ids() == {1, 4, 5, 6, 7, 8, 9, 10}
    assert ti.vectors_of([100, 101]).tolist() == [1, 4]
    ti.remove(range(1, 11))
    assert len(ti.table) == 0 and len(ti.store) == 0
    with pytest.raises(KeyError):
        ti.find([1])


def test_type_index_keeps_its_table_sorted_when_older_ids_arrive_later():
    """A saved index or a catch-up can bring rows older than the newest held."""
    ti = _TypeIndex(8, 0, FaissVectorStore(8))
    v = _vecs(12, dim=8)
    ti.add([50, 60], [(1, 0, 1, 0, 1), (2, 0, 1, 0, 1)], v[:2])
    ti.hold(np.array([(40, 3, 0, 1, 0, 1), (10, 4, 0, 1, 0, 1)], dtype=ti.table.dtype))  # held by the backend already
    ti.add([55, 5], [(5, 0, 1, 0, 1), (6, 0, 1, 0, 1)], v[2:4])
    assert ti.table["vector"].tolist() == [5, 10, 40, 50, 55, 60]
    assert ti.find([55, 5, 40])["chunk"].tolist() == [5, 6, 3]
    ti.add([50], [(9, 1, 2, 3, 4)], v[4:5])  # an id added again keeps its newest row
    assert ti.table["vector"].tolist() == [5, 10, 40, 50, 55, 60] and ti.find([50]).tolist() == [(50, 9, 1, 2, 3, 4)]
    assert ti.vectors_of([1]).tolist() == [] and ti.vectors_of([9]).tolist() == [50]


def test_an_index_that_has_the_two_column_index_loses_it_when_it_is_opened(tmp_path):
    """`vectors_owner` starts with the columns of the older `vectors_type` and answers its lookups."""
    s = Store(tmp_path / "idx", vector_backend="faiss")
    _seed(s, 5)
    s.close()
    with closing(sqlite3.connect(tmp_path / "idx" / "index.db")) as conn:
        conn.execute("CREATE INDEX vectors_type ON vectors(vec_type, chunk_id)")
        conn.commit()
    s = Store(tmp_path / "idx", vector_backend="faiss")
    indexes = {r[1] for r in s.conn.execute("PRAGMA index_list(vectors)")}
    assert "vectors_type" not in indexes and "vectors_owner" in indexes
    for lookup in ("SELECT vector_id FROM vectors WHERE vec_type = 'code'",
                   "SELECT vector_id, chunk_id, part FROM vectors WHERE vec_type = 'code' AND chunk_id IN (1, 2)",
                   "SELECT vec_type, COUNT(*) FROM vectors GROUP BY vec_type"):
        plan = " ".join(r[3] for r in s.conn.execute("EXPLAIN QUERY PLAN " + lookup))
        assert "COVERING INDEX vectors_owner" in plan
    assert s.vec_types() == ["code"] and len(s.vector_rows("code")) == 5 and s.counts()["vectors"] == {"code": 5}
    s.close()


def test_a_rebuild_takes_one_type_s_vectors_from_the_table_in_id_order(tmp_path):
    s = Store(tmp_path / "idx", vector_backend="faiss")
    ids = _add_chunks(s, 6)
    with s.transaction():
        s.ensure_vec_type("usage", EMBEDDER)
    for i, chunk_id in enumerate(ids):  # the two types' rows alternate in the table
        s.put_vectors("code", EMBEDDER, [VectorRow(chunk_id, 0, 1, 0, 1, f"c{i}")], _vecs(1, seed=i))
        s.put_vectors("usage", EMBEDDER, [VectorRow(chunk_id, 0, 1, 0, 1, f"u{i}")], _vecs(1, seed=100 + i))
    s.close()  # nothing was saved: the next start builds both indexes from the rows
    s = Store(tmp_path / "idx", vector_backend="faiss")
    for vec_type, first in (("code", 1), ("usage", 2)):
        ti = s._type_index(vec_type)
        assert ti.table["vector"].tolist() == list(range(first, 13, 2)) and ti.store.ids() == set(range(first, 13, 2))
    assert s.vector_search("usage", _vecs(1, seed=103)[0], 1)[0].chunk_id == ids[3]
    s.close()


def test_a_search_asks_the_backend_for_plain_lists(tmp_path):
    """Plugins get what they always got: lists of ints, and no filter when a filter keeps everything."""
    seen = []

    class Recording(FaissVectorStore):
        def search(self, query, k, allowed_ids=None):
            seen.append(allowed_ids)
            return super().search(query, k, allowed_ids)

    store = Store(tmp_path / "idx", vector_backend="faiss")
    ids = _seed(store, 6)
    store._in_use = store._in_use._replace(cls=Recording)
    store._types.clear()
    q = _vecs(1, seed=3)[0]
    assert len(store.vector_search("code", q, 3, ids[:2])) == 2 and len(store.vector_search("code", q, 3, ids)) == 3
    assert type(seen[0]) is list and all(type(i) is int for i in seen[0]) and seen[1] is None
    store.close()


# ---------------------------------------------------------------- how many vectors a search asks for


def test_type_index_says_how_many_vectors_hold_the_best_chunks():
    ti = _TypeIndex(8, 0, FaissVectorStore(8))
    assert ti.vectors_for(51) == 51
    ids, info = _rows(1, 10)
    ti.add(ids, info, _vecs(10, dim=8))
    assert ti.vectors_for(51) == 102  # two vectors a chunk: twice as many vectors as chunks wanted
    ti.remove([2, 3])
    ti.add([20, 21, 22], [(200, 0, 1, 0, 1), (201, 0, 1, 0, 1), (202, 0, 1, 0, 1)], _vecs(3, dim=8))
    assert ti.vectors_for(51) == 81  # 11 vectors that count as 7 chunks: 8 halves of two-part chunks, 3 whole ones
    ti.remove(range(1, 11))
    assert ti.vectors_for(51) == 51  # one vector a chunk: as many vectors as chunks


def test_one_backend_search_is_enough_when_chunks_have_several_vectors(tmp_path):
    """The store asks for more vectors than chunks when chunks have parts, so that the best n
    chunks are complete at once; it still asks again when they are not."""
    store = Store(tmp_path / "idx", vector_backend="faiss")
    ids = _add_chunks(store, 200)
    v = _vecs(400, seed=6)
    v[1::2] = l2_normalize(v[::2] + 0.05 * v[1::2])  # the two parts of a chunk lie close together
    rows = [VectorRow(c, part, 2, 0, 1, f"h{c}.{part}") for c in ids for part in range(2)]
    store.put_vectors("code", EMBEDDER, rows, v)
    ti = store._type_index("code")
    asked: list[int] = []
    search = ti.store.search
    ti.store.search = lambda q, k, allowed=None: asked.append(k) or search(q, k, allowed)

    def best_chunks(q, n):
        scores = (for_index(v, 16) @ for_index(q, 16)[0]).reshape(200, 2).max(axis=1)
        return [ids[i] for i in np.argsort(-scores)[:n]]

    q = _vecs(1, seed=1000)[0]
    assert [h.chunk_id for h in store.vector_search("code", q, 10)] == best_chunks(q, 10)
    assert asked == [22]  # 11 chunks of two vectors each
    asked.clear()
    many = np.repeat(v[:1], 30, axis=0) + 1e-3 * _vecs(30, seed=8)
    store.put_vectors("code", EMBEDDER, [VectorRow(ids[0], part, 30, 0, 1, f"x{part}") for part in range(30)], many)
    hits = store.vector_search("code", v[0], 10)  # 30 parts of one chunk lead: one search is not enough
    assert hits[0].chunk_id == ids[0] and len({h.chunk_id for h in hits}) == 10 and len(asked) > 1 and asked[0] == 24
    store.close()


# ---------------------------------------------------------------- the hook


class BoundStore(FaissVectorStore):
    """A plugin that records what `bind` gave it."""

    fetches: list = []

    def bind(self, fetch):
        BoundStore.fetches.append(fetch)


def test_bind_hands_every_backend_the_stored_vectors_once_built_and_once_loaded(tmp_path):
    BoundStore.fetches.clear()
    backend = f"{__name__}:BoundStore"
    s = Store(tmp_path / "idx", vector_backend=backend)
    ids = _seed(s, 5)
    assert len(BoundStore.fetches) == 1
    vids = [s.vector_rows("code")[(c, 0)][0] for c in ids]
    found, vecs = BoundStore.fetches[0](np.asarray(vids[::-1] + [10**9]))  # ids as a list or an array; one has no row
    assert sorted(found.tolist()) == sorted(vids) and vecs.dtype == np.float32 and vecs.shape == (5, 16)
    by_id = dict(zip(found.tolist(), vecs))
    as_upsert_got_them = for_index(_vecs(5), 16)
    assert all(np.array_equal(by_id[vid], as_upsert_got_them[i]) for i, vid in enumerate(vids))
    assert BoundStore.fetches[0]([])[1].shape == (0, 16)
    s.save_vectors()
    s.close()
    s2 = Store(tmp_path / "idx", vector_backend=backend)
    assert s2._type_index("code") is not None and len(BoundStore.fetches) == 2  # loaded from its file: bound again
    s2.close()


def test_the_base_class_ignores_bind():
    class Plain(VectorStore):
        upsert = remove = search = ids = __len__ = lambda self, *a: None

    assert Plain().bind(lambda ids: None) is None


# ---------------------------------------------------------------- what a saved index belongs to


class SavedPlugin(FaissVectorStore):
    """A plugin backend that is saved, under a suffix of its own."""

    suffix = ".plug"


def _count_rebuilds(monkeypatch):
    rebuilds: list[tuple] = []
    rebuild = Store._rebuild
    monkeypatch.setattr(Store, "_rebuild", lambda self, *a: rebuilds.append(a) or rebuild(self, *a))
    return rebuilds


# Every kind of saved index. The compact one scores 2 candidates, so that its codes choose them.
SAVED = [("faiss", {}), ("compact", {"rescore": 2}), (f"{__name__}:SavedPlugin", {})]


@pytest.mark.parametrize("backend, options", SAVED)
def test_a_saved_index_is_never_read_into_another_database(tmp_path, monkeypatch, backend, options):
    """`index.db` deleted by hand, its saved search index left beside it, then a rebuild: the new
    database numbers its vectors from 1 again, so the old file would match them by id."""
    idx = tmp_path / "idx"
    old = Store(idx, vector_backend=backend, vector_options=options)
    _seed(old, 40)
    old.save_vectors()
    first_id = old.database_id()
    old.close()
    for gone in idx.glob("index.db*"):
        gone.unlink()
    assert len(list(idx.glob("vec_code*"))) == 2  # the saved index and its note stay

    new = Store(idx, vector_backend=backend, vector_options=options)
    ids = _add_chunks(new, 40)
    other = _vecs(40, seed=9)
    new.put_vectors("code", EMBEDDER, [VectorRow(c, 0, 1, 0, 1, f"n{c}") for c in ids], other)
    assert sorted(vid for vid, _ in new.vector_rows("code").values()) == list(range(1, 41))  # the same ids again
    assert new.database_id() != first_id
    for i in range(0, 40, 4):
        hit = new.vector_search("code", other[i], 1)[0]
        assert hit.chunk_id == ids[i] and hit.score == pytest.approx(1.0, abs=1e-3)
    new.save_vectors()
    new.close()

    rebuilds = _count_rebuilds(monkeypatch)  # the file saved now is this database's: a start reads it
    again = Store(idx, vector_backend=backend, vector_options=options)
    assert again.vector_search("code", other[3], 1)[0].chunk_id == ids[3] and rebuilds == []
    again.close()


@pytest.mark.parametrize("backend, options", SAVED)
def test_another_index_s_file_under_this_index_s_note_is_not_read(tmp_path, monkeypatch, backend, options):
    """Two indexes of the same shape, and the saved file of one copied over the other's: by vector
    id it matches every row. The note beside it holds the checksum of other bytes."""
    vecs = {}
    for name, seed in (("a", 0), ("b", 9)):
        s = Store(tmp_path / name, vector_backend=backend, vector_options=options)
        ids = _add_chunks(s, 40)
        vecs[name] = _vecs(40, seed=seed)
        s.put_vectors("code", EMBEDDER, [VectorRow(c, 0, 1, 0, 1, f"h{c}") for c in ids], vecs[name])
        s.save_vectors()
        s.close()
    (saved,) = [p for p in (tmp_path / "a").glob("vec_code.*") if p.suffix != ".json"]
    shutil.copy(tmp_path / "b" / saved.name, saved)

    rebuilds = _count_rebuilds(monkeypatch)
    a = Store(tmp_path / "a", vector_backend=backend, vector_options=options)
    for i in range(0, 40, 4):
        hit = a.vector_search("code", vecs["a"][i], 1)[0]
        assert hit.chunk_id == ids[i] and hit.score == pytest.approx(1.0, abs=1e-3)
    assert len(rebuilds) == 1
    a.close()


@pytest.mark.parametrize("field", ["database", "save_id", "crc32"])
def test_a_saved_index_whose_note_lacks_what_a_start_checks_is_rebuilt_once(tmp_path, monkeypatch, field):
    idx = tmp_path / "idx"
    s = Store(idx, vector_backend="faiss")
    ids = _seed(s, 5)
    s.save_vectors()
    s.close()
    note = json.loads((idx / "vec_code.json").read_text())
    assert len(note["database"]) == len(note["save_id"]) == 32 and note["database"] != note["save_id"]
    assert note["crc32"] == zlib.crc32((idx / "vec_code.faiss").read_bytes())
    del note[field]
    (idx / "vec_code.json").write_text(json.dumps(note))  # as an index saved before notes held it

    rebuilds = _count_rebuilds(monkeypatch)
    s = Store(idx, vector_backend="faiss")
    assert s.vector_search("code", _vecs(5)[2], 1)[0].chunk_id == ids[2] and len(rebuilds) == 1
    s.save_vectors()
    s.close()
    s = Store(idx, vector_backend="faiss")
    assert s.vector_search("code", _vecs(5)[2], 1)[0].chunk_id == ids[2] and len(rebuilds) == 1
    again = json.loads((idx / "vec_code.json").read_text())
    assert again["database"] == s.database_id() and again["crc32"] == zlib.crc32((idx / "vec_code.faiss").read_bytes())
    assert again["save_id"] == s.get_meta("vec.code.save_id") != note.get("save_id")  # a new one for each save
    s.close()


def test_a_database_copied_without_its_identity_gets_its_own(tmp_path, monkeypatch):
    """Another index started from a backup of this one's database: the copy drops the
    `database_id` row, and the store gives it a new one. The original's saved files are not read
    into it, wherever they lie, although the copy holds the `save_id` they were saved with."""
    a = Store(tmp_path / "a", vector_backend="faiss")
    ids = _seed(a, 5)
    a.save_vectors()
    a.close()
    (tmp_path / "b").mkdir()
    source, copy = sqlite3.connect(tmp_path / "a" / "index.db"), sqlite3.connect(tmp_path / "b" / "index.db")
    with closing(source) as src, closing(copy) as dst:
        src.backup(dst)
        dst.execute("DELETE FROM meta WHERE key = 'database_id'")
        dst.commit()
    for saved in (tmp_path / "a").glob("vec_code*"):
        shutil.copy(saved, tmp_path / "b")

    rebuilds = _count_rebuilds(monkeypatch)
    a, b = Store(tmp_path / "a", vector_backend="faiss"), Store(tmp_path / "b", vector_backend="faiss")
    assert len(b.database_id()) == 32 and b.database_id() != a.database_id()
    assert b.get_meta("vec.code.save_id") == a.get_meta("vec.code.save_id") is not None
    assert a.vector_search("code", _vecs(5)[1], 1)[0].chunk_id == ids[1] and rebuilds == []  # its own file
    assert b.vector_search("code", _vecs(5)[1], 1)[0].chunk_id == ids[1] and len(rebuilds) == 1  # not the original's
    assert Store(tmp_path / "b").database_id() == b.database_id()  # and it keeps the one it got
    a.close(), b.close()


def _more(store, n, prefix, seed):
    """n more chunks with one vector each; returns the chunk ids and the vectors."""
    with store.transaction():
        ids = [store.upsert_chunk(_chunk(f"{prefix}{i:03d}")) for i in range(n)]
    vecs = _vecs(n, seed=seed)
    store.put_vectors("code", EMBEDDER, [VectorRow(c, 0, 1, 0, 1, f"{prefix}{c}") for c in ids], vecs)
    return ids, vecs


def _finds_each(store, ids, vecs):
    for chunk_id, vec in zip(ids, vecs):
        hit = store.vector_search("code", vec, 1)[0]
        assert hit.chunk_id == chunk_id and hit.score == pytest.approx(1.0, abs=1e-3)
    return True


@pytest.mark.parametrize("backend, options", SAVED)
@pytest.mark.parametrize("first", ["the vectors are written", "the index is used"])
def test_a_database_that_went_back_does_not_read_an_index_saved_after_it(tmp_path, monkeypatch, backend, options, first):
    """`index.db` restored to an earlier state (a backup put back, or its last commits lost in a
    power cut) under a search index that was saved later. The database hands out again the vector
    ids of the rows it lost, so the saved index holds other vectors under the new rows' ids."""
    idx, backup = tmp_path / "idx", tmp_path / "backup"
    s = Store(idx, vector_backend=backend, vector_options=options)
    ids = _seed(s, 40)
    s.save_vectors()
    s.close()
    backup.mkdir()
    for part in idx.glob("index.db*"):
        shutil.copy(part, backup)
    s = Store(idx, vector_backend=backend, vector_options=options)
    _more(s, 20, "lost", seed=7)
    s.load_vectors()
    s.save_vectors()
    assert json.loads((idx / "vec_code.json").read_text())["count"] == 60
    s.close()
    for part in idx.glob("index.db*"):
        part.unlink()
    for part in backup.iterdir():
        shutil.copy(part, idx)  # the database holds 40 again

    rebuilds = _count_rebuilds(monkeypatch)
    s = Store(idx, vector_backend=backend, vector_options=options)
    if first == "the index is used":
        assert _finds_each(s, ids[:3], _vecs(40)[:3])
    new, vecs = _more(s, 20, "new", seed=8)
    assert sorted(vid for vid, _ in s.vector_rows("code").values()) == list(range(1, 61))  # the lost rows' ids again
    assert _finds_each(s, new, vecs) and _finds_each(s, ids, _vecs(40)) and len(rebuilds) == 1
    s.save_vectors()
    s.close()
    s = Store(idx, vector_backend=backend, vector_options=options)  # the index saved now is of this state
    assert _finds_each(s, new, vecs) and len(rebuilds) == 1
    s.close()


@pytest.mark.parametrize("backend, options", SAVED)
@pytest.mark.parametrize("stopped, changed, rebuilt", [
    ("before the file is in place", [], 0),
    ("before the note is written", ["file"], 1),
    ("before the commit", ["file", "note"], 1),
])
def test_a_save_that_is_stopped_leaves_what_a_start_reads_right_or_rebuilds(tmp_path, monkeypatch, backend, options,
                                                                          stopped, changed, rebuilt):
    """The file, its note and the `save_id` in `meta` cannot change in one step. Wherever a save
    stops, the next start reads a file that is of this state of the database or of an earlier one,
    or it rebuilds. Here: the earlier file, which is behind the rows and is brought up to them;
    the new file under the earlier note; the new file and note under the earlier `save_id`."""
    from codemem import store as store_module

    idx = tmp_path / "idx"
    s = Store(idx, vector_backend=backend, vector_options=options)
    ids = _seed(s, 40)
    s.save_vectors()
    before = {p.name: p.read_bytes() for p in idx.glob("vec_code*")}
    earlier = s.get_meta("vec.code.save_id")
    new, vecs = _more(s, 5, "new", seed=3)

    class Stopped(BaseException):
        """As when the process is killed: nothing of the save runs after this."""

    set_meta, atomic_write = Store.set_meta, store_module._atomic_write

    def no_save_id(self, key, value):
        if key == "vec.code.save_id":
            raise Stopped
        set_meta(self, key, value)

    def no_note(path, data):
        if stopped == "before the commit":
            atomic_write(path, data)
        raise Stopped

    with monkeypatch.context() as m:
        if stopped == "before the file is in place":
            m.setattr(Store, "set_meta", no_save_id)
        else:
            m.setattr(store_module, "_atomic_write", no_note)
        with pytest.raises(Stopped):
            s.save_vectors()
    assert s.get_meta("vec.code.save_id") == earlier
    s.close()
    after = {p.name: p.read_bytes() for p in idx.glob("vec_code*")}
    assert set(after) == set(before)  # and no temporary file is left
    assert sorted("note" if name.endswith(".json") else "file" for name in after if after[name] != before[name]) == changed

    rebuilds = _count_rebuilds(monkeypatch)
    s = Store(idx, vector_backend=backend, vector_options=options)
    assert _finds_each(s, new, vecs) and _finds_each(s, ids, _vecs(40)) and len(rebuilds) == rebuilt
    s.save_vectors()
    s.close()
    s = Store(idx, vector_backend=backend, vector_options=options)
    assert _finds_each(s, new, vecs) and len(rebuilds) == rebuilt  # a save that ends is read
    s.close()


def test_two_processes_that_save_in_turn_each_leave_a_file_a_start_reads(tmp_path, monkeypatch):
    """Two stores on one folder stand in for two processes. One saves the index as it holds it,
    without the vectors the other wrote last: a start reads that file and adds the rows it lacks."""
    idx = tmp_path / "idx"
    a, b = Store(idx, vector_backend="faiss"), Store(idx, vector_backend="faiss")
    held = [(_seed(a, 10), _vecs(10))]
    a.save_vectors()
    rebuilds = _count_rebuilds(monkeypatch)
    for turn, (saver, other) in enumerate([(b, a), (a, b), (a, b), (b, a)]):
        held.append(_more(saver, 2, f"own{turn}", seed=10 + turn))
        assert all(_finds_each(saver, *vectors) for vectors in held)  # its index is in memory, and current
        held.append(_more(other, 2, f"other{turn}", seed=20 + turn))
        saver.save_vectors()
        note = json.loads((idx / "vec_code.json").read_text())
        assert note["save_id"] == other.get_meta("vec.code.save_id") and note["count"] == 10 + 4 * turn + 2
        start = Store(idx, vector_backend="faiss")
        assert all(_finds_each(start, *vectors) for vectors in held) and rebuilds == []
        start.close()
    a.close(), b.close()


# ---------------------------------------------------------------- the file a note names


@pytest.mark.parametrize("backend, options", SAVED)
@pytest.mark.parametrize("named, of_this_database", [
    ("../outside.bin", True), ("../outside.bin", False), ("{absolute}", True), ("sub/inside.bin", True),
    ("index.db", True), ("vec_usage{suffix}", True), ("vec_code.json", True), (7, True), (["vec_code{suffix}"], True),
    (None, True),
])
def test_a_note_names_no_file_but_its_own_index(tmp_path, monkeypatch, backend, options, named, of_this_database):
    """A note is a file in the index folder, and what it names is read by a start and deleted by
    a save and by `drop_vec_type`. Only the name a save gives that vector type's index counts.
    Any other note is no note: the index is rebuilt, and no file but the type's own is touched."""
    idx, outside = tmp_path / "idx", tmp_path / "outside.bin"
    s = Store(idx, vector_backend=backend, vector_options=options)
    ids = _seed(s, 40)
    with s.transaction():
        s.ensure_vec_type("usage", EMBEDDER)
    s.put_vectors("usage", EMBEDDER, [VectorRow(c, 0, 1, 0, 1, f"u{c}") for c in ids], _vecs(40, seed=1))
    s.save_vectors()
    s.close()
    note = json.loads((idx / "vec_code.json").read_text())
    suffix = note["file"][len("vec_code"):]
    (idx / "sub").mkdir()
    for copy in (outside, idx / "sub" / "inside.bin"):  # an index that could be read, where no note may reach
        shutil.copy(idx / note["file"], copy)
    if isinstance(named, str):
        named = named.format(suffix=suffix, absolute=outside)
    elif isinstance(named, list):
        named = [name.format(suffix=suffix) for name in named]
    bad = json.dumps({**note, "file": named, "database": note["database"] if of_this_database else "0" * 32})
    others = [outside, idx / "sub" / "inside.bin", idx / "index.db", idx / f"vec_usage{suffix}", idx / "vec_usage.json"]

    (idx / "vec_code.json").write_text(bad)
    rebuilds = _count_rebuilds(monkeypatch)
    s = Store(idx, vector_backend=backend, vector_options=options)
    assert _finds_each(s, ids, _vecs(40)) and [a[0] for a in rebuilds] == ["code"]  # the file it names is not read
    _more(s, 5, "new", seed=3)
    s.save_vectors()  # a save removes the file an earlier note described, when it is another backend's
    assert all(path.is_file() for path in others)
    assert json.loads((idx / "vec_code.json").read_text())["file"] == f"vec_code{suffix}"
    s.close()

    (idx / "vec_code.json").write_text(bad)
    s = Store(idx, vector_backend=backend, vector_options=options)
    with s.transaction():
        s.drop_vec_type("code")  # and so does dropping the type
    assert all(path.is_file() for path in others) and not list(idx.glob("vec_code*"))
    assert s.counts()["vectors"] == {"usage": 40}
    s.close()


@pytest.mark.parametrize("text", ["[1, 2]", '"vec_code.faiss"', "3", "null", "{}", '{"backend": ["compact"], "file": 3}', ""])
def test_a_note_that_is_not_what_a_save_writes_is_no_note(tmp_path, monkeypatch, text):
    idx = tmp_path / "idx"
    s = Store(idx, vector_backend="auto")
    ids = _seed(s, 5)
    s.save_vectors()
    s.close()
    (idx / "vec_code.json").write_text(text)
    rebuilds = _count_rebuilds(monkeypatch)
    s = Store(idx, vector_backend="auto")  # `auto` reads every note to see what the index was saved as
    assert s.search_index_status()["index"] == "faiss"
    assert s.vector_search("code", _vecs(5)[2], 1)[0].chunk_id == ids[2] and len(rebuilds) == 1
    s.save_vectors()
    with s.transaction():
        s.drop_vec_type("code")
    assert not list(idx.glob("vec_code*"))
    s.close()
