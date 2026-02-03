"""Tests for code-high-allowlist-pii-35.

Verifies that the full-text allowlist check no longer bypasses PII
redaction when allowlisted patterns appear alongside real PII.
"""

import pytest
from src.observability.sanitization import DataSanitizer, SanitizationConfig


def _make_sanitizer(allowlist_patterns=None):
    """Create a sanitizer with configurable allowlist."""
    config = SanitizationConfig(
        redact_emails=True,
        redact_ssn=True,
        redact_phone_numbers=True,
        redact_credit_cards=True,
        redact_ip_addresses=True,
        redact_high_confidence_secrets=True,
        allowlist_patterns=allowlist_patterns or [],
    )
    return DataSanitizer(config)


class TestAllowlistPIIRedaction:
    """Verify allowlist doesn't bypass PII redaction globally."""

    def test_allowlisted_domain_does_not_bypass_ssn(self):
        """Allowlisted domain in text should NOT prevent SSN redaction."""
        sanitizer = _make_sanitizer(allowlist_patterns=[r"example\.com"])
        text = "Contact support@example.com about SSN 123-45-6789"
        result = sanitizer.sanitize_text(text)
        # SSN should be redacted
        assert "123-45-6789" not in result.sanitized_text
        assert "SSN_REDACTED" in result.sanitized_text
        # example.com email may be preserved since the email itself is allowlisted
        # The key point: SSN must be redacted despite allowlisted domain

    def test_allowlisted_domain_does_not_bypass_credit_card(self):
        """Allowlisted domain should NOT prevent credit card redaction."""
        sanitizer = _make_sanitizer(allowlist_patterns=[r"example\.com"])
        text = "Visit example.com and pay with 4111-1111-1111-1111"
        result = sanitizer.sanitize_text(text)
        assert "4111-1111-1111-1111" not in result.sanitized_text

    def test_only_allowlisted_pii_preserved(self):
        """Text with only allowlisted PII should not be redacted."""
        sanitizer = _make_sanitizer(allowlist_patterns=[r"test@example\.com"])
        text = "Contact test@example.com for support"
        result = sanitizer.sanitize_text(text)
        # The email matches the allowlist, so it should be preserved
        assert "test@example.com" in result.sanitized_text

    def test_non_allowlisted_pii_always_redacted(self):
        """Text without any allowlisted content should redact all PII."""
        sanitizer = _make_sanitizer(allowlist_patterns=[r"example\.com"])
        text = "SSN: 123-45-6789 and phone: 555-123-4567"
        result = sanitizer.sanitize_text(text)
        assert "123-45-6789" not in result.sanitized_text

    def test_mixed_allowlisted_and_non_allowlisted(self):
        """Only non-allowlisted PII should be redacted in mixed text."""
        sanitizer = _make_sanitizer(allowlist_patterns=[r"admin@internal\.corp"])
        text = "Email admin@internal.corp about SSN 987-65-4321"
        result = sanitizer.sanitize_text(text)
        # SSN must be redacted regardless of allowlisted email
        assert "987-65-4321" not in result.sanitized_text
        assert "SSN_REDACTED" in result.sanitized_text

    def test_empty_allowlist_redacts_everything(self):
        """With no allowlist, all PII is redacted."""
        sanitizer = _make_sanitizer(allowlist_patterns=[])
        text = "SSN: 123-45-6789 email: user@domain.com"
        result = sanitizer.sanitize_text(text)
        assert "123-45-6789" not in result.sanitized_text
        assert "user@domain.com" not in result.sanitized_text

    def test_per_match_allowlist_still_works(self):
        """Individual PII matches that are allowlisted are preserved."""
        sanitizer = _make_sanitizer(allowlist_patterns=[r"192\.168\.1\.1"])
        text = "Server at 192.168.1.1 and attacker at 10.0.0.42"
        result = sanitizer.sanitize_text(text)
        # 192.168.1.1 is allowlisted, should be preserved
        assert "192.168.1.1" in result.sanitized_text
        # 10.0.0.42 is NOT allowlisted, should be redacted
        assert "10.0.0.42" not in result.sanitized_text
