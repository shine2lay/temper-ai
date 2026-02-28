"""Tests for src/utils/secrets.py.

Tests secret management, credential obfuscation, and secret detection.
"""

import os
from unittest.mock import patch

import pytest

from temper_ai.shared.utils.secrets import (
    SecretReference,
    detect_secret_patterns,
    resolve_secret,
)


class TestSecretReference:
    """Test SecretReference class."""

    def test_is_reference_env(self):
        """Test env reference detection."""
        assert SecretReference.is_reference("${env:API_KEY}") is True
        assert SecretReference.is_reference("${env:MY_SECRET_KEY}") is True

    def test_is_reference_vault(self):
        """Test vault reference detection."""
        assert SecretReference.is_reference("${vault:secret/data}") is True

    def test_is_reference_aws(self):
        """Test AWS Secrets Manager reference detection."""
        assert SecretReference.is_reference("${aws:my-secret-id}") is True

    def test_is_reference_plain_text(self):
        """Test that plain text is not a reference."""
        assert SecretReference.is_reference("plain-value") is False
        assert SecretReference.is_reference("sk-test-123") is False

    def test_is_reference_non_string(self):
        """Test that non-strings return False."""
        assert SecretReference.is_reference(123) is False
        assert SecretReference.is_reference(None) is False

    def test_resolve_env_success(self):
        """Test resolving environment variable."""
        with patch.dict(os.environ, {"TEST_KEY": "test-value"}):
            result = SecretReference.resolve("${env:TEST_KEY}")
            assert result == "test-value"

    def test_resolve_env_missing(self):
        """Test resolving missing environment variable."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(
                ValueError, match="Environment variable 'MISSING_KEY' not set"
            ):
                SecretReference.resolve("${env:MISSING_KEY}")

    def test_resolve_env_empty(self):
        """Test that empty environment variable raises error."""
        with patch.dict(os.environ, {"EMPTY_KEY": ""}):
            with pytest.raises(ValueError, match="Secret 'EMPTY_KEY' is empty"):
                SecretReference.resolve("${env:EMPTY_KEY}")

    def test_resolve_env_whitespace_only(self):
        """Test that whitespace-only value raises error."""
        with patch.dict(os.environ, {"WHITESPACE_KEY": "   "}):
            with pytest.raises(ValueError, match="Secret 'WHITESPACE_KEY' is empty"):
                SecretReference.resolve("${env:WHITESPACE_KEY}")

    def test_resolve_env_too_long(self):
        """Test that excessively long secret raises error."""
        long_value = "x" * 11000  # >10KB
        with patch.dict(os.environ, {"LONG_KEY": long_value}):
            with pytest.raises(ValueError, match="too long"):
                SecretReference.resolve("${env:LONG_KEY}")

    def test_resolve_env_null_bytes(self):
        """Test that secret with null bytes raises error."""
        # Cannot set env vars with null bytes, so we mock the validation instead
        with patch(
            "temper_ai.shared.utils.secrets.os.environ.get",
            return_value="test\x00value",
        ):
            with pytest.raises(ValueError, match="contains null bytes"):
                SecretReference.resolve("${env:NULL_KEY}")

    def test_resolve_vault_not_implemented(self):
        """Test that vault provider is not yet implemented."""
        with pytest.raises(
            NotImplementedError, match="HashiCorp Vault provider is planned for v1.1"
        ):
            SecretReference.resolve("${vault:secret/path}")

    def test_resolve_aws_not_implemented(self):
        """Test that AWS provider is not yet implemented."""
        with pytest.raises(
            NotImplementedError,
            match="AWS Secrets Manager provider is planned for v1.1",
        ):
            SecretReference.resolve("${aws:secret-id}")

    def test_resolve_plain_text(self):
        """Test that plain text is returned as-is."""
        result = SecretReference.resolve("plain-value")
        assert result == "plain-value"


class TestResolveSecret:
    """Test resolve_secret function."""

    def test_resolve_env_reference(self):
        """Test resolving environment variable reference."""
        with patch.dict(os.environ, {"API_KEY": "sk-test-123"}):
            result = resolve_secret("${env:API_KEY}")
            assert result == "sk-test-123"

    def test_resolve_plain_string(self):
        """Test that plain string is returned as-is."""
        result = resolve_secret("plain-value")
        assert result == "plain-value"

    def test_resolve_dict(self):
        """Test resolving secrets in dictionary."""
        with patch.dict(os.environ, {"SECRET": "secret-value"}):
            config = {"api_key": "${env:SECRET}", "timeout": 30, "name": "test"}
            result = resolve_secret(config)
            assert result["api_key"] == "secret-value"
            assert result["timeout"] == 30
            assert result["name"] == "test"

    def test_resolve_nested_dict(self):
        """Test resolving secrets in nested dictionary."""
        with patch.dict(os.environ, {"DB_PASS": "db-secret"}):
            config = {"database": {"host": "localhost", "password": "${env:DB_PASS}"}}
            result = resolve_secret(config)
            assert result["database"]["password"] == "db-secret"

    def test_resolve_list(self):
        """Test resolving secrets in list."""
        with patch.dict(os.environ, {"KEY1": "value1", "KEY2": "value2"}):
            items = ["${env:KEY1}", "plain", "${env:KEY2}"]
            result = resolve_secret(items)
            assert result == ["value1", "plain", "value2"]

    def test_resolve_non_string_types(self):
        """Test that non-string types are returned as-is."""
        assert resolve_secret(123) == 123
        assert resolve_secret(None) is None
        assert resolve_secret(True) is True


class TestDetectSecretPatterns:
    """Test detect_secret_patterns function."""

    def test_detect_openai_key(self):
        """Test detecting OpenAI API key."""
        text = "Your API key is sk-proj-" + ("a" * 50)  # Need longer key
        is_secret, confidence = detect_secret_patterns(text)
        assert is_secret is True
        assert confidence == "high"

    def test_detect_anthropic_key(self):
        """Test detecting Anthropic API key."""
        text = "Use key sk-ant-api03-" + ("a" * 50)  # Need longer key
        is_secret, confidence = detect_secret_patterns(text)
        assert is_secret is True
        assert confidence == "high"

    def test_detect_aws_key(self):
        """Test detecting AWS access key."""
        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        is_secret, confidence = detect_secret_patterns(text)
        assert is_secret is True
        assert confidence == "high"

    def test_detect_github_token(self):
        """Test detecting GitHub token."""
        text = "Token: ghp_abc123def456ghi789jkl012mno345"
        is_secret, confidence = detect_secret_patterns(text)
        assert is_secret is True
        assert confidence == "high"

    def test_detect_md5_hash(self):
        """Test detecting MD5-like hash (medium confidence)."""
        text = "Hash: 5d41402abc4b2a76b9719d911017c592"
        is_secret, confidence = detect_secret_patterns(text)
        assert is_secret is True
        assert confidence == "medium"

    def test_detect_base64(self):
        """Test detecting base64-encoded strings (medium confidence)."""
        text = "Token: SGVsbG8gV29ybGQhIFRoaXMgaXMgYSBsb25nIGJhc2U2NCBlbmNvZGVk"
        is_secret, confidence = detect_secret_patterns(text)
        assert is_secret is True
        assert confidence == "medium"

    def test_no_secret_detected(self):
        """Test that normal text is not flagged."""
        text = "This is normal text without secrets"
        is_secret, confidence = detect_secret_patterns(text)
        assert is_secret is False
        assert confidence is None

    def test_input_too_long(self):
        """Test that input exceeding 100KB raises error."""
        long_text = "x" * 103000  # >100KB
        with pytest.raises(ValueError, match="Input too long"):
            detect_secret_patterns(long_text)

    def test_jwt_token(self):
        """Test detecting JWT token."""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        is_secret, confidence = detect_secret_patterns(text)
        assert is_secret is True
        assert confidence == "high"

    def test_private_key(self):
        """Test detecting private key."""
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA..."
        is_secret, confidence = detect_secret_patterns(text)
        assert is_secret is True
        assert confidence == "high"
