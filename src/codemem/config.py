"""Settings, paths and per-vector-type model config.

Load order (later wins): built-in defaults -> ~/.codemem/config.toml ->
<repo>/.codemem.toml -> environment variables.

Settings are either index-time (they change what is stored; `Config.index_settings()` lists them,
and the eval harness hashes them to decide which systems can share an index) or search-time (they
change only how a query is answered, so systems that differ in them share one index).
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import threading
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MODEL = "jinaai/jina-code-embeddings-0.5b"
REPO_CONFIG_NAME = ".codemem.toml"
TEXT_FORMAT_VERSION = 3  # bump when a text builder's output changes, so old vectors are not reused
CHUNKER_VERSION = 2  # bump when chunking changes (kinds, ranges, keys, calls): an index is then rebuilt

# Directories that are never indexed, regardless of .gitignore.
ALWAYS_SKIP_DIRS = frozenset(
    {
        ".git", "venv", ".venv", "env", "build", "dist", "node_modules", "__pycache__", "site-packages",
        ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".eggs",
    }
)
# Skipped by default (gitignore-style; `use_default_ignore = false` keeps them): vendored
# dependencies and generated or minified code, which crowd results with copies and noise.
DEFAULT_IGNORE = (
    "vendor/", "*.min.js", "*.min.mjs", "*.bundle.js", "*_pb2.py", "*_pb2_grpc.py", "*.pb.go", "*.pb.cc",
    "*.pb.h",
)
BM25_FIELDS = ("name", "path", "signature", "doc", "body")
DEVICES = ("auto", "cpu", "xpu", "cuda", "mps")
DTYPES = ("auto", "float32", "float16", "bfloat16")
# Search-time score multipliers, neutral by default (docs/architecture.md §6). Halving tests,
# classes and blocks scores better on the eval only because its answers are never tests and rarely
# whole classes, while questions like "add OCR to uploads" often need both. The knobs stay for runs.
DEFAULT_TEST_WEIGHT = 1.0
DEFAULT_KIND_WEIGHTS: dict[str, float] = {}


@dataclass
class VectorConfig:
    model: str = DEFAULT_MODEL  # a hub name or a local model folder
    enabled: bool = True
    # "module:Class" subclassing embedder.Embedder, built as Class(model, config); None = the
    # built-in embedders (docs/architecture.md §3.5)
    embedder: str | None = None
    # A label for the weights; None = a hash of a local model folder's files, nothing for a hub name
    version: str | None = None


@dataclass
class EmbeddingConfig:
    """Where embeddings come from (docs/decisions.md §2). `local` runs the model on this machine:
    the default, private, offline and free. `openai` calls any OpenAI-compatible `/embeddings` API
    (Nebius, OpenAI, Together, a self-hosted vLLM or TEI server, Ollama), with `model` for every
    vector type, for documents and queries alike. The API key is read from the environment
    variable `api_key_env` names, never from a file; remote embedding sends code to the provider."""

    provider: str = "local"  # local | openai
    model: str = ""  # the API's model name (required for openai)
    base_url: str = ""  # e.g. https://api.studio.nebius.com/v1 (required for openai)
    api_key_env: str = ""  # environment variable holding the key; empty = no key (a local server)
    dimensions: int | None = None  # shorter vectors, for models trained for it (Qwen3-Embedding)
    query_prefix: str = ""  # an instruction before each query (instruction-tuned models want one)
    document_prefix: str = ""  # before each document
    batch_size: int = 64  # texts per request
    max_concurrency: int = 4  # requests in flight
    timeout_s: float = 60.0  # per request

    @property
    def remote(self) -> bool:
        return self.provider != "local"

    def index_settings(self) -> dict[str, Any]:
        """What changes the stored vectors: not the key's variable, the query prefix or request sizes."""
        return {
            "provider": self.provider, "model": self.model, "base_url": self.base_url,
            "dimensions": self.dimensions, "document_prefix": self.document_prefix,
        }


def _default_vectors() -> dict[str, VectorConfig]:
    return {"code": VectorConfig(), "usage": VectorConfig()}


