"""Hold the MCP handshake until codemem's embedding model has loaded, then relay stdio unchanged.

The agent sends its first model request right after the MCP handshake, and codemem loads its
embedding model at start (about 14 s on this Mac). A search sent before that is answered from
keywords. The eval's runs hold the agent until the model is loaded; this wrapper does the same.
It starts the server at once, leaves the agent's first message waiting in the pipe until the
server's log shows the model loaded (plus a margin), and then passes bytes both ways untouched.

usage: mcp_hold.py <log file> <margin s> <max wait s> -- <server command ...>
"""
import os
import re
import signal
import subprocess
import sys
import threading
import time

MARKER = re.compile(r"Loaded \d+ prompts with these keys")


def main() -> int:
    sep = sys.argv.index("--")
    log_path, margin, limit = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    cmd = sys.argv[sep + 1:]
    t0 = time.monotonic()
    log = open(log_path, "a", buffering=1, encoding="utf-8")

    def note(text: str) -> None:
        log.write("[hold %.2f] %s\n" % (time.monotonic() - t0, text))

    child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    note("server pid %d" % child.pid)
    loaded = threading.Event()
    stopping = threading.Event()

    def read_stderr() -> None:
        for raw in iter(child.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\n")
            log.write("%.2f %s\n" % (time.monotonic() - t0, line))
            if MARKER.search(line):
                loaded.set()

    threading.Thread(target=read_stderr, daemon=True).start()

    def stop(signum, frame) -> None:
        note("signal %d: stopping the server" % signum)
        stopping.set()
        loaded.set()
        try:
            child.terminate()
        except OSError:
            pass

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    seen = loaded.wait(limit) and not stopping.is_set()
    note("model marker %s" % ("seen" if seen else "NOT seen (limit %.0f s, or stopped)" % limit))
    if seen:
        time.sleep(margin)
    note("handshake released")

    def pump(src: int, dst: int, close_dst: bool) -> None:
        try:
            while True:
                data = os.read(src, 65536)
                if not data:
                    break
                view = memoryview(data)
                while view:
                    view = view[os.write(dst, view):]
        except OSError:
            pass
        finally:
            if close_dst:
                try:
                    os.close(dst)
                except OSError:
                    pass

    threading.Thread(target=pump, args=(0, child.stdin.fileno(), True), daemon=True).start()
    out = threading.Thread(target=pump, args=(child.stdout.fileno(), 1, False), daemon=True)
    out.start()
    code = child.wait()
    out.join(timeout=5)
    note("server exited with %s" % code)
    log.close()
    os._exit(0 if code is None else max(code, 0))


if __name__ == "__main__":
    main()
