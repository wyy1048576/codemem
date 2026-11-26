"""Shared data for the offline retrieval lab: tasks, gold labels, query vectors, and one index's
chunks, vectors and call edges in numpy. Everything is read from copies under .cache/review/lab/idx.
No model is needed: every chunk's vector is stored, so any candidate is scored exactly.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import numpy as np

ROOT = Path("/Users/andres/Desktop/CS329M/codemem")
LAB = ROOT / ".cache/review/lab"
WT = ROOT / ".cache/wt/lab-main"
DATA = ROOT / ".personal/benchmarks/data"
OUT = LAB / "out"
REPOS = {
    "pandas": {"repo": "pandas-dev/pandas", "index": LAB / "idx/pandas", "tasks": WT / "eval/tasks/e2e/pandas.jsonl",
               "qvec": DATA / "queries-pandas-dev__pandas-fcd0fc71c092.npy"},
    "vllm": {"repo": "vllm-project/vllm", "index": LAB / "idx/vllm", "tasks": WT / "eval/tasks/e2e/vllm.jsonl",
             "qvec": DATA / "queries-vllm-project__vllm-bcd15f72f080.npy"},
}
VAGUE = WT / "eval/tasks/vague-b7-v2.jsonl"
EXTRA_VECS = LAB / "qvec-extra.npz"  # made by embed_extra.py: vague L1/L2 and the issue titles
DIM = 896


def half(task_id: str) -> int:
    """0 = the half settings are chosen on, 1 = the half results are reported on."""
    return int(hashlib.sha256(task_id.encode("utf-8")).hexdigest(), 16) % 2


def title_of(query: str) -> str:
    return query.split("\n", 1)[0].strip()


def load_tasks(name: str) -> list[dict]:
    """The repo's tasks in the task file's order (the order of the stored question vectors)."""
    spec = REPOS[name]
    rows = []
    for line in spec["tasks"].read_text("utf-8").split("\n"):
        if line.strip():
            t = json.loads(line)
            if t.get("repo") == spec["repo"]:
                rows.append(t)
    vecs = np.load(spec["qvec"]).astype(np.float32)
    assert len(vecs) == len(rows), (len(vecs), len(rows))
    out = []
    for i, t in enumerate(rows):
        g = t["gold"]
        out.append({
            "id": t["id"], "query": t["query"], "vec": vecs[i], "split": t.get("split"), "n": i,
            "gold_files": set(g["files"]),
            "gold_fns": {(f["path"], f["symbol"]) for f in g["functions"] if f.get("symbol")},
            "gold_classes": {(c["path"], c["symbol"]) for c in g.get("classes", []) if c.get("symbol")},
            "tags": t.get("tags") or {}, "base_commit": t["base_commit"], "language": t.get("language"),
            "issue_created": (t.get("issue") or {}).get("created_at"), "half": half(t["id"]),
        })
    return out


def load_vague() -> dict[str, dict[str, str]]:
    """task id -> {"L1": text, "L2": text}, pandas tasks only."""
    out: dict[str, dict[str, str]] = {}
    for line in VAGUE.read_text("utf-8").split("\n"):
        if line.strip():
            r = json.loads(line)
            if r["id"].startswith("pandas-dev__pandas"):
                out.setdefault(r["id"], {})[r["level"]] = r["prompt"]
    return out


def query_sets(names=("vllm-L0", "pandas-L0", "vague-L0", "vague-L1", "vague-L2")) -> dict[str, dict]:
    """name -> {"repo": index name, "tasks": [task dicts with query text and vector]}.
    Also "vllm-title" and "pandas-title": the issue's first line as the query."""
    sets: dict[str, dict] = {}
    cache: dict[str, list[dict]] = {}
    extra = np.load(EXTRA_VECS, allow_pickle=False) if EXTRA_VECS.is_file() else None

    def tasks(repo: str) -> list[dict]:
        if repo not in cache:
            cache[repo] = load_tasks(repo)
        return cache[repo]

    for name in names:
        kind = name.split("-", 1)
        if name in ("vllm-L0", "pandas-L0"):
            sets[name] = {"repo": kind[0], "tasks": [dict(t) for t in tasks(kind[0])]}
        elif name in ("vllm-title", "pandas-title"):
            ids = extra[f"{kind[0]}_title_ids"].tolist()
            vecs = extra[f"{kind[0]}_title"]
            by = {i: v for i, v in zip(ids, vecs)}
            sets[name] = {"repo": kind[0], "tasks": [
                {**t, "query": title_of(t["query"]), "vec": by[t["id"]].astype(np.float32)} for t in tasks(kind[0])]}
        elif name.startswith("vague-"):
            level = kind[1]
            vague = load_vague()
            rows = [t for t in tasks("pandas") if t["id"] in vague]
            if level == "L0":
                sets[name] = {"repo": "pandas", "tasks": [dict(t) for t in rows]}
            else:
                ids = extra["vague_ids"].tolist()
                by = {i: v for i, v in zip(ids, extra[f"vague_{level}"])}
                sets[name] = {"repo": "pandas", "tasks": [
                    {**t, "query": vague[t["id"]][level], "vec": by[t["id"]].astype(np.float32), "l0_query": t["query"]}
                    for t in rows]}
        else:
            raise KeyError(name)
    return sets


