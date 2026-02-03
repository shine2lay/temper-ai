"""
Security tests for Calculator DoS prevention via depth limiting.

Tests protection against denial-of-service attacks using deeply nested
list/tuple structures that could cause stack overflow or memory exhaustion.

Attack Example:
    [[[[[[[[[[1]]]]]]]]]]  # 10 levels deep - causes RecursionError without protection
"""

import pytest
from src.tools.calculator import Calculator


class TestCalculatorDepthLimiting:
    """Test depth limiting prevents DoS attacks via nested structures."""

    def test_simple_expression_works(self):
        """Test normal expressions still work."""
        calc = Calculator()

        result = calc.execute(expression="2 + 3")
        assert result.success
        assert result.result == 5

    def test_simple_list_works(self):
        """Test simple lists work."""
        calc = Calculator()

        result = calc.execute(expression="[1, 2, 3]")
        assert result.success
        assert result.result == [1, 2, 3]

    def test_moderately_nested_list_works(self):
        """Test moderately nested structures work (within limit)."""
        calc = Calculator()

        # 5 levels deep - should work (limit is 10)
        result = calc.execute(expression="[[[[[1]]]]]")
        assert result.success
        assert result.result == [[[[[1]]]]]

    def test_max_depth_list_works(self):
        """Test structures at exactly max depth work."""
        calc = Calculator()

        # Exactly 10 levels deep (MAX_NESTING_DEPTH = 10)
        nested = "1"
        for _ in range(10):
            nested = f"[{nested}]"

        result = calc.execute(expression=nested)
        assert result.success

        # Verify correct nesting
        expected = 1
        for _ in range(10):
            expected = [expected]
        assert result.result == expected

    def test_deeply_nested_list_blocked(self):
        """Test deeply nested lists are blocked (DoS prevention)."""
        calc = Calculator()

        # 15 levels deep - exceeds MAX_NESTING_DEPTH=10
        nested = "1"
        for _ in range(15):
            nested = f"[{nested}]"

        result = calc.execute(expression=nested)
        assert not result.success
        assert "nesting depth exceeds maximum" in result.error.lower()

    def test_deeply_nested_tuple_blocked(self):
        """Test deeply nested tuples are blocked (DoS prevention)."""
        calc = Calculator()

        # 15 levels deep - exceeds MAX_NESTING_DEPTH=10
        nested = "1"
        for _ in range(15):
            nested = f"({nested},)"  # Note: comma needed for single-element tuple

        result = calc.execute(expression=nested)
        assert not result.success
        assert "nesting depth exceeds maximum" in result.error.lower()

    def test_mixed_list_tuple_nesting_blocked(self):
        """Test mixed list/tuple nesting counted correctly."""
        calc = Calculator()

        # 15 levels deep with mixed lists and tuples
        nested = "1"
        for i in range(15):
            if i % 2 == 0:
                nested = f"[{nested}]"  # List
            else:
                nested = f"({nested},)"  # Tuple

        result = calc.execute(expression=nested)
        assert not result.success
        assert "nesting depth exceeds maximum" in result.error.lower()

    def test_nested_operations_depth_counted(self):
        """Test nested operations count toward depth."""
        calc = Calculator()

        # Build deeply nested expression with operations
        # [[[[[[[[[[1 + 1]]]]]]]]]]
        nested = "1 + 1"
        for _ in range(15):
            nested = f"[{nested}]"

        result = calc.execute(expression=nested)
        assert not result.success
        assert "nesting depth exceeds maximum" in result.error.lower()

    def test_flat_large_list_works(self):
        """Test flat lists with many elements work (not about depth)."""
        calc = Calculator()

        # Large flat list (1000 elements) - should work
        flat_list = "[" + ", ".join(str(i) for i in range(1000)) + "]"

        result = calc.execute(expression=flat_list)
        assert result.success
        assert len(result.result) == 1000

    def test_error_message_helpful(self):
        """Test error message explains the security limit."""
        calc = Calculator()

        # 15 levels deep
        nested = "1"
        for _ in range(15):
            nested = f"[{nested}]"

        result = calc.execute(expression=nested)
        assert not result.success
        assert "nesting depth" in result.error.lower()
        assert "10" in result.error  # Mentions the limit
        assert "denial-of-service" in result.error.lower() or "dos" in result.error.lower()


