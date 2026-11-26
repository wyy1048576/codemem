# For track A, from Andre: the unfair-test screen may remove many tasks; report its counts per repo and difficulty, and warn early

- **Track:** from Andre, as project lead. Follows the decision of 2026-11-26 02:17
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 02:26 UTC
- **Work package:** A2 (task filters)
- **Branch, commits, pull request:** none

## Done

**Andre's worry.** The 8 of 18 may not be a special case of the pilot. If the screen leaves too
few tasks in a repo, or at one difficulty level, he wants to know at once, before the runs are
planned around a set that does not exist.

**Why a high rate is to be expected.** OpenAI's screen for SWE-bench Verified had 93 developers
annotate 1,699 samples for two faults: an issue that is underspecified, and tests that reject
valid solutions. The released set has 500. So losing about half of the candidates, or more, is
the normal case for tasks built from a pull request's own tests, and 44% is inside that range.
Source: https://openai.com/index/introducing-swe-bench-verified/

**What Andre asks of track A:**

1. **After each batch that is screened, one small table here:** for each repo and each
   difficulty level, the candidates validated, the tasks kept and the tasks removed.
2. **A warning as soon as a repo, or a difficulty level in a repo, is on course to fall under
   what the run matrix needs** (plan §3.3: 20 per repo, spread over the difficulty levels). Say
   how many more candidates that repo still has to draw from.
3. **Whether the screen removes hard tasks more often than easy ones.** If it does, the kept set
   is easier than the pool, and the results have to say so.

## Checked

- The SWE-bench Verified numbers were read from OpenAI's announcement today. Nothing else was run.

## Left

- Nothing on track C's side.

## Blocked on, or needed from others

- Nothing.

## Next

- Track A: the tables of point 1, with the second screen.
