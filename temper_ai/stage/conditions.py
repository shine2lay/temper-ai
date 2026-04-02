"""Condition evaluator for conditional node execution and loop control.

Conditions reference node outputs using dot-notation source paths:
    "node_name.output"              → NodeResult.output
    "node_name.structured.field"    → NodeResult.structured_output["field"]
    "node_name.status"              → NodeResult.status

Operators: equals, not_equals, contains, in, exists
"""

from __future__ import annotations

from temper_ai.shared.types import NodeResult
from temper_ai.stage.exceptions import ConditionError


def evaluate_condition(
    condition: dict,
    node_outputs: dict[str, NodeResult],
) -> bool:
    """Evaluate a condition against node outputs.

    Args:
        condition: Condition dict with "source", "operator", "value" keys.
        node_outputs: Completed node results keyed by node name.

    Returns:
        True if condition is met, False otherwise.

    Raises:
        ConditionError: If condition is malformed or source can't be resolved.
    """
    source = condition.get("source")
    operator = condition.get("operator", "equals")
    expected = condition.get("value")

    if not source:
        raise ConditionError("Condition missing 'source' field")

    try:
        actual = _resolve_source(source, node_outputs)
    except (KeyError, TypeError) as exc:
        raise ConditionError(
            f"Cannot resolve condition source '{source}': {exc}"
        ) from exc

    return _apply_operator(actual, operator, expected)


def _resolve_source(source: str, node_outputs: dict[str, NodeResult]) -> object:
    """Resolve a dot-notation source path to a value.

    Examples:
        "planner.output"            → node_outputs["planner"].output
        "review.structured.verdict" → node_outputs["review"].structured_output["verdict"]
        "review.status"             → node_outputs["review"].status
    """
    parts = source.split(".")
    if len(parts) < 2:
        raise KeyError(f"Source must be 'node_name.field[.subfield]', got '{source}'")

    node_name = parts[0]
    if node_name not in node_outputs:
        raise KeyError(f"Node '{node_name}' not found in outputs")

    result = node_outputs[node_name]
    field = parts[1]

    if field == "output":
        return result.output
    elif field == "status":
        return result.status
    elif field == "structured" and len(parts) >= 3:
        if result.structured_output is None:
            return None
        # Traverse nested fields: structured.verdict, structured.issues.count
        value: object = result.structured_output
        for key in parts[2:]:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value
    elif field == "cost_usd":
        return result.cost_usd
    elif field == "total_tokens":
        return result.total_tokens
    elif field == "error":
        return result.error
    else:
        raise KeyError(f"Unknown field '{field}' on NodeResult")


def _apply_operator(actual: object, operator: str, expected: object) -> bool:
    """Apply comparison operator."""
    if operator == "equals":
        return actual == expected
    elif operator == "not_equals":
        return actual != expected
    elif operator == "contains":
        if isinstance(actual, str):
            return str(expected) in actual
        if isinstance(actual, (list, dict)):
            return expected in actual
        return False
    elif operator == "in":
        if isinstance(expected, (list, tuple)):
            return actual in expected
        return False
    elif operator == "exists":
        return actual is not None
    elif operator == "not_exists":
        return actual is None
    else:
        raise ConditionError(f"Unknown operator '{operator}'")
