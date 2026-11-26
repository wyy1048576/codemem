# For track A's agents: how to run track C's codemem in the runs. One commit, two settings the runner sets by itself, every index built once more, a pause before the agent's first prompt, and what to look at in a run

- **Track:** shared: from track C, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 14:17 UTC
- **Work package:** none: track C (C2, C4, C5) handed to the runs
- **Branch, commits, pull request:** the tag `codemem-final` on `main`, cut at the lock (Fri Nov 27, noon Pacific); `main` until then. On `main` today: #51 (the defaults) and #52 (point 2). One pull request is still to merge: `andre/audit-fixes` (`21dcce1`). This entry describes `main` with it

## Done

**In short.** You run codemem as before: `cmeval e2e index`, then `cmeval e2e run`. Three things
are new. There is one commit to run (point 1). The runner gives codemem two settings by itself
(point 2). And every index is built once more before the first run on it (point 3). Points 4 to
6 say what must stay fixed and what to look at. You set no codemem option yourself.

**1. Which codemem to run.**

```bash
cd <the codemem checkout on the PC>
git fetch origin --tags
git checkout codemem-final      # before the tag exists: git checkout origin/main
uv sync                         # makes .venv/bin/codemem, the program the runner mounts into every container
uv run python -c "import faiss; print(faiss.__version__)"      # must print 1.16.0
git rev-parse HEAD              # every index.json and every run.json must name this commit
```

If `uv sync` fails, post the error and stop.

**2. What the runner pins, and why.** The runner puts two variables into codemem's environment.

| Variable | Where the runner sets it | What it does |
|---|---|---|
| `CODEMEM_VECTOR_BACKEND=faiss` | the build of an index (`cmeval e2e index`) and the server of every run | the exact search index, in both places |
| `CODEMEM_MODEL_IDLE_MINUTES=0` | the server of every run | the embedding model stays in memory for the whole run |

**Why the first.** Left to itself, codemem picks its search index by the memory of the place it
runs in: the exact index while that fits 2% of the memory, a compact one beyond. The build runs
on the host. A run is in a container with 16 GB.

- Take an index of 300,000 vectors. On the PC the build saves the exact index. In the container
  codemem picks the compact one (it does above 185,000 vectors), cannot use what the build saved,
  and builds the search index again at the start of every run.
- Until that is done, every `search_code` call is answered from keywords only.
- Measured on an index of 100,000 vectors: 5 s, and the searches asked in that time came back
  with keyword results and the note of point 5a. With the variable, the same start read the saved
  index in 0.5 s, and the first search had results by meaning.
- So without it the large repos, and only they, would run with a weaker codemem in the agent's
  first turns, which is when it searches.

**Why the second.** By default codemem frees its model after 60 minutes without a search. A run
must not differ by whether that fell into it.

**Two things the runner does not pin.** Check them once, on the machine that builds the indexes:

```bash
cat ~/.codemem/config.toml     # nothing but the cache's cap of point 3: a build reads this file, a run in a container does not
env | grep '^CODEMEM_'         # nothing, or CODEMEM_HOME only: a build gets the shell's variables, a run does not
```

**3. The indexes and the cache you have.** Build every index once more with the final commit,
before the first run on it:

```bash
cmeval e2e index <recipe> --tasks <task file>      # for every recipe
```

- **It builds again by itself,** because the codemem commit changed. No `--force`.
- **It is fast.** The vectors come from the vector cache in `~/.codemem/cache`, so the model has
  little to embed. Do not delete that folder. The first build moves the cache of the older
  codemem (`vectors.db`) into a new file (`vector_cache.db`) and says so in its log: "importing N
  vectors ... this happens once".
- **Raise the cache's cap for the run days.** The cache keeps at most 8 GB, about 4.2 million
  vectors, and then drops what was used longest ago. Ten repos at several commits each can
  reach that, and a later build would then embed again. On the machine that builds the indexes,
  put one line into `~/.codemem/config.toml`: `vector_cache_max_gb = 0` (no cap). It is the one
  setting that file should hold (point 2): it does not change what an index stores.
- **Why not keep the old indexes.** An index of the older codemem (`041124e`, `9dfe3fe`) still
  opens: nothing is chunked or embedded again. But its saved search index is not read, so every
  run would build it again at its start, and the index would be from another commit than the run.
- **If an older codemem must still build indexes on that machine** (`codemem-today`), give it a
  home of its own, before the first build with the final commit and while no codemem runs:
  `mkdir -p ~/.codemem-today/cache && cp ~/.codemem/cache/vectors.db* ~/.codemem-today/cache/`.
  Then set `CODEMEM_HOME=~/.codemem-today` for every command of the older codemem. Otherwise it
  loses its cache: it keeps it in `vectors.db`, and the new codemem deletes that file after it
  has moved the vectors.

