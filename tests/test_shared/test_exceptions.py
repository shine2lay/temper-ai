"""Tests for shared exceptions."""

from temper_ai.shared.exceptions import (
    TemperError, ErrorCode, sanitize_message,
)


class TestSanitizeMessage:
    def test_redacts_openai_key(self):
        msg = "Error with key sk-abc123def456ghi789jkl012mno345pqr678"
        result = sanitize_message(msg)
        assert "sk-abc" not in result
        assert "[REDACTED]" in result

    def test_redacts_anthropic_key(self):
        msg = "Key: sk-ant-abc123def456ghi789jkl012mno345"
        result = sanitize_message(msg)
        assert "sk-ant" not in result

    def test_redacts_google_key(self):
        msg = "Key: AIzaSyD-abc123_def456-ghi789_jkl012mno345p"
        result = sanitize_message(msg)
        assert "AIza" not in result

    def test_preserves_normal_text(self):
        msg = "This is a normal error message"
        assert sanitize_message(msg) == msg


class TestTemperError:
    def test_basic(self):
        err = TemperError("something broke")
        assert str(err) == "something broke"
        assert err.code is None
        assert err.cause is None

    def test_with_code(self):
        err = TemperError("timeout", code=ErrorCode.LLM_TIMEOUT)
        assert err.code == ErrorCode.LLM_TIMEOUT

    def test_with_cause(self):
        cause = ValueError("bad value")
        err = TemperError("wrapped", cause=cause)
        assert err.cause is cause

    def test_sanitizes_message(self):
        err = TemperError("Failed with key sk-abc123def456ghi789jkl012mno345pqr678")
        assert "sk-abc" not in str(err)
        assert "[REDACTED]" in str(err)

    def test_inherits_from_exception(self):
        err = TemperError("test")
        assert isinstance(err, Exception)


class TestErrorCode:
    def test_enum_values(self):
        assert ErrorCode.LLM_TIMEOUT == "LLM_TIMEOUT"
        assert ErrorCode.BUDGET_EXCEEDED == "BUDGET_EXCEEDED"
        assert ErrorCode.SAFETY_POLICY_DENIED == "SAFETY_POLICY_DENIED"
