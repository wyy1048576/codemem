"""End-to-end runs: run Claude Code on a task in its container, record what it did, and grade it.

One run (run_one) has these steps:

  1. check the preconditions: the task's image and tests.json, the login token file, the Claude Code binary,
     and an internal Docker network
  2. write the prompt, the MCP config and the container script (agent.sh) to the run's folder
  3. start a recording proxy on the network's gateway, then the container. On the network the container
     reaches the proxy and nothing else. A thread follows the stream of events and stops the agent after
     the turn limit
  4. in the container, as root: remove files that would configure the agent, make a user that is not
     root, then start Claude Code as that user with the time limit. After it stops, save its changes as a
     patch
  5. read the stream, the proxy log and the clocks, check the setup, and grade the patch with e2e.grade
  6. write run.json

A run that hit a usage limit or failed the setup check is discarded: it is not graded, and a batch does it
again. A run that ended at the time or turn limit is graded like any other.

The login token goes to the container only through the environment of the docker client (docker run -e NAME
with no value). It is never written to a file or put on a command line. Before anything is read from the
run's folder, every file there is searched for the token, and a copy of it is replaced.

A batch (run_batch) does the runs of several tasks, setups and repetitions one at a time, and resumes: a run
with run.json is done, unless it was discarded. Files go to CMEVAL_HOME/e2e/runs/<run id>/<task id>/<setup>/<rep>/.

run.json has these fields:

  run_id, task_id, repo, recipe, setup, model, rep
  end                 finished, time limit, turn limit, usage limit or error (classify_end)
  completed           the grader's verdict; null for a discarded run
  discard, discard_reason, flags
                      a discarded run is done again; a flag (for example "cross-check disagrees") asks a person to look
  identity            prompt level, frame and hash, harness and its version, binary, image tag and id, split, cmeval
                      commit, machine, limits, start time (UTC), the task's gold files
  integrity           setup_ok and the failed checks, the init event's facts, proxy_complete, cross_check, the
                      network, the removed configuration files, the files where the token was found and replaced
  result_event        subtype, is_error, num_turns, duration_ms, duration_api_ms, total_cost_usd
  usage_limit         the evidence of a usage limit (429 answers and their reset headers, the result text), or null
  turn_limit          the turn at which the runner stopped the agent, and how, or null
  exit_code           the exit code of `timeout` around Claude Code (124 or 137: the time limit). The exit code of
                      the docker client is in integrity.docker_exit_code
  tokens              source (proxy, agent or proxy-partial), processed_tokens of that source, the proxy's sums,
                      the agent's sums, and the agent's modelUsage as it is
  proxy_errors        the errors of the proxy log
  time                agent_s (the run's time, from clock.txt), duration_ms and duration_api_ms, prep_s and each
                      preparation step, container_start_s, collect_s, container_s, grade_s
  steps               e2e_steps.count_steps (searches, views, edits, tests, turn marks, gold files, and each Bash
                      command), and num_turns_result from the result event. `cmeval e2e recount` computes it again
  outcome             completed, the grader's record, the patch's files and changed lines, status_lines
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .e2e import grade, patch_files
from .e2e_steps import TurnCounter, count_steps, parse_stream
from .files import write_json
from .generate import GenerateError, Recipe, _run, changed_lines, image_exists, task_tag, tests_path
from .paths import cmeval_home, e2e_dir
from .proxy import AGENT_CLASSES, DEFAULT_UPSTREAM, TOKEN_CLASSES, RecordingProxy, cross_check, read_log, summarize
from .status import NullStatus
from .tasks import Task, load_tasks

SCHEMA = 1
HARNESS = "claude-code"
NETWORK = "cmeval-run"
TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
TOKEN_FILE_ENV = "CMEVAL_CLAUDE_TOKEN_FILE"
BIN_ENV = "CMEVAL_CLAUDE_BIN"
DEFAULT_MODEL = "claude-haiku-5-5"
REDACTED = b"[REDACTED]"
MAX_ERRORS_IN_A_ROW = 3

# Exit codes of a batch.
EXIT_USAGE_LIMIT = 4
EXIT_ERRORS = 5

ENDS = ("finished", "time limit", "turn limit", "usage limit", "error")
# Paths in the checkout that would configure the agent, at the top level and in any folder.
CONFIG_PATHSPECS = (":(glob)**/.claude/**", ":(glob)**/CLAUDE.md", ":(glob)**/AGENTS.md", ":(glob)**/.mcp.json")
# Run as the agent user, this stops every process of that user. The tests replace it, so that it never runs
# on the machine of a developer.
KILL_AGENT = "kill -9 -1"

PROMPT_LEVEL = "L0"
PROMPT_FRAME = "v1"
FRAME_V1 = """\
The repository in the current directory has the issue below. Change the code of the repository so that the \
issue is resolved. Work on your own until you are done: nobody can answer questions.