@dataclass
class Config:
    device: str = "auto"  # auto | cpu | xpu | cuda | mps
    vectors: dict[str, VectorConfig] = field(default_factory=_default_vectors)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    embedding_dim: int | None = None  # Matryoshka truncation, applied when searching; None = full dim
    dtype: str = "auto"  # auto = float16 on cuda/mps, float32 on cpu
    batch_size: int = 16
    max_seq_length: int = 1024  # tokens per embedded text (keeps CPU indexing tractable)
    # name, path, signature, doc, body. A 3-value list (name, signature, body) from older configs
    # is accepted: doc gets the body weight and path gets 0.
    bm25_weights: tuple[float, ...] = (10.0, 3.0, 5.0, 2.0, 1.0)
    bm25_stem: bool = False
    bm25_stopwords: bool = False
    bm25_query_terms: int = 32  # search-time: queries drop stopwords; 0 = keep every word
    bm25_common_share: float = 0.0  # opt-in: a query over bm25_query_terms words also drops words in more
    # than this share of chunks: a 250-word query on vLLM takes 0.11 s instead of 0.36 s, but on the dev
    # tasks keyword-only file MRR fell from 0.453 to 0.378 at 0.05 (docs/architecture.md §6)
    rrf_k: int = 60
    rrf_weights: dict[str, float] = field(default_factory=dict)  # signal -> weight, default 1.0
    candidates: int = 50  # top-N per signal before RRF
    max_defs_per_name: int = 5
    max_usage_items: int = 20
    include_commits: bool = False
    max_file_size: int = 10_000_000  # larger files are recorded as skipped (too_large), never silently
    ignore: list[str] = field(default_factory=list)  # extra gitignore-style patterns
    use_default_ignore: bool = True  # also skip DEFAULT_IGNORE (vendored, generated, minified)
    skip_generated: bool = True  # skip files marked "Code generated ... DO NOT EDIT" or "@generated"
    languages: list[str] | None = None  # None = every supported language
    code_header: bool = True  # put path / class context above the code that gets embedded
    window_chars: int | None = None  # longest embedded text; None = 3 chars per token of max_seq_length
    window_overlap_lines: int = 3
    max_block_lines: int = 200
    vector_cache: str = "global"  # global = reuse vectors across indexes (~/.codemem/cache) | off
    # The in-memory search index: faiss (exact) | "module:Class" subclassing store.VectorStore.
    # Vectors stay in SQLite, so a change rebuilds the search index from them, with no re-embedding.
    vector_backend: str = "faiss"
    # search-time result filters and weights (the eval adapter can set them per system)
    kinds: list[str] | None = None  # None = every kind; e.g. ["function", "method"]
    test_weight: float = DEFAULT_TEST_WEIGHT  # multiplies the fused score of test chunks; 0 drops them
    # multiplies the fused score of chunks of a kind; a config's table is merged over the defaults
    kind_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_KIND_WEIGHTS))
    steering: str = "light"  # none | light | strong
    preview_lines: int = 12
    preview_chars: int = 800
    debounce_ms: int = 500  # start an update once saves stop for this long ...
    debounce_max_wait_ms: int = 2000  # ... or at the latest this long after the first save
    catchup_budget_ms: int = 4000  # a search first applies and embeds pending edits for at most this long

    def enabled_vec_types(self) -> list[str]:
        return [name for name, v in self.vectors.items() if v.enabled]

    def model_id(self, vec_type: str) -> str:
        """Identity of the embedding space for a vec type: model, truncation, weights version
        and plugin embedder. Without a version or a plugin it is the string it was before they
        existed, so indexes keep their settings."""
        spec = self.vectors[vec_type]
        out = f"{spec.model}@{self.embedding_dim}" if self.embedding_dim else spec.model
        if version := model_version(spec):
            out += f"#{version}"
        if spec.embedder:
            out += f"+{spec.embedder}"
        return out

    def effective_window_chars(self) -> int:
        return self.window_chars or max(3 * (self.max_seq_length - 32), 1000)

    def bm25_weights5(self) -> tuple[float, float, float, float, float]:
        w = tuple(float(x) for x in self.bm25_weights)
        if len(w) == 3:  # older configs: name, signature, body (body included docstrings)
            return (w[0], 0.0, w[1], w[2], w[2])
        if len(w) != 5:
            raise ValueError(f"bm25 weights need 5 values ({', '.join(BM25_FIELDS)}) or 3, got {len(w)}")
        return w  # type: ignore[return-value]

    def index_settings(self) -> dict[str, Any]:
        """Every setting that changes what an index stores. Equal settings -> an equal index."""
        settings = {
            "text_format": TEXT_FORMAT_VERSION,
            "chunker": CHUNKER_VERSION,
            "vectors": {name: {"model": self.model_id(name)} for name in self.enabled_vec_types()},
            "embedding_dim": self.embedding_dim,
            "dtype": self.dtype,
            "batch_size": self.batch_size,
            "max_seq_length": self.max_seq_length,
            "bm25_stem": self.bm25_stem,
            "bm25_stopwords": self.bm25_stopwords,
            "max_defs_per_name": self.max_defs_per_name,
            "max_usage_items": self.max_usage_items,
            "include_commits": self.include_commits,
            "max_file_size": self.max_file_size,
            "ignore": list(self.ignore),
            "use_default_ignore": self.use_default_ignore,
            "skip_generated": self.skip_generated,
            "languages": sorted(self.languages) if self.languages is not None else None,
            "code_header": self.code_header,
            "window_chars": self.effective_window_chars(),
            "window_overlap_lines": self.window_overlap_lines,
            "max_block_lines": self.max_block_lines,
        }
        if self.embedding.remote:  # absent for the local model, so local indexes keep their settings
            settings["embedding"] = self.embedding.index_settings()
        if self.vector_backend != "faiss":  # likewise: systems with another backend get their own index
            settings["vector_backend"] = self.vector_backend
        return settings


