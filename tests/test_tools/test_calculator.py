"""
Unit tests for Calculator tool.

Tests safe mathematical expression evaluation.
"""

import pytest

from temper_ai.tools.calculator import Calculator


class TestCalculatorMetadata:
    """Test calculator metadata."""

    def test_metadata(self):
        """Test calculator metadata is correct."""
        calc = Calculator()
        assert calc.name == "Calculator"
        assert "mathematical expressions" in calc.description.lower()
        assert calc.version == "1.0"

    def test_parameters_schema(self):
        """Test parameters schema."""
        calc = Calculator()
        schema = calc.get_parameters_schema()

        assert schema["type"] == "object"
        assert "expression" in schema["properties"]
        assert schema["required"] == ["expression"]


class TestBasicArithmetic:
    """Test basic arithmetic operations."""

    def test_addition(self):
        """Test addition."""
        calc = Calculator()
        result = calc.execute(expression="2 + 3")

        assert result.success is True
        assert result.result == 5

    def test_subtraction(self):
        """Test subtraction."""
        calc = Calculator()
        result = calc.execute(expression="10 - 4")

        assert result.success is True
        assert result.result == 6

    def test_multiplication(self):
        """Test multiplication."""
        calc = Calculator()
        result = calc.execute(expression="7 * 8")

        assert result.success is True
        assert result.result == 56

    def test_division(self):
        """Test division."""
        calc = Calculator()
        result = calc.execute(expression="15 / 3")

        assert result.success is True
        assert result.result == 5.0

    def test_floor_division(self):
        """Test floor division."""
        calc = Calculator()
        result = calc.execute(expression="17 // 5")

        assert result.success is True
        assert result.result == 3

    def test_modulo(self):
        """Test modulo operation."""
        calc = Calculator()
        result = calc.execute(expression="17 % 5")

        assert result.success is True
        assert result.result == 2

    def test_power(self):
        """Test exponentiation."""
        calc = Calculator()
        result = calc.execute(expression="2 ** 8")

        assert result.success is True
        assert result.result == 256


class TestComplexExpressions:
    """Test complex mathematical expressions."""

    def test_multiple_operations(self):
        """Test expression with multiple operations."""
        calc = Calculator()
        result = calc.execute(expression="(2 + 3) * 4")

        assert result.success is True
        assert result.result == 20

    def test_order_of_operations(self):
        """Test operator precedence."""
        calc = Calculator()
        result = calc.execute(expression="2 + 3 * 4")

        assert result.success is True
        assert result.result == 14  # Not 20

    def test_nested_parentheses(self):
        """Test nested parentheses."""
        calc = Calculator()
        result = calc.execute(expression="((2 + 3) * (4 + 5)) / 3")

        assert result.success is True
        assert result.result == 15.0

    def test_negative_numbers(self):
        """Test negative numbers."""
        calc = Calculator()
        result = calc.execute(expression="-5 + 3")

        assert result.success is True
        assert result.result == -2

    def test_decimal_numbers(self):
        """Test decimal numbers."""
        calc = Calculator()
        result = calc.execute(expression="3.14 * 2")

        assert result.success is True
        assert result.result == pytest.approx(6.28)


class TestMathFunctions:
    """Test mathematical functions."""

    def test_sqrt(self):
        """Test square root."""
        calc = Calculator()
        result = calc.execute(expression="sqrt(16)")

        assert result.success is True
        assert result.result == 4.0

    def test_abs(self):
        """Test absolute value."""
        calc = Calculator()
        result = calc.execute(expression="abs(-10)")

        assert result.success is True
        assert result.result == 10

    def test_round(self):
        """Test rounding."""
        calc = Calculator()
        result = calc.execute(expression="round(3.7)")

        assert result.success is True
        assert result.result == 4

    def test_min(self):
        """Test minimum."""
        calc = Calculator()
        result = calc.execute(expression="min([1, 5, 3])")

        assert result.success is True
        assert result.result == 1

    def test_max(self):
        """Test maximum."""
        calc = Calculator()
        result = calc.execute(expression="max([1, 5, 3])")

        assert result.success is True
        assert result.result == 5

    def test_sum(self):
        """Test sum."""
        calc = Calculator()
        result = calc.execute(expression="sum([1, 2, 3, 4])")

        assert result.success is True
        assert result.result == 10

    def test_sin(self):
        """Test sine function."""
        calc = Calculator()
        result = calc.execute(expression="sin(0)")

        assert result.success is True
        assert result.result == pytest.approx(0.0)

    def test_cos(self):
        """Test cosine function."""
        calc = Calculator()
        result = calc.execute(expression="cos(0)")

        assert result.success is True
        assert result.result == pytest.approx(1.0)

    def test_log(self):
        """Test natural logarithm."""
        calc = Calculator()
        result = calc.execute(expression="log(2.718281828459045)")

        assert result.success is True
        assert result.result == pytest.approx(1.0)

    def test_exp(self):
        """Test exponential function."""
        calc = Calculator()
        result = calc.execute(expression="exp(1)")

        assert result.success is True
        assert result.result == pytest.approx(2.718281828459045)