<issue>
{query}
</issue>
"""


@dataclass(frozen=True)
class RunSettings:
    time_limit_s: int = 50 * 60
    turn_limit: int = 150
    cpus: float = 4
    memory: str = "16g"
    grade_cpus: int = 8
    effort: str = "medium"
    network: str = NETWORK
    kill_grace_s: int = 30
    # The host waits this much longer than the time limit, for the preparation and the patch.
    host_extra_s: int = 15 * 60
    poll_s: float = 0.5
    upstream: str = DEFAULT_UPSTREAM


# ---- setups

@dataclass(frozen=True)
class Setup:
    name: str
    mcp_config: dict | None  # None: not built yet
    mcp_servers: tuple[str, ...] = ()  # the servers that the init event must list, each "connected"
    checks: tuple[Callable[[dict], list[str]], ...] = ()  # more checks of the init event: failed checks

    @property
    def built(self) -> bool:
        return self.mcp_config is not None


SETUPS = {s.name: s for s in (
    Setup("grep", {"mcpServers": {}}),
    Setup("tool", None, ("codemem",)),
    Setup("upfront", None),
    Setup("placebo", None, ("codemem",)),
    Setup("tool-strong", None, ("codemem",)),
    Setup("grep-nosub", None),
    Setup("grep-map", None),
)}


def get_setup(name: str) -> Setup:
    if name not in SETUPS:
        raise GenerateError(f"setup {name}: no such setup (known: {', '.join(SETUPS)})")
    if not SETUPS[name].built:
        raise GenerateError(f"setup {name}: not built yet")
    return SETUPS[name]


def check_model(model: str) -> None:
    """Only a full model id. An alias can point at another model tomorrow (plan section 4.3)."""
    if not re.fullmatch(r"claude-[a-z]+-\d[\w.-]*", model) or model.endswith("-latest"):
        raise GenerateError(f"model {model}: give a full model id, for example {DEFAULT_MODEL}, not an alias")


def make_prompt(task: Task) -> str:
    """Prompt level L0 (the issue as written), in frame v1."""
    return FRAME_V1.format(query=task.query.strip())


# ---- preconditions

def token_file() -> Path:
    return Path(os.environ.get(TOKEN_FILE_ENV) or cmeval_home() / "secrets" / "claude-token")


def check_token_file(path: Path) -> None:
    if not path.is_file():
        raise GenerateError(f"no token file at {path}; make one with `claude setup-token` (or set {TOKEN_FILE_ENV})")
    if path.stat().st_mode & 0o077:
        raise GenerateError(f"token file {path} can be read by others; run chmod 600 {path}")


def read_token(path: Path) -> str:
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise GenerateError(f"token file {path} is empty")
    return token


def _is_linux_program(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(4) == b"\x7fELF"


def claude_bin() -> Path:
    """The Claude Code program that is mounted into the container. It must be a Linux program."""
    given = os.environ.get(BIN_ENV) or shutil.which("claude")
    if not given:
        raise GenerateError(f"no claude on PATH; install Claude Code or set {BIN_ENV}")
    path = Path(os.path.realpath(given))
    if not path.is_file():
        raise GenerateError(f"Claude Code binary {path} does not exist")
    if not _is_linux_program(path):
        raise GenerateError(f"{path} is not a Linux program (ELF); set {BIN_ENV} to the binary in "
                            "~/.local/share/claude/versions/")
    return path


def ensure_network(name: str = NETWORK) -> str:
    """Make the internal network if it does not exist. Returns its gateway address, where the proxy listens."""
    inspect = ["docker", "network", "inspect", name, "-f", "{{.Internal}} {{(index .IPAM.Config 0).Gateway}}"]
    proc = _run(inspect)
    if proc.returncode != 0:
        created = _run(["docker", "network", "create", "--internal", name])
        if created.returncode != 0:
            raise GenerateError(f"cannot make the Docker network {name}: {created.stderr.strip()}")
        proc = _run(inspect)
    parts = proc.stdout.split()
    if proc.returncode != 0 or not parts:
        raise GenerateError(f"cannot read the Docker network {name}: {proc.stderr.strip()}")
    if parts[0] != "true":
        raise GenerateError(f"the Docker network {name} is not internal; remove it (docker network rm {name})")
    if len(parts) < 2 or not re.fullmatch(r"[\d.]+", parts[1]):
        raise GenerateError(f"the Docker network {name} has no gateway address")
    return parts[1]


def preconditions(recipe: Recipe, task: Task, settings: RunSettings) -> dict:
    """Check what a run needs. Returns the image tag, the token file, the binary and the gateway."""
    tag = task_tag(recipe, task)
    if not image_exists(tag):
        raise GenerateError(f"{task.id}: image {tag} does not exist; build it with cmeval generate")
    if not tests_path(recipe, task).exists():
        raise GenerateError(f"{task.id}: no tests.json; validate the task with cmeval generate first")
    path = token_file()
    check_token_file(path)
    return {"tag": tag, "token_file": path, "claude_bin": claude_bin(), "gateway": ensure_network(settings.network)}


# ---- the container script

def agent_script(model: str, settings: RunSettings) -> str:
    """The shell script that runs in the task's container, as root. It reads and writes /out."""
    specs = " ".join(shlex.quote(p) for p in CONFIG_PATHSPECS)
    env = ("env -u ANTHROPIC_API_KEY HOME=/home/agent CLAUDE_CONFIG_DIR=/run/claude-empty "
           "CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 "
           f"CLAUDE_CODE_EFFORT_LEVEL={shlex.quote(settings.effort)} ENABLE_TOOL_SEARCH=false DISABLE_AUTOUPDATER=1")
    claude = (f'claude -p "$(cat /out/prompt.txt)" --model {shlex.quote(model)} --output-format stream-json --verbose '
              "--setting-sources user --strict-mcp-config --mcp-config /tmp/mcp.json --disable-slash-commands "
              "--no-session-persistence --exclude-dynamic-system-prompt-sections --permission-mode bypassPermissions "
              '--disallowedTools "WebSearch,WebFetch"')
    return (
        "# Written by cmeval. Runs in the task's container as root, and writes to /out.\n"
        # The files must be readable outside the container, also after a step fails.
        "trap 'chmod -R a+rwX /out' EXIT\n"
        'mark() { echo "$1 $(date +%s%N)" >> /out/prep.txt; }\n'
        "mark start\n"
        "cd /testbed || exit 2\n"
        # Files that would configure the agent. The removal is committed, so the agent's patch does not hold it.
        f"git ls-files -- {specs} > /out/removed.txt\n"
        "if [ -s /out/removed.txt ]; then\n"
        f"  git rm -rq --ignore-unmatch -- {specs} && git commit -qm 'cmeval: remove agent configuration'\n"
        "fi\n"
        "mark remove_config\n"
        "id -u agent > /dev/null 2>&1 || useradd -m agent\n"
        "chown -R agent:agent /testbed\n"
        "mark chown\n"
        "mkdir -p /run/claude-empty && chown agent /run/claude-empty\n"
        "cp /out/mcp.json /tmp/mcp.json && chmod 644 /tmp/mcp.json\n"
        "mark ready\n"
        # The run's time: from right before Claude Code starts to right after it ends.
        "s=$(date +%s%N)\n"
        f"timeout -k {settings.kill_grace_s} {settings.time_limit_s} runuser -u agent -- {env} {claude} "
        "> /out/stream.jsonl 2> /out/stderr.txt < /dev/null\n"
        "rc=$?\n"
        "e=$(date +%s%N)\n"
        "printf 'agent_start %s\\nagent_end %s\\nexit_code %s\\n' \"$s\" \"$e\" \"$rc\" > /out/clock.txt\n"
        # Stop what the agent left running, so that the working tree does not change while it is read.
        f"runuser -u agent -- bash -c '{KILL_AGENT}' > /dev/null 2>&1\n"
        "runuser -u agent -- git add -A > /out/git-add.log 2>&1\n"
        "runuser -u agent -- git diff --cached --binary HEAD > /out/agent.patch\n"
        'echo "status_lines $(runuser -u agent -- git status --short | wc -l)" > /out/after.txt\n'
        "mark collected\n"
    )


