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
import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MODEL = "jinaai/jina-code-embeddings-0.5b"
REPO_CONFIG_NAME = ".codemem.toml"
TEXT_FORMAT_VERSION = 2  # bump when a text builder's output changes, so old vectors are not reused

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


@dataclass
class VectorConfig:
    model: str = DEFAULT_MODEL
    enabled: bool = True


def _default_vectors() -> dict[str, VectorConfig]:
    return {
        "code": VectorConfig(),
        "usage": VectorConfig(),
        # Slot only: the builder returns None, so nothing is embedded.
        "summary": VectorConfig(enabled=False),
    }


@dataclass
class Config:
    device: str = "auto"  # auto | cpu | xpu | cuda | mps
    vectors: dict[str, VectorConfig] = field(default_factory=_default_vectors)
    embedding_dim: int | None = None  # Matryoshka truncation, applied when searching; None = full dim
    dtype: str = "auto"  # auto = float16 on cuda/mps, float32 on cpu
    batch_size: int = 16
    max_seq_length: int = 1024  # tokens per embedded text (keeps CPU indexing tractable)
    # name, path, signature, doc, body. A 3-value list (name, signature, body) from v1 configs is
    # accepted: doc gets the body weight and path gets 0.
    bm25_weights: tuple[float, ...] = (10.0, 3.0, 5.0, 2.0, 1.0)
    bm25_stem: bool = False
    bm25_stopwords: bool = False
    rrf_k: int = 60
    rrf_weights: dict[str, float] = field(default_factory=dict)  # signal -> weight, default 1.0
    candidates: int = 50  # top-N per signal before RRF
    max_defs_per_name: int = 5
    max_usage_items: int = 20
    include_commits: bool = False
    max_file_size: int = 1_000_000
    ignore: list[str] = field(default_factory=list)  # extra gitignore-style patterns
    use_default_ignore: bool = True  # also skip DEFAULT_IGNORE (vendored, generated, minified)
    skip_generated: bool = True  # skip files marked "Code generated ... DO NOT EDIT" or "@generated"
    languages: list[str] | None = None  # None = every supported language
    code_header: bool = True  # put path / class context above the code that gets embedded
    window_chars: int | None = None  # longest embedded text; None = 3 chars per token of max_seq_length
    window_overlap_lines: int = 3
    max_block_lines: int = 200
    vector_cache: str = "global"  # global = reuse vectors across indexes (~/.codemem/cache) | off
    # search-time result filters (the eval adapter can set them per system)
    kinds: list[str] | None = None  # None = every kind; e.g. ["function", "method"]
    test_weight: float = 1.0  # multiplies the fused score of test chunks; 0 drops them
    kind_weights: dict[str, float] = field(default_factory=dict)  # e.g. {"class": 0.5}; missing kinds 1.0
    steering: str = "light"  # none | light | strong
    preview_lines: int = 12
    preview_chars: int = 800
    debounce_ms: int = 400

    def enabled_vec_types(self) -> list[str]:
        return [name for name, v in self.vectors.items() if v.enabled]

    def model_id(self, vec_type: str) -> str:
        """Identity of the embedding space for a vec type (model + truncation)."""
        model = self.vectors[vec_type].model
        return f"{model}@{self.embedding_dim}" if self.embedding_dim else model

    def effective_window_chars(self) -> int:
        return self.window_chars or max(3 * (self.max_seq_length - 32), 1000)

    def bm25_weights5(self) -> tuple[float, float, float, float, float]:
        w = tuple(float(x) for x in self.bm25_weights)
        if len(w) == 3:  # v1: name, signature, body (body included docstrings)
            return (w[0], 0.0, w[1], w[2], w[2])
        if len(w) != 5:
            raise ValueError(f"bm25 weights need 5 values ({', '.join(BM25_FIELDS)}) or 3, got {len(w)}")
        return w  # type: ignore[return-value]

    def index_settings(self) -> dict[str, Any]:
        """Every setting that changes what an index stores. Equal settings -> an equal index."""
        return {
            "text_format": TEXT_FORMAT_VERSION,
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


def codemem_home() -> Path:
    return Path(os.environ.get("CODEMEM_HOME") or Path.home() / ".codemem")


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
    "window_overlap_lines", "max_block_lines", "vector_cache", "kinds", "test_weight", "kind_weights",
)


def config_from_dict(raw: dict[str, Any]) -> Config:
    cfg = Config()
    vectors = _default_vectors()
    for name, spec in (raw.get("vectors") or {}).items():
        current = vectors.get(name, VectorConfig(enabled=True))
        vectors[name] = VectorConfig(
            model=spec.get("model", current.model), enabled=spec.get("enabled", current.enabled)
        )
    cfg.vectors = vectors

    flat = {key: raw.get(key) for key in _FLAT_KEYS}
    bm25 = raw.get("bm25") or {}
    rrf = raw.get("rrf") or {}
    usage = raw.get("usage") or {}
    flat.update(
        bm25_weights=tuple(bm25["weights"]) if "weights" in bm25 else None,
        bm25_stem=bm25.get("stem"),
        bm25_stopwords=bm25.get("stopwords"),
        rrf_k=rrf.get("k"),
        rrf_weights=rrf.get("weights"),
        max_defs_per_name=usage.get("max_defs_per_name"),
        max_usage_items=usage.get("max_items"),
        include_commits=usage.get("include_commits"),
    )
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
    cfg.bm25_weights5()  # validates the length
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
