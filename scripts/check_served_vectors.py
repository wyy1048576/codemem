"""Check `codemem serve-embeddings` against the same model in process, and time the server.

    python scripts/check_served_vectors.py              # are served vectors the in-process ones?
    python scripts/check_served_vectors.py --overhead   # what do HTTP and JSON cost? (the fake model)

The check loads the configured model twice, one load after the other, never two at once: first in a
child process that embeds 20 code texts and 20 questions in process, then in a `codemem
serve-embeddings` child, which this script asks for the same texts with the settings the server
prints. It reports the largest difference between the two, beside the difference that grouping
texts into batches makes in process. Run it on each kind of device you serve from:
`CODEMEM_DEVICE=cpu`, `CODEMEM_MODEL=...` and the config files apply as for any codemem command.

`--overhead` embeds 256 short code texts with the fake model, in process and through a server in
this process, so the difference is the server's own cost: HTTP, JSON and the queue. The fake
model's vectors are mostly zeros, which JSON writes in three characters, so one more run gives
every position a value, as a real model does.

The texts are codemem's own source, cut and headed the way the indexer does it.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import io
import json
import os
import statistics
import subprocess
import sys
import time
import tomllib
import zlib
from pathlib import Path

import httpx
import numpy as np

import codemem
from codemem.chunker import chunk_source
from codemem.config import Config, config_from_dict, load_config
from codemem.embedder import FakeEmbedder, OpenAIEmbedder, SentenceTransformerEmbedder, l2_normalize
from codemem.embedserver import EmbeddingServer, local_embedder
from codemem.texts import TEXT_BUILDERS, BuildContext

QUESTIONS = [
    "disabled users stay logged in",
    "where is the vector cache key built",
    "how does a search wait for edits that were just saved",
    "add OCR to the upload pipeline",
    "which files are skipped as generated code",
    "retry a request when the API answers 429",
    "how are long functions split into windows",
    "who calls the function that links calls to definitions",
    "write the search index to disk when the index is quiet",
    "what happens when the embedding model is still loading",
    "normalize a vector to length one",
    "find the device the model runs on",
    "merge the keyword ranking with the vector rankings",
    "register the MCP server with Claude Code",
    "read the ignore rules of a repository",
    "hash the files of a model folder",
    "how is a chunk's usage text written",
    "which languages are supported and their file extensions",
    "stop the watcher when the service closes",
    "compare an updated index with a fresh build",
]


def code_texts() -> list[str]:
    """The `code` text of every chunk of codemem's own package, shortest first."""
    root = Path(codemem.__file__).parent
    texts = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root.parent).as_posix()
        texts += [TEXT_BUILDERS["code"](chunk, BuildContext()) for chunk in chunk_source(path.read_bytes(), rel)]
    return sorted(set(texts), key=lambda t: (len(t), t))


def spread(texts: list[str], n: int) -> list[str]:
    """`n` texts evenly spaced over the list, so short and long ones are both there."""
    return [texts[round(i * (len(texts) - 1) / (n - 1))] for i in range(n)]


def differences(a: np.ndarray, b: np.ndarray) -> str:
    return f"largest difference {float(np.abs(a - b).max()):.2e}, smallest cosine {float(np.sum(a * b, axis=1).min()):.6f}"


# ---------------------------------------------------------------- in process (a child of the check)


def embed_in_process() -> None:
    """Embed the check's texts with the configured local model and write the vectors to stdout."""
    result, sys.stdout = sys.stdout.buffer, sys.stderr  # nothing a library prints may land among the vectors
    embedder = local_embedder(load_config(None))
    documents, questions = spread(code_texts(), 20), QUESTIONS
    out = {
        "documents": embedder.embed_documents(documents),
        "documents_alone": np.vstack([embedder.embed_documents([t]) for t in documents]),
        "queries": embedder.embed_queries(questions),
    }
    if isinstance(embedder, SentenceTransformerEmbedder):  # what counting a batch's tokens would cost
        prefixed = [embedder.prefixes[1] + t for t in documents[-16:]]
        t = time.perf_counter()
        tokens = embedder.model.preprocess(prefixed)["attention_mask"].sum()
        out["tokenize_seconds"], out["tokens"] = np.asarray(time.perf_counter() - t), np.asarray(int(tokens))
        t = time.perf_counter()
        embedder.embed_texts(prefixed)
        out["batch_seconds"] = np.asarray(time.perf_counter() - t)
    out["key"] = np.asarray(embedder.key)
    np.savez(result, **out)


# ---------------------------------------------------------------- the check


