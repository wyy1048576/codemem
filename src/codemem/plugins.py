"""Load plugin classes named in config as "module:attr" (e.g. "mypkg.embed:MyEmbedder")."""

from __future__ import annotations

import importlib
from typing import Any


def load_object(spec: str) -> Any:
    module_name, sep, attr = spec.partition(":")
    if not sep or not module_name or not attr:
        raise ValueError(f"expected 'module:attr', got {spec!r}")
    try:
        obj: Any = importlib.import_module(module_name)
    except ImportError as e:
        raise ImportError(f"cannot import {module_name!r} for plugin {spec!r}: {e}") from e
    for part in attr.split("."):
        try:
            obj = getattr(obj, part)
        except AttributeError:
            raise ImportError(f"{module_name!r} has no attribute {attr!r} (plugin {spec!r})") from None
    return obj
