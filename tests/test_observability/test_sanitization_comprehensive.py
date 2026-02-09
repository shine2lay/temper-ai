"""Comprehensive tests for src/observability/sanitization.py.

Tests data sanitization for PII and secrets in observability logs.
"""
import pytest

from src.observability.sanitization import (
    DEFAULT_MAX_PROMPT_LENGTH,
    DEFAULT_MAX_RESPONSE_LENGTH,
    DataSanitizer,
    SanitizationConfig,
    SanitizationResult,
)


class TestSanitizationConfig:
    """Test SanitizationConfig dataclass."""

    def test_default_config(self):
        """Test default configuration is production-safe."""
        config = SanitizationConfig()
        assert config.enable_secret_detection is True
        assert config.redact_high_confidence_secrets is True
        assert config.redact_medium_confidence_secrets is True
        assert config.enable_pii_detection is True
        assert config.redact_emails is True
        assert config.redact_ssn is True
        assert config.redact_phone_numbers is True
        assert config.redact_credit_cards is True
        assert config.redact_ip_addresses is True
        assert config.include_hash is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = SanitizationConfig(
            enable_secret_detection=False,
            redact_emails=False,
            max_prompt_length=1000
        )
        assert config.enable_secret_detection is False
        assert config.redact_emails is False
        assert config.max_prompt_length == 1000

    def test_length_limits(self):
        """Test length limit defaults."""
        config = SanitizationConfig()
        assert config.max_prompt_length == DEFAULT_MAX_PROMPT_LENGTH
        assert config.max_response_length == DEFAULT_MAX_RESPONSE_LENGTH


class TestSanitizationResult:
    """Test SanitizationResult dataclass."""

    def test_no_redactions(self):
        """Test result with no redactions."""
        result = SanitizationResult(
            sanitized_text="clean text",
            original_length=10,
            redactions=[],
            content_hash="abc123"
        )
        assert result.was_sanitized is False
        assert result.num_redactions == 0

    def test_with_redactions(self):
        """Test result with redactions."""
        redactions = [
            {"type": "email", "pattern": "EMAIL_REDACTED"},
            {"type": "api_key", "pattern": "API_KEY_REDACTED"}
        ]
        result = SanitizationResult(
            sanitized_text="redacted text",
            original_length=50,
            redactions=redactions,
            content_hash="def456"
        )
        assert result.was_sanitized is True
        assert result.num_redactions == 2

    def test_to_metadata(self):
        """Test converting result to metadata."""
        redactions = [{"type": "email"}]
        result = SanitizationResult(
            sanitized_text="test",
            original_length=20,
            redactions=redactions,
            content_hash="hash123"
        )
        metadata = result.to_metadata()

        assert metadata["original_length"] == 20
        assert metadata["sanitized_length"] == 4
        assert metadata["num_redactions"] == 1
        assert metadata["content_hash"] == "hash123"
        assert "email" in metadata["redaction_types"]


