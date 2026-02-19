"""Tests for error fingerprinting core module.

Covers normalization, hashing, classification, and compute_error_fingerprint().
"""
import pytest

from temper_ai.observability.error_fingerprinting import (
    ErrorClassification,
    ErrorFingerprintResult,
    classify_error,
    compute_error_fingerprint,
    compute_fingerprint,
    extract_error_code,
    normalize_message,
    FINGERPRINT_LENGTH,
    MAX_NORMALIZED_MESSAGE_LENGTH,
)
from temper_ai.shared.utils.exceptions import BaseError, ErrorCode, LLMError


# ============================================================================
# normalize_message
# ============================================================================


class TestNormalizeMessage:
    """Tests for message normalization."""

    def test_empty_message(self):
        assert normalize_message("") == ""

    def test_uuid_replacement(self):
        msg = "Failed for workflow a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        result = normalize_message(msg)
        assert "<UUID>" in result
        assert "a1b2c3d4" not in result

    def test_timestamp_replacement(self):
        msg = "Error at 2026-02-15T10:30:45.123Z in handler"
        result = normalize_message(msg)
        assert "<TIMESTAMP>" in result
        assert "2026-02-15" not in result

    def test_timestamp_with_offset(self):
        msg = "Error at 2026-02-15T10:30:45+05:30"
        result = normalize_message(msg)
        assert "<TIMESTAMP>" in result

    def test_number_replacement(self):
        msg = "Token limit 4096 exceeded, used 5123 tokens"
        result = normalize_message(msg)
        assert "<N>" in result
        assert "4096" not in result
        assert "5123" not in result

    def test_small_numbers_preserved(self):
        msg = "Retry attempt 2 of 3 failed"
        result = normalize_message(msg)
        # 2 and 3 are < 3 digits, should be preserved
        assert "2" in result
        assert "3" in result

    def test_path_replacement(self):
        msg = "File not found: /home/user/project/config.yaml"
        result = normalize_message(msg)
        assert "<PATH>" in result
        assert "/home/user" not in result

    def test_hex_id_replacement(self):
        msg = "Agent a1b2c3d4e5f6 failed"
        result = normalize_message(msg)
        assert "<HEX>" in result

    def test_memory_address_replacement(self):
        msg = "Object at 0x7f3a4b5c6d7e is corrupted"
        result = normalize_message(msg)
        assert "<ADDR>" in result
        assert "0x7f3a4b5c6d7e" not in result

    def test_whitespace_collapse(self):
        msg = "Error   in   processing\n\tdata"
        result = normalize_message(msg)
        assert "  " not in result
        assert "\n" not in result
        assert "\t" not in result

    def test_truncation(self):
        msg = "x" * 500
        result = normalize_message(msg)
        assert len(result) == MAX_NORMALIZED_MESSAGE_LENGTH

    def test_deterministic(self):
        msg = "Connection to host a1b2c3d4-e5f6-7890-abcd-ef1234567890 timed out after 30000ms"
        result1 = normalize_message(msg)
        result2 = normalize_message(msg)
        assert result1 == result2

    def test_combined_replacements(self):
        msg = (
            "Workflow a1b2c3d4-e5f6-7890-abcd-ef1234567890 failed at "
            "2026-02-15T10:30:45Z in /home/user/project/main.py "
            "with 4096 tokens"
        )
        result = normalize_message(msg)
        assert "<UUID>" in result
        assert "<TIMESTAMP>" in result
        assert "<PATH>" in result
        assert "<N>" in result


# ============================================================================
# extract_error_code
# ============================================================================


class TestExtractErrorCode:
    """Tests for error code extraction."""

    def test_base_error_with_error_code(self):
        error = LLMError(
            "Connection failed",
            error_code=ErrorCode.LLM_CONNECTION_ERROR,
        )
        assert extract_error_code(error) == ErrorCode.LLM_CONNECTION_ERROR.value

    def test_standard_exception(self):
        error = TimeoutError("Operation timed out")
        result = extract_error_code(error)
        assert result == "TIMEOUT_ERROR"

    def test_value_error(self):
        error = ValueError("Invalid input")
        result = extract_error_code(error)
        assert result == "VALUE_ERROR"

    def test_runtime_error(self):
        error = RuntimeError("Something went wrong")
        result = extract_error_code(error)
        assert result == "RUNTIME_ERROR"

    def test_connection_error(self):
        error = ConnectionError("Refused")
        result = extract_error_code(error)
        assert result == "CONNECTION_ERROR"

    def test_generic_exception(self):
        error = Exception("Generic")
        result = extract_error_code(error)
        assert result == "EXCEPTION"


# ============================================================================
# classify_error
# ============================================================================