Then check that every index is ready. Run this in the codemem checkout:

```bash
python3 - <<'EOF'
import json, os, pathlib, subprocess

head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
root = pathlib.Path(os.environ.get("CMEVAL_HOME") or pathlib.Path.home() / ".cmeval") / "e2e" / "indexes"
for meta in sorted(root.glob("*/*/index.json")):
    wrong = []
    if json.loads(meta.read_text()).get("codemem_commit") != head:
        wrong.append("built by another codemem commit")
    notes = [json.loads(p.read_text()) for p in sorted((meta.parent / "index").glob("vec_*.json"))]
    if not notes or any(n.get("backend") != "faiss" for n in notes):
        wrong.append("its saved search index is not the exact one")
    print(meta.parent.relative_to(root), "ready" if not wrong else "NOT READY: " + "; ".join(wrong))
EOF
```

Every line must end in `ready`. `cmeval e2e run` does not check this: it takes any index of the
right base commit.

**4. What must not change once the runs have started.**

- The codemem commit, its environment (`uv.lock`: FAISS, PyTorch) and the indexes. If one of
  them changes, build the indexes again and use a new run ID.
- The container's limits (`--memory=16g`, `--cpus=4`, in `RunSettings`) and the GPU in the
  container (`CMEVAL_E2E_GPUS` not 0). On the CPU codemem embeds the whole repo again.
- The two variables of point 2, and the two checks below them.
- The steering level (`CMEVAL_CODEMEM_STEERING`): one per run ID.

**5. What to look at in a run's records.** Run these in the folder of a run ID:

```bash
cd "${CMEVAL_HOME:-$HOME/.cmeval}/e2e/runs/<run id>"
```

**a. A search that fell back to keywords.** codemem then ends the result with one of two notes.
Both hold the words "keyword matching only":

- `Note: codemem is still loading its embedding model or its search index (the first searches after it starts); these results come from keyword matching only.`
- `Note: codemem cannot embed right now (<the reason>), so these results come from keyword matching only.`

```bash
grep -l "keyword matching only" */*/*/stream.jsonl       # the runs that have one
```

With the pins, the case to expect is a search in the first seconds of a run, while the model
loads. The check run counts those: point 4 of the run plan's §6, "every search is a search by
meaning", is this count. A note in a later turn, or in most runs of one repo, is a finding:
post it.

**b. The settings a run's server got.**

```bash
grep -o '"CODEMEM_[A-Z_]*": "[^"]*"' <task id>/tool/1/mcp.json
# "CODEMEM_HOME": "/home/agent/.codemem"   "CODEMEM_MODEL_IDLE_MINUTES": "0"   "CODEMEM_VECTOR_BACKEND": "faiss"
```

**c. The index a run started from.** `run.json` has the commit that built the index, the commit
the run used, and the size of the index copy before and after the run. The two commits must be
equal. The two sizes must be close: a copy that shrank by a tenth or more is most likely a run
that built its search index again in the compact form, whose files are a third of the exact
ones. The same check tells whether a run made before the pin was hit.

```bash
python3 - <<'EOF'
import json, pathlib

for path in sorted(pathlib.Path(".").glob("*/*/*/run.json")):
    c = (json.loads(path.read_text()).get("identity") or {}).get("codemem")
    if not c:
        continue
    built, before, after = (c.get("index") or {}).get("codemem_commit"), c.get("index_bytes_before"), c.get("index_bytes_after")
    flags = []
    if built != c.get("commit"):
        flags.append(f"the index was built by codemem {built}, the run used {c.get('commit')}")
    if before and after and abs(after - before) > 0.1 * before:
        flags.append(f"the index copy went from {before:,} to {after:,} bytes")
    if flags:
        print(path.parent, "; ".join(flags))
EOF
```

It prints nothing when all is well.

**d. The watcher.** codemem follows the agent's edits through file events. A run shows this only
where the agent called `index_status`: the answer then has the line `watching for changes`. The
line `not watching (scanning on a timer or on request)` means that file events do
not work in that container. codemem then checks every file of the repo every 10 s and before
each search, which costs the `tool` setup time. Point 6 asks for the status where no agent did.

```bash
grep -l "not watching" */*/*/stream.jsonl       # must find nothing
```

**e. The search index and the model,** in the same `index_status` answer: the lines
`search index: exact (faiss)`, below it `vector_backend = "faiss"`, and `embedding model: in memory`.

