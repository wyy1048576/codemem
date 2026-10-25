import json
import os
import subprocess
import sys
import time

import pytest

from cmeval.paths import status_dir
from datetime import datetime, timedelta, timezone

from cmeval.status import STALE_SECONDS, JobStatus, is_over, pid_alive, prune, read_all


def read(status):
    return json.loads(status.path.read_text())


def test_counts_parts_log_and_done(tmp_path):
    with JobStatus("run", "r1", folder=tmp_path, interval=60) as status:
        status.total(5, "tasks")
        status.part("acme/a", 3, done=1)
        status.part("acme/b", 2)
        status.already_done(1)
        status.stage("repo 1/2: acme/a")
        status.advance(part="acme/a")
        status.log("line 1")
        status.write()
        data = read(status)
        assert (data["state"], data["done"], data["total"], data["unit"]) == ("running", 2, 5, "tasks")
        assert data["parts"] == {"acme/a": {"done": 2, "total": 3}, "acme/b": {"done": 0, "total": 2}}
        assert data["stage"] == "repo 1/2: acme/a" and data["log"] == ["line 1"] and data["pid"] == os.getpid()
        status.result(searched=3)
    data = read(status)
    assert data["state"] == "done" and data["ended"] and data["result"] == {"searched": 3}
    assert status.path.name.startswith("run-") and status.path.name.endswith(f"-{os.getpid()}.json")


def test_an_error_or_ctrl_c_marks_the_job_failed(tmp_path):
    with pytest.raises(ValueError):
        with JobStatus("run", "r1", folder=tmp_path, interval=60) as status:
            raise ValueError("bad input")
    assert read(status)["state"] == "failed" and read(status)["error"] == "ValueError: bad input"
    with pytest.raises(KeyboardInterrupt):
        with JobStatus("run", "r2", folder=tmp_path, interval=60) as status:
            raise KeyboardInterrupt
    assert read(status)["state"] == "failed" and read(status)["error"] == "KeyboardInterrupt"


def test_fail_marks_a_handled_error(tmp_path):
    with JobStatus("score", "r1", folder=tmp_path, interval=60) as status:
        status.fail("no run folder")
    assert read(status)["state"] == "failed" and read(status)["error"] == "no run folder"


def test_a_write_error_never_stops_the_job(tmp_path):
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("a file where the folder should be")
    with JobStatus("run", "r1", folder=blocked, interval=0.01) as status:
        status.advance()
        time.sleep(0.05)
    assert blocked.read_text() == "a file where the folder should be"


def test_the_thread_writes_without_calls_from_the_job(tmp_path):
    with JobStatus("run", "r1", folder=tmp_path, interval=0.02) as status:
        status.stage("building the index")  # a long call follows; the job makes no more calls
        deadline = time.monotonic() + 5
        while read(status)["stage"] != "building the index" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert read(status)["stage"] == "building the index"


def test_speed_and_time_left_use_this_session_only(tmp_path):
    clock = [1000.0]
    with JobStatus("run", "r1", folder=tmp_path, interval=60, clock=lambda: clock[0]) as status:
        status.total(100)
        status.already_done(40)  # from an earlier session: not in the speed
        status.write()
        assert read(status)["rate"] is None and read(status)["eta_seconds"] is None
        clock[0] += 60
        status.advance(10)
        status.write()
        data = read(status)
        assert data["rate"] == 10.0 and data["eta_seconds"] == 300  # 50 left at 10 a minute
        clock[0] += 600  # 10 minutes with no progress: the 5-minute window has no new work
        status.write()
        assert read(status)["rate"] is None


def test_prune_keeps_running_jobs_and_the_newest_finished(tmp_path):
    proc = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    dead_pid = int(proc.stdout)
    for i in range(5):
        (tmp_path / f"run-{i}.json").write_text(json.dumps({"state": "done", "pid": 1, "started": f"2026-10-25T00:0{i}"}))
    updated = datetime.now(timezone.utc).isoformat()
    (tmp_path / "run-live.json").write_text(json.dumps({"state": "running", "pid": os.getpid(), "started": "2026-10-24",
                                                        "updated": updated}))
    (tmp_path / "run-dead.json").write_text(json.dumps({"state": "running", "pid": dead_pid, "started": "2026-10-23"}))
    (tmp_path / "half-written.json").write_text("{")
    old_tmp, new_tmp = tmp_path / "run-x.json.tmp", tmp_path / "run-y.json.tmp"  # left by stopped writes
    old_tmp.write_text("{")
    new_tmp.write_text("{")
    os.utime(old_tmp, (time.time() - 7200, time.time() - 7200))
    prune(tmp_path, keep=2)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["half-written.json", "run-3.json", "run-4.json", "run-live.json", "run-y.json.tmp"]
    assert [job["file"] for job in read_all(tmp_path)] == ["run-4.json", "run-3.json", "run-live.json"]


def test_is_over_by_state_process_and_age():
    now = datetime.now(timezone.utc)
    live = {"state": "running", "pid": os.getpid(), "updated": now.isoformat()}
    assert not is_over(live, now)
    assert is_over({**live, "state": "done"}, now)
    assert is_over({**live, "pid": 0}, now)
    assert is_over({**live, "updated": (now - timedelta(seconds=STALE_SECONDS + 1)).isoformat()}, now)
    assert is_over({"state": "running", "pid": os.getpid()}, now)  # never wrote a time


def test_speed_starts_with_the_counted_work(tmp_path):
    clock = [0.0]
    with JobStatus("run", "r1", folder=tmp_path, interval=60, clock=lambda: clock[0]) as status:
        clock[0] = 240.0  # 4 minutes of setup: loading tasks and systems
        status.total(10)
        clock[0] = 300.0
        status.advance(5)
        status.write()
        assert read(status)["rate"] == 5.0  # 5 in the 1 minute since total(), not in 5 minutes


def test_error_text_keeps_its_last_characters(tmp_path):
    with pytest.raises(RuntimeError):
        with JobStatus("run", "r1", folder=tmp_path, interval=60) as status:
            raise RuntimeError("cannot write to C:")
    assert read(status)["error"] == "RuntimeError: cannot write to C:"


def test_pid_alive():
    assert pid_alive(os.getpid())
    assert not pid_alive(0)


def test_default_folder_is_in_cmeval_home():
    with JobStatus("run", "r1", interval=60) as status:
        pass
    assert status.path.parent == status_dir() and status.path.exists()
