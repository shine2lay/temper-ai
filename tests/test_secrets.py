"""
Tests for secrets management system.

Tests cover:
- Environment variable secret resolution
- Secret reference parsing
- Backward compatibility
- Security validations
- Secret redaction in logs
"""
import os
import pytest
import warnings
from unittest.mock import patch, MagicMock

from src.utils.secrets import (
    SecretReference,
    SecureCredential,
    resolve_secret,
    detect_secret_patterns
)
from src.compiler.schemas import InferenceConfig
from src.compiler.config_loader import ConfigLoader
from src.utils.config_helpers import sanitize_config_for_display


class TestSecretReference:
    """Tests for SecretReference class."""

    def test_is_reference_env(self):
        """Test detecting environment variable references."""
        assert SecretReference.is_reference("${env:API_KEY}") is True
        assert SecretReference.is_reference("${env:OPENAI_API_KEY}") is True
        assert SecretReference.is_reference("plain-text") is False
        assert SecretReference.is_reference("${invalid}") is False

    def test_is_reference_vault(self):
        """Test detecting Vault references."""
        assert SecretReference.is_reference("${vault:secret/data/api-key}") is True
        assert SecretReference.is_reference("${vault:kv/my-secret}") is True

    def test_is_reference_aws(self):
        """Test detecting AWS Secrets Manager references."""
        assert SecretReference.is_reference("${aws:my-secret-id}") is True
        assert SecretReference.is_reference("${aws:prod/api-keys}") is True

    def test_resolve_env_success(self):
        """Test successful environment variable resolution."""
        os.environ['TEST_API_KEY'] = 'sk-test123'
        try:
            result = SecretReference.resolve('${env:TEST_API_KEY}')
            assert result == 'sk-test123'
        finally:
            del os.environ['TEST_API_KEY']

    def test_resolve_env_missing(self):
        """Test error when environment variable not set."""
        with pytest.raises(ValueError, match="not set"):
            SecretReference.resolve('${env:NONEXISTENT_KEY}')

    def test_resolve_env_empty_value(self):
        """Test error when environment variable is empty."""
        os.environ['EMPTY_KEY'] = ''
        try:
            with pytest.raises(ValueError, match="is empty"):
                SecretReference.resolve('${env:EMPTY_KEY}')
        finally:
            del os.environ['EMPTY_KEY']

    def test_resolve_env_null_bytes(self):
        """Test security validation for null bytes (Python prevents this at OS level)."""
        # Python doesn't allow null bytes in environment variables at the OS level,
        # so we can't actually test this. The validation exists for defense in depth.
        # Just verify the validation function exists
        from src.utils.secrets import SecretReference
        try:
            SecretReference._validate_secret_value("test", "value\x00bad")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "null bytes" in str(e)

    def test_resolve_env_too_long(self):
        """Test security validation rejects overly long values."""
        os.environ['HUGE_KEY'] = 'x' * (11 * 1024)  # 11KB
        try:
            with pytest.raises(ValueError, match="too long"):
                SecretReference.resolve('${env:HUGE_KEY}')
        finally:
            del os.environ['HUGE_KEY']

    def test_resolve_vault_not_implemented(self):
        """Test Vault provider raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="Vault"):
            SecretReference.resolve('${vault:secret/api-key}')

    def test_resolve_aws_not_implemented(self):
        """Test AWS Secrets Manager raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="AWS"):
            SecretReference.resolve('${aws:my-secret}')

    def test_resolve_plain_text(self):
        """Test backward compatibility with plain text values."""
        result = SecretReference.resolve('plain-api-key')
        assert result == 'plain-api-key'


class TestSecureCredential:
    """Tests for SecureCredential class."""

    def test_create_and_retrieve(self):
        """Test creating and retrieving encrypted credential."""
        cred = SecureCredential("sk-secret-123")
        assert cred.get() == "sk-secret-123"

    def test_redacted_string_representation(self):
        """Test that credentials are redacted in string form."""
        cred = SecureCredential("sk-secret-123")
        assert str(cred) == "***REDACTED***"
        assert repr(cred) == "SecureCredential(***REDACTED***)"

    def test_empty_value_rejected(self):
        """Test that empty values are rejected."""
        with pytest.raises(ValueError, match="empty"):
            SecureCredential("")

    def test_truthy(self):
        """Test that credential is truthy."""
        cred = SecureCredential("sk-secret-123")
        assert bool(cred) is True