# ---- reading what a run left

def check_setup(init: dict | None, setup: Setup, model: str) -> list[str]:
    """The checks of the init event that fail. An empty list: the setup is what it should be."""
    if not init:
        return ["no init event"]
    failed = []
    servers = init.get("mcp_servers") or []
    names = sorted(s.get("name", "?") if isinstance(s, dict) else str(s) for s in servers)
    if names != sorted(setup.mcp_servers):
        failed.append(f"mcp_servers are {names}, expected {sorted(setup.mcp_servers)}")
    for s in servers:
        if isinstance(s, dict) and s.get("status") != "connected":
            failed.append(f"mcp server {s.get('name')} is {s.get('status')}")
    if init.get("permissionMode") != "bypassPermissions":
        failed.append(f"permissionMode is {init.get('permissionMode')}")
    if init.get("apiKeySource") != "none":
        failed.append(f"apiKeySource is {init.get('apiKeySource')}")
    if init.get("model") != model:
        failed.append(f"model is {init.get('model')}, expected {model}")
    web = sorted(set(init.get("tools") or []) & {"WebSearch", "WebFetch"})
    if web:
        failed.append(f"web tools are loaded: {', '.join(web)}")
    for check in setup.checks:
        failed += check(init)
    return failed


_USAGE_TEXT = re.compile(r"usage limit|limit reached|hit your limit|rate limit|resets? at", re.I)


