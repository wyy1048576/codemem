"""Indexing: one update function for the first build, a reconcile and a single save.

An update runs in two stages (docs/architecture.md §8):

  A. structure (`structure()`): find the changed files (the watcher's paths, or a scan of the
     whole repo), re-chunk them, apply each file's chunk diff by key, relink only the calls that
     can have changed, and queue every chunk whose texts may have changed (table `dirty_texts`).
     One transaction, under the write lock; it takes milliseconds per changed file.
  B. vectors (`embed_pending()`): drain the queue in batches. Rebuild the queued chunks' texts and
     store a vector for every text whose hash (or line range) changed: from this index, the shared
     vector cache, or else the model. The model runs outside the lock, so stage A can run in
     between, and the queue survives a crash.

A full build is the same code over an empty index. `verify()` compares the index with a fresh build
of the same files; the tests use it to check that incremental updates are exact.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pathspec

from . import __version__
from .callgraph import resolve_edges
from .chunker import chunk_source
from .config import ALWAYS_SKIP_DIRS, DEFAULT_IGNORE, Config, codemem_home
from .embedder import Embedder, make_embedder
from .languages import EXTENSIONS, LANGUAGES, language_for_path
from .schema import CALLABLE_KINDS, Chunk, text_hash
from .store import FileRow, IndexLock, Store, VectorRow, diff_snapshots
from .texts import BuildContext, build_parts
from .vectorcache import VectorCache

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, int, int], None]  # (phase, done, total)
EmbedderFactory = Callable[[str, Config], Embedder]

_GENERATED = re.compile(rb"Code generated .{0,200}DO NOT EDIT|@generated\b")
_MINIFIABLE = frozenset({"javascript", "typescript", "tsx"})
_EMBED_GROUP = 256  # texts per model call in a build; the model batches inside it
_BATCH_CHUNKS = 512  # queued chunks per stage-B batch
_RACY_SECONDS = 2.0  # a file this close to the last scan may have changed again within its mtime tick

# How much of an index a change of each index-time setting (Config.index_settings()) invalidates.
# Anything not listed (chunker version, file selection, BM25 tokenization, block size) rebuilds it.
_SETTING_TIERS = {
    "vectors": "vectors", "embedding_dim": "vectors", "dtype": "vectors", "batch_size": "vectors",
    "text_format": "texts", "max_seq_length": "texts", "code_header": "texts", "window_chars": "texts",
    "window_overlap_lines": "texts", "max_usage_items": "texts", "include_commits": "texts",
    "max_defs_per_name": "links",
}


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
    coverage: dict[str, Any] | None = None  # from a full scan: what the walk did not index, and why

    @property
    def is_clean(self) -> bool:
        return not (self.changed or self.deleted or self.skipped)


@dataclass
class IndexStats:
    files_scanned: int = 0
    files_changed: int = 0
    files_deleted: int = 0
    files_skipped: int = 0  # too large, generated, minified or binary (recorded with the reason)
    chunks_added: int = 0
    chunks_updated: int = 0
    chunks_deleted: int = 0
    chunks_moved: int = 0  # unchanged chunks whose line numbers shifted (nothing else is rewritten)
    edges: int = 0
    relinked: int = 0  # chunks whose outgoing calls were resolved again
    queued: int = 0  # chunks whose texts were queued for stage B
    pending: int = 0  # queued chunks not embedded yet when the update returned
    embedded: dict[str, int] = field(default_factory=dict)  # vectors (re)written for changed texts
    model_embedded: dict[str, int] = field(default_factory=dict)  # of which the model computed
    reused: dict[str, int] = field(default_factory=dict)  # of which came from this index
    cache_hits: dict[str, int] = field(default_factory=dict)  # of which came from the vector cache
    vectors_removed: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)  # chunked from what tree-sitter could recover
    timings: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def add_time(self, key: str, seconds: float) -> None:
        self.timings[key] = self.timings.get(key, 0.0) + seconds


# --------------------------------------------------------------------------- file walking


class IgnoreRules:
    """.gitignore files (root and nested) + always-skip dirs + config extras."""

    def __init__(self, root: Path, extra: list[str], skip_dirs: set[Path]):
        self.root = root
        self.specs: dict[str, pathspec.PathSpec] = {}
        self.skip_dirs = {os.path.normcase(str(p)) for p in skip_dirs}
        self.loaded: set[str] = set()
        if extra:
            self.specs[""] = pathspec.GitIgnoreSpec.from_lines(extra)

    def load_dir(self, rel_dir: str, abs_dir: Path) -> None:
        self.loaded.add(rel_dir)
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

    def ensure_dir(self, rel_dir: str) -> None:
        if rel_dir not in self.loaded:
            self.load_dir(rel_dir, self.root / rel_dir if rel_dir else self.root)

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

    def allows(self, rel: str) -> bool:
        """Whether the walk would reach the file `rel`: no ancestor folder skipped or ignored, and
        the file itself not ignored. The single rule for the walk, the watcher and path updates."""
        parts = rel.split("/")
        for i in range(len(parts) - 1):
            parent, d = "/".join(parts[:i]), "/".join(parts[: i + 1])
            self.ensure_dir(parent)
            if self.skip_dir(parts[i], self.root / d) or self.ignored(d, is_dir=True):
                return False
        self.ensure_dir("/".join(parts[:-1]))
        return not self.ignored(rel, is_dir=False)


def _rules_for(root: Path, config: Config, skip_dirs: Iterable[Path]) -> IgnoreRules:
    patterns = [*config.ignore, *(DEFAULT_IGNORE if config.use_default_ignore else ())]
    return IgnoreRules(root, patterns, {Path(p).resolve() for p in skip_dirs})


def indexed_extensions(config: Config) -> set[str]:
    """File extensions to read, for the configured languages (`.h` serves both C and C++)."""
    allowed = set(config.languages) if config.languages is not None else None
    exts = {ext for ext, lang in EXTENSIONS.items() if allowed is None or lang in allowed}
    if allowed is not None and allowed & {"c", "cpp"}:
        exts.add(".h")
    return exts


def walk_repo(root: Path, config: Config, skip_dirs: Iterable[Path] = ()) -> tuple[dict[str, Path], dict[str, Any]]:
    """Every file the index should read (repo-relative path -> absolute path), and the coverage:
    how many folders and files were left out and why. Skipped folders are counted, never entered."""
    root = root.resolve()
    rules = _rules_for(root, config, skip_dirs)
    exts = indexed_extensions(config)
    out: dict[str, Path] = {}
    skipped_dirs: Counter[str] = Counter()
    ignored_files = 0
    not_code: Counter[str] = Counter()
    for dirpath, dirnames, filenames in os.walk(root):
        abs_dir = Path(dirpath)
        rel_dir = abs_dir.relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        rules.load_dir(rel_dir, abs_dir)
        keep = []
        for d in sorted(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if rules.skip_dir(d, abs_dir / d):
                skipped_dirs[d] += 1
            elif rules.ignored(rel, is_dir=True):
                skipped_dirs["(ignored)"] += 1
            else:
                keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):  # the OS file order would change chunk ids between machines
            rel = f"{rel_dir}/{f}" if rel_dir else f
            ext = os.path.splitext(f)[1].lower()
            if ext not in exts:
                not_code[ext or "(none)"] += 1
            elif rules.ignored(rel, is_dir=False):
                ignored_files += 1
            else:
                out[rel] = abs_dir / f
    coverage = {
        "skipped_dirs": dict(skipped_dirs.most_common(10)),
        "ignored_files": ignored_files,
        "not_code_files": sum(not_code.values()),
        "not_code_by_extension": dict(not_code.most_common(10)),
    }
    return out, coverage


def walk_source_files(root: Path, config: Config, skip_dirs: set[Path] = frozenset()) -> dict[str, Path]:
    """Repo-relative (forward slash) path -> absolute path for every file in a supported language."""
    return walk_repo(root, config, skip_dirs)[0]


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


def _exists_exactly(path: Path) -> bool:
    """`path` exists with exactly this name. On a case-insensitive disk, `stat("Foo.py")` still
    succeeds after a rename to `foo.py`, and the old path would never be seen as deleted."""
    try:
        return path.is_file() and path.name in os.listdir(path.parent)
    except OSError:
        return False


# --------------------------------------------------------------------------- indexer


def _content_fields(c: Chunk) -> tuple:
    """Every chunk field the store keeps except its id and its position. A chunk whose parent (a
    `#2` key renumbered) or language (a `.h` file now read as C++) changed must be rewritten, or an
    updated index would differ from a rebuilt one. Texts depend on these fields only."""
    return (
        c.key, c.path, c.language, c.kind, c.subkind, c.name, c.qualname, c.class_name, c.parent_key,
        c.signature, c.docstring, c.lead_comment, c.content_hash, c.skeleton, c.is_test,
    )


def _moved_by(prev: Chunk, chunk: Chunk) -> int | None:
    """How many lines a chunk moved (0: not at all), when moving is all that changed; None if more
    changed. Same content means its calls moved by as many lines too."""
    delta = chunk.start_line - prev.start_line
    if chunk.end_line - prev.end_line != delta or _content_fields(prev) != _content_fields(chunk):
        return None
    return delta


def _order(chunks: Iterable[Chunk], keys: set[str]) -> list[str]:
    return [c.key for c in sorted(chunks, key=lambda c: (c.start_line, c.key)) if c.key in keys]


def _model_calls(hashes: list[str], text_of: dict[str, str], size: int, chars: int | None) -> Iterator[list[str]]:
    """Consecutive runs of at most `size` texts and, if set, `chars` characters (a longer text
    goes alone): one model call each."""
    run: list[str] = []
    total = 0
    for h in hashes:
        n = len(text_of[h])
        if run and (len(run) >= size or (chars is not None and total + n > chars)):
            yield run
            run, total = [], 0
        run.append(h)
        total += n
    if run:
        yield run


def _family(language: str) -> str:
    spec = LANGUAGES.get(language)
    return spec.family if spec else language


def _definitions(chunks: Iterable[Chunk]) -> dict[tuple[str, str], set[int]]:
    """(language family, name) -> ids of the chunks a call by that name can resolve to."""
    out: dict[tuple[str, str], set[int]] = defaultdict(set)
    for c in chunks:
        if c.kind in CALLABLE_KINDS and c.chunk_id is not None:
            out[(_family(c.language), c.name)].add(c.chunk_id)
    return out


@dataclass
class _TypeWork:
    """One vector type's part of a stage-B batch."""

    embedder: Embedder
    key: str
    rows_by_hash: dict[str, list[VectorRow]]
    text_of: dict[str, str]
    vectors: dict[str, np.ndarray]  # text hash -> vector, filled before the batch is stored
    missing: list[str]  # text hashes only the model can provide
    stale: list[tuple[int, int]]  # (vector_id, chunk_id) of texts that no longer exist
    from_index: set[str] = field(default_factory=set)  # hashes whose vector this index already had
    from_cache: set[str] = field(default_factory=set)  # hashes found in the shared vector cache


