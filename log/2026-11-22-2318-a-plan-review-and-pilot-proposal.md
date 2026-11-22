# The plan is checked against what exists, and the pilot repos are proposed

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-22 23:18 UTC
- **Work package:** the first job of §2.2 (propose the pilot repos). A1 is not started
- **Branch, commits, pull request:** branch `plan-index-two-first`, pull request #17, open. It changes `docs/plan/track-a-evals.md` only. Andre is the reviewer and merges it

## Done

- **The pilot is proposed, in two steps** (pull request #17, new §2.5):
  - Step 1, no container: the index and localization check on **pandas** and **playwright**, two
    repos of our own task sets. They are the smallest (16 and 12 minutes cold on the M5).
  - Step 2, the graded pilot from SWE-bench-Live: **keras** (Python, 13 tasks), **mui/base-ui**
    (TypeScript, 5 tasks), **rust-analyzer** (Rust, 12 tasks). Reserves: conan or pylint,
    TanStack/router, biome.
- **A table of which tasks serve which measurement** (new §2.4): our own task sets for retrieval
  and agent localization, SWE-bench-Live for end to end.
- **Difficulty is logged for every task we create** (§10). Counts for our 3,788 fresh tasks, from
  their tags: 44% easy, 37% medium, 19% hard.
- **Big Go and Rust repos for our own task sets** (§12.2), from a probe of 24 candidates:
  kubernetes, tidb, gitea; rust, zed, datafusion, and ruff as a medium repo. golang/go and
  cockroach cannot be used: they do not merge through GitHub pull requests.
- **Andrew decided:** local embedding first, Nebius later. Everything reaches `main` through a
  pull request, merged with squash and merge.

## Checked

Facts that other tracks can use. Each was checked today, on the page or the machine named.

- **The public task tables** (downloaded from Hugging Face): the `verified` Python split has 500
  tasks in 100 repos, from July 2024 to April 2025. TypeScript 111 tasks in 63 repos, Go 138 in
  92, Rust 171 in 55. **68 of the Rust tasks were created after June 2026.** No Python,
  TypeScript or Go task is that new. Only apache/datafusion is also one of our repos.
- **Claude Code 2.1.311 under a subscription login:** a headless run works with
  `ANTHROPIC_API_KEY` unset, and the result carries `usage`, `modelUsage` and `total_cost_usd`.
  **`usage` and `modelUsage` do not agree in one result:** a one-line Haiku run gave 2 input
  tokens in `usage` and 1,176 in `modelUsage`. So the cross-check of §5.3 must compare the proxy
  with `modelUsage`. An empty run already processes about 21,700 tokens.
- **`--max-turns`** is in the online CLI reference and not in the `--help` text of 2.1.311. Not
  tested.
- **Nebius** lists one embedding model, Qwen3-Embedding-8B, at $0.01 per million tokens. It does
  not list our jina model, and not the 9B or 14B chat models. Its rate-limit page gives 400,000
  tokens a minute only as an example, growing to at most 4 times the base. The page names no
  low-priority tier.
- **Index cost in October, from the run logs:** 1.79 million texts embedded in 14.3 hours on the
  M5, for 9 repos and 218 task commits. At 400,000 tokens a minute the same work is about 20
  hours through Nebius (an estimate: it uses the plan's 40M tokens for vLLM). So the API is not
  faster than the M5 until the limit is raised.
- **Not checked:** rule 5 of §2.2. Nobody has pulled a SWE-bench-Live image and run a task's
  tests. Index times of the three graded pilot repos are not measured.

## Left

- Pull request #17 waits for review.
- The x86 machine for graded runs is not named. Andrew has two candidates, to confirm.
- The Go and Rust task sets need a labeler each. The plan says "after the paper"; Andrew proposes
  the labelers from Dec 2. Open for the team.

## Blocked on, or needed from others

- **Andre:** review and merge pull request #17.
- **Wilson:** the `codemem-today` tag, Nov 23, as planned.
- **All:** say in the log if a proposed pilot repo is a bad choice, before A1 builds on it.

## Next

Andrew: step 1 of the pilot (index pandas and playwright with the local model), then A1 and A2 on
it. The check of rule 5 follows when the x86 machine is named.
