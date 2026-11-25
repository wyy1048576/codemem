# On a CPU the model ran 5 to 15 times slower than it has to, and vectors from two devices are close

- **Track:** C. Both points answer track A's entry of 2026-11-25 11:34
- **Who:** Andre, with Claude Code
- **When:** 2026-11-25 13:48 UTC
- **Work package:** part of C5
- **Branch, commits, pull request:** `andre/model-idle-unload` (`78eea77`), local, not pushed. It is
  stacked on `andre/embedding-endpoints`

## Done

**1. The CPU case is fixed on the branch.** On a CPU, `main` runs the model in `bfloat16`, the
format the weights are stored in, while the index key says `float32`. The branch converts the
weights to the precision the key names, on every device. Measured on an M1's CPU, the two
precisions taking turns in one process:

| | 20 short queries | 32 code texts of about 1,000 characters | Process memory, model loaded |
|---|---|---|---|
| CPU, `bfloat16` (`main`) | 18.0 s | 533 s | 0.42 GB |
| CPU, `float32` (branch) | 3.7 s | 35.8 s | 2.43 GB |
| Apple GPU, `float16` | 1.9 s | 9.1 s | 1.72 GB |

So a CPU build is 15 times faster with the fix, and a CPU query 5 times. It costs 2 GB more
memory on a CPU. It does not make a CPU fast: the GPU is still 4 times ahead on code texts.

**2. How far apart are the vectors of two devices?** The same 20 queries and 32 code texts:

| | Largest difference in any score | Smallest cosine | Same top 10 |
|---|---|---|---|
| CPU `float32` against Apple GPU `float16` | 0.0007 | 0.999996 | 20 of 20 queries |
| CPU `bfloat16` (`main`) against either | 0.0055 | 0.99978 | 18 of 20 |

The key keeps the vectors of two devices apart, and they are nearly the same numbers. So a
setting that lets one index serve several devices looks safe for `float32` and `float16`. It is
not built: say so here if the eval needs it, for example to use an index from the PC on a Mac.

**3. Also on the branch:**
- After a burst of embedding the GPU's working memory is given back: 2.80 GB fell to 1.59 GB
  within a second, and the next batch was not slower.
- A model that cannot load is retried with a back-off, with one traceback, not one every second.
- `model_idle_minutes` (default 0, which keeps the model): leave it at 0 in eval runs.

## Checked

- All numbers are the agent's measurements on an M1 with other jobs running. The CPU precisions
  took turns in one process, so the load slowed both alike.
- The branch's suite: 338 passed (the agent's run).
- **Not measured: CUDA.** The fix is the same code path, but track A's PC was not tested. The
  comparison between devices is Apple GPU against Apple CPU only, on 52 texts. No eval was run.
- Vectors that a CPU made under the `float32` key before this fix were made in `bfloat16`. If a
  CPU-built index feeds a reported number, build it again with the vector cache off.

## Left

- The pull requests, in this order: `andre/embedding-endpoints`, `andre/model-idle-unload`,
  `andre/worktree-start`, `andre/compact-store`, `andre/vector-cache-cap`.

## Blocked on, or needed from others

- **Andre:** push the branches and open the pull requests.
- **Andrew:** nothing. Your runs use the GPU, so they are not affected.

## Next

- Andre's session: a real pandas index is being built on the M1 to check the compact store
  against the exact one on pandas's own issue texts.
