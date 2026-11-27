"""End-to-end runs: run Claude Code on a task in its container, record what it did, and grade it.

One run (run_one) has these steps:

  1. check the preconditions: the task's image and tests.json, the login token file, the Claude Code binary,
     and an internal Docker network. For a codemem setup also the codemem program, the task's index (from
     `cmeval e2e index`), the Hugging Face cache, and the GPU setting
  2. write the prompt, the MCP config and the container script (agent.sh) to the run's folder. For a codemem
     setup, copy the task's index to cmindex/ in the run's folder. The container gets it at /cmindex, and the
     copy is deleted after the run
  3. start a recording proxy on the network's gateway, then the container. On the network the container
     reaches the proxy and nothing else. A thread follows the stream of events and stops the agent after
     the turn limit
  4. in the container, as root: remove files that would configure the agent, make a user that is not
     root. For a codemem setup, start codemem's MCP server through the gate (codemem_gate.py) and wait until
     its model and search index are in memory and a search has no note. Then start Claude Code as that user
     with the time limit; its codemem server is the gate's bridge to that warm server. After it stops, save
     its changes as a patch
  5. read the stream, the proxy log and the clocks, check the setup, and grade the patch with e2e.grade
  6. write run.json

The wait for codemem happens before the agent's clock starts (mark codemem_warm in prep.txt), so it is not part
of the agent's time, and the setup grep has no such wait. Without it, the agent's first search often came while
the model was still loading, and codemem answered it from keywords only.

A run is discarded when it hit a usage limit or failed the setup check. The setup check reads the init event
of the stream (check_setup), and for a codemem setup also the gate's ready file and the first search_code
result (codemem_checks): a warm-up that failed, or a first search answered from keywords only, fails it. A
discarded run is not graded, and the next batch does it again. When the warm-up fails, Claude Code does not
start, and the run ends in an error: three of them in a row stop the batch. A run that ended at the time or
turn limit is graded like any other.

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
                      commit, machine, limits, start time (UTC), the task's gold files. codemem: null for a setup
                      without codemem; else the codemem commit, the program, the task's index.json, the steering
                      level, and the bytes of the index copy before and after the run
  integrity           setup_ok and the failed checks, the init event's facts, proxy_complete, cross_check, the
                      network, the removed configuration files, the files where the token was found and replaced,
                      gpus (the container had the GPU). codemem setups only, else null: codemem_warm (the gate's
                      ready file: ok, seconds, warmup_searches, the index_status answer, or the error) and
                      codemem_fallback_searches (e2e_steps.codemem_fallbacks: the search_code results with one
                      of codemem's notes, with their turns; `cmeval e2e recount` computes it again)
  result_event        subtype, is_error, num_turns, duration_ms, duration_api_ms, total_cost_usd
  usage_limit         the evidence of a usage limit (429 answers and their reset headers, the result text), or null
  turn_limit          the turn at which the runner stopped the agent, and how, or null
  exit_code           the exit code of `timeout` around Claude Code (124 or 137: the time limit). The exit code of
                      the docker client is in integrity.docker_exit_code
  tokens              source (proxy, agent or proxy-partial), processed_tokens of that source, the proxy's sums,
                      the agent's sums, and the agent's modelUsage as it is
  proxy_errors        the errors of the proxy log
  time                agent_s (the run's time, from clock.txt), duration_ms and duration_api_ms, prep_s and each
                      preparation step, codemem_warm_s (the wait for codemem, a part of prep_s; null without
                      codemem), container_start_s, collect_s, container_s, grade_s
  steps               e2e_steps.count_steps (searches, views, edits, tests, turn marks, gold files, and each Bash
                      command), and num_turns_result from the result event. `cmeval e2e recount` computes it again
  outcome             completed, the grader's record, the patch's files and changed lines, status_lines, and
                      unexpected_paths (files of the patch that codemem could have written, such as .codemem*)
"""

from __future__ import annotations

import fnmatch
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
from pathlib import Path, PurePosixPath
from typing import Callable

from . import codemem_gate
from .e2e import grade, patch_files
from .e2e_index import CODEMEM_ENV, codemem_bin, codemem_checkout, codemem_commit, codemem_python_root, hf_cache, \
    index_root, index_state, read_index_meta