def usage_limit_evidence(proxy_records: list[dict], result: dict | None) -> dict | None:
    """Signs of a usage limit: a 429 answer in the proxy log, or an error result whose text names a limit."""
    refused = [{k: r.get(k) for k in ("seq", "start", "status", "error", "rate_limit_headers")}
               for r in proxy_records if r.get("status") == 429]
    text = None
    if result and result.get("is_error") and _USAGE_TEXT.search(str(result.get("result") or "")):
        text = str(result.get("result"))[:500]
    if not refused and not text:
        return None
    headers = (refused[-1].get("rate_limit_headers") or {}) if refused else {}
    reset = {k: v for k, v in headers.items() if "reset" in k or k == "retry-after"}
    return {"proxy_429": refused[:5], "proxy_429_count": len(refused), "result_text": text, "reset": reset}


def reset_hint(evidence: dict | None) -> str:
    """The reset time from the rate-limit headers, for a person to read. Epoch seconds become UTC times."""
    parts = []
    for name, value in sorted(((evidence or {}).get("reset") or {}).items()):
        shown = str(value)
        if shown.isdigit() and len(shown) >= 9:
            shown += f" ({datetime.fromtimestamp(int(shown), timezone.utc):%Y-%m-%d %H:%M} UTC)"
        parts.append(f"{name}={shown}")
    return ", ".join(parts) or "no reset time in the headers"


def classify_end(result: dict | None, exit_code: int | None, *, agent_s: float | None, time_limit_s: float,
                 turn_limited: bool = False, usage_evidence: dict | None = None) -> str:
    """How the run ended: one of ENDS. `exit_code` is the exit code of `timeout` around Claude Code: 124 when
    the limit sent TERM, 137 when it had to send KILL as well."""
    if usage_evidence:
        return "usage limit"
    if turn_limited:
        return "turn limit"
    if exit_code == 124 or (exit_code == 137 and agent_s is not None and agent_s >= time_limit_s):
        return "time limit"
    if result and result.get("subtype") == "success" and not result.get("is_error") and exit_code == 0:
        return "finished"
    return "error"


