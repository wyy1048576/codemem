# Track C's reply to "an index is tied to the device", and two branches finished (not merged)

- **Track:** C. The first part answers track A's entry of 2026-11-25 11:34
- **Who:** Andre, with Claude Code
- **When:** 2026-11-25 12:36 UTC
- **Work package:** part of C5 and C8
- **Branch, commits, pull request:** local branches, not pushed yet: `andre/embedding-endpoints`
  (`4b604b8`, 8 commits) and `andre/model-idle-unload` (`b680377`, 8 commits, follow-ups in
  progress). Each becomes a pull request

## Done

**1. Why an index is tied to its device, and what exists for it.**

- It is by design. The embedder's key names the model, the longest text, the precision and the
  device, so that two vectors under one key are the same numbers. A GPU in the container, as
  track A does it, is a correct way to keep the key equal.
- **A second way is finished on a branch:** `codemem serve-embeddings`. One model runs on the
  host, behind an OpenAI-style endpoint. Each container's codemem reaches it with
  `[embedding] provider = "openai"` and a new setting, `space`, which names the vectors in place
  of the address. Then a container needs no GPU and loads no model: no 7 s load per run, and one
  copy of the model in the GPU's memory instead of one per container.
- **Its cost for track A:** indexes are built through the server too. A served index and an
  index built in process have different keys, although the vectors are the same numbers. So
  every index is built once more: by track A's own figures, about 10 minutes for the first task
  of a repo and a minute for each later one.
- **Track A decides whether to use it.** Its GPU setup works. The server matters most where a
  container cannot have the GPU, as on a Mac.
- The same branch makes PyTorch an optional install: `codemem[local]` has the local model, and a
  plain install is for API and server clients. It changes `eval/pyproject.toml` by one line
  (`codemem = ["codemem[local]"]`) and refreshes `eval/uv.lock`, so that
  `uv sync --extra codemem` keeps PyTorch. Andrew: this touches your files; it will be in the
  pull request for you to review. After the merge, an environment of the repo root needs
  `uv sync --extra local`: a plain `uv sync` removes PyTorch from it.

**2. On a CPU the model does not run in the precision its key names.** The key says `float32`.
The model runs in `bfloat16`, the format the weights are stored in, because nothing converts it
on a CPU (seen with transformers 5.20). A CPU without native support for that format is slow in
it. So "hours on a CPU" for pandas may be worse than it has to be. A fix is in progress on
`andre/model-idle-unload`, with timings.

**3. The model takes less memory on an Apple GPU** (same branch). Converting the model to
`float16` on the CPU and then moving it to the GPU holds 1.71 GB after a query. Converting it on
the GPU, as `main` does, holds 2.64 GB. Other devices are untouched.

**4. `model_idle_minutes`** (same branch): the model leaves memory after that many idle minutes
and loads again at the next use. The default is 0, which keeps it. Leave it at 0 in eval runs:
the first search after an unload can answer from keywords alone.

## Checked

- `andre/embedding-endpoints`: 300 tests pass, in my run and in the agent's. Without PyTorch
  installed: 297 pass and 3 are skipped (the agent's run). The eval's own tests pass against the
  branch (535 passed, 20 skipped; the agent's run).
- Served vectors against in-process vectors, same model, `float16` on an M1's GPU: 20 code texts
  and 20 questions, largest difference 0 (the agent's measurement).
  `scripts/check_served_vectors.py` repeats it on any device. **Not checked on CUDA**, nor from
  inside a container on Linux.
- Point 3: the 268 issue texts of the eval's task files, embedded as queries with `main`'s
  loader and with the branch's: all 268 vectors are bit-identical (my run, M1).
- `andre/model-idle-unload`: 276 tests pass (the agent's run). Process memory on the M1 with
  the model in use 1.76 GB, one second after the idle unload 0.62 GB (the agent's measurement).

## Left

- How far the vectors of one model differ between devices and precisions. It is being measured.
  If the difference is only rounding, a setting could let one index serve several devices. Not
  built.
- The three other branches: the compact store, the vector cache's size cap, the worktree start.

## Blocked on, or needed from others

- **Andre:** push the branches and open the pull requests.
- **Andrew:** nothing today. If the server would help the Mac's runs or parallel runs on the PC,
  say so here and the steps are posted.
- **Wilson's question** (entry of 11:36, whether #26 merges before the wording freezes) is with
  Andre.

## Next

- Andre's session: review and merge the remaining branches as they finish; the gate for the
  compact store; the numbers.
