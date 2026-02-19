"""
Tests for secret sanitization in violation messages.

Ensures that detected secrets are never exposed in logs, violation messages,
or metadata. This is a CRITICAL security requirement.
"""
from temper_ai.safety.secret_detection import SecretDetectionPolicy


class TestSecretSanitizationInViolations:
    """Test that secrets are redacted in violation messages."""

    def test_aws_key_not_in_violation_message(self):
        """Ensure AWS keys are not exposed in violation messages."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})

        # Test with real AWS key pattern
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        result = policy.validate({"content": aws_key}, {})

        # Should detect violation
        assert not result.valid
        assert len(result.violations) > 0

        # But message should NOT contain the actual key
        violation_message = result.violations[0].message
        assert aws_key not in violation_message
        assert "AKIAIOSFODNN7" not in violation_message

        # Should show pattern type and redacted preview
        assert "aws_access_key" in violation_message.lower() or "AWS_ACCESS_KEY" in violation_message

    def test_api_key_not_in_violation_message(self):
        """Ensure API keys are not exposed in violation messages."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})

        # Test with generic API key
        api_key = "api_key=sk_live_abc123def456ghi789jkl012mno345pqr678stu901vwx234yz"
        result = policy.validate({"content": api_key}, {})

        # Should detect violation
        assert not result.valid
        assert len(result.violations) > 0

        # But message should NOT contain the actual key
        violation_message = result.violations[0].message
        assert "sk_live_abc123def456ghi789jkl012mno345pqr678stu901vwx234yz" not in violation_message
        assert "sk_live_abc123" not in violation_message

    def test_github_token_not_in_violation_message(self):
        """Ensure GitHub tokens are not exposed in violation messages."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})

        # Test with GitHub personal access token
        gh_token = "ghp_ABC123DEF456GHI789JKL012MNO345PQR678"
        result = policy.validate({"content": gh_token}, {})

        # Should detect violation
        assert not result.valid
        assert len(result.violations) > 0

        # But message should NOT contain the actual token
        violation_message = result.violations[0].message
        assert gh_token not in violation_message
        assert "ABC123DEF456" not in violation_message

    def test_jwt_token_not_in_violation_message(self):
        """Ensure JWT tokens are not exposed in violation messages."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})

        # Test with JWT token
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result = policy.validate({"content": jwt}, {})

        # Should detect violation
        assert not result.valid
        assert len(result.violations) > 0

        # But message should NOT contain the actual JWT
        violation_message = result.violations[0].message
        assert jwt not in violation_message
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in violation_message

    def test_password_not_in_violation_message(self):
        """Ensure passwords are not exposed in violation messages."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})

        # Test with password (high entropy to trigger HIGH severity)
        password_config = 'password="MyS3cr3tP@ssw0rd!XyZ#9876abcDEF"'
        result = policy.validate({"content": password_config}, {})

        # Should detect violation (may be MEDIUM severity if low entropy)
        assert len(result.violations) > 0

        # But message should NOT contain the actual password regardless of severity
        violation_message = result.violations[0].message
        assert "MyS3cr3tP@ssw0rd!XyZ#9876abcDEF" not in violation_message
        assert "MyS3cr3t" not in violation_message
        assert "P@ssw0rd" not in violation_message

    def test_violation_metadata_does_not_leak_secret(self):
        """Ensure metadata does not contain actual secret."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})

        # Test with AWS key
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        result = policy.validate({"content": aws_key}, {})

        # Should have violation with metadata
        assert not result.valid
        violation = result.violations[0]
        assert violation.metadata is not None

        # Metadata should not contain actual key
        metadata_str = str(violation.metadata)
        assert aws_key not in metadata_str
        assert "AKIAIOSFODNN7" not in metadata_str

        # But should have pattern type and violation_id (not secret_hash for security)
        assert "pattern_type" in violation.metadata
        assert "violation_id" in violation.metadata
        # SECURITY: secret_hash removed to prevent rainbow table attacks
        assert "secret_hash" not in violation.metadata

    def test_violation_id_in_metadata(self):
        """Ensure violation_id is included for deduplication (not secret_hash)."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})

        # Test with API key
        api_key = "api_key=sk_live_abc123def456"
        result = policy.validate({"content": api_key}, {})

        # Should have violation with violation_id
        assert not result.valid
        violation = result.violations[0]

        # SECURITY: Should have violation_id (not secret_hash to prevent rainbow tables)
        assert "violation_id" in violation.metadata
        assert len(violation.metadata["violation_id"]) == 16  # HMAC truncated to 16 chars (64 bits)
        assert "secret_hash" not in violation.metadata  # Must NOT have secret_hash

        # HMAC-based violation_ids provide session-scoped deduplication
        # Same secret in same session = same violation_id
        result2 = policy.validate({"content": api_key}, {})
        violation2 = result2.violations[0]
        assert "violation_id" in violation2.metadata
        # Same secret should have same violation_id (HMAC is deterministic within session)
        assert violation.metadata["violation_id"] == violation2.metadata["violation_id"]

        # Different secret should have different violation_id
        different_key = "api_key=sk_live_xyz789different"
        result3 = policy.validate({"content": different_key}, {})
        violation3 = result3.violations[0]
        assert violation.metadata["violation_id"] != violation3.metadata["violation_id"]

    def test_match_length_in_metadata(self):
        """Ensure match length is included in metadata."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})

        # Test with AWS key
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        result = policy.validate({"content": aws_key}, {})

        # Should have violation with match length
        assert not result.valid
        violation = result.violations[0]

        # Should have match_length in metadata
        assert "match_length" in violation.metadata
        assert violation.metadata["match_length"] == len(aws_key)

    def test_redacted_preview_format(self):
        """Ensure redacted preview has correct format."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})

        # Test with AWS key
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        result = policy.validate({"content": aws_key}, {})

        # Should have violation with redacted preview
        assert not result.valid
        violation = result.violations[0]

        # Preview should be in format [PATTERN_NAME:LENGTH_chars]
        message = violation.message
        assert "[AWS_ACCESS_KEY:" in message or "[aws_access_key:" in message.lower()
        assert "_chars]" in message or "chars]" in message

    def test_multiple_secrets_all_redacted(self):
        """Ensure multiple secrets are all redacted."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})

        # Test with multiple secrets
        content = """
        aws_key = AKIAIOSFODNN7EXAMPLE
        api_key = sk_live_abc123def456ghi789
        password = "MyS3cr3tP@ssw0rd!"
        """
        result = policy.validate({"content": content}, {})

        # Should detect all violations
        assert not result.valid
        assert len(result.violations) >= 3

        # None of the secrets should be in any violation message
        for violation in result.violations:
            message = violation.message
            assert "AKIAIOSFODNN7EXAMPLE" not in message
            assert "sk_live_abc123def456ghi789" not in message
            assert "MyS3cr3tP@ssw0rd!" not in message


