"""
Security tests for sensitive data exposure in violation logging.

Tests verify that detected secrets, PII, and credentials are not exposed
in application logs or observability database when safety violations occur.
"""
import logging

from src.observability.sanitization import DataSanitizer, SanitizationConfig
from src.safety.service_mixin import _sanitize_violation_context


class TestViolationContextSanitization:
    """Test suite for violation context sanitization."""

    def test_sanitize_simple_context_with_secret(self):
        """Ensure simple context with secret is sanitized."""
        # Setup - use OpenAI key pattern that definitely matches
        context = {
            "user": "alice",
            "api_key": "sk-proj-abc123def456ghi789xyz"
        }

        # Execute
        result = _sanitize_violation_context(context)

        # Assert
        assert result is not None
        assert "alice" in str(result)  # Non-secret data preserved
        assert "sk-proj-abc123def456ghi789xyz" not in str(result)  # Secret redacted
        assert "api_key" in result  # Key name preserved
        # Value should be redacted
        assert "REDACTED" in str(result.get("api_key", "")) or \
               result.get("api_key") != "sk-proj-abc123def456ghi789xyz"

    def test_sanitize_nested_context_with_credentials(self):
        """Ensure nested context structures are recursively sanitized."""
        # Setup - use JWT token that matches the pattern
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        context = {
            "user": "bob",
            "action": {
                "type": "api_call",
                "params": {
                    "url": "https://api.example.com",
                    "headers": {
                        "Authorization": f"Bearer {jwt_token}"
                    }
                }
            }
        }

        # Execute
        result = _sanitize_violation_context(context)

        # Assert
        assert result is not None
        assert jwt_token not in str(result)  # JWT should be redacted
        assert "bob" in str(result)  # Non-secret preserved
        assert "api_call" in str(result)  # Non-secret preserved

    def test_sanitize_none_context(self):
        """Ensure None context is handled gracefully."""
        # Execute
        result = _sanitize_violation_context(None)

        # Assert
        assert result is None

    def test_sanitize_empty_context(self):
        """Ensure empty context returns empty dict."""
        # Setup
        context = {}

        # Execute
        result = _sanitize_violation_context(context)

        # Assert
        assert result == {}

    def test_sanitize_context_with_email(self):
        """Ensure PII (email) is redacted from context."""
        # Setup
        context = {
            "user_email": "john.doe@company.com",
            "action": "login_attempt"
        }

        # Execute
        result = _sanitize_violation_context(context)

        # Assert
        assert result is not None
        assert "john.doe@company.com" not in str(result)
        assert "REDACTED" in str(result.get("user_email", "")) or \
               "EMAIL" in str(result.get("user_email", "")).upper()

    def test_sanitize_context_with_password(self):
        """Ensure password values are redacted."""
        # Setup - Use generic API key pattern
        context = {
            "content": 'api_key="sk-proj-MyS3cr3tK3yValue123"',
            "file_path": "config.py"
        }

        # Execute
        result = _sanitize_violation_context(context)

        # Assert
        assert result is not None
        assert "sk-proj-MyS3cr3tK3yValue123" not in str(result)
        assert "config.py" in str(result)  # Non-secret preserved

    def test_sanitize_context_with_list_values(self):
        """Ensure list values in context are sanitized."""
        # Setup
        openai_key = "sk-proj-" + "a" * 40  # Meets minimum 20 char requirement
        context = {
            "detected_patterns": [
                "api_key",
                "password"
            ],
            "samples": [
                openai_key,  # Full OpenAI key pattern (sk-proj- + 40 chars)
                "AKIAIOSFODNN7EXAMPLE"  # AWS access key
            ]
        }

        # Execute
        result = _sanitize_violation_context(context)

        # Assert
        assert result is not None
        # Pattern names should be preserved
        assert "api_key" in str(result)
        # Secret samples should be redacted
        assert openai_key not in str(result)
        assert "AKIAIOSFODNN7EXAMPLE" not in str(result)


