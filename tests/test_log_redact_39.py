"""Tests for code-high-log-redact-39.

Verifies that log_function_call decorator:
1. Redacts sensitive parameter names (password, api_key, token, etc.)
2. Preserves non-sensitive arguments for debugging
3. Has @functools.wraps to preserve function metadata
4. Doesn't log return values (prevents leaking sensitive return data)
"""

import logging
import pytest
from src.utils.logging import log_function_call


class TestLogFunctionCallRedaction:
    """Verify sensitive parameter redaction in log_function_call."""

    def test_password_redacted(self, caplog):
        """Password kwarg should be redacted in log output."""
        test_logger = logging.getLogger("test_redact")

        @log_function_call(test_logger, level=logging.INFO)
        def login(username, password=""):
            return "ok"

        with caplog.at_level(logging.INFO, logger="test_redact"):
            login("admin", password="super_secret_123")

        log_text = caplog.text
        assert "super_secret_123" not in log_text
        assert "***" in log_text
        assert "admin" in log_text  # non-sensitive arg visible

    def test_api_key_redacted(self, caplog):
        """api_key kwarg should be redacted."""
        test_logger = logging.getLogger("test_redact_apikey")

        @log_function_call(test_logger, level=logging.INFO)
        def call_api(endpoint, api_key=""):
            return {"status": "ok"}

        with caplog.at_level(logging.INFO, logger="test_redact_apikey"):
            call_api("/users", api_key="sk-proj-abc123def456")

        assert "sk-proj-abc123def456" not in caplog.text
        assert "***" in caplog.text

    def test_token_redacted(self, caplog):
        """token kwarg should be redacted."""
        test_logger = logging.getLogger("test_redact_token")

        @log_function_call(test_logger, level=logging.INFO)
        def authenticate(token=""):
            return True

        with caplog.at_level(logging.INFO, logger="test_redact_token"):
            authenticate(token="eyJhbGciOiJIUzI1NiJ9.secret")

        assert "eyJhbGciOiJIUzI1NiJ9.secret" not in caplog.text

    def test_non_sensitive_params_visible(self, caplog):
        """Non-sensitive parameters should remain visible."""
        test_logger = logging.getLogger("test_visible")

        @log_function_call(test_logger, level=logging.INFO)
        def process(name, count):
            return count

        with caplog.at_level(logging.INFO, logger="test_visible"):
            process("test_data", 42)

        assert "test_data" in caplog.text
        assert "42" in caplog.text

    def test_return_value_not_logged(self, caplog):
        """Return values should not be logged (prevent sensitive data leaks)."""
        test_logger = logging.getLogger("test_no_return")

        @log_function_call(test_logger, level=logging.INFO)
        def get_secret():
            return "this_is_a_secret_token"

        with caplog.at_level(logging.INFO, logger="test_no_return"):
            result = get_secret()

        assert result == "this_is_a_secret_token"  # Return value works
        assert "this_is_a_secret_token" not in caplog.text  # But not logged

    def test_functools_wraps_preserves_name(self):
        """Decorated function should preserve __name__."""
        test_logger = logging.getLogger("test_wraps")

        @log_function_call(test_logger)
        def my_special_function():
            """My docstring."""
            pass

        assert my_special_function.__name__ == "my_special_function"

    def test_functools_wraps_preserves_doc(self):
        """Decorated function should preserve __doc__."""
        test_logger = logging.getLogger("test_wraps_doc")

        @log_function_call(test_logger)
        def documented_func():
            """This is the docstring."""
            pass

        assert documented_func.__doc__ == "This is the docstring."

    def test_credentials_redacted(self, caplog):
        """credentials kwarg should be redacted."""
        test_logger = logging.getLogger("test_creds")

        @log_function_call(test_logger, level=logging.INFO)
        def connect(host, credentials=None):
            return True

        with caplog.at_level(logging.INFO, logger="test_creds"):
            connect("db.example.com", credentials={"user": "admin", "pass": "hunter2"})

        assert "hunter2" not in caplog.text
        assert "***" in caplog.text
        assert "db.example.com" in caplog.text
