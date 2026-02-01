"""Tests for OAuth Callback URL Validator.

SECURITY: These tests verify protection against:
- Open redirect attacks
- CSRF attacks
- Subdomain takeover
- Parameter pollution
"""
import pytest
from src.auth.oauth.callback_validator import CallbackURLValidator


class TestCallbackURLValidator:
    """Test OAuth callback URL validation."""

    def test_valid_https_url_accepted(self):
        """Valid HTTPS URL should be accepted."""
        validator = CallbackURLValidator(
            ["https://app.example.com/auth/callback"], allow_localhost=False
        )

        is_valid, error = validator.validate("https://app.example.com/auth/callback")
        assert is_valid is True
        assert error is None

    def test_valid_localhost_in_dev(self):
        """Localhost URLs should be accepted in dev."""
        validator = CallbackURLValidator(
            ["http://localhost:8000/auth/callback"], allow_localhost=True
        )

        is_valid, error = validator.validate("http://localhost:8000/auth/callback")
        assert is_valid is True
        assert error is None

    def test_localhost_127_accepted_in_dev(self):
        """127.0.0.1 URLs should be accepted in dev."""
        validator = CallbackURLValidator(
            ["http://127.0.0.1:8000/auth/callback"], allow_localhost=True
        )

        is_valid, error = validator.validate("http://127.0.0.1:8000/auth/callback")
        assert is_valid is True

    def test_localhost_rejected_in_prod(self):
        """Localhost URLs should be rejected in production with specific error."""
        # Note: http://localhost fails HTTPS check first, before localhost check
        # To test localhost-specific rejection, use https://localhost
        validator = CallbackURLValidator(
            ["https://localhost:8000/auth/callback"], allow_localhost=False
        )

        is_valid, error = validator.validate("https://localhost:8000/auth/callback")
        assert is_valid is False, "Localhost should be rejected in production"

        # Validate error message is specific and actionable
        assert "Localhost URLs not allowed in production" in error or \
               "localhost" in error.lower(), \
               f"Error message should mention localhost restriction: {error}"

        # SECURITY: Validate error message doesn't leak port number
        assert "8000" not in error, \
               f"Error message should not leak port numbers: {error}"

    def test_http_rejected_in_prod(self):
        """HTTP URLs should be rejected in production with security context."""
        validator = CallbackURLValidator(
            ["http://app.example.com/auth/callback"], allow_localhost=False
        )

        is_valid, error = validator.validate("http://app.example.com/auth/callback")
        assert is_valid is False, "HTTP should be rejected in production"

        # Validate error message mentions HTTPS requirement
        assert "HTTPS required" in error or \
               ("https" in error.lower() and "http" in error.lower()), \
               f"Error message should mention HTTPS requirement: {error}"

        # Validate error message doesn't leak the full URL
        assert "app.example.com" not in error or "domain" in error.lower(), \
               "Error message should not leak domain names without context"

    def test_url_with_query_params_rejected(self):
        """URLs with query parameters should be rejected (parameter pollution protection)."""
        validator = CallbackURLValidator(["https://app.example.com/auth/callback"])

        malicious_url = "https://app.example.com/auth/callback?code=123&state=abc"
        is_valid, error = validator.validate(malicious_url)

        assert is_valid is False, "URLs with query parameters should be rejected (parameter pollution)"

        # Validate error message indicates query parameter issue
        assert "query parameters" in error.lower() or \
               "query" in error.lower() or \
               "parameter" in error.lower(), \
               f"Error message should mention query parameters: {error}"

        # SECURITY: Validate error message doesn't echo the query parameters
        assert "code=123" not in error, \
               f"Error message should not echo query parameter values: {error}"
        assert "state=abc" not in error, \
               f"Error message should not echo query parameter values: {error}"

    def test_url_with_fragment_rejected(self):
        """URLs with fragments should be rejected."""
        validator = CallbackURLValidator(["https://app.example.com/auth/callback"])

        is_valid, error = validator.validate(
            "https://app.example.com/auth/callback#section"
        )
        assert is_valid is False
        assert "fragments" in error.lower()

    def test_url_not_in_whitelist_rejected(self):
        """URLs not in whitelist should be rejected (open redirect protection)."""
        validator = CallbackURLValidator(["https://app.example.com/auth/callback"])

        is_valid, error = validator.validate("https://evil.com/steal")
        assert is_valid is False, "Non-whitelisted URL should be rejected (open redirect protection)"

        # Validate error message indicates whitelist check failure
        assert "not in whitelist" in error.lower() or \
               "not allowed" in error.lower() or \
               "invalid" in error.lower(), \
               f"Error message should indicate whitelist validation failure: {error}"

        # SECURITY: Validate error message doesn't echo the malicious URL
        assert "evil.com" not in error, \
               f"Error message should not echo potentially malicious URLs: {error}"
        assert "/steal" not in error, \
               f"Error message should not echo attacker-controlled paths: {error}"

    def test_subdomain_not_matched(self):
        """Subdomains should not match parent domain (subdomain takeover protection)."""
        validator = CallbackURLValidator(["https://app.example.com/auth/callback"])

        # Should NOT match subdomain
        is_valid, error = validator.validate("https://evil.app.example.com/auth/callback")
        assert is_valid is False

    def test_trailing_slash_normalized(self):
        """Trailing slashes should be normalized."""
        validator = CallbackURLValidator(["https://app.example.com/auth/callback"])

        # Should match even with trailing slash
        is_valid, _ = validator.validate("https://app.example.com/auth/callback/")
        assert is_valid is True

        # Reverse: whitelist has trailing slash
        validator2 = CallbackURLValidator(["https://app.example.com/auth/callback/"])
        is_valid, _ = validator2.validate("https://app.example.com/auth/callback")
        assert is_valid is True

    def test_empty_url_rejected(self):
        """Empty URLs should be rejected."""
        validator = CallbackURLValidator(["https://app.example.com/auth/callback"])

        is_valid, error = validator.validate("")
        assert is_valid is False
        assert "required" in error.lower()

    def test_invalid_url_format_rejected(self):
        """Malformed URLs should be rejected."""
        validator = CallbackURLValidator(["https://app.example.com/auth/callback"])

        is_valid, error = validator.validate("not-a-valid-url")
        assert is_valid is False
        # Malformed URLs may fail scheme check or other validations
        assert "Invalid URL format" in error or \
               "not in whitelist" in error.lower() or \
               "Invalid URL scheme" in error

    def test_multiple_allowed_urls(self):
        """Multiple whitelisted URLs should all be accepted."""
        validator = CallbackURLValidator([
            "https://app.example.com/auth/callback",
            "https://staging.example.com/auth/callback",
            "http://localhost:8000/auth/callback",
        ], allow_localhost=True)

        # All should be valid
        assert validator.validate("https://app.example.com/auth/callback")[0] is True
        assert validator.validate("https://staging.example.com/auth/callback")[0] is True
        assert validator.validate("http://localhost:8000/auth/callback")[0] is True

        # But not this
        assert validator.validate("https://evil.com/callback")[0] is False

    def test_get_allowed_urls(self):
        """Should return sorted list of allowed URLs."""
        urls = [
            "https://app.example.com/auth/callback",
            "http://localhost:8000/auth/callback",
        ]
        validator = CallbackURLValidator(urls)

        allowed = validator.get_allowed_urls()
        assert len(allowed) == 2
        assert "https://app.example.com/auth/callback" in allowed
        assert "http://localhost:8000/auth/callback" in allowed
        # Should be sorted
        assert allowed == sorted(allowed)

    def test_add_allowed_url(self):
        """Should allow adding URLs to whitelist."""
        validator = CallbackURLValidator(["https://app.example.com/auth/callback"])

        # Initially not allowed
        assert validator.validate("https://new.example.com/callback")[0] is False

        # Add to whitelist
        validator.add_allowed_url("https://new.example.com/callback")

        # Now should be allowed
        assert validator.validate("https://new.example.com/callback")[0] is True

    def test_remove_allowed_url(self):
        """Should allow removing URLs from whitelist."""
        validator = CallbackURLValidator([
            "https://app.example.com/auth/callback",
            "https://remove-me.example.com/callback",
        ])

        # Initially allowed
        assert validator.validate("https://remove-me.example.com/callback")[0] is True

        # Remove from whitelist
        result = validator.remove_allowed_url("https://remove-me.example.com/callback")
        assert result is True

        # Now should be rejected
        assert validator.validate("https://remove-me.example.com/callback")[0] is False

        # Removing non-existent URL returns False
        result = validator.remove_allowed_url("https://never-existed.com/callback")
        assert result is False

    def test_path_must_match_exactly(self):
        """Path must match exactly (prevent path traversal)."""
        validator = CallbackURLValidator(["https://app.example.com/auth/callback"])

        # Different paths should not match
        assert validator.validate("https://app.example.com/auth/admin")[0] is False
        assert validator.validate("https://app.example.com/auth")[0] is False
        assert validator.validate("https://app.example.com/")[0] is False

    def test_port_must_match(self):
        """Port numbers must match exactly."""
        validator = CallbackURLValidator(["https://app.example.com:8443/auth/callback"])

        # Wrong port should not match
        assert validator.validate("https://app.example.com:9000/auth/callback")[0] is False
        assert validator.validate("https://app.example.com/auth/callback")[0] is False

        # Correct port should match
        assert validator.validate("https://app.example.com:8443/auth/callback")[0] is True

    @pytest.mark.parametrize("malicious_url", [
        "https://app.example.com/auth/callback@evil.com",  # Username in URL
        "https://app.example.com/auth/callback/../admin",  # Path traversal
        "https://app.example.com/auth/callback%00.evil.com",  # Null byte
        "https://app.example.com/auth/callback\r\nLocation: evil.com",  # CRLF injection
    ])
    def test_malicious_urls_rejected(self, malicious_url):
        """Various malicious URL patterns should be rejected."""
        validator = CallbackURLValidator(["https://app.example.com/auth/callback"])

        is_valid, _ = validator.validate(malicious_url)
        assert is_valid is False


