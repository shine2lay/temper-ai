#!/usr/bin/env python3
"""Name the tests that both passed and failed — the flaky ones.

A test that fails and then passes on its retry is reported as green, and
that is how "Compare › compares two runs side by side" failed at random for
weeks without anyone being told. A flaky test is a broken test; the rule
here is that it gets fixed, never skipped. This makes it impossible to
overlook by naming it in the job summary.

Two ways to spot one, both supported:

* **one report, retries**: Playwright writes one ``testcase`` per test. With
  PLAYWRIGHT_JUNIT_INCLUDE_RETRIES=1 (as CI sets it) a test that failed and
  then passed on its retry carries a ``flakyFailure`` or ``flakyError`` per
  failed attempt, so it counts as both failed and passed: flaky. A test that
  failed on every attempt carries ``rerunFailure`` or ``rerunError`` for its
  retries next to its ``failure``: a plain failure. Without that setting a
  retry-only pass looks like any other pass.
* **many reports, repeats**: the nightly runs the suite several times; a
  test that failed in one run and passed in another was flaky.

    flaky_report.py REPORT.xml [MORE.xml ...] [--title "Browser tests"]

Exits 1 when it finds one, so a nightly can be marked failed for flakiness
alone; pass --soft to only report.
"""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

FAILED = {"failure", "error", "rerunFailure", "rerunError"}  # the test's result was a failure
FAILED_THEN_PASSED = {"flakyFailure", "flakyError"}  # failed attempts of a test that then passed


def outcomes(paths: list[Path]) -> dict[str, set[str]]:
    """test name -> the set of outcomes seen for it across every report.

    Only element names and the name and classname attributes are read, never
    a message, stack trace or captured output.
    """
    seen: dict[str, set[str]] = defaultdict(set)
    for path in paths:
        if not path.exists():
            continue
        root = ET.parse(path).getroot()
        for case in root.iter("testcase"):
            classname = (case.get("classname") or "").strip()
            name = f"{classname} :: {case.get('name')}" if classname else str(case.get("name"))
            tags = {child.tag for child in case}
            if "skipped" in tags:
                continue
            if tags & FAILED:
                seen[name].add("failed")
                continue
            seen[name].add("passed")
            if tags & FAILED_THEN_PASSED:
                seen[name].add("failed")
    return seen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--title", default="")
    parser.add_argument("--soft", action="store_true", help="report but always exit 0")
    args = parser.parse_args()

    seen = outcomes(args.reports)
    flaky = sorted(name for name, results in seen.items() if results == {"passed", "failed"})
    always_failed = sorted(name for name, results in seen.items() if results == {"failed"})

    title = f"### {args.title} — flaky tests\n\n" if args.title else "### Flaky tests\n\n"
    if flaky:
        lines = [
            title,
            f"**{len(flaky)} test(s) both passed and failed.** A test that needs a retry is "
            "broken; it gets fixed, not skipped.\n",
        ]
        lines += [f"- `{name}`" for name in flaky]
        if always_failed:
            lines.append(f"\n({len(always_failed)} other test(s) failed every time — those are plain failures.)")
        text = "\n".join(lines) + "\n"
    else:
        text = title + "None: every test gave the same answer every time.\n"

    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    sys.stdout.write(text)

    return 1 if flaky and not args.soft else 0


if __name__ == "__main__":
    raise SystemExit(main())
