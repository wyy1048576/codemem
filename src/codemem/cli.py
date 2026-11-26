"""`codemem` command line. Human output on stdout, logs/progress on stderr, `--json` for scripts."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import __version__, agents
from .config import SERVE_HOST, SERVE_KEY_ENV, SERVE_PORT, find_repo_root, load_config

# .render, .embedder and .embedserver (and through them the search stack: numpy, faiss) are
# imported inside the commands that need them, so that `codemem hook`, which runs on every Grep
# and Glob, starts fast.


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
    if getattr(args, "no_cache", False):
        svc.config.vector_cache = "off"
    try:
        print(f"indexing {svc.repo_root} -> {svc.index_dir}", file=sys.stderr)
        if svc.copied_from is not None:
            print(f"starting from a copy of {svc.copied_from}", file=sys.stderr)
        indexer = Indexer(svc.repo_root, svc.store, svc.config, progress=_progress_printer(not args.json))
        stats = indexer.update(full=args.full)
        print(file=sys.stderr)
        _print_stats(stats, args.json)
        if getattr(args, "verify", False):
            print("verifying: building a fresh index to compare with ...", file=sys.stderr)
            diff = indexer.verify()
            if diff:
                print(f"the index differs from a fresh build ({len(diff)} differences, first ones):")
                for line in diff[:20]:
                    print(f"  {line}")
                return 1
            print("the index equals a fresh build")
    finally:
        svc.close()
    return 0


def cmd_init(args) -> int:
    repo = find_repo_root(args.path)
    config = load_config(repo)
    names = [a.strip() for a in args.agents.split(",") if a.strip()] if args.agents else []
    actions = agents.plan(
        repo, names, write_agent_notes=not args.no_agent_notes, write_hooks=args.write_hooks, steering=config.steering
    )
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
            f"note: `codemem` is not on PATH, so agents start it as `{sys.executable} -m codemem`; that "
            "works while this environment exists. `uv tool install <path-or-git-url>` (or pipx) makes "
            "a `codemem` command instead.",
            file=sys.stderr,
        )
    if args.no_index and not args.dry_run and not config.embedding.remote:
        _download_model(config)  # so an agent's first search doesn't wait for a download
    if not args.no_index and not args.dry_run:
        args.full = False
        args.json = False
        return cmd_index(args)
    return 0


def _download_model(config) -> None:
    from .embedder import make_embedder

    spec = config.vectors["code"]
    print(f"loading the embedding model {spec.model} (downloaded once, about 1 GB) ...", file=sys.stderr)
    make_embedder(spec, config).embed_documents(["warm up"])


def cmd_search(args) -> int:
    svc = _service(args)
    try:
        if not svc.has_index():
            print(f"no index for {svc.repo_root}; run `codemem index` first", file=sys.stderr)
            return 2
        signals = [s.strip() for s in args.signals.split(",")] if args.signals else None
        kinds = [s.strip() for s in args.kinds.split(",")] if args.kinds else None
        languages = [s.strip() for s in args.language.split(",")] if args.language else None
        options = dict(
            k=args.k, signals=signals, path_prefix=args.path_prefix, kinds=kinds, languages=languages,
            tests="exclude" if args.exclude_tests else args.tests,
        )
        try:
            note = _follow_checkout(svc, args.query, options)
            resp = svc.search(args.query, debug=args.debug, **options)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(resp.to_dict(), indent=2))
        else:
            from .render import format_results

            print(format_results(resp, debug=args.debug, preview=not args.no_preview))
            if args.debug:
                print(f"\n{json.dumps({k: round(v * 1000, 1) for k, v in resp.timings.items()})} (ms)", file=sys.stderr)
        if note:
            print(note, file=sys.stderr)
    finally:
        svc.close()
    return 0


def _follow_checkout(svc, query: str, options: dict) -> str:
    """What `codemem search` does before it answers, so that it never answers for another commit
    without saying so. No server watches for this command: after a `git switch`, a pull or edits
    the index can be behind the checkout. A full check finds that out (the one `codemem status`
    makes), and the index is then updated first, as `codemem index` would: the command waits for
    it, as it waits for the model. Returns what is left to say after the results: the chunks a
    large change left without vectors, or that the index could not be updated."""
    from .embedder import LocalModelUnavailable
    from .indexer import SettingsChanged
    from .render import format_behind, pending_note

    behind = svc.behind(options["signals"])
    if behind is None:
        return ""
    what = f"the index is behind this checkout ({format_behind(behind)})"
    print(f"{what}; updating it first", file=sys.stderr)
    try:
        fresh = svc.follow_checkout(query, **options)
    except (TimeoutError, SettingsChanged, LocalModelUnavailable) as e:
        # Another codemem process holds the index's write lock; or the update would be a rebuild,
        # which a search does not start; or the model that names the vectors cannot run here.
        return (
            f"note: {what} and could not be updated: {str(e).rstrip('.')}. These results are from the index as it "
            "is. Run `codemem index`, then search again."
        )
    return pending_note(fresh, svc.store.pending_paths() if fresh.pending_chunks else (0, []))


def cmd_status(args) -> int:
    svc = _service(args)
    try:
        if args.check_assist:
            return _check_assist(svc, args.json)
        info = svc.status(check_staleness=True)
        from .render import format_status

        print(json.dumps(info, indent=2, default=str) if args.json else format_status(info))
    finally:
        svc.close()
    return 0


def _check_assist(svc, as_json: bool) -> int:
    """`status --check-assist`: 0 when the endpoint can share a build's work, 1 when it cannot, 2
    when the config names none."""
    checker = logging.getLogger("codemem.assist")
    level = checker.level
    if checker.getEffectiveLevel() > logging.DEBUG:  # without -v: its warnings are what the report says
        checker.setLevel(logging.ERROR)
    try:
        reports = svc.check_assist()
    finally:
        checker.setLevel(level)
    if not reports:
        print("error: no assist endpoint to check: the config has no `[embedding.assist]` section", file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(reports, indent=2))
    else:
        from .render import format_assist_check

        print("\n\n".join(format_assist_check(report) for report in reports))
    return 0 if any(report["state"] == "sharing" for report in reports) else 1


def cmd_watch(args) -> int:
    svc = _service(args)
    print(f"catching up {svc.repo_root} ...", file=sys.stderr)
    stats = svc.update()
    if stats:
        _print_stats(stats, False)
    svc.start(prewarm=False)
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


def cmd_languages(args) -> int:
    from .languages import LANGUAGES

    for name, spec in LANGUAGES.items():
        print(f"{name:11s} {' '.join(spec.extensions)}")
    print("(.h is read as C unless it uses C++ syntax)")
    return 0


def cmd_mcp(args) -> int:
    from .server import run_stdio

    run_stdio(args.path, index_dir=args.index_dir)
    return 0


def cmd_hook(args) -> int:
    from .hook import run

    return run(sys.stdin, sys.stdout)


def cmd_serve_embeddings(args) -> int:
    from .embedserver import serve

    config = load_config(find_repo_root(args.path))
    try:
        server = serve(config, host=args.host, port=args.port)
    except (OSError, ValueError) as e:  # the port is taken, or the model cannot be served
        print(f"error: {e}", file=sys.stderr)
        return 2
    served = server.served
    # All of stdout is TOML: the settings of a client, under comments that say where they go.
    print(f"# codemem serve-embeddings: {served.model}, {served.dim} numbers per vector, at {server.url}")
    print("# A codemem embeds through this server with the section below, in ~/.codemem/config.toml or in")
    print("# <repo>/.codemem.toml. From a container or another machine, write the address this machine is")
    print("# reached at in base_url: an index is tied to `space`, not to the address.")
    if server.has_key:
        print(f"# This server asks for a key: a client needs {SERVE_KEY_ENV} in its environment too.")
    print(server.client_config(), flush=True)
    print("# The section above is for a codemem that runs no model of its own: every vector comes from this server.")
    print("# A codemem on another machine that runs this model itself can let this server embed a share of each")
    print("# build instead, and keep its own model for the rest, for searches and for edits. For that, leave the")
    print("# section above out and use these lines, with this machine's address in base_url:")
    print("".join(f"# {line}\n" for line in server.assist_config().splitlines()), flush=True)
    if not server.has_key and args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"warning: {args.host} is not the loopback address and no key is set: whoever can reach it can use "
            f"the model. Set {SERVE_KEY_ENV} to ask for a key.", file=sys.stderr,
        )
    print("serving (Ctrl+C to stop)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
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
    sp.add_argument(
        "--no-agent-notes", action="store_true",
        help="don't append the short codemem note to CLAUDE.md / AGENTS.md (it is appended by default)",
    )
    # The note used to be opt-in. The old flag is still accepted, so that existing commands run.
    sp.add_argument("--write-agent-notes", action="store_true", help=argparse.SUPPRESS)
    sp.add_argument(
        "--write-hooks", action="store_true",
        help="Claude Code: add two hooks to .claude/settings.json that point the agent at search_code when it has no lead",
    )
    sp.add_argument("--dry-run", action="store_true", help="show what would be written")
    sp.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    sp.set_defaults(func=cmd_init)

    sp = common(sub.add_parser("index", help="build or update the index"))
    sp.add_argument("--full", action="store_true", help="rebuild from scratch")
    sp.add_argument("--verify", action="store_true", help="then compare with a fresh build (slow; for checking)")
    sp.add_argument("--no-cache", action="store_true", help="don't reuse vectors from the shared cache (cold timing)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_index)

    sp = common(sub.add_parser("search", help="search the index"), path=False)
    sp.add_argument("query")
    sp.add_argument("-k", type=int, default=10)
    sp.add_argument("--signals", help="comma list, e.g. bm25,code,usage (default: all available)")
    sp.add_argument("--path-prefix", help="only results under this repo-relative path")
    sp.add_argument("--kinds", help="comma list of function,method,class,block (default: all)")
    sp.add_argument("--language", help="comma list of languages (default: all)")
    sp.add_argument("--tests", choices=("include", "exclude", "only"), default="include", help="test code in results")
    sp.add_argument("--exclude-tests", action="store_true", help="same as --tests exclude")
    sp.add_argument("--repo", help="repository (default: git root of the current directory)")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--debug", action="store_true", help="show per-signal ranks and timings")
    sp.add_argument("--no-preview", action="store_true")
    sp.set_defaults(func=cmd_search)

    sp = common(sub.add_parser("status", help="counts, models, indexed commit, staleness"))
    sp.add_argument("--json", action="store_true")
    sp.add_argument(
        "--check-assist", action="store_true",
        help="only compare the [embedding.assist] endpoint's vectors with the local model's, now and without a "
        "build, and print each probe text's numbers and the verdict. Loads the local model unless its vectors for "
        "the probe texts are remembered from an earlier check. Sends codemem's own probe texts, no code of the "
        "repository. Exit status: 0 it can share a build's work, 1 it cannot, 2 no assist is set",
    )
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser(
        "serve-embeddings", help="serve the local embedding model to other codemem processes (OpenAI-style HTTP)"
    )
    sp.add_argument("path", nargs="?", help="repository whose config selects the model (default: the current one)")
    sp.add_argument("--host", default=SERVE_HOST, help=f"address to listen on (default: {SERVE_HOST})")
    sp.add_argument("--port", type=int, default=SERVE_PORT, help=f"port to listen on (default: {SERVE_PORT})")
    sp.set_defaults(func=cmd_serve_embeddings)

    common(sub.add_parser("watch", help="foreground watcher (re-index on save)")).set_defaults(func=cmd_watch)
    common(sub.add_parser("mcp", help="MCP server over stdio (what agents launch)")).set_defaults(func=cmd_mcp)
    sub.add_parser("languages", help="list supported languages and file extensions").set_defaults(func=cmd_languages)
    sub.add_parser(
        "hook", help="Claude Code hooks: point the agent at search_code when it has no lead (see the README)"
    ).set_defaults(func=cmd_hook)
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
    if getattr(args, "index_dir", None):
        args.index_dir = str(Path(args.index_dir).resolve())
    try:
        return args.func(args)
    except TimeoutError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        from .embedder import LocalModelUnavailable  # here, not at the top: see the note there

        if not isinstance(e, LocalModelUnavailable):
            raise
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
