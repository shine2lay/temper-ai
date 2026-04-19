"""Calculator tool — safe math evaluation.

Uses AST whitelist approach — no eval(). Only allows arithmetic operations  # noqa
and a small set of math functions.
"""

import ast
import math
import operator
from collections.abc import Callable
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

_ALLOWED_OPERATORS: dict[type, Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_ALLOWED_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "ceil": math.ceil,
    "floor": math.floor,
}

_ALLOWED_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
}

_MAX_EXPONENT = 1000
_MAX_DEPTH = 10


class Calculator(BaseTool):
    """Safe math evaluator using AST whitelist — no eval()."""

    name = "Calculator"
    description = "Evaluate a mathematical expression safely. Supports arithmetic, sqrt, sin, cos, tan, log, exp, abs, round, min, max, pi, e."
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Math expression to evaluate (e.g., '2 * (3 + 4)', 'sqrt(16)', 'sin(pi/2)')",
            },
        },
        "required": ["expression"],
    }
    modifies_state = False

    def execute(self, **params: Any) -> ToolResult:
        expression = params.get("expression", "")
        if not expression or not expression.strip():
            return ToolResult(success=False, result="", error="Empty expression")

        try:
            tree = ast.parse(expression, mode="eval")
            result = _eval_node(tree.body, depth=0)
            return ToolResult(success=True, result=str(result))
        except (ValueError, TypeError, ZeroDivisionError, OverflowError) as e:
            return ToolResult(success=False, result="", error=str(e))
        except Exception as e:
            return ToolResult(
                success=False, result="",
                error=f"Invalid expression: {e}",
            )


def _eval_node(node: ast.AST, depth: int = 0) -> float | int:
    """Recursively evaluate an AST node using only allowed operations."""
    if depth > _MAX_DEPTH:
        raise ValueError(f"Expression too deeply nested (max {_MAX_DEPTH})")

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")

    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_CONSTANTS:
            return _ALLOWED_CONSTANTS[node.id]
        raise ValueError(f"Unknown variable: {node.id}")

    if isinstance(node, ast.UnaryOp):
        op = _ALLOWED_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op(_eval_node(node.operand, depth + 1))

    if isinstance(node, ast.BinOp):
        op = _ALLOWED_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        left = _eval_node(node.left, depth + 1)
        right = _eval_node(node.right, depth + 1)
        # Guard against huge exponents
        if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)):
            if abs(right) > _MAX_EXPONENT:
                raise ValueError(f"Exponent too large: {right} (max {_MAX_EXPONENT})")
        return op(left, right)

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only named function calls allowed")
        func_name = node.func.id
        if func_name not in _ALLOWED_FUNCTIONS:
            raise ValueError(f"Unknown function: {func_name}")
        args = [_eval_node(arg, depth + 1) for arg in node.args]
        return _ALLOWED_FUNCTIONS[func_name](*args)

    raise ValueError(f"Unsupported expression element: {type(node).__name__}")
