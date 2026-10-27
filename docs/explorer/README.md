# codemem Explorer

An interactive map of every file in this repo and the data flows between them.

- **Open it:** open `index.html` in a browser. It is one self-contained file: no server, no
  internet. From a checkout, its "open the file" links open the repo's files.
- **Tabs:** the system map (click a box to open its parts and files), the big picture (five steps
  from an agent's MCP call to a ranked answer, for presenting: Next, →, or a clicker's PageDown),
  data flows (step by step, with the parts lighting up), and all files as a tree. Press `/` to
  search everything.
- **Rebuild after the repo changes:** `python docs/explorer/build.py` (standard library only). It
  lists the repo's files with git, so the map follows whatever is checked out.
  `--repo PATH` builds from another checkout.
- **Check coverage only:** `python docs/explorer/build.py --check` lists any file that belongs to
  no component (exit code 1), for example a file added since the last build.

| File | What it is |
|---|---|
| `index.html` | the built page (generated, don't edit) |
| `content.json` | all the text: components, map layout, flows, the big picture, a description of every file |
| `template.html` | the app (HTML, CSS, vanilla JS) with a `__DATA__` placeholder |
| `build.py` | fills the template with `content.json` plus facts read from the repo |

A new file still shows up after a rebuild if a component's glob covers it (with what its
docstring says); otherwise `build.py` stops and names it. Add it to a component's `files` in
`content.json`, and a description under `files`, then rebuild.

`--artifact` also writes `artifact.html`, the same page without the doctype, head and body
wrapper, for publishing as a claude.ai artifact. It is not committed.
