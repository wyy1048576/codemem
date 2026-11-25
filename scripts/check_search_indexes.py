"""On a real index and the eval's own questions for that repo: does each search index return what
the exact one returns, and how long does a search take with it?

    uv run python scripts/check_search_indexes.py --index <index folder> --repo pandas-dev/pandas

`--index` is the folder of an index that codemem built with the real model (it holds `index.db`).
`--repo` is the repo's name as the eval's task files spell it. Everything else has a default:

  --tasks     the task file with the questions: by default the file in eval/tasks that has the
              most tasks for the repo (fresh-v1 for pandas, fresh-ts-v1 for playwright)
  --settings  the search indexes to compare, the first being the reference. By default: the exact
              index; `auto` (the default rule: exact while it fits the memory budget, else
              compact); the compact index as `auto` uses it (4 bits, 200 candidates); 2 bits with
              500; 1 bit with 500 and with 1,000
  --out       the JSON file to write (default: search-indexes-<repo>.json in this folder)
  --work      where the copy of the index goes (default: a new folder in the temp directory)
  --config    a codemem config file (TOML, like .codemem.toml), when the index was built with
              settings that are not this machine's own (by default: ~/.codemem/config.toml and
              the CODEMEM_* variables, as codemem reads them)

The index is never changed. The script copies `index.db` into the work folder (as much disk as
that file takes: 232 MB for pandas), runs on the copy and deletes it. No other codemem process
should be writing the index while it is copied. Every setting builds its search index from the
copy's stored vectors; the saved search indexes are not read and none is written.

The questions are the tasks' issue texts. They are embedded as queries by the embedder this
machine's configuration gives, which has to be the one the index was built with (the model, the
length, the number type and the device, as the index records them): the script names it and
stops if they differ. The vectors are kept beside the output file, so a second run embeds nothing.

For each question and vector type the script asks for the 50 best chunks, as a search does, and
compares with the reference: is the top 10 the same set, and how much of the top 50 is shared.
Then the whole search (keywords and vectors merged, 10 results): are the 10 results the same, in
the same order. All of it per split (dev, test) and together, with the median time of each call.

A pass: the rows `auto` and `compact:bits=4,rescore=200` show 1.000 for "top 10 same" of every
vector type and for "merged same", and 0.999 or more for the top-50 overlap. The 2-bit and 1-bit
rows are there to compare, and may lose a little. The last line says PASS or names what differs.
Send back the table as it is printed, and the JSON file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections import defaultdict
from pathlib import Path

import codemem  # before FAISS and PyTorch: on macOS it sets OpenMP up for the two of them (codemem/__init__.py)

import faiss  # noqa: E402
import numpy as np  # noqa: E402

from codemem.config import config_from_dict, load_config, physical_memory
from codemem.embedder import Embedder, make_embedder
from codemem.search import search
from codemem.store import Store

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = "faiss;auto;compact:bits=4,rescore=200;compact:bits=2,rescore=500;compact:bits=1,rescore=500;compact:bits=1,rescore=1000"
MUST_AGREE = ("auto", "compact:bits=4,rescore=200")  # the default rule, and the compact index as it uses it
COMPACT = {"bits": 4, "dim": 0, "rescore": 200}


class Precomputed(Embedder):
    """Query vectors made earlier, by text: the merged search then needs no model."""

    def __init__(self, vectors: dict[str, np.ndarray], dim: int, key: str):
        self.model_name, self._vectors, self._dim, self._key = "precomputed", vectors, dim, key

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def key(self) -> str:
        return self._key

    def embed_documents(self, texts):
        raise RuntimeError("this check embeds no documents")

    def embed_queries(self, texts):
        return np.stack([self._vectors[t] for t in texts])


def task_file(repo: str, name: str | None) -> Path:
    folder = ROOT / "eval" / "tasks"
    if name:
        path = Path(name) if Path(name).is_file() else folder / f"{name.removesuffix('.jsonl')}.jsonl"
        if not path.is_file():
            sys.exit(f"no task file {name}: give a path, or the name of a file in {folder}")
        return path
    counts = {}
    for path in sorted(folder.glob("*.jsonl")):
        counts[path] = sum(1 for line in path.read_text("utf-8").split("\n") if line.strip() and json.loads(line)["repo"] == repo)
    best = max(counts, key=counts.get, default=None)
    if best is None or not counts[best]:
        repos = sorted({json.loads(line)["repo"] for p in counts for line in p.read_text("utf-8").split("\n") if line.strip()})
        sys.exit(f"no task in {folder} is for the repo {repo!r}. The task files know: {', '.join(repos)}")
    return best


def questions(path: Path, repo: str, limit: int) -> list[dict]:
    """The repo's tasks, in the file's order; `n` is a task's place among them (with a limit,
    the first so many of each split are kept)."""
    rows, seen, n = [], defaultdict(int), 0
    for line in path.read_text("utf-8").split("\n"):
        if not line.strip():
            continue
        task = json.loads(line)
        if task["repo"] != repo:
            continue
        split = task.get("split", "dev")
        if not limit or seen[split] < limit:
            rows.append({"id": task["id"], "split": split, "query": task["query"], "n": n})
            seen[split] += 1
        n += 1
    return rows


def copy_index(index: Path, work: Path | None) -> tuple[Path, Path, int]:
    """A copy of the index's database in a folder of its own: (the copy, the folder to delete, bytes)."""
    files = [index / name for name in ("index.db", "index.db-wal", "index.db-shm") if (index / name).is_file()]
    if not files or files[0].name != "index.db":
        sys.exit(f"{index} holds no index.db: --index is the folder of a codemem index")
    size = sum(f.stat().st_size for f in files)
    if work is not None:
        work.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="codemem-search-indexes-", dir=work))
    free = shutil.disk_usage(folder).free
    if free < size * 1.2:
        shutil.rmtree(folder, ignore_errors=True)
        sys.exit(f"the copy of the index needs {size / 1e6:,.0f} MB and {folder.parent} has {free / 1e6:,.0f} MB free: "
                 "give another folder with --work")
    copy = folder / "index"
    copy.mkdir()
    for f in files:
        shutil.copy2(f, copy / f.name)
    return copy, folder, size


