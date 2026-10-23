"""`cmeval` command line. Results on stdout, problems on stderr."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from . import __version__
from .tasks import TaskError, load_tasks

MAX_PROBLEMS_SHOWN = 50

# Commands that exist in the plan but are not built yet.
PLANNED = {
    "import": "import tasks from a public dataset (SWE-bench Verified)",
    "collect": "collect fresh tasks from GitHub issues and fixes",
    "review": "review tasks by hand",
    "run": "run retrieval systems on tasks",
    "score": "score a run",
    "report": "write a report for a scored run",
}


def cmd_validate(args) -> int:
    try:
        tasks = load_tasks(args.file)
    except FileNotFoundError:
        print(f"{args.file}: no such file", file=sys.stderr)
        return 1
    except TaskError as exc:
        for problem in exc.problems[:MAX_PROBLEMS_SHOWN]:
            print(problem, file=sys.stderr)
        if len(exc.problems) > MAX_PROBLEMS_SHOWN:
            print(f"... and {len(exc.problems) - MAX_PROBLEMS_SHOWN} more problems", file=sys.stderr)
        print(f"{args.file}: not valid ({len(exc.problems)} problems)", file=sys.stderr)
        return 1
    print(f"{args.file}: {len(tasks)} tasks, valid")
    for label, counts in (
        ("source", Counter(t.source for t in tasks)),
        ("split", Counter(t.split for t in tasks)),
        ("repo", Counter(t.repo for t in tasks)),
    ):
        print(f"  {label}: " + ", ".join(f"{name} {n}" for name, n in sorted(counts.items())))
    return 0


def cmd_planned(args) -> int:
    print(f"cmeval {args.command}: not built yet", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cmeval", description="Evaluation suite for code retrieval.")
    parser.add_argument("--version", action="version", version=f"cmeval {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check a task file and print counts")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_validate)

    for name, help_text in PLANNED.items():
        p = sub.add_parser(name, help=f"{help_text} (not built yet)")
        p.set_defaults(func=cmd_planned)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    # Commands that are not built yet accept any arguments; built ones are strict.
    if extra and args.func is not cmd_planned:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
