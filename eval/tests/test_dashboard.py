import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from cmeval import dashboard
from cmeval.dashboard import jobs_payload, make_server

NOW = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


def write(folder, name, **fields):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps({"name": name, **fields}))


def at(seconds_ago):
    return (NOW - timedelta(seconds=seconds_ago)).isoformat()


@pytest.fixture
def dead_pid():
    proc = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    return int(proc.stdout)


def test_running_first_then_recent_by_end_time(tmp_path, dead_pid):
    me = os.getpid()
    write(tmp_path, "live", state="running", pid=me, started=at(100), updated=at(1))
    write(tmp_path, "old-done", state="done", pid=me, started=at(900), updated=at(800), ended=at(800))
    write(tmp_path, "new-failed", state="failed", pid=me, started=at(700), updated=at(10), ended=at(10))
    write(tmp_path, "killed", state="running", pid=dead_pid, started=at(600), updated=at(5))
    write(tmp_path, "silent", state="running", pid=me, started=at(500), updated=at(dashboard.STALE_SECONDS + 1))
    data = jobs_payload(tmp_path, now=NOW)
    assert [j["name"] for j in data["running"]] == ["live"]
    assert [(j["name"], j["state"]) for j in data["recent"]] == [
        ("killed", "stopped"), ("new-failed", "failed"), ("silent", "stopped"), ("old-done", "done")]
    assert data["folder"] == str(tmp_path)
    assert json.loads((tmp_path / "killed.json").read_text())["state"] == "running"  # the file is not changed


def test_recent_list_is_capped(tmp_path):
    for i in range(dashboard.RECENT + 3):
        write(tmp_path, f"job{i:02d}", state="done", pid=1, started=at(1000 - i), ended=at(500 - i))
    assert len(jobs_payload(tmp_path, now=NOW)["recent"]) == dashboard.RECENT


def test_no_status_folder_yet(tmp_path):
    assert jobs_payload(tmp_path / "missing", now=NOW)["running"] == []


@pytest.fixture
def server(tmp_path):
    server = make_server(0, folder=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", tmp_path
    server.shutdown()
    server.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.headers["Content-Type"], response.read()


def test_server_routes(server):
    url, folder = server
    write(folder, "r1", state="running", pid=os.getpid(), started=at(5), updated=datetime.now(timezone.utc).isoformat())
    status, kind, body = get(url + "/api/jobs")
    assert status == 200 and kind == "application/json" and json.loads(body)["running"][0]["name"] == "r1"
    for path, expected in (("/", "text/html"), ("/dashboard.css", "text/css"), ("/dashboard.js", "text/javascript")):
        status, kind, body = get(url + path)
        assert status == 200 and kind.startswith(expected) and body
    with pytest.raises(urllib.error.HTTPError) as info:
        get(url + "/../meta.json")
    assert info.value.code == 404


def test_server_has_no_route_that_writes(server):
    url, _ = server
    request = urllib.request.Request(url + "/api/jobs", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as info:
        urllib.request.urlopen(request, timeout=5)
    assert info.value.code == 501


def test_server_listens_on_localhost_only(tmp_path):
    server = make_server(0, folder=tmp_path)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()
