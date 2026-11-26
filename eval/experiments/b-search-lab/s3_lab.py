"""Stage 3: every experiment as a ranking function over the kept lists (s1_run.py) and the stored
vectors (lab_common.Index: every chunk scored exactly against the query vector, best part).

Per set and task and variant it keeps (first gold-function place, first gold-file place, candidates
added, microseconds of the variant's own work): out/s3-<set>.json. Experiment 8 keeps (reach, functions
named). The baseline ("base") is the product's fusion, checked equal to the product's top 50 in s1_report.

    ./run.sh s3_lab.py <repo> [<set> ...]        (vllm: vllm-L0 vllm-title; pandas: pandas-L0 pandas-title vague-L1 vague-L2)
"""
from __future__ import annotations

import json
import math
import random
import sys
import time
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, "/Users/andres/Desktop/CS329M/codemem/.cache/review/lab")
import core as C
import lab_common as L
from codemem.tokenize import tokenize

VERSIONS = ("a", "b99", "b90", "c")
K = 60.0
WEIGHTS7 = [(1, 1, 1), (0.5, 1, 1), (1.5, 1, 1), (2, 1, 1), (1, 1.5, 1), (1, 2, 1), (1, 1, 0.5), (1, 1, 0),
            (1, 1, 1.5), (1, 1.5, 0.5), (0.5, 1.5, 1)]


class Repo:
    def __init__(self, name: str):
        self.name = name
        self.ix = ix = L.Index(name, vectors=True)
        self.fu = C.Fuser(ix)
        self.loc = self.fu.loc.tolist()
        for v in VERSIONS:
            ix.graph(v)
        self.is_test = ix.is_test
        self.has_usage = ix.has_vec("usage")
        # file order of rows, for per-file maxima
        self.file_sorted = ix._file_rows
        self.file_ptr = ix._file_ptr
        # definitions by name and by qualified name, for experiment 6
        self.by_name: dict[str, list[int]] = defaultdict(list)
        self.by_qual: dict[str, list[int]] = defaultdict(list)
        for r in range(ix.N):
            if ix.kind[r] in ("function", "method", "class"):
                self.by_name[ix.cname[r]].append(r)
                self.by_qual[ix.qualname[r]].append(r)
        # a keyword index of files (path + the names of its chunks), for experiment 5
        self._file_bm25()
        # files changed together (experiment 13)
        cc = np.load(L.OUT / f"cochange-{name}.npz")
        self.cc_times, self.cc_ptr, self.cc_files = cc["times"], cc["ptr"], cc["files"]
        nf = len(ix.paths)
        commit_of = np.repeat(np.arange(len(self.cc_times)), np.diff(self.cc_ptr))
        order = np.lexsort((commit_of, self.cc_files))
        self.f_commits = commit_of[order]  # per file, its commits in time order
        self.f_ptr = np.searchsorted(self.cc_files[order], np.arange(nf + 1))
        bm = json.loads((L.OUT / f"bm25v-{name}.json").read_text("utf-8")) if (L.OUT / f"bm25v-{name}.json").is_file() else {}
        self.bm25v = {tid: {k: np.array([ix.row_of[c] for c in v], dtype=np.int64) for k, v in row.items() if not k.endswith("_text")}
                      for tid, row in bm.items()}
        self.bm25v_text = {tid: {k[:-5]: v for k, v in row.items() if k.endswith("_text")} for tid, row in bm.items()}

    def _file_bm25(self) -> None:
        ix = self.ix
        docs: list[Counter] = []
        names = defaultdict(list)
        for r in range(ix.N):
            names[int(ix.file_of[r])].append(ix.qualname[r])
        for f, p in enumerate(ix.paths):
            toks = tokenize(p) + tokenize(" ".join(names[f]))
            docs.append(Counter(toks))
        self.fdocs = docs
        self.f_len = np.array([sum(d.values()) for d in docs], dtype=np.float64)
        df = Counter()
        for d in docs:
            df.update(d.keys())
        n = len(docs)
        self.f_idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.f_avg = float(self.f_len.mean())
        self.f_post: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for f, d in enumerate(docs):
            for t, c in d.items():
                self.f_post[t].append((f, c))

    def file_bm25(self, query: str) -> np.ndarray:
        k1, b = 1.2, 0.75
        out = np.zeros(len(self.fdocs))
        for t in set(tokenize(query, stopwords=True)):
            idf = self.f_idf.get(t)
            if idf is None:
                continue
            for f, c in self.f_post[t]:
                out[f] += idf * c * (k1 + 1) / (c + k1 * (1 - b + b * self.f_len[f] / self.f_avg))
        return out

    def neighbours(self, rows, version: str, direction: str) -> set[int]:
        out: set[int] = set()
        for r in rows:
            out.update(self.ix.neighbours(int(r), version, direction).tolist())
        return out

    def cochange(self, seed_files, before: int) -> np.ndarray:
        """Per file of the snapshot: in how many commits older than `before` it changed together with
        any one of seed_files (summed over the seeds)."""
        nf = len(self.ix.paths)
        total = np.zeros(nf, dtype=np.int64)
        for f in seed_files:
            commits = self.f_commits[self.f_ptr[f]:self.f_ptr[f + 1]]
            commits = commits[self.cc_times[commits] < before]
            if not len(commits):
                continue
            segs = [self.cc_files[self.cc_ptr[c]:self.cc_ptr[c + 1]] for c in commits]
            total += np.bincount(np.concatenate(segs), minlength=nf)
        return total