def _lines(path: Path) -> list[list[str]]:
    return [line.split() for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def read_clock(out: Path) -> dict:
    """agent_start, agent_end (epoch ns) and exit_code from clock.txt; agent_s from the two times."""
    values = {p[0]: int(p[1]) for p in _lines(out / "clock.txt") if len(p) == 2 and p[1].lstrip("-").isdigit()}
    if "agent_start" in values and "agent_end" in values:
        values["agent_s"] = round((values["agent_end"] - values["agent_start"]) / 1e9, 3)
    return values


def read_prep(out: Path) -> dict:
    """The marks of prep.txt: seconds of each preparation step, and the seconds from start to ready. The mark
    "collected" comes after the agent; run_one times it from agent_end."""
    marks = [(p[0], int(p[1])) for p in _lines(out / "prep.txt") if len(p) == 2 and p[1].isdigit()]
    times = dict(marks)
    before = [m for m in marks if m[0] != "collected"]
    steps = {name: round((t - prev) / 1e9, 3) for (_, prev), (name, t) in zip(before, before[1:])}
    ready = round((times["ready"] - times["start"]) / 1e9, 3) if {"ready", "start"} <= set(times) else None
    return {"marks_ns": times, "steps_s": steps, "prep_s": ready}


def redact_secret(out: Path, secret: str) -> list[str]:
    """Replace each copy of the secret in the files of `out`. Returns the files that had one."""
    needle = secret.encode("utf-8")
    found = []
    for path in sorted(p for p in out.rglob("*") if p.is_file() and not p.is_symlink()):
        data = path.read_bytes()
        if needle in data:
            path.write_bytes(data.replace(needle, REDACTED))
            found.append(str(path.relative_to(out)))
    return found


def token_block(summary: dict | None, result: dict | None) -> dict:
    """Both token counts, and which one the run uses: the proxy when its log is complete, else the agent's
    modelUsage. When neither is whole (a run stopped at a limit has no result event), the proxy's partial sums."""
    usage = (result or {}).get("modelUsage") or None
    agent = None
    if usage:
        agent = {cls: sum(int(m.get(key) or 0) for m in usage.values() if isinstance(m, dict))
                 for cls, key in AGENT_CLASSES.items()}
        agent["processed_tokens"] = sum(agent[cls] for cls in TOKEN_CLASSES)
    proxy = None
    if summary:
        m = summary["messages"]
        proxy = {k: m[k] for k in (*TOKEN_CLASSES, "processed_tokens", "peak_context_tokens", "requests")}
    if summary and summary["proxy_complete"]:
        source, chosen = "proxy", proxy
    elif agent:
        source, chosen = "agent", agent
    else:
        source, chosen = ("proxy-partial", proxy) if proxy else (None, None)
    return {"source": source, "processed_tokens": chosen["processed_tokens"] if chosen else None,
            "proxy": proxy, "agent": agent, "agent_model_usage": usage}


def _cmeval_commit() -> str | None:
    root = Path(__file__).resolve().parents[2]
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "."], capture_output=True,
                               text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if head.returncode != 0:
        return None
    return head.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")


def _machine() -> dict:
    return {"hostname": socket.gethostname(), "platform": platform.platform(), "arch": platform.machine(),
            "cpu_count": os.cpu_count()}


# ---- one run

def _follow_stream(path: Path, counter: TurnCounter, limit: int, stop: threading.Event,
                   on_limit: Callable[[], None], poll: float) -> None:
    """Read new lines of the stream while the container runs. Call on_limit once when the main agent has
    more turns than the limit."""
    position, rest = 0, b""
    while not stop.wait(poll):
        if not path.exists():
            continue
        with open(path, "rb") as f:
            f.seek(position)
            data = f.read()
        position += len(data)
        lines = (rest + data).split(b"\n")
        rest = lines.pop()
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                counter.feed(event)
        if counter.turns > limit:
            on_limit()
            return


def run_dir(run_id: str, task_id: str, setup: str, rep: int) -> Path:
    return e2e_dir() / "runs" / run_id / task_id / setup / str(rep)