class TestConstants:
    """Test mathematical constants."""

    def test_pi(self):
        """Test pi constant."""
        calc = Calculator()
        result = calc.execute(expression="pi")

        assert result.success is True
        assert result.result == pytest.approx(3.141592653589793)

    def test_e(self):
        """Test e constant."""
        calc = Calculator()
        result = calc.execute(expression="e")

        assert result.success is True
        assert result.result == pytest.approx(2.718281828459045)

    def test_pi_in_expression(self):
        """Test using pi in calculation."""
        calc = Calculator()
        result = calc.execute(expression="2 * pi")

        assert result.success is True
        assert result.result == pytest.approx(6.283185307179586)

    def test_sin_pi_over_2(self):
        """Test sin(pi/2)."""
        calc = Calculator()
        result = calc.execute(expression="sin(pi / 2)")

        assert result.success is True
        assert result.result == pytest.approx(1.0)


class TestErrorHandling:
    """Test error handling."""

    def test_division_by_zero(self):
        """Test division by zero error."""
        calc = Calculator()
        result = calc.execute(expression="5 / 0")

        assert result.success is False
        assert "division by zero" in result.error.lower()

    def test_invalid_syntax(self):
        """Test invalid syntax error."""
        calc = Calculator()
        result = calc.execute(expression="2 +* 3")

        assert result.success is False
        assert "syntax" in result.error.lower()

    def test_empty_expression(self):
        """Test empty expression error."""
        calc = Calculator()
        result = calc.execute(expression="")

        assert result.success is False
        assert "non-empty" in result.error.lower()

    def test_unsupported_function(self):
        """Test unsupported function error."""
        calc = Calculator()
        result = calc.execute(expression="eval('2 + 2')")

        assert result.success is False
        assert "unsupported" in result.error.lower()

    def test_unsupported_operator(self):
        """Test unsupported operator error."""
        calc = Calculator()
        result = calc.execute(expression="'hello' + 'world'")

        assert result.success is False
        assert (
            "unsupported" in result.error.lower()
            or "not allowed" in result.error.lower()
        )

    def test_variable_assignment(self):
        """Test that variable assignment is not allowed."""
        calc = Calculator()
        result = calc.execute(expression="x = 5")

        assert result.success is False
        assert result.error is not None

    def test_missing_expression(self):
        """Test missing expression parameter."""
        calc = Calculator()
        result = calc.execute()

        assert result.success is False
        assert "expression" in result.error.lower()

    def test_non_string_expression(self):
        """Test non-string expression."""
        calc = Calculator()
        result = calc.execute(expression=123)

        assert result.success is False
        assert "string" in result.error.lower()


class TestSafety:
    """Test safety features."""

    def test_no_eval(self):
        """Test that eval() cannot be called."""
        calc = Calculator()
        result = calc.execute(expression="eval('print(1)')")

        assert result.success is False

    def test_no_exec(self):
        """Test that exec() cannot be called."""
        calc = Calculator()
        result = calc.execute(expression="exec('x = 1')")

        assert result.success is False

    def test_no_import(self):
        """Test that import statements don't work."""
        calc = Calculator()
        result = calc.execute(expression="__import__('os')")

        assert result.success is False

    def test_no_builtins(self):
        """Test that arbitrary builtins cannot be accessed."""
        calc = Calculator()
        result = calc.execute(expression="print('hello')")

        assert result.success is False


class TestLLMSchema:
    """Test LLM function calling schema."""

    def test_to_llm_schema(self):
        """Test conversion to LLM schema."""
        calc = Calculator()
        schema = calc.to_llm_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "Calculator"
        assert "expression" in schema["function"]["parameters"]["properties"]


class TestMetadata:
    """Test result metadata."""

    def test_metadata_includes_expression(self):
        """Test that result includes expression in metadata."""
        calc = Calculator()
        result = calc.execute(expression="2 + 2")

        assert result.success is True
        assert result.metadata["expression"] == "2 + 2"
        assert "result_type" in result.metadata
