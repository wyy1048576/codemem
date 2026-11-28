# Track A: the four comparisons pass and #92 is merged (`da25c74`). The runs can change at the start of a batch; that waits for Andrew's word. vscode is in the build queue

- **Track:** A, for the lead. Answers your entries of 11:18 and 11:34 UTC
- **Who:** Andrew, with Claude Code
- **When:** 2026-11-28 12:46 UTC
- **Work package:** A12 (the runs), A4 (the integrity checks)
- **Branch, commits, pull request:** PR #92 merged with squash: `main` = `da25c74` (equal to the branch at your `8649223`, empty diff). Scripts on the PC, outside the repo

## Done

**1. Your commit `8649223` is read, and it is in the merge.** One note: `sync` in a container waits for the writes of the whole machine, not only for the copy: the other stream's writes and an image save to D: too. Measured so far: 0.2 to 0.7 s. It is outside the agent's clock, and we watch `prep_steps_s.sync` in the records.

**2. The four comparisons pass.** Two containers of the same image without a network: the old step in one, the new step in the other, then every entry of `/testbed` compared.

| Task | Entries | Old step (chown) | New step (copy and swap) | Sync after the new step | Result |
|---|---|---|---|---|---|
| ruff 27689 | 23,213 | 250.4 s | 52.5 s | 0.2 s | same |
| duckdb 24011 | 35,776 | 501.3 s | 40.5 s | 0.7 s | same |
| kubernetes 140607 | 67,727 | 663.4 s | 41.4 s | 0.7 s | same |
| home-assistant 183382 | 66,782 | 736.7 s | 41.6 s | 0.4 s | same |

- **Compared for every entry:** path, size, mode, type, link target, modification time, link count and owner (`find -printf`, fields separated by NUL); the `sha256sum` of every file; extended attributes; and, as the agent's user, `git status --porcelain`, `HEAD` and the hash of `git diff`.
- **The same in all four:** no entry on one side only; every file's content; size, mode, type, link target, modification time and owner of every file and link; every file has one link; no extended attribute; the output of git (no status line).
- **Different, as in pandas and playwright:** the link count of every folder (old 1, new the real count), and the entry size of some folders (ruff 13, duckdb 2, kubernetes 52, home-assistant 106). Nothing else.
- **The old step costs more than we posted.** It is 8 minutes a run in duckdb and 11 in kubernetes too, not only in home-assistant. The times are under the load of two streams and one build job.
- Scripts and all listings: `~/.cmeval/logs/prepcmp2/` on the PC. Window: 11:47 to 12:32 UTC (in `pressure.log`; these containers have no name in the marks).

**3. #92 is merged: `main` = `da25c74`.** Tests at `8649223` on our Mac: 952 passed, 5 skipped.

**4. How the runs change, without a touch on a batch in progress.**

- A second checkout on the PC: `codemem-runs2` at `da25c74`, with its own environment. Its packages equal those of `codemem-runs` (`uv pip freeze`, 30 packages). `codemem-runs` stays at `739fbe3`.
- `batch.sh` reads the checkout for a new batch from one file and writes it down for that batch (`~/.cmeval/queue/batch-checkout/<run id>`). A batch that starts again keeps the checkout of its first start. So a batch never mixes the two methods, also after a crash.
- The batches in progress (`haiku-ruff-L0`, `haiku-homeassistant-L2`) are written down as the old checkout.
- **Not switched yet.** The file that names the new checkout does not exist. It waits for Andrew's own word (he was asked at 08:06 UTC and is asleep). When he agrees, each stream changes at its next batch. A record names its method: `prep_steps_s` has `copy_swap` and `sync`, or `chown`; `cmeval_commit` is `da25c74` or `739fbe3`.
- What that means for the tables: ruff L0 and home-assistant L0 to L2 have the old step; a later level of the same repo can have the new one. A pair always has one method.

**5. One real pair through the new code, as a check** (not a run of the sample; its own run id `prepcheck-haiku-homeassistant-L0`; kept and archived with home-assistant).

| home-assistant 183382, L0, Haiku | Old step (the sample's pair, 08:00 UTC) | New step (check pair, 12:34 UTC) |
|---|---|---|
| `grep`: preparation | 625 s (chown 605) | 84 s (copy and swap 36, sync 0.4) |
| `codemem`: preparation | 782 s (chown 708) | 72 s (copy and swap 18, sync 0.3) |
| `grep`: turns, tokens, agent seconds | 8, 335,392, 88.9 | 11, 493,142, 111.2 |
| `codemem`: turns, tokens, agent seconds | 7, 315,484, 125.9 | 7, 321,377, 126.1 |
| Both: completed, setup check, config files removed | yes, ok, 13 | yes, ok, 13 |

The pair took 8 minutes; the old pair about 24. One pair says nothing about the agent's seconds.

**6. Your point 3: confirmed.** The runner and the watchdog choose what runs next and start jobs again; they pass the same arguments to `cmeval e2e run`. Checked in the records: the 21 runs since the move to the runner (home-assistant 13, ruff 8) have `cmeval_commit` `739fbe3`, codemem `463171c`, the same limits (150 turns, 3,000 s, 4 CPUs, 16 GB, effort medium), the same harness (Claude Code 2.1.332), prompt frame `v1`, and the step `chown`, as the 26 runs before it.

**7. Sonnet: noted.** A stream starts its Sonnet steps when its own Haiku steps are done. A cut (one hard and one easy task per repo) is decided and posted before a repo's first Sonnet batch. No cut is planned now.

**8. vscode is in the build queue, before ruff's hard tier.** It starts when home-assistant's seed 2 ends (38 of 41 at 12:43 UTC).

- First a sample of 60 of the first collection (seed `b7-vscode-1`: 18 easy, 24 medium, 18 hard by difficulty; 6 are validated already), then 20 tasks of the hard tier. About 14 minutes a build, 2 at a time: about 8 hours.
- Then the screen, the prompts, the sample, the indexes and the blocks. vscode's first runs: not before Nov 29, about 04:00 UTC.

## Checked

- The comparison script on its own output: ruff's result read again after the run.
- `batch.sh` with a stand-in for `cmeval`: no switch file, a batch that began before the switch, a new batch, a checkout that does not exist (it falls back to `codemem-runs` and says so).

## Left

- The switch, after Andrew's word. Then the first records with `copy_swap` are checked before the Mac goes off.
- The home-assistant report (L2 runs now; about 14:30 UTC).

## Blocked on, or needed from others

- **Andrew:** yes or no to the change of the runs.
- **Andre:** nothing. Tell us if a level of a repo with the old step and a later level with the new step is a problem for a table; the alternative is a change only at the start of a repo.

## Next

- Andrew, with Claude Code: the switch when Andrew agrees; the home-assistant report; the hours of the drive, posted before the Mac goes off.
