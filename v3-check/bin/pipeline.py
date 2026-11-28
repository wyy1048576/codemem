"""The coordinator's order (message of 08:2x): per task, newest commit first, build its index and check it, then
its six Haiku sessions (L2, then L1; arms grep, tool, tool+ rotating from cell to cell); the running table at the
top of progress.md every 3 tasks. Then blocks (ii) upfront Haiku L2+L1, (iii) Sonnet L2 four arms on the 8 newest
tasks, (iv) Haiku L0 grep+tool, (v) Sonnet L2 four arms on the other 9, up to the cap of 280 sessions.

usage: pipeline.py [--blocks i,ii,iii,iv,v]
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import compare as K  # noqa: E402
import summary as S  # noqa: E402

C = K.C
HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
SHORT = {HAIKU: "haiku", SONNET: "sonnet", OPUS: "opus"}
ARM_ID = {"grep": "grep", "tool": "tool", "upfront": "upfront", "tool+": "toolplus", "tool-h": "toolh", "tool+h": "toolplush"}
# newest commit first (pandas-src commit dates; ties by the order found)
ORDER = ["67025", "70966", "71232", "69779", "71248", "71129", "70828", "69924", "70205", "70734", "68278", "68195",
         "67897", "69015", "68945", "68090", "66352"]
ORDER = [f"pandas-dev__pandas-{n}" for n in ORDER]
TOP_START, TOP_END = "<!-- running table: start -->", "<!-- running table: end -->"


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(C / "logs/pipeline.log", "a") as f:
        f.write(line + "\n")


def build_env() -> dict:
    e = dict(os.environ)
    root = str(K.CM)
    e.update({"PYTHONPATH": str(K.MAIN / "src"), "CODEMEM_HOME": str(C / "home"), "CODEMEM_VECTOR_BACKEND": "faiss",
              "HF_HOME": root + "/.cache/huggingface", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
              "TORCH_HOME": root + "/.cache/torch", "XDG_CACHE_HOME": root + "/.cache/xdg",
              "MPLCONFIGDIR": root + "/.cache/mpl", "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1",
              "MKL_NUM_THREADS": "1"})
    for k in ("CODEMEM_STEERING", "CODEMEM_MODEL", "CODEMEM_DEVICE"):
        e.pop(k, None)
    return e


def status(tid: str) -> dict:
    p = subprocess.run([str(K.PY), "-m", "codemem", "status", f"tasks/{tid}/repo", "--index-dir", f"tasks/{tid}/index",
                        "--json"], cwd=str(C), env=build_env(), capture_output=True, text=True)
    if p.returncode != 0:
        raise K.StopRun(f"{tid}: codemem status failed: {p.stderr[-500:]}", 5)
    return json.loads(p.stdout)


def is_current(st: dict) -> tuple[bool, str]:
    """Nothing changed and nothing left to embed, as `codemem status --json` reports it."""
    stale = st.get("stale") or {}
    ok = (st.get("state") == "ready" and st.get("pending_chunks") == 0 and st.get("pending_files") == 0
          and stale.get("changed_files") == 0 and stale.get("deleted_files") == 0)
    lu = st.get("last_update") or {}
    return ok, (f"state={st.get('state')} pending={st.get('pending_chunks')}/{st.get('pending_files')} "
                f"stale={stale.get('changed_files')}/{stale.get('deleted_files')} "
                f"model_embedded={sum((lu.get('model_embedded') or {}).values())}")


def index_check(tid: str, tasks: dict, seconds: float | None, new_vectors: int | None) -> dict:
    st = status(tid)
    ok, why = is_current(st)
    embedded = sum(((st.get("last_update") or {}).get("model_embedded") or {}).values())
    if embedded:
        new_vectors = embedded  # codemem's own count of the texts the model embedded in this build
    db = sqlite3.connect(f"file:{C}/tasks/{tid}/index/index.db?mode=ro", uri=True)
    gold = tasks[tid]["gold"]
    found = []
    for f in gold["functions"]:
        n = db.execute("select count(*) from chunks where path=? and qualname=?", (f["path"], f["symbol"])).fetchone()[0]
        found.append((f["symbol"], n))
    files = db.execute("select count(*) from files").fetchone()[0]
    chunks = db.execute("select count(*) from chunks").fetchone()[0]
    db.close()
    row = {"task": tid, "current": ok, "status": why, "files": files, "chunks": chunks, "new_vectors": new_vectors,
           "seconds": seconds, "gold_functions_in_index": [s for s, n in found if n], "gold_functions_missing":
           [s for s, n in found if not n], "time": time.strftime("%H:%M:%S")}
    with open(C / "logs/phase1.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")
    log(f"{tid}: index current={ok} files={files} chunks={chunks} new_vectors={new_vectors} seconds={seconds} "
        f"gold functions missing={row['gold_functions_missing']} ({why})")
    if not ok:
        raise K.StopRun(f"{tid}: the index is not current after its build: {why}", 5)
    return row


def checked(tid: str) -> bool:
    path = C / "logs/phase1.jsonl"
    if not path.exists():
        return False
    return any(r.get("task") == tid and r.get("current") for r in (json.loads(l) for l in path.read_text().split("\n") if l.strip()))


def build_numbers(tid: str) -> tuple[float | None, int | None]:
    path = C / "logs/builds.tsv"
    for line in (path.read_text().split("\n") if path.exists() else []):
        parts = line.split("\t")
        if len(parts) > 4 and parts[0] == tid:
            return float(parts[2]), int(parts[4])
    return None, None


class SkipTask(Exception):
    pass


def machine_ready() -> tuple[bool, str]:
    """At least 30% free by memory_pressure and a 1-minute load average under 6 (the coordinator's test)."""
    free = K.free_memory()
    load = float(subprocess.run(["sysctl", "-n", "vm.loadavg"], capture_output=True, text=True).stdout.split()[1])
    return free >= 30 and load < 6, f"free {free}%, load {load:.1f}"


def build(tid: str, tasks: dict) -> None:
    index = C / "tasks" / tid / "index" / "index.db"
    if index.exists() and checked(tid):
        return
    for attempt in (1, 2):
        if not index.exists():
            log(f"{tid}: building (attempt {attempt})")
            rc = subprocess.run([str(C / "bin/build.sh"), tid]).returncode
            if rc == 9:
                log(f"{tid}: the build stalled (attempt {attempt}): its embed counter did not move for 5 minutes")
                shutil.rmtree(C / "tasks" / tid / "index", ignore_errors=True)
                with open(C / "progress.md", "a") as f:
                    f.write(f"\n- {time.strftime('%H:%M')}: the build of {tid[-5:]} stalled (attempt {attempt}); "
                            f"partial index removed.\n")
                if attempt == 2:
                    raise SkipTask(f"{tid}: the build stalled twice")
                while True:
                    ok, why = machine_ready()
                    if ok:
                        log(f"{tid}: machine ready again ({why}); building once more")
                        break
                    log(f"{tid}: waiting for the machine ({why})")
                    time.sleep(30)
                continue
            if rc != 0:
                raise K.StopRun(f"{tid}: the build ended with {rc}", 5)
        break
    seconds, new_vectors = build_numbers(tid)
    index_check(tid, tasks, seconds, new_vectors)


def spec(arm: str, tid: str, level: str, model: str, cell: str, cd: bool) -> dict:
    return {"run": f"{ARM_ID[arm]}-{tid[-5:]}-{level}-{SHORT[model]}", "arm": arm, "task": tid, "level": level,
            "model": model, "cell": cell, "cd": cd}


def rotated(arms: list[str], k: int) -> list[str]:
    return arms[k % len(arms):] + arms[:k % len(arms)]


def write_table(note: str) -> None:
    import importlib
    importlib.reload(S)  # the table code may improve while a block runs
    S.write_progress_table(note, K.ledger_count())
    log(f"table written: {note}")


def haiku_block(tasks, vague, tids, cd, name, k0=0):
    """Per task: build and check its index, then L2 and L1 with grep, tool, tool+ rotating from cell to cell."""
    k = k0
    for i, tid in enumerate(tids):
        lock = K.heavy_lock()
        try:
            build(tid, tasks)
        except SkipTask as e:
            log(f"SKIP: {e}")
            with open(C / "progress.md", "a") as f:
                f.write(f"\n- **Skipped {tid[-5:]}**: its build stalled twice; no session for it.\n")
            k += 2
            continue
        finally:
            lock.close()
        for level in ("L2", "L1"):
            cell = f"{tid[-5:]}-{level}-haiku"
            for arm in rotated(["grep", "tool", "tool+"], k):
                K.run_spec(spec(arm, tid, level, HAIKU, cell, cd), tasks, vague)
            k += 1
        if (i + 1) % 3 == 0 or i + 1 == len(tids):
            write_table(f"block {name}, {i + 1} of {len(tids)} tasks")
    return k


def sonnet_block(tasks, vague, tids, name, k0=0):
    """Per task, L2 with the five arms rotating; the table every 2 tasks."""
    upfront(tids, ("L2",))
    k = k0
    for i, tid in enumerate(tids):
        cell = f"{tid[-5:]}-L2-sonnet"
        for arm in rotated(["grep", "tool", "tool-h", "tool+h", "upfront"], k):
            K.run_spec(spec(arm, tid, "L2", SONNET, cell, True), tasks, vague)
        k += 1
        if (i + 1) % 2 == 0 or i + 1 == len(tids):
            write_table(f"block {name}, {i + 1} of {len(tids)} tasks")


def upfront(tids, levels):
    lock = K.heavy_lock()
    lock.close()  # upfront.py takes the lock itself for each search
    subprocess.run([str(K.PY), str(C / "bin/upfront.py"), ",".join(levels), *tids], check=True)


def indexed(tid: str) -> bool:
    return (C / "tasks" / tid / "index" / "index.db").exists() and checked(tid)


def main() -> None:
    blocks = sys.argv[sys.argv.index("--blocks") + 1].split(",") if "--blocks" in sys.argv else ["A", "B", "C"]
    tasks, vague = K.load_tasks(), K.load_vague()
    first8, other9 = ORDER[:8], ORDER[8:]
    try:
        for b in blocks:
            log(f"block {b} starts")
            if b == "A":  # (i-b): Haiku, the other 9 tasks (2 done already), L2 then L1, 66352 last
                haiku_block(tasks, vague, other9, True, "A (i-b), Haiku, other 9 tasks, cd allowed", k0=16)
            elif b == "B":  # upfront with Haiku at L2, all 17 tasks
                tids = [t for t in ORDER if indexed(t)]
                upfront(tids, ("L2",))
                for tid in tids:
                    K.run_spec(spec("upfront", tid, "L2", HAIKU, f"{tid[-5:]}-L2-haiku-upfront", True), tasks, vague)
                write_table("block B, upfront with Haiku at L2, cd allowed")
            elif b == "C":  # Sonnet at L2 on the 9 tasks it has not seen: grep, tool, upfront
                tids = [t for t in other9 if indexed(t)]
                upfront(tids, ("L2",))
                k = 0
                for i, tid in enumerate(tids):
                    cell = f"{tid[-5:]}-L2-sonnet"
                    for arm in rotated(["grep", "tool", "upfront"], k):
                        K.run_spec(spec(arm, tid, "L2", SONNET, cell, True), tasks, vague)
                    k += 1
                    if (i + 1) % 3 == 0 or i + 1 == len(tids):
                        write_table(f"block C, Sonnet on the other 9 tasks, {i + 1} of {len(tids)}")
            elif b == "D":  # Opus at L2 on six tasks: grep, tool, upfront, the order rotating from task to task
                tids = [f"pandas-dev__pandas-{n}" for n in ("69924", "68195", "70828", "71129", "66352", "67025")]
                upfront(tids, ("L2",))  # the lists exist; nothing is searched again
                for k, tid in enumerate(tids):
                    for arm in rotated(["grep", "tool", "upfront"], k):
                        rec = K.run_spec(spec(arm, tid, "L2", OPUS, f"{tid[-5:]}-L2-opus", True), tasks, vague)
                        res = rec.get("result") or {}
                        if res.get("is_error") and res.get("subtype") != "error_max_turns":
                            raise K.StopRun(f"{rec['run']}: Claude Code reported an error, word for word: "
                                            f"{json.dumps(res)} | final text: {rec.get('final_text_tail')!r}", 6)
                    if (k + 1) % 3 == 0:
                        write_table(f"block D, Opus on six tasks, {k + 1} of 6")
            log(f"block {b} done")
    except K.StopRun as e:
        log(f"STOP: {e}")
        try:
            write_table(f"stopped: {e}")
        except Exception as e2:  # noqa: BLE001
            log(f"table not written: {e2}")
        sys.exit(e.code)
    except SystemExit as e:
        log(f"STOP (exit {e.code})")
        try:
            write_table(f"stopped (exit {e.code})")
        except Exception as e2:  # noqa: BLE001
            log(f"table not written: {e2}")
        raise
    log("all blocks done")


if __name__ == "__main__":
    main()
