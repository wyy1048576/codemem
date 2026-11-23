# Tracks B and C re-scoped: embedding options and branch handling move to track C

- **Track:** shared: it changes what tracks B and C own
- **Who:** Andre, with Claude Code
- **When:** 2026-11-23 02:44 UTC
- **Work package:** none: planning. B5 becomes C8, and B6 becomes C9
- **Branch, commits, pull request:** `main`. The edits to `docs/plan/`, `CONTRIBUTING.md`, `AGENTS.md` and `CLAUDE.md` are in Andre's working tree, for him to commit

## Done

- **Track C now also owns the embedding model options.** They were track B §5 and work package
  B5. They are track C §6 and C8. The experiments are C-E7, C-E7b and C-E7c.
- **Track C now also owns how an index follows git branches,** with the shared vector store. That
  was track B §6 and B6. It is track C §7 and C9. The experiment is C-E8.
- **Track B is the retrieval algorithm and its own eval:** keywords, the graph and the query
  path. Each new piece passes its gate on the retrieval eval before it goes into a configuration
  that track A runs.
- **Sections were renumbered.** Track B: experiments §5, work packages §6, needs and gives §7,
  risks §8. Track C: experiments §8, work packages §9, needs and gives §10, risks §11.
- **Dates did not change.** The `api` and `light` embedding presets by Dec 1, the local Qwen 8B
  preset by Dec 8, the branch work and the cache cap later, with no date.

## Checked

- The moved sections were cut and pasted by a script. Their numbers changed, and the names of
  their work packages and experiments. Three statements were corrected from track A's checks of
  Nov 22: Nebius names no low-priority tier; at its example limit an API build is not faster than
  the M5; and the overview no longer lists kafka, which cannot be collected.
- Tables, code fences, links and cross-references were checked by script in every plan file.

## Left

- Whether the shared vector store (C9) is built in this phase. Track A's per-task index copies are
  the reason it might be (track C §7.5).

## Blocked on, or needed from others

- Wilson: `status/track-b.md` still lists the `api` part of B5 under "Next". That work is track
  C's now, so please drop it when you next update the file.

## Next

- Andre: C1, with the `api` embedding preset of C8 beside it.
- Wilson: B1, then B2 and B3 side by side.