def run_one(recipe: Recipe, task: Task, *, setup: str, model: str, rep: int, out: Path,
            settings: RunSettings = RunSettings(), run_id: str | None = None) -> dict:
    """One run of Claude Code on one task. `out` is made again. Returns the record, also saved as run.json."""
    spec = get_setup(setup)
    check_model(model)
    ready = preconditions(recipe, task, settings)
    token = read_token(ready["token_file"])
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    out = out.resolve()
    prompt = make_prompt(task)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    (out / "mcp.json").write_text(json.dumps(spec.mcp_config) + "\n", encoding="utf-8")
    (out / "agent.sh").write_text(agent_script(model, settings), encoding="utf-8")
    image_id = _run(["docker", "image", "inspect", "-f", "{{.Id}}", ready["tag"]]).stdout.strip() or None
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    name = f"cmeval-run-{uuid.uuid4().hex[:12]}"
    counter, turn_limit = TurnCounter(), {}
    gateway = ready["gateway"]

    def stop_agent() -> None:
        # Stop the agent's processes, not the container, so that the script still saves the patch.
        proc = _run(["docker", "exec", "-u", "agent", name, "bash", "-c", KILL_AGENT])
        turn_limit.update(at_turn=counter.turns, how="docker exec kill")
        if proc.returncode not in (0, 1):  # 1: the kill found a process it could not signal
            _run(["docker", "kill", name])
            turn_limit["how"] = "docker kill"

    host_start_ns, host_timeout, docker_exit = time.time_ns(), False, None
    t0 = time.monotonic()
    try:
        with RecordingProxy(out / "proxy.jsonl", host=gateway, port=0, upstream=settings.upstream) as proxy:
            cmd = ["docker", "run", "--rm", "--name", name, "--network", settings.network,
                   f"--cpus={settings.cpus}", f"--memory={settings.memory}",
                   "-e", TOKEN_ENV, "-e", f"ANTHROPIC_BASE_URL=http://{gateway}:{proxy.port}",
                   "-v", f"{ready['claude_bin']}:/usr/local/bin/claude:ro", "-v", f"{out}:/out",
                   ready["tag"], "bash", "/out/agent.sh"]
            stop = threading.Event()
            watcher = threading.Thread(target=_follow_stream, name="cmeval-turns", daemon=True,
                                       args=(out / "stream.jsonl", counter, settings.turn_limit, stop, stop_agent,
                                             settings.poll_s))
            watcher.start()
            try:
                # The token is only in the environment of the docker client, which hands it to the container.
                docker_exit = _run(cmd, log=out / "docker.log", env={**os.environ, TOKEN_ENV: token},
                                   timeout=settings.time_limit_s + settings.kill_grace_s + settings.host_extra_s
                                   ).returncode
            except subprocess.TimeoutExpired:
                host_timeout = True
                _run(["docker", "rm", "-f", name])
            finally:
                stop.set()
                watcher.join()
    finally:
        _run(["docker", "rm", "-f", name])
    container_s = time.monotonic() - t0
    redacted = redact_secret(out, token)
    del token

    stream = parse_stream(out / "stream.jsonl")
    init, result = stream["init"], stream["result"]
    clock, prep = read_clock(out), read_prep(out)
    records = read_log(out / "proxy.jsonl")[0] if (out / "proxy.jsonl").exists() else []
    summary = summarize(out / "proxy.jsonl") if (out / "proxy.jsonl").exists() else None
    evidence = usage_limit_evidence(records, result)
    end = classify_end(result, clock.get("exit_code"), agent_s=clock.get("agent_s"),
                       time_limit_s=settings.time_limit_s, turn_limited=bool(turn_limit), usage_evidence=evidence)
    failed = check_setup(init, spec, model)
    usage = (result or {}).get("modelUsage")
    cross = cross_check(summary, usage) if summary and usage else None
    tokens = token_block(summary, result)
    removed = (out / "removed.txt").read_text(encoding="utf-8").splitlines() if (out / "removed.txt").exists() else []
    after = {p[0]: int(p[1]) for p in _lines(out / "after.txt") if len(p) == 2 and p[1].isdigit()}
    patch_path = out / "agent.patch"
    patch = patch_path.read_text(encoding="utf-8", errors="replace") if patch_path.exists() else ""

    discard = None
    if end == "usage limit":
        discard = "usage limit"
    elif failed:
        discard = "setup check failed: " + "; ".join(failed)
    graded, grade_s = None, None
    if discard is None:
        g0 = time.monotonic()
        try:
            graded = grade(recipe, task, patch, out / "grade", cpus=settings.grade_cpus)
        except (GenerateError, subprocess.TimeoutExpired, OSError) as exc:
            discard = f"grading failed: {exc}"
        grade_s = round(time.monotonic() - g0, 1)
    flags = []
    if cross is not None and not cross["agree"]:
        flags.append("cross-check disagrees")
    if summary and not summary["proxy_complete"] and end == "finished":
        flags.append("proxy log not complete")

    record = {
        "schema": SCHEMA,
        "run_id": run_id or out.parents[2].name,
        "task_id": task.id,
        "repo": task.repo,
        "recipe": recipe.name,
        "setup": setup,
        "model": model,
        "rep": rep,
        "end": end,
        "completed": graded["completed"] if graded else None,
        "discard": discard is not None,
        "discard_reason": discard,
        "flags": flags,
        "identity": {
            "prompt_level": PROMPT_LEVEL,
            "prompt_frame": PROMPT_FRAME,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "harness": HARNESS,
            "harness_version": (init or {}).get("claude_code_version"),
            "claude_bin": str(ready["claude_bin"]),
            "image": ready["tag"],
            "image_id": image_id,
            "split": task.split,
            "cmeval_commit": _cmeval_commit(),
            "machine": _machine(),
            "limits": {"turns": settings.turn_limit, "time_s": settings.time_limit_s, "cpus": settings.cpus,
                       "memory": settings.memory, "effort": settings.effort},
            "started_utc": started,
            "gold_files": list(task.gold.files),
        },
        "integrity": {
            "setup_ok": not failed,
            "setup_failures": failed,
            "init": {k: (init or {}).get(k) for k in ("model", "permissionMode", "apiKeySource", "mcp_servers",
                                                       "tools", "cwd")},
            "proxy_complete": summary["proxy_complete"] if summary else False,
            "cross_check": ({"agree": cross["agree"], "classes": cross["classes"]} if cross
                            else {"agree": None, "note": "no proxy log or no modelUsage in a result event"}),
            "network_internal": True,
            "network": settings.network,
            "removed_config_files": removed,
            "redacted_files": redacted,
            "stream_bad_lines": stream["bad_lines"],
            "host_timeout": host_timeout,
            "docker_exit_code": docker_exit,
        },
        "result_event": {k: (result or {}).get(k) for k in ("subtype", "is_error", "num_turns", "duration_ms",
                                                             "duration_api_ms", "total_cost_usd")},
        "usage_limit": evidence,
        "turn_limit": turn_limit or None,
        "exit_code": clock.get("exit_code"),
        "tokens": tokens,
        "proxy_errors": summary["errors"] if summary else None,
        "time": {
            "agent_s": clock.get("agent_s"),
            "duration_ms": (result or {}).get("duration_ms"),
            "duration_api_ms": (result or {}).get("duration_api_ms"),
            "prep_s": prep["prep_s"],
            "prep_steps_s": prep["steps_s"],
            # From the docker command to the first mark in the container. Both clocks are the host's on Linux.
            "container_start_s": (round((prep["marks_ns"]["start"] - host_start_ns) / 1e9, 3)
                                  if "start" in prep["marks_ns"] else None),
            "collect_s": (round((prep["marks_ns"]["collected"] - clock["agent_end"]) / 1e9, 3)
                          if "collected" in prep["marks_ns"] and "agent_end" in clock else None),
            "container_s": round(container_s, 1),
            "grade_s": grade_s,
        },
        "steps": count_steps(stream["events"], task.gold.files),
        "outcome": {
            "completed": graded["completed"] if graded else None,
            "grade": graded,
            "patch_files": len(patch_files(patch)),
            "patch_lines": changed_lines(patch),
            "status_lines": after.get("status_lines"),
        },
    }
    record["steps"]["num_turns_result"] = (result or {}).get("num_turns")
    write_json(out / "run.json", record)
    return record


