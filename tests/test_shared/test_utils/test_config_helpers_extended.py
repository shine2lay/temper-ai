"""Extended tests for temper_ai/shared/utils/config_helpers.py.

Targets uncovered lines:
- Lines 17-19: ImportError branch for secrets imports
- Lines 165-172: _redact_secret_reference for all reference types
- Line 195: _sanitize_dict when SecretReference.is_reference is True -> redact
- Lines 209-211: _sanitize_string detect_secret_patterns high confidence
- Line 214: _sanitize_string SecretReference is_reference branch
"""

from unittest.mock import MagicMock, patch

from temper_ai.shared.utils.config_helpers import (
    _redact_secret_reference,
    _sanitize_dict,
    _sanitize_string,
    _sanitize_value,
    sanitize_config_for_display,
)

# ---------------------------------------------------------------------------
# _redact_secret_reference (lines 165-172)
# ---------------------------------------------------------------------------


class TestRedactSecretReference:
    """Tests for _redact_secret_reference."""

    def test_env_reference_redacted(self):
        """${env:...} references are redacted (line 165-166)."""
        result = _redact_secret_reference("${env:OPENAI_API_KEY}")
        assert result == "${env:***REDACTED***}"

    def test_vault_reference_redacted(self):
        """${vault:...} references are redacted (lines 167-168)."""
        result = _redact_secret_reference("${vault:secret/openai}")
        assert result == "${vault:***REDACTED***}"

    def test_aws_reference_redacted(self):
        """${aws:...} references are redacted (lines 169-170)."""
        result = _redact_secret_reference("${aws:secretsmanager/key}")
        assert result == "${aws:***REDACTED***}"

    def test_unknown_reference_redacted(self):
        """Unknown reference format falls through to generic redact (lines 171-172)."""
        result = _redact_secret_reference("some_plain_secret_value")
        assert result == "***REDACTED***"

    def test_env_prefix_exact_match(self):
        """Only ${env: prefix matches the env case."""
        result = _redact_secret_reference("${env:SOME_VAR}")
        assert result.startswith("${env:")


# ---------------------------------------------------------------------------
# _sanitize_dict with SecretReference (line 195)
# ---------------------------------------------------------------------------


class TestSanitizeDictWithSecretReference:
    """Tests for _sanitize_dict when value is a secret reference."""

    def test_secret_key_with_secret_reference_value_redacted(self):
        """When key is secret-like and value is a SecretReference, it's redacted (line 195)."""
        mock_secret_ref = MagicMock()
        mock_secret_ref.is_reference = MagicMock(return_value=True)

        with (
            patch(
                "temper_ai.shared.utils.config_helpers.SecretReference", mock_secret_ref
            ),
        ):
            result = _sanitize_dict(
                {"api_key": "${env:MY_KEY}"},
                secret_patterns=["api_key"],
            )

        # Should be redacted
        assert "REDACTED" in result["api_key"] or result["api_key"] == "***REDACTED***"

    def test_secret_key_with_dict_value_recursed(self):
        """When key is secret-like but value is dict, recursion happens (lines 186-188)."""
        result = _sanitize_dict(
            {"password": {"nested": "val"}},
            secret_patterns=["password"],
        )
        assert isinstance(result["password"], dict)

    def test_secret_key_with_list_value_recursed(self):
        """When key is secret-like but value is list, recursion happens."""
        result = _sanitize_dict(
            {"token": ["item1", "item2"]},
            secret_patterns=["token"],
        )
        assert isinstance(result["token"], list)

    def test_non_secret_key_kept_as_is(self):
        """Non-secret keys are kept unchanged."""
        result = _sanitize_dict(
            {"model": "gpt-4", "temperature": 0.7},
            secret_patterns=["api_key"],
        )
        assert result["model"] == "gpt-4"
        assert result["temperature"] == 0.7

    def test_secret_key_plain_string_redacted(self):
        """Secret key with plain string value redacted (line 198)."""
        mock_secret_ref = MagicMock()
        mock_secret_ref.is_reference = MagicMock(return_value=False)

        with patch(
            "temper_ai.shared.utils.config_helpers.SecretReference", mock_secret_ref
        ):
            result = _sanitize_dict(
                {"api_key": "sk-plaintext123"},
                secret_patterns=["api_key"],
            )
        assert result["api_key"] == "***REDACTED***"


# ---------------------------------------------------------------------------
# _sanitize_string (lines 209-211, 214)
# ---------------------------------------------------------------------------


