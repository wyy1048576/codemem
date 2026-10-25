"""`cmeval dashboard`: a local web page with the live progress of long jobs.

The page asks /api/jobs every 2 seconds. The answer comes from the status files in
CMEVAL_HOME/status/ (status.py). The server only reads: it has no route that writes, so it cannot
change a job. It listens on 127.0.0.1 only, so other machines cannot open it.

Routes:
    GET /                the page
    GET /dashboard.css   the style (eval-viz colors)
    GET /dashboard.js    the script
    GET /api/jobs        {"now", "folder", "running": [...], "recent": [...]}
"""

from __future__ import annotations

import json
import webbrowser
from collections.abc import Callable
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .paths import status_dir
from .status import STALE_SECONDS, is_over, read_all

DEFAULT_PORT = 8765
RECENT = 10  # finished, failed, or stopped jobs shown under the running ones
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
STATIC = Path(__file__).parent / "static"
FILES = {
    "/": ("dashboard.html", "text/html; charset=utf-8"),
    "/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
    "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
}


def job_view(job: dict, now: datetime) -> dict:
    """The job as the page shows it. A "running" job that is over (status.is_over: its process is
    gone, or it has not written for STALE_SECONDS) is shown as "stopped". The file is not changed."""
    view = dict(job)
    if job.get("state") == "running" and is_over(job, now):
        view["state"] = "stopped"
    return view


def jobs_payload(folder: Path | None = None, now: datetime | None = None) -> dict:
    """Running jobs (newest start first), then the RECENT newest of the others (newest end first)."""
    folder = folder or status_dir()
    now = now or datetime.now(timezone.utc)
    views = [job_view(job, now) for job in read_all(folder)]
    running = [v for v in views if v["state"] == "running"]
    others = [v for v in views if v["state"] != "running"]
    others.sort(key=lambda v: str(v.get("ended") or v.get("updated") or ""), reverse=True)
    return {"now": now.isoformat(timespec="seconds"), "folder": str(folder), "running": running, "recent": others[:RECENT]}


def make_server(port: int = DEFAULT_PORT, folder: Path | None = None) -> ThreadingHTTPServer:
    """A server on 127.0.0.1:port (port 0: any free port). Call serve_forever() on it."""
    folder = folder or status_dir()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the name http.server asks for
            # A web page on another site can point its own name at 127.0.0.1 (DNS rebinding) and then
            # read this server as if it were that site. The browser still sends that site's name in
            # Host, so only the local names are answered.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            if host not in LOCAL_HOSTS:
                self._send(403, "text/plain; charset=utf-8", b"forbidden: open the dashboard as 127.0.0.1 or localhost\n")
                return
            path = self.path.split("?", 1)[0]
            if path == "/api/jobs":
                body = json.dumps(jobs_payload(folder)).encode("utf-8")
                self._send(200, "application/json", body)
            elif path in FILES:
                name, kind = FILES[path]
                self._send(200, kind, (STATIC / name).read_bytes())
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found\n")

        def _send(self, code: int, kind: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - one line per request would flood the terminal
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port: int = DEFAULT_PORT, *, open_browser: bool = False,
          progress: Callable[[str], None] = lambda message: None) -> None:
    """Serve until Ctrl-C."""
    server = make_server(port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    progress(f"dashboard at {url} (status files in {status_dir()}); Ctrl-C to stop")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
