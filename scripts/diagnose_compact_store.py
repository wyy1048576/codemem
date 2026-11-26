"""Where the compact index's codes stop being a function of the vector alone, on this machine.

    uv run python scripts/diagnose_compact_store.py

The compact index promises that a vector gets the same code whatever else it is coded with, so
an index patched edit by edit holds the same bytes as one built once from the same rows. Its
coding path has three stages: `prepare` (cut, divide by the norm), the rotation (`rows @ R`, a
float32 matrix product in numpy's BLAS) and FAISS's RaBitQ encode. This script checks each
stage by itself, then the scenarios of the tests that compare bytes, and one index of real size,
and says which stage a difference comes from.

It runs itself four times in child processes: numpy's BLAS on 1 thread or as the environment
leaves it, and FAISS on 1 or 16 threads. It needs numpy, faiss and codemem's store only, never
imports torch (so several threads are safe), and takes well under two minutes. Send back
everything it prints.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time

CONFIGS = [("1", 1), ("1", 16), ("env", 1), ("env", 16)]  # (numpy's BLAS threads, FAISS threads)
BLAS_VARS = ("OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS")
SIZES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 15, 16, 17, 24, 30, 31, 32, 33, 48, 64, 100, 128, 200, 205, 206, 256,
         300, 360, 512, 1000, 2048, 4096]
POSITION_CALLS = [8, 30, 300, 360, 4096]
DIMS = [32, 48, 896]  # the tests' lengths, and the model's


# --------------------------------------------------------------------------- one child


def _child(faiss_threads: int) -> dict:
    import faiss
    import numpy as np

    from codemem.embedder import l2_normalize
    from codemem.store import CompactVectorStore, _rotation, for_index, prepare

    faiss.omp_set_num_threads(faiss_threads)
    rng = np.random.default_rng(12345)

    def vecs(n, dim, seed=0):
        return l2_normalize(np.random.default_rng(seed).normal(size=(n, dim)))

    def ulp(a, b):
        return np.abs(a.view(np.int32).astype(np.int64) - b.view(np.int32).astype(np.int64))

    def layout(index):
        """(name, start, end, kind) of each part of one code; None if FAISS's layout is another."""
        d, nb, cs = index.d, index.rabitq.nb_bits, index.code_size
        s = (d + 7) // 8
        if nb == 1:
            parts = [("sign bits", 0, s, "bits"), ("f_add", s, s + 4, "f"), ("dp_multiplier", s + 4, s + 8, "f")]
        else:
            parts = [("sign bits", 0, s, "bits"), ("f_add", s, s + 4, "f"), ("dp_multiplier", s + 4, s + 8, "f"),
                     ("f_error", s + 8, s + 12, "f"), ("extra bits", s + 12, cs - 8, "bits"),
                     ("f_add_ex", cs - 8, cs - 4, "f"), ("f_rescale_ex", cs - 4, cs, "f")]
        return parts if parts[-1][2] == cs and (nb == 1 or cs - 8 - (s + 12) == (d * (nb - 1) + 7) // 8) else None

    def codes(index, n):
        return faiss.vector_to_array(index.codes).reshape(n, index.code_size)

    def where(x, a, b):
        """The first differing byte of two saved files, and of their bodies, and what holds it."""
        first = next(i for i in range(min(len(a), len(b))) if a[i] != b[i]) if a != b else None
        ha, hb = a.find(b"\n"), b.find(b"\n")
        head = a[:ha].decode()
        crc_at = head.find('"crc32": ') + len('"crc32": ')
        out = {"first_byte": first,
               "first_byte_is": None if first is None else ("head: crc32 digits" if crc_at <= first < ha else
                                                            "head: " + head[max(0, first - 12):first + 4]
                                                            if first < ha else "body")}
        body_a, body_b = a[ha + 1:], b[hb + 1:]
        if body_a == body_b:
            out["body"] = "equal (only the head differs)"
            return out
        off = next(i for i in range(min(len(body_a), len(body_b))) if body_a[i] != body_b[i])
        n = len(x._ids)
        at = 8 * n
        if off < at:
            out["body"] = f"byte {off}: vector ids"
            return out
        for k, index in enumerate(x._indexes):
            blob = faiss.serialize_index(index).tobytes()
            if off < at + len(blob):
                rel = off - at
                start = blob.find(faiss.vector_to_array(index.codes).tobytes())
                if start >= 0 and start <= rel < start + n * index.code_size:
                    j, inner = divmod(rel - start, index.code_size)
                    part = next((name for name, lo, hi, _ in (layout(index) or []) if lo <= inner < hi), f"byte {inner}")
                    out["body"] = f"byte {off}: index {k} (nb_bits {index.rabitq.nb_bits}), code of vector {j}, {part}"
                else:
                    out["body"] = f"byte {off}: index {k} (nb_bits {index.rabitq.nb_bits}), outside the codes"
                return out
            at += len(blob)
        out["body"] = f"byte {off}: past the indexes"
        return out

    def compare(x, y, queries, fetch, k=10):
        """What differs between two indexes that hold the same vectors."""
        a, b = x.to_bytes(), y.to_bytes()
        r = {"ids_equal": x._ids.tolist() == y._ids.tolist(), "bytes_equal": a == b}
        if a != b:
            r.update(where(x, a, b))
        if r["ids_equal"]:
            per_index = []
            for ia, ib in zip(x._indexes, y._indexes):
                ca, cb = codes(ia, len(x)), codes(ib, len(y))
                parts = layout(ia)
                one = {"nb_bits": ia.rabitq.nb_bits, "vectors_whose_code_differs": int((ca != cb).any(axis=1).sum()),
                       "of": len(x)}
                if parts is None:
                    one["layout"] = "unknown"
                else:
                    one["code_bits_differing"] = sum(int(np.unpackbits(ca[:, lo:hi] ^ cb[:, lo:hi]).sum())
                                                     for _, lo, hi, kind in parts if kind == "bits")
                    worst = {}
                    for name, lo, hi, kind in parts:
                        if kind == "f":
                            fa, fb = ca[:, lo:hi].copy().view("<f4")[:, 0], cb[:, lo:hi].copy().view("<f4")[:, 0]
                            if (fa != fb).any():
                                worst[name] = f"{float(np.abs(fa - fb).max()):.3g} ({int(ulp(fa, fb).max())} ulp)"
                    one["largest_factor_difference"] = worst or "none"
                per_index.append(one)
            r["codes"] = per_index
        x.bind(fetch)
        y.bind(fetch)
        top_x = [x.search(q, k) for q in queries]
        top_y = [y.search(q, k) for q in queries]
        r["queries"] = len(queries)
        r["top10_ids_differ"] = sum([i for i, _ in p] != [i for i, _ in q] for p, q in zip(top_x, top_y))
        r["top10_scores_differ"] = sum([s for _, s in p] != [s for _, s in q] for p, q in zip(top_x, top_y))
        return r

    def fetcher(table):
        def fetch(wanted):
            found = [int(i) for i in wanted if int(i) in table]
            return np.asarray(found, dtype=np.int64), np.stack([table[i] for i in found])
        return fetch

    out: dict = {"faiss_threads": faiss.omp_get_max_threads(), "torch_loaded_at_start": "torch" in sys.modules}
    try:
        from threadpoolctl import threadpool_info
        out["blas"] = [{k: p.get(k) for k in ("internal_api", "version", "num_threads", "threading_layer", "architecture")}
                       for p in threadpool_info() if p.get("user_api") == "blas"]
    except Exception as e:  # threadpoolctl is optional
        out["blas"] = f"threadpoolctl not available ({type(e).__name__})"

    # ---- stage 1: prepare (cut and norm), elementwise plus a per-row sum
    x = for_index(vecs(4096, 896, seed=1), 896)
    full = prepare(x, 896)
    out["prepare_depends_on_batch"] = any(
        not np.array_equal(prepare(x[o:o + m], 896), full[o:o + m]) for m in (1, 2, 3, 8, 300) for o in (0, 1001))

    # ---- stage 2: the rotation, numpy's BLAS: by the call's size, and by the position in one call
    rotation = {}
    for d in DIMS:
        s = CompactVectorStore(d, bits=1)
        x = for_index(vecs(4096, d, seed=d), d)
        full = s._coded(x)
        bad, worst = [], 0
        for m in SIZES:
            for o in sorted({0, int(rng.integers(0, 4097 - m))}):
                part = s._coded(x[o:o + m])
                if not np.array_equal(part, full[o:o + m]):
                    bad.append(m)
                    worst = max(worst, int(ulp(part, full[o:o + m]).max()))
                    break
        position = {}
        one = x[7:8]
        for m in POSITION_CALLS:
            rows = s._coded(np.repeat(one, m, axis=0))
            differ = np.flatnonzero((rows != rows[0]).any(axis=1))
            position[m] = {"distinct": len({r.tobytes() for r in rows}), "first_positions_unlike_0": differ[:12].tolist()}
        rotation[d] = {"sizes_unlike_a_4096_call": bad, "largest_ulp": worst, "same_vector_in_one_call": position,
                       "rotation_id": _rotation(d)[1]}
    out["rotation"] = rotation
    out["rotation_ids"] = {d: _rotation(d)[1] for d in (32, 48, 768, 896, 1024)}

    # ---- stage 3: FAISS's encode, the same float rows in one add or in pieces
    rows = CompactVectorStore(896, bits=4)._coded(for_index(vecs(5000, 896, seed=11), 896))
    out["rows_sha"] = hashlib.sha1(rows.tobytes()).hexdigest()[:12]
    encode = {}
    for nb in (1, 4):
        def made():
            index = faiss.IndexRaBitQ(896, faiss.METRIC_INNER_PRODUCT, nb)
            index.train(np.zeros((1, 896), dtype=np.float32))
            return index
        one, many = made(), made()
        one.add(rows)
        at, sizes = 0, [1, 2, 3, 7, 30, 512, 4096]
        while at < len(rows):
            step = sizes[(at // 7) % len(sizes)] if at < 1500 else 4096
            many.add(rows[at:at + step])
            at += step
        c1, c2 = faiss.vector_to_array(one.codes), faiss.vector_to_array(many.codes)
        encode[nb] = {"one_add_equals_pieces": bool(np.array_equal(c1, c2)), "codes_sha": hashlib.sha1(c1.tobytes()).hexdigest()[:12]}
    out["encode"] = encode

    # ---- the tests' scenarios
    scen = {}
    for bits in (1, 4):
        # test_an_index_patched_step_by_step_is_the_index_rebuilt_from_the_rows
        v = for_index(vecs(400, 48), 48)
        p = CompactVectorStore(48, bits=bits, rescore=16)
        p.upsert(list(range(201, 401)), v[200:]); p.upsert(list(range(1, 201)), v[:200]); p.remove(range(50, 120))
        p.upsert(list(range(60, 90)), v[59:89]); p.upsert([300, 10], v[[299, 9]])
        kept = sorted(p.ids())
        r = CompactVectorStore(48, bits=bits, rescore=16); r.upsert(kept, v[np.asarray(kept) - 1])
        table = {int(i): v[i - 1] for i in kept}
        scen[f"patched_vs_rebuilt[{bits}]"] = compare(p, r, for_index(vecs(20, 48, seed=4), 48), fetcher(table))
        # the last line of test_an_upsert_that_fails_part_of_the_way_leaves_the_index_as_it_was
        v = for_index(vecs(400, 32), 32)
        vs = CompactVectorStore(32, bits=bits, rescore=8); vs.upsert(list(range(101, 301)), v[100:300])
        for ids in ([301, 302], [150, 151], [5, 6], [350, 150, 50]):
            vs.upsert(ids, v[np.asarray(ids) - 1])
        final = sorted(vs.ids())
        once = CompactVectorStore(32, bits=bits, rescore=8); once.upsert(final, v[np.asarray(final) - 1])
        table = {int(i): v[i - 1] for i in final}
        scen[f"upserts_vs_once[{bits}]"] = compare(vs, once, for_index(vecs(20, 32, seed=6), 32), fetcher(table))
        # test_ties_at_the_candidate_cut_are_all_kept
        v = for_index(vecs(300, 32), 32); v[100:160] = v[100]
        other = np.random.default_rng(1).permutation(300) + 1
        a, b = CompactVectorStore(32, bits=bits, rescore=8), CompactVectorStore(32, bits=bits, rescore=8)
        a.upsert(list(range(1, 301)), v); b.upsert(other.tolist(), v)
        a.bind(fetcher({i + 1: v[i] for i in range(300)})); b.bind(fetcher({int(i): v[j] for j, i in enumerate(other)}))
        of = {int(i): j + 1 for j, i in enumerate(other)}
        in_a = set(a._ids[a._candidates(v[100], 8, None)].tolist())
        in_b = {of[i] for i in b._ids[b._candidates(v[100], 8, None)].tolist()}
        same = sum(set(a._ids[a._candidates(q, 8, None)].tolist()) == {of[i] for i in b._ids[b._candidates(q, 8, None)].tolist()}
                   for q in for_index(vecs(20, 32, seed=6), 32))
        copies = [codes(ix, 300)[100:160] for ix in a._indexes]
        scen[f"ties[{bits}]"] = {
            "distinct_codes_among_the_60_copies": [len({row.tobytes() for row in c}) for c in copies],
            "positions_whose_code_differs_from_copy_0": [(np.flatnonzero((c != c[0]).any(axis=1)) + 100).tolist()[:20] for c in copies],
            "all_60_copies_kept": set(range(101, 161)) <= in_a, "copies_kept": len(in_a & set(range(101, 161))),
            "a_equals_b_for_v100": in_a == in_b, "a_equals_b_of_20_queries": same,
            "search_v100_top2": [i for i, _ in a.search(v[100], 2)]}

    # ---- an index of real size: 6,000 vectors of 896 numbers, 60 of them copies of one,
    # appended in small calls as edits bring them, against the batches a rebuild uses (512, 4,096, rest)
    v = for_index(vecs(6000, 896, seed=21), 896); v[3000:3060] = v[3000]
    table = {i + 1: v[i] for i in range(6000)}
    queries = list(for_index(vecs(20, 896, seed=22), 896)) + [v[3000]]
    for bits in (1, 4):
        p, r = CompactVectorStore(896, bits=bits), CompactVectorStore(896, bits=bits)
        at, sizes = 0, [1, 2, 3, 5, 8, 13, 30, 64, 100, 200]
        while at < 6000:
            step = sizes[(at // 3) % len(sizes)] if at < 2500 else 4096
            p.upsert(list(range(at + 1, min(at + step, 6000) + 1)), v[at:at + step]); at += step
        for lo, hi in ((0, 512), (512, 4608), (4608, 6000)):
            r.upsert(list(range(lo + 1, hi + 1)), v[lo:hi])
        res = compare(p, r, queries, fetcher(table))
        res["copies_query_top10_equal"] = [i for i, _ in p.search(v[3000], 10)] == [i for i, _ in r.search(v[3000], 10)]
        scen[f"real_size_defaults[{bits}]"] = res
    out["scenarios"] = scen
    out["torch_loaded_at_end"] = "torch" in sys.modules
    return out


# --------------------------------------------------------------------------- the parent


def _cpu() -> str:
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    try:
        return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return platform.processor()


def _yes(flag) -> str:
    return "YES" if flag else "no"


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        print(json.dumps(_child(int(sys.argv[2]))))
        return 0
    import faiss
    import numpy as np

    started = time.monotonic()
    blas = np.show_config(mode="dicts")["Build Dependencies"]["blas"]
    print(f"platform {platform.platform()} | {platform.machine()} | {_cpu()} | {os.cpu_count()} CPUs | Python {platform.python_version()}")
    print(f"numpy {np.__version__}, BLAS {blas.get('name')} {blas.get('version')} ({blas.get('openblas configuration')})")
    print(f"faiss {faiss.__version__}, {faiss.get_compile_options().strip()}, loaded {[m for m in sys.modules if m.startswith('faiss.swigfaiss') or m.startswith('faiss._swigfaiss')]}")
    print(f"environment: " + ", ".join(f"{k}={os.environ.get(k, 'unset')}" for k in ("OMP_NUM_THREADS",) + BLAS_VARS))
    results = {}
    for blas_threads, faiss_threads in CONFIGS:
        env = dict(os.environ)
        if blas_threads == "1":
            env.update({k: "1" for k in BLAS_VARS})
        proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", str(faiss_threads)], env=env,
                              capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            print(f"child BLAS={blas_threads} FAISS={faiss_threads} failed with status {proc.returncode}:\n{proc.stderr[-3000:]}")
            return 1
        results[(blas_threads, faiss_threads)] = json.loads(proc.stdout.strip().splitlines()[-1])

    for (blas_threads, faiss_threads), r in results.items():
        print(f"\n== numpy BLAS threads: {'1' if blas_threads == '1' else 'as the environment leaves them'};"
              f" FAISS threads: {r['faiss_threads']} ==")
        print(f"BLAS as threadpoolctl sees it: {r['blas']}")
        print(f"stage 1, prepare: a row's bits depend on its call: {_yes(r['prepare_depends_on_batch'])}")
        for d, rot in r["rotation"].items():
            pos = "; ".join(f"call of {m}: {p['distinct']} distinct" + (f" (positions {p['first_positions_unlike_0']})" if p["distinct"] > 1 else "")
                            for m, p in rot["same_vector_in_one_call"].items())
            print(f"stage 2, rotation at {d} numbers: call sizes whose rows differ from a call of 4,096: "
                  f"{rot['sizes_unlike_a_4096_call'] or 'none'} (largest {rot['largest_ulp']} ulp); the same vector in one call: {pos}")
        print(f"stage 3, FAISS encode of the same float rows, one add against pieces: "
              + ", ".join(f"nb_bits {nb}: {'equal' if e['one_add_equals_pieces'] else 'DIFFERENT'}" for nb, e in r["encode"].items()))
        for name, s in r["scenarios"].items():
            print(f"scenario {name}: " + json.dumps(s))

    print("\n== what this says ==")
    rs = list(results.values())
    by = lambda b: [r for (bt, _), r in results.items() if bt == b]
    sizes = {b: any(rot["sizes_unlike_a_4096_call"] for r in by(b) for rot in r["rotation"].values()) for b in ("1", "env")}
    position = {b: any(p["distinct"] > 1 for r in by(b) for rot in r["rotation"].values() for p in rot["same_vector_in_one_call"].values())
                for b in ("1", "env")}
    split = any(not e["one_add_equals_pieces"] for r in rs for e in r["encode"].values())
    threads = any(len({results[(b, t)]["encode"][nb]["codes_sha"] for t in (1, 16)}) > 1
                  for b in ("1", "env") for nb in ("1", "4")
                  if results[(b, 1)]["rows_sha"] == results[(b, 16)]["rows_sha"])
    ids = {json.dumps(r["rotation_ids"], sort_keys=True) for r in rs}
    print(f"1. prepare depends on the call: {_yes(any(r['prepare_depends_on_batch'] for r in rs))}")
    print(f"2. the rotation (numpy's BLAS) depends on the call's size: with 1 BLAS thread {_yes(sizes['1'])}, with the default {_yes(sizes['env'])}")
    print(f"3. the rotation depends on the row's position in one call: with 1 BLAS thread {_yes(position['1'])}, with the default {_yes(position['env'])}")
    print(f"4. FAISS's encode depends on how the same rows are split into adds: {_yes(split)}")
    print(f"5. FAISS's codes of the same rows depend on FAISS's thread count: {_yes(threads)}")
    print(f"6. the rotation id (named in every saved file) is the same in all four processes: {_yes(len(ids) == 1)}"
          + ("" if len(ids) == 1 else " -> a saved compact index is REFUSED (and rebuilt) by a process with another BLAS thread count"))
    for b in ("1", "env"):
        for r in by(b)[:1]:
            for bits in (1, 4):
                s = r["scenarios"][f"real_size_defaults[{bits}]"]
                print(f"7. real size (6,000 x 896, bits {bits}, rescore 200), BLAS threads {b}: patched == rebuilt bytes {s['bytes_equal']};"
                      f" top-10 ids differ in {s['top10_ids_differ']} of {s['queries']} queries; copies' top 10 equal: {s['copies_query_top10_equal']}")
    if (sizes["1"] or sizes["env"] or position["1"] or position["env"]) and not (split or threads):
        print("=> the codes depend on the call through the rotation's matrix product in numpy's BLAS, not through FAISS"
              + (" (and the position in a call matters only on several BLAS threads)" if position["env"] and not position["1"] else ""))
    elif split or threads:
        print("=> FAISS's encode itself depends on the call or its threads")
    else:
        print("=> no stage differs here: the coding path is a function of the vector alone on this machine")
    print(f"torch loaded in any child: {_yes(any(r['torch_loaded_at_start'] or r['torch_loaded_at_end'] for r in rs))};"
          f" {time.monotonic() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