class TestResolveSecret:
    """Tests for resolve_secret helper function."""

    def test_resolve_string_reference(self):
        """Test resolving string with secret reference."""
        os.environ['MY_KEY'] = 'sk-abc123'
        try:
            result = resolve_secret("${env:MY_KEY}")
            assert result == 'sk-abc123'
        finally:
            del os.environ['MY_KEY']

    def test_resolve_plain_string(self):
        """Test resolving plain string (no change)."""
        result = resolve_secret("plain-value")
        assert result == "plain-value"

    def test_resolve_dict(self):
        """Test resolving secrets in dict."""
        os.environ['API_KEY'] = 'sk-secret'
        try:
            config = {
                "api_key_ref": "${env:API_KEY}",
                "model": "gpt-4"
            }
            result = resolve_secret(config)
            assert result["api_key_ref"] == "sk-secret"
            assert result["model"] == "gpt-4"
        finally:
            del os.environ['API_KEY']

    def test_resolve_list(self):
        """Test resolving secrets in list."""
        os.environ['KEY1'] = 'secret1'
        try:
            secrets = ["${env:KEY1}", "plain"]
            result = resolve_secret(secrets)
            assert result == ["secret1", "plain"]
        finally:
            del os.environ['KEY1']

    def test_resolve_nested(self):
        """Test resolving secrets in nested structures."""
        os.environ['NESTED_KEY'] = 'nested-secret'
        try:
            config = {
                "outer": {
                    "inner": {
                        "secret": "${env:NESTED_KEY}"
                    }
                }
            }
            result = resolve_secret(config)
            assert result["outer"]["inner"]["secret"] == "nested-secret"
        finally:
            del os.environ['NESTED_KEY']


class TestDetectSecretPatterns:
    """Tests for secret pattern detection."""

    def test_detect_openai_key(self):
        """Test detecting OpenAI API key pattern."""
        is_secret, confidence = detect_secret_patterns("sk-proj-abc123def456ghi789jkl012mno345")
        assert is_secret is True
        assert confidence == "high"

    def test_detect_anthropic_key(self):
        """Test detecting Anthropic API key pattern."""
        is_secret, confidence = detect_secret_patterns("sk-ant-api03-abc123def456ghi789jkl012mno345")
        assert is_secret is True
        assert confidence == "high"

    def test_detect_aws_key(self):
        """Test detecting AWS access key pattern."""
        is_secret, confidence = detect_secret_patterns("AKIAIOSFODNN7EXAMPLE")
        assert is_secret is True
        assert confidence == "high"

    def test_detect_github_token(self):
        """Test detecting GitHub personal access token."""
        is_secret, confidence = detect_secret_patterns("ghp_1234567890abcdefghijklmnopqrstuv")
        assert is_secret is True
        assert confidence == "high"

    def test_no_secret_in_normal_text(self):
        """Test that normal text is not flagged."""
        is_secret, confidence = detect_secret_patterns("This is normal text")
        assert is_secret is False
        assert confidence is None

    def test_medium_confidence_hash(self):
        """Test medium confidence detection for hash-like strings."""
        is_secret, confidence = detect_secret_patterns("a" * 40)  # SHA1-like
        assert is_secret is True
        assert confidence == "medium"


class TestInferenceConfigBackwardCompatibility:
    """Tests for backward compatibility with old api_key field."""

    def test_old_api_key_migrates_with_warning(self):
        """Test that old api_key field migrates to api_key_ref with warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            config = InferenceConfig(
                provider="openai",
                model="gpt-4",
                api_key="sk-old-key"
            )

            # Check that at least one deprecation warning was issued
            # (may have multiple from Pydantic itself)
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1

            # Check our custom warning is present
            our_warnings = [x for x in deprecation_warnings if "api_key_ref" in str(x.message)]
            assert len(our_warnings) >= 1

            # Check migration happened
            assert config.api_key_ref == "sk-old-key"
            assert config.api_key is None

    def test_new_api_key_ref_no_warning(self):
        """Test that new api_key_ref field works without our custom warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            config = InferenceConfig(
                provider="openai",
                model="gpt-4",
                api_key_ref="${env:OPENAI_API_KEY}"
            )

            # Our custom migration warning should not be issued
            # (Pydantic may issue its own deprecation warnings, but we don't check those)
            our_warnings = [x for x in w if "api_key_ref" in str(x.message) and "deprecated" in str(x.message).lower()]
            assert len(our_warnings) == 0
            assert config.api_key_ref == "${env:OPENAI_API_KEY}"

    def test_both_fields_prefers_api_key_ref(self):
        """Test that api_key_ref takes precedence if both set."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            config = InferenceConfig(
                provider="openai",
                model="gpt-4",
                api_key="sk-old",
                api_key_ref="${env:NEW_KEY}"
            )

            # api_key_ref should take precedence
            # Our custom migration warning should not be issued (since api_key_ref is already set)
            our_warnings = [x for x in w if "api_key_ref" in str(x.message) and "deprecated" in str(x.message).lower()]
            assert len(our_warnings) == 0
            assert config.api_key_ref == "${env:NEW_KEY}"


class TestConfigLoaderSecretResolution:
    """Tests for ConfigLoader secret resolution."""

    def test_agent_config_resolves_secrets(self, tmp_path):
        """Test that agent config resolves secret references."""
        # Create test config
        config_root = tmp_path / "configs"
        config_root.mkdir()
        agents_dir = config_root / "agents"
        agents_dir.mkdir()

        os.environ['TEST_OPENAI_KEY'] = 'sk-test-resolved'
        try:
            # Write config with secret reference
            config_file = agents_dir / "test_agent.yaml"
            config_file.write_text("""
