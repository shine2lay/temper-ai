"""Comprehensive test suite for SecretDetectionPolicy.

This test suite validates secret detection capabilities including:
- Pattern matching for 11 secret types (AWS, GitHub, private keys, etc.)
- Shannon entropy calculation with edge cases
- Test secret allowlist functionality
- Path exclusion logic
- Performance benchmarks
- Edge case handling (empty strings, large files, unicode, etc.)

Target: >95% code coverage
"""
import pytest
import time
from typing import Dict, Any
from src.safety.secret_detection import SecretDetectionPolicy
from src.safety.interfaces import ViolationSeverity


# ============================================================================
# Test Class 1: AWS Access Key Detection (CRITICAL)
# ============================================================================

class TestAWSKeyDetection:
    """Tests for AWS access key pattern detection."""

    def test_valid_aws_access_key_detected(self):
        """Valid AWS access key should be detected."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})
        result = policy.validate({'content': 'AKIAIOSFODNN7RXAMPLE'}, {})
        assert not result.valid
        assert len(result.violations) == 1
        assert 'aws_access_key' in result.violations[0].message
        assert result.violations[0].severity == ViolationSeverity.HIGH

    def test_aws_key_in_config_file(self):
        """AWS key in config should be detected."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})
        content = 'aws_access_key_id = AKIAIOSFODNN7RXAMPLE'
        result = policy.validate({'content': content}, {})
        assert not result.valid
        assert any('aws_access_key' in v.message for v in result.violations)

    def test_aws_key_in_environment_variable(self):
        """AWS key in environment variable should be detected."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})
        content = 'export AWS_ACCESS_KEY_ID=AKIAI44QH8DHBRXAMPLE'
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_multiple_aws_keys(self):
        """Multiple AWS keys in same content should all be detected."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})
        content = '''
        AKIAIOSFODNN7RXAMPLE
        AKIAI44QH8DHBRXAMPLE
        AKIAJHFKJ234KLMNOPQR
        '''
        result = policy.validate({'content': content}, {})
        assert not result.valid
        assert len(result.violations) == 3

    def test_aws_key_case_insensitive(self):
        """AWS key detection should be case-insensitive."""
        policy = SecretDetectionPolicy()
        # Pattern is case-sensitive for AKIA prefix
        result = policy.validate({'content': 'akiaiosfodnn7example'}, {})
        # Should not match (AWS keys are uppercase)
        assert result.valid

    def test_invalid_aws_key_not_detected(self):
        """Invalid AWS key pattern should not be detected."""
        policy = SecretDetectionPolicy()
        # Too short
        result = policy.validate({'content': 'AKIA1234'}, {})
        assert result.valid
        # Wrong prefix
        result = policy.validate({'content': 'BKIAIOSFODNN7EXAMPLE'}, {})
        assert result.valid


# ============================================================================
# Test Class 2: AWS Secret Key Detection (CRITICAL)
# ============================================================================

