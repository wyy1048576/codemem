"""System configs (TOML) and the adapter registry.

A config file lists systems to compare. An ablation is a list of systems in one file:

    [[system]]
    name = "cm-bm25-code"      # unique; used in run file names
    adapter = "codemem"        # a key of ADAPTERS
    signals = ["bm25", "code"] # every other key is passed to the adapter

Adapters are imported by name only when a config uses them, so the suite works without
optional packages (for example codemem) that other adapters need.
"""

from __future__ import annotations

import importlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .retriever import GRANULARITIES, Retriever

# adapter name -> "module:factory". The factory is called as factory(name=..., **params).
ADAPTERS: dict[str, str] = {
    "fake": "cmeval.adapters.fake:FakeRetriever",
    "grep": "cmeval.adapters.grep:GrepRetriever",
    "grep_fn": "cmeval.adapters.grep_fn:GrepFnRetriever",
}

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class SystemsError(ValueError):
    """A system config is not valid, or an adapter cannot be made."""


@dataclass
class SystemSpec:
    name: str
    adapter: str
    params: dict[str, Any] = field(default_factory=dict)


def parse_systems(data: dict[str, Any], where: str = "config") -> list[SystemSpec]:
    entries = data.get("system")
    if not isinstance(entries, list) or not entries:
        raise SystemsError(f"{where}: needs at least one [[system]] table")
    unknown = sorted(set(data) - {"system"})
    if unknown:
        raise SystemsError(f"{where}: unknown top-level keys: {', '.join(unknown)}")
    specs: list[SystemSpec] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        params = dict(entry)
        name = params.pop("name", None)
        adapter = params.pop("adapter", None)
        if not (isinstance(name, str) and _NAME_RE.match(name)):
            raise SystemsError(f"{where}: system {i}: name {name!r} must use only letters, digits, '_', '.', '-'")
        if name in seen:
            raise SystemsError(f"{where}: system name {name!r} is used twice")
        if adapter not in ADAPTERS:
            raise SystemsError(f"{where}: system {name!r}: unknown adapter {adapter!r} (known: {', '.join(sorted(ADAPTERS))})")
        seen.add(name)
        specs.append(SystemSpec(name, adapter, params))
    return specs


def load_systems(path: Path | str) -> list[SystemSpec]:
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemsError(f"{path.name}: not valid TOML: {exc}") from None
    return parse_systems(data, path.name)


def make_system(spec: SystemSpec) -> Retriever:
    """Import the adapter and build the system. Bad settings are reported with the system name."""
    module_name, factory_name = ADAPTERS[spec.adapter].split(":")
    try:
        factory = getattr(importlib.import_module(module_name), factory_name)
    except ImportError as exc:
        raise SystemsError(f"system {spec.name!r}: adapter {spec.adapter!r} needs a package that is not installed: {exc}") from None
    try:
        system = factory(name=spec.name, **spec.params)
    except TypeError as exc:
        raise SystemsError(f"system {spec.name!r}: bad settings for adapter {spec.adapter!r}: {exc}") from None
    if not isinstance(system, Retriever):
        raise SystemsError(f"system {spec.name!r}: adapter {spec.adapter!r} does not implement Retriever")
    if system.granularity not in GRANULARITIES:
        raise SystemsError(f"system {spec.name!r}: granularity {system.granularity!r} is not one of {', '.join(GRANULARITIES)}")
    return system