class TestClassifyError:
    """Tests for error classification."""

    def test_transient_errors(self):
        transient_codes = [
            "LLM_CONNECTION_ERROR", "LLM_TIMEOUT", "LLM_RATE_LIMIT",
            "SYSTEM_TIMEOUT", "SYSTEM_RESOURCE_ERROR", "TOOL_TIMEOUT",
            "AGENT_TIMEOUT", "WORKFLOW_TIMEOUT",
        ]
        for code in transient_codes:
            assert classify_error(code) == ErrorClassification.TRANSIENT, f"{code} should be transient"

    def test_safety_errors(self):
        safety_codes = [
            "SAFETY_VIOLATION", "SAFETY_POLICY_ERROR", "SAFETY_ACTION_BLOCKED",
        ]
        for code in safety_codes:
            assert classify_error(code) == ErrorClassification.SAFETY, f"{code} should be safety"

    def test_permanent_errors(self):
        permanent_codes = [
            "LLM_AUTH_ERROR", "CONFIG_NOT_FOUND", "VALIDATION_ERROR",
            "AGENT_EXECUTION_ERROR", "TOOL_NOT_FOUND",
        ]
        for code in permanent_codes:
            assert classify_error(code) == ErrorClassification.PERMANENT, f"{code} should be permanent"

    def test_unknown_errors(self):
        assert classify_error("UNKNOWN") == ErrorClassification.UNKNOWN
        assert classify_error("") == ErrorClassification.UNKNOWN

    def test_case_insensitive(self):
        assert classify_error("llm_timeout") == ErrorClassification.TRANSIENT
        assert classify_error("safety_violation") == ErrorClassification.SAFETY


# ============================================================================
# compute_fingerprint
# ============================================================================


class TestComputeFingerprint:
    """Tests for fingerprint computation."""

    def test_length(self):
        fp = compute_fingerprint("LLMError", "LLM_TIMEOUT", "Connection timed out")
        assert len(fp) == FINGERPRINT_LENGTH

    def test_hex_characters(self):
        fp = compute_fingerprint("LLMError", "LLM_TIMEOUT", "Connection timed out")
        assert all(c in "0123456789abcdef" for c in fp)

    def test_deterministic(self):
        fp1 = compute_fingerprint("LLMError", "LLM_TIMEOUT", "Connection timed out")
        fp2 = compute_fingerprint("LLMError", "LLM_TIMEOUT", "Connection timed out")
        assert fp1 == fp2

    def test_different_types_produce_different_fingerprints(self):
        fp1 = compute_fingerprint("LLMError", "LLM_TIMEOUT", "Timed out")
        fp2 = compute_fingerprint("ValueError", "LLM_TIMEOUT", "Timed out")
        assert fp1 != fp2

    def test_different_codes_produce_different_fingerprints(self):
        fp1 = compute_fingerprint("LLMError", "LLM_TIMEOUT", "Failed")
        fp2 = compute_fingerprint("LLMError", "LLM_AUTH_ERROR", "Failed")
        assert fp1 != fp2

    def test_normalizes_volatile_parts(self):
        fp1 = compute_fingerprint(
            "LLMError", "LLM_TIMEOUT",
            "Workflow a1b2c3d4-e5f6-7890-abcd-ef1234567890 timed out"
        )
        fp2 = compute_fingerprint(
            "LLMError", "LLM_TIMEOUT",
            "Workflow f1f2f3f4-a5a6-7890-1234-aabbccddeeff timed out"
        )
        # Same logical error, different UUIDs → same fingerprint
        assert fp1 == fp2


# ============================================================================
# compute_error_fingerprint (main entry point)
# ============================================================================


class TestComputeErrorFingerprint:
    """Tests for the main entry point."""

    def test_basic_exception(self):
        exc = ValueError("Invalid input value")
        result = compute_error_fingerprint(exc)

        assert isinstance(result, ErrorFingerprintResult)
        assert result.error_type == "ValueError"
        assert result.error_code == "VALUE_ERROR"
        assert result.classification == ErrorClassification.PERMANENT
        assert len(result.fingerprint) == FINGERPRINT_LENGTH
        assert result.normalized_message
        assert result.sample_message

    def test_base_error_exception(self):
        exc = LLMError(
            "Connection to provider timed out",
            error_code=ErrorCode.LLM_TIMEOUT,
        )
        result = compute_error_fingerprint(exc)

        assert result.error_type == "LLMError"
        assert result.error_code == ErrorCode.LLM_TIMEOUT.value
        assert result.classification == ErrorClassification.TRANSIENT

    def test_sample_message_truncated(self):
        exc = RuntimeError("x" * 500)
        result = compute_error_fingerprint(exc)
        assert len(result.sample_message) <= MAX_NORMALIZED_MESSAGE_LENGTH

    def test_same_error_same_fingerprint(self):
        exc1 = ValueError("Invalid input: value=12345")
        exc2 = ValueError("Invalid input: value=67890")
        # After normalization (5-digit numbers become <N>), these are the same
        fp1 = compute_error_fingerprint(exc1).fingerprint
        fp2 = compute_error_fingerprint(exc2).fingerprint
        assert fp1 == fp2

    def test_different_errors_different_fingerprints(self):
        exc1 = ValueError("Invalid input")
        exc2 = TypeError("Type mismatch")
        fp1 = compute_error_fingerprint(exc1).fingerprint
        fp2 = compute_error_fingerprint(exc2).fingerprint
        assert fp1 != fp2
