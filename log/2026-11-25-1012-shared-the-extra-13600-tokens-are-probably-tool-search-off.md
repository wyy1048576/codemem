# The extra 13,600 tokens per turn are probably `ENABLE_TOOL_SEARCH=false`, which the plan told the runner to set

- **Track:** shared. A suggestion for track A, with one consequence for track B
- **Who:** Andre, with Claude Code
- **When:** 2026-11-25 10:12 UTC
- **Work package:** A1 and A2 (the runner's flags); B8 (how `codemem init` registers the tools)
- **Branch, commits, pull request:** none. Nothing was changed

## Done

A hypothesis for the gap Andrew found: an empty call costs about 22,000 tokens outside the
container and about 35,600 inside it, with the plan's flags. It is not Linux.

**The evidence.**
1. The runner sets `ENABLE_TOOL_SEARCH=false` (`eval/src/cmeval/e2e_run.py` line 253 on branch
   `e2e-runner`), because plan §4.3 says to.
2. The tool list in the first event of the stream (entry of 2026-11-25 09:00) has 20 tools and no
   `ToolSearch`. In a default Claude Code session, `ToolSearch` is there, and 11 of those 20
   tools are **deferred**: only their names are sent, not their full descriptions. They are
   CronCreate, CronDelete, CronList, DesignSync, EnterWorktree, ExitWorktree, Monitor,
   NotebookEdit, RemoteTrigger, SendMessage and TaskStop. With tool search off, all 11 full
   descriptions are in the fixed prompt, and the fixed prompt is re-sent on every turn.
3. The 22,000-token call on the PC (entry of 2026-11-24 23:41) was made without the plan's flags.

**The test.** Two empty calls, same container, same flags, one with `ENABLE_TOOL_SEARCH=false` and
one without. Compare the cache-write tokens and the tool list in the first event.

**If it is confirmed, a suggestion.**
- Drop `ENABLE_TOOL_SEARCH=false` in every setup. Keep `"alwaysLoad": true` on codemem's server,
  which should still send codemem's tools up front. The runner's check that the first event of a
  `tool` run lists codemem's tools shows whether it does.
- Why:
  - **the baseline becomes Claude Code with its default setting,** which is the plan's own rule
    ("the agent as people use it");
  - **about 13,600 fewer tokens on every turn of every run,** in both setups: about 30% of the
    first pandas run (18 requests, 823,596 tokens);
  - **the saving codemem makes is no longer diluted** by text that neither setup needs.

This is track A's decision. The `ENABLE_TOOL_SEARCH=false` line in plan §4.3 was written by Andre's
agent. If the test confirms it, §4.3 should change.

## Checked

- The runner's source on `e2e-runner`, and the tool lists in Andrew's entries. Nothing was run.
- Which tools are deferred was read in Andre's own Claude Code session, which is another build.
  The deferred set of 2.1.332 may differ.

## Left

- The two-call test.

## Blocked on, or needed from others

- **Andrew:** the two-call test, before the settings of the main batch are fixed.
- **Wilson:** with tool search on by default, users get codemem's tools up front only if its
  server is registered with `"alwaysLoad": true`. `codemem init` does not write that today
  (`src/codemem/agents.py`). It belongs in the registration work of B8.

## Next

- Andrew: the test, then a decision on the flag.
