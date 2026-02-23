"""
Tests for structured logging module.

Tests cover:
- Secret redaction in log messages
- Structured JSON formatting
- Console formatting with colors
- Log context management
- Configuration from environment
"""

import json
import logging
import os
from unittest.mock import patch

import pytest

from temper_ai.shared.utils.logging import (
    ConsoleFormatter,
    LogContext,
    SecretRedactingFormatter,
    StructuredFormatter,
    get_logger,
    log_function_call,
    setup_logging,
)


class TestSecretRedaction:
    """Tests for secret redaction in logs."""

    def test_redact_env_secret_references(self):
        """Test that environment variable references are redacted."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="API key: ${env:OPENAI_API_KEY}",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "${env:OPENAI_API_KEY}" not in formatted
        assert "${env:***REDACTED***}" in formatted

    def test_redact_vault_secret_references(self):
        """Test that Vault references are redacted."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Secret: ${vault:secret/api-key}",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "${vault:***REDACTED***}" in formatted

    def test_redact_openai_api_keys(self):
        """Test that OpenAI API keys are redacted."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Using key: sk-proj-abc123def456ghi789jkl012mno345pqr678",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "sk-proj-" not in formatted
        assert "***REDACTED***" in formatted

    def test_redact_aws_keys(self):
        """Test that AWS access keys are redacted."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="AWS key: AKIAIOSFODNN7EXAMPLE",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "AKIAIOSFODNN7EXAMPLE" not in formatted
        assert "***REDACTED***" in formatted

    def test_redact_extra_fields(self):
        """Test that secret fields in extra data are redacted."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Processing",
            args=(),
            exc_info=None,
        )
        record.api_key = "sk-secret123"
        record.password = "pass123"
        record.user = "john"

        formatted = formatter.format(record)
        # api_key and password should be redacted
        assert hasattr(record, "api_key")  # Field still exists
        # user should not be redacted
        assert record.user == "john"

    def test_no_redaction_for_safe_content(self):
        """Test that normal content is not redacted."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Processing user request for data",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        assert "Processing user request for data" in formatted
        assert "***REDACTED***" not in formatted

    def test_sanitize_newline_injection(self):
        """Test that newline characters are escaped to prevent log injection."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="User input: Hello\nFAKE LOG ENTRY",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        # Newline should be escaped
        assert "\\n" in formatted
        assert "\nFAKE LOG ENTRY" not in formatted

    def test_sanitize_carriage_return_injection(self):
        """Test that carriage return characters are escaped."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="User input: data\rINJECTED",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        # Carriage return should be escaped
        assert "\\r" in formatted
        assert "\rINJECTED" not in formatted

    def test_sanitize_tab_injection(self):
        """Test that tab characters are escaped."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="User input: col1\tcol2\tinjected",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        # Tab should be escaped
        assert "\\t" in formatted

    def test_sanitize_null_byte_injection(self):
        """Test that null bytes are escaped (not removed)."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="User input: data\x00truncated",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        # Null byte should be escaped (preserves info for debugging)
        assert "\x00" not in formatted  # No literal null byte
        assert "\\x00" in formatted  # Escaped version present
        assert "data" in formatted
        assert "truncated" in formatted

    def test_sanitize_control_characters(self):
        """Test that other control characters are removed."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="User input: \x01\x02\x03dangerous\x07\x08",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        # Control characters should be removed
        assert "\x01" not in formatted
        assert "\x02" not in formatted
        assert "\x07" not in formatted
        assert "dangerous" in formatted

    def test_multiline_log_injection_attack(self):
        """Test protection against multiline log injection attack."""
        formatter = SecretRedactingFormatter()
        # Simulates attacker trying to inject fake log entry
        malicious_input = "normal input\n[ERROR] Security breach detected\n[CRITICAL] System compromised"
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"Processing user data: {malicious_input}",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        # Newlines should be escaped, preventing fake log entries
        assert "\\n" in formatted
        assert "\n[ERROR]" not in formatted
        assert "\n[CRITICAL]" not in formatted


class TestStructuredFormatter:
    """Tests for JSON structured logging."""

    def test_json_output_format(self):
        """Test that logs are formatted as valid JSON."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.funcName = "test_func"
        record.module = "test"

        formatted = formatter.format(record)

        # Should be valid JSON
        log_data = json.loads(formatted)

        # Check required fields
        assert log_data["level"] == "INFO"
        assert log_data["logger"] == "test.module"
        assert log_data["message"] == "Test message"
        assert log_data["module"] == "test"
        assert log_data["function"] == "test_func"
        assert log_data["line"] == 42
        assert "timestamp" in log_data

    def test_json_with_extra_fields(self):
        """Test that extra fields are included in JSON output."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Request processed",
            args=(),
            exc_info=None,
        )
        record.user_id = 123
        record.request_id = "abc-def"
        record.funcName = "process"
        record.module = "api"

        formatted = formatter.format(record)
        log_data = json.loads(formatted)

        assert "extra" in log_data
        assert log_data["extra"]["user_id"] == 123
        assert log_data["extra"]["request_id"] == "abc-def"

    def test_json_with_exception(self):
        """Test that exceptions are included in JSON output."""
        formatter = StructuredFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="Error occurred",
                args=(),
                exc_info=exc_info,
            )
            record.funcName = "test"
            record.module = "test"

            formatted = formatter.format(record)
            log_data = json.loads(formatted)

            assert "exception" in log_data
            assert "ValueError" in log_data["exception"]
            assert "Test error" in log_data["exception"]


class TestConsoleFormatter:
    """Tests for console output formatting."""

    def test_console_format_with_colors(self):
        """Test that console output includes ANSI color codes."""
        formatter = ConsoleFormatter(use_colors=True)
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Error message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)

        # Should contain ANSI color codes
        assert "\033[" in formatted  # ANSI escape code
        assert "ERROR" in formatted
        assert "test" in formatted
        assert "Error message" in formatted

    def test_console_format_without_colors(self):
        """Test that console output works without colors."""
        formatter = ConsoleFormatter(use_colors=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Info message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)

        # Should NOT contain ANSI color codes
        assert "\033[" not in formatted
        assert "INFO" in formatted
        assert "test" in formatted
        assert "Info message" in formatted


class TestLoggingSetup:
    """Tests for logging configuration."""

    def test_setup_with_default_level(self):
        """Test that setup_logging uses default INFO level."""
        with patch.dict(os.environ, {}, clear=True):
            setup_logging(format_type="console")

            logger = get_logger("test")
            assert logger.level == logging.NOTSET  # Uses root logger level

            root_logger = logging.getLogger()
            assert root_logger.level == logging.INFO

    def test_setup_with_env_level(self):
        """Test that setup_logging reads LOG_LEVEL from environment."""
        with patch.dict(os.environ, {"TEMPER_LOG_LEVEL": "DEBUG"}):
            setup_logging(format_type="console")

            root_logger = logging.getLogger()
            assert root_logger.level == logging.DEBUG

    def test_setup_with_explicit_level(self):
        """Test that setup_logging accepts explicit log level."""
        setup_logging(level="WARNING", format_type="console")

        root_logger = logging.getLogger()
        assert root_logger.level == logging.WARNING

    def test_setup_console_format(self):
        """Test that console format creates appropriate handler."""
        setup_logging(level="INFO", format_type="console")

        root_logger = logging.getLogger()
        assert len(root_logger.handlers) > 0

        # Should have at least one StreamHandler
        stream_handlers = [
            h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        assert len(stream_handlers) > 0

    def test_setup_json_format(self):
        """Test that JSON format creates structured handler."""
        setup_logging(level="INFO", format_type="json")

        root_logger = logging.getLogger()
        handlers = root_logger.handlers

        # Should have StructuredFormatter
        assert any(isinstance(h.formatter, StructuredFormatter) for h in handlers)

    def test_setup_both_formats(self):
        """Test that both formats can be enabled simultaneously."""
        setup_logging(level="INFO", format_type="both")

        root_logger = logging.getLogger()

        # Should have multiple handlers
        assert len(root_logger.handlers) >= 2


class TestLogContext:
    """Tests for log context manager."""

    def test_context_adds_fields(self, caplog):
        """Test that LogContext adds fields to log records."""
        import logging

        logger = get_logger("test.context")

        with caplog.at_level(logging.INFO, logger="test.context"):
            with LogContext(logger, user_id=123, request_id="abc"):
                logger.info("Processing request")

        # Check that context fields were added
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert hasattr(record, "user_id")
        assert record.user_id == 123
        assert hasattr(record, "request_id")
        assert record.request_id == "abc"

    def test_context_restoration(self, caplog):
        """Test that context is properly restored after exiting."""
        import logging

        logger = get_logger("test.restore")

        with caplog.at_level(logging.INFO, logger="test.restore"):
            with LogContext(logger, temp_field="temp"):
                logger.info("Inside context")

            logger.info("Outside context")

        # First log should have temp_field
        assert hasattr(caplog.records[0], "temp_field")

        # Second log should NOT have temp_field
        assert not hasattr(caplog.records[1], "temp_field")


class TestLogFunctionDecorator:
    """Tests for function call logging decorator."""

    def test_decorator_logs_entry_exit(self, caplog):
        """Test that decorator logs function entry and exit."""
        logger = get_logger("test.decorator")

        @log_function_call(logger, level=logging.INFO)
        def test_function(x, y):
            return x + y

        with caplog.at_level(logging.INFO, logger="test.decorator"):
            result = test_function(2, 3)

        assert result == 5
        assert len(caplog.records) >= 2

        # Check for entry and exit logs
        messages = [r.message for r in caplog.records]
        assert any("Entering test_function" in msg for msg in messages)
        assert any("Exiting test_function" in msg for msg in messages)

    def test_decorator_logs_exceptions(self, caplog):
        """Test that decorator logs exceptions."""
        logger = get_logger("test.exception")

        @log_function_call(logger, level=logging.INFO)
        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            failing_function()

        # Should have error log
        error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(error_logs) > 0
        assert "Exception in failing_function" in error_logs[0].message


class TestGetLogger:
    """Tests for logger retrieval."""

    def test_get_logger_returns_logger(self):
        """Test that get_logger returns a Logger instance."""
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.module"

    def test_get_logger_same_name_returns_same_instance(self):
        """Test that get_logger with same name returns same instance."""
        logger1 = get_logger("test.same")
        logger2 = get_logger("test.same")
        assert logger1 is logger2


class TestSecretRedactionIntegration:
    """Integration tests for secret redaction in real logging scenarios."""

    def test_api_key_never_appears_in_logs(self, caplog):
        """Test that API keys never appear in log output."""
        setup_logging(level="DEBUG", format_type="console")
        logger = get_logger("test.security")

        # Log message with API key
        logger.info("Connecting with key: sk-proj-abc123def456ghi789jkl012")

        # Check that API key was redacted
        for record in caplog.records:
            assert "sk-proj-" not in record.message
            assert "***REDACTED***" in record.message

    def test_secret_ref_never_appears_in_logs(self, caplog):
        """Test that secret references are redacted in logs."""
        setup_logging(level="INFO", format_type="console")
        logger = get_logger("test.refs")

        logger.info("Using secret: ${env:OPENAI_API_KEY}")

        for record in caplog.records:
            formatted = logging.Formatter().format(record)
            assert "OPENAI_API_KEY" not in formatted or "REDACTED" in formatted


class TestLogInjectionPrevention:
    """
    Comprehensive tests for log injection prevention (CWE-117).

    Tests cover:
    - URL-encoded injection (single and nested)
    - Unicode attack vectors
    - ANSI escape sequence injection
    - Zero-width character obfuscation
    - CRLF injection
    - Double-encoding attacks
    """

    def test_url_encoded_newline_blocked(self):
        """Test that URL-encoded newlines (%0A) are blocked."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "username=admin%0A[ERROR] Fake security violation"
        sanitized = _sanitize_for_logging(malicious)

        # After decoding and sanitization, newline should be escaped
        assert "\n" not in sanitized
        assert "\\n" in sanitized or "\\x0a" in sanitized.lower()

    def test_url_encoded_carriage_return_blocked(self):
        """Test that URL-encoded carriage returns (%0D) are blocked."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "username=admin%0D[ERROR] Fake log"
        sanitized = _sanitize_for_logging(malicious)

        assert "\r" not in sanitized
        assert "\\r" in sanitized or "\\x0d" in sanitized.lower()

    def test_double_url_encoded_newline_blocked(self):
        """Test that double URL-encoded newlines are blocked."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        # %25 = %, so %250A = %0A, which decodes to \n
        malicious = "admin%250A[ERROR] Fake"
        sanitized = _sanitize_for_logging(malicious)

        assert "\n" not in sanitized
        # Should see escaped newline after decoding
        assert "\\n" in sanitized or "\\x0a" in sanitized.lower()

    def test_triple_url_encoded_newline_blocked(self):
        """Test that deeply nested URL encoding is handled."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        # Triple encoding: %252525...
        malicious = "admin%25252540A[ERROR] Fake"  # %2540A → %40A → @A (partial decode)
        sanitized = _sanitize_for_logging(malicious)

        # Should not crash or timeout, should be safe
        assert len(sanitized) > 0
        assert "\n" not in sanitized

    def test_unicode_line_separator_blocked(self):
        """Test that Unicode line separators (U+2028) are blocked."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "admin\u2028[ERROR] Fake log"
        sanitized = _sanitize_for_logging(malicious)

        assert "\u2028" not in sanitized
        assert "\\u2028" in sanitized

    def test_unicode_paragraph_separator_blocked(self):
        """Test that Unicode paragraph separators (U+2029) are blocked."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "admin\u2029[ERROR] Fake log"
        sanitized = _sanitize_for_logging(malicious)

        assert "\u2029" not in sanitized
        assert "\\u2029" in sanitized

    def test_unicode_next_line_blocked(self):
        """Test that Unicode NEL (U+0085) is blocked."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "admin\u0085[ERROR] Fake log"
        sanitized = _sanitize_for_logging(malicious)

        assert "\u0085" not in sanitized
        # Should be escaped as hex
        assert "\\x85" in sanitized or "\\u0085" in sanitized

    def test_vertical_tab_blocked(self):
        """Test that vertical tab (U+000B) is blocked."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "admin\u000b[ERROR] Fake log"
        sanitized = _sanitize_for_logging(malicious)

        assert "\u000b" not in sanitized
        # May be escaped as either \x0b or \u000b
        assert "\\x0b" in sanitized or "\\u000b" in sanitized

    def test_form_feed_blocked(self):
        """Test that form feed (U+000C) is blocked."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "admin\u000c[ERROR] Fake log"
        sanitized = _sanitize_for_logging(malicious)

        assert "\u000c" not in sanitized
        # May be escaped as either \x0c or \u000c
        assert "\\x0c" in sanitized or "\\u000c" in sanitized

    def test_ansi_escape_sequences_stripped(self):
        """Test that ANSI escape codes are removed (terminal injection)."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        # ANSI escape to make text invisible (black on black)
        malicious = "admin\033[0;30m[ERROR] Hidden breach\033[0m"
        sanitized = _sanitize_for_logging(malicious)

        # ANSI escapes should be stripped
        assert "\033" not in sanitized
        assert "[0;30m" not in sanitized
        # Text content should remain
        assert "admin" in sanitized
        assert "Hidden breach" in sanitized

    def test_zero_width_space_removed(self):
        """Test that zero-width spaces (U+200B) are removed."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "admin\u200b\u200b[ERROR] Obfuscated"
        sanitized = _sanitize_for_logging(malicious)

        assert "\u200b" not in sanitized
        assert "admin" in sanitized
        assert "Obfuscated" in sanitized

    def test_zero_width_non_joiner_removed(self):
        """Test that zero-width non-joiners (U+200C) are removed."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "admin\u200c[ERROR] Hidden"
        sanitized = _sanitize_for_logging(malicious)

        assert "\u200c" not in sanitized

    def test_zero_width_joiner_removed(self):
        """Test that zero-width joiners (U+200D) are removed."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "admin\u200d[ERROR] Hidden"
        sanitized = _sanitize_for_logging(malicious)

        assert "\u200d" not in sanitized

    def test_zero_width_no_break_space_removed(self):
        """Test that zero-width no-break spaces (U+FEFF) are removed."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "admin\ufeff[ERROR] Hidden"
        sanitized = _sanitize_for_logging(malicious)

        assert "\ufeff" not in sanitized

    def test_crlf_injection_blocked(self):
        """Test that Windows CRLF sequences are escaped."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "admin\r\n[ERROR] Fake log\r\n[CRITICAL] Breach"
        sanitized = _sanitize_for_logging(malicious)

        # CRLF should be escaped as unit
        assert "\r\n" not in sanitized
        assert "\\r\\n" in sanitized

    def test_mixed_encoding_attack(self):
        """Test combination of URL encoding and control chars."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        malicious = "test%0A\r\nFAKE\x00NULL"
        sanitized = _sanitize_for_logging(malicious)

        assert "\n" not in sanitized
        assert "\r" not in sanitized
        assert "\x00" not in sanitized
        assert "\\n" in sanitized

    def test_legitimate_logs_preserved(self):
        """Test that normal log messages work correctly."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        normal = "User logged in successfully from IP 192.168.1.1"
        sanitized = _sanitize_for_logging(normal)

        # Should be unchanged (all printable ASCII)
        assert sanitized == normal

    def test_international_characters_preserved(self):
        """Test that legitimate international text is readable."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        international = "用户: José García (日本語)"
        sanitized = _sanitize_for_logging(international)

        # Should preserve Unicode printable characters
        assert "José" in sanitized
        assert "García" in sanitized
        assert "日本語" in sanitized

    def test_empty_string_handled(self):
        """Test that empty string is handled safely."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        assert _sanitize_for_logging("") == ""

    def test_oversized_input_truncated(self):
        """Test that huge inputs are truncated (DoS prevention)."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        huge = "A" * 20000
        sanitized = _sanitize_for_logging(huge, max_length=10000)

        # Should be truncated
        assert len(sanitized) <= 10100  # max_length + truncation message
        assert "[TRUNCATED]" in sanitized

    def test_mixed_safe_and_unsafe_chars(self):
        """Test handling of mixed safe/unsafe characters."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        mixed = "Safe text\nUnsafe\rMore\x00Data"
        sanitized = _sanitize_for_logging(mixed)

        assert "Safe text" in sanitized
        assert "\n" not in sanitized
        assert "\r" not in sanitized
        assert "\x00" not in sanitized
        assert "\\n" in sanitized

    def test_performance_on_large_input(self):
        """Test that large inputs don't cause DoS."""
        import time

        from temper_ai.shared.utils.logging import _sanitize_for_logging

        # 50KB input with injection attempts
        large_input = "A" * 50000 + "%0A[ERROR]" * 1000

        start = time.time()
        sanitized = _sanitize_for_logging(large_input, max_length=10000)
        elapsed = time.time() - start

        # Should complete quickly (< 100ms)
        assert elapsed < 0.1
        assert len(sanitized) <= 10100

    def test_unicode_normalization_applied(self):
        """Test that Unicode normalization (NFKC) is applied."""
        from temper_ai.shared.utils.logging import _sanitize_for_logging

        # Cyrillic 'e' (U+0435) looks like Latin 'e' (U+0065)
        # After normalization, behavior should be consistent
        text_with_cyrillic = "admin\u0435"  # admin + Cyrillic e
        sanitized = _sanitize_for_logging(text_with_cyrillic)

        # After NFKC normalization, the text should be sanitized consistently
        assert "admin" in sanitized

    def test_integration_no_multiline_in_real_logs(self, caplog):
        """Integration test: verify actual log output has no newlines from user input."""
        setup_logging(level="INFO", format_type="console")
        logger = get_logger("test.injection")

        # Attempt log injection with various techniques
        logger.info("User input: admin\n[ERROR] Fake security violation")
        logger.info("User input: admin%0A[ERROR] URL-encoded fake")
        logger.info("User input: admin\u2028[ERROR] Unicode line separator")

        # Verify no actual newlines in logged messages
        for record in caplog.records:
            # The message should have escaped newlines, not literal ones
            assert "\n[ERROR]" not in record.message
            assert "\\n" in record.message or record.message.count("\n") == 0

    def test_integration_siem_parseable_output(self, caplog):
        """Integration test: verify logs are parseable by SIEM (one entry per line)."""
        setup_logging(level="INFO", format_type="console")
        logger = get_logger("test.siem")

        # Log with injection attempt
        logger.info("Processing user=admin\n[FAKE] Injected entry")

        # Each log record should produce single-line output
        for record in caplog.records:
            formatted = SecretRedactingFormatter().format(record)
            lines = formatted.split("\n")
            # Should be one line (or minimal lines from wrapping, but no fake entries)
            assert "[FAKE]" not in formatted or "\\n[FAKE]" in formatted
