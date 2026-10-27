"""Build index.html: an interactive map of every file in the codemem repo.

The page is one self-contained HTML file (open it in a browser, no server needed). Its text lives
in content.json next to this script; the script adds what it can read from the repo (the list of
files, line counts, Python definitions, Markdown headings, the git commit) and checks that every
file belongs to a component.

    python build.py                # build index.html from the repo this folder is in
    python build.py --repo PATH    # from another checkout of the repo
    python build.py --check        # only check coverage (exit 1 on problems)
    python build.py --artifact     # also write artifact.html, the same page for claude.ai artifacts
"""

from __future__ import annotations

import argparse
import ast
import gzip
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

EXPLORER = Path(__file__).resolve().parent


def default_repo() -> Path:
    """The repo this folder is in (docs/explorer/), else a codemem checkout next to it."""
    try:
        top = subprocess.run(["git", "-C", str(EXPLORER), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
        return Path(top).resolve()
    except (OSError, subprocess.CalledProcessError):
        return EXPLORER.parent / "codemem"


ROOT = default_repo()  # --repo changes it
CONTENT = EXPLORER / "content.json"
TEMPLATE = EXPLORER / "template.html"
OUTPUT = EXPLORER / "index.html"
ARTIFACT = EXPLORER / "artifact.html"  # the copy published to claude.ai


def set_repo(path: Path) -> None:
    global ROOT
    ROOT = Path(path).resolve()
    if not (ROOT / ".git").exists():
        raise SystemExit(f"{ROOT} is not a git checkout; pass --repo PATH")


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def tracked_files() -> list[str]:
    """Files in git, and new files git doesn't ignore."""
    listed = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    return sorted(p for p in listed if p and (ROOT / p).is_file())


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Glob with `**` (any number of folders), `*` (within one folder) and `?`."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def assign(components: list[dict], files: list[str]) -> tuple[dict[str, str], list[str]]:
    """file -> component id. Exact paths win; then the pattern with the longest literal prefix."""
    problems: list[str] = []
    exact: dict[str, str] = {}
    patterns: list[tuple[int, str, re.Pattern[str], str]] = []
    for c in components:
        for entry in c.get("files", []):
            if any(ch in entry for ch in "*?"):
                literal = len(re.split(r"[*?]", entry, maxsplit=1)[0])
                patterns.append((literal, entry, _glob_regex(entry), c["id"]))
            elif entry in exact:
                problems.append(f"{entry} is listed in both {exact[entry]} and {c['id']}")
            else:
                exact[entry] = c["id"]
    known = set(files)
    for path, cid in exact.items():
        if path not in known:
            problems.append(f"{cid} lists {path}, which is not a tracked file")
    patterns.sort(key=lambda p: -p[0])
    owner: dict[str, str] = {}
    for path in files:
        if path in exact:
            owner[path] = exact[path]
            continue
        for _, _, rx, cid in patterns:
            if rx.match(path):
                owner[path] = cid
                break
        else:
            problems.append(f"{path} belongs to no component")
    return owner, problems


def check(content: dict | None = None) -> list[str]:
    """Coverage problems: files with no component, unknown paths, broken references."""
    content = content or json.loads(CONTENT.read_text(encoding="utf-8"))
    files = tracked_files()
    owner, problems = assign(content["components"], files)
    ids = {c["id"] for c in content["components"]}
    if len(ids) != len(content["components"]):
        problems.append("two components share an id")
    for c in content["components"]:
        if c.get("parent") and c["parent"] not in ids:
            problems.append(f"{c['id']} has unknown parent {c['parent']}")
        for r in c.get("related", []):
            if r not in ids:
                problems.append(f"{c['id']} relates to unknown component {r}")
    for e in content["edges"]:
        if e["from"] not in ids or e["to"] not in ids:
            problems.append(f"edge {e['from']} -> {e['to']} names an unknown component")
    known = set(files)
    for f in content["flows"]:
        for s in f["steps"]:
            problems += [f"flow {f['id']}: unknown component {n}" for n in s.get("nodes", []) if n not in ids]
            problems += [f"flow {f['id']}: unknown file {r}" for r in s.get("refs", []) if r.split("::")[0] not in known]
    boxes = {c["id"] for c in content["components"] if c.get("box")}
    edges = {(e["from"], e["to"]) for e in content["edges"]}
    for s in content.get("overview", {}).get("steps", []):
        problems += [f"big picture: {n} is not a box on the map" for n in s["nodes"] if n not in boxes]
        problems += [f"big picture: no map edge {a} -> {b}" for a, b in s["edges"] if (a, b) not in edges and (b, a) not in edges]
    try:  # the built page may not exist yet
        page = OUTPUT.relative_to(ROOT).as_posix()
    except ValueError:
        page = None
    problems += [f"description for {p}, which is not a tracked file" for p in content["files"] if p not in known and p != page]
    return problems


# ---- facts read from the files themselves


def _first_line(doc: str | None) -> str:
    return (doc or "").strip().split("\n", 1)[0].strip()


def python_facts(text: str) -> dict:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    symbols = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            symbols.append({"kind": "class", "name": node.name, "line": node.lineno,
                            "doc": _first_line(ast.get_docstring(node)), "methods": methods})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append({"kind": "def", "name": node.name, "line": node.lineno,
                            "doc": _first_line(ast.get_docstring(node))})
    return {"auto_summary": _first_line(ast.get_docstring(tree)), "symbols": symbols}


def markdown_facts(text: str) -> dict:
    headings, in_code = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and (m := re.match(r"(#{1,3}) +(.+)", line)):
            headings.append([len(m.group(1)), m.group(2).strip()])
    return {"headings": headings[:60]}


def file_facts(path: str) -> dict:
    data = (ROOT / path).read_bytes()
    facts: dict = {"bytes": len(data)}
    if path.endswith(".gz"):
        try:
            facts["lines"] = gzip.decompress(data).count(b"\n")
        except OSError:
            facts["lines"] = None
        return facts
    text = data.decode("utf-8", errors="replace")
    facts["lines"] = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    if path.endswith(".py"):
        facts.update(python_facts(text))
    elif path.endswith(".md"):
        facts.update(markdown_facts(text))
    return facts


def build(artifact: bool = False) -> Path:
    content = json.loads(CONTENT.read_text(encoding="utf-8"))
    problems = check(content)
    if problems:
        raise SystemExit("explorer content has problems:\n  " + "\n  ".join(problems))
    files = tracked_files()
    owner, _ = assign(content["components"], files)
    out_files = {}
    for path in files:
        out_files[path] = {**file_facts(path), **content["files"].get(path, {}), "component": owner[path]}
    by_comp: dict[str, list[str]] = {}
    for path, cid in owner.items():
        by_comp.setdefault(cid, []).append(path)
    components = [{**{k: v for k, v in c.items() if k != "files"}, "files": sorted(by_comp.get(c["id"], []))}
                  for c in content["components"]]
    missing = [p for p in files if not content["files"].get(p, {}).get("summary")]
    if missing:
        print(f"note: {len(missing)} files have no description yet (shown with what the code says):", *missing[:20],
              sep="\n  ", file=sys.stderr)
    data = {
        **{k: v for k, v in content.items() if k not in ("components", "files")},
        "components": components,
        "files": out_files,
        "repo_rel": Path(os.path.relpath(ROOT, EXPLORER)).as_posix() + "/",
        "git": {
            "commit": git("rev-parse", "--short", "HEAD").strip(),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
            "date": git("log", "-1", "--format=%cs").strip(),
        },
        "built": time.strftime("%Y-%m-%d"),
        "stats": {
            "files": len(files),
            "components": len(components),
            "flows": len(content["flows"]),
            "python_lines": sum(f.get("lines") or 0 for p, f in out_files.items() if p.endswith(".py")),
        },
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload)
    OUTPUT.write_text(html, encoding="utf-8", newline="\n")
    if artifact:
        ARTIFACT.write_text(artifact_page(html), encoding="utf-8", newline="\n")
    return OUTPUT


def artifact_page(html: str) -> str:
    """The same page for claude.ai, which adds its own doctype, head and body around it."""
    head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
    head = re.sub(r'<meta (charset|name="viewport")[^>]*>\s*', "", head)
    body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
    return head.strip() + "\n" + body.strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--repo", type=Path, default=ROOT, help=f"the codemem checkout (default: {ROOT})")
    parser.add_argument("--check", action="store_true", help="only check that every file is mapped")
    parser.add_argument("--artifact", action="store_true", help="also write artifact.html (no doctype/head/body wrapper)")
    args = parser.parse_args()
    set_repo(args.repo)
    if args.check:
        problems = check()
        print("\n".join(problems) or "every tracked file is mapped")
        raise SystemExit(1 if problems else 0)
    out = build(artifact=args.artifact)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB) from {ROOT}")


if __name__ == "__main__":
    main()
