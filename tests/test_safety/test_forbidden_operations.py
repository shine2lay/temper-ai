"""Tests for forbidden operations pattern type mismatch fix (code-high-pattern-mismatch-17)."""
import pytest
from src.safety.forbidden_operations import ForbiddenOperationsPolicy
from src.safety.interfaces import ViolationSeverity


class TestPatternMetadataTypeFix:
    """Test that custom patterns are stored as strings and compiled correctly without type mismatches."""

    def test_custom_pattern_stored_as_string(self):
        """Test that custom patterns are stored as strings (not dicts)."""
        config = {
            "custom_forbidden_patterns": {
                "test_pattern": r"dangerous_command"
            }
        }

        policy = ForbiddenOperationsPolicy(config)

        # Verify pattern stored as string
        assert "test_pattern" in policy.custom_forbidden_patterns
        pattern_str = policy.custom_forbidden_patterns["test_pattern"]
        assert isinstance(pattern_str, str)
        assert pattern_str == r"dangerous_command"

    def test_pattern_compilation_no_type_mismatch(self):
        """Test that patterns compile without accessing them as dicts (the bug)."""
        config = {
            "custom_forbidden_patterns": {
                "pattern1": r"dangerous1",
                "pattern2": r"dangerous2"
            }
        }

        policy = ForbiddenOperationsPolicy(config)

        # Get compiled patterns - this should NOT crash with type mismatch
        # Before fix: Would try to access pattern_str["pattern"] and crash
        # After fix: Correctly treats pattern as string
        compiled = policy.compiled_patterns

        # Verify both patterns were compiled
        assert "custom_pattern1" in compiled
        assert "custom_pattern2" in compiled

        # Verify compiled pattern structure has expected metadata
        assert "regex" in compiled["custom_pattern1"]
        assert "message" in compiled["custom_pattern1"]
        assert "severity" in compiled["custom_pattern1"]
        assert compiled["custom_pattern1"]["category"] == "custom"

    def test_invalid_pattern_non_string(self):
        """Test that non-string pattern values are rejected."""
        config = {
            "custom_forbidden_patterns": {
                "bad_pattern": 123  # Invalid: must be string
            }
        }

        with pytest.raises(ValueError, match="must be a string"):
            ForbiddenOperationsPolicy(config)

    def test_pattern_validation_end_to_end(self):
        """Test end-to-end: pattern stored as string, compiled, and detects violations."""
        config = {
            "custom_forbidden_patterns": {
                "test_rm": r"rm\s+-rf\s+/"
            }
        }

        policy = ForbiddenOperationsPolicy(config)

        # Test detection
        action = {
            "command": "rm -rf /tmp/test",
            "tool": "bash"
        }

        result = policy.validate(action, context={})

        # Should detect the custom pattern
        assert not result.valid
        assert len(result.violations) > 0

    def test_multiple_custom_patterns(self):
        """Test that multiple custom patterns all compile correctly."""
        config = {
            "custom_forbidden_patterns": {
                "pattern1": r"danger1",
                "pattern2": r"danger2",
                "pattern3": r"danger3",
            }
        }

        policy = ForbiddenOperationsPolicy(config)

        # All should be stored as strings
        assert all(isinstance(p, str) for p in policy.custom_forbidden_patterns.values())

        # Verify count
        assert len(policy.custom_forbidden_patterns) == 3

        # Verify all compiled without type errors
        compiled = policy.compiled_patterns
        assert "custom_pattern1" in compiled
        assert "custom_pattern2" in compiled
        assert "custom_pattern3" in compiled

    def test_compiled_pattern_default_message(self):
        """Test that default messages are generated correctly during compilation."""
        config = {
            "custom_forbidden_patterns": {
                "my_pattern": r"test_pattern"
            }
        }

        policy = ForbiddenOperationsPolicy(config)
        compiled = policy.compiled_patterns

        # Check default message was generated correctly
        assert "custom_my_pattern" in compiled
        assert "my_pattern" in compiled["custom_my_pattern"]["message"]
        assert compiled["custom_my_pattern"]["message"] == "Custom forbidden pattern: my_pattern"

    def test_compiled_pattern_default_severity(self):
        """Test that default severity is HIGH during compilation."""
        config = {
            "custom_forbidden_patterns": {
                "test": r"pattern"
            }
        }

        policy = ForbiddenOperationsPolicy(config)
        compiled = policy.compiled_patterns

        # Check default severity in compiled pattern
        assert compiled["custom_test"]["severity"] == ViolationSeverity.HIGH

    def test_compiled_pattern_regex_is_compiled(self):
        """Test that compiled patterns have actual compiled regex objects."""
        config = {
            "custom_forbidden_patterns": {
                "test": r"test_regex"
            }
        }

        policy = ForbiddenOperationsPolicy(config)
        compiled = policy.compiled_patterns

        # Verify regex is a compiled Pattern object, not a string
        import re
        assert isinstance(compiled["custom_test"]["regex"], re.Pattern)

    def test_pattern_too_long_rejected(self):
        """Test that patterns >500 chars are rejected."""
        config = {
            "custom_forbidden_patterns": {
                "too_long": "a" * 501
            }
        }

        with pytest.raises(ValueError, match="must be <= 500 characters"):
            ForbiddenOperationsPolicy(config)
