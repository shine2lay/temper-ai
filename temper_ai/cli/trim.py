"""``temper trim`` — drop old runs' sent material, keep every outcome.

    temper trim --dry-run              what it would do, changing nothing
    temper trim                        do it, using configs/retention
    temper trim --older-than-days 60   override the age for this pass
    temper trim --limit 50             stop after 50 runs (safe to repeat)
    temper trim --log FILE             append one JSON line per pass

Quiet by default: one line of figures on success, nothing else. It never
prints any of the material it drops — only counts and byte totals.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

from temper_ai.database import get_session, init_database
from temper_ai.observability.trim import (
    TrimError,
    TrimReport,
    database_bytes,
    fmt_bytes,
    load_policy,
    run_trim,
    vacuum,
)

DEFAULT_LOG = Path.home() / ".local" / "state" / "temper-trim" / "trim.log"


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "trim",
        help="Drop old runs' sent material (prompts, agent setup); keep every outcome",
    )
    parser.add_argument("--dry-run", action="store_true", help="Say what would be trimmed, change nothing")
    parser.add_argument("--older-than-days", type=int, default=None, help="Override the age from the config")
    parser.add_argument("--keep-recent", type=int, default=None, help="Override how many newest runs of each workflow stay whole")
    parser.add_argument("--limit", type=int, default=None, help="Trim at most this many runs this pass")
    parser.add_argument(
        "--vacuum", action="store_true",
        help="Afterwards, hand the freed space back for reuse (plain VACUUM, never FULL, safe alongside live runs)",
    )
    parser.add_argument("--config-dir", default=None, help="Config directory (default: repo configs/)")
    parser.add_argument("--log", default=None, help=f"Append a JSON line per pass (default: {DEFAULT_LOG})")
    parser.add_argument("--no-log", action="store_true", help="Do not write a log line")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    parser.add_argument("--quiet", action="store_true", help="Print nothing on success")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")


def cmd_trim(args) -> int:
    try:
        policy = load_policy(args.config_dir)
    except TrimError as exc:
        print(f"retention settings: {exc}", file=sys.stderr)
        return 2

    if args.older_than_days is not None:
        policy = replace(policy, older_than_days=args.older_than_days)
    if args.keep_recent is not None:
        policy = replace(policy, keep_recent_per_workflow=args.keep_recent)

    try:
        init_database()
    except Exception as exc:  # a database we cannot reach is not a trim problem
        print(f"trim: could not reach the database: {exc}", file=sys.stderr)
        return 2

    unvacuumed: list[str] = []
    try:
        with get_session() as session:
            report = run_trim(session, policy, limit=args.limit, dry_run=args.dry_run)
            if args.vacuum and not args.dry_run:
                unvacuumed = vacuum(session)
                # Measure the size again: the trim only marks rows dead, and
                # it is the vacuum that makes the space reusable. Reporting
                # the figure from before it would always show no gain.
                report = replace(report, db_bytes_after=database_bytes(session))
    except TrimError as exc:
        print(f"trim: {exc}", file=sys.stderr)
        return 2

    if not args.no_log:
        _append_log(Path(args.log) if args.log else DEFAULT_LOG, report)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    elif not args.quiet:
        print(_summary(report))

    if unvacuumed:
        # Not fatal: the rows are gone and autovacuum will catch up. Say it
        # anyway, because the size in the report will look worse than it is.
        print(
            f"trim: could not vacuum {', '.join(unvacuumed)} "
            "(autovacuum will hand the space back); the trimming itself is done",
            file=sys.stderr,
        )

    if report.stats.runs_failed:
        # Quiet must not mean silent about breakage. A pass where every run
        # failed once read as "nothing to do"; now it says so and exits 1, so
        # the weekly timer marks the unit failed and someone sees it.
        print(
            f"trim: {report.stats.runs_failed} runs could not be trimmed and were left whole",
            file=sys.stderr,
        )
        return 1
    return 0


def _summary(report: TrimReport) -> str:
    stats = report.stats
    head = "would trim" if report.dry_run else "trimmed"
    parts = [
        f"{report.database}: {head} {stats.runs_trimmed} of {stats.runs_scanned} runs",
        f"{stats.events_trimmed} events",
        f"{stats.checkpoints_trimmed} checkpoints",
        f"freed {fmt_bytes(stats.bytes_freed)}",
    ]
    if report.db_bytes_before is not None and report.db_bytes_after is not None and not report.dry_run:
        parts.append(f"database {fmt_bytes(report.db_bytes_before)} -> {fmt_bytes(report.db_bytes_after)}")
    if stats.runs_failed:
        parts.append(f"{stats.runs_failed} runs FAILED (left whole; see the log)")
    line = ", ".join(parts)
    kept = "; ".join(f"{reason}: {count}" for reason, count in sorted(stats.kept.items()))
    return f"{line}\nkept whole — {kept}" if kept else line


def _append_log(path: Path, report: TrimReport) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(report.as_line() + "\n")
    except OSError as exc:  # a missing log must never lose the work just done
        print(f"trim: could not write the log at {path}: {exc}", file=sys.stderr)
