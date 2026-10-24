"""Settings, paths and per-vector-type model config.

Load order (later wins): built-in defaults -> ~/.codemem/config.toml ->
<repo>/.codemem.toml -> environment variables.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MODEL = "jinaai/jina-code-embeddings-0.5b"
REPO_CONFIG_NAME = ".codemem.toml"

# Directories that are never indexed, regardless of .gitignore.
ALWAYS_SKIP_DIRS = frozenset(
    {".git", "venv", ".venv", "env", "build", "dist", "node_modules", "__pycache__", "site-packages"}
)


@dataclass
class VectorConfig:
    model: str = DEFAULT_MODEL
    enabled: bool = True
    # "module:Class" implementing embedder.Embedder; None = sentence-transformers.
    embedder: str | None = None
    # Label for the weights. None = content hash for a local model folder, nothing for a hub name.
    version: str | None = None


def _default_vectors() -> dict[str, VectorConfig]:
    return {
        "code": VectorConfig(),
        "usage": VectorConfig(),
        # Slot only in Week 1: the builder returns None, so nothing is embedded.
        "summary": VectorConfig(enabled=False),
    }


@dataclass
class Config:
    device: str = "auto"  # auto | cpu | xpu | cuda | mps
    vectors: dict[str, VectorConfig] = field(default_factory=_default_vectors)
    vector_backend: str = "faiss"  # faiss | "module:Class" implementing store.VectorStore
    embedding_dim: int | None = None  # Matryoshka truncation; None = full dim
    batch_size: int = 16
    max_seq_length: int = 1024  # tokens per embedded text (keeps CPU indexing tractable)
    bm25_weights: tuple[float, float, float] = (10.0, 5.0, 1.0)  # name, signature, body
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
    steering: str = "light"  # none | light | strong
    preview_lines: int = 12
    preview_chars: int = 800
    debounce_ms: int = 400

    def enabled_vec_types(self) -> list[str]:
        return [name for name, v in self.vectors.items() if v.enabled]

    def model_id(self, vec_type: str) -> str:
        """Identity of the embedding space for a vec type: model, truncation, weights version
        and embedder class. A change rebuilds that vector set. Without a version or embedder
        it is the same string as before they existed, so old indexes stay valid."""
        spec = self.vectors[vec_type]
        out = spec.model
        if self.embedding_dim:
            out += f"@{self.embedding_dim}"
        if version := model_version(spec):
            out += f"#{version}"
        if spec.embedder:
            out += f"+{spec.embedder}"
        return out


def codemem_home() -> Path:
    return Path(os.environ.get("CODEMEM_HOME") or Path.home() / ".codemem")


# --------------------------------------------------------------------------- model version

_HASH_CACHE_NAME = "model_hashes.json"
_hash_lock = threading.Lock()
_hash_memo: dict[Path, tuple[tuple, str]] = {}


def model_version(spec: VectorConfig) -> str | None:
    """The explicit `version`, else a content hash of a local model folder, else None."""
    if spec.version:
        return spec.version
    path = Path(spec.model).expanduser()
    if path.is_dir():
        return model_folder_hash(path)
    return None


def _model_files(root: Path) -> list[Path]:
    # Skip dot folders (.git, .cache) so tool metadata doesn't change the version.
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        out.extend(Path(dirpath) / f for f in sorted(filenames) if not f.startswith("."))
    return out


def model_folder_hash(root: Path) -> str:
    """sha256 over every file's relative path and content, first 12 hex chars.

    Content, not timestamps, so the same weights give the same version on any machine.
    Per-file hashes are cached in <codemem home>/model_hashes.json by (size, mtime), so a
    checkpoint is read once, not on every update.
    """
    root = root.resolve()
    files = [(f, f.stat()) for f in _model_files(root)]
    stamps = tuple((str(f), st.st_size, st.st_mtime_ns) for f, st in files)
    cache_path = codemem_home() / _HASH_CACHE_NAME
    with _hash_lock:
        memo = _hash_memo.get(root)
        if memo is not None and memo[0] == stamps:  # unchanged since last call in this process
            return memo[1]
        try:
            cache = json.loads(cache_path.read_text("utf-8"))
        except (OSError, ValueError):
            cache = {}
        changed = False
        total = hashlib.sha256()
        for f, st in files:
            key = str(f)
            stamp = [st.st_size, st.st_mtime_ns]
            entry = cache.get(key)
            if entry is None or entry[:2] != stamp:
                h = hashlib.sha256()
                with f.open("rb") as fh:
                    while block := fh.read(1 << 20):
                        h.update(block)
                entry = [*stamp, h.hexdigest()]
                cache[key] = entry
                changed = True
            total.update(f.relative_to(root).as_posix().encode("utf-8") + b"\0" + entry[2].encode() + b"\n")
        if changed:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache_path.with_name(cache_path.name + ".tmp")
                tmp.write_text(json.dumps(cache), "utf-8")
                os.replace(tmp, cache_path)
            except OSError:  # the cache is only a speed-up
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
    return raw


def config_from_dict(raw: dict[str, Any]) -> Config:
    cfg = Config()
    vectors = _default_vectors()
    for name, spec in (raw.get("vectors") or {}).items():
        current = vectors.get(name, VectorConfig(enabled=True))
        vectors[name] = VectorConfig(
            model=spec.get("model", current.model),
            enabled=spec.get("enabled", current.enabled),
            embedder=spec.get("embedder", current.embedder),
            version=spec.get("version", current.version),
        )
        if vectors[name].embedder is not None and ":" not in vectors[name].embedder:
            raise ValueError(f"vectors.{name}.embedder must be 'module:Class', got {vectors[name].embedder!r}")
    cfg.vectors = vectors

    flat = {
        "device": raw.get("device"),
        "vector_backend": raw.get("vector_backend"),
        "embedding_dim": raw.get("embedding_dim"),
        "batch_size": raw.get("batch_size"),
        "max_seq_length": raw.get("max_seq_length"),
        "max_file_size": raw.get("max_file_size"),
        "ignore": raw.get("ignore"),
        "steering": raw.get("steering"),
        "candidates": raw.get("candidates"),
    }
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

    if cfg.device not in {"auto", "cpu", "xpu", "cuda", "mps"}:
        raise ValueError(f"device must be auto|cpu|xpu|cuda|mps, got {cfg.device!r}")
    if cfg.vector_backend != "faiss" and ":" not in cfg.vector_backend:
        raise ValueError(f"vector_backend must be faiss or 'module:Class', got {cfg.vector_backend!r}")
    if cfg.steering not in {"none", "light", "strong"}:
        raise ValueError(f"steering must be none|light|strong, got {cfg.steering!r}")
    return cfg


def load_config(repo_root: Path | None = None) -> Config:
    raw = _read_toml(codemem_home() / "config.toml")
    if repo_root is not None:
        raw = _deep_merge(raw, _read_toml(Path(repo_root) / REPO_CONFIG_NAME))
    raw = _deep_merge(raw, _env_overrides())
    return config_from_dict(raw)
