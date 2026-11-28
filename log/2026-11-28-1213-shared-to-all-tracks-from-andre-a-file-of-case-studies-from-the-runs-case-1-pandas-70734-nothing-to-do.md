# To all tracks, from Andre: a file of case studies from the runs. Case 1 is pandas 70734. Nothing to do: keep it in mind when you analyse results

- **Track:** shared: from the lead, to tracks A and B. No answer is needed
- **Who:** Andre, with Claude Code
- **When:** 2026-11-28 12:13 UTC
- **Work package:** A12 (the runs), the analysis of the results
- **Branch, commits, pull request:** `case-studies.md` at the root of this branch (`worklog`), and one line for it in `README.md`

## Done

**A new file, `case-studies.md`, on this branch** (Andre). It collects runs worth knowing about before you read a results table: cases where one task or run moves a number for a reason other than the one the number seems to give. Track C keeps it, and adds cases as the runs go on.

**Case 1: pandas 70734** (Haiku, repetition 1).

- Writing its fix needs a fact about SAS's file format that is nowhere in the repo, so no run solved it in either setup, at any level.
- By chance, codemem's runs at L1 and L2 found a compiled SAS reader in the container (pyreadstat) and spent 10 to 19 turns trying to decode its machine code. That added 2.2M tokens.
- This one task turns codemem's pandas results from slightly better than grep to about even. With it: tokens −1%, cost +8%. Without it: tokens −11%, cost −2%.

**Nothing to do.** When you analyse or report results, read the file first and keep its cases in mind.

- A task stays in every total.
- Where a case applies, show the numbers without it beside the totals, not instead of them.

## Left

- None.

## Blocked on, or needed from others

- None.

## Next

- Track C adds cases as the runs go on. To suggest one, post a log entry.
