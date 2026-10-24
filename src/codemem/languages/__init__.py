"""Language registry: which files codemem reads, and how each language's syntax maps to chunks."""

from __future__ import annotations

from pathlib import PurePosixPath

from .c_family import C, Cpp, header_language
from .go import Go
from .java import Java
from .javascript import TSX, JavaScript, TypeScript
from .python import Python
from .rust import Rust
from .spec import Container, Definition, LanguageSpec

LANGUAGES: dict[str, LanguageSpec] = {
    spec.name: spec for spec in (Python(), JavaScript(), TypeScript(), TSX(), Go(), Java(), C(), Cpp(), Rust())
}
EXTENSIONS: dict[str, str] = {ext: spec.name for spec in LANGUAGES.values() for ext in spec.extensions}


def supported_languages() -> list[str]:
    return list(LANGUAGES)


def get_language(name: str) -> LanguageSpec:
    try:
        return LANGUAGES[name]
    except KeyError:
        raise ValueError(f"unsupported language {name!r}; choose from {supported_languages()}") from None


def language_for_path(path: str, data: bytes | None = None) -> str | None:
    """The language of a file by its extension (`.h` is sniffed from its content), else None."""
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".h":
        return header_language(data)
    return EXTENSIONS.get(suffix)


__all__ = [
    "EXTENSIONS", "LANGUAGES", "Container", "Definition", "LanguageSpec", "get_language",
    "language_for_path", "supported_languages",
]