from .e2e_steps import TurnCounter, codemem_fallbacks, count_steps, parse_stream
from .files import write_json
from .generate import NO_CORE_DUMPS, GenerateError, Recipe, _run, changed_lines, image_exists, task_tag, tests_path
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
GPUS_ENV = "CMEVAL_E2E_GPUS"
# How hard codemem's tool texts push the agent to codemem: none, light or strong. Not set = codemem's default.
STEERING_ENV = "CMEVAL_CODEMEM_STEERING"
STEERING_LEVELS = ("none", "light", "strong")
# For diagnostic batches only. Runs made with either of them are not comparable with other runs.
# Extra arguments for claude, for example "--thinking-display summarized" to get the thinking text in the stream.
DIAG_ARGS_ENV = "CMEVAL_E2E_DIAG_ARGS"
# 1 = the proxy also writes each request and answer body to bodies/ in the run folder.
BODIES_ENV = "CMEVAL_E2E_BODIES"
# Claude Code waits this long for an MCP server to start and for one tool call. codemem loads a model at start.
MCP_TIMEOUT_MS = 120_000
# Where the container of a codemem setup gets the index copy and the Hugging Face cache.
INDEX_MOUNT = "/cmindex"
# The GPU as a CDI device (nvidia-ctk cdi generate). Docker reads CDI specs without a restart of its daemon.
GPU_DEVICE = "nvidia.com/gpu=all"
HF_MOUNT = "/hf"
CODEMEM_SEARCH_TOOL = "mcp__codemem__search_code"
# The gate in the container (codemem_gate.py): its folder belongs to the agent's user, who runs the server.
GATE_DIR = "/tmp/cmgate"
GATE_SOCKET = f"{GATE_DIR}/codemem.sock"
# The longest wait for a warm codemem. A start reads the saved search index in seconds; a longer wait means
# that codemem builds or embeds again, and the run would not measure the codemem of the other runs.
GATE_TIMEOUT_S = 600
# Files of the run's folder that the gate writes (copied from GATE_DIR by agent.sh).
WARM_FILE = "codemem-warm.json"
GATE_LOGS = (f"cp {GATE_DIR}/gate.log /out/codemem-gate.log 2>/dev/null; "
             f"cp {GATE_DIR}/server.log /out/codemem-server.log 2>/dev/null")
# Files of the agent's patch that codemem could have written. `codemem mcp` should write none.
UNEXPECTED_PATTERNS = (".codemem*", ".mcp.json")

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
PROMPT_LEVELS = ("L0", "L1", "L2")
PROMPT_FRAME = "v1"
FRAME_V1 = """\
The repository in the current directory has the issue below. Change the code of the repository so that the \
issue is resolved. Work on your own until you are done: nobody can answer questions.

<issue>
{query}
</issue>
"""


def _gpus_default() -> bool:
    return os.environ.get(GPUS_ENV, "1") != "0"


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
    # The GPU for every setup, so that the containers of two setups are the same (plan 4.5, rule 1).
    gpus: bool = field(default_factory=_gpus_default)


# ---- setups

@dataclass(frozen=True)
class Setup:
    name: str
    mcp_config: dict | None  # None: not built yet, or made at run time (codemem)
    mcp_servers: tuple[str, ...] = ()  # the servers that the init event must list, each "connected"
    checks: tuple[Callable[[dict], list[str]], ...] = ()  # more checks of the init event: failed checks
    # codemem's MCP server. Its config holds paths of the host, so codemem_mcp_config makes it for each run.
    codemem: bool = False

    @property
    def built(self) -> bool:
        return self.mcp_config is not None or self.codemem


def _no_mcp_tools(init: dict) -> list[str]:
    tools = sorted(str(t) for t in init.get("tools") or [] if str(t).startswith("mcp__"))
    return [f"mcp tools are loaded: {', '.join(tools)}"] if tools else []