def for_index(vecs: np.ndarray) -> np.ndarray:
    """As codemem.store.for_index: normalised float32, rounded to float16 values again."""
    out = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    out = out / np.where(norms == 0, 1.0, norms)
    return out.astype(np.float16).astype(np.float32)


def prep_query(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, dtype=np.float32).reshape(-1)[:DIM]
    n = float(np.linalg.norm(q))
    return q / (n if n else 1.0)


class Index:
    """One index copy in memory. Chunks are numbered 0..N-1 ("rows", in chunk-id order)."""

    def __init__(self, name: str, vectors: bool = True, code_text: bool = False):
        t0 = time.perf_counter()
        self.name = name
        self.dir = REPOS[name]["index"]
        self.con = sqlite3.connect(f"file:{self.dir}/index.db?mode=ro", uri=True)
        cols = ("chunk_id, path, qualname, name, kind, subkind, start_line, end_line, is_test, parent_key, key, "
                "length(code), class_name, language, length(skeleton)")
        rows = self.con.execute(f"SELECT {cols} FROM chunks ORDER BY chunk_id").fetchall()
        self.N = len(rows)
        self.ids = np.array([r[0] for r in rows], dtype=np.int64)
        self.row_of = {cid: i for i, cid in enumerate(self.ids.tolist())}
        self.path = [r[1] for r in rows]
        self.qualname = [r[2] for r in rows]
        self.cname = [r[3] for r in rows]
        self.kind = [r[4] for r in rows]
        self.subkind = [r[5] for r in rows]
        self.start = np.array([r[6] for r in rows], dtype=np.int32)
        self.end = np.array([r[7] for r in rows], dtype=np.int32)
        self.is_test = np.array([bool(r[8]) for r in rows])
        self.parent_key = [r[9] for r in rows]
        self.key = [r[10] for r in rows]
        self.code_chars = np.array([r[11] for r in rows], dtype=np.int64)
        self.class_name = [r[12] for r in rows]
        self.language = [r[13] for r in rows]
        self.skel_chars = np.array([r[14] for r in rows], dtype=np.int64)
        self.row_of_key = {k: i for i, k in enumerate(self.key)}
        self.folder = [p.rsplit("/", 1)[0] if "/" in p else "" for p in self.path]
        self.paths = sorted(set(self.path))
        self.file_no = {p: i for i, p in enumerate(self.paths)}
        self.file_of = np.array([self.file_no[p] for p in self.path], dtype=np.int32)
        folders = sorted(set(self.folder))
        self.folder_no = {f: i for i, f in enumerate(folders)}
        self.folder_of = np.array([self.folder_no[f] for f in self.folder], dtype=np.int32)
        order = np.argsort(self.file_of, kind="stable")
        self._file_rows = order
        self._file_ptr = np.searchsorted(self.file_of[order], np.arange(len(self.paths) + 1))
        self.symbol_rows: dict[tuple[str, str], list[int]] = {}
        for i in range(self.N):
            self.symbol_rows.setdefault((self.path[i], self.qualname[i]), []).append(i)
        self.path_set = set(self.paths)
        # call edges, both directions (CSR)
        e = np.array(self.con.execute("SELECT caller_id, callee_id FROM edges").fetchall(), dtype=np.int64).reshape(-1, 2)
        lookup = np.full(int(self.ids.max()) + 1, -1, dtype=np.int64)
        lookup[self.ids] = np.arange(self.N)
        caller, callee = lookup[e[:, 0]], lookup[e[:, 1]]
        ok = (caller >= 0) & (callee >= 0)
        caller, callee = caller[ok], callee[ok]
        self.n_edges = int(ok.sum())
        self.e_caller, self.e_callee = caller, callee
        self._out_ptr, self._out = self._csr(caller, callee)  # row -> its callees
        self._in_ptr, self._in = self._csr(callee, caller)  # row -> its callers
        self.out_deg = np.diff(self._out_ptr)
        self.in_deg = np.diff(self._in_ptr)
        self._graphs: dict[str, tuple] = {}
        self.V: dict[str, np.ndarray] = {}
        self.owner: dict[str, np.ndarray] = {}
        self.vinfo: dict[str, np.ndarray] = {}
        self._starts: dict[str, np.ndarray] = {}
        self._owners_u: dict[str, np.ndarray] = {}
        if vectors:
            for vt in ("code", "usage"):
                self._load_vectors(vt, lookup)
        self.load_s = time.perf_counter() - t0

    def _csr(self, src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        order = np.argsort(src, kind="stable")
        ptr = np.searchsorted(src[order], np.arange(self.N + 1))
        return ptr, dst[order].astype(np.int32)

    def _load_vectors(self, vt: str, lookup: np.ndarray) -> None:
        cur = self.con.execute(
            "SELECT chunk_id, part, n_parts, start_off, end_off, data FROM vectors NOT INDEXED WHERE vec_type = ? "
            "ORDER BY vector_id", (vt,))
        info, mats = [], []
        while True:
            rows = cur.fetchmany(8192)
            if not rows:
                break
            info.extend((r[0], r[1], r[2], r[3], r[4]) for r in rows)
            raw = np.frombuffer(b"".join(r[5] for r in rows), dtype=np.float16).reshape(len(rows), -1)
            mats.append(for_index(raw[:, :DIM]))
        V = np.concatenate(mats)
        del mats
        info_a = np.array(info, dtype=np.int64)
        owner = lookup[info_a[:, 0]]
        keep = owner >= 0
        V, info_a, owner = V[keep], info_a[keep], owner[keep]
        order = np.argsort(owner, kind="stable")
        self.V[vt] = np.ascontiguousarray(V[order])
        self.owner[vt] = owner[order]
        self.vinfo[vt] = info_a[order]
        owners_u, starts = np.unique(self.owner[vt], return_index=True)
        self._owners_u[vt] = owners_u
        self._starts[vt] = starts

    # ---- edge versions (the coordinator's three): "a" all edges; "b99"/"b90" without the edges to
    # callees that have more callers than the 99th/90th percentile of callers per callee; "c" only
    # the edges whose callee's name is defined once (callable kinds, per language family)
    def edge_mask(self, version: str) -> np.ndarray:
        if version == "a":
            return np.ones(len(self.e_caller), dtype=bool)
        if version in ("b99", "b90"):
            callers_per = self.in_deg[self.in_deg > 0]
            k = int(np.percentile(callers_per, 99 if version == "b99" else 90))
            return self.in_deg[self.e_callee] <= k
        if version == "c":
            from collections import Counter
            from codemem.store import _family
            fam = [_family(x) for x in self.language]
            defs = Counter((fam[i], self.cname[i]) for i in range(self.N) if self.kind[i] in ("function", "method", "class"))
            uniq = np.array([defs[(fam[i], self.cname[i])] == 1 for i in range(self.N)])
            return uniq[self.e_callee]
        raise KeyError(version)

    def graph(self, version: str = "a") -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """(out_ptr, out, in_ptr, in) of one edge version, CSR by row."""
        if version not in self._graphs:
            m = self.edge_mask(version)
            op, o = self._csr(self.e_caller[m], self.e_callee[m])
            ip, i = self._csr(self.e_callee[m], self.e_caller[m])
            self._graphs[version] = (op, o, ip, i)
        return self._graphs[version]

    def neighbours(self, row: int, version: str = "a", direction: str = "both") -> np.ndarray:
        op, o, ip, i = self.graph(version)
        parts = []
        if direction in ("callees", "both"):
            parts.append(o[op[row]:op[row + 1]])
        if direction in ("callers", "both"):
            parts.append(i[ip[row]:ip[row + 1]])
        return np.concatenate(parts) if len(parts) > 1 else parts[0]

    # ---- structure
    def callees(self, row: int) -> np.ndarray:
        return self._out[self._out_ptr[row]:self._out_ptr[row + 1]]

    def callers(self, row: int) -> np.ndarray:
        return self._in[self._in_ptr[row]:self._in_ptr[row + 1]]

    def file_rows(self, file_no: int) -> np.ndarray:
        return self._file_rows[self._file_ptr[file_no]:self._file_ptr[file_no + 1]]

    def has_vec(self, vt: str) -> np.ndarray:
        out = np.zeros(self.N, dtype=bool)
        out[self._owners_u[vt]] = True
        return out

    # ---- exact scores
    def scores(self, vt: str, q: np.ndarray) -> np.ndarray:
        """Every chunk's similarity to the query by one vector type (its best part); -inf where
        the chunk has no vector of the type."""
        s = self.V[vt] @ prep_query(q)
        out = np.full(self.N, -np.inf, dtype=np.float32)
        out[self._owners_u[vt]] = np.maximum.reduceat(s, self._starts[vt])
        return out

    def gold_rows(self, task: dict) -> tuple[set[int], set[int]]:
        """(file numbers of the gold files the index has, rows of the gold functions it has)."""
        files = {self.file_no[p] for p in task["gold_files"] if p in self.file_no}
        fns: set[int] = set()
        for sym in task["gold_fns"]:
            fns.update(self.symbol_rows.get(sym, ()))
        return files, fns


def top_rows(scores: np.ndarray, n: int) -> np.ndarray:
    """Rows of the n best scores, best first (ties by row number, which is chunk-id order)."""
    n = min(n, len(scores))
    part = np.argpartition(-scores, n - 1)[:n] if n < len(scores) else np.arange(len(scores))
    part = part[np.lexsort((part, -scores[part]))]
    return part[np.isfinite(scores[part])]


def rrf(lists: dict[str, np.ndarray | list], k: int = 60, weights: dict[str, float] | None = None,
        depth: dict[str, int] | int | None = None) -> dict[int, float]:
    weights = weights or {}
    out: dict[int, float] = {}
    for name, ids in lists.items():
        w = weights.get(name, 1.0)
        if w == 0:
            continue
        d = depth.get(name) if isinstance(depth, dict) else depth
        seq = ids[:d] if d else ids
        for rank, doc in enumerate(seq, start=1):
            doc = int(doc)
            out[doc] = out.get(doc, 0.0) + w / (k + rank)
    return out


def boot_ci(diff: np.ndarray, n_boot: int = 10000, seed: int = 7) -> tuple[float, float, float]:
    """Mean of a paired per-task difference and its 95% bootstrap interval over tasks."""
    diff = np.asarray(diff, dtype=np.float64)
    if len(diff) == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diff), size=(n_boot, len(diff)))
    means = diff[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(diff.mean()), float(lo), float(hi)
