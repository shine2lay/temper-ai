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

    if field == "structured":
        return _resolve_structured_field(result, parts[2:])

    simple_fields = {
        "output": result.output,
        "status": result.status,
        "cost_usd": result.cost_usd,
        "total_tokens": result.total_tokens,
        "error": result.error,
    }
    if field in simple_fields:
        return simple_fields[field]

    raise KeyError(f"Unknown field '{field}' on NodeResult")


def _resolve_structured_field(result: NodeResult, subkeys: list[str]) -> object:
    """Traverse structured_output using a list of nested keys."""
    if not subkeys or result.structured_output is None:
        return None
    value: object = result.structured_output
    for key in subkeys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def _apply_operator(actual: object, operator: str, expected: object) -> bool:
    """Apply comparison operator using a dispatch table."""
    dispatch = {
        "equals": lambda a, e: a == e,
        "not_equals": lambda a, e: a != e,
        "exists": lambda a, e: a is not None,
        "not_exists": lambda a, e: a is None,
        "contains": _op_contains,
        "in": _op_in,
    }
    if operator not in dispatch:
        raise ConditionError(f"Unknown operator '{operator}'")
    return dispatch[operator](actual, expected)


def _op_contains(actual: object, expected: object) -> bool:
    """Implements 'contains' operator."""
    if isinstance(actual, str):
        return str(expected) in actual
    if isinstance(actual, (list, dict)):
        return expected in actual
    return False


def _op_in(actual: object, expected: object) -> bool:
    """Implements 'in' operator."""
    if isinstance(expected, (list, tuple)):
        return actual in expected
    return False
