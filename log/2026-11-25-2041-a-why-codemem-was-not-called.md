# Why codemem was not called: its text does reach the model, and the model never considers it

- **Track:** A, for track B. Answers Andre's question on tracking
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-25 20:41 UTC
- **Work package:** A4 (integrity), B8 (adoption)
- **Branch, commits, pull request:** `main` at `d76bccd` (#28: diagnostic options)

## Done

**1. Two diagnostic options in the runner (#28).** `CMEVAL_E2E_DIAG_ARGS="--thinking-display summarized"` puts a summary of the model's thinking in `stream.jsonl`. A headless Claude Code run asks the API to leave the thinking text out (`display: omitted`), so all 474 thinking blocks of the pilot are empty. The option is not in `claude --help`. `CMEVAL_E2E_BODIES=1` saves every request and answer body in the run folder. `run.json` marks such runs (`identity.diagnostic`).

**2. Three diagnostic runs** (`diag-light-1`: `tool`, Haiku, wording `light`, codemem `9dfe3fe`; pandas 70713, pandas 66225, playwright 42503). 0 codemem calls in all three.

**3. What the model was sent** (first request of pandas 70713):
- codemem's four tool definitions are there, as tools 24 to 27 of 27. Their descriptions are about 1,060 characters of 94,900 characters of tool definitions.
- codemem's server instructions are there too. They are not in the system prompt. Claude Code puts them in a system message after the user's prompt, under "# MCP Server Instructions", as the last text before the model answers. They end with "Use grep for exact string matches."
- So delivery is not the fault. With `alwaysLoad` the model has all of codemem's text from the first turn.

**4. What the model thought** (37 thinking summaries over the three runs). None names codemem or `search_code`. The model does not weigh it and reject it. In its first thought it already has a guess with identifiers from the issue, and goes to grep for them. Examples:
- playwright 42503: "I'm looking for where the '--debug=cli' option gets bound, so I'll grep the playwright source for the related identifiers: 'debugCli', 'debug=cli', and '_debugCli'."
- pandas 66225: "The likely culprit is the string 'nan' in the word list ... I'll check how pandas handles this in the pytables code."
- pandas 70713: "... I'm looking at how the cell styles get grouped into comma-joined selectors in `_translate`."

**5. A reading of this, not a measurement.** These issues name options, functions and error texts, and the model knows pandas and playwright well. So from turn 1 it has an exact string to look for, and for that case the `light` wording itself says to use grep. The agent does what the text tells it. Two things would test this: issue texts with the identifiers taken out (the plan's vague rewrites), and repos the model does not know.

## Checked

- Token counts equal to `modelUsage` on the three runs. Unit tests: 710 pass on `d76bccd`.
- Not checked: whether a thinking summary changes the agent's behaviour or cost. The option is for diagnosis only, not for reported runs.
- A summary is written by the API from the thinking. It is not the raw thinking.

## Left

- The same look at a `strong` run, where the model does call `search_code` once: why it does not call again.

## Blocked on, or needed from others

- **Wilson:** point 5 is for the wording. The saved request bodies are on the PC (`~/.cmeval/e2e/runs/diag-light-1/*/tool/1/bodies/`); ask here for any of them.

## Next

- Track A's session: the adoption check with these options on track B's frozen wording.
