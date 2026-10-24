"""Full + incremental indexing (hash based), for every supported language.

`Indexer.update()` is the only entry point; a full index is just an update
over an empty store. Steps:
  1. scan files; detect added/changed/deleted by content hash (mtime+size pre-check)
  2. re-chunk changed files, diff chunks by `key`, update SQLite + FTS
  3. recompute call edges, rebuild every enabled text type, and store a vector for every text
     whose hash changed: reused from this index or the shared vector cache when the same text
     was embedded before, else computed by the model
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pathspec

from . import __version__
from .callgraph import resolve_edges
from .chunker import chunk_source
from .config import ALWAYS_SKIP_DIRS, DEFAULT_IGNORE, Config, codemem_home
from .embedder import Embedder, make_embedder
from .languages import EXTENSIONS, language_for_path
from .schema import Chunk, text_hash
from .store import FileRow, IndexLock, Store, VectorRow
from .texts import BuildContext, build_parts
from .vectorcache import VectorCache

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, int, int], None]  # (phase, done, total)
EmbedderFactory = Callable[[str, Config], Embedder]

_GENERATED = re.compile(rb"Code generated .{0,200}DO NOT EDIT|@generated\b")
_MINIFIABLE = frozenset({"javascript", "typescript", "tsx"})
_EMBED_GROUP = 256  # texts per model call; the model batches inside it


@dataclass
class FileState:
    rel: str
    abs_path: Path
    mtime: float
    size: int


@dataclass
class ScanResult:
    changed: list[tuple[FileState, bytes, str, str]] = field(default_factory=list)  # (file, data, hash, language)
    skipped: list[tuple[FileState, str, str, str]] = field(default_factory=list)  # (file, hash, language, reason)
    touched: list[tuple[FileState, FileRow]] = field(default_factory=list)  # same content, new mtime
    deleted: list[str] = field(default_factory=list)
    total: int = 0

    @property
    def is_clean(self) -> bool:
        return not (self.changed or self.deleted or self.skipped)


@dataclass
class IndexStats:
    files_scanned: int = 0
    files_changed: int = 0
    files_deleted: int = 0
    files_skipped: int = 0  # generated or minified (kept out of the index)
    chunks_added: int = 0
    chunks_updated: int = 0
    chunks_deleted: int = 0
    edges: int = 0
    embedded: dict[str, int] = field(default_factory=dict)  # vectors (re)written for changed texts
    model_embedded: dict[str, int] = field(default_factory=dict)  # of which the model computed
    reused: dict[str, int] = field(default_factory=dict)  # of which came from this index
    cache_hits: dict[str, int] = field(default_factory=dict)  # of which came from the vector cache
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


def indexed_extensions(config: Config) -> set[str]:
    """File extensions to read, for the configured languages (`.h` serves both C and C++)."""
    allowed = set(config.languages) if config.languages is not None else None
    exts = {ext for ext, lang in EXTENSIONS.items() if allowed is None or lang in allowed}
    if allowed is not None and allowed & {"c", "cpp"}:
        exts.add(".h")
    return exts


def walk_source_files(root: Path, config: Config, skip_dirs: set[Path] = frozenset()) -> dict[str, Path]:
    """Repo-relative (forward slash) path -> absolute path for every file in a supported language."""
    root = root.resolve()
    patterns = [*config.ignore, *(DEFAULT_IGNORE if config.use_default_ignore else ())]
    rules = IgnoreRules(root, patterns, {p.resolve() for p in skip_dirs})
    exts = indexed_extensions(config)
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
        for f in sorted(filenames):  # the OS file order would change chunk ids between machines
            if os.path.splitext(f)[1].lower() not in exts:
                continue
            rel = f"{rel_dir}/{f}" if rel_dir else f
            if not rules.ignored(rel, is_dir=False):
                out[rel] = abs_dir / f
    return out


def skip_reason(data: bytes, language: str, config: Config) -> str | None:
    """Why a readable source file is kept out of the index, or None."""
    head = data[:8192]
    if b"\0" in head:
        return "binary"
    if config.skip_generated and _GENERATED.search(data[:2048]):
        return "generated"
    if language in _MINIFIABLE and any(len(line) > 5000 for line in data[:262144].split(b"\n")):
        return "minified"
    return None


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
        vector_cache: VectorCache | None = None,
    ):
        self.root = Path(repo_root).resolve()
        self.store = store
        self.config = config
        self.embedder_factory = embedder_factory
        self.progress = progress or (lambda phase, done, total: None)
        self._cache = vector_cache

    # ---- scanning
    def scan(self) -> ScanResult:
        files = walk_source_files(self.root, self.config, skip_dirs={self.store.index_dir})
        known = self.store.get_files()
        allowed = set(self.config.languages) if self.config.languages is not None else None
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
            prev = known.get(rel)
            if prev and prev.mtime == st.st_mtime and prev.size == st.st_size:
                present.add(rel)
                continue  # quick pre-check: unchanged
            try:
                data = abs_path.read_bytes()
            except OSError as e:
                log.warning("cannot read %s: %s", rel, e)
                continue
            language = language_for_path(rel, data)
            if language is None or (allowed is not None and language not in allowed):
                continue
            present.add(rel)
            digest = hashlib.sha256(data).hexdigest()[:20]
            if prev and prev.content_hash == digest and prev.language == language:
                result.touched.append((state, prev))
                continue
            reason = skip_reason(data, language, self.config)
            if reason is not None:
                if not (prev and prev.status == "skipped" and prev.content_hash == digest):
                    result.skipped.append((state, digest, language, reason))
                continue
            result.changed.append((state, data, digest, language))
        result.deleted = sorted(set(known) - present)
        return result

    # ---- main entry
    def update(self, *, full: bool = False) -> IndexStats:
        with IndexLock(self.store.index_dir):
            try:
                return self._update(full)
            finally:
                if self._cache is not None:
                    self._cache.close()

    def _update(self, full: bool) -> IndexStats:
        stats = IndexStats()
        t_start = time.perf_counter()
        store = self.store
        if full:
            self._wipe()

        t = time.perf_counter()
        scan = self.scan()
        stats.files_scanned = scan.total
        stats.timings["scan"] = time.perf_counter() - t

        # 1-2. chunk changed files (outside the transaction), then apply the diff.
        t = time.perf_counter()
        parsed: list[tuple[FileState, str, str, list[Chunk]]] = []
        for i, (state, data, digest, language) in enumerate(scan.changed):
            self.progress("chunk", i, len(scan.changed))
            try:
                chunks = chunk_source(data, state.rel, language=language, max_block_lines=self.config.max_block_lines)
                parsed.append((state, digest, language, chunks))
            except Exception as e:  # never let one bad file kill the index
                log.exception("failed to chunk %s", state.rel)
                stats.errors.append(f"{state.rel}: {e}")
        stats.timings["chunk"] = time.perf_counter() - t

        t = time.perf_counter()
        with store.transaction():
            for state, prev in scan.touched:
                store.upsert_file(state.rel, prev.content_hash, state.mtime, state.size, prev.language, prev.status)
            for rel in scan.deleted:
                stats.chunks_deleted += len(store.delete_file(rel))
            for state, digest, language, reason in scan.skipped:
                log.info("skipping %s: %s", state.rel, reason)
                stats.chunks_deleted += len(store.delete_file(state.rel))
                store.upsert_file(state.rel, digest, state.mtime, state.size, language, "skipped")
            for state, digest, language, chunks in parsed:
                self._apply_file(state, digest, language, chunks, stats)
            # 3a. call edges are cheap: always recompute globally.
            edges = resolve_edges(store.definitions(), store.all_calls(), self.config.max_defs_per_name)
            store.replace_edges(edges)
            stats.edges = len(edges)
            stats.files_changed = len(parsed)
            stats.files_deleted = len(scan.deleted)
            stats.files_skipped = len(scan.skipped)
        stats.timings["write_chunks"] = time.perf_counter() - t

        # 3b. texts -> vectors, only where a text's hash changed.
        self._embed(stats)

        with store.transaction():
            store.set_meta("repo_path", str(self.root))
            store.set_meta("indexed_commit", git_head(self.root))
            store.set_meta("indexed_at", time.time())
            store.set_meta("codemem_version", __version__)
            store.set_meta("index_settings", self.config.index_settings())
            stats.timings["total"] = time.perf_counter() - t_start
            store.set_meta("last_update", stats.to_dict())
        if stats.chunks_deleted or stats.vectors_removed:
            store.vacuum_if_sparse()
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
            for table in ("chunks", "fts", "calls", "edges", "vectors", "files"):
                store.conn.execute(f"DELETE FROM {table}")
        store.save_vectors()

    def _apply_file(self, state: FileState, digest: str, language: str, chunks: list[Chunk], stats: IndexStats) -> None:
        store = self.store
        old = {c.key: c for c in store.chunks_for_path(state.rel)}
        for chunk in chunks:
            prev = old.pop(chunk.key, None)
            if prev is None:
                stats.chunks_added += 1
            elif (prev.content_hash, prev.start_line, prev.end_line, prev.docstring) == (
                chunk.content_hash, chunk.start_line, chunk.end_line, chunk.docstring,
            ):
                chunk.chunk_id = prev.chunk_id
                continue
            else:
                stats.chunks_updated += 1
            store.upsert_chunk(chunk)
        store.delete_chunks([c.chunk_id for c in old.values()])
        stats.chunks_deleted += len(old)
        store.upsert_file(state.rel, digest, state.mtime, state.size, language, "ok")

    def _build_context(self) -> BuildContext:
        commits: dict[str, list[str]] = {}
        if self.config.include_commits:
            head = git_head(self.root)
            if head:
                for rel in self.store.get_files():
                    commits[rel] = git_commit_subjects(self.root, rel, head)
        return BuildContext(
            callers=self.store.caller_refs(),
            commits=commits,
            max_items=self.config.max_usage_items,
            code_header=self.config.code_header,
            window_chars=self.config.effective_window_chars(),
            window_overlap_lines=self.config.window_overlap_lines,
        )

    def _vector_cache(self) -> VectorCache | None:
        if self.config.vector_cache == "off":
            return None
        if self._cache is None:
            self._cache = VectorCache(codemem_home() / "cache" / "vectors.db")
        return self._cache

    def _embed(self, stats: IndexStats) -> None:
        store, cfg = self.store, self.config
        t = time.perf_counter()
        ctx = self._build_context()
        vec_types = cfg.enabled_vec_types()
        embedders = {v: self.embedder_factory(cfg.vectors[v].model, cfg) for v in vec_types}
        todo: dict[str, list[tuple[VectorRow, str]]] = {v: [] for v in vec_types}
        with store.transaction():
            for vec_type in vec_types:
                store.ensure_vec_type(vec_type, embedders[vec_type].key, cfg.embedding_dim)
            existing = {v: store.vector_rows(v) for v in vec_types}
            seen: dict[str, set[tuple[int, int]]] = {v: set() for v in vec_types}
            for chunk in store.iter_chunks():
                for vec_type in vec_types:
                    for part in build_parts(chunk, ctx, vec_type):
                        h = text_hash(part.text)
                        key = (chunk.chunk_id, part.part)
                        seen[vec_type].add(key)
                        prev = existing[vec_type].get(key)
                        if prev is None or prev[1] != h:
                            row = VectorRow(chunk.chunk_id, part.part, part.n_parts, part.start_off, part.end_off, h)
                            todo[vec_type].append((row, part.text))
            for vec_type in vec_types:
                # A text disappeared (a function lost its last caller, a long one got shorter).
                stale = [vid for key, (vid, _) in existing[vec_type].items() if key not in seen[vec_type]]
                store.delete_vectors(vec_type, stale)
                if stale:
                    stats.vectors_removed[vec_type] = len(stale)
        stats.timings["build_texts"] = time.perf_counter() - t

        cache = self._vector_cache()
        t_embed = 0.0
        t_write = 0.0
        total = sum(len(v) for v in todo.values())
        done = 0
        last_save = time.monotonic()
        for vec_type, items in todo.items():
            stats.embedded[vec_type] = len(items)
            stats.model_embedded[vec_type] = stats.reused[vec_type] = stats.cache_hits[vec_type] = 0
            if not items:
                continue
            embedder = embedders[vec_type]
            key = embedder.key
            rows_by_hash: dict[str, list[VectorRow]] = defaultdict(list)
            text_of: dict[str, str] = {}
            for row, text in items:
                rows_by_hash[row.text_hash].append(row)
                text_of[row.text_hash] = text

            def write(hashes: list[str], vecs: dict[str, np.ndarray]) -> None:
                nonlocal t_write, done, last_save
                t0 = time.perf_counter()
                rows = [r for h in hashes for r in rows_by_hash[h]]
                if rows:
                    store.put_vectors(vec_type, key, rows, np.stack([vecs[r.text_hash] for r in rows]))
                done += len(rows)
                self.progress("embed", done, total)
                if time.monotonic() - last_save > 60:  # long first index: checkpoint the search index
                    store.save_vectors()
                    last_save = time.monotonic()
                t_write += time.perf_counter() - t0

            found = store.find_vectors(key, rows_by_hash)
            stats.reused[vec_type] = sum(len(rows_by_hash[h]) for h in found)
            missing = [h for h in rows_by_hash if h not in found]
            if cache is not None and missing:
                cached = cache.get_many(key, missing)
                stats.cache_hits[vec_type] = sum(len(rows_by_hash[h]) for h in cached)
                found.update(cached)
                missing = [h for h in missing if h not in cached]
            if found:
                write(list(found), found)
            # Longest first: batches of similar length waste less padding.
            missing.sort(key=lambda h: len(text_of[h]), reverse=True)
            for start in range(0, len(missing), _EMBED_GROUP):
                group = missing[start : start + _EMBED_GROUP]
                t0 = time.perf_counter()
                vecs = embedder.embed_documents([text_of[h] for h in group])
                t_embed += time.perf_counter() - t0
                stats.model_embedded[vec_type] += len(group)
                if cache is not None:
                    cache.put_many(key, group, vecs)
                write(group, dict(zip(group, vecs)))
        t = time.perf_counter()
        store.save_vectors()
        stats.timings["embed"] = t_embed
        stats.timings["write_vectors"] = t_write + time.perf_counter() - t