def open_store(index: Path, setting: str) -> Store:
    """`faiss`, `auto`, or `compact` with options written `compact:bits=1,rescore=500`. For `auto`,
    `memory_mb=N` sets its budget."""
    name, _, text = setting.partition(":")
    given = {k: int(v) for k, v in (kv.split("=") for kv in text.split(",") if kv)}
    memory_mb = given.pop("memory_mb", 0)
    options = {**COMPACT, **given} if name in ("auto", "compact") else given
    return Store(index, vector_backend=name, vector_options=options, vector_memory_mb=memory_mb)


def embedder_of(store: Store, config) -> tuple[Embedder, str]:
    """The embedder this machine's configuration gives, checked against what the index recorded."""
    keys = {}
    for vec_type in store.vec_types():
        if vec_type not in config.vectors:
            sys.exit(f"the index has {vec_type} vectors, and the configuration has no such vector type")
        embedder = make_embedder(config.vectors[vec_type], config)
        built_with = store.get_meta(f"vec.{vec_type}.embedder")
        if embedder.key != built_with:
            sys.exit(f"the index's {vec_type} vectors were made by\n    {built_with}\nand this machine's configuration embeds with\n"
                     f"    {embedder.key}\nThe questions must be embedded as the index was: run this where the index was "
                     "built, with the configuration it was built with.")
        keys[vec_type] = embedder
    if len({e.key for e in keys.values()}) != 1:
        sys.exit("the index's vector types were made by different embedders; this check embeds a question once")
    embedder = next(iter(keys.values()))
    return embedder, embedder.key


def query_vectors(rows: list[dict], embedder: Embedder, key: str, cache: Path, given: str | None) -> np.ndarray:
    if given:
        vecs = np.load(given)  # one for each of the repo's tasks, in the task file's order
        if len(vecs) <= max(r["n"] for r in rows):
            sys.exit(f"{given} holds {len(vecs)} vectors, fewer than the repo has tasks")
        print(f"question vectors read from {given}: they must have been made by {key}")
        return vecs[[r["n"] for r in rows]].astype(np.float32)
    digest = hashlib.sha256("\n".join([key, *(r["query"] for r in rows)]).encode("utf-8")).hexdigest()[:12]
    path = cache.with_name(f"{cache.stem}.questions-{digest}.npy")
    if path.is_file():
        print(f"question vectors read from {path.name} (made earlier by {key})")
        return np.load(path)
    print(f"embedding {len(rows)} questions as queries with the index's own embedder, {key} ...", flush=True)
    t = time.perf_counter()
    vecs = embedder.embed_queries([r["query"] for r in rows]).astype(np.float32)
    np.save(path, vecs)
    print(f"  done in {time.perf_counter() - t:.0f} s; kept in {path.name}", flush=True)
    return vecs


