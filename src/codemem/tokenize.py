"""Code-aware tokenization for BM25.

The same function is applied to indexed text and to queries. Output tokens are
lowercase and contain only [a-z0-9_], so FTS5's unicode61 tokenizer (configured
with tokenchars '_') does no further splitting.

A change to the output needs a SCHEMA_VERSION bump: the keyword table keeps no copy
of its text, so removing a row recomputes the row's tokens with this code.
"""

from __future__ import annotations

import re
from functools import lru_cache

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")

STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were "
    "will with self cls".split()
)


def split_identifier(ident: str) -> list[str]:
    """`revoke_session` -> [revoke, session]; `getUserById` -> [get, user, by, id]."""
    return list(_split_identifier(ident))


@lru_cache(maxsize=1 << 17)
def _split_identifier(ident: str) -> tuple[str, ...]:
    # Identifiers repeat a lot across a repo, so indexing a large one splits each only once.
    parts: list[str] = []
    for piece in ident.split("_"):
        parts.extend(p.lower() for p in _CAMEL.findall(piece))
    return tuple(parts)


def _stem(token: str) -> str:
    # Deliberately light: plural and common verb suffixes only.
    for suffix, min_len in (("ies", 5), ("ing", 6), ("ed", 5), ("es", 5), ("s", 4)):
        if token.endswith(suffix) and len(token) >= min_len and not token.endswith("ss"):
            return token[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return token


def tokenize(text: str, *, stem: bool = False, stopwords: bool = False) -> list[str]:
    tokens: list[str] = []
    for ident in _IDENT.findall(text):
        parts = _split_identifier(ident)
        tokens.extend(parts)
        full = ident.lower().strip("_")
        if len(parts) > 1 and full:
            # Keep the whole identifier too, so exact-name queries score highest.
            tokens.append(full)
    if stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS]
    if stem:
        tokens = [_stem(t) for t in tokens]
    return tokens


def to_fts_text(text: str, **opts: bool) -> str:
    return " ".join(tokenize(text, **opts))


def fts_match_query(query: str, **opts: bool) -> str | None:
    """Build a safe FTS5 MATCH expression: quoted tokens OR-ed together."""
    return fts_or(tokenize(query, **opts))


def fts_or(tokens: list[str]) -> str | None:
    """Distinct tokens as one FTS5 MATCH expression, OR-ed together."""
    seen = dict.fromkeys(tokens)
    if not seen:
        return None
    # Tokens are [a-z0-9_] only, but quote anyway so FTS5 keywords (AND/OR/NEAR) stay literal.
    return " OR ".join('"' + tok.replace('"', '""') + '"' for tok in seen)
