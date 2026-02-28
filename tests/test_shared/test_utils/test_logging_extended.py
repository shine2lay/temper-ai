"""Extended tests for logging utilities - sanitization and formatter integration.

Tests cover:
- Sanitization advanced cases
- Formatter integration
"""

import logging

from temper_ai.shared.utils.logging import (
    ConsoleFormatter,
    SecretRedactingFormatter,
    StructuredFormatter,
    _sanitize_for_logging,
)


class TestSanitizationAdvancedCases:
    """Test advanced sanitization edge cases."""

    def test_sanitize_mixed_unicode_control_chars(self):
        """Test sanitization with mixed Unicode and control characters."""
        text = "Normal\u2028Unicode\x00Control\nNewline"
        result = _sanitize_for_logging(text)

        assert "\u2028" not in result  # Unicode line separator escaped
        assert "\x00" not in result  # Null byte escaped
        assert "\n" not in result  # Newline escaped
        assert "\\n" in result

    def test_sanitize_deeply_nested_url_encoding(self):
        """Test sanitization with deeply nested URL encoding."""
        # %25 = %, so %252541 = %2541 = %41 = A
        nested = "%25252541"  # Triple-encoded 'A'
        result = _sanitize_for_logging(nested)

        # Sanitization should either decode or preserve, but not crash
        assert isinstance(result, str) and len(result) > 0

    def test_sanitize_empty_and_none_inputs(self):
        """Test sanitization handles empty and None inputs."""
        assert _sanitize_for_logging("") == ""
        assert _sanitize_for_logging(None) == ""

    def test_sanitize_max_length_truncation(self):
        """Test sanitization truncates at max_length."""
        long_text = "A" * 15000
        result = _sanitize_for_logging(long_text, max_length=1000)

        assert len(result) <= 1020  # 1000 + "[TRUNCATED]"
        assert "[TRUNCATED]" in result


class TestFormatterIntegration:
    """Test formatter integration and interaction."""

    def test_formatters_preserve_log_record_integrity(self):
        """Test formatters don't corrupt log records."""
        formatters = [
            SecretRedactingFormatter(),
            StructuredFormatter(),
            ConsoleFormatter(use_colors=False),
        ]

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message with api_key=secret123",
            args=(),
            exc_info=None,
        )

        original_msg = record.getMessage()

        for formatter in formatters:
            formatted = formatter.format(record)
            assert isinstance(formatted, str)
            assert len(formatted) > 0
            # Original message should be preserved
            assert record.getMessage() == original_msg or "REDACTED" in formatted