def run(index: Path, setting: str, rows: list[dict], vecs: np.ndarray, key: str, config) -> dict:
    store = open_store(index, setting)
    t = time.perf_counter()
    store.load_vectors()
    load_s = time.perf_counter() - t
    by_text = {r["query"]: v for r, v in zip(rows, vecs)}
    precomputed = Precomputed(by_text, vecs.shape[1], key)
    status = store.search_index_status()
    out: dict = {"load_s": round(load_s, 2), "index": status["index"], "why": status["why"],
                 "memory_mb": {t: v["memory_mb"] for t, v in status["types"].items()}, "per_query": []}
    for r, v in zip(rows, vecs):
        entry: dict = {"id": r["id"], "split": r["split"], "ms": {}}
        for vec_type in store.vec_types():
            t = time.perf_counter()
            hits = store.vector_search(vec_type, v, 50)
            entry["ms"][vec_type] = (time.perf_counter() - t) * 1000
            entry[vec_type] = [h.chunk_id for h in hits]
        t = time.perf_counter()
        resp = search(store, r["query"], config, k=10, embedder_factory=lambda spec, cfg: precomputed)
        entry["ms"]["search"] = (time.perf_counter() - t) * 1000
        entry["search"] = [c.chunk_id for c in resp.results]
        out["per_query"].append(entry)
    store.close()
    return out


def compare(reference: dict, other: dict, vec_types: list[str]) -> dict:
    result: dict = {}
    for split in ("dev", "test", "all"):
        pairs = [(a, b) for a, b in zip(reference["per_query"], other["per_query"]) if split in (a["split"], "all")]
        if not pairs:
            continue
        row: dict = {"questions": len(pairs)}
        for vec_type in vec_types:
            same10 = [set(a[vec_type][:10]) == set(b[vec_type][:10]) for a, b in pairs]
            over10 = [len(set(a[vec_type][:10]) & set(b[vec_type][:10])) / max(1, len(a[vec_type][:10])) for a, b in pairs]
            over50 = [len(set(a[vec_type]) & set(b[vec_type])) / max(1, len(a[vec_type])) for a, b in pairs]
            row[vec_type] = {"top10_same_set": round(float(np.mean(same10)), 4), "top10_overlap": round(float(np.mean(over10)), 4),
                             "top50_overlap": round(float(np.mean(over50)), 4), "top10_differ": int(len(same10) - sum(same10)),
                             "worst_top50_overlap": round(float(min(over50)), 2)}
        same_list = [a["search"] == b["search"] for a, b in pairs]
        same_set = [set(a["search"]) == set(b["search"]) for a, b in pairs]
        row["search"] = {"same_10_in_order": round(float(np.mean(same_list)), 4), "same_10_as_a_set": round(float(np.mean(same_set)), 4),
                         "differ": int(len(same_set) - sum(same_set)),
                         "questions_that_differ": [b["id"] for (a, b), same in zip(pairs, same_list) if not same][:20]}
        row["ms_p50"] = {k: round(float(np.median([b["ms"][k] for _, b in pairs])), 2) for k in [*vec_types, "search"]}
        result[split] = row
    return result


def codemem_commit() -> str:
    src = Path(codemem.__file__).resolve().parent
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=src, capture_output=True, text=True)
    if sha.returncode:
        return f"version {codemem.__version__} (not a git checkout)"
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=src, capture_output=True, text=True).stdout.strip()
    return sha.stdout.strip() + (" with uncommitted changes" if dirty else "")


def table(report: dict) -> str:
    vec_types = list(report["vectors"])
    lines = [
        f"codemem {report['codemem']} | FAISS {report['faiss']} | {report['machine']}, {report['cpus']} CPUs, "
        f"{report['memory_gb']} GB | {report['measured']}",
        f"{report['repo']}: {report['questions']} questions of {report['tasks']} ("
        + ", ".join(f"{n} {split}" for split, n in report["splits"].items()) + "); vectors: "
        + ", ".join(f"{t} {n:,}" for t, n in report["vectors"].items()),
        f"questions embedded by {report['embedder']}, the embedder the index was built with",
        "",
    ]
    head = f"{'setting':<30} {'index':<8} {'split':<5}"
    for t in vec_types:
        head += f" | {t + ': top 10 same':>19} {'top-50 overlap':>14}"
    head += f" | {'merged same':>11} | " + " ".join(f"{t + ' ms':>9}" for t in [*vec_types, "search"])
    lines.append(head)
    for setting, entry in report["settings"].items():
        splits = sorted(entry["against_first"], key=("all", "dev", "test").index)
        for split in splits:
            row = entry["against_first"][split]
            line = f"{setting if split == splits[0] else '':<30} {entry['index'] if split == splits[0] else '':<8} {split:<5}"
            for t in vec_types:
                line += f" | {row[t]['top10_same_set']:>19.3f} {row[t]['top50_overlap']:>14.4f}"
            line += f" | {row['search']['same_10_in_order']:>11.3f} | " + " ".join(f"{row['ms_p50'][t]:>9.1f}" for t in [*vec_types, "search"])
            lines.append(line)
    lines += ["", report["verdict"]]
    return "\n".join(lines)