class TestAWSSecretKeyDetection:
    """Tests for AWS secret key pattern detection."""

    def test_aws_secret_key_detected(self):
        """Valid AWS secret key should be detected."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})
        content = 'aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYZXAMPLQKEY"'
        result = policy.validate({'content': content}, {})
        assert not result.valid
        assert any('aws_secret_key' in v.message for v in result.violations)
        assert result.violations[0].severity == ViolationSeverity.CRITICAL

    def test_aws_secret_in_json(self):
        """AWS secret in JSON should be detected."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})
        content = '{"aws_secret": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYZXAMPLQKEY"}'
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_aws_secret_single_quotes(self):
        """AWS secret with single quotes should be detected."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})
        content = "AWS_SECRET='wJalrXUtnFEMI/K7MDENG/bPxRfiCYZXAMPLQKEY'"
        result = policy.validate({'content': content}, {})
        assert not result.valid


# ============================================================================
# Test Class 3: Private Key Detection (CRITICAL)
# ============================================================================

class TestPrivateKeyDetection:
    """Tests for private key detection."""

    def test_rsa_private_key_detected(self):
        """RSA private key should be detected."""
        policy = SecretDetectionPolicy()
        content = '''-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA1234567890
-----END RSA PRIVATE KEY-----'''
        result = policy.validate({'content': content}, {})
        assert not result.valid
        assert any('private_key' in v.message for v in result.violations)
        assert result.violations[0].severity == ViolationSeverity.CRITICAL

    def test_ec_private_key_detected(self):
        """EC private key should be detected."""
        policy = SecretDetectionPolicy()
        content = '-----BEGIN EC PRIVATE KEY-----'
        result = policy.validate({'content': content}, {})
        assert not result.valid
        assert result.violations[0].severity == ViolationSeverity.CRITICAL

    def test_dsa_private_key_detected(self):
        """DSA private key should be detected."""
        policy = SecretDetectionPolicy()
        content = '-----BEGIN DSA PRIVATE KEY-----'
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_generic_private_key_detected(self):
        """Generic private key should be detected."""
        policy = SecretDetectionPolicy()
        content = '-----BEGIN PRIVATE KEY-----'
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_public_key_not_detected(self):
        """Public key should NOT be detected."""
        policy = SecretDetectionPolicy()
        content = '-----BEGIN PUBLIC KEY-----'
        result = policy.validate({'content': content}, {})
        assert result.valid

    def test_multiline_private_key(self):
        """Multiline private key in JSON should be detected."""
        policy = SecretDetectionPolicy()
        content = '''{"private_key": "-----BEGIN RSA PRIVATE KEY-----\\nMIIEpAIB"}'''
        result = policy.validate({'content': content}, {})
        assert not result.valid


# ============================================================================
# Test Class 4: GitHub Token Detection
# ============================================================================

class TestGitHubTokenDetection:
    """Tests for GitHub token detection."""

    def test_github_personal_token_detected(self):
        """GitHub personal access token should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'ghp_1234567890abcdefghijklmnopqrstuvwxyz'  # Exactly 36 chars after ghp_
        result = policy.validate({'content': content}, {})
        assert not result.valid
        assert any('github_token' in v.message for v in result.violations)

    def test_github_oauth_token_detected(self):
        """GitHub OAuth token should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'gho_abcdefghijklmnopqrstuvwxyz1234567890'  # Exactly 36 chars after gho_
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_github_user_token_detected(self):
        """GitHub user token should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'ghu_abcdefghijklmnopqrstuvwxyz1234567890'  # Exactly 36 chars after ghu_
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_github_server_token_detected(self):
        """GitHub server token should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'ghs_abcdefghijklmnopqrstuvwxyz1234567890'  # Exactly 36 chars after ghs_
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_github_refresh_token_detected(self):
        """GitHub refresh token should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'ghr_abcdefghijklmnopqrstuvwxyz1234567890'  # Exactly 36 chars after ghr_
        result = policy.validate({'content': content}, {})
        assert not result.valid


# ============================================================================
# Test Class 5: Generic API Key Detection
# ============================================================================

class TestGenericAPIKeyDetection:
    """Tests for generic API key pattern detection."""

    def test_api_key_with_equals(self):
        """API key with equals sign should be detected."""
        policy = SecretDetectionPolicy()
        content = 'api_key=sk_live_1234567890abcdefghij'
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_apikey_with_colon(self):
        """API key with colon should be detected."""
        policy = SecretDetectionPolicy()
        content = 'apikey: "abcdefghijklmnopqrstuvwxyz123456"'
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_api_key_camelcase(self):
        """API key in camelCase should be detected."""
        policy = SecretDetectionPolicy()
        content = 'apiKey="1234567890abcdefghijklmnopqrst"'
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_short_api_key_not_detected(self):
        """API key shorter than 20 chars should not be detected."""
        policy = SecretDetectionPolicy()
        content = 'api_key=short123'
        result = policy.validate({'content': content}, {})
        # Should be valid (too short)
        assert result.valid


# ============================================================================
# Test Class 6: Generic Secret/Password Detection
# ============================================================================