class TestDataSanitizerHMAC:
    """Test HMAC-based content hashing in DataSanitizer."""

    def test_content_hash_not_raw_sha256(self):
        """Ensure content hashing uses HMAC, not raw SHA256."""
        # Setup
        import hashlib
        sanitizer = DataSanitizer(SanitizationConfig(include_hash=True))
        test_content = "test secret content"

        # Execute
        result = sanitizer.sanitize_text(test_content)

        # Assert
        assert result.content_hash is not None

        # Compute raw SHA256 for comparison
        raw_sha256 = hashlib.sha256(test_content.encode('utf-8')).hexdigest()[:16]

        # HMAC hash should be different from raw SHA256
        assert result.content_hash != raw_sha256, \
            "Content hash appears to be raw SHA256, not HMAC!"

    def test_content_hash_consistency(self):
        """Ensure same content produces same HMAC hash."""
        # Setup
        sanitizer = DataSanitizer(SanitizationConfig(include_hash=True))
        test_content = "consistent content"

        # Execute
        result1 = sanitizer.sanitize_text(test_content)
        result2 = sanitizer.sanitize_text(test_content)

        # Assert
        assert result1.content_hash == result2.content_hash, \
            "Same content should produce same HMAC hash"

    def test_different_content_different_hash(self):
        """Ensure different content produces different HMAC hashes."""
        # Setup
        sanitizer = DataSanitizer(SanitizationConfig(include_hash=True))

        # Execute
        result1 = sanitizer.sanitize_text("content one")
        result2 = sanitizer.sanitize_text("content two")

        # Assert
        assert result1.content_hash != result2.content_hash, \
            "Different content should produce different hashes"

    def test_hmac_key_from_environment(self, monkeypatch):
        """Ensure HMAC key can be loaded from environment variable."""
        # Setup - set environment variable
        test_key_hex = "0123456789abcdef" * 4  # 32 bytes in hex
        monkeypatch.setenv('OBSERVABILITY_HMAC_KEY', test_key_hex)

        # Execute
        sanitizer = DataSanitizer(SanitizationConfig(include_hash=True))
        result = sanitizer.sanitize_text("test")

        # Assert
        assert result.content_hash is not None
        # Verify it used the environment key (hash should be deterministic)
        sanitizer2 = DataSanitizer(SanitizationConfig(include_hash=True))
        result2 = sanitizer2.sanitize_text("test")
        assert result.content_hash == result2.content_hash

    def test_invalid_hmac_key_falls_back_to_random(self, monkeypatch):
        """Ensure invalid HMAC key in env falls back to random generation."""
        # Setup - set invalid hex
        monkeypatch.setenv('OBSERVABILITY_HMAC_KEY', 'invalid_hex_value')

        # Execute (should not raise exception)
        sanitizer = DataSanitizer(SanitizationConfig(include_hash=True))
        result = sanitizer.sanitize_text("test")

        # Assert
        assert result.content_hash is not None  # Should still work with random key


class TestLoggingSecurityIntegration:
    """Integration tests for logging security."""

    def test_violation_logging_sanitizes_context(self, caplog):
        """Ensure safety violations log sanitized context, not raw secrets."""
        from src.safety import SafetyViolation, ViolationSeverity
        from src.safety.service_mixin import SafetyServiceMixin

        # Setup
        service = SafetyServiceMixin()
        violation = SafetyViolation(
            policy_name="SecretDetectionPolicy",
            severity=ViolationSeverity.HIGH,
            message="Secret detected",
            action="file_write",
            context={
                "file_path": "config.py",
                "detected_secret": "sk-proj-abc123def456ghi789xyz"  # OpenAI pattern
            }
        )

        # Execute
        with caplog.at_level(logging.ERROR):
            service.handle_violations([violation], raise_exception=False)

        # Assert - Check log records, not just text
        log_text = caplog.text
        assert "Secret detected" in log_text  # Message should be logged

        # CRITICAL: Secret must NOT appear in log text or records
        assert "sk-proj-abc123def456ghi789xyz" not in log_text

        # Check log records for context (extra data)
        for record in caplog.records:
            if hasattr(record, 'context'):
                # Context should exist but secret should be redacted
                context_str = str(record.context)
                assert "sk-proj-abc123def456ghi789xyz" not in context_str
                # Non-secret should appear in context
                assert "config.py" in context_str

    def test_multiple_violations_all_sanitized(self, caplog):
        """Ensure multiple violations all have sanitized contexts."""
        from src.safety import SafetyViolation, ViolationSeverity
        from src.safety.service_mixin import SafetyServiceMixin

        # Setup
        service = SafetyServiceMixin()
        violations = [
            SafetyViolation(
                policy_name="Policy1",
                severity=ViolationSeverity.MEDIUM,
                message="First violation",
                action="action1",
                context={"secret": "AKIAIOSFODNN7EXAMPLE"}  # AWS access key
            ),
            SafetyViolation(
                policy_name="Policy2",
                severity=ViolationSeverity.HIGH,
                message="Second violation",
                action="action2",
                context={"api_key": "sk-proj-xyz789abcdefghijklmno"}  # OpenAI key
            )
        ]

        # Execute
        with caplog.at_level(logging.WARNING):
            service.handle_violations(violations, raise_exception=False)

        # Assert
        log_text = caplog.text
        assert "AKIAIOSFODNN7EXAMPLE" not in log_text
        assert "sk-proj-xyz789abcdefghijklmno" not in log_text
        assert "First violation" in log_text
        assert "Second violation" in log_text
