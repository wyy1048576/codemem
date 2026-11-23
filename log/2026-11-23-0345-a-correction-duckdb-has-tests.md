# Correction: duckdb has about 200 tasks with tests, not 9. It is the C++ repo

- **Track:** A. It corrects the entry of 2026-11-22 23:54, which said duckdb had 9
- **Who:** Andre, with Claude Code
- **When:** 2026-11-23 03:45 UTC
- **Work package:** A9, the repo list of plan §8.3
- **Branch, commits, pull request:** `main`. The edit to `docs/plan/track-a-evals.md` §8.3 is in Andre's working tree, for him to commit

## Done

- **The count of 9 was an artifact.** `classify_path` in `eval/src/cmeval/patches.py` gives the
  class "other" to every file whose extension is not a known language. DuckDB writes its tests as
  `.test` files under `test/`. So a pull request that added only such a test was tagged as having
  no test.
- **Checked on GitHub:** of the 200 duckdb tasks tagged "no test", 25 were read at random. 24 of
  them changed a `.test` file.
- **So duckdb is the C++ repo,** fifth in the order of plan §8.3, with about 200 candidate tasks.
  llama.cpp is the reserve.
- **Godot stays out.** Of 10 further Godot pull requests read, 1 changed a test. Of 10 further
  llama.cpp ones, none did.
- **The plan now says that what counts as a test is set per repo, in its recipe** (§8.2), and
  that 10 pull requests are read by hand before a repo's count is trusted (§16).

## Checked

- The classifier's rule was read in the source.
- The 45 pull requests were read through GitHub's public API on Nov 22. The sample for duckdb is
  25 of 200, so "about 200" means roughly 160 to 200.
- Not checked: how long duckdb takes to build in a container, and how its test files are run for
  one task. The admission check of §8.2 decides.

## Left

- The test-file rule for duckdb in the collector or in the recipe: `.test` and `.test_slow`
  files under `test/`.
- The same question for every other repo. Rust keeps unit tests inside code files, as Andrew
  already noted.

## Blocked on, or needed from others

Nothing.

## Next

- Andrew: when duckdb's turn comes, give its recipe the test-file rule first, then run the
  admission check.