class Task:
    def __init__(self, repo: Repo, t: dict, run_row: dict):
        ix = repo.ix
        self.t, self.id = t, t["id"]
        self.files, self.fns = ix.gold_rows(t)
        self.lists = run_row["lists"]
        self.s_code = ix.scores("code", t["vec"])
        self.s_usage = ix.scores("usage", t["vec"])
        self.order, self.scores = repo.fu.baseline(run_row)
        self.cands = set(self.scores)
        self.file_of = ix.file_of

    def ranks(self, order) -> tuple[int | None, int | None]:
        fn = fl = None
        files, fns, file_of = self.files, self.fns, self.file_of
        for place, r in enumerate(order, start=1):
            if fn is None and r in fns:
                fn = place
            if fl is None and file_of[r] in files:
                fl = place
            if fn is not None and fl is not None:
                break
        return fn, fl


def fuse_extra(repo: Repo, task: Task, extra: list[tuple[list, float]], base_scores: dict | None = None):
    scores = dict(task.scores if base_scores is None else base_scores)
    for rows, w in extra:
        for rank, r in enumerate(rows, start=1):
            scores[r] = scores.get(r, 0.0) + w / (K + rank)
    loc = repo.loc
    return sorted(scores, key=lambda r: (-scores[r], loc[r]))


def best_by(scores: np.ndarray, rows, m: int, exclude: set[int] | None = None) -> list[int]:
    rows = [r for r in rows if not exclude or r not in exclude]
    if not rows:
        return []
    a = np.array(rows, dtype=np.int64)
    s = scores[a]
    ok = np.isfinite(s)
    a, s = a[ok], s[ok]
    idx = np.lexsort((a, -s))[:m]
    return a[idx].tolist()