def _codemem_loaded(init: dict) -> list[str]:
    """mcp_servers must be a list of {name, status} objects (check_setup reads the names and the status), and
    the search tool of codemem must be loaded."""
    failed = []
    servers = init.get("mcp_servers")
    if not isinstance(servers, list) or not all(isinstance(s, dict) and isinstance(s.get("name"), str)
                                                and isinstance(s.get("status"), str) for s in servers):
        failed.append(f"mcp_servers is not a list of name and status objects: {json.dumps(servers)[:200]}")
    if CODEMEM_SEARCH_TOOL not in (init.get("tools") or []):
        failed.append(f"tool {CODEMEM_SEARCH_TOOL} is not loaded")
    return failed


SETUPS = {s.name: s for s in (
    Setup("grep", {"mcpServers": {}}, checks=(_no_mcp_tools,)),
    Setup("tool", None, ("codemem",), checks=(_codemem_loaded,), codemem=True),
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


@dataclass(frozen=True)
class PromptSet:
    """The prompt texts of one level. L0 is the issue as written and needs no texts. L1 and L2 are rewrites
    (plan section 9), read from a file with one JSON object per line: id, level, prompt."""
    level: str = PROMPT_LEVEL
    texts: dict = field(default_factory=dict)
    source: str | None = None
    sha256: str | None = None


def load_prompts(path: Path, level: str) -> PromptSet:
    """The texts of one level from a prompts file. Lines of other levels are skipped."""
    if level not in PROMPT_LEVELS or level == PROMPT_LEVEL:
        raise GenerateError(f"prompt level {level}: a prompts file holds {', '.join(PROMPT_LEVELS[1:])}")
    data = Path(path).read_bytes()
    texts = {}
    for number, line in enumerate(data.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            task_id, row_level, text = row["id"], row["level"], row["prompt"]
        except (ValueError, KeyError, TypeError) as exc:
            raise GenerateError(f"{path}, line {number}: not a prompt row (id, level, prompt): {exc}") from None
        if row_level != level:
            continue
        if not isinstance(text, str) or not text.strip():
            raise GenerateError(f"{path}, line {number}: empty prompt for {task_id}")
        if task_id in texts:
            raise GenerateError(f"{path}, line {number}: second {level} prompt for {task_id}")
        texts[task_id] = text
    return PromptSet(level=level, texts=texts, source=Path(path).name, sha256=hashlib.sha256(data).hexdigest())


def make_prompt(task: Task, prompts: PromptSet | None = None) -> str:
    """The task's text in frame v1: the issue as written (L0), or the rewrite of the prompt set's level."""
    if prompts is None or prompts.level == PROMPT_LEVEL:
        return FRAME_V1.format(query=task.query.strip())
    if task.id not in prompts.texts:
        raise GenerateError(f"{task.id}: no {prompts.level} prompt in {prompts.source}")
    return FRAME_V1.format(query=prompts.texts[task.id].strip())


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


def codemem_preconditions(recipe: Recipe, task: Task, settings: RunSettings) -> dict:
    """Check what codemem needs in the container. Returns the program, its checkout and Python install, the
    Hugging Face cache, the task's index folder and index.json, and the codemem commit."""
    hint = f"run cmeval e2e index {recipe.name} first"
    if not settings.gpus:
        raise GenerateError(f"a codemem setup needs the GPU in the container ({GPUS_ENV}=1): the index is tied to "
                            "the device that built it, and on the CPU codemem embeds the whole repo again")
    try:
        program = codemem_bin()
        python_root = codemem_python_root(program)
    except GenerateError as exc:
        raise GenerateError(f"{exc}; then {hint}") from None
    state = index_state(recipe, task)
    if state != "ok":
        where = index_root(recipe, task)
        raise GenerateError(f"{task.id}: no index for base commit {task.base_commit[:12]} in {where} "
                            f"({state}); {hint}")
    hf = hf_cache()
    if not hf.is_dir():
        raise GenerateError(f"no Hugging Face cache at {hf} (codemem's embedding model is there); {hint}, "
                            "which loads the model")
    checkout = codemem_checkout(program)
    return {"bin": program, "checkout": checkout, "python_root": python_root, "hf_cache": hf,
            "index": index_root(recipe, task) / "index", "meta": read_index_meta(recipe, task),
            "commit": codemem_commit(checkout)}


def preconditions(recipe: Recipe, task: Task, settings: RunSettings, setup: Setup | None = None) -> dict:
    """Check what a run needs. Returns the image tag, the token file, the binary, the gateway, and for a codemem
    setup what codemem_preconditions returns (else None)."""
    tag = task_tag(recipe, task)
    if not image_exists(tag):
        raise GenerateError(f"{task.id}: image {tag} does not exist; build it with cmeval generate")
    if not tests_path(recipe, task).exists():
        raise GenerateError(f"{task.id}: no tests.json; validate the task with cmeval generate first")
    codemem = codemem_preconditions(recipe, task, settings) if setup and setup.codemem else None
    path = token_file()
    check_token_file(path)
    return {"tag": tag, "token_file": path, "claude_bin": claude_bin(), "gateway": ensure_network(settings.network),
            "codemem": codemem}


# ---- codemem in the container

def codemem_mcp_config(codemem: dict, settings: RunSettings) -> dict:
    """The MCP config of a codemem setup. The server runs the host's codemem program on /testbed, with the index
    copy at /cmindex, the model from the Hugging Face cache, and no network."""
    # Python in a container sees all processors of the host, also with --cpus.
    threads = str(max(1, int(settings.cpus)))
    # The model stays in memory for the whole run: an idle unload is for a user's machine, and a run
    # must not differ by whether one fell into it. The search index is the one the build saved
    # (CODEMEM_ENV): under the container's memory limit codemem would pick another for a large index,
    # and rebuild it while the agent's first searches are answered from keywords.
    env = {"HF_HOME": HF_MOUNT, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
           "CODEMEM_HOME": "/home/agent/.codemem", "CODEMEM_MODEL_IDLE_MINUTES": "0", **CODEMEM_ENV,
           "OMP_NUM_THREADS": threads, "MKL_NUM_THREADS": threads}
    if steering := os.environ.get(STEERING_ENV):
        if steering not in STEERING_LEVELS:
            raise GenerateError(f"{STEERING_ENV} must be one of {', '.join(STEERING_LEVELS)}, not {steering!r}")
        env["CODEMEM_STEERING"] = steering
    return {"mcpServers": {"codemem": {"command": str(codemem["bin"]),
                                       "args": ["mcp", "/testbed", "--index-dir", INDEX_MOUNT],
                                       "env": env, "alwaysLoad": True}}}


def codemem_python(codemem: dict) -> str:
    """The Python of codemem's environment, at its path on the host (the container has it at the same path)."""
    return str(Path(codemem["bin"]).parent / "python")


def gate_config(codemem: dict, settings: RunSettings) -> dict:
    """The config of the gate's server (codemem_gate.serve): codemem's command and environment from
    codemem_mcp_config, and the gate's own files and limits."""
    server = codemem_mcp_config(codemem, settings)["mcpServers"]["codemem"]
    return {"argv": [server["command"], *server["args"]], "env": server["env"], "cwd": "/testbed",
            "socket": GATE_SOCKET, "ready_file": f"{GATE_DIR}/warm.json", "log": f"{GATE_DIR}/server.log",
            "timeout_s": GATE_TIMEOUT_S, "call_timeout_s": MCP_TIMEOUT_MS / 1000, "poll_s": 0.5,
            "accept_timeout_s": settings.time_limit_s}


def gated_mcp_config(codemem: dict, settings: RunSettings) -> dict:
    """The MCP config that Claude Code gets in a codemem setup: the gate's bridge to the warm server. The
    environment is the server's, the one that the gate gives codemem; the bridge itself does not use it. It
    stays here so that mcp.json shows what codemem got."""
    direct = codemem_mcp_config(codemem, settings)["mcpServers"]["codemem"]
    return {"mcpServers": {"codemem": {"command": codemem_python(codemem),
                                       "args": [f"{GATE_DIR}/cmgate.py", "connect", GATE_SOCKET],
                                       "env": direct["env"], "alwaysLoad": True}}}


def codemem_mounts(codemem: dict, index_copy: Path) -> list[str]:
    """The docker run arguments of a codemem setup. The checkout and the Python install keep their paths, so
    that the program's links and its editable install work."""
    mounts = [f"{codemem['checkout']}:{codemem['checkout']}:ro"]
    if codemem["python_root"]:
        mounts.append(f"{codemem['python_root']}:{codemem['python_root']}:ro")
    mounts += [f"{codemem['hf_cache']}:{HF_MOUNT}:ro", f"{index_copy}:{INDEX_MOUNT}"]
    return [part for mount in mounts for part in ("-v", mount)]


def copy_index(index: Path, target: Path) -> None:
    """A private copy of the task's index. Any user can write it: codemem runs as the agent's user and updates
    the index when the agent edits files."""
    shutil.copytree(index, target)
    for folder, dirs, files in os.walk(target):
        os.chmod(folder, 0o777)
        for name in files:
            path = os.path.join(folder, name)
            os.chmod(path, os.stat(path).st_mode | 0o666)


def tree_bytes(path: Path) -> int | None:
    """The bytes of the files in a folder. None when the folder does not exist."""
    if not path.is_dir():
        return None
    return sum(os.lstat(os.path.join(folder, name)).st_size for folder, _, files in os.walk(path) for name in files)


def remove_index_copy(path: Path, tag: str) -> bool:
    """Delete the index copy. True when it is gone."""
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        # When the container was killed, agent.sh did not open the files to all users. Folders that codemem made
        # as the agent's user can then only be removed as root.
        _run(["docker", "run", "--rm", "--network", "none", *NO_CORE_DUMPS, "-v", f"{path.parent}:/x", tag, "rm",
              "-rf", f"/x/{path.name}"])
        shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


def unexpected_paths(patch: str) -> list[str]:
    """Files of the patch that match UNEXPECTED_PATTERNS in any part of their path."""
    return sorted(p for p in patch_files(patch)
                  if any(fnmatch.fnmatch(part, pattern) for part in PurePosixPath(p).parts
                         for pattern in UNEXPECTED_PATTERNS))


# ---- the container script

def diagnostic_args() -> list[str]:
    """Extra arguments for claude, from the environment. Empty in a normal batch."""
    return shlex.split(os.environ.get(DIAG_ARGS_ENV, ""))


def keep_bodies() -> bool:
    return os.environ.get(BODIES_ENV, "0") == "1"


def gate_script(python: str) -> str:
    """The lines of agent.sh that start codemem through the gate and wait until it is warm. The gate runs as the
    agent's user, without the login token. When it is not warm, the script stops before Claude Code."""
    py = shlex.quote(python)
    return (
        f"mkdir -p {GATE_DIR} && cp /out/cmgate.py /out/cmgate.json {GATE_DIR}/ && "
        f"chmod 644 {GATE_DIR}/cmgate.py {GATE_DIR}/cmgate.json && chown agent {GATE_DIR}\n"
        f"runuser -u agent -- env -u {TOKEN_ENV} -u ANTHROPIC_BASE_URL HOME=/home/agent {py} {GATE_DIR}/cmgate.py "
        f"serve {GATE_DIR}/cmgate.json > {GATE_DIR}/gate.log 2>&1 < /dev/null &\n"
        "gate=$!\n"
        f'while [ ! -e {GATE_DIR}/warm.json ] && kill -0 "$gate" 2>/dev/null; do sleep 0.2; done\n'
        f"cp {GATE_DIR}/warm.json /out/{WARM_FILE} 2>/dev/null\n"
        "mark codemem_warm\n"
        f"if ! grep -q '\"ok\": true' /out/{WARM_FILE} 2>/dev/null; then\n"
        f"  {GATE_LOGS}\n"
        "  exit 3\n"
        "fi\n"
    )


def agent_script(model: str, settings: RunSettings, gate_python: str | None = None) -> str:
    """The shell script that runs in the task's container, as root. It reads and writes /out. With gate_python
    (a codemem setup), it starts codemem through the gate and waits for it before the agent's clock starts."""
    specs = " ".join(shlex.quote(p) for p in CONFIG_PATHSPECS)
    # MCP_TIMEOUT and MCP_TOOL_TIMEOUT are the same in every setup, so that the setups differ only in the server.
    env = ("env -u ANTHROPIC_API_KEY HOME=/home/agent CLAUDE_CONFIG_DIR=/run/claude-empty "
           "CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 "
           f"CLAUDE_CODE_EFFORT_LEVEL={shlex.quote(settings.effort)} ENABLE_TOOL_SEARCH=false DISABLE_AUTOUPDATER=1 "
           f"MCP_TIMEOUT={MCP_TIMEOUT_MS} MCP_TOOL_TIMEOUT={MCP_TIMEOUT_MS}")
    claude = (f'claude -p "$(cat /out/prompt.txt)" --model {shlex.quote(model)} --output-format stream-json --verbose '
              "--setting-sources user --strict-mcp-config --mcp-config /tmp/mcp.json --disable-slash-commands "
              "--no-session-persistence --exclude-dynamic-system-prompt-sections --permission-mode bypassPermissions "
              '--disallowedTools "WebSearch,WebFetch"')
    for arg in diagnostic_args():
        claude += " " + shlex.quote(arg)
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
        + (gate_script(gate_python) if gate_python else "") +
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
        + (GATE_LOGS + "\n" if gate_python else "") +
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


def read_warm(out: Path) -> dict | None:
    """The gate's ready file (codemem-warm.json), or None when there is none or it is not JSON."""
    try:
        data = json.loads((out / WARM_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def codemem_checks(warm: dict | None, fallbacks: dict) -> list[str]:
    """The checks of a codemem setup that fail: the gate was not warm, or the first search_code result came from
    keywords only. Either way the run did not test codemem's search."""
    failed = []
    if warm is None:
        failed.append(f"codemem warm-up: no {WARM_FILE}")
    elif not warm.get("ok"):
        failed.append(f"codemem warm-up failed: {warm.get('error')}")
    first = fallbacks.get("first")
    if fallbacks.get("first_keywords_only") and first:
        failed.append(f"the first search_code result (turn {first['turn']}) came from keywords only "
                      f"({', '.join(first['notes'])})")
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
            settings: RunSettings = RunSettings(), run_id: str | None = None,
            prompts: PromptSet | None = None) -> dict:
    """One run of Claude Code on one task. `out` is made again. Returns the record, also saved as run.json."""
    spec = get_setup(setup)
    check_model(model)
    ready = preconditions(recipe, task, settings, spec)
    codemem = ready["codemem"]
    token = read_token(ready["token_file"])
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    out = out.resolve()
    prompt = make_prompt(task, prompts)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    mcp_config = gated_mcp_config(codemem, settings) if codemem else spec.mcp_config
    (out / "mcp.json").write_text(json.dumps(mcp_config) + "\n", encoding="utf-8")
    if codemem:
        (out / "cmgate.py").write_bytes(Path(codemem_gate.__file__).read_bytes())
        write_json(out / "cmgate.json", gate_config(codemem, settings))
    (out / "agent.sh").write_text(agent_script(model, settings, codemem_python(codemem) if codemem else None),
                                  encoding="utf-8")
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
    index_copy, index_bytes, index_removed = out / "cmindex", {}, None
    t0 = time.monotonic()
    try:
        if codemem:
            copy_index(codemem["index"], index_copy)
            index_bytes["before"] = tree_bytes(index_copy)
        with RecordingProxy(out / "proxy.jsonl", host=gateway, port=0, upstream=settings.upstream,
                            bodies_dir=out / "bodies" if keep_bodies() else None) as proxy:
            cmd = ["docker", "run", "--rm", "--name", name, "--network", settings.network,
                   f"--cpus={settings.cpus}", f"--memory={settings.memory}", *NO_CORE_DUMPS,
                   *(["--device", GPU_DEVICE] if settings.gpus else []),
                   "-e", TOKEN_ENV, "-e", f"ANTHROPIC_BASE_URL=http://{gateway}:{proxy.port}",
                   "-v", f"{ready['claude_bin']}:/usr/local/bin/claude:ro", "-v", f"{out}:/out",
                   *(codemem_mounts(codemem, index_copy) if codemem else []),
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
        if codemem:
            # Keep only the numbers: a copy is about 300 MB.
            index_bytes["after"] = tree_bytes(index_copy)
            index_removed = remove_index_copy(index_copy, ready["tag"])
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
    warm = read_warm(out) if codemem else None
    fallbacks = codemem_fallbacks(stream["events"]) if codemem else None
    if codemem:
        failed += codemem_checks(warm, fallbacks)
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
            "prompt_level": prompts.level if prompts else PROMPT_LEVEL,
            "prompt_source": {"file": prompts.source, "sha256": prompts.sha256} if prompts and prompts.source else None,
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
            "diagnostic": {"claude_args": diagnostic_args(), "bodies": keep_bodies()},
            "gold_files": list(task.gold.files),
            "codemem": {
                "commit": codemem["commit"],
                "bin": str(codemem["bin"]),
                "index": codemem["meta"],
                "steering": mcp_config["mcpServers"]["codemem"]["env"].get("CODEMEM_STEERING", "default"),
                "index_bytes_before": index_bytes.get("before"),
                "index_bytes_after": index_bytes.get("after"),
                "index_copy_removed": index_removed,
            } if codemem else None,
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
            "gpus": settings.gpus,
            "codemem_warm": warm,
            "codemem_fallback_searches": fallbacks,
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
            "codemem_warm_s": prep["steps_s"].get("codemem_warm"),
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
            "unexpected_paths": unexpected_paths(patch),
        },
    }
    record["steps"]["num_turns_result"] = (result or {}).get("num_turns")
    write_json(out / "run.json", record)
    return record


# ---- counting the steps again

def _recount_values(steps: dict) -> tuple:
    """Content searches, files viewed, gold opened, first edit turn, first gold surfaced turn and the steps
    version, from steps of any version."""
    if "searches" in steps:
        return (steps["searches"]["content"], len(steps["views"]["files_viewed"]), steps["gold_opened"],
                steps["first_edit_turn"], steps.get("first_gold_surfaced_turn"), steps.get("steps_version"))
    before = steps.get("turns_before_first_edit")  # version 1
    return (None, len(steps.get("files_read") or []), steps.get("gold_file_read"),
            before + 1 if before is not None else None, None, steps.get("steps_version"))


def _fallback_value(fallbacks: dict | None) -> str | None:
    """The fallback searches of a run for a line of recount: "2 of 5", and "first" when the first one came from
    keywords only."""
    if not fallbacks:
        return None
    text = f"{fallbacks['fell_back']} of {fallbacks['searches']}"
    return text + (" (first from keywords)" if fallbacks.get("first_keywords_only") else "")


def recount(run_id: str, tasks_file: Path | None = None, progress: Callable[[str], None] = print) -> int:
    """Compute `steps` of each run of a run id again from its stream.jsonl, with the rules of today, and write
    it into run.json. For a codemem setup also integrity.codemem_fallback_searches. Nothing else in the record
    changes: a run is not discarded after the fact. The gold files come from the record (identity), or
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
        events = parse_stream(path.parent / "stream.jsonl")["events"]
        steps = count_steps(events, gold)
        steps["num_turns_result"] = old.get("num_turns_result", (record.get("result_event") or {}).get("num_turns"))
        record["steps"] = steps
        fallbacks, old_fallbacks = None, None
        if (record.get("identity") or {}).get("codemem"):
            integrity = record.setdefault("integrity", {})
            old_fallbacks = integrity.get("codemem_fallback_searches")
            fallbacks = integrity["codemem_fallback_searches"] = codemem_fallbacks(events)
        write_json(path, record)
        done += 1
        names = ("content searches", "files viewed", "gold opened", "first edit turn", "first gold surfaced turn",
                 "steps version")
        pairs = list(zip(names, _recount_values(old), _recount_values(steps)))
        if fallbacks is not None:
            pairs.append(("codemem fallback searches", _fallback_value(old_fallbacks), _fallback_value(fallbacks)))
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
              status=None, prompts: PromptSet | None = None) -> BatchResult:
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
        record = run_one(recipe, task, setup=setup, model=model, rep=rep, out=out, settings=settings, run_id=run_id,
                         prompts=prompts)
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
