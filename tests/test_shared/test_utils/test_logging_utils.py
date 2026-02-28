"""Tests for structured logging utilities."""

import logging
from datetime import datetime

from temper_ai.shared.utils.logging import (
    ConsoleFormatter,
    SecretRedactingFormatter,
    StructuredFormatter,
    _recursive_url_decode,
    _sanitize_control_characters,
    _sanitize_for_logging,
    get_logger,
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
