# For track A, a question from Andre: do the records of the runs hold everything the analysis will need?

- **Track:** shared: from the lead, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 02:20 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks)
- **Branch, commits, pull request:** none

## Done

**The question.** The analysis will use tokens, turns, latency and the solve rate, and cost and whatever else the records give. Andre wants to be sure that what is recorded is enough for it, and that nothing we will want later is being thrown away. **Please answer with your early report. No run should wait for this.**

**What we could see ourselves, in the eval's code on `main` (`739fbe3`).** A run's folder holds `run.json`, `stream.jsonl`, `proxy.jsonl`, `agent.patch`, the grader's folder, the prompt, the logs of codemem's gate and server, and the clock. From those, as far as we can tell, the analysis has:

| For | Where |
|---|---|
| The solve rate | `completed`, `outcome`, the grader's folder |
| Tokens, by class and by model | `tokens`, and every request in `proxy.jsonl` |
| Turns and steps | `steps`, `result_event.num_turns`, every tool call in `stream.jsonl` |
| Latency | `time` (the run's clock, the preparation, the wait for codemem, the host's load) |
| Cost | `result_event.total_cost_usd` |
| What codemem did | `identity.block` (the 20 results, their seconds, the ranks of the gold file and function), the `search_code` calls and answers in `stream.jsonl` |
| How a run ended, and what was unusual | `end`, `flags`, `discard`, `usage_limit`, `turn_limit`, `integrity` |

**What we cannot see from here. Six questions.**

1. **Is every run's whole folder kept,** also for discarded attempts, flagged runs and runs stopped at a limit? With the disk as tight as it is: is any part of a run's folder ever deleted or trimmed to make room?
2. **Are the records copied off the SSD,** where to, and how often? They are the data of the whole project.
3. **How do we get them for the analysis?** For example one compressed archive per finished batch, without `bodies/` and the index copy. About how large is the folder of one run, and of the check run?
4. **Which fields are empty when a run ends at the time limit, the turn limit or a usage limit** (cost, `num_turns`, the tokens)? Can each be worked out again from `proxy.jsonl` and `stream.jsonl`?
5. **Does `proxy.jsonl` hold, for every request, its start and end time and its token counts,** so that a run's time can be split into the model's time and the tools' time, turn by turn?
6. **Request bodies are off in a normal batch** (`keep_bodies`). What would it cost in disk to keep them for the check run, or for one repetition of one repo? With them we could check what the model was sent in each turn: the place of the 20 results, the tool definitions, how the context grows.

**And one open question to you:** is there anything a run produces that is not kept today and that you think the analysis may want?

## Checked

The fields of `run.json` and the files of a run's folder were read in `eval/src/cmeval/e2e_run.py` at `739fbe3`. No record of a real run was seen from here.

## Left

Nothing.

## Blocked on, or needed from others

- **Track A:** the answers, with the early report.

## Next

Track A: the early report.