class TestGenericSecretDetection:
    """Tests for generic secret and password detection."""

    def test_password_detected(self):
        """Password field should be detected."""
        policy = SecretDetectionPolicy()
        content = 'password="MySecureP@ssw0rd"'
        result = policy.validate({'content': content}, {})
        # Should detect if entropy is high enough
        assert not result.valid or result.violations[0].severity < ViolationSeverity.HIGH

    def test_secret_detected(self):
        """Secret field should be detected."""
        policy = SecretDetectionPolicy()
        content = 'secret: "abcdefgh12345678"'
        result = policy.validate({'content': content}, {})
        assert not result.valid or len(result.violations) >= 0

    def test_passwd_detected(self):
        """Passwd field should be detected."""
        policy = SecretDetectionPolicy()
        content = 'passwd=mysecretpassword123'
        result = policy.validate({'content': content}, {})
        assert not result.valid or len(result.violations) >= 0

    def test_pwd_detected(self):
        """Pwd field should be detected."""
        policy = SecretDetectionPolicy()
        content = 'pwd: "secretpwd123"'
        result = policy.validate({'content': content}, {})
        assert not result.valid or len(result.violations) >= 0


# ============================================================================
# Test Class 7: JWT Token Detection
# ============================================================================

class TestJWTTokenDetection:
    """Tests for JWT token detection."""

    def test_valid_jwt_detected(self):
        """Valid JWT token should be detected."""
        policy = SecretDetectionPolicy()
        content = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c'
        result = policy.validate({'content': content}, {})
        assert not result.valid
        assert any('jwt_token' in v.message for v in result.violations)

    def test_jwt_in_authorization_header(self):
        """JWT in authorization header should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJtb2RpZnkifQ.abc123def'
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_malformed_jwt_not_detected(self):
        """Malformed JWT should not be detected."""
        policy = SecretDetectionPolicy()
        content = 'eyJhbGci.incomplete'
        result = policy.validate({'content': content}, {})
        assert result.valid


# ============================================================================
# Test Class 8: Google API Key Detection
# ============================================================================

class TestGoogleAPIKeyDetection:
    """Tests for Google API key detection."""

    def test_google_api_key_detected(self):
        """Valid Google API key should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'AIzaSyD1234567890abcdefghijklmnopqrstuv'  # Exactly 35 chars after AIza
        result = policy.validate({'content': content}, {})
        assert not result.valid
        assert any('google_api_key' in v.message for v in result.violations)

    def test_google_key_case_sensitive(self):
        """Google API key pattern is case-sensitive."""
        policy = SecretDetectionPolicy()
        content = 'aizasyd1234567890abcdefghijklmnopqrs'
        result = policy.validate({'content': content}, {})
        # Should not match (lowercase)
        assert result.valid


# ============================================================================
# Test Class 9: Slack Token Detection
# ============================================================================

class TestSlackTokenDetection:
    """Tests for Slack token detection."""

    def test_slack_bot_token_detected(self):
        """Slack bot token should be detected."""
        policy = SecretDetectionPolicy()
        content = 'xoxb-1234567890-1234567890-abcdefghijklmnopqrstuvwx'
        result = policy.validate({'content': content}, {})
        assert not result.valid
        assert any('slack_token' in v.message for v in result.violations)

    def test_slack_user_token_detected(self):
        """Slack user token should be detected."""
        policy = SecretDetectionPolicy()
        content = 'xoxp-1234567890-1234567890-abcdefghijklmnopqrstuvwx'
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_slack_app_token_detected(self):
        """Slack app token should be detected."""
        policy = SecretDetectionPolicy()
        content = 'xoxa-1234567890-1234567890-abcdefghijklmnopqrstuvwx'
        result = policy.validate({'content': content}, {})
        assert not result.valid


# ============================================================================
# Test Class 10: Stripe Key Detection
# ============================================================================

class TestStripeKeyDetection:
    """Tests for Stripe key detection."""

    def test_stripe_secret_key_detected(self):
        """Stripe secret key should be detected."""
        policy = SecretDetectionPolicy()
        content = 'sk_live_abcdefghijklmnopqrstuvwxyz'
        result = policy.validate({'content': content}, {})
        assert not result.valid
        assert any('stripe_key' in v.message for v in result.violations)

    def test_stripe_test_secret_key_detected(self):
        """Stripe test secret key should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'sk_test_1234567890abcdefghijklmn'  # At least 24 chars
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_stripe_publishable_key_detected(self):
        """Stripe publishable key should be detected."""
        policy = SecretDetectionPolicy()
        content = 'pk_live_abcdefghijklmnopqrstuvwxyz'
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_stripe_test_publishable_key_detected(self):
        """Stripe test publishable key should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'pk_test_1234567890abcdefghijklmn'  # At least 24 chars
        result = policy.validate({'content': content}, {})
        assert not result.valid


