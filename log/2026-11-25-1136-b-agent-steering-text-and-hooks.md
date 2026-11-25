# The agent-facing text now says when to search; two Claude Code hooks; `init` sets them up (pull request #26, not merged)

- **Track:** B. Two points are for track A: see "For track A"
- **Who:** Wilson, with Claude Code
- **When:** 2026-11-25 11:36 UTC
- **Work package:** B8 (the MCP integration)
- **Branch, commits, pull request:** branch `wilson/agent-steering-hooks`, one commit `9ac0022`, off `main` at `9dfe3fe`. Pull request #26, open, not reviewed, not merged

## Done

This is track B's answer to the entry of 2026-11-25 10:22 ("agents must pick up codemem"). It is
on a branch. Nothing here is on `main` yet.

The rule in all of it: **call `search_code` when there is no concrete lead** (no exact name, path
or error string), and grep once there is one.

**1. The `light` wording** (`src/codemem/prompts.py`). `none` and `strong` are unchanged. The
tool names, their parameters and the card layout are unchanged.

The server instructions:

```
codemem searches this repository by meaning: every function and class, with callers and tests.
Call search_code whenever you have no concrete lead:
- at the start of a task, before any grep or file listing: describe the behaviour in plain words;
- whenever you lose the trail: a grep returned nothing or too much, or you don't know which file or symbol to open next.
Once you have an exact name, path or error string, grep or read the file directly.
- get_chunk(ref): read one result in full with its callers and callees.
- refresh_index(): after git checkout, pull or rebase (the index follows your own edits).
```

The `search_code` description:

```
Find code from a plain-words description when you have no exact name to grep for: "where do users log in?", "why are disabled users still logged in?". Use it first on a new task, and again whenever you lose the trail. Returns ranked functions, classes and code blocks with file:line, signature and a short preview. Once you have an exact identifier or string, use grep. Optional filters: path_prefix (a folder), kinds (function, method, class, block), tests (include, exclude, only).
```

Size of the server instructions plus the four tool descriptions, counted from characters, without
the parameter schemas: `light` goes from 1,578 to 1,693 characters (about 394 to 423 tokens).
`strong` stays at 1,824 (about 456).

**2. A last line on every `search_code` result** from the MCP tool, in `light` and `strong`, not
in `none`: "Lost the trail later? Search again in different words." It is added in `server.py`.
`render.format_results` is unchanged, so the eval's hit text is unchanged.

**3. A new command, `codemem hook`** (`src/codemem/hook.py`): two Claude Code hooks.
- **The first search** (before a tool call). The first Grep, Glob or shell search of a session is
  refused once, with a pointer to `search_code`. The repeated call goes through. Nothing happens if
  `search_code` came first. A shell search is a Bash command that runs `rg`, `grep` or `find`,
  found by the word, not by reading the command.
- **The lost trail** (after a tool call). It never refuses. After a Grep or Glob that found
  nothing, matched more than 50 files, or was the third search in a row with no Read,
  `search_code` or `get_chunk` in between, it adds one line telling the agent to try
  `search_code`. The two searches after such a line get none. Shell commands take no part in it.

**4. `codemem init`.**
- `--write-hooks` (off by default) merges the hooks into the repo's `.claude/settings.json`. Other
  settings and hooks are kept, and a second run adds nothing.
- The agent note in `CLAUDE.md` or `AGENTS.md` is now written by default. `--no-agent-notes`
  skips it. `--write-agent-notes` is still accepted.

## For track A

- **Indexes need no rebuild.** Nothing at index time changed, and ranking is untouched.
- **The `tool` setup changes when #26 is merged.** The plan defines it as "the `light` wording",
  and that wording is what changed. Runs of `tool` before and after the merge are not the same
  setup. The pilot batch `pilot-haiku-1` runs the old wording (`main` at `9dfe3fe`).
- **The hooks and the note do not reach an eval run as the runner stands.** It removes `.claude/`
  and `CLAUDE.md` from the checkout. A setup with the hooks would need `.claude/settings.json`
  kept, `codemem` on the path inside the container, and a writable `CODEMEM_HOME`.
- **On Claude Code 2.1.332, which has no Grep or Glob tool** (entry of 2026-11-25 09:34), only the
  shell-search part of the first-search hook can fire. The lost-trail hook never does there,
  because it leaves shell commands out. Extending it to shell searches is open.
- To run it: branch `wilson/agent-steering-hooks`, commit `9ac0022`, default configuration
  (`steering = "light"`).

## Checked

- `uv run pytest`: 277 passed, on the branch. 30 of them are new: the hook, the merge into
  `settings.json`, the `init` flags.
- The installed `codemem hook` was fed sample calls by hand. It refused the first search once,
  gave the three lost-trail lines when it should, and treated shell searches as described.
- `codemem init --write-hooks` on a clone of `requests` (v2.32.3): it wrote `.mcp.json`,
  `.claude/settings.json` and `CLAUDE.md`. A second dry run planned no further change.
- **Not checked: the hooks have never run inside a Claude Code session.** The refusal format, the
  added-context format, the matcher and the `if` condition are from Claude Code's hooks
  documentation. The form of a Grep or Glob result is not documented. It was read from a session
  transcript. If it differs, the "nothing" and "too many" checks stay silent and only the
  three-in-a-row check works.
- **Not checked: whether any of this makes an agent call codemem more often.** No adoption number
  exists (B-E9).
- Not run: the retrieval eval and the eval's own tests. The eval imports `format_results`, which
  did not change.

## Left

- Review and merge of #26.
- One Claude Code session with the hooks installed, to see them fire.
- `"alwaysLoad": true` in the `.mcp.json` that `init` writes (item 3 of the entry of 10:22). Not in
  #26.
- The tag `codemem-today` (item 1 of that entry). Not made.
- `docs/explorer/` still describes `--write-agent-notes` as opt-in and has no entry for `hook.py`.

## Blocked on, or needed from others

- **Andrew:** say whether a setup with the hooks, or with the agent note, is wanted in the
  end-to-end runs, and whether the `tool` setup should move to the new `light` wording before the
  full runs. No date set.
- **Andre:** the entry of 10:22 says the tool descriptions and server instructions are frozen with
  `codemem-final`. #26 changes them. Say whether it should be merged before that freeze.

## Next

- Wilson: get #26 reviewed and merged, then `alwaysLoad` and the tag, then the adoption check on
  Andrew's `tool` setup.
