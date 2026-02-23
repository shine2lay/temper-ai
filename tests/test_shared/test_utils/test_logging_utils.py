"""Tests for structured logging utilities."""

import logging
from datetime import datetime
from io import StringIO
from unittest.mock import patch

import pytest

from temper_ai.shared.utils.logging import (
    ConsoleFormatter,
    LogContext,
    SecretRedactingFormatter,
    StructuredFormatter,
    _recursive_url_decode,
    _sanitize_control_characters,
    _sanitize_for_logging,
    get_logger,
    log_function_call,
    setup_logging,
)


class TestSanitization:
    """Tests for log sanitization functions."""

    def test_recursive_url_decode_single_level(self):
        """Test single level URL decoding."""
        assert _recursive_url_decode("%41%42%43") == "ABC"
        assert _recursive_url_decode("hello%20world") == "hello world"

    def test_recursive_url_decode_multiple_levels(self):
        """Test nested URL decoding."""
        # %2541 -> %41 -> A
        assert _recursive_url_decode("%2541") == "A"
        # Triple encoded
        assert _recursive_url_decode("%252541") == "A"

    def test_recursive_url_decode_depth_limit(self):
        """Test URL decoding stops at max depth."""
        result = _recursive_url_decode("%41", max_depth=0)
        assert result == "%41"  # No decoding

        result = _recursive_url_decode("%2541", max_depth=1)
        assert result == "%41"  # One level only

    def test_recursive_url_decode_no_encoding(self):
        """Test plain text is not modified."""
        assert _recursive_url_decode("plain text") == "plain text"
        assert _recursive_url_decode("123") == "123"

    def test_recursive_url_decode_invalid_encoding(self):
        """Test malformed URL encoding is handled."""
        # Should not crash on invalid encoding
        result = _recursive_url_decode("%ZZ")
        assert result is not None

    def test_sanitize_control_characters_newlines(self):
        """Test newline sanitization."""
        assert _sanitize_control_characters("line1\nline2") == "line1\\nline2"
        assert _sanitize_control_characters("line1\rline2") == "line1\\rline2"
        assert _sanitize_control_characters("line1\r\nline2") == "line1\\r\\nline2"

    def test_sanitize_control_characters_tabs(self):
        """Test tab sanitization."""
        assert _sanitize_control_characters("col1\tcol2") == "col1\\tcol2"

    def test_sanitize_control_characters_ascii_control(self):
        """Test ASCII control character escaping."""
        # Null byte
        assert _sanitize_control_characters("text\x00null") == "text\\x00null"
        # Bell character
        assert _sanitize_control_characters("text\x07bell") == "text\\x07bell"
        # DEL character
        assert _sanitize_control_characters("text\x7fdel") == "text\\x7fdel"

    def test_sanitize_control_characters_printable(self):
        """Test printable characters are preserved."""
        text = "Hello World 123 !@#$%"
        assert _sanitize_control_characters(text) == text

    def test_sanitize_control_characters_unicode(self):
        """Test Unicode characters are preserved."""
        text = "Hello 世界 🌍"
        assert _sanitize_control_characters(text) == text

    def test_sanitize_control_characters_unicode_line_terminators(self):
        """Test Unicode line terminators are escaped."""
        # Line separator U+2028
        assert _sanitize_control_characters("text\u2028end") == "text\\u2028end"
        # Paragraph separator U+2029
        assert _sanitize_control_characters("text\u2029end") == "text\\u2029end"

    def test_sanitize_for_logging_basic(self):
        """Test basic log sanitization."""
        text = "Hello World"
        assert _sanitize_for_logging(text) == text

    def test_sanitize_for_logging_newline_injection(self):
        """Test newline injection prevention."""
        malicious = "User input\nINFO: Fake log entry"
        result = _sanitize_for_logging(malicious)
        assert "\n" not in result
        assert "\\n" in result

    def test_sanitize_for_logging_url_encoded_newline(self):
        """Test URL-encoded newline bypass prevention."""
        malicious = "User input%0AINFO: Fake log"
        result = _sanitize_for_logging(malicious)
        assert "\n" not in result

    def test_sanitize_for_logging_ansi_escape(self):
        """Test ANSI escape code stripping."""
        text = "\x1b[31mRed Text\x1b[0m"
        result = _sanitize_for_logging(text)
        assert "\x1b" not in result
        assert "Red Text" in result

    def test_sanitize_for_logging_zero_width_chars(self):
        """Test zero-width character removal."""
        text = "hello\u200bworld"  # Zero-width space
        result = _sanitize_for_logging(text)
        assert "\u200b" not in result
        assert "helloworld" in result

    def test_sanitize_for_logging_length_limit(self):
        """Test length truncation."""
        long_text = "A" * 15000
        result = _sanitize_for_logging(long_text, max_length=1000)
        assert len(result) <= 1020  # 1000 + truncation suffix
        assert "[TRUNCATED]" in result

    def test_sanitize_for_logging_empty_string(self):
        """Test empty string handling."""
        assert _sanitize_for_logging("") == ""
        assert _sanitize_for_logging(None) == ""


