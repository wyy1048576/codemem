# Case studies from the runs

Runs worth knowing about before you read a results table: cases where one task or one run moves a
number for a reason other than the one the number seems to give. Each case says what happened, how
it moved the results, and what to keep in mind.

- **How to use it:** before you draw a conclusion from a table, check whether a case below covers
  one of its tasks.
- **How it is kept:** track C keeps this file. To suggest a case, post a log entry. A case is
  corrected in place, with the date, if a later run changes it.
- **Words used:** a *setup* is `grep` (the agent's own tools) or `codemem` (the same, plus codemem).
  L0 is the issue as written, L1 the same with every code name removed, L2 a short request. A
  *pair* is one task at one level, run once in each setup.

---

## 1. pandas 70734: the fix needs a fact that is not in the repo

*Haiku, repetition 1, L0 to L2. Runs of Nov 28 on track A's PC; release `run-records`, archive
`haiku-rep1-pandas.tgz`, folders `runs/haiku-pandas-L*/pandas-dev__pandas-70734/`. Added Nov 28.*

**In short.** Neither setup could solve it: writing the fix needs a fact about SAS's file format
that is nowhere in the repo. By chance, codemem's runs at L1 and L2 dug much longer, and added 2.2M
tokens. This one task turns codemem's pandas results from slightly better than grep to about even.

**The task.**

- **The bug:** a SAS data file keeps deleted rows on disk, marked as deleted, and pandas reads them
  anyway: 5 rows where SAS shows 3.
- **The real fix** changes 3 files (239 lines). To write it, you must know how SAS marks those
  rows: a flag in a page's header says the page holds deleted rows, another header field gives the
  distance to a small bitmap after the rows, and the bitmap has one bit per row.
- **None of that is in pandas, in the issue, or in any readable file in the container.** The
  issue's own example file is a link to an outside file host, which the runs cannot reach.
- The only source in the container is pyreadstat, an installed Python package that can read these
  files. It holds the format only as compiled machine code.

**What the six runs did.**

| Level | Setup | Turns | Tokens | Found pyreadstat? |
|---|---|---|---|---|
| L0 | grep | 13 | 655K | yes; looked at its folder and stopped |
| L0 | codemem | 12 | 615K | did not look outside the repo |
| L1 | grep | 12 | 543K | no: its command cut the output off before pyreadstat |
| L1 | codemem | 22 | 1.34M | yes; about 10 turns trying to decode its machine code |
| L2 | grep | 11 | 540K | no: its search skipped pyreadstat's folder |
| L2 | codemem | 29 | 1.97M | yes; 19 turns decoding its machine code |

- **No run changed the code.** All six stopped on their own, far below the limits, and asked for
  the same thing: a SAS file with deleted rows, or the format.
- **Whether a run found pyreadstat came down to how one shell command was worded.** codemem's
  search covers only the repo, and played no part.

**How close codemem's L2 run got.**

| What the fix needs | The real fix | What the agent decoded |
|---|---|---|
| Where the distance to the bitmap is stored | 24 bytes in (64-bit files), 12 (32-bit) | +0x18 and +0xc: the right numbers (24 and 12), though it put them in the wrong part of the file |
| The bit order | one bit per row, most significant first | the same: right |
| Which pages have deleted rows | flag 0x0080 in the page's type | not found |
| Where the bitmap sits | right after the page's rows | not sure |

It stopped because "I didn't want to ship a guessed parser", and offered to write the fix
unverified if nobody could send a file. Nobody answers in these runs, so the run ended there.
Without the flag, a fix would probably still have failed the hidden tests.

**How it moved the pandas results** (codemem against grep):

| | All 27 pairs | Without 70734 (24 pairs) |
|---|---|---|
| Tokens | −1% | −11% |
| Turns | −10% | −17% |
| Cost | +8% | −2% |
| Medium tasks, tokens | +16% | −8% |
| Pairs where codemem used fewer tokens | 17 of 27 | 16 of 24 |

Without it, codemem uses fewer tokens and turns than grep on pandas, at about the same cost. This is
still one repetition, and not yet beyond chance (p 0.15 for tokens, 0.09 for turns).

**Keep in mind.**

- **The task stays in every total.** It is a valid run, and dropping it after seeing the result
  would be cherry-picking. Show the numbers without it beside the totals, not instead of them.
- **A task that neither setup solves at any level** measures how long an agent keeps digging, and
  luck, not how well it finds code.
- **One part is not luck:** codemem read more before reaching the dead end (at L2, 10 turns and 493K
  tokens, against grep's 7 and 304K), as it did across pandas.
- **When the knowledge is outside the repo,** when the agent decides to stop matters more than how
  it searches.
