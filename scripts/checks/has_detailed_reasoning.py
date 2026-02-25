#!/usr/bin/env python3
"""Check that agents provided detailed reasoning.

Reads JSON from stdin. Checks that every agent's output is at least
MIN_LENGTH characters (substantial reasoning, not a terse answer).
Exits 0 if all agents meet the threshold, 1 otherwise.
"""

import json
import sys

MIN_LENGTH = 500


def main() -> int:
    """Check that all agent outputs meet minimum length."""
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return 1

    stage_outputs = data.get("stage_outputs", {})
    if not isinstance(stage_outputs, dict):
        return 1

    found_agents = False
    for stage in stage_outputs.values():
        if not isinstance(stage, dict):
            continue
        agent_outputs = stage.get("agent_outputs", {})
        if not isinstance(agent_outputs, dict):
            continue
        for agent_data in agent_outputs.values():
            found_agents = True
            if isinstance(agent_data, dict):
                output_len = len(str(agent_data.get("output", "")))
                if output_len < MIN_LENGTH:
                    return 1

    return 0 if found_agents else 1


if __name__ == "__main__":
    sys.exit(main())