class TestCalculatorDoSAttackVectors:
    """Test specific DoS attack patterns are blocked."""

    def test_extreme_nesting_attack_blocked(self):
        """Test extreme nesting (100+ levels) is blocked."""
        calc = Calculator()

        # 100 levels deep - severe attack
        nested = "1"
        for _ in range(100):
            nested = f"[{nested}]"

        result = calc.execute(expression=nested)
        assert not result.success
        assert "nesting depth" in result.error.lower()

    def test_nested_function_calls_depth_counted(self):
        """Test nested function calls count toward depth."""
        calc = Calculator()

        # abs(abs(abs(...abs([[[[[1]]]]])...)))
        nested = "[[[[[[1]]]]]]"  # 6 levels
        for _ in range(10):  # Add 10 more levels via function calls
            nested = f"abs({nested})"

        result = calc.execute(expression=nested)
        assert not result.success
        assert "nesting depth" in result.error.lower()

    def test_nested_binary_operations_depth_counted(self):
        """Test nested binary operations count toward depth."""
        calc = Calculator()

        # Build deeply nested binary ops
        # [[[[[[(1 + 2) * 3] / 4] - 5] + 6] * 7] / 8]...
        nested = "(1 + 2)"
        for i in range(15):
            op = ["+", "-", "*", "/"][i % 4]
            nested = f"[{nested} {op} {i + 3}]"

        result = calc.execute(expression=nested)
        assert not result.success
        assert "nesting depth" in result.error.lower()

    def test_wide_and_deep_structure_depth_limit_still_applies(self):
        """Test that wide structures don't bypass depth limit."""
        calc = Calculator()

        # 15 levels deep, each level has 10 elements
        # [[1,2,3,4,5,6,7,8,9,10], [1,2,3...], ...]
        wide_inner = "[" + ",".join(str(i) for i in range(10)) + "]"
        for _ in range(15):
            wide_inner = f"[{wide_inner}]"

        result = calc.execute(expression=wide_inner)
        assert not result.success
        assert "nesting depth" in result.error.lower()


class TestCalculatorLegitimateUseCases:
    """Test legitimate use cases still work after security fix."""

    def test_mathematical_expressions_work(self):
        """Test normal math expressions work."""
        calc = Calculator()

        test_cases = [
            ("2 + 3 * 4", 14),
            ("(2 + 3) * 4", 20),
            ("sqrt(16) + 4", 8.0),
            ("abs(-5) * 2", 10),
            ("max(1, 2, 3) + min(4, 5, 6)", 7),
        ]

        for expr, expected in test_cases:
            result = calc.execute(expression=expr)
            assert result.success, f"Failed: {expr}"
            assert result.result == expected, f"Wrong result for {expr}"

    def test_lists_and_tuples_within_limit_work(self):
        """Test lists/tuples within depth limit work normally."""
        calc = Calculator()

        test_cases = [
            "[1, 2, 3]",
            "(1, 2, 3)",
            "[[1, 2], [3, 4]]",
            "[1, [2, [3, [4]]]]",  # 4 levels
            "[(1, 2), (3, 4)]",
        ]

        for expr in test_cases:
            result = calc.execute(expression=expr)
            assert result.success, f"Failed: {expr}"

    def test_function_calls_with_lists_work(self):
        """Test functions with list arguments work."""
        calc = Calculator()

        result = calc.execute(expression="sum([1, 2, 3, 4, 5])")
        assert result.success
        assert result.result == 15

        result = calc.execute(expression="max([10, 20, 5, 15])")
        assert result.success
        assert result.result == 20

    def test_constants_work(self):
        """Test mathematical constants work."""
        calc = Calculator()

        result = calc.execute(expression="pi")
        assert result.success
        assert abs(result.result - 3.14159) < 0.001

        result = calc.execute(expression="e")
        assert result.success
        assert abs(result.result - 2.71828) < 0.001


