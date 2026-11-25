# The codemem setup works in the container; the pilot batch on both repos is running

- **Track:** A. One point is for track C: see "For the other tracks"
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 11:34 UTC
- **Work package:** A1 (the `tool` setup), A9 (validation under the corrected rules)
- **Branch, commits, pull request:** all on `main`: #23 `e6a65fc` (review fixes, ripgrep), #24 `9dfe3fe` (runner, step counts, score), #25 `77c6aa8` (the `tool` setup, `cmeval e2e index`)

## Done

- **The `tool` setup runs.** codemem's MCP server starts inside the task's container, from the
  host's codemem environment and a copy of an index that was built on the host. First real run
  (pandas 70742, Haiku): the server was connected in the first event, the four codemem tools
  were listed, every setup check passed, and the two token counts were equal.
- **`cmeval e2e index`** builds one index per task. Indexes for the 20 sampled task commits of
  pandas and playwright are built or in progress.
- **All 20 task images are built again** with ripgrep 15.2.0, and validated under the corrected
  rules. pandas: 10 of 10 valid again.
- **The pilot batch is running** (`pilot-haiku-1`): every valid task of both repos, in `grep`
  and in `tool`, taking turns, Haiku, one repetition. 36 runs.

## Checked

- In the first `tool` run the agent made **no call to codemem** (12 Bash calls, 5 edits). The
  tools were there from the first turn. One run says little; the batch will show how often the
  tools are used.
- Index build on the PC's GPU: pandas from nothing, 48,351 texts in 492 s (106 texts per
  second; the M5 Mac took 979 s in October). The next commits of the same repo take 36 to 78 s
  each, from the vector cache.
- 692 unit tests pass.

## Left

- The batch, then the six pass conditions of plan §2.2. Met so far: the grader is right; the
  token counts agree on every run.
- A `get_chunk` call on a gold file does not count as "gold file opened" yet.

## For the other tracks

**Track C, track B: an index is tied to the device that built it.** codemem's embedder identity
is `model|doc|L1024|float16|cuda` on a GPU and `...|float32|cpu` without one. An index built on
the GPU and opened on the CPU is embedded again in full: 48,000 texts for pandas, which takes
hours on a CPU. Consequences for the eval:

- **The container needs the GPU.** The runner gives it to every setup alike (NVIDIA container
  toolkit, as a CDI device). With it, the host's index is used as it is: 0 texts embedded again,
  0.5 s to open, 2 s for a catch-up scan, about 7 s to load the model once per run.
- **An index cannot move between the Mac (`mps`) and the PC (`cuda`),** or to a machine without
  a GPU. This answers the open point of §14.2 ("how an index that was built on the Mac is used on
  the PC"): it is not, with today's codemem.
- If `codemem-final` changes the embedder identity, the number type or the store, every index
  is built again. On the PC that is about 10 minutes for the first task of a repo and about a
  minute for each later one.

## Blocked on, or needed from others

- **Wilson:** the `codemem-today` tag. The pilot runs use `main` at `9dfe3fe` for codemem's
  code, which has the same `src/codemem` as `3d9f42b`.

## Next

- The batch result: completion, tokens, time and search behaviour per setup, and how often the
  agent called codemem. It goes here as soon as the batch ends.
