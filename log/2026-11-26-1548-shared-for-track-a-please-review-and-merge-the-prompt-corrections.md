# For track A: the prompt corrections are yours to review and merge (`andre/vague-prompts-v3`); Andre will not merge them

- **Track:** shared: from track C's session, for track A
- **Who:** Andre, with Claude Code
- **When:** 2026-11-26 15:48 UTC
- **Work package:** A9 (the vague prompts)
- **Branch, commits, pull request:** `andre/vague-prompts-v3` (`5a7c2a2`), no pull request yet: https://github.com/wyy1048576/codemem/pull/new/andre/vague-prompts-v3

## Done

**One thing the entry of 15:44 left unclear: who merges.** The prompt files are track A's, so
this branch is for Andrew and his session to review. Andre will not open or merge its pull
request.

- **If the corrections are useful as they are:** open the pull request from the link above and
  merge it. It adds two files and changes none: `eval/tasks/vague-b7-v3.jsonl` (your v2 file with
  13 of its 90 rows changed) and `eval/tasks/vague-b7-v3.changes.md` (each change with its
  reason). Then write the meta file with your own tool and point the runs at v3.
- **If you would rather change them:** take what you agree with into a file of your own; the
  changes page lists the 13 rows one by one, so each can be taken or left by itself.
- **Either way, before the check run:** the four L2 texts that leave out a behaviour a hidden
  test checks (playwright 43071, 42204; pandas 68090, 69924) and the one L1 that states what the
  issue never says (playwright 42792) are the five that can change a result.

## Checked

- The branch is `main` plus those two files; nothing of yours is edited.

## Left

- Nothing on our side.

## Blocked on, or needed from others

- **Andrew:** the review, and a line here on what you took.

## Next

- Track C's session: track B's part with Andre, as in the entry of 15:44.
