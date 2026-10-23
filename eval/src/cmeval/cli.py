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
    "collect": "collect fresh tasks from GitHub issues and fixes",
    "review": "review tasks by hand",
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


def cmd_import(args) -> int:
    from .importers import swebench
    from .paths import default_tasks_dir

    out = args.out or default_tasks_dir() / f"swebv-dev{args.n}.jsonl"
    report = swebench.import_swebench_verified(
        n=args.n,
        seed=args.seed,
        revision=args.revision or swebench.DEFAULT_REVISION,
        out=out,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )
    if report.written:
        print(f"{out}: {len(report.tasks)} tasks written, {len(report.skipped)} rows skipped")
    else:
        print(f"only {len(report.tasks)} of {args.n} tasks found; {out} was not changed", file=sys.stderr)
    for skip in report.skipped:
        print(f"  skipped {skip['id']}: {skip['reason']}")
    for key, value in report.stats.items():
        print(f"  {key}: {value}")
    return 0 if report.written else 1


def cmd_systems(args) -> int:
    from .systems import SystemsError, load_systems, make_system

    try:
        specs = load_systems(args.file)
        systems = [make_system(spec) for spec in specs]
    except FileNotFoundError:
        print(f"{args.file}: no such file", file=sys.stderr)
        return 1
    except SystemsError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{args.file}: {len(systems)} systems")
    for spec, system in zip(specs, systems):
        print(f"  {spec.name:24} adapter={spec.adapter:10} granularity={system.granularity:5} index_key={system.index_key()}")
        system.close()
    return 0


def cmd_run(args) -> int:
    from .repos import RepoError
    from .retriever import RetrieverError
    from .run import RunError, run
    from .systems import SystemsError
    from .tasks import TaskError

    try:
        summary = run(
            args.tasks, args.config, args.run_id,
            split=args.split, repo_filter=args.repo, limit_per_repo=args.limit_per_repo,
            index_mode=args.index_mode, k=args.k, keep_indexes=args.keep_indexes,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
    except (RunError, SystemsError, TaskError, RetrieverError, RepoError, FileNotFoundError) as exc:
        print(f"run {args.run_id}: {exc}", file=sys.stderr)
        return 1
    print(f"run {args.run_id}: {summary.run_dir}")
    print(f"  {summary.tasks} tasks x {summary.systems} systems: {summary.searched} searches done, "
          f"{summary.skipped} already done, {summary.index_calls} index calls, {summary.seconds:.1f} s")
    return 0


def cmd_score(args) -> int:
    from .metrics.tokens import TokenCountError
    from .score import DEFAULT_IOUS, ScoreError, score
    from .tasks import TaskError

    try:
        summary = score(args.run, tokens=args.tokens, ious=tuple(args.iou) if args.iou else DEFAULT_IOUS, tasks_file=args.tasks,
                        warn=lambda message: print(f"warning: {message}", file=sys.stderr),
                        progress=lambda message: print(message, file=sys.stderr, flush=True))
    except (ScoreError, TokenCountError, TaskError) as exc:
        print(f"score {args.run}: {exc}", file=sys.stderr)
        return 1

    def fmt(value, digits=3):
        return "-" if value is None else f"{value:.{digits}f}"

    estimate = "  (token numbers are ESTIMATES, never report them)" if summary.estimate else ""
    print(f"{summary.run_dir}: {summary.tasks_scored} tasks, {summary.rows} rows, tokens by {summary.counter}{estimate}")
    print(f"  {'system':22} {'file R@10':>9} {'file MRR':>8} {'fn R@10':>8} {'fn MRR':>7} {'fn tok->1st':>11} {'search ms':>9}")
    for r in summary.table:
        print(f"  {r['system']:22} {fmt(r['file_recall@10']):>9} {fmt(r['file_mrr']):>8} {fmt(r['function_recall@10']):>8} "
              f"{fmt(r['function_mrr']):>7} {fmt(r['function_tokens_to_first'], 0):>11} {fmt(r['search_ms_median'], 1):>9}")
    print("  (function level at IoU 0.5; '-' = not applicable or not found)")
    return 0


def cmd_report(args) -> int:
    from .report import ReportError, report
    from .score import ScoreError
    from .tasks import TaskError

    try:
        result = report(args.run, baseline=args.baseline, split=args.split, cutoff=args.cutoff, tasks_file=args.tasks)
    except (ReportError, ScoreError, TaskError) as exc:
        print(f"report {args.run}: {exc}", file=sys.stderr)
        return 1
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"{result.report_path}: {result.tasks_scored} tasks")
    if result.primary:
        print(f"  primary metrics vs. {args.baseline} (Holm over {len(result.primary)} tests):")
    for c in result.primary:
        digits = 0 if c.metric == "tokens_to_first" else 3
        diff = "-" if c.diff is None else f"{c.diff:+.{digits}f}"
        p_holm = "-" if c.p_holm is None else f"{c.p_holm:.3f}"
        print(f"  {c.system:22} {c.level} {c.metric:16} n={c.n:<3} diff {diff:>8}  Holm p {p_holm}")
    return 0