class TestSanitizationHelperMethods:
    """Test the sanitization helper methods directly."""

    def test_create_redacted_preview(self):
        """Test _create_redacted_preview method."""
        policy = SecretDetectionPolicy({})

        # Test AWS key preview
        preview = policy._create_redacted_preview("AKIAIOSFODNN7EXAMPLE", "aws_access_key")
        assert preview == "[AWS_ACCESS_KEY:20_chars]"
        assert "AKIA" not in preview

        # Test API key preview
        preview = policy._create_redacted_preview("sk_live_abc123def456", "generic_api_key")
        assert preview == "[GENERIC_API_KEY:20_chars]"
        assert "sk_live" not in preview

    def test_hash_secret(self):
        """Test _hash_secret method."""
        policy = SecretDetectionPolicy({})

        # Test hash generation
        secret_hash = policy._hash_secret("AKIAIOSFODNN7EXAMPLE")

        # Should be 16 characters (first 16 of SHA256)
        assert len(secret_hash) == 16

        # Should be consistent
        secret_hash2 = policy._hash_secret("AKIAIOSFODNN7EXAMPLE")
        assert secret_hash == secret_hash2

        # Different secrets should have different hashes
        secret_hash3 = policy._hash_secret("AKIAIOSFODNN7DIFFERENT")
        assert secret_hash != secret_hash3

    def test_hash_secret_deterministic(self):
        """Ensure hash is deterministic for deduplication."""
        policy = SecretDetectionPolicy({})

        # Same secret should always produce same hash
        hashes = [policy._hash_secret("test_secret") for _ in range(10)]
        assert len(set(hashes)) == 1  # All hashes identical


class TestBackwardCompatibility:
    """Ensure sanitization doesn't break existing functionality."""

    def test_detection_still_works(self):
        """Ensure secrets are still detected after sanitization."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})

        test_cases = [
            "AKIAIOSFODNN7EXAMPLE",  # AWS key
            "api_key=sk_live_abc123def456ghi789",  # API key
            "ghp_ABC123DEF456GHI789JKL012MNO345PQR678",  # GitHub token (36 chars after prefix)
            'password="SecureP@ssw0rd123VeryLongAndComplex"',  # Password
        ]

        for test_case in test_cases:
            result = policy.validate({"content": test_case}, {})
            # All should have violations (may not invalidate result if severity is MEDIUM)
            assert len(result.violations) > 0, f"Failed to detect secret in: {test_case}"

    def test_entropy_calculation_unchanged(self):
        """Ensure entropy calculation still works."""
        policy = SecretDetectionPolicy({})

        # Test entropy calculation
        entropy1 = policy._calculate_entropy("aaaaaa")  # Very low entropy (repeated)
        entropy2 = policy._calculate_entropy("aB3$xY9@kL2#mN5^pQ8&")  # High entropy (random mix)

        assert entropy1 < entropy2
        assert entropy2 > 3.5  # Should have higher entropy

    def test_test_secret_allowlist_unchanged(self):
        """Ensure test secret allowlist still works."""
        policy = SecretDetectionPolicy({"allow_test_secrets": True})

        # Test secrets should be allowed
        result = policy.validate({"content": "password=test"}, {})
        assert result.valid

        result = policy.validate({"content": "password=example"}, {})
        assert result.valid

    def test_path_exclusion_unchanged(self):
        """Ensure path exclusion still works."""
        policy = SecretDetectionPolicy({
            "excluded_paths": [".git", "node_modules"]
        })

        # Excluded paths should be skipped
        result = policy.validate({
            "content": "AKIAIOSFODNN7EXAMPLE",
            "file_path": ".git/config"
        }, {})
        assert result.valid

        result = policy.validate({
            "content": "AKIAIOSFODNN7EXAMPLE",
            "file_path": "node_modules/package.json"
        }, {})
        assert result.valid