class TestCalculatorDepthLimitBoundary:
    """Test edge cases around the depth limit boundary."""

    def test_exactly_at_limit_works(self):
        """Test expression at exactly MAX_NESTING_DEPTH works."""
        calc = Calculator()

        # Build expression with exactly 10 levels
        nested = "1"
        for _ in range(10):
            nested = f"[{nested}]"

        result = calc.execute(expression=nested)
        assert result.success

    def test_one_over_limit_fails(self):
        """Test expression at MAX_NESTING_DEPTH + 1 fails."""
        calc = Calculator()

        # Build expression with 11 levels
        nested = "1"
        for _ in range(11):
            nested = f"[{nested}]"

        result = calc.execute(expression=nested)
        assert not result.success
        assert "nesting depth" in result.error.lower()

    def test_depth_zero_expressions_work(self):
        """Test simple expressions with no nesting work."""
        calc = Calculator()

        result = calc.execute(expression="42")
        assert result.success
        assert result.result == 42

        result = calc.execute(expression="2 + 2")
        assert result.success
        assert result.result == 4


class TestCalculatorExponentBounding:
    """Test exponent bounding prevents CPU/memory exhaustion via ** operator."""

    def test_small_exponents_pass(self):
        """Test small legitimate exponents work normally."""
        calc = Calculator()

        assert calc.execute(expression="2 ** 10").result == 1024
        assert calc.execute(expression="10 ** 3").result == 1000
        assert calc.execute(expression="3 ** 5").result == 243

    def test_boundary_exponent_passes(self):
        """Test exponent at exactly MAX_EXPONENT (1000) passes."""
        calc = Calculator()

        result = calc.execute(expression="2 ** 1000")
        assert result.success
        assert result.result == 2 ** 1000

    def test_over_boundary_exponent_rejected(self):
        """Test exponent at MAX_EXPONENT + 1 is rejected."""
        calc = Calculator()

        result = calc.execute(expression="2 ** 1001")
        assert not result.success
        assert "exponent" in result.error.lower()
        assert "1000" in result.error

    def test_large_single_exponent_rejected(self):
        """Test very large single exponent is rejected."""
        calc = Calculator()

        result = calc.execute(expression="10 ** 100000000")
        assert not result.success
        assert "exponent" in result.error.lower()

    def test_nested_exponents_rejected(self):
        """Test nested exponents like 9**9**9 are rejected.

        Python parses 9**9**9 as 9**(9**9) = 9**387420489.
        The inner 9**9=387420489 is fine, but the outer exponent
        387420489 exceeds MAX_EXPONENT=1000.
        """
        calc = Calculator()

        result = calc.execute(expression="9 ** 9 ** 9")
        assert not result.success
        assert "exponent" in result.error.lower()

    def test_negative_large_exponent_rejected(self):
        """Test large negative exponents are also rejected."""
        calc = Calculator()

        result = calc.execute(expression="2 ** -1001")
        assert not result.success
        assert "exponent" in result.error.lower()

    def test_normal_arithmetic_unaffected(self):
        """Test that non-exponent arithmetic is completely unaffected."""
        calc = Calculator()

        assert calc.execute(expression="100 + 200").result == 300
        assert calc.execute(expression="999 * 999").result == 998001
        assert calc.execute(expression="1000000 / 3").result == pytest.approx(333333.333, rel=1e-3)
        assert calc.execute(expression="sqrt(144)").result == 12.0

    def test_zero_exponent_passes(self):
        """Test zero exponent is allowed."""
        calc = Calculator()

        result = calc.execute(expression="999 ** 0")
        assert result.success
        assert result.result == 1

    def test_exponent_one_passes(self):
        """Test exponent of 1 is allowed."""
        calc = Calculator()

        result = calc.execute(expression="42 ** 1")
        assert result.success
        assert result.result == 42

    def test_fractional_exponent_passes(self):
        """Test small fractional exponents work (square root via **)."""
        calc = Calculator()

        result = calc.execute(expression="16 ** 0.5")
        assert result.success
        assert result.result == pytest.approx(4.0)

    def test_error_message_informative(self):
        """Test error message explains the security limit."""
        calc = Calculator()

        result = calc.execute(expression="2 ** 9999")
        assert not result.success
        assert "exponent" in result.error.lower()
        assert "1000" in result.error
        assert "denial-of-service" in result.error.lower()


