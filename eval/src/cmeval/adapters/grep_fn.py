"""grep-fn (Decision 4): the grep baseline plus the step an agent takes next.

`grep -n` gives line numbers, and an agent then reads the function around them. grep-fn maps each
matching line to the innermost named function (the same finder and rule as the gold labels) and
ranks functions by keyword matches. So grep can be graded at file, class, and function level.

The defaults are the naive ranking of the proposal: files and functions by raw match count. Four
options make it closer to how an agent greps (chosen on the dev split, 2026-10-23):
- types: search only these rg file types (for example ["py"]), not docs and data files;
- weighting = "idf": a keyword found in few files counts more than a common word, and a file or
  function scores the sum of the weights of the different keywords in it, not the raw count
  (so long functions that repeat one word do not win);
- clean_keywords: drop keywords that are URLs, paths, file names, or commit hashes;
- tests_last: rank functions in test files after all other functions (test files as the gold
  labeler sees them: patches.classify_path).

Keywords are counted on whole lines. Only the hit text cuts long lines, as `rg --max-columns`.
"""

from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..labels import LANGUAGES, Definition, find_definitions, innermost
from ..patches import LANGUAGE_BY_EXT, classify_path
from ..retriever import Hit
from ..retriever import RetrieverError
from .grep import GrepRetriever, format_lines, preview_line, rank_files, rg_count, rg_files, rg_lines
from .keywords import extract_keywords

WEIGHTINGS = ("count", "idf")
# A keyword that cannot name code: a commit hash, a path, a web address, or a file name. Not .io
# (astropy.io) and not .json (Response.json): those are often real code names. C, C++ and
# TypeScript file names since F7 (no Python sample query has one).
_F7_EXTS = "|".join(re.escape(ext[1:]) for ext, lang in LANGUAGE_BY_EXT.items() if lang in ("c", "cpp", "typescript", "tsx"))
NOISE_RE = re.compile(rf"^[0-9a-f]{{7,}}$|/|\.(com|org|net)\b|\.(py|rst|txt|md|cfg|toml|ya?ml|{_F7_EXTS})$")
SPARE_KEYWORDS = 10  # extra keywords taken before cleaning, so the cleaned list can still be full


class GrepFnRetriever(GrepRetriever):
    granularity = "line"

    def __init__(self, name: str = "grep-fn", top_files: int = 50, types: list[str] | None = None,
                 weighting: str = "count", clean_keywords: bool = False, tests_last: bool = False, **kwargs):
        super().__init__(name=name, **kwargs)
        if weighting not in WEIGHTINGS:
            raise RetrieverError(f"{name}: weighting {weighting!r} must be one of {', '.join(WEIGHTINGS)}")
        self.top_files = top_files
        self.types = list(types) if types else None
        self.weighting = weighting
        self.clean_keywords = clean_keywords
        self.tests_last = tests_last
        self._n_files: int | None = None  # files of the chosen types; fixed for one checkout
        # (path, mtime_ns, size) -> functions. Cleared on build and update, so it never grows past one commit.
        self._defs_cache: dict[tuple[str, int, int], list[Definition]] = {}

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "adapter": "grep_fn", "top_files": self.top_files, "languages": sorted(LANGUAGES),
                "types": self.types, "weighting": self.weighting, "clean_keywords": self.clean_keywords,
                "tests_last": self.tests_last}

    def _keywords(self, query: str) -> list[str]:
        if not self.clean_keywords:
            return super()._keywords(query)
        super()._keywords("")  # the same "search before build" check
        keywords = extract_keywords(query, self.max_keywords + SPARE_KEYWORDS)
        return [kw for kw in keywords if not NOISE_RE.search(kw)][: self.max_keywords]

    def _idf(self, keywords: list[str]) -> tuple[dict[str, float], dict[str, float]]:
        """Keyword weights log(N / (1 + files with it)) + 1, and each file's sum over its keywords."""
        if self._n_files is None:
            self._n_files = max(1, len(rg_files(self.rg, self.repo, types=self.types)))
        n_files = self._n_files
        with ThreadPoolExecutor(max_workers=8) as pool:  # one rg for each keyword, in parallel
            found = dict(zip(keywords, pool.map(lambda kw: rg_files(self.rg, self.repo, [kw], self.types), keywords)))
        weights = {kw: math.log(n_files / (1 + len(files))) + 1 for kw, files in found.items()}
        file_scores: dict[str, float] = {}
        for kw, files in found.items():
            for path in files:
                file_scores[path] = file_scores.get(path, 0.0) + weights[kw]
        return weights, file_scores

    def _functions(self, path: str) -> list[Definition] | None:
        """Named functions in a file of the current checkout, or None if its language has no grammar."""
        language = classify_path(path)[1]
        if language not in LANGUAGES:
            return None
        file = self.repo / path
        stat = file.stat()
        key = (path, stat.st_mtime_ns, stat.st_size)
        if key not in self._defs_cache:
            # Bytes, not text mode: text mode turns a lone "\r" into a line break, and line numbers
            # would drift from rg's, which count "\n" only.
            text = file.read_bytes().decode("utf-8", "replace")
            defs, _ = find_definitions(text, language)  # a partial parse still finds most functions
            self._defs_cache[key] = [d for d in defs if d.kind == "function"]
        return self._defs_cache[key]

    def build(self, repo: Path, index_dir: Path):
        self._defs_cache.clear()
        self._n_files = None
        return super().build(repo, index_dir)

    def search(self, query: str, k: int) -> list[Hit]:
        keywords = self._keywords(query)
        if not keywords:
            return []
        if self.weighting == "idf":
            weights, file_scores = self._idf(keywords)
            ranked = sorted(file_scores.items(), key=lambda kv: (-kv[1], kv[0]))
        else:
            weights, ranked = None, rank_files(rg_count(self.rg, self.repo, keywords, self.types))
        top = [path for path, _ in ranked[: self.top_files]]
        lines = rg_lines(self.rg, self.repo, keywords, top, max_columns=None)  # count on whole lines

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
                entry = per_function.setdefault(fn, [0, set(), []])
                for kw in keywords:
                    count = lower.count(kw)
                    if count:
                        entry[0] += count
                        entry[1].add(kw)
                entry[2].append((number, preview_line(content)))
            last = 1 if self.tests_last and classify_path(path)[0] == "test" else 0
            for fn, (raw, distinct, fn_lines) in per_function.items():
                score = sum(weights[kw] for kw in distinct) if weights else raw
                scored.append((last, -score, -raw, file_rank, fn.start, path, fn, fn_lines, score, raw))

        # The defaults sort by (raw count, file rank, start line), the same as the naive ranking.
        scored.sort(key=lambda item: item[:5])
        hits = [
            Hit(path, fn.start, fn.end, fn.symbol, float(score), format_lines(path, fn_lines[: self.max_lines]),
                {"matches": raw})
            for *_, path, fn, fn_lines, score, raw in scored[:k]
        ]
        if hits:
            hits[0].extra["keywords"] = keywords
        return hits

    def close(self) -> None:
        super().close()
        self._defs_cache.clear()