def run_set(repo: Repo, set_name: str, tasks: list[dict], run: dict, out: dict, seeds=5) -> None:
    ix = repo.ix
    rec = out.setdefault(set_name, defaultdict(dict))
    meta = out.setdefault(set_name + ":meta", {})
    is_l0 = set_name.endswith("-L0")
    t_start = time.perf_counter()
    for ti, t in enumerate(tasks):
        task = Task(repo, t, run[t["id"]])
        tid = task.id

        def put(name: str, order, added: int, t0: float) -> None:
            fn, fl = task.ranks(order)
            rec[name][tid] = (fn, fl, added, int((time.perf_counter() - t0) * 1e6))

        put("base", task.order, 0, time.perf_counter())
        top = task.order
        # ---- 1. the graph as a fourth list; 3. random neighbours, placebo
        for v in VERSIONS:
            for d in ("both", "callers", "callees"):
                for n in (3, 5, 10):
                    t0 = time.perf_counter()
                    seeds_n = set(top[:n])
                    nb = repo.neighbours(top[:n], v, d) - seeds_n
                    nb_t = time.perf_counter() - t0
                    for m in (5, 10, 20):
                        t1 = time.perf_counter()
                        g = best_by(task.s_code, nb, m)
                        sel_t = time.perf_counter() - t1
                        added = sum(r not in task.cands for r in g)
                        for w in (0.5, 1.0, 2.0):
                            t2 = time.perf_counter()
                            order = fuse_extra(repo, task, [(g, w)])
                            fn, fl = task.ranks(order)
                            rec[f"e1|{v}|{d}|n{n}|m{m}|w{w}"][tid] = (fn, fl, added, int((nb_t + sel_t + time.perf_counter() - t2) * 1e6))
                        if d == "both" and (n, m) in ((5, 10), (10, 20), (3, 5), (5, 5), (10, 10)):
                            nbl = sorted(nb)
                            for s in range(seeds):
                                rng = random.Random(f"{tid}|{v}|{n}|{m}|{s}")
                                pick = rng.sample(nbl, min(m, len(nbl)))
                                for w in (0.5, 1.0, 2.0):
                                    order = fuse_extra(repo, task, [(pick, w)])
                                    fn, fl = task.ranks(order)
                                    rec[f"e3rand|{v}|n{n}|m{m}|w{w}|s{s}"][tid] = (fn, fl, sum(r not in task.cands for r in pick), 0)
                                if v == "a":
                                    rngp = random.Random(f"placebo|{tid}|{n}|{m}|{s}")
                                    pl = []
                                    while len(pl) < m:
                                        r = rngp.randrange(ix.N)
                                        if r not in seeds_n and r not in pl:
                                            pl.append(r)
                                    for w in (0.5, 1.0, 2.0):
                                        order = fuse_extra(repo, task, [(pl, w)])
                                        fn, fl = task.ranks(order)
                                        rec[f"e3placebo|n{n}|m{m}|w{w}|s{s}"][tid] = (fn, fl, sum(r not in task.cands for r in pl), 0)
        # the teammate's version: callers and callees of all 50 results, unfiltered, after rank 50
        nb50 = repo.neighbours(top[:50], "a", "both") - set(top[:50])
        meta.setdefault("teammate", {})[tid] = (len(nb50), len(nb50 & task.fns))
        # ---- 2. the graph as a lift only
        for depth in (50, 200):
            if depth == 50:
                base_s, base_o = task.scores, task.order
            else:
                base_o, base_s = repo.fu.fuse([(s, task.lists[s][:depth], 1.0) for s in C.SIGNALS], k=K)
            for v in VERSIONS:
                for n in (3, 5, 10):
                    t0 = time.perf_counter()
                    seeds_n = base_o[:n]
                    cnt = Counter()
                    for s_ in seeds_n:
                        for x in ix.neighbours(int(s_), v, "both").tolist():
                            if x in base_s:
                                cnt[x] += 1
                    nb_t = time.perf_counter() - t0
                    for beta in (0.25, 0.5, 1.0):
                        t1 = time.perf_counter()
                        sc = dict(base_s)
                        for x, c in cnt.items():
                            sc[x] += beta * c / (K + 1)
                        order = sorted(sc, key=lambda r: (-sc[r], repo.loc[r]))
                        fn, fl = task.ranks(order)
                        rec[f"e2|d{depth}|{v}|n{n}|b{beta}"][tid] = (fn, fl, 0 if depth == 50 else len(set(base_s) - task.cands),
                                                                   int((nb_t + time.perf_counter() - t1) * 1e6))
        # ---- 4. file siblings
        for n in (3, 5, 10):
            t0 = time.perf_counter()
            seeds_n = set(top[:n])
            sib = set()
            for f in {int(ix.file_of[r]) for r in top[:n]}:
                sib.update(ix.file_rows(f).tolist())
            sib -= seeds_n
            sib_t = time.perf_counter() - t0
            for m in (5, 10, 20):
                g = best_by(task.s_code, sib, m)
                added = sum(r not in task.cands for r in g)
                for w in (0.5, 1.0, 2.0):
                    t2 = time.perf_counter()
                    order = fuse_extra(repo, task, [(g, w)])
                    fn, fl = task.ranks(order)
                    rec[f"e4|n{n}|m{m}|w{w}"][tid] = (fn, fl, added, int((sib_t + time.perf_counter() - t2) * 1e6))
        # ---- 5. a file-level list
        t0 = time.perf_counter()
        s_sorted = task.s_code[repo.file_sorted]
        fmax = np.maximum.reduceat(s_sorted, repo.file_ptr[:-1])
        best3 = np.argsort(-task.s_code)[:3000]
        fb3 = defaultdict(list)
        for r in best3.tolist():
            fb3[int(ix.file_of[r])].append(float(task.s_code[r]))
        floor = float(task.s_code[best3[-1]])
        ftop3 = np.full(len(ix.paths), -np.inf)
        for f, v_ in fb3.items():
            v_ = (v_ + [floor, floor, floor])[:3]
            ftop3[f] = sum(v_) / 3
        fbm = repo.file_bm25(t["query"])
        r_max = np.empty(len(fmax)); r_max[np.argsort(-fmax, kind="stable")] = np.arange(1, len(fmax) + 1)
        r_bm = np.empty(len(fbm)); r_bm[np.argsort(-fbm, kind="stable")] = np.arange(1, len(fbm) + 1)
        frrf = 1.0 / (K + r_max) + 1.0 / (K + r_bm)
        f_t = time.perf_counter() - t0
        for meth, fs in (("max", fmax), ("top3", ftop3), ("bm25f", fbm), ("rrf", frrf)):
            forder = np.argsort(-fs, kind="stable")[:10].tolist()
            for F in (3, 5, 10):
                for c in (1, 2):
                    lst = []
                    for f in forder[:F]:
                        lst += best_by(task.s_code, ix.file_rows(f).tolist(), c)
                    added = sum(r not in task.cands for r in lst)
                    for w in (0.5, 1.0):
                        t2 = time.perf_counter()
                        order = fuse_extra(repo, task, [(lst, w)])
                        fn, fl = task.ranks(order)
                        rec[f"e5|{meth}|F{F}|c{c}|w{w}"][tid] = (fn, fl, added, int((f_t + time.perf_counter() - t2) * 1e6))
        # ---- 6. exact names (identifiers of the query, looked up among definitions)
        q_idents = C.identifiers(t["query"])
        for D in (3, 10):
            for no_tests in (True, False):
                t0 = time.perf_counter()
                lst: list[int] = []
                seen = set()
                for ident in q_idents:
                    rows = repo.by_qual.get(ident) or repo.by_name.get(ident.rsplit(".", 1)[-1]) or []
                    if no_tests:
                        rows = [r for r in rows if not repo.is_test[r]]
                    if not rows or len(rows) > D:
                        continue
                    for r in best_by(task.s_code, rows, len(rows)):
                        if r not in seen:
                            seen.add(r)
                            lst.append(r)
                lk_t = time.perf_counter() - t0
                for m in (5, 10, 20):
                    g = lst[:m]
                    added = sum(r not in task.cands for r in g)
                    for w in (0.5, 1.0, 2.0):
                        t2 = time.perf_counter()
                        order = fuse_extra(repo, task, [(g, w)])
                        fn, fl = task.ranks(order)
                        rec[f"e6|D{D}|nt{int(no_tests)}|m{m}|w{w}"][tid] = (fn, fl, added, int((lk_t + time.perf_counter() - t2) * 1e6))
        # ---- 7. fusion settings, and keywords from a shortened issue
        for depth in (50, 100, 200):
            for k in (10, 30, 60, 100):
                for wb, wc, wu in WEIGHTS7:
                    t0 = time.perf_counter()
                    order, sc = repo.fu.fuse([("bm25", task.lists["bm25"][:depth], wb), ("code", task.lists["code"][:depth], wc),
                                              ("usage", task.lists["usage"][:depth], wu)], k=k)
                    fn, fl = task.ranks(order)
                    rec[f"e7|d{depth}|k{k}|w{wb},{wc},{wu}"][tid] = (fn, fl, len(set(sc) - task.cands), int((time.perf_counter() - t0) * 1e6))
        # a chunk with no usage vector (nobody calls it) can be in two lists only: give it, in place of
        # the usage list's share, the share its code-list place gives
        for depth in (50, 200):
            for k in (60, 100):
                for wu in (1.0, 0.5):
                    t0 = time.perf_counter()
                    lists = [("bm25", task.lists["bm25"][:depth], 1.0), ("code", task.lists["code"][:depth], 1.0),
                             ("usage", task.lists["usage"][:depth], wu)]
                    order, sc = repo.fu.fuse(lists, k=k)
                    for rank, r in enumerate(task.lists["code"][:depth].tolist(), start=1):
                        if not repo.has_usage[r]:
                            sc[r] += wu / (k + rank)
                    order = sorted(sc, key=lambda r: (-sc[r], repo.loc[r]))
                    fn, fl = task.ranks(order)
                    rec[f"e7fill|d{depth}|k{k}|u{wu}"][tid] = (fn, fl, len(set(sc) - task.cands), int((time.perf_counter() - t0) * 1e6))
        if is_l0 and tid in repo.bm25v:
            bv = repo.bm25v[tid]
            for var in ("title", "w32", "w64", "w128", "idents", "idents_q"):
                order, sc = repo.fu.fuse([("bm25", bv[var][:50], 1.0), ("code", task.lists["code"][:50], 1.0),
                                          ("usage", task.lists["usage"][:50], 1.0)], k=K)
                fn, fl = task.ranks(order)
                rec[f"e7kw|{var}"][tid] = (fn, fl, len(set(sc) - task.cands), 0)
                order, sc = repo.fu.fuse([("bm25", task.lists["bm25"][:50], 1.0), ("code", task.lists["code"][:50], 1.0),
                                          ("usage", task.lists["usage"][:50], 1.0), ("bm25b", bv[var][:50], 1.0)], k=K)
                fn, fl = task.ranks(order)
                rec[f"e7kw2|{var}"][tid] = (fn, fl, len(set(sc) - task.cands), 0)
        # ---- 8. reach without changing the ranking: each card names its r neighbours most similar to the query
        top10 = top[:10]
        s10 = set(top10)
        hit10 = any(r in task.fns for r in top10)
        for v in VERSIONS:
            for d in ("both", "callers", "callees"):
                for rr in (3, 5):
                    named = set()
                    for r in top10:
                        nb = set(ix.neighbours(int(r), v, d).tolist()) - s10
                        named.update(best_by(task.s_code, nb, rr))
                    reach = hit10 or bool(named & task.fns)
                    rec[f"e8|{v}|{d}|r{rr}"][tid] = (1 if reach else None, len(named), 0, 0)
            # the same for the files: a card's file siblings (the best 3 by similarity)
        named = set()
        for r in top10:
            sib = set(ix.file_rows(int(ix.file_of[r])).tolist()) - s10
            named.update(best_by(task.s_code, sib, 3))
        rec["e8|siblings|r3"][tid] = (1 if (hit10 or named & task.fns) else None, len(named), 0, 0)
        # ---- 9. tests as a bridge: measure, then a list of the callees of the best-ranked test chunks
        test_rank = [r for r in top if repo.is_test[r]]
        tests_top10 = [r for r in top10 if repo.is_test[r]]
        tests_top50 = {int(r) for s in C.SIGNALS for r in task.lists[s][:50] if repo.is_test[int(r)]}
        m9 = {}
        for v in VERSIONS:
            c10 = repo.neighbours(tests_top10, v, "callees")
            c50 = repo.neighbours(tests_top50, v, "callees")
            c50_2 = c50 | repo.neighbours(c50, v, "callees") if len(c50) < 5000 else c50
            c10_2 = c10 | repo.neighbours(c10, v, "callees")
            m9[v] = (bool(c10 & task.fns), bool(c10_2 & task.fns), bool(c50 & task.fns), bool(c50_2 & task.fns),
                     len(tests_top10), len(tests_top50))
            for T in (3, 5, 10):
                t0 = time.perf_counter()
                callees = repo.neighbours(test_rank[:T], v, "callees")
                callees = {r for r in callees if not repo.is_test[r]}
                c_t = time.perf_counter() - t0
                for m in (5, 10, 20):
                    g = best_by(task.s_code, callees, m)
                    added = sum(r not in task.cands for r in g)
                    for w in (0.5, 1.0):
                        t2 = time.perf_counter()
                        order = fuse_extra(repo, task, [(g, w)])
                        fn, fl = task.ranks(order)
                        rec[f"e9|{v}|T{T}|m{m}|w{w}"][tid] = (fn, fl, added, int((c_t + time.perf_counter() - t2) * 1e6))
        meta.setdefault("tests_bridge", {})[tid] = m9
        # ---- 10. a cap per file in the top 10 (the others move down, not out)
        for cap in (1, 2, 3):
            t0 = time.perf_counter()
            kept, moved, per = [], [], Counter()
            for r in top:
                if len(kept) < 10:
                    f = int(ix.file_of[r])
                    if per[f] < cap:
                        per[f] += 1
                        kept.append(r)
                    else:
                        moved.append(r)
                else:
                    moved.append(r)
            order = kept + moved
            put(f"e10|cap{cap}", order, 0, t0)
        # ---- 11. test code weighted down, or left out
        for tw in (0.75, 0.5, 0.25):
            t0 = time.perf_counter()
            factor = {r: tw for r in task.scores if repo.is_test[r]}
            order, _ = repo.fu.fuse([(s, task.lists[s][:50], 1.0) for s in C.SIGNALS], k=K, factor=factor)
            put(f"e11|tw{tw}", order, 0, t0)
        t0 = time.perf_counter()
        order, _ = repo.fu.fuse([(s, [r for r in task.lists[s] if not repo.is_test[int(r)]][:50], 1.0) for s in C.SIGNALS], k=K)
        put("e11|exclude", order, 0, t0)
        # ---- 13. files changed together (only commits older than the issue)
        before = int(np.datetime64(t["issue_created"].replace("Z", ""), "s").astype(np.int64))
        n_commits = int(np.searchsorted(repo.cc_times, before))
        top10_files = []
        for r in top10:
            f = int(ix.file_of[r])
            if f not in top10_files:
                top10_files.append(f)
        per_file_top5 = set()
        for f in top10_files:
            cnt = repo.cochange([f], before)
            cnt[f] = 0
            nz = np.nonzero(cnt)[0]
            per_file_top5.update(nz[np.lexsort((nz, -cnt[nz]))][:5].tolist())
        summed = repo.cochange(top10_files, before)
        summed[top10_files] = 0
        nz = np.nonzero(summed)[0]
        summed_top5 = set(nz[np.lexsort((nz, -summed[nz]))][:5].tolist())
        meta.setdefault("cochange", {})[tid] = {
            "commits_before": n_commits, "gold_file_in_top10_files": bool(set(top10_files) & task.files),
            "gold_in_per_file_top5": bool(per_file_top5 & task.files), "gold_in_summed_top5": bool(summed_top5 & task.files),
            "has_file": bool(task.files)}
        for n in (3, 5, 10):
            t0 = time.perf_counter()
            seedf = []
            for r in top[:n]:
                f = int(ix.file_of[r])
                if f not in seedf:
                    seedf.append(f)
            cnt = repo.cochange(seedf, before)
            cnt[seedf] = 0
            nz = np.nonzero(cnt)[0]
            ranked_f = nz[np.lexsort((nz, -cnt[nz]))].tolist()
            cc_t = time.perf_counter() - t0
            for P in (3, 5, 10):
                rows = []
                for f in ranked_f[:P]:
                    rows += ix.file_rows(f).tolist()
                for m in (5, 10, 20):
                    g = best_by(task.s_code, rows, m)
                    added = sum(r not in task.cands for r in g)
                    for w in (0.5, 1.0):
                        t2 = time.perf_counter()
                        order = fuse_extra(repo, task, [(g, w)])
                        fn, fl = task.ranks(order)
                        rec[f"e13|n{n}|P{P}|m{m}|w{w}"][tid] = (fn, fl, added, int((cc_t + time.perf_counter() - t2) * 1e6))
        if (ti + 1) % 25 == 0:
            print(f"{set_name}: {ti + 1}/{len(tasks)} in {time.perf_counter() - t_start:.0f} s", flush=True)


def main() -> None:
    repo_name = sys.argv[1]
    names = sys.argv[2:] or {"vllm": ["vllm-L0", "vllm-title"], "pandas": ["pandas-L0", "pandas-title", "vague-L1", "vague-L2"]}[repo_name]
    t0 = time.perf_counter()
    repo = Repo(repo_name)
    print(f"{repo_name}: loaded in {time.perf_counter() - t0:.0f} s", flush=True)
    sets = L.query_sets(names)
    for name in names:
        run = C.load_run(name, repo.ix)
        out: dict = {}
        run_set(repo, name, sets[name]["tasks"], run, out)
        (L.OUT / f"s3-{name}.json").write_text(json.dumps(out), "utf-8")
        print(f"{name}: saved", flush=True)


if __name__ == "__main__":
    main()
