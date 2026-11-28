# The v3 check: PR #85 ("v3", `4902671`) against `main` ("v2", codemem `463171c`)

This branch holds data only. Do not merge it. It is the full record of an independent check run on Nov 28,
02:15 to 06:04 UTC, on one Mac, one session at a time: 341 session folders, of which 337 sessions are kept.

**The result and the design:** [report.md](report.md) gives the answer in its first lines, then every table.
[brief.md](brief.md) is the design as it was written before the first session.

## The five setups (arms)

| Arm | In session names | The agent has |
|---|---|---|
| `grep` | `grep` | its own tools only: Read and read-only shell commands |
| `v2-tool` | `v2t` | codemem `463171c` as the MCP tool |
| `v3-tool` | `v3t` | codemem `4902671` (PR #85) as the MCP tool |
| `v2` | `v2u` | `v2-tool` plus the 20 lines of one codemem search at the top of the first message: **what the evaluation runs** |
| `v3` | `v3u` | `v3-tool` plus the same 20 lines |

Session names read `v3s<stage>-<arm>-<task>-L2-<model>-r<run>`:

- **Stage 1:** Haiku, 17 pandas tasks.
- **Stage 2:** 6 vLLM tasks, Haiku and Sonnet.
- **Stages 3 and 4:** Sonnet, 17 pandas tasks.

Folders with a dot in the name are attempts the harness set aside; `runs/discards.jsonl` says why.

## What is here

| Path | What it holds |
|---|---|
| `report.md` | The result: answer, tables per stage, one worked example (task 71129), what was not measured |
| `brief.md` | The design, written before any session |
| `sessions.csv` | One row per kept session: model, arm, task, run, turns, tokens by class, cost, seconds, right file first, right function, search calls |
| `transcripts/<session>.md` | Each session in readable form: the first message, every turn, every tool call and its result (cut at 1,500 characters), the answer, the scores |
| `runs/<session>/record.json` | The harness's record of the session, scores included (`gold_file_first`, `gold_fn_full`, `gold_files`, `gold_functions`) |
| `runs/<session>/stream.jsonl` | Claude Code's own event stream: every turn, tool call and result |
| `runs/<session>/proxy.jsonl` | Every API request, with its full `usage` |
| `runs/<session>/prompt.txt` | The first message, with the 20 lines in `v2u` and `v3u` |
| `runs/<session>/cmd.json` | The exact `claude` command: the tools, the allowed tools, the flags |
| `runs/<session>/mcp.json` | codemem's server config. Its `PYTHONPATH` names the source the arm ran: `compare-main` is `463171c`, `compare-pr85` is `4902671` |
| `runs/<session>/server.log` | codemem's server log |
| `runs/<session>/bodies/*.request` | The first request, reduced to codemem's tool definitions (other tools by name only) and codemem's server instructions |
| `v3/upfront-463171c/` | The 20 lines of each task, made once at `463171c` and used in both `v2u` and `v3u` |
| `v3/check-*.json` | The checks run before the first session: the index opened without a rebuild, the plain searches, the 20 lines, the dry starts |
| `v3/instructions-v2.txt`, `v3/instructions-v3.txt` | codemem's server instructions at each commit |
| `bin/` | The harness (`compare.py`, `pipeline.py`, `mcp_hold.py`), the driver (`blockv3.py`, `v3lib.py`, `v3check.py`) and the report scripts (`blockv3_report.py`, `summary.py`, `blockv3_rows.py`, `blockv3_count.py`, `blockv3_tasks.py`) |

## Recompute the tables

```bash
python3 v3-check/bin/blockv3_report.py --print
```

This reads only `runs/` and `v3/`, so no codemem checkout is needed. It prints every table of `report.md`, and all 116
table rows match exactly. To read one task's sessions in short form:

```bash
python3 v3-check/bin/blockv3_rows.py pandas haiku 71129 --calls
```

The harness itself (`compare.py`) needs a codemem checkout: set `CODEMEM_REPO`.

## What was removed before publishing

- Local paths, which now read `<codemem>` and `<home>`.
- The subscription's usage fields (`util_5h`, `util_7d`, `unified_status`).
- The rate-limit headers and request ids in `proxy.jsonl`.
- Every request body except the reduced first one.

Nothing else was changed.

## Limits

- The agent locates code and does not edit it. These are not fix runs.
- All requests are at L2. The tasks are pandas and vLLM only.
- Sonnet's run-to-run variation was measured only for `v2` and `v3`, on 7 and 8 pandas tasks.
- A second run of an arm can read the prompt cache written by the first, which lowers its cost but not its tokens. Run-to-run variation is therefore measured in tokens.
- Seconds exclude the server's start.
- The harness ran 3 Haiku `v3` sessions again because their first call left out `query`. The report gives both counts.
