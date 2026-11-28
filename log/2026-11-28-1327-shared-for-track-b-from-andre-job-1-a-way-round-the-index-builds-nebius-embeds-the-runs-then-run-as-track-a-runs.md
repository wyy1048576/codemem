# For track B, from Andre: job 1, a way round the index builds. Nebius does the embedding, and the runs then go exactly as track A runs them

- **Track:** shared: from the lead, for track B. Follows our entry of 12:49 UTC (job 1 not on your PC; FarmShare first, Nebius last)
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 13:27 UTC
- **Work package:** B8 (job 1); `docs/plan/runs.md` §12
- **Branch, commits, pull request:** PR #90, `andre/eval-vector-backend` at `64344a9`. codemem stays at `463171c`

## Done

**1. Andre: if the bottleneck of job 1 is building the indexes, Nebius can take it.** The indexes are the exact one and the compact one, with its 1-bit code that a search scans and its 4-bit code that ranks the candidates. codemem at `463171c` can already send its embedding work elsewhere, in two ways.

**First choice: a rented Nebius GPU, with codemem's build assist.**

- **On the GPU machine:** run `codemem serve-embeddings`. It serves the same model as track A's runs (`jina-code-embeddings-0.5b`). Start it with a key (`CODEMEM_SERVE_KEY`), so that it is not open to anyone.
- **On the machine that runs job 1:** add the lines it prints for an assist (`[embedding.assist]`) to codemem's config for the builds.
  - The build then sends most texts to the GPU.
  - Every vector is stored under the local model's key, so the index is the one the local model alone would build (`docs/architecture.md`, "A second source for a build's vectors").
  - A run opens it without embedding again, and embeds the agent's own searches locally.
- **Check before any build:** `codemem status --check-assist`. Seven fixed texts must agree to a cosine of 0.99995 both ways.
- **This keeps the model of track A's runs.** Nebius's API (Token Factory) has no jina model, so the assist needs the rented GPU.

**Second choice, only if the first cannot work: Nebius Token Factory with Qwen3-Embedding-8B,** which codemem supports as its embedding provider (`docs/plan/track-a-evals.md` §2).

- **It is another model than track A's.** Andre accepts that for job 1, since job 1 compares two indexes of one model.
- **The catch:** one index holds one model's vectors, so the agent's own searches during a run would embed through the API too.
  - The run's container would have to reach the API and hold its key.
  - The runner does not allow that today: a container reaches only the model's API.
  - The agent runs as the same user as codemem's server, so it could read the key.
- **Ask here before you change anything for it.**

**2. With the indexes built, job 1 runs exactly as track A runs:** the same 8 kubernetes run tasks, the same prompts (L0, L1, L2), harness, limits and grading.

- If the machine's containers get no GPU, the runs embed their searches on the CPU (`CMEVAL_CODEMEM_DEVICE=cpu` on PR #90's branch). Then the builds use the same switch, with the assist doing the embedding.
- Build and run on the same machine. An index is tied to the device and precision of the local model that stores it.

**3. Job 1 compares the two indexes only:** codemem with the exact index against codemem with the compact one. No `grep` arm: 8 tasks × 3 levels × 2 indexes × Haiku and Sonnet, 96 runs, as before.

**4. Still open: the machine.** Wilson is looking into FarmShare first, and Nebius is the last resort. Andre posts the choice.

**5. Wait for one fix before any run.** PR #90's branch has `main` merged in, and with it the fault that track A found in #92's preparation step (their entry of 13:12 UTC). We merge their fix into the branch before job 1 runs anywhere.

**6. First, as before:** your answer on the v3 check (our entry of 12:49 UTC, points 2 and 3).

## Left

- Track B: the v3 answer; then, when the machine is settled, the assist check and the builds.
- Andre: the machine, and the Nebius GPU if it is the one.
- Track C: track A's fix merged into PR #90's branch.

## Blocked on, or needed from others

- **Track B:** whether FarmShare can run Docker containers, with a GPU or without, and a Claude login of your own there.

## Next

- Andre posts the machine for job 1.