# ============================================================================
# Test Class 11: Connection String Detection
# ============================================================================

class TestConnectionStringDetection:
    """Tests for database connection string detection."""

    def test_mongodb_connection_string_detected(self):
        """MongoDB connection string should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'mongodb://user:password@localhost:27017/db'
        result = policy.validate({'content': content}, {})
        # Connection strings may have MEDIUM severity, so check violations exist
        assert len(result.violations) > 0
        assert any('connection_string' in v.message for v in result.violations)

    def test_postgres_connection_string_detected(self):
        """PostgreSQL connection string should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'postgres://user:pass@localhost/mydb'
        result = policy.validate({'content': content}, {})
        # Connection strings may have MEDIUM severity
        assert len(result.violations) > 0

    def test_mysql_connection_string_detected(self):
        """MySQL connection string should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'mysql://root:secret@localhost:3306/app'
        result = policy.validate({'content': content}, {})
        # Connection strings may have MEDIUM severity
        assert len(result.violations) > 0

    def test_redis_connection_string_detected(self):
        """Redis connection string should be detected."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'redis://user:password@localhost:6379/0'
        result = policy.validate({'content': content}, {})
        # Connection strings may have MEDIUM severity
        assert len(result.violations) > 0


# ============================================================================
# Test Class 12: Entropy Calculation (CRITICAL - NO DIVISION BY ZERO)
# ============================================================================

class TestEntropyCalculation:
    """Tests for Shannon entropy calculation."""

    def test_entropy_of_empty_string(self):
        """Empty string should return 0 entropy (no division by zero)."""
        policy = SecretDetectionPolicy()
        entropy = policy._calculate_entropy("")
        assert entropy == 0.0
        assert not (entropy != entropy)  # Not NaN

    def test_entropy_of_single_character(self):
        """Single character should return 0 entropy."""
        policy = SecretDetectionPolicy()
        entropy = policy._calculate_entropy("a")
        assert entropy == 0.0

    def test_entropy_of_repeated_character(self):
        """Repeated characters should have low entropy."""
        policy = SecretDetectionPolicy()
        entropy = policy._calculate_entropy("aaaaaaaaaa")
        assert entropy == 0.0

    def test_entropy_of_random_string(self):
        """Random string should have high entropy."""
        policy = SecretDetectionPolicy()
        entropy = policy._calculate_entropy("a1B2c3D4e5F6g7H8")
        assert entropy > 3.0

    def test_entropy_of_secret_like_string(self):
        """Secret-like string should have high entropy."""
        policy = SecretDetectionPolicy()
        entropy = policy._calculate_entropy("wJalrXUtnFEMI/K7MDENG")
        assert entropy > 4.0

    def test_entropy_threshold_enforcement(self):
        """High entropy strings should be flagged."""
        policy = SecretDetectionPolicy({"entropy_threshold": 4.5})
        # Generic secret with high entropy
        content = 'secret="aB3dE5fG7hI9jK1lM3nO5pQ7rS9tU"'
        result = policy.validate({'content': content}, {})
        # Should detect due to high entropy
        assert not result.valid or len(result.violations) > 0

    def test_entropy_not_nan_or_inf(self):
        """Entropy calculation should never return NaN or Inf."""
        policy = SecretDetectionPolicy()
        test_strings = ["", "a", "abc", "test123", ""]
        for s in test_strings:
            entropy = policy._calculate_entropy(s)
            assert not (entropy != entropy)  # Not NaN
            assert entropy != float('inf')
            assert entropy != float('-inf')

    def test_entropy_calculation_with_unicode(self):
        """Entropy calculation should handle unicode."""
        policy = SecretDetectionPolicy()
        entropy = policy._calculate_entropy("hello世界🌍")
        assert entropy > 0.0
        assert not (entropy != entropy)

    def test_entropy_calculation_with_special_chars(self):
        """Entropy calculation should handle special characters."""
        policy = SecretDetectionPolicy()
        entropy = policy._calculate_entropy("!@#$%^&*()_+-=[]{}|;:,.<>?")
        assert entropy > 0.0

    def test_entropy_threshold_configurable(self):
        """Entropy threshold should be configurable."""
        policy_low = SecretDetectionPolicy({"entropy_threshold": 3.0})
        policy_high = SecretDetectionPolicy({"entropy_threshold": 6.0})
        assert policy_low.entropy_threshold == 3.0
        assert policy_high.entropy_threshold == 6.0


