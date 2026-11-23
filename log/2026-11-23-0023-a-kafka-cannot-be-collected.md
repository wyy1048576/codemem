# kafka cannot be collected; pull request #17 is closed and #19 replaces it

- **Track:** A
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-23 00:23 UTC
- **Work package:** A9, the repo list of plan §8.3
- **Branch, commits, pull request:** pull request #19 (branch `plan-probe-facts`), open, for Andre to review and merge. Pull request #17 is closed, not merged

## Done

- **Read the new plan** (`5ba62a9`): our own tasks first, a recipe for each repo, pandas and
  playwright as the first two. Track A works from it now.
- **Closed pull request #17.** The new plan covers most of it. Its two useful parts are in #19.
- **Probed the three repos of §8.3 that are not collected yet,** on GitHub, for the window of the
  collected sets (July 1 to October 22, 2026):

| Repo | Merged pull requests | With a linked issue |
|---|---|---|
| astral-sh/ruff | 1,806 | 395 |
| kubernetes/kubernetes | 1,421 | 246 |
| apache/kafka | 789 | **0** |

- **kafka does not work with `cmeval collect`.** Its issues are in Jira and GitHub issues are off
  for the repo. The collector starts from a pull request's linked GitHub issue. apache/flink is
  the same. Java repos that do link issues: keycloak (1,007), quarkus (414), trino (140),
  elasticsearch (1,562, very large).

## Checked

- The counts are GitHub search counts, read today. "With a linked issue" is an upper limit on
  tasks: in the collected sets, 58 to 87% of the pull requests with one linked issue became
  tasks, before the filter for tests.
- `has_issues` is false for apache/kafka and apache/flink in the GitHub API.
- Not checked: how hard the environment of any Java repo is to build.

## Left

- The team picks the Java repo that takes kafka's place (repo 10, so it is not urgent).
  `overview.md` §12, decision 2, still names kafka.
- Rust unit tests live in the same file as the code (`#[cfg(test)]` modules). The "with tests"
  filter goes by file path today, so it needs a rule for Rust before ruff is collected.

## Blocked on, or needed from others

- **Andre:** review and merge pull request #19. It edits `docs/plan/track-a-evals.md` only.
- **A request to all:** a change to `docs/plan/` that lands on `main` without a pull request
  makes open pull requests on the same file conflict. #17 was reworked twice for that reason.

## Next

Andrew: the admission check of plan §8.2 on pandas, then playwright.