agent:
  name: test_agent
  description: Test agent
  version: "1.0"
  type: standard
  prompt:
    inline: "Test prompt"
  inference:
    provider: openai
    model: gpt-4
    api_key_ref: ${env:TEST_OPENAI_KEY}
    temperature: 0.7
    max_tokens: 2048
  tools: []
  error_handling:
    retry_strategy: ExponentialBackoff
    max_retries: 3
    fallback: GracefulDegradation
    escalate_to_human_after: 3
""")

            # Load config
            loader = ConfigLoader(config_root=config_root)
            config = loader.load_agent("test_agent", validate=True)

            # Check secret was resolved
            assert config["agent"]["inference"]["api_key_ref"] == "sk-test-resolved"

        finally:
            del os.environ['TEST_OPENAI_KEY']

    def test_missing_secret_raises_error(self, tmp_path):
        """Test that missing secret raises clear error."""
        config_root = tmp_path / "configs"
        config_root.mkdir()
        agents_dir = config_root / "agents"
        agents_dir.mkdir()

        config_file = agents_dir / "bad_agent.yaml"
        config_file.write_text("""
agent:
  name: bad_agent
  description: Bad agent
  version: "1.0"
  type: standard
  prompt:
    inline: "Test prompt"
  inference:
    provider: openai
    model: gpt-4
    api_key_ref: ${env:MISSING_KEY}
    temperature: 0.7
    max_tokens: 2048
  tools: []
  error_handling:
    retry_strategy: ExponentialBackoff
    max_retries: 3
    fallback: GracefulDegradation
    escalate_to_human_after: 3
""")

        loader = ConfigLoader(config_root=config_root)

        with pytest.raises(Exception, match="MISSING_KEY"):
            loader.load_agent("bad_agent", validate=False)


class TestSanitizeConfigForDisplay:
    """Tests for config sanitization."""

    def test_sanitize_api_key(self):
        """Test that API keys are redacted."""
        config = {"api_key": "sk-secret123", "model": "gpt-4"}
        result = sanitize_config_for_display(config)
        assert result["api_key"] == "***REDACTED***"
        assert result["model"] == "gpt-4"

    def test_sanitize_secret_reference_env(self):
        """Test that secret references are partially redacted."""
        config = {"api_key_ref": "${env:OPENAI_API_KEY}"}
        result = sanitize_config_for_display(config)
        assert result["api_key_ref"] == "${env:***REDACTED***}"

    def test_sanitize_secret_reference_vault(self):
        """Test that Vault references are partially redacted."""
        config = {"api_key_ref": "${vault:secret/api-key}"}
        result = sanitize_config_for_display(config)
        assert result["api_key_ref"] == "${vault:***REDACTED***}"

    def test_sanitize_nested_secrets(self):
        """Test that nested secrets are redacted."""
        config = {
            "inference": {
                "api_key_ref": "${env:SECRET}",
                "model": "gpt-4"
            },
            "name": "test"
        }
        result = sanitize_config_for_display(config)
        assert result["inference"]["api_key_ref"] == "${env:***REDACTED***}"
        assert result["inference"]["model"] == "gpt-4"
        assert result["name"] == "test"

    def test_sanitize_password_fields(self):
        """Test that password fields are redacted."""
        config = {
            "password": "secret123",
            "db_password": "dbpass",
            "user": "admin"
        }
        result = sanitize_config_for_display(config)
        assert result["password"] == "***REDACTED***"
        assert result["db_password"] == "***REDACTED***"
        assert result["user"] == "admin"

    def test_sanitize_secret_patterns_in_values(self):
        """Test that values containing secret patterns are redacted."""
        config = {
            "token": "sk-proj-abc123def456ghi789jkl012mno345",
            "setting": "normal-value"
        }
        result = sanitize_config_for_display(config)
        assert result["token"] == "***REDACTED***"
        assert result["setting"] == "normal-value"


class TestSecretNeverInLogs:
    """Integration tests to ensure secrets never appear in logs/DB."""

    def test_secret_not_in_string_representation(self):
        """Test that SecureCredential never exposes secret in string form."""
        cred = SecureCredential("sk-very-secret-key")

        # str() should not expose secret
        assert "sk-very-secret-key" not in str(cred)
        assert "REDACTED" in str(cred)

        # repr() should not expose secret
        assert "sk-very-secret-key" not in repr(cred)
        assert "REDACTED" in repr(cred)

    def test_sanitized_config_safe_for_logging(self):
        """Test that sanitized config is safe to log."""
        config = {
            "inference": {
                "provider": "openai",
                "model": "gpt-4",
                "api_key": "sk-real-secret-key-123",
                "api_key_ref": "${env:OPENAI_API_KEY}"
            }
        }

        sanitized = sanitize_config_for_display(config)

        # Convert to string (simulating logging)
        log_output = str(sanitized)

        # Actual secret should not appear
        assert "sk-real-secret-key-123" not in log_output
        assert "REDACTED" in log_output
