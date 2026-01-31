"""
Calculator tool for safe mathematical expression evaluation.

Uses ast.literal_eval and a whitelist approach to safely evaluate math expressions.
"""
import ast
import operator
import math
from typing import Dict, Any
from src.tools.base import BaseTool, ToolMetadata, ToolResult


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


class Calculator(BaseTool):
    """
    Safe calculator tool for evaluating mathematical expressions.

    Supports:
    - Basic arithmetic: +, -, *, /, //, %, **
    - Mathematical functions: abs, round, sqrt, sin, cos, tan, log, exp
    - Mathematical constants: pi, e

    Safety:
    - No eval() or exec()
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

            # Evaluate safely
            result = self._safe_eval(tree.body)

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

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Evaluation error: {str(e)}"
            )

    def _safe_eval(self, node: Any) -> Any:
        """
        Safely evaluate AST node using whitelist approach.

        Args:
            node: AST node to evaluate

        Returns:
            Evaluated result (int, float, list, tuple)

        Raises:
            ValueError: If node contains unsafe operations
        """
        if isinstance(node, ast.Constant):  # Number/string literal (Python >= 3.8)
            if isinstance(node.value, (int, float)):
                return node.value
            else:
                raise ValueError(f"Unsupported constant type: {type(node.value)}")

        elif isinstance(node, ast.BinOp):  # Binary operation (e.g., 2 + 3)
            op_type = type(node.op)
            if op_type not in SAFE_OPERATORS:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")

            left = self._safe_eval(node.left)
            right = self._safe_eval(node.right)
            op_func = SAFE_OPERATORS[op_type]

            return op_func(left, right)  # type: ignore[operator]

        elif isinstance(node, ast.UnaryOp):  # Unary operation (e.g., -5)
            op_type = type(node.op)  # type: ignore[assignment]
            if op_type not in SAFE_OPERATORS:
                raise ValueError(f"Unsupported unary operator: {op_type.__name__}")

            operand = self._safe_eval(node.operand)
            op_func = SAFE_OPERATORS[op_type]

            return op_func(operand)  # type: ignore[operator]

        elif isinstance(node, ast.Call):  # Function call (e.g., sqrt(16))
            if not isinstance(node.func, ast.Name):
                raise ValueError("Only simple function names are allowed")

            func_name = node.func.id
            if func_name not in SAFE_FUNCTIONS:
                raise ValueError(f"Unsupported function: {func_name}")

            # Evaluate arguments
            args = [self._safe_eval(arg) for arg in node.args]

            # Check for keyword arguments (not supported)
            if node.keywords:
                raise ValueError("Keyword arguments are not supported")

            # Call function
            func = SAFE_FUNCTIONS[func_name]

            # Handle constants (pi, e)
            if callable(func):
                return func(*args)
            else:
                # It's a constant, not a function
                if args:
                    raise ValueError(f"{func_name} is a constant, not a function")
                return func

        elif isinstance(node, ast.Name):  # Variable name (e.g., pi, e)
            name = node.id
            if name not in SAFE_FUNCTIONS:
                raise ValueError(f"Unsupported name: {name}")

            value = SAFE_FUNCTIONS[name]

            # If it's a constant, return it
            if not callable(value):
                return value

            raise ValueError(f"{name} is a function and must be called with ()")

        elif isinstance(node, ast.List):  # List literal [1, 2, 3]
            return [self._safe_eval(item) for item in node.elts]

        elif isinstance(node, ast.Tuple):  # Tuple literal (1, 2, 3)
            return tuple(self._safe_eval(item) for item in node.elts)

        else:
            raise ValueError(f"Unsupported AST node type: {type(node).__name__}")