# ---- counting the steps again

def _recount_values(steps: dict) -> tuple:
    """Content searches, files viewed, gold opened and first edit turn, from steps of any version."""
    if "searches" in steps:
        return (steps["searches"]["content"], len(steps["views"]["files_viewed"]), steps["gold_opened"],
                steps["first_edit_turn"])
    before = steps.get("turns_before_first_edit")  # version 1
    return (None, len(steps.get("files_read") or []), steps.get("gold_file_read"),
            before + 1 if before is not None else None)


def recount(run_id: str, tasks_file: Path | None = None, progress: Callable[[str], None] = print) -> int:
    """Compute `steps` of each run of a run id again from its stream.jsonl, with the rules of today, and write
    it into run.json. Nothing else in the record changes. The gold files come from the record (identity), or
    from the task file for records that do not have them. Returns the number of runs counted again."""
    root = e2e_dir() / "runs" / run_id
    if not root.is_dir():
        raise FileNotFoundError(f"no run folder {root}")
    gold_of = {t.id: t.gold.files for t in load_tasks(tasks_file)} if tasks_file else {}
    done = 0
    for path in sorted(p for p in root.glob("*/*/*/run.json") if p.parent.name.isdigit()):
        record = json.loads(path.read_text(encoding="utf-8"))
        where = f"{record.get('task_id')} {record.get('setup')} rep {record.get('rep')}"
        gold = record.get("identity", {}).get("gold_files")
        gold = gold if gold is not None else gold_of.get(record.get("task_id"))
        if gold is None:
            progress(f"{where}: no gold files in the record; give the task file with --tasks")
            continue
        if not (path.parent / "stream.jsonl").exists():
            progress(f"{where}: no stream.jsonl; not counted again")
            continue
        old = record.get("steps") or {}
        steps = count_steps(parse_stream(path.parent / "stream.jsonl")["events"], gold)
        steps["num_turns_result"] = old.get("num_turns_result", (record.get("result_event") or {}).get("num_turns"))
        record["steps"] = steps
        write_json(path, record)
        done += 1
        names = ("content searches", "files viewed", "gold opened", "first edit turn")
        pairs = zip(names, _recount_values(old), _recount_values(steps))
        progress(f"{where}: " + ", ".join(f"{name} {'-' if a is None else a} -> {'-' if b is None else b}"
                                          for name, a, b in pairs))
    return done


