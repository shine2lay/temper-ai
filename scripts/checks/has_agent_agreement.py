#!/usr/bin/env python3
"""Check that all agents recommend the same option.

Reads JSON from stdin. Looks at each agent's output in
stage_outputs.*.agent_outputs and checks whether all agents mention
the same option (from workflow_inputs.options) in their first 300 chars.
Exits 0 if unanimous, 1 if split.
"""
import json
import sys

PREVIEW_LENGTH = 300


def main() -> int:
    """Check for unanimous agent agreement."""
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return 1

    options = data.get("workflow_inputs", {}).get("options", [])
    if not options:
        return 1

    stage_outputs = data.get("stage_outputs", {})
    if not isinstance(stage_outputs, dict):
        return 1

    # Collect agent output previews from all stages
    previews = []
    for stage in stage_outputs.values():
        if not isinstance(stage, dict):
            continue
        agent_outputs = stage.get("agent_outputs", {})
        if not isinstance(agent_outputs, dict):
            continue
        for agent_data in agent_outputs.values():
            if isinstance(agent_data, dict):
                text = str(agent_data.get("output", ""))[:PREVIEW_LENGTH].lower()
                previews.append(text)

    if not previews:
        return 1

    # For each option, check if ALL agents mention it
    for option in options:
        option_lower = option.lower()
        if all(option_lower in preview for preview in previews):
            return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