@dataclass
class _Batch:
    seqs: dict[int, int]  # chunk id -> the sequence number it was queued with
    work: dict[str, _TypeWork]
    build_time: float = 0.0  # seconds spent building texts and looking vectors up


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
        write_lock: threading.RLock | None = None,
    ):
        self.root = Path(repo_root).resolve()
        self.store = store
        self.config = config
        self.embedder_factory = embedder_factory
        self.progress = progress or (lambda phase, done, total: None)
        self._cache = vector_cache
        self._write_lock = write_lock or threading.RLock()  # shared by every thread that writes this index
        self._local = threading.local()
        self._rules: IgnoreRules | None = None
        self._claimed: set[int] = set()  # queued chunk ids a stage-B batch of this process is embedding
        self._claim_lock = threading.Lock()
        self._model_lock = threading.Lock()  # one model call at a time; a search waits only up to its budget
        self._searches = 0  # searches catching up right now: background batches hand them the model
        self._sec_per_char: float | None = None  # the model's measured speed (moving average)
        self._speed_warm = False  # the first call loads and warms the model: not a speed sample

    def _seconds_for(self, chars: int) -> float:
        """Estimated model time for a call of `chars` characters (0 until measured)."""
        return chars * self._sec_per_char if self._sec_per_char is not None else 0.0

    def _observe_speed(self, chars: int, seconds: float) -> None:
        if chars <= 0:
            return
        if not self._speed_warm:
            self._speed_warm = True
            return
        rate = seconds / chars
        self._sec_per_char = rate if self._sec_per_char is None else 0.7 * self._sec_per_char + 0.3 * rate

    @contextmanager
    def searching(self) -> Iterator[None]:
        """A search is catching up: background embedding (its `stop` asks `searches_waiting`) stops
        at its next model call, so the search waits for one call at most."""
        with self._claim_lock:
            self._searches += 1
        try:
            yield
        finally:
            with self._claim_lock:
                self._searches -= 1

    @property
    def searches_waiting(self) -> bool:
        return self._searches > 0

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """The in-process write lock, plus the cross-process lock file (taken once per thread)."""
        with self._write_lock:
            depth = getattr(self._local, "depth", 0)
            lock = IndexLock(self.store.index_dir) if depth == 0 else None
            if lock is not None:
                lock.acquire()
            self._local.depth = depth + 1
            try:
                yield
            finally:
                self._local.depth = depth
                if lock is not None:
                    lock.release()

    # ---- finding changed files
    def ignore_rules(self) -> IgnoreRules:
        if self._rules is None:
            self._rules = _rules_for(self.root, self.config, {self.store.index_dir})
        return self._rules

    def reset_rules(self) -> None:
        """Forget cached ignore rules (after a `.gitignore` or config change)."""
        self._rules = None

    def allows(self, rel: str) -> bool:
        """Whether `rel` is a file the index should read (path rules only; content rules apply later)."""
        return os.path.splitext(rel)[1].lower() in indexed_extensions(self.config) and self.ignore_rules().allows(rel)

    def _classify(
        self, rel: str, abs_path: Path, prev: FileRow | None, result: ScanResult, present: set[str], *, trust_mtime: bool,
    ) -> None:
        """Decide what one file needs: nothing, a new date (touched), skipping, or re-chunking."""
        try:
            st = abs_path.stat()
        except OSError:
            return
        state = FileState(rel, abs_path, st.st_mtime, st.st_size)
        if st.st_size > self.config.max_file_size:
            present.add(rel)
            if not (prev and prev.reason == "too_large" and prev.size == st.st_size and prev.mtime == st.st_mtime):
                result.skipped.append((state, "", language_for_path(rel) or "", "too_large"))
            return
        if trust_mtime and prev and prev.mtime == st.st_mtime and prev.size == st.st_size:
            present.add(rel)
            return  # quick pre-check: unchanged
        try:
            data = abs_path.read_bytes()
        except OSError as e:
            log.warning("cannot read %s: %s", rel, e)
            return
        language = language_for_path(rel, data)
        if language is None or (self.config.languages is not None and language not in self.config.languages):
            return
        present.add(rel)
        digest = hashlib.sha256(data).hexdigest()[:20]
        if prev and prev.content_hash == digest and prev.language == language:
            if (prev.mtime, prev.size) != (st.st_mtime, st.st_size):
                result.touched.append((state, prev))
            return
        reason = skip_reason(data, language, self.config)
        if reason is not None:
            result.skipped.append((state, digest, language, reason))
            return
        result.changed.append((state, data, digest, language))

    def scan(self) -> ScanResult:
        """The whole repo: every file the walk reaches, checked by size and date, then by hash."""
        files, coverage = walk_repo(self.root, self.config, skip_dirs={self.store.index_dir})
        known = self.store.get_files()
        last_scan = float(self.store.get_meta("last_scan_at", 0) or 0)
        result = ScanResult(total=len(files), coverage=coverage)
        present: set[str] = set()
        for rel, abs_path in files.items():
            prev = known.get(rel)
            # A file saved within the same mtime tick as the last scan may have changed again since.
            trust = prev is not None and prev.mtime < last_scan - _RACY_SECONDS
            self._classify(rel, abs_path, prev, result, present, trust_mtime=trust)
        result.deleted = sorted(set(known) - present)
        return result

    def scan_paths(self, paths: Iterable[str | Path]) -> ScanResult:
        """Only these paths (files or folders, as the watcher reports them), always read and hashed:
        a same-size edit within one mtime tick would pass the size-and-date check."""
        known = self.store.get_files()
        rules = self.ignore_rules()
        candidates: set[str] = set()
        for p in paths:
            rel = self._relative(p)
            if not rel:
                continue
            abs_path = self.root / rel
            if abs_path.is_dir():
                candidates.update(self._files_under(rel, rules))
            candidates.update(self.store.file_paths_under(rel))  # a moved or deleted folder
            candidates.add(rel)
        result = ScanResult(total=len(candidates))
        present: set[str] = set()
        for rel in sorted(candidates):
            if rel not in known and (not self.allows(rel) or not (self.root / rel).is_file()):
                continue
            abs_path = self.root / rel
            if not self.allows(rel) or not _exists_exactly(abs_path):
                result.deleted.append(rel)
                continue
            self._classify(rel, abs_path, known.get(rel), result, present, trust_mtime=False)
            if rel in known and rel not in present:
                result.deleted.append(rel)  # unreadable now, or no longer a supported language
        result.deleted = sorted(set(result.deleted))
        return result

    def _relative(self, path: str | Path) -> str | None:
        p = Path(path)
        if p.is_absolute():
            try:
                p = p.resolve().relative_to(self.root) if p.exists() else p.relative_to(self.root)
            except ValueError:
                return None
        rel = p.as_posix().removeprefix("./")
        return None if rel in ("", ".") or rel.startswith("../") else rel

    def _files_under(self, rel_dir: str, rules: IgnoreRules) -> Iterator[str]:
        if not rules.allows(f"{rel_dir}/x"):
            return
        exts = indexed_extensions(self.config)
        for dirpath, dirnames, filenames in os.walk(self.root / rel_dir):
            d_rel = Path(dirpath).relative_to(self.root).as_posix()
            rules.load_dir(d_rel, Path(dirpath))
            dirnames[:] = sorted(
                d for d in dirnames
                if not rules.skip_dir(d, Path(dirpath) / d) and not rules.ignored(f"{d_rel}/{d}", is_dir=True)
            )
            for f in sorted(filenames):
                rel = f"{d_rel}/{f}"
                if os.path.splitext(f)[1].lower() in exts and not rules.ignored(rel, is_dir=False):
                    yield rel

    # ---- settings and vector types
    def _changed_tiers(self) -> set[str]:
        """What the stored index was built with differs from the config: "rebuild", "links",
        "texts" or "vectors" (see _SETTING_TIERS)."""
        stored = self.store.get_meta("index_settings")
        if stored is None:
            return set()
        current = json.loads(json.dumps(self.config.index_settings()))
        return {_SETTING_TIERS.get(k, "rebuild") for k in set(stored) | set(current) if stored.get(k) != current.get(k)}

    def _embedders(self) -> dict[str, Embedder]:
        cfg = self.config
        return {v: self.embedder_factory(cfg.vectors[v].model, cfg) for v in cfg.enabled_vec_types()}

    def _commits_moved(self) -> bool:
        if not self.config.include_commits:
            return False
        head = git_head(self.root)
        return bool(head) and head != self.store.get_meta("indexed_commit")

    def _vector_cache(self) -> VectorCache | None:
        if self.config.vector_cache == "off":
            return None
        if self._cache is None:
            self._cache = VectorCache(codemem_home() / "cache" / "vectors.db")
        return self._cache

    # ---- stage A: structure
    def structure(
        self, stats: IndexStats, *, full: bool = False, paths: Iterable[str | Path] | None = None,
    ) -> set[int] | None:
        """Apply changed files to chunks, BM25 rows, calls and links, and queue the chunks whose
        texts may have changed. `paths` limits the check to those files (and folders). Returns
        the queued chunk ids, or None when everything was queued."""
        store, cfg = self.store, self.config
        with self._locked():
            tiers = self._changed_tiers()
            if full or "rebuild" in tiers:
                if tiers and not full:
                    log.info("index-time settings changed (%s); rebuilding the index", sorted(tiers))
                self._wipe()
                full = True
            t = time.perf_counter()
            scan_started = time.time()
            reconcile = paths is None or full
            scan = self.scan() if reconcile else self.scan_paths(paths or ())
            stats.files_scanned += scan.total
            stats.add_time("scan", time.perf_counter() - t)

            t = time.perf_counter()
            parsed: list[tuple[FileState, str, str, list[Chunk]]] = []
            for i, (state, data, digest, language) in enumerate(scan.changed):
                self.progress("chunk", i, len(scan.changed))
                try:
                    chunks = chunk_source(data, state.rel, language=language, max_block_lines=cfg.max_block_lines)
                    parsed.append((state, digest, language, chunks))
                except Exception as e:  # never let one bad file kill the index
                    log.exception("failed to chunk %s", state.rel)
                    stats.errors.append(f"{state.rel}: {e}")
            stats.add_time("chunk", time.perf_counter() - t)

            t = time.perf_counter()
            embedders = self._embedders()
            with store.transaction():
                seq = store.next_dirty_seq()
                reset = [store.ensure_vec_type(v, e.key, cfg.embedding_dim) for v, e in embedders.items()]
                affected = [s.rel for s, *_ in parsed] + scan.deleted + [s.rel for s, *_ in scan.skipped]
                old = store.chunks_for_paths(affected)
                old_by_path: dict[str, list[Chunk]] = defaultdict(list)
                for c in old:
                    old_by_path[c.path].append(c)
                old_edges = store.edges_from({c.chunk_id for c in old})
                changed: set[int] = set()  # new or changed chunks: relinked, and their texts re-checked
                gone: set[int] = set()
                for state, prev in scan.touched:
                    store.upsert_file(state.rel, prev.content_hash, state.mtime, state.size, prev.language, prev.status, prev.reason)
                for rel in scan.deleted:
                    gone.update(store.delete_file(rel))
                for state, digest, language, reason in scan.skipped:
                    log.info("skipping %s: %s", state.rel, reason)
                    gone.update(store.delete_file(state.rel))
                    store.upsert_file(state.rel, digest, state.mtime, state.size, language, "skipped", reason)
                stats.chunks_deleted += len(gone)
                for state, digest, language, chunks in parsed:
                    now_changed, now_gone = self._apply_file(
                        state, digest, language, chunks, old_by_path.get(state.rel, []), stats
                    )
                    changed |= now_changed
                    gone |= now_gone
                new = [c for *_, chunks in parsed for c in chunks]

                if full or "links" in tiers:
                    edges = resolve_edges(store.definitions(), store.all_calls(), cfg.max_defs_per_name)
                    store.replace_edges(edges)
                    stats.relinked += store.counts()["chunks"]
                    changed_edges: set[tuple[int, int]] = set()
                else:
                    callers, changed_edges = self._relink(_definitions(old), _definitions(new), changed, gone)
                    stats.relinked += len(callers)
                stats.edges = store.edge_count()

                queued: set[int] | None
                if full or tiers or any(reset) or self._commits_moved():
                    store.mark_all_dirty(seq)
                    stats.queued += store.dirty_count()
                    queued = None
                else:
                    # New or changed chunks (their code texts), what they call (each one's usage
                    # text lists them), what deleted chunks called, and every chunk whose callers
                    # changed. Identical chunks, and chunks that only moved, keep their texts.
                    dirty = changed | {b for a, b in old_edges if a in gone} | {b for _, b in store.edges_from(changed)}
                    dirty |= {b for _, b in changed_edges}
                    dirty -= gone
                    store.mark_dirty(dirty, seq)
                    stats.queued += len(dirty)
                    queued = dirty
                stats.files_changed += len(parsed)
                stats.files_deleted += len(scan.deleted)
                stats.files_skipped += len(scan.skipped)
                store.set_meta("repo_path", str(self.root))
                store.set_meta("indexed_commit", git_head(self.root))
                store.set_meta("indexed_at", time.time())
                store.set_meta("codemem_version", __version__)
                store.set_meta("index_settings", cfg.index_settings())
                if reconcile:
                    store.set_meta("last_scan_at", scan_started)
                    store.set_meta("coverage", scan.coverage)
            stats.add_time("write_chunks", time.perf_counter() - t)
        return queued

    def _relink(
        self, old_defs: dict[tuple[str, str], set[int]], new_defs: dict[tuple[str, str], set[int]],
        changed_ids: set[int], gone: set[int],
    ) -> tuple[set[int], set[tuple[int, int]]]:
        """Resolve again the calls that can have a new target: every call made by a new or changed
        chunk, and every call anywhere to a name whose set of definitions changed. (A chunk whose
        content is unchanged calls the same names, so only the second rule can move its links.)
        Returns the relinked callers and the edges that appeared or disappeared."""
        store, limit = self.store, self.config.max_defs_per_name
        changed = {k for k in old_defs.keys() | new_defs.keys() if old_defs.get(k, set()) != new_defs.get(k, set())}
        relevant: set[tuple[str, str]] = set()
        if changed:
            counts: Counter[tuple[str, str]] = Counter(
                (fam, name) for _, name, fam in store.definitions_named({n for _, n in changed})
            )
            for key in changed:
                now = counts.get(key, 0)
                before = now - len(new_defs.get(key, ())) + len(old_defs.get(key, ()))
                if now <= limit or before <= limit:  # above the limit both times: no links either way
                    relevant.add(key)
        callers = set(changed_ids)
        if relevant:
            callers |= {c for c, name, fam in store.calls_to_names({n for _, n in relevant}) if (fam, name) in relevant}
        callers -= gone
        before_edges = store.edges_from(callers)
        calls = store.calls_of(callers)
        defs = store.definitions_named({name for _, name, _ in calls})
        after_edges = resolve_edges(defs, calls, limit)
        store.replace_edges_from(callers, after_edges)
        return callers, before_edges ^ after_edges

    def _wipe(self) -> None:
        store = self.store
        with store.transaction():
            for vec_type in store.vec_types():
                store.drop_vec_type(vec_type)
            for table in ("chunks", "fts", "calls", "edges", "vectors", "files", "dirty_texts"):
                store.conn.execute(f"DELETE FROM {table}")
            store.conn.execute("DELETE FROM meta WHERE key IN ('index_settings', 'last_scan_at')")
        store.save_vectors()

    def _apply_file(
        self, state: FileState, digest: str, language: str, chunks: list[Chunk], old_chunks: list[Chunk],
        stats: IndexStats,
    ) -> tuple[set[int], set[int]]:
        """Write one re-chunked file, matching old and new chunks by key: new and changed chunks are
        written, chunks that only moved get their line numbers shifted, identical ones are left
        alone. Returns the ids of the new or changed chunks and of the deleted ones."""
        store = self.store
        old = {c.key: c for c in old_chunks}
        changed: set[int] = set()
        moved: list[tuple[Chunk, int]] = []
        for chunk in chunks:
            prev = old.pop(chunk.key, None)
            delta = _moved_by(prev, chunk) if prev is not None else None
            if delta is not None:
                chunk.chunk_id = prev.chunk_id
                if delta:
                    moved.append((chunk, delta))
                continue
            if prev is None:
                stats.chunks_added += 1
            else:
                stats.chunks_updated += 1
            chunk.chunk_id = store.upsert_chunk(chunk)
            changed.add(chunk.chunk_id)
        if moved:
            kept = {c.key for c in chunks} & {c.key for c in old_chunks}
            if _order(old_chunks, kept) != _order(chunks, kept):
                # Definitions were reordered. Usage texts list callers by line, so the moved chunks
                # are rewritten and re-checked like changed ones.
                for chunk, _ in moved:
                    store.upsert_chunk(chunk)
                    changed.add(chunk.chunk_id)
                stats.chunks_updated += len(moved)
            else:
                store.move_chunks([(c.chunk_id, c.start_line, c.end_line, d) for c, d in moved])
                stats.chunks_moved += len(moved)
        gone = {c.chunk_id for c in old.values()}
        store.delete_chunks(gone)
        stats.chunks_deleted += len(gone)
        partial = bool(getattr(chunks, "parse_errors", False))
        store.upsert_file(state.rel, digest, state.mtime, state.size, language, "ok", "parse_errors" if partial else "")
        if partial:
            stats.parse_errors.append(state.rel)
        return changed, gone

    # ---- stage B: vectors
    def embed_pending(
        self, stats: IndexStats, *, only: Iterable[int] | None = None, deadline: float | None = None,
        batch_chunks: int = _BATCH_CHUNKS, group: int = _EMBED_GROUP, group_chars: int | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> bool:
        """Embed queued chunks (all of them, or only `only`), newest edits first, until the queue is
        empty, the monotonic `deadline` passes, or `stop()` says so (asked before every model call).
        A model call holds at most `group` texts and, if set, `group_chars` characters; it isn't
        started when the model's measured speed says it would end past the deadline. Returns True
        when nothing of what was asked is left."""
        only = None if only is None else set(only)
        total = len(only) if only is not None else self.store.dirty_count()
        done = 0
        for v in self.config.enabled_vec_types():
            for counter in (stats.embedded, stats.model_embedded, stats.reused, stats.cache_hits):
                counter.setdefault(v, 0)
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                return False
            if stop is not None and stop():
                return False
            batch = self._take(batch_chunks, only)
            if batch is None:
                return True
            try:
                finished = self._compute(batch, stats, deadline, group, group_chars, stop)
                self._put(batch, stats)  # a batch cut short stores the chunks it finished
            finally:
                with self._claim_lock:
                    self._claimed -= set(batch.seqs)
            if not finished:
                return False
            done += len(batch.seqs)
            if only is not None:
                only -= set(batch.seqs)
            self.progress("embed", min(done, total), total)

    def _build_context(self, ids: list[int], paths: set[str]) -> BuildContext:
        cfg = self.config
        commits: dict[str, list[str]] = {}
        if cfg.include_commits:
            head = git_head(self.root)
            if head:
                commits = {rel: git_commit_subjects(self.root, rel, head) for rel in sorted(paths)}
        return BuildContext(
            callers=self.store.caller_refs(ids, limit=cfg.max_usage_items),
            commits=commits,
            max_items=cfg.max_usage_items,
            code_header=cfg.code_header,
            window_chars=cfg.effective_window_chars(),
            window_overlap_lines=cfg.window_overlap_lines,
        )

    def _take(self, limit: int, only: set[int] | None) -> _Batch | None:
        """Claim a batch of queued chunks and decide what each of their texts needs. Under the
        write lock, but short: no model call happens here."""
        store = self.store
        t = time.perf_counter()
        with self._locked():
            with self._claim_lock:
                claimed = set(self._claimed)
            seqs = store.dirty_batch(limit, skip=claimed, only=only)
            if not seqs:
                return None
            with self._claim_lock:
                self._claimed |= set(seqs)
            chunks = store.get_chunks(seqs)
            ctx = self._build_context(list(chunks), {c.path for c in chunks.values()})
            cache = self._vector_cache()
            work: dict[str, _TypeWork] = {}
            for vec_type, embedder in self._embedders().items():
                key = embedder.key
                stored = store.vector_parts(vec_type, chunks)
                rows_by_hash: dict[str, list[VectorRow]] = defaultdict(list)
                text_of: dict[str, str] = {}
                seen: set[tuple[int, int]] = set()
                for chunk in chunks.values():
                    for part in build_parts(chunk, ctx, vec_type):
                        h = text_hash(part.text)
                        seen.add((chunk.chunk_id, part.part))
                        prev = stored.get((chunk.chunk_id, part.part))
                        if prev is not None and prev[1:] == (h, part.n_parts, part.start_off, part.end_off):
                            continue
                        rows_by_hash[h].append(
                            VectorRow(chunk.chunk_id, part.part, part.n_parts, part.start_off, part.end_off, h)
                        )
                        text_of[h] = part.text
                stale = [(vid, cid) for (cid, part), (vid, *_) in stored.items() if (cid, part) not in seen]
                found = store.find_vectors(key, rows_by_hash) if rows_by_hash else {}
                tw = _TypeWork(embedder, key, rows_by_hash, text_of, dict(found), [], stale, from_index=set(found))
                missing = [h for h in rows_by_hash if h not in found]
                if cache is not None and missing:
                    cached = cache.get_many(key, missing)
                    tw.vectors.update(cached)
                    tw.from_cache = set(cached)
                    missing = [h for h in missing if h not in cached]
                tw.missing = missing
                work[vec_type] = tw
        return _Batch(seqs, work, time.perf_counter() - t)

    def _compute(
        self, batch: _Batch, stats: IndexStats, deadline: float | None = None, group: int = _EMBED_GROUP,
        group_chars: int | None = None, stop: Callable[[], bool] | None = None,
    ) -> bool:
        """Run the model on the texts nothing else could provide. The write lock is not held, so
        structure updates go on meanwhile. False if it stopped early (`stop()`, or the next call
        would end past the deadline); what it computed stays in `batch`."""
        stats.add_time("build_texts", batch.build_time)
        cache = self._vector_cache()
        # The model calls: newest edits first (a search cut short by its deadline has embedded the
        # agent's latest edit), code texts before usage texts, longest texts first (less padding).
        calls: list[tuple[int, int, int, _TypeWork, list[str]]] = []
        for rank, tw in enumerate(batch.work.values()):
            by_seq: dict[int, list[str]] = defaultdict(list)
            for h in tw.missing:
                by_seq[max(batch.seqs[r.chunk_id] for r in tw.rows_by_hash[h])].append(h)
            for seq, hashes in by_seq.items():
                hashes.sort(key=lambda h: len(tw.text_of[h]), reverse=True)
                runs = _model_calls(hashes, tw.text_of, group, group_chars)
                calls += [(-seq, rank, i, tw, texts) for i, texts in enumerate(runs)]
        calls.sort(key=lambda c: c[:3])
        for *_, tw, texts in calls:
            if stop is not None and stop():
                return False
            chars = sum(len(tw.text_of[h]) for h in texts)
            if deadline is None:
                self._model_lock.acquire()
            else:
                left = deadline - time.monotonic()
                if left <= 0 or not self._model_lock.acquire(timeout=left):
                    return False
                if self._seconds_for(chars) > deadline - time.monotonic():
                    self._model_lock.release()
                    return False  # it would end past the deadline
            try:
                t = time.perf_counter()
                vecs = tw.embedder.embed_documents([tw.text_of[h] for h in texts])
                took = time.perf_counter() - t
                stats.add_time("embed", took)
            finally:
                self._model_lock.release()
            self._observe_speed(chars, took)
            if cache is not None:
                cache.put_many(tw.key, texts, vecs)
            tw.vectors.update(zip(texts, vecs))
        return True

    def _put(self, batch: _Batch, stats: IndexStats) -> None:
        """Store the batch's vectors, for chunks that have all of them (a batch cut short stores
        what it finished; the rest stays queued) and were not queued again meanwhile."""
        store = self.store
        t = time.perf_counter()
        complete = set(batch.seqs)
        for tw in batch.work.values():
            complete -= {r.chunk_id for rs in tw.rows_by_hash.values() for r in rs if r.text_hash not in tw.vectors}
        if not complete:
            return
        with self._locked(), store.transaction():
            current = store.dirty_seqs(complete)
            ok = {i for i in complete if current.get(i) == batch.seqs[i]}
            for vec_type, tw in batch.work.items():
                rows = [r for rs in tw.rows_by_hash.values() for r in rs if r.chunk_id in ok]
                if rows:
                    store.put_vectors(vec_type, tw.key, rows, np.stack([tw.vectors[r.text_hash] for r in rows]))
                stale = [vid for vid, cid in tw.stale if cid in ok]
                store.delete_vectors(vec_type, stale)
                reused = sum(r.text_hash in tw.from_index for r in rows)
                cached = sum(r.text_hash in tw.from_cache for r in rows)
                stats.embedded[vec_type] = stats.embedded.get(vec_type, 0) + len(rows)
                stats.reused[vec_type] = stats.reused.get(vec_type, 0) + reused
                stats.cache_hits[vec_type] = stats.cache_hits.get(vec_type, 0) + cached
                stats.model_embedded[vec_type] = stats.model_embedded.get(vec_type, 0) + len(rows) - reused - cached
                if stale:
                    stats.vectors_removed[vec_type] = stats.vectors_removed.get(vec_type, 0) + len(stale)
            store.clear_dirty({i: batch.seqs[i] for i in ok})
        stats.add_time("write_vectors", time.perf_counter() - t)

    # ---- the whole update
    def update(self, *, full: bool = False, paths: Iterable[str | Path] | None = None, save: bool = True) -> IndexStats:
        """Stage A, then stage B until the queue is empty, then (with `save`) the FAISS files."""
        stats = IndexStats()
        t_start = time.perf_counter()
        try:
            self.structure(stats, full=full, paths=paths)
            self.embed_pending(stats)
            if save:
                t = time.perf_counter()
                self.store.save_vectors()
                stats.add_time("write_vectors", time.perf_counter() - t)
        finally:
            if self._cache is not None:
                self._cache.close()
        self.finish(stats, t_start)
        return stats

    def finish(self, stats: IndexStats, t_start: float) -> None:
        stats.pending = self.store.dirty_count()
        stats.timings["total"] = time.perf_counter() - t_start
        with self.store.transaction():
            self.store.set_meta("last_update", stats.to_dict())
        if stats.chunks_deleted or stats.vectors_removed:
            self.store.vacuum_if_sparse()
        self.progress("done", 1, 1)
        log.info(
            "indexed %s: %d files changed, %d deleted, embedded %s in %.2fs",
            self.root, stats.files_changed, stats.files_deleted, stats.embedded, stats.timings["total"],
        )

    # ---- checking
    def verify(self) -> list[str]:
        """Differences between this index and a fresh build of the same files ([] = consistent).
        The fresh build reuses the vector cache, so it costs almost no model calls."""
        cfg = self.config
        with tempfile.TemporaryDirectory(dir=self.store.index_dir.parent, prefix=".codemem-verify-") as tmp:
            fresh = Store(Path(tmp), bm25_stem=cfg.bm25_stem, bm25_stopwords=cfg.bm25_stopwords)
            try:
                Indexer(self.root, fresh, cfg, embedder_factory=self.embedder_factory).update(save=False)
                return diff_snapshots(self.store.snapshot(), fresh.snapshot())
            finally:
                fresh.close()