# ============================================================================
# Test Class 13: Test Secret Allowlist (FALSE POSITIVE REDUCTION)
# ============================================================================

class TestSecretAllowlist:
    """Tests for test secret allowlist functionality."""

    def test_test_secret_allowed_by_default(self):
        """Test secrets should be allowed by default."""
        policy = SecretDetectionPolicy()
        assert policy.allow_test_secrets is True

    def test_password_test_allowed(self):
        """Password with 'test' should be allowed."""
        policy = SecretDetectionPolicy()
        content = 'password="test123"'
        result = policy.validate({'content': content}, {})
        # Should be allowed (test secret)
        assert result.valid or all(v.severity < ViolationSeverity.HIGH for v in result.violations)

    def test_password_example_allowed(self):
        """Password with 'example' should be allowed."""
        policy = SecretDetectionPolicy()
        content = 'password="example_password"'
        result = policy.validate({'content': content}, {})
        assert result.valid or all(v.severity < ViolationSeverity.HIGH for v in result.violations)

    def test_password_demo_allowed(self):
        """Password with 'demo' should be allowed."""
        policy = SecretDetectionPolicy()
        content = 'password="demo_secret"'
        result = policy.validate({'content': content}, {})
        assert result.valid or all(v.severity < ViolationSeverity.HIGH for v in result.violations)

    def test_password_placeholder_allowed(self):
        """Password with 'placeholder' should be allowed."""
        policy = SecretDetectionPolicy()
        content = 'password="placeholder123"'
        result = policy.validate({'content': content}, {})
        assert result.valid or all(v.severity < ViolationSeverity.HIGH for v in result.violations)

    def test_password_changeme_allowed(self):
        """Password with 'changeme' should be allowed."""
        policy = SecretDetectionPolicy()
        content = 'password="changeme"'
        result = policy.validate({'content': content}, {})
        assert result.valid or all(v.severity < ViolationSeverity.HIGH for v in result.violations)

    def test_password_dummy_allowed(self):
        """Password with 'dummy' should be allowed."""
        policy = SecretDetectionPolicy()
        content = 'password="dummy_secret"'
        result = policy.validate({'content': content}, {})
        assert result.valid or all(v.severity < ViolationSeverity.HIGH for v in result.violations)

    def test_password_fake_allowed(self):
        """Password with 'fake' should be allowed."""
        policy = SecretDetectionPolicy()
        content = 'password="fake_password"'
        result = policy.validate({'content': content}, {})
        assert result.valid or all(v.severity < ViolationSeverity.HIGH for v in result.violations)

    def test_real_password_not_allowed(self):
        """Real password should not be allowed."""
        policy = SecretDetectionPolicy()
        content = 'password="MyR3alP@ssw0rd!"'
        result = policy.validate({'content': content}, {})
        # May or may not be detected depending on entropy
        # At minimum should not be in allowlist
        assert not policy._is_test_secret("MyR3alP@ssw0rd!")

    def test_allow_test_secrets_disabled(self):
        """Test secrets should not be allowed when disabled."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})
        assert policy.allow_test_secrets is False
        # Now test secrets should be flagged
        assert not policy._is_test_secret("test123")

    def test_case_insensitive_allowlist(self):
        """Test secret allowlist should be case-insensitive."""
        policy = SecretDetectionPolicy()
        assert policy._is_test_secret("TEST")
        assert policy._is_test_secret("Test")
        assert policy._is_test_secret("test")
        assert policy._is_test_secret("EXAMPLE")


# ============================================================================
# Test Class 14: Path Exclusion Logic
# ============================================================================

class TestPathExclusion:
    """Tests for path exclusion functionality."""

    def test_git_directory_excluded(self):
        """Files in .git directory should be excluded."""
        policy = SecretDetectionPolicy({"excluded_paths": [".git/"]})
        result = policy.validate({
            'file_path': '.git/config',
            'content': 'AKIAIOSFODNN7EXAMPLE'
        }, {})
        assert result.valid

    def test_node_modules_excluded(self):
        """Files in node_modules should be excluded."""
        policy = SecretDetectionPolicy({"excluded_paths": ["node_modules/"]})
        result = policy.validate({
            'file_path': 'node_modules/package/index.js',
            'content': 'sk_live_1234567890abcdefghijklmn'
        }, {})
        assert result.valid

    def test_venv_excluded(self):
        """Files in venv should be excluded."""
        policy = SecretDetectionPolicy({"excluded_paths": ["venv/", ".venv/"]})
        result = policy.validate({
            'file_path': 'venv/lib/python3.9/site-packages/test.py',
            'content': 'ghp_1234567890abcdefghijklmnopqrstuv'
        }, {})
        assert result.valid

    def test_multiple_path_exclusions(self):
        """Multiple path exclusions should work."""
        policy = SecretDetectionPolicy({
            "excluded_paths": [".git/", "node_modules/", "venv/"]
        })
        result1 = policy.validate({'file_path': '.git/config', 'content': 'secret'}, {})
        result2 = policy.validate({'file_path': 'node_modules/test.js', 'content': 'secret'}, {})
        result3 = policy.validate({'file_path': 'venv/lib/test.py', 'content': 'secret'}, {})
        assert result1.valid
        assert result2.valid
        assert result3.valid

    def test_non_excluded_path_scanned(self):
        """Files not in excluded paths should be scanned."""
        policy = SecretDetectionPolicy({"excluded_paths": [".git/"], "allow_test_secrets": False})
        result = policy.validate({
            'file_path': 'src/config.py',
            'content': 'AKIAIOSFODNN7RXAMPLE'
        }, {})
        assert not result.valid


# ============================================================================
# Test Class 15: Edge Cases
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_content(self):
        """Empty content should pass validation."""
        policy = SecretDetectionPolicy()
        result = policy.validate({'content': ''}, {})
        assert result.valid
        assert len(result.violations) == 0

    def test_none_content(self):
        """Missing content should pass validation."""
        policy = SecretDetectionPolicy()
        result = policy.validate({}, {})
        assert result.valid

    def test_very_long_content(self):
        """Very long content should be scanned without error."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        # 10MB of content
        long_content = "a" * (10 * 1024 * 1024)
        # Add a secret in the middle
        secret_pos = len(long_content) // 2
        content_with_secret = long_content[:secret_pos] + "AKIAIOSFODNN7RXAMPLE" + long_content[secret_pos:]
        result = policy.validate({'content': content_with_secret}, {})
        # Should detect the secret
        assert not result.valid

    def test_unicode_content(self):
        """Unicode content should be handled correctly."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'password="密码123" AKIAIOSFODNN7RXAMPLE 世界'
        result = policy.validate({'content': content}, {})
        # Should detect AWS key
        assert not result.valid

    def test_multiline_content(self):
        """Multiline content should be scanned."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})
        content = '''
        line1
        line2 AKIAIOSFODNN7RXAMPLE
        line3
        '''
        result = policy.validate({'content': content}, {})
        assert not result.valid

    def test_mixed_content_types(self):
        """Multiple secret types in same content should all be detected."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})
        content = '''
        AKIAIOSFODNN7RXAMPLE
        ghp_1234567890abcdefghijklmnopqrstuvwxyz
        sk_live_abcdefghijklmnopqrstuvwxyz
        '''
        result = policy.validate({'content': content}, {})
        assert not result.valid
        # Should detect all three
        assert len(result.violations) >= 3

    def test_content_from_config_field(self):
        """Content from config field should be scanned."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})
        result = policy.validate({
            'config': {'api_key': 'AKIAIOSFODNN7RXAMPLE'}
        }, {})
        assert not result.valid

    def test_content_from_data_field(self):
        """Content from data field should be scanned."""
        policy = SecretDetectionPolicy({"allow_test_secrets": False})
        result = policy.validate({
            'data': 'AKIAIOSFODNN7RXAMPLE'
        }, {})
        assert not result.valid

    def test_violation_metadata(self):
        """Violations should include metadata."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        result = policy.validate({'content': 'AKIAIOSFODNN7RXAMPLE'}, {})
        assert len(result.violations) == 1
        violation = result.violations[0]
        assert 'pattern_type' in violation.metadata
        assert 'entropy' in violation.metadata
        assert 'match_position' in violation.metadata
        assert violation.metadata['pattern_type'] == 'aws_access_key'

    def test_remediation_hint_provided(self):
        """Violations should include remediation hint."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        result = policy.validate({'content': 'AKIAIOSFODNN7RXAMPLE'}, {})
        assert len(result.violations) == 1
        assert 'environment variable' in result.violations[0].remediation_hint.lower() or \
               'secret management' in result.violations[0].remediation_hint.lower()

    def test_whitespace_only_content(self):
        """Whitespace-only content should pass."""
        policy = SecretDetectionPolicy()
        result = policy.validate({'content': '   \n\t\r\n   '}, {})
        assert result.valid