def verdict(report: dict) -> str:
    problems = []
    for setting in MUST_AGREE:
        entry = report["settings"].get(setting)
        if entry is None:
            continue
        for split, row in entry["against_first"].items():
            for t in report["vectors"]:
                if row[t]["top10_same_set"] < 1 or row[t]["top50_overlap"] < 0.999:
                    problems.append(f"{setting}, {split}, {t}: top 10 same {row[t]['top10_same_set']:.3f}, top-50 overlap {row[t]['top50_overlap']:.4f}")
            if row["search"]["same_10_in_order"] < 1:
                problems.append(f"{setting}, {split}: the merged search differs for {row['search']['differ']} questions as a set, "
                                f"{round((1 - row['search']['same_10_in_order']) * row['questions'])} in order")
    if problems:
        return "DIFFERS from the exact index:\n  " + "\n  ".join(problems)
    checked = [s for s in MUST_AGREE if s in report["settings"]]
    return f"PASS: {' and '.join(checked)} returned what the exact index returns, for every question" if checked else "no setting to judge"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", required=True, type=Path, help="the folder of a codemem index (it holds index.db)")
    ap.add_argument("--repo", required=True, help="the repo's name as the task files spell it, e.g. pandas-dev/pandas")
    ap.add_argument("--tasks", default=None, help="a task file's name or path (default: the one with the most tasks for the repo)")
    ap.add_argument("--settings", default=SETTINGS, help="search indexes to compare, separated by ';': the first is the reference")
    ap.add_argument("--limit", type=int, default=0, help="at most this many questions per split (0 = all)")
    ap.add_argument("--out", type=Path, default=None, help="the JSON file to write")
    ap.add_argument("--work", type=Path, default=None, help="where the copy of the index goes (default: the temp directory)")
    ap.add_argument("--config", type=Path, default=None, help="a codemem config file (TOML) the index was built with")
    ap.add_argument("--query-vectors", default=None, help="a .npy file of the questions' vectors, in the task file's order: nothing is embedded")
    args = ap.parse_args()

    tasks = task_file(args.repo, args.tasks)
    rows = questions(tasks, args.repo, args.limit)
    if not rows:
        sys.exit(f"{tasks} has no task for the repo {args.repo!r}")
    out_path = args.out or Path(f"search-indexes-{args.repo.replace('/', '__')}.json")
    config = config_from_dict(tomllib.loads(args.config.read_text("utf-8"))) if args.config else load_config()
    copy, folder, size = copy_index(args.index.resolve(), args.work)
    print(f"working on a copy of {args.index} in {folder} ({size / 1e6:,.0f} MB, deleted at the end); the index itself is not touched",
          flush=True)
    try:
        probe = Store(copy, vector_backend="faiss")
        vectors = probe.counts()["vectors"]
        embedder, key = embedder_of(probe, config)
        probe.close()
        if not vectors:
            sys.exit(f"{args.index} has no vectors")
        vecs = query_vectors(rows, embedder, key, out_path, args.query_vectors)
        splits = defaultdict(int)
        for r in rows:
            splits[r["split"]] += 1
        memory = physical_memory()
        report: dict = {
            "codemem": codemem_commit(), "faiss": faiss.__version__,
            "machine": f"{platform.machine()} {platform.platform()}", "cpus": os.cpu_count(),
            "memory_gb": round(memory / 1e9, 1) if memory else None, "measured": time.strftime("%Y-%m-%d %H:%M %z"),
            "index": str(args.index), "index_db_bytes": size, "repo": args.repo, "tasks": tasks.stem, "questions": len(rows),
            "splits": dict(splits), "vectors": vectors, "embedder": key, "settings": {},
        }
        reference = None
        for setting in [s.strip() for s in args.settings.split(";") if s.strip()]:
            print(f"{setting} ...", end=" ", flush=True)
            result = run(copy, setting, rows, vecs, key, config)
            reference = reference or result
            report["settings"][setting] = {
                "index": result["index"], "why": result["why"], "load_s": result["load_s"], "memory_mb": result["memory_mb"],
                "against_first": compare(reference, result, list(vectors)),
            }
            print(f"{result['index']} index, built in {result['load_s']:.1f} s", flush=True)
        report["verdict"] = verdict(report)
        out_path.write_text(json.dumps(report, indent=1), "utf-8")
        print()
        print(table(report))
        print(f"\nwritten to {out_path}")
        return 0 if report["verdict"].startswith("PASS") else 1
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
