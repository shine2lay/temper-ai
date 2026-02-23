"""
Tests for input validation in safety policies.

This test suite verifies that all safety policies properly validate
their configuration parameters to prevent security vulnerabilities from
malformed configurations.

Security issues prevented:
- Negative value integer overflow/underflow
- Zero value division by zero
- Type confusion attacks
- ReDoS vulnerabilities
- Memory exhaustion from oversized inputs
"""

import pytest

from temper_ai.safety.blast_radius import BlastRadiusPolicy


class TestBlastRadiusPolicyValidation:
    """Test input validation for BlastRadiusPolicy."""

    def test_negative_max_files_rejected(self):
        """Negative max_files should raise ValueError."""
        with pytest.raises(ValueError, match="max_files_per_operation must be >= 1"):
            BlastRadiusPolicy({"max_files_per_operation": -1})

    def test_zero_max_files_rejected(self):
        """Zero max_files should raise ValueError."""
        with pytest.raises(ValueError, match="max_files_per_operation must be >= 1"):
            BlastRadiusPolicy({"max_files_per_operation": 0})

    def test_excessive_max_files_rejected(self):
        """Extremely large max_files should raise ValueError."""
        with pytest.raises(
            ValueError, match="max_files_per_operation must be <= 10000"
        ):
            BlastRadiusPolicy({"max_files_per_operation": 999999999})

    def test_non_numeric_max_files_rejected(self):
        """Non-numeric max_files should raise ValueError."""
        with pytest.raises(
            ValueError, match="max_files_per_operation must be a number"
        ):
            BlastRadiusPolicy({"max_files_per_operation": "invalid"})

    def test_float_max_files_converted(self):
        """Float max_files should be converted to int."""
        policy = BlastRadiusPolicy({"max_files_per_operation": 5.7})
        assert policy.max_files == 5

    def test_nan_max_files_rejected(self):
        """NaN max_files should raise ValueError."""
        # This will fail in the int() conversion
        with pytest.raises(ValueError):
            BlastRadiusPolicy({"max_files_per_operation": float("nan")})

    def test_inf_max_files_rejected(self):
        """Infinite max_files should raise ValueError."""
        with pytest.raises((ValueError, OverflowError)):
            BlastRadiusPolicy({"max_files_per_operation": float("inf")})

    def test_negative_max_lines_rejected(self):
        """Negative max_lines_per_file should raise ValueError."""
        with pytest.raises(ValueError, match="max_lines_per_file must be >= 1"):
            BlastRadiusPolicy({"max_lines_per_file": -100})

    def test_zero_max_lines_rejected(self):
        """Zero max_lines_per_file should raise ValueError."""
        with pytest.raises(ValueError, match="max_lines_per_file must be >= 1"):
            BlastRadiusPolicy({"max_lines_per_file": 0})

    def test_excessive_max_lines_rejected(self):
        """Extremely large max_lines_per_file should raise ValueError."""
        with pytest.raises(ValueError, match="max_lines_per_file must be <= 1000000"):
            BlastRadiusPolicy({"max_lines_per_file": 10000000})

    def test_negative_total_lines_rejected(self):
        """Negative max_total_lines should raise ValueError."""
        with pytest.raises(ValueError, match="max_total_lines must be >= 1"):
            BlastRadiusPolicy({"max_total_lines": -1000})

    def test_negative_entities_rejected(self):
        """Negative max_entities_affected should raise ValueError."""
        with pytest.raises(ValueError, match="max_entities_affected must be >= 1"):
            BlastRadiusPolicy({"max_entities_affected": -50})

    def test_negative_ops_per_minute_rejected(self):
        """Negative max_operations_per_minute should raise ValueError."""
        with pytest.raises(ValueError, match="max_operations_per_minute must be >= 1"):
            BlastRadiusPolicy({"max_operations_per_minute": -10})

    def test_zero_ops_per_minute_rejected(self):
        """Zero max_operations_per_minute should raise ValueError."""
        with pytest.raises(ValueError, match="max_operations_per_minute must be >= 1"):
            BlastRadiusPolicy({"max_operations_per_minute": 0})

    def test_excessive_ops_per_minute_rejected(self):
        """Extremely large max_operations_per_minute should raise ValueError."""
        with pytest.raises(
            ValueError, match="max_operations_per_minute must be <= 1000"
        ):
            BlastRadiusPolicy({"max_operations_per_minute": 10000})

    def test_forbidden_patterns_not_list_rejected(self):
        """Forbidden patterns as non-list should raise ValueError."""
        with pytest.raises(ValueError, match="forbidden_patterns must be a list"):
            BlastRadiusPolicy({"forbidden_patterns": "DELETE FROM"})

    def test_forbidden_patterns_non_string_item_rejected(self):
        """Forbidden patterns with non-string item should raise ValueError."""
        with pytest.raises(
            ValueError, match="forbidden_patterns\\[0\\] must be a string"
        ):
            BlastRadiusPolicy({"forbidden_patterns": [123, "DELETE"]})

    def test_forbidden_patterns_empty_string_rejected(self):
        """Empty pattern strings should raise ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            BlastRadiusPolicy({"forbidden_patterns": ["DELETE FROM", ""]})

    def test_forbidden_patterns_invalid_regex_rejected(self):
        """Invalid regex patterns should raise ValueError."""
        with pytest.raises(ValueError, match="not a valid regex"):
            BlastRadiusPolicy({"forbidden_patterns": ["[invalid("]})

    def test_forbidden_patterns_oversized_list_rejected(self):
        """Oversized pattern list should raise ValueError."""
        huge_list = ["pattern" + str(i) for i in range(1001)]
        with pytest.raises(
            ValueError, match="config list/tuple/set must have <= 1000 items"
        ):
            BlastRadiusPolicy({"forbidden_patterns": huge_list})

    def test_forbidden_patterns_oversized_pattern_rejected(self):
        """Oversized pattern string should raise ValueError."""
        huge_pattern = "x" * 1001
        with pytest.raises(
            ValueError, match="forbidden_patterns\\[\\d+\\] exceeds maximum length"
        ):
            BlastRadiusPolicy({"forbidden_patterns": [huge_pattern]})

    def test_valid_config_accepted(self):
        """Valid configuration should be accepted."""
        policy = BlastRadiusPolicy(
            {
                "max_files_per_operation": 5,
                "max_lines_per_file": 100,
                "max_total_lines": 500,
                "max_entities_affected": 10,
                "max_operations_per_minute": 5,
                "forbidden_patterns": ["DELETE", "DROP"],
            }
        )
        assert policy.max_files == 5
        assert policy.max_lines_per_file == 100
        assert policy.max_total_lines == 500
        assert policy.max_entities == 10
        assert policy.max_ops_per_minute == 5
        assert len(policy.forbidden_patterns) == 2

    def test_default_config_accepted(self):
        """Default configuration should be accepted."""
        policy = BlastRadiusPolicy()
        assert policy.max_files == BlastRadiusPolicy.DEFAULT_MAX_FILES
        assert policy.max_lines_per_file == BlastRadiusPolicy.DEFAULT_MAX_LINES_PER_FILE
        assert policy.max_total_lines == BlastRadiusPolicy.DEFAULT_MAX_TOTAL_LINES
        assert policy.max_entities == BlastRadiusPolicy.DEFAULT_MAX_ENTITIES
        assert policy.max_ops_per_minute == BlastRadiusPolicy.DEFAULT_MAX_OPS_PER_MINUTE
        assert policy.forbidden_patterns == []

    def test_empty_config_accepted(self):
        """Empty configuration dict should use defaults."""
        policy = BlastRadiusPolicy({})
        assert policy.max_files == BlastRadiusPolicy.DEFAULT_MAX_FILES

    @pytest.mark.parametrize("malicious_value", [-1, -999999, 0])
    def test_all_numeric_params_reject_malicious_values(self, malicious_value):
        """All numeric parameters should reject malicious values."""
        params = [
            "max_files_per_operation",
            "max_lines_per_file",
            "max_total_lines",
            "max_entities_affected",
            "max_operations_per_minute",
        ]

        for param in params:
            with pytest.raises(ValueError):
                BlastRadiusPolicy({param: malicious_value})


class TestPolicySecurityValidation:
    """Security-focused validation tests across all policies."""

    @pytest.mark.parametrize(
        "malicious_value", [-1, -999999, 0, float("inf"), float("-inf")]
    )
    def test_numeric_attacks_blocked(self, malicious_value):
        """All malicious numeric values should be blocked."""
        # Test with a reasonable malicious_value first (skip NaN/Inf for int params)
        if malicious_value in (float("inf"), float("-inf")):
            # These should fail during int conversion
            with pytest.raises((ValueError, OverflowError)):
                BlastRadiusPolicy({"max_files_per_operation": malicious_value})
        else:
            with pytest.raises(ValueError):
                BlastRadiusPolicy({"max_files_per_operation": malicious_value})
