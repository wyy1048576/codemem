"""Checks before the v3-against-v2 sessions (brief .cache/review/briefs/v3-against-v2.md, 'Before the first session').
No model call: only codemem's server or command runs, one at a time, under v3lib.machine().

usage:
  v3check.py index <task id> ...            v2's and v3's server on a copy of an existing index: rebuilt or not
  v3check.py plain <task id> <run> <run> <run>
                                            the first search_code query of three earlier sessions, with only `query`,
                                            at 463171c and at 4902671, on one copy of the task's index
  v3check.py blocks <task id> ...           the 20 lines at 463171c (as upfront.py), against the saved ones
Results: v3/check-<what>.json and the lines printed."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import compare as K  # noqa: E402
import dedup_mc as M  # noqa: E402  (session_calls: a saved session's codemem calls, in order)
import upfront as U  # noqa: E402  (env: the upfront search's environment, with the code of compare-main)
import v3lib as L  # noqa: E402

C, V = L.C, L.V


def save(name: str, data) -> None:
    path = V / f"check-{name}.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    old.update(data)
    path.write_text(json.dumps(old, indent=1))


def check_index(task_id: str) -> dict:
    out = {}
    for arm in ("v2", "v3"):
        label = f"v3check-index-{arm}-{task_id[-5:]}"
        idx, home = C / "idx" / label, C / "home-runs" / label
        log_path = V / "logs" / f"{label}.log"
        L.clone_index(task_id, idx)
        before = L.snapshot(idx)
        with L.machine(label):
            s = L.Srv(arm, task_id, idx, home, log_path)
            s.initialize()
            t_init = round(time.monotonic() - s.t_start, 1)
            st_first = s.status()
            st_ready = s.wait_ready()
            t_ready = round(time.monotonic() - s.t_start, 1)
            text, err = s.call("search_code", {"query": "where is the configuration file read"})
            time.sleep(8)  # the start-up reconcile has had time to run
            st_after = s.status()
            s.close()
        after = L.snapshot(idx)
        shutil.rmtree(idx, ignore_errors=True)
        log = log_path.read_text(errors="replace") if log_path.exists() else ""
        out[arm] = {"commit": L.COMMIT[arm], "seconds_to_handshake": t_init, "seconds_to_ready": t_ready,
                    "status_first": st_first, "status_ready": st_ready, "status_after_search": st_after,
                    "search_error": err, "search_cards": len(K.cards(text)), "search_keyword_only": "keyword matching only" in text,
                    "before": before, "after": after,
                    "same_search_files": before["files"] == after["files"],
                    "same_counts": all(before[k] == after[k] for k in ("chunks", "file_rows", "vectors")),
                    "meta_changed": sorted(k for k in set(before["meta"]) | set(after["meta"])
                                           if before["meta"].get(k) != after["meta"].get(k)),
                    "log_lines": [l for l in log.split("\n") if "codemem" in l and "Loading weights" not in l][:40]}
        o = out[arm]
        print(f"{task_id} {arm} ({L.COMMIT[arm]}): ready {t_ready} s, state {st_ready.get('state')}, chunks "
              f"{st_ready.get('chunks')}, vectors {st_ready.get('vectors')}, stale {st_after.get('stale')}; search files "
              f"unchanged {o['same_search_files']}, counts unchanged {o['same_counts']}, meta changed {o['meta_changed']}; "
              f"search: {o['search_cards']} cards, keyword only {o['search_keyword_only']}", flush=True)
    save("index", {task_id: out})
    return out


def first_query(run: str) -> str:
    """The first search_code query of a saved session of this harness (runs/) or of the adopt probe (adopt/runs/)."""
    folder = K.RUNS / run if (K.RUNS / run).is_dir() else K.CM / ".cache/review/adopt/runs" / run
    calls = [c for c in M.session_calls(folder) if c["tool"] == "search_code"]
    return calls[0]["input"]["query"]


def check_plain(task_id: str, runs: list[str]) -> dict:
    queries = [first_query(r) for r in runs]
    label = f"v3check-plain-{task_id[-5:]}"
    idx = C / "idx" / label
    L.clone_index(task_id, idx)
    texts, tools = {}, {}
    for arm in ("v2", "v3"):
        home = C / "home-runs" / f"{label}-{arm}"
        with L.machine(label):
            s = L.Srv(arm, task_id, idx, home, V / "logs" / f"{label}-{arm}.log")
            s.initialize()
            tools[arm] = s.tools()
            s.wait_ready()
            texts[arm] = []
            for q in queries:
                for _ in range(30):
                    text, err = s.call("search_code", {"query": q})
                    if "still loading" not in text and "Search again in a few seconds" not in text:
                        break
                    time.sleep(1)
                texts[arm].append({"query": q, "text": text, "error": err})
            s.close()
    shutil.rmtree(idx, ignore_errors=True)
    rows = []
    for i, q in enumerate(queries):
        a, b = texts["v2"][i]["text"], texts["v3"][i]["text"]
        ca, cb = [(c["path"], c["start"], c["end"], c["name"], c["id"]) for c in K.cards(a)], \
                 [(c["path"], c["start"], c["end"], c["name"], c["id"]) for c in K.cards(b)]
        rows.append({"run": runs[i], "query": q, "cards_v2": len(ca), "cards_v3": len(cb), "same_cards": ca == cb,
                     "same_text": a == b, "chars_v2": len(a), "chars_v3": len(b),
                     "diff_lines": [l for l in set(b.split("\n")) ^ set(a.split("\n"))][:12]})
        print(f"{task_id} query {i + 1} ({runs[i]}): {len(ca)} / {len(cb)} cards, same cards {ca == cb}, "
              f"same text {a == b} ({len(a)} / {len(b)} chars): {q[:90]!r}", flush=True)
    save("plain", {task_id: {"rows": rows, "texts": texts,
                             "schemas": {arm: {t["name"]: t.get("inputSchema") for t in tools[arm]} for arm in tools},
                             "descriptions": {arm: {t["name"]: t.get("description") for t in tools[arm]} for arm in tools}}})
    return {"rows": rows}


def block_lines(path: Path) -> list[str]:
    d = json.loads(path.read_text())
    hits = d.get("results", d) if isinstance(d, dict) else d
    return [f"{h['path']}:{h['start_line']}  {h.get('qualname') or h.get('name') or ''}".rstrip() for h in hits[:20]]


def check_blocks(tids: list[str]) -> None:
    tasks, vague = L.all_tasks()
    L.BLOCKS.mkdir(parents=True, exist_ok=True)
    rows = {}
    for tid in tids:
        out = L.BLOCKS / f"{tid}-L2.json"
        text = vague[(tid, "L2")].strip()
        if not out.exists():
            label = f"v3block-{tid[-5:]}"
            idx, home = C / "idx" / label, C / "home-runs" / label
            L.clone_index(tid, idx)
            shutil.rmtree(home, ignore_errors=True)
            home.mkdir(parents=True)
            with L.machine(label):
                t0 = time.time()
                p = subprocess.run([str(K.PY), "-m", "codemem", "search", text, "--repo", str(C / "tasks" / tid / "repo"),
                                    "--index-dir", str(idx), "-k", "20", "--json"], env=U.env(home), capture_output=True,
                                   text=True, cwd=str(C))
                secs = round(time.time() - t0, 1)
            shutil.rmtree(idx, ignore_errors=True)
            shutil.rmtree(home, ignore_errors=True)
            if p.returncode != 0:
                raise SystemExit(f"{tid}: search failed: {p.stderr[-800:]}")
            d = json.loads(p.stdout)
            if not any(k.startswith("embed_query:") for k in d.get("timings") or {}):
                raise SystemExit(f"{tid}: the query was not embedded (keywords only): {d.get('timings')}")
            d["_request"], d["_seconds"], d["_commit"] = text, secs, L.COMMIT["v2"]
            d["_stderr_tail"] = p.stderr[-400:]
            out.write_text(json.dumps(d, indent=1))
        new = block_lines(out)
        saved_path = C / "upfront" / f"{tid}-L2.json"
        saved = block_lines(saved_path) if saved_path.exists() else None
        same_request = (json.loads(saved_path.read_text()).get("_request") == text) if saved_path.exists() else None
        gold = set(tasks[tid]["gold"]["files"])
        ranks = [i + 1 for i, l in enumerate(new) if l.split(":")[0] in gold]
        rows[tid] = {"lines": len(new), "saved": saved is not None, "same_as_saved": saved == new if saved else None,
                     "same_request": same_request, "gold_file_ranks": ranks,
                     "differs_at": [i + 1 for i, (a, b) in enumerate(zip(saved or [], new)) if a != b]}
        print(f"{tid}: {len(new)} lines; saved {'none' if saved is None else ('same' if saved == new else 'DIFFERENT')}; "
              f"gold file at {ranks[:5]}", flush=True)
    save("blocks", rows)


def main():
    what, args = sys.argv[1], sys.argv[2:]
    if what == "index":
        for t in args:
            check_index(t)
    elif what == "plain":
        check_plain(args[0], args[1:4])
    elif what == "blocks":
        check_blocks(args)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