def codemem_home() -> Path:
    return Path(os.environ.get("CODEMEM_HOME") or Path.home() / ".codemem")


# --------------------------------------------------------------------------- model weights version

_HASH_CACHE_NAME = "model_hashes.json"
_hash_lock = threading.Lock()
_hash_memo: dict[Path, tuple[tuple, str]] = {}


def model_version(spec: VectorConfig) -> str | None:
    """The weights version of a vector type's model: its `version`, else a hash of a local
    model folder's files, else None (a hub name, whose id names the weights)."""
    if spec.version:
        return spec.version
    path = Path(spec.model).expanduser()
    return model_folder_hash(path) if path.is_dir() else None


def _model_files(root: Path) -> list[Path]:
    # Dot folders and files (.git, .cache) are tool metadata, not weights.
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        out.extend(Path(dirpath) / f for f in sorted(filenames) if not f.startswith("."))
    return out


def model_folder_hash(root: Path) -> str:
    """sha256 over every file's relative path and content, first 12 hex characters. Content, not
    timestamps: the same weights give the same version on any machine, and new weights saved over
    the folder give a new one. Each file is read once: its hash is kept in
    <codemem home>/model_hashes.json by size and mtime (reading takes about 1 s per GB)."""
    root = root.resolve()
    files = [(f, f.stat()) for f in _model_files(root)]
    stamps = tuple((str(f), st.st_size, st.st_mtime_ns) for f, st in files)
    with _hash_lock:
        memo = _hash_memo.get(root)
        if memo is not None and memo[0] == stamps:  # unchanged since the last call in this process
            return memo[1]
        cache_path = codemem_home() / _HASH_CACHE_NAME
        try:
            cache = json.loads(cache_path.read_text("utf-8"))
        except (OSError, ValueError):
            cache = {}
        changed = False
        total = hashlib.sha256()
        for f, st in files:
            stamp = [st.st_size, st.st_mtime_ns]
            entry = cache.get(str(f))
            if entry is None or entry[:2] != stamp:
                log.info("hashing %s to version the model's weights (once per file)", f)
                h = hashlib.sha256()
                with f.open("rb") as fh:
                    while block := fh.read(1 << 20):
                        h.update(block)
                entry = cache[str(f)] = [*stamp, h.hexdigest()]
                changed = True
            total.update(f.relative_to(root).as_posix().encode("utf-8") + b"\0" + entry[2].encode() + b"\n")
        if changed:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
                tmp.write_text(json.dumps(cache), "utf-8")
                os.replace(tmp, cache_path)
            except OSError:  # the cache only saves time
                log.warning("could not write %s", cache_path)
        digest = total.hexdigest()[:12]
        _hash_memo[root] = (stamps, digest)
    return digest


def default_index_dir(repo_root: Path) -> Path:
    resolved = os.path.normcase(str(Path(repo_root).resolve()))
    digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()[:8]
    return codemem_home() / "indexes" / f"{Path(repo_root).resolve().name}-{digest}"


def find_repo_root(start: Path | str | None = None) -> Path:
    """Walk up from `start` to the nearest directory containing .git; else `start` itself."""
    start_path = Path(start or os.getcwd()).resolve()
    for candidate in (start_path, *start_path.parents):
        if (candidate / ".git").exists():
            return candidate
    return start_path


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _env_overrides() -> dict[str, Any]:
    raw: dict[str, Any] = {}
    if dev := os.environ.get("CODEMEM_DEVICE"):
        raw["device"] = dev
    if steering := os.environ.get("CODEMEM_STEERING"):
        raw["steering"] = steering
    if model := os.environ.get("CODEMEM_MODEL"):
        # Applies to every vec type; handy for `CODEMEM_MODEL=fake` in tests/dev.
        raw["vectors"] = {name: {"model": model} for name in _default_vectors()}
    if cache := os.environ.get("CODEMEM_VECTOR_CACHE"):
        raw["vector_cache"] = cache
    return raw


