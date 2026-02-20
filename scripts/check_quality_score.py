#!/usr/bin/env python3
"""Thin wrapper around architecture_scan.py that exits non-zero if score < threshold."""

import argparse
import json
import subprocess
import sys

DEFAULT_MIN_SCORE = 90


def main() -> None:
    parser = argparse.ArgumentParser(description="Quality score gate")
    parser.add_argument(
        "--min-score",
        type=int,
        default=DEFAULT_MIN_SCORE,
        help=f"Minimum passing score (default: {DEFAULT_MIN_SCORE})",
    )
    parser.add_argument(
        "--src-dir",
        default="temper_ai",
        help="Source directory to scan (default: temper_ai)",
    )
    args = parser.parse_args()

    result = subprocess.run(
        [sys.executable, "scripts/architecture_scan.py", args.src_dir],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Scanner failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(result.stdout)
    score = data["deterministic_score"]["score"]
    grade = data["deterministic_score"]["grade"]

    print(f"Quality score: {score}/100 ({grade})")

    if score < args.min_score:
        print(f"FAILED: score {score} < minimum {args.min_score}", file=sys.stderr)
        sys.exit(1)

    print(f"PASSED: score {score} >= minimum {args.min_score}")


if __name__ == "__main__":
    main()