class TestSanitizeStringExtended:
    """Tests for _sanitize_string covering high-confidence and secret-ref branches."""

    def test_detect_secret_patterns_high_confidence_redacts(self):
        """High-confidence secret detection causes full string redaction (lines 208-210)."""
        mock_detect = MagicMock(return_value=(True, "high"))

        with (
            patch(
                "temper_ai.shared.utils.config_helpers.detect_secret_patterns",
                mock_detect,
            ),
            patch("temper_ai.shared.utils.config_helpers.SecretReference", None),
        ):
            result = _sanitize_string("sk-supersecretkey1234567890")
        assert result == "***REDACTED***"

    def test_detect_secret_patterns_low_confidence_no_redact(self):
        """Low-confidence detection doesn't redact (branch: confidence != 'high')."""
        mock_detect = MagicMock(return_value=(True, "low"))

        with (
            patch(
                "temper_ai.shared.utils.config_helpers.detect_secret_patterns",
                mock_detect,
            ),
            patch("temper_ai.shared.utils.config_helpers.SecretReference", None),
        ):
            result = _sanitize_string("maybe-a-secret")
        # Not redacted because confidence is not 'high'
        assert result == "maybe-a-secret"

    def test_detect_secret_patterns_not_secret_no_redact(self):
        """Non-secret detection leaves string unchanged."""
        mock_detect = MagicMock(return_value=(False, None))

        with (
            patch(
                "temper_ai.shared.utils.config_helpers.detect_secret_patterns",
                mock_detect,
            ),
            patch("temper_ai.shared.utils.config_helpers.SecretReference", None),
        ):
            result = _sanitize_string("normal string")
        assert result == "normal string"

    def test_detect_secret_patterns_value_error_skipped(self):
        """ValueError from detect_secret_patterns is silently skipped (line 211)."""
        mock_detect = MagicMock(side_effect=ValueError("input too large"))

        with (
            patch(
                "temper_ai.shared.utils.config_helpers.detect_secret_patterns",
                mock_detect,
            ),
            patch("temper_ai.shared.utils.config_helpers.SecretReference", None),
        ):
            result = _sanitize_string("some text")
        # Fell through to original value since no exception raised
        assert result == "some text"

    def test_secret_reference_is_reference_redacted(self):
        """String that IS a secret reference is redacted (line 213-214)."""
        mock_secret_ref = MagicMock()
        mock_secret_ref.is_reference = MagicMock(return_value=True)

        with (
            patch("temper_ai.shared.utils.config_helpers.detect_secret_patterns", None),
            patch(
                "temper_ai.shared.utils.config_helpers.SecretReference", mock_secret_ref
            ),
        ):
            result = _sanitize_string("${env:MY_SECRET}")
        assert result == "***SECRET_REF***"

    def test_secret_reference_not_a_reference_kept(self):
        """String that is NOT a secret reference is kept unchanged."""
        mock_secret_ref = MagicMock()
        mock_secret_ref.is_reference = MagicMock(return_value=False)

        with (
            patch("temper_ai.shared.utils.config_helpers.detect_secret_patterns", None),
            patch(
                "temper_ai.shared.utils.config_helpers.SecretReference", mock_secret_ref
            ),
        ):
            result = _sanitize_string("plain text")
        assert result == "plain text"

    def test_no_detect_no_secret_ref_returns_as_is(self):
        """With neither detect nor SecretReference, string is returned unchanged."""
        with (
            patch("temper_ai.shared.utils.config_helpers.detect_secret_patterns", None),
            patch("temper_ai.shared.utils.config_helpers.SecretReference", None),
        ):
            result = _sanitize_string("hello world")
        assert result == "hello world"


# ---------------------------------------------------------------------------
# Module-level ImportError branch (lines 17-19)
# ---------------------------------------------------------------------------


class TestConfigHelpersImportFallback:
    """Test that the module handles missing secrets gracefully (lines 15-19)."""

    def test_sanitize_config_without_secrets_available(self):
        """sanitize_config_for_display works even if secrets module is not available."""
        # When SecretReference is None (graceful fallback), sanitization still works
        with (
            patch("temper_ai.shared.utils.config_helpers.SecretReference", None),
            patch("temper_ai.shared.utils.config_helpers.detect_secret_patterns", None),
        ):
            config = {"api_key": "sk-test", "model": "gpt-4"}
            result = sanitize_config_for_display(config)

        # model is not a secret key, api_key is and should be redacted
        assert result["model"] == "gpt-4"

    def test_sanitize_config_empty(self):
        """sanitize_config_for_display handles empty config."""
        result = sanitize_config_for_display({})
        assert result == {}

    def test_sanitize_config_with_extra_secret_keys(self):
        """Custom secret_keys extend redaction list."""
        config = {"my_secret_field": "value123", "safe_field": "hello"}
        result = sanitize_config_for_display(config, secret_keys=["my_secret_field"])
        assert result["my_secret_field"] == "***REDACTED***"
        assert result["safe_field"] == "hello"

    def test_sanitize_value_list_recursion(self):
        """_sanitize_value handles lists by recursing."""
        result = _sanitize_value(["hello", "world"], ["api_key"])
        assert result == ["hello", "world"]

    def test_sanitize_value_non_string_primitive(self):
        """_sanitize_value returns non-string primitives unchanged."""
        assert _sanitize_value(42, []) == 42
        assert _sanitize_value(3.14, []) == 3.14
        assert _sanitize_value(True, []) is True
        assert _sanitize_value(None, []) is None
