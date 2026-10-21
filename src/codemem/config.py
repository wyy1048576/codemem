"""Settings, paths and per-vector-type model config.

Load order (later wins): built-in defaults -> ~/.codemem/config.toml ->
<repo>/.codemem.toml -> environment variables.
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

# Directories that are never indexed, regardless of .gitignore.
ALWAYS_SKIP_DIRS = frozenset(
    {".git", "venv", ".venv", "env", "build", "dist", "node_modules", "__pycache__", "site-packages"}
)


@dataclass
class VectorConfig:
    model: str = DEFAULT_MODEL
    enabled: bool = True


def _default_vectors() -> dict[str, VectorConfig]:
    return {
        "code": VectorConfig(),
        "usage": VectorConfig(),
        # Slot only in Week 1: the builder returns None, so nothing is embedded.
        "summary": VectorConfig(enabled=False),
    }


@dataclass
class Config:
    device: str = "auto"  # auto | cpu | xpu | cuda
    vectors: dict[str, VectorConfig] = field(default_factory=_default_vectors)
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
        """Identity of the embedding space for a vec type (model + truncation)."""
        model = self.vectors[vec_type].model
        return f"{model}@{self.embedding_dim}" if self.embedding_dim else model


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
    return raw


def config_from_dict(raw: dict[str, Any]) -> Config:
    cfg = Config()
    vectors = _default_vectors()
    for name, spec in (raw.get("vectors") or {}).items():
        current = vectors.get(name, VectorConfig(enabled=True))
        vectors[name] = VectorConfig(
            model=spec.get("model", current.model), enabled=spec.get("enabled", current.enabled)
        )
    cfg.vectors = vectors

    flat = {
        "device": raw.get("device"),
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

    if cfg.device not in {"auto", "cpu", "xpu", "cuda"}:
        raise ValueError(f"device must be auto|cpu|xpu|cuda, got {cfg.device!r}")
    if cfg.steering not in {"none", "light", "strong"}:
        raise ValueError(f"steering must be none|light|strong, got {cfg.steering!r}")
    return cfg


def load_config(repo_root: Path | None = None) -> Config:
    raw = _read_toml(codemem_home() / "config.toml")
    if repo_root is not None:
        raw = _deep_merge(raw, _read_toml(Path(repo_root) / REPO_CONFIG_NAME))
    raw = _deep_merge(raw, _env_overrides())
    return config_from_dict(raw)
