# Track A's plan reviewed: the model gap and four languages in the main runs, and a run sheet

- **Track:** shared: a plan change for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-23 03:25 UTC
- **Work package:** none: planning. It changes the order of A9, A10 and A11
- **Branch, commits, pull request:** `main`. The edits to `docs/plan/track-a-evals.md` and `docs/plan/overview.md` are in Andre's working tree, for him to commit. **They include pull request #19 as it stood**, so #19 can be closed once this is on `main`

## Done

Andre asked for these. All are in `docs/plan/track-a-evals.md`.

- **How a run is judged** is now stated in one place (§4.7): what the agent gets, when a run ends,
  what is graded, and what "completed" means.
- **The model gap is in the main runs, not after them** (§11). At least one open model, the 9B,
  before the presentation. Then the 27B, then the 14B. It runs on its own endpoint, beside the
  Claude runs.
- **Rust and Go are part of the main results.** The repo order is now pandas, playwright, ruff,
  kubernetes, home-assistant, vscode (§8.3). The Go and Rust labelers of A10 move into the main
  timeline. Java stays for later.
- **Many tasks are prepared and a sample is run** (§3.3): 20 per repo, 6 easy, 8 medium and 6
  hard, drawn once from seed `main-1`. If usage runs short the sample shrinks to 15, then 12.
  Languages are not dropped before tasks.
- **Runs are scheduled by repetition:** repetition 1 of everything before repetition 2.
- **Wall time is compared only inside one batch,** turn about. A reused baseline serves tokens
  and completion.
- **§14 is now a run sheet:** five lanes that do not wait for each other, a queue night by night,
  the decisions already made, and the rules for running unattended.

## Checked

- Pull request #19 applied to the working tree without conflict before these edits.
- Tables, code fences and links were checked by script.
- Nothing in the plan was run. The night-by-night table is a target, not a measurement.

## Left

- Whether the hosted endpoint for the open models has a key on Andrew's machine. Without one,
  §14.4 says to run the 9B on the Mac.
- A Java repo in place of kafka.

## Blocked on, or needed from others

- **Andrew:** please read §4.7, §3.3 and all of §14 before the next unattended session, and say
  here if a rule in §14.5 cannot be followed on your machine.
- **Andrew:** your #19 is included here word for word. Nothing of it needs redoing.

## Next

- Andrew: the lanes of §14.3, starting with the row for tonight.
