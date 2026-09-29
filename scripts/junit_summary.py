#!/usr/bin/env python3
"""Turn JUnit XML into a summary a human reads once and understands.

A failing run used to say "Process completed with exit code 1" and nothing
else; you had to open the job, scroll a thousand lines of log, and hope the
first failure was the interesting one. This prints every failure, with the
first useful line of each, into the job summary GitHub shows above the log.

    junit_summary.py REPORT.xml [REPORT.xml ...] [--title "Python 3.12"]

Writes Markdown to $GITHUB_STEP_SUMMARY when set, otherwise to stdout, and
exits 0 whatever the tests did: it reports, it does not judge.
"""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

LIMIT = 60  # failures listed in full; the rest are counted


@dataclass
class Case:
    name: str
    kind: str          # failure | error | skipped
    message: str
    time: float = 0.0


@dataclass
class Report:
    total: int = 0
    failed: list[Case] = field(default_factory=list)
    skipped: int = 0
    seconds: float = 0.0


def _first_line(text: str) -> str:
    """The line of a traceback worth putting in a table."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for line in reversed(lines):
        if line.startswith("E ") or ":" in line and line.startswith(("assert", "Assertion")):
            return line.removeprefix("E ").strip()
    for line in reversed(lines):
        if not line.startswith(("+", "-", "_", "=")):
            return line
    return lines[-1] if lines else "(no message)"


def read(paths: list[Path]) -> Report:
    report = Report()
    for path in paths:
        if not path.exists():
            continue
        root = ET.parse(path).getroot()
        for suite in root.iter("testsuite"):
            report.seconds += float(suite.get("time") or 0)
        for case in root.iter("testcase"):
            report.total += 1
            classname = case.get("classname") or ""
            name = f"{classname}::{case.get('name')}" if classname else str(case.get("name"))
            if case.find("skipped") is not None:
                report.skipped += 1
                continue
            for kind in ("failure", "error"):
                node = case.find(kind)
                if node is not None:
                    detail = (node.get("message") or "") + "\n" + (node.text or "")
                    report.failed.append(
                        Case(name, kind, _first_line(detail), float(case.get("time") or 0))
                    )
                    break
    return report


def markdown(report: Report, title: str) -> str:
    passed = report.total - len(report.failed) - report.skipped
    head = f"## {title}\n\n" if title else ""
    if not report.total:
        return f"{head}No tests ran — the report is empty, which is itself a failure.\n"
    if not report.failed:
        return (
            f"{head}**{passed} passed**"
            + (f", {report.skipped} skipped" if report.skipped else "")
            + f" in {report.seconds:.0f}s\n"
        )

    lines = [
        f"{head}**{len(report.failed)} failed**, {passed} passed"
        + (f", {report.skipped} skipped" if report.skipped else "")
        + f" in {report.seconds:.0f}s\n",
        "| Test | What went wrong |",
        "| --- | --- |",
    ]
    for case in report.failed[:LIMIT]:
        message = case.message.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{case.name}` | {message[:180]} |")
    if len(report.failed) > LIMIT:
        lines.append(f"| … | and {len(report.failed) - LIMIT} more |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--title", default="")
    args = parser.parse_args()

    text = markdown(read(args.reports), args.title)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
