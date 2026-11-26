"""Start codemem in a task's container the way a run does, with no agent, and print what the start
looks like there: how long searches answer from keywords only, the search index in use, whether
the watcher runs, whether the model is in memory (preflight.py, beside this file, runs in the
container). The image, the limits, the GPU, the mounts and codemem's environment are the runner's
own (cmeval.e2e_run), so this cannot drift from what a run gets.

usage, in eval/:  uv run python <this file> RECIPE --tasks FILE [--id TASK_ID] [--print]
  --print   print the docker command and stop
"""
import argparse
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from cmeval import e2e_run
from cmeval import generate as gen
from cmeval.tasks import load_tasks

parser = argparse.ArgumentParser()
parser.add_argument("recipe")
parser.add_argument("--tasks", type=Path, required=True)
parser.add_argument("--id")
parser.add_argument("--print", action="store_true", dest="only_print")
args = parser.parse_args()

recipe = gen.load_recipe(args.recipe)
tasks = [t for t in load_tasks(args.tasks)
         if t.repo == recipe.repo and gen.tests_path(recipe, t).exists() and args.id in (None, t.id)]
if not tasks:
    sys.exit(f"no valid task of {recipe.repo} in {args.tasks}" + (f" with the id {args.id}" if args.id else ""))
task, settings = tasks[0], e2e_run.RunSettings()
codemem = e2e_run.codemem_preconditions(recipe, task, settings)  # the program, the index, the model cache, the GPU
env = e2e_run.codemem_mcp_config(codemem, settings)["mcpServers"]["codemem"]["env"]
# A private copy of the index, as a run gets; with --print only its place is named.
work = Path(tempfile.gettempdir()) / "cmeval-start-check" if args.only_print else Path(tempfile.mkdtemp(prefix="cmeval-start-check-"))
copy = work / "cmindex"
tag = gen.task_tag(recipe, task)
cmd = ["docker", "run", "--rm", "--network", "none", f"--cpus={settings.cpus}", f"--memory={settings.memory}",
       *(["--device", e2e_run.GPU_DEVICE] if settings.gpus else []),
       *e2e_run.codemem_mounts(codemem, copy), "-v", f"{Path(__file__).resolve().with_name('preflight.py')}:/preflight.py:ro",
       *[part for key, value in env.items() for part in ("-e", f"{key}={value}")],
       tag, str(codemem["bin"].parent / "python"), "/preflight.py", "/testbed", e2e_run.INDEX_MOUNT]
print(f"{task.id}: index built by codemem {codemem['meta'].get('codemem_commit')}, program at {codemem['commit']}", file=sys.stderr)
print(shlex.join(cmd), file=sys.stderr)
if args.only_print:
    sys.exit(0)
e2e_run.copy_index(codemem["index"], copy)
try:
    code = subprocess.run(cmd).returncode
finally:
    e2e_run.remove_index_copy(copy, tag)
    if not any(work.iterdir()):
        work.rmdir()
sys.exit(code)
