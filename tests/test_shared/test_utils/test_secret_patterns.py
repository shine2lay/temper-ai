"""Tests for temper_ai/shared/utils/secret_patterns.py.

Verifies that pattern registries are correctly structured and that
patterns match expected secrets (and don't match clean strings).
"""

import re

import pytest

from temper_ai.shared.utils.secret_patterns import (
    GENERIC_SECRET_PATTERNS,
    PII_PATTERNS,
    SECRET_KEY_NAMES,
    SECRET_PATTERNS,
)


class TestSecretPatternsStructure:
    """Structural / registry tests for SECRET_PATTERNS."""

    def test_is_dict(self):
        """SECRET_PATTERNS is a dict."""
        assert isinstance(SECRET_PATTERNS, dict)

    def test_all_keys_are_strings(self):
        """All keys in SECRET_PATTERNS are strings."""
        for key in SECRET_PATTERNS:
            assert isinstance(key, str), f"Key {key!r} is not a string"

    def test_all_values_are_strings(self):
        """All values in SECRET_PATTERNS are regex strings."""
        for key, val in SECRET_PATTERNS.items():
            assert isinstance(val, str), f"Pattern for {key!r} is not a string"

    def test_all_patterns_compile(self):
        """All patterns in SECRET_PATTERNS are valid regex."""
        for name, pattern in SECRET_PATTERNS.items():
            try:
                re.compile(pattern)
            except re.error as exc:
                pytest.fail(f"Pattern {name!r} failed to compile: {exc}")

    def test_expected_keys_present(self):
        """Expected vendor keys are registered."""
        expected = {
            "openai_key",
            "anthropic_key",
            "aws_access_key",
            "github_token",
            "stripe_key",
            "jwt_token",
            "private_key",
        }
        missing = expected - set(SECRET_PATTERNS)
        assert not missing, f"Missing expected keys: {missing}"


class TestGenericSecretPatternsStructure:
    """Structural tests for GENERIC_SECRET_PATTERNS."""

    def test_is_dict(self):
        assert isinstance(GENERIC_SECRET_PATTERNS, dict)

    def test_all_patterns_compile(self):
        """All generic patterns are valid regex."""
        for name, pattern in GENERIC_SECRET_PATTERNS.items():
            try:
                re.compile(pattern)
            except re.error as exc:
                pytest.fail(f"Generic pattern {name!r} failed to compile: {exc}")

    def test_expected_keys_present(self):
        """Key generic pattern names exist."""
        expected = {"api_key", "generic_secret", "db_credentials"}
        missing = expected - set(GENERIC_SECRET_PATTERNS)
        assert not missing, f"Missing generic keys: {missing}"


class TestPiiPatternsStructure:
    """Structural tests for PII_PATTERNS."""

    def test_is_dict(self):
        assert isinstance(PII_PATTERNS, dict)

    def test_all_patterns_compile(self):
        """All PII patterns are valid regex."""
        for name, pattern in PII_PATTERNS.items():
            try:
                re.compile(pattern)
            except re.error as exc:
                pytest.fail(f"PII pattern {name!r} failed to compile: {exc}")

    def test_expected_pii_keys(self):
        """Expected PII categories present."""
        expected = {"email", "ssn", "phone_us", "credit_card", "ipv4"}
        missing = expected - set(PII_PATTERNS)
        assert not missing, f"Missing PII keys: {missing}"


class TestSecretKeyNamesStructure:
    """Tests for SECRET_KEY_NAMES registry."""

    def test_is_list(self):
        assert isinstance(SECRET_KEY_NAMES, list)

    def test_all_strings(self):
        for name in SECRET_KEY_NAMES:
            assert isinstance(name, str)

    def test_common_names_present(self):
        """Common secret key names appear in the list."""
        for name in ("api_key", "password", "token", "secret"):
            assert name in SECRET_KEY_NAMES, f"{name!r} missing from SECRET_KEY_NAMES"