**6. Once per repo, before its batch: look at a start.** This starts codemem in a task's
container exactly as a run does (the image, the limits, the GPU, the mounts and the environment
are the runner's own), with no agent and no model call:

```bash
cd eval && uv run python ../scripts/check_run_start.py <recipe> --tasks <task file>
```

The script is on `main` since #52. Its docker command has not run anywhere yet (the Mac it was
written on cannot run Docker): `--print` prints the command and stops, and if it fails, post the
error.

It prints how many seconds after the start a search first has results by meaning, then the
status, then three lines that must say `ok`: `watching for changes`, `embedding model: in
memory`, `search index: exact (faiss)`. Post the seconds per repo: they say how long a run's
first searches can be from keywords only, on the PC.

Do it for every large repo too (vscode, home-assistant, kubernetes, trino), before its batch.
The check run is on pandas and one more small repo. Their indexes are small (pandas: 49,770
vectors), so it cannot show what a large index does at a start.

**7. The model's load at the start of a run: yours to handle in the runner** (Andre's decision
of Nov 26). codemem loads its embedding model when its server starts, about 7 s on the PC. A
`search_code` call that arrives in that time waits 4 s and is then answered from keywords, with
the first note of point 5a. That rule stays: a person has not typed a request by then, and an
agent that gets the note goes on with grep. In a run it matters, because the agent starts at
once and, so far, calls codemem once, in its first turn. If that call is the keyword one, the
run did not test codemem: in the pilot it was 1 call of 4.

- **Know how long it is.** The script of point 6 prints the seconds after which a search first
  has results by meaning, on the PC, per repo.
- **Do not let a run's first prompt come earlier.** How is yours to choose, as long as it is the
  same in both setups: for example hold the agent's start for those seconds in `grep` and in
  `tool` alike, and leave the wait out of the run's time.
- **Count what still slips through.** A `tool` run whose `search_code` result has the note (the
  `grep` of point 5a) did not search by meaning. In the check run there must be none. In a
  batch, run such a run again and say how many there were.

## Checked

- On an M1, without Docker. A container's memory limit was given to codemem through a cgroup
  file, the way it reads one on Linux.
- An index of 100,000 vectors (80,000 code, 20,000 usage), built with all the machine's memory
  and opened under a limit where codemem picks the compact index: the search index was ready
  after 5.0 s with FAISS on 4 threads, as in a run's container, and after 12.8 s on one. The
  searches asked 0.3 s and 4 s after the start were from keywords only; the one at 8 s was not.
  With the variable: ready after 0.5 s, the first search by meaning, nothing built again.
- An index built by `041124e` (the tests' sample repo, a stand-in model), opened by this code:
  no file chunked again, no text embedded again, the search index built again from the stored
  vectors. A new build beside it found all 33 of its vectors in the older cache.
- Tests: `tests/test_auto_index.py`, 15 pass, also with the suite forced onto each search index;
  with four neighbouring files, 113 pass; `eval/tests/test_e2e_run.py`, 36 pass. Both files
  also pass on a merge of this change with the two audit branches and `main` at `25d324f`.
- **Not checked:** Linux, x86, Docker, the GPU, the real model, the files the PC keeps a
  container's memory limit in, the watcher in a container, the script of point 6 inside a
  container. Point 6 is how these get checked on the PC.

## Left

- The pull request of `andre/audit-fixes` (Andre), then the tag.
- The eval's own lock file (`eval/uv.lock`) still has FAISS 1.15.1, while codemem's has 1.16.0.
  A run uses codemem's environment, so the runs are on 1.16.0. Only tests and the retrieval eval
  that import codemem into the eval's environment use 1.15.1. Both give the same results; the
  lock can follow after the runs.

## Blocked on, or needed from others

- **Andrew:** the four runs of the entry of 2026-11-26 11:32. Track C still owes their results.
  Two of them come before the first batch:
  - run 1, codemem's tests on Linux: nobody has run this code there;
  - run 2, the vectors per repo: the exact index takes 1,856 bytes a vector in the container,
    0.56 GB at 300,000 vectors and 1.9 GB at a million.

  Runs 3 and 4 measure the compact index. The evaluation no longer uses it, so they do not hold
  up a batch. Andre's decisions still wait for them.
- **Andrew:** a look at the change in `eval/src/cmeval/e2e_index.py` and `e2e_run.py`: one
  constant, used in two places.

## Next

- Track A: points 1 to 3 on the PC, point 6 for the first two repos, point 7, then the check run.
- Track C: reads the seconds of point 6 and the count of point 5a here, and answers in the log.
