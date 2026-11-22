# Contributing to codemem

For everyone who works in this repo: the three of us, and every coding agent we run (Claude Code,
Codex). Agents follow this file in every session.

## 1. Read first, in this order

1. **[docs/plan/overview.md](docs/plan/overview.md), always.** The question we are answering, the
   dates, and how the three tracks connect.
2. **The plan of your own track** (§2). This is your main job.
3. **The work log** (§4): where each track stands today.

Be aware of the other two tracks as well. You do not have to read them end to end. Read the
places where they meet yours: the table "What passes between the tracks" in the overview (§6), and
the section "What track … needs from, and gives to, the others" in each track file. Much of the
work in this phase is one track waiting on another.

How codemem works today is in [docs/architecture.md](docs/architecture.md). The plan describes
what is not built yet.

## 2. Who does what

| Track | Owner | Plan | In short |
|---|---|---|---|
| **A**, evaluation | Andrew | [docs/plan/track-a-evals.md](docs/plan/track-a-evals.md) | the end-to-end pipeline: an agent with and without codemem, measured by completion, time and tokens |
| **B**, retrieval | Wilson | [docs/plan/track-b-retrieval.md](docs/plan/track-b-retrieval.md) | what codemem stores and how it ranks: keywords, dense vectors, a graph, the embedding options |
| **C**, memory | Andre | [docs/plan/track-c-memory.md](docs/plan/track-c-memory.md) | a small index: shorter vectors, 1-bit codes with exact rescoring |

**Agents:** you work on the track of the person you are working for. If you cannot tell who that
is, ask before you start.

## 3. Working across tracks

- **Announce a change that another track depends on before it lands:** a tool name, the card
  layout, a flag of the pipeline, the vector store interface. The contracts are listed in
  [docs/data-model.md](docs/data-model.md) §12. The work log is where it is announced.
- **B and C keep A informed.** Track A starts on the codemem that exists today, on two or three
  repos. Each time a new piece of retrieval or a new index format works on one repo, say so in
  the log: the configuration name, the commit, what changed at index time, and what it does to
  memory and disk. Track A then indexes its pilot repos again and reruns them. Do not wait for a
  freeze.
- **A keeps B and C informed.** Each time the pipeline changes how B and C use it (a flag, a plan
  file, the format of a result), say so in the log.
- **If you are waiting on someone, write it down** in your track's status file, with the date you
  need it by. That is how the others find the bottleneck.

## 4. The work log

**Why.** Three people and their agents work at the same time. The log is how an agent that starts
a session learns what the others have finished, what is left and where things are stuck, so that
it can tell its user what to work on now.

**Where.** On its own branch, `worklog`, which holds nothing else. It is checked out as a second
folder inside the repo, `.worklog/`, so it can be read and written from any code branch without
switching. Code never goes there, and log entries never go into a code branch.

```
.worklog/
  status/track-a.md    where track A stands now: one screen, rewritten in place
  status/track-b.md
  status/track-c.md
  log/                 one file for each finished piece of work, never edited afterwards
  TEMPLATE.md          the form of an entry
```

**Set up, once per clone:**

```bash
git fetch origin worklog && git worktree add .worklog worklog
```

**At the start of every session, read it:**

```bash
git -C .worklog pull -q --rebase --autostash
cat .worklog/status/*.md
ls .worklog/log | tail -15
```

Then read the entries that are new to you.

**Every time a piece of work is finished, write to it.** "Finished" means any of these: a work
package or a part of one is done; an attempt failed in a way the others should know; something
another track depends on changed; or the session ends with work still open.

1. Add one new file in `log/`, copied from `TEMPLATE.md`. It says what was done, how it was
   checked, what is left, what is blocked and on whom, and what comes next.
2. Rewrite your own track's status file so that it is true again.
3. Publish both:

```bash
git -C .worklog pull -q --rebase --autostash
cp .worklog/TEMPLATE.md ".worklog/log/$(date -u +%Y-%m-%d-%H%M)-a-pipeline-skeleton.md"
# fill in the new entry, and update .worklog/status/track-a.md
git -C .worklog add -A
git -C .worklog commit -qm "log(A): the pipeline skeleton runs one task end to end"
git -C .worklog push -q || { git -C .worklog pull -q --rebase && git -C .worklog push -q; }
```

The file name is the UTC date and time, the track (`a`, `b`, `c` or `shared`) and a few words.

**Rules.**

- **One file per entry, and only your own track's status file.** Two people can then write at the
  same moment without a conflict.
- **Say what is true,** including what failed and what was not checked. "Done" means it was run
  and seen to work, and the entry says how.
- **Entries are never edited or deleted.** Correct a mistake with a new entry.
- **No keys, tokens or private data.** The branch is as visible as the repo.
- **Pushing the `worklog` branch is part of finishing work** and needs no separate go-ahead. This
  holds for that branch only.
- **When your user asks where things stand, what the bottleneck is or what to do next:** read the
  three status files and the newest entries, compare them with the dates in the overview (§8),
  and answer from that.