class TestSecretRedactingFormatter:
    """Tests for SecretRedactingFormatter."""

    def test_initialization(self):
        """Test formatter initialization."""
        formatter = SecretRedactingFormatter()
        assert isinstance(formatter, logging.Formatter)

    def test_format_with_secret_in_message(self):
        """Test secret redaction in log message."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="api_key=sk-1234567890abcdef",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        assert "sk-1234567890abcdef" not in result
        assert "REDACTED" in result

    def test_format_with_password(self):
        """Test password redaction."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="password=secret123",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        assert "secret123" not in result
        assert "REDACTED" in result

    def test_format_with_env_reference(self):
        """Test environment variable reference redaction."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Using API key from ${env:API_KEY}",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        assert "REDACTED" in result

    def test_format_preserves_original_message(self):
        """Test original message is restored after formatting."""
        formatter = SecretRedactingFormatter()
        original_msg = "password=secret"
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg=original_msg,
            args=(),
            exc_info=None,
        )

        formatter.format(record)
        assert record.msg == original_msg

    def test_redact_secrets_in_extra_fields(self):
        """Test secrets are redacted from extra fields."""
        formatter = SecretRedactingFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.api_key = "secret_key_123"
        record.password = "password123"

        formatter.format(record)
        assert record.api_key == "***REDACTED***"
        assert record.password == "***REDACTED***"

    def test_redact_secrets_method(self):
        """Test _redact_secrets method directly."""
        formatter = SecretRedactingFormatter()

        # Test password redaction
        assert "REDACTED" in formatter._redact_secrets("password=secret123")

        # Test API key redaction
        assert "REDACTED" in formatter._redact_secrets("api_key=abc123")

        # Test safe text is not modified
        safe_text = "Normal log message without secrets"
        assert formatter._redact_secrets(safe_text) == safe_text


class TestStructuredFormatter:
    """Tests for StructuredFormatter (JSON logs)."""

    def test_format_produces_valid_json(self):
        """Test formatter produces valid JSON."""
        import json

        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        data = json.loads(result)  # Should not raise

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert "Test message" in data["message"]
        assert data["module"] == "test"
        assert data["line"] == 42

    def test_format_includes_timestamp(self):
        """Test formatted output includes ISO timestamp."""
        import json

        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert "timestamp" in data
        # Should be ISO 8601 format
        datetime.fromisoformat(data["timestamp"])

    def test_format_includes_exception_info(self):
        """Test exception info is included when present."""
        import json

        formatter = StructuredFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert "exception" in data
        assert "ValueError" in data["exception"]
        assert "Test error" in data["exception"]

    def test_format_includes_extra_fields(self):
        """Test extra fields are included in JSON."""
        import json

        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.user_id = 123
        record.request_id = "req-456"

        result = formatter.format(record)
        data = json.loads(result)

        assert "extra" in data
        assert data["extra"]["user_id"] == 123
        assert data["extra"]["request_id"] == "req-456"

    def test_format_redacts_secret_fields(self):
        """Test secrets in extra fields are redacted."""
        import json

        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.api_key = "secret123"

        result = formatter.format(record)
        data = json.loads(result)

        assert "extra" in data
        assert data["extra"]["api_key"] == "***REDACTED***"


class TestConsoleFormatter:
    """Tests for ConsoleFormatter."""

    def test_initialization_with_colors(self):
        """Test formatter initializes with colors enabled."""
        formatter = ConsoleFormatter(use_colors=True)
        assert formatter.use_colors is True

    def test_initialization_without_colors(self):
        """Test formatter initializes with colors disabled."""
        formatter = ConsoleFormatter(use_colors=False)
        assert formatter.use_colors is False

    def test_format_with_colors(self):
        """Test formatting with colors adds ANSI codes."""
        formatter = ConsoleFormatter(use_colors=True)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        # Should contain ANSI color codes
        assert "\033[" in result
        assert "INFO" in result
        assert "test" in result

    def test_format_without_colors(self):
        """Test formatting without colors has no ANSI codes."""
        formatter = ConsoleFormatter(use_colors=False)
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        # Should not contain ANSI codes
        assert "\033[" not in result
        assert "INFO" in result

    def test_color_codes_for_levels(self):
        """Test correct color codes for each log level."""
        formatter = ConsoleFormatter(use_colors=True)

        levels = [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL"),
        ]

        for level_num, level_name in levels:
            record = logging.LogRecord(
                name="test",
                level=level_num,
                pathname="test.py",
                lineno=1,
                msg="Test",
                args=(),
                exc_info=None,
            )

            result = formatter.format(record)
            assert level_name in result
            if formatter.use_colors:
                assert "\033[" in result


class TestLoggingSetup:
    """Tests for setup_logging function."""

    def test_setup_logging_default_level(self):
        """Test setup_logging with default level."""
        with patch.dict("os.environ", {}, clear=True):
            setup_logging()

            root_logger = logging.getLogger()
            assert root_logger.level == logging.INFO

    def test_setup_logging_custom_level(self):
        """Test setup_logging with custom level."""
        setup_logging(level="DEBUG")

        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

    def test_setup_logging_env_variable(self):
        """Test setup_logging reads from TEMPER_LOG_LEVEL env var."""
        with patch.dict("os.environ", {"TEMPER_LOG_LEVEL": "WARNING"}):
            setup_logging()

            root_logger = logging.getLogger()
            assert root_logger.level == logging.WARNING

    def test_setup_logging_console_format(self):
        """Test setup_logging with console format."""
        setup_logging(format_type="console")

        root_logger = logging.getLogger()
        assert len(root_logger.handlers) > 0

        # Should have console handler
        handler_types = [type(h).__name__ for h in root_logger.handlers]
        assert "StreamHandler" in handler_types

    def test_setup_logging_json_format(self):
        """Test setup_logging with JSON format."""
        setup_logging(format_type="json")

        root_logger = logging.getLogger()
        handlers = root_logger.handlers

        # Should have JSON formatter
        assert any(isinstance(h.formatter, StructuredFormatter) for h in handlers)

    def test_setup_logging_both_formats(self):
        """Test setup_logging with both console and JSON."""
        setup_logging(format_type="both")

        root_logger = logging.getLogger()
        assert len(root_logger.handlers) >= 2

    def test_setup_logging_with_file(self, tmp_path):
        """Test setup_logging with log file."""
        log_file = tmp_path / "test.log"
        setup_logging(log_file=str(log_file))

        root_logger = logging.getLogger()

        # Should have file handler
        handler_types = [type(h).__name__ for h in root_logger.handlers]
        assert "FileHandler" in handler_types

        # File should be created
        assert log_file.exists()

    def test_setup_logging_clears_existing_handlers(self):
        """Test setup_logging clears existing handlers."""
        root_logger = logging.getLogger()
        initial_handler_count = len(root_logger.handlers)

        setup_logging(format_type="console")
        first_count = len(root_logger.handlers)

        setup_logging(format_type="console")
        second_count = len(root_logger.handlers)

        # Should not accumulate handlers
        assert first_count == second_count


class TestGetLogger:
    """Tests for get_logger function."""

    def test_get_logger_returns_logger(self):
        """Test get_logger returns a Logger instance."""
        logger = get_logger("test.module")
        assert isinstance(logger, logging.Logger)

    def test_get_logger_name(self):
        """Test get_logger sets correct name."""
        logger = get_logger("my.module")
        assert logger.name == "my.module"

    def test_get_logger_same_name_returns_same_instance(self):
        """Test get_logger returns same instance for same name."""
        logger1 = get_logger("test.module")
        logger2 = get_logger("test.module")
        assert logger1 is logger2


class TestLogContext:
    """Tests for LogContext context manager."""

    def test_log_context_adds_fields(self):
        """Test LogContext adds fields to log records."""
        logger = get_logger("test")
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        with LogContext(logger, user_id=123, request_id="req-456"):
            logger.info("Test message")

        output = stream.getvalue()
        assert "user_id" in output
        assert "123" in output
        assert "req-456" in output

    def test_log_context_restores_factory(self):
        """Test LogContext restores original log record factory."""
        old_factory = logging.getLogRecordFactory()

        logger = get_logger("test")
        with LogContext(logger, test_field="value"):
            pass

        new_factory = logging.getLogRecordFactory()
        assert new_factory == old_factory

    def test_log_context_nested(self):
        """Test nested LogContext works correctly."""
        logger = get_logger("test")
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        with LogContext(logger, outer="value1"):
            # Log in outer context
            logger.info("Outer message")
            outer_output = stream.getvalue()
            assert "outer" in outer_output
            assert "value1" in outer_output
            stream.truncate(0)
            stream.seek(0)

            with LogContext(logger, inner="value2"):
                # Log in inner context - should have both fields
                logger.info("Inner message")
                inner_output = stream.getvalue()
                assert "outer" in inner_output
                assert "value1" in inner_output
                assert "inner" in inner_output
                assert "value2" in inner_output
                stream.truncate(0)
                stream.seek(0)

            # Back to outer context - should only have outer field
            logger.info("Outer again")
            restored_output = stream.getvalue()
            assert "outer" in restored_output
            assert "value1" in restored_output
            # Inner field should not be present after exiting inner context
            assert "inner" not in restored_output or "value2" not in restored_output


class TestLogFunctionCall:
    """Tests for log_function_call decorator."""

    def test_decorator_logs_function_calls(self):
        """Test decorator logs function entry and exit."""
        logger = get_logger("test")

        with patch.object(logger, "log") as mock_log:

            @log_function_call(logger, level=logging.DEBUG)
            def test_function(x, y):
                return x + y

            result = test_function(1, 2)

            assert result == 3
            assert mock_log.call_count == 2  # Entry and exit
            assert "Entering" in mock_log.call_args_list[0][0][1]
            assert "Exiting" in mock_log.call_args_list[1][0][1]

    def test_decorator_logs_exceptions(self):
        """Test decorator logs exceptions."""
        logger = get_logger("test")

        with patch.object(logger, "error") as mock_error:

            @log_function_call(logger)
            def failing_function():
                raise ValueError("Test error")

            with pytest.raises(ValueError):
                failing_function()

            mock_error.assert_called_once()
            assert "Exception" in mock_error.call_args[0][0]

    def test_decorator_redacts_sensitive_params(self):
        """Test decorator redacts sensitive parameter values."""
        logger = get_logger("test")

        with patch.object(logger, "log") as mock_log:

            @log_function_call(logger)
            def secure_function(username, password="default"):
                return f"User: {username}"

            secure_function("alice", password="secret123")

            # Check that password is redacted in kwargs
            entry_call = mock_log.call_args_list[0]
            log_message = entry_call[0][1]
            assert "alice" in log_message
            # Password should be redacted in kwargs
            assert "***" in log_message or "secret123" not in log_message
