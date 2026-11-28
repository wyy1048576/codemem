"""Shared pieces of the v3-against-v2 check (brief .cache/review/briefs/v3-against-v2.md): the two codemem sources, the
vLLM tasks in the harness's task format, a stdio MCP client that starts codemem's server exactly as a session does
(compare.write_mcp: mcp_hold.py, compare.server_env, the task's repo, a copy of its index), and the machine discipline
of compare.run_one (quiet machine, heavy lock, model.lock.d) for anything that loads the embedding model."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import compare as K  # noqa: E402

C, CM, PY = K.C, K.CM, K.PY
V = C / "v3"
SRC = {"v2": K.MAIN / "src", "v3": CM / ".cache/wt/compare-pr85/src"}
COMMIT = {"v2": "463171c", "v3": "4902671"}
VLLM_TASKS = CM / ".cache/review/adopt/vllm-l2.jsonl"
BLOCKS = V / "upfront-463171c"  # the 20 lines, made at 463171c (codemem search -k 20 --json, as upfront.py)
PROTOCOL = "2025-11-25"


def vllm_tasks() -> dict:
    """The 6 vLLM L2 tasks in the format compare.extract reads (gold files, functions, no classes)."""
    out = {}
    for line in VLLM_TASKS.read_text().split("\n"):
        if line.strip():
            t = json.loads(line)
            out[t["id"]] = {"id": t["id"], "repo": "vllm", "query": t["prompt"], "l2": t["prompt"],
                            "gold": {"files": t["gold_files"], "functions": t["gold_functions"], "classes": []}}
    return out


def all_tasks() -> tuple[dict, dict]:
    """compare's pandas tasks and vague prompts, plus the vLLM tasks (their L2 text is the prompt itself)."""
    tasks, vague = K.load_tasks(), K.load_vague()
    for tid, t in vllm_tasks().items():
        tasks[tid] = t
        vague[(tid, "L2")] = t["l2"]
    return tasks, vague


def free_gb() -> float:
    st = shutil.disk_usage(str(CM))
    return st.free / 1024 ** 3


@contextmanager
def machine(what: str = ""):
    """As compare.run_one before a session: no other model process or headless session, quiet.sh, the heavy lock,
    then model.lock.d (shared with other agents)."""
    K.wait_for_quiet()
    subprocess.run([str(C / "bin/quiet.sh")])
    K.wait_for_quiet()
    lock = K.heavy_lock()
    t0 = time.time()
    while True:
        try:
            K.MODEL_LOCK.mkdir()
            break
        except FileExistsError:
            if time.time() - t0 > 3600:
                lock.close()
                raise SystemExit(f"model.lock.d was held for an hour ({what})")
            time.sleep(5)
    try:
        yield
    finally:
        try:
            K.MODEL_LOCK.rmdir()
        except OSError:
            pass
        lock.close()


def clone_index(task_id: str, idx: Path) -> None:
    shutil.rmtree(idx, ignore_errors=True)
    idx.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-c", "-R", str(C / "tasks" / task_id / "index"), str(idx)], check=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def snapshot(idx: Path) -> dict:
    """What an index folder holds, read without touching it (sqlite immutable): its search-index files (size and
    sha256), the row counts, and the meta that an update rewrites."""
    files = {f.name: {"bytes": f.stat().st_size, "sha256": sha256(f)[:16]} for f in sorted(idx.iterdir())
             if f.suffix in (".faiss", ".json")}
    db = sqlite3.connect(f"file:{idx}/index.db?immutable=1", uri=True)
    q = lambda s: db.execute(s).fetchall()  # noqa: E731
    out = {"files": files,
           "chunks": q("select count(*) from chunks")[0][0],
           "file_rows": q("select count(*) from files")[0][0],
           "vectors": dict(q("select vec_type, count(*) from vectors group by vec_type")),
           "meta": {k: v for k, v in q("select key, value from meta where key in ('indexed_at', 'last_update', "
                                       "'schema_version', 'index_settings', 'dirty_seq', 'last_scan_at', 'repo_path')")}}
    db.close()
    return out


class Srv:
    """codemem's MCP server over stdio, started as a session starts it, on a given copy of a task's index."""

    def __init__(self, arm: str, task_id: str, idx: Path, home: Path, log_path: Path):
        shutil.rmtree(home, ignore_errors=True)
        home.mkdir(parents=True)
        self.idx, self.home = idx, home
        log_path.unlink(missing_ok=True)
        self.log_path = log_path
        env = K.server_env(SRC[arm], home)
        env.update({k: v for k, v in K.clean_env("http://127.0.0.1:9").items()
                    if k in ("HOME", "USER", "PATH", "TMPDIR", "LANG")})
        repo = C / "tasks" / task_id / "repo"
        argv = [str(PY), str(C / "bin/mcp_hold.py"), str(log_path), K.HOLD_MARGIN, "120", "--",
                str(PY), "-m", "codemem", "mcp", str(repo), "--index-dir", str(idx)]
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  env=env, cwd=str(repo), start_new_session=True)
        self.t_start = time.monotonic()
        self.answers: dict = {}
        self.cond = threading.Condition()
        self.next_id = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                with self.cond:
                    self.answers[msg["id"]] = msg
                    self.cond.notify_all()

    def _send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if not notify:
            self.next_id += 1
            msg["id"] = self.next_id
        if params is not None:
            msg["params"] = params
        self.p.stdin.write((json.dumps(msg) + "\n").encode())
        self.p.stdin.flush()
        return msg.get("id")

    def request(self, method, params=None, timeout=300):
        rid = self._send(method, params)
        end = time.monotonic() + timeout
        with self.cond:
            while rid not in self.answers:
                left = end - time.monotonic()
                if left <= 0:
                    raise TimeoutError(f"no answer to {method}")
                self.cond.wait(left)
            return self.answers.pop(rid)

    def initialize(self):
        res = self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                          "clientInfo": {"name": "v3check", "version": "1"}})
        self._send("notifications/initialized", notify=True)
        return res

    def tools(self) -> list[dict]:
        return self.request("tools/list", {})["result"]["tools"]

    def call(self, tool, args, timeout=300) -> tuple[str, bool]:
        res = self.request("tools/call", {"name": tool, "arguments": args}, timeout)
        if "error" in res:
            return "JSONRPC-ERROR " + json.dumps(res["error"]), True
        r = res["result"]
        return "".join(c.get("text", "") for c in r.get("content", [])), bool(r.get("isError"))

    def status(self) -> dict:
        text, _ = self.call("index_status", {})
        try:
            return json.loads(text.rsplit("\n\n", 1)[-1])
        except ValueError:
            return {"unparsed": text[:300]}

    def wait_ready(self, limit=300) -> dict:
        t0 = time.monotonic()
        while True:
            st = self.status()
            if st.get("state") == "ready" and st.get("models_loaded"):
                return st
            if time.monotonic() - t0 > limit:
                raise TimeoutError(f"not ready: {st}")
            time.sleep(1)

    def close(self):
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=60)
        except subprocess.TimeoutExpired:
            K.kill_tree(self.p)
        for pid in K.leftover_servers(self.idx):
            try:
                import os
                import signal
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        shutil.rmtree(self.home, ignore_errors=True)