def start_server() -> tuple[subprocess.Popen, Config, str]:
    """`codemem serve-embeddings` on a free port; its printed settings as a client's config."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "codemem", "serve-embeddings", "--port", "0"], stdout=subprocess.PIPE, text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    printed: list[str] = []
    for line in proc.stdout:
        if not line.strip() and printed:
            break
        printed.append(line)
    if proc.poll() is not None:
        raise SystemExit("the server did not start")
    return proc, config_from_dict(tomllib.loads("".join(printed))), "".join(printed)


def check() -> int:
    documents, questions = spread(code_texts(), 20), QUESTIONS
    print(f"{len(documents)} code texts of {len(documents[0])} to {len(documents[-1])} characters, "
          f"{len(questions)} questions")
    child = subprocess.run([sys.executable, __file__, "--embed-in-process"], stdout=subprocess.PIPE, check=True)
    local = np.load(io.BytesIO(child.stdout))
    print(f"in process: {local['key']}")

    proc, cfg, printed = start_server()
    try:
        print(printed.rstrip())
        client = OpenAIEmbedder(cfg.embedding)
        served_documents = client.embed_documents(documents)
        served_alone = np.vstack([client.embed_documents([t]) for t in documents])
        served_queries = client.embed_queries(questions)
    finally:
        proc.terminate()
        proc.wait(30)
    print(f"through the server: {client.key}")

    print("\nserved against in process")
    print(f"  documents, one request against one call:  {differences(served_documents, local['documents'])}")
    print(f"  documents, each text alone both ways:     {differences(served_alone, local['documents_alone'])}")
    print(f"  queries, one request against one call:    {differences(served_queries, local['queries'])}")
    print("in process against in process")
    print(f"  documents, one call against each alone:   {differences(local['documents'], local['documents_alone'])}")
    scores, served_scores = local["queries"] @ local["documents"].T, served_queries @ served_documents.T
    same_best = int((scores.argmax(axis=1) == served_scores.argmax(axis=1)).sum())
    print(f"question against code text: largest difference in a score {float(np.abs(scores - served_scores).max()):.2e}; "
          f"{same_best} of {len(questions)} questions have the same best code text both ways")
    if "tokenize_seconds" in local:
        print(f"counting tokens: {local['tokenize_seconds'] * 1000:.1f} ms to tokenize 16 texts ({local['tokens']} "
              f"tokens) again, beside {local['batch_seconds'] * 1000:.0f} ms to embed them")
    worst = min(float(np.sum(served_documents * local["documents"], axis=1).min()),
                float(np.sum(served_queries * local["queries"], axis=1).min()))
    return 0 if worst >= 0.9999 else 1


# ---------------------------------------------------------------- the overhead


class DenseFake(FakeEmbedder):
    """The fake model with a value in every position."""

    def _embed(self, texts):
        rows = [np.random.default_rng(zlib.crc32(t.encode("utf-8"))).standard_normal(self._dim) for t in texts]
        return l2_normalize(np.asarray(rows, dtype=np.float32).reshape(len(texts), self._dim))


def median_seconds(run, repeats: int = 7) -> float:
    times = []
    for _ in range(repeats):
        t = time.perf_counter()
        run()
        times.append(time.perf_counter() - t)
    return statistics.median(times)


def overhead() -> int:
    texts = [t for t in code_texts() if len(t) <= 600][-256:]
    print(f"{len(texts)} code texts of {len(texts[0])} to {len(texts[-1])} characters "
          f"(median {int(statistics.median(len(t) for t in texts))}); medians of 7 runs")
    for label, kind, dim in (("fake:64", FakeEmbedder, 64), ("fake:896", FakeEmbedder, 896),
                             ("896 numbers, none of them zero", DenseFake, 896)):
        model = kind(dim)
        in_process = median_seconds(lambda: model.embed_documents(texts))
        server = EmbeddingServer(kind(dim), port=0).start()
        try:
            cfg = config_from_dict(tomllib.loads(server.client_config()))
            rows = [("in process", in_process)]
            for name, settings in (
                ("4 requests of 64 at once (the client's defaults)", {}),
                ("1 request of 256", {"batch_size": 256}),
                ("16 requests of 16, one at a time", {"batch_size": 16, "max_concurrency": 1}),
            ):
                client = OpenAIEmbedder(dataclasses.replace(cfg.embedding, **settings))
                client.embed_documents(texts[:1])  # open the connection
                rows.append((name, median_seconds(lambda: client.embed_documents(texts))))
            with httpx.Client(timeout=60) as http:
                http.get(f"{server.url}/models")
                rows.append(("1 request of 256, base64 reply", median_seconds(lambda: base64_request(http, server, texts))))
            # A search embeds one query. `_embed` goes around the client's cache of recent queries.
            one_served = median_seconds(lambda: client._embed(QUESTIONS[:1], ""), repeats=51)
            one_in_process = median_seconds(lambda: model.embed_queries(QUESTIONS[:1]), repeats=51)
        finally:
            server.close()
        vecs = model.embed_documents(texts)
        as_json = json.dumps({"data": [{"embedding": v} for v in vecs.tolist()]})
        encode = median_seconds(lambda: json.dumps({"data": [{"embedding": v} for v in vecs.tolist()]}))
        decode = median_seconds(lambda: np.asarray([d["embedding"] for d in json.loads(as_json)["data"]], np.float32))
        print(f"\n{label}: a reply of {len(as_json) / 1e6:.2f} MB as JSON, {vecs.nbytes * 4 / 3 / 1e6:.2f} MB as "
              f"base64; JSON alone costs {encode * 1000:.1f} ms to write and {decode * 1000:.1f} ms to read")
        for name, seconds in rows:
            extra = "" if name == "in process" else f"  (+{(seconds - in_process) / len(texts) * 1000:.3f} ms a text)"
            print(f"  {name:50s} {seconds * 1000:7.1f} ms  {len(texts) / seconds:8.0f} texts/s{extra}")
        print(f"  one query: {one_in_process * 1000:.2f} ms in process, {one_served * 1000:.2f} ms through the server")
    return 0


def base64_request(http: httpx.Client, server: EmbeddingServer, texts: list[str]) -> np.ndarray:
    body = {"model": server.served.model, "input": texts, "encoding_format": "base64"}
    data = http.post(f"{server.url}/embeddings", json=body).json()["data"]
    return np.stack([np.frombuffer(base64.b64decode(d["embedding"]), dtype="<f4") for d in data])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--overhead", action="store_true", help="time the server with the fake model")
    ap.add_argument("--embed-in-process", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.embed_in_process:
        embed_in_process()
        return 0
    return overhead() if args.overhead else check()


if __name__ == "__main__":
    sys.exit(main())
