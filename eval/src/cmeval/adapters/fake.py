"""A fake system for tests and dry runs. No real search: deterministic and fast.

It reads the repo's files with one suffix and ranks them by how many query words they contain.
A script can fix the hits for a query, so runner tests know the right answer in advance.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from ..retriever import Hit, IndexReport, RetrieverError, stable_hash

_WORD_RE = re.compile(r"[a-z0-9_]{3,}")


class FakeRetriever:
    def __init__(self, name: str = "fake", granularity: str = "line", suffix: str = ".py",
                 script: dict[str, list[dict]] | None = None):
        self.name = name
        self.granularity = granularity
        self.suffix = suffix
        self.script = script or {}
        self.files: dict[str, str] = {}
        self.calls: list[str] = []  # "build", "update", "search": tests can count them

    def describe(self) -> dict[str, Any]:
        return {"adapter": "fake", "granularity": self.granularity, "suffix": self.suffix, "scripted_queries": len(self.script)}

    def index_key(self) -> str:
        return stable_hash({"adapter": "fake", "suffix": self.suffix})

    def _index(self, repo: Path, index_dir: Path) -> IndexReport:
        start = time.perf_counter()
        repo = Path(repo)
        self.files = {
            p.relative_to(repo).as_posix(): p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(repo.rglob(f"*{self.suffix}"))
            if ".git" not in p.relative_to(repo).parts and p.is_file()
        }
        index_dir = Path(index_dir)
        index_dir.mkdir(parents=True, exist_ok=True)
        out = index_dir / "fake-index.json"
        out.write_text(json.dumps(sorted(self.files)), encoding="utf-8")
        return IndexReport(seconds=time.perf_counter() - start, bytes_on_disk=out.stat().st_size, items=len(self.files))

    def build(self, repo: Path, index_dir: Path) -> IndexReport:
        self.calls.append("build")
        return self._index(repo, index_dir)

    def update(self, repo: Path, index_dir: Path) -> IndexReport:
        self.calls.append("update")
        return self._index(repo, index_dir)

    def search(self, query: str, k: int) -> list[Hit]:
        self.calls.append("search")
        if query in self.script:
            return [Hit(**h) for h in self.script[query]][:k]
        if not self.files and "build" not in self.calls and "update" not in self.calls:
            raise RetrieverError(f"{self.name}: search before build")
        words = set(_WORD_RE.findall(query.lower()))
        scored = []
        for path, text in self.files.items():
            score = sum(text.lower().count(w) for w in words)
            if score:
                scored.append((-score, path, text))
        hits = []
        for neg_score, path, text in sorted(scored)[:k]:
            lines = text.count("\n") + (0 if text.endswith("\n") else 1)
            first = "\n".join(text.splitlines()[:3])
            if self.granularity == "line":
                hits.append(Hit(path, 1, max(lines, 1), None, float(-neg_score), first))
            else:
                hits.append(Hit(path, score=float(-neg_score), text=first))
        return hits

    def close(self) -> None:
        self.files = {}