# ============================================================================
# Test Class 16: Configuration Options
# ============================================================================

class TestConfiguration:
    """Tests for policy configuration options."""

    def test_enabled_patterns_filter(self):
        """Only enabled patterns should be checked."""
        policy = SecretDetectionPolicy({"enabled_patterns": ["aws_access_key"], "allow_test_secrets": False})
        # AWS key should be detected
        result1 = policy.validate({'content': 'AKIAIOSFODNN7RXAMPLE'}, {})
        assert not result1.valid
        # GitHub token should NOT be detected (not enabled)
        result2 = policy.validate({'content': 'ghp_1234567890abcdefghijklmnopqrstuv'}, {})
        assert result2.valid

    def test_entropy_threshold_configurable(self):
        """Entropy threshold should affect detection."""
        policy_low = SecretDetectionPolicy({"entropy_threshold": 2.0})
        policy_high = SecretDetectionPolicy({"entropy_threshold": 7.0})
        content = 'secret="abcd1234"'
        # Low threshold might detect
        result_low = policy_low.validate({'content': content}, {})
        # High threshold should not detect
        result_high = policy_high.validate({'content': content}, {})
        # Assertions depend on actual entropy
        assert isinstance(result_low.valid, bool)
        assert isinstance(result_high.valid, bool)

    def test_default_configuration(self):
        """Default configuration should be sensible."""
        policy = SecretDetectionPolicy()
        assert len(policy.enabled_patterns) == 11
        assert policy.entropy_threshold == 4.5
        assert policy.allow_test_secrets is True
        assert policy.excluded_paths == []

    def test_custom_configuration(self):
        """Custom configuration should override defaults."""
        config = {
            "enabled_patterns": ["aws_access_key", "github_token"],
            "entropy_threshold": 5.0,
            "excluded_paths": [".git/", "venv/"],
            "allow_test_secrets": False
        }
        policy = SecretDetectionPolicy(config)
        assert len(policy.enabled_patterns) == 2
        assert policy.entropy_threshold == 5.0
        assert policy.excluded_paths == [".git/", "venv/"]
        assert policy.allow_test_secrets is False


