#!/usr/bin/env python3
"""Check that workflow output has high synthesis confidence.

Reads JSON from stdin, checks that stage_outputs.*.synthesis.confidence >= 0.8.
Exits 0 (pass) or 1 (fail).

This check is intentionally strict — consensus_weak synthesis typically
produces lower confidence, so this check forces the selection optimizer
to run all iterations and pick the best-scoring output.
"""

import json
import sys

CONFIDENCE_THRESHOLD = 0.8


def main() -> int:
    """Check synthesis confidence in workflow output."""
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return 1

    stage_outputs = data.get("stage_outputs", {})
    if not isinstance(stage_outputs, dict):
        return 1

    for stage in stage_outputs.values():
        if not isinstance(stage, dict):
            continue
        synthesis = stage.get("synthesis", {})
        if isinstance(synthesis, dict):
            confidence = synthesis.get("confidence", 0)
            if (
                isinstance(confidence, (int, float))
                and confidence >= CONFIDENCE_THRESHOLD
            ):
                return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