class TestCallbackURLValidatorEnvironmentDetection:
    """Test automatic environment detection for localhost."""

    def test_localhost_auto_allowed_in_development(self, monkeypatch):
        """Localhost should be auto-allowed when ENVIRONMENT=development."""
        monkeypatch.setenv("ENVIRONMENT", "development")

        validator = CallbackURLValidator(["http://localhost:8000/auth/callback"])
        is_valid, _ = validator.validate("http://localhost:8000/auth/callback")
        assert is_valid is True

    def test_localhost_auto_rejected_in_production(self, monkeypatch):
        """Localhost should be auto-rejected when ENVIRONMENT=production."""
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Note: http://localhost fails HTTPS check first. Use https to test localhost check.
        validator = CallbackURLValidator(["https://localhost:8000/auth/callback"])
        is_valid, error = validator.validate("https://localhost:8000/auth/callback")
        assert is_valid is False
        assert "Localhost URLs not allowed in production" in error or \
               "localhost" in error.lower()

    def test_explicit_override_environment(self, monkeypatch):
        """Explicit allow_localhost should override environment."""
        monkeypatch.setenv("ENVIRONMENT", "production")

        # Force allow localhost even in production
        validator = CallbackURLValidator(
            ["http://localhost:8000/auth/callback"], allow_localhost=True
        )
        is_valid, _ = validator.validate("http://localhost:8000/auth/callback")
        assert is_valid is True
