"""grep-fn (Decision 4): the grep baseline plus the step an agent takes next.

`grep -n` gives line numbers, and an agent then reads the function around them. grep-fn maps each
matching line to the innermost named function (the same finder and rule as the gold labels) and
ranks functions by keyword matches. So grep can be graded at file, class, and function level.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..labels import LANGUAGES, Definition, find_definitions, innermost
from ..patches import classify_path
from ..retriever import Hit
from .grep import GrepRetriever, format_lines, rg_count, rg_lines


class GrepFnRetriever(GrepRetriever):
    granularity = "line"

    def __init__(self, name: str = "grep-fn", top_files: int = 50, **kwargs):
        super().__init__(name=name, **kwargs)
        self.top_files = top_files
        self._defs_cache: dict[tuple[str, str], list[Definition]] = {}

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "adapter": "grep_fn", "top_files": self.top_files, "languages": sorted(LANGUAGES)}

    def _functions(self, path: str) -> list[Definition] | None:
        """Named functions in a file of the current checkout, or None if its language has no grammar."""
        language = classify_path(path)[1]
        if language not in LANGUAGES:
            return None
        text = (self.repo / path).read_text(encoding="utf-8", errors="replace")
        key = (path, hashlib.sha256(text.encode("utf-8")).hexdigest())
        if key not in self._defs_cache:
            defs, _ = find_definitions(text, language)  # a partial parse still finds most functions
            self._defs_cache[key] = [d for d in defs if d.kind == "function"]
        return self._defs_cache[key]

    def search(self, query: str, k: int) -> list[Hit]:
        keywords = self._keywords(query)
        if not keywords:
            return []
        counts = rg_count(self.rg, self.repo, keywords)
        top = [path for path, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[: self.top_files]]
        lines = rg_lines(self.rg, self.repo, keywords, top)

        scored = []
        for file_rank, path in enumerate(top):
            functions = self._functions(path)
            if not functions:
                continue  # no grammar for this language, or no functions: lines cannot be mapped
            per_function: dict[Definition, list] = {}
            for number, content in lines.get(path, []):
                fn = innermost(functions, number)
                if fn is None:
                    continue  # a match outside every function
                lower = content.lower()
                entry = per_function.setdefault(fn, [0, []])
                entry[0] += sum(lower.count(kw) for kw in keywords)
                entry[1].append((number, content))
            for fn, (score, fn_lines) in per_function.items():
                scored.append((-score, file_rank, fn.start, path, fn, fn_lines))

        scored.sort(key=lambda item: item[:3])
        hits = [
            Hit(path, fn.start, fn.end, fn.symbol, float(-neg_score), format_lines(path, fn_lines[: self.max_lines]),
                {"matches": -neg_score})
            for neg_score, _, _, path, fn, fn_lines in scored[:k]
        ]
        if hits:
            hits[0].extra["keywords"] = keywords
        return hits

    def close(self) -> None:
        super().close()
        self._defs_cache.clear()
