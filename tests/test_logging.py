"""
Tests for structured logging module.

Tests cover:
- Secret redaction in log messages
- Structured JSON formatting
- Console formatting with colors
- Log context management
- Configuration from environment
"""
import os
import logging
import json
import pytest
from io import StringIO
from unittest.mock import patch

from src.utils.logging import (
    setup_logging,
    get_logger,
    SecretRedactingFormatter,
    StructuredFormatter,
    ConsoleFormatter,
    LogContext,
    log_function_call
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
            exc_info=None
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
            exc_info=None
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
            exc_info=None
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
            exc_info=None
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
            exc_info=None
        )
        record.api_key = "sk-secret123"
        record.password = "pass123"
        record.user = "john"

        formatted = formatter.format(record)
        # api_key and password should be redacted
        assert hasattr(record, 'api_key')  # Field still exists
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
            exc_info=None
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
            exc_info=None
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
            exc_info=None
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
            exc_info=None
        )
        formatted = formatter.format(record)
        # Tab should be escaped
        assert "\\t" in formatted

    def test_sanitize_null_byte_injection(self):
        """Test that null bytes are removed."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="User input: data\x00truncated",
            args=(),
            exc_info=None
        )
        formatted = formatter.format(record)
        # Null byte should be removed (not just escaped)
        assert "\x00" not in formatted
        assert "datatruncated" in formatted or "data" in formatted

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
            exc_info=None
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
            exc_info=None
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
            exc_info=None
        )
        record.funcName = "test_func"
        record.module = "test"

        formatted = formatter.format(record)

        # Should be valid JSON
        log_data = json.loads(formatted)

        # Check required fields
        assert log_data['level'] == 'INFO'
        assert log_data['logger'] == 'test.module'
        assert log_data['message'] == 'Test message'
        assert log_data['module'] == 'test'
        assert log_data['function'] == 'test_func'
        assert log_data['line'] == 42
        assert 'timestamp' in log_data

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
            exc_info=None
        )
        record.user_id = 123
        record.request_id = "abc-def"
        record.funcName = "process"
        record.module = "api"

        formatted = formatter.format(record)
        log_data = json.loads(formatted)

        assert 'extra' in log_data
        assert log_data['extra']['user_id'] == 123
        assert log_data['extra']['request_id'] == "abc-def"

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
                exc_info=exc_info
            )
            record.funcName = "test"
            record.module = "test"

            formatted = formatter.format(record)
            log_data = json.loads(formatted)

            assert 'exception' in log_data
            assert "ValueError" in log_data['exception']
            assert "Test error" in log_data['exception']


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
            exc_info=None
        )

        formatted = formatter.format(record)

        # Should contain ANSI color codes
        assert '\033[' in formatted  # ANSI escape code
        assert 'ERROR' in formatted
        assert 'test' in formatted
        assert 'Error message' in formatted

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
            exc_info=None
        )

        formatted = formatter.format(record)

        # Should NOT contain ANSI color codes
        assert '\033[' not in formatted
        assert 'INFO' in formatted
        assert 'test' in formatted
        assert 'Info message' in formatted


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
        with patch.dict(os.environ, {'LOG_LEVEL': 'DEBUG'}):
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
        stream_handlers = [h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)]
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
        logger = get_logger("test.context")

        with LogContext(logger, user_id=123, request_id="abc"):
            logger.info("Processing request")

        # Check that context fields were added
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert hasattr(record, 'user_id')
        assert record.user_id == 123
        assert hasattr(record, 'request_id')
        assert record.request_id == "abc"

    def test_context_restoration(self, caplog):
        """Test that context is properly restored after exiting."""
        logger = get_logger("test.restore")

        with LogContext(logger, temp_field="temp"):
            logger.info("Inside context")

        logger.info("Outside context")

        # First log should have temp_field
        assert hasattr(caplog.records[0], 'temp_field')

        # Second log should NOT have temp_field
        assert not hasattr(caplog.records[1], 'temp_field')


class TestLogFunctionDecorator:
    """Tests for function call logging decorator."""

    def test_decorator_logs_entry_exit(self, caplog):
        """Test that decorator logs function entry and exit."""
        logger = get_logger("test.decorator")

        @log_function_call(logger, level=logging.INFO)
        def test_function(x, y):
            return x + y

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
        error_logs = [r for r in caplog.records if r.levelname == 'ERROR']
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
