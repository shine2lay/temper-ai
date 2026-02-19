"""Comprehensive tests for OAuth Callback URL Validator - P0 SECURITY.

Tests cover:
1. Redirect URI validation (exact match, no open redirect)
2. URL scheme validation (HTTPS enforcement)
3. Hostname validation (prevent subdomain takeover)
4. Localhost validation (IPv4/IPv6 loopback detection)
5. Query parameter and fragment rejection
6. Case-insensitive URL comparison (RFC 3986)
7. URL normalization
8. Production vs development mode
"""
import pytest

from temper_ai.auth.oauth.callback_validator import CallbackURLValidator


class TestCallbackURLValidatorInitialization:
    """Test CallbackURLValidator initialization."""

    def test_initialization_with_allowed_urls(self):
        """Test initialization with allowed URLs."""
        allowed = ["https://app.example.com/callback"]
        validator = CallbackURLValidator(allowed)

        assert "https://app.example.com/callback" in validator.allowed_urls
        assert len(validator.allowed_urls) == 1

    def test_initialization_auto_detect_dev_environment(self, monkeypatch):
        """Test initialization auto-detects development environment."""
        monkeypatch.setenv("ENVIRONMENT", "development")

        validator = CallbackURLValidator([])

        assert validator.allow_localhost is True

    def test_initialization_auto_detect_prod_environment(self, monkeypatch):
        """Test initialization auto-detects production environment."""
        monkeypatch.setenv("ENVIRONMENT", "production")

        validator = CallbackURLValidator([])

        assert validator.allow_localhost is False

    def test_initialization_explicit_allow_localhost(self):
        """Test initialization with explicit allow_localhost."""
        validator = CallbackURLValidator([], allow_localhost=True)

        assert validator.allow_localhost is True

    def test_initialization_default_environment(self, monkeypatch):
        """Test initialization defaults to development if ENVIRONMENT not set."""
        monkeypatch.delenv("ENVIRONMENT", raising=False)

        validator = CallbackURLValidator([])

        assert validator.allow_localhost is True


