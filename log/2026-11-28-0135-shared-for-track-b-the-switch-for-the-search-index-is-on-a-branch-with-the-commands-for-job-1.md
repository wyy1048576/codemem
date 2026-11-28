# For track B: the switch that lets an eval batch name the search index is on a branch, with the commands for job 1

- **Track:** shared: from the lead, for track B (job 1: v2 on kubernetes with the exact and the compact index). For track A to know: it is eval code, on a branch, not merged
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 01:35 UTC
- **Work package:** B8; A6 (the setups)
- **Branch, commits, pull request:** `andre/eval-vector-backend` at `a6653cb`, one commit on `main` (`e7586b4`); it merges into `main` at `739fbe3` without a conflict. Not merged, no pull request yet

## Done

**The switch.** One environment variable for a batch, `CMEVAL_CODEMEM_VECTOR_BACKEND`: `faiss` (the exact index) or `compact`. Any other value is refused before anything is built or run.

- **Unset, everything is as on `main`,** byte for byte: the folders, the environment codemem gets, the commands and the records. New tests pin this, and one dump of index builds, blocks, runs and the replay was made on `main`'s code and on the branch's and compared. Track A's runs are not touched by this branch in any case: it is not merged.
- **With `compact`, a task's index and blocks get a folder of their own,** `indexes/kubernetes/<task id>/compact/`, with `index.json` saying `"vector_backend": "compact"`. Neither form's build touches the other's files, and a block made on the other form's index is refused.
- **The value goes to every place codemem runs for the batch:** the index build, the block's search, and the MCP server of a run. The replay takes it from each run's record.
- **When the variable is set, the record names the index** (`identity.codemem.vector_backend`, `identity.block.vector_backend`), and the setup check fails a run whose warm server reports another index.

**How to use it for job 1.** Run the eval from this branch for both arms, and set the variable in both, so that both get the same checks and both records name their index. From `eval/`:

```bash
IDS=(--id kubernetes__kubernetes-140607 --id kubernetes__kubernetes-140926 --id kubernetes__kubernetes-142138 --id kubernetes__kubernetes-142215 --id kubernetes__kubernetes-141618 --id kubernetes__kubernetes-142340 --id kubernetes__kubernetes-141057 --id kubernetes__kubernetes-140916)

# the compact arm (for the exact arm: CMEVAL_CODEMEM_VECTOR_BACKEND=faiss and --run-id k8s-exact-$m-$L)
export CMEVAL_CODEMEM_VECTOR_BACKEND=compact
cmeval e2e index kubernetes --tasks tasks/e2e/kubernetes.jsonl "${IDS[@]}"
cmeval e2e block kubernetes --tasks tasks/e2e/kubernetes.jsonl --sample tasks/run-sample-v1.jsonl --prompts tasks/vague-b10a-v3.jsonl
for m in haiku sonnet; do for L in L0 L1 L2; do
  cmeval e2e run kubernetes --tasks tasks/e2e/kubernetes.jsonl "${IDS[@]}" --setup codemem --model claude-$m-5-5 \
    --prompt-level $L --prompts tasks/vague-b10a-v3.jsonl --run-id k8s-compact-$m-$L
done; done
```

- **Make a dry run first** (`--dry-run`): all 8 tasks should say `index ok`.
- These commands were checked here only by parsing and by dry runs. If one does not run as written, say so in this log; do not change it silently.
- **The 20 results at the start, compact against exact** (`docs/plan/runs.md` §12, point 1): the `results` of `<task>/block-L*.json` against those of `<task>/compact/block-L*.json`.
- **The seconds of a build** compare only if each form is built with an empty `CODEMEM_HOME`: the second build would otherwise take its vectors from the cache of the first.

**What the first real run of the compact arm must show.** Nothing here ran in a container, so please check these on the first run and post them before the other runs count:

1. `compact/index/` holds `vec_*.rabitq` files, with `vec_*.json` notes that say `"backend": "compact"`, and no `vec_*.faiss`.
2. The blocks have `"embedded": true`.
3. `run.json` has `setup_ok` true, and `integrity.codemem_warm.status.search_index` shows the setting and the index as `compact`.
4. `identity.codemem.vector_backend` is `compact`, and the block's file is under `compact/`.
5. **`time.codemem_warm_s` and the number of warm-up searches are as small as in an exact run of the same task.** Tens of seconds would mean that codemem built the compact index again at the start of the run, and no check catches that.

## Checked

- The whole eval suite on the branch, on Andre's Mac: 952 passed, 20 skipped (`main`: 937 and 20). 15 new tests.
- **Not checked:** a container, a GPU, a real codemem process and a real build of the compact index; whether the container's FAISS supports the compact index (the lock has faiss-cpu 1.16.0, and codemem refuses an older one with a clear message).

## Left

Nothing on our side until you have tried it.

## Blocked on, or needed from others

- **Track B:** as before: the confirmation of both jobs, the post on whether your machine can do job 1, and, before any run that counts, the list of every difference from track A's setup.

## Next

Track B: the feasibility post.
