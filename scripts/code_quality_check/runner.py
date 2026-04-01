#!/usr/bin/env python3
"""Code quality checker.

Discovers rules, builds context, runs checks in parallel, reports findings.

Usage:
    python -m scripts.code_quality_check.runner [src_dir] [--tags security] [--json]
"""

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.code_quality_check.base import (
    ExternalToolRule,
    Finding,
    Rule,
    ScanContext,
    Severity,
    build_file_cache,
    build_file_list,
    compute_content_hash,
)
from scripts.code_quality_check.rules import discover_rules

logger = logging.getLogger(__name__)

# Severity ordering for display
_SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


def run_check(
    src_dir: Path,
    tags: list[str] | None = None,
) -> dict:
    """Run all rules and return structured results."""
    start = time.monotonic()

    all_rules = discover_rules()
    if tags:
        all_rules = [r for r in all_rules if any(t in r.tags for t in tags)]

    ast_rules = [r for r in all_rules if r.needs_ast]
    external_rules = [r for r in all_rules if isinstance(r, ExternalToolRule)]
    other_rules = [r for r in all_rules if not r.needs_ast and not isinstance(r, ExternalToolRule)]

    files = build_file_list(src_dir)
    file_cache = build_file_cache(files)
    ctx = ScanContext(src_dir=src_dir, files=files, file_cache=file_cache)

    all_findings: list[Finding] = []
    rules_to_run = ast_rules + external_rules + other_rules

    with ThreadPoolExecutor(max_workers=min(len(rules_to_run), 12)) as pool:
        futures = {pool.submit(rule.scan, ctx): rule for rule in rules_to_run}
        for future in as_completed(futures):
            rule = futures[future]
            try:
                all_findings.extend(future.result())
            except Exception as e:
                logger.error("Rule '%s' failed: %s", rule.key, e)

    duration = round(time.monotonic() - start, 2)

    # Sort: severity (critical first), then file, then line
    all_findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f.severity, 99), f.file, f.line))

    # Build summary
    by_severity: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for f in all_findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1

    return {
        "metadata": {
            "src_dir": str(src_dir),
            "timestamp": datetime.now(UTC).isoformat(),
            "duration_seconds": duration,
            "content_hash": compute_content_hash(src_dir),
            "rules_run": [r.key for r in rules_to_run],
            "total_files": len(files),
            "total_lines": ctx.total_lines,
        },
        "findings": [
            {
                "rule": f.rule,
                "severity": f.severity,
                "message": f.message,
                "file": f.file,
                "line": f.line,
                **({"metadata": f.metadata} if f.metadata else {}),
            }
            for f in all_findings
        ],
        "summary": {
            "total": len(all_findings),
            "by_severity": dict(sorted(by_severity.items(), key=lambda x: _SEVERITY_ORDER.get(x[0], 99))),
            "by_rule": dict(sorted(by_rule.items())),
            "rules_with_findings": len(by_rule),
            "rules_clean": len(rules_to_run) - len(by_rule),
        },
    }


def _print_report(result: dict) -> None:
    """Print a human-readable report to stderr."""
    summary = result["summary"]
    meta = result["metadata"]

    print(f"\nCode Quality Report — {meta['total_files']} files, {meta['total_lines']} lines", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)

    if summary["total"] == 0:
        print("\nNo issues found.", file=sys.stderr)
        return

    # Group findings by severity, then by rule
    findings = result["findings"]
    current_severity = None

    for f in findings:
        if f["severity"] != current_severity:
            current_severity = f["severity"]
            count = summary["by_severity"].get(current_severity, 0)
            print(f"\n{current_severity.upper()} ({count})", file=sys.stderr)
            print(f"{'-' * 40}", file=sys.stderr)

        loc = f"{f['file']}:{f['line']}" if f["file"] else "(global)"
        print(f"  {loc:45s} {f['message'][:100]}", file=sys.stderr)

    # Summary footer
    print(f"\n{'=' * 60}", file=sys.stderr)
    print(f"Total: {summary['total']} findings", file=sys.stderr)
    for sev, count in summary["by_severity"].items():
        print(f"  {sev:10s} {count}", file=sys.stderr)
    print(f"\nRules clean: {summary['rules_clean']}/{summary['rules_clean'] + summary['rules_with_findings']}", file=sys.stderr)
    print(f"Duration: {meta['duration_seconds']}s", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Code Quality Checker")
    parser.add_argument("src_dir", nargs="?", default="temper_ai", help="Source directory")
    parser.add_argument("--output", "-o", help="Write JSON to file")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout (default: human-readable)")
    parser.add_argument("--tags", nargs="*", help="Only run rules with these tags")
    parser.add_argument("--max-findings", type=int, default=0, help="Fail if findings exceed this count")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    src_dir = Path(args.src_dir).resolve()
    if not src_dir.is_dir():
        print(f"Error: {src_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    result = run_check(src_dir, tags=args.tags)

    if args.json:
        print(json.dumps(result, indent=2))
    elif args.output:
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        _print_report(result)

    # Gate: fail if too many findings
    if args.max_findings and result["summary"]["total"] > args.max_findings:
        print(
            f"\nFAILED: {result['summary']['total']} findings > max {args.max_findings}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
