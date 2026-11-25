# Three eval design decisions: the prompt frame, Claude Code's tools, ripgrep in the images

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 09:55 UTC
- **Work package:** A1, A9
- **Branch, commits, pull request:** ripgrep: one commit on the branch of pull request #23

## Done

Andrew decided the three points of the entries of 2026-11-25. They apply to every setup alike.

| Point | Decision | Reason |
|---|---|---|
| The prompt around the issue | **Frame `v1` is kept**, as given in the entry of 09:00 | Short, the same in every setup, and it names neither tests nor tools. A sentence such as "run the tests" would raise completion and add turns, and turns are what is measured |
| Claude Code's own tools | **All stay on.** Only WebSearch and WebFetch are off | The baseline is Claude Code as it ships. Each run record counts tool calls by name. Every batch is checked for `Workflow` and `Task` use and for token outliers, and the point is opened again only if a tool is seen to eat usage |
| ripgrep in the task images | **Yes**, version 15.2.0, in the base step of each recipe | Claude Code searches through the shell and expects `rg`, as on a developer's machine. With plain `grep` the baseline is slower and noisier than in real use, which would favour codemem |

## Checked

- The download links for ripgrep 15.2.0 exist for x86_64 and for aarch64.
- In the 9 runs so far, no run used a subagent or `Workflow`.
- Not checked yet: a build of the new base images. All task images are built again once, since
  their base changes.

## Left

- The `grep-nosub` setup, when it is built, means: no `Task` tool.

## Blocked on, or needed from others

Nothing. **A recipe for a new repo must install ripgrep in its base step,** as the two recipes do.

## Next

- As in the entry "the first agent runs work end to end".