def cmd_compare(args) -> int:
    from .compare import CompareError, compare
    from .repos import RepoError
    from .score import ScoreError
    from .tasks import TaskError

    try:
        result = compare(args.run_a, args.run_b, tasks_file=args.tasks)
    except (CompareError, ScoreError, TaskError, RepoError) as exc:
        print(f"compare {args.run_a} {args.run_b}: {exc}", file=sys.stderr)
        return 1
    print(f"update vs. rebuild check: {'PASS' if result.passed else 'FAIL (read the report)'}")
    print(f"  {'system':22} {'tasks':>5} {'same top 10':>11} {'metric diff':>11} {'token diff':>10}  result")
    for s in result.systems:
        print(f"  {s.system:22} {s.tasks:>5} {s.same_top:>5} ({s.share_same_top:>4.0%}) {s.largest_diff:>11.4f} "
              f"{s.largest_relative_diff:>10.2%}  {'pass' if s.passed else 'FAIL'}")
    print(f"  report: {result.report_path}")
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

    p = sub.add_parser("import", help="import tasks from a public dataset")
    p.add_argument("dataset", choices=["swebench-verified"])
    p.add_argument("--n", type=int, default=50, help="number of tasks (default 50)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--revision", default=None, help="dataset revision (default: the pinned one)")
    p.add_argument("--out", type=Path, default=None, help="task file (default: eval/tasks/swebv-dev<n>.jsonl)")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("run", help="run every system in a config on every task")
    p.add_argument("--tasks", type=Path, required=True, help="task file (.jsonl)")
    p.add_argument("--config", type=Path, required=True, help="system config (.toml)")
    p.add_argument("--run-id", required=True, help="name of the run folder in CMEVAL_HOME/runs")
    p.add_argument("--split", choices=["dev", "test"], default="dev", help="default dev; test only at milestones")
    p.add_argument("--repo", action="append", default=None, help="only this repo (owner/name); repeatable")
    p.add_argument("--limit-per-repo", type=int, default=None, help="first N tasks of each repo (by date)")
    p.add_argument("--index-mode", choices=["update", "rebuild"], default="update")
    p.add_argument("--k", type=int, default=50, help="hits for each search (default 50)")
    p.add_argument("--keep-indexes", action="store_true", help="keep index folders after the run")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("score", help="score a run: accuracy, tokens, latency")
    p.add_argument("run", help="run id (in CMEVAL_HOME/runs) or path to a run folder")
    p.add_argument("--tokens", choices=["anthropic", "estimate"], default="anthropic",
                   help="anthropic: count_tokens (key from ANTHROPIC_API_KEY or the Keychain); estimate: rough, never reported")
    p.add_argument("--iou", type=float, action="append", default=None, help="IoU thresholds (default 0.5, 0.3, 0.7)")
    p.add_argument("--tasks", type=Path, default=None,
                   help="tasks file to use instead of the path in meta.json (for runs from another machine; same sha256 required)")
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("report", help="write report.md for a scored run: tables, intervals, paired tests")
    p.add_argument("run", help="run id (in CMEVAL_HOME/runs) or path to a run folder")
    p.add_argument("--baseline", default="grep-fn", help="system for the paired tests (default grep-fn)")
    p.add_argument("--split", choices=["dev", "test"], default="dev", help="must match the run's split; test only at milestones")
    p.add_argument("--cutoff", default="2026-07-01", help="issue date that splits tasks into before and after (default 2026-07-01)")
    p.add_argument("--tasks", type=Path, default=None, help="tasks file to use instead of the path in meta.json (same sha256)")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("compare", help="update vs. rebuild check: compare two scored runs of the same tasks")
    p.add_argument("run_a", help="run id or folder (usually the update run; the report is written here)")
    p.add_argument("run_b", help="run id or folder (usually the rebuild run)")
    p.add_argument("--tasks", type=Path, default=None, help="tasks file to use instead of the path in run A's meta.json")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("systems", help="check a system config and list its systems")
    p.add_argument("file", type=Path)
    p.set_defaults(func=cmd_systems)

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
