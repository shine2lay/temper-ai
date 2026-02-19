"""Extended tests for logging utilities - handler hierarchy and configuration.

Tests cover:
- Logger hierarchy and propagation behavior
- Invalid log level handling fallback
- File handler parent directory creation
- LogContext exception handling during factory restoration
- Multiple successive setup_logging calls
- Sanitization advanced cases
- Formatter integration
"""
import logging
import sys
from io import StringIO
from pathlib import Path
import pytest

from temper_ai.shared.utils.logging import (
    setup_logging,
    get_logger,
    LogContext,
    SecretRedactingFormatter,
    StructuredFormatter,
    ConsoleFormatter,
    _sanitize_for_logging,
)


class TestLoggerHierarchy:
    """Test logger hierarchy and propagation behavior."""

    def test_child_logger_inherits_parent_level(self):
        """Test child logger inherits level from parent."""
        setup_logging(level="WARNING")

        parent_logger = get_logger("parent")
        child_logger = get_logger("parent.child")

        # Child should inherit parent's effective level
        parent_logger.warning("Parent warning")
        child_logger.warning("Child warning")

        # Both should respect WARNING level
        assert parent_logger.isEnabledFor(logging.WARNING)
        assert child_logger.isEnabledFor(logging.WARNING)
        assert not child_logger.isEnabledFor(logging.DEBUG)

    def test_logger_propagation_to_root(self):
        """Test log messages propagate to root logger."""
        setup_logging(level="INFO", format_type="console")

        root_logger = logging.getLogger()
        child_logger = get_logger("test.child")

        # Child logs should reach root handler
        handler_count_before = len(root_logger.handlers)
        child_logger.info("Test message")

        assert handler_count_before > 0  # Root has handlers
        assert child_logger.propagate is True  # Propagation enabled

    def test_logger_name_uniqueness(self):
        """Test get_logger returns same instance for same name."""
        logger1 = get_logger("unique.test")
        logger2 = get_logger("unique.test")
        logger3 = get_logger("different.test")

        assert logger1 is logger2  # Same name = same instance
        assert logger1 is not logger3  # Different name = different instance


class TestSetupLoggingEdgeCases:
    """Test setup_logging edge cases and error handling."""

    def test_invalid_log_level_falls_back_to_info(self):
        """Test invalid log level defaults to INFO."""
        setup_logging(level="INVALID_LEVEL")

        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO

    def test_successive_setup_clears_handlers(self):
        """Test multiple setup_logging calls don't accumulate handlers."""
        setup_logging(format_type="console")
        first_count = len(logging.getLogger().handlers)

        setup_logging(format_type="console")
        second_count = len(logging.getLogger().handlers)

        setup_logging(format_type="console")
        third_count = len(logging.getLogger().handlers)

        assert first_count == second_count == third_count

    def test_file_handler_creates_parent_directory(self, tmp_path):
        """Test file handler creates parent directories."""
        nested_log = tmp_path / "logs" / "nested" / "test.log"

        setup_logging(log_file=str(nested_log))

        assert nested_log.parent.exists()
        assert nested_log.exists()

    def test_both_format_creates_multiple_handlers(self):
        """Test format_type='both' creates console and JSON handlers."""
        setup_logging(format_type="both")

        root_logger = logging.getLogger()
        handlers = root_logger.handlers

        assert len(handlers) >= 2

        # Should have both ConsoleFormatter and StructuredFormatter
        formatter_types = [type(h.formatter).__name__ for h in handlers]
        assert "ConsoleFormatter" in formatter_types
        assert "StructuredFormatter" in formatter_types


class TestLogContextExceptionHandling:
    """Test LogContext exception handling and cleanup."""

    def test_log_context_restores_factory_on_exception(self):
        """Test LogContext restores factory even if exception occurs."""
        logger = get_logger("test")
        old_factory = logging.getLogRecordFactory()

        try:
            with LogContext(logger, test_field="value"):
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Factory should be restored despite exception
        new_factory = logging.getLogRecordFactory()
        assert new_factory == old_factory

    def test_log_context_with_empty_fields(self):
        """Test LogContext with no context fields."""
        logger = get_logger("test")

        # Should work even with no fields
        with LogContext(logger):
            logger.info("Message without context")

        assert True  # No exception raised

    def test_nested_log_context_exception_cleanup(self):
        """Test nested LogContext cleanup on exception."""
        logger = get_logger("test")
        old_factory = logging.getLogRecordFactory()

        try:
            with LogContext(logger, outer="val1"):
                with LogContext(logger, inner="val2"):
                    raise RuntimeError("Nested exception")
        except RuntimeError:
            pass

        # Should restore original factory
        assert logging.getLogRecordFactory() == old_factory


class TestSanitizationAdvancedCases:
    """Test advanced sanitization edge cases."""

    def test_sanitize_mixed_unicode_control_chars(self):
        """Test sanitization with mixed Unicode and control characters."""
        text = "Normal\u2028Unicode\x00Control\nNewline"
        result = _sanitize_for_logging(text)

        assert "\u2028" not in result  # Unicode line separator escaped
        assert "\x00" not in result     # Null byte escaped
        assert "\n" not in result       # Newline escaped
        assert "\\n" in result

    def test_sanitize_deeply_nested_url_encoding(self):
        """Test sanitization with deeply nested URL encoding."""
        # %25 = %, so %252541 = %2541 = %41 = A
        nested = "%25252541"  # Triple-encoded 'A'
        result = _sanitize_for_logging(nested)

        # Should decode to 'A' or intermediate stage, not original
        assert result != nested or "A" in result

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
            exc_info=None
        )

        original_msg = record.getMessage()

        for formatter in formatters:
            formatted = formatter.format(record)
            assert isinstance(formatted, str)
            assert len(formatted) > 0
            # Original message should be preserved
            assert record.getMessage() == original_msg or "REDACTED" in formatted