_FLAT_KEYS = (
    "device", "embedding_dim", "dtype", "batch_size", "max_seq_length", "max_file_size", "ignore", "steering",
    "candidates", "use_default_ignore", "skip_generated", "languages", "code_header", "window_chars",
    "window_overlap_lines", "max_block_lines", "vector_cache", "vector_backend", "kinds", "test_weight",
    "kind_weights", "debounce_ms", "debounce_max_wait_ms", "catchup_budget_ms",
)


def config_from_dict(raw: dict[str, Any]) -> Config:
    cfg = Config()
    vectors = _default_vectors()
    known = {f.name for f in fields(VectorConfig)}
    for name, spec in (raw.get("vectors") or {}).items():
        if unknown := sorted(set(spec) - known):
            raise ValueError(f"unknown [vectors.{name}] settings {unknown}; choose from {sorted(known)}")
        current = vectors.get(name, VectorConfig(enabled=True))
        vectors[name] = VectorConfig(**{k: spec.get(k, getattr(current, k)) for k in known})
        if vectors[name].embedder is not None and ":" not in vectors[name].embedder:
            raise ValueError(f"vectors.{name}.embedder must be 'module:Class', got {vectors[name].embedder!r}")
    cfg.vectors = vectors

    flat = {key: raw.get(key) for key in _FLAT_KEYS}
    bm25 = raw.get("bm25") or {}
    rrf = raw.get("rrf") or {}
    usage = raw.get("usage") or {}
    flat.update(
        bm25_weights=tuple(bm25["weights"]) if "weights" in bm25 else None,
        bm25_stem=bm25.get("stem"),
        bm25_stopwords=bm25.get("stopwords"),
        bm25_query_terms=bm25.get("query_terms"),
        bm25_common_share=bm25.get("common_share"),
        rrf_k=rrf.get("k"),
        rrf_weights=rrf.get("weights"),
        max_defs_per_name=usage.get("max_defs_per_name"),
        max_usage_items=usage.get("max_items"),
        include_commits=usage.get("include_commits"),
    )
    if flat["kind_weights"] is not None:  # `{ class = 1.0 }` keeps the default block weight
        flat["kind_weights"] = {**DEFAULT_KIND_WEIGHTS, **flat["kind_weights"]}
    for key, value in flat.items():
        if value is not None:
            setattr(cfg, key, value)

    if cfg.device not in DEVICES:
        raise ValueError(f"device must be {'|'.join(DEVICES)}, got {cfg.device!r}")
    if cfg.dtype not in DTYPES:
        raise ValueError(f"dtype must be {'|'.join(DTYPES)}, got {cfg.dtype!r}")
    if cfg.steering not in {"none", "light", "strong"}:
        raise ValueError(f"steering must be none|light|strong, got {cfg.steering!r}")
    if cfg.vector_cache not in {"global", "off"}:
        raise ValueError(f"vector_cache must be global|off, got {cfg.vector_cache!r}")
    if cfg.vector_backend != "faiss" and ":" not in cfg.vector_backend:
        raise ValueError(f"vector_backend must be faiss or 'module:Class', got {cfg.vector_backend!r}")
    from .texts import TEXT_BUILDERS

    if unknown := sorted(set(cfg.enabled_vec_types()) - set(TEXT_BUILDERS)):
        raise ValueError(f"vector types {unknown} have no text builder; choose from {sorted(TEXT_BUILDERS)}")
    cfg.bm25_weights5()  # validates the length
    emb = dict(raw.get("embedding") or {})
    known = {f.name for f in fields(EmbeddingConfig)}
    if unknown := sorted(set(emb) - known):
        raise ValueError(f"unknown [embedding] settings {unknown}; choose from {sorted(known)}")
    cfg.embedding = EmbeddingConfig(**emb)
    if cfg.embedding.provider not in {"local", "openai"}:
        raise ValueError(f"[embedding] provider must be local|openai, got {cfg.embedding.provider!r}")
    if cfg.embedding.remote and not (cfg.embedding.model and cfg.embedding.base_url):
        raise ValueError("[embedding] provider = openai needs model and base_url")
    if cfg.languages is not None:
        from .languages import supported_languages

        unknown = [lang for lang in cfg.languages if lang not in supported_languages()]
        if unknown:
            raise ValueError(f"unknown languages {unknown}; choose from {supported_languages()}")
    from .schema import KINDS

    for kinds in (cfg.kinds or [], cfg.kind_weights):
        unknown = [k for k in kinds if k not in KINDS]
        if unknown:
            raise ValueError(f"unknown kinds {unknown}; choose from {list(KINDS)}")
    return cfg


def load_config(repo_root: Path | None = None) -> Config:
    raw = _read_toml(codemem_home() / "config.toml")
    if repo_root is not None:
        raw = _deep_merge(raw, _read_toml(Path(repo_root) / REPO_CONFIG_NAME))
    raw = _deep_merge(raw, _env_overrides())
    return config_from_dict(raw)