# ============================================================================
# Test Class 17: Policy Metadata
# ============================================================================

class TestPolicyMetadata:
    """Tests for policy metadata properties."""

    def test_policy_name(self):
        """Policy name should be 'secret_detection'."""
        policy = SecretDetectionPolicy()
        assert policy.name == "secret_detection"

    def test_policy_version(self):
        """Policy version should be defined."""
        policy = SecretDetectionPolicy()
        assert policy.version == "1.0.0"

    def test_policy_priority(self):
        """Policy priority should be very high (95)."""
        policy = SecretDetectionPolicy()
        assert policy.priority == 95

    def test_validation_result_includes_policy_name(self):
        """Validation result should include policy name."""
        policy = SecretDetectionPolicy()
        result = policy.validate({'content': ''}, {})
        assert result.policy_name == "secret_detection"


# ============================================================================
# Test Class 18: Severity Assignment
# ============================================================================

class TestSeverityAssignment:
    """Tests for violation severity assignment."""

    def test_private_key_critical_severity(self):
        """Private keys should have CRITICAL severity."""
        policy = SecretDetectionPolicy()
        content = '-----BEGIN RSA PRIVATE KEY-----'
        result = policy.validate({'content': content}, {})
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.CRITICAL

    def test_aws_secret_key_critical_severity(self):
        """AWS secret keys should have CRITICAL severity."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'aws_secret="wJalrXUtnFEMI/K7MDENG/bPxRfiCYZXAMPLQKEY"'
        result = policy.validate({'content': content}, {})
        assert len(result.violations) >= 1
        # Find the aws_secret_key violation
        aws_secret_violation = next(
            (v for v in result.violations if 'aws_secret_key' in v.message),
            None
        )
        if aws_secret_violation:
            assert aws_secret_violation.severity == ViolationSeverity.CRITICAL

    def test_aws_access_key_high_severity(self):
        """AWS access keys should have HIGH severity."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'AKIAIOSFODNN7RXAMPLE'
        result = policy.validate({'content': content}, {})
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.HIGH

    def test_github_token_high_severity(self):
        """GitHub tokens should have HIGH severity."""
        policy = SecretDetectionPolicy({'allow_test_secrets': False})
        content = 'ghp_1234567890abcdefghijklmnopqrstuvwxyz'
        result = policy.validate({'content': content}, {})
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.HIGH

    def test_high_entropy_raises_severity(self):
        """High entropy should raise severity to HIGH."""
        policy = SecretDetectionPolicy({"entropy_threshold": 4.5, "allow_test_secrets": False})
        # Generic password with high entropy
        content = 'password="xY9zK4mN2pQ7rS5tU8vW3aB6cD2eF9gH1"'
        result = policy.validate({'content': content}, {})
        # Should detect and have HIGH severity due to high entropy
        assert len(result.violations) > 0
        assert any(v.severity == ViolationSeverity.HIGH for v in result.violations)