class TestURLSchemeValidation:
    """Test URL scheme validation (security: prevent javascript:, file:, data: schemes)."""

    def test_https_scheme_allowed(self):
        """Test HTTPS scheme is allowed."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://app.example.com/callback")

        assert is_valid is True
        assert error is None

    def test_http_scheme_allowed_in_dev(self):
        """Test HTTP scheme is allowed in development (localhost)."""
        validator = CallbackURLValidator(
            ["http://localhost:8000/callback"],
            allow_localhost=True
        )

        is_valid, error = validator.validate("http://localhost:8000/callback")

        assert is_valid is True
        assert error is None

    def test_http_scheme_rejected_in_prod_non_localhost(self):
        """Test HTTP scheme rejected in production for non-localhost."""
        validator = CallbackURLValidator(
            ["http://app.example.com/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("http://app.example.com/callback")

        assert is_valid is False
        assert "HTTPS required" in error

    def test_javascript_scheme_rejected(self):
        """Test javascript: scheme is rejected (XSS prevention)."""
        validator = CallbackURLValidator(
            ["javascript:alert('xss')"],
            allow_localhost=True
        )

        is_valid, error = validator.validate("javascript:alert('xss')")

        assert is_valid is False
        assert "Invalid URL scheme" in error

    def test_file_scheme_rejected(self):
        """Test file: scheme is rejected."""
        validator = CallbackURLValidator(
            ["file:///etc/passwd"],
            allow_localhost=True
        )

        is_valid, error = validator.validate("file:///etc/passwd")

        assert is_valid is False
        assert "Invalid URL scheme" in error

    def test_data_scheme_rejected(self):
        """Test data: scheme is rejected."""
        validator = CallbackURLValidator(
            ["data:text/html,<script>alert('xss')</script>"],
            allow_localhost=True
        )

        is_valid, error = validator.validate("data:text/html,<script>alert('xss')</script>")

        assert is_valid is False
        assert "Invalid URL scheme" in error

    def test_ftp_scheme_rejected(self):
        """Test ftp: scheme is rejected."""
        validator = CallbackURLValidator(
            ["ftp://example.com/file"],
            allow_localhost=True
        )

        is_valid, error = validator.validate("ftp://example.com/file")

        assert is_valid is False
        assert "Invalid URL scheme" in error


class TestHostnameValidation:
    """Test hostname validation."""

    def test_valid_hostname_accepted(self):
        """Test valid hostname is accepted."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://app.example.com/callback")

        assert is_valid is True
        assert error is None

    def test_empty_hostname_rejected(self):
        """Test empty hostname is rejected."""
        validator = CallbackURLValidator(
            ["https:///callback"],
            allow_localhost=True
        )

        is_valid, error = validator.validate("https:///callback")

        assert is_valid is False
        assert "valid hostname" in error

    def test_long_hostname_rejected(self):
        """Test hostname longer than 253 chars is rejected (RFC 1035)."""
        long_hostname = "a" * 254
        validator = CallbackURLValidator(
            [f"https://{long_hostname}.com/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate(f"https://{long_hostname}.com/callback")

        assert is_valid is False
        assert "Hostname too long" in error

    def test_ipv4_hostname_accepted(self):
        """Test IPv4 address as hostname is accepted."""
        validator = CallbackURLValidator(
            ["https://192.168.1.100/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://192.168.1.100/callback")

        assert is_valid is True
        assert error is None

    def test_ipv6_hostname_accepted(self):
        """Test IPv6 address as hostname is accepted."""
        validator = CallbackURLValidator(
            ["https://[2001:db8::1]/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://[2001:db8::1]/callback")

        assert is_valid is True
        assert error is None


class TestLocalhostValidation:
    """Test localhost and loopback address validation."""

    def test_localhost_allowed_in_dev(self):
        """Test localhost allowed in development mode."""
        validator = CallbackURLValidator(
            ["http://localhost:8000/callback"],
            allow_localhost=True
        )

        is_valid, error = validator.validate("http://localhost:8000/callback")

        assert is_valid is True
        assert error is None

    def test_localhost_rejected_in_prod(self):
        """Test localhost rejected in production mode."""
        validator = CallbackURLValidator(
            ["https://localhost:8000/callback"],  # Use HTTPS to pass HTTPS check first
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://localhost:8000/callback")

        assert is_valid is False
        assert "Localhost URLs not allowed" in error

    def test_localhost_localdomain_detected(self):
        """Test localhost.localdomain is detected as localhost."""
        validator = CallbackURLValidator(
            ["https://localhost.localdomain:8000/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://localhost.localdomain:8000/callback")

        assert is_valid is False
        assert "Localhost URLs not allowed" in error

    def test_ipv4_loopback_127_0_0_1_detected(self):
        """Test 127.0.0.1 is detected as loopback."""
        validator = CallbackURLValidator(
            ["https://127.0.0.1:8000/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://127.0.0.1:8000/callback")

        assert is_valid is False
        assert "Localhost URLs not allowed" in error

    def test_ipv4_loopback_127_x_x_x_detected(self):
        """Test all 127.x.x.x addresses detected as loopback."""
        validator = CallbackURLValidator(
            ["https://127.0.0.2:8000/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://127.0.0.2:8000/callback")

        assert is_valid is False
        assert "Localhost URLs not allowed" in error

    def test_ipv6_loopback_detected(self):
        """Test ::1 (IPv6 loopback) is detected."""
        validator = CallbackURLValidator(
            ["https://[::1]:8000/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://[::1]:8000/callback")

        assert is_valid is False
        assert "Localhost URLs not allowed" in error

    def test_ipv6_loopback_full_form_detected(self):
        """Test full IPv6 loopback form is detected."""
        validator = CallbackURLValidator(
            ["https://[0:0:0:0:0:0:0:1]:8000/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://[0:0:0:0:0:0:0:1]:8000/callback")

        assert is_valid is False
        assert "Localhost URLs not allowed" in error


class TestQueryParameterAndFragmentValidation:
    """Test query parameter and fragment rejection (prevent pollution/injection)."""

    def test_query_parameters_rejected(self):
        """Test URLs with query parameters are rejected."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://app.example.com/callback?param=value")

        assert is_valid is False
        assert "query parameters" in error

    def test_fragment_rejected(self):
        """Test URLs with fragments are rejected."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://app.example.com/callback#fragment")

        assert is_valid is False
        assert "fragments" in error

    def test_query_and_fragment_rejected(self):
        """Test URLs with both query and fragment are rejected."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://app.example.com/callback?param=value#fragment")

        assert is_valid is False
        # Should reject due to query parameters first
        assert "query parameters" in error


class TestWhitelistValidation:
    """Test whitelist exact match validation (prevent open redirect)."""

    def test_exact_match_succeeds(self):
        """Test exact URL match succeeds."""
        validator = CallbackURLValidator(
            ["https://app.example.com/auth/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://app.example.com/auth/callback")

        assert is_valid is True
        assert error is None

    def test_url_not_in_whitelist_rejected(self):
        """Test URL not in whitelist is rejected (open redirect prevention)."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://evil.com/steal-tokens")

        assert is_valid is False
        assert "not in whitelist" in error

    def test_subdomain_mismatch_rejected(self):
        """Test subdomain mismatch is rejected (prevent subdomain takeover)."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://malicious.example.com/callback")

        assert is_valid is False
        assert "not in whitelist" in error

    def test_path_mismatch_rejected(self):
        """Test path mismatch is rejected."""
        validator = CallbackURLValidator(
            ["https://app.example.com/auth/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://app.example.com/different/path")

        assert is_valid is False
        assert "not in whitelist" in error

    def test_port_mismatch_rejected(self):
        """Test port mismatch is rejected."""
        validator = CallbackURLValidator(
            ["https://app.example.com:8443/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://app.example.com:9000/callback")

        assert is_valid is False
        assert "not in whitelist" in error

    def test_multiple_allowed_urls(self):
        """Test validation against multiple allowed URLs."""
        validator = CallbackURLValidator(
            [
                "https://app.example.com/callback",
                "https://staging.example.com/callback",
                "http://localhost:8000/callback"
            ],
            allow_localhost=True
        )

        assert validator.validate("https://app.example.com/callback")[0] is True
        assert validator.validate("https://staging.example.com/callback")[0] is True
        assert validator.validate("http://localhost:8000/callback")[0] is True
        assert validator.validate("https://evil.com/callback")[0] is False


class TestURLNormalization:
    """Test URL normalization (case-insensitive comparison per RFC 3986)."""

    def test_case_insensitive_scheme(self):
        """Test scheme comparison is case-insensitive."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("HTTPS://app.example.com/callback")

        assert is_valid is True
        assert error is None

    def test_case_insensitive_hostname(self):
        """Test hostname comparison is case-insensitive."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://APP.EXAMPLE.COM/callback")

        assert is_valid is True
        assert error is None

    def test_case_sensitive_path(self):
        """Test path comparison is case-sensitive (per RFC 3986)."""
        validator = CallbackURLValidator(
            ["https://app.example.com/auth/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("https://app.example.com/AUTH/CALLBACK")

        assert is_valid is False
        assert "not in whitelist" in error

    def test_trailing_slash_normalized(self):
        """Test trailing slash is normalized (removed) in URL comparison."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        # Trailing slash is normalized away by _normalize_url
        is_valid, error = validator.validate("https://app.example.com/callback/")

        # Should pass because normalization removes trailing slash
        assert is_valid is True
        assert error is None

    def test_normalization_removes_trailing_slash(self):
        """Test URL normalization removes trailing slash from input."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        # Manually test normalization
        normalized = validator._normalize_url("https://app.example.com/callback/")

        assert normalized == "https://app.example.com/callback"


class TestValidatorHelperMethods:
    """Test validator helper methods."""

    def test_get_allowed_urls(self):
        """Test get_allowed_urls returns sorted list."""
        urls = [
            "https://c.example.com/callback",
            "https://a.example.com/callback",
            "https://b.example.com/callback"
        ]
        validator = CallbackURLValidator(urls, allow_localhost=False)

        allowed = validator.get_allowed_urls()

        assert allowed == sorted(urls)

    def test_add_allowed_url(self):
        """Test add_allowed_url adds URL to whitelist."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        validator.add_allowed_url("https://new.example.com/callback")

        assert "https://new.example.com/callback" in validator.allowed_urls

    def test_add_allowed_url_security_warning(self):
        """Test add_allowed_url should be used with caution (security)."""
        validator = CallbackURLValidator([], allow_localhost=False)

        # Adding malicious URL should be possible but discouraged
        validator.add_allowed_url("https://evil.com/steal")

        # Verify it was added (user responsibility to validate)
        assert "https://evil.com/steal" in validator.allowed_urls

    def test_remove_allowed_url(self):
        """Test remove_allowed_url removes URL from whitelist."""
        validator = CallbackURLValidator(
            ["https://app.example.com/callback"],
            allow_localhost=False
        )

        removed = validator.remove_allowed_url("https://app.example.com/callback")

        assert removed is True
        assert "https://app.example.com/callback" not in validator.allowed_urls

    def test_remove_nonexistent_url(self):
        """Test remove_allowed_url returns False for nonexistent URL."""
        validator = CallbackURLValidator([], allow_localhost=False)

        removed = validator.remove_allowed_url("https://nonexistent.com/callback")

        assert removed is False


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_url_rejected(self):
        """Test empty URL is rejected."""
        validator = CallbackURLValidator([], allow_localhost=True)

        is_valid, error = validator.validate("")

        assert is_valid is False
        assert "Callback URL is required" in error

    def test_malformed_url_rejected(self):
        """Test malformed URL is rejected."""
        validator = CallbackURLValidator([], allow_localhost=True)

        # URL with invalid characters
        is_valid, error = validator.validate("https://[invalid")

        assert is_valid is False
        # May fail at different validation stages, just ensure it's rejected
        assert is_valid is False

    def test_url_without_scheme_rejected(self):
        """Test URL without scheme is rejected."""
        validator = CallbackURLValidator(
            ["app.example.com/callback"],
            allow_localhost=False
        )

        is_valid, error = validator.validate("app.example.com/callback")

        assert is_valid is False

    def test_whitelist_empty_allows_none(self):
        """Test empty whitelist rejects all URLs."""
        validator = CallbackURLValidator([], allow_localhost=False)

        is_valid, error = validator.validate("https://app.example.com/callback")

        assert is_valid is False
        assert "not in whitelist" in error


class TestProductionVsDevelopmentMode:
    """Test production vs development security policies."""

    def test_production_mode_enforces_https(self, monkeypatch):
        """Test production mode enforces HTTPS."""
        monkeypatch.setenv("ENVIRONMENT", "production")

        validator = CallbackURLValidator(
            ["http://app.example.com/callback"],
        )

        is_valid, error = validator.validate("http://app.example.com/callback")

        assert is_valid is False
        assert "HTTPS required" in error

    def test_production_mode_rejects_localhost(self, monkeypatch):
        """Test production mode rejects localhost."""
        monkeypatch.setenv("ENVIRONMENT", "production")

        validator = CallbackURLValidator(
            ["https://localhost:8000/callback"],
        )

        is_valid, error = validator.validate("https://localhost:8000/callback")

        assert is_valid is False
        assert "Localhost URLs not allowed" in error

    def test_development_mode_allows_http_localhost(self, monkeypatch):
        """Test development mode allows HTTP localhost."""
        monkeypatch.setenv("ENVIRONMENT", "development")

        validator = CallbackURLValidator(
            ["http://localhost:8000/callback"],
        )

        is_valid, error = validator.validate("http://localhost:8000/callback")

        assert is_valid is True
        assert error is None

    def test_development_mode_still_validates_whitelist(self, monkeypatch):
        """Test development mode still enforces whitelist validation."""
        monkeypatch.setenv("ENVIRONMENT", "development")

        validator = CallbackURLValidator(
            ["http://localhost:8000/callback"],
        )

        is_valid, error = validator.validate("http://localhost:9000/callback")

        assert is_valid is False
        assert "not in whitelist" in error
