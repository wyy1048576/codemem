"""`codemem` command line. Human output on stdout, logs/progress on stderr, `--json` for scripts."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import __version__, agents
from .config import find_repo_root, load_config
from .render import format_results, format_status


def _progress_printer(enabled: bool):
    last = {"t": 0.0}

    def report(phase: str, done: int, total: int) -> None:
        if not enabled or phase == "done":
            return
        now = time.monotonic()
        if now - last["t"] > 0.5 or done == 0:
            last["t"] = now
            print(f"\r{phase}: {done}/{total}   ", end="", file=sys.stderr, flush=True)

    return report


def _service(args):
    from .service import CodememService

    repo = getattr(args, "path", None) or getattr(args, "repo", None)
    return CodememService(repo, index_dir=args.index_dir)


def _print_stats(stats, as_json: bool) -> None:
    if as_json:
        print(json.dumps(stats.to_dict(), indent=2))
        return
    t = stats.timings
    print(
        f"indexed {stats.files_scanned} files ({stats.files_changed} changed, {stats.files_deleted} deleted); "
        f"chunks +{stats.chunks_added} ~{stats.chunks_updated} -{stats.chunks_deleted}; edges {stats.edges}; "
        f"embedded {stats.embedded} in {t.get('total', 0):.2f}s "
        f"(chunk {t.get('chunk', 0):.2f}s, embed {t.get('embed', 0):.2f}s)"
    )
    for err in stats.errors:
        print(f"  error: {err}", file=sys.stderr)


def cmd_index(args) -> int:
    from .indexer import Indexer

    svc = _service(args)
    try:
        print(f"indexing {svc.repo_root} -> {svc.index_dir}", file=sys.stderr)
        stats = Indexer(
            svc.repo_root, svc.store, svc.config, progress=_progress_printer(not args.json)
        ).update(full=args.full)
        print(file=sys.stderr)
        _print_stats(stats, args.json)
    finally:
        svc.close()
    return 0


def cmd_init(args) -> int:
    repo = find_repo_root(args.path)
    config = load_config(repo)
    names = [a.strip() for a in args.agents.split(",") if a.strip()] if args.agents else []
    actions = agents.plan(repo, names, write_agent_notes=args.write_agent_notes, steering=config.steering)
    print(f"repo: {repo}")
    for a in actions:
        print(f"- {a.agent}: {a.description}")
        if not a.writes:
            print("\n" + a.content)
    writes = [a for a in actions if a.writes]
    if writes:
        if args.dry_run:
            for a in writes:
                print(f"\n--- would write {a.path} ---\n{a.content}")
            print("(dry run: nothing written)")
        else:
            ok = args.yes or input(f"Write {len(writes)} file(s)? [y/N] ").strip().lower() in ("y", "yes")
            if ok:
                for p in agents.apply(writes):
                    print(f"wrote {p}")
            else:
                print("skipped writing agent config")
    if names and not agents.command_on_path():
        print(
            "warning: `codemem` is not on PATH, so agents can't launch it. Install with "
            "`uv tool install <path-or-git-url>` (or pipx).",
            file=sys.stderr,
        )
    if not args.no_index and not args.dry_run:
        args.full = False
        args.json = False
        return cmd_index(args)
    return 0


def cmd_search(args) -> int:
    svc = _service(args)
    try:
        if not svc.has_index():
            print(f"no index for {svc.repo_root}; run `codemem index` first", file=sys.stderr)
            return 2
        signals = [s.strip() for s in args.signals.split(",")] if args.signals else None
        try:
            resp = svc.search(args.query, k=args.k, signals=signals, path_prefix=args.path_prefix, debug=args.debug)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(resp.to_dict(), indent=2))
        else:
            print(format_results(resp, debug=args.debug, preview=not args.no_preview))
            if args.debug:
                print(f"\n{json.dumps({k: round(v * 1000, 1) for k, v in resp.timings.items()})} (ms)", file=sys.stderr)
    finally:
        svc.close()
    return 0


def cmd_status(args) -> int:
    svc = _service(args)
    try:
        info = svc.status(check_staleness=True)
        print(json.dumps(info, indent=2, default=str) if args.json else format_status(info))
    finally:
        svc.close()
    return 0


def cmd_watch(args) -> int:
    svc = _service(args)
    print(f"catching up {svc.repo_root} ...", file=sys.stderr)
    stats = svc.update()
    if stats:
        _print_stats(stats, False)
    svc.start_watcher()
    print("watching for changes (Ctrl+C to stop)", file=sys.stderr)
    seen = svc.last_stats
    try:
        while True:
            time.sleep(0.2)
            if svc.last_stats is not seen:
                seen = svc.last_stats
                _print_stats(seen, False)
    except KeyboardInterrupt:
        pass
    finally:
        svc.close()
    return 0


def cmd_mcp(args) -> int:
    from .server import run_stdio

    run_stdio(args.path, index_dir=args.index_dir)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="codemem", description="Local hybrid code search for coding agents.")
    p.add_argument("--version", action="version", version=f"codemem {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging to stderr")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, path=True):
        if path:
            sp.add_argument("path", nargs="?", help="repository (default: git root of the current directory)")
        sp.add_argument("--index-dir", help="index location (default: ~/.codemem/indexes/<repo>-<hash>)")
        return sp

    sp = common(sub.add_parser("init", help="register with agents and build the index"))
    sp.add_argument("--agents", default="claude", help="comma list of claude,cursor,codex (default: claude)")
    sp.add_argument("--no-index", action="store_true", help="don't build the index now")
    sp.add_argument("--write-agent-notes", action="store_true", help="append a short note to CLAUDE.md / AGENTS.md")
    sp.add_argument("--dry-run", action="store_true", help="show what would be written")
    sp.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    sp.set_defaults(func=cmd_init)

    sp = common(sub.add_parser("index", help="build or update the index"))
    sp.add_argument("--full", action="store_true", help="rebuild from scratch")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_index)

    sp = common(sub.add_parser("search", help="search the index"), path=False)
    sp.add_argument("query")
    sp.add_argument("-k", type=int, default=10)
    sp.add_argument("--signals", help="comma list, e.g. bm25,code,usage (default: all available)")
    sp.add_argument("--path-prefix", help="only results under this repo-relative path")
    sp.add_argument("--repo", help="repository (default: git root of the current directory)")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--debug", action="store_true", help="show per-signal ranks and timings")
    sp.add_argument("--no-preview", action="store_true")
    sp.set_defaults(func=cmd_search)

    sp = common(sub.add_parser("status", help="counts, models, indexed commit, staleness"))
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_status)

    common(sub.add_parser("watch", help="foreground watcher (re-index on save)")).set_defaults(func=cmd_watch)
    common(sub.add_parser("mcp", help="MCP server over stdio (what agents launch)")).set_defaults(func=cmd_mcp)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # Windows consoles default to cp1252; code previews can contain any character.
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    args = build_parser().parse_args(argv)
    if args.command != "mcp":  # the MCP server configures its own stderr logging
        logging.basicConfig(
            stream=sys.stderr, level=logging.DEBUG if args.verbose else logging.WARNING,
            format="codemem %(levelname)s %(message)s",
        )
    if args.index_dir:
        args.index_dir = str(Path(args.index_dir).resolve())
    try:
        return args.func(args)
    except TimeoutError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
