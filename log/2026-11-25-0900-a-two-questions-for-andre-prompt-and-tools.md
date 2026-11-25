# Two questions for Andre before the first agent runs: the prompt frame, and Claude Code's tool list

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 09:00 UTC
- **Work package:** A1, the runner
- **Branch, commits, pull request:** the proxy is on `main` now: pull request #22, `0d3ff1b`. The runner is being written on branch `e2e-runner`

## Done

- **The recording proxy is merged** (`0d3ff1b`).
- **One Claude Code call ran inside a task container, by hand,** on the PC, in a pandas task image:
  as a user that is not root, with an empty settings folder, logged in by a token from
  `claude setup-token`, on a Docker network that is internal. From inside the container GitHub
  cannot be reached, and the proxy on the host can. The proxy recorded the request.
- So the run set-up of plan §4.3 and §4.4 works as written, with one difference: the installed
  Claude Code (2.1.332) has no `--max-turns`. The runner counts turns in the stream and stops
  the container at 150.

## Checked

- Read in the first event of the stream of that call: `permissionMode` is `bypassPermissions`,
  `mcp_servers` is empty, `apiKeySource` is `none`, the model is the one asked for.
- The tool list of that event, in the `grep` setup with the flags of §4.3:
  Task, Bash, CronCreate, CronDelete, CronList, DesignSync, Edit, EnterWorktree, ExitWorktree,
  ListAgents, Monitor, NotebookEdit, Read, RemoteTrigger, ReportFindings, ScheduleWakeup,
  SendMessage, TaskStop, Workflow, Write.
- An empty run in the container costs about 35,600 tokens (cache write) before the agent reads
  any code. Every run pays this, in both setups.
- No agent has worked on a task yet.

## Left

- The runner, its first real run, and the code review of tonight's three modules. Both are in
  progress.

## Blocked on, or needed from others

**Andre, two decisions. Neither blocks the bring-up runs: they use the defaults below. Both must
be fixed before the main batch, because they change every number.**

1. **The prompt frame.** The plan says the prompt is "the issue as written" (L0), and gives no
   wording around it. An agent that gets only the text of an issue can answer it instead of
   changing the code. The runner uses this fixed frame, recorded in every run as frame `v1`:

   > The repository in the current directory has the issue below. Change the code of the
   > repository so that the issue is resolved. Work on your own until you are done: nobody can
   > answer questions.
   >
   > `<issue>` the issue title and body `</issue>`

   It does not say to run tests, and it does not name the test command. Is this the wording you
   want? If codemem's `tool` setup needs a sentence here, that is track B's to say (§4.1 puts
   the wording in the tool, not in the prompt, and the frame is the same in every setup).

2. **Claude Code's own tools.** This version has no separate grep or glob tool: the agent
   searches through Bash. It also has `Task` (subagents) and `Workflow` (many subagents), and
   tools that make no sense in a container (`CronCreate`, `RemoteTrigger`, `ScheduleWakeup`,
   `DesignSync`). The plan's rule is "the agent as people use it", so the runner leaves all of
   them on, and only `WebSearch` and `WebFetch` are off. Two risks: a `Workflow` call can make
   one run many times as expensive as the others, and the search subagent of §4.1 is `Task`
   with the `Explore` agent, which matters for the `grep-nosub` setup. Keep all on, or switch
   off the ones that cannot work in a container?

## Next

- The first real agent run: one pandas task, Haiku, the `grep` setup.
- Then the 18 valid tasks, one repetition, as the bring-up runs of §2.2.
