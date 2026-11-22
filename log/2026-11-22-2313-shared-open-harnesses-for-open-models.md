# Track A's plan now names the open harnesses for the open models

- **Track:** shared: a plan change that concerns track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-22 23:13 UTC
- **Work package:** none: planning. It changes what A6 builds
- **Branch, commits, pull request:** `main`. The edits to `docs/plan/track-a-evals.md` and `docs/plan/overview.md` are in Andre's working tree, for him to commit

## Done

- **Track A §4.2 is rewritten and §4.6 is new.** They answer one question: the open models run on
  our own server or on a provider, so which harness lets us plug in the model?
- **Main harness for the open models: mini-SWE-agent,** with both of its action modes (plain text,
  and one tool call) tried for each model. codemem reaches it as a shell command.
- **Second harness: Qwen Code,** for the 9B and 27B models, with codemem attached over MCP, the
  way codemem ships.
- **Runner:** Harbor is tried first, for both arms. It runs Claude Code, Qwen Code, OpenCode and
  mini-SWE-agent from one job file and switches an MCP server on or off per run. Our own runner
  is the fallback.
- **A harness trial** on the pilot tasks is described in §4.6, with the traps the research found.
- **Two facts that change earlier assumptions:** Nebius serves the 27B model and, as far as we
  could see, neither the 9B nor the 14B, while DeepInfra lists all three. Qwen3-14B's context
  window is 32,768 tokens, so it runs in mini-SWE-agent only.

## Checked

- Everything was read on the projects' own pages on Nov 22 by three research passes. Nothing was
  installed or run.
- Two items were read in source code only and need confirming: the flag that selects
  mini-SWE-agent's text mode, and which Harbor agents get a real MCP connection.

## Left

- The harness trial itself.
- Whether Harbor's Claude Code agent accepts a subscription login, the clean-run switches of
  track A §4.3, and our recording proxy.
- Decision 12 in the overview: whether Claude Code driving an open model becomes an extra arm.

## Blocked on, or needed from others

Nothing.

## Next

- Andrew: once the open arm exists, run the harness trial of track A §4.6 on the pilot tasks, and
  write its outcome in this log.
