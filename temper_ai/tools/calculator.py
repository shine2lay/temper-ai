"""
Calculator tool for safe mathematical expression evaluation.

Uses ast.literal_eval and a whitelist approach to safely evaluate math expressions.
"""
import ast
import math
import operator
from typing import Any, Dict

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult
from temper_ai.tools.constants import (
    MAX_COLLECTION_SIZE,
)
from temper_ai.tools.constants import (
    MAX_EXPONENT as _MAX_EXPONENT,
)
from temper_ai.tools.constants import (
    MAX_NESTING_DEPTH as _MAX_NESTING_DEPTH,
)

# Safe operators allowed in expressions
SAFE_OPERATORS = {
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

# Safe functions allowed in expressions
SAFE_FUNCTIONS = {
    'abs': abs,
    'round': round,
    'min': min,
    'max': max,
    'sum': sum,
    'sqrt': math.sqrt,
    'ceil': math.ceil,
    'floor': math.floor,
    'sin': math.sin,
    'cos': math.cos,
    'tan': math.tan,
    'log': math.log,
    'log10': math.log10,
    'exp': math.exp,
    'pi': math.pi,
    'e': math.e,
}

# Maximum nesting depth for lists/tuples to prevent DoS attacks
MAX_NESTING_DEPTH = _MAX_NESTING_DEPTH

# Maximum exponent value to prevent CPU/memory exhaustion via ** operator
MAX_EXPONENT = _MAX_EXPONENT


class Calculator(BaseTool):
    """
    Safe calculator tool for evaluating mathematical expressions.

    Supports:
    - Basic arithmetic: +, -, *, /, //, %, **
    - Mathematical functions: abs, round, sqrt, sin, cos, tan, log, exp
    - Mathematical constants: pi, e

    Safety:
    - No use of Python eval/exec builtins
    - Whitelist-based AST evaluation
    - No access to built-in functions beyond math
    - Division by zero handling
    """

    def get_metadata(self) -> ToolMetadata:
        """Return calculator tool metadata."""
        return ToolMetadata(
            name="Calculator",
            description="Evaluates mathematical expressions safely. Supports basic arithmetic (+, -, *, /, %, **) and common math functions (sqrt, sin, cos, tan, log, abs, round, min, max).",
            version="1.0",
            category="utility",
            requires_network=False,
            requires_credentials=False,
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Return JSON schema for calculator parameters."""
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical expression to evaluate (e.g., '2 + 2', 'sqrt(16)', 'sin(pi/2)')"
                }
            },
            "required": ["expression"]
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute calculator with given expression.

        Args:
            expression: Mathematical expression to evaluate

        Returns:
            ToolResult with calculated result or error
        """
        expression = kwargs.get("expression", "")

        if not expression or not isinstance(expression, str):
            return ToolResult(
                success=False,
                error="Expression must be a non-empty string"
            )

        # Remove whitespace
        expression = expression.strip()

        try:
            # Parse expression into AST
            tree = ast.parse(expression, mode='eval')

            # Evaluate safely with depth tracking (prevents DoS via deep nesting)
            result = self._safe_eval(tree.body, depth=0)

            return ToolResult(
                success=True,
                result=result,
                metadata={
                    "expression": expression,
                    "result_type": type(result).__name__
                }
            )

        except ZeroDivisionError:
            return ToolResult(
                success=False,
                error="Division by zero"
            )

        except ValueError as e:
            return ToolResult(
                success=False,
                error=f"Invalid value: {str(e)}"
            )

        except SyntaxError as e:
            return ToolResult(
                success=False,
                error=f"Invalid expression syntax: {str(e)}"
            )

        except OverflowError as e:
            return ToolResult(
                success=False,
                error=f"Math error: {str(e)}"
            )

        except (TypeError, AttributeError) as e:
            return ToolResult(
                success=False,
                error=f"Evaluation error: {str(e)}"
            )

    def _eval_constant(self, node: ast.Constant) -> Any:
        """Evaluate a constant node."""
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value)}")

    def _eval_binop(self, node: ast.BinOp, depth: int) -> Any:
        """Evaluate a binary operation node."""
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")

        left = self._safe_eval(node.left, depth + 1)
        right = self._safe_eval(node.right, depth + 1)

        # Bound exponents to prevent CPU/memory exhaustion
        if op_type is ast.Pow:
            if isinstance(right, (int, float)) and abs(right) > MAX_EXPONENT:
                raise ValueError(
                    f"Exponent {right} exceeds maximum allowed value of {MAX_EXPONENT}. "
                    f"This prevents denial-of-service attacks via large exponentiation."
                )

        op_func = SAFE_OPERATORS[op_type]
        return op_func(left, right)  # type: ignore[operator]

    def _eval_unaryop(self, node: ast.UnaryOp, depth: int) -> Any:
        """Evaluate a unary operation node."""
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")

        operand = self._safe_eval(node.operand, depth + 1)
        op_func = SAFE_OPERATORS[op_type]
        return op_func(operand)  # type: ignore[operator]

    def _eval_call(self, node: ast.Call, depth: int) -> Any:
        """Evaluate a function call node."""
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function names are allowed")

        func_name = node.func.id
        if func_name not in SAFE_FUNCTIONS:
            raise ValueError(f"Unsupported function: {func_name}")

        # Evaluate arguments with depth tracking
        args = [self._safe_eval(arg, depth + 1) for arg in node.args]

        # Check for keyword arguments (not supported)
        if node.keywords:
            raise ValueError("Keyword arguments are not supported")

        # Call function
        func = SAFE_FUNCTIONS[func_name]

        # Handle constants (pi, e)
        if callable(func):
            return func(*args)

        # It's a constant, not a function
        if args:
            raise ValueError(f"{func_name} is a constant, not a function")
        return func

    def _eval_name(self, node: ast.Name) -> Any:
        """Evaluate a name (variable) node."""
        name = node.id
        if name not in SAFE_FUNCTIONS:
            raise ValueError(f"Unsupported name: {name}")

        value = SAFE_FUNCTIONS[name]

        # If it's a constant, return it
        if not callable(value):
            return value

        raise ValueError(f"{name} is a function and must be called with ()")

    def _eval_list(self, node: ast.List, depth: int) -> list[Any]:
        """Evaluate a list literal node."""
        # TO-08: Bound list size to prevent DoS via large literals
        if len(node.elts) > MAX_COLLECTION_SIZE:
            raise ValueError(f"List size {len(node.elts)} exceeds maximum of {MAX_COLLECTION_SIZE}")
        # Increment depth for nested lists
        return [self._safe_eval(item, depth + 1) for item in node.elts]

    def _eval_tuple(self, node: ast.Tuple, depth: int) -> tuple[Any, ...]:
        """Evaluate a tuple literal node."""
        # TO-08: Bound tuple size to prevent DoS via large literals
        if len(node.elts) > MAX_COLLECTION_SIZE:
            raise ValueError(f"Tuple size {len(node.elts)} exceeds maximum of {MAX_COLLECTION_SIZE}")
        # Increment depth for nested tuples
        return tuple(self._safe_eval(item, depth + 1) for item in node.elts)

    def _safe_eval(self, node: Any, depth: int = 0) -> Any:
        """
        Safely evaluate AST node using whitelist approach with depth limiting.

        Args:
            node: AST node to evaluate
            depth: Current nesting depth (for DoS prevention)

        Returns:
            Evaluated result (int, float, list, tuple)

        Raises:
            ValueError: If node contains unsafe operations or exceeds max depth
        """
        # Check nesting depth to prevent DoS attacks via deep recursion
        if depth > MAX_NESTING_DEPTH:
            raise ValueError(
                f"Expression nesting depth exceeds maximum of {MAX_NESTING_DEPTH}. "
                f"This prevents denial-of-service attacks via deeply nested structures."
            )

        if isinstance(node, ast.Constant):
            return self._eval_constant(node)
        elif isinstance(node, ast.BinOp):
            return self._eval_binop(node, depth)
        elif isinstance(node, ast.UnaryOp):
            return self._eval_unaryop(node, depth)
        elif isinstance(node, ast.Call):
            return self._eval_call(node, depth)
        elif isinstance(node, ast.Name):
            return self._eval_name(node)
        elif isinstance(node, ast.List):
            return self._eval_list(node, depth)
        elif isinstance(node, ast.Tuple):
            return self._eval_tuple(node, depth)
        else:
            raise ValueError(f"Unsupported AST node type: {type(node).__name__}")
