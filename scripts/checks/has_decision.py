#!/usr/bin/env python3
"""Check that workflow output contains a decision key.

Reads JSON from stdin, checks for 'final_decision' or 'decision'
in stage outputs. Exits 0 (pass) or 1 (fail).
"""
import json
import sys


def main() -> int:
    """Check for decision keys in workflow output."""
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return 1

    text = json.dumps(data)
    if "final_decision" in text or "decision" in text:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