# ---- a batch

def plan_runs(tasks: list[Task], setups: list[str], reps: int) -> list[tuple[Task, str, int]]:
    """The order of a batch: all of repetition 1 before repetition 2 (plan section 3.3). Inside one task the
    setups take turns, and the setup that goes first moves by one at each repetition (plan 4.5, rule 8)."""
    order = []
    for rep in range(1, reps + 1):
        shift = (rep - 1) % len(setups)
        turn = setups[shift:] + setups[:shift]
        order += [(task, setup, rep) for task in tasks for setup in turn]
    return order


def run_state(out: Path) -> str:
    """done (run.json, not discarded), redo (discarded, or a folder without run.json), or todo."""
    path = out / "run.json"
    if path.exists():
        try:
            return "redo" if json.loads(path.read_text(encoding="utf-8")).get("discard") else "done"
        except ValueError:
            return "redo"
    return "redo" if out.exists() else "todo"


def set_aside(out: Path) -> Path:
    """Move a discarded or unfinished run folder to <rep>.discarded-<n> beside it. Nothing is deleted."""
    n = 1
    while (target := out.with_name(f"{out.name}.discarded-{n}")).exists():
        n += 1
    out.rename(target)
    return target


def format_run(record: dict) -> str:
    tokens = record["tokens"]["processed_tokens"]
    verdict = ("discard: " + record["discard_reason"] if record["discard"]
               else "flagged: " + ", ".join(record["flags"]) if record["flags"] else "ok")
    seconds = record["time"]["agent_s"]
    return (f"{record['task_id']} {record['setup']} rep {record['rep']}: {record['end']}, "
            f"completed {record['completed']}, {tokens if tokens is not None else '-'} tokens, "
            f"{seconds if seconds is not None else '-'} s, {verdict}")


@dataclass
class BatchResult:
    exit_code: int = 0
    done: int = 0
    skipped: int = 0
    discarded: int = 0
    message: str = ""
    records: list[dict] = field(default_factory=list)


def run_batch(recipe: Recipe, tasks: list[Task], *, run_id: str, setups: list[str], model: str, reps: int = 1,
              settings: RunSettings = RunSettings(), progress: Callable[[str], None] = lambda message: None,
              status=None) -> BatchResult:
    """The runs of a batch, one at a time, in the order of plan_runs. Stops at a usage limit (exit code 4)
    and after three runs in a row that ended in an error (exit code 5)."""
    status = status or NullStatus()
    order = plan_runs(tasks, setups, reps)
    status.total(len(order), "runs")
    batch = BatchResult()
    errors_in_a_row = 0
    for task, setup, rep in order:
        out = run_dir(run_id, task.id, setup, rep)
        state = run_state(out)
        if state == "done":
            batch.skipped += 1
            status.already_done(1)
            continue
        if state == "redo":
            progress(f"{task.id} {setup} rep {rep}: earlier attempt moved to {set_aside(out).name}")
        status.stage(f"{task.id} {setup} rep {rep}")
        record = run_one(recipe, task, setup=setup, model=model, rep=rep, out=out, settings=settings, run_id=run_id)
        batch.records.append(record)
        batch.done += 1
        batch.discarded += record["discard"]
        status.advance()
        progress(format_run(record))
        if record["end"] == "usage limit":
            batch.exit_code = EXIT_USAGE_LIMIT
            batch.message = f"usage limit; the batch stops. Reset: {reset_hint(record['usage_limit'])}"
            break
        errors_in_a_row = errors_in_a_row + 1 if record["end"] == "error" else 0
        if errors_in_a_row >= MAX_ERRORS_IN_A_ROW:
            batch.exit_code = EXIT_ERRORS
            batch.message = f"{MAX_ERRORS_IN_A_ROW} runs in a row ended in an error; the batch stops"
            break
    return batch