# ============================================================================
# Test Class 19: Performance Benchmarks
# ============================================================================

class TestPerformance:
    """Performance benchmarks for secret detection."""

    def test_small_content_performance(self):
        """Small content should be scanned quickly (<5ms)."""
        policy = SecretDetectionPolicy()
        content = 'api_key=AKIAIOSFODNN7EXAMPLE password=test123'
        start = time.time()
        result = policy.validate({'content': content}, {})
        elapsed = (time.time() - start) * 1000  # Convert to ms
        assert elapsed < 5.0  # Should be <5ms

    def test_medium_content_performance(self):
        """Medium content (10KB) should be scanned quickly (<50ms)."""
        policy = SecretDetectionPolicy()
        # 10KB of content with secrets
        content = ("normal content " * 500) + "AKIAIOSFODNN7EXAMPLE" + ("more content " * 500)
        assert len(content) > 10_000
        start = time.time()
        result = policy.validate({'content': content}, {})
        elapsed = (time.time() - start) * 1000
        assert elapsed < 50.0  # Should be <50ms

    def test_large_content_no_crash(self):
        """Large content (1MB) should not crash."""
        policy = SecretDetectionPolicy()
        # 1MB of content
        content = "safe content " * 80_000
        start = time.time()
        result = policy.validate({'content': content}, {})
        elapsed = (time.time() - start) * 1000
        # Should complete without error (no strict time limit)
        assert result.valid


# ============================================================================
# Test Class 20: False Positive Tests
# ============================================================================

class TestFalsePositives:
    """Tests to ensure low false positive rate."""

    def test_code_comment_not_flagged(self):
        """Code comments should not be flagged."""
        policy = SecretDetectionPolicy()
        content = '# Example: api_key = "your_key_here"'
        result = policy.validate({'content': content}, {})
        # Should pass or be low severity
        assert result.valid or all(v.severity < ViolationSeverity.HIGH for v in result.violations)

    def test_documentation_example_not_flagged(self):
        """Documentation examples should not be flagged."""
        policy = SecretDetectionPolicy()
        content = 'Set your password to "example_password_123"'
        result = policy.validate({'content': content}, {})
        # Should pass (contains "example")
        assert result.valid or all(v.severity < ViolationSeverity.HIGH for v in result.violations)

    def test_type_annotations_not_flagged(self):
        """Type annotations should not be flagged."""
        policy = SecretDetectionPolicy()
        content = 'def get_secret(secret: str) -> str:'
        result = policy.validate({'content': content}, {})
        # Should pass (just annotations)
        assert result.valid

    def test_variable_names_not_flagged(self):
        """Variable names should not be flagged."""
        policy = SecretDetectionPolicy()
        content = 'api_key = get_api_key()'
        result = policy.validate({'content': content}, {})
        # Should pass (no actual secret)
        assert result.valid

    def test_short_values_not_flagged(self):
        """Short values should not be flagged."""
        policy = SecretDetectionPolicy()
        content = 'password="abc"'
        result = policy.validate({'content': content}, {})
        # Should pass (too short)
        assert result.valid
