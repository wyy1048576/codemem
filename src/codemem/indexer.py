"""Full + incremental indexing (hash based).

`Indexer.update()` is the only entry point; a full index is just an update
over an empty store. Steps:
  1. scan files; detect added/changed/deleted by content hash (mtime+size pre-check)
  2. re-chunk changed files, diff chunks by `key`, update SQLite + FTS
  3. recompute call edges, rebuild every enabled text type, re-embed texts whose hash changed
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pathspec

from .callgraph import resolve_edges
from .chunker import chunk_source
from .config import ALWAYS_SKIP_DIRS, Config, VectorConfig
from .embedder import Embedder, make_embedder
from .schema import Chunk, text_hash
from .store import IndexLock, Store
from .texts import BuildContext, build_texts

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, int, int], None]  # (phase, done, total)
EmbedderFactory = Callable[[VectorConfig, Config], Embedder]


@dataclass
class FileState:
    rel: str
    abs_path: Path
    mtime: float
    size: int


@dataclass
class ScanResult:
    changed: list[tuple[FileState, bytes, str]] = field(default_factory=list)  # (file, data, hash)
    touched: list[tuple[FileState, str]] = field(default_factory=list)  # same hash, new mtime
    deleted: list[str] = field(default_factory=list)
    total: int = 0

    @property
    def is_clean(self) -> bool:
        return not (self.changed or self.deleted)


@dataclass
class IndexStats:
    files_scanned: int = 0
    files_changed: int = 0
    files_deleted: int = 0
    chunks_added: int = 0
    chunks_updated: int = 0
    chunks_deleted: int = 0
    edges: int = 0
    embedded: dict[str, int] = field(default_factory=dict)
    vectors_removed: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- file walking


class IgnoreRules:
    """.gitignore files (root and nested) + always-skip dirs + config extras."""

    def __init__(self, root: Path, extra: list[str], skip_dirs: set[Path]):
        self.root = root
        self.specs: dict[str, pathspec.PathSpec] = {}
        self.skip_dirs = {os.path.normcase(str(p)) for p in skip_dirs}
        if extra:
            self.specs[""] = pathspec.GitIgnoreSpec.from_lines(extra)

    def load_dir(self, rel_dir: str, abs_dir: Path) -> None:
        gi = abs_dir / ".gitignore"
        if gi.is_file():
            try:
                lines = gi.read_text("utf-8", errors="replace").splitlines()
            except OSError:
                return
            spec = pathspec.GitIgnoreSpec.from_lines(lines)
            if rel_dir in self.specs:  # root: merge with config extras
                spec = self.specs[rel_dir] + spec
            self.specs[rel_dir] = spec

    def ignored(self, rel: str, is_dir: bool) -> bool:
        for base, spec in self.specs.items():
            if base and not rel.startswith(base + "/"):
                continue
            sub = rel[len(base) + 1 :] if base else rel
            if spec.match_file(sub + "/" if is_dir else sub):
                return True
        return False

    def skip_dir(self, name: str, abs_dir: Path) -> bool:
        return name in ALWAYS_SKIP_DIRS or os.path.normcase(str(abs_dir)) in self.skip_dirs


def walk_python_files(root: Path, config: Config, skip_dirs: set[Path] = frozenset()) -> dict[str, Path]:
    """Repo-relative (forward slash) path -> absolute path for every indexable .py file."""
    root = root.resolve()
    rules = IgnoreRules(root, config.ignore, {p.resolve() for p in skip_dirs})
    out: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        abs_dir = Path(dirpath)
        rel_dir = abs_dir.relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        rules.load_dir(rel_dir, abs_dir)
        keep = []
        for d in sorted(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if rules.skip_dir(d, abs_dir / d) or rules.ignored(rel, is_dir=True):
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in filenames:
            if not f.endswith(".py"):
                continue
            rel = f"{rel_dir}/{f}" if rel_dir else f
            if not rules.ignored(rel, is_dir=False):
                out[rel] = abs_dir / f
    return out


def git_head(root: Path) -> str | None:
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout.strip() or None


def git_commit_subjects(root: Path, rel: str, commit: str, n: int = 5) -> list[str]:
    """Commit subjects touching `rel`, only up to `commit` (no future leakage for evals)."""
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "log", f"-n{n}", "--format=%s", commit, "--", rel],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [s for s in res.stdout.splitlines() if s.strip()] if res.returncode == 0 else []


# --------------------------------------------------------------------------- indexer


class Indexer:
    def __init__(
        self,
        repo_root: Path | str,
        store: Store,
        config: Config,
        *,
        embedder_factory: EmbedderFactory = make_embedder,
        progress: ProgressFn | None = None,
    ):
        self.root = Path(repo_root).resolve()
        self.store = store
        self.config = config
        self.embedder_factory = embedder_factory
        self.progress = progress or (lambda phase, done, total: None)

    # ---- scanning
    def scan(self) -> ScanResult:
        files = walk_python_files(self.root, self.config, skip_dirs={self.store.index_dir})
        known = self.store.get_files()
        result = ScanResult(total=len(files))
        present: set[str] = set()
        for rel, abs_path in files.items():
            try:
                st = abs_path.stat()
            except OSError:
                continue
            state = FileState(rel, abs_path, st.st_mtime, st.st_size)
            if st.st_size > self.config.max_file_size:
                log.info("skipping %s: %d bytes > max_file_size", rel, st.st_size)
                continue
            present.add(rel)
            prev = known.get(rel)
            if prev and prev[1] == st.st_mtime and prev[2] == st.st_size:
                continue  # quick pre-check: unchanged
            try:
                data = abs_path.read_bytes()
            except OSError as e:
                log.warning("cannot read %s: %s", rel, e)
                continue
            digest = hashlib.sha256(data).hexdigest()[:20]
            if prev and prev[0] == digest:
                result.touched.append((state, digest))
            else:
                result.changed.append((state, data, digest))
        result.deleted = sorted(set(known) - present)
        return result

    # ---- main entry
    def update(self, *, full: bool = False) -> IndexStats:
        with IndexLock(self.store.index_dir):
            return self._update(full)

    def _update(self, full: bool) -> IndexStats:
        stats = IndexStats()
        t_start = time.perf_counter()
        store = self.store
        with store.transaction():
            store.ensure_backend()
        if full:
            self._wipe()
        else:
            with store.transaction():
                store.reconcile()

        t = time.perf_counter()
        scan = self.scan()
        stats.files_scanned = scan.total
        stats.timings["scan"] = time.perf_counter() - t

        # 1-2. chunk changed files (outside the transaction), then apply the diff.
        t = time.perf_counter()
        parsed: list[tuple[FileState, str, list[Chunk]]] = []
        for i, (state, data, digest) in enumerate(scan.changed):
            self.progress("chunk", i, len(scan.changed))
            try:
                parsed.append((state, digest, chunk_source(data, state.rel)))
            except Exception as e:  # never let one bad file kill the index
                log.exception("failed to chunk %s", state.rel)
                stats.errors.append(f"{state.rel}: {e}")
        stats.timings["chunk"] = time.perf_counter() - t

        t = time.perf_counter()
        with store.transaction():
            for state, digest in scan.touched:
                store.upsert_file(state.rel, digest, state.mtime, state.size)
            for rel in scan.deleted:
                stats.chunks_deleted += len(store.delete_file(rel))
            for state, digest, chunks in parsed:
                self._apply_file(state, digest, chunks, stats)
            # 3a. call edges are cheap: always recompute globally.
            edges = resolve_edges(store.definitions(), store.all_calls(), self.config.max_defs_per_name)
            store.replace_edges(edges)
            stats.edges = len(edges)
            stats.files_changed = len(parsed)
            stats.files_deleted = len(scan.deleted)
        stats.timings["write_chunks"] = time.perf_counter() - t

        # 3b. texts -> embeddings, only where the text hash changed.
        self._embed(stats)

        with store.transaction():
            store.set_meta("repo_path", str(self.root))
            store.set_meta("indexed_commit", git_head(self.root))
            store.set_meta("indexed_at", time.time())
            stats.timings["total"] = time.perf_counter() - t_start
            store.set_meta("last_update", stats.to_dict())
        self.progress("done", 1, 1)
        log.info(
            "indexed %s: %d files changed, %d deleted, embedded %s in %.2fs",
            self.root, stats.files_changed, stats.files_deleted, stats.embedded, stats.timings["total"],
        )
        return stats

    def _wipe(self) -> None:
        store = self.store
        with store.transaction():
            for vec_type in store.vec_types():
                store.drop_vec_type(vec_type)
            for table in ("chunks", "fts", "calls", "edges", "embeddings", "files"):
                store.conn.execute(f"DELETE FROM {table}")
        store.save_vectors()

    def _apply_file(self, state: FileState, digest: str, chunks: list[Chunk], stats: IndexStats) -> None:
        store = self.store
        old = {c.key: c for c in store.chunks_for_path(state.rel)}
        for chunk in chunks:
            prev = old.pop(chunk.key, None)
            if prev is None:
                stats.chunks_added += 1
            elif (prev.content_hash, prev.start_line, prev.end_line) == (
                chunk.content_hash, chunk.start_line, chunk.end_line,
            ):
                chunk.chunk_id = prev.chunk_id
                continue
            else:
                stats.chunks_updated += 1
            store.upsert_chunk(chunk)
        store.delete_chunks([c.chunk_id for c in old.values()])
        stats.chunks_deleted += len(old)
        store.upsert_file(state.rel, digest, state.mtime, state.size)

    def _build_context(self) -> BuildContext:
        commits: dict[str, list[str]] = {}
        if self.config.include_commits:
            head = git_head(self.root)
            if head:
                for rel in self.store.get_files():
                    commits[rel] = git_commit_subjects(self.root, rel, head)
        return BuildContext(
            callers=self.store.caller_refs(), commits=commits, max_items=self.config.max_usage_items
        )

    def _embed(self, stats: IndexStats) -> None:
        store, cfg = self.store, self.config
        t = time.perf_counter()
        ctx = self._build_context()
        vec_types = cfg.enabled_vec_types()
        todo: dict[str, list[tuple[int, str, str]]] = {v: [] for v in vec_types}
        with store.transaction():
            for vec_type in vec_types:
                store.ensure_vec_type(vec_type, cfg.model_id(vec_type))
            existing = {v: store.embedding_hashes(v) for v in vec_types}
            stale: dict[str, list[int]] = {v: [] for v in vec_types}
            seen: dict[str, set[int]] = {v: set() for v in vec_types}
            for chunk in store.iter_chunks():
                texts = build_texts(chunk, ctx, vec_types)
                for vec_type in vec_types:
                    text = texts.get(vec_type)
                    if text is None:
                        continue
                    seen[vec_type].add(chunk.chunk_id)
                    h = text_hash(text)
                    if existing[vec_type].get(chunk.chunk_id) != h:
                        todo[vec_type].append((chunk.chunk_id, h, text))
            for vec_type in vec_types:
                # Text disappeared (e.g. a function lost its last caller): drop the vector.
                stale[vec_type] = [i for i in existing[vec_type] if i not in seen[vec_type]]
                store.remove_embeddings(vec_type, stale[vec_type])
                if stale[vec_type]:
                    stats.vectors_removed[vec_type] = len(stale[vec_type])
        stats.timings["build_texts"] = time.perf_counter() - t

        t_embed = 0.0
        t_write = 0.0
        total = sum(len(v) for v in todo.values())
        done = 0
        last_save = time.monotonic()
        max_chars = max(cfg.max_seq_length * 6, 2000)
        step = max(cfg.batch_size * 8, 1)
        for vec_type, items in todo.items():
            stats.embedded[vec_type] = len(items)
            if not items:
                continue
            embedder = self.embedder_factory(cfg.vectors[vec_type], cfg)
            model_id = cfg.model_id(vec_type)
            for start in range(0, len(items), step):
                batch = items[start : start + step]
                self.progress("embed", done, total)
                t = time.perf_counter()
                vecs = embedder.embed_documents([text[:max_chars] for _, _, text in batch])
                t_embed += time.perf_counter() - t
                t = time.perf_counter()
                with store.transaction():
                    store.put_embeddings(vec_type, model_id, [i for i, _, _ in batch], [h for _, h, _ in batch], vecs)
                if time.monotonic() - last_save > 60:  # long first index: checkpoint vectors
                    store.save_vectors()
                    last_save = time.monotonic()
                t_write += time.perf_counter() - t
                done += len(batch)
        t = time.perf_counter()
        store.save_vectors()
        stats.timings["embed"] = t_embed
        stats.timings["write_vectors"] = t_write + time.perf_counter() - t
