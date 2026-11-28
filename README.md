# codemem work log

This branch holds the team's work log and nothing else. The rules are in `CONTRIBUTING.md` on
`main`, §4.

| Path | What it holds |
|---|---|
| `status/track-a.md`, `status/track-b.md`, `status/track-c.md` | where each track stands now. One screen each, rewritten in place by that track |
| `log/` | one file for each finished piece of work. Never edited afterwards |
| `TEMPLATE.md` | the form of an entry |
| `case-studies.md` | runs worth knowing about before you read a results table. Kept by track C; read it when you analyse results |

Read it from a clone of the repo:

```bash
git -C .worklog pull -q --rebase --autostash
cat .worklog/status/*.md
ls .worklog/log | tail -15
```