class TestCalculatorSecurityProperties:
    """Test security properties of the depth limiting."""

    def test_depth_limit_prevents_stack_overflow(self):
        """
        Test that depth limit prevents stack overflow.

        Without limit, deeply nested structures would cause RecursionError.
        With limit, we get a controlled error instead.

        Note: With extreme nesting (1000+ levels), Python's AST parser
        may fail first with "too many nested parentheses", which is also
        a valid protection (defense in depth).
        """
        calc = Calculator()

        # This would cause RecursionError without limit
        nested = "1"
        for _ in range(1000):  # Extreme nesting
            nested = f"[{nested}]"

        result = calc.execute(expression=nested)
        assert not result.success
        # Should get controlled error (either our depth limit or parser limit)
        # Both are valid protections
        assert ("nesting depth" in result.error.lower() or
                "too many nested" in result.error.lower())
        assert "recursion" not in result.error.lower()  # Not a recursion error

    def test_depth_limit_prevents_memory_exhaustion(self):
        """
        Test that depth limit prevents memory exhaustion.

        Note: With extreme nesting (500+ levels), Python's AST parser
        may fail first with "too many nested parentheses", which is also
        a valid protection (defense in depth).
        """
        calc = Calculator()

        # Very deep nesting that would consume lots of memory
        nested = "1"
        for _ in range(500):
            nested = f"[{nested}]"

        result = calc.execute(expression=nested)
        assert not result.success
        # Should fail quickly with controlled error (either limit works)
        assert ("nesting depth" in result.error.lower() or
                "too many nested" in result.error.lower())

    def test_fail_secure_behavior(self):
        """Test that failures are secure (don't expose internals)."""
        calc = Calculator()

        # Attack expression
        nested = "1"
        for _ in range(50):
            nested = f"[{nested}]"

        result = calc.execute(expression=nested)
        assert not result.success

        # Error should be informative but not leak internals
        assert "nesting depth" in result.error.lower()
        assert "maximum" in result.error.lower()
        # Should NOT contain stack traces or internal details
        assert "traceback" not in result.error.lower()
        assert "ast." not in result.error.lower()  # No AST internals

    def test_depth_tracking_accurate_across_node_types(self):
        """Test depth is tracked accurately across different AST node types."""
        calc = Calculator()

        # Mix of lists, tuples, operations, function calls
        # Each should increment depth
        nested = "1"
        nested = f"abs({nested})"      # depth 1: function call
        nested = f"[{nested}]"          # depth 2: list
        nested = f"({nested},)"         # depth 3: tuple
        nested = f"{nested} + 1"        # depth 4: binop
        nested = f"-{nested}"           # depth 5: unaryop
        nested = f"[{nested}]"          # depth 6: list
        nested = f"abs({nested})"       # depth 7: function call
        nested = f"[{nested}]"          # depth 8: list
        nested = f"[{nested}]"          # depth 9: list
        nested = f"[{nested}]"          # depth 10: list
        nested = f"[{nested}]"          # depth 11: list - EXCEEDS

        result = calc.execute(expression=nested)
        assert not result.success
        assert "nesting depth" in result.error.lower()