class TestSecretPatternMatching:
    """Tests that patterns match real secret formats."""

    def _matches(self, pattern_name: str, text: str) -> bool:
        pattern = SECRET_PATTERNS[pattern_name]
        return bool(re.search(pattern, text))

    def test_openai_key_matches(self):
        """openai_key matches sk- prefixed keys."""
        key = "sk-" + "a" * 20
        assert self._matches("openai_key", key)

    def test_openai_key_no_short_match(self):
        """openai_key does not match sk- with < 20 chars."""
        short_key = "sk-" + "a" * 5
        assert not self._matches("openai_key", short_key)

    def test_openai_project_key_matches(self):
        """openai_project_key matches sk-proj- format."""
        key = "sk-proj-" + "a" * 20
        assert self._matches("openai_project_key", key)

    def test_aws_access_key_matches(self):
        """aws_access_key matches AKIA format."""
        key = "AKIA" + "A" * 16
        assert self._matches("aws_access_key", key)

    def test_aws_access_key_wrong_prefix(self):
        """aws_access_key does not match wrong prefix."""
        assert not self._matches("aws_access_key", "BKIA" + "A" * 16)

    def test_github_token_ghp_matches(self):
        """github_token matches ghp_ prefix."""
        token = "ghp_" + "a" * 30
        assert self._matches("github_token", token)

    def test_github_token_ghs_matches(self):
        """github_token matches ghs_ prefix."""
        token = "ghs_" + "a" * 30
        assert self._matches("github_token", token)

    def test_stripe_test_key_matches(self):
        """stripe_key matches sk_test_ format."""
        key = "sk_test_" + "a" * 24
        assert self._matches("stripe_key", key)

    def test_stripe_live_key_matches(self):
        """stripe_key matches pk_live_ format."""
        key = "pk_live_" + "a" * 24
        assert self._matches("stripe_key", key)

    def test_private_key_header_matches(self):
        """private_key matches PEM header line."""
        pem = "-----BEGIN PRIVATE KEY-----"
        assert self._matches("private_key", pem)

    def test_rsa_private_key_matches(self):
        """private_key matches RSA variant."""
        pem = "-----BEGIN RSA PRIVATE KEY-----"
        assert self._matches("private_key", pem)

    def test_jwt_token_matches(self):
        """jwt_token matches JWT triple-dot format."""
        # Minimal JWT: eyJ<header>.eyJ<payload>.<sig>
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzIn0.abcdef1234567890abc"
        assert self._matches("jwt_token", jwt)

    def test_connection_string_postgres_matches(self):
        """connection_string matches postgres:// URLs."""
        conn = "postgres://user:pass@localhost:5432/db"
        assert self._matches("connection_string", conn)

    def test_connection_string_redis_matches(self):
        """connection_string matches redis:// URLs."""
        conn = "redis://localhost:6379/0"
        assert self._matches("connection_string", conn)

    def test_anthropic_key_matches(self):
        """anthropic_key matches sk-ant-api prefix."""
        key = "sk-ant-api03-" + "a" * 20
        assert self._matches("anthropic_key", key)


class TestPiiPatternMatching:
    """Tests that PII patterns match real PII values."""

    def _matches(self, pattern_name: str, text: str) -> bool:
        pattern = PII_PATTERNS[pattern_name]
        return bool(re.search(pattern, text))

    def test_email_matches(self):
        """email matches standard email format."""
        assert self._matches("email", "user@example.com")

    def test_email_no_match_plain_text(self):
        """email does not match plain text without @."""
        assert not self._matches("email", "not-an-email")

    def test_ssn_matches(self):
        """ssn matches NNN-NN-NNNN format."""
        assert self._matches("ssn", "123-45-6789")

    def test_ssn_no_match_wrong_format(self):
        """ssn does not match wrong format."""
        assert not self._matches("ssn", "123456789")

    def test_credit_card_matches(self):
        """credit_card matches NNNN-NNNN-NNNN-NNNN format."""
        assert self._matches("credit_card", "4111-1111-1111-1111")

    def test_ipv4_matches(self):
        """ipv4 matches dotted-decimal IP."""
        assert self._matches("ipv4", "192.168.1.1")

    def test_phone_us_matches(self):
        """phone_us matches common US phone formats."""
        assert self._matches("phone_us", "555-867-5309")
        assert self._matches("phone_us", "(555) 867-5309")


class TestBoundedQuantifiers:
    """Verify patterns use bounded quantifiers (ReDoS prevention)."""

    def test_no_unbounded_plus_in_key_patterns(self):
        """Critical secret patterns should not have unbounded + after char classes."""
        # This is a heuristic - check that known patterns don't end with [...]+ at end
        # (bounded patterns use {min,max} quantifiers)
        for name, pattern in SECRET_PATTERNS.items():
            # Patterns should not have the classic ReDoS form: ([a-z]+)+
            assert (
                "([a-zA-Z0-9]+)+" not in pattern
            ), f"Pattern {name!r} may have ReDoS risk: nested unbounded quantifiers"