class TestDataSanitizer:
    """Test DataSanitizer class."""

    def test_initialization_default(self):
        """Test default initialization."""
        sanitizer = DataSanitizer()
        assert sanitizer.config.enable_secret_detection is True

    def test_initialization_custom_config(self):
        """Test initialization with custom config."""
        config = SanitizationConfig(enable_pii_detection=False)
        sanitizer = DataSanitizer(config)
        assert sanitizer.config.enable_pii_detection is False

    def test_sanitize_text_no_secrets(self):
        """Test sanitizing clean text."""
        sanitizer = DataSanitizer()
        result = sanitizer.sanitize_text("This is normal text")

        assert result.sanitized_text == "This is normal text"
        assert result.num_redactions == 0
        assert result.content_hash is not None

    def test_sanitize_openai_key(self):
        """Test sanitizing OpenAI API key."""
        sanitizer = DataSanitizer()
        text = "Your API key is sk-proj-abc123def456"
        result = sanitizer.sanitize_text(text)

        assert "sk-proj-abc123def456" not in result.sanitized_text
        assert result.was_sanitized is True
        assert any(r["type"] == "openai_project_key" for r in result.redactions)

    def test_sanitize_email(self):
        """Test sanitizing email addresses."""
        sanitizer = DataSanitizer()
        text = "Contact john.doe@example.com for support"
        result = sanitizer.sanitize_text(text)

        assert "john.doe@example.com" not in result.sanitized_text
        assert "[EMAIL_REDACTED]" in result.sanitized_text
        assert result.was_sanitized is True

    def test_sanitize_ssn(self):
        """Test sanitizing SSN."""
        sanitizer = DataSanitizer()
        text = "SSN: 123-45-6789"
        result = sanitizer.sanitize_text(text)

        assert "123-45-6789" not in result.sanitized_text
        assert "[SSN_REDACTED]" in result.sanitized_text

    def test_sanitize_phone_number(self):
        """Test sanitizing phone numbers."""
        sanitizer = DataSanitizer()
        text = "Call (555) 123-4567"
        result = sanitizer.sanitize_text(text)

        assert "555" not in result.sanitized_text or "[PHONE_REDACTED]" in result.sanitized_text
        assert result.was_sanitized is True

    def test_sanitize_credit_card(self):
        """Test sanitizing credit card numbers."""
        sanitizer = DataSanitizer()
        text = "Card: 4532-1234-5678-9010"
        result = sanitizer.sanitize_text(text)

        assert "4532-1234-5678-9010" not in result.sanitized_text
        assert "[CREDIT_CARD_REDACTED]" in result.sanitized_text

    def test_sanitize_ip_address(self):
        """Test sanitizing IP addresses."""
        sanitizer = DataSanitizer()
        text = "Server at 192.168.1.100"
        result = sanitizer.sanitize_text(text)

        assert result.was_sanitized is True
        # IP addresses should be redacted

    def test_sanitize_jwt_token(self):
        """Test sanitizing JWT tokens."""
        sanitizer = DataSanitizer()
        text = "Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123"
        result = sanitizer.sanitize_text(text)

        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result.sanitized_text
        assert result.was_sanitized is True

    def test_sanitize_aws_key(self):
        """Test sanitizing AWS access keys."""
        sanitizer = DataSanitizer()
        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        result = sanitizer.sanitize_text(text)

        assert "AKIAIOSFODNN7EXAMPLE" not in result.sanitized_text
        assert result.was_sanitized is True

    def test_multiple_secrets(self):
        """Test sanitizing multiple secrets."""
        sanitizer = DataSanitizer()
        text = "Email john@example.com with API key sk-test-123"
        result = sanitizer.sanitize_text(text)

        assert "john@example.com" not in result.sanitized_text
        assert "sk-test-123" not in result.sanitized_text
        assert result.num_redactions >= 2

    def test_length_truncation(self):
        """Test text length truncation."""
        config = SanitizationConfig(max_prompt_length=100)
        sanitizer = DataSanitizer(config)

        long_text = "x" * 200
        result = sanitizer.sanitize_text(long_text)

        assert len(result.sanitized_text) <= 120  # 100 + ellipsis marker

    def test_allowlist_patterns(self):
        """Test allowlist patterns."""
        config = SanitizationConfig(
            allowlist_patterns=[r"test@example\.com"]
        )
        sanitizer = DataSanitizer(config)

        text = "Email test@example.com"
        result = sanitizer.sanitize_text(text)

        # Allowlisted email should not be redacted
        assert "test@example.com" in result.sanitized_text

    def test_disable_secret_detection(self):
        """Test disabling secret detection."""
        config = SanitizationConfig(enable_secret_detection=False)
        sanitizer = DataSanitizer(config)

        text = "API key sk-test-123"
        result = sanitizer.sanitize_text(text)

        # Secret should not be redacted when detection is disabled
        assert "sk-test-123" in result.sanitized_text

    def test_disable_pii_detection(self):
        """Test disabling PII detection."""
        config = SanitizationConfig(enable_pii_detection=False)
        sanitizer = DataSanitizer(config)

        text = "Email john@example.com"
        result = sanitizer.sanitize_text(text)

        # PII should not be redacted when detection is disabled
        assert "john@example.com" in result.sanitized_text

    def test_sanitize_dict(self):
        """Test sanitizing dictionary."""
        sanitizer = DataSanitizer()
        data = {
            "user": "john@example.com",
            "api_key": "sk-test-123",
            "timeout": 30
        }
        result = sanitizer.sanitize_dict(data)

        assert "john@example.com" not in str(result)
        assert "sk-test-123" not in str(result)
        assert result["timeout"] == 30

    def test_sanitize_nested_dict(self):
        """Test sanitizing nested dictionary."""
        sanitizer = DataSanitizer()
        data = {
            "config": {
                "credentials": {
                    "api_key": "sk-secret-123"
                },
                "timeout": 30
            }
        }
        result = sanitizer.sanitize_dict(data)

        # API key should be redacted in nested structure
        assert "sk-secret-123" not in str(result)

    def test_content_hash_generation(self):
        """Test content hash generation."""
        sanitizer = DataSanitizer()
        text = "Test content"
        result1 = sanitizer.sanitize_text(text)
        result2 = sanitizer.sanitize_text(text)

        # Same content should produce same hash
        assert result1.content_hash == result2.content_hash

    def test_content_hash_different_content(self):
        """Test different content produces different hashes."""
        sanitizer = DataSanitizer()
        result1 = sanitizer.sanitize_text("content1")
        result2 = sanitizer.sanitize_text("content2")

        assert result1.content_hash != result2.content_hash

    def test_empty_text(self):
        """Test sanitizing empty text."""
        sanitizer = DataSanitizer()
        result = sanitizer.sanitize_text("")

        assert result.sanitized_text == ""
        assert result.num_redactions == 0

    def test_none_text(self):
        """Test sanitizing None value."""
        sanitizer = DataSanitizer()
        result = sanitizer.sanitize_text(None)

        assert result.sanitized_text == ""

    def test_medium_confidence_secrets(self):
        """Test medium confidence secret detection."""
        config = SanitizationConfig(
            redact_medium_confidence_secrets=True
        )
        sanitizer = DataSanitizer(config)

        # MD5 hash (medium confidence)
        text = "Hash: 5d41402abc4b2a76b9719d911017c592"
        result = sanitizer.sanitize_text(text)

        # Medium confidence secrets should be redacted
        assert result.was_sanitized is True

    def test_disable_medium_confidence(self):
        """Test disabling medium confidence secret detection."""
        config = SanitizationConfig(
            redact_medium_confidence_secrets=False
        )
        sanitizer = DataSanitizer(config)

        # MD5 hash (medium confidence)
        text = "Hash: 5d41402abc4b2a76b9719d911017c592"
        result = sanitizer.sanitize_text(text)

        # Should not be redacted
        assert "5d41402abc4b2a76b9719d911017c592" in result.sanitized_text
